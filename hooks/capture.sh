#!/bin/bash
# jev capture hook -- the ONLY thing on the critical path.
#
# It is a dumb spooler. No JSON parsing, no network, no config read beyond the
# kill-switch tests. Python startup alone is 30-60ms, which is why nothing here
# is Python. Target: under 10ms, always.
#
# THE ONE FORK ON THE HAPPY PATH, AND WHY IT IS PAID. The canonical JEV_HOME
# block below costs one subshell (`cd ... && pwd -P`) whenever $JEV_HOME is not
# already exported. That is not decoration: without $JEV_HOME there is no
# machine-wide kill switch here, and `jev install` prints
# `~/.claude/jev-disabled` to the operator as THE way to stop jev everywhere.
# An audit found that switch honoured by one hook of three -- a kill switch
# that stops one writer and not the other is the failure this repo has now
# shipped twice. A couple of milliseconds is the price of the switch being
# true. Export $JEV_HOME and even that is gone.
#
# AND THE CWD GUARD ADDS NOTHING TO IT (JEV-60). The guard used to drop
# every capture on a symlinked or trailing-slash $CLAUDE_PROJECT_DIR, silently.
# It is now two-stage: the byte match first, at zero forks, and `pwd -P` on both
# sides only when that misses. Measured the way the switch was: 6.54/6.84ms on
# the byte-match path against 6.71/6.85ms before the fix -- unchanged, it is the
# same instructions -- and 7.78/8.26ms when the resolution is actually needed,
# inside the 10ms budget. A capture the guard still refuses now leaves a row in
# data/drops. The full table is at the guard itself.
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

# --- jev home: canonical block, byte-identical in every hook ----------------
# W2/JEV-56. $JEV_HOME is WHERE JEV ITSELF LIVES, resolved WITHOUT reference to
# $CLAUDE_PROJECT_DIR. The two are the same directory only when jev is running
# in its own repo; once `jev install` registers this hook in somebody else's
# repo they are different, and every asset below -- config/tiers.json, the
# assignment ledger, the breaker log, the stderr log -- belongs to jev, not to
# the project being routed.
#
# The pivot audit found the failure this prevents: resolve jev's root from
# $CLAUDE_PROJECT_DIR and, in the wrong install shape, `config/tiers.json`
# names a file that does not exist (so every delegation fails to frontier),
# the ledger is written into somebody else's working tree, and the kill switch
# names a path that will never exist -- a switch that is permanently off.
#
# ONE MECHANISM, BOTH READERS. `src/paths.py` resolves JEV_HOME with the same
# two-line rule -- the environment variable if it names a directory, otherwise
# the directory two levels above this file -- so the bash half and the Python
# half cannot disagree. `tests/test_jev_home.sh` asserts they return the same
# absolute path, and `paths.jev_home_source()` reports which arm fired.
#
# FAIL SAFE, like everything else here: a $JEV_HOME that cannot be established
# is not guessed at, it is an exit.
#
# W5. A RELATIVE $JEV_HOME IS REFUSED, NOT NORMALISED, AND THE REASON IS THE
# KILL SWITCH. Bash uses the value VERBATIM after an `is_dir` test, so
# `JEV_HOME=.` makes every jev asset cwd-relative -- config/tiers.json, the
# ledger, the breaker log, and `$JEV_HOME/.jev-disabled`, which is the GLOBAL
# kill switch. A switch whose path depends on where the caller happened to be
# standing is precisely what the per-project block below says must never
# happen: "anchored on $ROOT, never cwd-relative". `src/paths.py` RAISES on
# the same value rather than silently `.resolve()`-ing it against the cwd, so
# the two readers agree that there is exactly one kind of $JEV_HOME that means
# the same thing to both -- an absolute one. A hook cannot raise, so it
# refuses. Not a fallback: falling back to the derived path would be this
# reader guessing where the other one declines to, and `jev` and
# `paths.resolve_jev_home()` already reject the value loudly at the point a
# human sets it.
JEV_HOME="${JEV_HOME:-}"
case "$JEV_HOME" in ""|/*) ;; *) exit 0 ;; esac
[ -d "$JEV_HOME" ] || JEV_HOME="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd -P)"
[ -n "$JEV_HOME" ] || exit 0
[ -d "$JEV_HOME" ] || exit 0
# --- end jev home -----------------------------------------------------------

# --- jev GLOBAL kill switch: canonical block, byte-identical in every hook ---
# SWITCH ONE OF TWO, and the one that does not depend on which repo you are in.
# It stops routing in EVERY project at once, which is what you want at 3am when
# you do not yet know which repo is misbehaving. The per-project block below is
# the other one: an opt-out for a single repo, which is a different question.
#
# Two paths, either of which is enough:
#
#   $JEV_HOME/.jev-disabled        what `./teardown.sh` and `jev uninstall`
#                                  set. JEV_HOME-anchored, NOT project-anchored,
#                                  so it is a real path in every install shape.
#                                  Under the rejected global install this is
#                                  precisely the switch that would have named a
#                                  file that can never exist.
#   $HOME/.claude/jev-disabled     machine-wide, set by hand, honoured even if
#                                  the jev install itself is unreachable.
#                                  Read-only; nothing in this repo writes here.
#
# Same fail-safe rule as the per-project switch below: ANY entry at either path
# means OFF, and a state that cannot be established ALSO means OFF -- hence the
# unset-HOME case. A switch is never given the benefit of the doubt.
[ -n "$HOME" ] || exit 0
{ [ -e "$JEV_HOME/.jev-disabled" ] || [ -L "$JEV_HOME/.jev-disabled" ]; } && exit 0
{ [ -e "$HOME/.claude/jev-disabled" ] || [ -L "$HOME/.claude/jev-disabled" ]; } && exit 0
# --- end jev GLOBAL kill switch ---------------------------------------------

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

# SURFACE is read HERE, above the cwd guard rather than below it, because the
# guard now has to be able to write down that it fired, and a drop row that
# cannot name its surface is half an attrition record.
SURFACE="${1:-unknown}"

# --- the drop record: attrition is never silent (JEV-33, JEV-60) ------------
# One writer for every capture this hook refuses, so a new refusal cannot be
# added without a row. Durably under data/ rather than logs/, because attrition
# has to outlive a log rotation.
#
# Cost: a shell function DEFINITION is parsed, not executed -- it costs the
# happy path nothing. The two forks (date, mkdir) are paid only on a path that
# has already decided to drop the capture. bash 3.2 has no EPOCHREALTIME and no
# printf %()T, so `date` is the only clock there is; whole seconds are plenty
# for counting drops.
#
# Concurrency: several hooks can fire at once. One short line appended with >>
# is a single O_APPEND write well under PIPE_BUF, so parallel writers interleave
# cleanly rather than corrupting each other -- the same property store.py relies
# on. Nothing is read, locked or rewritten.
#
# $2 is a pre-built JSON fragment with a LEADING comma, or empty. Callers escape
# any path they put in it with parameter expansion rather than a fork.
drop() { # reason, extra-fields
  _dts=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null) || return 0
  # `[ -d ]` is a builtin; the mkdir fork is paid once, on the first drop of a
  # fresh checkout, and never again.
  [ -d "$ROOT/data/drops" ] || mkdir -p "$ROOT/data/drops" 2>/dev/null || return 0
  printf '{"at":"%s","surface":"%s","reason":"%s"%s,"pid":%s}\n' \
    "$_dts" "$SURFACE" "$1" "$2" "$$" \
    >> "$ROOT/data/drops/${_dts%%T*}.jsonl" 2>/dev/null
}

# Defensive cwd guard. settings.local.json should never load outside this repo,
# but the isolation requirement is hard enough to be worth enforcing twice.
#
# TWO-STAGE, AND THE STAGING IS THE WHOLE POINT (JEV-60).
#
# It was a BYTE comparison of two paths that are only semantically equal.
# `CLAUDE_PROJECT_DIR=/repo/` (a trailing slash) or a checkout reached through a
# symlink -- which is the NORMAL case for anything under /tmp on macOS, where
# /tmp is a symlink to /private/tmp -- made "$PWD/" fail to match "$ROOT"/* for a
# session squarely inside the project, and the hook exited here on every single
# invocation. Every capture dropped, with no record that anything had happened.
#
# `hooks/agent_route_actuator.sh` fixed the same defect by resolving BOTH sides
# with `pwd -P` unconditionally. This hook does not copy that, because this is
# the only hook on a genuinely hot critical path (10ms, and 5.37 -> 6.48ms of it
# was already spent on the global kill switch). Instead:
#
#   stage 1  the byte match, which is what a real session under /Users/... hits,
#            and it still costs ZERO forks -- exactly what it cost before;
#   stage 2  only when stage 1 misses, resolve both sides with `pwd -P` (two
#            subshells) and decide on the resolved paths;
#   stage 3  a genuine miss is RECORDED, not silent.
#
# MEASURED, with the method tests/test_hook.sh uses (best of three windows, 30
# spawns each, wall clock INCLUDING the process spawn), two runs on 2026-09-21:
#
#   pre-fix,  byte-match path      6.71 / 6.85 ms   30 of 30 captured
#   post-fix, byte-match path      6.54 / 6.84 ms   30 of 30 captured
#   post-fix, resolved (symlink)   7.78 / 8.00 ms   30 of 30 captured
#   post-fix, trailing slash       7.99 / 8.26 ms   30 of 30 captured
#   pre-fix,  symlinked root       3.54 ms          0 of 30 captured
#
# The hot path costs what it cost -- the difference is inside the noise, because
# it executes exactly the same instructions as before. Correctness costs about
# 1.2ms and only where the byte match misses, leaving ~1.7ms of the 10ms budget.
# The last row is the defect: it was the FASTEST configuration precisely because
# it did nothing, and said nothing about doing nothing.
case "$PWD/" in
  "$ROOT"/*) ;;
  *)
    # An unresolvable $CLAUDE_PROJECT_DIR is its own drop reason: it passed
    # `[ -d ]` above, so "cannot cd into it" is a permissions story, not a
    # missing-directory one, and the two want different fixes.
    ROOT_P=$(cd "$ROOT" 2>/dev/null && pwd -P) || ROOT_P=""
    PWD_P=$(pwd -P 2>/dev/null) || PWD_P="$PWD"
    if [ -z "$ROOT_P" ]; then
      _dp="$ROOT"; _dp="${_dp//\\/\\\\}"; _dp="${_dp//\"/\\\"}"
      drop "project_dir_unresolvable" ",\"project_dir\":\"$_dp\""
      exit 0
    fi
    case "$PWD_P/" in
      "$ROOT_P"/*) ;;
      *)
        _dc="$PWD_P"; _dc="${_dc//\\/\\\\}"; _dc="${_dc//\"/\\\"}"
        _dp="$ROOT_P"; _dp="${_dp//\\/\\\\}"; _dp="${_dp//\"/\\\"}"
        drop "cwd_outside_project" ",\"cwd\":\"$_dc\",\"project_dir\":\"$_dp\""
        exit 0
        ;;
    esac
    ;;
esac

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
  # record it, through the one `drop` writer above, which is now shared with the
  # cwd guard so that no refusal can be added without a row.
  #
  # The `cap` literal stays a literal: this is a fork-free bash 3.2 hot path and
  # cannot read config/surfaces.json, so tests/test_pipeline.py asserts the two
  # numbers here match `spool_backpressure_max_files` instead.
  # Single-quoted around the expansion, NOT escaped inside double quotes: the
  # cap literal below has to survive as those exact bytes, because
  # tests/test_pipeline.py greps this file's TEXT for it and asserts it matches
  # config/surfaces.json. Backslash-escaping it inside double quotes reads the
  # same to bash and is invisible to that regex -- which is how the one
  # assertion protecting this literal stops biting without anything going red.
  # For the same reason the literal appears exactly twice in this file, so it
  # is not written out again in any comment.
  drop "spool_backpressure" ',"ready_files":'"$#"',"cap":500'
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
