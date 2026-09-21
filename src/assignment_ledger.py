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

JEV-57: WHICH REPO DID THIS ROW COME FROM
-----------------------------------------
`jev` installs PER PROJECT, but since W2 (`0f5901f`) the ledger lives at
`$JEV_HOME/data/agent_route/` -- **one directory shared by every repo jev is
installed in**. The `-v1` row schema has no `project` field, so `verify()`
could not partition and rows from unrelated codebases interleaved in one
stream. Every cost and outcome claim this study makes is per delegated task,
and a task belongs to a repo: pooling two repos' tasks into one rate is the
same class of confound as JEV-32 (scoring rows against a config they did not
run under). It looks like a result.

The fix has three parts, and the third is the one that matters:

  * `-v2` adds `project`, sourced from the resolved project directory AT
    DECISION TIME (`$CLAUDE_PROJECT_DIR` in the hook), never inferred later
    from a path or a timestamp.
  * `verify()` partitions by it and REFUSES to aggregate across projects
    unless the caller says so by name (`pool_projects=True`). A refusal is the
    point: silently pooling is exactly the failure being prevented, and a
    default that pools is a default that hides it.
  * **`-v1` rows are fenced, not backfilled.** A row that never carried a
    project cannot be given one honestly -- the ledger is shared, so "it must
    have been this repo" is precisely the inference that is unsafe. Legacy
    rows land in their own partition, `<v1:no-project>`, which never merges
    with a named one. `data/agent_route/assignments/` was EMPTY when this
    landed, so in this install there are zero such rows; the partition exists
    for the installs where there are.

TWO WRITERS, ONE SCHEMA, AND THE ORDER THEY LAND IN
---------------------------------------------------
The rows are written by `hooks/agent_route_actuator.sh`, not by this module;
`ledger_row()` is the Python mirror that
`tests/test_agent_actuator.py::test_the_hooks_row_and_the_python_row_have_the_same_keys`
holds against it. The hook is owned by another agent this wave, so this module
can emit EITHER version: `ledger_row(project=None)` is the `-v1` row the hook
writes today, `ledger_row(project=...)` is `-v2`. `LEDGER_SCHEMA` names what
the deployed writer emits and flips to `-v2` in the same change that lands
`project` in the hook -- until then the parity test stays green AND stays a
working drift detector, because the moment the hook emits `project` it fails
and names this file.
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

#: `-v1`: no `project`, so it cannot be attributed to a repo. This is what
#: every row written before JEV-57 carries, and what the hook still writes.
LEDGER_SCHEMA_V1 = "agent-route-assignment-v1"

#: `-v2`: adds `project`, the resolved project directory at decision time.
LEDGER_SCHEMA_V2 = "agent-route-assignment-v2"

#: What the DEPLOYED writer (`hooks/agent_route_actuator.sh`) emits today.
#: Flip this to `LEDGER_SCHEMA_V2` in the same change that adds `project` to
#: the hook's two jq row objects -- see the module docstring. It is deliberately
#: not bumped ahead of the writer: a schema version that claims a field the
#: rows do not carry is worse than no version at all.
LEDGER_SCHEMA = LEDGER_SCHEMA_V1

#: The partition `-v1` rows land in. Not a project, and never merged with one:
#: "no project recorded" is a distinct, honest answer to "which repo?", and
#: collapsing it into whichever repo happens to be reading is the backfill this
#: ticket forbids.
LEGACY_PARTITION = "<v1:no-project>"


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
    project: str | None = None,
) -> dict:
    """The row the hook writes before the spawn. Also the schema the jq writes.

    Kept in Python as well as in `jq` so a test can assert the two produce the
    same keys -- the drift hazard `state_builders` vs the inline hook already
    demonstrated.

    `project` is the resolved project directory the decision was made in
    (`$CLAUDE_PROJECT_DIR` in the hook), recorded RAW. A worktree's path is not
    its repository's path, and normalising the two together is an analysis
    decision made with knowledge this hook does not have; the ledger's job is
    to record where the decision happened, exactly.

    Omitted -> a `-v1` row, byte-for-byte the shape the deployed hook writes.
    Given -> a `-v2` row. There is no third state: a `-v2` row without a
    project would be a schema that lies.
    """
    row = {
        "schema": LEDGER_SCHEMA_V1 if project is None else LEDGER_SCHEMA_V2,
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
    if project is not None:
        row["project"] = project
    return row


def row_project(row: dict) -> str:
    """Which partition a row belongs to. Missing -> `LEGACY_PARTITION`.

    An empty string is treated as missing too: the hook's `$CLAUDE_PROJECT_DIR`
    is empty when Claude Code did not set it, and "" is not a repo.
    """
    project = row.get("project")
    return project if project else LEGACY_PARTITION


def partition_by_project(rows: list[dict]) -> dict[str, list[dict]]:
    """Rows grouped by the repo the decision was made in, insertion-ordered."""
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(row_project(row), []).append(row)
    return out


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

class ProjectsWouldBePooled(ValueError):
    """`verify()` was handed rows from more than one repo and not told what to
    do about it.

    Raised rather than returned, and raised rather than silently pooled, for
    the JEV-32 reason: a confounded rate is indistinguishable from a real one
    once it is a number on a page. The caller has to say `project=` (score one
    repo) or `pool_projects=True` (score them together, on the record).
    """

    def __init__(self, found: list[str]):
        self.found = found
        super().__init__(
            "the ledger holds rows from "
            f"{len(found)} projects ({', '.join(found)}) and pooling them "
            "would confound every rate derived from the result. Pass "
            "project='<dir>' to score one, or pool_projects=True to say "
            "explicitly that pooling is what you want."
        )


def verify(
    rows: list[dict],
    resolved: dict[str, str],
    config: dict,
    *,
    project: str | None = None,
    pool_projects: bool = False,
) -> dict:
    """Join assignments to what actually ran, within ONE project.

    JEV-57. The ledger at `$JEV_HOME/data/agent_route/` is shared by every repo
    jev is installed in, so "the rows" is not automatically "this repo's rows".
    Three ways to call this, and the default is the safe one:

      * `project="/path/to/repo"` -- score that repo. Rows from any other,
        including the `-v1` legacy partition, are excluded and counted in
        `projects_excluded` so the exclusion is visible rather than assumed.
      * `pool_projects=True` -- score everything together, deliberately. The
        result says `pooled: True` and names every partition it swallowed.
      * neither -- fine while the rows are from one project (the normal case
        for a single install), `ProjectsWouldBePooled` the moment they are not.

    `resolved` is {tool_use_id: resolvedModel}, read from wherever the truth
    happens to live -- a `PostToolUse` echo or a transcript. This function does
    not fetch it, so it stays testable with fakes and costs no API call.

    Five classes, and the interesting one is `overridden`:
      * honoured  -- resolvedModel starts with the tier's resolved_prefix
      * overridden-- we rewrote, something else won. THE ONE THAT MATTERS: an
                     overridden assignment makes the treatment arm identical to
                     the control arm while still looking like a treatment.
      * unobserved-- we rewrote and never saw a resolvedModel. Attrition, and
                     counted as such rather than assumed honoured.
      * unverifiable -- we rewrote, but nothing in `config` maps the row to a
                     `resolved_prefix`, so the join cannot be made. NEVER
                     folded into `honoured` and never into `not_routed`: a row
                     we cannot check is a row we cannot check, and saying so is
                     the whole point of this function.
      * not_routed-- we deliberately left the input alone. Not a failure.

    WHAT "DID WE REWRITE?" IS DECIDED BY, AND WHY IT IS NOT `tier`
    --------------------------------------------------------------
    This used to read `if not tier: -> not_routed`, and it was wrong in the one
    place it mattered most. `JQ_FRONTIER` in `hooks/agent_route_actuator.sh`
    writes **`tier: null`** on every fail-to-frontier row -- it cannot do
    otherwise, because the branch is reached precisely when `config/tiers.json`
    could not be read, so there is no tier key to name -- while still rewriting
    `model` to the frontier alias. So every real fail-to-frontier assignment,
    the branch that bills FRONTIER RATES, was classified "we deliberately left
    the input alone": scored as the control arm, and invisible.

    The test that was supposed to cover this hand-built
    `{"decision": "fail_to_frontier", "tier": "opus5"}` -- a row the hook has
    never produced. It is now generated by running the hook.

    The rewrite test is therefore the thing the hook actually records about
    itself: **a decision that rewrites, and an `assigned_alias` that is not
    null.** The tier, when absent, is recovered from the alias.
    """
    # JEV-57. Partition BEFORE anything is counted. Everything below this block
    # produces a rate, and a rate is the thing that must not be pooled.
    partitions = partition_by_project(rows)
    found = list(partitions)
    excluded: list[str] = []

    if project is not None:
        excluded = [p for p in found if p != project]
        rows = partitions.get(project, [])
        scope = project
    elif pool_projects:
        scope = None
    elif len(found) > 1:
        raise ProjectsWouldBePooled(found)
    else:
        scope = found[0] if found else None

    tiers = config.get("tiers") or {}
    summary = {"honoured": 0, "overridden": 0, "unobserved": 0,
               "unverifiable": 0, "not_routed": 0}
    detail: list[dict] = []

    for row in rows:
        alias = row.get("assigned_alias")
        # A `routed` row with a null alias rewrote nothing. The hook can no
        # longer emit one -- an aliasless tier now fails to frontier -- but a
        # ledger is append-only and rows written before that fix are still on
        # disk, so the reader must not claim an assignment that never happened.
        if row.get("decision") not in tier_map.REWRITING or alias is None:
            summary["not_routed"] += 1
            continue
        tier = row.get("tier") or tier_map.tier_for_alias(config, alias)
        prefix = (tiers.get(tier) or {}).get("resolved_prefix") if tier else None
        got = resolved.get(row.get("tool_use_id"))
        if not prefix:
            verdict = "unverifiable"
        elif got is None:
            verdict = "unobserved"
        elif got.startswith(prefix):
            verdict = "honoured"
        else:
            verdict = "overridden"
        summary[verdict] += 1
        if verdict != "honoured":
            detail.append({
                "tool_use_id": row.get("tool_use_id"),
                "decision": row.get("decision"),
                "tier": tier,
                "assigned_alias": alias,
                "expected_prefix": prefix,
                "resolved_model": got,
                "verdict": verdict,
            })

    total_routed = (summary["honoured"] + summary["overridden"]
                    + summary["unobserved"] + summary["unverifiable"])
    return {
        # JEV-57. The result NAMES its own denominator's scope. A rate that
        # does not say which repo it is a rate for is the confound this ticket
        # exists to stop, and a caller that prints the number without the
        # scope has to have discarded it on purpose.
        "project": scope,
        "pooled": bool(pool_projects),
        "projects_in_ledger": found,
        "projects_excluded": excluded,
        "rows_scored": len(rows),
        "summary": summary,
        "detail": detail,
        "routed_total": total_routed,
        "honour_rate": (summary["honoured"] / total_routed) if total_routed else None,
    }
