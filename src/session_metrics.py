#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The "before" baseline: per-session cost, tokens and wall-clock, harvested
from Claude Code's own transcripts.

Shadow mode changes nothing about a session, so Phase 1 has no productivity
delta to report. This module exists so that a later enforce phase has something
honest to be differenced against. It starts collecting on day 0 for that reason.

Transcripts are read IN PLACE and never modified; `~/.claude/projects` is the
one path this experiment touches outside its own folder, and it is read-only.
Nothing from another project is copied here -- the fixture this module's test
runs against holds derived numbers only.

Four counting traps, all of them live, and the third one was being handled
backwards until JEV-49:

**`input_tokens` is a trap.** A real line reads `"input_tokens": 2` beside
`"cache_creation_input_tokens": 17315, "cache_read_input_tokens": 30419`.
Summing `input_tokens` produces a cost figure wrong by four orders of magnitude.
This is *normal cache-read behaviour*, not a defect: 81% of rows look like it.

**Lines duplicate.** Deduplication is mandatory, not a nicety, and the key is
the pair `(requestId, message.id)` -- see `dedupe_key`.

**`usage.iterations[]` is asymmetric.** It does NOT simply restate the top
level. Token fields must be summed from it; cache scalars must not. See
`normalise_usage`, which is where the whole rule is written down.

**Cache writes do not all bill at the same rate.** A 1-hour-TTL write bills at
2x the input rate, a 5-minute one at 1.25x, and both TTLs occur in this corpus.
The split is per row, in `usage.cache_creation`, and must be read rather than
assumed from the auth path -- see `call_cost` and PREREGISTRATION "Auth path".
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_loader as cl  # noqa: E402
import paths  # noqa: E402

TTL_FIELDS = ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")

SCALAR_TOKEN_FIELDS = ("input_tokens", "output_tokens")
SCALAR_CACHE_FIELDS = ("cache_creation_input_tokens", "cache_read_input_tokens")


class UnpricedModelError(RuntimeError):
    """A billable request was made by a model absent from `config/pricing.json`.

    Deliberately fatal under `strict=True`. `config_loader.cost_usd()` returns
    None rather than guessing -- that guard is what stops `claude-spend#31`'s
    437% over-report, where a substring match on "opus" billed Opus 5 at Opus
    4.0 rates. But a guard that degrades into a coverage statistic at the foot
    of a report is a silent under-report instead, which is the same failure
    wearing the other sign. A published total either covers every billable row
    or says on its face that it does not.
    """


DENIAL_MARKER = "The user doesn't want to proceed with this tool use"
INTERRUPT_MARKERS = (
    "[Request interrupted by user",
    "Request interrupted by user for tool use",
)


@dataclass
class SessionMetrics:
    session_id: str
    transcript: str
    project: str

    # token classes -- never summed into one number
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    # the same cache-write tokens again, split by TTL -- these two sum to
    # cache_creation_input_tokens and are NOT additional tokens
    cache_creation_5m_input_tokens: int = 0
    cache_creation_1h_input_tokens: int = 0
    thinking_tokens: int = 0
    web_search_requests: int = 0

    computed_cost_usd: float = 0.0
    reported_cost_usd: float | None = None
    cost_delta_pct: float | None = None
    unpriced_models: list[str] = field(default_factory=list)
    unpriced_requests: int = 0

    # JEV-49 instrumentation: how much of this session's bill was invisible
    # before the iterations[] fix, and how often the TTL split had to be repaired
    iteration_rows: int = 0
    hidden_input_tokens: int = 0
    hidden_output_tokens: int = 0
    ttl_splits_repaired: int = 0

    assistant_lines: int = 0
    unique_requests: int = 0
    duplication_factor: float = 0.0
    user_turns: int = 0

    wall_clock_s: float | None = None
    reported_total_duration_s: float | None = None
    reported_api_duration_s: float | None = None
    reported_tool_duration_s: float | None = None
    started_at: str | None = None
    ended_at: str | None = None

    tool_calls: dict[str, int] = field(default_factory=dict)
    tool_errors: int = 0
    sidechain_lines: int = 0

    # friction proxies
    permission_denials: int = 0
    user_interruptions: int = 0

    models: dict[str, int] = field(default_factory=dict)
    lines_added: int | None = None
    lines_removed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def session_files(path: Path) -> list[Path]:
    """A session is not one file.

    Claude Code writes the main transcript as `<session-id>.jsonl` and every
    subagent it spawns into a sibling `<session-id>/subagents/*.jsonl`. Those
    subagent turns are billed to the session but appear nowhere in the main
    transcript, so a cost computed from the main file alone under-reports by
    however much delegated work the session did -- which on an agent-heavy
    session is a large fraction of the bill.

    This was found by reconciling against Claude Code's own cost-state totals
    and discovering a 32% shortfall. It is exactly what that check is for.
    """
    files = [path]
    subagents = path.with_suffix("") / "subagents"
    if subagents.is_dir():
        files.extend(sorted(subagents.glob("*.jsonl")))
    return files


def _lines(path: Path, include_subagents: bool = True) -> Iterator[dict[str, Any]]:
    targets = session_files(path) if include_subagents else [path]
    for target in targets:
        with target.open("r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    line = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if target is not path:
                    line["_subagent_file"] = target.name
                yield line


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    parts.append(_text_of(block.get("content")))
        return "\n".join(parts)
    return ""


def normalise_usage(usage: dict[str, Any]) -> dict[str, Any]:
    """One usage blob, with `iterations[]` folded in under the correct rule.

    A multi-round-trip turn writes a per-iteration breakdown into
    `usage.iterations[]`, and the top-level fields relate to it THREE different
    ways. Measured over 3,790 assistant rows of this project's own transcripts
    (2,510 of them carrying iterations):

    * scalar token fields -- `input_tokens`, `output_tokens` -- **MUST** be
      summed from `iterations[]`. The top level is a floor, not a total: 71
      rows under-report input and 74 under-report output, the worst by 237,380
      tokens in a single record (top level said 4).
    * scalar cache fields -- `cache_creation_input_tokens`,
      `cache_read_input_tokens` -- **MUST NOT** be summed. The top-level value
      already equals the iteration sum, exactly, on all 2,510 rows
      (12,053,678 and 403,398,115 tokens respectively, both matching to the
      token). Summing them double-counts.
    * the `cache_creation` TTL **sub-object** behaves like the token fields,
      not like the scalar it decomposes: on those same 71 rows the top-level
      sub-object is SHORT, and `sum(iterations[].cache_creation)` restores the
      scalar exactly. No third-party report covers this half; it was found
      here, and it matters because the TTL split decides the multiplier.

    The invariant `5m + 1h == cache_creation_input_tokens` holds on every row
    once the sub-object is summed. Where a row breaks it anyway, the remainder
    is attributed to the 5-minute bucket -- the *cheaper* one, so the repair
    cannot inflate a cost figure -- and flagged as `ttl_split_repaired` so the
    count is reportable rather than invisible.
    """
    iterations = usage.get("iterations") or []
    out: dict[str, Any] = {}

    for key in SCALAR_TOKEN_FIELDS:
        summed = sum(i.get(key, 0) or 0 for i in iterations)
        # max(), not sum-if-present: the top level is a floor. If a future
        # shape ever puts the larger number there, we must not lose it.
        out[key] = max(summed, usage.get(key, 0) or 0)

    for key in SCALAR_CACHE_FIELDS:
        out[key] = usage.get(key, 0) or 0

    details = usage.get("output_tokens_details") or {}
    out["thinking_tokens"] = max(
        sum((i.get("output_tokens_details") or {}).get("thinking_tokens", 0) or 0
            for i in iterations),
        details.get("thinking_tokens", 0) or 0,
    )

    top_split = usage.get("cache_creation") or {}
    split = {k: sum((i.get("cache_creation") or {}).get(k, 0) or 0 for i in iterations)
             for k in TTL_FIELDS}
    if sum(split.values()) < sum(top_split.get(k, 0) or 0 for k in TTL_FIELDS):
        split = {k: top_split.get(k, 0) or 0 for k in TTL_FIELDS}

    shortfall = out["cache_creation_input_tokens"] - sum(split.values())
    out["ttl_split_repaired"] = shortfall != 0
    if shortfall > 0:
        split["ephemeral_5m_input_tokens"] += shortfall
    elif shortfall < 0:
        # More split than scalar: trust the scalar, which is what cost-state
        # itself reconciles against, and shave the expensive bucket first.
        excess = -shortfall
        take = min(excess, split["ephemeral_1h_input_tokens"])
        split["ephemeral_1h_input_tokens"] -= take
        split["ephemeral_5m_input_tokens"] -= (excess - take)

    out.update(split)
    return out


def merge_copies(kept: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    """Fold another copy of the SAME request into the one we are keeping.

    Claude Code writes one `(requestId, message.id)` several times as the turn
    streams -- up to 9 times in this corpus. The early copies are placeholders
    carrying `input_tokens: 2` and no `iterations[]`; only the last copy carries
    the completed breakdown. A dedupe that keeps the FIRST copy keeps the
    placeholder and discards the turn: 48 keys in this project's corpus grow
    across their copies, all 48 monotonically, all 48 inside subagent
    transcripts, for 4,889,713 input tokens in a single session.

    Per-field maximum rather than "last wins" so that a non-monotonic sequence
    cannot lose tokens either; on all 48 observed keys the two rules agree.
    In all 36 sessions carrying a `cost-state` line, every copy of every key is
    identical, so this rule cannot move a number that first-party accounting
    can check -- and it does not.
    """
    if kept is None:
        return dict(incoming)
    for key, value in incoming.items():
        if isinstance(value, bool):
            kept[key] = kept.get(key, False) or value
        elif isinstance(value, (int, float)):
            kept[key] = max(kept.get(key, 0), value)
    return kept


def dedupe_key(line: dict[str, Any]) -> tuple[str, str | None] | None:
    """The billing identity of one transcript line, or None if it is not one.

    `claude-spend#31` dedupes on `requestId` + `message.id`, and this project
    keeps that pair even though, in this corpus, it is exactly equivalent to
    `requestId` alone: 728 unique request ids over 728 unique pairs, with no
    request id carrying two message ids. The 659-vs-660 discrepancy noted in
    the prep is fully explained by `<synthetic>` rows, which carry a
    `message.id`, no `requestId`, and zero tokens -- an artefact of counting
    distinct ids in two different populations, not a retry.

    A line with no `requestId` was never a billable API call.
    """
    request_id = line.get("requestId")
    if not request_id:
        return None
    return (request_id, (line.get("message") or {}).get("id"))


def call_cost(model: str, usage: dict[str, Any]) -> float | None:
    """Cost of one normalised usage blob, with the cache-write TTL priced.

    `config_loader.cost_usd()` knows one cache-write multiplier. Billing has
    two: a 5-minute write is 1.25x the input rate and a 1-hour write is 2x
    (`ccusage#899`: $479, 19% under-reported across ~40,000 records). Rather
    than fork the cost formula -- `config_loader.py` is not this ticket's file
    -- the 1-hour tokens are re-expressed as the number of 5-minute tokens that
    bill identically, and the existing, tested formula is called once. The
    arithmetic is exact; only the token count handed to the cost function is
    effective, and `SessionMetrics` keeps the true counts for reconciliation.

    Returns None for an unknown model, never a guess.
    """
    pricing = cl.pricing()
    rate = pricing["models"].get(model)
    if rate is None:
        return None
    cw = rate.get("cache_write_multiplier", pricing["cache_write_multiplier"])
    cw_1h = rate.get("cache_write_multiplier_1h", pricing.get("cache_write_multiplier_1h", cw))
    hour_tokens = usage.get("ephemeral_1h_input_tokens", 0) or 0
    effective = {k: usage.get(k, 0) or 0
                 for k in SCALAR_TOKEN_FIELDS + SCALAR_CACHE_FIELDS}
    effective["cache_creation_input_tokens"] += hour_tokens * (cw_1h / cw - 1.0)
    return cl.cost_usd(model, effective)


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def analyse(path: Path, strict: bool = False) -> SessionMetrics:
    """Harvest one session. `strict=True` refuses to return a partial total.

    Non-strict is the default because `src/baseline.py` and the report path
    want every session they can get; strict is for anything that publishes a
    single number. Either way the exclusion is on the face of `render()`.
    """
    m = SessionMetrics(session_id=path.stem, transcript=str(path), project=path.parent.name)

    seen_requests: set[tuple[str, str | None]] = set()
    by_key: dict[tuple[str, str | None], dict[str, Any]] = {}
    key_model: dict[tuple[str, str | None], str] = {}
    tool_calls: Counter[str] = Counter()
    models: Counter[str] = Counter()
    per_model: dict[str, Counter[str]] = defaultdict(Counter)
    timestamps: list[datetime] = []
    cost_state: dict[str, Any] | None = None

    for line in _lines(path):
        ltype = line.get("type")

        if ltype == "cost-state":
            cost_state = line  # duplicated like everything else; last one wins
            continue

        ts = _parse_ts(line.get("timestamp"))
        if ts:
            timestamps.append(ts)
        if line.get("isSidechain") or line.get("_subagent_file"):
            m.sidechain_lines += 1

        message = line.get("message") or {}
        role = message.get("role")

        if role == "user":
            m.user_turns += 1
            body = _text_of(message.get("content"))
            if DENIAL_MARKER in body:
                m.permission_denials += 1
            if any(marker in body for marker in INTERRUPT_MARKERS):
                m.user_interruptions += 1
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    m.tool_errors += 1
            continue

        if role != "assistant":
            continue

        m.assistant_lines += 1
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_calls[block.get("name", "unknown")] += 1

        # Deduplicate on the (requestId, message.id) PAIR -- see dedupe_key.
        # Without any dedupe every token count is roughly doubled here (1.97x
        # measured on this corpus, not the 3.1x an older sample reported).
        key = dedupe_key(line)
        if key is None:
            continue
        raw_usage = message.get("usage") or {}
        usage = normalise_usage(raw_usage)
        if raw_usage.get("iterations"):
            m.iteration_rows += 1
        if key not in seen_requests:
            seen_requests.add(key)
            m.hidden_input_tokens += usage["input_tokens"] - (raw_usage.get("input_tokens", 0) or 0)
            m.hidden_output_tokens += usage["output_tokens"] - (raw_usage.get("output_tokens", 0) or 0)
            m.ttl_splits_repaired += 1 if usage["ttl_split_repaired"] else 0
        # Every copy is folded in, not just the first -- see merge_copies.
        by_key[key] = merge_copies(by_key.get(key), usage)
        key_model[key] = message.get("model") or "unknown"

    for key, usage in by_key.items():
        model = key_model[key]
        models[model] += 1
        bucket = per_model[model]
        for key_name in (SCALAR_TOKEN_FIELDS + SCALAR_CACHE_FIELDS + TTL_FIELDS
                         + ("thinking_tokens",)):
            bucket[key_name] += usage[key_name]

    m.unique_requests = len(seen_requests)
    m.tool_calls = dict(tool_calls.most_common())
    m.models = dict(models)
    if m.unique_requests:
        m.duplication_factor = round(m.assistant_lines / m.unique_requests, 3)

    for model, bucket in per_model.items():
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                    "cache_read_input_tokens", "thinking_tokens"):
            setattr(m, key, getattr(m, key) + bucket[key])
        m.cache_creation_5m_input_tokens += bucket["ephemeral_5m_input_tokens"]
        m.cache_creation_1h_input_tokens += bucket["ephemeral_1h_input_tokens"]
        cost = call_cost(model, dict(bucket))
        if cost is None:
            billable = sum(bucket[k] for k in SCALAR_TOKEN_FIELDS + SCALAR_CACHE_FIELDS)
            if billable:
                # A model with no rate and no tokens (`<synthetic>`) is not a
                # coverage hole; one with tokens is.
                m.unpriced_models.append(model)
                m.unpriced_requests += models[model]
        else:
            m.computed_cost_usd += cost

    if strict and m.unpriced_models:
        raise UnpricedModelError(
            f"{path.name}: {m.unpriced_requests} billable request(s) on "
            f"{', '.join(sorted(m.unpriced_models))}, absent from config/pricing.json. "
            "Price the model or publish the total as a lower bound; do not guess a rate."
        )

    if timestamps:
        m.started_at = min(timestamps).isoformat()
        m.ended_at = max(timestamps).isoformat()
        m.wall_clock_s = round((max(timestamps) - min(timestamps)).total_seconds(), 1)

    if cost_state:
        m.reported_cost_usd = cost_state.get("totalCostUSD")
        for field_name, key in (
            ("reported_total_duration_s", "totalDuration"),
            ("reported_api_duration_s", "totalAPIDuration"),
            ("reported_tool_duration_s", "totalToolDuration"),
        ):
            value = cost_state.get(key)
            if isinstance(value, (int, float)):
                setattr(m, field_name, round(value / 1000.0, 1))
        m.lines_added = cost_state.get("totalLinesAdded")
        m.lines_removed = cost_state.get("totalLinesRemoved")
        m.web_search_requests = sum(
            u.get("webSearchRequests", 0) for u in (cost_state.get("modelUsage") or {}).values()
        )
        m.computed_cost_usd += m.web_search_requests * cl.pricing()["web_search_usd_per_request"]
        if m.reported_cost_usd:
            m.cost_delta_pct = round(
                (m.computed_cost_usd - m.reported_cost_usd) / m.reported_cost_usd * 100, 2
            )

    m.computed_cost_usd = round(m.computed_cost_usd, 6)
    return m


def reconcile_per_model(path: Path) -> list[dict[str, Any]]:
    """Compare our deduplicated token sums against Claude Code's own per-model
    totals. This is the sharpest available test of the dedupe logic: if the
    duplication factor were being mishandled, these would differ by ~3x.
    """
    cost_state = None
    for line in _lines(path):
        if line.get("type") == "cost-state":
            cost_state = line
    if not cost_state:
        return []

    seen: dict[tuple[str, str | None], dict[str, Any]] = {}
    key_model: dict[tuple[str, str | None], str] = {}
    per_model: dict[str, Counter[str]] = defaultdict(Counter)
    for line in _lines(path):
        message = line.get("message") or {}
        if message.get("role") != "assistant":
            continue
        key = dedupe_key(line)
        if key is None:
            continue
        seen[key] = merge_copies(seen.get(key), normalise_usage(message.get("usage") or {}))
        key_model[key] = message.get("model") or "unknown"

    for key, usage in seen.items():
        b = per_model[key_model[key]]
        b["inputTokens"] += usage["input_tokens"]
        b["outputTokens"] += usage["output_tokens"]
        b["cacheCreationInputTokens"] += usage["cache_creation_input_tokens"]
        b["cacheReadInputTokens"] += usage["cache_read_input_tokens"]

    # The transcript records `claude-opus-5` while cost-state keys the very same
    # usage as `claude-opus-5[1m]`. Matching on the exact string alone reports a
    # spurious -100% on every field, so fall back to the base name.
    def ours_for(model: str) -> Counter:
        if model in per_model:
            return per_model[model]
        base = model.split("[", 1)[0]
        merged: Counter = Counter()
        for name, counts in per_model.items():
            if name.split("[", 1)[0] == base:
                merged.update(counts)
        return merged

    rows = []
    for model, reported in (cost_state.get("modelUsage") or {}).items():
        ours = ours_for(model)
        for key in ("inputTokens", "outputTokens", "cacheCreationInputTokens", "cacheReadInputTokens"):
            theirs = reported.get(key, 0)
            mine = ours[key]
            rows.append({
                "model": model,
                "field": key,
                "ours": mine,
                "claude_code": theirs,
                "delta_pct": round((mine - theirs) / theirs * 100, 3) if theirs else None,
            })
    return rows


def cost_decomposition(path: Path, since: datetime | None = None,
                       until: datetime | None = None) -> dict[str, Any]:
    """One session's cost under each of JEV-49's three fixes, in isolation.

    A single merged "before and after" number hides which bug mattered, so the
    cost is computed four times over the same deduplicated rows:

      `pre`          the rules as they stood: top-level fields only, one flat
                     cache-write multiplier, `claude-opus-4-7` unpriced and
                     therefore silently dropped
      `plus_iter`    + token fields summed from `iterations[]`
      `plus_ttl`     + 1-hour cache writes billed at 2x
      `post`         + `claude-opus-4-7` priced from first-party cost-state

    Web search is carried as its own line and added to neither: it is billed
    per request from cost-state, it is in the session baselines, and it is
    absent from per-call run rows (`config_loader.cost_usd` does not know about
    it). Reconciling the two without saying so would be wrong by exactly that
    amount.

    `since`/`until` bound the window by row timestamp, so a reconciliation can
    name a window rather than a set of files.
    """
    pricing = cl.pricing()
    first_raw: dict[tuple, dict[str, Any]] = {}
    first_norm: dict[tuple, dict[str, Any]] = {}
    merged: dict[tuple, dict[str, Any]] = {}
    key_model: dict[tuple, str] = {}
    rows: dict[str, int] = Counter()
    seen: set[tuple[str, str | None]] = set()
    cost_state = None
    first = last = None

    for line in _lines(path):
        if line.get("type") == "cost-state":
            cost_state = line
            continue
        message = line.get("message") or {}
        if message.get("role") != "assistant":
            continue
        ts = _parse_ts(line.get("timestamp"))
        if since and (ts is None or ts < since):
            continue
        if until and (ts is None or ts > until):
            continue
        key = dedupe_key(line)
        if key is None:
            continue
        if ts:
            first = ts if first is None or ts < first else first
            last = ts if last is None or ts > last else last
        model = message.get("model") or "unknown"
        key_model[key] = model
        u = message.get("usage") or {}
        n = normalise_usage(u)
        if key not in seen:
            seen.add(key)
            rows[model] += 1
            first_raw[key] = {k: (u.get(k, 0) or 0)
                              for k in SCALAR_TOKEN_FIELDS + SCALAR_CACHE_FIELDS}
            first_norm[key] = dict(n)
        merged[key] = merge_copies(merged.get(key), n)

    def fold(per_key: dict[tuple, dict[str, Any]]) -> dict[str, Counter]:
        buckets: dict[str, Counter] = defaultdict(Counter)
        for key, usage in per_key.items():
            for name in SCALAR_TOKEN_FIELDS + SCALAR_CACHE_FIELDS + TTL_FIELDS:
                buckets[key_model[key]][name] += usage.get(name, 0)
        return buckets

    raw, norm, full = fold(first_raw), fold(first_norm), fold(merged)

    def total(buckets: dict[str, Counter], ttl: bool, exclude: tuple[str, ...]) -> float:
        out = 0.0
        for model, b in buckets.items():
            if model in exclude or model not in pricing["models"]:
                continue
            usage = dict(b)
            if not ttl:
                usage["ephemeral_1h_input_tokens"] = 0
            out += call_cost(model, usage) or 0.0
        return out

    legacy = ("claude-opus-4-7",)
    web_requests = sum(
        u.get("webSearchRequests", 0)
        for u in ((cost_state or {}).get("modelUsage") or {}).values()
    )
    return {
        "session_id": path.stem,
        "rows_by_model": dict(rows),
        "billable_requests": len(seen),
        "pre": round(total(raw, ttl=False, exclude=legacy), 6),
        "plus_iter": round(total(norm, ttl=False, exclude=legacy), 6),
        "plus_copy": round(total(full, ttl=False, exclude=legacy), 6),
        "plus_ttl": round(total(full, ttl=True, exclude=legacy), 6),
        "post": round(total(full, ttl=True, exclude=()), 6),
        "web_search_requests": web_requests,
        "web_search_usd": round(web_requests * pricing["web_search_usd_per_request"], 6),
        "reported_cost_usd": (cost_state or {}).get("totalCostUSD"),
        "cache_1h_tokens": sum(b["ephemeral_1h_input_tokens"] for b in full.values()),
        "placeholder_input_tokens_recovered": sum(
            full[m]["input_tokens"] - norm[m]["input_tokens"] for m in full),
        "first_row_utc": first.isoformat() if first else None,
        "last_row_utc": last.isoformat() if last else None,
    }


def reconciliation_window(targets: list[Path], since: datetime | None = None,
                          until: datetime | None = None) -> dict[str, Any]:
    """Everything a Console reconciliation needs for a bounded window.

    The transcript-derived side of the reconciliation, and nothing else. The
    other side -- the Console usage page or an invoice -- cannot be read from
    this process and must be supplied by the operator; PREREGISTRATION
    "Reconciliation" states exactly what to pull and why the two sides are not
    a like-for-like comparison for every auth path.
    """
    parts = [cost_decomposition(p, since, until) for p in targets]
    parts = [p for p in parts if p["billable_requests"]]
    stamps = [p[k] for p in parts for k in ("first_row_utc", "last_row_utc") if p[k]]
    return {
        "sessions": len(parts),
        "billable_requests": sum(p["billable_requests"] for p in parts),
        "window_first_row_utc": min(stamps) if stamps else None,
        "window_last_row_utc": max(stamps) if stamps else None,
        "pre_usd": round(sum(p["pre"] for p in parts), 6),
        "post_usd": round(sum(p["post"] for p in parts), 6),
        "web_search_usd": round(sum(p["web_search_usd"] for p in parts), 6),
        "claude_code_reported_usd": round(
            sum(p["reported_cost_usd"] or 0.0 for p in parts), 6),
        "sessions_reporting_a_cost_state": sum(
            1 for p in parts if p["reported_cost_usd"] is not None),
        "per_session": parts,
    }


def find_transcripts(project_filter: str | None = None) -> list[Path]:
    if not paths.CLAUDE_PROJECTS.exists():
        return []
    out = []
    for directory in sorted(paths.CLAUDE_PROJECTS.iterdir()):
        if not directory.is_dir():
            continue
        if project_filter and project_filter not in directory.name:
            continue
        out.extend(sorted(directory.glob("*.jsonl")))
    return out


def this_project_transcripts() -> list[Path]:
    """Sessions for THIS folder -- the baseline the experiment is about."""
    slug = str(paths.ROOT).replace("/", "-")
    return find_transcripts(project_filter=slug)


def render(m: SessionMetrics) -> str:
    lines = [
        f"session       {m.session_id}",
        f"project       {m.project}",
        f"models        {', '.join(f'{k} x{v}' for k, v in m.models.items()) or 'none'}",
        "",
        f"  assistant lines      {m.assistant_lines}",
        f"  unique requests      {m.unique_requests}   (duplication factor {m.duplication_factor}x)",
        f"  user turns           {m.user_turns}",
        "",
        "  tokens by class (never summed into one number)",
        f"    input              {m.input_tokens:>12,}"
        + (f"   ({m.hidden_input_tokens:,} recovered from iterations[])"
           if m.hidden_input_tokens else ""),
        f"    cache write        {m.cache_creation_input_tokens:>12,}"
        f"   (5m {m.cache_creation_5m_input_tokens:,} @1.25x / "
        f"1h {m.cache_creation_1h_input_tokens:,} @2x)",
        f"    cache read         {m.cache_read_input_tokens:>12,}",
        f"    output             {m.output_tokens:>12,}",
        f"    of which thinking  {m.thinking_tokens:>12,}",
        "",
        f"  computed cost        ${m.computed_cost_usd:.4f}"
        + (f"   <- LOWER BOUND: {m.unpriced_requests} request(s) on "
           f"{', '.join(m.unpriced_models)} are NOT in this number"
           if m.unpriced_models else ""),
    ]
    if m.reported_cost_usd is not None:
        lines.append(f"  Claude Code's total  ${m.reported_cost_usd:.4f}")
        lines.append(f"  delta                {m.cost_delta_pct:+.2f}%   <- published, not tuned away")
    else:
        lines.append("  Claude Code's total  (absent: cost-state is written only at session end)")
    if m.unpriced_models:
        lines.append(f"  UNPRICED MODELS      {', '.join(m.unpriced_models)}"
                     f"   ({m.unpriced_requests} requests excluded)")
    lines += [
        "",
        f"  wall clock           {m.wall_clock_s}s   (reported: {m.reported_total_duration_s}s)",
        f"  api / tool time      {m.reported_api_duration_s}s / {m.reported_tool_duration_s}s",
        f"  subagent lines       {m.sidechain_lines}   (from <session>/subagents/*.jsonl)",
        "",
        "  friction proxies",
        f"    permission denials {m.permission_denials}",
        f"    interruptions      {m.user_interruptions}",
        f"    tool errors        {m.tool_errors}",
        "",
        f"  tool calls           {', '.join(f'{k}={v}' for k, v in list(m.tool_calls.items())[:10]) or 'none'}",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-session baseline metrics.")
    parser.add_argument("transcript", nargs="?", help="path to a .jsonl transcript")
    parser.add_argument("--project", help="substring of the project directory name")
    parser.add_argument("--this-project", action="store_true", help="sessions for this folder")
    parser.add_argument("--reconcile", action="store_true", help="per-model token reconciliation")
    parser.add_argument("--freeze-fixture", metavar="NAME",
                        help="write derived numbers to data/fixtures/NAME.json as a regression baseline")
    parser.add_argument("--strict", action="store_true",
                        help="refuse to print a total that excludes an unpriced model")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.transcript:
        targets = [Path(args.transcript)]
    elif args.this_project:
        targets = this_project_transcripts()
    else:
        targets = find_transcripts(args.project)

    if not targets:
        print("no transcripts found")
        return 1

    all_metrics = []
    for path in targets:
        m = analyse(path, strict=args.strict)
        all_metrics.append(m)
        if args.json:
            print(json.dumps(m.to_dict(), default=str))
        else:
            print(render(m))
            print()
        if args.reconcile:
            rows = reconcile_per_model(path)
            if rows:
                print("  per-model token reconciliation against Claude Code's own totals")
                print(f"    {'model':<30} {'field':<26} {'ours':>13} {'claude code':>13} {'delta':>8}")
                for r in rows:
                    d = "exact" if r["delta_pct"] == 0 else (f"{r['delta_pct']:+.2f}%" if r["delta_pct"] is not None else "-")
                    print(f"    {r['model']:<30} {r['field']:<26} {r['ours']:>13,} {r['claude_code']:>13,} {d:>8}")
                print()

    if args.freeze_fixture:
        paths.FIXTURES.mkdir(parents=True, exist_ok=True)
        target = paths.FIXTURES / f"{args.freeze_fixture}.json"
        target.write_text(json.dumps([m.to_dict() for m in all_metrics], indent=2, default=str))
        print(f"frozen: {target}")
        print("Derived numbers only -- no transcript content is copied into this folder.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
