#!/bin/bash
# Seam 1: the hook's process boundary.
#
# Feed a recorded payload on stdin; assert on exit code, stdout, and the files
# that appear in the spool. No network, no Python, no running Claude Code.
#
# The hook's contract is narrow and absolute: exit 0 always, stdout empty always
# (Claude Code parses it, and a stray byte there is a permission decision we
# never intended to make), and never lose or half-write a record.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/hooks/capture.sh"
PAYLOAD='{"session_id":"test","cwd":"'"$ROOT"'","tool_name":"Bash","tool_input":{"command":"ls"}}'

pass=0; fail=0
ok()   { echo "  ok    $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL  $1"; fail=$((fail+1)); }
reset(){ rm -f "$ROOT"/spool/ready/*.json "$ROOT"/spool/tmp/* 2>/dev/null; }
count(){ ls "$ROOT"/spool/ready/*.json 2>/dev/null | wc -l | tr -d ' '; }

echo "seam 1: hook process boundary"

# --- happy path -------------------------------------------------------------
reset
out=$(cd "$ROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash)
rc=$?
[ "$rc" -eq 0 ]        && ok "exits 0" || bad "exit code was $rc"
[ -z "$out" ]          && ok "stdout is empty" || bad "stdout was: $out"
[ "$(count)" = "1" ]   && ok "one record spooled" || bad "spooled $(count) records"

name=$(basename "$(ls "$ROOT"/spool/ready/*.json)")
case "$name" in pre_bash__*) ok "surface encoded in filename" ;; *) bad "bad name: $name" ;; esac
if [ -z "$(ls -A "$ROOT/spool/tmp" 2>/dev/null)" ]; then ok "staging dir left clean"; else bad "staging dir not clean"; fi
if grep -q '"session_id":"test"' "$ROOT"/spool/ready/*.json; then ok "payload stored verbatim"; else bad "payload altered"; fi

# --- kill switch ------------------------------------------------------------
reset
touch "$ROOT/.jev-disabled"
(cd "$ROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash); rc=$?
rm -f "$ROOT/.jev-disabled"
[ "$rc" -eq 0 ]      && ok "kill switch: exits 0" || bad "kill switch exit $rc"
[ "$(count)" = "0" ] && ok "kill switch: nothing captured" || bad "captured despite kill switch"

# --- cwd guard --------------------------------------------------------------
reset
(cd /tmp && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash); rc=$?
[ "$rc" -eq 0 ]      && ok "cwd guard: exits 0" || bad "cwd guard exit $rc"
[ "$(count)" = "0" ] && ok "cwd guard: nothing captured outside the folder" || bad "captured from outside cwd"

# --- missing CLAUDE_PROJECT_DIR --------------------------------------------
reset
(cd "$ROOT" && echo "$PAYLOAD" | env -u CLAUDE_PROJECT_DIR "$HOOK" pre_bash); rc=$?
[ "$rc" -eq 0 ]      && ok "no project dir: exits 0" || bad "no project dir exit $rc"
[ "$(count)" = "0" ] && ok "no project dir: nothing captured" || bad "captured without project dir"

# --- unwritable spool (fail-open) ------------------------------------------
reset
chmod 500 "$ROOT/spool/tmp"
(cd "$ROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash) >/dev/null 2>&1; rc=$?
chmod 700 "$ROOT/spool/tmp"
[ "$rc" -eq 0 ] && ok "unwritable spool: still exits 0 (fails open)" || bad "unwritable spool exit $rc"

# --- empty stdin ------------------------------------------------------------
reset
(cd "$ROOT" && printf '' | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash); rc=$?
[ "$rc" -eq 0 ]      && ok "empty stdin: exits 0" || bad "empty stdin exit $rc"
[ "$(count)" = "0" ] && ok "empty stdin: no empty record spooled" || bad "spooled an empty record"

# --- large payload ----------------------------------------------------------
reset
big=$(python3 -c "import json;print(json.dumps({'session_id':'test','cwd':'$ROOT','tool_input':{'command':'x'*200000}}))")
(cd "$ROOT" && echo "$big" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash); rc=$?
[ "$rc" -eq 0 ]      && ok "200KB payload: exits 0" || bad "large payload exit $rc"
[ "$(count)" = "1" ] && ok "200KB payload: spooled whole" || bad "large payload not spooled"

# --- backpressure -----------------------------------------------------------
reset
i=0; while [ $i -lt 501 ]; do echo '{}' > "$ROOT/spool/ready/filler__$i.json"; i=$((i+1)); done
before=$(count)
(cd "$ROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash); rc=$?
after=$(count)
[ "$rc" -eq 0 ]            && ok "backpressure: exits 0" || bad "backpressure exit $rc"
[ "$before" = "$after" ]   && ok "backpressure: stops writing past the cap" || bad "wrote past cap ($before -> $after)"
reset

# --- latency budget ---------------------------------------------------------
start=$(python3 -c 'import time;print(time.time())')
i=0; while [ $i -lt 30 ]; do (cd "$ROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash); i=$((i+1)); done
end=$(python3 -c 'import time;print(time.time())')
ms=$(python3 -c "print(f'{($end-$start)/30*1000:.2f}')")
under=$(python3 -c "print(1 if $ms < 10 else 0)")
[ "$under" = "1" ] && ok "under 10ms budget (${ms}ms incl. process spawn)" || bad "too slow: ${ms}ms"
reset

echo "  -> $pass passed, $fail failed"
[ "$fail" -eq 0 ]
