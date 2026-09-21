#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-06's missing half: the module that compares a before to an after.

Everything here is in-process, runs against temporary directories and
hand-built fixtures, reads no live state and makes no API call. What it pins
is the set of properties that make the report safe to read rather than merely
informative:

  * "no after corpus exists" is not "$0.00". This repository's most repeated
    lesson, and the one the no-data path exists to honour.
  * a guard that could not run never reads as a guard that passed (exit 1).
  * two figures from different analysis windows cannot be differenced -- the
    $2.88-vs-$5.21 trap raises rather than printing a number.
  * task duration is never presented as a speed win for the human, and the
    two denominators are never a ratio.
  * escalations that nothing records report NOT OBSERVABLE, not 0.
  * every dollar carries its lower-bound tag.
"""

from __future__ import annotations

import io
import json
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pyversion  # noqa: E402

pyversion.require()

import assignment_ledger  # noqa: E402
import report  # noqa: E402
from accuracy_gate import (  # noqa: E402
    EXIT_CLEAN,
    EXIT_COULD_NOT_RUN,
    EXIT_INVOKED_WRONG,
    EXIT_REGRESSION,
    FAIL,
    NOT_EVALUABLE,
    PASS,
)

CORRECTED = ROOT / "data" / "baseline" / "delegation-pre-rule-v1-corrected.json"
FROZEN_V1 = ROOT / "data" / "baseline" / "delegation-pre-rule-v1.json"

PROJECT = "/tmp/fake-project"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def window(label="w", *, starts, ends, scope="interactive_sessions_only",
           project=PROJECT, pricing="pricing-2026-09-20b",
           rule="session_metrics.billable_requests") -> report.Window:
    return report.Window(label=label, scope=scope, costing_rule=rule,
                         pricing_version=pricing, project=project,
                         starts_at=starts, ends_at=ends)


BEFORE_WINDOW = window("before", starts="2026-09-19T00:00:00Z",
                       ends="2026-09-20T11:11:49Z")
AFTER_WINDOW = window("after", starts="2026-09-22T00:00:00Z",
                      ends="2026-09-23T00:00:00Z")


def task(tool_use_id="tu", *, attempts=1, outcome_found=True, completed=True,
         task_s=800.0, block_s=1.5, cost=2.0, hook_ms=None,
         tier="haiku45") -> report.TaskRow:
    return report.TaskRow(
        tool_use_id=tool_use_id, tier=tier, project=PROJECT, attempts=attempts,
        outcome_found=outcome_found, completed=completed,
        task_duration_s=task_s, blocking_duration_s=block_s, cost_usd=cost,
        hook_ms=hook_ms)


def side(label, win, tasks, *, router=False) -> report.Side:
    return report.Side(label=label, window=win, source=f"<{label} fixture>",
                       tasks=tasks, router_present=router,
                       notes=[report.LOWER_BOUND_NOTE])


def run_cli(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = report.main(list(argv))
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# The window guard -- the trap this project has already fallen into twice
# ---------------------------------------------------------------------------

class TestWindowGuard(unittest.TestCase):

    def test_the_2_88_vs_5_21_comparison_raises(self):
        """$2.88 is the JEV-24a cut; $5.21 is the whole corpus. Two cuts of ONE
        corpus, and differencing them measures the cut, not a change."""
        pre_cut = window("pre-cut", starts="2026-09-19T19:58:56Z",
                         ends="2026-09-20T11:11:49Z")
        whole = window("whole corpus", starts="2026-09-19T19:58:56Z",
                       ends="2026-09-21T00:00:00Z")
        a = report.Figure("cost/task", report.CORRECTED_ANCHOR_USD, "USD", 7,
                          pre_cut)
        b = report.Figure("cost/task", report.WHOLE_CORPUS_ANCHOR_USD, "USD", 33,
                          whole)
        with self.assertRaises(report.WindowsDiffer) as ctx:
            report.diff(a, b)
        self.assertIn("disjoint", str(ctx.exception))
        self.assertIn("2.88", str(ctx.exception))
        self.assertIn("5.21", str(ctx.exception))

    def test_overlapping_windows_raise_even_when_everything_else_matches(self):
        after = window("after", starts="2026-09-20T00:00:00Z",
                       ends="2026-09-22T00:00:00Z")
        with self.assertRaises(report.WindowsDiffer):
            report.comparable(BEFORE_WINDOW, after)

    def test_unknown_bounds_are_never_provably_disjoint(self):
        """A missing bound is not a benign default. It refuses."""
        open_ended = window("after", starts=None, ends=None)
        with self.assertRaises(report.WindowsDiffer):
            report.comparable(BEFORE_WINDOW, open_ended)

    def test_scope_pricing_rule_and_project_must_all_match(self):
        for kwargs in ({"scope": "all_sessions"},
                       {"pricing": "pricing-2026-09-20"},
                       {"rule": "baseline.legacy_v1_requests"},
                       {"project": "/some/other/repo"}):
            with self.subTest(**kwargs):
                other = window("after", starts="2026-09-22T00:00:00Z",
                               ends="2026-09-23T00:00:00Z", **kwargs)
                with self.assertRaises(report.WindowsDiffer):
                    report.comparable(BEFORE_WINDOW, other)

    def test_a_label_is_not_part_of_comparability(self):
        """Renaming a window does not make it a different population."""
        report.comparable(BEFORE_WINDOW, window("renamed",
                                                starts="2026-09-22T00:00:00Z",
                                                ends="2026-09-23T00:00:00Z"))

    def test_diff_refuses_a_missing_value_rather_than_calling_it_no_change(self):
        a = report.Figure("x", None, "USD", 0, BEFORE_WINDOW)
        b = report.Figure("x", 1.0, "USD", 1, AFTER_WINDOW)
        with self.assertRaises(report.CouldNotRun):
            report.diff(a, b)


# ---------------------------------------------------------------------------
# The before anchor
# ---------------------------------------------------------------------------

class TestBeforeAnchor(unittest.TestCase):

    def test_the_corrected_anchor_reads_2_88(self):
        s = report.side_from_corrected_baseline(
            CORRECTED, scope="interactive_sessions_only", project=PROJECT)
        self.assertEqual(s.n_tasks, 7)
        self.assertAlmostEqual(s.cost_per_delegated_task().value,
                               report.CORRECTED_ANCHOR_USD, places=6)
        self.assertEqual(s.window.ends_at, "2026-09-20T11:11:49Z")

    def test_the_frozen_v1_record_is_refused(self):
        """It was computed under the defective rule and understates by 45.2%."""
        self.assertTrue(FROZEN_V1.exists())
        with self.assertRaises(report.InvokedWrong):
            report.side_from_corrected_baseline(
                FROZEN_V1, scope="interactive_sessions_only", project=PROJECT)

    def test_the_anchor_carries_no_per_task_rows_and_says_so(self):
        s = report.side_from_corrected_baseline(
            CORRECTED, scope="interactive_sessions_only", project=PROJECT)
        self.assertIsNone(s.tasks)
        self.assertIsNone(s.rework)
        self.assertEqual(s.blocking_values, [])

    def test_an_unknown_scope_is_invoked_wrong_not_a_silent_default(self):
        with self.assertRaises(report.InvokedWrong):
            report.side_from_corrected_baseline(
                CORRECTED, scope="whatever", project=PROJECT)


# ---------------------------------------------------------------------------
# R1
# ---------------------------------------------------------------------------

class TestR1Rework(unittest.TestCase):

    def test_a_retried_task_contributes_attempts_minus_one(self):
        s = side("after", AFTER_WINDOW, [task("a", attempts=3), task("b")],
                 router=True)
        self.assertEqual(s.rework.retries, 2)

    def test_a_task_that_ran_and_did_not_finish_is_a_failure(self):
        s = side("after", AFTER_WINDOW,
                 [task("a", completed=False), task("b")], router=True)
        self.assertEqual(s.rework.failures, 1)

    def test_attrition_is_reported_beside_r1_and_not_folded_into_it(self):
        s = side("after", AFTER_WINDOW,
                 [task("a", outcome_found=False, completed=True), task("b")],
                 router=True)
        self.assertEqual(s.rework.attrition, 1)
        self.assertEqual(s.rework.failures, 0)
        self.assertEqual(s.rework.observed_events, 0)

    def test_escalations_are_NOT_OBSERVABLE_never_zero_on_the_routed_side(self):
        """Nothing in src/ records an escalation: `tier_map.FAILURES` has no
        escalation outcome and operator decision 3 (RESTART) is unimplemented.
        A 0 here would be a guard that could not run reading as one that
        passed, one level down."""
        s = side("after", AFTER_WINDOW, [task("a")], router=True)
        self.assertIsNone(s.rework.escalations)
        self.assertIn("NOT OBSERVABLE", s.rework.escalations_note.upper())
        _, body = report.r1_rework(
            side("before", BEFORE_WINDOW, [task("z")]), s)
        text = "\n".join(body)
        self.assertIn("NOT OBSERVABLE", text)

    def test_escalations_are_zero_BY_CONSTRUCTION_on_an_unrouted_side(self):
        s = side("before", BEFORE_WINDOW, [task("a")], router=False)
        self.assertEqual(s.rework.escalations, 0)
        self.assertIn("BY CONSTRUCTION", s.rework.escalations_note)

    def test_an_increase_in_rework_is_a_regression(self):
        before = side("before", BEFORE_WINDOW, [task("a"), task("b")])
        after = side("after", AFTER_WINDOW,
                     [task("a", attempts=2), task("b")], router=True)
        criterion, _ = report.r1_rework(before, after)
        self.assertEqual(criterion.status, FAIL)
        self.assertEqual(criterion.exit_code, EXIT_REGRESSION)

    def test_no_increase_passes(self):
        before = side("before", BEFORE_WINDOW, [task("a", attempts=2), task("b")])
        after = side("after", AFTER_WINDOW, [task("a"), task("b")], router=True)
        criterion, _ = report.r1_rework(before, after)
        self.assertEqual(criterion.status, PASS)

    def test_a_side_with_no_rows_is_not_evaluable_never_zero_rework(self):
        before = report.side_from_corrected_baseline(
            CORRECTED, scope="interactive_sessions_only", project=PROJECT)
        after = side("after", AFTER_WINDOW, [task("a")], router=True)
        criterion, body = report.r1_rework(before, after)
        self.assertEqual(criterion.status, NOT_EVALUABLE)
        self.assertEqual(criterion.exit_code, EXIT_COULD_NOT_RUN)
        self.assertIn("NOT zero", "\n".join(body))


# ---------------------------------------------------------------------------
# R2
# ---------------------------------------------------------------------------

class TestR2Latency(unittest.TestCase):

    def _rendered(self):
        before = side("before", BEFORE_WINDOW,
                      [task("a", task_s=794.6, block_s=1.5),
                       task("b", task_s=900.0, block_s=2.0)])
        after = side("after", AFTER_WINDOW,
                     [task("c", task_s=400.0, block_s=1.4),
                      task("d", task_s=410.0, block_s=1.6)], router=True)
        criterion, body = report.r2_latency(before, after)
        return criterion, "\n".join(body)

    def test_the_two_durations_are_reported_separately(self):
        _, text = self._rendered()
        self.assertIn("BLOCKING duration", text)
        self.assertIn("TASK duration", text)

    def test_the_two_denominators_are_stated_and_are_not_a_ratio(self):
        _, text = self._rendered()
        self.assertIn("NOT A RATIO", text)
        self.assertIn("Do not divide one by the other", text)
        # No line divides one duration by the other, in either direction.
        for forbidden in ("/ blocking", "/ task", "530x", "x faster"):
            self.assertNotIn(forbidden, text, msg=forbidden)

    def test_a_task_duration_halving_is_never_a_speed_win_for_the_human(self):
        """Task duration drops from ~800s to ~400s here. The verdict must be
        driven by the BLOCKING number, and the caveat must be present."""
        criterion, text = self._rendered()
        self.assertIn("CANNOT improve felt latency", text)
        self.assertIn("background", text)
        self.assertIn("blocking", criterion.name)

    def test_a_blocking_regression_fails(self):
        before = side("before", BEFORE_WINDOW, [task("a", block_s=1.0)])
        after = side("after", AFTER_WINDOW, [task("b", block_s=9.0)], router=True)
        criterion, _ = report.r2_latency(before, after)
        self.assertEqual(criterion.status, FAIL)

    def test_a_blocking_reduction_demands_a_mechanism_other_than_routing(self):
        before = side("before", BEFORE_WINDOW, [task("a", block_s=5.0)])
        after = side("after", AFTER_WINDOW, [task("b", block_s=1.0)], router=True)
        _, body = report.r2_latency(before, after)
        self.assertIn("needs a mechanism other than routing", "\n".join(body))

    def test_p50_and_p95_come_from_stats_quantiles(self):
        _, text = self._rendered()
        self.assertIn("p50=", text)
        self.assertIn("p95=", text)

    def test_a_side_with_no_blocking_values_is_not_evaluable(self):
        before = report.side_from_corrected_baseline(
            CORRECTED, scope="interactive_sessions_only", project=PROJECT)
        after = side("after", AFTER_WINDOW, [task("a")], router=True)
        criterion, body = report.r2_latency(before, after)
        self.assertEqual(criterion.status, NOT_EVALUABLE)
        self.assertIn("NOT zero", "\n".join(body))


# ---------------------------------------------------------------------------
# R3
# ---------------------------------------------------------------------------

class TestR3Quality(unittest.TestCase):

    def test_no_gate_verdict_is_NOT_a_pass(self):
        criterion, body = report.r3_quality(None, "")
        self.assertEqual(criterion.status, NOT_EVALUABLE)
        self.assertEqual(criterion.exit_code, EXIT_COULD_NOT_RUN)
        self.assertIn("THIS IS NOT A PASS", "\n".join(body))

    def test_gate_exit_1_is_not_a_pass_either(self):
        criterion, _ = report.r3_quality(EXIT_COULD_NOT_RUN, "")
        self.assertEqual(criterion.status, NOT_EVALUABLE)

    def test_gate_exit_2_is_not_a_pass_either(self):
        criterion, _ = report.r3_quality(EXIT_INVOKED_WRONG, "")
        self.assertEqual(criterion.status, NOT_EVALUABLE)

    def test_gate_exit_3_is_a_regression(self):
        criterion, _ = report.r3_quality(EXIT_REGRESSION, "")
        self.assertEqual(criterion.status, FAIL)
        self.assertEqual(criterion.exit_code, EXIT_REGRESSION)

    def test_gate_exit_0_passes_and_says_what_green_means(self):
        criterion, body = report.r3_quality(EXIT_CLEAN, "")
        self.assertEqual(criterion.status, PASS)
        self.assertIn("NO LARGE REGRESSION", "\n".join(body))


# ---------------------------------------------------------------------------
# R4
# ---------------------------------------------------------------------------

class TestR4Overhead(unittest.TestCase):

    def test_the_layers_own_latency_is_reported_in_the_wins_units(self):
        before = side("before", BEFORE_WINDOW, [task("a", block_s=2.0, cost=2.0)])
        after = side("after", AFTER_WINDOW,
                     [task("b", block_s=1.5, hook_ms=600.0, cost=1.0)],
                     router=True)
        r2, _ = report.r2_latency(before, after)
        _, _, delta5 = report.r5_cost(before, after)
        criterion, body = report.r4_overhead(before, after, r2, delta5)
        text = "\n".join(body)
        self.assertIn("router hook latency", text)
        self.assertIn("NET LATENCY", text)
        self.assertIn("NET SPEND", text)
        # -0.5s saved, +0.6s of hook: the layer costs more than it saves.
        self.assertAlmostEqual(criterion.value, 0.1, places=6)
        self.assertEqual(criterion.status, FAIL)

    def test_a_missing_term_makes_r4_not_evaluable_never_a_pass(self):
        """SPEC §2 R4 is latency AND spend. A net win computed from one term is
        the criterion being quietly skipped."""
        before = side("before", BEFORE_WINDOW, [task("a", block_s=2.0)])
        after = side("after", AFTER_WINDOW,
                     [task("b", block_s=1.5, hook_ms=1.0)], router=True)
        r2, _ = report.r2_latency(before, after)
        criterion, body = report.r4_overhead(before, after, r2, None)
        self.assertEqual(criterion.status, NOT_EVALUABLE)
        self.assertEqual(criterion.exit_code, EXIT_COULD_NOT_RUN)
        self.assertIn("not a net win", "\n".join(body))

    def test_an_unrecorded_overhead_is_not_zero(self):
        before = side("before", BEFORE_WINDOW, [task("a", block_s=2.0)])
        after = side("after", AFTER_WINDOW, [task("b", block_s=1.5)], router=True)
        r2, _ = report.r2_latency(before, after)
        _, body = report.r4_overhead(before, after, r2, None)
        self.assertIn("NOT zero", "\n".join(body))

    def test_the_before_sides_overhead_is_zero_by_construction_and_labelled(self):
        before = side("before", BEFORE_WINDOW, [task("a")])
        after = side("after", AFTER_WINDOW, [task("b", hook_ms=10.0)],
                     router=True)
        r2, _ = report.r2_latency(before, after)
        _, body = report.r4_overhead(before, after, r2, None)
        self.assertIn("BY CONSTRUCTION", "\n".join(body))


# ---------------------------------------------------------------------------
# R5
# ---------------------------------------------------------------------------

class TestR5Cost(unittest.TestCase):

    def test_r5_is_reported_and_never_gates(self):
        before = side("before", BEFORE_WINDOW, [task("a", cost=2.88)])
        after = side("after", AFTER_WINDOW, [task("b", cost=90.0)], router=True)
        criterion, body = report.r5_cost(before, after)[:2]
        self.assertNotEqual(criterion.status, FAIL)
        self.assertIn("NOT A GATE", "\n".join(body))

    def test_every_dollar_line_carries_the_lower_bound_tag(self):
        before = side("before", BEFORE_WINDOW, [task("a", cost=2.88)])
        after = side("after", AFTER_WINDOW, [task("b", cost=1.0)], router=True)
        _, body, _ = report.r5_cost(before, after)
        # Every line carrying an actual FIGURE. `$/assignment` in prose is a
        # denominator's name, not a number.
        for line in body:
            if re.search(r"\$\s*-?\d", line):
                self.assertIn(report.LOWER_BOUND_TAG, line, msg=line)

    def test_the_whole_corpus_figure_is_named_as_a_different_cut(self):
        before = side("before", BEFORE_WINDOW, [task("a", cost=2.88)])
        after = side("after", AFTER_WINDOW, [task("b", cost=1.0)], router=True)
        _, body, _ = report.r5_cost(before, after)
        text = "\n".join(body)
        self.assertIn("5.21", text)
        self.assertIn("must never be differenced", text)

    def test_incomparable_windows_are_reported_not_differenced(self):
        overlapping = window("after", starts="2026-09-20T00:00:00Z",
                             ends="2026-09-22T00:00:00Z")
        before = side("before", BEFORE_WINDOW, [task("a", cost=2.88)])
        after = side("after", overlapping, [task("b", cost=1.0)], router=True)
        criterion, body, delta = report.r5_cost(before, after)
        self.assertEqual(criterion.status, NOT_EVALUABLE)
        self.assertIsNone(delta)
        self.assertIn("NOT DIFFERENCED", "\n".join(body))


# ---------------------------------------------------------------------------
# The orphan side, the two denominators, and mixed timestamp spellings
# ---------------------------------------------------------------------------

class TestOrphanSpendAndDenominators(unittest.TestCase):

    def test_orphan_spend_is_in_the_r5_numerator_not_only_a_footnote(self):
        """The anchor's delegated_cost_usd is EVERY subagent transcript. An
        after side counting only attributed spend understates the treatment
        arm -- bias in the direction that flatters the layer."""
        s = side("after", AFTER_WINDOW, [task("a", cost=1.0)], router=True)
        s.unassigned_cost_usd = 3.93
        self.assertAlmostEqual(s.attributed_cost_usd, 1.0)
        self.assertAlmostEqual(s.total_delegated_cost_usd, 4.93)
        self.assertAlmostEqual(s.cost_per_delegated_task().value, 4.93)

    def test_the_figure_names_its_split_numerator(self):
        s = side("after", AFTER_WINDOW, [task("a", cost=1.0)], router=True)
        s.unassigned_cost_usd = 3.93
        self.assertIn("unattributed", s.cost_per_delegated_task().note)

    def test_both_denominators_are_printed(self):
        before = side("before", BEFORE_WINDOW, [task("a", cost=2.0)])
        after = side("after", AFTER_WINDOW,
                     [task("a", cost=4.0),
                      task("b", cost=0.0, outcome_found=False)], router=True)
        # $/assignment = 4/2 = 2.00; $/outcome = 4/1 = 4.00.
        self.assertAlmostEqual(after.cost_per_delegated_task().value, 2.0)
        self.assertAlmostEqual(after.cost_per_outcome().value, 4.0)
        _, body, _ = report.r5_cost(before, after)
        text = "\n".join(body)
        self.assertIn("realised cost / outcome", text)
        self.assertIn("comes to look cheaper", text)

    def test_the_aggregate_before_side_says_its_denominator_differs(self):
        s = report.side_from_corrected_baseline(
            CORRECTED, scope="interactive_sessions_only", project=PROJECT)
        self.assertIn("denominators differ", s.cost_per_delegated_task().note)


class TestTimestampSpellings(unittest.TestCase):

    def test_the_cuts_Z_and_a_transcripts_offset_compare_as_instants(self):
        """`Z` (0x5A) sorts after `.` and `+`. A lexical comparison gets an
        after side that starts when the before side ends the wrong way round."""
        before = window("before", starts="2026-09-19T00:00:00+00:00",
                        ends="2026-09-20T11:11:49Z")
        after = window("after", starts="2026-09-20T11:11:49.000000+00:00",
                       ends="2026-09-21T00:00:00+00:00")
        # Lexically "2026-09-20T11:11:49Z" > "2026-09-20T11:11:49.000000+00:00",
        # so a string comparison would call these overlapping. They touch.
        self.assertGreater(before.ends_at, after.starts_at)
        report.comparable(before, after)

    def test_an_unparseable_bound_is_never_provably_disjoint(self):
        bad = window("after", starts="not-a-time", ends="also-not")
        with self.assertRaises(report.WindowsDiffer):
            report.comparable(BEFORE_WINDOW, bad)

    def test_parse_stamp_normalises_both_spellings_to_one_instant(self):
        a = report.parse_stamp("2026-09-20T11:11:49Z")
        b = report.parse_stamp("2026-09-20T11:11:49.000000+00:00")
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# The three empty after states
# ---------------------------------------------------------------------------

class TestThreeEmptyStates(unittest.TestCase):

    ROW = {"schema": assignment_ledger.LEDGER_SCHEMA_V2, "tool_use_id": "tu-1",
           "project": PROJECT, "tier": "haiku45", "decision": "routed",
           "timestamp": "2026-09-22T10:00:00Z", "hook_ms": 9.0}

    def test_an_empty_ledger_is_no_after_corpus(self):
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "assignments"
            ledger.mkdir()
            code, out, _ = run_cli("--before", str(CORRECTED),
                                   "--after-ledger", str(ledger),
                                   "--project", PROJECT)
        self.assertEqual(code, EXIT_COULD_NOT_RUN)
        self.assertIn(report.NO_AFTER_CORPUS, out)

    def test_rows_but_no_transcripts_is_invoked_wrong_not_no_corpus(self):
        """The corpus EXISTS; the invocation did not ask for it. Saying 'no
        after corpus exists' here would assert a fact it never checked."""
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "assignments"
            write_ledger(ledger, [self.ROW])
            code, out, err = run_cli("--before", str(CORRECTED),
                                     "--after-ledger", str(ledger),
                                     "--project", PROJECT)
        self.assertEqual(code, EXIT_INVOKED_WRONG)
        self.assertIn("--after-session", err)
        self.assertNotIn(report.NO_AFTER_CORPUS, out)

    def test_a_row_that_joins_to_nothing_is_attrition_not_an_absent_corpus(self):
        """The join is intention-to-treat, so there is no fourth state: an
        unjoined assignment is a row with ATTRITION on it, and R1 says so."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / "assignments"
            write_ledger(ledger, [dict(self.ROW, tool_use_id="nothing-joins")])
            empty = root / "empty.jsonl"
            empty.write_text("", encoding="utf-8")
            code, out, _ = run_cli("--before", str(CORRECTED),
                                   "--after-ledger", str(ledger),
                                   "--after-session", str(empty),
                                   "--project", PROJECT)
        self.assertNotIn(report.NO_AFTER_CORPUS, out)
        self.assertIn("attrition=1", out)
        # No gate verdict was supplied, so the whole report still exits 1.
        self.assertEqual(code, EXIT_COULD_NOT_RUN)

    def test_the_no_after_message_reports_what_it_actually_read(self):
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "assignments"
            ledger.mkdir()
            _, out, _ = run_cli("--before", str(CORRECTED),
                                "--after-ledger", str(ledger),
                                "--project", PROJECT)
        self.assertIn("What was checked:", out)
        self.assertIn(str(ledger), out)


# ---------------------------------------------------------------------------
# --before-session may not cross the cut
# ---------------------------------------------------------------------------

class TestBeforeSessionRespectsTheCut(unittest.TestCase):

    def test_a_before_session_running_past_the_cut_is_refused(self):
        """Post-cut work wearing a pre-rule label is the JEV-24a trap one step
        out: still disjoint from a later after, so comparable() waves it
        through, and the 'before' silently contains the treatment."""
        with TemporaryDirectory() as tmp:
            parent = build_corpus(Path(tmp))   # runs on 2026-09-22
            code, _, err = run_cli("--before", str(CORRECTED),
                                   "--before-session", str(parent),
                                   "--project", PROJECT)
        self.assertEqual(code, EXIT_INVOKED_WRONG)
        self.assertIn("past the", err)
        self.assertIn("2026-09-20T11:11:49Z", err)


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------

class TestPower(unittest.TestCase):

    def test_the_power_statement_names_both_n_and_forbids_inference(self):
        before = side("before", BEFORE_WINDOW,
                      [task(f"b{i}", attempts=1 + (i == 0)) for i in range(7)])
        after = side("after", AFTER_WINDOW,
                     [task(f"a{i}") for i in range(5)], router=True)
        text = report.power_statement(before, after)
        self.assertIn("n = 7", text)
        self.assertIn("5 after", text)
        self.assertIn("DO NOT READ SIGNIFICANCE", text)

    def test_at_tiny_n_the_detectable_effect_is_enormous_or_none(self):
        mde = report.mde_proportion(0.14, 7, 5)
        self.assertTrue(mde is None or mde > 0.5,
                        f"n=7 vs n=5 should detect almost nothing, got {mde}")

    def test_a_larger_n_detects_a_smaller_effect(self):
        small = report.mde_proportion(0.20, 50, 50)
        large = report.mde_proportion(0.20, 2000, 2000)
        self.assertIsNotNone(small)
        self.assertIsNotNone(large)
        self.assertLess(large, small)

    def test_a_zero_variance_before_side_is_degenerate_not_infinitely_sensitive(self):
        """0.0s would read as "any difference is detectable". It is not."""
        self.assertIsNone(report.mde_continuous([5.0, 5.0, 5.0], 10))

    def test_continuous_mde_shrinks_with_n(self):
        values = [float(v) for v in range(20)]
        self.assertGreater(report.mde_continuous(values, 5),
                           report.mde_continuous(values, 500))


# ---------------------------------------------------------------------------
# The no-after path: the repeated lesson
# ---------------------------------------------------------------------------

class TestNoAfterCorpus(unittest.TestCase):

    def test_the_cli_says_no_after_corpus_exists_and_exits_1(self):
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "assignments"
            ledger.mkdir()
            code, out, _ = run_cli(
                "--before", str(CORRECTED),
                "--after-ledger", str(ledger),
                "--project", PROJECT)
        self.assertEqual(code, EXIT_COULD_NOT_RUN)
        self.assertIn(report.NO_AFTER_CORPUS, out)

    def test_it_never_prints_a_zero_that_looks_like_an_answer(self):
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "assignments"
            ledger.mkdir()
            _, out, _ = run_cli("--before", str(CORRECTED),
                                "--after-ledger", str(ledger),
                                "--project", PROJECT)
        for forbidden in ("$0.00", "$0.0000", "0 tasks", "0.00%"):
            self.assertNotIn(forbidden, out, msg=f"printed {forbidden!r}")
        self.assertIn("NOT a report that the after side", out)

    def test_it_still_shows_the_before_anchor(self):
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "assignments"
            ledger.mkdir()
            _, out, _ = run_cli("--before", str(CORRECTED),
                                "--after-ledger", str(ledger),
                                "--project", PROJECT)
        self.assertIn("2.8798", out)
        self.assertIn(report.LOWER_BOUND_TAG, out)

    def test_the_live_empty_ledger_in_this_repo_produces_exactly_this(self):
        """`data/agent_route/assignments` is empty and `agent_route` is off.
        This is the output on the day the report is first run for real."""
        live = ROOT / "data" / "agent_route" / "assignments"
        if not live.is_dir():
            self.skipTest("no live assignments directory in this checkout")
        self.assertEqual(assignment_ledger.read_ledger(live), [])
        code, out, _ = run_cli("--before", str(CORRECTED),
                               "--after-ledger", str(live),
                               "--project", str(ROOT))
        self.assertEqual(code, EXIT_COULD_NOT_RUN)
        self.assertIn(report.NO_AFTER_CORPUS, out)

    def test_the_epilogue_refuses_to_be_read_as_a_pass(self):
        self.assertIn("DO NOT READ IT AS A PASS",
                      report.epilogue(EXIT_COULD_NOT_RUN))


# ---------------------------------------------------------------------------
# Project partitioning (JEV-57)
# ---------------------------------------------------------------------------

def write_ledger(directory: Path, rows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "rows.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class TestProjectPartitioning(unittest.TestCase):

    ROWS = [
        {"schema": assignment_ledger.LEDGER_SCHEMA_V2, "tool_use_id": "t1",
         "project": "/repo/a", "tier": "haiku45", "decision": "routed",
         "timestamp": "2026-09-22T00:00:00Z", "hook_ms": 12.0},
        {"schema": assignment_ledger.LEDGER_SCHEMA_V2, "tool_use_id": "t2",
         "project": "/repo/b", "tier": "haiku45", "decision": "routed",
         "timestamp": "2026-09-22T00:01:00Z", "hook_ms": 14.0},
    ]

    def test_two_projects_without_a_flag_refuse_to_pool(self):
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "assignments"
            write_ledger(ledger, self.ROWS)
            with self.assertRaises(assignment_ledger.ProjectsWouldBePooled):
                report._ledger_rows_for(ledger, project=None, pool_projects=False)

    def test_the_cli_turns_that_into_exit_2_with_the_fix_in_the_message(self):
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "assignments"
            write_ledger(ledger, self.ROWS)
            code, _, err = run_cli("--before", str(CORRECTED),
                                   "--after-ledger", str(ledger))
        self.assertEqual(code, EXIT_INVOKED_WRONG)
        self.assertIn("pool_projects", err)

    def test_naming_one_project_selects_only_its_rows(self):
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "assignments"
            write_ledger(ledger, self.ROWS)
            rows = report._ledger_rows_for(ledger, project="/repo/a",
                                           pool_projects=False)
        self.assertEqual([r["tool_use_id"] for r in rows], ["t1"])

    def test_pooling_is_possible_but_must_be_asked_for(self):
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "assignments"
            write_ledger(ledger, self.ROWS)
            rows = report._ledger_rows_for(ledger, project=None,
                                           pool_projects=True)
        self.assertEqual(len(rows), 2)

    def test_project_and_pool_projects_are_exclusive(self):
        code, _, err = run_cli("--before", str(CORRECTED),
                               "--project", "/repo/a", "--pool-projects")
        self.assertEqual(code, EXIT_INVOKED_WRONG)
        self.assertIn("exclusive", err)

    def test_a_v1_row_lands_in_the_legacy_partition_not_a_repo(self):
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "assignments"
            write_ledger(ledger, [
                {"schema": assignment_ledger.LEDGER_SCHEMA_V1,
                 "tool_use_id": "t0", "timestamp": "2026-09-22T00:00:00Z"}])
            rows = report._ledger_rows_for(ledger, project="/repo/a",
                                           pool_projects=False)
        self.assertEqual(rows, [])


# ---------------------------------------------------------------------------
# The transcript path, end to end, on a hand-built corpus
# ---------------------------------------------------------------------------

def build_corpus(root: Path, *, tool_use_id="tu-1", cost_tokens=100_000,
                 stop_reason="end_turn") -> Path:
    """A minimal but REAL parent transcript plus one subagent transcript.

    Costed by `session_metrics.analyse` through `subagent_outcomes`, so this
    exercises the reuse the module is built on rather than a stub.
    """
    parent = root / "session-1.jsonl"
    parent.write_text("\n".join(json.dumps(line) for line in [
        {"type": "assistant", "timestamp": "2026-09-22T10:00:00.000Z",
         "message": {"role": "assistant", "id": "m0", "model": "claude-opus-5",
                     "stop_reason": "tool_use",
                     "content": [{"type": "tool_use", "id": tool_use_id,
                                  "name": "Agent",
                                  "input": {"subagent_type": "general-purpose"}}]}},
        {"type": "user", "timestamp": "2026-09-22T10:00:01.500Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": tool_use_id,
              "content": "Async agent launched successfully. agentId: a1"}]}},
    ]) + "\n", encoding="utf-8")

    subagents = root / "session-1" / "subagents"
    subagents.mkdir(parents=True)
    (subagents / "agent-a1.jsonl").write_text("\n".join(json.dumps(line) for line in [
        {"type": "assistant", "timestamp": "2026-09-22T10:00:02.000Z",
         "requestId": "req-1",
         "message": {"role": "assistant", "id": "m1", "model": "claude-opus-5",
                     "stop_reason": "tool_use", "content": [],
                     "usage": {"input_tokens": cost_tokens, "output_tokens": 10}}},
        {"type": "assistant", "timestamp": "2026-09-22T10:13:00.000Z",
         "requestId": "req-2",
         "message": {"role": "assistant", "id": "m2", "model": "claude-opus-5",
                     "stop_reason": stop_reason, "content": [],
                     "usage": {"input_tokens": cost_tokens, "output_tokens": 10}}},
    ]) + "\n", encoding="utf-8")
    (subagents / "agent-a1.meta.json").write_text(json.dumps({
        "toolUseId": tool_use_id, "agentType": "general-purpose",
        "requestShape": "background", "spawnDepth": 1}), encoding="utf-8")
    return parent


class TestTranscriptPath(unittest.TestCase):

    def test_a_live_side_carries_both_durations_and_a_real_cost(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = build_corpus(root)
            ledger = root / "assignments"
            write_ledger(ledger, [{
                "schema": assignment_ledger.LEDGER_SCHEMA_V2,
                "tool_use_id": "tu-1", "project": PROJECT, "tier": "haiku45",
                "decision": "routed", "timestamp": "2026-09-22T10:00:00Z",
                "hook_ms": 21.0}])
            s = report.side_from_sessions(
                [parent], label="after", scope="interactive_sessions_only",
                pricing_version="pricing-2026-09-20b", project=PROJECT,
                ledger_dir=ledger)
        self.assertEqual(s.n_tasks, 1)
        row = s.tasks[0]
        self.assertAlmostEqual(row.blocking_duration_s, 1.5, places=3)
        self.assertGreater(row.task_duration_s, 700)
        self.assertGreater(row.cost_usd, 0.0)
        self.assertEqual(row.hook_ms, 21.0)
        self.assertEqual(row.tier, "haiku45")
        self.assertTrue(row.completed)

    def test_a_truncated_subagent_transcript_is_a_task_level_failure(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = build_corpus(root, stop_reason=None)
            s = report.side_from_sessions(
                [parent], label="after", scope="interactive_sessions_only",
                pricing_version="pricing-2026-09-20b", project=PROJECT)
        self.assertFalse(s.tasks[0].completed)
        self.assertEqual(s.rework.failures, 1)

    def test_the_window_bounds_come_from_the_data(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = build_corpus(root)
            s = report.side_from_sessions(
                [parent], label="after", scope="interactive_sessions_only",
                pricing_version="pricing-2026-09-20b", project=PROJECT)
        self.assertIsNotNone(s.window.starts_at)
        self.assertIsNotNone(s.window.ends_at)

    def test_costing_goes_through_session_metrics_not_a_local_sum(self):
        """The module must not own a costing rule. If it did, this figure
        would not match `session_metrics.analyse` to the cent."""
        import session_metrics as sm
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = build_corpus(root)
            s = report.side_from_sessions(
                [parent], label="after", scope="interactive_sessions_only",
                pricing_version="pricing-2026-09-20b", project=PROJECT)
            direct = sm.analyse(root / "session-1" / "subagents" / "agent-a1.jsonl")
        self.assertAlmostEqual(s.tasks[0].cost_usd, direct.computed_cost_usd,
                               places=10)


# ---------------------------------------------------------------------------
# Side snapshots
# ---------------------------------------------------------------------------

class TestSideSnapshot(unittest.TestCase):

    def test_roundtrip(self):
        original = side("after", AFTER_WINDOW,
                        [task("a", attempts=2, hook_ms=7.0)], router=True)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "side.json"
            path.write_text(json.dumps(report.side_to_json(original)),
                            encoding="utf-8")
            restored = report.side_from_json(path)
        self.assertEqual(restored.window, original.window)
        self.assertEqual(restored.tasks[0].attempts, 2)
        self.assertTrue(restored.router_present)

    def test_a_foreign_schema_is_invoked_wrong(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "side.json"
            path.write_text(json.dumps({"schema": "something-else"}),
                            encoding="utf-8")
            with self.assertRaises(report.InvokedWrong):
                report.side_from_json(path)


# ---------------------------------------------------------------------------
# The whole report, and its exit taxonomy
# ---------------------------------------------------------------------------

def paired_sides(tmp: Path, *, after_tasks=None, gate=EXIT_CLEAN):
    before = side("before", BEFORE_WINDOW,
                  [task(f"b{i}", cost=2.88, block_s=2.0, task_s=800.0)
                   for i in range(7)])
    after = side("after", AFTER_WINDOW,
                 after_tasks or [task(f"a{i}", cost=1.2, block_s=1.9,
                                      task_s=700.0, hook_ms=15.0)
                                 for i in range(5)],
                 router=True)
    bp, ap = tmp / "before.json", tmp / "after.json"
    bp.write_text(json.dumps(report.side_to_json(before)), encoding="utf-8")
    ap.write_text(json.dumps(report.side_to_json(after)), encoding="utf-8")
    return bp, ap


class TestWholeReport(unittest.TestCase):

    def test_a_clean_run_exits_0_and_reports_all_five_criteria(self):
        with TemporaryDirectory() as tmp:
            bp, ap = paired_sides(Path(tmp))
            code, out, _ = run_cli("--before-json", str(bp),
                                   "--after-json", str(ap),
                                   "--gate-exit", "0")
        self.assertEqual(code, EXIT_CLEAN, msg=out)
        for name in ("R1", "R2", "R3", "R4", "R5"):
            self.assertIn(name, out)

    def test_the_criteria_are_printed_in_the_specs_corrected_order(self):
        with TemporaryDirectory() as tmp:
            bp, ap = paired_sides(Path(tmp))
            _, out, _ = run_cli("--before-json", str(bp), "--after-json", str(ap),
                                "--gate-exit", "0")
        verdict = out.split("=== VERDICT ===")[1]
        positions = [verdict.index(f"R{i}") for i in range(1, 6)]
        self.assertEqual(positions, sorted(positions))

    def test_rework_is_the_primary_criterion_and_says_so(self):
        with TemporaryDirectory() as tmp:
            bp, ap = paired_sides(Path(tmp))
            _, out, _ = run_cli("--before-json", str(bp), "--after-json", str(ap),
                                "--gate-exit", "0")
        self.assertIn("PRIMARY", out)
        self.assertIn("RESTART", out)

    def test_a_missing_gate_verdict_downgrades_the_whole_report_to_1(self):
        with TemporaryDirectory() as tmp:
            bp, ap = paired_sides(Path(tmp))
            code, out, _ = run_cli("--before-json", str(bp), "--after-json", str(ap))
        self.assertEqual(code, EXIT_COULD_NOT_RUN, msg=out)

    def test_a_rework_increase_exits_3(self):
        with TemporaryDirectory() as tmp:
            bp, ap = paired_sides(Path(tmp), after_tasks=[
                task("a0", attempts=3, cost=1.2, block_s=1.0, hook_ms=1.0),
                task("a1", cost=1.2, block_s=1.0, hook_ms=1.0)])
            code, out, _ = run_cli("--before-json", str(bp), "--after-json", str(ap),
                                   "--gate-exit", "0")
        self.assertEqual(code, EXIT_REGRESSION, msg=out)

    def test_a_failed_gate_exits_3_even_when_everything_else_is_green(self):
        with TemporaryDirectory() as tmp:
            bp, ap = paired_sides(Path(tmp))
            code, _, _ = run_cli("--before-json", str(bp), "--after-json", str(ap),
                                 "--gate-exit", "3")
        self.assertEqual(code, EXIT_REGRESSION)

    def test_invoked_wrong_beats_a_regression(self):
        """Precedence is accuracy_gate's: not knowing what we measured is the
        worst news available."""
        code, _, _ = run_cli("--before", "/nonexistent/anchor.json",
                             "--project", "/a", "--pool-projects")
        self.assertEqual(code, EXIT_INVOKED_WRONG)

    def test_the_power_statement_is_printed_not_left_to_the_reader(self):
        with TemporaryDirectory() as tmp:
            bp, ap = paired_sides(Path(tmp))
            _, out, _ = run_cli("--before-json", str(bp), "--after-json", str(ap),
                                "--gate-exit", "0")
        self.assertIn("POWER", out)
        self.assertIn("DO NOT READ SIGNIFICANCE", out)

    def test_the_lower_bound_note_appears_in_the_header(self):
        with TemporaryDirectory() as tmp:
            bp, ap = paired_sides(Path(tmp))
            _, out, _ = run_cli("--before-json", str(bp), "--after-json", str(ap),
                                "--gate-exit", "0")
        self.assertIn("LOWER BOUND", out)
        self.assertIn("27.6", out)

    def test_json_output_carries_the_exit_code_and_the_lower_bound(self):
        with TemporaryDirectory() as tmp:
            bp, ap = paired_sides(Path(tmp))
            _, out, _ = run_cli("--before-json", str(bp), "--after-json", str(ap),
                                "--gate-exit", "0", "--json")
        blob = out[out.index("{"):out.rindex("}") + 1]
        record = json.loads(blob)
        self.assertEqual(record["exit_code"], EXIT_CLEAN)
        self.assertIn("LOWER BOUND", record["lower_bound"])
        self.assertEqual(len(record["criteria"]), 5)

    def test_no_before_side_is_invoked_wrong(self):
        code, _, err = run_cli("--gate-exit", "0")
        self.assertEqual(code, EXIT_INVOKED_WRONG)
        self.assertIn("before side is required", err)

    def test_a_gate_verdict_file_without_an_exit_code_is_refused(self):
        with TemporaryDirectory() as tmp:
            bp, ap = paired_sides(Path(tmp))
            verdict = Path(tmp) / "verdict.json"
            verdict.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
            code, _, err = run_cli("--before-json", str(bp),
                                   "--after-json", str(ap),
                                   "--gate-verdict", str(verdict))
        self.assertEqual(code, EXIT_INVOKED_WRONG)
        self.assertIn("cannot be read as a pass", err)


# ---------------------------------------------------------------------------
# Source-level: this module owns no costing or quantile rule
# ---------------------------------------------------------------------------

class TestNoReimplementation(unittest.TestCase):

    SOURCE = (ROOT / "src" / "report.py").read_text(encoding="utf-8")

    def test_it_reuses_the_named_modules(self):
        for module in ("session_metrics", "subagent_outcomes",
                       "assignment_ledger", "stats", "accuracy_gate"):
            self.assertIn(module, self.SOURCE)

    def test_it_does_not_reimplement_pricing(self):
        for forbidden in ("cache_write_multiplier", "pricing.json",
                          "input_tokens *", "def call_cost"):
            self.assertNotIn(forbidden, self.SOURCE, msg=forbidden)

    def test_it_does_not_reimplement_quantiles(self):
        self.assertNotIn("def quantiles", self.SOURCE)
        self.assertIn("stats.quantiles", self.SOURCE)

    def test_the_exit_taxonomy_is_imported_not_redefined(self):
        self.assertNotIn("EXIT_COULD_NOT_RUN = ", self.SOURCE)
        self.assertIn("from accuracy_gate import", self.SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
