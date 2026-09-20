#!/usr/bin/env python3
"""Seam 2 (the arm interface) and seam 3 (analysis as pure functions).

Seam 2: a fake arm behind `evaluate(state, questions, config) -> Run` lets the
worker's orchestration, interleaving, randomisation, error handling and row
writing be exercised with zero API spend and zero flakiness.

Seam 3: the statistics are pure functions, so they are tested against inputs
whose answers are known by hand rather than by running the code and recording
what it happened to print.

Every test redirects the storage paths into a temp directory, so running the
suite never touches collected data.
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import analyze  # noqa: E402
import config_loader as cl  # noqa: E402
import paths  # noqa: E402
import state_builders as sb  # noqa: E402
import stats  # noqa: E402
import store  # noqa: E402
import worker  # noqa: E402
from arms.base import ArmConfig, Run, classify_exception  # noqa: E402


class TempStorage(unittest.TestCase):
    """Point every writable path at a throwaway directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self._saved = {}
        for name in ("CAPTURES", "STATES", "RUNS", "LABELS", "SPOOL", "SPOOL_READY", "SPOOL_TMP"):
            self._saved[name] = getattr(paths, name)
            target = base / name.lower()
            target.mkdir(parents=True, exist_ok=True)
            setattr(paths, name, target)

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(paths, name, value)
        self._tmp.cleanup()


def payload(command: str, session: str = "s1") -> dict:
    return {
        "session_id": session,
        "cwd": str(ROOT),
        "permission_mode": "auto",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


class TestStateBuilders(unittest.TestCase):
    def test_identical_payloads_hash_identically(self):
        a = sb.build("pre_bash", payload("ls -la"))
        b = sb.build("pre_bash", payload("ls -la"))
        self.assertEqual(sb.sha256(a), sb.sha256(b))

    def test_different_commands_hash_differently(self):
        a = sb.sha256(sb.build("pre_bash", payload("ls")))
        b = sb.sha256(sb.build("pre_bash", payload("rm -rf /")))
        self.assertNotEqual(a, b)

    def test_command_appears_verbatim(self):
        self.assertIn("git push --force", sb.build("pre_bash", payload("git push --force")))

    def test_missing_command_is_an_error_not_an_empty_state(self):
        with self.assertRaises(sb.StateBuildError):
            sb.build("pre_bash", {"tool_input": {}})

    def test_stop_refuses_to_read_the_transcript_tail(self):
        """The leakage guard: without a capture-time byte offset, refuse."""
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps({"message": {"role": "user", "content": "hi"}}) + "\n")
            path = fh.name
        with self.assertRaises(sb.StateBuildError):
            sb.build("stop", {"transcript_path": path})

    def test_stop_truncates_at_the_recorded_offset(self):
        lines = [
            json.dumps({"message": {"role": "user", "content": "please fix the bug"}}),
            json.dumps({"message": {"role": "assistant", "content": "done"}}),
            json.dumps({"message": {"role": "assistant", "content": "SECRET FUTURE TURN"}}),
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            prefix = lines[0] + "\n" + lines[1] + "\n"
            fh.write(prefix + lines[2] + "\n")
            path = fh.name
        state = sb.build("stop", {
            "transcript_path": path,
            "transcript_bytes_at_capture": len(prefix.encode()),
        })
        self.assertIn("please fix the bug", state)
        self.assertNotIn("SECRET FUTURE TURN", state)

    def test_truncation_keeps_the_end_and_marks_itself(self):
        state = sb._truncate("A" * 10 + "B" * 50, limit=20)
        self.assertTrue(state.startswith("[... earlier content truncated ...]"))
        self.assertTrue(state.endswith("B" * 20))


class TestQuestionSets(unittest.TestCase):
    def test_every_surface_resolves_every_phrasing(self):
        for surface in paths.SURFACES:
            spec = cl.question_set(surface)
            phrasings = set()
            for q in spec["questions"].values():
                phrasings |= set(q["phrasings"])
            for p in phrasings:
                resolved = cl.questions_for(surface, phrasing=p)
                self.assertEqual(set(resolved), set(spec["questions"]))
                for entry in resolved.values():
                    self.assertTrue(entry["instructions"].strip())

    def test_phrasings_are_distinct(self):
        """Paraphrases would make the sensitivity sweep measure nothing."""
        for surface in paths.SURFACES:
            for name, q in cl.question_set(surface)["questions"].items():
                texts = list(q["phrasings"].values())
                self.assertEqual(len(texts), len(set(texts)), f"{surface}:{name}")
                self.assertGreaterEqual(len(texts), 2, f"{surface}:{name}")

    def test_phrasing_is_part_of_the_replay_key(self):
        self.assertNotEqual(
            cl.question_set_id("pre_bash", phrasing="a"),
            cl.question_set_id("pre_bash", phrasing="b"),
        )

    def test_score_anchors_are_within_the_allowed_range(self):
        anchors = cl.question_set("post_edit")["questions"]["risk"]["anchors"]
        self.assertTrue(2 <= len(anchors) <= 10)


class TestCostModel(unittest.TestCase):
    def test_cache_multipliers_are_applied(self):
        usage = {"input_tokens": 0, "cache_creation_input_tokens": 1_000_000,
                 "cache_read_input_tokens": 1_000_000, "output_tokens": 0}
        cost = cl.cost_usd("claude-opus-5", usage)
        self.assertAlmostEqual(cost, 5.0 * 1.25 + 5.0 * 0.10, places=6)

    def test_jev_output_is_free(self):
        self.assertAlmostEqual(
            cl.cost_usd("typesafe-ai/jev", {"input_tokens": 1_000_000, "output_tokens": 999_999}),
            0.042, places=6,
        )

    def test_unknown_model_returns_none_rather_than_guessing(self):
        self.assertIsNone(cl.cost_usd("some-model-we-never-priced", {"input_tokens": 100}))

    def test_context_suffix_is_priced_separately(self):
        self.assertIn("claude-opus-5[1m]", cl.pricing()["models"])


class TestArmSeam(TempStorage):
    def test_fake_arm_is_deterministic(self):
        cfg = cl.arm("fake")
        q = cl.questions_for("pre_bash")
        a = worker.evaluate_one("same state", q, cfg)
        b = worker.evaluate_one("same state", q, cfg)
        self.assertEqual(a.answers, b.answers)

    def test_different_arms_disagree_sometimes(self):
        q = cl.questions_for("pre_bash")
        a = worker.evaluate_one("x", q, cl.arm("fake"))
        b = worker.evaluate_one("x", q, cl.arm("fake_b"))
        self.assertNotEqual(a.answers, b.answers)

    def test_a_failing_arm_becomes_a_row_not_an_exception(self):
        """Attrition must be measurable, so failures are recorded, never dropped."""
        broken = ArmConfig(name="broken", arm_config_id="broken-v1", kind="nonexistent-kind")
        run = worker.evaluate_one("state", cl.questions_for("pre_bash"), broken)
        self.assertFalse(run.ok)
        self.assertIsNotNone(run.error_kind)

    def test_error_classification(self):
        self.assertEqual(classify_exception(TimeoutError("timed out"))[0], "timeout")
        self.assertEqual(classify_exception(json.JSONDecodeError("x", "y", 0))[0], "malformed_response")


class TestWorkerOrchestration(TempStorage):
    def arms(self):
        return [cl.arm("fake"), cl.arm("fake_b"), cl.arm("fake_c")]

    def test_all_arms_see_byte_identical_state(self):
        worker.process_capture(payload("rm -rf build/"), "pre_bash", self.arms())
        rows = list(store.runs())
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r["state_sha256"] for r in rows}), 1)

    def test_state_hash_matches_the_stored_blob(self):
        worker.process_capture(payload("ls"), "pre_bash", self.arms())
        capture = next(iter(store.captures()))
        stored = store.read_state(capture["state_sha256"])
        self.assertEqual(sb.sha256(stored), capture["state_sha256"])

    def test_arm_order_is_randomised_across_decisions(self):
        import random
        seen = set()
        for i in range(40):
            worker.process_capture(
                payload(f"cmd {i}"), "pre_bash", self.arms(), rng=random.Random(i)
            )
        for row in store.runs():
            seen.add(tuple(row["arm_order"]))
        self.assertGreater(len(seen), 1, "arm order never varied; the confound survives")

    def test_every_row_carries_the_join_keys(self):
        worker.process_capture(payload("ls"), "pre_bash", self.arms())
        for row in store.runs():
            for key in ("decision_id", "surface", "session_id", "question_set_id",
                        "state_sha256", "arm", "arm_config_id", "pricing_version", "run_context"):
                self.assertIn(key, row)

    def test_capture_and_runs_join_on_decision_id(self):
        worker.process_capture(payload("ls"), "pre_bash", self.arms())
        captures = {c["decision_id"] for c in store.captures()}
        for row in store.runs():
            self.assertIn(row["decision_id"], captures)

    def test_identical_states_deduplicate_in_storage(self):
        for _ in range(5):
            worker.process_capture(payload("ls -la"), "pre_bash", self.arms())
        self.assertEqual(len(list(paths.STATES.glob("*.json"))), 1)
        self.assertEqual(len(list(store.captures())), 5)

    def test_storage_is_append_only(self):
        worker.process_capture(payload("a"), "pre_bash", self.arms())
        first = len(list(store.runs()))
        worker.process_capture(payload("b"), "pre_bash", self.arms())
        self.assertEqual(len(list(store.runs())), first * 2)

    def test_dry_run_writes_nothing(self):
        worker.process_capture(payload("ls"), "pre_bash", self.arms(), dry_run=True)
        self.assertEqual(list(store.runs()), [])
        self.assertEqual(list(store.captures()), [])

    def test_drain_removes_processed_spool_files(self):
        paths.SPOOL_READY.mkdir(parents=True, exist_ok=True)
        (paths.SPOOL_READY / "pre_bash__1.json").write_text(json.dumps(payload("ls")))
        n = worker.drain_once(self.arms(), verbose=False)
        self.assertEqual(n, 1)
        self.assertEqual(list(paths.SPOOL_READY.glob("*.json")), [])

    def test_unprocessable_capture_is_quarantined_not_deleted(self):
        paths.SPOOL_READY.mkdir(parents=True, exist_ok=True)
        (paths.SPOOL_READY / "pre_bash__bad.json").write_text("{not json")
        worker.drain_once(self.arms(), verbose=False)
        dead = list((paths.SPOOL / "dead").glob("*.json"))
        self.assertEqual(len(dead), 1)


class TestLiveArmWireFormats(unittest.TestCase):
    """The live arms' translation layers, tested offline.

    No network: these check the shapes we send and the shapes we accept, which
    is where a silent incompatibility between arms would otherwise hide.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        from arms import claude, jev
        self.jev, self.claude = jev, claude
        self.q = cl.questions_for("pre_bash")
        self.all_types = {
            "b": {"type": "boolean", "instructions": "is it?"},
            "c": {"type": "choice", "instructions": "which?", "options": {"x": "X", "y": "Y"}},
            "s": {"type": "score", "instructions": "how much?", "anchors": ["low", "mid", "high"]},
        }

    def test_jev_wire_uses_criteria_per_type(self):
        wire = self.jev.to_wire(self.all_types)
        self.assertNotIn("criteria", wire["b"])          # boolean needs none
        self.assertIsInstance(wire["c"]["criteria"], dict)   # choice: a record
        self.assertIsInstance(wire["s"]["criteria"], list)   # score: ordered array
        for entry in wire.values():
            self.assertIn("instructions", entry)

    def test_jev_rejects_out_of_range_score_anchors(self):
        with self.assertRaises(ValueError):
            self.jev.to_wire({"s": {"type": "score", "instructions": "x", "anchors": ["only one"]}})
        with self.assertRaises(ValueError):
            self.jev.to_wire({"s": {"type": "score", "instructions": "x",
                                    "anchors": [str(i) for i in range(11)]}})

    def test_jev_rejects_too_many_choice_options(self):
        with self.assertRaises(ValueError):
            self.jev.to_wire({"c": {"type": "choice", "instructions": "x",
                                    "options": {str(i): "" for i in range(256)}}})

    def test_jev_normalises_into_the_shared_answer_shape(self):
        raw = {
            "b": {"type": "boolean", "probability": 0.9},
            "c": {"type": "choice", "choice": "x", "probabilities": {"x": 0.7, "y": 0.3}},
            "s": {"type": "score", "score": 2, "probabilities": {"0": 0.2, "1": 0.6, "2": 0.2}},
        }
        out = self.jev.from_wire(raw, self.all_types)
        self.assertEqual(out["b"]["probability"], 0.9)
        self.assertEqual(out["c"]["choice"], "x")
        self.assertEqual(out["s"]["score"], 3.0)   # 0-indexed 2 -> 1-indexed 3

    def test_jev_reads_confidence_from_the_answer_itself(self):
        """Confirmed live: confidence sits directly on the answer, not under a
        per-answer providerMetadata. We were looking in the wrong place and
        silently discarding it on every call."""
        out = self.jev.from_wire(
            {"c": {"type": "choice", "choice": "x", "probabilities": {"x": 0.9, "y": 0.1},
                   "confidence": 0.92}},
            {"c": self.all_types["c"]},
        )
        self.assertEqual(out["c"]["confidence"], 0.92)

    def test_jev_omits_confidence_when_absent(self):
        """Absent for boolean questions, as documented and as observed live."""
        out = self.jev.from_wire({"b": {"type": "boolean", "probability": 0.5}},
                                 {"b": self.all_types["b"]})
        self.assertNotIn("confidence", out["b"])

    def test_jev_score_keeps_its_fractional_part(self):
        """Jev returns an expected value across the anchors -- 3.37, not 3.
        Casting to int would discard that and bias every score downward."""
        out = self.jev.from_wire(
            {"s": {"type": "score", "score": 2.37, "probabilities": {"0": 0.1, "1": 0.5, "2": 0.4}}},
            {"s": self.all_types["s"]},
        )
        self.assertAlmostEqual(out["s"]["score"], 3.37)      # 2.37 shifted onto the 1-n scale
        self.assertNotEqual(out["s"]["score"], int(out["s"]["score"]))

    def test_jev_score_is_shifted_onto_the_same_scale_as_the_claude_arms(self):
        """Jev is 0-indexed, our Claude schema is 1-indexed. Unshifted, an
        IDENTICAL judgement from two arms would differ by exactly one point on
        every item -- a uniform offset Spearman hides entirely and only
        Bland-Altman would catch."""
        out = self.jev.from_wire(
            {"s": {"type": "score", "score": 0.0, "probabilities": {"0": 1.0, "1": 0.0, "2": 0.0}}},
            {"s": self.all_types["s"]},
        )
        self.assertEqual(out["s"]["score"], 1.0)             # bottom anchor is 1, not 0
        self.assertEqual(sorted(out["s"]["probabilities"], key=int), ["1", "2", "3"])
        self.assertEqual(out["s"]["score_index_origin"], "jev_0_shifted_to_1")

    def test_jev_and_claude_score_scales_agree_at_both_ends(self):
        """The bottom and top anchors must mean the same number in both arms."""
        n = len(self.all_types["s"]["anchors"])
        claude_schema = self.claude.build_schema(self.all_types)["properties"]["s"]["properties"]
        self.assertEqual(claude_schema["score"]["minimum"], 1)
        self.assertEqual(claude_schema["score"]["maximum"], n)
        bottom = self.jev.from_wire(
            {"s": {"type": "score", "score": 0.0, "probabilities": {}}}, {"s": self.all_types["s"]})
        top = self.jev.from_wire(
            {"s": {"type": "score", "score": float(n - 1), "probabilities": {}}},
            {"s": self.all_types["s"]})
        self.assertEqual(bottom["s"]["score"], claude_schema["score"]["minimum"])
        self.assertEqual(top["s"]["score"], claude_schema["score"]["maximum"])

    def test_claude_boolean_schema_asks_for_a_probability_not_a_label(self):
        """If the baseline returned a bare label there would be no threshold
        sweep and no sharpness comparison to make."""
        schema = self.claude.build_schema(self.q)
        for name in self.q:
            props = schema["properties"][name]["properties"]
            self.assertIn("probability", props)
            self.assertEqual(props["probability"]["type"], "number")
            self.assertEqual((props["probability"]["minimum"], props["probability"]["maximum"]), (0, 1))

    def test_claude_schema_is_strict(self):
        schema = self.claude.build_schema(self.all_types)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(self.all_types))
        self.assertEqual(schema["properties"]["c"]["properties"]["choice"]["enum"], ["x", "y"])
        self.assertEqual(schema["properties"]["s"]["properties"]["score"]["maximum"], 3)

    def test_claude_prompt_includes_state_and_every_option(self):
        prompt = self.claude.build_prompt("SOME STATE", self.all_types)
        self.assertIn("SOME STATE", prompt)
        for fragment in ("x: X", "y: Y", "1: low", "3: high"):
            self.assertIn(fragment, prompt)

    def test_thinking_is_never_disabled_on_opus(self):
        """Documented failure mode: tool calls leak into visible text."""
        source = (ROOT / "src" / "arms" / "claude.py").read_text()
        self.assertNotIn('"type": "disabled"', source)
        self.assertNotIn("'type': 'disabled'", source)

    def test_both_arms_emit_the_same_answer_shape(self):
        """The analysis must never need to know which arm produced a row."""
        jev_out = self.jev.from_wire(
            {"b": {"type": "boolean", "probability": 0.4}}, {"b": self.all_types["b"]}
        )
        fake_out = worker.evaluate_one("s", {"b": self.all_types["b"]}, cl.arm("fake")).answers
        self.assertEqual(set(jev_out["b"]), set(fake_out["b"]))

    def test_live_arms_refuse_to_run_without_credentials(self):
        """Fail loudly and classifiably rather than silently sending nothing.

        Both the environment AND the .env file are hidden, because
        paths.require reads .env first. Popping only os.environ would make
        this test start spending money the moment the user fills in .env --
        the suite's zero-API-spend property has to hold after that, not just
        before it.
        """
        import os
        saved_env = os.environ.pop("AI_GATEWAY_API_KEY", None)
        saved_file = paths.ENV_FILE
        paths.ENV_FILE = Path(self._tmp.name) / "definitely-not-here.env"
        try:
            run = worker.evaluate_one("state", self.q, cl.arm("jev"))
            self.assertFalse(run.ok, "an arm with no credential must not report success")
            self.assertIsNotNone(run.error_kind)
            # A network error would mean we DID reach out. The only acceptable
            # outcome is refusing before the socket opens.
            self.assertNotIn(run.error_kind, ("account_gated", "auth", "rate_limit",
                                              "server_error", "client_error", "timeout"),
                             f"the arm contacted the network: {run.error_kind}")
        finally:
            paths.ENV_FILE = saved_file
            if saved_env is not None:
                os.environ["AI_GATEWAY_API_KEY"] = saved_env


class TestStatistics(unittest.TestCase):
    """Known answers, worked out by hand."""

    def test_perfect_and_chance_agreement(self):
        a = [True, False, True, False]
        self.assertEqual(stats.cohens_kappa(a, a), 1.0)
        self.assertEqual(stats.raw_agreement(a, a), 1.0)
        # 2x2 with both raters 50/50 and half the cells: po = pe = 0.5, kappa = 0
        self.assertAlmostEqual(
            stats.cohens_kappa([True, True, False, False], [True, False, True, False]), 0.0
        )

    def test_total_disagreement_is_negative_kappa(self):
        self.assertLess(stats.cohens_kappa([True, False], [False, True]), 0.0)

    def test_pabak_is_two_po_minus_one(self):
        a = [True] * 8 + [False] * 2
        b = [True] * 10
        self.assertAlmostEqual(stats.pabak(a, b), 2 * 0.8 - 1)

    def test_skewed_base_rate_splits_kappa_from_raw_agreement(self):
        """The exact failure mode the report is built to expose."""
        a = [False] * 97 + [True] * 3
        b = [False] * 100
        self.assertAlmostEqual(stats.raw_agreement(a, b), 0.97)
        self.assertEqual(stats.majority_baseline(b), 1.0)   # a constant 'no' beats the arm
        self.assertLessEqual(stats.cohens_kappa(a, b), 0.0)

    def test_both_raters_constant_makes_kappa_undefined_not_perfect(self):
        self.assertTrue(math.isnan(stats.cohens_kappa([True] * 10, [True] * 10)))
        self.assertEqual(stats.pabak([True] * 10, [True] * 10), 1.0)

    def test_confusion_counts_sum_to_n(self):
        a = [True, True, False, False, True]
        b = [True, False, False, False, True]
        cm = stats.confusion(a, b)
        self.assertEqual(sum(cm.values()), 5)
        self.assertEqual(cm["tt"], 2)
        self.assertEqual(cm["ff"], 2)
        self.assertEqual(cm["tf"], 1)

    def test_quadratic_weighted_kappa_penalises_distance(self):
        near = stats.quadratic_weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 4], 5)
        far = stats.quadratic_weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 1], 5)
        self.assertGreater(near, far)

    def test_spearman_endpoints(self):
        self.assertEqual(stats.spearman_rho([1, 2, 3, 4], [1, 2, 3, 4]), 1.0)
        self.assertEqual(stats.spearman_rho([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)

    def test_quantiles_are_not_means(self):
        values = [1.0] * 99 + [1000.0]
        q = stats.quantiles(values, [0.5, 0.99])
        self.assertEqual(q["p50"], 1.0)
        self.assertEqual(q["p99"], 1.0)
        self.assertEqual(stats.quantiles(values, [1.0])["p100"], 1000.0)

    def test_entropy_is_zero_when_decisive_and_one_when_hedging(self):
        self.assertAlmostEqual(stats.entropy_bits([0.0, 1.0]), 0.0)
        self.assertAlmostEqual(stats.entropy_bits([0.5, 0.5]), 1.0)

    def test_clustered_intervals_are_wider_than_naive_ones(self):
        """The whole reason for clustering: eleven identical decisions in one
        session are one observation, not eleven."""
        a, b, clusters = [], [], []
        for session in range(10):
            agree = session < 8
            for _ in range(11):
                a.append(True)
                b.append(agree)
                clusters.append(f"session-{session}")

        def stat(idx):
            return stats.pabak([a[i] for i in idx], [b[i] for i in idx])

        clustered = stats.clustered_bootstrap(clusters, stat, n_resamples=500)
        naive = stats.naive_bootstrap(len(a), stat, n_resamples=500)
        self.assertAlmostEqual(clustered.point, naive.point)
        self.assertGreater(clustered.hi - clustered.lo, naive.hi - naive.lo)
        self.assertEqual(clustered.n_clusters, 10)

    def test_bootstrap_is_seeded_and_reproducible(self):
        clusters = [f"s{i % 5}" for i in range(50)]
        values = [i % 3 == 0 for i in range(50)]

        def stat(idx):
            return sum(values[i] for i in idx) / len(idx)

        first = stats.clustered_bootstrap(clusters, stat, n_resamples=200)
        second = stats.clustered_bootstrap(clusters, stat, n_resamples=200)
        self.assertEqual((first.lo, first.hi), (second.lo, second.hi))


class TestDiscrimination(unittest.TestCase):
    def test_auc_is_one_when_perfectly_separable(self):
        self.assertEqual(stats.auc([0.9, 0.8, 0.7], [0.3, 0.2, 0.1]), 1.0)

    def test_auc_is_zero_when_perfectly_inverted(self):
        self.assertEqual(stats.auc([0.1, 0.2], [0.8, 0.9]), 0.0)

    def test_auc_is_a_half_for_a_coin_flip(self):
        """Identical distributions must read 0.5, not something flattering."""
        self.assertAlmostEqual(stats.auc([0.5] * 50, [0.5] * 50), 0.5)

    def test_auc_handles_ties_via_mid_ranks(self):
        """pos={0.6,0.5}, neg={0.5,0.4}: of the four pairs, three are wins and
        one is a tie, so 3.5/4 = 0.875. A tie must count half, not zero."""
        self.assertAlmostEqual(stats.auc([0.6, 0.5], [0.5, 0.4]), 0.875)

    def test_auc_is_nan_without_both_classes(self):
        self.assertTrue(math.isnan(stats.auc([0.9, 0.8], [])))

    def test_youden_finds_the_separating_threshold(self):
        tau, j = stats.youden_threshold([0.9, 0.85, 0.8], [0.2, 0.15, 0.1])
        self.assertAlmostEqual(j, 1.0)
        self.assertGreater(tau, 0.2)
        self.assertLessEqual(tau, 0.8)

    def test_roc_curve_is_monotone_in_threshold(self):
        curve = stats.roc_curve([0.9, 0.7, 0.5], [0.4, 0.2, 0.1])
        tprs = [tpr for _, tpr, _ in curve]
        self.assertEqual(tprs, sorted(tprs))


class TestSyntheticSet(unittest.TestCase):
    def test_strata_are_balanced_and_populated(self):
        path = paths.DATA / "synthetic" / "pre_bash-v1.jsonl"
        if not path.exists():
            self.skipTest("synthetic set not built")
        items = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        counts = {}
        for item in items:
            counts[item["stratum"]] = counts.get(item["stratum"], 0) + 1
        self.assertEqual(set(counts), {"destructive", "borderline", "benign"})
        self.assertGreaterEqual(min(counts.values()), 100,
                                "minority class too small for a tight interval")

    def test_labeller_notes_never_reach_an_arm(self):
        """The note is for a human in Phase 2. Leaking it into state would
        hand every arm the answer."""
        path = paths.DATA / "synthetic" / "pre_bash-v1.jsonl"
        if not path.exists():
            self.skipTest("synthetic set not built")
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            state = sb.build("pre_bash", item["payload"])
            self.assertNotIn(item["labeller_note"], state)
            self.assertNotIn(item["stratum"], state)

    def test_every_item_builds_a_state(self):
        path = paths.DATA / "synthetic" / "pre_bash-v1.jsonl"
        if not path.exists():
            self.skipTest("synthetic set not built")
        for line in path.read_text().splitlines():
            if line.strip():
                self.assertTrue(sb.build("pre_bash", json.loads(line)["payload"]))


class TestReport(TempStorage):
    def populate(self, n=12):
        for i in range(n):
            worker.process_capture(
                payload(f"command number {i}", session=f"s{i % 3}"),
                "pre_bash",
                [cl.arm("fake"), cl.arm("fake_b")],
            )

    def test_report_runs_end_to_end(self):
        self.populate()
        text = analyze.report(reference="fake")
        self.assertIn("SURFACE: pre_bash", text)
        self.assertIn("majority-class baseline", text)
        self.assertIn("PABAK", text)

    def test_report_never_says_accuracy(self):
        self.populate()
        lowered = analyze.report(reference="fake").lower()
        for banned in analyze.BANNED:
            self.assertNotIn(banned, lowered)

    def test_report_prints_the_base_rate_beside_agreement(self):
        self.populate()
        text = analyze.report(reference="fake")
        self.assertIn("base rate of", text)

    def test_state_identity_violation_is_reported_loudly(self):
        self.populate(2)
        rogue = next(iter(store.runs()))
        rogue["state_sha256"] = "0" * 64
        store.append_run(rogue)
        text = analyze.report(reference="fake")
        self.assertIn("STATE IDENTITY VIOLATED", text)

    def test_report_survives_an_empty_dataset(self):
        self.assertIn("JEV SHADOW-MODE REPORT", analyze.report(reference="fake"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
