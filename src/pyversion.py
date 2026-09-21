#!/usr/bin/env python3
# NO PEP-723 HEADER, AND NO `uv run` SHEBANG, DELIBERATELY.
#
# Every other entry point in src/ carries `requires-python = ">=3.12"` and is
# launched through `uv run --script`. This file is the exception, because it is
# the thing that CHECKS the floor. It has to run, and produce a sentence, on
# whatever interpreter it was handed -- including the one that cannot read the
# rest of the project.
#
# JEV-44. See ISSUES.md.
#
# WHY THIS FILE EXISTS AT ALL
# ---------------------------
# `src/arms/jev.py:237` puts a backslash inside an f-string expression, which
# is a SyntaxError before Python 3.12. That was reported as a 3.11 problem. It
# is worse than that: `python3` under cron resolves through PATH=/usr/bin:/bin
# (man 5 crontab) to Apple's /usr/bin/python3, which on this machine is
# **3.9.6**. JEV-37 will put the drift canary in the operator's crontab, and a
# bare `python3` there produces a daily alarm that means nothing.
#
# The fix is NOT to make jev.py parse on 3.11. That would convert a loud
# failure into a silent one: the suite would go green on an interpreter the
# project does not support and has never been measured on, while every other
# header in src/ still says 3.12. The fix is to state the floor and refuse.
#
# HOW TO USE IT
# -------------
# From Python, as the FIRST thing an entry point does, before it imports
# anything that might not parse:
#
#     sys.path.insert(0, str(ROOT / "src"))
#     import pyversion; pyversion.require()
#
# From shell, as a preflight before spending anything:
#
#     "$PY" "$ROOT/src/pyversion.py" || exit 1
#
# CONSTRAINTS THIS FILE MUST KEEP
# -------------------------------
#   * It imports nothing from this project, and nothing outside the stdlib
#     core. It runs before `sys.path` is trustworthy.
#   * No f-strings, no annotations, no walrus, no match. It must parse on an
#     interpreter far below the floor it enforces -- a guard that raises
#     SyntaxError is a second copy of the bug.
#   * tests/test_python_floor.py byte-compiles it with /usr/bin/python3 so
#     that this stays true rather than being a comment about the past.
"""Assert the interpreter floor, loudly and before any work happens."""

import sys

# The floor, in one place. It matches the `requires-python = ">=3.12"` header
# on every executable module in src/ and tests/.
MIN = (3, 12)

# The exit code for "wrong interpreter".
#
# NOT 1, and not anything in 0-4. `src/canary.py` owns 0 clean / 1 drift /
# 2 baselined / 3 incomplete / 4 jitter-flip, and JEV-37 is going to read those
# codes out of a cron wrapper. A guard that exits 1 from that wrapper is
# reported to the operator as DRIFT -- a false scientific finding produced by a
# misconfigured PATH. 78 is EX_CONFIG from sysexits(3): "something was found
# wrong in the configuration", which is exactly the situation.
EXIT_WRONG_PYTHON = 78

# The interpreter that satisfies the floor on this machine. Referenced in the
# failure message so the reader does not have to go looking, and kept in sync
# with tests/lib/require_python.sh.
SUGGESTED = "/opt/homebrew/bin/python3"

_ENV_OVERRIDE = "JEV_PYTHON"


def _dotted(version):
    return ".".join(str(n) for n in version[:3])


def explain(found, executable, min_version=MIN):
    """Return the operator-facing failure message, or None if `found` is fine.

    Pure, so the message can be tested without needing an old interpreter on
    the box, and so the caller decides whether to print, raise or log.
    """
    if tuple(found[:2]) >= tuple(min_version[:2]):
        return None
    return (
        "\n"
        "=============================================================\n"
        " WRONG PYTHON INTERPRETER -- refusing to run (JEV-44)\n"
        "=============================================================\n"
        "  required : >= %s\n"
        "  found    : %s\n"
        "  from     : %s\n"
        "\n"
        "  This project declares `requires-python = \">=3.12\"` on every\n"
        "  executable module. Below that floor, src/arms/jev.py:237 is a\n"
        "  SyntaxError, and tests/test_pipeline.py reports 16 errors that\n"
        "  have nothing to do with the code under test.\n"
        "\n"
        "  If you got here from cron, a hook or a wrapper: PATH under cron\n"
        "  is /usr/bin:/bin (man 5 crontab), so a bare `python3` is Apple's\n"
        "  system interpreter, not the one this study runs on. Name the\n"
        "  interpreter by absolute path.\n"
        "\n"
        "  Fix:\n"
        "      %s=%s <your command>\n"
        "  or invoke %s directly.\n"
        "=============================================================\n"
        % (
            _dotted(min_version),
            _dotted(found),
            executable,
            _ENV_OVERRIDE,
            SUGGESTED,
            SUGGESTED,
        )
    )


def require(min_version=MIN, stream=None):
    """Exit with EXIT_WRONG_PYTHON, and a sentence, if this interpreter is
    below the floor. Returns None otherwise, so it is safe at import time."""
    message = explain(sys.version_info, sys.executable or "<unknown>", min_version)
    if message is None:
        return None
    (stream or sys.stderr).write(message)
    sys.exit(EXIT_WRONG_PYTHON)


def main():
    require()
    return 0


if __name__ == "__main__":
    sys.exit(main())
