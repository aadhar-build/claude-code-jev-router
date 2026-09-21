#!/bin/bash
# W2. `jev install` / `jev uninstall` -- opt-in per project, and removable.
#
# The question this file exists to answer is not "does install write a file".
# It is: **can this be taken back out of somebody else's repo without touching
# anything that is not ours?** Merging into a settings file we do not own is
# where this breaks, so that is what is tested hardest:
#
#   1. a target with UNRELATED hooks, permissions and env survives exactly
#   2. install -> uninstall is BYTE-IDENTICAL when nothing else changed
#   3. install -> user edits -> uninstall keeps the user's edit and says
#      plainly that the guarantee is now the weaker one
#   4. the verifier is not vacuous: shown a removal that took somebody else's
#      handler, it reports it
#   5. every refusal refuses WHOLE -- nothing half-written
#   6. the switch is set BEFORE the unregistration, and left behind
#
# Everything runs in a throwaway directory. The live repo's own
# .claude/settings.local.json and .jev-disabled are sha-checked before and
# after: neither is a file this test may touch, and neither is covered by
# tests/audit_live_writes.sh, which watches spool/, data/ and logs/.
#
# Offline. No network, no spend, no API key.

REPOROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
JEV="$REPOROOT/jev"

pass=0; fail=0
ok()  { echo "  ok    $1"; pass=$((pass+1)); }
bad() { echo "  FAIL  $1"; fail=$((fail+1)); }

sha() { if [ -f "$1" ]; then shasum -a 256 "$1" | awk '{print $1}'; else echo "ABSENT"; fi; }

LIVE_SETTINGS="$REPOROOT/.claude/settings.local.json"
LIVE_SWITCH="$REPOROOT/.jev-disabled"
LIVE_SETTINGS_BEFORE="$(sha "$LIVE_SETTINGS")"
LIVE_SWITCH_BEFORE="$(sha "$LIVE_SWITCH")"
USER_SETTINGS="$HOME/.claude/settings.json"
USER_SETTINGS_BEFORE="$(sha "$USER_SETTINGS")"

SANDBOX="$(mktemp -d)"
SANDBOX="$(cd "$SANDBOX" && pwd -P)"
cleanup() { chmod -R u+rwX "$SANDBOX" 2>/dev/null; rm -rf "$SANDBOX"; }
trap cleanup EXIT

echo
echo "=============================================================="
echo " jev install / uninstall -- opt-in per project, and removable"
echo "=============================================================="

# A target repo whose settings file is emphatically NOT ours: another hook on
# another matcher, a permissions block, an env block, and a key we have never
# heard of. Every one of them must come back exactly.
mkrepo() { # <name> -> echoes the repo path
  local d="$SANDBOX/$1"
  mkdir -p "$d/.claude"
  cat > "$d/.claude/settings.local.json" <<'EOF'
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": { "allow": ["Bash(ls:*)", "Read(//tmp/**)"], "deny": [] },
  "env": { "SOMEONE_ELSES_VAR": "1" },
  "a_key_jev_has_never_heard_of": { "nested": [1, 2, {"deep": true}] },
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash",
        "hooks": [ { "type": "command", "command": "their-own-hook.sh", "timeout": 3 } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command", "command": "their-stop-hook.sh" } ] }
    ]
  }
}
EOF
  printf '%s' "$d"
}

# ---------------------------------------------------------------------------
echo
echo "  1. INSTALL into a repo that is not ours"
# ---------------------------------------------------------------------------
R1="$(mkrepo r1)"
cp "$R1/.claude/settings.local.json" "$SANDBOX/r1-original.json"

"$JEV" install "$R1" --dry-run >/dev/null 2>&1; rc=$?
[ "$rc" = "0" ] && ok "install --dry-run exits 0" || bad "install --dry-run exit $rc"
[ "$(sha "$R1/.claude/settings.local.json")" = "$(sha "$SANDBOX/r1-original.json")" ] \
  && ok "install --dry-run changed nothing" || bad "install --dry-run modified the file"
[ -e "$R1/.claude/jev-install.json" ] && bad "install --dry-run left a record behind" \
                                      || ok "install --dry-run left no record behind"

"$JEV" install "$R1" >/dev/null 2>&1; rc=$?
[ "$rc" = "2" ] && ok "install refuses without --yes (exit 2), as teardown.sh does" \
               || bad "install ran without confirmation (exit $rc)"

"$JEV" install "$R1" --yes >/dev/null 2>&1; rc=$?
[ "$rc" = "0" ] && ok "install --yes exits 0" || bad "install --yes exit $rc"

python3 - "$R1/.claude/settings.local.json" "$SANDBOX/r1-original.json" <<'PY'
import json, sys
got = json.load(open(sys.argv[1])); was = json.load(open(sys.argv[2]))
problems = []
# Everything that is not "hooks" must be identical, value for value.
for k, v in was.items():
    if k == "hooks":
        continue
    if got.get(k) != v:
        problems.append(f"top-level key {k!r} changed")
for k in got:
    if k not in was:
        problems.append(f"top-level key {k!r} appeared")
# Their hooks must all still be there, unchanged.
def handlers(d):
    out = []
    for ev, groups in (d.get("hooks") or {}).items():
        for g in groups:
            for h in g.get("hooks", []):
                out.append((ev, g.get("matcher"), json.dumps(h, sort_keys=True)))
    return out
theirs = [h for h in handlers(was)]
mine = handlers(got)
for h in theirs:
    if h not in mine:
        problems.append(f"an unrelated hook was lost or altered: {h}")
ours = [h for h in mine if h not in theirs]
if len(ours) != 1:
    problems.append(f"expected exactly one new handler, got {len(ours)}")
elif "agent_route_actuator.sh" not in ours[0][2]:
    problems.append(f"the new handler is not ours: {ours[0]}")
elif ours[0][1] != "Agent":
    problems.append(f"the new handler is on matcher {ours[0][1]!r}, not Agent")
print("\n".join(problems))
sys.exit(1 if problems else 0)
PY
[ $? = 0 ] && ok "unrelated hooks, permissions, env and unknown keys all survive the merge" \
           || bad "the merge damaged something that was not ours"

grep -q '"matcher": "Agent"' "$R1/.claude/settings.local.json" \
  && ok "jev's entry is registered on matcher Agent" \
  || bad "no Agent matcher in the written file"
grep -q "$REPOROOT/hooks/agent_route_actuator.sh" "$R1/.claude/settings.local.json" \
  && ok "the registered command is an ABSOLUTE path into JEV_HOME (a foreign repo cannot anchor on \$CLAUDE_PROJECT_DIR)" \
  || bad "the registered command does not point at this jev install"

before2="$(sha "$R1/.claude/settings.local.json")"
"$JEV" install "$R1" --yes >/dev/null 2>&1; rc=$?
[ "$rc" = "0" ] && [ "$(sha "$R1/.claude/settings.local.json")" = "$before2" ] \
  && ok "install is idempotent: a second run changes not one byte" \
  || bad "a second install changed the file (rc=$rc)"

# ---------------------------------------------------------------------------
echo
echo "  2. UNINSTALL -- byte-identical when nothing else changed (tier A)"
# ---------------------------------------------------------------------------
out=$("$JEV" uninstall "$R1" --dry-run 2>&1); rc=$?
[ "$rc" = "0" ] && ok "uninstall --dry-run exits 0" || bad "uninstall --dry-run exit $rc"
[ "$(sha "$R1/.claude/settings.local.json")" = "$before2" ] \
  && ok "uninstall --dry-run changed nothing" || bad "uninstall --dry-run modified the file"
[ -e "$R1/.jev-disabled" ] && bad "uninstall --dry-run set the switch" \
                          || ok "uninstall --dry-run did not set the switch"
case "$out" in
  *"BYTE-REVERSIBLE"*) ok "uninstall --dry-run forecasts which guarantee applies" ;;
  *) bad "uninstall --dry-run does not say which reversal tier would apply" ;;
esac

"$JEV" uninstall "$R1" >/dev/null 2>&1; rc=$?
[ "$rc" = "2" ] && ok "uninstall refuses without --yes (exit 2)" \
               || bad "uninstall ran without confirmation (exit $rc)"

out=$("$JEV" uninstall "$R1" --yes 2>&1); rc=$?
[ "$rc" = "0" ] && ok "uninstall --yes exits 0" || bad "uninstall --yes exit $rc"

# THE CLAIM: byte for byte, the file we found.
if cmp -s "$R1/.claude/settings.local.json" "$SANDBOX/r1-original.json"; then
  ok "THE CLAIM: after uninstall the settings file is BYTE-IDENTICAL to the one install found"
else
  bad "the settings file is not byte-identical to the original"
fi
case "$out" in
  *"BYTE-REVERSIBLE"*) ok "uninstall reports the guarantee it actually achieved" ;;
  *) bad "uninstall did not name its reversal tier" ;;
esac
case "$out" in
  *RESTORING*) ok "it restored the install-time bytes rather than editing (teardown.sh's guarantee, intact)" ;;
  *) bad "uninstall edited the file when it could have restored it" ;;
esac

# The switch, and the ordering that is the whole reason for it.
[ -f "$R1/.jev-disabled" ] \
  && ok "uninstall set the per-project switch and LEFT it (the file watcher is not a guarantee)" \
  || bad "uninstall did not leave the switch behind"
case "$out" in
  *"rm '$R1/.jev-disabled'"*) ok "and printed the one command that removes it" ;;
  *) bad "the switch is set and the way to clear it was not printed" ;;
esac
case "$out" in
  *QUIESCENT*) ok "uninstall states the difference between 'the switch is set' and 'no process is spawned'" ;;
  *) bad "uninstall does not distinguish switched-off from quiescent" ;;
esac
case "$out" in
  *"routed model"*) ok "uninstall names the part that is not reversible at all" ;;
  *) bad "uninstall omits the irreversible part" ;;
esac
ls "$R1/.claude/settings.local.json.jev-backup-"* >/dev/null 2>&1 \
  && ok "a verbatim backup of the file as uninstall found it is left on disk" \
  || bad "no verbatim backup was left"
[ -e "$R1/.claude/jev-install.json" ] && bad "the install record survived uninstall" \
                                     || ok "the install record is gone"

out=$("$JEV" uninstall "$R1" --yes 2>&1); rc=$?
[ "$rc" = "0" ] && cmp -s "$R1/.claude/settings.local.json" "$SANDBOX/r1-original.json" \
  && ok "uninstall is idempotent: a second run says so and changes nothing" \
  || bad "a second uninstall was not a no-op (rc=$rc)"

# ---------------------------------------------------------------------------
echo
echo "  3. A TARGET WITH NO SETTINGS FILE -- uninstall must leave no trace"
# ---------------------------------------------------------------------------
R2="$SANDBOX/r2"; mkdir -p "$R2"
"$JEV" install "$R2" --yes >/dev/null 2>&1; rc=$?
[ "$rc" = "0" ] && [ -f "$R2/.claude/settings.local.json" ] \
  && ok "install creates .claude/ and the settings file when there is none" \
  || bad "install into a bare repo failed (rc=$rc)"
"$JEV" uninstall "$R2" --yes >/dev/null 2>&1; rc=$?
[ "$rc" = "0" ] && [ ! -e "$R2/.claude/settings.local.json" ] \
  && ok "uninstall REMOVES the file jev created -- there is nothing left to be identical to" \
  || bad "uninstall left a settings file jev had created (rc=$rc)"

# ---------------------------------------------------------------------------
echo
echo "  4. THE WEAKER CASE -- the user edited the file after install (tier B)"
# ---------------------------------------------------------------------------
R3="$(mkrepo r3)"
"$JEV" install "$R3" --yes >/dev/null 2>&1
# The user adds a hook of their own, after we installed. Tier A is now the
# WRONG answer: restoring the install-time bytes would silently revert them.
python3 - "$R3/.claude/settings.local.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["hooks"].setdefault("PostToolUse", []).append(
    {"matcher": "Write", "hooks": [{"type": "command", "command": "their-new-hook.sh"}]})
d["env"]["ADDED_LATER"] = "yes"
json.dump(d, open(p, "w"), indent=2)
PY
cp "$R3/.claude/settings.local.json" "$SANDBOX/r3-edited.json"

out=$("$JEV" uninstall "$R3" --yes 2>&1); rc=$?
[ "$rc" = "0" ] && ok "uninstall after a user edit exits 0" || bad "tier B uninstall exit $rc"
case "$out" in
  *"STRUCTURALLY VERIFIED"*) ok "it says plainly that the guarantee is now the weaker one" ;;
  *) bad "tier B did not announce itself as weaker than byte-identity" ;;
esac
case "$out" in
  *"BYTE-REVERSIBLE"*) bad "tier B claimed byte-reversibility it cannot have" ;;
  *) ok "and does NOT claim byte-reversibility" ;;
esac
python3 - "$R3/.claude/settings.local.json" "$SANDBOX/r3-edited.json" <<'PY'
import json, sys
got = json.load(open(sys.argv[1])); was = json.load(open(sys.argv[2]))
problems = []
if got.get("env", {}).get("ADDED_LATER") != "yes":
    problems.append("the user's later env edit was reverted")
post = (got.get("hooks") or {}).get("PostToolUse")
if not post or "their-new-hook.sh" not in json.dumps(post):
    problems.append("the user's later hook was reverted")
if "agent_route_actuator.sh" in json.dumps(got):
    problems.append("a jev entry survived the uninstall")
for k, v in was.items():
    if k != "hooks" and got.get(k) != v:
        problems.append(f"top-level key {k!r} changed")
print("\n".join(problems))
sys.exit(1 if problems else 0)
PY
[ $? = 0 ] && ok "the user's post-install edits survive, and every jev entry is gone" \
           || bad "tier B damaged or reverted the user's own changes"

# ---------------------------------------------------------------------------
echo
echo "  4b. THE ORDINARY CASE -- the user's own hook is on PreToolUse (W5)"
# ---------------------------------------------------------------------------
# The arrangement §4 above did NOT test, and the one defect it hid.
#
# §4 adds the user's hook under PostToolUse, which is the one arrangement where
# PreToolUse's group order is unperturbed -- so the weaker tier was tested only
# where it worked. Add a PreToolUse hook instead (the single most likely thing a
# user does after installing) and jev's group, which `merge_entries` always
# APPENDS, is no longer last. Check 3 used to compare the re-install
# POSITIONALLY, so it fired on a removal that was entirely correct, uninstall
# restored the backup and stopped -- and left jev REGISTERED. Quiescence is the
# one thing uninstall exists to deliver, so this is the case that matters most.
R7="$SANDBOX/r7"; mkdir -p "$R7"
"$JEV" install "$R7" --yes >/dev/null 2>&1
python3 - "$R7/.claude/settings.local.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
# Appended AFTER jev's group, which is what makes the original order
# unreconstructable: re-installing puts ours back at the end, not the front.
d["hooks"].setdefault("PreToolUse", []).append(
    {"matcher": "Write", "hooks": [{"type": "command", "command": "their-own-hook.sh"}]})
json.dump(d, open(p, "w"), indent=2)
PY
out=$("$JEV" uninstall "$R7" --yes 2>&1); rc=$?
[ "$rc" = "0" ] \
  && ok "THE W5 CASE: uninstall succeeds when the user's own hook is on PreToolUse" \
  || bad "uninstall aborted on the ordinary PreToolUse arrangement (rc=$rc): $out"
case "$out" in
  *"THE REST OF THE FILE IS NOT WHAT IT WAS"*)
    bad "the verifier fired spuriously on a correct removal" ;;
  *) ok "...and the verifier did not fire on a correct removal" ;;
esac
case "$out" in
  *"STRUCTURALLY VERIFIED"*) ok "it is still tier B, still named, still not claiming byte-identity" ;;
  *) bad "the PreToolUse case did not name its tier" ;;
esac
grep -q "agent_route_actuator.sh" "$R7/.claude/settings.local.json" \
  && bad "THE DEFECT: uninstall exited but left jev REGISTERED -- silent, not quiescent" \
  || ok "QUIESCENT: no jev entry is left registered, so no jev process is spawned at all"
grep -q "their-own-hook.sh" "$R7/.claude/settings.local.json" \
  && ok "and the user's own PreToolUse hook is untouched" \
  || bad "the user's own PreToolUse hook was lost"
"$JEV" status "$R7" 2>&1 | grep -q "not installed here" \
  && ok "jev status agrees: nothing is registered here any more" \
  || bad "status still reports an installed hook after the PreToolUse-case uninstall"

# ---------------------------------------------------------------------------
echo
echo "  5. THE VERIFIER IS NOT VACUOUS"
# ---------------------------------------------------------------------------
# A check computed by the same code that made the change proves only that the
# code is self-consistent. So: hand the verifier a removal that took somebody
# else's handler with it, and require it to say so. Without this, every "ok"
# in section 4 could be produced by a verifier that always returns clean.
python3 - "$REPOROOT" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1] + "/src")
import install as I

cmd = str((I.paths.ROOT / "hooks/agent_route_actuator.sh").resolve())
before = {
  "permissions": {"allow": ["Bash(ls:*)"]},
  "hooks": {"PreToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "theirs.sh"}]},
      {"matcher": "Agent", "hooks": [{"type": "command", "command": cmd, "timeout": 10}]}]}}

clean, removed = I.split_hooks(before)
assert len(removed) == 1, removed
if I.verify_removal(before, clean):
    print("FALSE POSITIVE: a correct removal was reported as damage"); sys.exit(1)

# (a) their hook taken out along with ours
greedy = {"permissions": before["permissions"]}
if not I.verify_removal(before, greedy):
    print("MISSED: an unrelated hook was removed and the verifier said nothing"); sys.exit(1)

# (b) a value outside "hooks" quietly changed
tampered = json.loads(json.dumps(clean))
tampered["permissions"]["allow"] = ["Bash(rm:*)"]
probs = I.verify_removal(before, tampered)
if not any("outside" in p for p in probs):
    print("MISSED: a change outside \"hooks\" was not reported:", probs); sys.exit(1)

# (c) a handler appearing that was never there
extra = json.loads(json.dumps(clean))
extra["hooks"]["PreToolUse"].append(
    {"matcher": "Read", "hooks": [{"type": "command", "command": "surprise.sh"}]})
if not I.verify_removal(before, extra):
    print("MISSED: a handler appeared from nowhere and the verifier said nothing"); sys.exit(1)

# (d) our entry left in place while claiming removal
if not I.verify_removal(before, before):
    print("MISSED: nothing was removed at all and the verifier said nothing"); sys.exit(1)

# ---------------------------------------------------------------------------
# W5. The order question, at unit level. Check 3 was made order-INSENSITIVE
# across the groups of one event, because `merge_entries` appends ours at the
# end and the original position is not reconstructable. The order that DOES
# matter -- the user's own groups relative to each other -- is still exact, and
# these two cases are what keeps the relaxation honest.
ordered = {"hooks": {"PreToolUse": [
    {"matcher": "Agent", "hooks": [{"type": "command", "command": cmd, "timeout": 10}]},
    {"matcher": "Bash",  "hooks": [{"type": "command", "command": "a.sh"}]},
    {"matcher": "Read",  "hooks": [{"type": "command", "command": "b.sh"}]}]}}
clean_o, rem_o = I.split_hooks(ordered)
assert len(rem_o) == 1, rem_o
probs = I.verify_removal(ordered, clean_o)
if probs:
    print("FALSE POSITIVE: ours sitting FIRST in PreToolUse is reported as damage:",
          probs); sys.exit(1)

# (e) the user's own groups reordered rather than merely stripped -- order that
#     genuinely matters is still checked, and exactly.
swapped = {"hooks": {"PreToolUse": [
    {"matcher": "Read", "hooks": [{"type": "command", "command": "b.sh"}]},
    {"matcher": "Bash", "hooks": [{"type": "command", "command": "a.sh"}]}]}}
if not I.verify_removal(ordered, swapped):
    print("MISSED: the user's own groups were reordered and the verifier said nothing")
    sys.exit(1)

# (f) a LOOKALIKE removed. The command merely CONTAINS one of our script names;
#     it is not ours, it must survive the strip, and a removal of it must be
#     reported by a check that does NOT consult the stripper's own predicate.
look = "/my/own/hooks/agent_route_actuator.sh --mine"
if I.is_ours(look):
    print("OWNERSHIP IS STILL A SUBSTRING MATCH: a foreign command claimed as ours")
    sys.exit(1)
if not I.is_ours(cmd):
    print("OWNERSHIP IS BROKEN: our own entry is not recognised"); sys.exit(1)
mixed = {"hooks": {"PreToolUse": [
    {"matcher": "Write", "hooks": [{"type": "command", "command": look}]},
    {"matcher": "Agent", "hooks": [{"type": "command", "command": cmd, "timeout": 10}]}]}}
clean_m, rem_m = I.split_hooks(mixed)
if len(rem_m) != 1 or look not in json.dumps(clean_m):
    print("THE SUBSTRING DEFECT: split_hooks took somebody else's lookalike:", rem_m)
    sys.exit(1)
if I.verify_removal(mixed, clean_m):
    print("FALSE POSITIVE on the lookalike case"); sys.exit(1)
if not I.verify_removal(mixed, {}):
    print("MISSED: the lookalike was removed too and check 2 blessed it -- the")
    print("verifier is still using the stripper's own ownership predicate")
    sys.exit(1)
PY
[ $? = 0 ] && ok "the removal verifier catches a greedy removal, a silent edit, an inserted handler, a no-op, a reorder and a lookalike removal" \
           || bad "the removal verifier is vacuous -- it does not catch damage it is meant to catch"

# ---------------------------------------------------------------------------
echo
echo "  6. REFUSALS -- whole, never half"
# ---------------------------------------------------------------------------
R4="$SANDBOX/r4"; mkdir -p "$R4/.claude"
printf '{ this is not json' > "$R4/.claude/settings.local.json"
b="$(sha "$R4/.claude/settings.local.json")"
out=$("$JEV" install "$R4" --yes 2>&1); rc=$?
[ "$rc" = "1" ] && ok "install REFUSES a settings file that is not valid JSON (exit 1)" \
               || bad "install did not refuse unparseable JSON (exit $rc)"
[ "$(sha "$R4/.claude/settings.local.json")" = "$b" ] \
  && ok "...and changed nothing: merging into a file we cannot parse is how a setting gets silently dropped" \
  || bad "install modified a file it could not parse"
ls "$R4/.claude/"*jev-backup* >/dev/null 2>&1 && bad "a refusal still left a backup behind" \
                                              || ok "a refusal leaves no partial state at all"

out=$("$JEV" install "$SANDBOX/does-not-exist" --yes 2>&1); rc=$?
[ "$rc" = "1" ] && ok "install refuses a target directory that does not exist" \
               || bad "install into a missing directory exited $rc"

R5="$SANDBOX/r5"; mkdir -p "$R5/.claude"
printf '{"hooks":{}}\n' > "$SANDBOX/elsewhere.json"
ln -s "$SANDBOX/elsewhere.json" "$R5/.claude/settings.local.json"
eb="$(sha "$SANDBOX/elsewhere.json")"
out=$("$JEV" install "$R5" --yes 2>&1); rc=$?
[ "$rc" = "1" ] && [ "$(sha "$SANDBOX/elsewhere.json")" = "$eb" ] \
  && ok "install refuses a SYMLINKED settings file rather than writing through it" \
  || bad "install followed a symlink (exit $rc)"

R6="$SANDBOX/r6"; mkdir -p "$R6/.claude"
printf '{"hooks": []}\n' > "$R6/.claude/settings.local.json"
out=$("$JEV" install "$R6" --yes 2>&1); rc=$?
[ "$rc" = "1" ] && ok "install refuses a \"hooks\" key that is an array, not an object" \
               || bad "install accepted a malformed hooks key (exit $rc)"

# ---------------------------------------------------------------------------
echo
echo "  6b. SOMEBODY ELSE'S HOOK THAT SHARES OUR FILENAME (W5)"
# ---------------------------------------------------------------------------
# Ownership used to be `e["script"] in command` -- a SUBSTRING test. A stranger
# with their own /my/own/hooks/agent_route_actuator.sh on matcher `Write` had it
# DELETED by `jev install`, and install's output never mentioned it: it survived
# only in the backup. Low likelihood, and silent data loss in somebody else's
# repository, which is the category that matters most for a tool people install.
R8="$SANDBOX/r8"; mkdir -p "$R8/.claude"
LOOKALIKE="/my/own/hooks/agent_route_actuator.sh --mine"
cat > "$R8/.claude/settings.local.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Write",
        "hooks": [ { "type": "command", "command": "$LOOKALIKE" } ] }
    ]
  }
}
EOF
out=$("$JEV" install "$R8" --yes 2>&1); rc=$?
[ "$rc" = "0" ] && ok "install into a repo holding a lookalike exits 0" \
                || bad "install exit $rc"
grep -q -- "--mine" "$R8/.claude/settings.local.json" \
  && ok "THE CLAIM: a foreign handler that merely NAMES one of our scripts survives install" \
  || bad "SILENT DATA LOSS: install deleted somebody else's hook that shares our filename"
case "$out" in
  *"NOT OURS"*) ok "...and install says so OUT LOUD rather than leaving it to the backup" ;;
  *) bad "install noticed nothing: a near-miss on ownership was not reported" ;;
esac
case "$out" in
  *"REPLACING"*) bad "install claimed to replace a handler that is not ours" ;;
  *) ok "and does not claim it as a stale entry of ours" ;;
esac
out=$("$JEV" uninstall "$R8" --yes 2>&1); rc=$?
[ "$rc" = "0" ] && ok "uninstall of that repo exits 0" || bad "uninstall exit $rc: $out"
grep -q -- "--mine" "$R8/.claude/settings.local.json" \
  && ok "and the lookalike survives uninstall too -- it was never ours to remove" \
  || bad "uninstall deleted somebody else's lookalike hook"
grep -q "$REPOROOT/hooks/agent_route_actuator.sh" "$R8/.claude/settings.local.json" \
  && bad "our own entry survived the uninstall" \
  || ok "while our own entry, matched by its EXACT absolute path, is gone"

# ---------------------------------------------------------------------------
echo
echo "  7. NOTHING OUTSIDE THE TARGET REPO, EVER"
# ---------------------------------------------------------------------------
[ "$(sha "$USER_SETTINGS")" = "$USER_SETTINGS_BEFORE" ] \
  && ok "~/.claude/settings.json is untouched -- non-negotiable 3, asserted not assumed" \
  || bad "~/.claude/settings.json CHANGED"
[ "$(sha "$LIVE_SETTINGS")" = "$LIVE_SETTINGS_BEFORE" ] \
  && ok "this repo's own .claude/settings.local.json is untouched (nothing here armed anything)" \
  || bad "THIS TEST MODIFIED THE LIVE REGISTRATION"
[ "$(sha "$LIVE_SWITCH")" = "$LIVE_SWITCH_BEFORE" ] \
  && ok "this repo's own kill switch is as we found it" \
  || bad "this test moved the live kill switch"
# The global file is named in the prose -- it is half the reason this module
# exists -- so the assertion has to be about WRITES, not about mentions.
python3 - "$REPOROOT/src/install.py" <<'PY' && ok "no write verb anywhere in src/install.py is aimed at \$HOME, ~/ or ~/.claude/settings.json" || bad "src/install.py can write outside the target repo"
import re, sys
bad = []
for i, line in enumerate(open(sys.argv[1]).read().splitlines(), 1):
    stripped = line.lstrip()
    if stripped.startswith("#"):
        continue
    if re.search(r"(write_bytes|write_text|open\s*\(|mkdir|unlink|replace|copyfile|copy2)"
                 r"[^\n]{0,120}(Path\.home|expanduser|\$HOME|~/)", line):
        bad.append(f"{i}: {stripped[:100]}")
    # Path.home() has no business being constructed here at all.
    if "Path.home()" in line:
        bad.append(f"{i}: constructs a path under $HOME: {stripped[:100]}")
print("\n".join(bad))
sys.exit(1 if bad else 0)
PY

echo
echo "  ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ] || exit 1
