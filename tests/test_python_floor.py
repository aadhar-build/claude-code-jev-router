#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-44: the interpreter floor is asserted, not assumed.

WHAT THIS TESTS, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------
It does NOT test that `src/arms/jev.py` parses. It already parses on the
interpreter this study runs on (3.14), and proving that proves nothing.

What it tests is the GUARD: that an entry point invoked by something other
than a human shell -- cron, a wrapper, a hook -- discovers the wrong
interpreter *before* doing any work, and says so in a sentence rather than in
sixteen SyntaxErrors.

The distinction matters because of the numbers. Under BOTH Apple's
/usr/bin/python3 (3.9.6, which is what `python3` resolves to under cron's
PATH) and Homebrew's 3.11, `tests/test_pipeline.py` reports exactly **16
errors**, all of them the same lazy `from arms import claude, jev` inside
`TestLiveArmWireFormats.setUp` (test_pipeline.py:445). The count is identical
across two interpreters five minor versions apart, so it identifies nothing
about which interpreter ran -- and it moves the moment anyone adds a test to
that class. "16 is the known defect, a different count is your regression" is
therefore not a usable rule, and this file exists so that nobody needs one.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pyversion  # noqa: E402

# Apple's system python. Present on every macOS box, always older than the
# floor, and -- the whole point of this ticket -- what a bare `python3`
# resolves to under cron, whose PATH is /usr/bin:/bin (man 5 crontab).
SYSTEM_PY = Path("/usr/bin/python3")

PEP723_REQUIRES = re.compile(
    r"^# requires-python = \">=3\.(\d+)\"$", re.MULTILINE
)

# Acceptance criterion 4 is "check EVERY test module". The list is derived
# from `run_all.sh` rather than written down here, so a module added to the
# suite is covered the moment it is added -- the same self-maintaining
# property `audit_live_writes.sh` has, and for the same reason: a checklist
# that has to be updated by hand is a checklist that goes stale.
#
# `tests/gate4_drain.py` is appended explicitly because it is a tracked
# entry point with a `__main__` that `run_all.sh` does not invoke. Being
# outside the suite is exactly what makes an unpinned entry point dangerous:
# whoever runs it runs it by hand, from an unknown shell.
_INVOKED = re.compile(r"\$ROOT/((?:tests|src)/[A-Za-z0-9_]+\.py)")


def _guarded_modules():
    text = (ROOT / "tests" / "run_all.sh").read_text()
    found = {ROOT / rel for rel in _INVOKED.findall(text)}
    found.add(ROOT / "tests" / "gate4_drain.py")
    return sorted(p for p in found if p.exists())


TEST_MODULES = _guarded_modules()


class TestTheGuardModuleItself(unittest.TestCase):
    """A guard written in syntax the old interpreter cannot read is not a
    guard -- it is a second copy of the bug being guarded against."""

    def test_the_guard_parses_on_the_oldest_interpreter_on_this_machine(self):
        if not SYSTEM_PY.exists():
            self.skipTest(f"no {SYSTEM_PY} on this machine")
        r = subprocess.run(
            [str(SYSTEM_PY), "-m", "py_compile", str(ROOT / "src" / "pyversion.py")],
            capture_output=True, text=True,
        )
        self.assertEqual(
            r.returncode, 0,
            f"src/pyversion.py must parse on {SYSTEM_PY}:\n{r.stderr}",
        )

    def test_the_guard_imports_nothing_from_this_project(self):
        """It has to be importable before `sys.path` is arranged, and before
        anything else in `src/` has been proven parseable."""
        src = (ROOT / "src" / "pyversion.py").read_text()
        for line in src.splitlines():
            if line.startswith(("import ", "from ")):
                mod = line.split()[1].split(".")[0]
                self.assertIn(
                    mod, {"sys", "os", "__future__"},
                    f"pyversion.py imports {mod!r}; it must depend on nothing",
                )

    def test_explain_returns_a_message_below_the_floor_and_none_at_or_above(self):
        self.assertIsNone(pyversion.explain((3, 12, 0), "/x/python3"))
        self.assertIsNone(pyversion.explain((3, 14, 7), "/x/python3"))
        msg = pyversion.explain((3, 9, 6), "/usr/bin/python3")
        self.assertIsNotNone(msg)
        self.assertIn("3.9.6", msg)
        self.assertIn("3.12", msg)
        self.assertIn("/usr/bin/python3", msg)

    def test_the_failure_names_the_override_that_fixes_it(self):
        msg = pyversion.explain((3, 11, 15), "/x/python3")
        self.assertIn("JEV_PYTHON", msg)

    def test_the_exit_code_cannot_be_confused_with_a_canary_verdict(self):
        """JEV-37's canary owns 0-4 (clean/drift/baselined/incomplete/jitter).
        A guard that exits 1 from a cron wrapper reads as DRIFT."""
        self.assertNotIn(pyversion.EXIT_WRONG_PYTHON, range(5))
        self.assertEqual(pyversion.EXIT_WRONG_PYTHON, 78)  # EX_CONFIG


class TestTheGuardAsAPreflight(unittest.TestCase):
    """`python3 src/pyversion.py` is the one-line preflight a shell wrapper
    runs before it spends anything."""

    def test_it_refuses_the_system_interpreter_loudly(self):
        if not SYSTEM_PY.exists():
            self.skipTest(f"no {SYSTEM_PY} on this machine")
        r = subprocess.run(
            [str(SYSTEM_PY), str(ROOT / "src" / "pyversion.py")],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, pyversion.EXIT_WRONG_PYTHON)
        self.assertIn("3.12", r.stderr)          # the floor
        self.assertIn("3.9.", r.stderr)          # what it actually got
        # A sentence, not a stack. "no traceback" is the legibility property
        # the ticket asks for -- the word "SyntaxError" appears in the message
        # on purpose, because naming the defect is the point.
        self.assertNotIn("Traceback (most recent call last)", r.stderr)

    def test_it_is_silent_and_green_on_a_conforming_interpreter(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "src" / "pyversion.py")],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(r.stderr.strip(), "")


class TestEveryTestModuleIsPinnedAndGuarded(unittest.TestCase):
    """Acceptance criteria 1 and 4: the pin goes on every test module, not
    just the one that happened to be noticed."""

    HEADER_FIX = (
        "\n\n  Add, as the first five lines of {name} (this is the\n"
        "  convention every executable module in src/ already uses):\n\n"
        "    #!/usr/bin/env -S uv run --script\n"
        "    # /// script\n"
        '    # requires-python = ">=3.12"\n'
        "    # dependencies = []\n"
        "    # ///\n"
    )

    GUARD_FIX = (
        "\n\n  Add to {name}, immediately after its sys.path line and\n"
        "  BEFORE any project import (below the floor, `import worker` ->\n"
        "  `from arms import jev` is a SyntaxError, and a guard placed after\n"
        "  it is never reached):\n\n"
        "    import pyversion; pyversion.require()\n"
    )

    def test_every_test_module_declares_requires_python(self):
        for p in TEST_MODULES:
            with self.subTest(module=p.name):
                m = PEP723_REQUIRES.search(p.read_text())
                self.assertIsNotNone(
                    m,
                    f"{p.name} is invoked by run_all.sh and has no PEP-723 "
                    f"requires-python header (JEV-44)."
                    + self.HEADER_FIX.format(name=p.name),
                )
                self.assertGreaterEqual(int(m.group(1)), 12, p.name)

    def test_every_test_module_asserts_the_floor_at_runtime(self):
        """The header only binds `uv run`. `python3 tests/test_pipeline.py`
        ignores it completely, and that is how the 16 errors are produced."""
        for p in TEST_MODULES:
            with self.subTest(module=p.name):
                self.assertIn(
                    "pyversion.require()", p.read_text(),
                    f"{p.name} is invoked by run_all.sh and does not call "
                    f"pyversion.require() (JEV-44)."
                    + self.GUARD_FIX.format(name=p.name),
                )

    def test_uv_run_now_selects_a_conforming_interpreter(self):
        r = subprocess.run(
            ["uv", "run", "--offline", "--quiet", str(ROOT / "tests" / "test_python_floor.py"),
             "--version-probe"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        if r.returncode != 0 and "uv" in r.stderr and "not found" in r.stderr:
            self.skipTest("uv unavailable")
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        major, minor = r.stdout.strip().split(".")[:2]
        self.assertEqual(int(major), 3)
        self.assertGreaterEqual(int(minor), 12, f"uv picked {r.stdout.strip()}")


class TestTheSuiteRefusesTheWrongInterpreter(unittest.TestCase):
    """Acceptance criterion 3. The assertion that matters is not `nonzero` --
    the suite already exits nonzero on 3.9, after running the JEV-42 audit,
    the hook tests, and sixteen SyntaxErrors. It is that it refuses BEFORE
    any of that."""

    FIRST_WORK_BANNER = "JEV-42 guard"

    def test_run_all_refuses_before_doing_any_work(self):
        if not SYSTEM_PY.exists():
            self.skipTest(f"no {SYSTEM_PY} on this machine")
        env = dict(os.environ, JEV_PYTHON=str(SYSTEM_PY))
        r = subprocess.run(
            [str(ROOT / "tests" / "run_all.sh")],
            capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=120,
        )
        out = r.stdout + r.stderr
        self.assertNotEqual(r.returncode, 0, "the suite ran on 3.9.6")
        # Not merely nonzero: the guard's 78 must SURVIVE the shell. The
        # natural thing to write is `. require_python.sh || exit 1`, and that
        # collapses 78 into 1 -- which is the very confusion with
        # src/canary.py's DRIFT verdict that 78 was chosen to avoid. A caller
        # copying this line into a cron wrapper would rebuild the false alarm.
        self.assertEqual(
            r.returncode, pyversion.EXIT_WRONG_PYTHON,
            "run_all.sh swallowed the guard's exit code; use `|| exit $?`",
        )
        self.assertIn("3.12", out)
        self.assertIn("3.9.", out)
        # The resolver must echo the path the caller actually named, because
        # sys.executable does not: /usr/bin/python3 reports itself as the
        # Xcode shim it forwards to.
        self.assertIn("invoked as : %s" % SYSTEM_PY, out)
        self.assertNotIn("Traceback (most recent call last)", out)
        self.assertNotIn(
            self.FIRST_WORK_BANNER, out,
            "the suite started working before checking the interpreter",
        )

    def test_run_all_invokes_no_bare_python3(self):
        """A bare `python3` in a file that cron or a wrapper can reach is the
        defect itself, not a style point."""
        text = (ROOT / "tests" / "run_all.sh").read_text()
        offenders = [
            (i, ln) for i, ln in enumerate(text.splitlines(), 1)
            if re.search(r"(?<![\w/$\"'])python3\b", ln) and not ln.lstrip().startswith("#")
        ]
        self.assertEqual(offenders, [], f"bare python3 in run_all.sh: {offenders}")

    def test_the_resolver_accepts_an_explicit_conforming_interpreter(self):
        """The accept path is tested by sourcing the resolver directly. It is
        NOT tested by running the whole suite -- this module is IN the suite,
        and that would recurse."""
        env = dict(os.environ, JEV_PYTHON=sys.executable)
        r = subprocess.run(
            ["bash", "-c",
             f'. "{ROOT}/tests/lib/require_python.sh" && echo "$JEV_PY"'],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), sys.executable)

    def test_the_resolver_does_not_fall_back_to_a_different_interpreter(self):
        """Strict. An operator who names an interpreter and silently gets a
        different one has no way to reason about what ran."""
        if not SYSTEM_PY.exists():
            self.skipTest(f"no {SYSTEM_PY} on this machine")
        env = dict(os.environ, JEV_PYTHON=str(SYSTEM_PY))
        r = subprocess.run(
            ["bash", "-c",
             f'. "{ROOT}/tests/lib/require_python.sh" && echo "$JEV_PY"'],
            capture_output=True, text=True, env=env,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("3.12", r.stdout + r.stderr)


if __name__ == "__main__":
    pyversion.require()
    if "--version-probe" in sys.argv:
        print("%d.%d.%d" % sys.version_info[:3])
        raise SystemExit(0)
    unittest.main(verbosity=2)
