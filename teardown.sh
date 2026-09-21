#!/bin/bash
# JEV-40. The one command that returns this machine to stock Claude Code.
#
#   ./teardown.sh --dry-run    # show exactly what would change
#   ./teardown.sh --yes        # do it
#
# It does two things, in this order:
#
#   1. Sets the kill switch (`.jev-disabled`), which every hook script tests
#      before doing anything else. This takes effect on the NEXT hook
#      invocation, in already-running sessions, with no restart -- verified
#      live on 2026-09-20 and re-asserted by tests/reversibility.sh.
#   2. Unregisters the hooks by moving `.claude/settings.local.json` aside to a
#      timestamped `.disabled-<ts>` file. Moved, not deleted, so the decision is
#      reversible and the restore command can be printed.
#
# Step 1 before step 2 deliberately: the switch is the guaranteed path. The
# documentation says direct edits to settings files are "normally picked up
# automatically by the file watcher", and "normally" is not a guarantee, so the
# switch goes on first and the unregistration follows.
#
# `--yes` is required. A teardown that can happen by accident -- from a stray
# test, a tab-complete, an agent being helpful -- is its own kind of hazard in a
# folder where a running worker is mid-collection.

set -u
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
SETTINGS="$ROOT/.claude/settings.local.json"
SWITCH="$ROOT/.jev-disabled"
STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
PARKED="$SETTINGS.disabled-$STAMP"

MODE=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) MODE="dry" ;;
    --yes|-y)  MODE="go" ;;
    *) echo "usage: $0 {--dry-run|--yes}" >&2; exit 2 ;;
  esac
done
if [ -z "$MODE" ]; then
  echo "usage: $0 {--dry-run|--yes}" >&2
  echo "  --dry-run  print what would change and change nothing" >&2
  echo "  --yes      actually tear down" >&2
  exit 2
fi

say() { printf '%s\n' "$1"; }

say ""
say "jev teardown — $ROOT"
say ""

if [ "$MODE" = "dry" ]; then
  say "DRY RUN. Nothing below has been done."
  say ""
fi

# --- 1. the switch ----------------------------------------------------------
if [ -e "$SWITCH" ] || [ -L "$SWITCH" ]; then
  say "  switch      already set ($SWITCH)"
elif [ "$MODE" = "dry" ]; then
  say "  switch      would create $SWITCH"
else
  if : > "$SWITCH" 2>/dev/null; then
    say "  switch      created $SWITCH — every hook now exits on line one"
  else
    say "  switch      COULD NOT CREATE $SWITCH — fix this before relying on it"
  fi
fi

# --- 2. the registration ----------------------------------------------------
RESTORE=""
if [ ! -f "$SETTINGS" ]; then
  say "  hooks       not registered (no .claude/settings.local.json) — nothing to do"
elif [ "$MODE" = "dry" ]; then
  say "  hooks       would move $SETTINGS"
  say "              to       $PARKED"
else
  if mv "$SETTINGS" "$PARKED" 2>/dev/null; then
    say "  hooks       unregistered; registration parked at"
    say "              $PARKED"
    RESTORE="mv '$PARKED' '$SETTINGS'"
  else
    say "  hooks       COULD NOT MOVE $SETTINGS — the hooks are still registered"
  fi
fi

say ""
say "  What this DOES undo"
say "    - hooks firing. Both the switch and the unregistration stop them. The"
say "      switch takes effect at the NEXT hook invocation, including in a"
say "      session that is already running; a hook already in flight finishes."
say "    - anything this folder would have collected from here on."
say ""
say "  What this DOES NOT undo"
say "    - data already collected. It is all under $ROOT (data/, spool/, logs/,"
say "      reports/). Delete the folder to remove it; this command will not."
say "    - your .env. Untouched."
say "    - configuration outside this folder. There is none to undo: nothing is"
say "      ever written to ~/.claude/settings.json or anywhere else outside"
say "      this folder. \`uv run src/doctor.py\` asserts that."
say "    - work already produced by a routed model, and the 'delegate where"
say "      possible' working rule. Neither is a program state and no flag"
say "      reverses either. See the table in ISSUES.md, JEV-40."
say ""
say "  Scope"
say "    This stops THESE hooks, because THESE scripts test the switch. It is"
say "    not enforced by Claude Code. The harness-native equivalent, which"
say "    stops every hook from every source, is \"disableAllHooks\": true in a"
say "    settings file, or --settings '{\"disableAllHooks\": true}' for one run."
say ""
if [ "$MODE" = "dry" ]; then
  say "  Run again with --yes to apply."
else
  say "  To undo this teardown:"
  [ -n "$RESTORE" ] && say "    $RESTORE"
  say "    rm '$SWITCH'"
fi
say ""
exit 0
