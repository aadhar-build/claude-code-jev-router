"""Outcome measurement for delegated tasks -- JEV-36, repurposed.

"Nothing in this repository has ever measured whether a routed subagent did the
work correctly." This module closes the other half of that gap: whether it did
the work correctly is Class 2's job; what it COST, how long it TOOK, and how
long the human WAITED is this one's.

### Where the numbers come from, and where they demonstrably do not

JEV-36 records that the outcome cannot come from `PostToolUse`. That was
verified again here against real transcripts on 2026-09-21 rather than taken on
trust:

  - `~/.claude/projects/<project>/<session>.jsonl` contains, for a background
    delegation, a `tool_result` whose text begins "Async agent launched
    successfully." It carries an `agentId`, an `output_file` path and prose.
    It carries NO `usage` object, NO token counts and NO timing fields. There is
    nothing in it to cost. `async_launch_usage_fields()` asserts that.
  - `~/.claude/projects/<project>/<session>/subagents/agent-<id>.jsonl` DOES
    carry per-call `message.usage`, `message.model` and per-line `timestamp`.
    A 46-line sample spanned 2026-09-19T20:18:06.836Z to 20:23:17.773Z on
    `claude-opus-5`.
  - `agent-<id>.meta.json` carries `{agentType, description, toolUseId,
    spawnDepth, requestShape, requestNonInteractive}`. `toolUseId` is the join
    key to the W1 assignment ledger, whose rows carry `tool_use_id` and `tier`.

So: assignment comes from the ledger, outcome comes from the subagent
transcript, and the two meet on the tool-use id. A ledger row with no matching
transcript is ATTRITION, not a zero.

### Two durations, never one (SPEC §2 S2, JEV-36 A3.5)

  task duration      first to last timestamp inside the subagent transcript.
  blocking duration  parent's `tool_use` timestamp to the matching
                     `tool_result` timestamp in the PARENT transcript.

For `requestShape: "background"` the second is the acknowledgement round-trip
and is near zero; the human's wait is elsewhere. A background subagent can get
objectively faster while the human waits exactly as long. The SPEC's goal says
"no added FELT latency", so reporting one number would answer a different
question from the one asked. When the two diverge, the divergence is the
finding -- `requestShape` is carried alongside so the divergence is
interpretable rather than mysterious.

### Attrition by tier (JEV-36, last bullet)

"A tier that fails more often would otherwise look cheaper." `attrition_by_tier`
reports, per tier, assignments made, outcomes found, and cost per OUTCOME as
well as cost per assignment. A tier whose tasks die early has cheap rows and an
expensive truth.

No network. No API calls. Costing goes through `src/session_metrics.py`, which
handles the failure modes naive summing gets wrong (subagent files billed to the
session, the `iterations[]` rows, the 5m/1h cache-write TTL split).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import session_metrics as sm  # noqa: E402

# The tool names Claude Code uses for a delegation. Both are matched because
# the name has changed across versions and a transcript on disk may carry
# either; missing one would silently drop every blocking duration.
AGENT_TOOL_NAMES = frozenset({"Agent", "Task"})

ASYNC_LAUNCH_MARKER = "Async agent launched successfully"

# Every field that would let us cost a call. If any of these ever appears in an
# async-launch tool result, `PostToolUse` becomes viable and this module's
# premise changes -- so the absence is asserted, not assumed.
USAGE_FIELDS = (
    "input_tokens", "output_tokens", "cache_creation_input_tokens",
    "cache_read_input_tokens", "inputTokens", "outputTokens",
    "total_cost_usd", "totalCostUsd", "duration_ms", "durationMs",
)


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text")
    return ""


# ---------------------------------------------------------------------------
# The PostToolUse premise, verified rather than assumed
# ---------------------------------------------------------------------------

def async_launch_usage_fields(tool_result: dict[str, Any]) -> list[str]:
    """Usage-bearing fields present in an async-launch tool result.

    Empty means JEV-36 is right and `PostToolUse` cannot supply an outcome.
    Non-empty would mean the harness changed and this module can be simplified.
    """
    blob = json.dumps(tool_result, ensure_ascii=False)
    # Only structural keys count; the prose sometimes mentions tokens in
    # passing, and a substring match on the narrative would be a false alarm.
    found = []
    for field_name in USAGE_FIELDS:
        if f'"{field_name}"' in blob:
            found.append(field_name)
    return found


def is_async_launch(tool_result: dict[str, Any]) -> bool:
    content = tool_result.get("content")
    return ASYNC_LAUNCH_MARKER in _text_of(content)


# ---------------------------------------------------------------------------
# Reading the parent transcript: blocking duration
# ---------------------------------------------------------------------------

@dataclass
class Blocking:
    tool_use_id: str
    spawned_at: str | None = None
    returned_at: str | None = None
    blocking_duration_s: float | None = None
    async_launched: bool = False
    usage_fields_in_result: list[str] = field(default_factory=list)


def blocking_intervals(parent_transcript: Path) -> dict[str, Blocking]:
    """tool_use -> tool_result wall time in the PARENT, per delegation.

    This is the number that answers "how long did the human wait", and it is
    NOT the subagent's duration. For a background launch the result comes back
    in milliseconds with an acknowledgement, and the subagent runs on for
    minutes afterwards.
    """
    out: dict[str, Blocking] = {}
    if not parent_transcript.exists():
        return out
    for raw in parent_transcript.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            continue
        message = line.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") in AGENT_TOOL_NAMES:
                tool_use_id = block.get("id")
                if tool_use_id:
                    out.setdefault(tool_use_id, Blocking(tool_use_id))
                    out[tool_use_id].spawned_at = line.get("timestamp")
            elif block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id")
                if not tool_use_id or tool_use_id not in out:
                    continue
                record = out[tool_use_id]
                record.returned_at = line.get("timestamp")
                record.async_launched = is_async_launch(block)
                record.usage_fields_in_result = async_launch_usage_fields(block)
    for record in out.values():
        start, end = _ts(record.spawned_at), _ts(record.returned_at)
        if start and end:
            record.blocking_duration_s = (end - start).total_seconds()
    return out


# ---------------------------------------------------------------------------
# Reading the subagent transcript: task duration, cost, model
# ---------------------------------------------------------------------------

@dataclass
class SubagentOutcome:
    agent_id: str
    transcript: str
    tool_use_id: str | None = None
    agent_type: str | None = None
    request_shape: str | None = None
    description: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    task_duration_s: float | None = None
    cost_usd: float = 0.0
    models: dict[str, int] = field(default_factory=dict)
    unpriced_models: list[str] = field(default_factory=list)
    assistant_lines: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


def read_subagent(transcript: Path) -> SubagentOutcome:
    """One subagent file plus its sibling `.meta.json`.

    Costing is `session_metrics.analyse`, not a hand-rolled sum. `analyse`
    looks for a `<stem>/subagents` directory beside its argument; a subagent
    file has none, so calling it per file is safe and does not double-count.
    """
    metrics = sm.analyse(transcript)
    meta: dict[str, Any] = {}
    candidate = transcript.parent / (transcript.name[:-len(".jsonl")] + ".meta.json")
    if candidate.exists():
        meta = json.loads(candidate.read_text(encoding="utf-8"))
    agent_id = transcript.stem
    if agent_id.startswith("agent-"):
        agent_id = agent_id[len("agent-"):]
    return SubagentOutcome(
        agent_id=agent_id,
        transcript=str(transcript),
        tool_use_id=meta.get("toolUseId"),
        agent_type=meta.get("agentType"),
        request_shape=meta.get("requestShape"),
        description=meta.get("description"),
        started_at=metrics.started_at,
        ended_at=metrics.ended_at,
        task_duration_s=metrics.wall_clock_s,
        cost_usd=metrics.computed_cost_usd,
        models=dict(metrics.models),
        unpriced_models=list(metrics.unpriced_models),
        assistant_lines=metrics.assistant_lines,
        input_tokens=metrics.input_tokens,
        output_tokens=metrics.output_tokens,
        cache_creation_input_tokens=metrics.cache_creation_input_tokens,
        cache_read_input_tokens=metrics.cache_read_input_tokens,
    )


def read_session_subagents(session_transcript: Path) -> list[SubagentOutcome]:
    directory = session_transcript.with_suffix("") / "subagents"
    if not directory.is_dir():
        return []
    return [read_subagent(p) for p in sorted(directory.glob("*.jsonl"))]


# ---------------------------------------------------------------------------
# Assignment meets outcome
# ---------------------------------------------------------------------------

@dataclass
class DelegatedTask:
    tool_use_id: str
    tier: str | None = None
    decision: str | None = None
    subagent_type: str | None = None
    assigned_alias: str | None = None
    agent_id: str | None = None
    request_shape: str | None = None
    task_duration_s: float | None = None
    blocking_duration_s: float | None = None
    cost_usd: float | None = None
    outcome_found: bool = False
    attrition_reason: str | None = None


def join_outcomes(ledger_rows: Iterable[dict], outcomes: Iterable[SubagentOutcome],
                  blocking: dict[str, Blocking] | None = None) -> list[DelegatedTask]:
    """Join W1's assignment ledger to the subagent transcripts on tool_use_id.

    Intention-to-treat: EVERY ledger row produces a row here, including the ones
    with no outcome on disk. Those carry `outcome_found=False` and an
    `attrition_reason`. Dropping them would be a per-protocol analysis wearing
    an ITT label, and it would bias in the one direction that matters -- towards
    whichever tier's tasks die before they finish.
    """
    blocking = blocking or {}
    by_tool_use: dict[str, SubagentOutcome] = {
        o.tool_use_id: o for o in outcomes if o.tool_use_id}
    rows: list[DelegatedTask] = []
    for ledger in ledger_rows:
        tool_use_id = ledger.get("tool_use_id") or ""
        row = DelegatedTask(
            tool_use_id=tool_use_id,
            tier=ledger.get("tier"),
            decision=ledger.get("decision"),
            subagent_type=ledger.get("subagent_type"),
            assigned_alias=ledger.get("assigned_alias"),
        )
        wait = blocking.get(tool_use_id)
        if wait:
            row.blocking_duration_s = wait.blocking_duration_s
            row.request_shape = "background" if wait.async_launched else row.request_shape
        outcome = by_tool_use.get(tool_use_id)
        if outcome is None:
            row.attrition_reason = "no subagent transcript joined to this assignment"
        else:
            row.outcome_found = True
            row.agent_id = outcome.agent_id
            row.task_duration_s = outcome.task_duration_s
            row.cost_usd = outcome.cost_usd
            row.request_shape = outcome.request_shape or row.request_shape
        rows.append(row)
    return rows


def attrition_by_tier(rows: Iterable[DelegatedTask]) -> dict[str, dict[str, float]]:
    """Per tier: assignments, outcomes, attrition rate, and BOTH cost means.

    `cost_per_assignment` divides by everything assigned; `cost_per_outcome`
    divides only by the tasks that produced one. When a tier's tasks die, the
    first number falls and the second rises, and printing only the first is how
    a tier that fails more often comes to look cheaper.
    """
    buckets: dict[str, dict[str, float]] = {}
    for row in rows:
        tier = row.tier or "(unrouted)"
        b = buckets.setdefault(tier, {
            "assignments": 0.0, "outcomes": 0.0, "cost_usd": 0.0,
            "attrition": 0.0, "attrition_rate": 0.0,
            "cost_per_assignment": 0.0, "cost_per_outcome": float("nan"),
        })
        b["assignments"] += 1
        if row.outcome_found:
            b["outcomes"] += 1
            b["cost_usd"] += row.cost_usd or 0.0
        else:
            b["attrition"] += 1
    for b in buckets.values():
        b["attrition_rate"] = b["attrition"] / b["assignments"] if b["assignments"] else 0.0
        b["cost_per_assignment"] = (b["cost_usd"] / b["assignments"]
                                    if b["assignments"] else float("nan"))
        b["cost_per_outcome"] = (b["cost_usd"] / b["outcomes"]
                                 if b["outcomes"] else float("nan"))
    return buckets


def outcomes_for_session(session_transcript: Path,
                         ledger_rows: Iterable[dict] | None = None
                         ) -> list[DelegatedTask]:
    """Everything joinable for one session.

    When no ledger is supplied, the delegations found in the parent transcript
    stand in for assignments so the two durations are still reportable on a
    session that predates the router. Tier is unknown in that case and reads
    as `(unrouted)` -- which is the truth, not a default.
    """
    blocking = blocking_intervals(session_transcript)
    outcomes = read_session_subagents(session_transcript)
    if ledger_rows is None:
        ledger_rows = [{"tool_use_id": tool_use_id} for tool_use_id in blocking]
    return join_outcomes(ledger_rows, outcomes, blocking)


def render_outcomes(rows: list[DelegatedTask]) -> str:
    out = ["=== delegated-task outcomes (JEV-36) ===",
           "  BOTH durations are reported. A background subagent can get faster",
           "  while the human waits exactly as long; the SPEC's goal is 'no added",
           "  FELT latency', so one number would answer a different question.",
           "",
           f"    {'tool_use_id':<32}{'tier':<12}{'shape':<12}"
           f"{'task_s':>9}{'block_s':>9}{'cost_usd':>10}"]
    for row in rows:
        task_s = "-" if row.task_duration_s is None else f"{row.task_duration_s:.1f}"
        block_s = "-" if row.blocking_duration_s is None else f"{row.blocking_duration_s:.1f}"
        cost = "-" if row.cost_usd is None else f"{row.cost_usd:.4f}"
        tier = row.tier or "(unrouted)"
        shape = row.request_shape or "?"
        flag = "" if row.outcome_found else "  ATTRITION"
        out.append(f"    {row.tool_use_id:<32}{tier:<12}{shape:<12}"
                   f"{task_s:>9}{block_s:>9}{cost:>10}{flag}")
    out.append("")
    out.append("  attrition by tier:")
    out.append(f"    {'tier':<14}{'assigned':>9}{'outcomes':>9}{'attrition':>11}"
               f"{'$/assigned':>12}{'$/outcome':>12}")
    for tier, b in sorted(attrition_by_tier(rows).items()):
        out.append(f"    {tier:<14}{int(b['assignments']):>9}{int(b['outcomes']):>9}"
                   f"{b['attrition_rate']:>11.2%}{b['cost_per_assignment']:>12.4f}"
                   f"{b['cost_per_outcome']:>12.4f}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Print the two-durations table and the attrition-by-tier table.

    Exit codes match `src/accuracy_gate.py`: 0 ran clean, 1 COULD NOT RUN,
    2 invoked wrong. There is no exit 3 here -- this module MEASURES, it does
    not judge, and a measurement has no regression to find.

        uv run src/subagent_outcomes.py --session ~/.claude/projects/<p>/<s>.jsonl
        uv run src/subagent_outcomes.py --session <s>.jsonl --ledger data/agent_route/assignments
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="subagent_outcomes",
        description="Per delegated task: cost, task duration AND blocking "
                    "duration, joined to the assignment ledger, with attrition "
                    "reported by tier.")
    parser.add_argument("--session", required=True,
                        help="a PARENT session transcript (.jsonl). Its "
                             "<stem>/subagents/ directory carries the outcomes.")
    parser.add_argument("--ledger", default=None,
                        help="W1 assignment ledger directory. Without it, the "
                             "delegations in the transcript stand in and tier "
                             "reads as (unrouted).")
    args = parser.parse_args(argv)

    session = Path(args.session).expanduser()
    if not session.exists():
        print(f"COULD NOT RUN: no such transcript: {session}", file=sys.stderr)
        return 1

    ledger_rows = None
    if args.ledger:
        import assignment_ledger
        ledger_dir = Path(args.ledger).expanduser()
        if not ledger_dir.is_dir():
            print(f"INVOKED WRONG: --ledger is not a directory: {ledger_dir}",
                  file=sys.stderr)
            return 2
        ledger_rows = assignment_ledger.read_ledger(ledger_dir)

    rows = outcomes_for_session(session, ledger_rows)
    if not rows:
        print("COULD NOT RUN: no delegations found in this transcript and no "
              "ledger rows supplied. Nothing was measured -- this is NOT a "
              "report that there were no costs.", file=sys.stderr)
        return 1
    print(render_outcomes(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
