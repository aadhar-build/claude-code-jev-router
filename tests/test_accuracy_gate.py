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
import hashlib
import inspect
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

    # ------------------------------------------------------------------
    # The two-fabricated-labels exploit, found by audit 2026-09-21.
    #
    # `evaluable` used to be a single global bool. Any ONE question with one
    # positive and one negative label flipped the whole AUC criterion from
    # NOT_EVALUABLE to PASS -- including for questions carrying no labels at
    # all. Reproduced against the real corpus: two hand-written labels on
    # `needs_review`, `destructive` entirely unlabelled, and the gate printed
    # `exit 0 -- CLEAN`. The safety-critical question was unmeasured and the
    # gate said the change was clear.
    #
    # This is the exact failure the gate exists to prevent, so it gets two
    # tests rather than one.
    # ------------------------------------------------------------------

    def test_an_unlabelled_question_makes_auc_unevaluable_not_invisible(self):
        """A question absent from the labels must not vanish from the report."""
        base, treat, labels = [], [], {}
        for i in range(40):
            positive = i % 2 == 0
            p = 0.9 if positive else 0.1
            for q in ("destructive", "needs_review"):
                base.append(run_row(f"d{i}", q, p))
                treat.append(run_row(f"d{i}", q, p))
            # ONLY needs_review is labelled. destructive is left unlabelled.
            labels[(f"d{i}", "needs_review")] = positive
        taus = dict(TAUS)
        taus["needs_review"] = 0.5
        result = gate.class1_compare(base, treat, taus, arm="jev", labels=labels)
        auc = next(c for c in result.criteria if c.name.startswith("AUC"))
        self.assertEqual(
            auc.status, gate.NOT_EVALUABLE,
            "an unlabelled question must make AUC unevaluable, not be skipped",
        )
        self.assertIn("destructive", auc.detail)
        self.assertEqual(result.exit_code, gate.EXIT_COULD_NOT_RUN)
        self.assertNotEqual(result.exit_code, gate.EXIT_CLEAN)

    def test_too_few_labels_on_a_question_is_not_a_pass(self):
        """Two labels are not a measurement, however well they behave."""
        base, treat, labels = [], [], {}
        for i in range(40):
            p = 0.9 if i % 2 == 0 else 0.1
            base.append(run_row(f"d{i}", "destructive", p))
            treat.append(run_row(f"d{i}", "destructive", p))
        labels[("d0", "destructive")] = True
        labels[("d1", "destructive")] = False
        result = gate.class1_compare(base, treat, TAUS, arm="jev", labels=labels)
        auc = next(c for c in result.criteria if c.name.startswith("AUC"))
        self.assertEqual(auc.status, gate.NOT_EVALUABLE)
        self.assertIn(str(gate.AUC_MIN_LABELLED), auc.detail)
        self.assertEqual(result.exit_code, gate.EXIT_COULD_NOT_RUN)

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
        A tier IN USE is expanded through `config/tiers.json` into its alias
        and its resolved model prefix, so naming the model is caught too.
        """
        tokens = fx.tier_tokens(["haiku45"])
        self.assertIn("haiku45", tokens)
        self.assertIn("haiku", tokens)
        self.assertIn("claude-haiku-4-5", tokens)
        found = fx.blind_check(
            {"task": "t", "file": "f", "diff": "+# routed to claude-haiku-4-5"},
            fx.blind_tokens("baseline", "treatment", tiers=["haiku45"]))
        self.assertIn("claude-haiku-4-5", found)

    def test_a_tier_that_is_not_in_use_does_not_contribute_tokens(self):
        """W5 FALSE POSITIVE. `tier_tokens()` used to enumerate every tier in
        `config/tiers.json` whether or not the run touched it, so prose naming
        a model the run never used tripped the blind and forced exit 1."""
        tokens = fx.tier_tokens(["cheap"])
        for absent in ("opus", "haiku", "sonnet", "claude-opus-5"):
            self.assertNotIn(absent, tokens)

    def test_the_tiers_actually_in_the_fixtures_are_blind_tokens(self):
        """W5 FALSE NEGATIVE, and the sharp one.

        The tier names these fixtures record are `cheap` and `frontier`.
        Neither appears in `config/tiers.json`, so under the old hardcoded
        list NEITHER was ever a token: a diff reading "# cheap tier" passed
        the blind check cleanly. The check was guarding names that were not in
        play and ignoring the two that were.
        """
        report = self.run_suite()
        self.assertEqual(report.tiers_in_use, ["cheap", "frontier"])
        tokens = fx.blind_tokens("baseline", "treatment",
                                 tiers=report.tiers_in_use)
        self.assertIn("cheap", tokens)
        self.assertIn("frontier", tokens)
        found = fx.blind_check(
            {"task": "t", "file": "f", "diff": "+# routed to the cheap tier"},
            tokens)
        self.assertEqual(found, ["cheap"])

    def test_a_cheap_tier_leak_in_a_fixture_is_caught_end_to_end(self):
        """The false negative, proven through the whole gate rather than on
        the token list alone: a planted `cheap` leak must be exit 1."""
        path = self.suite_dir / "recorded" / "treatment" / "clamp-probability" / "0.json"
        blob = json.loads(path.read_text())
        blob["diff"] += "+# generated on the cheap tier\n"
        path.write_text(json.dumps(blob))
        report = self.run_suite(judge=fx.RecordedJudge(self.suite_dir))
        self.assertTrue(report.blind_failures)
        self.assertIn("cheap", report.blind_failures[0])
        self.assertEqual(report.exit_code, gate.EXIT_COULD_NOT_RUN)

    def test_the_blind_check_matches_whole_words_and_not_substrings(self):
        """W5 FALSE POSITIVE. Substring matching flagged any diff touching a
        variable named `control`/`controller`, and any prose containing
        `haikus`. It erred safe -- a spurious blind failure is exit 1, not a
        false pass -- but a guard that fires on ordinary code is a guard that
        gets switched off, and on real mined tasks it would have produced
        COULD-NOT-RUNs with nothing to do with the blind.
        """
        tokens = fx.blind_tokens("baseline", "treatment", tiers=["haiku45"])
        for benign in ("+ self.controller = Controller()",
                       "+ control_flow_graph = build()",
                       "+# it wrote haikus about baselines",
                       "+ warm=True"):
            self.assertEqual(
                fx.blind_check({"task": "t", "file": "f", "diff": benign}, tokens),
                [], benign)

    def test_word_boundaries_do_not_weaken_the_checks_that_must_still_fire(self):
        """The boundary is applied only to word-character ends, so `arm=` still
        matches `arm=treatment` and a DATED model id is still caught."""
        tokens = fx.blind_tokens("baseline", "treatment", tiers=["haiku45"])
        self.assertIn("arm=", fx.blind_check(
            {"task": "t", "file": "f", "diff": "+# arm=treatment"}, tokens))
        self.assertIn("claude-haiku-4-5", fx.blind_check(
            {"task": "t", "file": "f", "diff": "+# claude-haiku-4-5-20251001"}, tokens))
        self.assertIn("baseline", fx.blind_check(
            {"task": "t", "file": "f", "diff": "+# the BASELINE run"}, tokens))

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
                                            ref="0" * 32)


# ---------------------------------------------------------------------------
# W5 audit: the blind is a property of the INTERFACE, not of one judge's
# good behaviour. Three ways the arm can reach a judge, and all three closed.
# ---------------------------------------------------------------------------

class SpyJudge:
    """Records everything it is handed. It is the adversary the blind is for."""
    enabled = True

    def __init__(self):
        self.calls: list[dict] = []

    def score(self, payload, **kwargs):
        self.calls.append({"payload": payload, **kwargs})
        return fx.JudgeVerdict()


class SpyExecutor:
    """A real executor that records the order it was driven in."""

    def __init__(self, root: Path):
        self.inner = fx.RecordedExecutor(root)
        self.order: list[tuple[str, str, int]] = []
        self.executions: list[fx.Execution] = []

    def run(self, task, arm, seed):
        self.order.append((task.task_id, arm, seed))
        execution = self.inner.run(task, arm, seed)
        self.executions.append(execution)
        return execution


class TestBlindIsStructural(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jev-w5-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.suite_dir = self.tmp / "suite-v1"
        shutil.copytree(SUITE, self.suite_dir)

    def run_suite(self, **kwargs):
        return fx.run_class2(fx.load_suite(self.suite_dir),
                             kwargs.pop("executor", None) or fx.RecordedExecutor(self.suite_dir),
                             baseline_arm="baseline", treatment_arm="treatment",
                             **kwargs)

    # -- defect 1: the arm label at the interface ---------------------------

    def test_the_judge_protocol_does_not_take_an_arm(self):
        """The regression test for the defect itself.

        `Judge.score` used to require `(payload, *, task_id, arm, seed)`. A
        clean payload handed over beside `arm="treatment"` is not a blind; it
        is one implementation's discipline. If anyone re-adds the parameter,
        this fails.
        """
        params = inspect.signature(fx.Judge.score).parameters
        self.assertEqual([p for p in params if p != "self"], ["payload", "ref"])
        for name in ("arm", "task_id", "seed"):
            self.assertNotIn(name, params)

    def test_no_judge_implementation_accepts_an_arm(self):
        for cls in (fx.NoJudge, fx.RecordedJudge, fx.LiveJudge):
            params = inspect.signature(cls.score).parameters
            self.assertNotIn("arm", params, cls.__name__)

    def test_a_spy_judge_never_receives_either_arm_name_in_any_argument(self):
        """The end-to-end version: drive a full run and inspect every single
        thing the judge was handed."""
        spy = SpyJudge()
        self.run_suite(judge=spy)
        self.assertEqual(len(spy.calls), 72)
        for call in spy.calls:
            blob = json.dumps(call)
            for leak in ("baseline", "treatment", "cheap", "frontier"):
                self.assertNotIn(leak, blob)
            self.assertEqual(sorted(call), ["payload", "ref"])
            self.assertRegex(call["ref"], r"^[0-9a-f]{32}$")

    def test_the_ref_is_opaque_and_not_a_relabelled_arm(self):
        """A ref must not be decodable by guessing the arm names, which is all
        an unsalted hash of (task, arm, seed) would take."""
        spy = SpyJudge()
        self.run_suite(judge=spy)
        refs = {c["ref"] for c in spy.calls}
        self.assertEqual(len(refs), 72)          # no collisions
        unsalted = {
            hashlib.sha256(f"{t}\x00{a}\x00{s}".encode()).hexdigest()[:32]
            for t in [x.task_id for x in fx.load_suite(self.suite_dir).tasks]
            for a in ("baseline", "treatment") for s in range(3)}
        self.assertEqual(refs & unsalted, set())

    def test_the_salt_is_fresh_per_run_so_refs_do_not_carry_across_runs(self):
        a, b = SpyJudge(), SpyJudge()
        self.run_suite(judge=a, order_seed=7)
        self.run_suite(judge=b, order_seed=7)
        # Same order_seed, so the two runs judged the SAME units in the SAME
        # sequence -- that is the control for the assertion underneath.
        self.assertEqual([c["payload"]["task"] for c in a.calls],
                         [c["payload"]["task"] for c in b.calls])
        # ...and yet no ref repeats, because the salt is fresh per run.
        self.assertEqual(set(c["ref"] for c in a.calls) &
                         set(c["ref"] for c in b.calls), set())

    def test_the_order_seed_is_recorded_but_the_salt_is_not(self):
        report = self.run_suite(order_seed=99)
        self.assertEqual(report.order_seed, 99)
        blob = json.dumps(report, default=lambda o: getattr(o, "__dict__", str(o)))
        self.assertNotIn("salt", blob)

    def test_the_live_judge_has_no_way_to_receive_the_decoder(self):
        """`RecordedJudge.bind` is the decoder. Its ABSENCE on LiveJudge is
        the blind, and `run_class2` type-checks rather than duck-types so a
        live judge that grew a `bind` could not acquire the salt by accident.
        """
        self.assertFalse(hasattr(fx.LiveJudge(), "bind"))
        self.assertFalse(hasattr(fx.NoJudge(), "bind"))
        self.assertTrue(hasattr(fx.RecordedJudge(self.suite_dir), "bind"))
        source = inspect.getsource(fx.run_class2)
        self.assertIn("isinstance(judge, RecordedJudge)", source)

    def test_the_recorded_judge_resolves_refs_through_an_index_it_scans(self):
        """The fixtures did not move: the index is built by walking the same
        recorded/judge/<arm>/<task>/<seed>.json tree that was always there."""
        judge = fx.RecordedJudge(self.suite_dir)
        mint = fx.RefMint()
        judge.bind(mint)
        self.assertEqual(len(judge._index), 72)
        verdict = judge.score({"task": "t", "file": "f", "diff": "+x"},
                              ref=mint.ref("clamp-probability", "baseline", 0))
        self.assertEqual(verdict.dimensions["correctness"], 8.0)

    def test_an_unknown_ref_is_a_harness_failure_and_leaks_nothing(self):
        judge = fx.RecordedJudge(self.suite_dir)
        judge.bind(fx.RefMint())
        with self.assertRaises(fx.HarnessFailure) as ctx:
            judge.score({}, ref="f" * 32)
        message = str(ctx.exception)
        self.assertIn("f" * 32, message)
        # An error message is not a side channel.
        for leak in ("baseline", "treatment", "cheap", "frontier"):
            self.assertNotIn(leak, message)

    def test_an_unbound_recorded_judge_refuses_rather_than_guessing(self):
        with self.assertRaises(fx.HarnessFailure):
            fx.RecordedJudge(self.suite_dir).score({}, ref="0" * 32)

    # -- defect 2: task order is part of the blind --------------------------

    def test_task_order_is_randomised_and_the_arms_interleave(self):
        """The defect: `run_class2` ran baseline fully then treatment fully,
        so the judge saw BBBTTTBBBTTT... and could learn the arm by counting
        without reading a single token. JEV-29's 'randomise task order' box
        was unticked and it was unticked truthfully.
        """
        spy = SpyExecutor(self.suite_dir)
        report = self.run_suite(executor=spy, order_seed=12345)
        self.assertEqual(len(spy.order), 72)

        # Not the old block structure.
        arms = "".join("B" if a == "baseline" else "T" for _, a, _ in spy.order)
        self.assertNotEqual(arms, "BBBTTT" * 12)

        # Tasks are not walked in manifest order either.
        suite_order = [t.task_id for t in fx.load_suite(self.suite_dir).tasks]
        first_seen = []
        for task_id, _, _ in spy.order:
            if task_id not in first_seen:
                first_seen.append(task_id)
        self.assertNotEqual(first_seen, suite_order)

        # And every unit still ran exactly once.
        self.assertEqual(len(set(spy.order)), 72)
        self.assertEqual(report.execution_order, spy.order)

    def test_no_task_runs_its_whole_baseline_block_before_its_treatment_block(self):
        """The property that actually matters, stated directly: for at least
        one task, a treatment seed precedes a baseline seed."""
        spy = SpyExecutor(self.suite_dir)
        self.run_suite(executor=spy, order_seed=2024)
        positions: dict[str, list[tuple[int, str]]] = {}
        for i, (task_id, arm, _) in enumerate(spy.order):
            positions.setdefault(task_id, []).append((i, arm))
        interleaved = [t for t, seq in positions.items()
                       if [a for _, a in seq] != ["baseline"] * 3 + ["treatment"] * 3]
        self.assertGreater(len(interleaved), 6, "arms are still blocked per task")

    def test_the_judge_is_driven_in_the_same_shuffled_order_as_the_executor(self):
        """Randomising the executor alone would fix NOTHING: the executor
        legitimately knows the arm. It is the JUDGE's call sequence that has
        to be unpredictable.

        This is the regression test for the subtle half of defect 2. Splitting
        `run_class2` into execute-then-judge invites judging in suite order,
        which would leave the judge seeing the same regular structure it always
        saw while the executor alone got shuffled -- a fix that fixes nothing
        and looks like it worked. So: compare the judge's actual call sequence
        to the executor's, by payload.
        """
        spy_exec = SpyExecutor(self.suite_dir)
        spy_judge = SpyJudge()
        report = self.run_suite(executor=spy_exec, judge=spy_judge, order_seed=31337)

        suite = fx.load_suite(self.suite_dir)
        prompt_of = {t.task_id: t.prompt for t in suite.tasks}
        self.assertEqual(len(set(prompt_of.values())), len(suite.tasks),
                         "prompts must be unique for this test to identify tasks")

        # The judge's Nth payload must be the executor's Nth unit. The ref is
        # opaque by design, so the payload's task prompt is the join.
        judge_tasks = [c["payload"]["task"] for c in spy_judge.calls]
        executor_tasks = [prompt_of[task_id] for task_id, _, _ in spy_exec.order]
        self.assertEqual(judge_tasks, executor_tasks)

        # And that sequence must not be suite order (each task 6x in a block),
        # which is what judging in phase 3 would have produced.
        suite_order_tasks = [prompt_of[t.task_id] for t in suite.tasks for _ in range(6)]
        self.assertNotEqual(judge_tasks, suite_order_tasks)

        # The diffs travel with them: the judge sees the execution that was
        # actually run for that unit, not a re-derived one.
        judge_diffs = [c["payload"]["diff"] for c in spy_judge.calls]
        self.assertEqual(judge_diffs, [e.diff for e in spy_exec.executions])

        self.assertEqual(len(set(c["ref"] for c in spy_judge.calls)), 72)
        self.assertEqual(report.execution_order, spy_exec.order)

    def test_the_judge_does_not_see_a_per_task_block_of_six(self):
        """Stated as the property rather than as an inequality: if the judge
        were driven in suite order, its first six payloads would all be the
        same task. They must not be."""
        spy_judge = SpyJudge()
        self.run_suite(judge=spy_judge, order_seed=777)
        first_six = [c["payload"]["task"] for c in spy_judge.calls[:6]]
        self.assertGreater(len(set(first_six)), 1)

    def test_the_same_order_seed_reproduces_the_run_exactly(self):
        a, b = SpyExecutor(self.suite_dir), SpyExecutor(self.suite_dir)
        self.run_suite(executor=a, order_seed=4242)
        self.run_suite(executor=b, order_seed=4242)
        self.assertEqual(a.order, b.order)

    def test_a_different_order_seed_gives_a_different_order(self):
        a, b = SpyExecutor(self.suite_dir), SpyExecutor(self.suite_dir)
        self.run_suite(executor=a, order_seed=1)
        self.run_suite(executor=b, order_seed=2)
        self.assertNotEqual(a.order, b.order)

    def test_an_omitted_order_seed_is_random_and_still_recorded(self):
        seeds = {self.run_suite().order_seed for _ in range(5)}
        self.assertGreater(len(seeds), 1)

    def test_the_report_is_deterministic_even_though_the_order_is_not(self):
        """Randomising what the judge sees is the point. Randomising the
        OUTPUT would only make the gate harder to read."""
        a = self.run_suite(order_seed=11, judge=fx.RecordedJudge(self.suite_dir))
        b = self.run_suite(order_seed=99, judge=fx.RecordedJudge(self.suite_dir))
        self.assertEqual([o.task_id for o in a.outcomes],
                         [o.task_id for o in b.outcomes])
        self.assertEqual([o.baseline_pass for o in a.outcomes],
                         [o.baseline_pass for o in b.outcomes])
        self.assertEqual(a.cost_by_tier, b.cost_by_tier)
        self.assertEqual(a.attrition_by_tier, b.attrition_by_tier)
        self.assertEqual([o.dimension_delta for o in a.outcomes],
                         [o.dimension_delta for o in b.outcomes])

    def test_the_order_seed_is_rendered_so_a_run_can_be_reproduced(self):
        text = fx.render_class2(self.run_suite(order_seed=8675309))
        self.assertIn("8675309", text)
        self.assertIn("RANDOMISED", text)
        self.assertIn("--order-seed", text)

    def test_the_duration_medians_each_carry_their_own_n(self):
        report = self.run_suite()
        for arm in ("baseline", "treatment"):
            self.assertIn("n_task", report.durations[arm])
            self.assertIn("n_blocking", report.durations[arm])
        text = fx.render_class2(report)
        self.assertIn("task_s", text)
        self.assertIn("blocking_s", text)


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
        ~/.claude/projects/<proj>/<session>-.../sess.jsonl on 2026-09-21:
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
        result = so.join_outcomes(
            [{"tool_use_id": "toolu_A", "tier": "cheap", "decision": "routed"}],
            outcomes, blocking)
        rows = result.rows
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0].task_duration_s, 540.0)
        self.assertAlmostEqual(rows[0].blocking_duration_s, 1.4, places=3)
        self.assertNotEqual(rows[0].task_duration_s, rows[0].blocking_duration_s)
        self.assertEqual(rows[0].request_shape, "background")
        rendered = so.render_outcomes(result)
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
        result = so.join_outcomes(
            [{"tool_use_id": "toolu_A", "tier": "cheap"},
             {"tool_use_id": "toolu_MISSING", "tier": "cheap"}],
            [], {})
        self.assertEqual([r.outcome_found for r in result.rows], [False, False])
        self.assertIn("no subagent transcript", result.rows[0].attrition_reason)
        self.assertIn("ATTRITION", so.render_outcomes(result))

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
        text = so.render_outcomes(so.SessionOutcomes(rows=rows))
        self.assertIn("$/assigned", text)
        self.assertIn("$/outcome", text)

    def test_intention_to_treat_keeps_every_assigned_row(self):
        ledger = [{"tool_use_id": f"t{i}", "tier": "cheap"} for i in range(5)]
        result = so.join_outcomes(ledger, [], {})
        self.assertEqual(len(result.rows), len(ledger))

    # -- W5: the MIRROR of attrition ----------------------------------------

    def test_a_transcript_with_no_assignment_is_a_named_category_not_a_drop(self):
        """The W5 defect, in its smallest form.

        A transcript that joins to no ledger row used to be read off disk and
        discarded without a line of output. On the real <session> session that
        was 3 transcripts and $3.93 -- 2.3% of delegated spend -- vanishing
        while the same table printed an attrition rate of 0.00%.
        """
        self.write_subagent("orphan1", [
            assistant_line("req1", "2026-09-20T10:00:00.000Z"),
        ], {"agentType": "general-purpose", "toolUseId": "toolu_NESTED",
            "spawnDepth": 2, "parentAgentId": "aparent1"})
        outcomes = so.read_session_subagents(self.session)
        result = so.join_outcomes([{"tool_use_id": "toolu_A", "tier": "cheap"}],
                                  outcomes, {})
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(len(result.unassigned), 1)
        self.assertGreater(result.unassigned_cost_usd, 0.0)
        self.assertAlmostEqual(result.total_cost_usd,
                               result.assigned_cost_usd + result.unassigned_cost_usd)

    def test_the_orphan_cost_is_rendered_with_its_share_and_its_reason(self):
        self.write_subagent("orphan1", [
            assistant_line("req1", "2026-09-20T10:00:00.000Z"),
        ], {"agentType": "general-purpose", "toolUseId": "toolu_NESTED",
            "spawnDepth": 2, "parentAgentId": "aparent1"})
        result = so.join_outcomes([], so.read_session_subagents(self.session), {})
        text = so.render_outcomes(result)
        self.assertIn("joined to NO assignment", text)
        self.assertIn("nested spawn", text)
        self.assertIn("aparent1", text)
        self.assertIn("total delegated spend", text)
        self.assertIn("unattributed", text)

    def test_the_orphan_section_is_printed_even_when_there_are_none(self):
        """Silence is the defect. An empty category must still say so --
        otherwise the reader cannot tell 'none' from 'not checked'."""
        result = so.join_outcomes([{"tool_use_id": "t0", "tier": "cheap"}], [], {})
        text = so.render_outcomes(result)
        self.assertIn("joined to NO assignment", text)
        self.assertIn("every transcript on disk is attributed", text)

    def test_both_medians_are_rendered_with_their_own_explicit_n(self):
        """The two published medians were over 33 and 30 and were printed
        side by side under one implied n."""
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
        ], {"agentType": "Explore", "toolUseId": "toolu_A"})
        self.write_subagent("orphan1", [
            assistant_line("req3", "2026-09-20T10:00:00.000Z"),
            assistant_line("req4", "2026-09-20T10:03:00.000Z"),
        ], {"agentType": "general-purpose", "toolUseId": "toolu_NESTED",
            "spawnDepth": 2, "parentAgentId": "aparent1"})
        result = so.outcomes_for_session(self.session)
        text = so.render_outcomes(result)
        self.assertIn("ITS OWN n", text)
        # task duration over 2 transcripts, blocking over 1 assignment.
        self.assertIn("n=2", text)
        self.assertIn("n=1", text)
        self.assertIn("DIFFERENT sets", text)

    def test_the_cli_does_not_report_could_not_run_when_only_orphans_exist(self):
        """Orphans alone are still a measurement, and $3.93 is not nothing."""
        self.write_parent([])
        self.write_subagent("orphan1", [
            assistant_line("req1", "2026-09-20T10:00:00.000Z"),
        ], {"agentType": "general-purpose", "toolUseId": "toolu_NESTED",
            "spawnDepth": 2, "parentAgentId": "aparent1"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = so.main(["--session", str(self.session)])
        self.assertEqual(code, 0)
        self.assertIn("joined to NO assignment", buf.getvalue())

    # -- W5: a task that never completed ------------------------------------

    def test_a_truncated_transcript_is_not_indistinguishable_from_a_finished_one(self):
        """Nothing read a status or completion marker, so a truncated
        transcript yielded `outcome_found=True` with a PARTIAL cost that read
        as a final one. Observed for real: one of the 33 transcripts on the
        <session> session ends on an assistant `tool_use` whose result came
        back and was never answered.
        """
        finished = [assistant_line("req1", "2026-09-20T10:00:00.000Z")]
        finished[-1]["message"]["stop_reason"] = "end_turn"
        self.write_subagent("done", finished,
                            {"agentType": "Explore", "toolUseId": "toolu_DONE"})
        cut = [assistant_line("req2", "2026-09-20T10:00:00.000Z")]
        cut[-1]["message"]["stop_reason"] = "tool_use"
        self.write_subagent("cut", cut,
                            {"agentType": "Explore", "toolUseId": "toolu_CUT"})

        by_id = {o.tool_use_id: o for o in so.read_session_subagents(self.session)}
        self.assertTrue(by_id["toolu_DONE"].completed)
        self.assertFalse(by_id["toolu_CUT"].completed)
        self.assertIn("tool_use", by_id["toolu_CUT"].completion)

        result = so.join_outcomes(
            [{"tool_use_id": "toolu_DONE"}, {"tool_use_id": "toolu_CUT"}],
            by_id.values(), {})
        # Both have an outcome; only one finished. Three states, not two.
        self.assertEqual([r.outcome_found for r in result.rows], [True, True])
        self.assertEqual([r.completed for r in result.rows], [True, False])
        self.assertEqual(len(result.incomplete), 1)
        self.assertIn("INCOMPLETE", so.render_outcomes(result))

    def test_a_trailing_non_assistant_line_does_not_read_as_truncation(self):
        """A transcript may carry an `attachment`, `tool_result` or system
        line AFTER a final assistant turn that ended cleanly. Last-line-only
        would read every one of those as truncated; the marker is the last
        ASSISTANT message.

        This case is SYNTHETIC on purpose. The real <session> corpus does not
        discriminate between the two rules -- its one attachment-tailed file
        is also its one genuinely truncated file -- so the corpus cannot be
        cited as evidence for this choice, and this test supplies the case the
        corpus lacks.
        """
        lines = [assistant_line("req1", "2026-09-20T10:00:00.000Z")]
        lines[-1]["message"]["stop_reason"] = "end_turn"
        lines.append({"type": "attachment", "timestamp": "2026-09-20T10:00:01.000Z"})
        self.write_subagent("a1", lines,
                            {"agentType": "Explore", "toolUseId": "toolu_A"})
        outcome = so.read_subagent(self.subagents / "agent-a1.jsonl")
        self.assertTrue(outcome.completed)
        self.assertEqual(outcome.completion, "end_turn")

    def test_a_transcript_with_no_assistant_message_is_not_complete(self):
        self.write_subagent("a1", [{"type": "user", "message": {"role": "user"}}],
                            {"agentType": "Explore", "toolUseId": "toolu_A"})
        outcome = so.read_subagent(self.subagents / "agent-a1.jsonl")
        self.assertFalse(outcome.completed)
        self.assertIn("no assistant message", outcome.completion)

    # -- W5: a retried task --------------------------------------------------

    def test_two_transcripts_sharing_a_tool_use_id_do_not_collapse(self):
        """`{o.tool_use_id: o for o in outcomes}` silently kept the LAST file
        and the earlier attempt's cost disappeared. A retry costs what both
        attempts cost."""
        for name, req in (("try1", "req1"), ("try2", "req2")):
            lines = [assistant_line(req, "2026-09-20T10:00:00.000Z")]
            lines[-1]["message"]["stop_reason"] = "end_turn"
            self.write_subagent(name, lines,
                                {"agentType": "Explore", "toolUseId": "toolu_RETRY"})
        outcomes = so.read_session_subagents(self.session)
        self.assertEqual(len(outcomes), 2)
        each = outcomes[0].cost_usd
        self.assertGreater(each, 0.0)

        result = so.join_outcomes([{"tool_use_id": "toolu_RETRY", "tier": "cheap"}],
                                  outcomes, {})
        row = result.rows[0]
        self.assertEqual(row.attempts, 2)
        self.assertAlmostEqual(row.cost_usd, each * 2)
        self.assertEqual(result.unassigned, [])   # neither attempt is an orphan
        self.assertIn("RETRIED x2", so.render_outcomes(result))

    def test_a_retry_is_one_assignment_not_two(self):
        """Intention-to-treat: the unit is the ASSIGNMENT. Two attempts at one
        assignment must not inflate the denominator."""
        for name, req in (("try1", "req1"), ("try2", "req2")):
            self.write_subagent(name, [assistant_line(req, "2026-09-20T10:00:00.000Z")],
                                {"agentType": "Explore", "toolUseId": "toolu_RETRY"})
        result = so.join_outcomes([{"tool_use_id": "toolu_RETRY", "tier": "cheap"}],
                                  so.read_session_subagents(self.session), {})
        self.assertEqual(len(result.rows), 1)
        by_tier = so.attrition_by_tier(result.rows)
        self.assertEqual(by_tier["cheap"]["assignments"], 1)
        self.assertEqual(by_tier["cheap"]["outcomes"], 1)
        # but both transcripts are accounted for
        self.assertEqual(result.n_transcripts, 2)

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
