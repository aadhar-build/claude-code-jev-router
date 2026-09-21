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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyversion  # noqa: E402

# JEV-44: assert the floor BEFORE importing anything that does not parse
# below it. The PEP-723 header above binds `uv run` only; `python3
# tests/<this file>` ignores it entirely, and that is the invocation that
# produced 16 SyntaxErrors out of src/arms/jev.py:237.
pyversion.require()


import paths  # noqa: E402
import reversibility  # noqa: E402

USER_SETTINGS = Path.home() / ".claude" / "settings.json"
PROJECT_LOCAL_SETTINGS = paths.ROOT / ".claude" / "settings.local.json"

# Paths that source code is allowed to reference outside ROOT, read-only.
# W2 adds a third: HOME_KILL_SWITCH, `~/.claude/jev-disabled`. It is the
# machine-wide kill switch, and it is READ-ONLY in exactly the sense the other
# two are -- the hooks `[ -e ]` it and nothing in this repo ever creates it. It
# has to live outside the folder to do its job: a switch that stops jev in every
# project cannot be anchored inside one project.
ALLOWED_OUTSIDE_READS = {"CLAUDE_PROJECTS", "CLAUDE_HISTORY", "HOME_KILL_SWITCH"}

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
    "data/baseline/delegation-pre-rule-v1-corrected.json",
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
    # JEV-40: agree with the hooks' own fail-safe test, which treats ANY entry
    # at the path as ON. `paths.killed()` uses `.exists()`, which reads a
    # dangling symlink as absent -- so ask reversibility.switch_state(), the one
    # function that mirrors the shipped block.
    is_set, desc = reversibility.switch_state()
    if is_set:
        record("WARN", "kill-switch", f".jev-disabled {desc} — every hook exits on line one")
    else:
        record("PASS", "kill-switch", "absent (capture enabled when hooks are registered)")


def check_switch_on_every_hook() -> None:
    """JEV-40: one switch, all surfaces. A registered hook without the canonical
    block is a surface that cannot be turned off."""
    hooks, err = reversibility.registered_hooks()
    if err:
        record("FAIL", "switch-coverage", err)
        return
    if not hooks:
        record("PASS", "switch-coverage", "no hooks registered — nothing to cover")
        return
    bad = [f"{h['event']}/{h['matcher']}" for h in hooks
           if not h["checks_switch"] or not h["anchored"]]
    if bad:
        record("FAIL", "switch-coverage",
               f"registered without an anchored kill-switch check: {', '.join(bad)}")
    else:
        record("PASS", "switch-coverage",
               f"all {len(hooks)} registered hook(s) check the anchored switch on line one")


def check_routing_breaker() -> None:
    """JEV-35 / W1: is the static router's circuit breaker open?

    Fail-to-frontier protects quality on the error path and does NOT protect
    cost -- a sustained failure bills frontier rates for as long as it lasts.
    The breaker bounds that by suspending rewriting entirely, and the whole
    point of a breaker is that somebody finds out. The hook says so in a
    `systemMessage` at the time; this is the half that is still true tomorrow
    morning, when the session that saw the message is gone.
    """
    marker = paths.AGENT_ROUTE / "BREAKER-OPEN"
    if not marker.exists():
        record("PASS", "routing-breaker", "closed (no BREAKER-OPEN marker)")
        return
    first = marker.read_text(errors="replace").splitlines()[:1]
    record("WARN", "routing-breaker",
           f"OPEN — static routing SUSPENDED, every delegation at its default "
           f"tier. {first[0] if first else ''}")


def _age_since(stamp: str, fallback: Path) -> tuple[str, str]:
    """(printable timestamp, printable age). Falls back to the file's mtime.

    The marker's first token is the UTC stamp the hook wrote. A marker whose
    first line has been edited or truncated still has an mtime, and an age from
    the filesystem is worth more than no age at all -- it is labelled as such.
    """
    origin = None
    try:
        origin = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        shown = stamp
    except ValueError:
        try:
            origin = datetime.fromtimestamp(fallback.stat().st_mtime, timezone.utc)
        except OSError:
            return ("timestamp unrecorded", "unknown")
        shown = origin.strftime("%Y-%m-%dT%H:%M:%SZ") + " (file mtime)"
    seconds = max(0, int((datetime.now(timezone.utc) - origin).total_seconds()))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        age = f"{days}d {hours}h"
    elif hours:
        age = f"{hours}h {minutes}m"
    else:
        age = f"{minutes}m"
    return (shown, age)


def check_routing_inert() -> None:
    """JEV-61: is the actuator INERT -- registered, and routing nothing?

    A DIFFERENT CONDITION FROM BREAKER-OPEN, WITH A DIFFERENT REMEDY, WHICH IS
    WHY IT IS A SEPARATE CHECK RATHER THAN A BRANCH INSIDE THE BREAKER'S.

      BREAKER-OPEN  the router works, and has deliberately stopped rewriting
                    because the provider kept failing. It is self-limiting: the
                    breaker's state is derived from a log that keeps being
                    written, so a later success clears it without anyone acting.

      INERT         the hook cannot route AND cannot record -- no jq, an
                    unwritable ledger, a cwd outside the project. It writes no
                    decisions, so NO LATER EVENT COULD HONESTLY CLEAR IT. That
                    asymmetry is W5's decision, not an omission: a stale false
                    alarm beats a false negative, because an inert hook is
                    byte-identical to the control arm while appearing installed
                    -- the exact state this repo has now shipped five times.
                    Someone fixes the cause and removes the marker by hand.
    """
    marker = paths.AGENT_ROUTE / "INERT"
    if not marker.exists():
        record("PASS", "routing-inert", "no INERT marker — the actuator is "
                                        "recording its decisions")
        return
    lines = marker.read_text(errors="replace").splitlines()
    first = lines[0] if lines else ""
    stamp = first.split(" ", 1)[0]
    cause = (first.split("INERT:", 1)[1].strip() if "INERT:" in first else "")
    cause = cause or "cause unrecorded"
    detail = lines[1].strip() if len(lines) > 1 else ""
    shown, age = _age_since(stamp, marker)
    record("WARN", "routing-inert",
           f"INERT since {shown} ({age} ago) — cause: {cause}."
           + (f" {detail}" if detail else "")
           + " The actuator is registered and routes nothing, so no assignment "
             "is being recorded. This marker does not self-clear (an inert hook "
             f"writes no decisions that could): fix the cause, then `rm {marker}`.")


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
    check_routing_breaker()
    check_routing_inert()
    check_hook_registration()
    check_switch_on_every_hook()

    width = max(len(name) for _, name, _ in results)
    print(f"\njev doctor — {paths.ROOT}\n")
    for status, name, detail in results:
        mark = {"PASS": "  ok  ", "WARN": " warn ", "FAIL": " FAIL "}[status]
        print(f"[{mark}] {name.ljust(width)}  {detail}")

    fails = sum(1 for s, _, _ in results if s == "FAIL")
    warns = sum(1 for s, _, _ in results if s == "WARN")
    # JEV-40. The full reversibility state, in one place: which hooks are
    # registered, whether the switch is set, what is inside the folder, what has
    # been written outside it, and the one command that undoes the first two.
    # It is printed rather than recorded as a check because it is not a
    # pass/fail question -- it is the answer to "how do I stop this".
    #
    # Printed BEFORE the summary line, so that `doctor.py | tail -3` still ends
    # on the pass/warn/fail counts.
    print("\n".join(reversibility.lines()))

    print(f"{len(results) - fails - warns} passed, {warns} warned, {fails} failed\n")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
