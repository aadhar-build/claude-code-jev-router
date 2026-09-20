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

Three counting traps, all of them live:

**`input_tokens` is a trap.** A real line reads `"input_tokens": 2` beside
`"cache_creation_input_tokens": 17315, "cache_read_input_tokens": 30419`.
Summing `input_tokens` produces a cost figure wrong by four orders of magnitude.

**Lines duplicate roughly threefold.** Deduplication by `requestId` is
mandatory, not a nicety.

**`usage.iterations[]` restates the same numbers.** A second, independent
double-counting hazard that looks like extra data.
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
    thinking_tokens: int = 0
    web_search_requests: int = 0

    computed_cost_usd: float = 0.0
    reported_cost_usd: float | None = None
    cost_delta_pct: float | None = None
    unpriced_models: list[str] = field(default_factory=list)

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


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def analyse(path: Path) -> SessionMetrics:
    m = SessionMetrics(session_id=path.stem, transcript=str(path), project=path.parent.name)

    seen_requests: set[str] = set()
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

        # Deduplicate by requestId. Without this every token count is roughly
        # tripled -- and `usage.iterations[]` is deliberately never read.
        request_id = line.get("requestId")
        if not request_id or request_id in seen_requests:
            continue
        seen_requests.add(request_id)

        model = message.get("model") or "unknown"
        models[model] += 1
        usage = message.get("usage") or {}
        bucket = per_model[model]
        bucket["input_tokens"] += usage.get("input_tokens", 0)
        bucket["output_tokens"] += usage.get("output_tokens", 0)
        bucket["cache_creation_input_tokens"] += usage.get("cache_creation_input_tokens", 0)
        bucket["cache_read_input_tokens"] += usage.get("cache_read_input_tokens", 0)
        bucket["thinking_tokens"] += (usage.get("output_tokens_details") or {}).get("thinking_tokens", 0)

    m.unique_requests = len(seen_requests)
    m.tool_calls = dict(tool_calls.most_common())
    m.models = dict(models)
    if m.unique_requests:
        m.duplication_factor = round(m.assistant_lines / m.unique_requests, 3)

    for model, bucket in per_model.items():
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                    "cache_read_input_tokens", "thinking_tokens"):
            setattr(m, key, getattr(m, key) + bucket[key])
        cost = cl.cost_usd(model, dict(bucket))
        if cost is None:
            m.unpriced_models.append(model)
        else:
            m.computed_cost_usd += cost

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

    seen: set[str] = set()
    per_model: dict[str, Counter[str]] = defaultdict(Counter)
    for line in _lines(path):
        message = line.get("message") or {}
        if message.get("role") != "assistant":
            continue
        rid = line.get("requestId")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        usage = message.get("usage") or {}
        b = per_model[message.get("model") or "unknown"]
        b["inputTokens"] += usage.get("input_tokens", 0)
        b["outputTokens"] += usage.get("output_tokens", 0)
        b["cacheCreationInputTokens"] += usage.get("cache_creation_input_tokens", 0)
        b["cacheReadInputTokens"] += usage.get("cache_read_input_tokens", 0)

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
        f"    input              {m.input_tokens:>12,}",
        f"    cache write        {m.cache_creation_input_tokens:>12,}",
        f"    cache read         {m.cache_read_input_tokens:>12,}",
        f"    output             {m.output_tokens:>12,}",
        f"    of which thinking  {m.thinking_tokens:>12,}",
        "",
        f"  computed cost        ${m.computed_cost_usd:.4f}",
    ]
    if m.reported_cost_usd is not None:
        lines.append(f"  Claude Code's total  ${m.reported_cost_usd:.4f}")
        lines.append(f"  delta                {m.cost_delta_pct:+.2f}%   <- published, not tuned away")
    else:
        lines.append("  Claude Code's total  (absent: cost-state is written only at session end)")
    if m.unpriced_models:
        lines.append(f"  UNPRICED MODELS      {', '.join(m.unpriced_models)}")
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
        m = analyse(path)
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
