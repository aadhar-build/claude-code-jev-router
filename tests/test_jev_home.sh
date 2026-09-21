#!/bin/bash
# W2. $JEV_HOME, and TWO switches -- proven on the W1 actuator itself.
#
# ---------------------------------------------------------------------------
# WHY THIS FILE EXISTS
# ---------------------------------------------------------------------------
# Two findings from the pivot audit, and one habit this repo has earned.
#
# 1. **Two mechanisms that can disagree silently.** `src/paths.py` derived its
#    root from `__file__`; every bash hook derived its root from
#    `$CLAUDE_PROJECT_DIR`. In jev's own repo those are the same directory, so
#    the disagreement was invisible. The moment `jev install` registers a hook
#    in somebody else's repo they are different, and the sharp end of that is
#    a kill switch that names a path which will never exist -- a switch that is
#    permanently off, with no way to stop the tool.
#
#    So there is now ONE rule, `$JEV_HOME if it is a directory, else two levels
#    above this file`, written twice -- in bash and in Python -- and this file
#    runs both halves and requires the same absolute path out of each.
#
# 2. **Two switches, because one is not enough.** A global one (stop jev
#    everywhere, at 3am, before you know which repo is misbehaving) and a
#    per-project opt-out (this repo's delegations are not to be re-routed).
#    Both fail-safe: any entry at the path means OFF.
#
# 3. **Nothing is inherited by assumption.** JEV-51 shipped a kill switch that
#    stopped one writer and not another. So every switch here is asserted
#    against `hooks/agent_route_actuator.sh` ITSELF, in the install shape that
#    matters -- JEV_HOME and the project being two DIFFERENT directories -- and
#    the assertion is the strong one for an actuator: not "it stopped logging"
#    but "it stopped deciding". Zero bytes on stdout AND no ledger row.
#
# Offline. No network, no spend, no API key. The real repo is read only.

REPOROOT="$(cd "$(dirname "$0")/.." && pwd -P)"

pass=0; fail=0
ok()  { echo "  ok    $1"; pass=$((pass+1)); }
bad() { echo "  FAIL  $1"; fail=$((fail+1)); }

SANDBOX="$(mktemp -d)"
SANDBOX="$(cd "$SANDBOX" && pwd -P)"
cleanup() { chmod -R u+rwX "$SANDBOX" 2>/dev/null; rm -rf "$SANDBOX"; }
trap cleanup EXIT

# A jev install, and a SEPARATE project to route. The whole point is that these
# are two different directories: with one directory every assertion below would
# pass whichever root the hook actually used.
HOME_DIR="$SANDBOX/jevhome"
PROJ="$SANDBOX/someone-elses-repo"
FAKE_HOME="$SANDBOX/fakehome"
mkdir -p "$HOME_DIR/hooks" "$HOME_DIR/config" "$HOME_DIR/src" "$HOME_DIR/logs" \
         "$PROJ/.claude" "$FAKE_HOME/.claude"
cp "$REPOROOT"/hooks/*.sh "$HOME_DIR/hooks/"
cp "$REPOROOT/config/tiers.json" "$HOME_DIR/config/"
cp "$REPOROOT/config/registration.json" "$HOME_DIR/config/"
cp "$REPOROOT/src/paths.py" "$HOME_DIR/src/"
chmod +x "$HOME_DIR"/hooks/*.sh

ACT="$HOME_DIR/hooks/agent_route_actuator.sh"
LEDGERS="$HOME_DIR/data/agent_route/assignments"

payload() {
  printf '{"session_id":"s1","tool_use_id":"toolu_01","hook_event_name":"PreToolUse","cwd":"%s","permission_mode":"auto","tool_name":"Agent","tool_input":{"prompt":"Find every caller of drain_once.","description":"find callers","subagent_type":"Explore"}}' "$PROJ"
}

# Fire the actuator the way Claude Code would once `jev install` has put it in
# somebody else's repo: cwd and $CLAUDE_PROJECT_DIR are THEIR repo, the script
# lives in OURS, and $JEV_HOME is not set -- the hook must work it out itself.
fire() { # [env assignments...]
  OUT="$(cd "$PROJ" && payload | env -u JEV_HOME CLAUDE_PROJECT_DIR="$PROJ" \
        HOME="$FAKE_HOME" "$@" "$ACT" 2>/dev/null)"
  RC=$?
}
reset() { rm -rf "$HOME_DIR/data"; }

echo
echo "=============================================================="
echo " JEV_HOME -- one rule, both readers; and two switches, proven"
echo "=============================================================="

# ---------------------------------------------------------------------------
echo
echo "  1. ONE MECHANISM, BOTH READERS"
# ---------------------------------------------------------------------------
# The bash half, extracted FROM THE REAL HOOK at test time rather than retyped
# -- the same idiom tests/reversibility.sh uses for its actuator fixture, and
# for the same reason: a fixture that is a second copy of the thing it stands
# in for is a fixture that will drift away from it.
#
# The probe is written INTO $HOME_DIR/hooks/, because SELF-DERIVATION is the arm
# under test: a probe placed anywhere else would derive a different home, and
# the comparison would be about the probe rather than about the rule.
ASK="$HOME_DIR/hooks/_ask_jev_home.sh"
{
  echo '#!/bin/bash'
  awk '/^# --- jev home: canonical block/,/^# --- end jev home/' "$ACT"
  echo 'printf "%s\n" "$JEV_HOME"'
} > "$ASK"
chmod +x "$ASK"
# It must be the block, not an empty extraction that would make every
# comparison below trivially true.
grep -q '^JEV_HOME=' "$ASK" \
  && ok "the JEV_HOME block extracts from the shipped hook (this gate is not vacuous)" \
  || bad "could not extract the canonical JEV_HOME block from $ACT"

# The Python half, from the same install, asked exactly one question.
PYASK="import sys; sys.path.insert(0, '$HOME_DIR/src')
import paths; print(paths.JEV_HOME); print(paths.jev_home_source())"

# 1a. The SELF arm: no $JEV_HOME in the environment. Both halves must find the
#     install they are part of, from nothing but their own location -- and in
#     particular must NOT find $CLAUDE_PROJECT_DIR, which is a different
#     directory here and is exactly what the old mechanism would have returned.
b=$(cd "$PROJ" && env -u JEV_HOME CLAUDE_PROJECT_DIR="$PROJ" "$ASK")
p=$(cd "$PROJ" && env -u JEV_HOME CLAUDE_PROJECT_DIR="$PROJ" python3 -c "$PYASK")
p_home=$(printf '%s\n' "$p" | sed -n 1p)
p_src=$(printf '%s\n' "$p" | sed -n 2p)
[ "$b" = "$HOME_DIR" ] \
  && ok "bash, with no \$JEV_HOME: resolves to the install it is part of, NOT to \$CLAUDE_PROJECT_DIR" \
  || bad "bash self-derivation gave [$b], expected [$HOME_DIR]"
[ "$p_home" = "$HOME_DIR" ] && [ "$p_src" = "self" ] \
  && ok "paths.py, with no \$JEV_HOME: the same directory, by the same rule" \
  || bad "paths.py self-derivation gave [$p_home] (source $p_src), expected [$HOME_DIR]"
[ "$b" = "$p_home" ] \
  && ok "THE CLAIM: the bash half and the Python half return the SAME absolute path" \
  || bad "the two halves disagree: bash [$b] vs python [$p_home]"

# 1b. The ENV arm: $JEV_HOME set, and set to somewhere else entirely.
OTHER="$SANDBOX/another-install"; mkdir -p "$OTHER"
b2=$(cd "$PROJ" && env JEV_HOME="$OTHER" CLAUDE_PROJECT_DIR="$PROJ" "$ASK")
p2=$(cd "$PROJ" && env JEV_HOME="$OTHER" python3 -c "$PYASK")
[ "$b2" = "$OTHER" ] && [ "$(printf '%s\n' "$p2" | sed -n 1p)" = "$OTHER" ] \
  && [ "$(printf '%s\n' "$p2" | sed -n 2p)" = "env" ] \
  && ok "\$JEV_HOME set: both halves honour it, and paths.py reports which arm fired" \
  || bad "env arm disagrees: bash [$b2] python [$p2]"

# 1c. A $JEV_HOME that does not name a directory is NOT honoured -- it falls
#     back to self-derivation rather than resolving to nonsense.
b3=$(cd "$PROJ" && env JEV_HOME="$SANDBOX/not-a-directory" CLAUDE_PROJECT_DIR="$PROJ" "$ASK")
p3=$(cd "$PROJ" && env JEV_HOME="$SANDBOX/not-a-directory" python3 -c "$PYASK" | sed -n 1p)
[ "$b3" = "$HOME_DIR" ] && [ "$p3" = "$HOME_DIR" ] \
  && ok "a \$JEV_HOME that is not a directory is ignored by both halves, identically" \
  || bad "a bogus \$JEV_HOME diverged: bash [$b3] python [$p3]"
rm -f "$ASK"

# ---------------------------------------------------------------------------
echo
echo "  2. THE FOREIGN-INSTALL SHAPE -- jev's assets stay in jev's home"
# ---------------------------------------------------------------------------
# This is the install shape the audit was about, and it has never been
# exercised before: the hook registered in a repo it does not live in.
reset
fire
[ "$RC" = "0" ] && ok "the actuator exits 0 in a foreign repo (fail-safe is absolute)" \
                || bad "the actuator exited $RC"
case "$OUT" in
  *'"model":"haiku"'*) ok "it routes: the rule table was found in JEV_HOME, not in the routed repo" ;;
  *) bad "no routing decision in a foreign repo -- it read tiers.json from the wrong root: [$OUT]" ;;
esac
case "$OUT" in
  *'"subagent_type":"Explore"'*) ok "and echoes the caller's whole input back (input fidelity holds here too)" ;;
  *) bad "updatedInput dropped a field: [$OUT]" ;;
esac
ls "$LEDGERS"/*.jsonl >/dev/null 2>&1 \
  && ok "the assignment ledger is written under JEV_HOME" \
  || bad "no ledger under $LEDGERS -- jev's own record went somewhere else"
[ -e "$PROJ/data" ] || [ -e "$PROJ/config" ] || [ -e "$PROJ/logs" ] \
  && bad "the actuator created data/, config/ or logs/ in SOMEONE ELSE'S repo" \
  || ok "and NOTHING was written into the routed repo -- no data/, no logs/, no config/"

# The pre-JEV_HOME behaviour, stated as a fact rather than a memory: had the
# rule table been looked for under the routed project, it would not have been
# found, and every delegation would have failed to frontier.
[ -f "$PROJ/config/tiers.json" ] \
  && bad "the test's own fixture is wrong: the routed repo has a tiers.json" \
  || ok "the routed repo has no tiers.json -- so \"it routed\" above could only have come from JEV_HOME"

# ---------------------------------------------------------------------------
echo
echo "  3. SWITCH ONE -- the GLOBAL switch, on the W1 actuator itself"
# ---------------------------------------------------------------------------
# Three shapes each, because a switch whose state cannot be established must
# read as ON, never OFF. And the assertion is the strong one: not "it stopped
# recording" but "it stopped deciding" -- zero bytes AND no ledger.
for shape in file dir dangling unreadable; do
  reset
  SW="$HOME_DIR/.jev-disabled"
  rm -rf "$SW"
  case "$shape" in
    file)       : > "$SW" ;;
    dir)        mkdir -p "$SW" ;;
    dangling)   ln -s "$SANDBOX/nowhere-at-all" "$SW" ;;
    unreadable) : > "$SW"; chmod 000 "$SW" ;;
  esac
  fire
  chmod 600 "$SW" 2>/dev/null
  [ "$RC" = "0" ] && [ -z "$OUT" ] && [ ! -d "$LEDGERS" ] \
    && ok "global switch as a $shape: the actuator stops DECIDING (no stdout, no ledger)" \
    || bad "global switch as a $shape did not stop the actuator (rc=$RC out=[$OUT])"
  rm -rf "$SW"
done

reset
fire
case "$OUT" in
  *'"model":"haiku"'*) ok "control: with the switch removed it routes again -- section 3 is not vacuous" ;;
  *) bad "the actuator did not recover after the switch was removed: [$OUT]" ;;
esac

# The machine-wide one, which is honoured even if the install is unreachable.
reset
: > "$FAKE_HOME/.claude/jev-disabled"
fire
[ -z "$OUT" ] && [ ! -d "$LEDGERS" ] \
  && ok "machine-wide \$HOME/.claude/jev-disabled: stops routing in every project at once" \
  || bad "the machine-wide switch did not stop the actuator: [$OUT]"
rm -f "$FAKE_HOME/.claude/jev-disabled"

# ---------------------------------------------------------------------------
echo
echo "  4. SWITCH TWO -- the PER-PROJECT opt-out"
# ---------------------------------------------------------------------------
# "There will be repos where you do not want delegations re-routed." That is a
# different question from "stop jev everywhere", and before W2 there was no way
# to express it separately: the only switch was anchored on a root that was
# both at once.
for shape in file dir dangling; do
  reset
  SW="$PROJ/.jev-disabled"
  rm -rf "$SW"
  case "$shape" in
    file)     : > "$SW" ;;
    dir)      mkdir -p "$SW" ;;
    dangling) ln -s "$SANDBOX/nowhere-at-all" "$SW" ;;
  esac
  fire
  [ "$RC" = "0" ] && [ -z "$OUT" ] && [ ! -d "$LEDGERS" ] \
    && ok "per-project opt-out as a $shape: this repo is not routed, and jev is untouched elsewhere" \
    || bad "the per-project opt-out as a $shape did not stop the actuator (rc=$RC out=[$OUT])"
  rm -rf "$SW"
done

# The two are genuinely independent, which is the whole point of having two.
reset
: > "$PROJ/.jev-disabled"
[ -e "$HOME_DIR/.jev-disabled" ] \
  && bad "the fixture is wrong: the global switch is also set" \
  || ok "the per-project opt-out works with the GLOBAL switch demonstrably absent"
rm -f "$PROJ/.jev-disabled"

# ---------------------------------------------------------------------------
echo
echo "  5. \"THE SWITCH IS OFF\" IS NOT \"THE TOOL IS QUIESCENT\""
# ---------------------------------------------------------------------------
# The distinction JEV-51 was filed over, asserted rather than remembered.
reset
: > "$HOME_DIR/.jev-disabled"
fire
[ "$RC" = "0" ] && [ -z "$OUT" ] \
  && ok "with the switch set the hook still RUNS and still exits 0 -- a process per Agent call" \
  || bad "switched-off behaviour is not exit 0 with empty stdout (rc=$RC)"
[ ! -d "$HOME_DIR/data/agent_route" ] \
  && ok "...but decides nothing and writes nothing: that is switched off, not quiescent" \
  || bad "a switched-off actuator still wrote to data/agent_route"
rm -f "$HOME_DIR/.jev-disabled"

# Quiescent is a different act, and only uninstall reaches it.
"$REPOROOT/jev" install "$PROJ" --yes >/dev/null 2>&1
"$REPOROOT/jev" status "$PROJ" 2>&1 | grep -q "INSTALLED" \
  && ok "a switched-off install still REPORTS as installed -- the hook is still registered" \
  || bad "status does not report an installed-but-switched-off repo as installed"
"$REPOROOT/jev" uninstall "$PROJ" --yes >/dev/null 2>&1
"$REPOROOT/jev" status "$PROJ" 2>&1 | grep -q "not installed here" \
  && ok "after uninstall nothing is registered: no hook, no process, quiescent" \
  || bad "status still reports an installed hook after uninstall"
rm -f "$PROJ/.jev-disabled"

echo
echo "  ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ] || exit 1
