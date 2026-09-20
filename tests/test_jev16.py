#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-16: the determinism instrument's own defects.

Three things are asserted here, all offline, all with the `fake` arm:

  1. `replay._emit` stamps `config_fingerprint`. Without it, replay rows do not
     join live rows, which `worker.py` has stamped since 2026-09-20.
  2. `replay.run_determinism` can SELECT its items -- by decision id and by the
     originating run context -- instead of slicing `store.captures()` in file
     order with every context pooled.
  3. `determinism.collect`/`analyse` do not pool repeat groups across
     `arm_config_id` or across the originating run context. Pooling either one
     reports a configuration change, or a difference between the balanced
     synthetic set and live traffic, as non-determinism.

A new file rather than an addition to `tests/test_pipeline.py`, which another
agent has open.
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

pyversion.require()

import canary  # noqa: E402
import config_loader as cl  # noqa: E402
import determinism  # noqa: E402
import paths  # noqa: E402
import replay  # noqa: E402
import state_builders as sb  # noqa: E402
import store  # noqa: E402
from arms.base import ArmConfig  # noqa: E402


def payload(command: str, session: str = "s1") -> dict:
    return {
        "session_id": session,
        "cwd": str(ROOT),
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": "d"},
        "permission_mode": "default",
    }


class Sandboxed(unittest.TestCase):
    """Point every writable path at a throwaway directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self._saved = {}
        for name in ("CAPTURES", "STATES", "RUNS", "LABELS", "DROPS", "REPORTS"):
            self._saved[name] = getattr(paths, name)
            target = base / name.lower()
            target.mkdir(parents=True, exist_ok=True)
            setattr(paths, name, target)

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(paths, name, value)
        self._tmp.cleanup()

    def fakes(self, *names):
        return [ArmConfig(name=n, arm_config_id=f"{n}-v1", kind="fake") for n in names]

    def seed_capture(self, decision_id: str, command: str, run_context: str) -> str:
        state = sb.build("pre_bash", payload(command))
        sha = sb.sha256(state)
        store.write_state(state, sha)
        store.append_capture({
            "decision_id": decision_id,
            "picked_at": store.utcnow(),
            "surface": "pre_bash",
            "session_id": "s1",
            "state_sha256": sha,
            "state_chars": len(state),
            "state_builder_version": sb.STATE_BUILDER_VERSION,
            "state_source": sb.STATE_SOURCE["pre_bash"],
            "run_context": run_context,
            "is_sidechain": False,
        })
        return sha


# --------------------------------------------------------------------------
# 1. the join key
# --------------------------------------------------------------------------

class ConfigFingerprint(Sandboxed):

    def test_emit_stamps_config_fingerprint_on_every_row(self):
        """worker.py stamps it; replay.py must too, or the streams cannot join."""
        expected = cl.config_fingerprint()["config_sha256"]
        state = sb.build("pre_bash", payload("ls"))
        import random
        replay._emit(
            decision_id="d1", surface="pre_bash", session_id="s1", state=state,
            questions=cl.questions_for("pre_bash"),
            qsid=cl.question_set_id("pre_bash"),
            arms=self.fakes("fake", "fake_b"),
            run_context="replay", rng=random.Random(1),
        )
        rows = list(store.runs())
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row.get("config_fingerprint"), expected)

    def test_replay_synthetic_capture_rows_carry_it_too(self):
        """The capture row is the join partner; worker stamps both halves."""
        expected = cl.config_fingerprint()["config_sha256"]
        replay.run_synthetic(self.fakes("fake"), "pre_bash", 2, __import__("random").Random(1))
        caps = list(store.captures())
        self.assertTrue(caps)
        for c in caps:
            self.assertEqual(c.get("config_fingerprint"), expected)

    def test_canary_capture_rows_carry_it_too(self):
        """The one authorised line in canary.py -- same reason, same field."""
        expected = cl.config_fingerprint()["config_sha256"]
        fixture = json.loads((paths.FIXTURES / "canary-set-v1.json").read_text())
        canary.run_sweep(fixture, self.fakes("fake"), __import__("random").Random(1))
        caps = list(store.captures())
        self.assertTrue(caps)
        for c in caps:
            self.assertEqual(c.get("config_fingerprint"), expected)


# --------------------------------------------------------------------------
# 2. selection
# --------------------------------------------------------------------------

class DeterminismSelection(Sandboxed):

    def test_ids_selects_exactly_the_requested_captures(self):
        for i, cmd in enumerate(["ls", "rm -rf /", "git status"]):
            self.seed_capture(f"d{i}", cmd, "synthetic")
        import random
        replay.run_determinism(self.fakes("fake"), "pre_bash", repeats=2, limit=50,
                               rng=random.Random(1), ids=["d2", "d0"])
        got = sorted({r["decision_id"] for r in store.runs()})
        self.assertEqual(got, ["d0", "d2"])
        self.assertEqual(len(list(store.runs())), 4)   # 2 items x 2 repeats x 1 arm

    def test_unknown_id_is_an_error_not_a_silent_skip(self):
        self.seed_capture("d0", "ls", "synthetic")
        import random
        with self.assertRaises(KeyError):
            replay.run_determinism(self.fakes("fake"), "pre_bash", repeats=1, limit=50,
                                   rng=random.Random(1), ids=["d0", "nope"])

    def test_context_filters_on_the_captures_origin(self):
        self.seed_capture("live1", "ls", "live")
        self.seed_capture("syn1", "rm -rf /", "synthetic")
        self.seed_capture("syn2", "git status", "synthetic")
        import random
        replay.run_determinism(self.fakes("fake"), "pre_bash", repeats=1, limit=50,
                               rng=random.Random(1), context="synthetic")
        got = sorted({r["decision_id"] for r in store.runs()})
        self.assertEqual(got, ["syn1", "syn2"])

    def test_seed_synthetic_materialises_without_spending(self):
        """The nine JEV-41 probe states are in the synthetic FILE and not in the
        store. Materialising them is a capture write and zero API calls."""
        ids = replay.seed_synthetic("pre_bash", ["syn-0000", "syn-0121"])
        self.assertEqual(ids, ["syn-syn-0000", "syn-syn-0121"])
        self.assertEqual(len(list(store.runs())), 0)
        caps = {c["decision_id"]: c for c in store.captures()}
        self.assertEqual(sorted(caps), ["syn-syn-0000", "syn-syn-0121"])
        items = {i["synthetic_id"]: i for i in
                 (json.loads(l) for l in
                  (paths.DATA / "synthetic" / "pre_bash-v1.jsonl").read_text().splitlines()
                  if l.strip())}
        for sid in ("syn-0000", "syn-0121"):
            want = sb.sha256(sb.build("pre_bash", items[sid]["payload"]))
            self.assertEqual(caps[f"syn-{sid}"]["state_sha256"], want)
            self.assertEqual(store.read_state(want),
                             sb.build("pre_bash", items[sid]["payload"]))

    def test_seeding_twice_does_not_duplicate_the_capture(self):
        replay.seed_synthetic("pre_bash", ["syn-0000"])
        replay.seed_synthetic("pre_bash", ["syn-0000"])
        self.assertEqual(len(list(store.captures())), 1)


# --------------------------------------------------------------------------
# 3. pooling
# --------------------------------------------------------------------------

class GroupKeying(Sandboxed):
    """`collect` and `analyse` must keep apart what the study keeps apart."""

    def emit_rows(self, decision_id, sha, arm, arm_config_id, probs):
        for p in probs:
            store.append_run({
                "decision_id": decision_id, "surface": "pre_bash", "arm": arm,
                "arm_config_id": arm_config_id, "ok": True,
                "question_set_id": cl.question_set_id("pre_bash"),
                "state_sha256": sha, "run_context": "replay",
                "sweep": "determinism",
                "answers": {"destructive": {"type": "boolean", "probability": p}},
            })

    def test_arm_config_id_is_part_of_the_group_key(self):
        """Two configurations of one arm on identical bytes are two groups. If
        they pool, a config change is reported as non-determinism -- which is
        exactly the conflation A7.5 is stuck in."""
        sha = self.seed_capture("d0", "rm -rf /", "synthetic")
        self.emit_rows("d0", sha, "cc_haiku45", "cc-haiku45-cli-v1", [0.85, 0.85, 0.85])
        self.emit_rows("d0", sha, "cc_haiku45", "cc-haiku45-cli-v2-nothink", [0.02, 0.02, 0.02])
        groups, _, _ = determinism.collect("pre_bash")
        self.assertEqual(len(groups), 2, "v1 and v2 pooled into one group")
        self.assertEqual({g.arm_config_id for g in groups},
                         {"cc-haiku45-cli-v1", "cc-haiku45-cli-v2-nothink"})
        for g in groups:
            self.assertEqual(g.spread, 0.0, "a pooled group fakes a 0.83 spread")

    def test_analyse_separates_arm_config_ids(self):
        sha = self.seed_capture("d0", "rm -rf /", "synthetic")
        self.emit_rows("d0", sha, "cc_haiku45", "cc-haiku45-cli-v1", [0.85, 0.85, 0.85])
        self.emit_rows("d0", sha, "cc_haiku45", "cc-haiku45-cli-v2-nothink", [0.02, 0.02, 0.02])
        groups, _, _ = determinism.collect("pre_bash")
        r = determinism.analyse(groups, "cc_haiku45", "destructive", 0.5,
                                arm_config_id="cc-haiku45-cli-v2-nothink",
                                origin="synthetic")
        self.assertEqual(r.n_groups, 1)
        self.assertEqual(r.groups[0].mean, 0.02)

    def test_analyse_separates_origin_contexts(self):
        """The occupancy half is keyed on run_context; the repeat half must be
        too. A live repeat group and a synthetic one are different workloads."""
        live_sha = self.seed_capture("live1", "ls", "live")
        syn_sha = self.seed_capture("syn1", "rm -rf /", "synthetic")
        self.emit_rows("live1", live_sha, "jev", "jev-gateway-v1", [0.10, 0.10, 0.10])
        self.emit_rows("syn1", syn_sha, "jev", "jev-gateway-v1", [0.96, 0.94, 0.96])
        groups, _, _ = determinism.collect("pre_bash")
        self.assertEqual({g.origin_context for g in groups}, {"live", "synthetic"})
        r = determinism.analyse(groups, "jev", "destructive", 0.95,
                                arm_config_id="jev-gateway-v1", origin="synthetic")
        self.assertEqual(r.n_groups, 1)
        self.assertEqual(r.groups[0].decision_id, "syn1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
