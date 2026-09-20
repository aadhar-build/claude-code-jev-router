#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Re-evaluate stored or synthetic states without touching a live session.

This is where most of the study's leverage comes from. A captured state is
permanently replayable, so a question can be re-asked under a different
phrasing, a shuffled option order, a truncated state, or a new arm, and the
result joins to the original decision on `decision_id` -- which means the Phase 2
labelling pass, keyed on `(decision_id, question_name)`, applies to every variant
ever produced, with zero re-running.

`run_context` keeps the streams apart and is never mixed in analysis:

  live       captured from a real session
  replay     a stored state re-evaluated
  synthetic  the stratified stress set
  canary     the daily drift check

Modes:
  --synthetic          run the stress set
  --decisions          re-run stored captures
  --determinism N      the same call N times, to see which arms are stable
  --phrasings          every phrasing variant of each question
  --truncation         states cut to 50% and 75%

The question set version comes from `config/surfaces.json` unless
`--question-version` overrides it. It is part of the replay key, so the same
state under a different version is a new row, never an overwrite.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_loader as cl  # noqa: E402
import paths  # noqa: E402
import state_builders as sb  # noqa: E402
import store  # noqa: E402
import worker  # noqa: E402
from arms.base import ArmConfig  # noqa: E402


def _emit(
    *,
    decision_id: str,
    surface: str,
    session_id: str,
    state: str,
    questions: dict[str, Any],
    qsid: str,
    arms: list[ArmConfig],
    run_context: str,
    rng: random.Random,
    extra: dict[str, Any] | None = None,
) -> int:
    """Evaluate one state against every arm and write the rows."""
    state_sha = sb.sha256(state)
    store.write_state(state, state_sha)

    order = list(arms)
    rng.shuffle(order)
    written = 0
    for position, config in enumerate(order):
        run = worker.evaluate_one(state, questions, config)
        row = run.to_dict()
        row.update({
            "decision_id": decision_id,
            "surface": surface,
            "session_id": session_id,
            "question_set_id": qsid,
            "state_sha256": state_sha,
            "run_context": run_context,
            "arm_order_position": position,
            "arm_order": [c.name for c in order],
            "evaluated_at": store.utcnow(),
            "pricing_version": cl.pricing()["version"],
            "cost_usd": cl.cost_usd(run.response_model or "", row["usage"]) if run.ok else None,
        })
        if extra:
            row.update(extra)
        store.append_run(row)
        written += 1
    return written


def stratified_sample(items: list[dict], n: int, rng: random.Random) -> list[dict]:
    """Take n items spread evenly across strata, preferring DISTINCT commands.

    Necessary because the synthetic file is command-major: each command appears
    once per context, so a naive head-of-list slice returns the same command
    three times over and the sample measures almost nothing. At ~21s per
    subscription call a ten-item run is all you get, so those ten items have to
    be ten different commands.
    """
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_stratum[item["stratum"]].append(item)

    picked: list[dict] = []
    strata = sorted(by_stratum)
    per_stratum = {s: n // len(strata) for s in strata}
    for s in strata[: n % len(strata)]:          # spread the remainder
        per_stratum[s] += 1

    for stratum in strata:
        pool = by_stratum[stratum]
        # One entry per distinct command first, in shuffled order.
        seen: set[str] = set()
        unique: list[dict] = []
        for item in rng.sample(pool, len(pool)):
            command = item["payload"]["tool_input"]["command"]
            if command not in seen:
                seen.add(command)
                unique.append(item)
        want = per_stratum[stratum]
        chosen = unique[:want]
        if len(chosen) < want:                    # only then allow repeats
            chosen += [i for i in pool if i not in chosen][: want - len(chosen)]
        picked.extend(chosen)

    # Interleave the strata rather than returning them in blocks. A long run can
    # be interrupted -- rate limits, a laptop lid, an impatient operator -- and
    # returning all the benign items first means a partial run yields a dataset
    # with one stratum in it, from which no AUC can be computed at all. Shuffled,
    # any prefix of the run is a usable stratified sample.
    rng.shuffle(picked)
    return picked


def run_synthetic(arms: list[ArmConfig], surface: str, limit: int | None,
                  rng: random.Random, sample: int | None = None,
                  version: str | None = None) -> int:
    path = paths.DATA / "synthetic" / f"{surface}-v1.jsonl"
    if not path.exists():
        print(f"no synthetic set at {path}; run src/make_synthetic.py first")
        return 0

    items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if sample:
        items = stratified_sample(items, sample, rng)
        print(f"stratified sample of {len(items)} from {path.name}:")
        for item in items:
            print(f"    {item['stratum']:<12} {item['payload']['tool_input']['command'][:56]}")
        print()
    elif limit:
        items = items[:limit]

    version = version or cl.surface_question_version(surface)
    questions = cl.questions_for(surface, version=version)
    qsid = cl.question_set_id(surface, version=version)
    written = 0
    for i, item in enumerate(items, 1):
        state = sb.build(surface, item["payload"])
        decision_id = f"syn-{item['synthetic_id']}"
        store.append_capture({
            "decision_id": decision_id,
            "picked_at": store.utcnow(),
            "surface": surface,
            "session_id": item["payload"]["session_id"],
            "state_sha256": sb.sha256(state),
            "state_chars": len(state),
            "state_builder_version": sb.STATE_BUILDER_VERSION,
            "state_source": sb.STATE_SOURCE[surface],
            "run_context": "synthetic",
            "stratum": item["stratum"],
            "is_sidechain": False,
        })
        written += _emit(
            decision_id=decision_id, surface=surface,
            session_id=item["payload"]["session_id"], state=state,
            questions=questions, qsid=qsid, arms=arms,
            run_context="synthetic", rng=rng,
            extra={"stratum": item["stratum"]},
        )
        if i % 25 == 0:
            print(f"  {i}/{len(items)} items, {written} rows")
    return written


def run_determinism(arms: list[ArmConfig], surface: str, repeats: int, limit: int,
                    rng: random.Random, version: str | None = None) -> int:
    """The same bytes, N times. If Jev is deterministic and temperature-zero
    LLMs are not, that deserves its own section in the writeup."""
    captures = [c for c in store.captures() if c["surface"] == surface][:limit]
    version = version or cl.surface_question_version(surface)
    questions = cl.questions_for(surface, version=version)
    qsid = cl.question_set_id(surface, version=version)
    written = 0
    for capture in captures:
        state = store.read_state(capture["state_sha256"])
        for attempt in range(1, repeats + 1):
            written += _emit(
                decision_id=capture["decision_id"], surface=surface,
                session_id=capture.get("session_id") or "", state=state,
                questions=questions, qsid=qsid, arms=arms,
                run_context="replay", rng=rng,
                extra={"sweep": "determinism", "attempt": attempt},
            )
    return written


def run_phrasings(arms: list[ArmConfig], surface: str, limit: int, rng: random.Random,
                  version: str | None = None) -> int:
    """Every phrasing variant. If an arm is phrasing-insensitive while another
    is not, that is itself a result -- and it is why the baseline prompts are
    pre-registered."""
    version = version or cl.surface_question_version(surface)
    spec = cl.question_set(surface, version)
    phrasings = sorted({p for q in spec["questions"].values() for p in q["phrasings"]})
    captures = [c for c in store.captures() if c["surface"] == surface][:limit]
    written = 0
    for capture in captures:
        state = store.read_state(capture["state_sha256"])
        for phrasing in phrasings:
            written += _emit(
                decision_id=capture["decision_id"], surface=surface,
                session_id=capture.get("session_id") or "", state=state,
                questions=cl.questions_for(surface, version=version, phrasing=phrasing),
                qsid=cl.question_set_id(surface, version=version, phrasing=phrasing),
                arms=arms, run_context="replay", rng=rng,
                extra={"sweep": "phrasing", "phrasing": phrasing},
            )
    return written


def run_truncation(arms: list[ArmConfig], surface: str, limit: int, rng: random.Random,
                   version: str | None = None) -> int:
    """How much of the state does each arm actually need?"""
    captures = [c for c in store.captures() if c["surface"] == surface][:limit]
    version = version or cl.surface_question_version(surface)
    questions = cl.questions_for(surface, version=version)
    qsid = cl.question_set_id(surface, version=version)
    written = 0
    for capture in captures:
        full = store.read_state(capture["state_sha256"])
        for fraction in (0.5, 0.75, 1.0):
            cut = full if fraction == 1.0 else full[: max(1, int(len(full) * fraction))]
            written += _emit(
                decision_id=capture["decision_id"], surface=surface,
                session_id=capture.get("session_id") or "", state=cut,
                questions=questions, qsid=qsid, arms=arms,
                run_context="replay", rng=rng,
                extra={"sweep": "truncation", "fraction": fraction},
            )
    return written


def run_decisions(arms: list[ArmConfig], surface: str, limit: int, rng: random.Random,
                  version: str | None = None) -> int:
    captures = [c for c in store.captures() if c["surface"] == surface][:limit]
    version = version or cl.surface_question_version(surface)
    questions = cl.questions_for(surface, version=version)
    qsid = cl.question_set_id(surface, version=version)
    written = 0
    for capture in captures:
        written += _emit(
            decision_id=capture["decision_id"], surface=surface,
            session_id=capture.get("session_id") or "",
            state=store.read_state(capture["state_sha256"]),
            questions=questions, qsid=qsid, arms=arms,
            run_context="replay", rng=rng,
        )
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay stored or synthetic states.")
    parser.add_argument("--surface", default="pre_bash")
    parser.add_argument("--question-version", metavar="V",
                        help="override the question set version pinned for this surface in "
                             "config/surfaces.json (e.g. v2). The version is part of the "
                             "replay key, so rows are never overwritten by a different one.")
    parser.add_argument("--arms", help="comma-separated (default: config enabled)")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--sample", type=int, metavar="N",
                        help="stratified sample of N distinct commands (use this, not --limit, "
                             "for the synthetic set)")
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--decisions", action="store_true")
    parser.add_argument("--determinism", type=int, metavar="N")
    parser.add_argument("--phrasings", action="store_true")
    parser.add_argument("--truncation", action="store_true")
    parser.add_argument("--estimate", action="store_true",
                        help="print the call count and projected cost, then exit")
    args = parser.parse_args()

    paths.ensure_dirs()
    names = args.arms.split(",") if args.arms else cl.arms_config()["enabled"]
    arms = [cl.arm(n.strip()) for n in names]
    rng = random.Random(args.seed)

    if args.estimate:
        synthetic_path = paths.DATA / "synthetic" / f"{args.surface}-v1.jsonl"
        n_syn = len(synthetic_path.read_text().splitlines()) if synthetic_path.exists() else 0
        n_cap = len([c for c in store.captures() if c["surface"] == args.surface])
        print(f"synthetic items : {n_syn}")
        print(f"stored captures : {n_cap}")
        print(f"arms            : {[a.name for a in arms]}")
        print(f"\n--synthetic      -> {n_syn * len(arms):>6} calls")
        print(f"--decisions      -> {min(n_cap, args.limit) * len(arms):>6} calls")
        print(f"--determinism 20 -> {min(n_cap, args.limit) * len(arms) * 20:>6} calls")
        print(f"--phrasings      -> {min(n_cap, args.limit) * len(arms) * 3:>6} calls")
        print(f"--truncation     -> {min(n_cap, args.limit) * len(arms) * 3:>6} calls")
        print("\nEvery call spends real money on the Claude arms. Estimate before running.")
        return 0

    total = 0
    if args.synthetic:
        print(f"synthetic stress set -> {[a.name for a in arms]}")
        total += run_synthetic(arms, args.surface,
                               args.limit if args.limit != 50 else None, rng, sample=args.sample,
                               version=args.question_version)
    if args.decisions:
        total += run_decisions(arms, args.surface, args.limit, rng,
                               version=args.question_version)
    if args.determinism:
        total += run_determinism(arms, args.surface, args.determinism, args.limit, rng,
                                 version=args.question_version)
    if args.phrasings:
        total += run_phrasings(arms, args.surface, args.limit, rng,
                               version=args.question_version)
    if args.truncation:
        total += run_truncation(arms, args.surface, args.limit, rng,
                                version=args.question_version)

    if total == 0:
        parser.print_help()
        return 1
    print(f"wrote {total} run rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
