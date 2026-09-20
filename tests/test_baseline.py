#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-38 / JEV-24a: the persisted "before" baseline.

The properties under test are the ones that make the artifact worth keeping:
it is append-only, it is idempotent, it carries no third-party content, and it
records its own provenance and its own unknowns.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pyversion  # noqa: E402

# JEV-44: assert the floor BEFORE importing anything that does not parse
# below it. The PEP-723 header above binds `uv run` only; `python3
# tests/<this file>` ignores it entirely, and that is the invocation that
# produced 16 SyntaxErrors out of src/arms/jev.py:237.
pyversion.require()


import baseline as bl  # noqa: E402
import paths  # noqa: E402


def rows() -> list[dict]:
    if not bl.SESSIONS.exists():
        return []
    return [json.loads(l) for l in bl.SESSIONS.read_text().splitlines() if l.strip()]


class TestPathsRegistration(unittest.TestCase):
    def test_baseline_is_a_registered_writable_dir(self):
        """paths.py is the single source of truth and doctor asserts against it."""
        self.assertIn(paths.BASELINE, paths.WRITABLE_DIRS)

    def test_baseline_is_inside_the_folder(self):
        self.assertIn(paths.ROOT, paths.BASELINE.parents)

    def test_the_committed_files_are_not_gitignored(self):
        """The whole point is that this survives losing the folder. A carve-out
        that does not actually work is worse than none, because it looks done.
        `data/` (directory) cannot be re-included beneath; `data/*` can."""
        body = (ROOT / ".gitignore").read_text()
        self.assertIn("data/*", body)
        self.assertNotIn("\ndata/\n", body)
        self.assertIn("!data/baseline/sessions.jsonl", body)


class TestSnapshotIsIdempotent(unittest.TestCase):
    """Re-running must never double-count. The corpus is LIVE, so the test
    drives the real code against a temporary stream rather than the real one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._sessions, self._manifest = bl.SESSIONS, bl.MANIFEST
        bl.SESSIONS = self.tmp / "sessions.jsonl"
        bl.MANIFEST = self.tmp / "manifest.json"

    def tearDown(self):
        bl.SESSIONS, bl.MANIFEST = self._sessions, self._manifest

    def test_second_run_on_an_unchanged_corpus_appends_nothing(self):
        if not bl.transcripts():
            self.skipTest("no transcripts for this project on disk")
        first = bl.snapshot()
        n1 = len(bl.SESSIONS.read_text().splitlines())
        second = bl.snapshot()
        n2 = len(bl.SESSIONS.read_text().splitlines())
        # A live session may legitimately grow between the two calls; what must
        # never happen is an unchanged session appending a duplicate row.
        appended = set(second["sessions_appended_this_run"])
        unchanged = set(second["sessions_unchanged_this_run"])
        self.assertEqual(appended & unchanged, set())
        self.assertEqual(n2 - n1, len(appended))
        # A brand-new session can start between the two calls, so the corpus can
        # only grow, never shrink. Asserting equality here made the test fail on
        # correct behaviour.
        self.assertGreaterEqual(second["sessions_captured"], first["sessions_captured"])

    def test_a_changed_fingerprint_appends_exactly_one_row(self):
        if not bl.transcripts():
            self.skipTest("no transcripts for this project on disk")
        bl.snapshot()
        before = len(bl.SESSIONS.read_text().splitlines())
        # Forge an older digest for one session; it must be re-appended.
        lines = bl.SESSIONS.read_text().splitlines()
        row = json.loads(lines[0])
        forged = row["session_id"]
        row["source"]["digest"] = "0" * 32
        lines[0] = json.dumps(row)
        bl.SESSIONS.write_text("\n".join(lines) + "\n")
        result = bl.snapshot()
        after = len(bl.SESSIONS.read_text().splitlines())
        # The corpus is live: another session may legitimately have grown in the
        # interval, so assert against what the run itself reports rather than a
        # hard 1. What must hold is that the forged session came back and that
        # the file grew by exactly the number of sessions claimed.
        self.assertIn(forged, result["sessions_appended_this_run"])
        self.assertEqual(after - before, len(result["sessions_appended_this_run"]))
        self.assertEqual(result["sessions_appended_this_run"].count(forged), 1)


class TestNoThirdPartyContent(unittest.TestCase):
    """The hard rule that already governs data/fixtures/."""

    def test_no_row_carries_a_long_free_text_string(self):
        data = rows()
        if not data:
            self.skipTest("baseline not snapshotted yet")
        for row in data:
            for path, value in self._strings(row):
                self.assertLess(
                    len(value), 80,
                    f"{path} looks like copied content, not a derived number: {value[:60]!r}",
                )

    def test_subagent_descriptions_are_never_copied(self):
        """`subagents/*.meta.json` carries a prompt-derived `description`. It is
        the one field in that file that is third-party content."""
        for row in rows():
            for task in row.get("tasks", []):
                self.assertNotIn("description", task)

    def test_source_is_read_only(self):
        source = (ROOT / "src" / "baseline.py").read_text()
        for forbidden in ("write_text(paths.CLAUDE", "open(paths.CLAUDE_PROJECTS",
                          "shutil.copy", "shutil.move"):
            self.assertNotIn(forbidden, source)

    def _strings(self, obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield from self._strings(v, f"{prefix}.{k}")
        elif isinstance(obj, list):
            for v in obj:
                yield from self._strings(v, f"{prefix}[]")
        elif isinstance(obj, str):
            yield prefix, obj


class TestProvenanceAndUnknowns(unittest.TestCase):
    def test_every_row_records_size_and_mtime(self):
        """So a later re-read can prove it is the same file."""
        data = rows()
        if not data:
            self.skipTest("baseline not snapshotted yet")
        for row in data:
            src = row["source"]
            self.assertIsInstance(src["transcript_size_bytes"], int)
            datetime.fromisoformat(src["transcript_mtime_utc"])
            self.assertEqual(len(src["digest"]), 32)

    def test_retention_is_established_not_guessed(self):
        r = bl.retention_finding()
        self.assertEqual(r["setting"], "cleanupPeriodDays")
        self.assertEqual(r["default_days"], 30)
        self.assertTrue(r["sources"], "a retention claim with no citation is a guess")
        self.assertTrue(any("code.claude.com" in s for s in r["sources"]))

    def test_unrecoverable_reports_a_method_or_says_it_cannot(self):
        """An unknown gap reported as zero is worse than a gap reported honestly."""
        u = bl.unrecoverable()
        if u["determinable"]:
            self.assertIsInstance(u["count"], int)
            self.assertTrue(u["is_lower_bound"])
            self.assertIn("blind_spot", u)
        else:
            self.assertIsNone(u["count"])
            self.assertIn("why_not", u)

    def test_tokens_are_never_summed_into_one_number(self):
        for row in rows():
            for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                        "cache_read_input_tokens", "thinking_tokens"):
                self.assertIn(key, row)
            self.assertNotIn("total_tokens", row)


class TestDelegationBaseline(unittest.TestCase):
    """JEV-24a."""

    def setUp(self):
        if not bl.DELEGATION.exists():
            self.skipTest("delegation baseline not frozen yet")
        self.rec = json.loads(bl.DELEGATION.read_text())

    def test_the_cut_is_fixed_and_attributable(self):
        cut = self.rec["cut"]
        self.assertEqual(cut["timestamp_utc"], bl.Q17B_CUT_UTC)
        self.assertEqual(len(cut["commit"]), 40)

    def test_no_request_after_the_cut_is_counted(self):
        limit = bl._cut()
        for s in self.rec["per_session"]:
            if s["last_request_utc"]:
                self.assertLess(datetime.fromisoformat(s["last_request_utc"]), limit)

    def test_both_measures_are_present(self):
        for scope in ("all_sessions", "interactive_sessions_only"):
            t = self.rec[scope]
            self.assertIn("delegation_rate_by_spend", t)
            self.assertIn("delegation_rate_by_task_count", t)

    def test_the_raw_counts_are_frozen_so_a_denominator_can_be_rechosen(self):
        t = self.rec["all_sessions"]
        for key in ("main_session_cost_usd", "delegated_cost_usd",
                    "delegated_tasks", "human_prompts"):
            self.assertIn(key, t)
        self.assertIn("by_task_count", self.rec["denominators"])

    def test_unpriced_spend_is_counted_not_silently_zeroed(self):
        """A model absent from config/pricing.json prices as None. Coercing it
        to 0.0 would shrink the denominator invisibly."""
        self.assertIn("unpriced_requests", self.rec["all_sessions"])

    def test_the_pricing_snapshot_is_recorded(self):
        """Every cost in the record is computed through config/pricing.json. A
        frozen number whose inputs can move is not frozen -- JEV-28 is expected
        to change Fable's rates."""
        self.assertIn("pricing_version", self.rec)

    def test_re_running_does_not_rewrite_the_frozen_record(self):
        before = bl.DELEGATION.read_text()
        bl.delegation_baseline()
        self.assertEqual(bl.DELEGATION.read_text(), before)

    def test_the_window_is_recorded(self):
        w = self.rec["transcript_window"]
        self.assertEqual(w["cut_utc"], bl.Q17B_CUT_UTC)
        self.assertIn("first_request_utc", w)


if __name__ == "__main__":
    unittest.main(verbosity=2)
