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
  --seed-synthetic     store captures for named synthetic items; spends nothing

Item selection (JEV-16): --ids and --context. A sweep without either slices
`store.captures()` in append order with every run context pooled, which is an
accident of write order rather than a sample.
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

    # JEV-16, following worker.py's pattern (see the comment at worker.py:438).
    # Resolved ONCE, here, BEFORE any arm is called. `config_fingerprint()`
    # calls `assert_config_fresh()`, which raises; reading it inside the arm
    # loop would let a config edit landing mid-sweep raise after the calls had
    # already been paid for, and would let two rows from one _emit disagree
    # about the config they ran under. Raising here costs nothing.
    config_fp = cl.config_fingerprint()["config_sha256"]

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
            "config_fingerprint": config_fp,
            "cost_usd": cl.cost_usd(run.response_model or "", row["usage"]) if run.ok else None,
        })
        if extra:
            row.update(extra)
        store.append_run(row)
        written += 1
    return written


def _synthetic_items(surface: str) -> dict[str, dict[str, Any]]:
    path = paths.DATA / "synthetic" / f"{surface}-v1.jsonl"
    if not path.exists():
        return {}
    return {i["synthetic_id"]: i
            for i in (json.loads(line) for line in path.read_text().splitlines() if line.strip())}


def _write_synthetic_capture(surface: str, item: dict[str, Any], *,
                             config_fp: str, known: set[str]) -> tuple[str, str, str]:
    """Record that a synthetic decision point exists. Zero API calls.

    Returns `(decision_id, state, state_sha256)`. Idempotent against `known`,
    which the caller seeds from `store.captures()`: a capture is an immutable
    decision point, and a second sweep over the same item re-evaluates it
    rather than observing a new one.

    The `syn-` prefix is applied to a `synthetic_id` that already begins
    `syn-`, so ids on disk read `syn-syn-0121`. That is a defect and it is NOT
    fixed here: the 60 existing synthetic captures and their 180 run rows all
    carry the doubled form, and renaming would orphan every one of them from
    its rows. Reported, not repaired.
    """
    state = sb.build(surface, item["payload"])
    state_sha = sb.sha256(state)
    decision_id = f"syn-{item['synthetic_id']}"
    if decision_id not in known:
        store.write_state(state, state_sha)
        store.append_capture({
            "decision_id": decision_id,
            "picked_at": store.utcnow(),
            "surface": surface,
            "session_id": item["payload"]["session_id"],
            "state_sha256": state_sha,
            "state_chars": len(state),
            "state_builder_version": sb.STATE_BUILDER_VERSION,
            "state_source": sb.STATE_SOURCE[surface],
            "run_context": "synthetic",
            "stratum": item["stratum"],
            "is_sidechain": False,
            "config_fingerprint": config_fp,
        })
        known.add(decision_id)
    return decision_id, state, state_sha


def seed_synthetic(surface: str, synthetic_ids: list[str]) -> list[str]:
    """Materialise stored captures and states for named synthetic items.

    Needed because `--determinism` replays STORED captures, and only the 60
    items of the original stratified sample were ever stored. The nine states
    the Amendment 7 thinking-token probe used are in the synthetic file and
    seven of them are not in the store, so without this the sweep cannot be
    pointed at the exact states whose cross-config delta it is meant to
    explain. Writes capture rows only; spends nothing.
    """
    items = _synthetic_items(surface)
    missing = [s for s in synthetic_ids if s not in items]
    if missing:
        raise KeyError(f"not in the {surface} synthetic set: {missing}")
    config_fp = cl.config_fingerprint()["config_sha256"]
    known = {c.get("decision_id") for c in store.captures()}
    out = []
    for sid in synthetic_ids:
        decision_id, _, _ = _write_synthetic_capture(
            surface, items[sid], config_fp=config_fp, known=known)
        out.append(decision_id)
    return out


def _select(surface: str, *, limit: int, ids: list[str] | None = None,
            context: str | None = None) -> list[dict[str, Any]]:
    """Which stored captures a sweep runs over.

    Before JEV-16 every sweep did `store.captures()[:limit]` in FILE ORDER with
    every run context pooled, which is not a sample of anything: the first 50
    happened to be 48 synthetic and 2 live, an accident of the order rows were
    appended in. `--ids` names the items; `--context` restricts to one origin,
    because `PREREGISTRATION.md` section 4 forbids pooling live with synthetic
    and a sweep that silently mixes them produces a flip rate belonging to
    neither.
    """
    captures = [c for c in store.captures() if c["surface"] == surface]
    if context:
        captures = [c for c in captures if (c.get("run_context") or "live") == context]
    if ids:
        by_id = {c["decision_id"]: c for c in captures}
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            raise KeyError(
                f"no stored capture for {unknown} on surface {surface}"
                + (f" with run_context={context}" if context else "")
                + ". For synthetic items use --seed-synthetic first.")
        return [by_id[i] for i in ids]
    return captures[:limit]


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
    config_fp = cl.config_fingerprint()["config_sha256"]
    known = {c.get("decision_id") for c in store.captures()}
    for i, item in enumerate(items, 1):
        decision_id, state, _ = _write_synthetic_capture(
            surface, item, config_fp=config_fp, known=known)
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
                    rng: random.Random, version: str | None = None,
                    ids: list[str] | None = None, context: str | None = None) -> int:
    """The same bytes, N times. If Jev is deterministic and temperature-zero
    LLMs are not, that deserves its own section in the writeup.

    `ids` and `context` select the items; see `_select`. Without them this
    slices the capture file in append order, which is not a sample.
    """
    captures = _select(surface, limit=limit, ids=ids, context=context)
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
                  version: str | None = None, ids: list[str] | None = None,
                  context: str | None = None) -> int:
    """Every phrasing variant. If an arm is phrasing-insensitive while another
    is not, that is itself a result -- and it is why the baseline prompts are
    pre-registered."""
    version = version or cl.surface_question_version(surface)
    spec = cl.question_set(surface, version)
    phrasings = sorted({p for q in spec["questions"].values() for p in q["phrasings"]})
    captures = _select(surface, limit=limit, ids=ids, context=context)
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
                   version: str | None = None, ids: list[str] | None = None,
                   context: str | None = None) -> int:
    """How much of the state does each arm actually need?"""
    captures = _select(surface, limit=limit, ids=ids, context=context)
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
                  version: str | None = None, ids: list[str] | None = None,
                  context: str | None = None) -> int:
    captures = _select(surface, limit=limit, ids=ids, context=context)
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
    parser.add_argument("--ids", metavar="ID[,ID...]",
                        help="run over exactly these decision_ids, in this order. Without it a "
                             "sweep slices the capture file in APPEND ORDER, which is not a "
                             "sample: the first 50 today are 48 synthetic and 2 live by accident "
                             "of when rows were written.")
    parser.add_argument("--context", choices=("live", "synthetic", "canary", "replay"),
                        metavar="{live,synthetic,canary}",
                        help="restrict to captures with this run_context. PREREGISTRATION section "
                             "4 forbids pooling live with synthetic; a sweep that mixes them "
                             "yields a rate belonging to neither.")
    parser.add_argument("--seed-synthetic", metavar="SID[,SID...]",
                        help="write capture rows and states for these synthetic_ids (e.g. "
                             "syn-0000) and exit. ZERO API calls. Needed because --determinism "
                             "replays STORED captures and only the original stratified sample "
                             "was ever stored.")
    parser.add_argument("--estimate", action="store_true",
                        help="print the call count and projected cost, then exit")
    args = parser.parse_args()

    paths.ensure_dirs()
    names = args.arms.split(",") if args.arms else cl.arms_config()["enabled"]
    arms = [cl.arm(n.strip()) for n in names]
    rng = random.Random(args.seed)
    ids = [i.strip() for i in args.ids.split(",") if i.strip()] if args.ids else None

    if args.seed_synthetic:
        sids = [i.strip() for i in args.seed_synthetic.split(",") if i.strip()]
        written = seed_synthetic(args.surface, sids)
        print(f"captures available for {len(written)} synthetic item(s), 0 API calls:")
        for did in written:
            print(f"    {did}")
        return 0

    if args.estimate:
        synthetic_path = paths.DATA / "synthetic" / f"{args.surface}-v1.jsonl"
        n_syn = len(synthetic_path.read_text().splitlines()) if synthetic_path.exists() else 0
        # Honour the selection, or the estimate describes a different run than
        # the one about to be made -- which is how a 90-call budget becomes 360.
        n_cap = len(_select(args.surface, limit=args.limit, ids=ids, context=args.context))
        n_all = len([c for c in store.captures() if c["surface"] == args.surface])
        print(f"synthetic items : {n_syn}")
        print(f"stored captures : {n_all} ({n_cap} selected"
              + (f", --ids {len(ids)}" if ids else "")
              + (f", --context {args.context}" if args.context else "")
              + ")")
        print(f"arms            : {[a.name for a in arms]}")
        reps = args.determinism or 20
        print(f"\n--synthetic      -> {n_syn * len(arms):>6} calls")
        print(f"--decisions      -> {n_cap * len(arms):>6} calls")
        print(f"--determinism {reps:<2} -> {n_cap * len(arms) * reps:>6} calls")
        print(f"--phrasings      -> {n_cap * len(arms) * 3:>6} calls")
        print(f"--truncation     -> {n_cap * len(arms) * 3:>6} calls")
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
                               version=args.question_version, ids=ids, context=args.context)
    if args.determinism:
        total += run_determinism(arms, args.surface, args.determinism, args.limit, rng,
                                 version=args.question_version, ids=ids, context=args.context)
    if args.phrasings:
        total += run_phrasings(arms, args.surface, args.limit, rng,
                               version=args.question_version, ids=ids, context=args.context)
    if args.truncation:
        total += run_truncation(arms, args.surface, args.limit, rng,
                                version=args.question_version, ids=ids, context=args.context)

    if total == 0:
        parser.print_help()
        return 1
    print(f"wrote {total} run rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
