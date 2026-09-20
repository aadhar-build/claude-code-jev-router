"""Filesystem layout and credential loading.

Every path this experiment writes to is derived from ROOT. Nothing is written
outside it -- see doctor.py, which asserts that.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ENV_FILE = ROOT / ".env"
KILL_SWITCH = ROOT / ".jev-disabled"

HOOKS = ROOT / "hooks"
CONFIG = ROOT / "config"
QUESTIONS = ROOT / "questions"
LOGS = ROOT / "logs"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"

SPOOL = ROOT / "spool"
SPOOL_TMP = SPOOL / "tmp"
SPOOL_READY = SPOOL / "ready"

DATA = ROOT / "data"
CAPTURES = DATA / "captures"
STATES = DATA / "states"
RUNS = DATA / "runs"
LABELS = DATA / "labels"
FIXTURES = DATA / "fixtures"

# The one path outside ROOT, and it is READ-ONLY. Claude Code owns it; we never
# write there. Fixtures used by tests are copied into FIXTURES.
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

WRITABLE_DIRS = [
    SPOOL_TMP,
    SPOOL_READY,
    CAPTURES,
    STATES,
    RUNS,
    LABELS,
    FIXTURES,
    LOGS,
    REPORTS,
]

SURFACES = ("pre_bash", "stop", "user_prompt", "post_edit")


def ensure_dirs() -> None:
    for d in WRITABLE_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse .env into a dict. Does not mutate os.environ.

    Deliberately minimal: KEY=VALUE, '#' comments, no interpolation, no quoting
    rules. An API key does not need a parser.
    """
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def env_file_mode_ok(path: Path = ENV_FILE) -> bool:
    """True if .env is not readable or writable by group or other."""
    if not path.exists():
        return False
    mode = path.stat().st_mode
    return not (mode & (stat.S_IRWXG | stat.S_IRWXO))


def require(name: str) -> str:
    """Fetch a credential from .env, falling back to the process environment."""
    value = load_env().get(name) or os.environ.get(name, "")
    if not value:
        raise RuntimeError(
            f"{name} is not set. Add it to {ENV_FILE} (mode 600) or export it."
        )
    return value


def killed() -> bool:
    return KILL_SWITCH.exists()
