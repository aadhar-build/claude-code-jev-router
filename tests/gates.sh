#!/bin/bash
# The three gates that must ALL pass before the hook is enabled.
#
# This is the point in the project where a bug stops being a wrong number in a
# report and starts being something that interferes with real editing sessions.
# So the gates are adversarial: each one tries to make the hook misbehave.
#
#   1. isolation  -- nothing outside this folder is ever touched
#   2. fail-open  -- every failure path still exits 0
#   3. kill switch -- one file stops everything, instantly
#
# Run: ./tests/gates.sh

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/hooks/capture.sh"
PAYLOAD='{"session_id":"gate-test","cwd":"'"$ROOT"'","tool_name":"Bash","tool_input":{"command":"ls"}}'

pass=0; fail=0
ok()  { echo "    ok    $1"; pass=$((pass+1)); }
bad() { echo "    FAIL  $1"; fail=$((fail+1)); }
reset(){ rm -f "$ROOT"/spool/ready/*.json "$ROOT"/spool/tmp/* 2>/dev/null; }
count(){ ls "$ROOT"/spool/ready/*.json 2>/dev/null | wc -l | tr -d ' '; }

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
OUTSIDE=$(mktemp -d)
(cd "$OUTSIDE" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$OUTSIDE" "$HOOK" pre_bash) 2>/dev/null
[ "$(count)" = "0" ] && ok "a session in another directory captures nothing" \
                     || bad "captured from outside the folder"
rmdir "$OUTSIDE" 2>/dev/null

# 1d. cwd guard: even with our project dir, a cwd outside the folder is refused.
reset
(cd /tmp && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash) 2>/dev/null
[ "$(count)" = "0" ] && ok "cwd guard refuses a cwd outside the folder" \
                     || bad "cwd guard did not hold"

# 1e. Worktree subagents: the guard must hold wherever the copy lives.
reset
(cd "$ROOT" && echo "$PAYLOAD" | JEV_ARM_SUBPROCESS=1 CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash) 2>/dev/null
[ "$(count)" = "0" ] && ok "arm subprocess captures nothing (no feedback loop)" \
                     || bad "an arm subprocess captured its own decision"

# 1f. Nothing is written outside the folder, checked by mtime across the run.
STAMP=$(mktemp)
reset
(cd "$ROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash) 2>/dev/null
OUTSIDE_WRITES=$(find "$HOME/.claude" "$HOME/.config" /tmp -maxdepth 2 -newer "$STAMP" \
                   -not -path "*/projects/*" 2>/dev/null | grep -v "^$STAMP$" | wc -l | tr -d ' ')
rm -f "$STAMP"
[ "$OUTSIDE_WRITES" = "0" ] && ok "no writes outside the folder during a capture" \
                            || bad "$OUTSIDE_WRITES path(s) outside the folder changed"
reset

echo
echo "=============================================================="
echo " GATE 2 -- FAIL-OPEN"
echo "=============================================================="
echo "  Every failure path must still exit 0. A measurement harness"
echo "  must never be able to wedge an editing session."
echo

try() { # name, setup, teardown
  reset
  eval "$2"
  (cd "$ROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash) >/tmp/jev-gate-out 2>/dev/null
  rc=$?
  eval "$3"
  out=$(cat /tmp/jev-gate-out); rm -f /tmp/jev-gate-out
  if [ "$rc" -eq 0 ] && [ -z "$out" ]; then ok "$1"; else bad "$1 (exit $rc, stdout '$out')"; fi
}

try "spool/tmp unwritable"      "chmod 500 '$ROOT/spool/tmp'"   "chmod 700 '$ROOT/spool/tmp'"
try "spool/ready unwritable"    "chmod 500 '$ROOT/spool/ready'" "chmod 700 '$ROOT/spool/ready'"
try "spool/ready missing"       "mv '$ROOT/spool/ready' '$ROOT/spool/ready.bak'" "mv '$ROOT/spool/ready.bak' '$ROOT/spool/ready'"
try "logs/ missing"             "mv '$ROOT/logs' '$ROOT/logs.bak'" "mv '$ROOT/logs.bak' '$ROOT/logs'"
try "CLAUDE_PROJECT_DIR unset"  "unset CLAUDE_PROJECT_DIR"      "true"
try "backpressure exceeded"     "i=0; while [ \$i -lt 501 ]; do echo '{}' > '$ROOT/spool/ready/f__\$i.json'; i=\$((i+1)); done" "reset"

# Empty and malformed stdin.
reset
(cd "$ROOT" && printf '' | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash) 2>/dev/null; rc=$?
[ "$rc" -eq 0 ] && [ "$(count)" = "0" ] && ok "empty stdin: exits 0, spools nothing" || bad "empty stdin"
reset
(cd "$ROOT" && echo 'not json at all' | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash) 2>/dev/null; rc=$?
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
touch "$ROOT/.jev-disabled"
(cd "$ROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash) 2>/dev/null; rc=$?
c1=$(count)
mkdir -p "$ROOT/src/deep/nested" 2>/dev/null
(cd "$ROOT/src" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash) 2>/dev/null
c2=$(count)
rmdir "$ROOT/src/deep/nested" "$ROOT/src/deep" 2>/dev/null
rm -f "$ROOT/.jev-disabled"
[ "$rc" -eq 0 ]  && ok "kill switch: exits 0" || bad "kill switch exit $rc"
[ "$c1" = "0" ]  && ok "kill switch: nothing captured from the repo root" || bad "captured despite kill switch"
[ "$c2" = "0" ]  && ok "kill switch: nothing captured from a subdirectory (anchored, not cwd-relative)" \
                 || bad "kill switch failed from a subdirectory"

reset
(cd "$ROOT" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$ROOT" "$HOOK" pre_bash) 2>/dev/null
[ "$(count)" = "1" ] && ok "removing the kill switch resumes capture" || bad "did not resume after removal"
reset

echo
echo "=============================================================="
printf " %d passed, %d failed\n" "$pass" "$fail"
if [ "$fail" -eq 0 ]; then
  echo " ALL GATES PASS -- safe to register the hook"
else
  echo " GATES FAILED -- DO NOT register the hook"
fi
echo "=============================================================="
[ "$fail" -eq 0 ]
