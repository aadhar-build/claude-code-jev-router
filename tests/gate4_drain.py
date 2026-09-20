#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""GATE 4's drain step: run the real worker against a SANDBOX spool.

`tests/gates.sh` owns the assertions; this file exists only to do the one thing
bash cannot -- drive `worker.drain_once()` -- and to report what happened as
JSON on stdout.

Two properties make it safe to run beside a live collection window:

  * every path the worker writes is repointed into the sandbox BEFORE the worker
    is imported, so `spool/`, `data/runs/` and `data/captures/` are untouched;
  * the only arm is `FakeArm`. No network, no subprocess, no spend.

`--mutate` is the gate's teeth. It wraps EVERY state builder in the exact
failure decision #7 forbids -- read `transcript_path` live, at worker time,
and append whatever is there now -- and the gate then asserts that the hash it
claims is stable DOES move. A leakage test that cannot fail proves nothing, so
the mutation runs on every gate invocation rather than being demonstrated once
by hand and then rotting.

The mutation patches `state_builders.BUILDERS[surface]`, not the module-level
function: `worker` reaches the builder through that dict, so patching
`sb.build_pre_bash` would leave the real builder in place and the gate would
read "no leak" from a mutation that never took effect.

Usage:
  gate4_drain.py --sandbox DIR --config DIR [--mutate]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "src"))

import pyversion  # noqa: E402

# JEV-44: assert the floor BEFORE importing anything that does not parse
# below it. The PEP-723 header above binds `uv run` only; `python3
# tests/<this file>` ignores it entirely, and that is the invocation that
# produced 16 SyntaxErrors out of src/arms/jev.py:237.
pyversion.require()


import paths  # noqa: E402


def repoint(sandbox: Path, config: Path) -> None:
    """Send every writable path into the sandbox. Questions stay real.

    `questions/` is read-only and frozen by PREREGISTRATION section 8, so the
    gate reads the real files: a gate that ran against a copied question set
    would not be testing the question set in force.
    """
    paths.CONFIG = config
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
    paths.SPOOL_WATERMARK = paths.DATA / "spool_watermark.json"
    paths.LOGS = sandbox / "logs"
    paths.REPORTS = sandbox / "reports"
    paths.KILL_SWITCH = sandbox / ".jev-disabled"
    paths.WRITABLE_DIRS = [
        paths.SPOOL_TMP, paths.SPOOL_READY, paths.CAPTURES, paths.STATES,
        paths.RUNS, paths.LABELS, paths.FIXTURES, paths.DROPS, paths.LOGS,
        paths.REPORTS,
    ]


def leak(original):
    """The decision-#7 violation, in one line. Deliberately naive on purpose:
    read the transcript as it exists NOW, minutes after the decision point."""

    def leaky(payload):
        state = original(payload)
        transcript = payload.get("transcript_path")
        if transcript and Path(transcript).exists():
            state += "\n\n" + Path(transcript).read_text(encoding="utf-8", errors="ignore")
        return state

    return leaky


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sandbox", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--builders", action="store_true",
                    help="print the surfaces that have a state builder, and exit")
    args = ap.parse_args()

    repoint(Path(args.sandbox).resolve(), Path(args.config).resolve())

    import state_builders as sb  # noqa: E402  (after repoint, by design)

    if args.builders:
        print(json.dumps(sorted(sb.BUILDERS)))
        return 0

    import config_loader as cl  # noqa: E402
    import store  # noqa: E402
    import worker  # noqa: E402

    if args.mutate:
        for surface, builder in list(sb.BUILDERS.items()):
            sb.BUILDERS[surface] = leak(builder)

    before_captures = len(list(store.captures()))
    before_runs = len(list(store.runs()))

    worker.drain_once([cl.arm("fake")], verbose=False)

    captures = list(store.captures())
    runs = list(store.runs())
    dead_dir = paths.SPOOL / "dead"
    dead = []
    if dead_dir.is_dir():
        for reason in sorted(dead_dir.glob("*.reason")):
            dead.append({"file": reason.name[: -len(".reason")],
                         "reason": reason.read_text(encoding="utf-8")})

    new = captures[before_captures:]
    out = {
        "new_captures": [
            {
                "decision_id": c.get("decision_id"),
                "surface": c.get("surface"),
                "session_id": c.get("session_id"),
                "state_sha256": c.get("state_sha256"),
                "state_source": c.get("state_source"),
                "state": store.read_state(c["state_sha256"]),
            }
            for c in new
        ],
        "new_runs": len(runs) - before_runs,
        "dead": dead,
        "ready_left": len(list(paths.SPOOL_READY.glob("*.json"))),
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
