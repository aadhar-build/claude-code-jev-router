#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-43. The wall-clock decomposition, tested against fixtures whose answer
is known by construction.

The point of these tests is that the decomposition is arithmetic over a row,
not a statistic over a corpus: every number below is hand-computed, so a
regression shows up as a wrong number rather than a shifted distribution.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pyversion  # noqa: E402

pyversion.require()

import latency  # noqa: E402


def cc_row(
    *,
    arm="cc_opus5",
    arm_config_id="cc-opus5-cli-v1",
    total_ms=9682.0,
    duration_ms=5350,
    duration_api_ms=5033,
    ok=True,
    decision_id="D1",
    arm_dispatch="concurrent",
    dispatch_offset_ms=0.0,
    run_context="live",
):
    return {
        "arm": arm,
        "arm_config_id": arm_config_id,
        "ok": ok,
        "run_context": run_context,
        "decision_id": decision_id,
        "arm_dispatch": arm_dispatch,
        "dispatch_offset_ms": dispatch_offset_ms,
        "timing_ms": {"total_ms": total_ms},
        "raw": {"duration_ms": duration_ms, "duration_api_ms": duration_api_ms},
    }


def jev_row(*, total_ms=563.0, decision_id="D1", dispatch_offset_ms=0.0,
            arm_dispatch="concurrent", ok=True):
    return {
        "arm": "jev",
        "arm_config_id": "jev-gateway-v1",
        "ok": ok,
        "run_context": "live",
        "decision_id": decision_id,
        "arm_dispatch": arm_dispatch,
        "dispatch_offset_ms": dispatch_offset_ms,
        "timing_ms": {"total_ms": total_ms},
        "raw": {"model": "typesafe-ai/jev"},
    }


class TestDecompose(unittest.TestCase):
    def test_three_clocks_sum_to_total(self):
        d = latency.decompose(cc_row(total_ms=9682.0, duration_ms=5350,
                                     duration_api_ms=5033))
        self.assertAlmostEqual(d.spawn_ms, 4332.0)
        self.assertAlmostEqual(d.in_session_ms, 317.0)
        self.assertAlmostEqual(d.api_ms, 5033.0)
        self.assertAlmostEqual(d.spawn_ms + d.in_session_ms + d.api_ms, 9682.0)

    def test_refuses_a_jev_row(self):
        # jev has no subprocess and no in-session clock. Returning zeros would
        # silently make it look like a clean cc_* row.
        with self.assertRaises(latency.LatencyError):
            latency.decompose(jev_row())

    def test_refuses_a_failed_row(self):
        # ok=False rows carry no timing at all; averaging over them is the
        # documented way this corpus lies to you.
        row = cc_row(ok=False)
        row["timing_ms"] = None
        row["raw"] = None
        with self.assertRaises(latency.LatencyError):
            latency.decompose(row)

    def test_refuses_a_row_missing_duration_ms(self):
        row = cc_row()
        del row["raw"]["duration_ms"]
        with self.assertRaises(latency.LatencyError):
            latency.decompose(row)


class TestContaminationClassifier(unittest.TestCase):
    def test_threshold_invariance_across_the_empirical_gap(self):
        """The corpus has zero mass between ~1.5s and ~18.5s of in-session
        residual. Any cut inside that gap must give the same classification;
        that invariance is the whole robustness argument for excluding the
        contaminated mode, so it is asserted rather than asserted-in-prose."""
        clean = [120.0, 258.0, 331.0, 539.0, 1_400.0]
        dirty = [18_526.0, 18_690.0, 19_785.0, 22_035.0]
        sample = clean + dirty
        expected = [False] * len(clean) + [True] * len(dirty)
        for floor in (2_000.0, 5_000.0, 10_000.0, 15_000.0, 18_000.0):
            got = [latency.is_contaminated(v, floor_ms=floor) for v in sample]
            self.assertEqual(got, expected, f"classification moved at floor={floor}")

    def test_default_floor_sits_inside_the_gap(self):
        self.assertGreater(latency.CONTAMINATION_FLOOR_MS, 1_500.0)
        self.assertLess(latency.CONTAMINATION_FLOOR_MS, 18_500.0)

    def test_gap_is_reported_so_a_future_corpus_can_invalidate_it(self):
        clean = [120.0, 331.0, 1_400.0]
        dirty = [18_526.0, 22_035.0]
        gap = latency.empirical_gap(clean + dirty, floor_ms=5_000.0)
        self.assertAlmostEqual(gap.below, 1_400.0)
        self.assertAlmostEqual(gap.above, 18_526.0)
        self.assertAlmostEqual(gap.width_ms, 17_126.0)


class TestBaselinesAndAdjustment(unittest.TestCase):
    def test_baselines_exclude_contaminated_rows(self):
        rows = [
            cc_row(duration_ms=1_300, duration_api_ms=1_000),   # residual 300
            cc_row(duration_ms=1_500, duration_api_ms=1_000),   # residual 500
            cc_row(duration_ms=19_700, duration_api_ms=1_000),  # residual 18700
        ]
        base = latency.clean_baselines(rows)
        self.assertAlmostEqual(base[("cc_opus5", "cc-opus5-cli-v1")], 400.0)

    def test_baselines_do_not_pool_across_arm_config_id(self):
        rows = [
            cc_row(arm="cc_haiku45", arm_config_id="cc-haiku45-cli-v1",
                   duration_ms=4_000, duration_api_ms=1_000),   # residual 3000
            cc_row(arm="cc_haiku45", arm_config_id="cc-haiku45-cli-v2-nothink",
                   duration_ms=1_400, duration_api_ms=1_000),   # residual 400
        ]
        base = latency.clean_baselines(rows)
        self.assertAlmostEqual(base[("cc_haiku45", "cc-haiku45-cli-v1")], 3_000.0)
        self.assertAlmostEqual(base[("cc_haiku45", "cc-haiku45-cli-v2-nothink")], 400.0)

    def test_adjustment_removes_only_the_excess_over_the_clean_baseline(self):
        base = {("cc_opus5", "cc-opus5-cli-v1"): 400.0}
        dirty = cc_row(total_ms=20_000.0, duration_ms=19_700, duration_api_ms=1_000)
        # residual 18_700; excess over baseline 18_300; adjusted 1_700
        self.assertAlmostEqual(latency.adjusted_total_ms(dirty, base), 1_700.0)

    def test_adjustment_is_identity_on_a_clean_row(self):
        base = {("cc_opus5", "cc-opus5-cli-v1"): 400.0}
        clean = cc_row(total_ms=5_000.0, duration_ms=4_000, duration_api_ms=3_700)
        self.assertAlmostEqual(latency.adjusted_total_ms(clean, base), 5_000.0)

    def test_adjustment_is_identity_on_a_jev_row(self):
        # jev spawns nothing and loads no user config: it cannot be contaminated,
        # and the adjustment must not quietly reach it.
        self.assertAlmostEqual(latency.adjusted_total_ms(jev_row(total_ms=563.0), {}),
                               563.0)


class TestDispatchWall(unittest.TestCase):
    def test_wall_is_the_max_over_arms_not_the_sum(self):
        rows = [
            jev_row(decision_id="D", dispatch_offset_ms=0.0, total_ms=560.0),
            cc_row(decision_id="D", arm="cc_opus5", dispatch_offset_ms=2.0,
                   total_ms=5_000.0, duration_ms=4_000, duration_api_ms=3_700),
            cc_row(decision_id="D", arm="cc_haiku45",
                   arm_config_id="cc-haiku45-cli-v1", dispatch_offset_ms=3.0,
                   total_ms=11_600.0, duration_ms=10_000, duration_api_ms=9_700),
        ]
        walls = latency.dispatch_walls(rows, {}, adjusted=False)
        self.assertAlmostEqual(walls["D"], 11_603.0)

    def test_wall_drops_when_one_arm_paid_the_contaminated_mode(self):
        base = {("cc_opus5", "cc-opus5-cli-v1"): 400.0,
                ("cc_haiku45", "cc-haiku45-cli-v1"): 400.0}
        rows = [
            jev_row(decision_id="D", dispatch_offset_ms=0.0, total_ms=560.0),
            cc_row(decision_id="D", arm="cc_opus5", dispatch_offset_ms=2.0,
                   total_ms=23_000.0, duration_ms=22_000, duration_api_ms=3_300),
            cc_row(decision_id="D", arm="cc_haiku45",
                   arm_config_id="cc-haiku45-cli-v1", dispatch_offset_ms=3.0,
                   total_ms=11_600.0, duration_ms=10_000, duration_api_ms=9_700),
        ]
        raw = latency.dispatch_walls(rows, base, adjusted=False)
        adj = latency.dispatch_walls(rows, base, adjusted=True)
        self.assertAlmostEqual(raw["D"], 23_002.0)
        # opus residual 18_700, excess 18_300 -> adjusted total 4_700 -> 4_702
        # so the decision's wall falls back to haiku's 11_603
        self.assertAlmostEqual(adj["D"], 11_603.0)

    def test_a_failed_row_does_not_enter_the_wall(self):
        rows = [
            jev_row(decision_id="D", total_ms=560.0),
            {"arm": "cc_opus5", "arm_config_id": "cc-opus5-cli-v1", "ok": False,
             "decision_id": "D", "run_context": "live", "arm_dispatch": "concurrent",
             "dispatch_offset_ms": 1.0, "timing_ms": None, "raw": None},
        ]
        self.assertAlmostEqual(latency.dispatch_walls(rows, {})["D"], 560.0)


class TestQuantiles(unittest.TestCase):
    def test_linear_interpolation_matches_hand_computation(self):
        v = [1.0, 2.0, 3.0, 4.0]
        self.assertAlmostEqual(latency.quantile(v, 0.0), 1.0)
        self.assertAlmostEqual(latency.quantile(v, 0.5), 2.5)
        self.assertAlmostEqual(latency.quantile(v, 1.0), 4.0)
        self.assertAlmostEqual(latency.quantile(v, 0.25), 1.75)

    def test_empty_is_none_not_zero(self):
        self.assertIsNone(latency.quantile([], 0.5))


class TestSummary(unittest.TestCase):
    def test_summary_reports_rate_and_both_publishable_numbers(self):
        rows = [
            cc_row(total_ms=5_000.0, duration_ms=4_000, duration_api_ms=3_700),
            cc_row(total_ms=5_000.0, duration_ms=4_000, duration_api_ms=3_700),
            cc_row(total_ms=23_000.0, duration_ms=22_000, duration_api_ms=3_700),
        ]
        s = latency.summarise(rows)
        key = ("cc_opus5", "cc-opus5-cli-v1", "concurrent", "live")
        g = s[key]
        self.assertEqual(g["n"], 3)
        self.assertEqual(g["n_contaminated"], 1)
        self.assertAlmostEqual(g["contamination_rate"], 1 / 3)
        # api clock is untouched by the contamination
        self.assertAlmostEqual(g["api_ms"]["p50"], 3_700.0)
        # the clean-only wall clock drops the contaminated row entirely
        self.assertEqual(g["clean_total_ms"]["n"], 2)
        self.assertAlmostEqual(g["clean_total_ms"]["p50"], 5_000.0)

    def test_summary_never_pools_across_run_context(self):
        """CONTEXT.md: run context is 'never pooled across values'. A replay
        row is the same arm answering a re-sent state on a quiet machine; its
        latency is not a live latency. This bit us for real -- the JEV-16
        determinism sweep appends `replay` rows to the same file while this
        report runs."""
        rows = [
            cc_row(run_context="live", total_ms=5_000.0,
                   duration_ms=4_000, duration_api_ms=3_700),
            cc_row(run_context="replay", total_ms=9_000.0,
                   duration_ms=8_000, duration_api_ms=7_700),
        ]
        s = latency.summarise(rows)
        keys = sorted(s)
        self.assertEqual(len(keys), 2, f"run_context was pooled: {keys}")
        contexts = {k[-1] for k in keys}
        self.assertEqual(contexts, {"live", "replay"})
        for key, g in s.items():
            self.assertEqual(g["n"], 1)
            self.assertEqual(g["run_context"], key[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
