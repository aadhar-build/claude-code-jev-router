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
    "stop": build_stop,
    "user_prompt": build_user_prompt,
    "post_edit": build_post_edit,
}

STATE_SOURCE = {
    "pre_bash": "payload",
    "stop": "transcript@byte_offset",
    "user_prompt": "payload",
    "post_edit": "payload",
}


def build(surface: str, payload: dict[str, Any]) -> str:
    builder = BUILDERS.get(surface)
    if builder is None:
        raise StateBuildError(f"no state builder for surface: {surface}")
    return builder(payload)
