#!/bin/bash
# Scratch reproduction for JEV-60. Not part of the suite.
REPO=/Users/aadharagarwal/projects/JEV-experiments/.claude/worktrees/jev-critical-path
R=$(mktemp -d /tmp/jevrepro.XXXX)
trap 'rm -rf "$R"' EXIT
mkdir -p "$R/spool/tmp" "$R/spool/ready" "$R/logs" "$R/data" "$R/.claude"
P='{"session_id":"s1","tool_input":{"command":"ls"}}'
export HOME="$R" JEV_HOME="$R"
count(){ ls "$R"/spool/ready/*.json 2>/dev/null | wc -l | tr -d ' '; }
RP=$(cd "$R" && pwd -P)
echo "ROOT=$R  resolved=$RP"
echo "--- control (byte-identical root, cwd=root)"
( cd "$R" && echo "$P" | CLAUDE_PROJECT_DIR="$R" bash "$REPO/hooks/capture.sh" pre_bash ); echo "rc=$? spooled=$(count)"
rm -f "$R"/spool/ready/*.json
echo "--- trailing slash CLAUDE_PROJECT_DIR"
( cd "$R" && echo "$P" | CLAUDE_PROJECT_DIR="$R/" bash "$REPO/hooks/capture.sh" pre_bash ); echo "rc=$? spooled=$(count)"
rm -f "$R"/spool/ready/*.json
echo "--- symlinked: cwd is the physical path, CLAUDE_PROJECT_DIR the symlinked one"
( cd "$RP" && echo "$P" | CLAUDE_PROJECT_DIR="$R" bash "$REPO/hooks/capture.sh" pre_bash ); echo "rc=$? spooled=$(count)"
echo "--- any record of the drops?"
ls -R "$R/data" 2>/dev/null; cat "$R"/logs/capture.err 2>/dev/null
echo "--- inline shadow, symlinked"
( cd "$RP" && echo '{"session_id":"s1","tool_use_id":"t","cwd":"'"$RP"'","tool_input":{"command":"ls"}}' | JEV_INLINE_RUN_CONTEXT=test CLAUDE_PROJECT_DIR="$R" bash "$REPO/hooks/inline_shadow_bash.sh" ); echo "rc=$?"
ls -R "$R/data" 2>/dev/null
echo "SANDBOX=$R"
