#!/usr/bin/env bash
# Offline selftest: no Claude session, no network. Needs bash + jq.
HERE="$(cd "$(dirname "$0")" && pwd)"
command -v jq >/dev/null || { echo "jq required"; exit 2; }
T="$(mktemp -d "${TMPDIR:-/tmp}/spikeC0.XXXXXX")"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/probe"
export CLAUDE_PROJECT_DIR="$T" PROBE_LOG="$T/probe/probe.log"
H="$HERE/probe/rewrite_probe.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "PASS  $1"; }
bad() { fail=$((fail+1)); echo "FAIL  $1  ($2)"; }
run() { printf '%s' "$1" | bash "$H"; echo "rc=$?" >"$T/rc"; }
rc() { sed 's/rc=//' "$T/rc"; }
mk() { jq -cn --argjson ti "$1" '{hook_event_name:"PreToolUse",tool_name:"Agent",tool_use_id:"toolu_TEST",tool_input:$ti}'; }
FULL='{"description":"d","prompt":"SECRET_PROMPT_TEXT","subagent_type":"general-purpose","run_in_background":true,"extra":{"a":[1,2]}}'

# 1 rewrite, all other fields preserved
O="$(run "$(mk "$FULL")")"
[ "$(rc)" = 0 ] && [ "$(echo "$O" | jq -r '.hookSpecificOutput.updatedInput.subagent_type')" = gp-lite ] \
 && [ "$(echo "$O" | jq -c '.hookSpecificOutput.updatedInput|del(.subagent_type)')" = "$(echo "$FULL" | jq -c 'del(.subagent_type)')" ] \
 && [ "$(echo "$O" | jq -r '.hookSpecificOutput.permissionDecision')" = allow ] \
 && [ "$(echo "$O" | jq -r '.hookSpecificOutput.hookEventName')" = PreToolUse ] \
 && ok "1 general-purpose, no model -> gp-lite, other fields preserved" || bad "1" "$O"
# 2 absent subagent_type
O="$(run "$(mk '{"description":"d","prompt":"p"}')")"
[ "$(echo "$O" | jq -r '.hookSpecificOutput.updatedInput.subagent_type')" = gp-lite ] && [ "$(echo "$O" | jq -r '.hookSpecificOutput.updatedInput.prompt')" = p ] \
 && ok "2 absent subagent_type -> gp-lite" || bad "2" "$O"
# 3 explicit model
O="$(run "$(mk '{"description":"d","prompt":"p","subagent_type":"general-purpose","model":"opus"}')")"
[ -z "$O" ] && [ "$(rc)" = 0 ] && ok "3 explicit model -> untouched" || bad "3" "$O"
# 4 other types
n=0; for ty in Explore my-agent my-plugin:reviewer fork; do
  O="$(run "$(mk "{\"description\":\"d\",\"prompt\":\"p\",\"subagent_type\":\"$ty\"}")")"; [ -z "$O" ] && [ "$(rc)" = 0 ] && n=$((n+1)); done
[ $n = 4 ] && ok "4 Explore/custom/plugin-namespaced/fork -> untouched" || bad "4" "only $n/4 untouched"
# 5 .probe-off
touch "$T/.probe-off"
O="$(run "$(mk "$FULL")")"; [ -z "$O" ] && [ "$(rc)" = 0 ] && ok "5 .probe-off -> untouched" || bad "5" "$O"
rm -f "$T/.probe-off"
# 6 malformed/empty
n=0; for bad_in in "" "not json" '{"tool_input":"str"}' '{"a":1}' '[1,2'; do
  O="$(run "$bad_in")"; [ -z "$O" ] && [ "$(rc)" = 0 ] && n=$((n+1)); done
[ $n = 5 ] && ok "6 malformed/empty stdin -> exit 0, no output" || bad "6" "only $n/5"
# log hygiene
if grep -q SECRET_PROMPT_TEXT "$PROBE_LOG"; then bad "log" "prompt text leaked"; else ok "log contains no prompt text ($(wc -l <"$PROBE_LOG" | tr -d ' ') lines)"; fi
echo "--- probe.log sample"; head -4 "$PROBE_LOG"
echo "passed=$pass failed=$fail"; [ $fail = 0 ]
