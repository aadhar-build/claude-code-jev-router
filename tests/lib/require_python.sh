#!/bin/bash
# JEV-44: resolve the interpreter ONCE, by absolute path, and refuse before
# doing any work if it is below the floor.
#
# WHY A SHELL FILE AND NOT JUST THE PYTHON GUARD
# ----------------------------------------------
# `src/pyversion.py` can only defend a process that has already started. It
# cannot defend `tests/test_hook.sh`, which shells out to `python3` through
# PATH sixteen times, or `tests/test_inline_shadow.sh:86`, which launches
# `src/bench_inline.py` (declared `>=3.12`) the same way. Those inherit
# whatever PATH they were handed.
#
# So this file does two things:
#
#   1. Resolves `$JEV_PY` to an absolute interpreter and proves it is >= 3.12,
#      printing the guard's own message if it is not. Single source of truth:
#      the check is `src/pyversion.py`, not a second copy of the comparison.
#   2. Puts that interpreter's directory at the FRONT of PATH, so every
#      sub-script's bare `python3` resolves to the same one. Without this the
#      override is cosmetic -- the suite would honour it and the six shell
#      tests underneath it would not.
#
# STRICT, NOT HELPFUL. If $JEV_PYTHON names an interpreter below the floor,
# this fails. It does not quietly go looking for a better one. An operator who
# names an interpreter and silently gets a different one has no way to reason
# about what actually ran, which is the same class of defect as the study's
# config fields that looked live and were inert (JEV-31b).
#
# Usage, from any script in this repo:
#
#     . "$ROOT/tests/lib/require_python.sh" || exit 1
#     "$JEV_PY" some_script.py
#
# For a CRON or wrapper entry point that must not depend on this repo's shell
# library, the equivalent two lines are:
#
#     PY="${JEV_PYTHON:-/opt/homebrew/bin/python3}"
#     "$PY" "$ROOT/src/pyversion.py" || exit 1

jev_require_python() {
  local root py dir

  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

  # The interpreter an unconfigured caller would actually get. Under cron that
  # is /usr/bin/python3 (PATH=/usr/bin:/bin, man 5 crontab) -- which is the
  # case this whole file exists to catch, so it is checked rather than skipped.
  py="${JEV_PYTHON:-}"
  [ -n "$py" ] || py="$(command -v python3 2>/dev/null)"

  if [ -z "$py" ]; then
    echo "JEV-44: no python3 on PATH and JEV_PYTHON is unset." >&2
    echo "        This project requires >= 3.12; try /opt/homebrew/bin/python3." >&2
    return 78
  fi

  case "$py" in
    /*) ;;
    *)  py="$(command -v "$py" 2>/dev/null)" ;;
  esac

  if [ ! -x "$py" ]; then
    echo "JEV-44: '${JEV_PYTHON:-python3}' resolved to '$py', which is not executable." >&2
    return 78
  fi

  # The floor itself is asserted by the Python guard, so there is exactly one
  # definition of ">= 3.12" and exactly one failure message in the project.
  # `sys.executable` is not always the path the caller typed -- /usr/bin/python3
  # on macOS reports itself as the Xcode shim it forwards to -- so the resolved
  # path is echoed here as well. The operator has to be able to match the
  # message against what they actually wrote in the crontab.
  "$py" "$root/src/pyversion.py" || {
    echo "  invoked as : $py" >&2
    echo "  (from ${JEV_PYTHON:+\$JEV_PYTHON}${JEV_PYTHON:-PATH})" >&2
    return 78
  }

  JEV_PY="$py"
  export JEV_PY

  dir="$(dirname "$py")"
  case ":$PATH:" in
    *":$dir:"*) ;;
    *) PATH="$dir:$PATH"; export PATH ;;
  esac
  return 0
}

# Sourcing this file performs the check. `.` returns the status of the last
# command it ran, so `. require_python.sh || exit 1` does the right thing.
jev_require_python
