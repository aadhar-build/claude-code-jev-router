#!/bin/bash
# Seam 1, again: the inline-shadow hook's process boundary.
#
# This script does something capture.sh never does -- it makes a network call on
# the critical path -- so its contract is the same one but harder to keep:
# exit 0 always, stdout empty always, and a logged row on every path including
# the ones where everything went wrong. A dropped failure row is invisible
# attrition; an emitted byte on stdout is a permission decision we promised
# never to make.
#
# No network and no API spend: the happy path, the auth failure and the timeout
# all run against a loopback fake (src/bench_inline.py --serve), and the
# unreachable-host case uses a closed port on localhost so it fails identically
# on a plane. Set JEV_TEST_LIVE=1 to add ONE real call (~$0.000013).

#
# --------------------------------------------------------------------------
# SANDBOXED (JEV-42)
# --------------------------------------------------------------------------
# This file used to run the hook with CLAUDE_PROJECT_DIR pointed at the REAL
# project root, and the kill-switch case touched the REAL `.jev-disabled`.
# That is not a harmless second or two: for the duration of that window every
# live capture hook that fires exits on line one, so the decision points that
# happened during it are lost with no file missing and no row to count them --
# the same invisible attrition as JEV-42's `rm`, by a different mechanism. And
# a run interrupted between the `touch` and the `rm -f` leaves collection
# switched OFF indefinitely, with nothing anywhere to say so.
#
# It also wrote its scratch tree into the real `data/inline/`, alongside the
# live inline-shadow rows.
#
# So the hook now runs against a throwaway root under `logs/` (gitignored,
# removed on exit). `config/` and `questions/` are symlinked in because the
# hook reads them, and they are read-only inputs; `.env` likewise, for the
# opt-in live call. Every guard in the hook is `$CLAUDE_PROJECT_DIR`-anchored,
# so what is under test is unchanged.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/hooks/inline_shadow_bash.sh"

mkdir -p "$ROOT/logs"
SANDBOX="$(mktemp -d "$ROOT/logs/inlinetest.XXXXXX")" || exit 1
mkdir -p "$SANDBOX/spool/tmp" "$SANDBOX/spool/ready" "$SANDBOX/logs" "$SANDBOX/data"
ln -s "$ROOT/config"    "$SANDBOX/config"
ln -s "$ROOT/questions" "$SANDBOX/questions"
[ -f "$ROOT/.env" ] && ln -s "$ROOT/.env" "$SANDBOX/.env"
# Symlinked rather than copied: a copy of .env under logs/ would be a second
# home for the API key, at whatever mode the copy happened to land in.

WORK="$SANDBOX/work"
LOGDIR="$WORK/log"

pass=0; fail=0
ok()  { echo "  ok    $1"; pass=$((pass+1)); }
bad() { echo "  FAIL  $1"; fail=$((fail+1)); }

# `wait` after the kill so bash reaps the job quietly instead of printing a
# "Terminated" line into the middle of the test output.
cleanup() { kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; chmod -R u+rwX "$SANDBOX" 2>/dev/null; rm -rf "$SANDBOX"; }
trap cleanup EXIT

rm -rf "$WORK"; mkdir -p "$LOGDIR"

PAYLOAD='{"session_id":"itest","tool_use_id":"tu1","cwd":"/Users/dev/scratch","tool_name":"Bash","tool_input":{"command":"rm -rf /var/data","description":"clear the cache"}}'

reset() { rm -rf "$LOGDIR"; mkdir -p "$LOGDIR"; }
rows()  { cat "$LOGDIR"/*.jsonl 2>/dev/null; }
nrows() { rows | wc -l | tr -d ' '; }
field() { rows | tail -1 | jq -r "$1" 2>/dev/null; }

# Every case runs the hook the way Claude Code would, plus the two env overrides
# that keep the test's rows out of the live log.
run_hook() {
  (cd "$SANDBOX" && printf '%s' "$PAYLOAD" | \
    CLAUDE_PROJECT_DIR="$SANDBOX" \
    JEV_INLINE_LOG_DIR="$LOGDIR" \
    JEV_INLINE_API_KEY="${KEY:-test-key}" \
    JEV_INLINE_ENDPOINT="$ENDPOINT" \
    JEV_INLINE_MAX_TIME="${MAXTIME:-5}" \
    "$@" "$HOOK")
}

echo "seam 1: inline shadow hook process boundary"

# --- the loopback fake ------------------------------------------------------
python3 "$ROOT/src/bench_inline.py" --serve > "$WORK/url" 2>"$WORK/srv.err" &
SRV=$!
i=0
while [ ! -s "$WORK/url" ] && [ $i -lt 100 ]; do sleep 0.05; i=$((i+1)); done
BASE=$(cat "$WORK/url" 2>/dev/null)
if [ -n "$BASE" ]; then ok "loopback fake listening on $BASE"; else bad "fake server never started"; fi

# --- happy path -------------------------------------------------------------
reset
ENDPOINT="$BASE"
out=$(run_hook); rc=$?
[ "$rc" -eq 0 ]      && ok "happy: exits 0" || bad "happy: exit $rc"
[ -z "$out" ]        && ok "happy: stdout is empty" || bad "happy: stdout was [$out]"
[ "$(nrows)" = "1" ] && ok "happy: one row logged" || bad "happy: logged $(nrows) rows"
[ "$(field .ok)" = "true" ] && ok "happy: ok=true" || bad "happy: ok=$(field .ok)"
[ "$(field '.probabilities.destructive')" != "null" ] \
  && ok "happy: probabilities recorded" || bad "happy: no probabilities"
[ "$(field '.would_gate')" != "null" ] \
  && ok "happy: would-be decision recorded" || bad "happy: no decision"
[ "$(field '.timing_ms.total_ms')" != "null" ] \
  && ok "happy: curl timing decomposed" || bad "happy: no timing"
[ "$(field '.tool_use_id')" = "tu1" ] && ok "happy: join key carried" || bad "happy: no tool_use_id"

# The one assertion that keeps two implementations of one format honest. If the
# bash state builder drifts from state_builders.build_pre_bash, inline rows stop
# joining to the shadow rows measured for the same command, and decision #8
# quietly stops comparing like with like.
expected=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/src')
import state_builders as sb
print(sb.sha256(sb.build_pre_bash(json.loads(sys.stdin.read()))))
")
[ "$(field .state_sha256)" = "$expected" ] \
  && ok "happy: state_sha256 matches state_builders.build_pre_bash" \
  || bad "state drift: hook $(field .state_sha256) vs python $expected"

# The 60,000-char truncation is the subtle half of the same format: it only
# fires on a command longer than any test would otherwise write, and a
# one-character disagreement about where the cut lands changes the hash.
reset
BIG=$(python3 -c "import json;print(json.dumps({'session_id':'itest','tool_use_id':'big','cwd':'/x','tool_input':{'command':'echo '+'y'*70000}}))")
(cd "$SANDBOX" && printf '%s' "$BIG" | CLAUDE_PROJECT_DIR="$SANDBOX" \
  JEV_INLINE_LOG_DIR="$LOGDIR" JEV_INLINE_API_KEY=test-key \
  JEV_INLINE_ENDPOINT="$BASE" "$HOOK") >/dev/null 2>&1
expected_big=$(printf '%s' "$BIG" | python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/src')
import state_builders as sb
print(sb.sha256(sb.build_pre_bash(json.loads(sys.stdin.read()))))
")
[ "$(field .state_sha256)" = "$expected_big" ] \
  && ok "truncated state hashes identically to the Python builder" \
  || bad "truncation drift: hook $(field .state_sha256) vs python $expected_big"

# --- bogus API key ----------------------------------------------------------
reset
KEY="bogus"
out=$(run_hook); rc=$?
KEY=""
[ "$rc" -eq 0 ]      && ok "bogus key: exits 0" || bad "bogus key: exit $rc"
[ -z "$out" ]        && ok "bogus key: stdout is empty" || bad "bogus key: stdout was [$out]"
[ "$(nrows)" = "1" ] && ok "bogus key: failure logged as a row" || bad "bogus key: $(nrows) rows"
[ "$(field .error_kind)" = "auth" ] && ok "bogus key: error_kind=auth" || bad "bogus key: error_kind=$(field .error_kind)"
[ "$(field .ok)" = "false" ] && ok "bogus key: ok=false" || bad "bogus key: ok=$(field .ok)"

# --- unreachable host -------------------------------------------------------
# Port 9 on loopback: refused immediately, no DNS, deterministic offline.
reset
ENDPOINT="http://127.0.0.1:9/v1/evaluate"
out=$(run_hook); rc=$?
[ "$rc" -eq 0 ]      && ok "unreachable: exits 0" || bad "unreachable: exit $rc"
[ -z "$out" ]        && ok "unreachable: stdout is empty" || bad "unreachable: stdout was [$out]"
[ "$(nrows)" = "1" ] && ok "unreachable: failure logged as a row" || bad "unreachable: $(nrows) rows"
[ "$(field .error_kind)" = "connection" ] \
  && ok "unreachable: error_kind=connection" || bad "unreachable: error_kind=$(field .error_kind)"

# --- timeout ----------------------------------------------------------------
# The claim under test is not just "it logs a timeout" but "it gives up when it
# said it would". The fake sleeps 30s; --max-time is 1s; the wall clock has to
# show the hook came back on its own terms.
reset
ENDPOINT="$BASE/slow"
MAXTIME="1"
t0=$(python3 -c 'import time;print(time.time())')
out=$(run_hook); rc=$?
t1=$(python3 -c 'import time;print(time.time())')
MAXTIME=""
ENDPOINT="$BASE"
elapsed=$(python3 -c "print(f'{($t1-$t0):.2f}')")
under=$(python3 -c "print(1 if ($t1-$t0) < 2.5 else 0)")
[ "$rc" -eq 0 ]      && ok "timeout: exits 0" || bad "timeout: exit $rc"
[ -z "$out" ]        && ok "timeout: stdout is empty" || bad "timeout: stdout was [$out]"
[ "$(field .error_kind)" = "timeout" ] \
  && ok "timeout: error_kind=timeout" || bad "timeout: error_kind=$(field .error_kind)"
[ "$under" = "1" ] && ok "timeout: returned in ${elapsed}s, inside --max-time + slack" \
  || bad "timeout: took ${elapsed}s against a 1s --max-time"

# --- jq missing -------------------------------------------------------------
# jq is a hard dependency of THIS hook (capture.sh is deliberately parse-free),
# so its absence must degrade to a logged row rather than a stray byte or a
# non-zero exit. A PATH with everything but jq in it is the honest way to test
# that; a fake jq on the PATH would still satisfy `command -v`.
reset
SHIM="$WORK/shim"
mkdir -p "$SHIM"
for t in date mkdir openssl curl cat rm; do
  p=$(command -v "$t") && ln -sf "$p" "$SHIM/$t"
done
ENDPOINT="$BASE"
out=$(run_hook env "PATH=$SHIM"); rc=$?
[ "$rc" -eq 0 ]      && ok "no jq: exits 0" || bad "no jq: exit $rc"
[ -z "$out" ]        && ok "no jq: stdout is empty" || bad "no jq: stdout was [$out]"
[ "$(nrows)" = "1" ] && ok "no jq: still logged a row" || bad "no jq: $(nrows) rows"
if rows | grep -q '"error_kind":"no_jq"'; then
  ok "no jq: error_kind=no_jq"
else
  bad "no jq: row was $(rows | tail -1)"
fi

# --- kill switch ------------------------------------------------------------
reset
touch "$SANDBOX/.jev-disabled"
out=$(run_hook); rc=$?
rm -f "$SANDBOX/.jev-disabled"
[ "$rc" -eq 0 ]      && ok "kill switch: exits 0" || bad "kill switch: exit $rc"
[ -z "$out" ]        && ok "kill switch: stdout is empty" || bad "kill switch: stdout was [$out]"
[ "$(nrows)" = "0" ] && ok "kill switch: no call, no row" || bad "kill switch: logged $(nrows) rows"

# --- recursion guard --------------------------------------------------------
reset
out=$(run_hook env JEV_ARM_SUBPROCESS=1); rc=$?
[ "$rc" -eq 0 ]      && ok "arm subprocess: exits 0" || bad "arm subprocess: exit $rc"
[ -z "$out" ]        && ok "arm subprocess: stdout is empty" || bad "arm subprocess: stdout was [$out]"
[ "$(nrows)" = "0" ] && ok "arm subprocess: no call, no row" || bad "arm subprocess: logged $(nrows) rows"

# --- cwd guard --------------------------------------------------------------
reset
out=$(cd /usr && printf '%s' "$PAYLOAD" | CLAUDE_PROJECT_DIR="$SANDBOX" \
  JEV_INLINE_LOG_DIR="$LOGDIR" JEV_INLINE_API_KEY=test-key \
  JEV_INLINE_ENDPOINT="$BASE" "$HOOK"); rc=$?
[ "$rc" -eq 0 ]      && ok "cwd guard: exits 0" || bad "cwd guard: exit $rc"
[ "$(nrows)" = "0" ] && ok "cwd guard: nothing logged from outside the folder" \
  || bad "cwd guard: logged $(nrows) rows"

# --- malformed payload ------------------------------------------------------
reset
out=$(cd "$SANDBOX" && printf 'not json at all' | CLAUDE_PROJECT_DIR="$SANDBOX" \
  JEV_INLINE_LOG_DIR="$LOGDIR" JEV_INLINE_API_KEY=test-key \
  JEV_INLINE_ENDPOINT="$BASE" "$HOOK"); rc=$?
[ "$rc" -eq 0 ]      && ok "bad payload: exits 0" || bad "bad payload: exit $rc"
[ -z "$out" ]        && ok "bad payload: stdout is empty" || bad "bad payload: stdout was [$out]"
[ "$(nrows)" = "1" ] && ok "bad payload: logged a row" || bad "bad payload: $(nrows) rows"

# --- no temp files left behind ----------------------------------------------
leftover=$(ls -a "$LOGDIR" 2>/dev/null | grep -c '^\.\(req\|body\)\.')
[ "$leftover" = "0" ] && ok "no curl temp files left behind" || bad "$leftover temp files left"

# --- one live call, opt-in --------------------------------------------------
if [ "$JEV_TEST_LIVE" = "1" ]; then
  reset
  out=$(cd "$SANDBOX" && printf '%s' "$PAYLOAD" | CLAUDE_PROJECT_DIR="$SANDBOX" \
    JEV_INLINE_LOG_DIR="$LOGDIR" JEV_INLINE_RUN_CONTEXT=test "$HOOK"); rc=$?
  [ "$rc" -eq 0 ]             && ok "LIVE: exits 0" || bad "LIVE: exit $rc"
  [ -z "$out" ]               && ok "LIVE: stdout is empty" || bad "LIVE: stdout was [$out]"
  [ "$(field .ok)" = "true" ] && ok "LIVE: ok=true, model $(field .response_model), $(field .timing_ms.total_ms)ms" \
    || bad "LIVE: ok=$(field .ok) error_kind=$(field .error_kind)"
else
  echo "  skip  LIVE round trip (set JEV_TEST_LIVE=1 to spend ~\$0.000013)"
fi

echo "  -> $pass passed, $fail failed"
[ "$fail" -eq 0 ]
