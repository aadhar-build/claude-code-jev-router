#!/bin/bash
# JEV-40. The reversibility gate: one switch, and a PROOF that OFF means vanilla.
#
# The three existing gates (isolation, fail-open, kill switch) were written when
# every hook was an OBSERVER, and for an observer OFF only has to mean "stop
# recording" -- which is exactly what they assert: no spool file appears. From
# JEV-35 onward a hook is an ACTUATOR that rewrites tool input, and OFF has to
# mean something stronger: *stop deciding, and let the default happen exactly as
# it would have*.
#
# Those are different claims, and the difference is not visible in a spool
# count. A hook that exits early STILL RAN. The only thing that separates it
# from a hook that never existed is whether the tool input it leaves behind is
# identical to the untouched one. So this file does not assert that; it measures
# it, against `src/hook_dispatch.py`, which models Claude Code's documented
# PreToolUse dispatch.
#
# Five sections:
#   1. ENUMERATION  -- every registered hook carries the canonical switch block,
#                      so a new surface cannot be added without it
#   2. FAIL SAFE    -- a switch whose state cannot be established reads as ON
#   3. OFF = VANILLA-- byte-identity of the resolved tool input, with a positive
#                      control that proves the comparison can see a rewrite
#   4. TEARDOWN     -- the documented one-command way out, exercised in a sandbox
#   5. LIVE SESSION -- the switch is evaluated per invocation, not cached
#
# Everything runs in a sandbox project directory. The live
# `.claude/settings.local.json` is READ and never written; section 0 and the
# final check assert its bytes are unchanged, because it is the registration a
# collection window is currently running on.
#
# Offline. No network, no spend, nothing written to data/ or spool/.

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
LIVE_SETTINGS="$ROOT/.claude/settings.local.json"
DISPATCH="$ROOT/src/hook_dispatch.py"

pass=0; fail=0
ok()  { echo "    ok    $1"; pass=$((pass+1)); }
bad() { echo "    FAIL  $1"; fail=$((fail+1)); }

sha() { if [ -f "$1" ]; then shasum -a 256 "$1" | awk '{print $1}'; else echo "ABSENT"; fi; }

LIVE_SHA_BEFORE="$(sha "$LIVE_SETTINGS")"

SANDBOX="$(mktemp -d)"
# pwd -P: on macOS /tmp is a symlink to /private/tmp, and the hooks' cwd guard
# compares "$PWD/" against "$ROOT"/*. An unresolved sandbox path makes every
# hook exit on the cwd guard, which would make every arm below trivially equal
# and the whole gate vacuous.
SANDBOX="$(cd "$SANDBOX" && pwd -P)"
cleanup() { chmod -R u+rwX "$SANDBOX" 2>/dev/null; rm -rf "$SANDBOX"; }
trap cleanup EXIT

echo
echo "=============================================================="
echo " REVERSIBILITY -- one switch, and a proof that OFF is vanilla"
echo "=============================================================="

# ---------------------------------------------------------------------------
# 0. The live registration is present and readable. Without it, section 1 would
#    pass by enumerating nothing, which is the exact failure the gate exists to
#    prevent.
# ---------------------------------------------------------------------------
if [ -f "$LIVE_SETTINGS" ]; then
  ok "live registration present at .claude/settings.local.json"
else
  bad "no .claude/settings.local.json -- the enumeration gate would pass vacuously"
fi

# ---------------------------------------------------------------------------
# 1. ENUMERATION
# ---------------------------------------------------------------------------
echo
echo "  1. ENUMERATION -- every hook checks the switch, before anything else"
echo

ENUM=$(python3 - "$ROOT" <<'PY'
import json, re, shlex, sys
from pathlib import Path

root = Path(sys.argv[1])
settings_path = root / ".claude" / "settings.local.json"

sys.path.insert(0, str(root / "src"))
from hook_dispatch import registered_handlers  # noqa: E402

BEGIN = "# --- jev kill switch: canonical block, byte-identical in every hook"
END = "# --- end jev kill switch"


def block_of(text):
    """Extract the canonical switch block, or None."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith(BEGIN)), None)
    if start is None:
        return None, None
    end = next((i for i, l in enumerate(lines[start:], start) if l.startswith(END)), None)
    if end is None:
        return None, None
    return "\n".join(lines[start:end + 1]), start


# Anything before the switch that could touch the world, or emit a decision.
EFFECTFUL = re.compile(
    r"\b(curl|wget|nc|jq|python3?|node|mkdir|touch|cp|mv|rm|tee|openssl|date|shasum)\b"
    r"|hookSpecificOutput|updatedInput|permissionDecision"
    r"|(^|[^0-9<>&])>>?\s*[\"'$/]"
)
# Setup that is allowed to precede it: comments, the fail-open trap, stderr
# redirection, locale pinning, plain assignments, the recursion guard and the
# `[ -n/-d ]` tests that establish $ROOT itself.
ALLOWED = re.compile(
    r"^\s*(#|$)"
    r"|^\s*trap\b"
    r"|^\s*exec\s+[0-9]*[<>]"
    r"|^\s*export\s+LC_ALL"
    r"|^\s*(if|fi|else|elif|then)\b"
    r"|^\s*[A-Za-z_][A-Za-z0-9_]*=\S*\s*$"
    r"|^\s*\[\s*-[nd]\s"
)

out = {"scripts": {}, "registered": [], "errors": []}

# Every registered hook command, on every event -- plus every hook script on
# disk, because a hook is written before it is registered and the block must be
# there on the day it is written, not the day it goes live.
scripts = set()
if settings_path.exists():
    settings = json.loads(settings_path.read_text())
    for h in registered_handlers(settings):
        out["registered"].append({"event": h["event"], "matcher": h["matcher"],
                                  "command": h["command"], "type": h["type"]})
        if h["type"] != "command":
            out["errors"].append(f"{h['event']}: non-command hook type {h['type']!r} "
                                 f"-- the switch cannot be asserted on it")
            continue
        cmd = h["command"] or ""
        if "$CLAUDE_PROJECT_DIR" not in cmd and "${CLAUDE_PROJECT_DIR}" not in cmd:
            out["errors"].append(f"{h['event']}: command is not $CLAUDE_PROJECT_DIR-anchored: {cmd}")
        expanded = cmd.replace("${CLAUDE_PROJECT_DIR}", str(root)).replace("$CLAUDE_PROJECT_DIR", str(root))
        try:
            argv = shlex.split(expanded)
        except ValueError:
            out["errors"].append(f"{h['event']}: unparseable command {cmd}")
            continue
        target = next((a for a in argv if a.endswith((".sh", ".py", ".bash"))), None)
        if target is None:
            out["errors"].append(f"{h['event']}: no script found in command {cmd}")
            continue
        p = Path(target)
        if not p.exists():
            out["errors"].append(f"{h['event']}: registered script does not exist: {p}")
            continue
        scripts.add(str(p.resolve()))
        out["registered"][-1]["script"] = str(p.resolve())

for p in sorted((root / "hooks").glob("*.sh")):
    scripts.add(str(p.resolve()))

for s in sorted(scripts):
    p = Path(s)
    text = p.read_text()
    blk, line = block_of(text)
    rel = str(p.relative_to(root)) if root in p.parents else str(p)
    if blk is None:
        out["scripts"][rel] = {"ok": False, "why": "canonical switch block absent"}
        continue
    if ".jev-disabled" in text.replace(blk, ""):
        out["scripts"][rel] = {"ok": False, "why": "references .jev-disabled outside the canonical block"}
        continue
    preceding = text.splitlines()[:line]
    offenders = [f"{i+1}:{l.strip()[:60]}" for i, l in enumerate(preceding)
                 if not ALLOWED.search(l) and EFFECTFUL.search(l)]
    out["scripts"][rel] = {"ok": not offenders, "block": blk, "line": line + 1,
                           "why": "; ".join(offenders)}

print(json.dumps(out))
PY
)

if [ -z "$ENUM" ]; then
  bad "enumeration helper produced no output"
else
  n_reg=$(printf '%s' "$ENUM" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["registered"]))')
  n_scripts=$(printf '%s' "$ENUM" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["scripts"]))')

  if [ "$n_reg" -gt 0 ]; then
    ok "enumerated $n_reg registered hook handler(s) from settings.local.json"
  else
    bad "no registered hook handlers found -- this gate must not pass on an empty set"
  fi

  printf '%s' "$ENUM" | python3 -c 'import json,sys
for e in json.load(sys.stdin)["errors"]: print(e)' | while read -r line; do
    [ -n "$line" ] && echo "    FAIL  registration: $line"
  done
  n_err=$(printf '%s' "$ENUM" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["errors"]))')
  if [ "$n_err" = "0" ]; then
    ok "every registered command is \$CLAUDE_PROJECT_DIR-anchored and resolves to a script"
  else
    fail=$((fail+n_err))
  fi

  # Each script individually, so a failure names the file.
  while IFS='|' read -r name good why; do
    [ -z "$name" ] && continue
    if [ "$good" = "True" ]; then
      ok "$name: canonical switch block present, nothing effectful precedes it"
    else
      bad "$name: $why"
    fi
  done <<EOF
$(printf '%s' "$ENUM" | python3 -c 'import json,sys
d=json.load(sys.stdin)["scripts"]
for k,v in sorted(d.items()): print("%s|%s|%s" % (k, v["ok"], v.get("why") or ""))')
EOF

  # The block must be the SAME block everywhere. Identical by extraction, not
  # by a regex that would drift apart from the thing it matches.
  n_distinct=$(printf '%s' "$ENUM" | python3 -c 'import json,sys
d=json.load(sys.stdin)["scripts"]
print(len({v.get("block") for v in d.values()}))')
  if [ "$n_distinct" = "1" ] && [ "$n_scripts" -gt 1 ]; then
    ok "the switch block is byte-identical across all $n_scripts hook scripts"
  elif [ "$n_scripts" -le 1 ]; then
    bad "only $n_scripts hook script found -- expected at least two"
  else
    bad "$n_distinct different switch blocks across $n_scripts hook scripts -- they have drifted"
  fi
fi

# ---------------------------------------------------------------------------
# Build the sandbox project used by sections 2-5.
# ---------------------------------------------------------------------------
mkdir -p "$SANDBOX/hooks" "$SANDBOX/spool/tmp" "$SANDBOX/spool/ready" \
         "$SANDBOX/.claude" "$SANDBOX/data" "$SANDBOX/logs" "$SANDBOX/config" 2>/dev/null
cp "$ROOT"/hooks/*.sh "$SANDBOX/hooks/" 2>/dev/null
cp "$ROOT/teardown.sh" "$SANDBOX/teardown.sh" 2>/dev/null
cp "$LIVE_SETTINGS" "$SANDBOX/.claude/settings.local.json" 2>/dev/null
chmod +x "$SANDBOX"/hooks/*.sh "$SANDBOX/teardown.sh" 2>/dev/null

SWITCH="$SANDBOX/.jev-disabled"
BASH_PAYLOAD="$SANDBOX/payload-bash.json"
AGENT_PAYLOAD="$SANDBOX/payload-agent.json"

python3 - "$SANDBOX" <<'PY'
import json, sys
from pathlib import Path
s = Path(sys.argv[1])
(s / "payload-bash.json").write_text(json.dumps({
    "session_id": "reversibility", "cwd": str(s), "tool_name": "Bash",
    "tool_input": {"command": "ls -la", "description": "list"},
}))
# Agent-shaped, because that is the tool JEV-35 rewrites. No `model` key: the
# default case, where a routing hook ADDS a field that was not there.
(s / "payload-agent.json").write_text(json.dumps({
    "session_id": "reversibility", "cwd": str(s), "tool_name": "Agent",
    "tool_input": {
        "prompt": "Find every caller of build_pre_bash.",
        "description": "find callers",
        "subagent_type": "Explore",
    },
}))
PY

sandbox_clean() { rm -f "$SANDBOX"/spool/ready/*.json "$SANDBOX"/spool/tmp/* 2>/dev/null; }
sandbox_count() { ls "$SANDBOX"/spool/ready/*.json 2>/dev/null | wc -l | tr -d ' '; }

fire_capture() {
  # Fire the real capture hook the way Claude Code fires it, from inside the
  # sandbox project.
  ( cd "$SANDBOX" && CLAUDE_PROJECT_DIR="$SANDBOX" "$SANDBOX/hooks/capture.sh" pre_bash \
      < "$BASH_PAYLOAD" ) 2>/dev/null
}

# ---------------------------------------------------------------------------
# 2. FAIL SAFE
# ---------------------------------------------------------------------------
echo
echo "  2. FAIL SAFE -- a switch whose state cannot be established reads as ON"
echo

rm -rf "$SWITCH"; sandbox_clean
fire_capture; rc=$?
if [ "$rc" = "0" ] && [ "$(sandbox_count)" = "1" ]; then
  ok "control: with no switch, the sandbox hook captures (so the cases below are not vacuous)"
else
  bad "control: expected one capture with no switch, got $(sandbox_count) (rc=$rc)"
fi

# 2a. Ordinary file.
rm -rf "$SWITCH"; : > "$SWITCH"; sandbox_clean
fire_capture; rc=$?
[ "$rc" = "0" ] && [ "$(sandbox_count)" = "0" ] \
  && ok "regular file: OFF" || bad "regular file did not stop the hook (rc=$rc, $(sandbox_count) captured)"

# 2b. A DIRECTORY at the switch path. `[ -f ]` reads this as absent, so an
#     operator who typed `mkdir` instead of `touch` would believe the
#     experiment was off while it kept running.
rm -rf "$SWITCH"; mkdir -p "$SWITCH"; sandbox_clean
fire_capture; rc=$?
[ "$rc" = "0" ] && [ "$(sandbox_count)" = "0" ] \
  && ok "directory at the switch path: OFF (\`-f\` alone would have read it as absent)" \
  || bad "a directory at the switch path did not stop the hook (rc=$rc, $(sandbox_count) captured)"

# 2c. A DANGLING SYMLINK. `[ -e ]` follows the link and reads it as absent.
rm -rf "$SWITCH"; ln -s "$SANDBOX/nowhere-at-all" "$SWITCH"; sandbox_clean
fire_capture; rc=$?
[ "$rc" = "0" ] && [ "$(sandbox_count)" = "0" ] \
  && ok "dangling symlink at the switch path: OFF (\`-e\` alone would have followed it)" \
  || bad "a dangling symlink did not stop the hook (rc=$rc, $(sandbox_count) captured)"

# 2d. A file that exists and CANNOT BE READ. Presence is what is tested, not
#     content, so this must still read as present.
rm -rf "$SWITCH"; : > "$SWITCH"; chmod 000 "$SWITCH"; sandbox_clean
fire_capture; rc=$?
chmod 600 "$SWITCH" 2>/dev/null
[ "$rc" = "0" ] && [ "$(sandbox_count)" = "0" ] \
  && ok "unreadable file at the switch path: OFF" \
  || bad "an unreadable switch did not stop the hook (rc=$rc, $(sandbox_count) captured)"

# 2e. And the inline shadow hook, which is the other registered-capable surface.
rm -rf "$SWITCH"; mkdir -p "$SWITCH"
out=$( cd "$SANDBOX" && CLAUDE_PROJECT_DIR="$SANDBOX" JEV_INLINE_LOG_DIR="$SANDBOX/data/inline" \
       "$SANDBOX/hooks/inline_shadow_bash.sh" < "$BASH_PAYLOAD" 2>/dev/null ); rc=$?
n=$(cat "$SANDBOX"/data/inline/*.jsonl 2>/dev/null | wc -l | tr -d ' ')
[ "$rc" = "0" ] && [ -z "$out" ] && [ "$n" = "0" ] \
  && ok "inline shadow hook honours the same fail-safe (no call, no row, empty stdout)" \
  || bad "inline shadow: rc=$rc rows=$n stdout=[$out]"
rm -rf "$SWITCH"

# ---------------------------------------------------------------------------
# 3. OFF EQUALS VANILLA
# ---------------------------------------------------------------------------
echo
echo "  3. OFF = VANILLA -- byte-identity of the resolved tool input"
echo

VANILLA_SETTINGS="$SANDBOX/.claude/settings.vanilla.json"
printf '{"hooks":{}}\n' > "$VANILLA_SETTINGS"

resolve() { # resolve <settings> <payload>
  python3 "$DISPATCH" --settings "$1" --project-dir "$SANDBOX" --payload "$2" 2>/dev/null
}

# The control arm: hooks unregistered ENTIRELY. This is what "vanilla" means --
# not a hook that returned early, but no hook at all.
VAN_BASH=$(resolve "$VANILLA_SETTINGS" "$BASH_PAYLOAD")
VAN_AGENT=$(resolve "$VANILLA_SETTINGS" "$AGENT_PAYLOAD")
[ -n "$VAN_BASH" ] && [ -n "$VAN_AGENT" ] \
  && ok "vanilla arm resolves (hooks unregistered entirely)" \
  || bad "vanilla arm produced nothing -- the comparison has no control"

# 3a. The LIVE registration, switch ON.
rm -rf "$SWITCH"; : > "$SWITCH"; sandbox_clean
A_BASH=$(resolve "$SANDBOX/.claude/settings.local.json" "$BASH_PAYLOAD")
[ "$A_BASH" = "$VAN_BASH" ] \
  && ok "live registration + switch ON: resolved input is byte-identical to vanilla" \
  || bad "live registration + switch ON DIFFERS from vanilla: [$A_BASH] vs [$VAN_BASH]"
[ "$(sandbox_count)" = "0" ] && ok "live registration + switch ON: nothing recorded either" \
  || bad "switch ON still recorded $(sandbox_count)"

# 3b. The LIVE registration, switch OFF. Byte-identical too -- capture.sh is an
#     observer -- but this arm must also PROVE the hook actually ran, or 3a
#     proves nothing.
rm -rf "$SWITCH"; sandbox_clean
B_BASH=$(resolve "$SANDBOX/.claude/settings.local.json" "$BASH_PAYLOAD")
[ "$B_BASH" = "$VAN_BASH" ] \
  && ok "live registration + switch OFF: still byte-identical (today's hooks only observe)" \
  || bad "live registration + switch OFF DIFFERS from vanilla: [$B_BASH]"
[ "$(sandbox_count)" = "1" ] \
  && ok "live registration + switch OFF: the hook DID run (1 capture) -- 3a is not vacuous" \
  || bad "the hook did not run with the switch off; 3a would prove nothing ($(sandbox_count) captures)"

# --- the actuator fixture ---------------------------------------------------
# A hook of the shape JEV-35 will register: it returns permissionDecision allow
# plus updatedInput with `model` rewritten. It carries the canonical switch
# block, EXTRACTED FROM THE REAL HOOK rather than retyped, so this fixture and
# the shipped hooks cannot drift apart.
{
  echo '#!/bin/bash'
  echo "trap 'exit 0' EXIT"
  echo 'ROOT="${CLAUDE_PROJECT_DIR:-}"'
  echo '[ -n "$ROOT" ] || exit 0'
  awk '/^# --- jev kill switch: canonical block/,/^# --- end jev kill switch/' "$ROOT/hooks/capture.sh"
  cat <<'ACT'
PAYLOAD=$(cat)
printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
p = json.load(sys.stdin)
ti = dict(p.get("tool_input", {}))
ti["model"] = "claude-haiku-4-5"
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "updatedInput": ti}}))
'
exit 0
ACT
} > "$SANDBOX/hooks/actuator.sh"
chmod +x "$SANDBOX/hooks/actuator.sh"

cat > "$SANDBOX/.claude/settings.actuator.json" <<'ACTSET'
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Agent",
        "hooks": [
          { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR/hooks/actuator.sh\"", "timeout": 10 }
        ]
      }
    ]
  }
}
ACTSET

# 3c. POSITIVE CONTROL. Actuator registered, switch OFF: the resolved input must
#     DIFFER. Without this, every assertion above would pass on a test that
#     cannot detect a rewrite at all -- which is the state the repo was in
#     before this file existed.
rm -rf "$SWITCH"
C_AGENT=$(resolve "$SANDBOX/.claude/settings.actuator.json" "$AGENT_PAYLOAD")
if [ "$C_AGENT" != "$VAN_AGENT" ]; then
  ok "positive control: an actuator with the switch OFF DOES change the input"
else
  bad "positive control failed: the actuator changed nothing, so this gate cannot detect a rewrite"
fi
case "$C_AGENT" in
  *'"model":"claude-haiku-4-5"'*) ok "positive control: the rewritten field is the one JEV-35 rewrites (model)" ;;
  *) bad "positive control: no rewritten model in [$C_AGENT]" ;;
esac
# Input fidelity, previewing JEV-35's own gate: updatedInput replaces the ENTIRE
# object, so a dropped field looks exactly like a routing effect.
fid=$(python3 - "$C_AGENT" "$VAN_AGENT" <<'PY'
import json, sys
got, van = json.loads(sys.argv[1]), json.loads(sys.argv[2])
bad = [k for k in van if got.get(k) != van[k]]
print("|".join(bad))
PY
)
[ -z "$fid" ] && ok "positive control: prompt/description/subagent_type echoed back unchanged" \
              || bad "actuator dropped or altered: $fid"

# 3d. THE CLAIM. Actuator registered, switch ON: byte-identical to vanilla. This
#     is the assertion JEV-35 is gated on, and 3c is what makes it mean
#     something.
rm -rf "$SWITCH"; : > "$SWITCH"
D_AGENT=$(resolve "$SANDBOX/.claude/settings.actuator.json" "$AGENT_PAYLOAD")
[ "$D_AGENT" = "$VAN_AGENT" ] \
  && ok "ACTUATOR + switch ON: resolved input byte-identical to hooks-unregistered" \
  || bad "ACTUATOR + switch ON left a DIFFERENT input: [$D_AGENT] vs [$VAN_AGENT]"

# 3e. And with the switch in each of its fail-safe forms, the actuator must
#     still leave vanilla behind -- the fail-safe has to hold on the path where
#     it matters, not only on the observer.
for form in dir dangling unreadable; do
  rm -rf "$SWITCH"
  case "$form" in
    dir)        mkdir -p "$SWITCH" ;;
    dangling)   ln -s "$SANDBOX/nowhere-at-all" "$SWITCH" ;;
    unreadable) : > "$SWITCH"; chmod 000 "$SWITCH" ;;
  esac
  got=$(resolve "$SANDBOX/.claude/settings.actuator.json" "$AGENT_PAYLOAD")
  chmod 600 "$SWITCH" 2>/dev/null
  [ "$got" = "$VAN_AGENT" ] \
    && ok "ACTUATOR + switch as $form: still byte-identical to vanilla" \
    || bad "ACTUATOR + switch as $form rewrote the input: [$got]"
done
rm -rf "$SWITCH"

# ---------------------------------------------------------------------------
# 4. TEARDOWN
# ---------------------------------------------------------------------------
echo
echo "  4. TEARDOWN -- one documented command, exercised in the sandbox"
echo

before=$(sha "$SANDBOX/.claude/settings.local.json")
"$SANDBOX/teardown.sh" >/dev/null 2>&1; rc=$?
[ "$rc" = "2" ] && ok "teardown refuses to run without --yes (exit 2)" \
                || bad "teardown ran without confirmation (exit $rc)"

dry=$("$SANDBOX/teardown.sh" --dry-run 2>&1); rc=$?
[ "$rc" = "0" ] && ok "teardown --dry-run exits 0" || bad "teardown --dry-run exit $rc"
[ "$(sha "$SANDBOX/.claude/settings.local.json")" = "$before" ] \
  && ok "teardown --dry-run changed nothing" || bad "teardown --dry-run modified the registration"
[ -e "$SANDBOX/.jev-disabled" ] && bad "teardown --dry-run created the switch" \
                               || ok "teardown --dry-run did not create the switch"
case "$dry" in
  *"DOES NOT undo"*) ok "teardown states plainly what it does not undo" ;;
  *) bad "teardown does not say what it leaves behind" ;;
esac
case "$dry" in
  *"routed model"*) ok "teardown names the irreversible part (work produced by a routed model)" ;;
  *) bad "teardown omits the irreversible part" ;;
esac

out=$("$SANDBOX/teardown.sh" --yes 2>&1); rc=$?
[ "$rc" = "0" ] && ok "teardown --yes exits 0" || bad "teardown --yes exit $rc"
[ -f "$SANDBOX/.jev-disabled" ] && ok "teardown --yes set the switch" || bad "teardown --yes did not set the switch"
[ -f "$SANDBOX/.claude/settings.local.json" ] \
  && bad "teardown --yes left the hooks registered" \
  || ok "teardown --yes unregistered the hooks"
parked=$(ls "$SANDBOX"/.claude/settings.local.json.disabled-* 2>/dev/null | head -1)
if [ -n "$parked" ] && [ "$(sha "$parked")" = "$before" ]; then
  ok "teardown --yes parked the registration intact (moved, not deleted)"
else
  bad "the parked registration is missing or altered"
fi

# After teardown, the dispatch oracle must see no hooks at all -- the strongest
# form of OFF, and it must equal vanilla too.
T_BASH=$(resolve "$SANDBOX/.claude/settings.local.json" "$BASH_PAYLOAD")
[ "$T_BASH" = "$VAN_BASH" ] && ok "after teardown: resolved input byte-identical to vanilla" \
                            || bad "after teardown the input still differs: [$T_BASH]"

# And the printed restore command puts it back.
mv "$parked" "$SANDBOX/.claude/settings.local.json" 2>/dev/null
rm -f "$SANDBOX/.jev-disabled"
[ "$(sha "$SANDBOX/.claude/settings.local.json")" = "$before" ] \
  && ok "the documented restore command returns the registration byte-for-byte" \
  || bad "restore did not reproduce the original registration"

# ---------------------------------------------------------------------------
# 5. LIVE SESSION
# ---------------------------------------------------------------------------
echo
echo "  5. LIVE SESSION -- the switch is read per invocation, never cached"
echo

# Established as fact on 2026-09-20 by probing a running session: with the
# switch absent a Bash call was captured, with the switch present the next Bash
# call in the SAME session was not, and with it removed again the call after
# that was. No restart at any point. See docs/REVERSIBILITY.md.
#
# The mechanism is why it generalises: the switch is not hook CONFIGURATION, it
# is a file test performed by the hook SCRIPT, and the script is read from disk
# by a fresh process on every invocation. Whether Claude Code caches its hook
# config cannot affect it. The assertion below is that mechanism, reproduced
# offline: one unchanged registration, the switch toggled underneath it.
rm -rf "$SWITCH"; sandbox_clean
fire_capture; a=$(sandbox_count)
: > "$SWITCH"
fire_capture; b=$(sandbox_count)
rm -f "$SWITCH"
fire_capture; c=$(sandbox_count)
if [ "$a" = "1" ] && [ "$b" = "1" ] && [ "$c" = "2" ]; then
  ok "toggling the switch under an unchanged registration takes effect immediately"
else
  bad "switch toggling did not take effect per invocation (counts $a/$b/$c)"
fi

if [ -f "$ROOT/docs/REVERSIBILITY.md" ]; then
  ok "the live-session finding is written down (docs/REVERSIBILITY.md)"
else
  bad "docs/REVERSIBILITY.md missing -- the live-session fact is not recorded anywhere"
fi

# ---------------------------------------------------------------------------
# 6. The live registration must be exactly as we found it.
# ---------------------------------------------------------------------------
echo
if [ "$(sha "$LIVE_SETTINGS")" = "$LIVE_SHA_BEFORE" ]; then
  ok "the live .claude/settings.local.json is byte-identical to before this run"
else
  bad "THIS TEST MODIFIED THE LIVE REGISTRATION -- restore it before continuing"
fi
if [ -e "$ROOT/.jev-disabled" ] || [ -L "$ROOT/.jev-disabled" ]; then
  echo "    note  the live switch is currently SET (capture is off)"
fi

echo
echo "=============================================================="
if [ "$fail" -eq 0 ]; then
  echo " $pass passed, 0 failed"
  echo " OFF IS PROVEN EQUAL TO VANILLA -- JEV-35 may proceed"
else
  echo " $pass passed, $fail FAILED"
fi
echo "=============================================================="
echo
[ "$fail" -eq 0 ]
