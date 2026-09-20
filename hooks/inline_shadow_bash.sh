#!/bin/bash
# jev TRUE inline shadow -- pre_bash only. Decision #8 in docs/PLAN.md.
#
# capture.sh is the primary instrument for the arm comparison, but a
# capture-and-replay harness never exercises the script you would actually
# deploy. This one does: it calls Jev SYNCHRONOUSLY, with a hard --max-time,
# logs the decision it WOULD have made, and always exits 0 having emitted
# nothing. It is the enforce hook with the enforcement removed, so the timeout,
# the fail-open path and the real p99 are measured under live conditions rather
# than projected.
#
# It is deliberately more expensive than capture.sh -- four jq spawns, an
# openssl spawn and a network round trip on the critical path. That cost is not
# an accident to be optimised away: it IS the projected enforce overhead, and
# bench_inline.py reports it.
#
# Usage: inline_shadow_bash.sh            (pre_bash hook payload on stdin)

# The trap comes FIRST, before anything that can fail -- same discipline as
# capture.sh. A failed redirect on a fresh checkout (logs/ is gitignored) would
# otherwise exit non-zero before any later trap could catch it.
trap 'exit 0' EXIT
# No `set -e`: a failure must skip the record, not abort with a nonzero status.

# Structural guarantee that nothing reaches Claude Code. stdout on a PreToolUse
# hook is parsed as a permission decision, so a single stray byte from curl, jq
# or openssl would be us gating a tool call we promised never to gate. Closing
# it here means no later line CAN leak, rather than every later line having to
# remember to redirect. Command substitution captures child stdout through its
# own pipe, so the script still reads every subprocess it needs.
exec >/dev/null

# Decimal separators: curl's -w timings are written in the current locale, and
# under a comma-decimal locale "0,557" is not a JSON number. Pin it.
export LC_ALL=C

ROOT="${CLAUDE_PROJECT_DIR:-}"
if [ -n "$ROOT" ] && [ -d "$ROOT/logs" ]; then
  exec 2>>"$ROOT/logs/inline_shadow.err"
else
  exec 2>/dev/null
fi

# Recursion guard, identical in spirit to capture.sh: an arm subprocess running
# `claude -p` starts a real session that would load this hook and call Jev about
# its own decisions -- billed, logged, and not a live decision point.
[ -n "$JEV_ARM_SUBPROCESS" ] && exit 0

[ -n "$ROOT" ] || exit 0
[ -d "$ROOT" ] || exit 0

# --- jev kill switch: canonical block, byte-identical in every hook ----------
# One switch, all surfaces. `tests/reversibility.sh` enumerates the registered
# hooks and fails if any of them lacks this block, so a new surface cannot be
# added without it.
#
# Anchored on $ROOT, never cwd-relative: a hook fires with whatever cwd the
# session happens to have, and a relative test silently stops working the moment
# you cd into a subdirectory.
#
# FAIL SAFE (JEV-40): ANY entry at this path means OFF. `-f` alone reads a
# directory as absent, so an operator who ran `mkdir .jev-disabled` would
# believe the switch was set while the hook kept firing; `-e` alone reads a
# dangling symlink as absent. An unreadable file still stats, so it too reads as
# present. When the state of the switch cannot be established, the answer is
# OFF, not ON -- the switch is never given the benefit of the doubt.
{ [ -e "$ROOT/.jev-disabled" ] || [ -L "$ROOT/.jev-disabled" ]; } && exit 0
# --- end jev kill switch ----------------------------------------------------

# Defensive cwd guard, as capture.sh.
case "$PWD/" in
  "$ROOT"/*) ;;
  *) exit 0 ;;
esac

SURFACE="pre_bash"
ENDPOINT="${JEV_INLINE_ENDPOINT:-https://ai-gateway.vercel.sh/v1/evaluate}"
MODEL="${JEV_INLINE_MODEL:-typesafe-ai/jev}"
MAX_TIME="${JEV_INLINE_MAX_TIME:-2.0}"
RUN_CONTEXT="${JEV_INLINE_RUN_CONTEXT:-live}"
SURFACES_CONFIG="$ROOT/config/surfaces.json"
# QFILE is resolved from SURFACES_CONFIG below, once jq is known to be present.
# It is deliberately NOT hardcoded to v1: the question set version is the replay
# key, and a hardcoded version is how a surface gets scored against a question
# set nobody chose.
QFILE=""

# Thresholds default to 0.5 even though FINDINGS 4b shows 0.5 is the wrong
# operating point for Jev on both questions (Youden-optimal 0.36 and 0.95).
# Those two constants were fitted on the synthetic set they were derived from,
# which is the textbook way to overfit an operating point -- baking them into
# the deployed script would launder a provisional number into an artefact.
# Instead tau travels on every row, so any threshold can be re-applied offline
# to already-logged probabilities without re-running anything.
TAU_DESTRUCTIVE="${JEV_INLINE_TAU_DESTRUCTIVE:-0.5}"
TAU_NEEDS_REVIEW="${JEV_INLINE_TAU_NEEDS_REVIEW:-0.5}"

LOGDIR="${JEV_INLINE_LOG_DIR:-$ROOT/data/inline}"
mkdir -p "$LOGDIR" 2>/dev/null || exit 0
LOG="$LOGDIR/$(date -u +%Y-%m-%d).jsonl"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Every exit path from here on writes a row. A dropped failure is invisible
# attrition, which is exactly how a latency distribution gets quietly flattered.
# This fallback uses printf alone so it still works when jq is the thing that is
# missing or broken.
emit_minimal() {
  printf '{"timestamp":"%s","surface":"%s","run_context":"%s","ok":false,"error_kind":"%s"}\n' \
    "$TS" "$SURFACE" "$RUN_CONTEXT" "$1" >> "$LOG" 2>/dev/null
}

# jq is required here -- unlike capture.sh, this script genuinely has to parse
# the payload to build a request. Its absence is a logged error, not a silent
# skip, so the attrition table can show it.
command -v jq >/dev/null 2>&1 || { emit_minimal "no_jq"; exit 0; }

# Resolve the pinned question set version from config rather than assuming one.
# No fallback: an unresolvable version is a logged failure, never a silent v1.
QVERSION=$(jq -r --arg s "$SURFACE" '.surfaces[$s].question_set // empty' \
  "$SURFACES_CONFIG" 2>/dev/null)
[ -n "$QVERSION" ] || { emit_minimal "no_question_set_version"; exit 0; }
QFILE="$ROOT/questions/$SURFACE/$QVERSION.json"
[ -f "$QFILE" ] || { emit_minimal "no_question_set"; exit 0; }

T0=$(jq -n 'now')

TMPREQ="$LOGDIR/.req.$$.$RANDOM"
TMPBODY="$LOGDIR/.body.$$.$RANDOM"
trap 'rm -f "$TMPREQ" "$TMPBODY"; exit 0' EXIT

PAYLOAD=$(cat)
[ -n "$PAYLOAD" ] || { emit_minimal "empty_payload"; exit 0; }

# One jq call does three jobs: pulls the join keys, builds the state string, and
# emits them together -- ids on the first line, state on the rest -- so bash can
# split them with parameter expansion and no further process.
#
# The state expression MUST stay byte-identical to state_builders.build_pre_bash.
# If it drifts, an inline row and a shadow row for the same command carry
# different state_sha256 values and the two halves of decision #8 stop joining.
# tests/test_inline_shadow.sh asserts the hashes match Python's, which is the
# only thing that keeps two implementations of one format honest.
EXTRACT=$(printf '%s' "$PAYLOAD" | jq -j '
  def state:
    (.tool_input.command) as $cmd
    | ("Command:\n" + $cmd)
    # `!= ""` and not plain truthiness: jq considers the empty string true,
    # Python does not, and `if tool_input.get("description")` is what the
    # Python builder tests.
    + (if ((.tool_input.description // "") != "")
       then "\n\nStated purpose:\n" + .tool_input.description else "" end)
    + "\n\nWorking directory: " + (.cwd // "unknown");
  def truncate:
    if (. | length) > 60000
    then "[... earlier content truncated ...]\n" + .[-60000:] else . end;
  if ((.tool_input.command // "") == "") then empty
  else
    ((.session_id // "") + "\t" + (.tool_use_id // "") + "\n" + (state | truncate))
  end
') || { emit_minimal "payload_parse_error"; exit 0; }
[ -n "$EXTRACT" ] || { emit_minimal "no_command"; exit 0; }

IDS="${EXTRACT%%$'\n'*}"
STATE="${EXTRACT#*$'\n'}"
SESSION_ID="${IDS%%$'\t'*}"
TOOL_USE_ID="${IDS#*$'\t'}"

# openssl, not shasum: shasum is a perl script and pays a ~25ms interpreter
# startup on a path whose whole purpose is to measure milliseconds.
SHA_LINE=$(printf '%s' "$STATE" | openssl dgst -sha256 2>/dev/null)
STATE_SHA="${SHA_LINE##* }"

# Credentials from .env, falling back to the environment -- the same precedence
# paths.require uses. Read with the shell rather than grep/sed/cut so the common
# path costs no extra process.
API_KEY="$JEV_INLINE_API_KEY"
if [ -z "$API_KEY" ] && [ -f "$ROOT/.env" ]; then
  # `|| [ -n "$_k" ]`: read returns 1 at EOF even when it filled the variables,
  # so a .env whose last line has no trailing newline would otherwise lose its
  # last key -- and the key we want is frequently the last line.
  while IFS='=' read -r _k _v || [ -n "$_k" ]; do
    if [ "$_k" = "AI_GATEWAY_API_KEY" ]; then API_KEY="$_v"; break; fi
  done < "$ROOT/.env"
fi
[ -n "$API_KEY" ] || API_KEY="$AI_GATEWAY_API_KEY"

# The question set is read from questions/pre_bash/v1.json rather than inlined,
# so the deployed script and the replay harness ask literally the same question.
# question_set_id is derived in the row-writing jq rather than here: a separate
# jq just to read two strings would add a spawn to the number this script
# exists to measure.
jq -n --arg model "$MODEL" --arg state "$STATE" --slurpfile qs "$QFILE" '
  $qs[0] as $spec | $spec.primary_phrasing as $ph |
  {model: $model, state: $state,
   questions: ($spec.questions
               | with_entries(.value = {type: .value.type,
                                        instructions: .value.phrasings[$ph]}))}
' > "$TMPREQ" 2>/dev/null || { emit_minimal "request_build_error"; exit 0; }

: > "$TMPBODY"

DNS=0; CONNECT=0; APPCONNECT=0; TTFB=0; TOTAL=0; HTTP_CODE=0; CURL_EXIT=0
NO_KEY=""
if [ -z "$API_KEY" ]; then
  # No credential: skip the call rather than spend a round trip learning that
  # it would have been rejected. Still a logged row -- a run that never left the
  # machine is attrition like any other.
  NO_KEY=1
else
  # -w mirrors the decomposition src/arms/timed_http.py records, so an inline
  # latency and a worker latency are comparable field by field rather than only
  # in total. --max-time is the entire fail-safe: past it curl aborts, exit 28,
  # and the hook logs a timeout instead of holding up a tool call.
  TIMING=$(curl -s -o "$TMPBODY" \
    -w '%{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total} %{http_code}' \
    --max-time "$MAX_TIME" \
    -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $API_KEY" \
    --data-binary @"$TMPREQ" \
    "$ENDPOINT")
  CURL_EXIT=$?
  # Word splitting rather than `read <<<`: a here-string makes bash materialise
  # a temp file under $TMPDIR, which is outside this folder and would break the
  # self-containment claim for the sake of parsing six numbers.
  if [ -n "$TIMING" ]; then
    set -- $TIMING
    DNS="${1:-0}"; CONNECT="${2:-0}"; APPCONNECT="${3:-0}"
    TTFB="${4:-0}"; TOTAL="${5:-0}"; HTTP_CODE="${6:-0}"
  fi
fi

# Error vocabulary is timed_http's, deliberately: attrition joins across inline
# and worker rows on error_kind, and two vocabularies for one failure mode make
# that table useless.
ERROR_KIND=""
if [ -n "$NO_KEY" ]; then ERROR_KIND="no_api_key"; fi
case "$CURL_EXIT" in
  0)  ;;
  6)  ERROR_KIND="dns" ;;
  7)  ERROR_KIND="connection" ;;
  28) ERROR_KIND="timeout" ;;
  35|60|77|91) ERROR_KIND="tls" ;;
  *)  ERROR_KIND="connection" ;;
esac
if [ -z "$ERROR_KIND" ]; then
  case "$HTTP_CODE" in
    200|201) ;;
    401) ERROR_KIND="auth" ;;
    # 403 is its own kind: "the key is wrong" and "the key is fine but the
    # account is gated" are different problems.
    403) ERROR_KIND="account_gated" ;;
    429) ERROR_KIND="rate_limit" ;;
    5*)  ERROR_KIND="server_error" ;;
    *)   ERROR_KIND="client_error" ;;
  esac
fi

# %{http_code} is the literal string "000" when the transfer never completed,
# so it arrives as --arg and is converted inside jq rather than as --argjson.
jq -n -c \
  --rawfile body "$TMPBODY" \
  --arg ts "$TS" \
  --arg surface "$SURFACE" \
  --arg session_id "$SESSION_ID" \
  --arg tool_use_id "$TOOL_USE_ID" \
  --arg state_sha256 "$STATE_SHA" \
  --slurpfile qs "$QFILE" \
  --arg run_context "$RUN_CONTEXT" \
  --arg endpoint "$ENDPOINT" \
  --arg error_kind "$ERROR_KIND" \
  --arg http_code "$HTTP_CODE" \
  --arg curl_exit "$CURL_EXIT" \
  --arg max_time "$MAX_TIME" \
  --arg dns "$DNS" --arg connect "$CONNECT" --arg appconnect "$APPCONNECT" \
  --arg ttfb "$TTFB" --arg total "$TOTAL" \
  --arg t0 "$T0" \
  --arg tau_d "$TAU_DESTRUCTIVE" --arg tau_r "$TAU_NEEDS_REVIEW" '
  def num: (tonumber? // 0);
  # curl reports 0 for phases it never reached, so a failed connect after a
  # successful DNS lookup would otherwise subtract to a negative millisecond.
  def nonneg: (if . < 0 then 0 else . end);
  ((try ($body | fromjson) catch null)) as $b
  | ($b.answers // {}) as $a
  | {destructive: $tau_d, needs_review: $tau_r} as $tau_s
  | ($tau_s | with_entries(.value |= num)) as $tau
  | ($a | with_entries(.value = (.value.probability? // null))
        | with_entries(select(.value != null))) as $p
  | ($p | length > 0) as $answered
  | {
      timestamp: $ts,
      surface: $surface,
      session_id: $session_id,
      tool_use_id: $tool_use_id,
      state_sha256: $state_sha256,
      question_set_id: ($qs[0].question_set_id + "#" + $qs[0].primary_phrasing),
      run_context: $run_context,
      endpoint: $endpoint,
      # ok means "a decision was available", not "curl returned". A 200 with no
      # answers object is a failure for every purpose this row serves.
      ok: (($error_kind == "") and $answered),
      error_kind: (if $error_kind != "" then $error_kind
                   elif ($answered | not) then "malformed_response"
                   else null end),
      http_code: ($http_code | num),
      curl_exit: ($curl_exit | num),
      max_time_s: ($max_time | num),
      probabilities: $p,
      tau: $tau,
      # The whole point of the script: what enforce mode WOULD have done. It is
      # written down and never acted on.
      would_gate_per_question:
        ($p | with_entries(.value = (.value >= ($tau[.key] // 0.5)))),
      would_gate: ([$p | to_entries[] | .value >= ($tau[.key] // 0.5)] | any),
      response_model: ($b.model // null),
      input_tokens: ($b.usage.inputTokens // null),
      # Decomposed the same way src/arms/timed_http.py decomposes it, so inline
      # and worker latencies compare field by field. curl reports cumulative
      # seconds; these are per-phase milliseconds.
      timing_ms: {
        dns_ms:     (($dns | num) * 1000),
        connect_ms: ((($connect | num) - ($dns | num)) * 1000 | nonneg),
        tls_ms:     (if ($appconnect | num) > 0
                     then (($appconnect | num) - ($connect | num)) * 1000 | nonneg
                     else 0 end),
        ttfb_ms:    (($ttfb | num) * 1000),
        total_ms:   (($total | num) * 1000)
      },
      curl_time_total_ms: (($total | num) * 1000),
      # In-hook wall clock: everything the hook does, including its own jq and
      # openssl spawns, but NOT the cost of spawning the hook itself. That last
      # piece is only visible from outside, and bench_inline.py measures it.
      hook_ms: ((now - ($t0 | num)) * 1000)
    }
' >> "$LOG" 2>/dev/null || emit_minimal "row_write_error"

exit 0
