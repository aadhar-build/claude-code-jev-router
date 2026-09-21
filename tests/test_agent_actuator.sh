#!/bin/bash
# JEV-35 / W1: the static floor, at the hook's process boundary.
#
# This is the seam that matters. `src/tier_map.py` can be unit-tested into a
# corner and still be wrong about the thing that ships, because what ships is a
# bash script that has to parse a payload, echo it back byte-faithfully, write a
# ledger, and emit exactly one line of JSON on a file descriptor Claude Code
# reads as a permission decision. Everything below feeds the REAL
# hooks/agent_route_actuator.sh on stdin and asserts on exit code, on the exact
# bytes of stdout, and on the files that appear.
#
# SANDBOXED, for the reason PREREGISTRATION.md Amendment 6 records: this suite
# runs while a collection window is open. Every invocation points
# CLAUDE_PROJECT_DIR and HOME at a throwaway root under logs/ (gitignored,
# inside the folder, removed on exit). The hook derives every path it touches
# from $CLAUDE_PROJECT_DIR and $HOME and has no other anchor, so the behaviour
# under test is identical and an escape into the live tree is a visible failure
# rather than the expected outcome.
#
# No network. No API key. No Jev call. The static floor makes none.

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
HOOK="${JEV_TEST_ACTUATOR:-$ROOT/hooks/agent_route_actuator.sh}"

mkdir -p "$ROOT/logs"
SANDBOX="$(mktemp -d "$ROOT/logs/actuatortest.XXXXXX")" || exit 1
# pwd -P: on macOS /tmp is a symlink and the hook's cwd guard compares "$PWD/"
# against "$ROOT"/*. An unresolved path makes every invocation exit on the cwd
# guard, which would make every assertion below trivially pass.
SANDBOX="$(cd "$SANDBOX" && pwd -P)"
cleanup() { chmod -R u+rwX "$SANDBOX" 2>/dev/null; rm -rf "$SANDBOX"; }
trap cleanup EXIT

mkdir -p "$SANDBOX/config" "$SANDBOX/logs" "$SANDBOX/data" "$SANDBOX/.claude"
cp "$ROOT/config/tiers.json" "$SANDBOX/config/tiers.json"

AR="$SANDBOX/data/agent_route"
LEDGERS="$AR/assignments"
BREAKER="$AR/breaker.jsonl"
MARKER="$AR/BREAKER-OPEN"

pass=0; fail=0
ok()  { echo "  ok    $1"; pass=$((pass+1)); }
bad() { echo "  FAIL  $1"; fail=$((fail+1)); }

reset() { rm -rf "$AR"; rm -rf "$SANDBOX/.claude/jev-disabled" "$SANDBOX/.jev-disabled"; }

# Build a PreToolUse/Agent payload. Shape verified against 202 real Agent
# tool_use blocks in ~/.claude/projects.
mkpayload() { # <subagent_type> [extra json fragment]
  local st="$1" extra="$2"
  printf '{"session_id":"s1","tool_use_id":"toolu_01","hook_event_name":"PreToolUse","cwd":"%s","permission_mode":"auto","tool_name":"Agent","tool_input":{"prompt":"Audit every call site of drain_once.","description":"audit drain_once","subagent_type":"%s","run_in_background":false%s}}' \
    "$SANDBOX" "$st" "$extra"
}

# Run the hook exactly as Claude Code would: payload on stdin, cwd inside the
# project, CLAUDE_PROJECT_DIR set. Captures stdout verbatim into $OUT.
run() { # <payload> [env assignments...]
  local p="$1"; shift
  OUT="$(cd "$SANDBOX" && printf '%s' "$p" | env CLAUDE_PROJECT_DIR="$SANDBOX" JEV_HOME="$SANDBOX" HOME="$SANDBOX" "$@" "$HOOK")"
  RC=$?
}

# The resolved tool input, as src/hook_dispatch.py defines byte-identity:
# json.dumps(sort_keys=True, separators=(",",":")) of the surviving object.
updated() { printf '%s' "$OUT" | python3 -c 'import json,sys
d=json.load(sys.stdin)
print(json.dumps(d["hookSpecificOutput"]["updatedInput"],sort_keys=True,separators=(",",":")))' 2>/dev/null; }

ledger_field() { # <key>
  python3 -c 'import json,sys,glob
rows=[json.loads(l) for f in sorted(glob.glob(sys.argv[1]+"/*.jsonl")) for l in open(f) if l.strip()]
print(rows[-1].get(sys.argv[2]) if rows else "NOROWS")' "$LEDGERS" "$1" 2>/dev/null
}
ledger_count() { cat "$LEDGERS"/*.jsonl 2>/dev/null | grep -c . | tr -d ' '; }

echo "JEV-35 / W1: the static floor at the hook's process boundary"
echo "  sandbox: ${SANDBOX#$ROOT/}"

echo
echo "  0. IT PARSES AT ALL"
# Not a formality. The jq programs are embedded as SINGLE-QUOTED shell strings,
# so one apostrophe in a jq comment silently ends the string and turns the rest
# of the program into shell. That bug is invisible from the outside: `trap 'exit
# 0' EXIT` means the hook still exits 0 and still emits nothing, which is
# exactly what a correctly-behaving no-rule decision looks like. It happened
# once during development and was caught only by reading stderr.
bash -n "$HOOK" 2>/dev/null \
  && ok "the hook is syntactically valid bash (an apostrophe inside an embedded jq program would fail here, and nowhere else)" \
  || bad "the hook does not parse as bash: $(bash -n "$HOOK" 2>&1 | head -2)"

# ---------------------------------------------------------------------------
echo
echo "  1. THE HAPPY PATH -- a rule fires and the tier is rewritten"
# ---------------------------------------------------------------------------
reset
run "$(mkpayload Explore)"
[ "$RC" -eq 0 ] && ok "exits 0" || bad "exit code was $RC"
printf '%s' "$OUT" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null \
  && ok "stdout is exactly one well-formed JSON object" \
  || bad "stdout is not parseable JSON: [$OUT]"
[ "$(printf '%s' "$OUT" | grep -c .)" = "1" ] \
  && ok "stdout is ONE line -- no subprocess leaked a byte onto the decision fd" \
  || bad "stdout was $(printf '%s' "$OUT" | grep -c .) lines"
case "$(updated)" in
  *'"model":"haiku"'*) ok "Explore -> haiku (the ALIAS, which is what the Agent tool accepts)" ;;
  *) bad "Explore did not become haiku: $(updated)" ;;
esac
case "$OUT" in
  *'"permissionDecision":"allow"'*) ok "emits permissionDecision allow" ;;
  *) bad "no permissionDecision allow in [$OUT]" ;;
esac

# ---------------------------------------------------------------------------
echo
echo "  2. THE INPUT-FIDELITY GATE -- updatedInput replaces the ENTIRE object"
# ---------------------------------------------------------------------------
# A hook that drops `subagent_type` spawns a subagent of the WRONG TYPE, and
# that failure is indistinguishable in the results from a routing-quality
# effect. So this is asserted field by field, including a field the hook has
# never heard of.
reset
run "$(mkpayload Explore ',"weird_future_field":{"a":[1,2,3]}')"
fid=$(printf '%s' "$OUT" | python3 -c 'import json,sys
got=json.load(sys.stdin)["hookSpecificOutput"]["updatedInput"]
van=json.loads(sys.argv[1])["tool_input"]
missing=[k for k in van if k not in got]
changed=[k for k in van if k!="model" and k in got and got[k]!=van[k]]
print("|".join(["missing:"+k for k in missing]+["changed:"+k for k in changed]))' \
  "$(mkpayload Explore ',"weird_future_field":{"a":[1,2,3]}')" 2>/dev/null)
[ -z "$fid" ] \
  && ok "every field the caller sent is echoed back unchanged (prompt, description, subagent_type, run_in_background, and an unknown field)" \
  || bad "updatedInput dropped or altered: $fid"
case "$(updated)" in
  *'"subagent_type":"Explore"'*) ok "subagent_type specifically survives -- the field whose loss is indistinguishable from a routing effect" ;;
  *) bad "subagent_type missing from updatedInput" ;;
esac
case "$(updated)" in
  *'"weird_future_field":{"a":[1,2,3]}'*) ok "a field the hook has never heard of survives (right-biased merge, not a field list)" ;;
  *) bad "unknown field dropped" ;;
esac

# ---------------------------------------------------------------------------
echo
echo "  3. THE CEILING -- general-purpose is 65% of traffic and carries no signal"
# ---------------------------------------------------------------------------
reset
run "$(mkpayload general-purpose)"
[ "$RC" -eq 0 ] && ok "general-purpose: exits 0" || bad "exit code $RC"
[ -z "$OUT" ] \
  && ok "general-purpose: ZERO bytes on stdout -- the input is untouched, which IS the control arm" \
  || bad "general-purpose was rewritten: [$OUT]"
[ "$(ledger_field decision)" = "no_rule" ] \
  && ok "general-purpose: ledger records decision=no_rule (a rule that fired, mapping to nothing)" \
  || bad "ledger decision was $(ledger_field decision)"
case "$(ledger_field rule)" in
  *'tier=null (no routing signal)'*) ok "the ceiling is named in the row: tier=null, no routing signal" ;;
  *) bad "rule text does not name the null mapping: $(ledger_field rule)" ;;
esac

echo
echo "  3b. A MISS IS NOT AN ERROR -- an unmapped type is left alone, never escalated"
reset
run "$(mkpayload 'impeccable:impeccable-documenter')"
[ -z "$OUT" ] \
  && ok "an unmapped (plugin-namespaced) type is left untouched, NOT routed to frontier" \
  || bad "unmapped type was rewritten: [$OUT]"
[ "$(ledger_field decision)" = "no_rule" ] \
  && ok "unmapped type: decision=no_rule, and no breaker failure is recorded" \
  || bad "unmapped decision was $(ledger_field decision)"
# A miss DOES append an outcome line, and it must be a SUCCESS one: the rule
# table was read and evaluated, it simply had nothing to say. That success line
# is what closes a breaker after a transient fault, so it has to be written --
# what must never be written on a miss is a FAILURE.
grep -q '"ok":false' "$BREAKER" 2>/dev/null \
  && bad "a miss recorded a router FAILURE: $(cat "$BREAKER")" \
  || ok "a miss records a SUCCESS outcome, never a failure -- it cannot trip the breaker, and it can close one"

# ---------------------------------------------------------------------------
echo
echo "  4. THE CALLER'S OWN CHOICE WINS (explicit_model_action=keep)"
# ---------------------------------------------------------------------------
reset
run "$(mkpayload Explore ',"model":"opus"')"
[ -z "$OUT" ] \
  && ok "a caller who already asked for opus is not clobbered by the static map" \
  || bad "the map overrode an explicit caller choice: [$OUT]"
[ "$(ledger_field decision)" = "explicit_model_kept" ] \
  && ok "the kept choice is still recorded, so it stays attributable" \
  || bad "decision was $(ledger_field decision)"
[ "$(ledger_field original_model)" = "opus" ] \
  && ok "original_model is on the row" || bad "original_model=$(ledger_field original_model)"

echo
echo "  4b. ...and the override setting is honoured when an operator sets it"
reset
python3 -c 'import json,sys
p=sys.argv[1]; c=json.load(open(p)); c["explicit_model_action"]="override"
open(p,"w").write(json.dumps(c))' "$SANDBOX/config/tiers.json"
run "$(mkpayload Explore ',"model":"opus"')"
case "$(updated)" in
  *'"model":"haiku"'*) ok "explicit_model_action=override lets the map win, and it is configuration not code" ;;
  *) bad "override did not take effect: [$OUT]" ;;
esac
cp "$ROOT/config/tiers.json" "$SANDBOX/config/tiers.json"

# ---------------------------------------------------------------------------
echo
echo "  5. THE ASSIGNMENT LEDGER, WRITTEN BEFORE THE SPAWN"
# ---------------------------------------------------------------------------
# The hook is synchronous and the spawn cannot begin until it exits, so "the row
# exists when the hook exits" IS "the row exists before the spawn". What makes
# the ordering load-bearing rather than incidental is 5b: when the ledger cannot
# be written, NOTHING is rewritten.
reset
run "$(mkpayload Explore)"
[ "$(ledger_count)" = "1" ] \
  && ok "one ledger row exists by the time the hook exits, i.e. before the spawn" \
  || bad "ledger had $(ledger_count) rows"
for f in decision tier assigned_alias rule config_sha256 original_model timestamp session_id tool_use_id hook_ms; do
  v="$(ledger_field "$f")"
  [ -n "$v" ] && [ "$v" != "NOROWS" ] || bad "ledger row has no $f"
done
ok "the row carries the decision, the tier, the rule that fired, the config fingerprint and the original model"
[ "$(ledger_field config_sha256)" = "$(shasum -a 256 "$SANDBOX/config/tiers.json" | awk '{print $1}')" ] \
  && ok "config_sha256 is the real content hash of the rule table that produced the decision" \
  || bad "config_sha256 does not match the file"

echo
echo "  5b. NO RECORD, NO REWRITE -- an unwritable ledger leaves the input untouched"
reset
mkdir -p "$LEDGERS"
chmod 500 "$LEDGERS"
run "$(mkpayload Explore)"
chmod 700 "$LEDGERS"
[ "$RC" -eq 0 ] && ok "unwritable ledger: still exits 0 (fail safe is absolute)" || bad "exit $RC"
[ -z "$OUT" ] \
  && ok "unwritable ledger: emits NOTHING -- an unrecorded rewrite is exactly what the before-spawn gate forbids, and untouched is the control arm" \
  || bad "rewrote without being able to record it: [$OUT]"
grep -q 'ledger_write_failed' "$BREAKER" 2>/dev/null \
  && ok "unwritable ledger: counted as a router failure, so a sustained one opens the breaker" \
  || bad "no ledger_write_failed outcome recorded"

# ---------------------------------------------------------------------------
echo
echo "  6. FAIL TO FRONTIER -- and the line where it stops applying"
# ---------------------------------------------------------------------------
reset
mv "$SANDBOX/config/tiers.json" "$SANDBOX/config/tiers.json.away"
run "$(mkpayload Explore)"
[ "$RC" -eq 0 ] && ok "missing config: exits 0" || bad "exit $RC"
case "$(updated)" in
  *'"model":"opus"'*) ok "missing config: FAILS TO FRONTIER (opus), never to a cheap tier -- quality is protected on the error path" ;;
  *) bad "missing config did not fail to frontier: [$OUT]" ;;
esac
case "$(updated)" in
  *'"subagent_type":"Explore"'*) ok "missing config: the frontier rewrite is still byte-faithful -- every field echoed" ;;
  *) bad "the error path dropped a field: $(updated)" ;;
esac
[ "$(ledger_field decision)" = "fail_to_frontier" ] \
  && ok "missing config: the error is on the ledger, not silent" || bad "decision=$(ledger_field decision)"
grep -q '"ok":false' "$BREAKER" 2>/dev/null \
  && ok "missing config: counted as a router failure for the breaker" || bad "no failure outcome recorded"
mv "$SANDBOX/config/tiers.json.away" "$SANDBOX/config/tiers.json"

echo
echo "  6b. ...garbage config is the same story"
reset
printf 'this is not json at all' > "$SANDBOX/config/tiers.broken"
mv "$SANDBOX/config/tiers.json" "$SANDBOX/config/tiers.json.away"
mv "$SANDBOX/config/tiers.broken" "$SANDBOX/config/tiers.json"
run "$(mkpayload Explore)"
case "$(updated)" in
  *'"model":"opus"'*) ok "unparseable config: fails to frontier, fields intact" ;;
  *) bad "unparseable config: [$OUT]" ;;
esac
rm -f "$SANDBOX/config/tiers.json"
mv "$SANDBOX/config/tiers.json.away" "$SANDBOX/config/tiers.json"

echo
echo "  6c. THE OTHER SIDE OF THE LINE -- an unparseable PAYLOAD cannot fail to frontier"
# There is no faithful updatedInput to build from bytes that do not parse, and a
# partial object would spawn the wrong agent type. So the hook goes inert. This
# is fail-SAFE, and it is a different property from fail-to-frontier.
reset
run 'this is not json {{{'
[ "$RC" -eq 0 ] && ok "garbage stdin: exits 0" || bad "exit $RC"
[ -z "$OUT" ] \
  && ok "garbage stdin: ZERO bytes on stdout -- no partial updatedInput is ever constructed" \
  || bad "emitted something from garbage: [$OUT]"
reset
run '{"tool_name":"Agent","tool_input":"not-an-object"}'
[ -z "$OUT" ] && ok "tool_input that is not an object: zero bytes out" || bad "[$OUT]"
# The only case that reaches the unparseable_payload branch: pure garbage on
# stdin exits earlier, at the `tool_name` substring guard, and is not counted as
# a router failure because nothing was ever asked of the router.
grep -q 'unparseable_payload' "$BREAKER" 2>/dev/null \
  && ok "an Agent payload we cannot parse IS counted as a router failure, so a run of them opens the breaker rather than quietly disappearing" \
  || bad "no unparseable_payload outcome recorded: $(cat "$BREAKER" 2>/dev/null)"

# ---------------------------------------------------------------------------
echo
echo "  7. THE CIRCUIT BREAKER -- because fail-to-frontier does not protect cost"
# ---------------------------------------------------------------------------
reset
mkdir -p "$AR"
NOW=$(date +%s)
for i in 1 2 3; do
  printf '{"ts":%s,"ok":false,"error":"synthetic"}\n' "$((NOW - i))" >> "$BREAKER"
done
run "$(mkpayload Explore)"
[ "$RC" -eq 0 ] && ok "breaker open: exits 0" || bad "exit $RC"
case "$OUT" in
  *updatedInput*) bad "breaker open but the hook still rewrote: [$OUT]" ;;
  *) ok "breaker open: STOPS REWRITING ENTIRELY, input left untouched" ;;
esac
case "$OUT" in
  *'"systemMessage"'*'breaker OPEN'*) ok "breaker open: loudly visible to the user via systemMessage, the loudest channel a hook has" ;;
  *) bad "no systemMessage: [$OUT]" ;;
esac
[ -f "$MARKER" ] \
  && ok "breaker open: a sticky marker is left on disk, so the condition survives the session that caused it" \
  || bad "no BREAKER-OPEN marker"
[ "$(ledger_field decision)" = "breaker_open" ] \
  && ok "breaker open: still ledgered, so the suspension is attributable too" || bad "decision=$(ledger_field decision)"
[ "$(grep -c . "$BREAKER")" = "3" ] \
  && ok "breaker open: appends NOTHING -- otherwise the newest failure keeps moving and the TTL could never expire" \
  || bad "breaker log grew to $(grep -c . "$BREAKER") lines while open"

echo
echo "  7b. ...it survives a fresh process, because every hook invocation is one"
run "$(mkpayload Explore)"
case "$OUT" in
  *updatedInput*) bad "breaker state did not survive the process boundary" ;;
  *) ok "a second, entirely separate process reads the same open breaker off disk" ;;
esac

echo
echo "  7c. ...and closes itself: past the TTL the newest failure is stale (half-open)"
reset
mkdir -p "$AR"
OLD=$((NOW - 100000))
for i in 1 2 3; do
  printf '{"ts":%s,"ok":false,"error":"synthetic"}\n' "$((OLD - i))" >> "$BREAKER"
done
run "$(mkpayload Explore)"
case "$(updated)" in
  *'"model":"haiku"'*) ok "past the TTL: one attempt is allowed through and it routes normally" ;;
  *) bad "half-open did not let an attempt through: [$OUT]" ;;
esac
[ ! -f "$MARKER" ] && ok "a successful decision clears the sticky marker" || bad "marker survived a success"

echo
echo "  7d. ...a single success closes it -- N CONSECUTIVE failures, not N total"
reset
mkdir -p "$AR"
printf '{"ts":%s,"ok":false,"error":"x"}\n{"ts":%s,"ok":false,"error":"x"}\n{"ts":%s,"ok":true,"error":null}\n{"ts":%s,"ok":false,"error":"x"}\n' \
  "$((NOW-5))" "$((NOW-4))" "$((NOW-3))" "$((NOW-2))" >> "$BREAKER"
run "$(mkpayload Explore)"
case "$(updated)" in
  *'"model":"haiku"'*) ok "3 failures with a success among them does not open the breaker" ;;
  *) bad "breaker opened on non-consecutive failures: [$OUT]" ;;
esac

# ---------------------------------------------------------------------------
echo
echo "  8. TWO KILL SWITCHES, PROVEN ON THIS HOOK AND NOT INHERITED BY ASSUMPTION"
# ---------------------------------------------------------------------------
# This repo has already shipped a kill switch that stopped one writer and not
# the other. So each switch is exercised against THIS script, in all three
# fail-safe shapes, and the assertion is the strong one: not merely "it stopped
# logging" but "it stopped DECIDING".
for shape in file dir danglingsymlink; do
  reset
  case "$shape" in
    file) : > "$SANDBOX/.jev-disabled" ;;
    dir)  mkdir -p "$SANDBOX/.jev-disabled" ;;
    danglingsymlink) ln -s "$SANDBOX/nothing-here" "$SANDBOX/.jev-disabled" ;;
  esac
  run "$(mkpayload Explore)"
  [ -z "$OUT" ] && [ ! -d "$LEDGERS" ] \
    && ok "per-project switch as a $shape: the hook stops ROUTING, not merely logging" \
    || bad "per-project switch as a $shape did not stop the actuator: [$OUT]"
done

for shape in file dir danglingsymlink; do
  reset
  mkdir -p "$SANDBOX/.claude"
  case "$shape" in
    file) : > "$SANDBOX/.claude/jev-disabled" ;;
    dir)  mkdir -p "$SANDBOX/.claude/jev-disabled" ;;
    danglingsymlink) ln -s "$SANDBOX/.claude/nothing-here" "$SANDBOX/.claude/jev-disabled" ;;
  esac
  run "$(mkpayload Explore)"
  [ -z "$OUT" ] && [ ! -d "$LEDGERS" ] \
    && ok "global switch as a $shape: stops routing in every project at once" \
    || bad "global switch as a $shape did not stop the actuator: [$OUT]"
  rm -rf "$SANDBOX/.claude/jev-disabled"
done

reset
OUT="$(cd "$SANDBOX" && printf '%s' "$(mkpayload Explore)" | env -u HOME CLAUDE_PROJECT_DIR="$SANDBOX" JEV_HOME="$SANDBOX" "$HOOK")"
[ -z "$OUT" ] \
  && ok "an unset HOME reads as OFF -- a switch whose state cannot be established is never given the benefit of the doubt" \
  || bad "unset HOME still routed: [$OUT]"

# ---------------------------------------------------------------------------
echo
echo "  9. THE OTHER GUARDS"
# ---------------------------------------------------------------------------
reset
run "$(mkpayload Explore)" JEV_ARM_SUBPROCESS=1
[ -z "$OUT" ] && ok "JEV_ARM_SUBPROCESS: an arm's own \`claude -p\` session is not routed by the actuator under measurement" \
              || bad "recursion guard failed: [$OUT]"
reset
run "$(mkpayload Explore)" JEV_GRADER=1
[ -z "$OUT" ] && ok "JEV_GRADER: the blinded grader's own delegations are not routed by the thing it is grading" \
              || bad "grader guard failed: [$OUT]"

reset
OUT="$(cd "$ROOT" && printf '%s' "$(mkpayload Explore)" | env CLAUDE_PROJECT_DIR="$SANDBOX" JEV_HOME="$SANDBOX" HOME="$SANDBOX" "$HOOK")"
[ -z "$OUT" ] && ok "cwd guard: a session running outside the project root is left alone" \
              || bad "cwd guard failed: [$OUT]"

reset
run '{"session_id":"s1","tool_use_id":"t","tool_name":"Bash","tool_input":{"command":"ls"}}'
[ -z "$OUT" ] && [ ! -d "$LEDGERS" ] \
  && ok "a non-Agent tool is left strictly alone, and is not a router failure either" \
  || bad "rewrote a non-Agent tool input: [$OUT]"

# ---------------------------------------------------------------------------
echo
echo "  10. THE LATENCY BUDGET, MEASURED RATHER THAN INTENDED"
# ---------------------------------------------------------------------------
# Non-negotiable 5: anything on the synchronous path has a budget enforced by a
# test. The static floor makes no network call, so this is process spawn plus a
# handful of forks -- but "no added felt latency" has to be a number.
reset
BUDGET=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["latency_budget_ms"])' "$SANDBOX/config/tiers.json")
T_START=$(python3 -c 'import time; print(time.time())')
i=0
while [ "$i" -lt 20 ]; do
  run "$(mkpayload Explore)"
  i=$((i + 1))
done
MEAN_MS=$(python3 -c 'import sys,time; print((time.time()-float(sys.argv[1]))*1000/20)' "$T_START")
python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) < float(sys.argv[2]) else 1)' "$MEAN_MS" "$BUDGET" \
  && ok "mean wall-clock over 20 invocations is ${MEAN_MS%%.*}ms, inside the ${BUDGET}ms budget in config/tiers.json" \
  || bad "mean ${MEAN_MS}ms EXCEEDS the ${BUDGET}ms budget -- this hook is on the spawn critical path"
python3 -c 'import json,sys,glob
rows=[json.loads(l) for f in sorted(glob.glob(sys.argv[1]+"/*.jsonl")) for l in open(f) if l.strip()]
ms=[r["hook_ms"] for r in rows if r.get("hook_ms") is not None]
sys.exit(0 if ms and max(ms) < float(sys.argv[2]) else 1)' "$LEDGERS" "$BUDGET" \
  && ok "every ledger row carries its own hook_ms, and none exceeded the budget" \
  || bad "a ledger row reported hook_ms over budget (or carried none)"

# ---------------------------------------------------------------------------
echo
echo "  11. ZERO API CALLS, AND NOTHING WRITTEN OUTSIDE THE SANDBOX"
# ---------------------------------------------------------------------------
grep -qE 'curl|wget|nc |openssl s_client|API_KEY|https?://' "$HOOK" \
  && bad "the static floor contains a network primitive or a credential -- it must make none" \
  || ok "no curl, no wget, no endpoint, no API key anywhere in the hook"

# Every path the hook writes is derived from $CLAUDE_PROJECT_DIR; the only $HOME
# reference is a read-only kill-switch test. Asserted rather than assumed.
python3 - "$HOOK" <<'PY' && ok "no write verb in the hook is aimed at \$HOME or an absolute system path" || bad "the hook writes outside the project root"
import re, sys
src = open(sys.argv[1]).read().splitlines()
bad = []
for i, line in enumerate(src, 1):
    if line.lstrip().startswith("#"):
        continue
    if re.search(r'(>>?|mkdir|rm|mv|cp|touch|ln)\s+[^\n]{0,80}(\$HOME|~/|/tmp/|/var/|/etc/)', line):
        bad.append(f"{i}: {line.strip()}")
print("\n".join(bad))
sys.exit(1 if bad else 0)
PY

echo
echo "  ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ] || exit 1
