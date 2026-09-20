#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-38 + JEV-24a: persist the "before" baseline, in the repo, before the
source can go away.

`session_metrics.py` is a VIEWER. It reads a transcript on demand and prints;
nothing accumulates. JEV-06 was marked done claiming per-session metrics "start
collecting on day 0". They never did. This module is the accumulator.

**Why it is urgent rather than tidy.** The transcripts it reads live in
`~/.claude/projects/`, outside this folder, under Claude Code's
`cleanupPeriodDays` retention -- default 30 days, unset on this machine (see
`retention_finding()`). Every other artifact in this study is self-contained;
the one number the whole before-versus-after comparison rests on was the
exception. A rotated transcript cannot be reconstructed at any price.

**The hard rule, inherited from `data/fixtures/`: DERIVED NUMBERS ONLY.** No
third-party transcript content is copied into this folder. Costs, token classes
by class, wall-clock, turn counts, tool-call counts by name, friction proxies,
delegation counts and file fingerprints -- never prompt text, never message
content, never a subagent `description`. `~/.claude/` is read-only here.

Two streams are written, both under `data/baseline/` and both committed:

    sessions.jsonl   append-only, one row per (session, fingerprint). Keyed by
                     session_id; idempotent, because a row is appended only
                     when the transcript's fingerprint has CHANGED. Re-running
                     on an untouched corpus appends nothing. Readers take the
                     LAST row per session_id.
    manifest.json    what was known at snapshot time that a row cannot carry:
                     the retention finding, the unrecoverable-session count and
                     the method that produced it, and the corpus totals.

**Idempotency is fingerprint-based, not id-based, on purpose.** A live session
is still growing. Keying on `session_id` alone would either double-count on
every run or freeze the first (partial) reading forever. Keying on
`(size, mtime)` of the main transcript plus every subagent file means an
unchanged corpus is a no-op and a grown session gets one new row, so the growth
itself is on the record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_loader as cl  # noqa: E402
import paths  # noqa: E402
import session_metrics as sm  # noqa: E402
import store  # noqa: E402

SESSIONS = paths.BASELINE / "sessions.jsonl"
MANIFEST = paths.BASELINE / "manifest.json"
DELEGATION = paths.BASELINE / "delegation-pre-rule-v1.json"

SCHEMA_VERSION = "baseline-v1"

# ---------------------------------------------------------------------------
# JEV-24a: the cut.
#
# The ticket says "cut the corpus at a fixed timestamp: the moment Q17b was
# answered, 2026-09-20". The moment itself was never written down. The first
# DURABLE record of it is the commit that introduced the Q17b row into SPEC.md:
#
#   f890a3b9cddee9109638381968935d001bc14ffc
#   "Update SPEC and ISSUES with the twenty grilling decisions"
#   2026-09-20T16:41:49+05:30  ==  2026-09-20T11:11:49Z
#
# The real adoption moment is at or BEFORE that commit, never after -- the rule
# had to be answered before it could be written down. So using the commit as
# the cut is conservative in the only direction that matters: everything this
# module counts as pre-rule is genuinely pre-rule. It may exclude a few minutes
# of genuinely pre-rule activity; it cannot include post-rule activity.
# ---------------------------------------------------------------------------
Q17B_CUT_UTC = "2026-09-20T11:11:49Z"
Q17B_CUT_COMMIT = "f890a3b9cddee9109638381968935d001bc14ffc"
Q17B_CUT_BASIS = (
    "first durable record of Q17b: the commit that introduced the Q17b row into "
    "SPEC.md. The rule was answered at or before this instant, never after, so "
    "the cut cannot admit post-rule behaviour."
)


def _cut() -> datetime:
    return datetime.fromisoformat(Q17B_CUT_UTC.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Retention -- established, not guessed
# ---------------------------------------------------------------------------

def retention_finding() -> dict[str, Any]:
    """What Claude Code's transcript retention actually is.

    Established 2026-09-20 from primary sources (official docs + this machine's
    own config), NOT from recollection. Recorded because the study otherwise
    rests on an unstated assumption about someone else's storage.
    """
    configured = None
    for candidate in (Path.home() / ".claude" / "settings.json",
                      paths.ROOT / ".claude" / "settings.local.json"):
        try:
            data = json.loads(candidate.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if "cleanupPeriodDays" in data:
            configured = data["cleanupPeriodDays"]
    return {
        "setting": "cleanupPeriodDays",
        "default_days": 30,
        "configured_value": configured,
        "effective_days": configured if configured is not None else 30,
        "covers_subagent_transcripts": True,
        "when_cleanup_runs": "retention sweep at CLI startup (skipped by --bare)",
        "claude_code_version": "2.1.278",
        "established_on": "2026-09-20",
        "sources": [
            "https://code.claude.com/docs/en/data-usage.md#data-retention -- "
            "'Claude Code clients store session transcripts locally in plaintext "
            "under ~/.claude/projects/ for 30 days by default to enable session "
            "resumption. Adjust the period with cleanupPeriodDays.'",
            "https://code.claude.com/docs/en/claude-directory.md"
            "#automatic-cleanup-in-claude-code -- default 30 days, minimum 1 day; "
            "the cleanup table lists projects/<project>/<session>/subagents/ "
            "explicitly, so subagent transcripts are swept on the same clock.",
            "https://code.claude.com/docs/en/settings-reference.md",
        ],
        "what_this_means_for_the_study": (
            "The 'before' baseline's source data is deleted 30 days after a "
            "session's files were last touched, by a third party's sweep, on a "
            "clock this repo does not control. data/baseline/ is the only copy "
            "that survives that. It is committed for exactly that reason."
        ),
    }


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

def project_dir() -> Path:
    slug = str(paths.ROOT).replace("/", "-")
    return paths.CLAUDE_PROJECTS / slug


def transcripts() -> list[Path]:
    d = project_dir()
    return sorted(d.glob("*.jsonl")) if d.is_dir() else []


def subagent_files(path: Path) -> list[Path]:
    d = path.with_suffix("") / "subagents"
    return sorted(d.glob("*.jsonl")) if d.is_dir() else []


def _stat(p: Path) -> dict[str, Any]:
    st = p.stat()
    return {
        "name": p.name,
        "size_bytes": st.st_size,
        "mtime_utc": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
    }


def fingerprint(path: Path) -> dict[str, Any]:
    """Enough for a later re-read to PROVE it is the same file.

    Size and mtime of the main transcript and of every subagent file, plus a
    digest over all of it so a single string can be compared.
    """
    main = _stat(path)
    subs = [_stat(p) for p in subagent_files(path)]
    blob = json.dumps({"main": main, "subagents": subs}, sort_keys=True)
    return {
        "transcript_size_bytes": main["size_bytes"],
        "transcript_mtime_utc": main["mtime_utc"],
        "subagent_files": subs,
        "digest": hashlib.sha256(blob.encode()).hexdigest()[:32],
    }


# ---------------------------------------------------------------------------
# Request-level walk -- the unit JEV-24a actually needs
# ---------------------------------------------------------------------------

def requests(path: Path) -> Iterator[dict[str, Any]]:
    """One record per DEDUPLICATED billable request, carrying its timestamp and
    whether it ran inside a subagent.

    `session_metrics.analyse` aggregates a whole session, which is the wrong
    granularity for JEV-24a: the "delegate where possible" rule was adopted
    *mid-session* in the only real work session this repo has, so a
    session-level cut is meaningless here. See `cut_note` in the frozen record.

    Dedupe is by `requestId` across the main transcript AND its subagents
    together, and `usage.iterations[]` is never read -- the two double-counting
    hazards `session_metrics` documents.
    """
    seen: set[str] = set()
    for line in sm._lines(path):
        message = line.get("message") or {}
        if message.get("role") != "assistant":
            continue
        rid = line.get("requestId")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        usage = message.get("usage") or {}
        bucket = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        }
        model = message.get("model") or "unknown"
        # A model absent from config/pricing.json prices as None, NOT as zero.
        # `claude-opus-4-7` is unpriced on this corpus, and coercing it to 0.0
        # would silently shrink the denominator of every rate below.
        cost = cl.cost_usd(model, bucket)
        yield {
            "ts": sm._parse_ts(line.get("timestamp")),
            "model": model,
            "cost_usd": cost if cost is not None else 0.0,
            "priced": cost is not None,
            "delegated": bool(line.get("_subagent_file")) or bool(line.get("isSidechain")),
        }


def delegated_tasks(path: Path) -> list[dict[str, Any]]:
    """One record per delegated task, from the subagent transcripts themselves.

    Ground truth is `subagents/*.meta.json`, not a tally of `Agent` tool_use
    blocks in the main transcript: a task spawned by another subagent
    (`spawnDepth` > 1) never appears as a tool call in the main transcript at
    all, so the tool-call tally under-counts. The task's timestamp is its
    subagent transcript's FIRST request, which is when the delegation actually
    began.

    `description` is deliberately NOT read: it is prompt-derived third-party
    text and copying it here would break the derived-numbers-only rule.
    """
    out = []
    for f in subagent_files(path):
        meta: dict[str, Any] = {}
        meta_path = f.with_suffix(".meta.json")
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        stamps = [r["ts"] for r in requests(f) if r["ts"]]
        cost = sum(r["cost_usd"] for r in requests(f))
        out.append({
            "agent_file": f.name,
            "agent_type": meta.get("agentType"),
            "spawn_depth": meta.get("spawnDepth"),
            "request_shape": meta.get("requestShape"),
            "tool_use_id": meta.get("toolUseId"),
            "started_at": min(stamps).isoformat() if stamps else None,
            "ended_at": max(stamps).isoformat() if stamps else None,
            "requests": len(stamps),
            "cost_usd": round(cost, 6),
        })
    return out


# ---------------------------------------------------------------------------
# Session classification and human-prompt counts, from Claude Code's own index
# ---------------------------------------------------------------------------

def prompt_index() -> list[dict[str, Any]]:
    """`~/.claude/history.jsonl`, filtered to this repo, READING ONLY
    {timestamp, sessionId}. The `display` field is the prompt text and is never
    touched.
    """
    out = []
    try:
        raw = paths.CLAUDE_HISTORY.read_text(errors="ignore")
    except OSError:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("project") != str(paths.ROOT):
            continue
        ts = row.get("timestamp")
        out.append({
            "session_id": row.get("sessionId"),
            "at": datetime.fromtimestamp(ts / 1000.0, timezone.utc).isoformat()
            if isinstance(ts, (int, float)) else None,
        })
    return out


def unrecoverable() -> dict[str, Any]:
    """How many sessions were ALREADY GONE at first snapshot.

    An unknown gap reported as zero is worse than a gap reported honestly, so
    the method is recorded beside the number and its blind spot is stated.

    Method: `~/.claude/history.jsonl` is an index of every prompt the user
    typed, carrying `sessionId` and `project`. It is written by Claude Code and
    is NOT swept by `cleanupPeriodDays` (it is not under `projects/`). Any
    session_id it lists for this repo that has no transcript on disk is a
    session whose transcript has been reaped.

    The blind spot, stated rather than hidden: this index only records sessions
    that received at least one TYPED prompt. A non-interactive session
    (`claude -p`, an advisor call, a hook-spawned run) never appears in it, so
    a reaped non-interactive session is invisible to this method and is NOT
    counted. The number below is therefore a LOWER BOUND on reaped sessions,
    and is labelled as such.
    """
    on_disk = {p.stem for p in transcripts()}
    index = prompt_index()
    if not index and not paths.CLAUDE_HISTORY.exists():
        return {
            "determinable": False,
            "count": None,
            "method": "none available",
            "why_not": "~/.claude/history.jsonl is absent; there is no independent "
                       "index of sessions to diff the on-disk corpus against. The "
                       "number of already-unrecoverable sessions is UNKNOWN and "
                       "must not be read as zero.",
        }
    indexed = {r["session_id"] for r in index if r["session_id"]}
    missing = sorted(indexed - on_disk)
    return {
        "determinable": True,
        "count": len(missing),
        "is_lower_bound": True,
        "missing_session_ids": missing,
        "method": "diff ~/.claude/history.jsonl (prompt index, project-filtered, "
                  "reading only {timestamp, sessionId}) against transcripts on disk",
        "blind_spot": "the prompt index records only sessions that received a typed "
                      "prompt; a reaped NON-interactive session (claude -p, advisor, "
                      "hook-spawned) leaves no trace in it and is not counted. Treat "
                      "the count as a lower bound, never as a proof of zero loss.",
        "indexed_sessions": len(indexed),
        "sessions_on_disk": len(on_disk),
    }


# ---------------------------------------------------------------------------
# One row per session
# ---------------------------------------------------------------------------

def session_row(path: Path, interactive_ids: set[str], snapshot_at: str) -> dict[str, Any]:
    m = sm.analyse(path)
    reqs = list(requests(path))
    tasks = delegated_tasks(path)
    main_cost = sum(r["cost_usd"] for r in reqs if not r["delegated"])
    sub_cost = sum(r["cost_usd"] for r in reqs if r["delegated"])
    prompts = [r for r in prompt_index() if r["session_id"] == path.stem]

    row = {
        "schema": SCHEMA_VERSION,
        "session_id": m.session_id,
        "snapshot_at": snapshot_at,
        # Provenance of the file, so a later re-read can prove identity.
        "source": fingerprint(path),
        # Whether a human ever typed into this session. Heuristic, named here so
        # it can be argued with: a session present in Claude Code's prompt index
        # received typed prompts; one absent from it was invoked by a tool.
        "kind": "interactive" if m.session_id in interactive_ids else "tool_invoked",
        "kind_basis": "presence in ~/.claude/history.jsonl for this project",
        "human_prompts": len(prompts),
        "first_human_prompt_at": prompts[0]["at"] if prompts else None,
        "last_human_prompt_at": prompts[-1]["at"] if prompts else None,
        # Timing
        "started_at": m.started_at,
        "ended_at": m.ended_at,
        "wall_clock_s": m.wall_clock_s,
        "reported_total_duration_s": m.reported_total_duration_s,
        "reported_api_duration_s": m.reported_api_duration_s,
        "reported_tool_duration_s": m.reported_tool_duration_s,
        # Tokens, by class, never summed into one number
        "input_tokens": m.input_tokens,
        "output_tokens": m.output_tokens,
        "cache_creation_input_tokens": m.cache_creation_input_tokens,
        "cache_read_input_tokens": m.cache_read_input_tokens,
        "thinking_tokens": m.thinking_tokens,
        "web_search_requests": m.web_search_requests,
        # Cost, with the reconciliation delta published rather than tuned away.
        # reported_cost_usd is null until the session ends: Claude Code writes
        # its cost-state line at session end, so a live session has none.
        "computed_cost_usd": m.computed_cost_usd,
        "reported_cost_usd": m.reported_cost_usd,
        "cost_delta_pct": m.cost_delta_pct,
        "unpriced_models": m.unpriced_models,
        "unpriced_requests": sum(1 for r in reqs if not r["priced"]),
        "main_session_cost_usd": round(main_cost, 6),
        "delegated_cost_usd": round(sub_cost, 6),
        # Turns and tools
        "assistant_lines": m.assistant_lines,
        "unique_requests": m.unique_requests,
        "duplication_factor": m.duplication_factor,
        "user_turns": m.user_turns,
        "sidechain_lines": m.sidechain_lines,
        "tool_calls": m.tool_calls,
        "tool_errors": m.tool_errors,
        "models": m.models,
        "lines_added": m.lines_added,
        "lines_removed": m.lines_removed,
        # Friction proxies
        "permission_denials": m.permission_denials,
        "user_interruptions": m.user_interruptions,
        # Delegation
        "delegated_tasks": len(tasks),
        "delegated_task_agent_types": dict(
            Counter(t["agent_type"] or "unknown" for t in tasks)),
        "delegated_task_spawn_depths": dict(
            Counter(str(t["spawn_depth"]) for t in tasks)),
        "delegated_requests": sum(1 for r in reqs if r["delegated"]),
        "main_session_requests": sum(1 for r in reqs if not r["delegated"]),
        "tasks": tasks,
    }
    return row


def existing_digests() -> dict[str, str]:
    """Last recorded fingerprint per session_id."""
    out: dict[str, str] = {}
    if not SESSIONS.exists():
        return out
    for raw in SESSIONS.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        sid = row.get("session_id")
        digest = (row.get("source") or {}).get("digest")
        if sid and digest:
            out[sid] = digest
    return out


def snapshot() -> dict[str, Any]:
    """Append a row for every session whose transcript has changed since last
    time. Unchanged sessions append nothing -- that is the idempotence."""
    paths.BASELINE.mkdir(parents=True, exist_ok=True)
    snapshot_at = store.utcnow()
    interactive = {r["session_id"] for r in prompt_index() if r["session_id"]}
    known = existing_digests()

    appended, skipped, rows = [], [], []
    for path in transcripts():
        row = session_row(path, interactive, snapshot_at)
        rows.append(row)
        if known.get(row["session_id"]) == row["source"]["digest"]:
            skipped.append(row["session_id"])
            continue
        store.append_jsonl(SESSIONS, row)
        appended.append(row["session_id"])

    manifest = {
        "schema": SCHEMA_VERSION,
        "ticket": "JEV-38",
        "snapshot_at": snapshot_at,
        "project_root": str(paths.ROOT),
        "transcript_dir": str(project_dir()),
        "sessions_captured": len(rows),
        "sessions_appended_this_run": appended,
        "sessions_unchanged_this_run": skipped,
        "total_computed_cost_usd": round(sum(r["computed_cost_usd"] for r in rows), 6),
        "total_delegated_cost_usd": round(sum(r["delegated_cost_usd"] for r in rows), 6),
        "total_delegated_tasks": sum(r["delegated_tasks"] for r in rows),
        "total_human_prompts": sum(r["human_prompts"] for r in rows),
        "unpriced_requests": sum(r["unpriced_requests"] for r in rows),
        "unpriced_models": sorted({m for r in rows for m in r["unpriced_models"]}),
        "unpriced_note": (
            "Spend on a model absent from config/pricing.json is NOT included in "
            "total_computed_cost_usd. It is counted here so the gap is visible."
        ),
        "window": {
            "first_activity_utc": min((r["started_at"] for r in rows if r["started_at"]),
                                      default=None),
            "last_activity_utc": max((r["ended_at"] for r in rows if r["ended_at"]),
                                     default=None),
        },
        "retention": retention_finding(),
        "already_unrecoverable": unrecoverable(),
        "derived_numbers_only": (
            "No third-party transcript content is copied into this folder. No "
            "prompt text, no message content, no subagent description. Only "
            "counts, costs, timings and file fingerprints."
        ),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    return manifest


# ---------------------------------------------------------------------------
# JEV-24a
# ---------------------------------------------------------------------------

def delegation_baseline() -> dict[str, Any]:
    """The pre-rule delegation baseline: the fraction of spend that was
    delegated to subagents BEFORE the "delegate where possible" rule.

    Cut at `Q17B_CUT_UTC`, at REQUEST level rather than session level -- see
    `requests()` for why the session-level cut the ticket describes does not
    work on this corpus.

    Two measures, because they answer different questions and can disagree
    sharply. `by_spend` is the one A2.6 registers ("the fraction of spend that
    was delegated"). `by_task_count` needs a denominator and none is
    self-evident, so all three raw counts are frozen and the chosen denominator
    is named rather than implied.
    """
    cut = _cut()
    per_session = []
    for path in transcripts():
        reqs = [r for r in requests(path) if r["ts"] and r["ts"] < cut]
        tasks = [t for t in delegated_tasks(path)
                 if t["started_at"] and datetime.fromisoformat(t["started_at"]) < cut]
        prompts = [r for r in prompt_index()
                   if r["session_id"] == path.stem and r["at"]
                   and datetime.fromisoformat(r["at"]) < cut]
        per_session.append({
            "session_id": path.stem,
            "kind": "interactive" if prompts else "tool_invoked",
            "requests_pre_cut": len(reqs),
            "unpriced_requests_pre_cut": sum(1 for r in reqs if not r["priced"]),
            "unpriced_models_pre_cut": sorted({r["model"] for r in reqs if not r["priced"]}),
            "main_cost_usd": round(sum(r["cost_usd"] for r in reqs if not r["delegated"]), 6),
            "delegated_cost_usd": round(sum(r["cost_usd"] for r in reqs if r["delegated"]), 6),
            "delegated_tasks": len(tasks),
            "human_prompts": len(prompts),
            "first_request_utc": min((r["ts"] for r in reqs), default=None),
            "last_request_utc": max((r["ts"] for r in reqs), default=None),
        })

    def totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
        main = sum(r["main_cost_usd"] for r in rows)
        deleg = sum(r["delegated_cost_usd"] for r in rows)
        tasks = sum(r["delegated_tasks"] for r in rows)
        prompts = sum(r["human_prompts"] for r in rows)
        total = main + deleg
        unpriced = sum(r["unpriced_requests_pre_cut"] for r in rows)
        return {
            "sessions": len(rows),
            "unpriced_requests": unpriced,
            "unpriced_models": sorted({m for r in rows for m in r["unpriced_models_pre_cut"]}),
            "unpriced_note": (
                "requests on a model absent from config/pricing.json contribute "
                "0 to both numerator and denominator of the by-spend rate. They "
                "are counted here rather than hidden."
            ),
            "main_session_cost_usd": round(main, 6),
            "delegated_cost_usd": round(deleg, 6),
            "total_cost_usd": round(total, 6),
            "delegated_tasks": tasks,
            "human_prompts": prompts,
            "delegation_rate_by_spend": round(deleg / total, 6) if total else None,
            "delegation_rate_by_task_count": (
                round(tasks / (tasks + prompts), 6) if (tasks + prompts) else None),
        }

    interactive_rows = [r for r in per_session if r["kind"] == "interactive"]
    stamps = [r["first_request_utc"] for r in per_session if r["first_request_utc"]]
    ends = [r["last_request_utc"] for r in per_session if r["last_request_utc"]]

    record = {
        "schema": "delegation-pre-rule-v1",
        "ticket": "JEV-24a",
        "frozen_at": store.utcnow(),
        "cut": {
            "timestamp_utc": Q17B_CUT_UTC,
            "commit": Q17B_CUT_COMMIT,
            "basis": Q17B_CUT_BASIS,
            "direction": "conservative: the rule was adopted at or before the cut, "
                         "so nothing counted here can be post-rule behaviour",
        },
        "cut_note": (
            "JEV-24a says 'sessions after that point are already post-rule'. On "
            "this corpus that unit does not work: the rule was adopted MID-SESSION "
            "inside 4ba49645, the only sustained work session the repo has, which "
            "spans 2026-09-19T19:58Z to the present. A session-level cut would "
            "either drop the entire real corpus or admit the post-rule half of it. "
            "The cut is therefore applied per billable REQUEST and per delegated "
            "TASK, by timestamp. This is a deviation from the ticket's literal "
            "wording and is recorded as one."
        ),
        "transcript_window": {
            "first_request_utc": min(stamps).isoformat() if stamps else None,
            "last_pre_cut_request_utc": max(ends).isoformat() if ends else None,
            "cut_utc": Q17B_CUT_UTC,
        },
        "denominators": {
            "by_spend": "delegated_cost_usd / (main_session_cost_usd + "
                        "delegated_cost_usd), over deduplicated billable requests "
                        "timestamped before the cut. This is the measure A2.6 "
                        "registers and is the PRIMARY figure.",
            "by_task_count": "delegated_tasks / (delegated_tasks + human_prompts). "
                             "A 'unit of work' has no canonical count in a "
                             "transcript; a typed human prompt is the closest "
                             "available analogue of a unit of work that was NOT "
                             "delegated. The raw counts are frozen beside the "
                             "ratio so any other denominator can be recomputed.",
        },
        "all_sessions": totals(per_session),
        "interactive_sessions_only": totals(interactive_rows),
        "per_session": [
            {**r,
             "first_request_utc": r["first_request_utc"].isoformat() if r["first_request_utc"] else None,
             "last_request_utc": r["last_request_utc"].isoformat() if r["last_request_utc"] else None}
            for r in per_session
        ],
        "external_validity_note": (
            "PREREGISTRATION A2.6 registers this as the anchor for the confound: "
            "the 'delegate where possible' rule deliberately raises the delegation "
            "rate, improving power and lowering external validity. This is the "
            "rate before that reshaping. A2.5 asks for the analysis with and "
            "without this experiment's own infrastructure work -- on this corpus "
            "essentially ALL the work is infrastructure work on this experiment, "
            "so the 'without' variant is empty and the split offered instead is "
            "interactive versus tool-invoked sessions."
        ),
        "limitations": (
            "The pre-cut window is roughly 15 hours of a single-author, "
            "single-repo corpus. It is a point estimate from one session, not a "
            "sample. It bounds nothing and must be reported as an anchor, not as "
            "a population rate."
        ),
    }
    paths.BASELINE.mkdir(parents=True, exist_ok=True)
    DELEGATION.write_text(json.dumps(record, indent=2) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist the 'before' baseline (JEV-38/24a).")
    parser.add_argument("--snapshot", action="store_true", help="append changed sessions")
    parser.add_argument("--delegation", action="store_true", help="freeze the JEV-24a baseline")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not (args.snapshot or args.delegation):
        args.snapshot = args.delegation = True

    if args.snapshot:
        manifest = snapshot()
        if args.json:
            print(json.dumps(manifest, indent=2))
        else:
            u = manifest["already_unrecoverable"]
            print(f"snapshot        {manifest['sessions_captured']} sessions "
                  f"({len(manifest['sessions_appended_this_run'])} appended, "
                  f"{len(manifest['sessions_unchanged_this_run'])} unchanged)")
            print(f"total spend     ${manifest['total_computed_cost_usd']:.4f}")
            print(f"delegated       ${manifest['total_delegated_cost_usd']:.4f} "
                  f"over {manifest['total_delegated_tasks']} tasks")
            print(f"retention       cleanupPeriodDays={manifest['retention']['effective_days']}d "
                  f"({'configured' if manifest['retention']['configured_value'] is not None else 'DEFAULT, unset'})")
            print(f"unrecoverable   {u['count'] if u['determinable'] else 'UNKNOWN'}"
                  f"{' (lower bound)' if u.get('is_lower_bound') else ''}")
            print(f"written         {SESSIONS}")

    if args.delegation:
        record = delegation_baseline()
        a, i = record["all_sessions"], record["interactive_sessions_only"]
        if args.json:
            print(json.dumps(record, indent=2))
        else:
            print()
            print(f"JEV-24a pre-rule delegation baseline (cut {Q17B_CUT_UTC})")
            for label, t in (("all sessions", a), ("interactive only", i)):
                print(f"  {label:<18} spend ${t['total_cost_usd']:.4f} "
                      f"(delegated ${t['delegated_cost_usd']:.4f})")
                print(f"  {'':<18} by spend      {t['delegation_rate_by_spend']}")
                print(f"  {'':<18} by task count {t['delegation_rate_by_task_count']} "
                      f"({t['delegated_tasks']} tasks / {t['human_prompts']} prompts)")
            print(f"  written           {DELEGATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
