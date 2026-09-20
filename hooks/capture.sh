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

ROOT="${CLAUDE_PROJECT_DIR:-}"
[ -n "$ROOT" ] || exit 0
[ -d "$ROOT" ] || exit 0

# Kill switch. Anchored, not cwd-relative: a hook fires with whatever cwd the
# session happens to have, and a relative test silently stops working the moment
# you cd into a subdirectory.
[ -f "$ROOT/.jev-disabled" ] && exit 0

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
