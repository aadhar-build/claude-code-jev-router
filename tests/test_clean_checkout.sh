#!/bin/bash
# JEV-56. THE SUITE MUST GO GREEN ON A CLEAN CHECKOUT, AND THIS PROVES IT.
#
# `tests/reversibility.sh` could not. Four of its gates needed
# `.claude/settings.local.json`, which is gitignored BY DESIGN so that a live
# hook registration never travels to a clone or a cloud session. The gates were
# failing CORRECTLY -- each guards against passing vacuously on an empty set --
# and the two requirements were individually right and jointly unsatisfiable.
# You cannot distribute a tool whose suite cannot go green from a fresh clone.
#
# The fix was to materialise a fixture registration with the REAL installer when
# no live one exists. This file is what stops that fix silently rotting: it
# builds an actual clean checkout -- every tracked file, nothing ignored, so no
# `.claude/settings.local.json` and no `.jev-disabled` -- and runs the gate
# there.
#
# It is deliberately not a re-implementation of the check. It runs the real
# gate, in the condition that used to break it, and requires the same exit code
# a human would look for.
#
# Offline. Reads the repo, writes only to its own throwaway directory.

REPOROOT="$(cd "$(dirname "$0")/.." && pwd -P)"

pass=0; fail=0
ok()  { echo "  ok    $1"; pass=$((pass+1)); }
bad() { echo "  FAIL  $1"; fail=$((fail+1)); }

SANDBOX="$(mktemp -d)"
SANDBOX="$(cd "$SANDBOX" && pwd -P)"
CLEAN="$SANDBOX/checkout"
cleanup() { chmod -R u+rwX "$SANDBOX" 2>/dev/null; rm -rf "$SANDBOX"; }
trap cleanup EXIT
mkdir -p "$CLEAN"

echo
echo "=============================================================="
echo " JEV-56 -- the reversibility gate, run on a CLEAN CHECKOUT"
echo "=============================================================="
echo

# Every file git knows about, plus the files that are new and not ignored --
# which is what a commit of the current tree would produce. Nothing that
# .gitignore excludes, which is the whole point: that set is exactly what a
# clone gets, and it is missing the registration.
LIST="$SANDBOX/files.z"
( cd "$REPOROOT" && git ls-files -z > "$LIST" \
  && git ls-files --others --exclude-standard -z >> "$LIST" ) || {
  bad "could not enumerate the tracked files (is this a git checkout?)"
  echo; echo "  ${pass} passed, ${fail} failed"; exit 1; }

( cd "$REPOROOT" && tar --null -T "$LIST" -cf - ) | ( cd "$CLEAN" && tar -xf - ) || {
  bad "could not materialise a clean checkout"
  echo; echo "  ${pass} passed, ${fail} failed"; exit 1; }

# The two absences that define "clean" here. Asserted, because if either one
# were present the run below would prove nothing -- it would just be the live
# path again, under a different name.
[ ! -e "$CLEAN/.claude/settings.local.json" ] \
  && ok "the clean checkout has NO .claude/settings.local.json (gitignored by design)" \
  || bad "the clean checkout has a registration -- this test would be vacuous"
[ ! -e "$CLEAN/.jev-disabled" ] \
  && ok "the clean checkout has NO .jev-disabled (also gitignored, also local)" \
  || bad "the clean checkout carries a kill switch"
[ -x "$CLEAN/jev" ] \
  && ok "the clean checkout carries the \`jev\` CLI, which is what materialises the fixture" \
  || bad "no executable jev in the clean checkout -- the fixture cannot be built"
[ -f "$CLEAN/config/registration.json" ] \
  && ok "and config/registration.json, the committed description of what it registers" \
  || bad "config/registration.json is not in the clean checkout"

echo
out="$( cd "$CLEAN" && bash tests/reversibility.sh 2>&1 )"; rc=$?

if [ "$rc" = "0" ]; then
  ok "THE CLAIM: tests/reversibility.sh is GREEN on a clean checkout (exit 0)"
else
  bad "tests/reversibility.sh FAILED on a clean checkout (exit $rc)"
  printf '%s\n' "$out" | grep -E "FAIL" | sed 's/^/          /'
fi

case "$out" in
  *"FIXTURE registration"*)
    ok "...and it says so: the proof was made against the installer's registration, not the operator's" ;;
  *) bad "the gate did not report which registration it tested" ;;
esac

# Not vacuous: a run that enumerated nothing must still be a failure. The gate
# reports its own count, so this reads it rather than trusting the exit code.
n=$(printf '%s\n' "$out" | sed -n 's/^ *\([0-9][0-9]*\) passed.*/\1/p' | tail -1)
[ -n "$n" ] && [ "$n" -gt 30 ] \
  && ok "the clean-checkout run asserted $n gates, not a handful -- it is the whole file" \
  || bad "the clean-checkout run only reported '$n' passing gates"
printf '%s\n' "$out" | grep -q "enumerated 0 registered" \
  && bad "the gate enumerated an EMPTY registration and still passed" \
  || ok "the registration it enumerated was not empty"

echo
echo "  ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ] || exit 1
