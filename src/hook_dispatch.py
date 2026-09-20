#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""A faithful model of Claude Code's `PreToolUse` dispatch, so that "the tool
input the harness would have used" is something we can compute and compare.

JEV-40 needs to prove a claim that cannot be proved by reading a hook script:
*with the switch on, the tool input left behind is byte-identical to the one
Claude Code would have produced with no hooks registered at all.* A hook that
exits early still ran. Only a comparison of the resulting input can tell the two
apart, and that comparison needs an oracle for "the resulting input".

This module is that oracle. It reads a settings file, runs the registered
`PreToolUse` handlers against a payload exactly as the documented contract
says they are run, and returns the tool input that survives.

The contract implemented here, from `code.claude.com/docs/en/hooks.md`
(Claude Code v2.1.278, read 2026-09-20):

  * Handlers are grouped by `matcher`, a regex over the tool name. A missing or
    empty matcher matches every tool.
  * A command handler receives the hook payload as JSON on stdin.
  * Empty stdout, plain-text stdout, or stdout that does not parse as JSON
    leaves the tool input UNCHANGED (a non-blocking error at worst).
  * `hookSpecificOutput.updatedInput` replaces the tool's arguments ENTIRELY --
    not a merge. A field the hook forgets to echo back is a field the tool never
    sees.
  * `hookSpecificOutput.permissionDecision: "deny"`, or a top-level
    `{"decision": "block"}`, stops the call. Exit code 2 also blocks.
  * Handlers run in order; each one sees the input left by the previous one.

"Byte-identical" is defined here as identity of the CANONICAL serialisation --
`json.dumps(..., sort_keys=True, separators=(",", ":"))` -- of the resulting
`tool_input` object. Canonicalisation matters because the comparison is between
an object that went through a hook's `jq` and one that did not, and jq's key
order is not Python's. Key order is not part of the claim; the set of keys and
their exact values is.

For JEV-35 the same definition transfers to a live session: the oracle there is
the `tool_input` echoed by `PostToolUse`, which reflects `updatedInput`,
serialised the same way.

Usage:
    hook_dispatch.py --settings PATH --project-dir DIR --payload FILE
    hook_dispatch.py ... --print resolved|report
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 15


def canonical(obj: Any) -> str:
    """The serialisation the byte-identity claim is made about."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _matches(matcher: str | None, tool_name: str) -> bool:
    if matcher in (None, "", "*"):
        return True
    try:
        return re.fullmatch(matcher, tool_name) is not None
    except re.error:
        return matcher == tool_name


def registered_handlers(settings: dict, event: str | None = None) -> list[dict]:
    """Flatten a settings file into one record per registered hook handler.

    Every event, not just `PreToolUse`: the enumeration gate has to see a hook
    the moment it is registered, whatever surface it is registered on.
    """
    out: list[dict] = []
    hooks = settings.get("hooks") or {}
    for event_name, groups in hooks.items():
        if event is not None and event_name != event:
            continue
        for group in groups or []:
            for handler in group.get("hooks") or []:
                out.append(
                    {
                        "event": event_name,
                        "matcher": group.get("matcher"),
                        "type": handler.get("type"),
                        "command": handler.get("command"),
                        "timeout": handler.get("timeout"),
                    }
                )
    return out


def run_pre_tool_use(
    settings: dict,
    payload: dict,
    project_dir: Path,
    env: dict[str, str] | None = None,
) -> dict:
    """Dispatch `PreToolUse` handlers and report the tool input that survives.

    Returns a dict with the resolved input, whether the call would have been
    blocked, and a per-handler trace -- the trace is what makes a failure
    diagnosable rather than merely red.
    """
    tool_name = payload.get("tool_name", "")
    current = payload.get("tool_input", {})
    trace: list[dict] = []
    blocked = False

    base_env = dict(os.environ if env is None else env)
    base_env["CLAUDE_PROJECT_DIR"] = str(project_dir)

    for handler in registered_handlers(settings, "PreToolUse"):
        if not _matches(handler["matcher"], tool_name):
            continue
        if handler["type"] != "command":
            trace.append({"command": handler["command"], "skipped": "not a command hook"})
            continue

        this_payload = dict(payload)
        this_payload["tool_input"] = current
        try:
            proc = subprocess.run(
                ["bash", "-c", handler["command"]],
                input=json.dumps(this_payload),
                capture_output=True,
                text=True,
                cwd=str(project_dir),
                env=base_env,
                timeout=handler.get("timeout") or DEFAULT_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            # A timed-out PreToolUse command hook renders no decision and does
            # not block the call. Documented explicitly, and worth modelling:
            # a hook that stalls must not look like a hook that rewrote.
            trace.append({"command": handler["command"], "outcome": "timeout"})
            continue

        entry = {
            "command": handler["command"],
            "exit": proc.returncode,
            "stdout_bytes": len(proc.stdout),
            "outcome": "unchanged",
        }

        if proc.returncode == 2:
            blocked = True
            entry["outcome"] = "blocked (exit 2)"
            trace.append(entry)
            break

        try:
            decision = json.loads(proc.stdout) if proc.stdout.strip() else None
        except json.JSONDecodeError:
            decision = None

        if isinstance(decision, dict):
            if decision.get("decision") == "block":
                blocked = True
                entry["outcome"] = "blocked (decision)"
            hso = decision.get("hookSpecificOutput") or {}
            if hso.get("permissionDecision") == "deny":
                blocked = True
                entry["outcome"] = "blocked (permissionDecision)"
            updated = hso.get("updatedInput")
            if isinstance(updated, dict):
                # Replaces the ENTIRE input object. Not a merge -- that is the
                # whole reason JEV-35 needs an input-fidelity gate.
                current = updated
                entry["outcome"] = "rewrote updatedInput"

        trace.append(entry)
        if blocked:
            break

    return {
        "tool_name": tool_name,
        "resolved_input": current,
        "resolved_canonical": canonical(current),
        "blocked": blocked,
        "trace": trace,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--settings", required=True, type=Path)
    ap.add_argument("--project-dir", required=True, type=Path)
    ap.add_argument("--payload", required=True, type=Path)
    ap.add_argument("--print", dest="mode", default="resolved",
                    choices=["resolved", "report"])
    args = ap.parse_args()

    if args.settings.exists():
        settings = json.loads(args.settings.read_text())
    else:
        # An absent settings file is the "hooks unregistered entirely" arm. It
        # must be representable, because it is the control the whole comparison
        # is against.
        settings = {}

    payload = json.loads(args.payload.read_text())
    result = run_pre_tool_use(settings, payload, args.project_dir.resolve())

    if args.mode == "report":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(result["resolved_canonical"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
