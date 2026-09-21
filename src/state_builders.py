"""Build the state string each arm sees, from a captured hook payload.

Decision #7 governs this module: **state is built from the hook payload only,
never by reading the live transcript.** The worker runs minutes after capture,
so any builder that read `transcript_path` at worker time would see turns that
happened *after* the decision point. On `user_prompt` routing that means the
classifier would see Claude's answer to the prompt it is supposed to route.

That leakage would help every arm equally, so agreement metrics would never
reveal it -- the numbers would simply be wrong, and unreproducible in enforce
mode where the future does not exist.

The one surface that genuinely needs conversation context is `stop`, and it gets
the transcript truncated to `transcript_bytes_at_capture` -- the byte length the
hook recorded at capture time -- never the tail as it exists now.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

STATE_BUILDER_VERSION = "state-builders-v1"

# Cap on state size. Jev's window is 64k tokens with 32k max for state; this is a
# conservative character budget that keeps every arm comparable.
MAX_STATE_CHARS = 60_000


class StateBuildError(Exception):
    pass


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _truncate(text: str, limit: int = MAX_STATE_CHARS) -> str:
    """Truncate from the FRONT, keeping the end.

    For a transcript the recent turns matter most; for a command the whole thing
    fits anyway. Truncation is marked so it is visible in the state itself rather
    than silently changing what an arm was asked about.
    """
    if len(text) <= limit:
        return text
    return "[... earlier content truncated ...]\n" + text[-limit:]


def build_pre_bash(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command")
    if not command:
        raise StateBuildError("pre_bash payload has no tool_input.command")
    parts = [f"Command:\n{command}"]
    if tool_input.get("description"):
        parts.append(f"Stated purpose:\n{tool_input['description']}")
    parts.append(f"Working directory: {payload.get('cwd', 'unknown')}")
    return _truncate("\n\n".join(parts))


def build_user_prompt(payload: dict[str, Any]) -> str:
    prompt = payload.get("prompt")
    if not prompt:
        raise StateBuildError("user_prompt payload has no prompt")
    continuation = payload.get("is_continuation")
    return _truncate(
        f"User prompt:\n{prompt}\n\nThis is a continuation of an earlier turn: {bool(continuation)}"
    )


def build_post_edit(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input") or {}
    tool_name = payload.get("tool_name", "unknown")
    response = payload.get("tool_response")
    parts = [f"Tool: {tool_name}", f"File: {tool_input.get('file_path', 'unknown')}"]
    if "old_string" in tool_input or "new_string" in tool_input:
        parts.append(f"Replaced:\n{tool_input.get('old_string', '')}")
        parts.append(f"With:\n{tool_input.get('new_string', '')}")
    elif "content" in tool_input:
        parts.append(f"New file contents:\n{tool_input['content']}")
    else:
        raise StateBuildError("post_edit payload has neither a replacement nor content")
    if isinstance(response, str) and response:
        parts.append(f"Tool result:\n{response[:2000]}")
    return _truncate("\n\n".join(parts))


def build_agent_route(payload: dict[str, Any]) -> str:
    """JEV-34. One delegated task, about to be spawned, described richly.

    WHY THIS IS NOT DESCRIPTION-ONLY (JEV-54)
    -----------------------------------------
    The ticket originally specified `prompt` + `subagent_type` and nothing else.
    SWE-Router (arXiv:2607.00053) measures a Bayes-error floor for exactly that
    input -- "a similar issue can hide either a localized typo or a multi-module
    refactor, and the prompt does not separate the two" -- and gains +15.3pp
    Route-AUC from a partial trajectory instead. Our own baseline says the same
    thing from the other side: 78 of 120 delegated tasks (65%) are
    `general-purpose`, the one agent type that carries no routing signal.

    We cannot give this surface a trajectory (see the leakage note below), but
    everything the payload already carries is free, and `agent_route` has no
    legacy corpus to fork -- so it is built rich from the first row rather than
    enriched later at the cost of an era boundary.

    EVERY FIELD, AND WHY IT CANNOT LEAK (plan decision #7, per field)
    ----------------------------------------------------------------
    * `tool_input.description` -- written by the delegating agent BEFORE the
      spawn; present in 202/202 observed `Agent` tool calls.
    * `tool_input.prompt` -- the task text, likewise written before the spawn.
      It is the closest thing to a trajectory this surface can have: the parent
      composed it out of its own accumulated context. It is NOT a trajectory,
      and it must not be described as one -- it is the parent's summary of one.
    * `tool_input.subagent_type` -- the type being spawned; 190/202. Absent in
      12/202, rendered `unspecified` rather than raising, because refusing 6% of
      traffic would silently drop exactly the unusual spawns.
    * `tool_input.run_in_background` -- whether the parent blocks on this task.
      Decision-time intent, set by the caller; 8/202.
    * envelope `agent_type` / `agent_id` -- the INVOKER's identity, i.e. who is
      delegating. Documented common hook input fields, added when the session is
      itself a subagent. `agent_id`'s presence is the only payload-visible proxy
      for spawn depth, and it is labelled as a proxy: true `spawnDepth` lives in
      transcript metadata (`src/baseline.py:266` reads it there) and reading it
      at worker time is forbidden.
    * `permission_mode`, `effort.level`, `cwd` -- documented common input
      fields, describing the session the spawn is issued from. All fixed at the
      moment the hook fires.

    None of these is read from the filesystem or the transcript at build time.
    The builder is a pure function of the payload dict, so a worker running an
    hour late produces the same bytes as the hook would have -- which is the
    property GATE 4 exists to assert and `tests/test_agent_route.py` asserts at
    unit level.

    THE ONE FIELD DELIBERATELY WITHHELD
    -----------------------------------
    `tool_input.model`, present in 39/202 observed spawns (37 `sonnet`, 2
    `opus`). It is payload-only and leaks nothing -- it is excluded on
    measurement grounds, not safety grounds. It names the answer: a classifier
    asked "how hard is this work" while shown the model the parent already
    picked can copy rather than judge, and at JEV-35 it is the very field the
    actuator overwrites. The anchors refuse to name a model for the same reason
    the state does. It stays recoverable for analysis through `tool_use_id`.
    """
    tool_input = payload.get("tool_input") or {}
    prompt = tool_input.get("prompt")
    if not prompt:
        raise StateBuildError("agent_route payload has no tool_input.prompt")

    subagent_type = tool_input.get("subagent_type") or "unspecified (harness default)"
    invoker = payload.get("agent_type")
    nested = bool(payload.get("agent_id"))
    effort = payload.get("effort")
    effort_level = effort.get("level") if isinstance(effort, dict) else effort
    background = tool_input.get("run_in_background")

    parts = [
        f"Task summary: {tool_input.get('description') or 'none given'}",
        f"Requested agent type (the subagent about to be spawned): {subagent_type}",
        (
            "Delegating agent (who is issuing this delegation): "
            + (f"{invoker} subagent" if invoker else "the main session")
        ),
        (
            "Delegation nesting: nested -- issued from inside a subagent"
            if nested
            else "Delegation nesting: top level -- issued from the main session"
        ),
        f"Runs in the background (the delegating agent does not block): {bool(background)}",
        f"Session permission mode: {payload.get('permission_mode') or 'unknown'}",
        f"Session effort level: {effort_level or 'unspecified'}",
        f"Working directory: {payload.get('cwd', 'unknown')}",
        f"Task given to the subagent:\n{prompt}",
    ]
    # Truncated from the BACK, unlike every other builder. A transcript's value
    # is in its tail; a delegation prompt states the task first and elaborates
    # afterwards, so the head is what must survive. Real traffic never reaches
    # the cap -- the longest observed delegation prompt is 13.8k chars against a
    # 60k budget -- but the direction is wrong or right regardless of whether it
    # has fired yet.
    return _truncate_tail("\n\n".join(parts))


def _truncate_tail(text: str, limit: int = MAX_STATE_CHARS) -> str:
    """Truncate from the BACK, keeping the beginning. See `build_agent_route`."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[... later content truncated ...]"


def build_stop(payload: dict[str, Any]) -> str:
    """The one surface that reads the transcript -- truncated at capture length.

    `last_assistant_message` alone cannot judge completion, because completion is
    relative to what was asked. So we read the transcript, but only the prefix
    that existed when the hook fired.
    """
    transcript_path = payload.get("transcript_path")
    limit = payload.get("transcript_bytes_at_capture")
    if not transcript_path:
        raise StateBuildError("stop payload has no transcript_path")
    path = Path(transcript_path)
    if not path.exists():
        raise StateBuildError(f"transcript no longer exists: {transcript_path}")
    if not isinstance(limit, int) or limit <= 0:
        raise StateBuildError(
            "stop state requires transcript_bytes_at_capture; without it the "
            "builder would read turns that happened after the decision point"
        )

    with path.open("rb") as fh:
        blob = fh.read(limit)

    turns: list[str] = []
    for raw in blob.decode("utf-8", errors="ignore").splitlines():
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            continue  # a partial final line is expected at a byte boundary
        role = (line.get("message") or {}).get("role")
        if role not in ("user", "assistant"):
            continue
        content = (line.get("message") or {}).get("content")
        text = _flatten_content(content)
        if text:
            turns.append(f"{role.upper()}: {text}")

    if not turns:
        raise StateBuildError("no usable turns in the truncated transcript")

    last = payload.get("last_assistant_message")
    tail = f"\n\nFinal assistant message:\n{last}" if last else ""
    return _truncate("Conversation so far:\n\n" + "\n\n".join(turns) + tail)


def _flatten_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    out: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            out.append(block.get("text", ""))
        elif btype == "tool_use":
            out.append(f"[tool_use {block.get('name')}]")
        elif btype == "tool_result":
            body = _flatten_content(block.get("content"))
            flag = " is_error" if block.get("is_error") else ""
            out.append(f"[tool_result{flag}] {body[:500]}")
    return "\n".join(s for s in out if s).strip()


BUILDERS = {
    "pre_bash": build_pre_bash,
    "agent_route": build_agent_route,
    "stop": build_stop,
    "user_prompt": build_user_prompt,
    "post_edit": build_post_edit,
}

STATE_SOURCE = {
    "pre_bash": "payload",
    # JEV-34. Payload-only, like `pre_bash` -- the richness comes from using
    # MORE of the payload, not from reaching outside it.
    "agent_route": "payload",
    "stop": "transcript@byte_offset",
    "user_prompt": "payload",
    "post_edit": "payload",
}


def build(surface: str, payload: dict[str, Any]) -> str:
    builder = BUILDERS.get(surface)
    if builder is None:
        raise StateBuildError(f"no state builder for surface: {surface}")
    return builder(payload)
