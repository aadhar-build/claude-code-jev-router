#!/usr/bin/env bash
# Spike C0 probe. PreToolUse hook on Agent. ALWAYS exits 0 (fail-safe).
# Rewrites subagent_type general-purpose/absent -> gp-lite ONLY when no model is set.
# Never logs prompt text. Needs bash + jq.
trap 'exit 0' EXIT
set +e

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(dirname "$HERE")}"
LOG="${PROBE_LOG:-$ROOT/probe/probe.log}"
TARGET="gp-lite"

log() { # decision orig new tool_use_id
  printf '%s decision=%s orig=%s new=%s tool_use_id=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" "$4" >> "$LOG" 2>/dev/null
}
clean() { printf '%s' "$1" | tr -c 'A-Za-z0-9:_.-' '_' | cut -c1-64; }

INPUT="$(cat 2>/dev/null)"

if [ -e "$ROOT/.probe-off" ]; then
  log "off" "-" "-" "-"
  exit 0
fi
if ! command -v jq >/dev/null 2>&1; then
  log "skipped-nojq" "-" "-" "-"
  exit 0
fi
if [ -z "$INPUT" ] || ! printf '%s' "$INPUT" | jq -e '(.tool_input|type)=="object"' >/dev/null 2>&1; then
  log "skipped-malformed" "-" "-" "-"
  exit 0
fi

ORIG="$(printf '%s' "$INPUT" | jq -r '.tool_input.subagent_type // ""' 2>/dev/null)"
HASMODEL="$(printf '%s' "$INPUT" | jq -r '(.tool_input.model // "") | if . == "" then "no" else "yes" end' 2>/dev/null)"
TUID="$(printf '%s' "$INPUT" | jq -r '.tool_use_id // "-"' 2>/dev/null)"
CORIG="$(clean "${ORIG:-<absent>}")"
CTUID="$(clean "$TUID")"

if [ "$ORIG" != "" ] && [ "$ORIG" != "general-purpose" ]; then
  log "skipped-type" "$CORIG" "-" "$CTUID"
  exit 0
fi
if [ "$HASMODEL" != "no" ]; then
  log "skipped-model-set" "$CORIG" "-" "$CTUID"
  exit 0
fi

OUT="$(printf '%s' "$INPUT" | jq -c --arg t "$TARGET" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"allow",permissionDecisionReason:"spike-c0: rewrite subagent_type",updatedInput:(.tool_input + {subagent_type:$t})}}' 2>/dev/null)"
if [ -z "$OUT" ]; then
  log "skipped-jqfail" "$CORIG" "-" "$CTUID"
  exit 0
fi
log "rewrote" "$CORIG" "$TARGET" "$CTUID"
printf '%s\n' "$OUT"
exit 0
