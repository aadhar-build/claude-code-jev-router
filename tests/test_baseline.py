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
import shutil
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
import config_loader as cl  # noqa: E402
import paths  # noqa: E402
import session_metrics as sm  # noqa: E402


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
        # The corrected companion is committed for the same reason and would be
        # silently orphaned by a stray edit above it.
        self.assertIn("!data/baseline/delegation-pre-rule-v1-corrected.json", body)


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


class TestTheCompletedCopyIsTheOneThatCounts(unittest.TestCase):
    """The defect: `baseline.requests()` kept the FIRST copy of a duplicated
    request and never read `usage.iterations[]`.

    Claude Code writes one `(requestId, message.id)` up to nine times as a turn
    streams. The early copies are placeholders carrying `input_tokens: 2`; the
    completed breakdown arrives only in the last. Keeping the first keeps the
    placeholder and throws the turn away -- and all 48 keys that grow across
    their copies in this repo's corpus are inside SUBAGENT transcripts, so the
    loss lands on the delegated side, which is the numerator of the one rate
    the JEV-24a record exists to publish. Measured over the whole corpus the
    two rules gave $105.09 against $171.94.

    Shape below is fabricated to the measured pattern; no transcript content is
    copied into this repo.
    """

    INPUT_RATE = 5e-06
    OUTPUT_RATE = 2.5e-05

    def _transcript(self) -> Path:
        def row(usage):
            return {"type": "assistant", "requestId": "req_s", "isSidechain": True,
                    "timestamp": "2026-09-20T05:36:08Z",
                    "message": {"role": "assistant", "id": "msg_s",
                                "model": "claude-opus-5", "content": [], "usage": usage}}
        placeholder = {"input_tokens": 2, "output_tokens": 0,
                       "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        completed = {"input_tokens": 4, "output_tokens": 691,
                     "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                     "iterations": [{"input_tokens": 2, "output_tokens": 26},
                                    {"input_tokens": 133139, "output_tokens": 350},
                                    {"input_tokens": 2, "output_tokens": 315}]}
        fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        for usage in (placeholder, placeholder, completed):
            fh.write(json.dumps(row(usage)) + "\n")
        fh.close()
        self.addCleanup(lambda: Path(fh.name).unlink(missing_ok=True))
        return Path(fh.name)

    def test_three_copies_are_one_request(self):
        reqs = list(bl.requests(self._transcript()))
        self.assertEqual(len(reqs), 1)
        self.assertTrue(reqs[0]["delegated"])
        self.assertTrue(reqs[0]["priced"])

    def test_the_cost_is_the_completed_copy_not_the_placeholder(self):
        expected = 133143 * self.INPUT_RATE + 691 * self.OUTPUT_RATE
        reqs = list(bl.requests(self._transcript()))
        self.assertAlmostEqual(reqs[0]["cost_usd"], expected, places=9)

    def test_the_quarantined_v1_rule_would_have_said_two_tokens(self):
        """The bug this replaces, stated as a number so it cannot come back."""
        legacy = list(bl.legacy_v1_requests(self._transcript()))
        self.assertEqual(len(legacy), 1)
        self.assertAlmostEqual(legacy[0]["cost_usd"], 2 * self.INPUT_RATE, places=9)
        self.assertLess(legacy[0]["cost_usd"],
                        list(bl.requests(self._transcript()))[0]["cost_usd"])

    def test_the_production_path_does_not_use_the_quarantined_rule(self):
        source = (ROOT / "src" / "baseline.py").read_text()
        walk = source[source.index("def per_session_pre_cut"):
                      source.index("def delegation_baseline_corrected")]
        self.assertNotIn("legacy_v1_requests(path)", walk)


class TestTheTwoModulesMayNotDiverge(unittest.TestCase):
    """Two costing rules that must agree cannot be two pieces of code.

    `baseline.requests` is now a projection of
    `session_metrics.billable_requests`; this fails the moment somebody gives
    baseline.py its own walk again. The identity asserted is the strongest one
    available: per-request costs summed must equal the session-level total,
    which `call_cost` makes exact because it is linear in tokens.
    """

    def _frozen_copy(self, path: Path) -> Path:
        """Copy one session's files -- main transcript plus `subagents/` -- to a
        temp dir so both passes read the SAME BYTES.

        The corpus is live. `run_all.sh` deliberately runs while sessions are
        being written (see its header), so a request appended between the two
        reads would surface as a divergence that is not one. This test must go
        red for exactly one reason: the two rules disagreeing.
        """
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        dest = tmp / path.name
        shutil.copy2(path, dest)
        subs = path.with_suffix("") / "subagents"
        if subs.is_dir():
            out = dest.with_suffix("") / "subagents"
            out.mkdir(parents=True)
            for f in sorted(subs.glob("*.jsonl")):
                shutil.copy2(f, out / f.name)
        return dest

    def _session_total_excluding_web_search(self, path: Path) -> float:
        m = sm.analyse(path)
        web = (m.web_search_requests or 0) * cl.pricing()["web_search_usd_per_request"]
        return m.computed_cost_usd - web

    def test_requests_is_a_projection_of_the_shared_helper(self):
        source = (ROOT / "src" / "baseline.py").read_text()
        body = source[source.index("def requests(path: Path)"):
                      source.index("def legacy_v1_requests")]
        self.assertIn("sm.billable_requests(path)", body)
        for reimplemented in ("dedupe_key(", "normalise_usage(", "merge_copies(",
                              "seen: set", "cl.cost_usd("):
            self.assertNotIn(reimplemented, body,
                             "baseline.py is re-implementing a session_metrics rule; "
                             "that is exactly how the two diverged the first time")

    def test_per_request_costs_sum_to_the_session_total_on_a_fixture(self):
        fixture = TestTheCompletedCopyIsTheOneThatCounts()
        fixture.addCleanup = lambda fn: None
        path = fixture._transcript()
        try:
            total = sum(r["cost_usd"] for r in bl.requests(path))
            self.assertAlmostEqual(total, self._session_total_excluding_web_search(path),
                                   places=9)
        finally:
            path.unlink(missing_ok=True)

    def test_per_request_costs_sum_to_the_session_total_on_the_real_corpus(self):
        found = bl.transcripts()
        if not found:
            self.skipTest("no transcripts for this project on disk")
        checked = 0
        for live in found:
            path = self._frozen_copy(live)
            reqs = list(bl.requests(path))
            if not reqs:
                continue
            if any(not r["priced"] for r in reqs):
                # An unpriced model contributes 0 on both sides, but it also
                # means the session total is a partial. Skip rather than assert
                # an identity that is true for the wrong reason.
                continue
            checked += 1
            self.assertAlmostEqual(
                sum(r["cost_usd"] for r in reqs),
                self._session_total_excluding_web_search(path),
                # session_metrics rounds its session total to 6 places, so the
                # tolerance is that rounding and nothing more. A real divergence
                # between the two rules is cents to dollars, not 5e-7.
                delta=2e-6,
                msg=f"{live.name}: baseline.py and session_metrics.py disagree",
            )
        if not checked:
            self.skipTest("no fully priced session on disk")


class TestTheFrozenRecordIsImmutable(unittest.TestCase):
    """The frozen record is the only 'before' the project has. Finding a defect
    in how it was computed is exactly the moment somebody reaches for --force."""

    def test_force_is_refused_rather_than_honoured(self):
        if not bl.DELEGATION.exists():
            self.skipTest("delegation baseline not frozen yet")
        before = bl.DELEGATION.read_text()
        with self.assertRaises(RuntimeError):
            bl.delegation_baseline(force=True)
        self.assertEqual(bl.DELEGATION.read_text(), before)


class TestCorrectedCompanion(unittest.TestCase):
    """The correction is published beside the frozen record, never over it."""

    def setUp(self):
        if not bl.CORRECTED.exists():
            self.skipTest("corrected companion not written yet")
        self.rec = json.loads(bl.CORRECTED.read_text())

    def test_it_names_the_rule_that_produced_it(self):
        self.assertEqual(self.rec["costing_rule"]["name"],
                         "session_metrics.billable_requests")
        self.assertEqual(self.rec["costing_rule"]["dedupe_key"],
                         "(requestId, message.id)")

    def test_it_preserves_the_frozen_record_rather_than_replacing_it(self):
        self.assertTrue(bl.DELEGATION.exists())
        self.assertEqual(self.rec["supersedes_for_analysis"], bl.DELEGATION.name)
        self.assertIsNotNone(self.rec["as_frozen"]["all_sessions"])

    def test_it_uses_the_same_cut_as_the_frozen_record(self):
        self.assertEqual(self.rec["cut"]["timestamp_utc"], bl.Q17B_CUT_UTC)
        self.assertTrue(self.rec["cut"]["same_cut_as_frozen"])

    def test_both_sides_of_the_rate_are_recomputed(self):
        old = self.rec["frozen_rule_today"]["interactive_sessions_only"]
        new = self.rec["corrected"]["interactive_sessions_only"]
        self.assertGreater(new["delegated_cost_usd"], old["delegated_cost_usd"])
        self.assertGreater(new["main_session_cost_usd"], old["main_session_cost_usd"])
        self.assertGreater(new["delegation_rate_by_spend"],
                           old["delegation_rate_by_spend"])

    def test_it_is_labelled_a_lower_bound(self):
        self.assertIn("LOWER BOUND", self.rec["lower_bound"])
        self.assertIn("27.6", self.rec["lower_bound"])

    def test_it_records_the_corpus_it_actually_read(self):
        """paths.ROOT is the worktree when this runs from one, and the slug
        Claude Code keys transcripts on would then be a near-empty corpus."""
        self.assertIn("transcript_dir", self.rec["corpus"])
        self.assertIn("project_root", self.rec["corpus"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
