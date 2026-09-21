#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""SPEC §2 R1-R5: the before/after report. JEV-06's missing half.

Everything else in this repository is apparatus. The router decides, the
installer installs, the accuracy gate brakes -- and until this module existed
**nothing compared a before to an after**. `session_metrics.py` is a viewer:
it reads one transcript and prints. This is the thing that finally says
whether any of it helped.

WHAT IT REPORTS, IN THE SPEC'S OWN ORDER
----------------------------------------
  R1  rework rate      PRIMARY. retries + task-level failures per delegated
                       task. An escalation pays TWICE -- operator decision 3
                       is RESTART, so a redo is the whole task again, serially
                       -- which is why this leads and cost does not.
  R2  felt latency     BLOCKING duration p50/p95, reported SEPARATELY from
                       task duration, each over its own n.
  R3  quality          taken from `src/accuracy_gate.py`'s verdict. Absent ->
                       NOT_EVALUABLE -> exit 1. Never a pass.
  R4  net win after    the layer's own latency (hook_ms, which IS on the
      the layer's cost  blocking path) and its own spend, in the win's units.
  R5  realised cost    per delegated task against the corrected $2.88 anchor.
                       REPORTED, NOT A GATE.

THE THING THIS MODULE REFUSES TO DO
-----------------------------------
**Routing delegated tasks cannot improve felt latency.** Measured on the one
session we have: median task duration 794.6s against median BLOCKING duration
1.5s -- a 530x gap, because every observed delegation is `requestShape:
background`. A background subagent could be made twice as fast and the human's
wait would not move. So a task-duration improvement is NEVER printed here as a
speed win for the human, and the two denominators (33 and 30 on that session)
are carried with their figures and are explicitly **not a ratio**.

THE TRAP THIS PROJECT HAS ALREADY FALLEN INTO TWICE
---------------------------------------------------
`$2.88` per delegated task is the figure **under the JEV-24a cut**. The
whole-corpus figure is **$5.21**. They are two cuts of ONE corpus and comparing
them measures the cut, not the change. So a `Figure` here carries its `Window`
and `diff()` raises `WindowsDiffer` unless the two windows agree on scope,
costing rule, pricing version and project AND their time ranges are disjoint.
Comparing across windows is not discouraged in a comment; it raises.

EVERY DOLLAR HERE IS A LOWER BOUND
----------------------------------
Transcript-derived cost runs ~27.6% under Claude Code's own reported total
(FINDINGS.md Part 1), even after subagents are folded in. Every `$` line is
tagged. A lower bound that reads as a total is how a saving gets overstated.

EXIT CODES -- the taxonomy from `src/accuracy_gate.py`, unchanged
-----------------------------------------------------------------
  0  ran clean
  1  COULD NOT RUN -- and this is NOT a pass. "No after corpus exists" lives
     here, and it prints that sentence rather than a table of zeros.
  2  invoked wrong -- including `ProjectsWouldBePooled`, where the fix is a
     flag and not a retry.
  3  ran and found a regression -- R1 rework increased, or R3 failed.

Unlike `subagent_outcomes.py`, which measures and does not judge, this module
DOES judge: R1 "no increase" and R3 "both classes pass" are gates, so exit 3 is
live here.

USAGE
-----
    uv run src/report.py \\
        --before data/baseline/delegation-pre-rule-v1-corrected.json \\
        --before-scope interactive_sessions_only \\
        --after-ledger data/agent_route/assignments \\
        --project "$PWD"

Today that prints "NO AFTER CORPUS EXISTS" and exits 1, because
`data/agent_route/` is empty and `agent_route` is `mode: "off"`. That is the
correct output, and it is not a zero.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import assignment_ledger                                       # noqa: E402
import stats                                                   # noqa: E402
import subagent_outcomes                                       # noqa: E402
from accuracy_gate import (                                    # noqa: E402
    EXIT_CLEAN,
    EXIT_COULD_NOT_RUN,
    EXIT_INVOKED_WRONG,
    EXIT_REGRESSION,
    FAIL,
    NOT_EVALUABLE,
    PASS,
    Criterion,
    worst,
)

# ---------------------------------------------------------------------------
# Constants a reader should be able to find in one place
# ---------------------------------------------------------------------------

#: SPEC §11. The corrected anchor, under the JEV-24a cut.
CORRECTED_ANCHOR_USD = 2.879784

#: SPEC §10. The SAME corpus with NO cut. Recorded here only so the guard can
#: name the trap it is preventing. It must never be differenced against the
#: number above; that comparison measures the cut, not a change.
WHOLE_CORPUS_ANCHOR_USD = 5.21

#: FINDINGS.md Part 1.
UNDERSTATEMENT_PCT = 27.6

LOWER_BOUND_TAG = "(LOWER BOUND)"

LOWER_BOUND_NOTE = (
    "EVERY $ figure here is a LOWER BOUND and is tagged "
    f"{LOWER_BOUND_TAG}: transcript-derived "
    f"cost runs about {UNDERSTATEMENT_PCT}% under Claude Code's own reported total "
    "(FINDINGS.md Part 1), even after subagents are folded in."
)

NO_AFTER_CORPUS = "NO AFTER CORPUS EXISTS"

FELT_LATENCY_CAVEAT = (
    "Routing delegated tasks CANNOT improve felt latency. Every observed "
    "delegation is requestShape: background -- measured median task duration "
    "794.6s against median BLOCKING duration 1.5s. A background subagent could "
    "be made twice as fast and the human's wait would not move. An R2 win "
    "therefore needs a mechanism other than routing before it may be claimed."
)

#: alpha = 0.05 two-sided, power = 0.80.
Z_ALPHA = 1.959964
Z_BETA = 0.841621

SIDE_SCHEMA = "jev-report-side-v1"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class InvokedWrong(RuntimeError):
    """Exit 2. The invocation was not understood, so nothing was measured."""


class CouldNotRun(RuntimeError):
    """Exit 1. Invoked correctly and still could not produce a verdict."""


class WindowsDiffer(ValueError):
    """Two figures from different analysis windows were about to be compared.

    This is the JEV-24a trap, and it has caught this project twice. `$2.88`
    per delegated task is the pre-cut window; `$5.21` is the whole corpus.
    Differencing them reports the cut as if it were an effect.

    Raised rather than warned, for the `ProjectsWouldBePooled` reason: a
    confounded number is indistinguishable from a real one once it is on a
    page.
    """


# ---------------------------------------------------------------------------
# Window -- the population definition, not the calendar
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    """Everything that has to match before two figures may be differenced.

    `label` is prose and is NOT part of comparability -- renaming a window does
    not make it a different population. The other five fields are the
    population definition, and `starts_at`/`ends_at` are what make before and
    after *disjoint in time* rather than two views of one corpus.

    A bound of `None` means "unknown", and an unknown bound can never be proven
    disjoint from anything. `comparable()` refuses it. That is deliberate: the
    failure mode this repository keeps hitting is a missing fact that reads as
    a benign default.
    """
    label: str
    scope: str
    costing_rule: str
    pricing_version: str
    project: str
    starts_at: str | None = None
    ends_at: str | None = None

    def describe(self) -> str:
        span = f"{self.starts_at or '?'} .. {self.ends_at or '?'}"
        return (f"{self.label} [scope={self.scope} rule={self.costing_rule} "
                f"pricing={self.pricing_version} project={self.project} "
                f"window={span}]")

    def population_key(self) -> tuple:
        return (self.scope, self.costing_rule, self.pricing_version, self.project)


def parse_stamp(value: str | None) -> datetime | None:
    """An ISO-8601 instant, or None.

    `2026-09-20T11:11:49Z` and `2026-09-19T19:58:56.537000+00:00` are the SAME
    corpus's two spellings -- the first is what the cut and the ledger write,
    the second is what `datetime.isoformat()` puts in a transcript-derived
    bound. Comparing them as STRINGS is lexical: 'Z' (0x5A) sorts after both
    '.' and '+', so an after side starting in the same second the before side
    ends compares the wrong way round. The whole "structurally impossible"
    claim rests on this comparison, and it must not rest on string luck.
    """
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _disjoint(a: Window, b: Window) -> bool:
    """True only when both windows have PARSEABLE bounds that do not overlap."""
    bounds = [parse_stamp(x) for x in
              (a.starts_at, a.ends_at, b.starts_at, b.ends_at)]
    if any(x is None for x in bounds):
        return False
    a0, a1, b0, b1 = bounds
    first, second = ((a0, a1), (b0, b1)) if a0 <= b0 else ((b0, b1), (a0, a1))
    return first[1] <= second[0]


def comparable(before: Window, after: Window) -> None:
    """Raise `WindowsDiffer` unless these two windows may be differenced."""
    problems: list[str] = []
    if before.scope != after.scope:
        problems.append(f"scope {before.scope!r} vs {after.scope!r}")
    if before.costing_rule != after.costing_rule:
        problems.append(
            f"costing rule {before.costing_rule!r} vs {after.costing_rule!r}")
    if before.pricing_version != after.pricing_version:
        problems.append(
            f"pricing {before.pricing_version!r} vs {after.pricing_version!r}")
    if before.project != after.project:
        problems.append(f"project {before.project!r} vs {after.project!r}")
    if not _disjoint(before, after):
        problems.append(
            f"time ranges are not provably disjoint "
            f"({before.starts_at}..{before.ends_at} vs "
            f"{after.starts_at}..{after.ends_at})")
    if problems:
        raise WindowsDiffer(
            "refusing to compare two windows: " + "; ".join(problems) + ". "
            f"This is the JEV-24a trap: ${CORRECTED_ANCHOR_USD:.2f} per "
            f"delegated task is the PRE-CUT window and "
            f"${WHOLE_CORPUS_ANCHOR_USD:.2f} is the WHOLE CORPUS. Differencing "
            "two cuts of one corpus measures the cut, not the change.")


# ---------------------------------------------------------------------------
# Figure -- a number that carries its window everywhere it goes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Figure:
    name: str
    value: float | None
    unit: str
    n: int
    window: Window
    note: str = ""
    lower_bound: bool = False

    def render(self) -> str:
        if self.value is None:
            shown = "        -"
        elif self.unit == "USD":
            shown = f"${self.value:8.4f}"
        elif self.unit == "rate":
            shown = f"{self.value:8.2%} "
        else:
            shown = f"{self.value:9.2f}"
        tag = f" {LOWER_BOUND_TAG}" if self.lower_bound else ""
        return (f"    {self.name:<34}{shown}{tag}  n={self.n}"
                f"  [{self.window.label}]"
                + (f"  {self.note}" if self.note else ""))


@dataclass(frozen=True)
class Delta:
    name: str
    before: Figure
    after: Figure
    absolute: float
    relative: float | None


def diff(before: Figure, after: Figure) -> Delta:
    """The ONLY way two figures become one number in this module.

    It calls `comparable()` first, so there is no code path that differences
    across windows. That is what "structurally impossible" means here: not a
    rule a reader has to remember, a function that raises.
    """
    comparable(before.window, after.window)
    if before.value is None or after.value is None:
        raise CouldNotRun(
            f"{before.name}: one side has no value "
            f"(before={before.value!r}, after={after.value!r}). Nothing was "
            "measured -- this is NOT a report of no change.")
    absolute = after.value - before.value
    relative = (absolute / before.value) if before.value else None
    return Delta(before.name, before, after, absolute, relative)


# ---------------------------------------------------------------------------
# A side of the comparison
# ---------------------------------------------------------------------------

@dataclass
class TaskRow:
    """One delegated task, on either side. The canonical intermediate.

    Both builders -- the frozen baseline record and a live transcript + ledger
    join -- produce these, so the criteria below never learn where a side came
    from.
    """
    tool_use_id: str
    tier: str | None = None
    project: str = assignment_ledger.LEGACY_PARTITION
    attempts: int = 1
    outcome_found: bool = True
    completed: bool = True
    task_duration_s: float | None = None
    blocking_duration_s: float | None = None
    cost_usd: float | None = None
    hook_ms: float | None = None

    @property
    def retries(self) -> int:
        return max(0, self.attempts - 1)

    @property
    def failed(self) -> bool:
        """Ran and did not finish. Distinct from attrition, which is a
        MEASUREMENT gap and is reported beside R1 rather than folded into it."""
        return self.outcome_found and not self.completed


@dataclass
class Rework:
    """R1's components, each with its own observability.

    `escalations` is `None`, never `0`, on any side where nothing records one.
    Nothing in `src/` mentions escalation: `tier_map.FAILURES` has no
    escalation outcome and operator decision 3 (RESTART) is not implemented. A
    `0` there would be a guard that could not run reading as a guard that
    passed, one level down.
    """
    n_tasks: int
    retries: int
    failures: int
    attrition: int
    escalations: int | None
    escalations_note: str

    @property
    def observed_events(self) -> int:
        return self.retries + self.failures

    @property
    def rate(self) -> float | None:
        if not self.n_tasks:
            return None
        return self.observed_events / self.n_tasks


@dataclass
class Side:
    """One arm of the comparison: `before` or `after`.

    `tasks is None` means the record does not carry per-task rows at all --
    which is exactly true of `delegation-pre-rule-v1-corrected.json`, an
    aggregate of costs with no durations, no retries and no completion states.
    R1 and R2 on such a side are "not carried by this record", printed as
    such. They are NOT zero, and letting them read as zero would make the
    demoted criterion (R5) the only one that ever reports.
    """
    label: str
    window: Window
    source: str
    tasks: list[TaskRow] | None = None
    n_delegated_tasks: int | None = None
    delegated_cost_usd: float | None = None
    unassigned_cost_usd: float = 0.0
    router_present: bool = False
    notes: list[str] = field(default_factory=list)

    # -- counts ------------------------------------------------------------

    @property
    def n_tasks(self) -> int:
        if self.tasks is not None:
            return len(self.tasks)
        return self.n_delegated_tasks or 0

    @property
    def carries_tasks(self) -> bool:
        return self.tasks is not None

    # -- R1 ----------------------------------------------------------------

    @property
    def rework(self) -> Rework | None:
        if self.tasks is None:
            return None
        if self.router_present:
            note = ("no field in assignment-ledger schema v2 records an "
                    "escalation, and operator decision 3 (RESTART) is not "
                    "implemented. NOT OBSERVABLE, which is not the same as none.")
            escalations: int | None = None
        else:
            note = "0 BY CONSTRUCTION: there is no router on this side to escalate."
            escalations = 0
        return Rework(
            n_tasks=len(self.tasks),
            retries=sum(t.retries for t in self.tasks),
            failures=sum(1 for t in self.tasks if t.failed),
            attrition=sum(1 for t in self.tasks if not t.outcome_found),
            escalations=escalations,
            escalations_note=note,
        )

    # -- R2 ----------------------------------------------------------------

    @property
    def blocking_values(self) -> list[float]:
        if self.tasks is None:
            return []
        return [t.blocking_duration_s for t in self.tasks
                if t.blocking_duration_s is not None]

    @property
    def task_values(self) -> list[float]:
        if self.tasks is None:
            return []
        return [t.task_duration_s for t in self.tasks
                if t.task_duration_s is not None]

    # -- R4 ----------------------------------------------------------------

    @property
    def hook_ms_values(self) -> list[float]:
        if self.tasks is None:
            return []
        return [t.hook_ms for t in self.tasks if t.hook_ms is not None]

    # -- R5 ----------------------------------------------------------------

    @property
    def cost_values(self) -> list[float]:
        if self.tasks is None:
            return []
        return [t.cost_usd for t in self.tasks if t.cost_usd is not None]

    @property
    def attributed_cost_usd(self) -> float | None:
        """Spend on transcripts that joined to an assignment."""
        if self.delegated_cost_usd is not None:
            return self.delegated_cost_usd
        values = self.cost_values
        return sum(values) if values else None

    @property
    def total_delegated_cost_usd(self) -> float | None:
        """ALL delegated spend -- attributed PLUS the orphans.

        The orphan side is not optional. `join_outcomes`' own docstring records
        what omitting it cost: $3.93 of real delegated spend disappeared while
        the same table printed an attrition rate of 0.00%. The corrected
        anchor's `delegated_cost_usd` is every subagent transcript in its
        window, so an after side counting only ATTRIBUTED spend would
        understate the treatment arm -- bias in the one direction that flatters
        the layer.
        """
        attributed = self.attributed_cost_usd
        if attributed is None:
            return self.unassigned_cost_usd or None
        return attributed + self.unassigned_cost_usd

    @property
    def n_outcomes(self) -> int:
        """Tasks that produced an outcome. The OTHER denominator."""
        if self.tasks is None:
            return self.n_tasks
        return sum(1 for t in self.tasks if t.outcome_found)

    def cost_per_delegated_task(self) -> Figure:
        """$/ASSIGNMENT: the denominator that includes attrition."""
        total = self.total_delegated_cost_usd
        n = self.n_tasks
        value = (total / n) if (total is not None and n) else None
        note = "denominator is ASSIGNMENTS, attrition included"
        if self.tasks is None:
            note += "; this record's count is OUTCOMES, so the two sides' " \
                    "denominators differ -- see $/outcome below"
        if self.unassigned_cost_usd:
            note += (f"; numerator = ${self.attributed_cost_usd or 0.0:.4f} "
                     f"attributed + ${self.unassigned_cost_usd:.4f} unattributed")
        return Figure(
            name="realised cost / delegated task",
            value=value,
            unit="USD",
            n=n,
            window=self.window,
            lower_bound=True,
            note=note,
        )

    def cost_per_outcome(self) -> Figure:
        """$/OUTCOME: divides only by the tasks that produced one.

        Printed beside $/assignment for `attrition_by_tier`'s reason -- when a
        tier's tasks die the first number falls and this one rises, and showing
        only the first is how a tier that fails more often comes to look
        cheaper.
        """
        total = self.total_delegated_cost_usd
        n = self.n_outcomes
        value = (total / n) if (total is not None and n) else None
        return Figure(
            name="realised cost / outcome",
            value=value,
            unit="USD",
            n=n,
            window=self.window,
            lower_bound=True,
            note="denominator is OUTCOMES, attrition excluded",
        )


# ---------------------------------------------------------------------------
# Builder: the frozen "before"
# ---------------------------------------------------------------------------

def side_from_corrected_baseline(path: Path, *, scope: str,
                                 project: str,
                                 label: str = "before") -> Side:
    """The corrected anchor: `data/baseline/delegation-pre-rule-v1-corrected.json`.

    NOT `-v1`. The frozen `-v1` record was computed by a defective costing rule
    that kept the FIRST copy of a duplicated request (an `input_tokens: 2`
    placeholder) and never read `iterations[]`. Its $1.58 per delegated task
    understates the truth by 45.2%; a real 20% saving measured against it would
    have been published as a 46% INCREASE.

    The record is read through its `corrected` scope only. `as_frozen` and
    `frozen_rule_today` exist to prove the movement is the rule rather than
    corpus drift, and are not an analysis baseline.

    This record carries costs and counts and nothing else -- no durations, no
    retries, no completion states. The resulting Side has `tasks=None`, so R1
    and R2 report "not carried by this record" rather than zero. Pass
    `--before-session` to measure R1/R2 on the before side from transcripts.
    """
    if not path.exists():
        raise CouldNotRun(f"the before anchor is not on disk: {path}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CouldNotRun(f"the before anchor is not readable JSON: {exc}") from None
    schema = record.get("schema")
    if schema != "delegation-pre-rule-v1-corrected":
        raise InvokedWrong(
            f"--before must be the CORRECTED companion "
            f"(schema 'delegation-pre-rule-v1-corrected'), got {schema!r}. The "
            "frozen -v1 record was computed under the defective costing rule "
            "and understates delegated spend by 45.2%.")
    corrected = record.get("corrected") or {}
    if scope not in corrected:
        raise InvokedWrong(
            f"--before-scope {scope!r} is not a scope of this record; "
            f"available: {', '.join(sorted(corrected))}")
    block = corrected[scope]
    window = Window(
        label=f"{label}: pre-rule, JEV-24a cut",
        scope=scope,
        costing_rule=(record.get("costing_rule") or {}).get(
            "name", "session_metrics.billable_requests"),
        pricing_version=record.get("pricing_version", "unknown"),
        project=project,
        starts_at=(record.get("transcript_window") or {}).get("first_request_utc"),
        ends_at=(record.get("cut") or {}).get("timestamp_utc"),
    )
    return Side(
        label=label,
        window=window,
        source=str(path),
        tasks=None,
        n_delegated_tasks=block.get("delegated_tasks"),
        delegated_cost_usd=block.get("delegated_cost_usd"),
        router_present=False,
        notes=[
            "this record carries COSTS AND COUNTS ONLY -- no durations, no "
            "retries, no completion states.",
            record.get("lower_bound", LOWER_BOUND_NOTE),
        ],
    )


# ---------------------------------------------------------------------------
# Builder: a live side, from transcripts and (optionally) the ledger
# ---------------------------------------------------------------------------

def _ledger_rows_for(directory: Path, *, project: str | None,
                     pool_projects: bool) -> list[dict]:
    """Read the shared ledger, partitioned by repo -- never pooled by accident.

    The ledger at `$JEV_HOME/data/agent_route/` is shared by every repo `jev`
    is installed in (JEV-57). "The rows" is not automatically "this repo's
    rows", and pooling two repos confounds every rate derived from the result.
    """
    rows = assignment_ledger.read_ledger(directory)
    partitions = assignment_ledger.partition_by_project(rows)
    if pool_projects:
        return rows
    if project is not None:
        return partitions.get(project, [])
    if len(partitions) > 1:
        raise assignment_ledger.ProjectsWouldBePooled(sorted(partitions))
    return rows


def side_from_sessions(sessions: Sequence[Path], *, label: str,
                       scope: str, pricing_version: str, project: str,
                       ledger_dir: Path | None = None,
                       project_filter: str | None = None,
                       pool_projects: bool = False,
                       window_label: str | None = None) -> Side:
    """Join transcripts to the ledger and flatten to `TaskRow`s.

    Costing is `subagent_outcomes` -> `session_metrics.analyse`, which is the
    rule that handles the documented failure modes naive summing gets wrong.
    Nothing is re-implemented here.

    Intention-to-treat is preserved: every ledger row produces a row, including
    the ones with no outcome on disk, and the mirror (`unassigned`) is carried
    as a cost that is REAL and attributed to no assignment rather than dropped.
    """
    ledger_rows: list[dict] | None = None
    if ledger_dir is not None:
        if not ledger_dir.is_dir():
            raise InvokedWrong(f"--ledger is not a directory: {ledger_dir}")
        ledger_rows = _ledger_rows_for(ledger_dir, project=project_filter,
                                       pool_projects=pool_projects)
    hook_ms_by_id: dict[str, float] = {}
    project_by_id: dict[str, str] = {}
    for row in ledger_rows or []:
        tool_use_id = row.get("tool_use_id") or ""
        if isinstance(row.get("hook_ms"), (int, float)):
            hook_ms_by_id[tool_use_id] = float(row["hook_ms"])
        project_by_id[tool_use_id] = assignment_ledger.row_project(row)

    tasks: list[TaskRow] = []
    unassigned_cost = 0.0
    stamps: list[str] = []
    for session in sessions:
        if not session.exists():
            raise CouldNotRun(f"no such transcript: {session}")
        result = subagent_outcomes.outcomes_for_session(session, ledger_rows)
        unassigned_cost += result.unassigned_cost_usd
        for row in result.rows:
            tasks.append(TaskRow(
                tool_use_id=row.tool_use_id,
                tier=row.tier,
                project=project_by_id.get(row.tool_use_id,
                                          assignment_ledger.LEGACY_PARTITION),
                attempts=row.attempts or (1 if row.outcome_found else 0),
                outcome_found=row.outcome_found,
                completed=row.completed,
                task_duration_s=row.task_duration_s,
                blocking_duration_s=row.blocking_duration_s,
                cost_usd=row.cost_usd,
                hook_ms=hook_ms_by_id.get(row.tool_use_id),
            ))
        for outcome in result.unassigned:
            for stamp in (outcome.started_at, outcome.ended_at):
                if stamp:
                    stamps.append(stamp)
        for outcome in subagent_outcomes.read_session_subagents(session):
            for stamp in (outcome.started_at, outcome.ended_at):
                if stamp:
                    stamps.append(stamp)
    for row in ledger_rows or []:
        if row.get("timestamp"):
            stamps.append(str(row["timestamp"]))

    # Ordered by PARSED instant. `min()` over mixed 'Z' and '+00:00' spellings
    # is lexical and picks the wrong end of the corpus.
    parsed = sorted(x for x in (parse_stamp(s) for s in stamps) if x is not None)
    window = Window(
        label=window_label or f"{label}: live",
        scope=scope,
        costing_rule="session_metrics.billable_requests",
        pricing_version=pricing_version,
        project=project,
        starts_at=parsed[0].isoformat() if parsed else None,
        ends_at=parsed[-1].isoformat() if parsed else None,
    )
    return Side(
        label=label,
        window=window,
        source=", ".join(str(s) for s in sessions) or "(no sessions)",
        tasks=tasks,
        unassigned_cost_usd=unassigned_cost,
        router_present=ledger_dir is not None,
        notes=[LOWER_BOUND_NOTE],
    )


# ---------------------------------------------------------------------------
# Builder: a frozen side snapshot (fixtures, and the future frozen "after")
# ---------------------------------------------------------------------------

def side_to_json(side: Side) -> dict[str, Any]:
    return {
        "schema": SIDE_SCHEMA,
        "label": side.label,
        "source": side.source,
        "router_present": side.router_present,
        "unassigned_cost_usd": side.unassigned_cost_usd,
        "n_delegated_tasks": side.n_delegated_tasks,
        "delegated_cost_usd": side.delegated_cost_usd,
        "notes": list(side.notes),
        "window": {
            "label": side.window.label,
            "scope": side.window.scope,
            "costing_rule": side.window.costing_rule,
            "pricing_version": side.window.pricing_version,
            "project": side.window.project,
            "starts_at": side.window.starts_at,
            "ends_at": side.window.ends_at,
        },
        "tasks": None if side.tasks is None else [vars(t) for t in side.tasks],
    }


def side_from_json(path: Path, *, label: str | None = None) -> Side:
    if not path.exists():
        raise CouldNotRun(f"no such side snapshot: {path}")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("schema") != SIDE_SCHEMA:
        raise InvokedWrong(
            f"expected schema {SIDE_SCHEMA!r}, got {record.get('schema')!r}")
    w = record.get("window") or {}
    window = Window(
        label=w.get("label", "?"),
        scope=w.get("scope", "?"),
        costing_rule=w.get("costing_rule", "?"),
        pricing_version=w.get("pricing_version", "?"),
        project=w.get("project", "?"),
        starts_at=w.get("starts_at"),
        ends_at=w.get("ends_at"),
    )
    raw_tasks = record.get("tasks")
    tasks = None if raw_tasks is None else [TaskRow(**t) for t in raw_tasks]
    return Side(
        label=label or record.get("label", "?"),
        window=window,
        source=record.get("source", str(path)),
        tasks=tasks,
        n_delegated_tasks=record.get("n_delegated_tasks"),
        delegated_cost_usd=record.get("delegated_cost_usd"),
        unassigned_cost_usd=record.get("unassigned_cost_usd", 0.0),
        router_present=record.get("router_present", False),
        notes=list(record.get("notes") or []),
    )


# ---------------------------------------------------------------------------
# Power -- stated, printed, never left for the reader to infer
# ---------------------------------------------------------------------------

def mde_proportion(p1: float, n1: int, n2: int) -> float | None:
    """Smallest INCREASE in a rate this design could detect at 80% power.

    Normal approximation, alpha = 0.05 two-sided. Approximate, and said to be
    approximate: with a handful of tasks it is the order of magnitude that
    matters, and the order of magnitude is "almost anything".
    """
    if n1 <= 0 or n2 <= 0:
        return None
    for step in range(1, 10_001):
        p2 = p1 + step / 10_000.0
        if p2 >= 1.0:
            return None
        pooled = (p1 * n1 + p2 * n2) / (n1 + n2)
        se_null = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
        se_alt = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
        if se_alt <= 0:
            continue
        if (p2 - p1) >= Z_ALPHA * se_null + Z_BETA * se_alt:
            return p2 - p1
    return None


def mde_continuous(values_before: Sequence[float], n_after: int) -> float | None:
    """MDE ~ (z_a + z_b) * sigma * sqrt(1/n1 + 1/n2), in the values' own units."""
    n1 = len(values_before)
    if n1 < 2 or n_after < 1:
        return None
    sigma = statistics.stdev(values_before)
    if sigma == 0.0:
        # Degenerate rather than infinitely sensitive. A before side with zero
        # variance says nothing about what could be detected, and printing
        # "0.0s" there would read as "any difference is detectable".
        return None
    return (Z_ALPHA + Z_BETA) * sigma * math.sqrt(1 / n1 + 1 / n_after)


def power_statement(before: Side, after: Side) -> str:
    n1, n2 = before.n_tasks, after.n_tasks
    lines = [
        "=== POWER -- what this N could and could not have detected ===",
        f"  n = {n1} delegated task(s) before, {n2} after. Normal "
        "approximations, alpha 0.05 two-sided, 80% power. APPROXIMATE.",
    ]
    rework = before.rework
    if rework is not None and rework.rate is not None:
        mde = mde_proportion(rework.rate, n1, n2)
        if mde is None:
            lines.append(
                f"  R1: at a baseline rework rate of {rework.rate:.2%} with "
                f"n={n1} vs n={n2}, NO increase short of certainty is "
                "detectable. Any R1 comparison here is descriptive only.")
        else:
            lines.append(
                f"  R1: baseline rework {rework.rate:.2%}; the smallest "
                f"INCREASE detectable is about +{mde:.2%} "
                f"(to {rework.rate + mde:.2%}). Anything smaller is invisible "
                "to this design.")
    else:
        lines.append("  R1: not computable -- the before side carries no "
                     "per-task rows, so there is no baseline rate.")
    for name, values in (("R2 blocking", before.blocking_values),
                         ("R2 task duration", before.task_values)):
        mde = mde_continuous(values, n2)
        if mde is None:
            lines.append(f"  {name}: not computable at n={len(values)} before, "
                         f"n={n2} after (too few values, or no variance in "
                         "them). NOT 'any difference is detectable'.")
        else:
            lines.append(f"  {name}: smallest detectable shift about "
                         f"{mde:.1f}s (sd over n={len(values)} before).")
    mde_cost = mde_continuous(before.cost_values, n2)
    if mde_cost is None:
        lines.append("  R5: not computable -- the before side carries no "
                     "per-task costs, or no variance in them. R5 is reported, "
                     "not gated, so this does not block.")
    else:
        lines.append(f"  R5: smallest detectable shift about ${mde_cost:.2f} "
                     "per delegated task.")
    lines.append("  DO NOT READ SIGNIFICANCE OFF THE TABLES ABOVE. At these "
                 "sample sizes most real differences are unmeasurable.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The criteria
# ---------------------------------------------------------------------------

def _quantiles(values: Sequence[float]) -> dict[str, float]:
    return stats.quantiles(values, [0.5, 0.95])


def r1_rework(before: Side, after: Side) -> tuple[Criterion, list[str]]:
    """PRIMARY. Ships if rework does not increase."""
    out = ["=== R1  REWORK RATE -- PRIMARY ===",
           "  A redo is not a small correction. Operator decision 3 is RESTART:",
           "  an escalated task starts again from the original task, so it pays",
           "  TWICE -- in money, and in time, serially. One wrong downgrade",
           "  wipes out the saving from many correct ones.",
           "  The verdict below fires on ANY increase, per SPEC §2. At the N in",
           "  the POWER block it is DESCRIPTIVE, not a significant finding.",
           ""]
    rows: list[Rework | None] = []
    for side in (before, after):
        rework = side.rework
        if rework is None:
            rows.append(None)
            out.append(f"    {side.label:<8} not carried by this record "
                       f"({side.source}). NOT zero.")
            continue
        rows.append(rework)
        esc = ("NOT OBSERVABLE" if rework.escalations is None
               else str(rework.escalations))
        rate = "-" if rework.rate is None else f"{rework.rate:.2%}"
        out.append(f"    {side.label:<8} tasks={rework.n_tasks:<4} "
                   f"retries={rework.retries:<4} failures={rework.failures:<4} "
                   f"escalations={esc:<15} rework rate={rate}")
        out.append(f"             attrition={rework.attrition} "
                   "(a MEASUREMENT gap, reported beside R1 and never folded "
                   "into it)")
        out.append(f"             escalations: {rework.escalations_note}")
    out.append("")

    b, a = rows[0], rows[1]
    if b is None or a is None or b.rate is None or a.rate is None:
        return Criterion(
            name="R1 rework rate",
            status=NOT_EVALUABLE,
            detail="one side carries no per-task rows; no rate to compare",
        ), out
    before_fig = Figure("rework rate", b.rate, "rate", b.n_tasks, before.window)
    after_fig = Figure("rework rate", a.rate, "rate", a.n_tasks, after.window)
    delta = diff(before_fig, after_fig)
    out.append(f"    delta {delta.absolute:+.2%} "
               f"(before {b.rate:.2%} -> after {a.rate:.2%})")
    status = FAIL if delta.absolute > 0 else PASS
    detail = ("rework INCREASED -- this is the primary criterion and it blocks"
              if status == FAIL else "no increase")
    return Criterion(name="R1 rework rate", status=status,
                     value=delta.absolute, threshold=0.0, detail=detail), out


def r2_latency(before: Side, after: Side) -> tuple[Criterion, list[str]]:
    """Felt latency. Two tables, two denominators, and NOT a ratio."""
    out = ["=== R2  FELT LATENCY ===",
           f"  {FELT_LATENCY_CAVEAT}",
           "",
           "  BLOCKING duration -- the time the human actually waits:"]
    evaluable = True
    for side in (before, after):
        values = side.blocking_values
        if not values:
            out.append(f"    {side.label:<8} not carried by this record. NOT zero.")
            evaluable = False
            continue
        q = _quantiles(values)
        out.append(f"    {side.label:<8} p50={q['p50']:8.2f}s  "
                   f"p95={q['p95']:8.2f}s   n={len(values)}")
    out.append("")
    out.append("  TASK duration -- how long the background subagent ran. This is")
    out.append("  NOT a speed number for the human and is never reported as one:")
    for side in (before, after):
        values = side.task_values
        if not values:
            out.append(f"    {side.label:<8} not carried by this record. NOT zero.")
            continue
        q = _quantiles(values)
        out.append(f"    {side.label:<8} p50={q['p50']:8.2f}s  "
                   f"p95={q['p95']:8.2f}s   n={len(values)}")
    out.append("")
    for side in (before, after):
        n_block, n_task = len(side.blocking_values), len(side.task_values)
        if n_block or n_task:
            out.append(f"    {side.label}: the two denominators are {n_task} "
                       f"(task) and {n_block} (blocking). They are both true "
                       "and they are")
            out.append("             NOT A RATIO. Do not divide one by the other.")
    out.append("")

    if not evaluable:
        return Criterion(
            name="R2 felt latency (blocking)",
            status=NOT_EVALUABLE,
            detail="one side carries no blocking durations",
        ), out
    b = _quantiles(before.blocking_values)["p50"]
    a = _quantiles(after.blocking_values)["p50"]
    before_fig = Figure("blocking p50", b, "s", len(before.blocking_values),
                        before.window)
    after_fig = Figure("blocking p50", a, "s", len(after.blocking_values),
                       after.window)
    delta = diff(before_fig, after_fig)
    out.append(f"    blocking p50 delta {delta.absolute:+.2f}s")
    if delta.absolute < 0:
        out.append("    A REDUCTION here needs a mechanism other than routing "
                   "before it may be claimed as a win. See the caveat above.")
    status = FAIL if delta.absolute > 0 else PASS
    return Criterion(name="R2 felt latency (blocking p50)", status=status,
                     value=delta.absolute, threshold=0.0,
                     detail=("blocking duration REGRESSED" if status == FAIL
                             else "no regression")), out


def r3_quality(gate_exit: int | None,
               gate_detail: str) -> tuple[Criterion, list[str]]:
    """Quality non-regression, taken from the accuracy gate's own verdict.

    This module does not re-run the gate and does not re-implement it. Absent
    -> NOT_EVALUABLE -> exit 1. A guard that could not run must never read as a
    guard that passed.
    """
    out = ["=== R3  QUALITY NON-REGRESSION ===",
           "  Taken from src/accuracy_gate.py. Green means 'NO LARGE REGRESSION",
           "  FOUND', never 'quality preserved'.",
           ""]
    if gate_exit is None:
        out.append("    no gate verdict supplied (--gate-exit / --gate-verdict).")
        out.append("    THIS IS NOT A PASS. Nothing about quality has been cleared.")
        return Criterion(name="R3 quality (accuracy gate)",
                         status=NOT_EVALUABLE,
                         detail="no accuracy-gate verdict supplied"), out
    out.append(f"    accuracy gate exited {gate_exit}. {gate_detail}")
    if gate_exit == EXIT_CLEAN:
        status, detail = PASS, "the gate ran and found no large regression"
    elif gate_exit == EXIT_REGRESSION:
        status, detail = FAIL, "the gate found a regression"
    else:
        status = NOT_EVALUABLE
        detail = (f"the gate exited {gate_exit} -- it did not reach a verdict. "
                  "NOT a pass.")
        out.append("    " + detail)
    return Criterion(name="R3 quality (accuracy gate)", status=status,
                     value=float(gate_exit), detail=detail), out


def r4_overhead(before: Side, after: Side,
                r2: Criterion, r5_delta: Delta | None) -> tuple[Criterion, list[str]]:
    """The layer's own cost, in the same units as the win it claims.

    A layer that saves 5,000 tokens but adds 250ms to every tool call has not
    obviously helped. `FINDINGS.md:563` is the measured version: a synchronous
    gate adds +337 tokens and +557ms p50 per call and removes nothing.
    """
    out = ["=== R4  NET WIN AFTER THE LAYER'S OWN COST ===",
           "  Reported in the SAME UNITS as the win. This is the criterion most",
           "  likely to be quietly skipped.",
           ""]
    hook_values = after.hook_ms_values
    overhead_s = None
    if hook_values:
        q = _quantiles(hook_values)
        overhead_s = q["p50"] / 1000.0
        out.append(f"    router hook latency   p50={q['p50']:8.1f}ms  "
                   f"p95={q['p95']:8.1f}ms   n={len(hook_values)}")
        out.append("    This IS on the blocking path: the hook runs before the")
        out.append("    spawn returns, so it is felt latency the layer added.")
    else:
        out.append("    router hook latency   not recorded on the after side "
                   "(no hook_ms in the ledger rows). NOT zero.")
    out.append(f"    before-side overhead  0 BY CONSTRUCTION -- there is no "
               f"layer on the '{before.label}' side.")
    out.append("")

    if after.unassigned_cost_usd:
        out.append(f"    unattributed delegated spend ${after.unassigned_cost_usd:.4f} "
                   f"{LOWER_BOUND_TAG}")
        out.append("    -- real spend on transcripts that join to no assignment.")
        out.append("       Excluded from every per-tier figure, never from the total.")
        out.append("")

    parts: list[str] = []
    if overhead_s is not None and r2.value is not None:
        net = r2.value + overhead_s
        parts.append(f"latency: blocking delta {r2.value:+.2f}s + layer "
                     f"overhead {overhead_s:+.3f}s = net {net:+.3f}s")
        out.append(f"    NET LATENCY  {net:+.3f}s  "
                   f"({'the layer costs more than it saves' if net > 0 else 'net saving'})")
    if r5_delta is not None:
        out.append(f"    NET SPEND    ${r5_delta.absolute:+.4f} per delegated "
                   f"task {LOWER_BOUND_TAG}")
        out.append("    This IS R5's delta, not a second subtraction: a routed "
                   "task's cost already")
        out.append("    contains whatever the layer's decision billed, "
                   "fail-to-frontier premium included.")
        parts.append(f"spend: {r5_delta.absolute:+.4f} USD/task")
    if not parts:
        out.append("    Neither term is computable on this data. NOT a net win "
                   "of zero.")
        return Criterion(name="R4 net win after overhead",
                         status=NOT_EVALUABLE,
                         detail="the layer's own overhead was not measurable"), out
    net_latency = (r2.value + overhead_s) if (overhead_s is not None
                                              and r2.value is not None) else None
    if net_latency is None or r5_delta is None:
        # SPEC §2 R4 is "the layer's added latency AND spend, subtracted from
        # R1/R2" -- plural. A PASS computed from one term is the criterion
        # being quietly skipped, which the SPEC names as the likeliest failure.
        missing = []
        if net_latency is None:
            missing.append("latency")
        if r5_delta is None:
            missing.append("spend")
        out.append(f"    NOT EVALUABLE: the {' and '.join(missing)} term(s) "
                   "were not measurable. A net win computed from one term is")
        out.append("    not a net win.")
        return Criterion(name="R4 net win after overhead",
                         status=NOT_EVALUABLE,
                         value=net_latency,
                         detail=f"missing: {', '.join(missing)}"), out
    status = FAIL if net_latency > 0 else PASS
    return Criterion(name="R4 net win after overhead", status=status,
                     value=net_latency,
                     detail="; ".join(parts)), out


def r5_cost(before: Side, after: Side) -> tuple[Criterion, list[str], Delta | None]:
    """REPORTED, NOT A GATE. Its status is never FAIL."""
    out = ["=== R5  REALISED COST PER DELEGATED TASK (reported, NOT a gate) ===",
           f"  {LOWER_BOUND_NOTE}",
           ""]
    before_fig = before.cost_per_delegated_task()
    after_fig = after.cost_per_delegated_task()
    out.append(before_fig.render())
    out.append(before.cost_per_outcome().render())
    out.append(after_fig.render())
    out.append(after.cost_per_outcome().render())
    out.append("    BOTH denominators are shown because they move in opposite "
               "directions when a tier's tasks die:")
    out.append("    $/assignment falls and $/outcome rises. Printing only the "
               "first is how a tier that fails")
    out.append("    more often comes to look cheaper.")
    out.append(f"    corrected anchor (SPEC §11)    ${CORRECTED_ANCHOR_USD:8.4f} "
               f"{LOWER_BOUND_TAG}  [pre-rule, JEV-24a cut]")
    out.append(f"    NOTE: the whole-corpus figure ${WHOLE_CORPUS_ANCHOR_USD:.2f} "
               f"{LOWER_BOUND_TAG} must never be differenced against the")
    out.append("          anchor above -- it is a different cut of the SAME "
               "corpus. diff() raises rather than allowing it.")
    out.append("")
    delta: Delta | None = None
    try:
        delta = diff(before_fig, after_fig)
    except (WindowsDiffer, CouldNotRun) as exc:
        out.append(f"    NOT DIFFERENCED: {exc}")
        return Criterion(name="R5 realised cost / task",
                         status=NOT_EVALUABLE,
                         detail="the two sides are not comparable; see above"), out, None
    rel = "" if delta.relative is None else f" ({delta.relative:+.1%})"
    out.append(f"    delta ${delta.absolute:+.4f} per delegated task{rel} "
               f"{LOWER_BOUND_TAG}")
    out.append("    R5 is REPORTED, NOT A GATE. It never blocks, in either "
               "direction.")
    return Criterion(name="R5 realised cost / task", status=PASS,
                     value=delta.absolute,
                     detail="reported, not gated"), out, delta


# ---------------------------------------------------------------------------
# The whole report
# ---------------------------------------------------------------------------

@dataclass
class Report:
    before: Side
    after: Side | None
    criteria: list[Criterion] = field(default_factory=list)
    body: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.after is None:
            return EXIT_COULD_NOT_RUN
        if not self.criteria:
            return EXIT_COULD_NOT_RUN
        return worst(*(c.exit_code for c in self.criteria))


def render_no_after(before: Side, *, ledger_dir: Path | None = None,
                    checked: str = "") -> str:
    """The day-one output. It says so; it does not print zeros.

    "No after corpus exists" and "the after corpus cost $0.00" are different
    facts, and conflating them is this repository's most repeated lesson -- the
    inert config fields, the kill switch that stopped one writer of two, the
    jq-comment apostrophe, and `project_dir()`'s baseline of zeros that looked
    like a finished answer.
    """
    out = [
        "=== SPEC §2 R1-R5 before/after report ===",
        "",
        f"  {NO_AFTER_CORPUS}.",
        "",
        "  Nothing has been measured. This is NOT a report that the after side",
        "  cost nothing, took no time and reworked nothing -- there is no after",
        "  side.",
        "",
        # Report what was LOOKED AT, never a remembered fact about the tree.
        # A sentence asserting "agent_route is off" without reading the config
        # would be the same class of error as the kill switch that stopped one
        # writer of two: a message that is true today and unchecked forever.
        f"  What was checked: {checked or 'no after inputs were supplied at all'}",
    ]
    if ledger_dir is not None:
        out.append(f"  Ledger directory read: {ledger_dir} -- 0 assignment rows.")
    out += [
        "",
        "  What exists is the BEFORE anchor, printed here so it is visible:",
        f"    source  {before.source}",
        f"    window  {before.window.describe()}",
    ]
    n = before.n_tasks
    total = before.total_delegated_cost_usd
    out.append(f"    delegated tasks                {n}")
    if total is not None:
        out.append(f"    delegated spend               ${total:.4f} {LOWER_BOUND_TAG}")
    out.append("  " + before.cost_per_delegated_task().render())
    out.append("  " + before.cost_per_outcome().render())
    for note in before.notes:
        out.append(f"    note: {note}")
    rework = before.rework
    if rework is None:
        out.append("    R1 / R2 on the before side: NOT CARRIED by this record. "
                   "Pass --before-session to")
        out.append("    measure them from transcripts.")
    out += [
        "",
        "  To produce a real after side, the router has to be armed and a",
        "  session has to run under it. Arming is a separate, gated decision",
        "  and this module does not perform it.",
    ]
    return "\n".join(out)


def build_report(before: Side, after: Side | None, *,
                 gate_exit: int | None = None,
                 gate_detail: str = "",
                 ledger_dir: Path | None = None,
                 checked: str = "") -> Report:
    report = Report(before=before, after=after)
    if after is None:
        report.body = [render_no_after(before, ledger_dir=ledger_dir,
                                       checked=checked)]
        return report

    body: list[str] = [
        "=== SPEC §2 R1-R5 before/after report ===",
        "",
        f"  before  {before.window.describe()}",
        f"          {before.source}",
        f"  after   {after.window.describe()}",
        f"          {after.source}",
        "",
        f"  {LOWER_BOUND_NOTE}",
        "",
    ]
    c1, out1 = r1_rework(before, after)
    body += out1 + [""]
    c2, out2 = r2_latency(before, after)
    body += out2 + [""]
    c3, out3 = r3_quality(gate_exit, gate_detail)
    body += out3 + [""]
    c5, out5, delta5 = r5_cost(before, after)
    c4, out4 = r4_overhead(before, after, c2, delta5)
    body += out4 + [""]
    body += out5 + [""]
    body.append(power_statement(before, after))
    body.append("")
    body.append("=== VERDICT ===")
    report.criteria = [c1, c2, c3, c4, c5]
    for criterion in report.criteria:
        body.append(criterion.line())
    report.body = body
    return report


def epilogue(code: int) -> str:
    names = {
        EXIT_CLEAN: "CLEAN (ran, nothing to act on)",
        EXIT_COULD_NOT_RUN: "COULD NOT RUN (this is NOT a pass)",
        EXIT_INVOKED_WRONG: "INVOKED WRONG",
        EXIT_REGRESSION: "REGRESSION FOUND",
    }
    banner = f"VERDICT: exit {code} -- {names[code]}"
    if code == EXIT_COULD_NOT_RUN:
        banner += ("\n  This report did not reach a verdict. DO NOT READ IT AS A "
                   "PASS.\n  Nothing has been shown to have helped, or to have "
                   "harmed.")
    return banner


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report",
        description="SPEC §2 R1-R5 before/after. Exit 0 clean / 1 COULD NOT RUN "
                    "/ 2 invoked wrong / 3 regression found.")
    parser.add_argument("--before", default=None,
                        help="data/baseline/delegation-pre-rule-v1-corrected.json "
                             "(the CORRECTED companion, not the frozen -v1).")
    parser.add_argument("--before-scope", default="interactive_sessions_only",
                        help="which scope of the corrected record to read.")
    parser.add_argument("--before-session", action="append", default=None,
                        help="parent transcript(s) for a transcript-derived "
                             "before side, which carries R1 and R2 as well as R5.")
    parser.add_argument("--before-json", default=None,
                        help="a frozen side snapshot (jev-report-side-v1).")
    parser.add_argument("--after-session", action="append", default=None,
                        help="parent transcript(s) of the after corpus.")
    parser.add_argument("--after-ledger", default=None,
                        help="the W1 assignment ledger directory.")
    parser.add_argument("--after-json", default=None,
                        help="a frozen side snapshot (jev-report-side-v1).")
    parser.add_argument("--project", default=None,
                        help="score ONE repo. The ledger is shared across every "
                             "repo jev is installed in (JEV-57).")
    parser.add_argument("--pool-projects", action="store_true",
                        help="score every repo together, deliberately and on "
                             "the record.")
    parser.add_argument("--pricing-version", default=None,
                        help="pricing version of the after side; defaults to "
                             "the before side's, so a mismatch has to be stated.")
    parser.add_argument("--gate-exit", type=int, default=None,
                        help="the exit code src/accuracy_gate.py returned. "
                             "Absent -> R3 is NOT_EVALUABLE -> exit 1.")
    parser.add_argument("--gate-verdict", default=None,
                        help="a JSON file with an 'exit_code' field, as an "
                             "alternative to --gate-exit.")
    parser.add_argument("--json", action="store_true",
                        help="emit the machine-readable summary too.")
    return parser


def _gate(args: argparse.Namespace) -> tuple[int | None, str]:
    if args.gate_exit is not None and args.gate_verdict:
        raise InvokedWrong("--gate-exit and --gate-verdict are exclusive")
    if args.gate_exit is not None:
        return args.gate_exit, "(supplied with --gate-exit)"
    if args.gate_verdict:
        path = Path(args.gate_verdict).expanduser()
        if not path.exists():
            raise CouldNotRun(f"no such gate verdict: {path}")
        record = json.loads(path.read_text(encoding="utf-8"))
        code = record.get("exit_code")
        if not isinstance(code, int):
            raise InvokedWrong(
                f"{path} has no integer 'exit_code'; a verdict file without "
                "one cannot be read as a pass")
        return code, f"(from {path})"
    return None, ""


def _build_before(args: argparse.Namespace, project: str) -> Side:
    if args.before_json:
        return side_from_json(Path(args.before_json).expanduser(), label="before")
    if args.before_session:
        anchor = (side_from_corrected_baseline(Path(args.before).expanduser(),
                                               scope=args.before_scope,
                                               project=project)
                  if args.before else None)
        pricing = anchor.window.pricing_version if anchor else "unknown"
        side = side_from_sessions(
            [Path(s).expanduser() for s in args.before_session],
            label="before", scope=args.before_scope, pricing_version=pricing,
            project=project, window_label="before: transcript-derived")
        # THE CUT IS NOT OPTIONAL WHEN AN ANCHOR IS NAMED. A transcript that
        # runs past `cut.timestamp_utc` is post-rule work wearing a pre-rule
        # label: still disjoint from a later after side, so `comparable()`
        # would wave it through, and the "before" would silently contain the
        # treatment. This is the JEV-24a trap one step out.
        if anchor is not None:
            cut = parse_stamp(anchor.window.ends_at)
            observed = parse_stamp(side.window.ends_at)
            if cut is not None and observed is not None and observed > cut:
                raise InvokedWrong(
                    f"--before-session runs to {side.window.ends_at}, past the "
                    f"anchor's JEV-24a cut at {anchor.window.ends_at}. Work "
                    "after the cut is POST-rule and must not be labelled "
                    "'before'. Supply a session that ends at or before the "
                    "cut, or drop --before and accept a transcript-derived "
                    "window with no cut applied.")
        return side
    if args.before:
        return side_from_corrected_baseline(Path(args.before).expanduser(),
                                            scope=args.before_scope,
                                            project=project)
    raise InvokedWrong(
        "a before side is required: --before (the corrected anchor), "
        "--before-session or --before-json")


def _build_after(args: argparse.Namespace, before: Side,
                 project: str, project_filter: str | None) -> Side | None:
    """The after side, or None -- and None means exactly one thing.

    THREE empty states, not one, because they have three different fixes:

      * no after inputs at all, or a ledger with no rows      -> None, "no
        after corpus exists". The honest day-one answer.
      * a ledger WITH rows and no transcripts supplied        -> InvokedWrong.
        The corpus exists; the invocation did not ask for it. Printing "no
        after corpus exists" here would be a message asserting a fact it never
        checked.
      * rows and transcripts that join to nothing -- CANNOT HAPPEN. The join
        is intention-to-treat, so an unjoined row is an ATTRITION row, not an
        absent one, and R1 reports it as such.
    """
    if args.after_json:
        return side_from_json(Path(args.after_json).expanduser(), label="after")
    ledger_dir = Path(args.after_ledger).expanduser() if args.after_ledger else None
    sessions = [Path(s).expanduser() for s in (args.after_session or [])]
    if ledger_dir is None and not sessions:
        return None
    pricing = args.pricing_version or before.window.pricing_version
    side = side_from_sessions(
        sessions, label="after", scope=before.window.scope,
        pricing_version=pricing, project=project, ledger_dir=ledger_dir,
        project_filter=project_filter, pool_projects=args.pool_projects,
        window_label="after: live")
    if side.tasks:
        return side
    n_rows = 0
    if ledger_dir is not None:
        n_rows = len(_ledger_rows_for(ledger_dir, project=project_filter,
                                      pool_projects=args.pool_projects))
    if n_rows and not sessions:
        raise InvokedWrong(
            f"{ledger_dir} records {n_rows} assignment(s) for this project, "
            "and no --after-session was supplied. The after corpus EXISTS; "
            "this invocation did not ask for it. Pass the parent transcript(s) "
            "whose subagents carry the outcomes.")
    # There is deliberately no third branch for "rows AND sessions AND no
    # tasks": it cannot happen. `join_outcomes` is intention-to-treat, so every
    # ledger row becomes a task even when nothing on disk joins to it -- it
    # becomes an ATTRITION row, which is the honest answer and is already
    # reported by R1. A branch for it would be unreachable code pretending to
    # be a guard.
    return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.project and args.pool_projects:
            raise InvokedWrong(
                "--project and --pool-projects are exclusive: one scores a "
                "single repo, the other says pooling is what you want.")
        # The FILTER and the LABEL are separate. An unspecified `--project`
        # must reach `_ledger_rows_for` as None so it RAISES on two repos;
        # defaulting it to the legacy partition would quietly select a
        # partition instead, which is the confound wearing a default's hat.
        project_filter = args.project
        project = (args.project if args.project
                   else ("<pooled>" if args.pool_projects
                         else "<unpartitioned>"))
        gate_exit, gate_detail = _gate(args)
        before = _build_before(args, project)
        after = _build_after(args, before, project, project_filter)
        ledger_dir = (Path(args.after_ledger).expanduser()
                      if args.after_ledger else None)
        checked = ", ".join(filter(None, [
            f"--after-ledger {ledger_dir}" if ledger_dir else "",
            f"--after-session x{len(args.after_session)}"
            if args.after_session else "",
            f"--after-json {args.after_json}" if args.after_json else "",
        ]))
        report = build_report(before, after, gate_exit=gate_exit,
                              gate_detail=gate_detail, ledger_dir=ledger_dir,
                              checked=checked)
    except assignment_ledger.ProjectsWouldBePooled as exc:
        print(f"INVOKED WRONG: {exc}", file=sys.stderr)
        print(epilogue(EXIT_INVOKED_WRONG), file=sys.stderr)
        return EXIT_INVOKED_WRONG
    except InvokedWrong as exc:
        print(f"INVOKED WRONG: {exc}", file=sys.stderr)
        print(epilogue(EXIT_INVOKED_WRONG), file=sys.stderr)
        return EXIT_INVOKED_WRONG
    except WindowsDiffer as exc:
        print(f"INVOKED WRONG: {exc}", file=sys.stderr)
        print(epilogue(EXIT_INVOKED_WRONG), file=sys.stderr)
        return EXIT_INVOKED_WRONG
    except CouldNotRun as exc:
        print(f"COULD NOT RUN: {exc}", file=sys.stderr)
        print(epilogue(EXIT_COULD_NOT_RUN), file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    print("\n".join(report.body))
    if args.json:
        print()
        print(json.dumps({
            "before": side_to_json(report.before),
            "after": None if report.after is None else side_to_json(report.after),
            "criteria": [
                {"name": c.name, "status": c.status, "value": c.value,
                 "detail": c.detail} for c in report.criteria],
            "exit_code": report.exit_code,
            "lower_bound": LOWER_BOUND_NOTE,
        }, indent=2, sort_keys=True))
    code = report.exit_code
    print()
    print(epilogue(code))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
