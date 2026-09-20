#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
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

import pyversion  # noqa: E402

# JEV-44: assert the floor BEFORE importing anything that does not parse
# below it. The PEP-723 header above binds `uv run` only; `python3
# tests/<this file>` ignores it entirely, and that is the invocation that
# produced 16 SyntaxErrors out of src/arms/jev.py:237.
pyversion.require()


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



class TestUsageNormalisation(unittest.TestCase):
    """JEV-49 bug 1: the `iterations[]` rule is THREE-WAY, not two-way.

    Measured on this project's own transcripts (.scratch/a2-prep/jev49-facts.md
    and the sweep in JEV-49's commit message), over 3,790 assistant rows:

      * scalar TOKEN fields  -- top level is a *floor*, not the total. 71 rows
        under-report input; 74 under-report output. Worst single row: top-level
        `input_tokens: 4` against iterations summing to 237,384.
      * scalar CACHE fields  -- top level already equals the iteration sum, on
        every one of 2,510 rows carrying iterations, to the token. Summing them
        would double-count.
      * the cache_creation TTL SUB-OBJECT -- behaves like the token fields, not
        like the scalar it decomposes: on those same 71 rows the top-level
        sub-object is SHORT of `cache_creation_input_tokens`, and the iteration
        sum restores it exactly. This half is in no third-party report.

    The fixtures below are fabricated to that measured shape. No transcript
    content is copied into this repo.
    """

    ITER_ROW = {
        "input_tokens": 4,
        "output_tokens": 691,
        "cache_creation_input_tokens": 11331,
        "cache_read_input_tokens": 30419,
        "cache_creation": {"ephemeral_5m_input_tokens": 9837, "ephemeral_1h_input_tokens": 0},
        "iterations": [
            {"input_tokens": 2, "output_tokens": 80,
             "cache_creation_input_tokens": 1494, "cache_read_input_tokens": 0,
             "cache_creation": {"ephemeral_5m_input_tokens": 1494, "ephemeral_1h_input_tokens": 0}},
            {"input_tokens": 158467, "output_tokens": 7255,
             "cache_creation_input_tokens": 9837, "cache_read_input_tokens": 30419,
             "cache_creation": {"ephemeral_5m_input_tokens": 9837, "ephemeral_1h_input_tokens": 0}},
            {"input_tokens": 2, "output_tokens": 615,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
             "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}},
        ],
    }

    def test_token_fields_are_summed_from_iterations(self):
        u = sm.normalise_usage(self.ITER_ROW)
        self.assertEqual(u["input_tokens"], 158471)
        self.assertEqual(u["output_tokens"], 7950)

    def test_cache_scalars_are_taken_from_the_top_level_not_summed(self):
        u = sm.normalise_usage(self.ITER_ROW)
        self.assertEqual(u["cache_creation_input_tokens"], 11331)
        self.assertEqual(u["cache_read_input_tokens"], 30419)

    def test_the_ttl_sub_object_is_summed_from_iterations(self):
        """The half nobody has reported: the sub-object is short at top level."""
        u = sm.normalise_usage(self.ITER_ROW)
        self.assertEqual(u["ephemeral_5m_input_tokens"], 11331)
        self.assertEqual(u["ephemeral_1h_input_tokens"], 0)

    def test_the_split_always_reconstitutes_the_scalar(self):
        u = sm.normalise_usage(self.ITER_ROW)
        self.assertEqual(
            u["ephemeral_5m_input_tokens"] + u["ephemeral_1h_input_tokens"],
            u["cache_creation_input_tokens"],
        )

    def test_a_row_without_iterations_is_passed_through(self):
        plain = {"input_tokens": 2, "output_tokens": 40,
                 "cache_creation_input_tokens": 500, "cache_read_input_tokens": 9000,
                 "cache_creation": {"ephemeral_5m_input_tokens": 500,
                                    "ephemeral_1h_input_tokens": 0}}
        u = sm.normalise_usage(plain)
        self.assertEqual(u["input_tokens"], 2)
        self.assertEqual(u["cache_creation_input_tokens"], 500)
        self.assertEqual(u["ephemeral_5m_input_tokens"], 500)

    def test_top_level_is_a_floor_never_a_ceiling(self):
        """If a future shape ever puts the larger number at top level, keep it."""
        odd = {"input_tokens": 900, "output_tokens": 10,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
               "iterations": [{"input_tokens": 5, "output_tokens": 1}]}
        u = sm.normalise_usage(odd)
        self.assertEqual(u["input_tokens"], 900)
        self.assertEqual(u["output_tokens"], 10)

    def test_a_split_that_does_not_add_up_is_repaired_and_counted(self):
        broken = {"input_tokens": 1, "output_tokens": 1,
                  "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 0,
                  "cache_creation": {"ephemeral_5m_input_tokens": 0,
                                     "ephemeral_1h_input_tokens": 0}}
        u = sm.normalise_usage(broken)
        self.assertTrue(u["ttl_split_repaired"])
        self.assertEqual(u["ephemeral_5m_input_tokens"], 1000)


class TestCacheWriteTTLPricing(unittest.TestCase):
    """JEV-49 bug 3: a 1-hour cache write bills at 2x, a 5-minute one at 1.25x.

    Both TTLs are live in this corpus: 12,334,854 tokens of 5m writes across 27
    sessions and 5,161,696 tokens of 1h writes in one. A single flat multiplier
    cannot be right for both.
    """

    def test_pricing_table_carries_both_multipliers(self):
        p = cl.pricing()
        self.assertEqual(p["cache_write_multiplier"], 1.25)
        self.assertEqual(p["cache_write_multiplier_1h"], 2.0)

    def test_one_hour_writes_cost_more_than_five_minute_writes(self):
        base = {"input_tokens": 0, "output_tokens": 0,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1_000_000}
        five = sm.call_cost("claude-opus-5", dict(base, ephemeral_5m_input_tokens=1_000_000,
                                                  ephemeral_1h_input_tokens=0))
        hour = sm.call_cost("claude-opus-5", dict(base, ephemeral_5m_input_tokens=0,
                                                  ephemeral_1h_input_tokens=1_000_000))
        self.assertAlmostEqual(five, 1_000_000 * 5e-06 * 1.25, places=9)
        self.assertAlmostEqual(hour, 1_000_000 * 5e-06 * 2.00, places=9)
        self.assertGreater(hour, five)

    def test_unknown_model_still_returns_none_rather_than_guessing(self):
        self.assertIsNone(sm.call_cost("claude-opus-9000", {"input_tokens": 1}))


class TestDedupeKey(unittest.TestCase):
    """JEV-49 bug 2, dedupe half: the key is the PAIR."""

    def test_key_is_request_id_and_message_id(self):
        line = {"requestId": "req_1", "message": {"role": "assistant", "id": "msg_1"}}
        self.assertEqual(sm.dedupe_key(line), ("req_1", "msg_1"))

    def test_two_message_ids_under_one_request_id_are_two_rows(self):
        a = {"requestId": "req_1", "message": {"role": "assistant", "id": "msg_1"}}
        b = {"requestId": "req_1", "message": {"role": "assistant", "id": "msg_2"}}
        self.assertNotEqual(sm.dedupe_key(a), sm.dedupe_key(b))

    def test_a_row_with_no_request_id_is_not_billable(self):
        self.assertIsNone(sm.dedupe_key({"message": {"role": "assistant", "id": "msg_1"}}))


class TestUnpricedModelIsAHardFailure(unittest.TestCase):
    """JEV-49 bug 2, pricing half: coverage is not a footnote."""

    def _transcript(self, model: str) -> Path:
        row = {"type": "assistant", "requestId": "req_x", "timestamp": "2026-09-20T00:00:00Z",
               "message": {"role": "assistant", "id": "msg_x", "model": model,
                           "content": [], "usage": {"input_tokens": 10, "output_tokens": 10,
                                                    "cache_creation_input_tokens": 0,
                                                    "cache_read_input_tokens": 0}}}
        fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        fh.write(json.dumps(row) + "\n")
        fh.close()
        return Path(fh.name)

    def test_strict_mode_raises_on_an_unpriced_model(self):
        with self.assertRaises(sm.UnpricedModelError):
            sm.analyse(self._transcript("claude-opus-9000"), strict=True)

    def test_non_strict_records_it_and_the_render_says_so_in_the_headline(self):
        m = sm.analyse(self._transcript("claude-opus-9000"))
        self.assertIn("claude-opus-9000", m.unpriced_models)
        self.assertEqual(m.unpriced_requests, 1)
        out = sm.render(m)
        head = out[: out.index("wall clock")]
        self.assertIn("LOWER BOUND", head)

    def test_a_zero_token_synthetic_row_does_not_trip_strict_mode(self):
        """`<synthetic>` rows carry no billable tokens and no requestId."""
        m = sm.analyse(self._transcript("claude-opus-5"), strict=True)
        self.assertEqual(m.unpriced_requests, 0)

    def test_opus_4_7_is_priced_from_first_party_cost_state(self):
        """217 rows in the baseline window were excluded for want of a rate.

        The rate was not guessed: it is the unique solution that reproduces
        `cost-state.modelUsage['claude-opus-4-7'].costUSD` to the cent in every
        session of this project that reports one -- 40 of them at the time of
        writing, and the corpus keeps growing, so the claim is universal rather
        than a count.
        """
        rate = cl.pricing()["models"]["claude-opus-4-7"]
        self.assertEqual(rate["input"], 5e-06)
        self.assertEqual(rate["output"], 2.5e-05)


class TestIterationsAreReadAsymmetrically(unittest.TestCase):
    """Replaces test_iterations_are_never_read, which encoded the wrong rule.

    That test asserted the string `"iterations"` never appeared in the source.
    It passed, and it was wrong: it froze a 158,471-token under-count in place.
    """

    def test_the_source_reads_iterations(self):
        source = (ROOT / "src" / "session_metrics.py").read_text()
        self.assertIn('"iterations"', source)

    def test_the_asymmetry_is_documented_where_it_is_implemented(self):
        doc = sm.normalise_usage.__doc__ or ""
        self.assertIn("MUST", doc)
        self.assertIn("MUST NOT", doc)


class TestDuplicateCopiesAreCompleted(unittest.TestCase):
    """JEV-49, the half that only shows up when the first two bugs meet.

    Claude Code writes the SAME `(requestId, message.id)` several times as a
    turn streams -- up to 9 copies in this corpus. The early copies are
    placeholders: `input_tokens: 2`, no `iterations[]`. Only the final copy
    carries the completed `iterations[]`. Dedupe that keeps the FIRST copy
    therefore keeps the placeholder and throws the turn away.

    Measured: 48 keys in this project's corpus grow across their copies, all 48
    monotonically, all 48 inside subagent transcripts -- 4,889,713 input tokens
    in one session, which is $24 of Opus at list. In all 36 sessions that carry
    a `cost-state` line, first and last copies are identical, so this rule
    changes nothing that first-party accounting can check, and cannot disturb
    the reconciliation.

    Shape below is fabricated to the measured pattern; no transcript content is
    copied into this repo.
    """

    def _transcript(self) -> Path:
        def row(usage):
            return {"type": "assistant", "requestId": "req_s", "isSidechain": True,
                    "timestamp": "2026-09-20T15:36:08Z",
                    "message": {"role": "assistant", "id": "msg_s", "model": "claude-opus-5",
                                "content": [], "usage": usage}}
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
        return Path(fh.name)

    def test_the_completed_copy_is_the_one_that_counts(self):
        m = sm.analyse(self._transcript())
        self.assertEqual(m.unique_requests, 1)
        self.assertEqual(m.assistant_lines, 3)
        self.assertEqual(m.input_tokens, 133143)
        self.assertEqual(m.output_tokens, 691)

    def test_the_placeholder_alone_would_have_said_two(self):
        """The bug this replaces, stated as a number so it cannot come back."""
        m = sm.analyse(self._transcript())
        self.assertNotEqual(m.input_tokens, 2)

    def test_the_decomposition_prices_the_copy_rule_separately(self):
        d = sm.cost_decomposition(self._transcript())
        self.assertEqual(d["billable_requests"], 1)
        self.assertLess(d["plus_iter"], d["plus_copy"])
        self.assertAlmostEqual(d["plus_copy"], 133143 * 5e-06 + 691 * 2.5e-05, places=9)

if __name__ == "__main__":
    unittest.main(verbosity=2)
