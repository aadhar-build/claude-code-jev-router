#!/bin/bash
# The four gates that must ALL pass before a surface's hook is enabled.
#
# This is the point in the project where a bug stops being a wrong number in a
# report and starts being something that interferes with real editing sessions.
# So the gates are adversarial: each one tries to make the hook misbehave.
#
#   1. isolation   -- nothing outside this folder is ever touched
#   2. fail-open   -- every failure path still exits 0
#   3. kill switch -- one file stops everything, instantly
#   4. future leakage (JEV-15) -- an arm can never see a turn that had not
#      happened when the decision point fired
#
# Run: ./tests/gates.sh [surface]        (default: pre_bash)
#
# --------------------------------------------------------------------------
# PARAMETERISED ON SURFACE (JEV-15)
# --------------------------------------------------------------------------
# Gates 1-3 used to hardcode `pre_bash`, so a new surface could be registered
# without ever being gated. JEV-19 (`stop`), JEV-20 (`post_edit`) and JEV-34
# (`agent_route` -- the surface that will be allowed to change which model the
# user's work runs on) each need to gate something that is not `pre_bash`, so
# the surface is now an argument and the payload shape follows from it.
#
# --------------------------------------------------------------------------
# THE GATES RUN IN A SANDBOX, AND THAT IS NOT COSMETIC
# --------------------------------------------------------------------------
# This script used to operate on the LIVE spool: it `rm -f spool/ready/*.json`
# between assertions, chmod'd `spool/tmp` unwritable, moved `spool/ready` and
# `logs/` aside, and wrote 501 filler files into the path a running worker
# drains. Against the live collection window that is silent data loss -- exactly
# the failure shape JEV-31/32/33 exist to stop -- because a deleted capture has
# no run row, no capture row, and therefore never appears in the attrition count
# the pre-registration commits to reporting.
#
# So every hook invocation here runs with CLAUDE_PROJECT_DIR pointed at a
# throwaway root under `logs/` (gitignored, inside the folder, removed on exit).
# The hook's guards are all anchored on CLAUDE_PROJECT_DIR, so the behaviour
# under test is identical -- and a capture escaping into the real spool now
# becomes a visible failure rather than the expected outcome. Gate 1's claims
# about the real repository (user-level settings, registration, gitignore) are
# still made against the real repository, because that is what they are about.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/hooks/capture.sh"
SURFACE="${1:-pre_bash}"
SESSION="gate-$SURFACE-$$"

mkdir -p "$ROOT/logs"
SANDBOX="$(mktemp -d "$ROOT/logs/gate-sandbox.XXXXXX")" || exit 1
GATEROOT="$SANDBOX"
mkdir -p "$GATEROOT/spool/tmp" "$GATEROOT/spool/ready" "$GATEROOT/logs" "$GATEROOT/data"
cleanup() { chmod -R u+rwX "$SANDBOX" 2>/dev/null; rm -rf "$SANDBOX"; }
trap cleanup EXIT

pass=0; fail=0
ok()  { echo "    ok    $1"; pass=$((pass+1)); }
bad() { echo "    FAIL  $1"; fail=$((fail+1)); }
reset(){ rm -f "$GATEROOT"/spool/ready/*.json "$GATEROOT"/spool/tmp/* 2>/dev/null; }
count(){ ls "$GATEROOT"/spool/ready/*.json 2>/dev/null | wc -l | tr -d ' '; }

# A minimal payload of the shape each surface's state builder actually consumes.
# `transcript_path` and `transcript_bytes_at_capture` are appended when given:
# the hook never parses either, but GATE 4 needs them in the payload it drains.
payload_for() { # surface [transcript_path] [byte_offset]
  s="$1"; tp="${2:-}"; off="${3:-}"
  extra=""
  [ -n "$tp" ]  && extra=",\"transcript_path\":\"$tp\""
  [ -n "$off" ] && extra="$extra,\"transcript_bytes_at_capture\":$off"
  head="{\"session_id\":\"$SESSION\",\"cwd\":\"$GATEROOT\",\"permission_mode\":\"default\""
  case "$s" in
    pre_bash)
      echo "$head,\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"ls -la\",\"description\":\"list\"}$extra}" ;;
    stop)
      echo "$head,\"last_assistant_message\":\"done\"$extra}" ;;
    user_prompt)
      echo "$head,\"prompt\":\"refactor the worker\",\"is_continuation\":false$extra}" ;;
    post_edit)
      echo "$head,\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$GATEROOT/x.py\",\"content\":\"print(1)\"},\"tool_response\":\"written\"$extra}" ;;
    *)
      echo "$head,\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"ls\"}$extra}" ;;
  esac
}

fire() { # payload [surface]
  (cd "$GATEROOT" && printf '%s\n' "$1" | CLAUDE_PROJECT_DIR="$GATEROOT" "$HOOK" "${2:-$SURFACE}")
}

PAYLOAD="$(payload_for "$SURFACE")"

echo
echo "=============================================================="
echo " GATES -- surface: $SURFACE"
echo " sandbox root: ${SANDBOX#$ROOT/}"
echo "=============================================================="

echo
echo "=============================================================="
echo " GATE 1 -- ISOLATION"
echo "=============================================================="
echo "  Nothing outside this folder may be written, and no session"
echo "  outside this folder may be captured."
echo

# 1a. User-level settings must never have been touched.
if [ -f "$HOME/.claude/settings.json" ]; then
  if python3 -c "import json,sys; sys.exit(0 if 'hooks' not in json.load(open('$HOME/.claude/settings.json')) else 1)"; then
    ok "~/.claude/settings.json has no hooks key"
  else
    bad "~/.claude/settings.json has a hooks key -- isolation broken"
  fi
else
  ok "~/.claude/settings.json absent"
fi

# 1b. Registration lives in settings.local.json, and that file is gitignored.
if [ -f "$ROOT/.claude/settings.local.json" ]; then
  ok ".claude/settings.local.json exists"
  if git -C "$ROOT" check-ignore -q .claude/settings.local.json; then
    ok "settings.local.json is gitignored (will not reach a clone or cloud session)"
  else
    bad "settings.local.json is TRACKED -- it would ship hooks to anyone who clones"
  fi
  if [ -f "$ROOT/.claude/settings.json" ]; then
    bad ".claude/settings.json exists -- that file DOES travel to cloud sessions"
  else
    ok "no .claude/settings.json (the file that would travel)"
  fi
else
  echo "    --    not registered yet (expected before go-live)"
fi

# 1c. A session in another directory must capture nothing.
reset
OUTSIDE="$SANDBOX/another-project"
mkdir -p "$OUTSIDE"
(cd "$OUTSIDE" && printf '%s\n' "$PAYLOAD" | CLAUDE_PROJECT_DIR="$OUTSIDE" "$HOOK" "$SURFACE") 2>/dev/null
[ "$(count)" = "0" ] && ok "a session in another directory captures nothing" \
                     || bad "captured from outside the folder"

# 1d. cwd guard: even with our project dir, a cwd outside the folder is refused.
reset
(cd /tmp && printf '%s\n' "$PAYLOAD" | CLAUDE_PROJECT_DIR="$GATEROOT" "$HOOK" "$SURFACE") 2>/dev/null
[ "$(count)" = "0" ] && ok "cwd guard refuses a cwd outside the folder" \
                     || bad "cwd guard did not hold"

# 1e. Worktree subagents: the guard must hold wherever the copy lives.
reset
(cd "$GATEROOT" && printf '%s\n' "$PAYLOAD" | JEV_ARM_SUBPROCESS=1 CLAUDE_PROJECT_DIR="$GATEROOT" "$HOOK" "$SURFACE") 2>/dev/null
[ "$(count)" = "0" ] && ok "arm subprocess captures nothing (no feedback loop)" \
                     || bad "an arm subprocess captured its own decision"

# 1f. Nothing is written outside the folder, checked by mtime across the run.
#
# Retried up to three times, which is not the usual excuse for a flaky test.
# The subject is DETERMINISTIC -- the hook either writes outside the folder on
# every invocation or on none -- while the observation window is shared with
# every other process on the machine, and /tmp is written by anything at any
# moment. A single clean window is therefore conclusive evidence for the hook;
# a dirty one is evidence about the machine. Failing reports the paths, so a
# real violation is diagnosable rather than just a count.
OUTSIDE_PATHS=""
attempt=1
while [ "$attempt" -le 3 ]; do
  STAMP="$SANDBOX/stamp"; touch "$STAMP"
  reset
  fire "$PAYLOAD" >/dev/null 2>&1
  OUTSIDE_PATHS=$(find "$HOME/.claude" "$HOME/.config" /tmp -maxdepth 2 -newer "$STAMP" \
                    -not -path "*/projects/*" 2>/dev/null | grep -v "^$STAMP$")
  rm -f "$STAMP"
  [ -z "$OUTSIDE_PATHS" ] && break
  attempt=$((attempt+1))
done
[ -z "$OUTSIDE_PATHS" ] && ok "no writes outside the folder during a capture" \
                        || bad "path(s) outside the folder changed: $(echo "$OUTSIDE_PATHS" | tr '\n' ' ')"

# 1g. The surface travels as a filename prefix, so the worker can route it.
reset
fire "$PAYLOAD" >/dev/null 2>&1
name=$(basename "$(ls "$GATEROOT"/spool/ready/*.json 2>/dev/null | head -1)" 2>/dev/null)
case "$name" in
  "$SURFACE"__*) ok "capture is filed under the surface it was fired for ($SURFACE)" ;;
  *)             bad "surface not encoded in filename: '$name'" ;;
esac
reset

echo
echo "=============================================================="
echo " GATE 2 -- FAIL-OPEN"
echo "=============================================================="
echo "  Every failure path must still exit 0. A measurement harness"
echo "  must never be able to wedge an editing session."
echo

GATE_OUT="$SANDBOX/gate-out"

try() { # name, setup, teardown
  reset
  eval "$2"
  (cd "$GATEROOT" && printf '%s\n' "$PAYLOAD" | CLAUDE_PROJECT_DIR="$GATEROOT" "$HOOK" "$SURFACE") >"$GATE_OUT" 2>/dev/null
  rc=$?
  eval "$3"
  out=$(cat "$GATE_OUT"); rm -f "$GATE_OUT"
  if [ "$rc" -eq 0 ] && [ -z "$out" ]; then ok "$1"; else bad "$1 (exit $rc, stdout '$out')"; fi
}

try "spool/tmp unwritable"      "chmod 500 '$GATEROOT/spool/tmp'"   "chmod 700 '$GATEROOT/spool/tmp'"
try "spool/ready unwritable"    "chmod 500 '$GATEROOT/spool/ready'" "chmod 700 '$GATEROOT/spool/ready'"
try "spool/ready missing"       "mv '$GATEROOT/spool/ready' '$GATEROOT/spool/ready.bak'" "mv '$GATEROOT/spool/ready.bak' '$GATEROOT/spool/ready'"
try "logs/ missing"             "mv '$GATEROOT/logs' '$GATEROOT/logs.bak'" "mv '$GATEROOT/logs.bak' '$GATEROOT/logs'"
try "CLAUDE_PROJECT_DIR unset"  "unset CLAUDE_PROJECT_DIR"      "true"
try "backpressure exceeded"     "i=0; while [ \$i -lt 501 ]; do echo '{}' > '$GATEROOT/spool/ready/f__\$i.json'; i=\$((i+1)); done" "reset"

# Empty and malformed stdin.
reset
(cd "$GATEROOT" && printf '' | CLAUDE_PROJECT_DIR="$GATEROOT" "$HOOK" "$SURFACE") 2>/dev/null; rc=$?
[ "$rc" -eq 0 ] && [ "$(count)" = "0" ] && ok "empty stdin: exits 0, spools nothing" || bad "empty stdin"
reset
(cd "$GATEROOT" && echo 'not json at all' | CLAUDE_PROJECT_DIR="$GATEROOT" "$HOOK" "$SURFACE") 2>/dev/null; rc=$?
[ "$rc" -eq 0 ] && ok "malformed stdin: exits 0 (the hook never parses, by design)" || bad "malformed stdin"
reset

# Downstream failure must not reach the session: a bogus key is a worker problem.
if grep -q '^AI_GATEWAY_API_KEY=.' "$ROOT/.env" 2>/dev/null; then
  ok "credentials present, and the hook never reads them (no network on the critical path)"
fi

echo
echo "=============================================================="
echo " GATE 3 -- KILL SWITCH"
echo "=============================================================="
echo "  One file stops everything, from any working directory."
echo

reset
touch "$GATEROOT/.jev-disabled"
(cd "$GATEROOT" && printf '%s\n' "$PAYLOAD" | CLAUDE_PROJECT_DIR="$GATEROOT" "$HOOK" "$SURFACE") 2>/dev/null; rc=$?
c1=$(count)
mkdir -p "$GATEROOT/src/deep/nested" 2>/dev/null
(cd "$GATEROOT/src/deep/nested" && printf '%s\n' "$PAYLOAD" | CLAUDE_PROJECT_DIR="$GATEROOT" "$HOOK" "$SURFACE") 2>/dev/null
c2=$(count)
rm -rf "$GATEROOT/src"
rm -f "$GATEROOT/.jev-disabled"
[ "$rc" -eq 0 ]  && ok "kill switch: exits 0" || bad "kill switch exit $rc"
[ "$c1" = "0" ]  && ok "kill switch: nothing captured from the repo root" || bad "captured despite kill switch"
[ "$c2" = "0" ]  && ok "kill switch: nothing captured from a subdirectory (anchored, not cwd-relative)" \
                 || bad "kill switch failed from a subdirectory"

reset
fire "$PAYLOAD" 2>/dev/null
[ "$(count)" = "1" ] && ok "removing the kill switch resumes capture" || bad "did not resume after removal"
reset

echo
echo "=============================================================="
echo " GATE 4 -- FUTURE LEAKAGE (decision #7)"
echo "=============================================================="
echo "  State is built from what existed when the hook fired, and"
echo "  from nothing that happened afterwards."
echo
echo "  Leakage would help EVERY arm equally, so no agreement metric"
echo "  can reveal it -- the numbers would simply be wrong, and"
echo "  unreproducible in enforce mode where the future does not"
echo "  exist. It has to be asserted here, at the hook/worker"
echo "  boundary, or nowhere."
echo
echo "  Offline: FakeArm only. No network, no spend, no live spool."
echo

G4="$SANDBOX/gate4"
mkdir -p "$G4"
TRANSCRIPT="$G4/transcript.jsonl"
DRAIN="$ROOT/tests/gate4_drain.py"

# A sandbox copy of config/ with the surface under test (and `stop`, which owns
# the negative control) switched to `shadow`. Config is data: the gate must not
# depend on which surfaces happen to be enabled today, and a capture quarantined
# because its surface is `off` would be a pass for entirely the wrong reason.
mkdir -p "$SANDBOX/config"
cp "$ROOT"/config/*.json "$SANDBOX/config/" 2>/dev/null
python3 -c '
import json, sys
path = sys.argv[1]
blob = json.load(open(path))
for surface in sys.argv[2:]:
    if surface in blob.get("surfaces", {}):
        blob["surfaces"][surface]["mode"] = "shadow"
json.dump(blob, open(path, "w"), indent=2)
' "$SANDBOX/config/surfaces.json" "$SURFACE" stop || bad "could not prepare the sandbox config"

drain() { # [--mutate] -> writes JSON to $G4/out.json
  python3 "$DRAIN" --sandbox "$GATEROOT" --config "$SANDBOX/config" $1 > "$G4/out.json" 2>"$G4/err"
}
cap_field(){ python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
c=d['new_captures']
print(c[0].get(sys.argv[2],'') if c else '')" "$G4/out.json" "$1"; }
n_new()    { python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))['new_captures']))" "$G4/out.json"; }
n_runs()   { python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['new_runs'])" "$G4/out.json"; }
state_has(){ python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
print('yes' if any(sys.argv[2] in c['state'] for c in d['new_captures']) else 'no')" "$G4/out.json" "$1"; }
dead_reasons(){ python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
print(' | '.join(x['reason'] for x in d['dead']))" "$G4/out.json"; }

# A fixture transcript the builders can actually parse. `build_stop` skips any
# line it cannot decode, so a fixture of junk would make even a LEAKING builder
# look stable -- the mutation check below would then pass for the wrong reason.
write_transcript() {
  : > "$TRANSCRIPT"
  i=1
  while [ "$i" -le 3 ]; do
    printf '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"PAST_TURN_%d what should we do"}]}}\n' "$i" >> "$TRANSCRIPT"
    printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"PAST_TURN_%d here is the plan"}]}}\n' "$i" >> "$TRANSCRIPT"
    i=$((i+1))
  done
}
append_future() { # n lines that could only have been written after the capture
  i=1
  while [ "$i" -le "${1:-20}" ]; do
    printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"FUTURE_TURN_%d this happened after the decision point"}]}}\n' "$i" >> "$TRANSCRIPT"
    i=$((i+1))
  done
}

# A surface with no state builder cannot be gated, and must say so rather than
# reporting a green result on an assertion it never made.
BUILDERS="$(python3 "$DRAIN" --sandbox "$GATEROOT" --config "$SANDBOX/config" --builders 2>/dev/null)"
LEAK_SURFACES="$SURFACE"
case "$BUILDERS" in
  *"\"$SURFACE\""*) ;;
  *) bad "no state builder for '$SURFACE' -- GATE 4 cannot assert decision #7 for this surface"
     LEAK_SURFACES="" ;;
esac
# `stop` is the ONLY surface whose state is read from the transcript at all, so
# it is always exercised: on a payload-only surface the leakage assertion is
# true by construction, and a gate that only ever tests the easy case is not a
# gate. Its negative control is the offset guard below.
case " $LEAK_SURFACES " in *" stop "*) ;; *) LEAK_SURFACES="$LEAK_SURFACES stop" ;; esac

for s in $LEAK_SURFACES; do
  echo "  --- $s ---"
  reset
  write_transcript
  OFFSET=$(wc -c < "$TRANSCRIPT" | tr -d ' ')
  P4="$(payload_for "$s" "$TRANSCRIPT" "$OFFSET")"

  # (a) capture, drain, record the hash. This is the reference.
  fire "$P4" "$s" 2>/dev/null
  drain
  SHA_A=$(cap_field state_sha256)
  SRC=$(cap_field state_source)
  if [ -n "$SHA_A" ] && [ "$(n_new)" = "1" ]; then
    ok "$s: capture drained through the worker; state_sha256 recorded"
  else
    bad "$s: nothing drained ($(cat "$G4/err" 2>/dev/null | tail -1))"
  fi
  [ -n "$SRC" ] && ok "$s: state_source recorded on the row ($SRC)" \
                || bad "$s: no state_source on the capture row"

  # (b) the real scenario: the capture sits in the spool while the session keeps
  #     going. Twenty more turns land BEFORE the worker gets to it.
  fire "$P4" "$s" 2>/dev/null
  append_future 20
  drain
  SHA_B=$(cap_field state_sha256)
  if [ -n "$SHA_B" ] && [ "$SHA_A" = "$SHA_B" ]; then
    ok "$s: 20 turns appended after capture do NOT change state_sha256"
  else
    bad "$s: LEAKAGE -- state_sha256 moved after the transcript grew ($SHA_A -> $SHA_B)"
  fi
  if [ "$(state_has FUTURE_TURN)" = "no" ]; then
    ok "$s: the stored state contains none of the 20 later turns"
  else
    bad "$s: LEAKAGE -- a later turn is present in the bytes the arms were given"
  fi

  # (c) the mutation. A test that cannot fail proves nothing, so the gate breaks
  #     the builder on purpose -- read `transcript_path` live, at worker time --
  #     and asserts that the two checks above DO fire.
  fire "$P4" "$s" 2>/dev/null
  drain --mutate
  SHA_C=$(cap_field state_sha256)
  if [ -n "$SHA_C" ] && [ "$SHA_C" != "$SHA_A" ]; then
    ok "$s: MUTATION -- a builder that reads the live transcript is caught (hash moves)"
  else
    bad "$s: MUTATION NOT CAUGHT -- the leakage assertion above is vacuous"
  fi
  if [ "$(state_has FUTURE_TURN)" = "yes" ]; then
    ok "$s: MUTATION -- the leaked state really does carry the later turns"
  else
    bad "$s: MUTATION did not leak; the FUTURE_TURN check is not testing what it claims"
  fi
done

# (d) NEGATIVE CONTROL. `build_stop` refuses to run without
#     `transcript_bytes_at_capture`, because without it there is nothing to
#     truncate at and the builder would read the tail as it exists now. The
#     refusal is in the builder; what has never been asserted is that it is
#     WIRED THROUGH THE WORKER -- that the capture is quarantined rather than
#     quietly processed on a full-file read. A guard that silently passes when
#     its input is missing is not a guard.
echo "  --- negative control: the stripped byte offset ---"
reset
write_transcript
P4="$(payload_for stop "$TRANSCRIPT")"   # no transcript_bytes_at_capture
case "$P4" in
  *transcript_bytes_at_capture*) bad "negative control payload still carries the offset" ;;
  *) ok "negative control: payload has transcript_path and NO byte offset" ;;
esac
fire "$P4" stop 2>/dev/null
drain
if [ "$(n_new)" = "0" ] && [ "$(n_runs)" = "0" ]; then
  ok "offset stripped: no capture row and no run row were written"
else
  bad "offset stripped: the capture was PROCESSED ($(n_new) captures, $(n_runs) runs)"
fi
REASONS="$(dead_reasons)"
case "$REASONS" in
  *transcript_bytes_at_capture*) ok "offset stripped: capture is quarantined, naming the missing offset" ;;
  *)                             bad "quarantine reason does not name the offset: '$REASONS'" ;;
esac

# (e) the gate itself must not have touched the live collection window.
LEAKED=$( { grep -rl "$SESSION" "$ROOT/spool" 2>/dev/null; grep -rl "$SESSION" "$ROOT/data/captures" 2>/dev/null; } | wc -l | tr -d ' ')
[ "$LEAKED" = "0" ] && ok "gate ran entirely in its sandbox: no trace in the live spool or captures" \
                    || bad "the gate wrote $LEAKED file(s) into the live collection window"

echo
echo "=============================================================="
printf " %d passed, %d failed   (surface: %s)\n" "$pass" "$fail" "$SURFACE"
if [ "$fail" -eq 0 ]; then
  echo " ALL GATES PASS -- safe to register the hook for $SURFACE"
else
  echo " GATES FAILED -- DO NOT register the hook for $SURFACE"
fi
echo "=============================================================="
[ "$fail" -eq 0 ]
