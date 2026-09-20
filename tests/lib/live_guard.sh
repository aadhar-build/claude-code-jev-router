#!/bin/bash
# JEV-42: the runtime tripwire for "a test just damaged the live collection
# window".
#
# WHY THIS EXISTS
# ---------------
# `tests/test_hook.sh` spent the whole of the live window so far running
# `rm -f "$ROOT"/spool/ready/*.json` between assertion blocks, against the real
# project root, while the worker drained that exact directory. See
# PREREGISTRATION.md Amendment 6: at least seven invocations, an unknown and
# unrecoverable number of captures destroyed. A deleted spool file produces no
# capture row and no run row, so it cannot even enter the attrition count the
# pre-registration commits to reporting -- the loss is invisible to the
# measurement built to catch it.
#
# Sandboxing the tests (which this commit also does) prevents the known cases.
# This file is the belt to that braces: it makes the DAMAGE detectable, so a
# future test that forgets to sandbox FAILS the suite instead of silently
# succeeding.
#
# WHAT IT CHECKS, AND WHY THESE CHECKS AND NOT A DIRECTORY DIFF
# -------------------------------------------------------------
# A naive "list spool/ready before and after" is useless here: the worker is
# SUPPOSED to be emptying that directory every 30 seconds, so a plain diff is
# either permanently red or permanently ignored. Every invariant below is one
# that legitimate draining cannot violate:
#
#   * inodes of spool/, spool/ready, spool/tmp, logs/ -- unchanged. Catches the
#     `mv "$ROOT/spool/ready" ... .bak` / `mv "$ROOT/logs" "$ROOT/logs.bak"`
#     shape, which the pre-fix gates.sh and test_hook.sh both used and which
#     loses every capture that fires during the window.
#   * modes of spool/tmp and spool/ready -- unchanged. `chmod 500` is the
#     SECOND silent-loss mechanism in the old test_hook.sh: it does not delete
#     anything, it makes every live hook that fires during the window take its
#     fail-open path and drop the capture on the floor. Same invisible loss, no
#     missing file to notice afterwards.
#   * the kill switch is in the same state after as before. The third
#     mechanism: `touch "$ROOT/.jev-disabled"` (old test_inline_shadow.sh)
#     turns collection OFF for the duration, and a test killed mid-run leaves
#     it off indefinitely with nothing to report it.
#   * the worker is still alive if it was alive.
#   * CONSERVATION: ready + claimed + dead + capture_rows never decreases.
#     This is the one that catches deletion. The worker moves a file
#     ready -> claimed -> (capture row | dead/), so its own draining holds the
#     sum constant and a new capture only increases it. `rm` from spool/ready
#     is the only thing that can make it fall.
#   * data/drops and data/inline line counts never decrease -- those are
#     declared attrition streams and an append-only decision log respectively.
#
# Usage, as a script (this is how run_all.sh drives it):
#   live_guard.sh snapshot <file>
#   live_guard.sh verify   <file> <label>      # nonzero, and loud, on damage
#
# Or sourced, for the same two functions.

jev_guard_root() { (cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd); }

# `stat` is not portable between BSD and GNU; this project runs on macOS but
# the fallback keeps the guard from silently reporting "unchanged" for every
# field on a Linux box, which would be worse than not having it.
_jev_ino()  { stat -f '%i' "$1" 2>/dev/null || stat -c '%i' "$1" 2>/dev/null || echo "-"; }
_jev_mode() { stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1" 2>/dev/null || echo "-"; }
_jev_lines(){ cat "$@" 2>/dev/null | wc -l | tr -d ' '; }
_jev_files(){ ls "$1" 2>/dev/null | wc -l | tr -d ' '; }

jev_live_snapshot() { # <outfile>
  local R out pid
  R="$(jev_guard_root)"; out="$1"
  pid="$(cat "$R/logs/worker.pid" 2>/dev/null)"
  {
    echo "ino_spool=$(_jev_ino "$R/spool")"
    echo "ino_ready=$(_jev_ino "$R/spool/ready")"
    echo "ino_tmp=$(_jev_ino "$R/spool/tmp")"
    echo "ino_logs=$(_jev_ino "$R/logs")"
    echo "ino_data=$(_jev_ino "$R/data")"
    echo "mode_ready=$(_jev_mode "$R/spool/ready")"
    echo "mode_tmp=$(_jev_mode "$R/spool/tmp")"
    echo "killswitch=$( { [ -e "$R/.jev-disabled" ] || [ -L "$R/.jev-disabled" ]; } && echo on || echo off)"
    echo "worker_pid=${pid:-none}"
    echo "worker_alive=$( [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && echo yes || echo no)"
    echo "n_ready=$(ls "$R"/spool/ready/*.json 2>/dev/null | wc -l | tr -d ' ')"
    echo "n_claimed=$(_jev_files "$R/spool/claimed")"
    echo "n_dead=$(_jev_files "$R/spool/dead")"
    echo "n_caprows=$(_jev_lines "$R"/data/captures/*.jsonl)"
    echo "n_droprows=$(_jev_lines "$R"/data/drops/*.jsonl)"
    echo "n_inlinerows=$(_jev_lines "$R"/data/inline/*.jsonl)"
  } > "$out"
}

jev_live_verify() { # <snapfile> <label>
  local snap label now v bad R
  snap="$1"; label="${2:-unnamed}"
  R="$(jev_guard_root)"
  [ -f "$snap" ] || { echo "  LIVE-GUARD: no snapshot to compare ($snap)"; return 1; }
  now="$(mktemp "${TMPDIR:-/tmp}/jev-guard.XXXXXX")"
  jev_live_snapshot "$now"

  # shellcheck disable=SC1090
  bad=""
  _before() { grep "^$1=" "$snap" | cut -d= -f2-; }
  _after()  { grep "^$1=" "$now"  | cut -d= -f2-; }

  for v in ino_spool ino_ready ino_tmp ino_logs ino_data mode_ready mode_tmp killswitch; do
    if [ "$(_before "$v")" != "$(_after "$v")" ]; then
      bad="$bad\n    $v: $(_before "$v") -> $(_after "$v")"
    fi
  done

  if [ "$(_before worker_alive)" = "yes" ] && [ "$(_after worker_alive)" != "yes" ]; then
    bad="$bad\n    worker (pid $(_before worker_pid)) was alive before and is not now"
  fi

  for v in n_dead n_caprows n_droprows n_inlinerows; do
    if [ "$(_after "$v")" -lt "$(_before "$v")" ] 2>/dev/null; then
      bad="$bad\n    $v went BACKWARDS: $(_before "$v") -> $(_after "$v")"
    fi
  done

  # The conservation law. Draining holds it constant; a new capture raises it;
  # only deletion from the spool can lower it.
  local sum_b sum_a
  sum_b=$(( $(_before n_ready) + $(_before n_claimed) + $(_before n_dead) + $(_before n_caprows) ))
  sum_a=$(( $(_after  n_ready) + $(_after  n_claimed) + $(_after  n_dead) + $(_after  n_caprows) ))
  if [ "$sum_a" -lt "$sum_b" ]; then
    bad="$bad\n    CAPTURES DESTROYED: ready+claimed+dead+rows fell $sum_b -> $sum_a"
    bad="$bad\n    (that difference is decision points that now have no capture row,"
    bad="$bad\n     no run row, and cannot appear in the attrition count -- see"
    bad="$bad\n     PREREGISTRATION.md Amendment 6)"
  fi

  rm -f "$now"
  if [ -n "$bad" ]; then
    echo
    echo "=============================================================="
    echo " LIVE-GUARD FAILURE after: $label"
    echo "=============================================================="
    # shellcheck disable=SC2059
    printf "  the live collection window was modified:$bad\n"
    echo
    echo "  A test must never touch the real spool/, data/ or logs/."
    echo "  Point CLAUDE_PROJECT_DIR at a throwaway root instead --"
    echo "  tests/gates.sh and tests/test_hook.sh are the pattern."
    echo "=============================================================="
    return 1
  fi
  return 0
}

# Script mode.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    snapshot) jev_live_snapshot "$2" ;;
    verify)   jev_live_verify "$2" "${3:-unnamed}" ;;
    *) echo "usage: live_guard.sh snapshot <file> | verify <file> <label>" >&2; exit 2 ;;
  esac
fi
