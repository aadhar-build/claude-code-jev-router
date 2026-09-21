#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""W3 -- the accuracy gate. JEV-29 and JEV-36, repurposed. SPEC §6.

Everything here runs against fixtures or tempdirs. No network, no API calls, no
writes outside a `TemporaryDirectory`, and nothing touches the live collection
window.

The tests are grouped by the requirement they defend, and each group names it,
because every one of these exists because of a specific prior finding rather
than a general wish for coverage:

  1. per-task pass/fail, never an aggregate      (TwinRouterBench)
  2. score the final diff, never per-edit-call   (73% vs 26%; Bash-written edits)
  3. blind by construction, then asserted        (JEV-29)
  4. exit codes 0/1/2/3, and 1 never reads as 0  (SPEC §6, the whole point)
  5. the gate prints its own limitation          (SPEC §2)
  6. outcomes cannot come from PostToolUse       (JEV-36, verified on real data)
  7. both durations, separately                  (JEV-36 A3.5, "felt latency")
  8. attrition by tier                           (JEV-36, last bullet)
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pyversion  # noqa: E402

pyversion.require()

import accuracy_gate as gate  # noqa: E402
import fixture_executor as fx  # noqa: E402
import subagent_outcomes as so  # noqa: E402

SUITE = ROOT / "tests" / "fixtures" / "accuracy" / "suite-v1"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def run_row(decision_id: str, question: str, probability: float, *,
            arm: str = "jev", ok: bool = True,
            question_set_id: str = "pre_bash/v1#a",
            state_sha256: str = "aaaa", attempt: int = 0) -> dict:
    return {
        "decision_id": decision_id,
        "arm": arm,
        "ok": ok,
        "attempt": attempt,
        "question_set_id": question_set_id,
        "state_sha256": state_sha256,
        "answers": {question: {"type": "boolean", "probability": probability}},
    }


TAUS = {"destructive": 0.5}


# ---------------------------------------------------------------------------
# Class 1
# ---------------------------------------------------------------------------

class TestClass1(unittest.TestCase):

    def test_identical_replay_produces_no_band_flip_and_perfect_kappa(self):
        rows = [run_row(f"d{i}", "destructive", 0.1 + i * 0.05) for i in range(20)]
        result = gate.class1_compare(rows, list(rows), TAUS, arm="jev")
        self.assertEqual(result.band_flips, 0)
        self.assertEqual(result.n_paired, 20)
        self.assertAlmostEqual(result.kappa, 1.0)

    def test_the_join_is_on_decision_id_not_state_sha256(self):
        """State trimming changes the state hash BY DESIGN.

        A hash join would find zero pairs and then report a clean run over an
        empty set -- the exact shape of a decorative gate.
        """
        base = [run_row(f"d{i}", "destructive", 0.2, state_sha256="before") for i in range(10)]
        treat = [run_row(f"d{i}", "destructive", 0.2, state_sha256="after-trimming")
                 for i in range(10)]
        result = gate.class1_compare(base, treat, TAUS, arm="jev")
        self.assertEqual(result.n_paired, 10)

    def test_band_flip_above_five_percent_blocks_with_exit_three(self):
        base = [run_row(f"d{i}", "destructive", 0.2) for i in range(100)]
        treat = [run_row(f"d{i}", "destructive", 0.9 if i < 6 else 0.2) for i in range(100)]
        result = gate.class1_compare(base, treat, TAUS, arm="jev")
        self.assertEqual(result.band_flips, 6)
        self.assertEqual(result.exit_code, gate.EXIT_REGRESSION)
        flip = next(c for c in result.criteria if c.name.startswith("band-flip"))
        self.assertEqual(flip.status, gate.FAIL)

    def test_band_flip_between_two_and_five_percent_is_report_only(self):
        base = [run_row(f"d{i}", "destructive", 0.2) for i in range(100)]
        treat = [run_row(f"d{i}", "destructive", 0.9 if i < 3 else 0.2) for i in range(100)]
        result = gate.class1_compare(base, treat, TAUS, arm="jev")
        flip = next(c for c in result.criteria if c.name.startswith("band-flip"))
        self.assertEqual(flip.status, gate.WARN)
        # A warn is not a block; only the missing AUC keeps this off exit 0.
        self.assertEqual(flip.exit_code, gate.EXIT_CLEAN)

    def test_kappa_below_point_eight_blocks(self):
        base = [run_row(f"d{i}", "destructive", 0.9 if i % 2 else 0.1) for i in range(100)]
        treat = [run_row(f"d{i}", "destructive", 0.9 if i % 3 else 0.1) for i in range(100)]
        result = gate.class1_compare(base, treat, TAUS, arm="jev")
        kappa = next(c for c in result.criteria if c.name.startswith("kappa"))
        self.assertLess(result.kappa, gate.KAPPA_BLOCK)
        self.assertEqual(kappa.status, gate.FAIL)
        self.assertEqual(result.exit_code, gate.EXIT_REGRESSION)

    def test_auc_is_not_evaluable_without_labels_and_that_is_exit_one(self):
        rows = [run_row(f"d{i}", "destructive", 0.1) for i in range(20)]
        result = gate.class1_compare(rows, list(rows), TAUS, arm="jev")
        auc = next(c for c in result.criteria if c.name.startswith("AUC"))
        self.assertEqual(auc.status, gate.NOT_EVALUABLE)
        self.assertEqual(result.exit_code, gate.EXIT_COULD_NOT_RUN)
        self.assertNotEqual(result.exit_code, gate.EXIT_CLEAN)

    def test_all_three_criteria_evaluated_and_clean_is_exit_zero(self):
        base, treat, labels = [], [], {}
        for i in range(40):
            positive = i % 2 == 0
            p = 0.9 if positive else 0.1
            base.append(run_row(f"d{i}", "destructive", p))
            treat.append(run_row(f"d{i}", "destructive", p))
            labels[(f"d{i}", "destructive")] = positive
        result = gate.class1_compare(base, treat, TAUS, arm="jev", labels=labels)
        self.assertEqual([c.status for c in result.criteria],
                         [gate.PASS, gate.PASS, gate.PASS])
        self.assertEqual(result.exit_code, gate.EXIT_CLEAN)
        self.assertEqual(result.auc_baseline["destructive"], 1.0)

    def test_auc_drop_beyond_the_threshold_blocks(self):
        base, treat, labels = [], [], {}
        for i in range(40):
            positive = i % 2 == 0
            base.append(run_row(f"d{i}", "destructive", 0.9 if positive else 0.1))
            # Ranking destroyed, bands untouched: only AUC can see this.
            treat.append(run_row(f"d{i}", "destructive", 0.9 if i % 4 < 2 else 0.1))
            labels[(f"d{i}", "destructive")] = positive
        result = gate.class1_compare(base, treat, TAUS, arm="jev", labels=labels)
        auc = next(c for c in result.criteria if c.name.startswith("AUC"))
        self.assertEqual(auc.status, gate.FAIL)
        self.assertEqual(result.exit_code, gate.EXIT_REGRESSION)

    def test_a_regression_outranks_a_criterion_that_could_not_be_evaluated(self):
        """3 beats 1. Finding a regression IS running."""
        base = [run_row(f"d{i}", "destructive", 0.2) for i in range(100)]
        treat = [run_row(f"d{i}", "destructive", 0.9 if i < 20 else 0.2) for i in range(100)]
        result = gate.class1_compare(base, treat, TAUS, arm="jev")   # no labels
        self.assertEqual(result.exit_code, gate.EXIT_REGRESSION)

    def test_question_set_mismatch_is_invoked_wrong_not_a_regression(self):
        base = [run_row("d1", "destructive", 0.2, question_set_id="pre_bash/v1#a")]
        treat = [run_row("d1", "destructive", 0.2, question_set_id="pre_bash/v2#a")]
        with self.assertRaises(gate.InvokedWrong):
            gate.class1_compare(base, treat, TAUS, arm="jev")

    def test_a_question_with_no_tau_is_invoked_wrong(self):
        """There is no frozen tau file in this repo. tau is an input, not a default."""
        rows = [run_row("d1", "needs_review", 0.2)]
        with self.assertRaises(gate.InvokedWrong):
            gate.class1_compare(rows, list(rows), TAUS, arm="jev")

    def test_nothing_paired_is_could_not_run_not_a_clean_pass(self):
        base = [run_row("d1", "destructive", 0.2)]
        treat = [run_row("d2", "destructive", 0.2)]
        with self.assertRaises(gate.CouldNotRun):
            gate.class1_compare(base, treat, TAUS, arm="jev")

    def test_failed_rows_are_attrition_and_never_silently_shrink_the_denominator(self):
        base = [run_row(f"d{i}", "destructive", 0.2) for i in range(10)]
        treat = [run_row(f"d{i}", "destructive", 0.2, ok=(i > 2)) for i in range(10)]
        result = gate.class1_compare(base, treat, TAUS, arm="jev")
        self.assertEqual(result.n_paired, 7)
        self.assertEqual(result.attrition["treatment_rows_not_ok"], 3)
        self.assertEqual(result.attrition["in_baseline_missing_from_treatment"], 3)
        self.assertIn("in_baseline_missing_from_treatment=3", gate.render_class1(result))

    def test_later_attempt_wins_over_an_earlier_one(self):
        rows = [run_row("d1", "destructive", 0.1, attempt=0),
                run_row("d1", "destructive", 0.9, attempt=1)]
        units, _, _ = gate.index_units(rows, "jev")
        self.assertEqual(units[("d1", "destructive")], 0.9)

    def test_a_minority_question_destroyed_blocks_even_though_pooling_would_pass(self):
        """The hole that per-question scoring exists to close.

        `destructive` fires on ~5% of units; `needs_review` on ~half. Here
        `destructive` is turned into noise -- the question the gate most exists
        to protect, destroyed -- while `needs_review` is byte-identical.

        Pooled over both questions that reads as kappa ~0.9 and a band-flip
        rate under 5%: a PASS and a WARN, and the gate goes green on the one
        failure it was built to catch. Scored per question and blocked on the
        worst, it is exit 3.
        """
        taus = {"destructive": 0.5, "needs_review": 0.5}
        false_positives = {1, 3, 5, 7, 9, 11, 13, 15}   # none divisible by 20
        base, treat = [], []
        for i in range(200):
            # `destructive` fires on 10 of 200 units. Treatment misses every one
            # of them and invents eight of its own: 18 flips, 9% of THIS
            # question but only 4.5% of the pooled 400.
            base.append(run_row(f"d{i}", "destructive", 0.9 if i % 20 == 0 else 0.1))
            treat.append(run_row(f"d{i}", "destructive",
                                 0.9 if i in false_positives else 0.1))
            q = 0.9 if i % 2 else 0.1
            base.append(run_row(f"d{i}", "needs_review", q))
            treat.append(run_row(f"d{i}", "needs_review", q))

        result = gate.class1_compare(base, treat, taus, arm="jev")

        # The pooled numbers would both have passed.
        self.assertLessEqual(result.band_flip_rate, gate.BAND_FLIP_BLOCK)
        self.assertGreaterEqual(result.kappa, gate.KAPPA_BLOCK)
        # Per question, the minority question is wrecked.
        self.assertGreater(result.flip_rate_by_question["destructive"],
                           gate.BAND_FLIP_BLOCK)
        self.assertLess(result.kappa_by_question["destructive"], gate.KAPPA_BLOCK)
        self.assertAlmostEqual(result.kappa_by_question["needs_review"], 1.0)
        self.assertEqual(result.exit_code, gate.EXIT_REGRESSION)

    def test_the_per_question_breakdown_is_printed(self):
        taus = {"destructive": 0.5, "needs_review": 0.5}
        rows = [run_row("d1", "destructive", 0.9), run_row("d1", "needs_review", 0.1)]
        text = gate.render_class1(gate.class1_compare(rows, list(rows), taus, arm="jev"))
        self.assertIn("per question", text)
        self.assertIn("destructive", text)
        self.assertIn("worst", text.lower())

    def test_the_limitation_is_printed_by_the_gate_itself(self):
        rows = [run_row(f"d{i}", "destructive", 0.2) for i in range(20)]
        text = gate.render_class1(gate.class1_compare(rows, list(rows), TAUS, arm="jev"))
        self.assertIn("LIMITATION", text)
        self.assertIn("does not re-run the coding", text)


class TestKappa(unittest.TestCase):

    def test_perfect_agreement(self):
        self.assertAlmostEqual(gate.cohens_kappa_bool([True, False, True],
                                                      [True, False, True]), 1.0)

    def test_hand_computed_value(self):
        # 10 units: 4 TT, 3 FF, 2 TF, 1 FT.  po = 0.7
        # pa = 6/10, pb = 5/10 -> pe = 0.6*0.5 + 0.4*0.5 = 0.5
        # kappa = (0.7 - 0.5) / 0.5 = 0.4
        a = [True] * 6 + [False] * 4
        b = [True] * 4 + [False] * 2 + [False] * 3 + [True]
        self.assertEqual(len(a), len(b))
        self.assertAlmostEqual(gate.cohens_kappa_bool(a, b), 0.4)

    def test_constant_and_identical_raters_are_total_agreement_not_nan(self):
        k = gate.cohens_kappa_bool([False] * 10, [False] * 10)
        self.assertEqual(k, 1.0)

    def test_empty_is_nan_and_becomes_not_evaluable(self):
        self.assertTrue(gate.cohens_kappa_bool([], []) != gate.cohens_kappa_bool([], []))


# ---------------------------------------------------------------------------
# Class 2
# ---------------------------------------------------------------------------

class TestClass2(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jev-w3-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.suite_dir = self.tmp / "suite-v1"
        shutil.copytree(SUITE, self.suite_dir)

    def load(self, **kwargs):
        return fx.load_suite(self.suite_dir, **kwargs)

    def executor(self):
        return fx.RecordedExecutor(self.suite_dir)

    def run_suite(self, **kwargs):
        return fx.run_class2(self.load(), self.executor(),
                             baseline_arm="baseline", treatment_arm="treatment", **kwargs)

    # -- requirement 1: per-task, never aggregate ---------------------------

    def test_a_single_regressing_task_blocks_even_though_the_aggregate_barely_moves(self):
        """TwinRouterBench: one under-routed step fails the instance.

        Eleven of twelve tasks still pass in every seed. An aggregate pass rate
        would read 97% and ship. The block rule is per task and it fires.
        """
        target = self.suite_dir / "recorded" / "treatment" / "guard-empty-input"
        for seed in range(3):
            blob = json.loads((target / f"{seed}.json").read_text())
            blob["tests_passed"] = False
            (target / f"{seed}.json").write_text(json.dumps(blob))
        report = self.run_suite()
        self.assertEqual([o.task_id for o in report.hard_regressions], ["guard-empty-input"])
        self.assertEqual(report.exit_code, gate.EXIT_REGRESSION)
        aggregate = (sum(sum(o.treatment_pass) for o in report.outcomes)
                     / sum(len(o.treatment_pass) for o in report.outcomes))
        self.assertGreater(aggregate, 0.85)

    def test_a_flaky_treatment_task_does_not_trip_the_block_rule(self):
        """This is the gate admitting what it cannot catch.

        `clamp-probability` fails one treatment seed of three. The rule needs
        ALL treatment seeds to fail, so this passes -- and the power table
        printed beside it is the only honest account of that.
        """
        report = self.run_suite()
        flaky = next(o for o in report.outcomes if o.task_id == "clamp-probability")
        self.assertEqual(flaky.treatment_pass.count(False), 1)
        self.assertFalse(flaky.hard_regression)
        self.assertEqual(report.exit_code, gate.EXIT_CLEAN)

    def test_a_task_failing_in_both_arms_is_not_a_regression(self):
        target = self.suite_dir / "recorded"
        for arm in ("baseline", "treatment"):
            for seed in range(3):
                path = target / arm / "idempotent-append" / f"{seed}.json"
                blob = json.loads(path.read_text())
                blob["tests_passed"] = False
                path.write_text(json.dumps(blob))
        report = self.run_suite()
        self.assertEqual(report.hard_regressions, [])
        self.assertEqual(report.exit_code, gate.EXIT_CLEAN)

    # -- requirement 2: the final diff, never a tool call -------------------

    def test_scoring_reads_the_diff_and_an_edit_made_by_bash_is_not_invisible(self):
        """An "optimized" agent that moved its edits into `sed` and heredocs
        would show fewer flagged Edit/Write/MultiEdit calls and look FALSELY
        BETTER. Nothing in the scorer reads a tool call, so the two executions
        below -- identical diffs, wildly different tool usage -- score the same.
        """
        task = self.load().tasks[0]
        diff = ("diff --git a/src/client.py b/src/client.py\n"
                "--- a/src/client.py\n+++ b/src/client.py\n"
                "+def retry_with_backoff(fn):\n")
        via_edit_tool = fx.Execution(task.task_id, "baseline", 0, diff=diff, tests_passed=True)
        via_bash_heredoc = fx.Execution(task.task_id, "treatment", 0, diff=diff, tests_passed=True)
        self.assertTrue(fx.hard_check(task, via_edit_tool).passed)
        self.assertTrue(fx.hard_check(task, via_bash_heredoc).passed)
        source = (ROOT / "src" / "fixture_executor.py").read_text()
        for tool_field in ("tool_use", "tool_name", "MultiEdit"):
            self.assertNotIn(f'"{tool_field}"', source)

    def test_the_assertion_must_appear_in_ADDED_lines_not_merely_in_context(self):
        task = self.load().tasks[0]
        diff = ("diff --git a/src/client.py b/src/client.py\n"
                " def retry_with_backoff(fn):   # pre-existing context line\n"
                "+pass\n")
        self.assertFalse(fx.hard_check(task, fx.Execution(
            task.task_id, "treatment", 0, diff=diff, tests_passed=True)).passed)

    def test_passing_tests_with_no_diff_at_all_still_fails_the_acceptance_note(self):
        task = self.load().tasks[0]
        check = fx.hard_check(task, fx.Execution(task.task_id, "t", 0, diff="",
                                                 tests_passed=True))
        self.assertFalse(check.passed)
        self.assertIn("acceptance assertion absent", check.reasons[0])

    # -- requirement 3: blind by construction -------------------------------

    def test_the_payload_carries_only_task_file_and_diff(self):
        task = self.load().tasks[0]
        execution = fx.Execution(task.task_id, "treatment", 2, diff="+x", tier="cheap",
                                 cost_usd=0.01, tests_passed=True)
        payload = fx.judge_payload(task, execution)
        self.assertEqual(sorted(payload), ["diff", "file", "task"])
        blob = json.dumps(payload)
        for leak in ("treatment", "cheap", "seed", "arm", "0.01"):
            self.assertNotIn(leak, blob)

    def test_the_blind_check_is_an_assertion_and_it_fires(self):
        tokens = fx.blind_tokens("baseline", "treatment")
        self.assertEqual(fx.blind_check({"task": "t", "file": "f", "diff": "+x"}, tokens), [])
        found = fx.blind_check(
            {"task": "t", "file": "f", "diff": "+# produced by the treatment arm"}, tokens)
        self.assertIn("treatment", found)

    def test_the_blind_check_covers_tier_and_model_tokens_not_just_arm_labels(self):
        """The arm label is not the only way to learn the arm.

        A diff carrying `# routed to claude-haiku-4-5`, or a prompt naming the
        `sonnet` alias, identifies the tier and therefore the arm just as well.
        The token set is read from `config/tiers.json` rather than hardcoded,
        so a tier added there is covered without anyone remembering this file.
        """
        tokens = fx.tier_tokens()
        self.assertIn("haiku", tokens)
        self.assertIn("claude-haiku-4-5", tokens)
        found = fx.blind_check(
            {"task": "t", "file": "f", "diff": "+# routed to claude-haiku-4-5"},
            fx.blind_tokens("baseline", "treatment"))
        self.assertIn("claude-haiku-4-5", found)

    def test_the_shipped_fixture_payloads_pass_the_blind_check(self):
        suite = self.load()
        tokens = fx.blind_tokens("baseline", "treatment")
        executor = self.executor()
        for task in suite.tasks:
            for arm in ("baseline", "treatment"):
                for seed in range(suite.seeds):
                    payload = fx.judge_payload(task, executor.run(task, arm, seed))
                    self.assertEqual(fx.blind_check(payload, tokens), [],
                                     f"{task.task_id}/{arm}/{seed}")

    def test_a_broken_blind_is_exit_one_not_exit_three(self):
        """The verdict is UNUSABLE, which is a failure to measure -- not a
        measured regression. Reporting it as exit 3 would be a different lie."""
        manifest = json.loads((self.suite_dir / "suite.json").read_text())
        manifest["tasks"][0]["prompt"] += " (compare against the baseline implementation)"
        (self.suite_dir / "suite.json").write_text(json.dumps(manifest))
        report = self.run_suite(judge=fx.RecordedJudge(self.suite_dir))
        self.assertTrue(report.blind_failures)
        self.assertEqual(report.exit_code, gate.EXIT_COULD_NOT_RUN)
        self.assertIn("BLIND INTEGRITY FAILED", fx.render_class2(report))

    # -- requirement 8: attrition by tier -----------------------------------

    def test_attrition_is_reported_by_tier(self):
        report = self.run_suite()
        self.assertEqual(report.attrition_by_tier["cheap"]["did_not_complete"], 1)
        self.assertEqual(report.attrition_by_tier["frontier"]["did_not_complete"], 0)
        self.assertEqual(report.attrition_by_arm.get("treatment"), 1)
        self.assertIsNone(report.attrition_by_arm.get("baseline"))

    def test_a_cheap_tier_that_fails_costs_more_per_success_than_per_attempt(self):
        """The number that stops cheap failures from reading as a saving."""
        report = self.run_suite()
        cheap = report.cost_by_tier["cheap"]
        per_attempt = cheap["cost_usd"] / cheap["attempts"]
        per_success = cheap["cost_usd"] / cheap["successes"]
        self.assertGreater(per_success, per_attempt)
        self.assertIn("$/success", fx.render_class2(report))

    def test_class2_reports_both_durations_per_arm(self):
        report = self.run_suite()
        self.assertEqual(sorted(report.durations), ["baseline", "treatment"])
        self.assertLess(report.durations["treatment"]["task_s"],
                        report.durations["baseline"]["task_s"])
        # The treatment got faster; the human's wait did not move.
        self.assertEqual(report.durations["treatment"]["blocking_s"],
                         report.durations["baseline"]["blocking_s"])
        text = fx.render_class2(report)
        self.assertIn("blocking_s", text)
        self.assertIn("BOTH durations", text)

    def test_agent_attrition_and_harness_failure_are_not_the_same_thing(self):
        """A crashed agent is a data point; a broken harness is an absence of
        one. Collapsing them would turn a broken harness into evidence."""
        (self.suite_dir / "recorded" / "treatment" / "cache-ttl-split" / "1.json").unlink()
        with self.assertRaises(fx.HarnessFailure):
            self.run_suite()

    # -- tiers 2 and 3 ------------------------------------------------------

    def test_rule_violations_below_a_third_of_tasks_do_not_soft_block(self):
        report = self.run_suite(judge=fx.RecordedJudge(self.suite_dir))
        worse = sum(1 for o in report.outcomes
                    if o.treatment_violations > o.baseline_violations)
        self.assertEqual(worse, 2)
        self.assertFalse(report.rule_soft_block)

    def test_rule_violations_above_a_third_of_tasks_soft_block(self):
        for tid in [t["id"] for t in
                    json.loads((self.suite_dir / "suite.json").read_text())["tasks"]][:6]:
            for seed in range(3):
                path = self.suite_dir / "recorded" / "judge" / "treatment" / tid / f"{seed}.json"
                blob = json.loads(path.read_text())
                blob["rule_violations"] = ["a", "b"]
                path.write_text(json.dumps(blob))
        report = self.run_suite(judge=fx.RecordedJudge(self.suite_dir))
        self.assertTrue(report.rule_soft_block)
        # Soft-block is reported, not blocking. Only the hard rule blocks.
        self.assertEqual(report.exit_code, gate.EXIT_CLEAN)

    def test_a_dimension_move_below_the_noise_floor_is_not_a_regression(self):
        report = self.run_suite(judge=fx.RecordedJudge(self.suite_dir))
        deltas = [o.dimension_delta.get("tests", 0.0) for o in report.outcomes]
        self.assertTrue(any(d < 0 for d in deltas))
        self.assertLess(max(abs(d) for d in deltas), fx.DIMENSION_REGRESSION_DELTA)
        self.assertEqual(report.dimension_regressions, [])

    def test_a_dimension_move_at_or_beyond_the_noise_floor_is_reported(self):
        for seed in range(3):
            path = (self.suite_dir / "recorded" / "judge" / "treatment"
                    / "normalise-timestamps" / f"{seed}.json")
            blob = json.loads(path.read_text())
            blob["dimensions"]["correctness"] = 7.0   # baseline is 8.0
            path.write_text(json.dumps(blob))
        report = self.run_suite(judge=fx.RecordedJudge(self.suite_dir))
        self.assertEqual([(t, n) for t, n, _ in report.dimension_regressions],
                         [("normalise-timestamps", "correctness")])

    # -- the suite itself ---------------------------------------------------

    def test_the_suite_is_within_the_spec_range_and_declares_itself_synthetic(self):
        suite = self.load()
        self.assertTrue(12 <= len(suite.tasks) <= 20, len(suite.tasks))
        self.assertEqual(suite.seeds, 3)
        self.assertTrue(suite.synthetic)
        self.assertIn("SYNTHETIC FIXTURES", fx.render_class2(self.run_suite()))

    def test_every_task_carries_an_acceptance_note_with_a_named_assertion(self):
        for task in self.load().tasks:
            self.assertTrue(task.acceptance_note, task.task_id)
            self.assertTrue(task.must_contain, task.task_id)
            self.assertTrue(task.target_file, task.task_id)

    def test_the_smoke_subset_is_the_first_n_tasks(self):
        self.assertEqual(len(self.load(smoke=6).tasks), 6)

    # -- the live path is not armed -----------------------------------------

    def test_the_live_executor_refuses_and_prints_what_it_would_have_run(self):
        executor = fx.LiveExecutor(suite_root=self.suite_dir, workspace=self.tmp, armed=False)
        task = self.load().tasks[0]
        with self.assertRaises(gate.CouldNotRun) as ctx:
            executor.run(task, "treatment", 0)
        self.assertIn("claude", str(ctx.exception))
        self.assertIn("not armed", str(ctx.exception))

    def test_the_live_judge_refuses_without_making_a_call(self):
        with self.assertRaises(gate.CouldNotRun):
            fx.LiveJudge(armed=False).score({"task": "", "file": "", "diff": ""},
                                            task_id="t", arm="a", seed=0)


# ---------------------------------------------------------------------------
# Exit codes -- requirement 4, the single most important mechanical detail
# ---------------------------------------------------------------------------

def quiet_main(argv: list[str]) -> int:
    """Run the CLI with its report captured.

    The gate is loud by design -- it prints its own limitation and its own
    power table. That is right in a terminal and noise in a test runner, and
    `tests/run_all.sh` pipes this file through `tail -4`.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        return gate.main(argv)


class TestExitCodes(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jev-w3-exit-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_four_codes_are_distinct(self):
        codes = {gate.EXIT_CLEAN, gate.EXIT_COULD_NOT_RUN,
                 gate.EXIT_INVOKED_WRONG, gate.EXIT_REGRESSION}
        self.assertEqual(codes, {0, 1, 2, 3})

    def test_could_not_run_is_never_collapsed_into_clean(self):
        self.assertNotEqual(gate.EXIT_COULD_NOT_RUN, gate.EXIT_CLEAN)
        self.assertEqual(gate.worst(gate.EXIT_CLEAN, gate.EXIT_COULD_NOT_RUN),
                         gate.EXIT_COULD_NOT_RUN)

    def test_precedence_invoked_wrong_beats_regression_beats_could_not_run(self):
        self.assertEqual(gate.worst(gate.EXIT_REGRESSION, gate.EXIT_COULD_NOT_RUN,
                                    gate.EXIT_CLEAN), gate.EXIT_REGRESSION)
        self.assertEqual(gate.worst(gate.EXIT_INVOKED_WRONG, gate.EXIT_REGRESSION),
                         gate.EXIT_INVOKED_WRONG)

    def _class1_argv(self, **over):
        args = {"baseline": str(self.tmp / "b.jsonl"), "treatment": str(self.tmp / "t.jsonl")}
        args.update(over)
        return ["class1", "--baseline", args["baseline"], "--treatment", args["treatment"],
                "--arm", "jev", "--tau", "destructive=0.5"]

    def _write(self, name: str, rows: list[dict]) -> str:
        path = self.tmp / name
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return str(path)

    def test_a_missing_corpus_is_exit_one_and_says_so_out_loud(self):
        code = quiet_main(self._class1_argv())
        self.assertEqual(code, gate.EXIT_COULD_NOT_RUN)

    def test_an_empty_corpus_is_exit_one_not_a_clean_pass_over_nothing(self):
        (self.tmp / "b.jsonl").write_text("")
        (self.tmp / "t.jsonl").write_text("")
        self.assertEqual(quiet_main(self._class1_argv()), gate.EXIT_COULD_NOT_RUN)

    def test_a_malformed_tau_is_exit_two_and_distinct_from_exit_one(self):
        rows = [run_row("d1", "destructive", 0.2)]
        b = self._write("b.jsonl", rows)
        t = self._write("t.jsonl", rows)
        code = quiet_main(["class1", "--baseline", b, "--treatment", t, "--tau", "nonsense"])
        self.assertEqual(code, gate.EXIT_INVOKED_WRONG)
        self.assertNotEqual(code, gate.EXIT_COULD_NOT_RUN)

    def test_a_missing_tau_flag_entirely_is_exit_two(self):
        rows = [run_row("d1", "destructive", 0.2)]
        b = self._write("b.jsonl", rows)
        t = self._write("t.jsonl", rows)
        self.assertEqual(quiet_main(["class1", "--baseline", b, "--treatment", t]),
                         gate.EXIT_INVOKED_WRONG)

    def test_no_subcommand_is_exit_two(self):
        self.assertEqual(quiet_main([]), gate.EXIT_INVOKED_WRONG)

    def test_class1_over_the_real_corpus_replayed_against_itself_exits_one(self):
        """The state of this repository today, asserted rather than described.

        An identical replay produces zero band flips and kappa 1.0, and the
        gate STILL exits 1, because `data/labels/` is empty and AUC therefore
        cannot be evaluated. If this test ever starts failing with exit 0,
        someone has either added labels (good) or added a default (bad).
        """
        corpus = ROOT / "data" / "runs" / "2026-09-20.jsonl"
        if not corpus.exists():
            self.skipTest("the live corpus is not on disk in this checkout")
        code = quiet_main(["class1", "--baseline", str(corpus), "--treatment", str(corpus),
                          "--arm", "jev", "--tau", "destructive=0.36",
                          "--tau", "needs_review=0.95"])
        self.assertEqual(code, gate.EXIT_COULD_NOT_RUN)

    def test_class2_over_the_shipped_fixture_suite_exits_zero(self):
        code = quiet_main(["class2", "--suite", str(SUITE), "--judge", "recorded"])
        self.assertEqual(code, gate.EXIT_CLEAN)

    def test_class2_with_a_missing_suite_is_exit_two(self):
        self.assertEqual(quiet_main(["class2", "--suite", str(self.tmp / "nope")]),
                         gate.EXIT_INVOKED_WRONG)

    def test_class2_with_the_unarmed_live_executor_is_exit_one(self):
        code = quiet_main(["class2", "--suite", str(SUITE), "--executor", "live"])
        self.assertEqual(code, gate.EXIT_COULD_NOT_RUN)

    def test_a_broken_harness_surfaces_as_exit_one_through_the_cli(self):
        suite_copy = self.tmp / "suite-v1"
        shutil.copytree(SUITE, suite_copy)
        (suite_copy / "recorded" / "treatment" / "add-retry-backoff" / "0.json").unlink()
        self.assertEqual(quiet_main(["class2", "--suite", str(suite_copy)]),
                         gate.EXIT_COULD_NOT_RUN)

    def test_the_could_not_run_banner_refuses_to_be_read_as_a_pass(self):
        text = gate._epilogue(gate.EXIT_COULD_NOT_RUN)
        self.assertIn("DO NOT READ THIS AS A PASS", text)
        self.assertNotIn("DO NOT READ THIS AS A PASS", gate._epilogue(gate.EXIT_CLEAN))


# ---------------------------------------------------------------------------
# Power -- requirement 5
# ---------------------------------------------------------------------------

class TestPower(unittest.TestCase):

    def test_a_deterministic_regression_on_one_task_is_always_caught(self):
        self.assertEqual(gate.detection_probability(1, 3, 1.0), 1.0)

    def test_a_flaky_regression_on_one_task_is_usually_missed(self):
        # p=0.7 per seed, k=3 -> 0.343. The gate misses it about two times in three.
        self.assertAlmostEqual(gate.detection_probability(1, 3, 0.7), 0.343)

    def test_power_rises_with_the_number_of_affected_tasks(self):
        probs = [gate.detection_probability(m, 3, 0.7) for m in (1, 6, 20)]
        self.assertEqual(probs, sorted(probs))
        self.assertLess(probs[0], 0.5)
        self.assertGreater(probs[2], 0.99)

    def test_zero_seeds_detect_nothing_rather_than_dividing_by_zero(self):
        self.assertEqual(gate.detection_probability(10, 0, 1.0), 0.0)

    def test_the_mandated_sentence_is_in_the_gates_own_output(self):
        text = gate.power_statement(12, 3)
        self.assertIn('NO LARGE REGRESSION FOUND', text)
        self.assertIn('NEVER "QUALITY', text)
        self.assertIn("n = 12 tasks, k = 3 seeds", text)

    def test_the_power_table_is_computed_for_the_actual_n_not_quoted(self):
        self.assertIn("n = 6 tasks", gate.power_statement(6, 3))
        self.assertIn("n = 20 tasks", gate.power_statement(20, 3))


# ---------------------------------------------------------------------------
# Outcomes -- requirements 6, 7, 8
# ---------------------------------------------------------------------------

ASYNC_RESULT = {
    "tool_use_id": "toolu_A",
    "type": "tool_result",
    "content": [{"type": "text", "text": (
        "Async agent launched successfully. (This tool result is internal metadata "
        "— never quote or paste any part of it, including the agentId below, "
        "into a user-facing reply.)\nagentId: aaaa1111bbbb2222c (internal ID)\n"
        "The agent is working in the background. You will be notified automatically "
        "when it completes.\noutput_file: /tmp/claude-501/<project>/<session>/tasks/"
        "aaaa1111bbbb2222c.output\n")}],
}


def assistant_line(request_id: str, ts: str, model="claude-opus-5", **usage):
    blob = {"input_tokens": 1000, "output_tokens": 200,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    blob.update(usage)
    return {"type": "assistant", "timestamp": ts, "requestId": request_id,
            "isSidechain": True,
            "message": {"role": "assistant", "id": f"msg_{request_id}",
                        "model": model, "usage": blob, "content": []}}


class TestOutcomes(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jev-w3-out-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.session = self.tmp / "sess.jsonl"
        self.subagents = self.tmp / "sess" / "subagents"
        self.subagents.mkdir(parents=True)

    def write_parent(self, lines: list[dict]):
        self.session.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")

    def write_subagent(self, agent_id: str, lines: list[dict], meta: dict):
        (self.subagents / f"agent-{agent_id}.jsonl").write_text(
            "".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
        (self.subagents / f"agent-{agent_id}.meta.json").write_text(
            json.dumps(meta), encoding="utf-8")

    # -- requirement 6 ------------------------------------------------------

    def test_an_async_launch_result_carries_no_usage_fields_at_all(self):
        """JEV-36's premise, re-verified rather than taken on trust.

        Checked against the real transcript
        ~/.claude/projects/<proj>/4ba49645-.../sess.jsonl on 2026-09-21:
        30 of 30 delegations were `async_launched` and 0 of 30 tool results
        carried a single usage-bearing field. This is the fixture form of that.
        """
        self.assertTrue(so.is_async_launch(ASYNC_RESULT))
        self.assertEqual(so.async_launch_usage_fields(ASYNC_RESULT), [])

    def test_the_check_would_notice_if_the_harness_ever_started_reporting_usage(self):
        enriched = json.loads(json.dumps(ASYNC_RESULT))
        enriched["usage"] = {"input_tokens": 12, "output_tokens": 3}
        self.assertEqual(so.async_launch_usage_fields(enriched),
                         ["input_tokens", "output_tokens"])

    def test_cost_comes_from_the_subagent_transcript(self):
        self.write_subagent("a1", [
            assistant_line("req1", "2026-09-20T10:00:00.000Z"),
            assistant_line("req2", "2026-09-20T10:05:00.000Z"),
        ], {"agentType": "Explore", "toolUseId": "toolu_A", "requestShape": "background"})
        outcome = so.read_subagent(self.subagents / "agent-a1.jsonl")
        self.assertEqual(outcome.tool_use_id, "toolu_A")
        self.assertEqual(outcome.agent_type, "Explore")
        self.assertGreater(outcome.cost_usd, 0.0)
        self.assertEqual(outcome.unpriced_models, [])
        self.assertEqual(outcome.models, {"claude-opus-5": 2})

    # -- requirement 7: two durations, separately ---------------------------

    def test_task_duration_and_blocking_duration_are_recorded_separately(self):
        """A background subagent can get objectively faster while the human
        waits exactly as long. On the real transcript probed for this work the
        median task duration was 794.6s against a median blocking duration of
        1.5s -- a factor of ~530. One number would answer a different question
        from the one the SPEC asks ("no added FELT latency")."""
        self.write_parent([
            {"type": "assistant", "timestamp": "2026-09-20T10:00:00.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "toolu_A", "name": "Agent", "input": {}}]}},
            {"type": "user", "timestamp": "2026-09-20T10:00:01.400Z",
             "message": {"role": "user", "content": [ASYNC_RESULT]}},
        ])
        self.write_subagent("a1", [
            assistant_line("req1", "2026-09-20T10:00:02.000Z"),
            assistant_line("req2", "2026-09-20T10:09:02.000Z"),
        ], {"agentType": "Explore", "toolUseId": "toolu_A", "requestShape": "background"})

        blocking = so.blocking_intervals(self.session)
        self.assertAlmostEqual(blocking["toolu_A"].blocking_duration_s, 1.4, places=3)
        self.assertTrue(blocking["toolu_A"].async_launched)

        outcomes = so.read_session_subagents(self.session)
        rows = so.join_outcomes(
            [{"tool_use_id": "toolu_A", "tier": "cheap", "decision": "routed"}],
            outcomes, blocking)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0].task_duration_s, 540.0)
        self.assertAlmostEqual(rows[0].blocking_duration_s, 1.4, places=3)
        self.assertNotEqual(rows[0].task_duration_s, rows[0].blocking_duration_s)
        self.assertEqual(rows[0].request_shape, "background")
        rendered = so.render_outcomes(rows)
        self.assertIn("task_s", rendered)
        self.assertIn("block_s", rendered)

    def test_a_task_tool_name_is_matched_as_well_as_agent(self):
        self.write_parent([
            {"type": "assistant", "timestamp": "2026-09-20T10:00:00.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "toolu_B", "name": "Task", "input": {}}]}},
            {"type": "user", "timestamp": "2026-09-20T10:00:03.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "toolu_B", "content": "done"}]}},
        ])
        blocking = so.blocking_intervals(self.session)
        self.assertAlmostEqual(blocking["toolu_B"].blocking_duration_s, 3.0)
        self.assertFalse(blocking["toolu_B"].async_launched)

    # -- requirement 8: attrition by tier -----------------------------------

    def test_an_assignment_with_no_transcript_is_attrition_not_a_zero(self):
        rows = so.join_outcomes(
            [{"tool_use_id": "toolu_A", "tier": "cheap"},
             {"tool_use_id": "toolu_MISSING", "tier": "cheap"}],
            [], {})
        self.assertEqual([r.outcome_found for r in rows], [False, False])
        self.assertIn("no subagent transcript", rows[0].attrition_reason)
        self.assertIn("ATTRITION", so.render_outcomes(rows))

    def test_a_tier_that_fails_more_often_does_not_look_cheaper(self):
        """The mechanism JEV-36's last bullet exists to prevent.

        Both tiers are assigned four tasks. `cheap` completes one at $0.01;
        `frontier` completes all four at $0.04. Per ASSIGNMENT cheap looks 16x
        cheaper. Per OUTCOME it is only 4x cheaper, and its attrition rate is
        75%. Both numbers are printed side by side.
        """
        rows = []
        for i in range(4):
            rows.append(so.DelegatedTask(f"c{i}", tier="cheap",
                                         outcome_found=(i == 0),
                                         cost_usd=0.01 if i == 0 else None))
            rows.append(so.DelegatedTask(f"f{i}", tier="frontier",
                                         outcome_found=True, cost_usd=0.04))
        by_tier = so.attrition_by_tier(rows)
        self.assertAlmostEqual(by_tier["cheap"]["attrition_rate"], 0.75)
        self.assertAlmostEqual(by_tier["frontier"]["attrition_rate"], 0.0)
        self.assertAlmostEqual(by_tier["cheap"]["cost_per_assignment"], 0.0025)
        self.assertAlmostEqual(by_tier["cheap"]["cost_per_outcome"], 0.01)
        self.assertGreater(by_tier["cheap"]["cost_per_outcome"],
                           by_tier["cheap"]["cost_per_assignment"])
        text = so.render_outcomes(rows)
        self.assertIn("$/assigned", text)
        self.assertIn("$/outcome", text)

    def test_intention_to_treat_keeps_every_assigned_row(self):
        ledger = [{"tool_use_id": f"t{i}", "tier": "cheap"} for i in range(5)]
        rows = so.join_outcomes(ledger, [], {})
        self.assertEqual(len(rows), len(ledger))

    # -- the CLI: "report attrition by tier" must be a command, not a promise --

    def _populated_session(self):
        self.write_parent([
            {"type": "assistant", "timestamp": "2026-09-20T10:00:00.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "toolu_A", "name": "Agent", "input": {}}]}},
            {"type": "user", "timestamp": "2026-09-20T10:00:01.400Z",
             "message": {"role": "user", "content": [ASYNC_RESULT]}},
        ])
        self.write_subagent("a1", [
            assistant_line("req1", "2026-09-20T10:00:02.000Z"),
            assistant_line("req2", "2026-09-20T10:09:02.000Z"),
        ], {"agentType": "Explore", "toolUseId": "toolu_A", "requestShape": "background"})

    def _quiet_cli(self, argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = so.main(argv)
        return code, buffer.getvalue()

    def test_the_cli_prints_both_tables_and_exits_zero(self):
        self._populated_session()
        code, text = self._quiet_cli(["--session", str(self.session)])
        self.assertEqual(code, 0)
        self.assertIn("attrition by tier", text)
        self.assertIn("block_s", text)
        self.assertIn("$/outcome", text)

    def test_the_cli_exits_one_on_a_missing_transcript(self):
        code, _ = self._quiet_cli(["--session", str(self.tmp / "nope.jsonl")])
        self.assertEqual(code, 1)

    def test_a_transcript_with_no_delegations_is_exit_one_not_a_report_of_no_cost(self):
        self.write_parent([{"type": "user", "timestamp": "2026-09-20T10:00:00.000Z",
                            "message": {"role": "user", "content": "hello"}}])
        code, text = self._quiet_cli(["--session", str(self.session)])
        self.assertEqual(code, 1)
        self.assertIn("NOT a report that there were no costs", text)

    def test_a_bad_ledger_path_is_exit_two(self):
        self._populated_session()
        code, _ = self._quiet_cli(["--session", str(self.session),
                                   "--ledger", str(self.tmp / "not-a-dir")])
        self.assertEqual(code, 2)


# ---------------------------------------------------------------------------

def main() -> int:
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print()
    print(f"ran {result.testsRun} tests, "
          f"{len(result.failures)} failures, {len(result.errors)} errors")
    print("W3 accuracy gate: Class 1, Class 2, exit codes, power, outcomes")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
