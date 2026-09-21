#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Worker lifecycle: the kill switch, graceful stop, and the claim reap.

JEV-51 and JEV-31. Both tickets are about the same window — the moment between
`candidate.rename(claimed/)` and `spooled.unlink()` — from two sides:

  JEV-51  nothing should ENTER that window while the kill switch is set, and a
          stop signal must not land INSIDE it and abandon the file.
  JEV-31  anything already stranded in that window by a previous crash must
          come back out, with its retry count visible, and a payload that keeps
          killing the worker must terminate rather than loop.

Every test here is offline. The only arm is the `fake` arm, and in the
subprocess tests its `evaluate` is replaced by a sleeper. There is no network,
no `claude -p`, and no spend.

SANDBOXING, INCLUDING THE KILL SWITCH
-------------------------------------
`tests/test_pipeline.py:TempStorage` repoints the storage paths but NOT
`paths.KILL_SWITCH`. That was harmless while nothing in the worker read the
switch. It is not harmless now: the live `.jev-disabled` is present during
Phase A, so a kill-switch test that forgot to repoint it would "pass" against
the real switch while proving nothing, and would go on passing after the fix
was reverted. Every test below repoints it and every kill-switch assertion is
paired with a CONTROL in which the switch is absent.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT / "src"))

import pyversion  # noqa: E402

# JEV-44: assert the floor BEFORE importing anything that does not parse below
# it. The PEP-723 header above binds `uv run` only; `python3 tests/<this file>`
# ignores it entirely.
pyversion.require()

import config_loader as cl  # noqa: E402
import paths  # noqa: E402
import worker  # noqa: E402
from arms import fake  # noqa: E402


def payload(command: str = "ls -la", session: str = "s1") -> dict:
    return {
        "session_id": session,
        "cwd": str(ROOT),
        "permission_mode": "auto",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


class Sandbox(unittest.TestCase):
    """A throwaway root, laid out exactly as the live one is.

    `claimed/` and `dead/` are placed UNDER `spool/`, matching the live tree.
    `TempStorage` in test_pipeline puts them at `base/spool_claimed` while
    `worker.drain_once` reached them as `paths.SPOOL / "claimed"` — two
    different directories in the sandbox and one in production, which is
    precisely the shape of bug that lets a reap test pass without reaping
    anything.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self._saved = {}

        def point(name, value):
            self._saved[name] = getattr(paths, name)
            setattr(paths, name, value)

        spool = self.base / "spool"
        data = self.base / "data"
        point("SPOOL", spool)
        point("SPOOL_TMP", spool / "tmp")
        point("SPOOL_READY", spool / "ready")
        point("SPOOL_CLAIMED", spool / "claimed")
        point("SPOOL_DEAD", spool / "dead")
        point("DATA", data)
        point("CAPTURES", data / "captures")
        point("STATES", data / "states")
        point("RUNS", data / "runs")
        point("LABELS", data / "labels")
        point("DROPS", data / "drops")
        point("SPOOL_WATERMARK", data / "spool_watermark.json")
        point("LOGS", self.base / "logs")
        point("KILL_SWITCH", self.base / ".jev-disabled")
        for d in (paths.SPOOL_TMP, paths.SPOOL_READY, paths.SPOOL_CLAIMED,
                  paths.SPOOL_DEAD, paths.CAPTURES, paths.STATES, paths.RUNS,
                  paths.LABELS, paths.DROPS, paths.LOGS):
            d.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._restore)

    def _restore(self):
        for name, value in self._saved.items():
            setattr(paths, name, value)

    def arms(self):
        return [cl.arm("fake")]

    def seed_ready(self, n: int, prefix: str = "pre_bash") -> list[Path]:
        out = []
        for i in range(n):
            p = paths.SPOOL_READY / f"{prefix}__9{i}-{i}.json"
            p.write_text(json.dumps(payload(f"echo {i}")), encoding="utf-8")
            out.append(p)
        return out

    def count_arm_calls(self):
        """Replace the fake arm's evaluate with a counter.

        `worker.evaluate_one` reaches the arm as
        `load_arm_module(config.kind).evaluate`, so patching the module
        attribute is what the worker actually calls. Patching
        `worker.evaluate_one` instead would count the wrapper, not the arm, and
        would still count a call the kill switch was supposed to prevent.
        """
        calls = []
        real = fake.evaluate

        def counting(state, questions, config):
            calls.append(config.name)
            return real(state, questions, config)

        fake.evaluate = counting
        self.addCleanup(lambda: setattr(fake, "evaluate", real))
        return calls


# ---------------------------------------------------------------------------
# JEV-51 (1): the kill switch stops SPENDING, not merely recording
# ---------------------------------------------------------------------------

class TestKillSwitchStopsDispatch(Sandbox):
    def test_control_switch_absent_the_arms_are_called(self):
        """The control. Without it, the assertion below could pass because the
        drain is broken rather than because the switch works."""
        calls = self.count_arm_calls()
        self.seed_ready(3)
        n = worker.drain_once(self.arms(), verbose=False)
        self.assertEqual(n, 3)
        self.assertEqual(len(calls), 3)

    def test_switch_engaged_and_spool_non_empty_means_zero_arm_calls(self):
        """JEV-51's headline criterion, counted rather than inspected."""
        calls = self.count_arm_calls()
        self.seed_ready(3)
        paths.KILL_SWITCH.touch()
        n = worker.drain_once(self.arms(), verbose=False)
        self.assertEqual(calls, [], "kill switch engaged but an arm was invoked")
        self.assertEqual(n, 0)

    def test_switch_engaged_leaves_the_spool_exactly_where_it_was(self):
        """Disabled must mean quiescent, not destructive: nothing claimed,
        nothing quarantined, nothing drained."""
        self.seed_ready(3)
        paths.KILL_SWITCH.touch()
        worker.drain_once(self.arms(), verbose=False)
        self.assertEqual(len(list(paths.SPOOL_READY.glob("*.json"))), 3)
        self.assertEqual(list(paths.SPOOL_CLAIMED.glob("*.json")), [])
        self.assertEqual(list(paths.SPOOL_DEAD.glob("*.json")), [])

    def test_a_switch_appearing_mid_drain_stops_the_next_claim(self):
        """The switch is re-read before EVERY claim, not once per cycle: a
        30s poll interval would otherwise keep spending for up to 30s after
        the operator believed they had stopped it."""
        calls = self.count_arm_calls()
        self.seed_ready(4)
        real = fake.evaluate

        def arm_then_kill(state, questions, config):
            paths.KILL_SWITCH.touch()
            return real(state, questions, config)

        fake.evaluate = arm_then_kill
        worker.drain_once(self.arms(), verbose=False)
        self.assertEqual(len(calls), 1, "kept dispatching after the switch was set")
        self.assertEqual(len(list(paths.SPOOL_READY.glob("*.json"))), 3)
        self.assertEqual(list(paths.SPOOL_CLAIMED.glob("*.json")), [])

    def test_the_switch_is_fail_safe_here_too(self):
        """JEV-40's rule: ANY entry at the path means OFF. A directory is the
        case an operator creates with `mkdir` instead of `touch`."""
        calls = self.count_arm_calls()
        self.seed_ready(1)
        paths.KILL_SWITCH.mkdir()
        worker.drain_once(self.arms(), verbose=False)
        self.assertEqual(calls, [])


class TestConfigStalenessStrandsNothing(Sandbox):
    """The OTHER uncaught exit, found while fixing the signal one (JEV-30/51).

    `cl.surface_mode()` reaches `surfaces()`, which calls
    `assert_config_fresh()`. A config edit underneath a running worker is a
    deliberate hard refusal -- config is pinned per process on purpose. But the
    refusal used to fire from *after* `candidate.rename()` and *outside* the
    `try:` wrapping `process_capture`, so it propagated past a poll loop that
    caught only `KeyboardInterrupt` and killed the process **with a file
    stranded in claimed/**. That is precisely the failure JEV-51 is about,
    arriving by a second route.

    A refusal must cost nothing: it fires before anything leaves `ready/`.
    """

    def test_a_stale_config_refusal_leaves_the_spool_untouched(self):
        self.seed_ready(3)
        calls = self.count_arm_calls()
        real_mode = cl.surface_mode

        def stale(surface):
            raise cl.ConfigStaleError("config changed after this process loaded it")

        cl.surface_mode = stale
        self.addCleanup(lambda: setattr(cl, "surface_mode", real_mode))

        with self.assertRaises(cl.ConfigStaleError):
            worker.drain_once(self.arms(), verbose=False)

        self.assertEqual(len(list(paths.SPOOL_READY.glob("*.json"))), 3,
                         "a config refusal must not consume a capture")
        self.assertEqual(list(paths.SPOOL_CLAIMED.glob("*.json")), [],
                         "a config refusal stranded a claim")
        self.assertEqual(list(paths.SPOOL_DEAD.glob("*.json")), [])
        self.assertEqual(calls, [], "arms were called before the refusal")

    def test_the_config_fingerprint_is_resolved_once_before_dispatch(self):
        """If the fingerprint were read per row, a config edit landing during a
        dispatch would raise INSIDE the row-writing loop, be swallowed by
        `except Exception`, and quarantine a perfectly good capture to `dead/`
        — after every arm call had already been paid for. Resolving it once,
        beside the question version and before `_dispatch`, means a row
        honestly carries the config that was in force when it ran."""
        seen = []
        real_fp = cl.config_fingerprint

        def counting():
            seen.append(1)
            return real_fp()

        cl.config_fingerprint = counting
        self.addCleanup(lambda: setattr(cl, "config_fingerprint", real_fp))

        arms = [cl.arm("fake"), cl.arm("fake_b"), cl.arm("fake_c")]
        worker.process_capture(payload("ls"), "pre_bash", arms)
        self.assertEqual(len(seen), 1,
                         f"config_fingerprint called {len(seen)}x for one capture")

    def test_both_row_streams_carry_the_same_fingerprint(self):
        """JEV-30's join key is worthless if the capture row and its run rows
        can disagree."""
        import store
        worker.process_capture(payload("ls"), "pre_bash", self.arms())
        caps = list(store.captures())
        runs = list(store.runs())
        self.assertEqual(len(caps), 1)
        self.assertTrue(runs)
        fp = caps[0]["config_fingerprint"]
        self.assertTrue(fp)
        for r in runs:
            self.assertEqual(r["config_fingerprint"], fp)


# ---------------------------------------------------------------------------
# JEV-51 (2,3): SIGTERM / SIGINT mid-dispatch strand nothing
# ---------------------------------------------------------------------------

class TestGracefulStop(unittest.TestCase):
    """Real process, real signal. See tests/worker_driver.py for the sandbox."""

    DISPATCH_SECONDS = 3.0

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sandbox = Path(self._tmp.name)
        self.ready = self.sandbox / "spool" / "ready"
        self.claimed = self.sandbox / "spool" / "claimed"
        self.ready.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            (self.ready / f"pre_bash__8{i}-{i}.json").write_text(
                json.dumps(payload(f"echo {i}")), encoding="utf-8")

    def _start(self, ignore_sigint=False):
        # `ignore_sigint` reproduces the condition JEV-51 actually names: the
        # worker is launched as a BACKGROUND JOB, and the shell sets SIGINT to
        # SIG_IGN for background jobs, which Python inherits. Without this the
        # SIGINT test would run against the default disposition and would not
        # be testing the claim at all.
        pre = (lambda: signal.signal(signal.SIGINT, signal.SIG_IGN)) if ignore_sigint else None
        proc = subprocess.Popen(
            [sys.executable, str(TESTS / "worker_driver.py"),
             "--sandbox", str(self.sandbox),
             "--dispatch-seconds", str(self.DISPATCH_SECONDS),
             "--interval", "0.2"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            preexec_fn=pre)
        self.addCleanup(self._hard_kill, proc)
        return proc

    def _hard_kill(self, proc):
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)

    def _wait_for_dispatch(self, proc, timeout=20.0):
        sentinel = self.sandbox / "dispatch_started"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if sentinel.exists():
                return
            if proc.poll() is not None:
                self.fail(f"driver exited early:\n{proc.stdout.read()}")
            time.sleep(0.05)
        self.fail("the driver never reached a dispatch")

    def _signal_mid_dispatch(self, sig, ignore_sigint=False):
        proc = self._start(ignore_sigint=ignore_sigint)
        self._wait_for_dispatch(proc)
        # Comfortably inside the 3s dispatch, comfortably after it started.
        time.sleep(0.4)
        os.kill(proc.pid, sig)
        try:
            out = proc.communicate(timeout=60)[0]
        except subprocess.TimeoutExpired:
            proc.kill()
            self.fail("worker did not exit within 60s of the signal")
        return proc.returncode, out

    def test_sigterm_mid_dispatch_exits_zero_and_strands_no_claim(self):
        """JEV-51's second named criterion. `run-collection.sh stop` sends
        exactly this signal, and today it lands on the default disposition."""
        rc, out = self._signal_mid_dispatch(signal.SIGTERM)
        self.assertEqual(rc, 0, f"SIGTERM did not exit cleanly (rc={rc}):\n{out}")
        stranded = sorted(p.name for p in self.claimed.glob("*.json"))
        self.assertEqual(stranded, [], f"stranded claim after SIGTERM: {stranded}\n{out}")

    def test_sigint_mid_dispatch_exits_zero_and_strands_no_claim(self):
        """SIGINT gets an explicit handler rather than relying on
        `KeyboardInterrupt`: under `nohup ... &` the shell sets SIGINT to
        SIG_IGN, so the `except KeyboardInterrupt` that was the worker's only
        graceful exit is unreachable in the way it is actually run."""
        rc, out = self._signal_mid_dispatch(signal.SIGINT, ignore_sigint=True)
        self.assertEqual(rc, 0, f"SIGINT did not exit cleanly (rc={rc}):\n{out}")
        stranded = sorted(p.name for p in self.claimed.glob("*.json"))
        self.assertEqual(stranded, [], f"stranded claim after SIGINT: {stranded}\n{out}")

    def test_the_in_flight_capture_is_finished_not_abandoned(self):
        """Graceful means the capture in flight is completed and written, and
        the ones not yet claimed are left in ready/ for the next worker."""
        rc, out = self._signal_mid_dispatch(signal.SIGTERM)
        self.assertEqual(rc, 0, out)
        runs = list((self.sandbox / "data" / "runs").glob("*.jsonl"))
        rows = [json.loads(line) for f in runs
                for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(rows), 1, f"expected the in-flight capture to complete:\n{out}")
        left = sorted(p.name for p in self.ready.glob("*.json"))
        self.assertEqual(len(left), 2, f"unclaimed captures were not left in ready/: {left}")


# ---------------------------------------------------------------------------
# JEV-31: the claim marker and the startup reap
# ---------------------------------------------------------------------------

class TestClaimMarker(Sandbox):
    def test_a_claim_records_the_worker_pid_not_the_hook_pid(self):
        """The defect under JEV-31's reap design: the number in
        `pre_bash__2474-20808.json` is `capture.sh`'s `$$`. No owning pid was
        ever written down, so 'is the owner alive' could not be asked."""
        seen = {}
        real = fake.evaluate

        def peek(state, questions, config):
            for p in paths.SPOOL_CLAIMED.glob("*.json"):
                seen["name"] = p.name
            return real(state, questions, config)

        fake.evaluate = peek
        self.addCleanup(lambda: setattr(fake, "evaluate", real))
        self.seed_ready(1)
        worker.drain_once(self.arms(), verbose=False)
        self.assertIn("name", seen, "nothing was ever in claimed/")
        parsed = worker.parse_claim(seen["name"])
        self.assertIsNotNone(parsed, f"claim name is not parseable: {seen['name']}")
        self.assertEqual(parsed["pid"], os.getpid())
        self.assertEqual(parsed["retries"], 0)
        self.assertEqual(seen["name"].split("__", 1)[0], "pre_bash",
                         "the surface must still parse off the front of the name")

    def test_the_claim_is_removed_on_success(self):
        self.seed_ready(2)
        worker.drain_once(self.arms(), verbose=False)
        self.assertEqual(list(paths.SPOOL_CLAIMED.glob("*.json")), [])


class TestReap(Sandbox):
    def _claim(self, base="pre_bash__71-1", pid=None, retries=0, when=None):
        name = worker.claim_name(base, pid=pid if pid is not None else os.getpid(),
                                 claimed_at=when or int(time.time()), retries=retries)
        p = paths.SPOOL_CLAIMED / name
        p.write_text(json.dumps(payload()), encoding="utf-8")
        return p

    @staticmethod
    def _dead_pid() -> int:
        """A pid that is definitely not alive: spawn a process and reap it."""
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

    def test_a_claim_owned_by_a_dead_pid_returns_to_ready(self):
        self._claim(pid=self._dead_pid())
        reaped = worker.reap_claimed(verbose=False)
        self.assertEqual(reaped, 1)
        self.assertEqual(list(paths.SPOOL_CLAIMED.glob("*.json")), [])
        back = list(paths.SPOOL_READY.glob("*.json"))
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0].name.split("__", 1)[0], "pre_bash")

    def test_a_reclaimed_capture_is_distinguishable_from_a_first_claim(self):
        """JEV-31: 'or a poison payload loops forever'. The retry counter has
        to survive the round trip through ready/, not just the reap."""
        self._claim(pid=self._dead_pid())
        worker.reap_claimed(verbose=False)
        back = list(paths.SPOOL_READY.glob("*.json"))[0]
        self.assertEqual(worker.ready_retries(back.name), 1)

    def test_a_claim_owned_by_a_LIVE_pid_is_never_reaped_at_any_age(self):
        """The race the reap design is built around: reaping a live claim
        produces two full sets of well-formed rows under two decision_ids
        sharing one state_sha256 — inflation, which the section 5 assertion
        cannot see and the clustered bootstrap must not be fed."""
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        # Deliberately ancient: age alone must never be sufficient.
        self._claim(pid=proc.pid, when=int(time.time()) - 86400)
        self.assertEqual(worker.reap_claimed(verbose=False), 0)
        self.assertEqual(len(list(paths.SPOOL_CLAIMED.glob("*.json"))), 1)
        self.assertEqual(list(paths.SPOOL_READY.glob("*.json")), [])

    def test_our_own_claim_is_never_reaped(self):
        self._claim(pid=os.getpid())
        self.assertEqual(worker.reap_claimed(verbose=False), 0)
        self.assertEqual(len(list(paths.SPOOL_CLAIMED.glob("*.json"))), 1)

    def test_a_legacy_unmarked_claim_is_reaped_unconditionally(self):
        """Every file stranded before this fix carries the HOOK's pid and no
        marker. It must not be gated on age: `rename()` preserves mtime, so a
        capture that waited in a deep backlog is claimed already looking old,
        and the legacy file that the very restart shipping this fix creates
        would otherwise survive until the restart after next."""
        legacy = paths.SPOOL_CLAIMED / "pre_bash__2474-20808.json"
        legacy.write_text(json.dumps(payload()), encoding="utf-8")
        self.assertEqual(worker.reap_claimed(verbose=False), 1)
        back = list(paths.SPOOL_READY.glob("*.json"))
        self.assertEqual(len(back), 1)
        self.assertEqual(worker.ready_retries(back[0].name), 1)

    def test_retries_are_capped_and_the_payload_is_quarantined_with_a_reason(self):
        """'Cap the retries and quarantine after N, so a payload that kills
        the worker cannot resurrect itself indefinitely.'"""
        self._claim(pid=self._dead_pid(), retries=worker.MAX_CLAIM_RETRIES - 1)
        worker.reap_claimed(verbose=False)
        self.assertEqual(list(paths.SPOOL_READY.glob("*.json")), [])
        dead = list(paths.SPOOL_DEAD.glob("*.json"))
        self.assertEqual(len(dead), 1)
        reason = (paths.SPOOL_DEAD / f"{dead[0].name}.reason").read_text(encoding="utf-8")
        self.assertIn("reap", reason.lower())
        self.assertIn(str(worker.MAX_CLAIM_RETRIES), reason)

    def test_a_poison_payload_terminates_rather_than_looping(self):
        """End to end: reap, re-claim, reap, ... must reach dead/ in bounded
        time. The counter is what makes that true."""
        self._claim(pid=self._dead_pid())
        for _ in range(worker.MAX_CLAIM_RETRIES + 2):
            worker.reap_claimed(verbose=False)
            for f in paths.SPOOL_READY.glob("*.json"):
                f.rename(paths.SPOOL_CLAIMED / worker.claim_name(
                    f.stem, pid=self._dead_pid(),
                    claimed_at=int(time.time()),
                    retries=worker.ready_retries(f.name)))
        self.assertEqual(list(paths.SPOOL_READY.glob("*.json")), [])
        self.assertEqual(list(paths.SPOOL_CLAIMED.glob("*.json")), [])
        self.assertEqual(len(list(paths.SPOOL_DEAD.glob("*.json"))), 1)

    def test_the_reap_does_not_run_inside_the_drain_loop(self):
        """Mitigation two for the inflation race: the reap happens at startup
        only, before anything in this process is in flight. A drain cycle does
        a read-only count and reaps nothing."""
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        self._claim(pid=self._dead_pid())
        worker.drain_once(self.arms(), verbose=False)
        self.assertEqual(len(list(paths.SPOOL_CLAIMED.glob("*.json"))), 1,
                         "drain_once reaped; the reap must be startup-only")


class TestReapAtStartup(unittest.TestCase):
    """The reap has to be wired into `main()`, not merely to exist."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sandbox = Path(self._tmp.name)
        (self.sandbox / "spool" / "claimed").mkdir(parents=True)
        (self.sandbox / "spool" / "ready").mkdir(parents=True)
        (self.sandbox / "spool" / "claimed" / "pre_bash__2474-20808.json").write_text(
            json.dumps(payload()), encoding="utf-8")

    def test_a_stranded_claim_is_recovered_and_drained_by_a_fresh_worker(self):
        proc = subprocess.Popen(
            [sys.executable, str(TESTS / "worker_driver.py"),
             "--sandbox", str(self.sandbox), "--dispatch-seconds", "0",
             "--interval", "0.2"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(lambda: (proc.kill(), proc.wait(timeout=10))
                        if proc.poll() is None else None)
        deadline = time.time() + 30
        runs_dir = self.sandbox / "data" / "runs"
        while time.time() < deadline:
            if any(runs_dir.glob("*.jsonl")):
                break
            time.sleep(0.1)
        os.kill(proc.pid, signal.SIGTERM)
        out = proc.communicate(timeout=60)[0]
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("reap", out.lower(), f"the reap was not reported:\n{out}")
        rows = [line for f in runs_dir.glob("*.jsonl")
                for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(rows), 1, f"the stranded capture was not drained:\n{out}")
        self.assertEqual(list((self.sandbox / "spool" / "claimed").glob("*.json")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
