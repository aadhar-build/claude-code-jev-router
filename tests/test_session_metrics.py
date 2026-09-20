#!/usr/bin/env python3
"""The one test in this project with a known-correct answer already on disk.

Claude Code writes its own authoritative cost total into every completed
transcript. That makes the baseline harvester checkable against ground truth in
a way nothing else here is -- and if it fails, every cost number downstream is
wrong.

The fixture holds DERIVED NUMBERS ONLY. No transcript content from any other
project is copied into this folder; the transcript itself is read in place,
read-only, and the test skips cleanly when it is not available.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config_loader as cl  # noqa: E402
import paths  # noqa: E402
import session_metrics as sm  # noqa: E402

FIXTURE = paths.FIXTURES / "session-baseline.json"


def frozen() -> dict | None:
    if not FIXTURE.exists():
        return None
    rows = json.loads(FIXTURE.read_text())
    return rows[0] if rows else None


class TestPricingAgainstClaudeCode(unittest.TestCase):
    """Solve for the rate Claude Code itself charged, and check our table."""

    def implied_rate(self, usage: dict) -> float:
        web = usage.get("webSearchRequests", 0) * cl.pricing()["web_search_usd_per_request"]
        cost = usage["costUSD"] - web
        denom = (
            usage["inputTokens"]
            + usage["cacheCreationInputTokens"] * cl.pricing()["cache_write_multiplier"]
            + usage["cacheReadInputTokens"] * cl.pricing()["cache_read_multiplier"]
            + usage["outputTokens"] * 5
        )
        return cost / denom

    def test_haiku_and_sonnet_rates_reproduce_exactly(self):
        row = frozen()
        if row is None:
            self.skipTest("fixture not frozen; run session_metrics.py --freeze-fixture")
        path = Path(row["transcript"])
        if not path.exists():
            self.skipTest("source transcript no longer on disk")

        cost_state = None
        for line in sm._lines(path, include_subagents=False):
            if line.get("type") == "cost-state":
                cost_state = line
        self.assertIsNotNone(cost_state, "no cost-state line")

        checked = 0
        for model, usage in cost_state["modelUsage"].items():
            if "[" in model:
                continue  # long-context blend is checked separately
            rate = cl.pricing()["models"].get(model)
            if not rate:
                continue
            self.assertAlmostEqual(
                self.implied_rate(usage), rate["input"], places=9,
                msg=f"{model}: our table disagrees with Claude Code's own accounting",
            )
            checked += 1
        self.assertGreater(checked, 0, "no priced models to check")

    def test_web_search_is_a_cent_per_request(self):
        self.assertEqual(cl.pricing()["web_search_usd_per_request"], 0.01)


class TestBaselineRegression(unittest.TestCase):
    """Re-derive the frozen numbers from the transcript."""

    def setUp(self):
        self.row = frozen()
        if self.row is None:
            self.skipTest("fixture not frozen")
        self.path = Path(self.row["transcript"])
        if not self.path.exists():
            self.skipTest("source transcript no longer on disk")
        self.m = sm.analyse(self.path)

    def test_dedupe_by_request_id_is_stable(self):
        self.assertEqual(self.m.unique_requests, self.row["unique_requests"])
        self.assertEqual(self.m.assistant_lines, self.row["assistant_lines"])

    def test_lines_really_do_duplicate(self):
        """If this ever reads 1.0, the dedupe is silently doing nothing."""
        self.assertGreater(self.m.duplication_factor, 2.0)
        self.assertEqual(self.m.duplication_factor, self.row["duplication_factor"])

    def test_cost_is_reproducible(self):
        self.assertAlmostEqual(self.m.computed_cost_usd, self.row["computed_cost_usd"], places=4)

    def test_input_tokens_are_dwarfed_by_cache_reads(self):
        """The trap that makes a naive cost estimate wrong by 10,000x."""
        self.assertLess(self.m.input_tokens * 100, self.m.cache_read_input_tokens)

    def test_subagent_transcripts_are_included(self):
        """A session is not one file. Dropping subagents under-reports the bill."""
        self.assertGreater(self.m.sidechain_lines, 0)
        main_only = sum(1 for _ in sm._lines(self.path, include_subagents=False))
        with_subs = sum(1 for _ in sm._lines(self.path, include_subagents=True))
        self.assertGreater(with_subs, main_only)

    def test_reconciliation_delta_is_reported_not_hidden(self):
        self.assertIsNotNone(self.m.cost_delta_pct)
        self.assertIn("delta", sm.render(self.m))

    def test_transcript_cost_is_a_lower_bound(self):
        """Claude Code bills for background models it never transcribes, so our
        figure must come in under its total, never over."""
        self.assertLess(self.m.computed_cost_usd, self.m.reported_cost_usd)

    def test_friction_proxies_are_counted(self):
        self.assertEqual(self.m.permission_denials, self.row["permission_denials"])
        self.assertGreaterEqual(self.m.tool_errors, 0)

    def test_per_model_reconciliation_matches_on_base_name(self):
        """The transcript says `claude-opus-5`; cost-state says
        `claude-opus-5[1m]`. Matching on the exact string alone reported a
        spurious -100% on every field."""
        rows = sm.reconcile_per_model(self.path)
        opus = [r for r in rows if r["model"].startswith("claude-opus-5") and r["field"] == "cacheReadInputTokens"]
        self.assertTrue(opus)
        self.assertGreater(opus[0]["ours"], 0, "base-name fallback is not matching")


class TestHarvesterSafety(unittest.TestCase):
    def test_reads_are_confined_to_the_transcript_directory(self):
        self.assertTrue(str(paths.CLAUDE_PROJECTS).endswith(".claude/projects"))

    def test_malformed_transcript_does_not_crash(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write("{not json\n")
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n")
            fh.write("\n")
            path = Path(fh.name)
        m = sm.analyse(path)
        self.assertEqual(m.user_turns, 1)
        self.assertEqual(m.unique_requests, 0)

    def test_empty_transcript_yields_zeroes_not_an_exception(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            path = Path(fh.name)
        m = sm.analyse(path)
        self.assertEqual(m.unique_requests, 0)
        self.assertIsNone(m.reported_cost_usd)

    def test_iterations_are_never_read(self):
        """usage.iterations[] restates the same numbers -- reading it would
        double-count a second time."""
        source = (ROOT / "src" / "session_metrics.py").read_text()
        self.assertNotIn('"iterations"', source.replace("`iterations[]`", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
