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

### The mirror, which was missing (W5 audit, 2026-09-21)

The paragraph above had a hole exactly the width of its own promise. "A ledger
row with no matching transcript is ATTRITION, not a zero" names ONE of the two
ways a join can fail, and the module only ever implemented that one. A
TRANSCRIPT with no matching ledger row was read off disk, joined against
nothing, and dropped on the floor without a line of output.

Measured on the real session
`~/.claude/projects/<proj>/<session-id>.jsonl`:

    subagent transcripts on disk                    33
    rows the CLI printed                            30
    cost the CLI reported                     $168.02
    cost actually on disk                     $171.94
    silently dropped                            $3.93   (2.3% of delegated spend)
    attrition the CLI printed                    0.00%

Every one of the three orphans is a NESTED spawn -- `spawnDepth: 2`, spawned by
another agent rather than by the parent session -- so its `tool_use` block is
in the spawning AGENT's transcript, not in the parent's. `outcomes_for_session`
builds its stand-in ledger from `blocking_intervals`, which only sees top-level
`Agent`/`Task` blocks in the parent. Sidechains and compacted-away regions fail
the same way. The reported figure was not merely incomplete, it was reported
with an attrition rate of 0.00% -- i.e. the module asserted that nothing was
missing, in the same table from which $3.93 was missing.

So: every transcript that joins to no assignment is now its own NAMED CATEGORY
(`SessionOutcomes.unassigned`), with its own count and its own cost, rendered
whether or not it is empty. A number that cannot be attributed is reported as
unattributed; it is never rounded to nothing.

### Denominators are printed, because they are not the same denominator

The two medians this module and its Class 2 sibling publish are taken over
DIFFERENT SETS -- task duration over every transcript, blocking duration over
every assignment -- and on the session above those were 33 and 30. Two medians
printed side by side under one implied `n` invite a comparison that is not
valid. Every median rendered here carries the `n` it was taken over.

### Two failure modes that the corpus happens not to contain

Neither was observed; both were unguarded, and "not observed yet" is not a
guard.

  - A TASK THAT NEVER COMPLETED. Nothing read a status or a completion marker,
    so a truncated transcript yielded `outcome_found=True` with a partial cost,
    indistinguishable from a finished one -- which is precisely the shape of
    error the attrition machinery exists to prevent, one level down.
    `transcript_completion` now reads the final assistant message's
    `stop_reason` and a row carries `completed` separately from `outcome_found`.
  - A RETRIED TASK. `{o.tool_use_id: o for o in outcomes}` silently kept the
    LAST file sharing a `toolUseId` and discarded the earlier attempt's cost.
    Outcomes are now grouped into lists per id, cost is summed across attempts,
    and `attempts` travels on the row.

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

# A subagent turn that ended on purpose. Anything else as the LAST assistant
# stop_reason -- `max_tokens`, `tool_use`, a missing field because the file was
# cut mid-write -- means the transcript stops rather than ends, and its cost is
# a partial cost. Measured across the 33 transcripts of the <session> session:
# 31 `end_turn`, 1 `stop_sequence`, and 1 `tool_use` -- that last one being a
# genuinely truncated task the old code reported as a finished outcome.
TERMINAL_STOP_REASONS = frozenset({"end_turn", "stop_sequence"})

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
    # Why a transcript may be an orphan. `spawn_depth > 1` means it was
    # spawned by another AGENT, so its tool_use block is in that agent's
    # transcript and will never be found in the parent's.
    spawn_depth: int | None = None
    parent_agent_id: str | None = None
    # Did the turn END, or does the file merely STOP? See
    # `transcript_completion`. A partial cost that reads as a final one is the
    # error this exists to prevent.
    completed: bool = True
    completion: str = ""


def transcript_completion(transcript: Path) -> tuple[bool, str]:
    """Did this subagent turn finish, or is the transcript truncated?

    W5 audit: nothing read a status or a completion marker, so a truncated
    transcript produced `outcome_found=True` with a partial cost and was
    indistinguishable from a finished one.

    The marker is the LAST ASSISTANT message's `stop_reason`. A file cut
    mid-write has no terminal stop_reason at all.

    Deliberately the last *assistant* line rather than the last line of the
    file, and the reason is a principle rather than a corpus observation: a
    transcript may legitimately carry non-assistant trailing lines -- an
    `attachment`, a `tool_result`, a system line -- AFTER a final assistant
    turn that ended cleanly, and last-line-only would read every one of those
    as truncated. On the <session> corpus the two rules happen to agree, which
    is luck and not evidence: the single file there whose last line is an
    `attachment` is also the single genuinely truncated one, so it does not
    discriminate between the rules. Do not read the corpus as having tested
    this choice; it has not.
    """
    last_stop: Any = None
    saw_assistant = False
    if not transcript.exists():
        return False, "no transcript file"
    for raw in transcript.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            # A half-written final line is itself evidence of truncation, but
            # it is not conclusive on its own -- keep what we have.
            continue
        if line.get("type") != "assistant":
            continue
        message = line.get("message")
        if not isinstance(message, dict):
            continue
        saw_assistant = True
        last_stop = message.get("stop_reason")
    if not saw_assistant:
        return False, "no assistant message in the transcript"
    if last_stop is None:
        return False, "final assistant message carries no stop_reason (truncated)"
    if last_stop in TERMINAL_STOP_REASONS:
        return True, str(last_stop)
    return False, f"final assistant message stopped at {last_stop!r}"


def read_subagent(transcript: Path) -> SubagentOutcome:
    """One subagent file plus its sibling `.meta.json`.

    Costing is `session_metrics.analyse`, not a hand-rolled sum. `analyse`
    looks for a `<stem>/subagents` directory beside its argument; a subagent
    file has none, so calling it per file is safe and does not double-count.
    """
    metrics = sm.analyse(transcript)
    completed, completion = transcript_completion(transcript)
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
        spawn_depth=meta.get("spawnDepth"),
        parent_agent_id=meta.get("parentAgentId"),
        completed=completed,
        completion=completion,
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
    # More than one transcript shared this tool_use_id: the task was RETRIED.
    # Cost is summed across attempts. This used to be a silent overwrite.
    attempts: int = 0
    # False when any attempt's transcript is truncated. Separate from
    # `outcome_found`: an outcome that exists but did not finish is a third
    # state, and folding it into either of the other two loses it.
    completed: bool = True
    completion: str = ""


@dataclass
class SessionOutcomes:
    """Both sides of the join, and the two ways it can fail, kept together.

    `rows` is the intention-to-treat table: one row per ASSIGNMENT.
    `unassigned` is its mirror: transcripts that exist on disk and belong to no
    assignment. Neither is allowed to be silent, and the module returns both
    together precisely so that printing one without the other takes an effort.
    """
    rows: list[DelegatedTask] = field(default_factory=list)
    unassigned: list[SubagentOutcome] = field(default_factory=list)

    @property
    def assigned_cost_usd(self) -> float:
        return sum(r.cost_usd or 0.0 for r in self.rows)

    @property
    def unassigned_cost_usd(self) -> float:
        return sum(o.cost_usd for o in self.unassigned)

    @property
    def total_cost_usd(self) -> float:
        return self.assigned_cost_usd + self.unassigned_cost_usd

    @property
    def unassigned_share(self) -> float:
        total = self.total_cost_usd
        return (self.unassigned_cost_usd / total) if total else 0.0

    @property
    def n_transcripts(self) -> int:
        """The denominator for task duration: every transcript, orphans too."""
        return sum(r.attempts for r in self.rows) + len(self.unassigned)

    @property
    def incomplete(self) -> list[DelegatedTask]:
        return [r for r in self.rows if r.outcome_found and not r.completed]


def join_outcomes(ledger_rows: Iterable[dict], outcomes: Iterable[SubagentOutcome],
                  blocking: dict[str, Blocking] | None = None) -> SessionOutcomes:
    """Join W1's assignment ledger to the subagent transcripts on tool_use_id.

    Intention-to-treat: EVERY ledger row produces a row here, including the ones
    with no outcome on disk. Those carry `outcome_found=False` and an
    `attrition_reason`. Dropping them would be a per-protocol analysis wearing
    an ITT label, and it would bias in the one direction that matters -- towards
    whichever tier's tasks die before they finish.

    AND THE MIRROR, which this function used to omit: every OUTCOME that joins
    to no ledger row is returned in `unassigned` rather than discarded. A join
    has two sides and both of them can be empty; reporting only one of those
    facts is how $3.93 of real delegated spend disappeared while the same table
    printed an attrition rate of 0.00%.

    Returns `SessionOutcomes`, not a bare list, so that the orphan side cannot
    be ignored by a caller that simply never asked for it.
    """
    blocking = blocking or {}
    outcomes = list(outcomes)   # iterated twice: once to group, once to orphan
    # Grouped, not overwritten. Two transcripts sharing a toolUseId is a
    # RETRY, and `{o.tool_use_id: o for o in outcomes}` kept only the last.
    by_tool_use: dict[str, list[SubagentOutcome]] = {}
    for outcome in outcomes:
        if outcome.tool_use_id:
            by_tool_use.setdefault(outcome.tool_use_id, []).append(outcome)

    claimed: set[str] = set()
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
        attempts = by_tool_use.get(tool_use_id) or []
        if not attempts:
            row.attrition_reason = "no subagent transcript joined to this assignment"
        else:
            claimed.add(tool_use_id)
            row.outcome_found = True
            row.attempts = len(attempts)
            row.agent_id = ", ".join(a.agent_id for a in attempts)
            # Summed, never last-wins: a retried task cost what every attempt
            # cost, and the earlier attempt's spend is not free.
            row.cost_usd = sum(a.cost_usd for a in attempts)
            durations = [a.task_duration_s for a in attempts
                         if a.task_duration_s is not None]
            row.task_duration_s = sum(durations) if durations else None
            row.request_shape = next(
                (a.request_shape for a in attempts if a.request_shape),
                row.request_shape)
            unfinished = [a for a in attempts if not a.completed]
            if unfinished:
                row.completed = False
                row.completion = unfinished[0].completion
            else:
                row.completed = True
                row.completion = attempts[-1].completion
        rows.append(row)

    unassigned = [o for o in outcomes
                  if not o.tool_use_id or o.tool_use_id not in claimed]
    return SessionOutcomes(rows=rows, unassigned=unassigned)


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
                         ) -> SessionOutcomes:
    """Everything joinable for one session, AND everything that did not join.

    When no ledger is supplied, the delegations found in the parent transcript
    stand in for assignments so the two durations are still reportable on a
    session that predates the router. Tier is unknown in that case and reads
    as `(unrouted)` -- which is the truth, not a default.

    That stand-in ledger is exactly where the W5 defect lived, and it is worth
    being precise about why, because the fix is NOT to make the stand-in
    complete. `blocking_intervals` reads the PARENT transcript, so it can only
    ever see top-level `Agent`/`Task` blocks. A subagent spawned by another
    subagent (`spawnDepth > 1`) has its `tool_use` block in that agent's
    transcript; a sidechain or a compacted-away region loses it too. There is
    no way to recover those assignments from the parent, so the stand-in
    ledger is IRREDUCIBLY incomplete and the only honest move is to say so
    about the transcripts it fails to cover -- which is what `unassigned` is.
    """
    blocking = blocking_intervals(session_transcript)
    outcomes = read_session_subagents(session_transcript)
    if ledger_rows is None:
        ledger_rows = [{"tool_use_id": tool_use_id} for tool_use_id in blocking]
    return join_outcomes(ledger_rows, outcomes, blocking)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def render_outcomes(result: SessionOutcomes) -> str:
    rows = result.rows
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
        flags = []
        if not row.outcome_found:
            flags.append("ATTRITION")
        if row.outcome_found and not row.completed:
            flags.append(f"INCOMPLETE ({row.completion})")
        if row.attempts > 1:
            flags.append(f"RETRIED x{row.attempts} (cost AND duration summed)")
        flag = ("  " + "  ".join(flags)) if flags else ""
        out.append(f"    {row.tool_use_id:<32}{tier:<12}{shape:<12}"
                   f"{task_s:>9}{block_s:>9}{cost:>10}{flag}")

    # --- the medians, each with the n it was taken over ---------------------
    task_values = [r.task_duration_s for r in rows if r.task_duration_s is not None]
    block_values = [r.blocking_duration_s for r in rows
                    if r.blocking_duration_s is not None]
    orphan_task_values = [o.task_duration_s for o in result.unassigned
                          if o.task_duration_s is not None]
    out.append("")
    out.append("  medians, each over ITS OWN n -- these are NOT the same denominator:")
    med_task = _median(task_values + orphan_task_values)
    med_block = _median(block_values)
    n_task = len(task_values) + len(orphan_task_values)
    retried = sum(r.attempts - 1 for r in rows if r.attempts > 1)
    task_note = ("assignments with a duration, retries SUMMED into one value, "
                 "plus orphans")
    out.append(f"    task duration      "
               f"{'-' if med_task is None else format(med_task, '.1f'):>10}s   "
               f"n={n_task}  ({task_note})")
    out.append(f"    blocking duration  "
               f"{'-' if med_block is None else format(med_block, '.1f'):>10}s   "
               f"n={len(block_values)}  (assignments with a parent tool_result)")
    if retried:
        out.append(f"    note: {retried} extra attempt(s) are summed into their "
                   f"assignment's value, so n={n_task} is over assignments +")
        out.append(f"          orphans, not over the {result.n_transcripts} "
                   "transcripts on disk.")
    if n_task != len(block_values):
        out.append(f"    -> the two medians are over DIFFERENT sets "
                   f"({n_task} vs {len(block_values)}). They are both true and")
        out.append("       they are not a ratio. Do not divide one by the other.")

    # --- the mirror of attrition: transcripts that joined to nothing --------
    out.append("")
    out.append("  transcripts that joined to NO assignment (the mirror of attrition):")
    if not result.unassigned:
        out.append("    none -- every transcript on disk is attributed to an assignment.")
    else:
        out.append(f"    {'agent_id':<20}{'type':<22}{'depth':>6}{'cost_usd':>10}"
                   f"   why it did not join")
        for o in result.unassigned:
            depth = "-" if o.spawn_depth is None else str(o.spawn_depth)
            why = ("nested spawn: its tool_use block is in agent "
                   f"{o.parent_agent_id}'s transcript, not the parent session's"
                   if (o.spawn_depth or 0) > 1 and o.parent_agent_id
                   else "no toolUseId in .meta.json" if not o.tool_use_id
                   else "tool_use block absent from the parent transcript")
            out.append(f"    {o.agent_id:<20}{(o.agent_type or '?'):<22}{depth:>6}"
                       f"{o.cost_usd:>10.4f}   {why}")
        out.append(f"    {len(result.unassigned)} transcript(s), "
                   f"${result.unassigned_cost_usd:.4f} "
                   f"= {result.unassigned_share:.2%} of delegated spend.")
        out.append("    This cost is REAL and is excluded from every per-tier figure")
        out.append("    below, because there is no assignment to attribute it to.")

    out.append("")
    out.append(f"  total delegated spend  ${result.total_cost_usd:.4f}"
               f"   = ${result.assigned_cost_usd:.4f} attributed"
               f" + ${result.unassigned_cost_usd:.4f} unattributed")

    incomplete = result.incomplete
    if incomplete:
        out.append("")
        out.append("  transcripts that STOP rather than END -- partial costs, counted:")
        for row in incomplete:
            out.append(f"    {row.tool_use_id:<32}{row.completion}")

    out.append("")
    out.append(f"  attrition by tier (over {len(rows)} assignment(s); the "
               f"{len(result.unassigned)} unattributed")
    out.append("  transcript(s) above are NOT in these figures):")
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

    result = outcomes_for_session(session, ledger_rows)
    if not result.rows and not result.unassigned:
        print("COULD NOT RUN: no delegations found in this transcript and no "
              "ledger rows supplied. Nothing was measured -- this is NOT a "
              "report that there were no costs.", file=sys.stderr)
        return 1
    print(render_outcomes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
