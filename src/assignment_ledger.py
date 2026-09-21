"""The assignment ledger, the circuit breaker's state, and the honesty check.

Three things live here because they are three views of one record.

1. THE LEDGER (`data/agent_route/assignments/<date>.jsonl`)
   Written by `hooks/agent_route_actuator.sh` **before** the spawn, never after.
   A ledger written afterwards is missing exactly when it matters most: when the
   task crashed. Each row carries the decision, the tier, the rule that fired
   verbatim, the fingerprint of the rule table, and the model the caller
   originally asked for -- the five things without which an outcome observed an
   hour later cannot be attributed to anything.

2. THE BREAKER (`data/agent_route/breaker.jsonl`)
   Fail-to-frontier protects quality on the error path and does not protect
   cost: a sustained failure silently bills frontier rates for as long as it
   lasts. The breaker bounds that. It is an APPEND-ONLY OUTCOME LOG, not a
   counter file, and that is not a style choice: parallel `Agent` spawns are the
   normal case in this harness, and a read-modify-write counter loses
   increments under exactly the conditions that matter. One short line per
   outcome, appended with O_APPEND and well under PIPE_BUF, interleaves cleanly
   -- the property `hooks/capture.sh` already relies on.

   State is derived, never stored: *are the last N outcomes all failures, and is
   the newest of them inside the TTL?* Half-open falls out for free. Past the
   TTL the newest failure is stale, one attempt is allowed through, and that
   attempt's own outcome line decides what happens next. No lock, no second
   file, no reset step that can be forgotten.

3. THE VERIFIER
   **Verify against `resolvedModel`, not against what you asked for.** Asking
   for a model and getting it are different events, and an `availableModels`
   allowlist, a `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`, or a plain typo makes a
   silently-ignored assignment look identical to a control-arm spawn. The
   comparison is a PREFIX match against `tiers[...].resolved_prefix`, because
   `resolvedModel` is a full and sometimes dated, sometimes suffixed id --
   `claude-haiku-4-5-20251001`, `claude-opus-5[1m]` -- while the hook emits a
   bare alias (`haiku`). Equality would report every honoured assignment as a
   mismatch.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import tier_map

ASSIGNMENTS_DIR = tier_map.AGENT_ROUTE_DIR / "assignments"
BREAKER_LOG = tier_map.AGENT_ROUTE_DIR / "breaker.jsonl"

#: The sticky marker the hook drops when the breaker opens, so the condition is
#: visible to `doctor.py` and to a human reading the tree, not only to whoever
#: happens to be watching a session transcript at the time.
BREAKER_MARKER = tier_map.AGENT_ROUTE_DIR / "BREAKER-OPEN"

LEDGER_SCHEMA = "agent-route-assignment-v1"


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def ledger_row(
    decision: tier_map.Decision,
    *,
    timestamp: str,
    session_id: str,
    tool_use_id: str,
    config_sha256: str,
    config_version: str,
    hook_ms: float | None = None,
) -> dict:
    """The row the hook writes before the spawn. Also the schema the jq writes.

    Kept in Python as well as in `jq` so a test can assert the two produce the
    same keys -- the drift hazard `state_builders` vs the inline hook already
    demonstrated.
    """
    return {
        "schema": LEDGER_SCHEMA,
        "timestamp": timestamp,
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "subagent_type": decision.subagent_type,
        "decision": decision.outcome,
        "tier": decision.tier,
        "assigned_alias": decision.alias,
        "rule": decision.rule,
        "original_model": decision.original_model,
        "config_version": config_version,
        "config_sha256": config_sha256,
        "hook_ms": hook_ms,
    }


def read_ledger(directory: Path | None = None) -> list[dict]:
    directory = directory or ASSIGNMENTS_DIR
    rows: list[dict] = []
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # A torn line is attrition, not a crash. Counted by the caller
                # if it cares; never a reason to lose the rows either side.
                continue
    return rows


# ---------------------------------------------------------------------------
# Breaker
# ---------------------------------------------------------------------------

def breaker_outcomes(path: Path | None = None) -> list[dict]:
    path = path or BREAKER_LOG
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def breaker_state(
    config: dict,
    path: Path | None = None,
    now: float | None = None,
) -> dict:
    """Derive breaker state from the append-only outcome log.

    Open iff the last `max_consecutive_failures` outcomes are ALL failures and
    the newest one is inside `ttl_s`. Deriving rather than storing means there
    is no state to get stuck: the log is the truth, and a single success line
    closes the breaker without anyone having to remember to clear a file.
    """
    settings = config.get("breaker") or {}
    n = int(settings.get("max_consecutive_failures", 3))
    ttl = float(settings.get("ttl_s", 900))
    now = time.time() if now is None else now

    outcomes = breaker_outcomes(path)
    # Parallel spawns append in completion order, not start order, so the log is
    # only approximately sorted. Sort by the timestamp each writer stamped.
    outcomes.sort(key=lambda r: r.get("ts", 0))
    tail = outcomes[-n:] if n > 0 else []

    consecutive = 0
    for row in reversed(outcomes):
        if row.get("ok"):
            break
        consecutive += 1

    newest_ts = float(outcomes[-1].get("ts", 0)) if outcomes else 0.0
    fresh = (now - newest_ts) < ttl if outcomes else False

    open_ = bool(n > 0 and len(tail) == n and consecutive >= n and fresh)
    return {
        "open": open_,
        "consecutive_failures": consecutive,
        "threshold": n,
        "ttl_s": ttl,
        "newest_ts": newest_ts,
        "age_s": (now - newest_ts) if outcomes else None,
        # Distinguished on purpose: "we are past the TTL with N failures behind
        # us" is half-open, and the next attempt is a probe whose outcome line
        # decides. Reporting it as plain "closed" would hide a real condition.
        "half_open": bool(n > 0 and consecutive >= n and not fresh and outcomes),
        "last_error": next(
            (r.get("error") for r in reversed(outcomes) if not r.get("ok")), None),
    }


# ---------------------------------------------------------------------------
# Verification against resolvedModel
# ---------------------------------------------------------------------------

def verify(rows: list[dict], resolved: dict[str, str], config: dict) -> dict:
    """Join assignments to what actually ran.

    `resolved` is {tool_use_id: resolvedModel}, read from wherever the truth
    happens to live -- a `PostToolUse` echo or a transcript. This function does
    not fetch it, so it stays testable with fakes and costs no API call.

    Four classes, and the interesting one is `overridden`:
      * honoured  -- resolvedModel starts with the tier's resolved_prefix
      * overridden-- we rewrote, something else won. THE ONE THAT MATTERS: an
                     overridden assignment makes the treatment arm identical to
                     the control arm while still looking like a treatment.
      * unobserved-- we rewrote and never saw a resolvedModel. Attrition, and
                     counted as such rather than assumed honoured.
      * not_routed-- we deliberately left the input alone. Not a failure.
    """
    tiers = config.get("tiers") or {}
    summary = {"honoured": 0, "overridden": 0, "unobserved": 0, "not_routed": 0}
    detail: list[dict] = []

    for row in rows:
        tier = row.get("tier")
        if not tier or row.get("decision") not in tier_map.REWRITING:
            summary["not_routed"] += 1
            continue
        prefix = (tiers.get(tier) or {}).get("resolved_prefix")
        got = resolved.get(row.get("tool_use_id"))
        if got is None:
            verdict = "unobserved"
        elif prefix and got.startswith(prefix):
            verdict = "honoured"
        else:
            verdict = "overridden"
        summary[verdict] += 1
        if verdict != "honoured":
            detail.append({
                "tool_use_id": row.get("tool_use_id"),
                "tier": tier,
                "expected_prefix": prefix,
                "resolved_model": got,
                "verdict": verdict,
            })

    total_routed = summary["honoured"] + summary["overridden"] + summary["unobserved"]
    return {
        "summary": summary,
        "detail": detail,
        "routed_total": total_routed,
        "honour_rate": (summary["honoured"] / total_routed) if total_routed else None,
    }
