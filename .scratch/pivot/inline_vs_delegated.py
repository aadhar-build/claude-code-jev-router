#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Is delegating to a subagent cheaper or dearer than doing the work inline?

The pivot question, against THIS corpus, in answer to JEV-47's citation of
AqueGen/model-routing ($1.36 inline < $1.68 routed < $2.01 session-tier).

Nothing here reimplements costing. Every dollar comes from
`session_metrics.call_cost`, fed by `session_metrics.normalise_usage` and
`session_metrics.merge_copies`, over rows keyed by `session_metrics.dedupe_key`.
Component costs (fresh input / output / 5m write / 1h write / cache read) are
obtained by calling that same tested formula with every OTHER field zeroed, so
the split is exact by construction and cannot drift from the total.

Three things it computes.

1. **Per delegated task**, from `subagents/*.jsonl` + `*.meta.json`: total cost,
   the five cost components, the cold-start prefix write (the mechanism AqueGen
   blames), request count and attrition signals. Broken down by `agentType`.

2. **The counterfactual, as a BOUND and not a point estimate.** For a task of N
   subagent turns spawned when the main session's context was C_main tokens:

     penalty(delegating) = sub_prefix x write_multiplier(TTL of that row)
     saving(delegating)  = N x (C_main - sub_prefix) x cache_read_multiplier

   The cold prefix is a real write the subagent pays and inline would not (it is
   already cached in the main session). Against it, each of the N turns inline
   would have re-read the whole main context rather than the subagent's smaller
   one. Both terms are in tokens x the model's input rate, so `call_cost` prices
   them. `net = penalty - saving` is an UPPER BOUND on the delegation penalty,
   because it omits a third term that is not estimable here: inline, every
   subagent turn's output also bloats the main context for the whole REMAINDER
   of the session, and that saving accrues to delegation too.

   C_main is read from the main-transcript assistant request that carries the
   `tool_use` block whose id equals `meta.toolUseId` -- i.e. the turn that
   actually spawned the task. Tasks at spawnDepth > 1 have no such block in the
   main transcript and are reported with C_main unknown rather than guessed.

3. **How much the frozen JEV-24a record understates delegation.**
   `baseline.requests()` dedupes on `requestId` alone keeping the FIRST copy and
   never reads `iterations[]`. PREREGISTRATION A8.2b: all 48 keys that grow
   across copies are inside SUBAGENT transcripts. The frozen rule is re-run here
   beside the corrected one over the identical files, and the gap is reported.

Bounds on everything below, all pre-existing and all documented:
  * FINDINGS.md Part 1 (1.4): transcript-derived cost runs ~27.6% UNDER Claude
    Code's own total. Every figure here is a LOWER BOUND.
  * JEV-55: this corpus is effectively ONE session. No CI is computed and none
    should be. Descriptives only.
  * JEV-49: the ~2,005 run rows in data/runs cannot carry these corrections and
    are not used. Only transcripts are read.
  * Amendment 8: subscription auth, 1-hour TTL at 2x, read PER ROW, never
    inferred from the auth path.

Read-only. Writes nothing outside its own --out path.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
REPO = HERE.parent.parent.parent
sys.path.insert(0, str(REPO / "src"))

import config_loader as cl  # noqa: E402
import session_metrics as sm  # noqa: E402

# The five mutually exclusive cost components. Keys are the fields
# `call_cost` consumes; zeroing all but one isolates that one's price.
COMPONENTS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "ephemeral_5m_input_tokens",
    "ephemeral_1h_input_tokens",
)


def component_costs(model: str, usage: dict[str, Any]) -> dict[str, float] | None:
    """Price each component alone, through the one tested formula.

    `call_cost` expects the TTL split beside `cache_creation_input_tokens`; when
    isolating a TTL bucket the scalar must be set to that bucket's size, since
    the scalar is what carries the write into `cl.cost_usd` and the 1h field
    only supplies the multiplier uplift.
    """
    if model not in cl.pricing()["models"]:
        return None
    out: dict[str, float] = {}
    for field in COMPONENTS:
        iso = {k: 0 for k in
               sm.SCALAR_TOKEN_FIELDS + sm.SCALAR_CACHE_FIELDS + sm.TTL_FIELDS}
        n = usage.get(field, 0) or 0
        if field in sm.TTL_FIELDS:
            iso["cache_creation_input_tokens"] = n
            iso[field] = n
        else:
            iso[field] = n
        out[field] = sm.call_cost(model, iso) or 0.0
    return out


def walk(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deduplicated, normalised, copy-merged billable requests of ONE file.

    The full `session_metrics` rule set: dedupe on (requestId, message.id),
    normalise `iterations[]` asymmetrically, fold every copy by per-field max so
    the COMPLETED copy wins. Returns requests in first-seen order plus counters.
    """
    merged: dict[tuple, dict[str, Any]] = {}
    key_model: dict[tuple, str] = {}
    key_ts: dict[tuple, Any] = {}
    order: list[tuple] = []
    flags = Counter()

    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                line = json.loads(raw)
            except json.JSONDecodeError:
                continue
            message = line.get("message") or {}
            if message.get("role") == "user":
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_result" \
                            and block.get("is_error"):
                        flags["tool_errors"] += 1
                body = sm._text_of(message.get("content"))
                if sm.DENIAL_MARKER in body:
                    flags["permission_denials"] += 1
                if any(mk in body for mk in sm.INTERRUPT_MARKERS):
                    flags["interruptions"] += 1
                continue
            if message.get("role") != "assistant":
                continue
            key = sm.dedupe_key(line)
            if key is None:
                continue
            if key not in merged:
                order.append(key)
                key_ts[key] = line.get("timestamp")
            key_model[key] = message.get("model") or "unknown"
            n = sm.normalise_usage(message.get("usage") or {})
            if n.get("ttl_split_repaired"):
                flags["ttl_splits_repaired"] += 1
            merged[key] = sm.merge_copies(merged.get(key), n)
            flags["copies"] += 1

    reqs = [{"model": key_model[k], "usage": merged[k], "ts": key_ts[k]} for k in order]
    return reqs, dict(flags)


def frozen_rule_cost(path: Path) -> float:
    """`src/baseline.py:requests()` exactly: first copy wins, no iterations[]."""
    seen: set[str] = set()
    total = 0.0
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                line = json.loads(raw)
            except json.JSONDecodeError:
                continue
            message = line.get("message") or {}
            if message.get("role") != "assistant":
                continue
            rid = line.get("requestId")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            u = message.get("usage") or {}
            bucket = {k: (u.get(k, 0) or 0) for k in
                      sm.SCALAR_TOKEN_FIELDS + sm.SCALAR_CACHE_FIELDS}
            c = cl.cost_usd(message.get("model") or "unknown", bucket)
            total += c if c is not None else 0.0
    return total


def spawn_contexts(main: Path) -> dict[str, dict[str, Any]]:
    """toolUseId -> the main session's context size at the moment it spawned.

    The spawning turn is the assistant request whose content carries a
    `tool_use` block with that id. Its own usage describes the context Claude
    was holding: cache_read + cache_creation + fresh input. That is C_main, the
    number each of N inline turns would have had to re-read.
    """
    out: dict[str, dict[str, Any]] = {}
    with main.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                line = json.loads(raw)
            except json.JSONDecodeError:
                continue
            message = line.get("message") or {}
            if message.get("role") != "assistant":
                continue
            ids = [b.get("id") for b in (message.get("content") or [])
                   if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")]
            if not ids:
                continue
            # C_main must be the context of ONE round trip, not the turn's
            # total. `cache_read_input_tokens` at top level is the SUM across
            # `iterations[]` (session_metrics.normalise_usage documents this),
            # so a 3-iteration turn reports ~3x the real context -- which is
            # how a 431K figure appears against a 200K window. Take the single
            # largest iteration where iterations exist. This is deliberately
            # the conservative direction: a smaller C_main shrinks the saving
            # attributed to delegation.
            raw_u = message.get("usage") or {}
            iters = raw_u.get("iterations") or []
            def _ctx(d: dict[str, Any]) -> int:
                return ((d.get("cache_read_input_tokens", 0) or 0)
                        + (d.get("cache_creation_input_tokens", 0) or 0)
                        + (d.get("input_tokens", 0) or 0))
            ctx = max((_ctx(i) for i in iters), default=0) if iters else _ctx(raw_u)
            for tid in ids:
                prev = out.get(tid)
                # several copies of the spawning turn stream; keep the largest
                if prev is None or ctx > prev["context_tokens"]:
                    out[tid] = {"context_tokens": ctx,
                                "model": message.get("model") or "unknown"}
    return out


def analyse_task(sub: Path, ctx_by_tool_use: dict[str, dict[str, Any]]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    try:
        meta = json.loads(sub.with_suffix(".meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        pass

    reqs, flags = walk(sub)
    per_component = Counter()
    total = 0.0
    tokens = Counter()
    models = Counter()
    unpriced = 0
    unpriced_models: set[str] = set()

    for r in reqs:
        models[r["model"]] += 1
        for f in COMPONENTS + ("cache_creation_input_tokens",):
            tokens[f] += r["usage"].get(f, 0) or 0
        comp = component_costs(r["model"], r["usage"])
        if comp is None:
            unpriced += 1
            unpriced_models.add(r["model"])
            continue
        for k, v in comp.items():
            per_component[k] += v
        total += sm.call_cost(r["model"], r["usage"]) or 0.0

    # The cold start: the FIRST request's cache write is the prefix the subagent
    # had to lay down because it began with empty context.
    prefix_tokens = 0
    prefix_cost = 0.0
    prefix_ttl = None
    if reqs:
        f0 = reqs[0]
        prefix_tokens = f0["usage"].get("cache_creation_input_tokens", 0) or 0
        c0 = component_costs(f0["model"], f0["usage"])
        if c0 is not None:
            prefix_cost = c0["ephemeral_5m_input_tokens"] + c0["ephemeral_1h_input_tokens"]
        prefix_ttl = ("1h" if (f0["usage"].get("ephemeral_1h_input_tokens", 0) or 0) > 0
                      else ("5m" if prefix_tokens else None))

    tool_use_id = meta.get("toolUseId")
    spawn = ctx_by_tool_use.get(tool_use_id) if tool_use_id else None

    # Counterfactual terms, priced through call_cost on the SPAWNING model.
    saving = None
    net = None
    c_main = None
    breakeven_k = None
    spawn_model = None
    if spawn and reqs:
        c_main = spawn["context_tokens"]
        spawn_model = spawn["model"]
        extra_read = max(0, c_main - prefix_tokens) * len(reqs)
        iso = {k: 0 for k in
               sm.SCALAR_TOKEN_FIELDS + sm.SCALAR_CACHE_FIELDS + sm.TTL_FIELDS}
        iso["cache_read_input_tokens"] = extra_read
        saving = sm.call_cost(spawn["model"], iso)
        if saving is not None:
            net = prefix_cost - saving
            # Break-even turn ratio. If inline finishes the SAME task in a
            # fraction k of the subagent's N turns, its whole bill scales with
            # k -- output, reads and writes alike -- not just the extra context
            # re-reads. So inline(k) ~= k * inline(1), where
            # inline(1) = D - penalty + saving, and delegation stops being
            # cheaper below k* = D / inline(1).
            inline_same_n = total - prefix_cost + saving
            breakeven_k = (total / inline_same_n) if inline_same_n > 0 else None

    return {
        "agent_file": sub.name,
        "agent_type": meta.get("agentType"),
        "spawn_depth": meta.get("spawnDepth"),
        "request_shape": meta.get("requestShape"),
        "requests": len(reqs),
        "models": dict(models),
        "unpriced_requests": unpriced,
        "unpriced_models": sorted(unpriced_models),
        "cost_usd": round(total, 6),
        "cost_frozen_rule_usd": round(frozen_rule_cost(sub), 6),
        "components_usd": {k: round(v, 6) for k, v in per_component.items()},
        "tokens": dict(tokens),
        "cold_start_prefix_tokens": prefix_tokens,
        "cold_start_prefix_usd": round(prefix_cost, 6),
        "cold_start_ttl": prefix_ttl,
        "main_context_at_spawn_tokens": c_main,
        "spawn_model": spawn_model,
        "counterfactual_saving_usd": None if saving is None else round(saving, 6),
        "counterfactual_net_usd": None if net is None else round(net, 6),
        "counterfactual_inline_same_n_usd": None if saving is None else round(
            total - prefix_cost + saving, 6),
        "breakeven_turn_ratio": None if breakeven_k is None else round(breakeven_k, 4),
        "flags": flags,
    }


def descriptives(values: list[float]) -> dict[str, Any]:
    """No CI. JEV-55: one cluster. These are descriptives, not inference."""
    if not values:
        return {"n": 0}
    s = sorted(values)
    return {
        "n": len(s),
        "min": round(s[0], 6),
        "p25": round(s[max(0, len(s) // 4)], 6),
        "median": round(statistics.median(s), 6),
        "p75": round(s[min(len(s) - 1, (3 * len(s)) // 4)], 6),
        "max": round(s[-1], 6),
        "mean": round(statistics.fmean(s), 6),
        "sum": round(sum(s), 6),
    }


def coverage(main: Path, computed: float) -> dict[str, Any]:
    """Computed total against Claude Code's own cost-state, if it wrote one."""
    reported = None
    try:
        with main.open("r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                if '"cost-state"' not in raw:
                    continue
                try:
                    line = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if line.get("type") == "cost-state":
                    reported = line.get("totalCostUSD")
    except OSError:
        pass
    return {
        "reported_cost_usd": reported,
        "computed_cost_usd": round(computed, 6),
        "ratio": None if not reported else round(computed / reported, 4),
    }


def run(project_dir: Path, label: str) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []

    for main in sorted(project_dir.glob("*.jsonl")):
        subs = sorted((main.with_suffix("") / "subagents").glob("*.jsonl"))
        main_reqs, _ = walk(main)
        main_cost = 0.0
        main_tokens = Counter()
        main_unpriced = 0
        for r in main_reqs:
            c = sm.call_cost(r["model"], r["usage"])
            if c is None:
                main_unpriced += 1
                continue
            main_cost += c
            for f in COMPONENTS:
                main_tokens[f] += r["usage"].get(f, 0) or 0
        if not subs and not main_reqs:
            continue
        ctx = spawn_contexts(main) if subs else {}
        mine = [analyse_task(s, ctx) for s in subs]
        tasks.extend(mine)
        deleg = sum(t["cost_usd"] for t in mine)
        sessions.append({
            "session_id": main.stem,
            "main_requests": len(main_reqs),
            "main_cost_usd": round(main_cost, 6),
            "main_unpriced_requests": main_unpriced,
            "main_tokens": dict(main_tokens),
            "delegated_tasks": len(mine),
            "delegated_cost_usd": round(deleg, 6),
            "delegated_cost_frozen_rule_usd": round(
                sum(t["cost_frozen_rule_usd"] for t in mine), 6),
            "coverage": coverage(main, main_cost + deleg),
        })

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in tasks:
        by_type[t["agent_type"] or "unknown"].append(t)

    def roll(group: list[dict[str, Any]]) -> dict[str, Any]:
        comp = Counter()
        for t in group:
            for k, v in t["components_usd"].items():
                comp[k] += v
        tot = sum(t["cost_usd"] for t in group)
        writes = comp["ephemeral_5m_input_tokens"] + comp["ephemeral_1h_input_tokens"]
        nets = [t["counterfactual_net_usd"] for t in group
                if t["counterfactual_net_usd"] is not None]
        return {
            "tasks": len(group),
            "cost_usd": descriptives([t["cost_usd"] for t in group]),
            "requests": descriptives([float(t["requests"]) for t in group]),
            "total_usd": round(tot, 6),
            "components_usd": {k: round(v, 6) for k, v in comp.items()},
            "cache_write_share": None if not tot else round(writes / tot, 4),
            "cache_read_share": None if not tot else round(
                comp["cache_read_input_tokens"] / tot, 4),
            "cold_start_prefix_usd_total": round(
                sum(t["cold_start_prefix_usd"] for t in group), 6),
            "cold_start_share_of_cost": None if not tot else round(
                sum(t["cold_start_prefix_usd"] for t in group) / tot, 4),
            "cold_start_prefix_tokens": descriptives(
                [float(t["cold_start_prefix_tokens"]) for t in group]),
            "counterfactual_net_usd": descriptives(nets),
            "counterfactual_resolvable": len(nets),
            "inline_same_n_usd_total": round(sum(
                t["counterfactual_inline_same_n_usd"] for t in group
                if t["counterfactual_inline_same_n_usd"] is not None), 6),
            "breakeven_turn_ratio": descriptives(
                [t["breakeven_turn_ratio"] for t in group
                 if t["breakeven_turn_ratio"] is not None]),
            "spawn_models": dict(Counter(
                t["spawn_model"] for t in group if t["spawn_model"])),
            "ttl_of_cold_start": dict(Counter(t["cold_start_ttl"] for t in group)),
            "single_request_tasks": sum(1 for t in group if t["requests"] <= 1),
            "tool_errors": sum(t["flags"].get("tool_errors", 0) for t in group),
            "interruptions": sum(t["flags"].get("interruptions", 0) for t in group),
            "permission_denials": sum(t["flags"].get("permission_denials", 0) for t in group),
            "unpriced_requests": sum(t["unpriced_requests"] for t in group),
        }

    frozen = sum(t["cost_frozen_rule_usd"] for t in tasks)
    corrected = sum(t["cost_usd"] for t in tasks)

    return {
        "label": label,
        "project_dir": str(project_dir),
        "pricing_version": cl.pricing()["version"],
        "sessions_with_activity": len(sessions),
        "delegated_tasks": len(tasks),
        "overall": roll(tasks),
        "by_agent_type": {k: roll(v) for k, v in sorted(by_type.items())},
        "frozen_vs_corrected": {
            "delegated_cost_frozen_rule_usd": round(frozen, 6),
            "delegated_cost_corrected_usd": round(corrected, 6),
            "understatement_usd": round(corrected - frozen, 6),
            "understatement_pct": None if not corrected else round(
                100.0 * (corrected - frozen) / corrected, 2),
        },
        "sessions": sessions,
        "tasks": tasks,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=HERE.parent / "inline-vs-delegated.json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    base = Path.home() / ".claude" / "projects"
    targets = [
        (base / "-Users-aadharagarwal-projects-JEV-experiments", "main-project"),
        (base / "-Users-aadharagarwal-projects-JEV-experiments--claude-worktrees-jev-critical-path",
         "worktree-post-pivot"),
    ]
    result = {
        "schema": "inline-vs-delegated-v1",
        "caveats": [
            "LOWER BOUND: FINDINGS.md Part 1.4 -- transcript-derived cost runs ~27.6% under Claude Code's own total.",
            "NO CI: JEV-55 -- this corpus is effectively one session. Descriptives only.",
            "Run rows in data/runs are NOT used: JEV-49 says the corrections are inapplicable to them.",
            "Cache-write TTL read per row (Amendment 8 A8.2), never inferred from the auth path.",
        ],
        "corpora": [run(d, label) for d, label in targets if d.is_dir()],
    }
    args.out.write_text(json.dumps(result, indent=2))
    if not args.quiet:
        for c in result["corpora"]:
            o = c["overall"]
            print(f"\n=== {c['label']}  ({c['delegated_tasks']} delegated tasks) ===")
            print(f"  total delegated  ${o['total_usd']}")
            print(f"  per task         median ${o['cost_usd'].get('median')} "
                  f"[{o['cost_usd'].get('min')} .. {o['cost_usd'].get('max')}]")
            print(f"  components       {o['components_usd']}")
            print(f"  cache-write share {o['cache_write_share']}  "
                  f"cold-start share {o['cold_start_share_of_cost']}")
            print(f"  counterfactual net (delegated - inline), upper bound on penalty:")
            print(f"                   {o['counterfactual_net_usd']}  "
                  f"resolvable {o['counterfactual_resolvable']}/{c['delegated_tasks']}")
            print(f"  frozen-rule gap  {c['frozen_vs_corrected']}")
            for t, r in c["by_agent_type"].items():
                print(f"    {t:22s} n={r['tasks']:3d}  total ${r['total_usd']:<10} "
                      f"median ${r['cost_usd'].get('median')}  "
                      f"cold-start {r['cold_start_share_of_cost']}")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
