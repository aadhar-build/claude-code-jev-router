#!/usr/bin/env python3
"""Run the REAL `worker.main()` loop in a subprocess, against a SANDBOX root.

This exists for one reason: JEV-51's acceptance criterion is *"a test that
SIGTERMs a worker mid-dispatch and asserts no stranded claim"*, and a signal
disposition cannot be tested in-process. It needs a real process, a real
`worker.main()`, and a real `kill`.

It is NOT "starting the worker" in the sense the collection window means:

  * every writable path is repointed into a throwaway sandbox BEFORE `worker`
    is imported, exactly as `tests/gate4_drain.py` does, so the live `spool/`,
    `data/` and `logs/` are never opened;
  * `paths.KILL_SWITCH` is repointed too, so the live `.jev-disabled` neither
    silences this driver nor is touched by it;
  * the only arm is the offline `fake` arm, and its `evaluate` is replaced here
    by one that writes a sentinel and sleeps. No network, no subprocess, no
    spend, no `claude -p`.

Usage:
  worker_driver.py --sandbox DIR [--dispatch-seconds 2.0] [--interval 0.2]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "src"))

import paths  # noqa: E402


def repoint(sandbox: Path) -> None:
    paths.SPOOL = sandbox / "spool"
    paths.SPOOL_TMP = paths.SPOOL / "tmp"
    paths.SPOOL_READY = paths.SPOOL / "ready"
    paths.SPOOL_CLAIMED = paths.SPOOL / "claimed"
    paths.SPOOL_DEAD = paths.SPOOL / "dead"
    paths.DATA = sandbox / "data"
    paths.CAPTURES = paths.DATA / "captures"
    paths.STATES = paths.DATA / "states"
    paths.RUNS = paths.DATA / "runs"
    paths.LABELS = paths.DATA / "labels"
    paths.FIXTURES = paths.DATA / "fixtures"
    paths.DROPS = paths.DATA / "drops"
    paths.BASELINE = paths.DATA / "baseline"
    paths.SPOOL_WATERMARK = paths.DATA / "spool_watermark.json"
    paths.LOGS = sandbox / "logs"
    paths.REPORTS = sandbox / "reports"
    # The live kill switch is PRESENT right now. Without this line the driver
    # would drain nothing and every assertion below would pass vacuously.
    paths.KILL_SWITCH = sandbox / ".jev-disabled"
    paths.WRITABLE_DIRS = [
        paths.SPOOL_TMP, paths.SPOOL_READY, paths.SPOOL_CLAIMED, paths.SPOOL_DEAD,
        paths.CAPTURES, paths.STATES, paths.RUNS, paths.LABELS, paths.FIXTURES,
        paths.DROPS, paths.LOGS, paths.REPORTS,
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sandbox", required=True)
    ap.add_argument("--dispatch-seconds", type=float, default=2.0)
    ap.add_argument("--interval", type=float, default=0.2)
    args = ap.parse_args()

    sandbox = Path(args.sandbox).resolve()
    repoint(sandbox)

    from arms import fake  # noqa: E402
    import worker  # noqa: E402

    real_evaluate = fake.evaluate
    sentinel = sandbox / "dispatch_started"

    def slow_evaluate(state, questions, config):
        """Announce that a dispatch is in flight, then take long enough that
        the test can reliably land a signal inside it."""
        sentinel.write_text(str(time.time()), encoding="utf-8")
        time.sleep(args.dispatch_seconds)
        return real_evaluate(state, questions, config)

    fake.evaluate = slow_evaluate

    sys.argv = ["worker.py", "--interval", str(args.interval), "--arms", "fake"]
    return worker.main()


if __name__ == "__main__":
    raise SystemExit(main())
