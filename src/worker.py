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

**Both arms run async, in one worker, interleaved per decision point with
randomised arm order.** Making Jev inline and the LLMs offline would confound the
comparison with process spawn, TLS setup and time-of-day network drift that only
one arm pays. Enforce-mode latency is measured separately, by bench_inline.py.

**Every arm sees byte-identical state.** The state is built once, hashed once,
and the hash is recorded on every row, so a serialisation drift fails loudly in
analysis instead of silently skewing every comparison.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_loader as cl  # noqa: E402
import paths  # noqa: E402
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


def process_capture(
    payload: dict[str, Any],
    surface: str,
    arms: list[ArmConfig],
    *,
    run_context: str = "live",
    phrasing: str | None = None,
    rng: random.Random | None = None,
    dry_run: bool = False,
) -> tuple[str, list[Run]]:
    rng = rng or random.Random()
    decision_id = store.ulid()
    picked_at = store.utcnow()

    state = sb.build(surface, payload)
    state_sha = sb.sha256(state)
    questions = cl.questions_for(surface, phrasing=phrasing)
    qsid = cl.question_set_id(surface, phrasing=phrasing)

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

    # Randomised arm order per decision point: no arm systematically pays the
    # cold-connection cost or a particular slice of time-of-day network drift.
    order = list(arms)
    rng.shuffle(order)

    results: list[Run] = []
    for config in order:
        run = evaluate_one(state, questions, config)
        results.append(run)

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
                "arm_order_position": position,
                "arm_order": [c.name for c in order],
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
    for spooled in ready:
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
            print(f"  {surface} {decision_id} -> {ok}/{len(results)} arms ok")
    return processed


def _quarantine(spooled: Path, reason: str, *, verbose: bool) -> None:
    """Never silently delete a capture we failed to process."""
    dead = paths.SPOOL / "dead"
    dead.mkdir(parents=True, exist_ok=True)
    spooled.rename(dead / spooled.name)
    (dead / f"{spooled.name}.reason").write_text(reason, encoding="utf-8")
    if verbose:
        print(f"  quarantined {spooled.name}: {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Drain the capture spool.")
    parser.add_argument("--once", action="store_true", help="drain and exit")
    parser.add_argument("--interval", type=float, default=2.0, help="poll seconds")
    parser.add_argument("--arms", help="comma-separated arm names (default: config enabled)")
    args = parser.parse_args()

    paths.ensure_dirs()
    names = args.arms.split(",") if args.arms else cl.arms_config()["enabled"]
    arms = [cl.arm(n.strip()) for n in names]

    print(f"worker: arms={[a.name for a in arms]} spool={paths.SPOOL_READY}")
    if args.once:
        n = drain_once(arms)
        print(f"drained {n} capture(s)")
        return 0

    print("polling; ctrl-c to stop")
    try:
        while True:
            drain_once(arms, verbose=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
