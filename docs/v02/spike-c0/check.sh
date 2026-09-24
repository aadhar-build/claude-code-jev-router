#!/usr/bin/env bash
# Usage: ./check.sh [expected_agentType] [expected_model_prefix|-]
# Prints only ids/types/models/efforts/counts - never prompt or message text.
HERE="$(cd "$(dirname "$0")" && pwd)"
command -v jq >/dev/null || { echo "jq required"; exit 2; }
EXP_TYPE="${1:-}"; EXP_MODEL="${2:--}"
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
enc() { printf '%s' "$1" | sed 's/[^A-Za-z0-9]/-/g'; }
sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -c1-12; }

# Candidate encoded project dirs: physical and logical path (macOS /tmp -> /private/tmp), or override.
cands=()
if [ -n "${SPIKE_PROJECT_DIR_NAME:-}" ]; then cands+=("$CFG/projects/$SPIKE_PROJECT_DIR_NAME")
else
  cands+=("$CFG/projects/$(enc "$(cd "$HERE" && pwd -P)")")
  cands+=("$CFG/projects/$(enc "$(cd "$HERE" && pwd)")")
fi
PROJ=""; for c in "${cands[@]}"; do [ -d "$c" ] && { PROJ="$c"; break; }; done
echo "spike dir      : $HERE"
echo "hook script sha: $(sha "$HERE/probe/rewrite_probe.sh")   gp-lite.md sha: $(sha "$HERE/.claude/agents/gp-lite.md")"
echo ".probe-off     : $([ -e "$HERE/.probe-off" ] && echo PRESENT || echo absent)"
if [ -z "$PROJ" ]; then
  echo "project dir not found; tried: ${cands[*]}"; echo "FAIL (no transcripts: was claude started from this directory?)"; exit 1
fi
echo "project dir    : $PROJ"

files=("$PROJ"/*/subagents/agent-*.meta.json)
if [ ! -e "${files[0]}" ]; then echo "subagent metas : 0"; echo "FAIL (no subagent was spawned)"; exit 1; fi
echo "subagent metas : ${#files[@]}"
sorted=( $(ls -t "${files[@]}") )

show() { # meta path -> prints "type model effort" 
  local m="$1" j="${1%.meta.json}.jsonl" t mo ef
  t="$(jq -r '.agentType // "?"' "$m" 2>/dev/null)"
  if [ -f "$j" ]; then
    read -r mo ef < <(jq -r 'select(.type=="assistant") | "\(.message.model // "?") \(.effort // "null")"' "$j" 2>/dev/null | head -1)
  fi
  echo "${t} ${mo:-?} ${ef:-?}"
}
echo "--- newest 3 subagents (agentType  first-assistant-model  effort-field)"
i=0; for m in "${sorted[@]}"; do i=$((i+1)); [ $i -le 3 ] || break
  echo "  #$i $(basename "${m%.meta.json}")  $(show "$m")"; done
read -r T MO EF <<<"$(show "${sorted[0]}")"
echo "--- newest: agentType=$T model=$MO effort=$EF"
[ -f "$HERE/probe/probe.log" ] && { echo "--- probe.log (last 3)"; tail -3 "$HERE/probe/probe.log"; } || echo "--- probe.log: none (hook never ran)"

ok=1
[ -n "$EXP_TYPE" ] && [ "$T" != "$EXP_TYPE" ] && { echo "  type mismatch: want $EXP_TYPE got $T"; ok=0; }
if [ "$EXP_MODEL" != "-" ]; then case "$MO" in "$EXP_MODEL"*) ;; *) echo "  model mismatch: want prefix $EXP_MODEL got $MO"; ok=0;; esac; fi
[ $ok = 1 ] && { echo PASS; exit 0; } || { echo FAIL; exit 1; }
