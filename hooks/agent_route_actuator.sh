#!/bin/bash
# jev W1 -- THE STATIC FLOOR. The first actuator in this repo (JEV-35).
#
# A PreToolUse hook on the `Agent` tool that applies a static
# `subagent_type -> tier` map from config/tiers.json by rewriting
# `tool_input.model`. There is no classifier here, no network call, no Jev call,
# no API key, and nothing that can time out. Five independent sources find
# learned routers frequently fail to beat a trivial static rule; this is that
# rule, shipped first, as the baseline anything cleverer has to beat.
#
# BUILT, NOT ARMED. `agent_route` is `mode: "off"` in config/surfaces.json and
# no entry for this script exists in .claude/settings.local.json. Arming is a
# separate deliberate act (JEV-52).
#
# ---------------------------------------------------------------------------
# FAIL SAFE AND FAIL TO FRONTIER ARE NOT THE SAME THING
# ---------------------------------------------------------------------------
# This repo has already shipped a kill switch that stopped one writer and not
# the other, so the two properties are separated here explicitly.
#
#   FAIL SAFE (absolute, structural).  `trap 'exit 0' EXIT` on the first line
#   makes every unhandled error inert: the hook exits 0, emits nothing, and the
#   tool input is untouched. Nothing this script can do may wedge a session.
#
#   FAIL TO FRONTIER (a routing decision, and only a routing decision).
#   Operator decision 2026-09-21, overriding the default recommendation: when
#   the router cannot decide but a FAITHFUL rewrite is still constructible, the
#   task goes to the frontier tier rather than a cheap one. Quality is protected
#   on the error path; cost is not.
#
# The boundary between them is the payload. Fail-to-frontier requires echoing
# every field of `tool_input` back, so it is reachable ONLY after `tool_input`
# has parsed. Before that -- no jq, empty stdin, garbage stdin -- there is no
# faithful `updatedInput` to build, and the only correct action is to emit
# nothing. Emitting a partial object would spawn the wrong agent type, which is
# indistinguishable in the results from a routing-quality effect. So:
#
#   payload parsed + config broken   -> frontier rewrite, all fields echoed
#   payload unparseable              -> ZERO bytes on stdout, input untouched
#
# Both count as router failures for the breaker. Neither can break the session.
#
# ---------------------------------------------------------------------------
# THE CIRCUIT BREAKER, AND WHY IT IS MANDATORY
# ---------------------------------------------------------------------------
# Fail-to-frontier protects quality and does not protect cost: a sustained
# failure silently bills frontier rates for as long as it lasts. After N
# consecutive failures inside the TTL the hook STOPS REWRITING ENTIRELY, leaves
# the input untouched, drops a sticky marker file, and says so in a
# `systemMessage` -- the loudest channel a hook actually has, since stdout is a
# permission decision and stderr is a log nobody reads.
#
# State is an APPEND-ONLY OUTCOME LOG, never a counter file. Parallel `Agent`
# spawns are the normal case in this harness and a read-modify-write counter
# loses increments under exactly the conditions that matter. One short line per
# outcome, O_APPEND and well under PIPE_BUF, interleaves cleanly -- the property
# hooks/capture.sh already relies on. Open/closed is DERIVED from the tail of
# that log, so there is no stuck state and no reset step to forget, and
# half-open falls out for free: past the TTL the newest failure is stale, one
# attempt is allowed, and its own outcome line decides. While the breaker is
# open nothing is appended, so the TTL can actually expire.
#
# Usage: agent_route_actuator.sh          (PreToolUse/Agent payload on stdin)

# The trap comes FIRST, before anything that can fail -- capture.sh's discipline
# transplanted verbatim, and for the same reason: logs/ is gitignored, so on a
# fresh checkout a failed stderr redirect would exit non-zero before any later
# trap could catch it.
trap 'exit 0' EXIT
# No `set -e`: a failure must skip the decision, not abort with a nonzero status.

# STDOUT DISCIPLINE, MADE STRUCTURAL RATHER THAN REMEMBERED.
# Claude Code parses this hook's stdout as a permission decision, so a stray
# byte from jq, tail or openssl would be us gating a tool call we promised never
# to gate. inline_shadow_bash.sh closes stdout outright; this hook cannot,
# because emitting on stdout is its whole job. So instead: fd 3 becomes the real
# stdout and fd 1 goes to /dev/null. No later line CAN leak, and the single
# deliberate emission at the bottom is the only thing addressed to `>&3`.
exec 3>&1 >/dev/null

# Decimal separators and collation: pinned for the same reason inline_shadow
# pins them -- a comma-decimal locale turns a timestamp into something that is
# not a JSON number.
export LC_ALL=C

ROOT="${CLAUDE_PROJECT_DIR:-}"
if [ -n "$ROOT" ] && [ -d "$ROOT/logs" ]; then
  exec 2>>"$ROOT/logs/agent_route.err"
else
  exec 2>/dev/null
fi

# Recursion guard. The cc_* arms shell out to `claude -p`, which starts a real
# Claude Code session -- one that would load this project's hooks and have its
# own delegations rewritten by the actuator under measurement. Env vars are
# inherited, so the guard holds however deep the spawn goes.
[ -n "$JEV_ARM_SUBPROCESS" ] && exit 0

# The blinded grader's own delegations must not be routed by the thing it is
# grading. Same shape as the recursion guard, different reason.
[ -n "$JEV_GRADER" ] && exit 0

[ -n "$ROOT" ] || exit 0
[ -d "$ROOT" ] || exit 0

# --- jev GLOBAL kill switch -------------------------------------------------
# Switch one of two. This one is machine-wide: it stops routing in EVERY project
# at once, which is what you want at 3am when you do not yet know which repo is
# misbehaving. Read-only; nothing in this repo ever writes here.
#
# Same fail-safe rule as the per-project switch below: ANY entry at the path
# means OFF, and a state that cannot be established ALSO means OFF -- hence the
# unset-HOME case. A switch is never given the benefit of the doubt.
[ -n "$HOME" ] || exit 0
{ [ -e "$HOME/.claude/jev-disabled" ] || [ -L "$HOME/.claude/jev-disabled" ]; } && exit 0
# --- end jev GLOBAL kill switch ---------------------------------------------

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

# Defensive cwd guard, as capture.sh. settings.local.json should never load
# outside this repo, but the isolation requirement is hard enough to be worth
# enforcing twice -- and this hook changes what runs, not merely what is logged.
case "$PWD/" in
  "$ROOT"/*) ;;
  *) exit 0 ;;
esac

# jq is the only way to echo an arbitrary tool input back byte-faithfully. With
# no jq there is no faithful updatedInput to build, so the hook goes inert
# rather than guessing -- see the fail-safe/fail-to-frontier note above.
command -v jq >/dev/null 2>&1 || exit 0

CFG="$ROOT/config/tiers.json"
DIR="$ROOT/data/agent_route"
LEDGER_DIR="$DIR/assignments"
BREAKER="$DIR/breaker.jsonl"
MARKER="$DIR/BREAKER-OPEN"

# THE ONE TIER LITERAL IN THIS SCRIPT, AND IT IS DELIBERATE.
# Everything else is configuration. This is the fail-to-frontier target used
# when config/tiers.json is the thing that failed -- and a fail-safe value
# cannot itself depend on the thing that failed. "opus" is the frontier ALIAS,
# matching tiers.opus5.alias; if you change the frontier tier in config, change
# this too, and tests/test_agent_actuator.py asserts the two agree.
FRONTIER_FALLBACK_ALIAS="opus"
# Breaker defaults for the same path: when config cannot be read, its breaker
# settings cannot be read either, and an unbounded fail-to-frontier is the exact
# outage the breaker exists to stop.
BREAKER_N_FALLBACK=3
BREAKER_TTL_FALLBACK=900

TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# One extra fork to get a sub-second clock: /bin/bash on macOS is 3.2, with no
# EPOCHREALTIME and no printf %()T, and BSD date has no %N. inline_shadow_bash.sh
# pays the same fork for the same reason. `hook_ms` travels on every ledger row
# so the latency budget in config/tiers.json is a measurement, not an intention.
T0=$(jq -n 'now' 2>/dev/null) || T0=0

PAYLOAD=$(cat)
[ -n "$PAYLOAD" ] || exit 0

# Defensive: this hook is registered with matcher `Agent` and should never see
# anything else, but a matcher is a regex in a settings file and settings files
# get edited. Rewriting `model` on some other tool's input would be a silent
# corruption, so anything that is not an Agent spawn is left strictly alone --
# and is not a router failure either, because nothing was asked of the router.
case "$PAYLOAD" in
  *'"tool_name":"Agent"'*|*'"tool_name": "Agent"'*) ;;
  *) exit 0 ;;
esac

mkdir -p "$LEDGER_DIR" 2>/dev/null
LEDGER="$LEDGER_DIR/${TS%%T*}.jsonl"

# Content hash of the rule table, so a decision can later be joined to the exact
# rule text that produced it. openssl, not shasum: shasum is a perl script and
# pays ~25ms of interpreter startup on a path whose budget is measured in
# milliseconds. src/tier_map.config_sha256() computes the same digest with
# hashlib and a test asserts they agree.
CFG_SHA=""
if [ -f "$CFG" ]; then
  CFG_SHA_LINE=$(openssl dgst -sha256 "$CFG" 2>/dev/null)
  CFG_SHA="${CFG_SHA_LINE##* }"
fi

# The tail of the breaker log. `tail` rather than a bash read loop: the log is
# append-only and unbounded, and reading all of it in the shell would make the
# hook slower the longer it has been installed. 50 lines bounds the window;
# tests/test_agent_actuator.py asserts max_consecutive_failures stays well
# inside it.
BREAKER_TAIL=$(tail -n 50 "$BREAKER" 2>/dev/null)

# The breaker predicate, defined ONCE and spliced into both jq programs below.
# The fallback program cannot read the config, so it must still be able to open
# the breaker with literal defaults -- otherwise a permanently broken config
# would fail to frontier forever with the breaker never engaging. Sharing the
# text rather than retyping it is what stops the two copies drifting.
JQ_BREAKER='
  def breaker_state($log; $n; $ttl; $now):
    ($log | split("\n") | map(select(length > 0) | (fromjson? // empty))
          | sort_by(.ts // 0)) as $bo
    | ($bo | reverse) as $rev
    | ([ $rev | to_entries[] | select(.value.ok == true) | .key ]
       | (.[0] // ($rev | length))) as $consec
    | (if ($bo | length) > 0 then (($bo | last).ts // 0) else 0 end) as $newest
    | (($now - $newest) < $ttl) as $fresh
    | {open: (($n > 0) and ($consec >= $n) and $fresh and (($bo | length) >= $n)),
       consecutive: $consec, newest: $newest};
'

# Three lines out of jq, always, in this order:
#   1. the assignment ledger row (JSON)
#   2. what to write to the real stdout, or "-" for nothing
#   3. the breaker outcome line to append, or "-" for nothing
#
# "-" for nothing rather than an empty line, because an empty line is also what
# a truncated jq run produces and the two must not be confusable.
JQ_DECIDE='
  $cfg[0] as $c
  | (.tool_input) as $ti
  | if ($ti | type) != "object" then error("no tool_input") else . end
  | if (($c.tiers | type) != "object") or (($c.rules | type) != "object")
       or (($c.tiers[$c.frontier_tier] | type) != "object")
    then error("unusable tiers.json") else . end
  | (($c.breaker.max_consecutive_failures // 3) | floor) as $bn
  | (($c.breaker.ttl_s // 900) | tonumber) as $bttl
  | breaker_state($breaker; $bn; $bttl; now) as $br
  | ($ti.subagent_type // null) as $st
  | (if (($ti.model // "") == "") then null else $ti.model end) as $orig
  # `inherit` sits in tool_input.model but expresses no tier preference -- it
  # means "use whatever model the parent is on". Treating it as a deliberate
  # caller choice would exclude those spawns from routing forever while looking
  # like deference to the caller. Still recorded as original_model either way.
  # (No apostrophes in this program: it is a single-quoted shell string.)
  | (($c.explicit_model_ignored_values // ["inherit"])) as $ignored
  | (($orig != null) and (($ignored | index($orig)) == null)) as $chose
  | (if $br.open then
       {outcome: "breaker_open", tier: null, alias: null,
        rule: ("breaker OPEN: " + ($br.consecutive | tostring)
               + " consecutive failures, threshold " + ($bn | tostring))}
     elif ($chose and (($c.explicit_model_action // "keep") == "keep")) then
       {outcome: "explicit_model_kept", tier: null, alias: null,
        rule: ("explicit_model_action=keep; caller asked for " + ($orig | tojson))}
     else
       ($c.rules[$st // ""] // null) as $rule
       | if $rule == null then
           (if (($c.unmapped_action // "leave") == "frontier") then
              {outcome: "routed", tier: $c.frontier_tier,
               alias: $c.tiers[$c.frontier_tier].alias,
               rule: ("unmapped_action=frontier for subagent_type=" + ($st | tojson))}
            else
              {outcome: "no_rule", tier: null, alias: null,
               rule: ("unmapped_action=leave; no rule for subagent_type=" + ($st | tojson))}
            end)
         elif ($rule.tier == null) then
           {outcome: "no_rule", tier: null, alias: null,
            rule: ("rules[" + ($st | tojson) + "].tier=null (no routing signal)")}
         elif (($c.tiers[$rule.tier] | type) != "object") then
           error("rule names unknown tier")
         else
           {outcome: "routed", tier: $rule.tier, alias: $c.tiers[$rule.tier].alias,
            rule: ("rules[" + ($st | tojson) + "].tier=" + ($rule.tier | tojson))}
         end
     end) as $d
  | {schema: "agent-route-assignment-v1",
     timestamp: $ts,
     session_id: (.session_id // null),
     tool_use_id: (.tool_use_id // null),
     subagent_type: $st,
     decision: $d.outcome,
     tier: $d.tier,
     assigned_alias: $d.alias,
     rule: $d.rule,
     original_model: $orig,
     config_version: ($c.version // null),
     config_sha256: (if $sha == "" then null else $sha end),
     hook_ms: ((now - ($t0 | tonumber)) * 1000)} as $row
  | $row,
    (if $d.alias != null then
       # `$ti + {model: ...}` is a RIGHT-BIASED MERGE over the whole object, so
       # every key the caller sent survives by construction -- there is no
       # field list here that could fall out of date. This is the
       # input-fidelity gate: updatedInput replaces the ENTIRE tool input, and
       # a dropped `subagent_type` spawns the wrong agent type.
       ({hookSpecificOutput: {hookEventName: "PreToolUse",
                              permissionDecision: "allow",
                              updatedInput: ($ti + {model: $d.alias})}} | tojson)
     elif $d.outcome == "breaker_open" then
       # The loudest channel a hook has. No updatedInput: the input is left
       # exactly as it arrived, so hook_dispatch treats this as "unchanged" and
       # the OFF-is-vanilla byte-identity claim still holds.
       ({systemMessage: ("jev routing breaker OPEN (" + ($br.consecutive | tostring)
                         + " consecutive router failures) -- static routing is "
                         + "SUSPENDED and every delegation is running at its "
                         + "default tier. See data/agent_route/BREAKER-OPEN.")} | tojson)
     else "-" end),
    (if ($d.outcome == "breaker_open") then
       # Deliberately append nothing while open: another failure line would
       # push the newest timestamp forward and the TTL could never expire.
       "-"
     else
       ({ts: now, ok: ($d.outcome != "fail_to_frontier"),
          error: (if $d.outcome == "fail_to_frontier" then $d.rule else null end)}
        | tojson)
     end)
'

# The fallback: payload parsed, config did not. Everything the caller sent is
# echoed and `model` goes to the frontier alias. Reached only when JQ_DECIDE
# raised -- and if the payload is what is broken, this raises too and the hook
# emits nothing at all, which is the correct answer.
JQ_FRONTIER='
  (.tool_input) as $ti
  | if ($ti | type) != "object" then error("no tool_input") else . end
  | breaker_state($breaker; ($bn | tonumber); ($bttl | tonumber); now) as $br
  | (if $br.open then
       {outcome: "breaker_open", alias: null,
        rule: ("breaker OPEN: " + ($br.consecutive | tostring) + " consecutive failures")}
     else
       {outcome: "fail_to_frontier", alias: $frontier,
        rule: ("fail_to_frontier: " + $why)}
     end) as $d
  | {schema: "agent-route-assignment-v1",
     timestamp: $ts,
     session_id: (.session_id // null),
     tool_use_id: (.tool_use_id // null),
     subagent_type: ($ti.subagent_type // null),
     decision: $d.outcome,
     tier: null,
     assigned_alias: $d.alias,
     rule: $d.rule,
     original_model: (if (($ti.model // "") == "") then null else $ti.model end),
     config_version: null,
     config_sha256: (if $sha == "" then null else $sha end),
     hook_ms: ((now - ($t0 | tonumber)) * 1000)},
    (if $d.alias != null then
       ({hookSpecificOutput: {hookEventName: "PreToolUse",
                              permissionDecision: "allow",
                              updatedInput: ($ti + {model: $d.alias})}} | tojson)
     elif $d.outcome == "breaker_open" then
       ({systemMessage: ("jev routing breaker OPEN (" + ($br.consecutive | tostring)
                         + " consecutive router failures) -- static routing is "
                         + "SUSPENDED and every delegation is running at its "
                         + "default tier. See data/agent_route/BREAKER-OPEN.")} | tojson)
     else "-" end),
    (if $d.outcome == "breaker_open" then "-"
     else ({ts: now, ok: false, error: $d.rule} | tojson) end)
'

RESULT=$(printf '%s' "$PAYLOAD" | jq -r -c \
  --slurpfile cfg "$CFG" \
  --arg ts "$TS" --arg sha "$CFG_SHA" --arg t0 "$T0" \
  --arg breaker "$BREAKER_TAIL" \
  "$JQ_BREAKER $JQ_DECIDE" 2>/dev/null)

if [ -z "$RESULT" ]; then
  WHY="tiers.json missing or unusable"
  [ -f "$CFG" ] || WHY="tiers.json not found at config/tiers.json"
  RESULT=$(printf '%s' "$PAYLOAD" | jq -r -c \
    --arg ts "$TS" --arg sha "$CFG_SHA" --arg t0 "$T0" \
    --arg breaker "$BREAKER_TAIL" \
    --arg frontier "$FRONTIER_FALLBACK_ALIAS" --arg why "$WHY" \
    --arg bn "$BREAKER_N_FALLBACK" --arg bttl "$BREAKER_TTL_FALLBACK" \
    "$JQ_BREAKER $JQ_FRONTIER" 2>/dev/null)
fi

# Still nothing: the payload itself is unparseable. There is no faithful
# updatedInput to build, so the hook emits ZERO bytes and the tool input is
# untouched. Recorded as a router failure so a run of malformed payloads opens
# the breaker rather than quietly disappearing.
if [ -z "$RESULT" ]; then
  printf '{"ts":%s,"ok":false,"error":"unparseable_payload"}\n' \
    "${T0:-0}" >> "$BREAKER" 2>/dev/null
  exit 0
fi

ROW="${RESULT%%$'\n'*}"
REST="${RESULT#*$'\n'}"
EMIT="${REST%%$'\n'*}"
OUTCOME="${REST#*$'\n'}"

# --- THE ASSIGNMENT LEDGER, WRITTEN BEFORE THE SPAWN ------------------------
# Not after. A ledger written afterwards is missing exactly when it matters
# most: when the task crashed. Everything below this point is ordered so that
# the durable record exists before the decision can take effect.
printf '%s\n' "$ROW" >> "$LEDGER" 2>/dev/null
LEDGER_RC=$?

if [ "$LEDGER_RC" -ne 0 ]; then
  # The ledger could not be written. Three options were available: rewrite
  # anyway (an unattributable assignment, which is precisely what the
  # before-spawn gate forbids), block the call (never -- fail safe is
  # absolute), or leave the input untouched. Untouched wins: it is the control
  # arm, and its absence from the ledger is itself the honest record.
  printf '{"ts":%s,"ok":false,"error":"ledger_write_failed"}\n' \
    "${T0:-0}" >> "$BREAKER" 2>/dev/null
  exit 0
fi

[ "$OUTCOME" = "-" ] || printf '%s\n' "$OUTCOME" >> "$BREAKER" 2>/dev/null

# The sticky marker: a breaker open only in a transcript is a breaker nobody
# finds tomorrow morning. src/doctor.py reads this file.
case "$ROW" in
  *'"decision":"breaker_open"'*)
    printf '%s jev routing breaker OPEN -- static routing suspended, every delegation at its default tier.\nClear by fixing the cause; the breaker closes itself on the first successful decision after the TTL.\n' \
      "$TS" > "$MARKER" 2>/dev/null ;;
  *) rm -f "$MARKER" 2>/dev/null ;;
esac

# The single deliberate emission, on the only fd that reaches Claude Code.
[ "$EMIT" = "-" ] || printf '%s\n' "$EMIT" >&3

exit 0
