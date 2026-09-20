#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-40. The whole reversibility state of this machine, in one place.

`doctor.py` answers "is this healthy". This answers a different question, the
one you ask when you want out: *what is this folder currently doing to my
machine, and what exactly would it take to stop?*

Four parts, printed together because they are only useful together:

  1. which hooks are registered, and whether each one checks the switch
  2. whether the switch is set
  3. what is inside the folder
  4. what has been written outside it

Plus the teardown command, so the answer to "how do I stop this" is on the same
screen as the reason you asked.

Run standalone (`uv run src/reversibility.py`) or via `uv run src/doctor.py`,
which prints this block after its check table.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths  # noqa: E402

SWITCH_BLOCK_MARKER = "# --- jev kill switch: canonical block"

USER_SETTINGS = Path.home() / ".claude" / "settings.json"
PROJECT_LOCAL_SETTINGS = paths.ROOT / ".claude" / "settings.local.json"
PROJECT_SHARED_SETTINGS = paths.ROOT / ".claude" / "settings.json"

TEARDOWN_CMD = "./teardown.sh --yes"


def switch_state() -> tuple[bool, str]:
    """(set, description). Mirrors the hooks' own fail-safe test exactly.

    The hooks treat ANY entry at the path as ON -- a regular file, a directory,
    an unreadable file, or a dangling symlink -- because a switch whose state
    cannot be established must never be read as OFF. This function has to agree
    with them, or the operator is told one thing while the hooks do another.
    """
    p = paths.KILL_SWITCH
    if p.is_symlink() and not p.exists():
        return True, "SET (dangling symlink at the path — still counts as set)"
    if p.is_dir():
        return True, "SET (a DIRECTORY at the path — counts as set; `rmdir` to clear)"
    if p.exists():
        return True, "SET"
    return False, "not set"


def registered_hooks() -> tuple[list[dict], str | None]:
    """Every registered handler, with the script it resolves to."""
    if not PROJECT_LOCAL_SETTINGS.exists():
        return [], None
    try:
        settings = json.loads(PROJECT_LOCAL_SETTINGS.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"unreadable: {exc}"

    out: list[dict] = []
    for event, groups in (settings.get("hooks") or {}).items():
        for group in groups or []:
            for handler in group.get("hooks") or []:
                cmd = handler.get("command") or ""
                expanded = (cmd.replace("${CLAUDE_PROJECT_DIR}", str(paths.ROOT))
                               .replace("$CLAUDE_PROJECT_DIR", str(paths.ROOT)))
                script = None
                try:
                    script = next((a for a in shlex.split(expanded)
                                   if a.endswith((".sh", ".py", ".bash"))), None)
                except ValueError:
                    pass
                checks = False
                if script and Path(script).exists():
                    checks = SWITCH_BLOCK_MARKER in Path(script).read_text()
                out.append({
                    "event": event,
                    "matcher": group.get("matcher") or "(all tools)",
                    "command": cmd,
                    "script": script,
                    "anchored": "CLAUDE_PROJECT_DIR" in cmd,
                    "checks_switch": checks,
                })
    return out, None


def _dir_stats(d: Path) -> str:
    if not d.is_dir():
        return "absent"
    files = [f for f in d.rglob("*") if f.is_file()]
    size = sum(f.stat().st_size for f in files)
    return f"{len(files)} files, {size / 1024:.0f} KiB"


def outside_writes() -> list[tuple[str, str]]:
    """What has been written outside this folder. The answer should be nothing."""
    rows: list[tuple[str, str]] = []

    if not USER_SETTINGS.exists():
        rows.append(("~/.claude/settings.json", "does not exist — nothing was written there"))
    else:
        try:
            data = json.loads(USER_SETTINGS.read_text())
            if "hooks" in data:
                rows.append(("~/.claude/settings.json", "HAS a `hooks` key — isolation is broken"))
            else:
                rows.append(("~/.claude/settings.json",
                             "exists (yours, pre-existing) — no `hooks` key, untouched by this folder"))
        except (OSError, json.JSONDecodeError) as exc:
            rows.append(("~/.claude/settings.json", f"unreadable: {exc}"))

    rows.append((str(paths.CLAUDE_PROJECTS),
                 "READ ONLY — transcripts are read in place; nothing is written back"))

    if PROJECT_SHARED_SETTINGS.exists():
        rows.append((".claude/settings.json",
                     "EXISTS — this file travels to clones and cloud sessions; registration must not live here"))
    else:
        rows.append((".claude/settings.json",
                     "absent, as intended — registration lives only in the gitignored settings.local.json"))

    return rows


def lines() -> list[str]:
    out: list[str] = []
    a = out.append

    a("")
    a("reversibility — what this folder is doing, and how to stop it")
    a("")

    # 1. hooks
    hooks, err = registered_hooks()
    if err:
        a(f"  hooks registered   .claude/settings.local.json {err}")
    elif not hooks:
        a("  hooks registered   NONE — this machine is already stock Claude Code")
    else:
        a(f"  hooks registered   {len(hooks)} handler(s) in .claude/settings.local.json (gitignored)")
        for h in hooks:
            mark = "checks switch" if h["checks_switch"] else "DOES NOT CHECK THE SWITCH"
            anchor = "anchored" if h["anchored"] else "NOT $CLAUDE_PROJECT_DIR-ANCHORED"
            a(f"                     - {h['event']} / {h['matcher']}: {h['command']}")
            a(f"                       {anchor}, {mark}")

    # 2. switch
    is_set, desc = switch_state()
    a("")
    a(f"  kill switch        {desc}  ({paths.KILL_SWITCH})")
    if is_set:
        a("                     every hook exits on line one. Takes effect at the NEXT")
        a("                     hook invocation, in sessions already running.")
    else:
        a("                     `touch .jev-disabled` to stop every hook immediately.")

    # 3. inside
    a("")
    a("  inside the folder  everything this experiment has produced:")
    for label, d in (("data/", paths.DATA), ("spool/", paths.SPOOL),
                     ("logs/", paths.LOGS), ("reports/", paths.REPORTS)):
        a(f"                     - {label:<10} {_dir_stats(d)}")
    a(f"                     - .env       {'present (mode 600)' if paths.ENV_FILE.exists() else 'absent'}")
    a("                     Deleting this folder removes all of it.")

    # 4. outside
    a("")
    a("  outside the folder what has been written elsewhere on this machine:")
    for name, detail in outside_writes():
        a(f"                     - {name}")
        a(f"                       {detail}")

    # teardown
    a("")
    a(f"  teardown           {TEARDOWN_CMD}        (./teardown.sh --dry-run first)")
    a("                     Sets the switch, then unregisters the hooks by moving")
    a("                     settings.local.json aside. It does NOT delete data/,")
    a("                     spool/, logs/ or .env, and it cannot undo work already")
    a("                     produced by a routed model — see ISSUES.md, JEV-40.")
    a("")
    return out


def main() -> int:
    print("\n".join(lines()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
