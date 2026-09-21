#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-56 sibling: the execution plan and the tickets must agree.

WHY THIS TEST EXISTS
--------------------
On 2026-09-21 a board audit found five inconsistencies between the wave table in
`ISSUES.md` and the `Blocked by:` lines of the tickets it schedules. Every one
was the same shape -- a ticket scheduled in a wave that runs BEFORE a ticket it
depends on -- and none of them was visible to anyone reading either half alone.
Three of them had survived a deliberate restructure of the whole plan the day
before.

The plan is prose, and prose does not typecheck. This does. It reads the wave
table and the tickets out of the same file and asserts the four invariants that
were actually violated, so the next restructure fails loudly instead of quietly
scheduling JEV-27 before the ticket that tells it what to size.

It reads `ISSUES.md` and nothing else. No network, no API calls, no data.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pyversion  # noqa: E402

pyversion.require()

# Overridable so the checker can be pointed at a previous revision of the board
# and shown to go RED on it -- a test that has never failed is a test nobody has
# reason to believe. See the red-run recorded in JEV-56's commit message.
ISSUES = Path(os.environ.get("JEV_ISSUES_MD") or (ROOT / "ISSUES.md"))

TICKET_RE = re.compile(r"^## (JEV-\d+[ab]?):", re.M)
STATUS_RE = re.compile(r"^\*{0,2}Status:\*{0,2}\s*(.+)$", re.M)
BLOCKED_RE = re.compile(r"^\*{0,2}Blocked by:\*{0,2}\s*(.+?)(?=\n\n)", re.M | re.S)
WAVE_ROW_RE = re.compile(r"^\|\s*\*{0,2}(A\d|B\d)\*{0,2}\s*\|(.+?)\|", re.M)
# a JEV reference inside a blocker line, ignoring ones struck through as cleared
JEV_REF_RE = re.compile(r"JEV-(\d+[ab]?)")

VALID_STATUSES = ("ready-for-agent", "in-progress", "blocked", "done", "in-review")

# Wave ordering. Everything in Phase A runs before the gate; everything in
# Phase B runs after it.
WAVE_ORDER = {w: i for i, w in enumerate(
    ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "B1", "B2", "B3", "B4"]
)}


def _sections(text: str) -> dict[str, str]:
    """Split ISSUES.md into one blob per ticket."""
    out: dict[str, str] = {}
    marks = list(TICKET_RE.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[m.group(1)] = text[m.start():end]
    return out


def _live_edges(blocker_text: str) -> list[str]:
    """The tickets a `Blocked by:` line actually declares as blockers.

    Two kinds of JEV reference in these lines are NOT blocking edges, and
    reading them as edges produces confident nonsense -- the first version of
    this test reported five violations, all of them false:

    * **Struck through.** `~~JEV-34~~ -- cleared` is a record that a dependency
      WAS resolved. Counting it would make every resolved edge permanent.
    * **Reverse direction.** These lines routinely name what the ticket blocks,
      not what blocks it: JEV-29's "None -- and it blocks JEV-23", JEV-55's
      "none. **This gates JEV-27**", JEV-46's "Not blocked by JEV-27, though
      JEV-27 is blocked by this". Reading those backwards inverts the graph.

    So: drop struck-through spans, then keep only the head of the line -- the
    part before the first sentence break or em-dash, which by the convention
    this file already follows is where the edges are and where the commentary
    is not.
    """
    text = re.sub(r"~~.*?~~", "", blocker_text, flags=re.S)
    head = re.split(r"—|--|\.\s", text, maxsplit=1)[0]
    if re.search(r"\bnone\b", head, re.I):
        return []
    return JEV_REF_RE.findall(head)


def _wave_membership(text: str) -> dict[str, str]:
    """ticket -> wave, read off the two wave tables."""
    plan_end = text.find("## JEV-01")
    plan = text[:plan_end]
    membership: dict[str, str] = {}
    for m in WAVE_ROW_RE.finditer(plan):
        wave, cells = m.group(1), m.group(2)
        for num in re.findall(r"\*\*(\d+[ab]?)\*\*", cells):
            membership[f"JEV-{num.zfill(2) if len(num) < 2 else num}"] = wave
    return membership


class TestTheBoardIsInternallyConsistent(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = ISSUES.read_text()
        cls.sections = _sections(cls.text)
        cls.waves = _wave_membership(cls.text)

    def test_the_wave_tables_parse_at_all(self) -> None:
        """A guard against this whole file passing vacuously."""
        self.assertGreaterEqual(
            len(self.waves), 30,
            f"only {len(self.waves)} tickets found in the wave tables -- the "
            "table format changed and every test below is now meaningless",
        )
        self.assertGreaterEqual(len(self.sections), 50)

    def test_the_edge_parser_finds_the_edges_we_checked_by_hand(self) -> None:
        """The guard `_live_edges` needs and did not have.

        `_live_edges` keeps the head of the `Blocked by:` line, cutting at the
        first em-dash or sentence break. That heuristic is why the multi-blocker
        lines survive -- they happen to have no sentence break before their last
        blocker. "Happen to" is not a property; a blocker line written in a new
        style would silently parse to zero edges and every scheduling assertion
        below would pass by checking nothing.

        So the multi-blocker tickets verified by hand during the 2026-09-21
        reconciliation are pinned here. If the parser stops seeing these, it has
        stopped seeing edges generally, and it says so instead of going quiet.

        Recorded honestly: the first version of THIS test failed, and the
        parser was right and the hand-written expectations were wrong. JEV-23
        really does declare ten blockers and JEV-27 really does declare three.
        The sets below were then read off the file rather than recalled, which
        is the only way a fixture like this is worth anything.
        """
        expected = {
            # ten blockers over five wrapped lines, two of them repeated
            "JEV-23": {"52", "34", "35", "36", "24a", "27", "28", "29", "46", "47"},
            # five blockers, wrapped, mixing bold and plain
            "JEV-53": {"12", "23", "50", "48", "52"},
            # bolded blockers with parentheticals, wrapped mid-parenthetical
            "JEV-27": {"38", "49", "46"},
            # the simplest possible line
            "JEV-36": {"35"},
            # one blocker followed by a second sentence that must NOT be read
            "JEV-12": {"10"},
        }
        for ticket, want in expected.items():
            with self.subTest(ticket=ticket):
                bm = BLOCKED_RE.search(self.sections[ticket])
                self.assertIsNotNone(bm, f"{ticket} has no parseable Blocked by:")
                got = set(_live_edges(bm.group(1)))
                self.assertEqual(
                    want, got,
                    f"{ticket}: parser found {sorted(got)}, expected "
                    f"{sorted(want)} -- the Blocked by: style changed and "
                    "_live_edges no longer reads it",
                )

    def test_every_ticket_has_a_recognised_status(self) -> None:
        for name, blob in self.sections.items():
            with self.subTest(ticket=name):
                m = STATUS_RE.search(blob)
                self.assertIsNotNone(m, f"{name} has no Status: line")
                status = m.group(1).lower()
                self.assertTrue(
                    any(v in status for v in VALID_STATUSES),
                    f"{name} status {status!r} is not one of {VALID_STATUSES}",
                )

    def test_no_ticket_is_scheduled_before_a_ticket_it_depends_on(self) -> None:
        """INCONSISTENCY 1, 2 and 5. The one that actually bit us.

        Old A3 held JEV-46 and JEV-47, both `Blocked by: JEV-34`, while JEV-34
        sat in A4 -- a wave that runs after them. JEV-48 was three waves ahead
        of JEV-36. JEV-12 was in Phase A behind a Phase B blocker.
        """
        violations = []
        for name, blob in self.sections.items():
            wave = self.waves.get(name)
            if wave is None:
                continue
            bm = BLOCKED_RE.search(blob)
            if not bm:
                continue
            for num in _live_edges(bm.group(1)):
                dep = f"JEV-{num}"
                if dep == name or dep == "JEV-52":
                    continue  # the gate is an explicit phase boundary, not an edge
                dep_wave = self.waves.get(dep)
                if dep_wave is None:
                    continue
                if WAVE_ORDER[dep_wave] > WAVE_ORDER[wave]:
                    violations.append(
                        f"{name} is in {wave} but depends on {dep} in {dep_wave}"
                    )
        self.assertEqual([], violations, "\n".join(violations))

    def test_every_open_ticket_is_in_exactly_one_wave(self) -> None:
        """INCONSISTENCY 4. JEV-54 and JEV-55 were in no wave at all.

        JEV-55 states that it gates the primary metric, JEV-27 and JEV-52, and
        was invisible to anyone reading the execution plan.
        """
        orphans = []
        for name, blob in self.sections.items():
            m = STATUS_RE.search(blob)
            if m and ("done" in m.group(1).lower()
                      or "superseded" in blob[:400].lower()):
                continue
            if name in ("JEV-52",):  # the gate is the boundary, not a wave member
                continue
            if name not in self.waves:
                orphans.append(name)
        self.assertEqual(
            [], orphans,
            "open tickets in no wave (they cannot be scheduled and will be "
            f"forgotten): {orphans}",
        )

    def test_the_gate_blocks_on_every_phase_a_ticket(self) -> None:
        """INCONSISTENCY 5. JEV-52 omitted six, two load-bearing.

        JEV-37 builds what the gate's own step 5 runs; JEV-55 decides what its
        step 6 must write down.
        """
        gate = self.sections["JEV-52"]
        listed = set(JEV_REF_RE.findall(gate))
        missing = []
        for name, wave in self.waves.items():
            if not wave.startswith("A"):
                continue
            num = name.split("-")[1]
            if num.lstrip("0") not in {n.lstrip("0") for n in listed}:
                missing.append(name)
        self.assertEqual(
            [], missing,
            f"Phase A tickets absent from JEV-52's blockers: {missing}",
        )

    def test_no_phase_a_ticket_claims_to_register_or_arm_anything(self) -> None:
        """The standing rule that the dev/live gate exists to enforce."""
        forbidden = re.compile(
            r"remove `?\.jev-disabled|start the worker|register the first surface",
            re.I,
        )
        offenders = []
        for name, blob in self.sections.items():
            if self.waves.get(name, "").startswith("A") and forbidden.search(blob):
                offenders.append(name)
        self.assertEqual(
            [], offenders,
            f"Phase A tickets describing a live action (JEV-52's job): {offenders}",
        )


if __name__ == "__main__":
    if not ISSUES.exists():
        print(f"ISSUES.md not found at {ISSUES}", file=sys.stderr)
        raise SystemExit(2)
    unittest.main(verbosity=2)
