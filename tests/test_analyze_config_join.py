#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-32: analyze.py must join rows to the config THEY ran under.

`analyze.py` resolved the question spec from whatever `config/surfaces.json`
says at analysis time, while every row carries the `question_set_id` it was
actually produced under. Two rows run under different pins were pooled into one
n, one agreement number and one interval, and nothing said so.

`src/validate_threshold.py` and `src/determinism.py` already key on the row's
own `question_set_id` and filter rather than pool. These tests pin the same
behaviour onto `analyze.py`, which was the outlier.

This file is separate from test_pipeline.py on purpose: analyze.py is frozen by
PREREGISTRATION section 8 and its fix lands as its own commit, so the tests that
justify that commit are kept where they can be read beside it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pyversion  # noqa: E402

pyversion.require()

import analyze  # noqa: E402
import config_loader as cl  # noqa: E402
import store  # noqa: E402
from test_pipeline import TempStorage, payload  # noqa: E402


class TestQuestionSetJoin(TempStorage):
    """Rows from two question sets must not become one number."""

    def populate(self, n=6):
        import worker

        for i in range(n):
            worker.process_capture(
                payload(f"command number {i}", session=f"s{i % 3}"),
                "pre_bash",
                [cl.arm("fake"), cl.arm("fake_b")],
            )

    def clone_decisions(self, mutation, keep=2, suffix="-alt"):
        """Append whole decisions -- capture AND runs -- with fields overridden.

        The capture is cloned alongside the run rows because `Joined` drops any
        run whose decision_id has no capture; a clone without one would be
        silently discarded and the test would pass for the wrong reason. That
        mistake was made once while writing this file and is recorded here so
        it is not made again.
        """
        captures = {c["decision_id"]: c for c in store.captures()}
        seen = set()
        for r in list(store.runs()):
            if r["decision_id"] not in seen:
                if len(seen) >= keep:
                    break
                seen.add(r["decision_id"])
                capture = dict(captures[r["decision_id"]])
                capture["decision_id"] = r["decision_id"] + suffix
                store.append_capture(capture)
            clone = dict(r)
            clone.update(mutation)
            clone["decision_id"] = r["decision_id"] + suffix
            store.append_run(clone)

    def restamp(self, question_set_id, keep=2):
        """Decisions carrying a different question-set pin.

        A different phrasing is a different row BY DESIGN (CONTEXT.md): the
        phrasing sweep exists to detect whether an answer is a property of the
        command or of the wording. Pooling #a with #b destroys exactly the
        contrast the sweep was built to measure.
        """
        self.clone_decisions({"question_set_id": question_set_id}, keep=keep)

    def primary_n(self, text, question="destructive"):
        """Every `n=` printed for `question` UNDER THE CONFIGURED PIN.

        Scoped to the primary section on purpose: an off-pin section printing
        its own n is the fix working, not the defect. What must not move is the
        headline group's n.
        """
        primary = cl.question_set_id("pre_bash")
        out = []
        in_primary = True
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("question set:"):
                in_primary = stripped.split("question set:")[1].strip().startswith(primary)
            elif stripped.startswith("QUESTION SET") or stripped.startswith("!! QUESTION SET"):
                in_primary = False
            elif in_primary and stripped.startswith(f"{question}  (n="):
                out.append(int(stripped.split("(n=")[1].split(",")[0]))
        return out

    def test_a_second_question_set_is_not_pooled_into_the_primary_n(self):
        self.populate()
        primary = cl.question_set_id("pre_bash")
        self.assertEqual(primary, "pre_bash/v1#a")
        before = self.primary_n(analyze.report(reference="fake"))
        self.assertTrue(before, "no paired observations to compare; fixture is wrong")

        self.restamp("pre_bash/v1#b")
        after = self.primary_n(analyze.report(reference="fake"))
        self.assertEqual(
            before, after,
            "rows stamped pre_bash/v1#b were pooled into the pre_bash/v1#a "
            "statistics: the primary n moved when an off-pin row was added",
        )

    def test_the_second_question_set_is_reported_in_its_own_section(self):
        self.populate()
        self.restamp("pre_bash/v1#b")
        text = analyze.report(reference="fake")
        self.assertIn("pre_bash/v1#b", text,
                      "the off-pin rows are invisible: neither pooled-and-named "
                      "nor reported separately")
        self.assertIn("pre_bash/v1#a", text,
                      "the report does not name the pin its headline was computed under")

    def test_an_unresolvable_question_set_is_flagged_not_silently_counted(self):
        self.populate()
        before = self.primary_n(analyze.report(reference="fake"))
        self.restamp("pre_bash/v9#a")
        text = analyze.report(reference="fake")
        self.assertEqual(before, self.primary_n(text),
                         "rows naming a question set that does not exist were counted")
        self.assertIn("QUESTION SET", text.upper(),
                      "a row naming a nonexistent question set produced no warning")

    def test_arm_set_eras_are_disclosed(self):
        """JEV-30 left two arm-set eras in the data and no row-level version.

        `arm_order` is the only trace, and it is intrinsic to the row -- unlike
        a wall-clock bisect against the restart, which is the contamination
        JEV-43 exists to remove. Disclosed, deliberately not partitioned: see
        the commit message.
        """
        self.populate()
        text = analyze.report(reference="fake")
        self.assertIn("arm set", text.lower(),
                      "the report does not say which arm set its rows ran under")

    def test_mixed_config_fingerprints_within_one_pin_are_flagged(self):
        """A rate can be edited without bumping `pricing.json:version`.

        `config_fingerprint` is a content hash and catches that; the version
        string cannot. No row on disk carries one yet, so absence must stay
        silent while a DISAGREEMENT must not.
        """
        self.populate()
        for fp in ("aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"):
            self.clone_decisions({"config_fingerprint": fp}, keep=1,
                                 suffix="-fp" + fp[0])
        text = analyze.report(reference="fake")
        self.assertIn("CONFIG FINGERPRINT", text.upper(),
                      "two different configs produced these rows and the report is silent")

    def test_absent_fingerprints_are_not_flagged(self):
        """Every one of the 2,005 rows on disk predates the fingerprint."""
        self.populate()
        text = analyze.report(reference="fake")
        self.assertNotIn("CONFIG FINGERPRINT", text.upper(),
                         "the pre-fingerprint era is being reported as a defect")


class TestSyntheticQuestionSetJoin(TempStorage):
    """synthetic_report resolves the spec at read time too (analyze.py:264)."""

    def test_synthetic_report_names_the_pin_it_applied(self):
        text = analyze.synthetic_report()
        self.assertIn("pre_bash/v1", text,
                      "the synthetic report does not say which question set it applied")


if __name__ == "__main__":
    unittest.main(verbosity=2)
