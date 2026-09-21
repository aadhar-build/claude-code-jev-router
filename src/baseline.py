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

**JEV-59: the key is (fingerprint, costing rule, pricing version), not the
fingerprint alone -- and that is the whole ticket.** A row is not a function of
the transcript; it is a function of the transcript AND the rule that priced it.
Keyed on the fingerprint only, correcting the costing rule changed nothing on
disk: the transcripts were untouched, so the stream said "nothing to do" and
went on carrying costs from a rule that had been withdrawn. That is idempotent
and wrong, which is worse than stale, because it looks current. With the rule
and the pricing snapshot in the key, a rule change re-snapshots itself exactly
once and then settles -- the "one-off forced re-snapshot" the ticket asks for,
without a `--force` flag anyone has to remember to pass.

**Rows say what produced them, and old rows are not rewritten.** Every
`baseline-v2` row carries `costing_rule` and `pricing_version`. The `-v1` rows
already in the stream do not, and are left exactly as they were: an absent
`costing_rule` reads as `session_metrics.COSTING_RULE_LEGACY` via
`row_costing_rule()`. Nothing is deleted and nothing is back-stamped, so the
old numbers remain auditable and are distinguishable from the new ones by a
field rather than by a date somebody has to look up.

**The stream is a HISTORY; the totals are over the last row per session.** One
row per reading, so a session that grew has several. Summing every row
double-counts -- 29 rows over 15 sessions summed to ~$724 against a true
$125.58. `latest_per_session()` is the aggregation rule, in code, and
`manifest.json` states it in words beside its own totals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
# The corrected companion. The frozen v1 record above STAYS -- it is the
# pre-registered artifact and several things depend on its being immutable --
# but it was computed under a defective request rule, so it is no longer the
# file analysis should read. This one is, and it carries both numbers plus the
# reason they differ. See `delegation_baseline_corrected`.
CORRECTED = paths.BASELINE / "delegation-pre-rule-v1-corrected.json"

# JEV-59. `baseline-v2` adds two fields to every row -- `costing_rule` and
# `pricing_version` -- so a row says what produced its numbers. `-v1` rows do
# not carry them and are NOT backfilled: a reader treats an absent
# `costing_rule` as `sm.COSTING_RULE_LEGACY`, which is a claim about what is
# missing rather than an invented value.
SCHEMA_VERSION = "baseline-v2"
SCHEMA_VERSION_V1 = "baseline-v1"


def row_costing_rule(row: dict[str, Any]) -> str:
    """Which costing rule a stream row was produced under.

    Absent -> the pre-`98979a7` first-copy rule, because that is the only rule
    that was ever in production without stamping itself. Stated once, here, so
    no reader has to re-derive it and none can quietly assume the current one.
    """
    return row.get("costing_rule") or sm.COSTING_RULE_LEGACY


def row_pricing_version(row: dict[str, Any]) -> str:
    """Which pricing snapshot a stream row was priced under. Absent -> the only
    snapshot that predates the field, `pricing-2026-09-20` -- the one that had
    not yet priced `claude-opus-4-7` and therefore produced $0.00 sessions."""
    return row.get("pricing_version") or "pricing-2026-09-20"

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

BASELINE_PROJECT_ENV = "JEV_BASELINE_PROJECT"


def baseline_project_root() -> Path:
    """Which project's transcripts this module reads, defaulting to this one.

    Claude Code keys both `~/.claude/projects/<slug>/` and the `project` field
    of `~/.claude/history.jsonl` on the working directory's absolute path. A
    GIT WORKTREE has a different absolute path, so running this module from
    `.claude/worktrees/<name>` silently reads a different, near-empty corpus
    and produces a baseline of zeros that looks like a finished answer. That is
    not a hypothetical: the corrected companion was computed from a worktree.

    `$JEV_BASELINE_PROJECT` names the project root to read instead, and BOTH
    the transcript directory and the prompt-index filter are derived from it,
    so the two can never point at different projects. Whatever it resolves to
    is recorded in every artifact this module writes.
    """
    override = os.environ.get(BASELINE_PROJECT_ENV)
    return Path(override).resolve() if override else paths.ROOT


def project_dir() -> Path:
    """Claude Code's transcript directory for this project.

    The slug replaces EVERY non-alphanumeric character with a dash, not just
    `/`. The old `replace("/", "-")` is right for a path made of letters,
    digits and slashes and wrong for any other -- `.claude/worktrees/x` maps to
    `--claude-worktrees-x`, and the naive slug looked for `-.claude-...`, found
    nothing, and reported an empty corpus rather than an error. An empty corpus
    is the dangerous failure here: it produces a baseline of zeros that looks
    like a finished answer.

    The naive form is still tried as a fallback so an existing directory
    written under it is not orphaned.
    """
    root = str(baseline_project_root())
    slug = re.sub(r"[^a-zA-Z0-9]", "-", root)
    candidate = paths.CLAUDE_PROJECTS / slug
    if candidate.is_dir():
        return candidate
    legacy = paths.CLAUDE_PROJECTS / root.replace("/", "-")
    return legacy if legacy.is_dir() else candidate


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

    **This function owns no counting rules.** It is a thin projection of
    `session_metrics.billable_requests`, which is the one place the dedupe key,
    the `iterations[]` asymmetry, the keep-the-COMPLETED-copy rule and the
    cache-write TTL split are written down. It used to own its own walk, and
    that is exactly how the two diverged: it deduped on `requestId` alone, kept
    the FIRST copy -- the `input_tokens: 2` placeholder -- and never read
    `usage.iterations[]`, because all 48 growing keys sit inside subagent
    transcripts. `tests/test_baseline.py` now fails the moment the two rules
    disagree again.

    **The size of the divergence depends on the window, and the two numbers
    must not be swapped for each other** -- commit `98979a7`, SPEC.md §11:

      * WHOLE CORPUS, NO CUT: $105.09 against $171.94, the frozen rule
        understating delegated spend by **38.9%**. This figure may only ever
        be quoted with the words "whole-corpus, no cut" attached.
      * UNDER THE JEV-24a CUT -- the window `delegation-pre-rule-v1.json` was
        actually frozen under, and therefore the one that describes the "before"
        anchor: **+45.2%** ($11.04 -> $20.16 delegated, $1.58 -> $2.88 per
        delegated task, +82.6%).

    Quoting 38.9% against the frozen record is the error §11 was written to
    stop: a real 20% saving measured against the old $1.58 anchor would have
    been published as a 46% INCREASE.

    `session_metrics.analyse` aggregates a whole session, which is the wrong
    granularity for JEV-24a: the "delegate where possible" rule was adopted
    *mid-session* in the only real work session this repo has, so a
    session-level cut is meaningless here. See `cut_note` in the frozen record.

    A model absent from `config/pricing.json` prices as None upstream. It is
    projected to 0.0 here with `priced=False` beside it, so an unpriced request
    contributes to neither numerator nor denominator and is still countable.
    """
    for record in sm.billable_requests(path):
        usage = record.get("usage") or {}
        yield {
            "ts": record["ts"],
            "model": record["model"],
            "cost_usd": record["cost_usd"] if record["priced"] else 0.0,
            "priced": record["priced"],
            "delegated": record["delegated"],
            # Not a counting rule: a plain sum of fields `billable_requests`
            # has already normalised and merged. It exists so an unpriced
            # request can be told apart from a COVERAGE HOLE. `<synthetic>`
            # rows carry no rate and no tokens; a real model missing from
            # `config/pricing.json` carries tokens. Counting the two together
            # is how the manifest came to say `unpriced_requests: 5` beside
            # `unpriced_models: []` -- two fields contradicting each other on
            # the same page.
            "billable_tokens": sum(
                usage.get(k, 0) for k in
                sm.SCALAR_TOKEN_FIELDS + sm.SCALAR_CACHE_FIELDS),
        }


def legacy_v1_requests(path: Path) -> Iterator[dict[str, Any]]:
    """QUARANTINED. The defective rule `delegation-pre-rule-v1.json` was frozen
    under. Nothing in the production path may call this.

    It is kept for one purpose only: the corrected companion has to say what
    the frozen rule yields *today*, so that the movement between the frozen
    file and the corrected one can be split into the part caused by the rule
    and the part caused by `config/pricing.json` drifting underneath it
    (`pricing-2026-09-20` -> `-20b` priced `claude-opus-4-7`, which had been
    counted as unpriced). Without this, the two effects are one number and
    neither is attributable.

    Its three defects, named so nobody restores it by accident:
      1. dedupes on `requestId` alone, not the `(requestId, message.id)` pair;
      2. keeps the FIRST copy of a duplicated request -- the streaming
         placeholder carrying `input_tokens: 2` -- instead of the completed one;
      3. never reads `usage.iterations[]`, and prices cache writes at one flat
         multiplier rather than splitting 5-minute from 1-hour TTL.
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
        if row.get("project") != str(baseline_project_root()):
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
        # JEV-59. WHAT PRODUCED THESE NUMBERS. Without these two fields a row
        # costed under the defective first-copy rule and a row costed under
        # the corrected one are indistinguishable in the same append-only file.
        # The short id only. The prose that decodes it lives once, in
        # `manifest.json` and in `session_metrics.COSTING_RULE_DESCRIPTION` --
        # a sentence repeated in all 44 rows is both bloat and a long free-text
        # string in a file whose whole discipline is DERIVED NUMBERS ONLY.
        "costing_rule": sm.COSTING_RULE,
        "pricing_version": cl.pricing()["version"],
        "computed_cost_usd": m.computed_cost_usd,
        "reported_cost_usd": m.reported_cost_usd,
        "cost_delta_pct": m.cost_delta_pct,
        "unpriced_models": m.unpriced_models,
        # The COVERAGE HOLE: requests that were billable and could not be
        # priced. Matched to `unpriced_models` on purpose -- the two used to
        # disagree because this line counted every unpriced request including
        # the zero-token `<synthetic>` ones, which are not a coverage hole.
        "unpriced_requests": sum(
            1 for r in reqs if not r["priced"] and r["billable_tokens"]),
        "unpriced_zero_token_requests": sum(
            1 for r in reqs if not r["priced"] and not r["billable_tokens"]),
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


def stream_rows() -> list[dict[str, Any]]:
    """Every row in the committed stream, in file order. A torn line is skipped
    rather than fatal -- the rows either side of it are still the record."""
    out: list[dict[str, Any]] = []
    if not SESSIONS.exists():
        return out
    for raw in SESSIONS.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def latest_per_session(rows: list[dict[str, Any]] | None = None) -> dict[str, dict]:
    """THE AGGREGATION RULE for this stream, in one place.

    The stream is a HISTORY: a session that grew between two snapshots has one
    row per reading, on purpose, so the growth is on the record. Summing every
    row therefore double-counts -- at the time JEV-59 was written, 29 rows held
    15 sessions and a naive sum read ~$724 against a true $125.58. Readers take
    the LAST row per `session_id`, and this function is what they call so that
    nobody re-derives it slightly differently.
    """
    out: dict[str, dict] = {}
    for row in (stream_rows() if rows is None else rows):
        sid = row.get("session_id")
        if sid:
            out[sid] = row
    return out


def snapshot_identity(row: dict[str, Any]) -> tuple[str, str, str]:
    """What makes one reading of a session the SAME reading as another.

    JEV-59. This used to be the transcript fingerprint alone, and that is what
    made the wrong numbers permanent: a row is not a function of the transcript
    only, it is a function of (transcript, costing rule, pricing snapshot). Fix
    the costing rule and the fingerprint is unchanged, so the stream said
    "nothing to do" and kept costs computed under a rule that had been
    withdrawn -- fingerprint-idempotent, and idempotently wrong.

    Widening the key does the one-off forced re-snapshot JEV-59 asks for, and
    does it DETERMINISTICALLY rather than by a flag somebody has to remember:
    every session appends exactly once under the new rule, then the stream is
    idempotent again, and the next rule or pricing change re-snapshots itself
    instead of needing another ticket. A `--force` would have been a second
    switch with the same blast radius and no memory.
    """
    return (
        (row.get("source") or {}).get("digest") or "",
        row_costing_rule(row),
        row_pricing_version(row),
    )


def existing_digests() -> dict[str, tuple[str, str, str]]:
    """Last recorded (fingerprint, costing rule, pricing version) per session."""
    return {sid: snapshot_identity(row)
            for sid, row in latest_per_session().items()
            if (row.get("source") or {}).get("digest")}


def snapshot() -> dict[str, Any]:
    """Append a row for every session whose (transcript, costing rule, pricing
    snapshot) differs from its last recorded reading. A session unchanged on
    all three appends nothing -- that is the idempotence, and JEV-59 is the
    reason the last two are in it."""
    paths.BASELINE.mkdir(parents=True, exist_ok=True)
    snapshot_at = store.utcnow()
    interactive = {r["session_id"] for r in prompt_index() if r["session_id"]}
    known = existing_digests()

    appended, skipped, rows = [], [], []
    for path in transcripts():
        row = session_row(path, interactive, snapshot_at)
        rows.append(row)
        if known.get(row["session_id"]) == snapshot_identity(row):
            skipped.append(row["session_id"])
            continue
        store.append_jsonl(SESSIONS, row)
        appended.append(row["session_id"])

    # The durable record, read back AFTER the appends: the latest reading of
    # every session ever snapshotted, including any whose transcript has since
    # been reaped. This, not `rows`, is what the totals below are over.
    totalled = list(latest_per_session().values())

    manifest = {
        "schema": SCHEMA_VERSION,
        "ticket": "JEV-38",
        "pricing_version": cl.pricing()["version"],
        "snapshot_at": snapshot_at,
        "costing_rule": sm.COSTING_RULE,
        "costing_rule_description": sm.COSTING_RULE_DESCRIPTION,
        # `jev_home` is where the code lives (a worktree, often); `corpus_root`
        # is the project whose transcripts were read. They differ whenever this
        # runs from `.claude/worktrees/`, and recording only the first is how a
        # manifest ends up naming a directory that has nothing to do with its
        # numbers. `project_root` is kept under its old name for readers.
        "project_root": str(paths.ROOT),
        "jev_home": str(paths.ROOT),
        "corpus_root": str(baseline_project_root()),
        "transcript_dir": str(project_dir()),
        # --- JEV-59: what these totals are OVER -------------------------------
        # The manifest used to give `sessions_captured` and a set of totals with
        # nothing saying how the two related to `sessions.jsonl`. They are NOT a
        # subset: the stream is a history, with one row per reading of a growing
        # session, and the totals are over the LAST row per session_id. A reader
        # summing every row double-counts (29 rows / 15 sessions summed to ~$724
        # against a true $125.58 when this was written). Said here, in the file,
        # rather than in a commit message nobody reads next to the number.
        #
        # The totals are over the STREAM, not over what is on disk. Those are
        # the same set today and stop being the same set the moment a
        # snapshotted session is reaped -- which is no longer hypothetical:
        # `already_unrecoverable` went 0 -> 1 on this very run. Totalled over
        # on-disk transcripts, this file would silently SHRINK as Claude Code's
        # 30-day sweep ran, while the stream still held the spend. A "before"
        # baseline that decays with the source it was built to outlive is the
        # one thing JEV-38 exists to prevent.
        "totals_scope": (
            "every session ever snapshotted into sessions.jsonl, counted ONCE "
            "at its latest reading -- NOT only those still on disk, so these "
            "totals cannot shrink when a transcript is reaped"
        ),
        "aggregation_rule": (
            "take the LAST row per session_id in sessions.jsonl; never sum all "
            "rows -- the stream is append-only history and a grown session has "
            "one row per reading"
        ),
        "stream_rows_total": len(stream_rows()),
        # On disk right now, which is the number that CAN fall.
        "sessions_captured": len(rows),
        # In the durable record, which is the number the totals are over.
        "sessions_in_stream": len(totalled),
        "sessions_appended_this_run": appended,
        "sessions_unchanged_this_run": skipped,
        "total_computed_cost_usd": round(
            sum(r["computed_cost_usd"] for r in totalled), 6),
        "total_delegated_cost_usd": round(
            sum(r["delegated_cost_usd"] for r in totalled), 6),
        "total_delegated_tasks": sum(r["delegated_tasks"] for r in totalled),
        "total_human_prompts": sum(r["human_prompts"] for r in totalled),
        # JEV-59: these two are summed only over rows that CARRY them. A `-v1`
        # row has neither field, and reading a missing field as 0 would report
        # "no coverage hole" for rows whose coverage was never measured.
        "unpriced_requests": sum(
            r["unpriced_requests"] for r in totalled if "unpriced_requests" in r),
        "unpriced_zero_token_requests": sum(
            r["unpriced_zero_token_requests"] for r in totalled
            if "unpriced_zero_token_requests" in r),
        "unpriced_models": sorted(
            {m for r in totalled for m in (r.get("unpriced_models") or [])}),
        "unpriced_note": (
            "Spend on a model absent from config/pricing.json is NOT included in "
            "total_computed_cost_usd. It is counted here so the gap is visible. "
            "unpriced_requests is the COVERAGE HOLE -- requests that carried "
            "tokens and could not be priced -- and is what unpriced_models "
            "names. unpriced_zero_token_requests is the harmless remainder "
            "(`<synthetic>` rows, no rate and no tokens) and is NOT a gap."
        ),
        "window": {
            # Over the stream, like the totals: the window a reaped session
            # covered is still part of what this baseline measured.
            "first_activity_utc": min(
                (r["started_at"] for r in totalled if r["started_at"]), default=None),
            "last_activity_utc": max(
                (r["ended_at"] for r in totalled if r["ended_at"]), default=None),
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

def per_session_pre_cut(
    request_fn: Any = None,
) -> list[dict[str, Any]]:
    """Per-session pre-cut figures, under whichever request rule is handed in.

    Factored out of `delegation_baseline` so the corrected companion computes
    NUMERATOR AND DENOMINATOR over the same window, the same sessions and the
    same code -- only the per-request rule changes. A corrected rate whose two
    halves came from different passes is not a corrected rate.

    `request_fn` defaults to `requests` (the shared, canonical rule). The only
    other legitimate argument is `legacy_v1_requests`, and only for the
    side-by-side inside the companion.
    """
    fn = request_fn or requests
    cut = _cut()
    per_session = []
    for path in transcripts():
        reqs = [r for r in fn(path) if r["ts"] and r["ts"] < cut]
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
    return per_session


def totals_of(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold per-session rows into the registered rates."""
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
        "cost_per_delegated_task_usd": round(deleg / tasks, 6) if tasks else None,
    }


def delegation_baseline(force: bool = False) -> dict[str, Any]:
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
    # FROZEN means frozen, and as of the costing-rule fix it means frozen with
    # no escape hatch at all. The cost side is computed through
    # config/pricing.json, so the day JEV-28 reconciles Fable's rates a re-run
    # would silently move a number the pre-registration treats as fixed.
    #
    # `force` used to overwrite this file. That made the ONLY "before" the
    # project has one flag away from being destroyed -- and the costing defect
    # is exactly the kind of discovery that tempts somebody to use it. The
    # frozen artifact is now immutable; corrections go to the companion, which
    # `delegation_baseline_corrected()` writes and which states both numbers
    # and the reason they differ.
    if DELEGATION.exists():
        if force:
            raise RuntimeError(
                f"{DELEGATION.name} is frozen (JEV-24a) and will not be rewritten. "
                "Things depend on its being frozen. Write the corrected companion "
                f"instead: baseline.py --corrected  ->  {CORRECTED.name}"
            )
        return json.loads(DELEGATION.read_text())

    per_session = per_session_pre_cut()
    totals = totals_of
    interactive_rows = [r for r in per_session if r["kind"] == "interactive"]
    stamps = [r["first_request_utc"] for r in per_session if r["first_request_utc"]]
    ends = [r["last_request_utc"] for r in per_session if r["last_request_utc"]]

    record = {
        "schema": "delegation-pre-rule-v1",
        "ticket": "JEV-24a",
        "frozen_at": store.utcnow(),
        # Every cost below is computed through this pricing snapshot. A frozen
        # number whose inputs can move is not frozen.
        "pricing_version": cl.pricing()["version"],
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
            "inside <session>, the only sustained work session the repo has, which "
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


# ---------------------------------------------------------------------------
# The corrected companion
# ---------------------------------------------------------------------------

CORRECTION_REASON = (
    "delegation-pre-rule-v1.json was computed by a request walk private to "
    "baseline.py that deduped on `requestId` alone, kept the FIRST copy of a "
    "duplicated request and never read `usage.iterations[]`. Claude Code writes "
    "the same request up to 9 times as a turn streams; the early copies are "
    "placeholders carrying `input_tokens: 2` and the COMPLETED breakdown "
    "arrives only in the last. Keeping the first therefore keeps the "
    "placeholder and discards the turn. All 48 keys that grow across their "
    "copies in this corpus are inside subagent transcripts, so the error lands "
    "almost entirely on the DELEGATED side -- which is the numerator of the "
    "one rate this record exists to publish. The same walk also priced cache "
    "writes at a single flat multiplier instead of splitting 1-hour TTL (2x) "
    "from 5-minute (1.25x); the main session is 100% 1-hour TTL, so that half "
    "of the fix moves the denominator. Both halves are now delegated to "
    "session_metrics.billable_requests, the module where each of these rules "
    "was bought with a real bug and written down."
)

LOWER_BOUND_NOTE = (
    "EVERY cost here is a LOWER BOUND, corrected or not. FINDINGS.md Part 1 "
    "establishes that transcript-derived cost runs about 27.6% under Claude "
    "Code's own first-party total for the same window, and this correction "
    "does not close that gap -- it removes a second, independent undercount "
    "sitting on top of it. Requests on a model absent from config/pricing.json "
    "still contribute zero to both sides and are counted separately."
)


def delegation_baseline_corrected(write: bool = True) -> dict[str, Any]:
    """Recompute the JEV-24a baseline under the corrected costing rule, as a
    COMPANION to the frozen record rather than a replacement for it.

    The frozen `delegation-pre-rule-v1.json` is left exactly as it is. This
    file records three passes over the same cut, the same sessions and the same
    corpus, so the movement can be attributed instead of merely observed:

      `as_frozen`            the frozen record, quoted verbatim from disk
      `frozen_rule_today`    the frozen (defective) rule re-run against today's
                             corpus and today's config/pricing.json. Differs
                             from `as_frozen` ONLY by pricing drift and corpus
                             growth, never by the rule.
      `corrected`            the shared rule, same window. Differs from
                             `frozen_rule_today` ONLY by the rule.

    Numerator and denominator are both recomputed in every pass, from the same
    function, because the W0 finding is right that the denominator moves too:
    the main session is entirely 1-hour-TTL cache writes, which the flat
    multiplier under-priced.
    """
    frozen = json.loads(DELEGATION.read_text()) if DELEGATION.exists() else None

    corrected_rows = per_session_pre_cut(requests)
    legacy_rows = per_session_pre_cut(legacy_v1_requests)

    def scopes(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "all_sessions": totals_of(rows),
            "interactive_sessions_only": totals_of(
                [r for r in rows if r["kind"] == "interactive"]),
        }

    def movement(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in ("main_session_cost_usd", "delegated_cost_usd", "total_cost_usd",
                    "delegation_rate_by_spend", "cost_per_delegated_task_usd"):
            b, a = before.get(key), after.get(key)
            if not isinstance(b, (int, float)) or not isinstance(a, (int, float)):
                continue
            out[key] = {
                "before": b,
                "after": a,
                "delta": round(a - b, 6),
                "pct_change": round((a - b) / b * 100, 2) if b else None,
                "before_understates_after_by_pct": round((a - b) / a * 100, 2) if a else None,
            }
        return out

    stamps = [r["first_request_utc"] for r in corrected_rows if r["first_request_utc"]]
    ends = [r["last_request_utc"] for r in corrected_rows if r["last_request_utc"]]

    record = {
        "schema": "delegation-pre-rule-v1-corrected",
        "ticket": "JEV-24a",
        "supersedes_for_analysis": DELEGATION.name,
        "supersedes_note": (
            f"{DELEGATION.name} is NOT deleted, NOT edited and NOT re-frozen. It "
            "remains the pre-registered artifact and the record of what was "
            "published. This file is what analysis should read; the frozen one is "
            "what the project said before it found the defect. Both are kept so "
            "the correction itself stays auditable."
        ),
        "computed_at": store.utcnow(),
        "correction_reason": CORRECTION_REASON,
        "lower_bound": LOWER_BOUND_NOTE,
        "costing_rule": {
            "name": "session_metrics.billable_requests",
            "module": "src/session_metrics.py",
            "dedupe_key": "(requestId, message.id)",
            "duplicate_copy_rule": "per-field maximum across every copy -- the "
                                   "COMPLETED copy wins over the streaming "
                                   "placeholders",
            "iterations_rule": "token fields summed from usage.iterations[]; scalar "
                               "cache fields taken from the top level and NOT summed; "
                               "the cache_creation TTL sub-object follows the token "
                               "rule",
            "cache_write_pricing": "5-minute TTL at 1.25x input, 1-hour TTL at 2x, "
                                   "split read per row rather than assumed",
            "request_timestamp": "the earliest copy of a request; 0 of 2197 keys in "
                                 "this corpus have copies either side of the cut, so "
                                 "the choice does not move the window",
        },
        "superseded_rule": {
            "name": "baseline.legacy_v1_requests",
            "status": "QUARANTINED -- retained only to compute frozen_rule_today",
            "dedupe_key": "requestId alone",
            "duplicate_copy_rule": "keeps the FIRST copy (the input_tokens: 2 "
                                   "placeholder)",
            "iterations_rule": "usage.iterations[] never read",
            "cache_write_pricing": "one flat multiplier, no TTL split",
        },
        # The cut is copied from the frozen record's constants, not re-derived.
        # A corrected figure computed over a different window is not comparable
        # to the thing it corrects.
        "cut": {
            "timestamp_utc": Q17B_CUT_UTC,
            "commit": Q17B_CUT_COMMIT,
            "basis": Q17B_CUT_BASIS,
            "same_cut_as_frozen": bool(
                frozen and frozen["cut"]["timestamp_utc"] == Q17B_CUT_UTC),
        },
        "corpus": {
            "project_root": str(baseline_project_root()),
            "transcript_dir": str(project_dir()),
            "sessions_scanned": len(corrected_rows),
            "sessions_in_frozen_record": len(frozen["per_session"]) if frozen else None,
            "sessions_with_pre_cut_spend": sum(
                1 for r in corrected_rows if r["requests_pre_cut"]),
            "note": (
                "The corpus has grown since the freeze, but the cut does the work: "
                "a session that started after 2026-09-20T11:11:49Z contributes zero "
                "pre-cut requests. Only the sessions that carried pre-cut spend at "
                "freeze time carry any now, so this is the same window over the same "
                "material."
            ),
        },
        "pricing_version": cl.pricing()["version"],
        "frozen_pricing_version": frozen["pricing_version"] if frozen else None,
        "as_frozen": {
            "all_sessions": frozen["all_sessions"] if frozen else None,
            "interactive_sessions_only": frozen["interactive_sessions_only"] if frozen else None,
        },
        "frozen_rule_today": scopes(legacy_rows),
        "corrected": scopes(corrected_rows),
        "movement_rule_only": {
            scope: movement(totals_of(
                [r for r in legacy_rows if scope == "all_sessions" or r["kind"] == "interactive"]),
                totals_of(
                [r for r in corrected_rows if scope == "all_sessions" or r["kind"] == "interactive"]))
            for scope in ("all_sessions", "interactive_sessions_only")
        },
        "movement_vs_frozen_record": {
            scope: movement(frozen[scope], totals_of(
                [r for r in corrected_rows if scope == "all_sessions" or r["kind"] == "interactive"]))
            for scope in ("all_sessions", "interactive_sessions_only")
        } if frozen else None,
        "transcript_window": {
            "first_request_utc": min(stamps).isoformat() if stamps else None,
            "last_pre_cut_request_utc": max(ends).isoformat() if ends else None,
            "cut_utc": Q17B_CUT_UTC,
        },
        "denominators": frozen["denominators"] if frozen else None,
        "cut_note": frozen["cut_note"] if frozen else None,
        "per_session": [
            {**r,
             "first_request_utc": r["first_request_utc"].isoformat() if r["first_request_utc"] else None,
             "last_request_utc": r["last_request_utc"].isoformat() if r["last_request_utc"] else None}
            for r in corrected_rows if r["requests_pre_cut"]
        ],
        "limitations": frozen["limitations"] if frozen else None,
        "external_validity_note": frozen["external_validity_note"] if frozen else None,
    }
    if write:
        paths.BASELINE.mkdir(parents=True, exist_ok=True)
        CORRECTED.write_text(json.dumps(record, indent=2) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist the 'before' baseline (JEV-38/24a).")
    parser.add_argument("--snapshot", action="store_true", help="append changed sessions")
    parser.add_argument("--delegation", action="store_true",
                        help="freeze the JEV-24a baseline (once; refuses to overwrite)")
    parser.add_argument("--corrected", action="store_true",
                        help="write the corrected companion beside the frozen record")
    parser.add_argument("--force", action="store_true",
                        help="(refused) the frozen JEV-24a record is immutable; "
                             "use --corrected")
    parser.add_argument("--transcript-dir", metavar="PROJECT_ROOT",
                        help="project root whose transcripts to read, for when this "
                             "runs from a git worktree whose path is not the project's "
                             "(sets $" + BASELINE_PROJECT_ENV + ")")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.transcript_dir:
        os.environ[BASELINE_PROJECT_ENV] = args.transcript_dir
    # Snapshotting is the ROUTINE action and is the no-flag default. Freezing
    # the delegation baseline is a one-shot and must be asked for by name, so
    # that a routine re-snapshot can never rewrite a pre-registered number.
    if not (args.snapshot or args.delegation or args.corrected):
        args.snapshot = True

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
        record = delegation_baseline(force=args.force)
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
            print(f"  pricing           {record['pricing_version']}")
            print(f"  frozen_at         {record['frozen_at']}  (immutable)")
            print(f"  file              {DELEGATION}")

    if args.corrected:
        record = delegation_baseline_corrected()
        if args.json:
            print(json.dumps(record, indent=2))
        else:
            print()
            print(f"JEV-24a delegation baseline, CORRECTED (cut {Q17B_CUT_UTC})")
            print(f"  corpus            {record['corpus']['transcript_dir']}")
            for scope in ("all_sessions", "interactive_sessions_only"):
                frz = (record["as_frozen"] or {}).get(scope) or {}
                old = record["frozen_rule_today"][scope]
                new = record["corrected"][scope]
                print(f"  {scope}")
                print(f"    as frozen       delegated ${frz.get('delegated_cost_usd', 0):.4f} "
                      f"of ${frz.get('total_cost_usd', 0):.4f}  "
                      f"rate {frz.get('delegation_rate_by_spend')}")
                print(f"    frozen rule now delegated ${old['delegated_cost_usd']:.4f} "
                      f"of ${old['total_cost_usd']:.4f}  "
                      f"rate {old['delegation_rate_by_spend']}")
                print(f"    CORRECTED       delegated ${new['delegated_cost_usd']:.4f} "
                      f"of ${new['total_cost_usd']:.4f}  "
                      f"rate {new['delegation_rate_by_spend']}")
                print(f"    per task        ${new['cost_per_delegated_task_usd']} "
                      f"over {new['delegated_tasks']} delegated tasks")
            print(f"  pricing           {record['pricing_version']} "
                  f"(frozen under {record['frozen_pricing_version']})")
            print("  all figures are LOWER BOUNDS -- see FINDINGS.md Part 1")
            print(f"  file              {CORRECTED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
