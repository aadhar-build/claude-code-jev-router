#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Spool drainer. The sole writer of data/runs/.

Started manually in a visible terminal for the duration of the experiment. No
launchd, no SessionStart self-start: when the output is a published measurement,
"the experiment is running" should be an observable state, not an ambient one.

Two properties matter more than anything else here:

**Every arm runs offline, in one worker, on the same decision point.** Making Jev
inline and the LLMs offline would confound the comparison with process spawn, TLS
setup and time-of-day network drift that only one arm pays. Enforce-mode latency
is measured separately, by bench_inline.py.

**Every arm sees byte-identical state.** The state is built once, hashed once,
and the hash is recorded on every row, so a serialisation drift fails loudly in
analysis instead of silently skewing every comparison.

--------------------------------------------------------------------------
ARM DISPATCH: what `arm_order` and `arm_order_position` mean (JEV-33)
--------------------------------------------------------------------------

Until 2026-09-20 the arms were evaluated **sequentially** in a per-decision
randomised order. The randomisation was never about the order itself; it existed
so that no arm systematically occupied the late slots of a ~20-80s serial window
and therefore systematically paid a slice of time-of-day network drift, nor
systematically occupied the first slot and paid the cold-connection cost. In that
era `arm_order` was causal: position N genuinely ran after positions 0..N-1, and
`arm_order_position` was the control variable an analysis would condition on.

Since JEV-33 the arms are dispatched **concurrently** — all of them start within
a few hundred microseconds of one decision's t0. That does not weaken the
protection the randomisation existed for; it removes the hazard outright. There
are no late slots to be unlucky in, because there are no slots. Concurrency is
the stronger version of the same guarantee, not a relaxation of it.

But it changes what the two fields MEAN, and those fields are already on 750+
committed rows, so they are not silently redefined:

  arm_dispatch          NEW. "concurrent" on every row written by this code.
                        ABSENT on every row written before the boundary, and
                        absence is defined to mean "sequential". replay.py and
                        canary.py rows are also sequential and also omit it.
                        This is the era marker; condition on it, do not pool
                        latency across it without saying so.
  arm_order             Post-boundary: the randomised **submission** order into
                        the thread pool. It no longer determines when a call
                        ran, so it is NOT a latency-confound control any more.
                        It is kept because the submission stagger is real,
                        merely tiny, and because dropping a field mid-window is
                        worse than narrowing one.
  arm_order_position    Post-boundary: this arm's index in that submission
                        order. The invariant row["arm"] ==
                        row["arm_order"][row["arm_order_position"]] holds in
                        both eras and is tested.
  dispatch_offset_ms    NEW. Measured ms from the decision's t0 to the moment
                        this arm's call actually began. This is the EMPIRICAL
                        replacement for the order control: an analysis can now
                        verify the stagger is negligible instead of trusting
                        the design. Sequential-era rows do not have it.
  dispatch_wall_ms      NEW. t0 to the last arm finishing, per decision. The
                        direct drain-rate instrument.
  concurrent_arms       NEW. How many arms were in flight together. Concurrent
                        `claude -p` spawns contend for CPU, so a cc_* arm's
                        total_ms is inflated relative to the sequential era by
                        an amount this field lets an analysis condition on.
                        `raw.duration_api_ms` separates API time from spawn.

**The honest statement for the writeup**: pre- and post-boundary latency are
different measurements of different things and must not be pooled. Agreement,
answers, cost and attrition are unaffected — the arms see identical bytes and
ask identical questions in both eras.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent import futures
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_loader as cl  # noqa: E402
import paths  # noqa: E402
import spool_watch  # noqa: E402
import state_builders as sb  # noqa: E402
import store  # noqa: E402
from arms.base import ArmConfig, Run, classify_exception  # noqa: E402


def load_arm_module(kind: str):
    if kind == "fake":
        from arms import fake
        return fake
    if kind == "jev":
        from arms import jev
        return jev
    if kind == "anthropic":
        from arms import claude
        return claude
    if kind == "claude_cli":
        from arms import claude_cli
        return claude_cli
    raise ValueError(f"unknown arm kind: {kind}")


def evaluate_one(state: str, questions: dict[str, Any], config: ArmConfig) -> Run:
    """Call an arm, converting any failure into a Run with ok=False.

    Failures are rows. Dropping them would make attrition invisible, which is
    exactly how a latency distribution gets quietly flattered.
    """
    try:
        return load_arm_module(config.kind).evaluate(state, questions, config)
    except Exception as exc:  # noqa: BLE001 -- an arm must never kill the worker
        # Deliberately NOT BaseException: a Ctrl-C during a live call would
        # otherwise be recorded as an arm failure, quietly poisoning the
        # attrition statistics with failures the arm never had.
        kind, detail = classify_exception(exc)
        return Run(
            arm=config.name,
            arm_config_id=config.arm_config_id,
            ok=False,
            error_kind=kind,
            error_detail=detail[:2000],
        )


def _dispatch(
    state: str,
    questions: dict[str, Any],
    order: list[ArmConfig],
) -> tuple[list[Run], list[float], float]:
    """Run every arm concurrently, returning results IN SUBMISSION ORDER.

    Results are indexed by submission position rather than collected with
    as_completed(), because the position is written onto the row: pairing a
    future with the wrong arm would mislabel `arm_order_position` silently,
    which is worse than being slow.

    Note for whoever reads a wedged terminal: a Ctrl-C here blocks inside the
    pool's shutdown until the in-flight `claude -p` calls return, which can be
    up to the arm's timeout_s (180-240s). The worker is not hung.
    """
    if not order:
        return [], [], 0.0

    t0 = time.perf_counter()
    offsets: list[float] = [0.0] * len(order)

    def call(position: int, config: ArmConfig) -> Run:
        offsets[position] = (time.perf_counter() - t0) * 1000.0
        return evaluate_one(state, questions, config)

    with futures.ThreadPoolExecutor(max_workers=len(order)) as pool:
        pending = [pool.submit(call, i, c) for i, c in enumerate(order)]
        results = [f.result() for f in pending]

    return results, offsets, (time.perf_counter() - t0) * 1000.0


def process_capture(
    payload: dict[str, Any],
    surface: str,
    arms: list[ArmConfig],
    *,
    run_context: str = "live",
    version: str | None = None,
    phrasing: str | None = None,
    rng: random.Random | None = None,
    dry_run: bool = False,
) -> tuple[str, list[Run]]:
    rng = rng or random.Random()
    decision_id = store.ulid()
    picked_at = store.utcnow()

    state = sb.build(surface, payload)
    state_sha = sb.sha256(state)
    # Resolved once, then passed to both calls. Taking the config default twice
    # would let the questions actually asked and the question_set_id recorded
    # beside them drift apart, which is unreconstructable after the fact.
    version = version or cl.surface_question_version(surface)
    questions = cl.questions_for(surface, version=version, phrasing=phrasing)
    qsid = cl.question_set_id(surface, version=version, phrasing=phrasing)

    capture_row = {
        "decision_id": decision_id,
        "picked_at": picked_at,
        "surface": surface,
        "session_id": payload.get("session_id"),
        "prompt_id": payload.get("prompt_id"),
        "tool_use_id": payload.get("tool_use_id"),
        "agent_type": payload.get("agent_type"),
        "is_sidechain": bool(payload.get("agent_id")),
        "permission_mode": payload.get("permission_mode"),
        "cwd": payload.get("cwd"),
        "state_sha256": state_sha,
        "state_chars": len(state),
        "state_builder_version": sb.STATE_BUILDER_VERSION,
        "state_source": sb.STATE_SOURCE[surface],
        "run_context": run_context,
    }

    # Randomised submission order per decision point, then CONCURRENT dispatch.
    # See the module docstring: the randomisation existed so no arm
    # systematically paid a late slot in a serial window; concurrency removes
    # the slots entirely. The shuffle is kept so that the residual sub-
    # millisecond submission stagger is still randomised rather than fixed.
    order = list(arms)
    rng.shuffle(order)

    results, offsets, dispatch_wall_ms = _dispatch(state, questions, order)

    if dry_run:
        return decision_id, results

    store.write_state(state, state_sha)
    store.append_capture(capture_row)

    for position, run in enumerate(results):
        row = run.to_dict()
        usage = row["usage"]
        row.update(
            {
                "decision_id": decision_id,
                "surface": surface,
                "session_id": payload.get("session_id"),
                "question_set_id": qsid,
                "state_sha256": state_sha,
                "run_context": run_context,
                # See the module docstring for what these four mean now that
                # the calls overlap. `arm_dispatch` is the era marker; its
                # ABSENCE on a row means the sequential era.
                "arm_dispatch": "concurrent",
                "arm_order_position": position,
                "arm_order": [c.name for c in order],
                "concurrent_arms": len(order),
                "dispatch_offset_ms": round(offsets[position], 3),
                "dispatch_wall_ms": round(dispatch_wall_ms, 1),
                "evaluated_at": store.utcnow(),
                "pricing_version": cl.pricing()["version"],
                "cost_usd": cl.cost_usd(run.response_model or "", usage) if run.ok else None,
            }
        )
        store.append_run(row)

    return decision_id, results


def drain_once(arms: list[ArmConfig], *, verbose: bool = True) -> int:
    ready = sorted(paths.SPOOL_READY.glob("*.json"))
    processed = 0
    claimed_dir = paths.SPOOL / "claimed"
    claimed_dir.mkdir(parents=True, exist_ok=True)

    for candidate in ready:
        # Sample the depth on every claim, not once per poll cycle: the backlog
        # peaks while the worker is mid-capture and a 30s poll steps over the
        # peak it exists to catch (JEV-33).
        spool_watch.sample()

        # Claim the file by renaming it out of ready/ before doing any work.
        # rename is atomic, so exactly one worker wins and the loser moves on.
        # Without this, two workers evaluate the same capture against the live
        # arms and we pay twice for a duplicate row.
        spooled = claimed_dir / candidate.name
        try:
            candidate.rename(spooled)
        except (FileNotFoundError, OSError):
            continue

        surface = spooled.name.split("__", 1)[0]
        try:
            payload = json.loads(spooled.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _quarantine(spooled, f"unreadable: {exc}", verbose=verbose)
            continue

        mode = cl.surface_mode(surface)
        if mode == "off":
            _quarantine(spooled, "surface is off", verbose=verbose)
            continue

        active = [] if mode == "capture_only" else arms
        try:
            decision_id, results = process_capture(payload, surface, active)
        except sb.StateBuildError as exc:
            _quarantine(spooled, f"state build failed: {exc}", verbose=verbose)
            continue
        except Exception as exc:  # noqa: BLE001
            _quarantine(spooled, f"unexpected: {exc}", verbose=verbose)
            continue

        spooled.unlink(missing_ok=True)
        processed += 1
        if verbose:
            ok = sum(1 for r in results if r.ok)
            print(f"  {surface} {decision_id} -> {ok}/{len(results)} arms ok", flush=True)
    return processed


def _quarantine(spooled: Path, reason: str, *, verbose: bool) -> None:
    """Never silently delete a capture we failed to process.

    Tolerant of the file having already gone. Two workers draining the same
    spool will race: one processes and unlinks a file while the other is still
    deciding to quarantine it. An unguarded rename raises FileNotFoundError,
    which killed a live collection run and stopped capture accumulating without
    any visible signal. Losing one duplicate record is fine; losing the worker
    is not.
    """
    dead = paths.SPOOL / "dead"
    dead.mkdir(parents=True, exist_ok=True)
    try:
        spooled.rename(dead / spooled.name)
    except FileNotFoundError:
        if verbose:
            print(f"  {spooled.name} vanished before quarantine (another worker took it)",
                  flush=True)
        return
    (dead / f"{spooled.name}.reason").write_text(reason, encoding="utf-8")
    if verbose:
        print(f"  quarantined {spooled.name}: {reason}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Drain the capture spool.")
    parser.add_argument("--once", action="store_true", help="drain and exit")
    parser.add_argument("--interval", type=float, default=2.0, help="poll seconds")
    parser.add_argument("--arms", help="comma-separated arm names (default: config enabled)")
    args = parser.parse_args()

    paths.ensure_dirs()
    # Validate every surface's pinned question set BEFORE claiming any spool
    # file. surface_mode() would load the config anyway, but by then a capture
    # has already been renamed into claimed/ and a bad pin would orphan it.
    cl.surfaces()
    names = args.arms.split(",") if args.arms else cl.arms_config()["enabled"]
    arms = [cl.arm(n.strip()) for n in names]

    print(f"worker: arms={[a.name for a in arms]} spool={paths.SPOOL_READY}", flush=True)
    print(f"worker: dispatch=concurrent ({len(arms)} arms in flight per decision); "
          "rows carry arm_dispatch='concurrent' -- see the module docstring "
          "for what arm_order means now", flush=True)
    print(spool_watch.report(), flush=True)
    if args.once:
        n = drain_once(arms)
        print(f"drained {n} capture(s)")
        return 0

    print("polling; ctrl-c to stop")
    try:
        while True:
            drain_once(arms, verbose=True)
            spool_watch.sample()  # keep the mark live even on an idle cycle
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
