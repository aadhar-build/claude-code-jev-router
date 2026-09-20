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
SPOOL_CLAIMED = SPOOL / "claimed"
SPOOL_DEAD = SPOOL / "dead"

DATA = ROOT / "data"
CAPTURES = DATA / "captures"
STATES = DATA / "states"
RUNS = DATA / "runs"
LABELS = DATA / "labels"
FIXTURES = DATA / "fixtures"

# JEV-38. The persisted "before" baseline: an append-only, IN-REPO record of
# per-session derived metrics, snapshotted from transcripts that live outside
# this folder under a retention policy we do not control. This is the one
# directory under data/ that is committed to git, because it is the one thing
# that must survive losing the folder. Derived numbers only -- never prompt
# text, never message content.
BASELINE = DATA / "baseline"

# JEV-33. The backpressure-drop stream, written by hooks/capture.sh (NOT by
# store.py) when the spool is too deep to accept another capture, and the
# monotonic spool high-water mark, written by the worker. Both live under
# data/ rather than logs/ because a dropped capture is attrition the
# pre-registration commits to reporting, and attrition must outlive a log
# rotation.
DROPS = DATA / "drops"
SPOOL_WATERMARK = DATA / "spool_watermark.json"

# The one path outside ROOT, and it is READ-ONLY. Claude Code owns it; we never
# write there. Fixtures used by tests are copied into FIXTURES.
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# Also outside ROOT and also READ-ONLY. Claude Code's own prompt index: one
# line per prompt the user typed, carrying {timestamp, project, sessionId,
# display}. JEV-38 reads ONLY the first three -- `display` is the prompt text
# and is never read, never copied. It is the independent index against which
# "how many sessions were already unrecoverable" can be answered at all: a
# session_id that appears here with no transcript on disk is a session that
# has been reaped.
CLAUDE_HISTORY = Path.home() / ".claude" / "history.jsonl"

WRITABLE_DIRS = [
    SPOOL_TMP,
    SPOOL_READY,
    CAPTURES,
    STATES,
    RUNS,
    LABELS,
    FIXTURES,
    BASELINE,
    DROPS,
    LOGS,
    REPORTS,
]

SURFACES = ("pre_bash", "stop", "user_prompt", "post_edit")


def ensure_dirs() -> None:
    for d in WRITABLE_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def load_env(path: Path | None = None) -> dict[str, str]:
    """Parse .env into a dict. Does not mutate os.environ.

    Deliberately minimal: KEY=VALUE, '#' comments, no interpolation, no quoting
    rules. An API key does not need a parser.
    """
    # Resolved at call time, not bound as a default: a default argument is
    # evaluated once at import, so patching paths.ENV_FILE afterwards would have
    # no effect -- which is exactly how a test meant to run WITHOUT credentials
    # ended up making a real, billed API call.
    path = path or ENV_FILE
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


def env_file_mode_ok(path: Path | None = None) -> bool:
    """True if .env is not readable or writable by group or other."""
    path = path or ENV_FILE
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
    """True if the kill switch is set.

    JEV-40: this must agree with the hooks' own test, which treats ANY entry at
    the path as ON -- a regular file, a directory, an unreadable file, or a
    dangling symlink. `.exists()` alone follows a symlink and reads a dangling
    one as absent, which would report "running" while every hook was exiting on
    line one. `src/reversibility.py` describes the same rule in words for the
    operator; these two are the only places it is encoded outside the hooks.
    """
    return KILL_SWITCH.exists() or KILL_SWITCH.is_symlink()
