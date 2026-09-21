#!/bin/bash
# JEV-60 critical-path cost, measured with tests/test_hook.sh's method:
# best of three windows, 30 spawns each, wall clock including process spawn.
REPO=/Users/aadharagarwal/projects/JEV-experiments/.claude/worktrees/jev-critical-path
cd "$REPO" || exit 1
mkdir -p logs
SB=$(mktemp -d "$REPO/logs/measure.XXXXXX") || exit 1
mkdir -p "$SB/spool/tmp" "$SB/spool/ready" "$SB/logs" "$SB/data" "$SB/.claude"
trap 'rm -rf "$SB"' EXIT
export HOME="$SB" JEV_HOME="$SB"
PAYLOAD='{"session_id":"measure","cwd":"'"$SB"'","tool_name":"Bash","tool_input":{"command":"ls"}}'

# The pre-fix hook, straight out of the last commit.
PREFIX="$SB/capture_prefix.sh"
git show HEAD:hooks/capture.sh > "$PREFIX" && chmod +x "$PREFIX"

ln -sfn "$SB" "$SB/self"

bench() { # label, hook, project_dir
  best=""
  for attempt in 1 2 3; do
    rm -f "$SB"/spool/ready/*.json 2>/dev/null
    start=$(python3 -c 'import time;print(time.time())')
    i=0; while [ $i -lt 30 ]; do
      (cd "$SB" && echo "$PAYLOAD" | CLAUDE_PROJECT_DIR="$3" "$2" pre_bash)
      i=$((i+1))
    done
    end=$(python3 -c 'import time;print(time.time())')
    ms=$(python3 -c "print(f'{($end-$start)/30*1000:.2f}')")
    best=$(python3 -c "print(min([$ms] + ([$best] if '$best' else [])))")
  done
  n=$(ls "$SB"/spool/ready/*.json 2>/dev/null | wc -l | tr -d ' ')
  echo "$1: ${best}ms   (captured $n of 30)"
}

bench "pre-fix  byte-match path " "$PREFIX" "$SB"
bench "post-fix byte-match path " "$REPO/hooks/capture.sh" "$SB"
bench "post-fix resolved (symlink)" "$REPO/hooks/capture.sh" "$SB/self"
bench "post-fix trailing slash   " "$REPO/hooks/capture.sh" "$SB/"
bench "pre-fix  symlink (dropped)" "$PREFIX" "$SB/self"
