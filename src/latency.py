#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-43. Decomposing `cc_*` wall-clock into the clocks that belong to the
study and the clocks that belong to the operator's machine.

This module is arithmetic over rows. It computes no statistics that
`src/analyze.py` computes, and it is not a second analysis entry point: it
answers one question -- how much of a `cc_*` row's `total_ms` is the arm, and
how much is the environment the arm happened to be spawned into.

THE THREE CLOCKS
----------------
A `cc_*` row carries two independent measurements of the same event, one taken
outside the subprocess and one taken inside it, and the difference between them
is the whole ticket:

    total_ms      our own Clock, in arms/claude_cli.evaluate, wrapping
                  subprocess.run. Covers everything: fork/exec, Node startup,
                  Claude Code's config + plugin load, the session, teardown.
    duration_ms   Claude Code's own report of how long the session took, from
                  the CLI's JSON output. Starts after the CLI has booted.
    duration_api_ms
                  Claude Code's report of time spent in the Anthropic API.

Hence

    spawn_ms      = total_ms - duration_ms        process + CLI startup/teardown
    in_session_ms = duration_ms - duration_api_ms in-session non-API work
    api_ms        = duration_api_ms               the model call itself

and the three sum to `total_ms` exactly, by construction.

WHAT LIVES IN EACH, AND WHO OWNS IT
-----------------------------------
`api_ms` is clean. It is the only clock on a `cc_*` row that contains nothing
of the operator's machine, and it is the quantity that is comparable with
`jev`'s `total_ms` (both are one HTTP round trip to a model).

`in_session_ms` is a mixture: Claude Code's ~5.2K-token preamble, the tool
round trip, AND every hook the operator's `~/.claude` registers -- SessionStart
hooks at the top, Stop hooks at the bottom, all of them inside Claude Code's
own clock. This is where the JEV-43 contamination lands.

`spawn_ms` is also a mixture. Node startup and our own fork/exec belong to the
study; loading the operator's settings, marketplace list and plugin manifests
happens before Claude Code starts its own clock and does not. The two are not
separable from a row, so `spawn_ms` is reported as a bounded quantity and never
as a clean one.

THE CONTAMINATION, AND WHY EXCLUSION IS DEFENSIBLE
--------------------------------------------------
`in_session_ms` over the 2026-09-20 corpus is sharply bimodal: 1,255 of 1,322
successful `cc_*` rows below 1.24s, **zero rows between 1.24s and 18.53s**, and 67
rows in a tight band at 18.5-22.0s. A gap with no mass in it is not a tail; it
is a second process. The classifier here therefore does not tune a threshold --
it cuts inside a hole, and `is_contaminated` is invariant to where in the hole
you cut. `empirical_gap` exists so that a future corpus which fills the hole in
invalidates the method loudly instead of silently.

The second mode is identified, not bounded: see `reports/jev43-wallclock.md`.

USAGE NOTES THAT ARE EASY TO GET WRONG
--------------------------------------
- Group by `(arm, arm_config_id)` and condition on `arm_dispatch`. `cc_haiku45`
  spans two `arm_config_id` eras whose latency does not pool, and concurrent
  dispatch contends for CPU. `arm` alone is not a grouping key.
- `ok=False` rows carry no timing. Every function here refuses them rather
  than coercing them to zero.
- `jev` rows have no `duration_ms` and cannot be decomposed. `decompose`
  raises; `adjusted_total_ms` passes them through untouched.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Iterable

# The cut. Any value strictly inside the empirical gap gives identical
# classification -- see tests/test_latency.py::TestContaminationClassifier.
# 5s is the middle of nothing in particular, which is the point.
CONTAMINATION_FLOOR_MS = 5_000.0

CC_PREFIX = "cc_"


class LatencyError(ValueError):
    """A row cannot be decomposed. Never returns zeros in place of this."""


@dataclass(frozen=True)
class Decomposition:
    total_ms: float
    spawn_ms: float
    in_session_ms: float
    api_ms: float


@dataclass(frozen=True)
class Gap:
    """The empty interval between the clean mode and the contaminated mode."""
    below: float | None
    above: float | None
    width_ms: float | None


def is_cc(row: dict[str, Any]) -> bool:
    return str(row.get("arm", "")).startswith(CC_PREFIX)


def group_key(row: dict[str, Any]) -> tuple[str, str]:
    return (row["arm"], row["arm_config_id"])


def decompose(row: dict[str, Any]) -> Decomposition:
    """Split a successful `cc_*` row's wall-clock into the three clocks."""
    if not is_cc(row):
        raise LatencyError(
            f"{row.get('arm')!r} has no subprocess and no in-session clock; "
            "only cc_* rows decompose"
        )
    if not row.get("ok"):
        raise LatencyError("row is ok=False and carries no timing")
    timing = row.get("timing_ms") or {}
    raw = row.get("raw") or {}
    total = timing.get("total_ms")
    duration = raw.get("duration_ms")
    api = raw.get("duration_api_ms")
    for name, value in (("timing_ms.total_ms", total),
                        ("raw.duration_ms", duration),
                        ("raw.duration_api_ms", api)):
        if value is None:
            raise LatencyError(f"row is missing {name}")
    return Decomposition(
        total_ms=float(total),
        spawn_ms=float(total) - float(duration),
        in_session_ms=float(duration) - float(api),
        api_ms=float(api),
    )


def is_contaminated(in_session_ms: float,
                    floor_ms: float = CONTAMINATION_FLOOR_MS) -> bool:
    """True iff this row's in-session residual sits in the second mode."""
    return in_session_ms >= floor_ms


def empirical_gap(values: Iterable[float],
                  floor_ms: float = CONTAMINATION_FLOOR_MS) -> Gap:
    """The observed hole the classifier cuts inside.

    `below` is the largest clean value, `above` the smallest contaminated one.
    A narrow or zero width means the bimodality has gone and exclusion is no
    longer justified by a gap -- which the report is required to say out loud.
    """
    clean = [v for v in values if not is_contaminated(v, floor_ms)]
    dirty = [v for v in values if is_contaminated(v, floor_ms)]
    below = max(clean) if clean else None
    above = min(dirty) if dirty else None
    width = (above - below) if (below is not None and above is not None) else None
    return Gap(below=below, above=above, width_ms=width)


def clean_baselines(rows: Iterable[dict[str, Any]],
                    floor_ms: float = CONTAMINATION_FLOOR_MS,
                    ) -> dict[tuple[str, str], float]:
    """Median uncontaminated `in_session_ms`, per `(arm, arm_config_id)`.

    This is what an in-session residual *should* cost in this harness: the
    preamble, the tool round trip, and whatever fast hooks always fire. It is
    the subtrahend for the adjustment, not zero -- subtracting the whole
    residual would credit the arm with time it genuinely spent.

    Deliberately keyed on `(arm, arm_config_id)` only, and so pooled across
    `run_context` and `arm_dispatch`: this is a property of the configuration,
    the clean distribution is tight (p95 under 0.62s everywhere), and a
    per-context baseline would be estimated from very few rows in the thin
    contexts. `summarise` reports per-context distributions; this does not.
    """
    buckets: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        if not is_cc(row) or not row.get("ok"):
            continue
        try:
            d = decompose(row)
        except LatencyError:
            continue
        if is_contaminated(d.in_session_ms, floor_ms):
            continue
        buckets.setdefault(group_key(row), []).append(d.in_session_ms)
    return {k: quantile(v, 0.5) for k, v in buckets.items() if v}


def adjusted_total_ms(row: dict[str, Any],
                      baselines: dict[tuple[str, str], float],
                      floor_ms: float = CONTAMINATION_FLOOR_MS) -> float:
    """`total_ms` with the contaminated mode's excess removed.

    Identity on clean rows and on every non-`cc_*` arm. On a contaminated row
    it removes `in_session_ms - baseline`, i.e. the excess over what this arm's
    in-session residual normally costs -- leaving the ordinary residual in
    place. Falls back to removing nothing if no baseline exists for the group,
    because a missing baseline is not evidence of zero.
    """
    timing = row.get("timing_ms") or {}
    total = timing.get("total_ms")
    if total is None:
        raise LatencyError("row is missing timing_ms.total_ms")
    total = float(total)
    if not is_cc(row) or not row.get("ok"):
        return total
    try:
        d = decompose(row)
    except LatencyError:
        return total
    if not is_contaminated(d.in_session_ms, floor_ms):
        return total
    base = baselines.get(group_key(row))
    if base is None:
        return total
    return total - (d.in_session_ms - base)


def dispatch_walls(rows: Iterable[dict[str, Any]],
                   baselines: dict[tuple[str, str], float],
                   adjusted: bool = True,
                   floor_ms: float = CONTAMINATION_FLOOR_MS,
                   ) -> dict[str, float]:
    """Per-decision wall clock, recomputed as the max over arms.

    `dispatch_wall_ms` as stored is t0-to-last-arm-finishing. It is a **max**,
    so a single contaminated arm inflates the whole decision by the full
    residual -- which is why JEV-33's concurrent figure moves and its serial
    per-arm medians do not. Recomputed here from `dispatch_offset_ms +
    total_ms` so the adjustment can propagate into it.

    Rows with `ok=False` contribute nothing: they have no timing, and a failed
    arm did not hold the decision open in any recoverable way.

    **Concurrent-era rows only.** `dispatch_offset_ms` is written inside
    `_dispatch`'s pool callable and is absent on serial rows, where it
    defaults to 0 here -- so on a serial decision this returns a max where
    the truth is a sum. Filter to `arm_dispatch == "concurrent"` before
    calling, as the report does.
    """
    walls: dict[str, float] = {}
    for row in rows:
        if not row.get("ok"):
            continue
        timing = row.get("timing_ms") or {}
        if timing.get("total_ms") is None:
            continue
        offset = row.get("dispatch_offset_ms") or 0.0
        total = (adjusted_total_ms(row, baselines, floor_ms) if adjusted
                 else float(timing["total_ms"]))
        did = row["decision_id"]
        end = float(offset) + total
        if end > walls.get(did, -math.inf):
            walls[did] = end
    return walls


def quantile(values: Iterable[float], p: float) -> float | None:
    """Linear-interpolated quantile. `None` on empty -- never 0."""
    v = sorted(values)
    if not v:
        return None
    if len(v) == 1:
        return v[0]
    i = (len(v) - 1) * p
    lo = int(math.floor(i))
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def _dist(values: list[float]) -> dict[str, Any]:
    v = sorted(values)
    return {
        "n": len(v),
        "min": v[0] if v else None,
        "p50": quantile(v, 0.5),
        "p90": quantile(v, 0.90),
        "p95": quantile(v, 0.95),
        "p99": quantile(v, 0.99),
        "max": v[-1] if v else None,
        "mean": (sum(v) / len(v)) if v else None,
    }


def summarise(rows: Iterable[dict[str, Any]],
              floor_ms: float = CONTAMINATION_FLOOR_MS,
              ) -> dict[tuple[str, str, str | None, str], dict[str, Any]]:
    """Decomposition and contamination, per
    `(arm, arm_config_id, arm_dispatch, run_context)`.

    The four-way key is deliberate, and every part of it has bitten something:

    - `arm_config_id` -- `cc_haiku45` spans two configurations whose latency
      does not pool (JEV-41 turned its thinking off mid-window).
    - `arm_dispatch` -- serial and concurrent spawns contend differently.
    - `run_context` -- CONTEXT.md: "never pooled across values". A `replay`
      row is the same arm on a re-sent state and usually a quieter machine.
      `data/runs/` is append-only and shared: the JEV-16 determinism sweep
      writes `replay` rows into the very file this report reads.
    """
    rows = list(rows)
    baselines = clean_baselines(rows, floor_ms)
    groups: dict[tuple[str, str, str | None, str], list[Decomposition]] = {}
    for row in rows:
        if not is_cc(row) or not row.get("ok"):
            continue
        try:
            d = decompose(row)
        except LatencyError:
            continue
        key = (row["arm"], row["arm_config_id"], row.get("arm_dispatch"),
               row.get("run_context") or "unknown")
        groups.setdefault(key, []).append(d)

    out: dict[tuple[str, str, str | None, str], dict[str, Any]] = {}
    for key, ds in groups.items():
        dirty = [d for d in ds if is_contaminated(d.in_session_ms, floor_ms)]
        clean = [d for d in ds if not is_contaminated(d.in_session_ms, floor_ms)]
        gap = empirical_gap([d.in_session_ms for d in ds], floor_ms)
        out[key] = {
            "arm": key[0],
            "arm_config_id": key[1],
            "arm_dispatch": key[2],
            "run_context": key[3],
            "n": len(ds),
            "n_contaminated": len(dirty),
            "contamination_rate": len(dirty) / len(ds) if ds else 0.0,
            "clean_baseline_in_session_ms": baselines.get((key[0], key[1])),
            "gap": {"below": gap.below, "above": gap.above, "width_ms": gap.width_ms},
            "total_ms": _dist([d.total_ms for d in ds]),
            "spawn_ms": _dist([d.spawn_ms for d in ds]),
            "in_session_ms": _dist([d.in_session_ms for d in ds]),
            "api_ms": _dist([d.api_ms for d in ds]),
            "clean_in_session_ms": _dist([d.in_session_ms for d in clean]),
            "clean_total_ms": _dist([d.total_ms for d in clean]),
        }
    return out


def load_rows(path) -> list[dict[str, Any]]:
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
