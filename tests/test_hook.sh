#!/bin/bash
# Seam 1: the hook's process boundary.
#
# Feed a recorded payload on stdin; assert on exit code, stdout, and the files
# that appear in the spool. No network, no Python, no running Claude Code.
#
# The hook's contract is narrow and absolute: exit 0 always, stdout empty always
# (Claude Code parses it, and a stray byte there is a permission decision we
# never intended to make), and never lose or half-write a record.
#
# --------------------------------------------------------------------------
# THIS TEST RUNS IN A SANDBOX, AND THAT IS NOT COSMETIC (JEV-42)
# --------------------------------------------------------------------------
# Until 2026-09-20 every assertion below ran against the REAL project root.
# `reset()` was `rm -f "$ROOT"/spool/ready/*.json` and it ran between assertion
# blocks; the fail-open case `chmod 500`-ed the live staging directory; the
# backpressure case wrote 501 filler files into the directory a running worker
# was draining; the fresh-checkout case moved `logs/` aside. `run_all.sh`
# invokes this file, so "run the full test suite" -- the instruction in every
# agent brief -- was the destructive command.
#
# It destroyed live captures. At least seven invocations across roughly
# 14:10Z-15:05Z on 2026-09-20, by two agents. The number lost is unknown and
# unrecoverable, and it is declared in PREREGISTRATION.md Amendment 6 rather
# than estimated away, because a capture deleted from `spool/ready/` leaves no
# capture row and no run row and therefore cannot enter the attrition count the
# pre-registration commits to reporting. That is the same failure shape as
# JEV-31/32/33: loss invisible to the measurement built to catch it.
#
# Note that `rm` was only the loudest of the three mechanisms. `chmod 500` on
# the live `spool/tmp` deletes nothing -- it makes every hook that fires during
# the window take its fail-open path and drop the capture, leaving no missing
# file to notice afterwards.
#
# So every hook invocation here runs with CLAUDE_PROJECT_DIR pointed at a
# throwaway root under `logs/` (gitignored, inside the folder, removed on
# exit), exactly as `tests/gates.sh` now does.
#
# WHY THIS DOES NOT WEAKEN THE TEST. Every path `hooks/capture.sh` touches is
# derived from `$CLAUDE_PROJECT_DIR`: `ROOT="${CLAUDE_PROJECT_DIR:-}"`, then
# `$ROOT/logs/capture.err`, `$ROOT/.jev-disabled`, `$ROOT/spool/tmp`,
# `$ROOT/spool/ready`, `$ROOT/data/drops`, and the cwd guard compares `$PWD/`
# against `"$ROOT"/*`. There is no `$HOME`, no `/tmp`, no `dirname $0`, no
# hardcoded path anywhere in the script. The hook cannot tell the difference,
# so the behaviour under test is IDENTICAL -- and a capture escaping into the
# real spool is now a visible failure (the last assertion) rather than the
# expected outcome.
#
# The mutation proof that these assertions still bite lives in
# tests/test_hook_mutations.sh: it breaks the hook eight ways and requires each
# break to produce a specific FAIL line here.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Overridable so tests/test_hook_mutations.sh can run this file against a
# deliberately broken COPY of the hook. The live hooks/capture.sh is never
# edited: a real session is firing it right now.
HOOK="${JEV_TEST_HOOK:-$ROOT/hooks/capture.sh}"

mkdir -p "$ROOT/logs"
SANDBOX="$(mktemp -d "$ROOT/logs/hooktest.XXXXXX")" || exit 1
TESTROOT="$SANDBOX"
mkdir -p "$TESTROOT/spool/tmp" "$TESTROOT/spool/ready" "$TESTROOT/logs" "$TESTROOT/data"
cleanup() { chmod -R u+rwX "$SANDBOX" 2>/dev/null; rm -rf "$SANDBOX"; }
trap cleanup EXIT

# Unique per run, so the "did anything reach the live window" check at the end
# is actually capable of finding something. The old fixed "test" would have
# matched (or not matched) for reasons unrelated to this run.
SESSION="hooktest-$$"
PAYLOAD='{"session_id":"'"$SESSION"'","cwd":"'"$TESTROOT"'","tool_name":"Bash","tool_input":{"command":"ls"}}'

pass=0; fail=0
ok()   { echo "  ok    $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL  $1"; fail=$((fail+1)); }
reset(){ rm -f "$TESTROOT"/spool/ready/*.json "$TESTROOT"/spool/tmp/* 2>/dev/null; }
count(){ ls "$TESTROOT"/spool/ready/*.json 2>/dev/null | wc -l | tr -d ' '; }

echo "seam 1: hook process boundary"
echo "  sandbox root: ${SANDBOX#$ROOT/}"

# --- happy path -------------------------------------------------------------
reset
out=$(cd "$TESTROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$TESTROOT" "$HOOK" pre_bash)
rc=$?
[ "$rc" -eq 0 ]        && ok "exits 0" || bad "exit code was $rc"
[ -z "$out" ]          && ok "stdout is empty" || bad "stdout was: $out"
[ "$(count)" = "1" ]   && ok "one record spooled" || bad "spooled $(count) records"

name=$(basename "$(ls "$TESTROOT"/spool/ready/*.json 2>/dev/null)" 2>/dev/null)
case "$name" in pre_bash__*) ok "surface encoded in filename" ;; *) bad "bad name: $name" ;; esac
if [ -z "$(ls -A "$TESTROOT/spool/tmp" 2>/dev/null)" ]; then ok "staging dir left clean"; else bad "staging dir not clean"; fi
if grep -q "\"session_id\":\"$SESSION\"" "$TESTROOT"/spool/ready/*.json 2>/dev/null; then ok "payload stored verbatim"; else bad "payload altered"; fi

# --- kill switch ------------------------------------------------------------
reset
touch "$TESTROOT/.jev-disabled"
(cd "$TESTROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$TESTROOT" "$HOOK" pre_bash); rc=$?
rm -f "$TESTROOT/.jev-disabled"
[ "$rc" -eq 0 ]      && ok "kill switch: exits 0" || bad "kill switch exit $rc"
[ "$(count)" = "0" ] && ok "kill switch: nothing captured" || bad "captured despite kill switch"

# --- cwd guard --------------------------------------------------------------
reset
(cd /tmp && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$TESTROOT" "$HOOK" pre_bash); rc=$?
[ "$rc" -eq 0 ]      && ok "cwd guard: exits 0" || bad "cwd guard exit $rc"
[ "$(count)" = "0" ] && ok "cwd guard: nothing captured outside the folder" || bad "captured from outside cwd"

# --- missing CLAUDE_PROJECT_DIR --------------------------------------------
reset
(cd "$TESTROOT" && echo "$PAYLOAD" | env -u CLAUDE_PROJECT_DIR "$HOOK" pre_bash); rc=$?
[ "$rc" -eq 0 ]      && ok "no project dir: exits 0" || bad "no project dir exit $rc"
[ "$(count)" = "0" ] && ok "no project dir: nothing captured" || bad "captured without project dir"

# --- unwritable spool (fail-open) ------------------------------------------
reset
chmod 500 "$TESTROOT/spool/tmp"
(cd "$TESTROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$TESTROOT" "$HOOK" pre_bash) >/dev/null 2>&1; rc=$?
chmod 700 "$TESTROOT/spool/tmp"
[ "$rc" -eq 0 ] && ok "unwritable spool: still exits 0 (fails open)" || bad "unwritable spool exit $rc"

# --- empty stdin ------------------------------------------------------------
reset
(cd "$TESTROOT" && printf '' | CLAUDE_PROJECT_DIR="$TESTROOT" "$HOOK" pre_bash); rc=$?
[ "$rc" -eq 0 ]      && ok "empty stdin: exits 0" || bad "empty stdin exit $rc"
[ "$(count)" = "0" ] && ok "empty stdin: no empty record spooled" || bad "spooled an empty record"

# --- large payload ----------------------------------------------------------
reset
big=$(python3 -c "import json;print(json.dumps({'session_id':'$SESSION','cwd':'$TESTROOT','tool_input':{'command':'x'*200000}}))")
(cd "$TESTROOT" && echo "$big" | CLAUDE_PROJECT_DIR="$TESTROOT" "$HOOK" pre_bash); rc=$?
[ "$rc" -eq 0 ]      && ok "200KB payload: exits 0" || bad "large payload exit $rc"
[ "$(count)" = "1" ] && ok "200KB payload: spooled whole" || bad "large payload not spooled"

# --- backpressure -----------------------------------------------------------
# A drop is ATTRITION. This used to snapshot the live data/drops/ stream and
# copy it back afterwards, which was itself a hazard -- a real drop landing
# between the snapshot and the restore would have been overwritten by the copy.
# In the sandbox the drop stream starts empty and belongs to this run alone, so
# the whole dance is gone and `dropped_before` is simply 0.
DROPFILE="$TESTROOT/data/drops/$(date -u '+%Y-%m-%d').jsonl"
dropcount(){ cat "$TESTROOT"/data/drops/*.jsonl 2>/dev/null | wc -l | tr -d ' '; }

reset
i=0; while [ $i -lt 501 ]; do echo '{}' > "$TESTROOT/spool/ready/filler__$i.json"; i=$((i+1)); done
before=$(count)
dropped_before=$(dropcount)
(cd "$TESTROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$TESTROOT" "$HOOK" pre_bash); rc=$?
after=$(count)
dropped_after=$(dropcount)
[ "$rc" -eq 0 ]            && ok "backpressure: exits 0" || bad "backpressure exit $rc"
[ "$before" = "$after" ]   && ok "backpressure: stops writing past the cap" || bad "wrote past cap ($before -> $after)"
# JEV-33: a refusal used to be silent, so the lost capture never reached the
# attrition count the pre-registration commits to reporting.
[ "$dropped_after" -eq $((dropped_before + 1)) ] \
  && ok "backpressure: the drop is recorded durably" \
  || bad "drop not recorded ($dropped_before -> $dropped_after)"
if tail -1 "$DROPFILE" 2>/dev/null | grep -q '"reason":"spool_backpressure"'; then
  ok "backpressure: drop row names its reason and surface"
else
  bad "drop row malformed: $(tail -1 "$DROPFILE" 2>/dev/null)"
fi
reset

# --- recursion guard --------------------------------------------------------
# The cc_* arms spawn `claude -p`. Without this guard that session would fire
# these hooks and feed its own decisions back into the dataset.
reset
(cd "$TESTROOT" && echo "$PAYLOAD" | JEV_ARM_SUBPROCESS=1 CLAUDE_PROJECT_DIR="$TESTROOT" "$HOOK" pre_bash); rc=$?
[ "$rc" -eq 0 ]      && ok "arm subprocess: exits 0" || bad "arm subprocess exit $rc"
[ "$(count)" = "0" ] && ok "arm subprocess: captures nothing (no feedback loop)" || bad "captured from an arm subprocess"

# --- missing logs/ (fail-open on a fresh checkout) ---------------------------
# logs/ is gitignored, so it is absent on a clone. If the stderr redirect ran
# before the trap was installed, the hook would exit non-zero here.
reset
mv "$TESTROOT/logs" "$TESTROOT/logs.bak" 2>/dev/null
(cd "$TESTROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$TESTROOT" "$HOOK" pre_bash) >/dev/null 2>&1; rc=$?
captured=$(count)
mv "$TESTROOT/logs.bak" "$TESTROOT/logs" 2>/dev/null
[ "$rc" -eq 0 ]        && ok "no logs/ dir: still exits 0" || bad "no logs/ dir exit $rc"
[ "$captured" = "1" ]  && ok "no logs/ dir: still captures" || bad "no logs/ dir captured $captured"
reset

# --- latency budget ---------------------------------------------------------
# Best of three, which is not the usual excuse for a flaky test. The subject is
# a fixed cost -- the same script, the same spawns, every time -- while the
# observation window is shared with every other process on the machine, and
# this suite now runs the hook a few hundred times in a row (the mutation
# driver runs it ten times over). One clean window is conclusive evidence about
# the hook; a dirty one is evidence about the machine. Same reasoning as GATE
# 1f in gates.sh.
best=""
attempt=1
while [ "$attempt" -le 3 ]; do
  reset
  start=$(python3 -c 'import time;print(time.time())')
  i=0; while [ $i -lt 30 ]; do (cd "$TESTROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$TESTROOT" "$HOOK" pre_bash); i=$((i+1)); done
  end=$(python3 -c 'import time;print(time.time())')
  ms=$(python3 -c "print(f'{($end-$start)/30*1000:.2f}')")
  best=$(python3 -c "print(min([$ms] + ([$best] if '$best' else [])))")
  [ "$(python3 -c "print(1 if $ms < 10 else 0)")" = "1" ] && break
  attempt=$((attempt+1))
done
[ "$(python3 -c "print(1 if $best < 10 else 0)")" = "1" ] \
  && ok "under 10ms budget (${best}ms incl. process spawn, best of $attempt)" \
  || bad "too slow: ${best}ms"
reset

# --- the test must not have touched the live collection window --------------
# Read-only, by design: this greps the real spool and the real capture rows for
# this run's unique session id. Anything found here is a capture that escaped
# the sandbox, which is the JEV-42 defect reappearing.
LEAKED=$( { grep -rl "$SESSION" "$ROOT/spool" 2>/dev/null; grep -rl "$SESSION" "$ROOT/data/captures" 2>/dev/null; } | wc -l | tr -d ' ')
[ "$LEAKED" = "0" ] && ok "ran entirely in its sandbox: no trace in the live spool or captures" \
                    || bad "wrote $LEAKED file(s) into the LIVE collection window"

echo "  -> $pass passed, $fail failed"
[ "$fail" -eq 0 ]
