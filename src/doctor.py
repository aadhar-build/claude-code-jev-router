#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Health and self-containment check.

Run this before and after anything else. It answers three questions:
  1. Is the folder laid out correctly and are credentials loadable?
  2. Is the isolation requirement intact -- no hooks registered at user level?
  3. Is the self-containment requirement intact -- does anything write outside
     this folder?

Exit code 0 = all checks pass, 1 = at least one FAIL. WARNs do not fail the run.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths  # noqa: E402

USER_SETTINGS = Path.home() / ".claude" / "settings.json"
PROJECT_LOCAL_SETTINGS = paths.ROOT / ".claude" / "settings.local.json"

# Paths that source code is allowed to reference outside ROOT, read-only.
ALLOWED_OUTSIDE_READS = {"CLAUDE_PROJECTS", "CLAUDE_HISTORY"}

# The only paths under data/ that may be tracked by git, listed exactly rather
# than by prefix so that a new file cannot join the list by accident. Each is
# aggregate or synthetic, carries no third-party content, and has a stated
# reason to outlive the folder:
#   canary-set-v1.json          a PRE-REGISTERED fixture; unauditable if untracked
#   baseline/*                  JEV-38: derived per-session metrics whose SOURCE
#                               lives outside this repo under a retention sweep
#                               we do not control
COMMITTABLE_DATA_PATHS = {
    "data/fixtures/canary-set-v1.json",
    "data/baseline/sessions.jsonl",
    "data/baseline/manifest.json",
    "data/baseline/delegation-pre-rule-v1.json",
}

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))


def check_layout() -> None:
    missing = [str(d.relative_to(paths.ROOT)) for d in paths.WRITABLE_DIRS if not d.is_dir()]
    if missing:
        record("FAIL", "layout", f"missing directories: {', '.join(missing)}")
    else:
        record("PASS", "layout", f"{len(paths.WRITABLE_DIRS)} writable dirs present")


def check_paths_inside_root() -> None:
    """Every path constant except the documented read-only one must be under ROOT."""
    offenders = []
    for name in dir(paths):
        if name.startswith("_") or name in ALLOWED_OUTSIDE_READS:
            continue
        value = getattr(paths, name)
        if isinstance(value, Path) and paths.ROOT not in value.parents and value != paths.ROOT:
            offenders.append(f"{name}={value}")
    if offenders:
        record("FAIL", "paths-under-root", "; ".join(offenders))
    else:
        record("PASS", "paths-under-root", "all write paths resolve under the folder")


def check_credentials() -> None:
    if not paths.ENV_FILE.exists():
        record("FAIL", "env-file", f"{paths.ENV_FILE} does not exist")
        return
    if not paths.env_file_mode_ok():
        record("FAIL", "env-mode", ".env is group- or world-accessible; run chmod 600 .env")
    else:
        record("PASS", "env-mode", "mode 600")

    env = paths.load_env()
    if env.get("AI_GATEWAY_API_KEY"):
        record("PASS", "cred:AI_GATEWAY_API_KEY", f"present ({len(env['AI_GATEWAY_API_KEY'])} chars)")
    else:
        record("WARN", "cred:AI_GATEWAY_API_KEY", "empty — the jev arm cannot run until this is set")

    # ANTHROPIC_API_KEY is deliberately NOT required: the baseline runs on the
    # subscription via the claude CLI. The metered-API arms stay defined but
    # disabled, so a missing key is the expected state, not a problem.
    if env.get("ANTHROPIC_API_KEY"):
        record("PASS", "cred:ANTHROPIC_API_KEY",
               "present — only needed if you re-enable the metered opus5/haiku45 arms")
    else:
        record("PASS", "cred:ANTHROPIC_API_KEY",
               "absent, as intended — the baseline runs on the subscription")


def check_claude_cli() -> None:
    """The cc_* arms shell out to `claude`, so it has to be there and logged in."""
    found = shutil.which("claude")
    if not found:
        record("FAIL", "claude-cli", "not on PATH — the cc_* baseline arms cannot run")
        return
    record("PASS", "claude-cli", found)

    try:
        arms = json.loads((paths.CONFIG / "arms.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        record("WARN", "arms-config", str(exc))
        return
    enabled = arms.get("enabled", [])
    metered = [n for n in enabled if arms["arms"].get(n, {}).get("kind") == "anthropic"]
    if metered:
        record("WARN", "arms-enabled",
               f"metered-API arms enabled ({', '.join(metered)}) — these need ANTHROPIC_API_KEY "
               f"and change the headline claim back to model-vs-model")
    else:
        record("PASS", "arms-enabled", f"{', '.join(enabled)} — subscription-only, no API key needed")


def check_gitignore() -> None:
    gi = paths.ROOT / ".gitignore"
    if not gi.exists():
        record("FAIL", "gitignore", "missing")
        return
    body = gi.read_text()
    required = [".env", ".claude/settings.local.json", "data/", "spool/", "logs/", ".jev-disabled"]
    missing = [r for r in required if r not in body]
    if missing:
        record("FAIL", "gitignore", f"not ignored: {', '.join(missing)}")
    else:
        record("PASS", "gitignore", "credentials, data, spool, logs and hook registration ignored")


def check_nothing_staged_secret() -> None:
    try:
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=paths.ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        record("WARN", "git", "not a git repository yet")
        return
    leaked = [f for f in tracked
              if f not in COMMITTABLE_DATA_PATHS
              and (f == ".env" or f.startswith(("data/", "spool/", "logs/"))
                   or f == ".claude/settings.local.json")]
    if leaked:
        record("FAIL", "git-tracked", f"should never be tracked: {', '.join(leaked)}")
    else:
        allowed = sorted(f for f in tracked if f in COMMITTABLE_DATA_PATHS)
        detail = f"{len(tracked)} files tracked, none sensitive"
        if allowed:
            detail += f"; {len(allowed)} allowlisted under data/ ({', '.join(allowed)})"
        record("PASS", "git-tracked", detail)


def check_user_settings_untouched() -> None:
    """The isolation requirement: no hooks may be registered at user level."""
    if not USER_SETTINGS.exists():
        record("PASS", "user-settings", "no ~/.claude/settings.json")
        return
    try:
        data = json.loads(USER_SETTINGS.read_text())
    except json.JSONDecodeError as exc:
        record("WARN", "user-settings", f"unparseable: {exc}")
        return
    if "hooks" in data:
        record("FAIL", "user-settings", "~/.claude/settings.json has a `hooks` key — isolation broken")
    else:
        record("PASS", "user-settings", "no `hooks` key at user level")


def check_no_outside_writes_in_source() -> None:
    """Static check: no source file writes to a path outside this folder.

    Looks for home-anchored or absolute-system paths in write position. This is a
    lint, not a proof -- the runtime gate is check_paths_inside_root plus the
    fact that every writer imports its destination from paths.py.
    """
    suspicious = re.compile(
        r"""(open\(|write_text\(|write_bytes\(|mkdir\(|touch\(|shutil\.(copy|move)).{0,120}?"""
        r"""(~/|Path\.home\(\)|/tmp/|/var/|/etc/|LaunchAgents)""",
        re.VERBOSE,
    )
    offenders = []
    for f in sorted((paths.ROOT / "src").rglob("*.py")) + sorted((paths.ROOT / "hooks").rglob("*.sh")):
        if f.name == "doctor.py":
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if suspicious.search(line):
                offenders.append(f"{f.relative_to(paths.ROOT)}:{i}")
    if offenders:
        record("FAIL", "no-outside-writes", "; ".join(offenders))
    else:
        record("PASS", "no-outside-writes", "no source file writes outside the folder")


def check_kill_switch() -> None:
    if paths.killed():
        record("WARN", "kill-switch", ".jev-disabled present — capture is OFF")
    else:
        record("PASS", "kill-switch", "absent (capture enabled when hooks are registered)")


def check_hook_registration() -> None:
    if not PROJECT_LOCAL_SETTINGS.exists():
        record("PASS", "hook-registration", "not yet registered (expected until ticket 8)")
        return
    try:
        data = json.loads(PROJECT_LOCAL_SETTINGS.read_text())
    except json.JSONDecodeError as exc:
        record("FAIL", "hook-registration", f"settings.local.json unparseable: {exc}")
        return
    events = sorted((data.get("hooks") or {}).keys())
    record("PASS", "hook-registration", f"registered for: {', '.join(events) or 'nothing'}")


def main() -> int:
    paths.ensure_dirs()
    check_layout()
    check_paths_inside_root()
    check_credentials()
    check_claude_cli()
    check_gitignore()
    check_nothing_staged_secret()
    check_user_settings_untouched()
    check_no_outside_writes_in_source()
    check_kill_switch()
    check_hook_registration()

    width = max(len(name) for _, name, _ in results)
    print(f"\njev doctor — {paths.ROOT}\n")
    for status, name, detail in results:
        mark = {"PASS": "  ok  ", "WARN": " warn ", "FAIL": " FAIL "}[status]
        print(f"[{mark}] {name.ljust(width)}  {detail}")

    fails = sum(1 for s, _, _ in results if s == "FAIL")
    warns = sum(1 for s, _, _ in results if s == "WARN")
    print(f"\n{len(results) - fails - warns} passed, {warns} warned, {fails} failed\n")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
