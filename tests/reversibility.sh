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
# Six sections, numbered 0-5:
#   0. THE REGISTRATION UNDER TEST -- live, or a fixture the real installer
#                      materialises. Named out loud, because it bounds what
#                      every section below is entitled to claim (JEV-56)
#   1. ENUMERATION  -- every registered hook carries the canonical switch
#                      blocks, so a new surface cannot be added without them
#   2. FAIL SAFE    -- a switch whose state cannot be established reads as ON
#   3. OFF = VANILLA-- byte-identity of the resolved tool input, with a positive
#                      control that proves the comparison can see a rewrite
#   4. TEARDOWN     -- the documented one-command way out, exercised in a sandbox
#   5. LIVE SESSION -- the switch is evaluated per invocation, not cached
#
# Everything runs in a sandbox project directory. The live
# `.claude/settings.local.json` is READ and never written; the final check
# asserts its bytes are unchanged, because it is the registration a collection
# window would be running on.
#
# JEV-56: THIS FILE IS GREEN ON A CLEAN CHECKOUT, and `tests/test_clean_checkout.sh`
# proves it by running this file in one. A registration is gitignored by design,
# so on a fresh clone there is none; the gate then materialises one with
# `jev install` rather than failing, and says which it used. "Is a registration
# present and correct?" and "does OFF equal vanilla?" are now separate
# questions: the first needs a real file and is skipped without one; the second
# needs only A registration, and never passes on an empty set.
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
# Build the sandbox project, BEFORE section 0 -- because section 0 is now a
# question about which registration everything below is measured against, and
# that question cannot be answered until the sandbox exists.
# ---------------------------------------------------------------------------
mkdir -p "$SANDBOX/hooks" "$SANDBOX/spool/tmp" "$SANDBOX/spool/ready" \
         "$SANDBOX/.claude" "$SANDBOX/data" "$SANDBOX/logs" "$SANDBOX/config" || {
  echo "    FAIL  could not build the sandbox project at $SANDBOX"; exit 1; }
cp "$ROOT"/hooks/*.sh "$SANDBOX/hooks/" || {
  echo "    FAIL  could not copy hooks/ into the sandbox"; exit 1; }
cp "$ROOT/teardown.sh" "$SANDBOX/teardown.sh" || {
  echo "    FAIL  could not copy teardown.sh into the sandbox"; exit 1; }
# The sandbox is a COMPLETE jev install, not just a hooks directory: config and
# src as well. That is what lets `jev install --into $SANDBOX` below run with
# JEV_HOME pointed here, which is what makes the fixture registration name the
# SANDBOX's hooks rather than the live repo's.
cp "$ROOT"/config/*.json "$SANDBOX/config/" || {
  echo "    FAIL  could not copy config/ into the sandbox"; exit 1; }
mkdir -p "$SANDBOX/src"
cp "$ROOT"/src/*.py "$SANDBOX/src/" || {
  echo "    FAIL  could not copy src/ into the sandbox"; exit 1; }
chmod +x "$SANDBOX"/hooks/*.sh "$SANDBOX/teardown.sh" || {
  echo "    FAIL  could not make the sandboxed hooks executable"; exit 1; }

SANDBOX_SETTINGS="$SANDBOX/.claude/settings.local.json"

# ---------------------------------------------------------------------------
# JEV-56. WHICH REGISTRATION IS THE PROOF MADE AGAINST?
#
# `.claude/settings.local.json` is gitignored BY DESIGN -- a live registration
# must never travel to a clone or a cloud session. So on a clean checkout there
# is no registration to test, and four gates here used to fail: correctly, since
# each guards against passing vacuously on an empty set, but for a reason that
# makes the suite impossible to go green from a fresh clone. You cannot
# distribute a tool whose suite cannot go green on a clean checkout.
#
# The fix separates two questions this file used to conflate:
#
#   "is a registration PRESENT AND CORRECT?"   needs a real file, and is
#                                              reported as NOT APPLICABLE when
#                                              there is none. Absence is not a
#                                              failure; an EMPTY one always is.
#   "does OFF equal VANILLA?"                  needs only A registration --
#                                              real or fixture.
#
# And the fixture is MATERIALISED BY THE REAL INSTALLER (`jev install`), not
# hand-copied. That is the idiom this file already uses for the actuator
# fixture below -- "extracted from the real hook at test time, so the fixture
# and the shipped hooks cannot drift apart" -- applied to the one input that
# was missed. It tests the installer inside this gate for free, and the
# registration under test is a KNOWN one rather than whatever the operator
# happens to have lying around.
#
# The old `cp ... 2>/dev/null` here is gone. On a clean checkout that copy
# failed SILENTLY and sections 2-5 then ran against a sandbox with no
# registration at all, which is why the failures surfaced three sections later
# instead of at the missing input.
# ---------------------------------------------------------------------------
if [ -f "$LIVE_SETTINGS" ]; then
  REG_MODE="live"
  cp "$LIVE_SETTINGS" "$SANDBOX_SETTINGS" || {
    echo "    FAIL  a live registration exists at $LIVE_SETTINGS but could not be"
    echo "          copied into the sandbox. Stopping HERE, at the missing input,"
    echo "          rather than three sections later."
    exit 1; }
else
  REG_MODE="fixture"
  # JEV_HOME points at the sandbox, so the fixture registers the SANDBOX's copy
  # of each hook. Registering the real ones would make every arm below resolve
  # jev's assets -- and jev's kill switch -- out of the live repo.
  if ! JEV_HOME="$SANDBOX" "$ROOT/jev" install "$SANDBOX" --yes > "$SANDBOX/install.log" 2>&1; then
    echo "    FAIL  no live registration, and 'jev install' could not materialise a"
    echo "          fixture one into the sandbox. See $SANDBOX/install.log"
    sed 's/^/          /' "$SANDBOX/install.log"
    exit 1
  fi
  if [ ! -f "$SANDBOX_SETTINGS" ]; then
    echo "    FAIL  the installer reported success and wrote no registration"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# 0. WHAT THIS PROOF IS MADE AGAINST. Stated first, and out loud, because the
#    answer changes what the sections below are entitled to claim.
# ---------------------------------------------------------------------------
echo
echo "  0. THE REGISTRATION UNDER TEST"
echo
if [ "$REG_MODE" = "live" ]; then
  ok "LIVE registration: this machine's own .claude/settings.local.json"
  echo "          the hooks a collection window here is actually running on"
else
  ok "FIXTURE registration: materialised by \`jev install\` into the sandbox"
  echo "          there is no .claude/settings.local.json on this checkout -- it is"
  echo "          gitignored by design -- so the proof below is made against the"
  echo "          registration the installer WRITES, which is the one a reader"
  echo "          cloning this repo would get. That is a different claim from the"
  echo "          live one, and it is the one stated in docs/REVERSIBILITY.md."
fi

# ---------------------------------------------------------------------------
# 1. ENUMERATION
# ---------------------------------------------------------------------------
echo
echo "  1. ENUMERATION -- every hook checks the switch, before anything else"
echo

ENUM=$(python3 - "$ROOT" "$SANDBOX_SETTINGS" "$REG_MODE" <<'PY'
import json, re, shlex, sys
from pathlib import Path

root = Path(sys.argv[1])
# The registration under test -- live or fixture, decided above and passed in.
# NOT hardcoded to root/.claude/settings.local.json any more: that path is
# gitignored by design, and hardcoding it is what made this gate impossible to
# pass on a clean checkout (JEV-56).
settings_path = Path(sys.argv[2])
reg_mode = sys.argv[3]

sys.path.insert(0, str(root / "src"))
from hook_dispatch import registered_handlers  # noqa: E402

# TWO canonical blocks now, because there are two switches.
#
#   the PER-PROJECT block   $ROOT/.jev-disabled, $CLAUDE_PROJECT_DIR-anchored.
#                           The opt-out for one repo. Every hook carries it.
#   the GLOBAL block        $JEV_HOME/.jev-disabled and ~/.claude/jev-disabled.
#                           JEV_HOME-anchored, so it is a real path in EVERY
#                           install shape -- including the one the audit found,
#                           where a project-anchored switch names a file that
#                           can never exist and is therefore permanently off.
#
# The global block is required of every INSTALLABLE hook -- the ones
# `config/registration.json` says `jev install` can put in somebody else's repo
# -- and that list is read from the installer's own config rather than written
# out here, so a new installable surface cannot be added without it.
BEGIN = "# --- jev kill switch: canonical block, byte-identical in every hook"
END = "# --- end jev kill switch"
GBEGIN = "# --- jev GLOBAL kill switch: canonical block, byte-identical in every hook"
GEND = "# --- end jev GLOBAL kill switch"
HBEGIN = "# --- jev home: canonical block, byte-identical in every installable hook"
HEND = "# --- end jev home"

try:
    REG = json.loads((root / "config" / "registration.json").read_text())
    INSTALLABLE = {str((root / e["script"]).resolve()) for e in REG["entries"]}
except (OSError, json.JSONDecodeError, KeyError):
    REG, INSTALLABLE = None, set()


def block_of(text, begin=BEGIN, end=END):
    """Extract a canonical block, or None."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith(begin)), None)
    if start is None:
        return None, None
    stop = next((i for i, l in enumerate(lines[start:], start) if l.startswith(end)), None)
    if stop is None:
        return None, None
    return "\n".join(lines[start:stop + 1]), start


# Anything before the switch that could touch the world, or emit a decision.
EFFECTFUL = re.compile(
    r"\b(curl|wget|nc|jq|python3?|node|mkdir|touch|cp|mv|rm|tee|openssl|date|shasum)\b"
    # echo and printf too: any byte on stdout before the switch, on a PreToolUse
    # hook, is a permission decision we never intended to make.
    r"|\b(echo|printf)\b"
    r"|hookSpecificOutput|updatedInput|permissionDecision"
    r"|(^|[^0-9<>&])>>?\s*[\"'$/]"
)

# The block tests "$ROOT/.jev-disabled". A hook that copy-pastes it WITHOUT
# first deriving ROOT from $CLAUDE_PROJECT_DIR tests "/.jev-disabled" -- a path
# that will never exist -- and would otherwise sail through this gate with a
# switch that is structurally dead.
ROOT_DERIVED = re.compile(r"^\s*ROOT=.*CLAUDE_PROJECT_DIR")
ROOT_GUARDED = re.compile(r"^\s*\[\s+-n\s+\"\$ROOT\"\s+\]")
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
    # The JEV_HOME derivation, named explicitly rather than tolerated by
    # accident. It runs `cd`/`dirname`/`pwd` in a subshell, none of which are in
    # EFFECTFUL today -- so it would pass silently, and the day someone adds
    # `dirname` to EFFECTFUL it would start failing for no reason anybody could
    # reconstruct. It touches nothing and emits nothing; it is allowed on
    # purpose.
    r"|^\s*JEV_HOME=|JEV_HOME=\"\$\(cd "
)
# The one line of the JEV_HOME block that is a fallback assignment, matched
# whole so a future edit to it has to come back through this gate.
JEV_HOME_DERIVED = re.compile(r"JEV_HOME=.*(BASH_SOURCE|\$0)")

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
        # TWO legal shapes, and no third.
        #
        #   $CLAUDE_PROJECT_DIR-anchored  the in-repo registration, where the
        #                                 project IS jev.
        #   an absolute path under a jev  what `jev install` writes into
        #   install                       somebody else's repo, which cannot
        #                                 anchor on their project dir because
        #                                 the script does not live there.
        #
        # Anything else -- a bare name, a relative path, a path outside any jev
        # install -- is a command whose meaning depends on the session's cwd,
        # which is exactly the class of bug the anchoring rule exists to stop.
        anchored = ("$CLAUDE_PROJECT_DIR" in cmd or "${CLAUDE_PROJECT_DIR}" in cmd)
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
        if not anchored and not p.is_absolute():
            out["errors"].append(
                f"{h['event']}: command is neither $CLAUDE_PROJECT_DIR-anchored nor "
                f"an absolute path into a jev install: {cmd}")
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
    gblk, gline = block_of(text, GBEGIN, GEND)
    hblk, hline = block_of(text, HBEGIN, HEND)
    installable = str(p.resolve()) in INSTALLABLE
    rel = str(p.relative_to(root)) if root in p.parents else str(p)
    if blk is None:
        out["scripts"][rel] = {"ok": False, "why": "canonical switch block absent"}
        continue
    # An installable hook -- one `jev install` can put in a repo it does not
    # live in -- MUST carry the global block too. Without it the only switch is
    # anchored on the routed project, and there is no way to stop jev
    # everywhere at once.
    if installable and gblk is None:
        out["scripts"][rel] = {"ok": False, "block": blk,
                               "why": "INSTALLABLE and has no GLOBAL kill-switch block -- "
                                      "there would be no way to stop it everywhere at once"}
        continue
    if installable and hblk is None:
        out["scripts"][rel] = {"ok": False, "block": blk,
                               "why": "INSTALLABLE and has no canonical JEV_HOME block -- "
                                      "it would resolve jev's own assets from the routed repo"}
        continue
    # A second, drifting copy of the switch test anywhere outside the blocks
    # that own it is the thing that rots. Either block is fine; a third is not.
    residue = text.replace(blk, "")
    if gblk:
        residue = residue.replace(gblk, "")
    if hblk:
        residue = residue.replace(hblk, "")
    if ".jev-disabled" in residue:
        out["scripts"][rel] = {"ok": False, "block": blk,
                               "why": "references .jev-disabled outside the canonical blocks"}
        continue
    # Effectful-before is measured from the FIRST switch block, whichever it is:
    # the global one comes first in the actuator, and anything effectful ahead
    # of it is ahead of every switch this script has.
    first = min(x for x in (line, gline) if x is not None)
    preceding = text.splitlines()[:first]
    offenders = [f"effectful before the switch at line {i+1}: {l.strip()[:60]}"
                 for i, l in enumerate(preceding)
                 if not ALLOWED.search(l) and EFFECTFUL.search(l)]
    before_project = text.splitlines()[:line]
    if not any(ROOT_DERIVED.search(l) for l in before_project):
        offenders.append("$ROOT is not derived from $CLAUDE_PROJECT_DIR before the block "
                         "-- the switch would test /.jev-disabled")
    if not any(ROOT_GUARDED.search(l) for l in before_project):
        offenders.append('missing `[ -n "$ROOT" ]` before the block')
    if gblk is not None:
        before_global = text.splitlines()[:gline]
        if not any(JEV_HOME_DERIVED.search(l) for l in before_global):
            offenders.append("the GLOBAL block is present but $JEV_HOME is never derived "
                             "before it -- the switch would test /.jev-disabled")
    out["scripts"][rel] = {"ok": not offenders, "block": blk, "gblock": gblk,
                           "installable": installable, "line": line + 1,
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
    ok "every registered command is \$CLAUDE_PROJECT_DIR-anchored or absolute into a jev install, and resolves to a script"
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
    ok "the per-project switch block is byte-identical across all $n_scripts hook scripts"
  elif [ "$n_scripts" -le 1 ]; then
    bad "only $n_scripts hook script found -- expected at least two"
  else
    bad "$n_distinct different switch blocks across $n_scripts hook scripts -- they have drifted"
  fi

  # And the GLOBAL block, across every script that carries one. Same rule, same
  # reason: two copies of a switch test are two copies that can drift.
  g=$(printf '%s' "$ENUM" | python3 -c 'import json,sys
d=json.load(sys.stdin)["scripts"]
blocks={v.get("gblock") for v in d.values() if v.get("gblock")}
have=[k for k,v in d.items() if v.get("gblock")]
inst=[k for k,v in d.items() if v.get("installable")]
print("%d|%d|%d" % (len(blocks), len(have), len(inst)))')
  n_gblocks="${g%%|*}"; rest="${g#*|}"; n_have="${rest%%|*}"; n_inst="${rest##*|}"
  if [ "$n_inst" = "0" ]; then
    bad "config/registration.json names no installable hook -- this gate would pass on an empty set"
  elif [ "$n_have" -lt "$n_inst" ]; then
    bad "$n_have of $n_inst installable hook(s) carry the GLOBAL switch block"
  elif [ "$n_gblocks" = "1" ]; then
    ok "the GLOBAL switch block is byte-identical across all $n_have hook script(s) that carry it"
  else
    bad "$n_gblocks different GLOBAL switch blocks -- they have drifted"
  fi
fi

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

# The enumeration checker must REJECT a dead switch, not merely accept a live
# one. A hook that copy-pastes the block without deriving $ROOT tests
# "/.jev-disabled" and is structurally off forever; a checker that cannot see
# that is a checker that will wave the next surface straight through.
mkdir -p "$SANDBOX/badhook"
{
  echo '#!/bin/bash'
  awk '/^# --- jev kill switch: canonical block/,/^# --- end jev kill switch/' "$ROOT/hooks/capture.sh"
  echo 'exit 0'
} > "$SANDBOX/badhook/no_root.sh"
verdict=$(python3 - "$SANDBOX/badhook/no_root.sh" <<'NEGATIVE'
import re, sys
from pathlib import Path
lines = Path(sys.argv[1]).read_text().splitlines()
start = next(i for i, l in enumerate(lines)
             if l.startswith("# --- jev kill switch: canonical block"))
derived = any(re.search(r"^\s*ROOT=.*CLAUDE_PROJECT_DIR", l) for l in lines[:start])
print("accepted" if derived else "rejected")
NEGATIVE
)
[ "$verdict" = "rejected" ] \
  && ok "the enumeration checker REJECTS a block whose \$ROOT is never derived" \
  || bad "the checker accepted a structurally dead switch"

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
  # HOME is pinned at the sandbox. `hook_dispatch.py` passes the process
  # environment through to the hook, and the actuator's MACHINE-WIDE kill switch
  # is `$HOME/.claude/jev-disabled`. Without this pin, an operator who had set
  # that switch -- the switch this repo now tells them to use -- would find this
  # gate red, with a message about byte-identity that has nothing to do with the
  # cause. tests/test_agent_actuator.py pins HOME for exactly this reason; the
  # fix did not travel here on its own.
  HOME="$SANDBOX" python3 "$DISPATCH" --settings "$1" --project-dir "$SANDBOX" --payload "$2" 2>/dev/null
}

# The control arm: hooks unregistered ENTIRELY. This is what "vanilla" means --
# not a hook that returned early, but no hook at all.
VAN_BASH=$(resolve "$VANILLA_SETTINGS" "$BASH_PAYLOAD")
VAN_AGENT=$(resolve "$VANILLA_SETTINGS" "$AGENT_PAYLOAD")
[ -n "$VAN_BASH" ] && [ -n "$VAN_AGENT" ] \
  && ok "vanilla arm resolves (hooks unregistered entirely)" \
  || bad "vanilla arm produced nothing -- the comparison has no control"

# 3a. The LIVE registration, switch ON -- against EVERY payload this gate
#     carries, not just the one that happens to match today's matcher. When
#     JEV-35 registers a hook on matcher `Agent`, a Bash-only comparison would
#     pass without the routing hook ever running, which is exactly the vacuity
#     this section exists to prevent. So first: every registered matcher must
#     have a payload here.
uncovered=$(python3 - "$SANDBOX/.claude/settings.local.json" <<'COVERAGE'
import json, re, sys
from pathlib import Path
tools = ["Bash", "Agent"]          # the payloads this gate carries
p = Path(sys.argv[1])
settings = json.loads(p.read_text()) if p.exists() else {}
missing = []
for event, groups in (settings.get("hooks") or {}).items():
    for g in groups or []:
        m = g.get("matcher")
        if m in (None, "", "*"):
            continue
        if not any(re.fullmatch(m, tool) for tool in tools):
            missing.append("%s/%s" % (event, m))
print(",".join(sorted(set(missing))))
COVERAGE
)
[ -z "$uncovered" ] \
  && ok "every registered matcher has a payload in this gate (no surface is untested)" \
  || bad "registered matchers with no payload here: $uncovered -- add one before registering it"

rm -rf "$SWITCH"; : > "$SWITCH"; sandbox_clean
A_BASH=$(resolve "$SANDBOX/.claude/settings.local.json" "$BASH_PAYLOAD")
[ "$A_BASH" = "$VAN_BASH" ] \
  && ok "live registration + switch ON (Bash): byte-identical to vanilla" \
  || bad "live registration + switch ON DIFFERS from vanilla: [$A_BASH] vs [$VAN_BASH]"
# The Agent payload is the one JEV-35 will rewrite, and it must hold with the
# switch ON whatever is registered. With the switch OFF it is EXPECTED to differ
# once a routing hook exists, so that direction is deliberately not asserted.
A_AGENT=$(resolve "$SANDBOX/.claude/settings.local.json" "$AGENT_PAYLOAD")
[ "$A_AGENT" = "$VAN_AGENT" ] \
  && ok "live registration + switch ON (Agent): byte-identical to vanilla" \
  || bad "live registration + switch ON rewrote an Agent input: [$A_AGENT] vs [$VAN_AGENT]"
[ "$(sandbox_count)" = "0" ] && ok "live registration + switch ON: nothing recorded either" \
  || bad "switch ON still recorded $(sandbox_count)"

# 3b. The registration under test, switch OFF -- and this arm must PROVE the
#     hook actually ran, or 3a proves nothing at all.
#
#     JEV-56. THE ORACLE FOR "IT RAN" DEPENDS ON WHAT IS REGISTERED, and until
#     now it was hardcoded to one of them: a spool file appearing. That is the
#     right oracle for an OBSERVER on `Bash` (capture.sh), and the WRONG one for
#     an ACTUATOR on `Agent` -- which writes no spool file, so the count is zero
#     and this gate fails for a reason that has nothing to do with the claim.
#     The fixture registration is exactly that shape. So the oracle is chosen
#     from the registration rather than assumed, and if NEITHER applies this
#     gate fails, because then nothing here has been shown to run.
REG_SCRIPTS=$(printf '%s' "$ENUM" | python3 -c 'import json,sys
d = json.load(sys.stdin)["registered"]
print(" ".join(sorted({(r.get("script") or "").rsplit("/", 1)[-1] for r in d})))')

rm -rf "$SWITCH"; sandbox_clean
B_BASH=$(resolve "$SANDBOX/.claude/settings.local.json" "$BASH_PAYLOAD")
[ "$B_BASH" = "$VAN_BASH" ] \
  && ok "registration under test + switch OFF (Bash): still byte-identical to vanilla" \
  || bad "registration + switch OFF DIFFERS from vanilla: [$B_BASH]"

ran="no"
case " $REG_SCRIPTS " in
  *" capture.sh "*)
    # The observer's oracle: a capture appeared.
    [ "$(sandbox_count)" = "1" ] \
      && { ok "switch OFF: the observer hook DID run (1 capture) -- 3a is not vacuous"; ran="yes"; } \
      || bad "capture.sh is registered and did not run with the switch off ($(sandbox_count) captures)"
    ;;
esac
case " $REG_SCRIPTS " in
  *" agent_route_actuator.sh "*)
    # The actuator's oracle: with the switch OFF it must CHANGE the input. This
    # is the direction §3 deliberately declines to assert when no actuator is
    # registered -- with one registered it is precisely the proof that the hook
    # ran, and the companion to 3a's "switch ON, and it did not".
    B_AGENT=$(resolve "$SANDBOX/.claude/settings.local.json" "$AGENT_PAYLOAD")
    [ "$B_AGENT" != "$VAN_AGENT" ] \
      && { ok "switch OFF: the registered ACTUATOR DID run and rewrote the input -- 3a is not vacuous"; ran="yes"; } \
      || bad "the registered actuator changed nothing with the switch off; 3a would prove nothing"
    ;;
esac
[ "$ran" = "yes" ] \
  || bad "no registered hook could be shown to have run at all ($REG_SCRIPTS) -- every assertion in §3 would be vacuous"

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
