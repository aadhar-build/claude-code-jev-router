#!/bin/bash
# jev capture hook -- the ONLY thing on the critical path.
#
# It is a dumb spooler. No JSON parsing, no network, no config read beyond one
# [ -f ] kill-switch test. Python startup alone is 30-60ms, which is why nothing
# here is Python. Target: under 10ms, always.
#
# Fail-open is absolute: every path exits 0. A measurement harness must never be
# able to wedge an editing session. stdout stays empty -- Claude Code parses it,
# and a stray byte there is a permission decision we never intended to make.
#
# Usage: capture.sh <surface>            (hook payload arrives on stdin)

# The trap comes FIRST, before anything that can fail. `logs/` is gitignored,
# so on a fresh checkout it does not exist -- and a failed `exec` redirect
# would exit non-zero before any later trap could catch it. That is a fail-open
# violation caused by the very line meant to make failures visible.
trap 'exit 0' EXIT
# No `set -e`: a failure must skip the record, not abort with a nonzero status.

if [ -n "$CLAUDE_PROJECT_DIR" ] && [ -d "$CLAUDE_PROJECT_DIR/logs" ]; then
  exec 2>>"$CLAUDE_PROJECT_DIR/logs/capture.err"
else
  exec 2>/dev/null
fi

# Recursion guard. The cc_* arms shell out to `claude -p`, which starts a real
# Claude Code session -- one that would load this project's hooks and capture
# its own decisions straight back into the dataset. The worker exports this to
# every arm subprocess; env vars are inherited, so the guard holds however deep
# the spawn goes.
[ -n "$JEV_ARM_SUBPROCESS" ] && exit 0

ROOT="${CLAUDE_PROJECT_DIR:-}"
[ -n "$ROOT" ] || exit 0
[ -d "$ROOT" ] || exit 0

# --- jev kill switch: canonical block, byte-identical in every hook ----------
# One switch, all surfaces. `tests/reversibility.sh` enumerates the registered
# hooks and fails if any of them lacks this block, so a new surface cannot be
# added without it.
#
# Anchored on $ROOT, never cwd-relative: a hook fires with whatever cwd the
# session happens to have, and a relative test silently stops working the moment
# you cd into a subdirectory.
#
# FAIL SAFE (JEV-40): ANY entry at this path means OFF. `-f` alone reads a
# directory as absent, so an operator who ran `mkdir .jev-disabled` would
# believe the switch was set while the hook kept firing; `-e` alone reads a
# dangling symlink as absent. An unreadable file still stats, so it too reads as
# present. When the state of the switch cannot be established, the answer is
# OFF, not ON -- the switch is never given the benefit of the doubt.
{ [ -e "$ROOT/.jev-disabled" ] || [ -L "$ROOT/.jev-disabled" ]; } && exit 0
# --- end jev kill switch ----------------------------------------------------

# Defensive cwd guard. settings.local.json should never load outside this repo,
# but the isolation requirement is hard enough to be worth enforcing twice.
case "$PWD/" in
  "$ROOT"/*) ;;
  *) exit 0 ;;
esac

SURFACE="${1:-unknown}"
TMP="$ROOT/spool/tmp"
READY="$ROOT/spool/ready"
[ -d "$TMP" ] || exit 0
[ -d "$READY" ] || exit 0

# Backpressure: if the worker has fallen behind, stop writing rather than fill
# the disk. Counted with a glob rather than `ls | wc -l` to avoid a subshell.
set -- "$READY"/*.json
if [ "$#" -gt 500 ]; then
  # JEV-33. A refusal here used to be SILENT: no capture row, no run row, and
  # therefore no entry in the attrition count the pre-registration commits to
  # reporting -- a loss invisible to the measurement built to catch it. So
  # record it. Durably, under data/ rather than logs/, because attrition has to
  # outlive a log rotation.
  #
  # Cost is paid ONLY on this path, which is the rare one: two forks (mkdir,
  # date). The happy path below is untouched and still fork-free. bash 3.2 has
  # no EPOCHREALTIME and no printf %()T, so `date` is the only clock there is;
  # whole seconds are plenty for counting drops.
  #
  # Concurrency: several hooks can fire at once. One short line appended with
  # >> is a single O_APPEND write well under PIPE_BUF, so parallel writers
  # interleave cleanly rather than corrupting each other -- the same property
  # store.py relies on. Nothing is read, locked or rewritten.
  DROPS="$ROOT/data/drops"
  # `[ -d ]` is a builtin; the mkdir fork is paid once, on the first drop of a
  # fresh checkout, and never again.
  [ -d "$DROPS" ] || mkdir -p "$DROPS" 2>/dev/null || exit 0
  TS=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null) || exit 0
  printf '{"at":"%s","surface":"%s","reason":"spool_backpressure","ready_files":%s,"cap":500,"pid":%s}\n' \
    "$TS" "$SURFACE" "$#" "$$" >> "$DROPS/${TS%%T*}.jsonl" 2>/dev/null
  exit 0
fi

# No timestamp here: /bin/bash on macOS is 3.2 (no EPOCHREALTIME) and BSD date
# has no %N, so there is no sub-second clock available without spawning a
# process. The worker timestamps on pickup; hook cost is measured separately in
# a controlled loop by bench_inline.py.
ID="$$-${RANDOM}"
STAGED="$TMP/$ID"

cat > "$STAGED" || exit 0
[ -s "$STAGED" ] || { rm -f "$STAGED"; exit 0; }

# Surface travels as a filename prefix rather than inside the JSON, so the hook
# never has to parse or rewrite the payload.
mv -f "$STAGED" "$READY/${SURFACE}__${ID}.json" || rm -f "$STAGED"

exit 0
