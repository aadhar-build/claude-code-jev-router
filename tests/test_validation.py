#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Known answers for the two validation tools.

Both tools exist to stop a number being believed too easily, so their own
numbers have to be checkable by hand. The construction of each fixture is the
test: a perfectly separable set MUST show a zero optimism gap, and a set where
the score carries no information about the label MUST show a large one. If
either of those came out the other way, the optimism gap would not be measuring
optimism.

The pure functions take lists, not files, so most of this never touches the
store. The three tests that do exercise the collection filters -- sweep rows,
duplicates, run_context -- because those are where live data will break things
that synthetic data never does.
"""

from __future__ import annotations

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
import determinism as det  # noqa: E402
import paths  # noqa: E402
import store  # noqa: E402
import validate_threshold as vt  # noqa: E402


def items_for(n_pos: int, n_neg: int) -> list[dict]:
    return (
        [{"decision_id": f"p{i}", "stratum": "destructive", "session_id": "s"}
         for i in range(n_pos)]
        + [{"decision_id": f"n{i}", "stratum": "benign", "session_id": "s"}
           for i in range(n_neg)]
    )


def labels_for(items: list[dict]) -> dict[str, bool]:
    return {i["decision_id"]: i["stratum"] == "destructive" for i in items}


# --------------------------------------------------------------------------
# threshold rules
# --------------------------------------------------------------------------

class ThresholdRules(unittest.TestCase):
    POS = [0.9, 0.6, 0.3]
    NEG = [0.2, 0.1]

    def test_rates_at_uses_greater_or_equal(self):
        # tau sits exactly on a positive score: it must be caught, not missed.
        tpr, fpr = vt.rates_at(0.3, self.POS, self.NEG)
        self.assertEqual(tpr, 1.0)
        self.assertEqual(fpr, 0.0)

    def test_rates_at_midpoint(self):
        tpr, fpr = vt.rates_at(0.5, self.POS, self.NEG)
        self.assertAlmostEqual(tpr, 2 / 3)
        self.assertEqual(fpr, 0.0)

    def test_threshold_for_recall_takes_the_highest_tau_that_clears_target(self):
        self.assertEqual(vt.threshold_for_recall(self.POS, self.NEG, 1.0), 0.3)
        self.assertEqual(vt.threshold_for_recall(self.POS, self.NEG, 0.6), 0.6)
        # 1/3 recall exactly clears a 0.33 target, so the strictest tau wins.
        self.assertEqual(vt.threshold_for_recall(self.POS, self.NEG, 0.33), 0.9)

    def test_threshold_for_recall_is_nan_when_unreachable(self):
        tau = vt.threshold_for_recall([0.9], [0.95], 1.01)
        self.assertNotEqual(tau, tau)     # nan


# --------------------------------------------------------------------------
# splitting
# --------------------------------------------------------------------------

class Splitting(unittest.TestCase):
    def setUp(self):
        self.items = items_for(10, 20)

    def test_splits_are_disjoint_and_exhaustive(self):
        for train, test in vt.make_splits(self.items, 20, seed=1, train_frac=0.5):
            self.assertEqual(train & test, set())
            self.assertEqual(len(train | test), 30)

    def test_splits_are_stratified(self):
        for train, test in vt.make_splits(self.items, 20, seed=1, train_frac=0.5):
            self.assertEqual(sum(1 for d in train if d.startswith("p")), 5)
            self.assertEqual(sum(1 for d in test if d.startswith("p")), 5)

    def test_splits_are_reproducible_and_seed_sensitive(self):
        a = vt.make_splits(self.items, 5, seed=7, train_frac=0.5)
        b = vt.make_splits(self.items, 5, seed=7, train_frac=0.5)
        c = vt.make_splits(self.items, 5, seed=8, train_frac=0.5)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_no_stratum_is_handed_entirely_to_one_side(self):
        # A test half with no positives has an undefined TPR; the splitter must
        # never produce one, even at an extreme train fraction.
        for train, test in vt.make_splits(self.items, 20, seed=3, train_frac=0.99):
            self.assertTrue(any(d.startswith("p") for d in test))
            self.assertTrue(any(d.startswith("p") for d in train))


# --------------------------------------------------------------------------
# the optimism gap itself -- the two anchor cases
# --------------------------------------------------------------------------

class OptimismGap(unittest.TestCase):
    def test_perfectly_separable_set_has_a_zero_gap(self):
        """Every positive at 0.9, every negative at 0.1.

        Whatever half the rule is fitted on, it picks 0.9 and scores a perfect
        J on both halves. Anything other than an exactly zero gap would mean the
        procedure manufactures optimism out of nothing.
        """
        items = items_for(10, 20)
        scores = {i["decision_id"]: (0.9 if i["stratum"] == "destructive" else 0.1)
                  for i in items}
        v = vt.validate(items, scores, labels_for(items), arm="a", question="q",
                        context="synthetic", n_splits=50)
        self.assertEqual(v.auc, 1.0)
        self.assertEqual(set(v.youden.column("tau")), {0.9})
        self.assertEqual(set(v.youden.column("gap")), {0.0})
        self.assertEqual(set(v.youden.column("test_j")), {1.0})
        ok, _ = vt.survives(v)
        self.assertTrue(ok)

    def test_pure_noise_shows_a_large_gap(self):
        """Score and label are independent by construction: AUC 0.5.

        A Youden fit on any half still finds a threshold with a positive J --
        that is exactly the overfit. On the other half it buys nothing, so the
        gap is large and the verdict must be FAIL.
        """
        items = items_for(15, 15)
        # Interleave the classes along the score axis, so ranking is uninformative.
        scores = {}
        for k, item in enumerate(sorted(items, key=lambda i: i["decision_id"])):
            scores[item["decision_id"]] = round(0.02 + 0.03 * k, 3)
        # Re-key so that ordering by score alternates label.
        ordered = sorted(scores, key=lambda d: scores[d])
        labels = {d: (k % 2 == 0) for k, d in enumerate(ordered)}
        items = [{"decision_id": d,
                  "stratum": "destructive" if labels[d] else "benign",
                  "session_id": "s"} for d in ordered]

        v = vt.validate(items, scores, labels, arm="a", question="q",
                        context="synthetic", n_splits=200)
        self.assertLess(abs(v.auc - 0.5), 0.1)
        gap = vt.stats.quantiles(v.youden.column("gap"), [0.5])["p50"]
        self.assertGreater(gap, 0.15)
        ok, checks = vt.survives(v)
        self.assertFalse(ok)
        self.assertTrue(any("optimism gap" in name and not passed
                            for name, passed, _ in checks))

    def test_in_sample_j_is_never_below_the_median_test_j_for_noise(self):
        """The direction of the bias is the claim: fitting flatters itself."""
        items = items_for(12, 12)
        ordered = [i["decision_id"] for i in items]
        scores = {d: round(0.02 + 0.04 * k, 3) for k, d in enumerate(sorted(ordered))}
        labels = {d: (k % 2 == 0) for k, d in enumerate(sorted(scores, key=lambda x: scores[x]))}
        items = [{"decision_id": d,
                  "stratum": "destructive" if labels[d] else "benign",
                  "session_id": "s"} for d in ordered]
        v = vt.validate(items, scores, labels, arm="a", question="q",
                        context="synthetic", n_splits=200)
        trained = vt.stats.quantiles(v.youden.column("train_j"), [0.5])["p50"]
        tested = vt.stats.quantiles(v.youden.column("test_j"), [0.5])["p50"]
        self.assertGreater(trained, tested)

    def test_unlabelled_items_are_excluded_and_counted(self):
        items = items_for(5, 5)
        scores = {i["decision_id"]: 0.5 for i in items}
        scores["mystery"] = 0.4
        labels = labels_for(items)
        v = vt.validate(items, scores, labels, arm="a", question="q",
                        context="live", n_splits=5)
        self.assertEqual(v.n_unlabelled, 1)
        self.assertEqual(v.n_items, 10)

    def test_render_survives_an_empty_result_set(self):
        text = vt.render([], surface="pre_bash", n_splits=10, seed=1, diagnostics={})
        self.assertIn("NO VALIDATABLE DATA", text)


# --------------------------------------------------------------------------
# collection filters
# --------------------------------------------------------------------------

class TempStorage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self._saved = {}
        for name in ("CAPTURES", "STATES", "RUNS", "LABELS"):
            self._saved[name] = getattr(paths, name)
            target = base / name.lower()
            target.mkdir(parents=True, exist_ok=True)
            setattr(paths, name, target)

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(paths, name, value)
        self._tmp.cleanup()

    def capture(self, did, stratum, context="synthetic"):
        store.append_capture({
            "decision_id": did, "surface": "pre_bash", "session_id": "s1",
            "state_sha256": "a" * 64, "run_context": context, "stratum": stratum,
            "is_sidechain": False,
        })

    def run_row(self, did, p, *, arm="jev", context="synthetic", sweep=None, ok=True):
        row = {
            "decision_id": did, "surface": "pre_bash", "session_id": "s1",
            "arm": arm, "ok": ok, "run_context": context,
            "question_set_id": cl.question_set_id("pre_bash"),
            "state_sha256": "a" * 64,
            "answers": {"destructive": {"type": "boolean", "probability": p}},
        }
        if sweep:
            row["sweep"] = sweep
        store.append_run(row)


class CollectionFilters(TempStorage):
    def test_determinism_sweep_rows_never_enter_the_threshold_analysis(self):
        """The bug this guards: once --determinism runs, every synthetic item
        gains twenty extra rows and would be weighted twenty-fold."""
        self.capture("d1", "destructive")
        self.run_row("d1", 0.8)
        for _ in range(20):
            self.run_row("d1", 0.2, context="replay", sweep="determinism")
        items, scores, diag = vt.collect("pre_bash", "synthetic")
        self.assertEqual(len(items), 1)
        self.assertEqual(scores["jev"]["destructive"], {"d1": 0.8})
        self.assertEqual(diag["duplicates"], 0)

    def test_duplicate_rows_are_counted_not_averaged(self):
        self.capture("d1", "benign")
        self.run_row("d1", 0.1)
        self.run_row("d1", 0.9)
        items, scores, diag = vt.collect("pre_bash", "synthetic")
        self.assertEqual(scores["jev"]["destructive"]["d1"], 0.1)
        self.assertEqual(diag["duplicates"], 1)

    def test_failed_runs_are_excluded_and_counted(self):
        self.capture("d1", "benign")
        self.run_row("d1", 0.1, ok=False)
        _items, scores, diag = vt.collect("pre_bash", "synthetic")
        self.assertEqual(diag["failed"], 1)
        self.assertEqual(scores, {})

    def test_contexts_do_not_leak_into_each_other(self):
        self.capture("s1", "benign", context="synthetic")
        self.capture("l1", None, context="live")
        self.run_row("s1", 0.1, context="synthetic")
        self.run_row("l1", 0.9, context="live")
        _i, syn, _d = vt.collect("pre_bash", "synthetic")
        _i, live, _d = vt.collect("pre_bash", "live")
        self.assertEqual(set(syn["jev"]["destructive"]), {"s1"})
        self.assertEqual(set(live["jev"]["destructive"]), {"l1"})


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------

class GroupStatistics(unittest.TestCase):
    def test_spread_and_sd_of_a_constant_group_are_zero(self):
        g = det.Group("d", "jev", "destructive", None, [0.97] * 10)
        self.assertEqual(g.spread, 0.0)
        self.assertEqual(g.sd, 0.0)
        self.assertTrue(g.unanimous(0.5))
        self.assertEqual(g.pairwise_disagreement(0.5), 0.0)

    def test_one_flip_in_ten_is_reported_as_one_flip_in_ten(self):
        """The FINDINGS 2.3 borderline case, reconstructed."""
        g = det.Group("d", "jev", "destructive", None, [0.49] * 9 + [0.52])
        self.assertFalse(g.unanimous(0.5))
        self.assertAlmostEqual(g.fraction_above(0.5), 0.1)
        self.assertAlmostEqual(g.pairwise_disagreement(0.5), 0.18)

    def test_a_perfectly_split_group_is_maximally_unpredictable(self):
        g = det.Group("d", "jev", "destructive", None, [0.4] * 5 + [0.6] * 5)
        self.assertAlmostEqual(g.pairwise_disagreement(0.5), 0.5)


class Bucketing(unittest.TestCase):
    def build(self, n_near: int, n_far: int, flips_near: int, flips_far: int):
        groups = []
        for i in range(n_near):
            probs = ([0.49] * 5 + [0.51] * 5) if i < flips_near else [0.49] * 10
            groups.append(det.Group(f"near{i}", "jev", "q", None, probs))
        for i in range(n_far):
            # A "far" flipper sits at mean ~0.23 -- two thirds of a band away from
            # tau -- and still straddles it. That is the pattern that would mean
            # the wobble is not a boundary effect.
            probs = ([0.05] * 8 + [0.95] * 2) if i < flips_far else [0.10] * 10
            groups.append(det.Group(f"far{i}", "jev", "q", None, probs))
        return groups

    def test_flips_confined_near_the_threshold(self):
        rows = det.bucket(self.build(10, 10, flips_near=4, flips_far=0), 0.5)
        near = rows[0]                                   # 0.00 - 0.02
        far = [r for r in rows if r.lo >= 0.20][0]
        self.assertEqual(near.n_groups, 10)
        self.assertAlmostEqual(near.flip_rate, 0.4)
        self.assertEqual(far.n_groups, 10)
        self.assertEqual(far.flip_rate, 0.0)

    def test_a_thin_bucket_refuses_to_quote_a_rate(self):
        rows = det.bucket(self.build(2, 10, flips_near=2, flips_far=0), 0.5)
        self.assertEqual(rows[0].n_groups, 2)
        self.assertIsNone(rows[0].flip_rate)

    def test_empty_buckets_report_nothing_rather_than_zero_percent(self):
        lines: list[str] = []
        det._band_table(det.bucket([], 0.5), lines, rates=True)
        self.assertTrue(all("0%" not in line for line in lines))

    def test_arm_question_rollup(self):
        groups = self.build(10, 10, flips_near=4, flips_far=0)
        r = det.analyse(groups, "jev", "q", 0.5, arm_config_id=None, origin=None)
        self.assertEqual(r.n_groups, 20)
        self.assertEqual(r.n_calls, 200)
        self.assertAlmostEqual(r.flip_rate, 0.2)
        self.assertAlmostEqual(r.call_flip_rate, 20 / 200)
        self.assertIn("CONFINED", det._interpret_bands(r))

    def test_a_thin_flipping_bucket_is_never_read_as_stability(self):
        """Regression: an earlier interpretation ignored buckets below the
        reporting minimum and announced 'no flips anywhere' over a sample in
        which every flip had happened, because all of them were in a bucket of
        four. Suppressing a RATE must never suppress the FACT."""
        groups = self.build(4, 30, flips_near=4, flips_far=0)
        r = det.analyse(groups, "jev", "q", 0.5, arm_config_id=None, origin=None)
        summary = det._interpret_bands(r)
        self.assertNotIn("no flips", summary)
        self.assertIn("CONFINED", summary)
        self.assertIn("not yet resolvable", summary)

    def test_flips_everywhere_is_reported_as_the_bad_case(self):
        groups = self.build(10, 10, flips_near=4, flips_far=6)
        r = det.analyse(groups, "jev", "q", 0.5, arm_config_id=None, origin=None)
        self.assertIn("bad case", det._interpret_bands(r))


class DeterminismDegradation(TempStorage):
    def test_no_repeat_data_says_so_and_quotes_no_rate(self):
        self.capture("d1", "destructive")
        self.run_row("d1", 0.8)
        groups, single, diag = det.collect("pre_bash")
        self.assertEqual(groups, [])
        text = det.render([], single, diag, surface="pre_bash", tau_map={})
        self.assertIn("NOT ENOUGH REPEAT DATA", text)
        self.assertIn("replay.py --determinism", text)
        self.assertNotIn("DECISION FLIP RATE", text)
        # Occupancy is still available and still useful.
        self.assertIn("BAND OCCUPANCY", text)

    def test_a_designed_sweep_is_picked_up(self):
        self.capture("d1", "destructive")
        for p in [0.49] * 9 + [0.52]:
            self.run_row("d1", p, context="replay", sweep="determinism")
        groups, _single, diag = det.collect("pre_bash")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].n, 10)
        self.assertIn("designed", diag["source"])

    def test_incidental_repeats_are_flagged_as_not_a_sweep(self):
        self.capture("d1", "destructive")
        for p in (0.49, 0.50, 0.51):
            self.run_row("d1", p)
        groups, single, diag = det.collect("pre_bash")
        self.assertEqual(len(groups), 1)
        self.assertIn("NOT a designed sweep", diag["source"])
        r = det.analyse(groups, "jev", "destructive", 0.5, arm_config_id=None, origin=None)
        text = det.render([r], single, diag, surface="pre_bash", tau_map={})
        self.assertIn("NOT produced by a determinism sweep", text)

    def test_too_few_groups_is_withheld_rather_than_estimated(self):
        groups = [det.Group("d1", "jev", "q", None, [0.4] * 5 + [0.6] * 5)]
        r = det.analyse(groups, "jev", "q", 0.5, arm_config_id=None, origin=None)
        text = det.render([r], {}, {"source": "designed determinism sweep"},
                          surface="pre_bash", tau_map={})
        self.assertIn("Withheld", text)
        self.assertNotIn("DECISION FLIP RATE", text)

    def test_occupancy_separates_contexts(self):
        self.capture("s1", "destructive", context="synthetic")
        self.capture("l1", None, context="live")
        self.run_row("s1", 0.50, context="synthetic")
        self.run_row("l1", 0.51, context="live")
        _g, single, _d = det.collect("pre_bash")
        self.assertEqual(set(single), {"synthetic", "live"})
        self.assertEqual(single["synthetic"]["jev"]["destructive"], [0.50])
        self.assertEqual(single["live"]["jev"]["destructive"], [0.51])


class TauParsing(unittest.TestCase):
    def test_flat_and_per_question(self):
        flat, per_q = det.parse_tau(["0.5", "destructive=0.36", "destructive=0.4"])
        self.assertEqual(flat, [0.5])
        self.assertEqual(per_q, {"destructive": [0.36, 0.4]})

    def test_per_question_overrides_the_flat_value(self):
        self.assertEqual(det._taus("destructive", {"destructive": [0.36]}, [0.5]), [0.36])
        self.assertEqual(det._taus("needs_review", {"destructive": [0.36]}, [0.5]), [0.5])
        self.assertEqual(det._taus("needs_review", {}, []), det.DEFAULT_TAUS["needs_review"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
