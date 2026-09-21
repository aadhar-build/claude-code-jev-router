"""Filesystem layout and credential loading.

Every path this experiment writes to is derived from ROOT. Nothing is written
outside it -- see doctor.py, which asserts that.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

# --- jev home: the Python half of the canonical block ------------------------
# W2. ONE MECHANISM, BOTH READERS.
#
# Before this, `paths.py` derived its root from `__file__` while every bash hook
# derived its root from `$CLAUDE_PROJECT_DIR`. Two mechanisms, and in any install
# shape where the project being routed is not jev's own repo they disagree --
# silently, because neither one can see the other. The pivot audit found the
# sharp end of that: with jev's root taken from the session's project directory,
# the kill switch names a path that will never exist, so the switch is
# permanently off and there is no way to stop the tool.
#
# The rule, identical here and in `hooks/agent_route_actuator.sh`:
#
#     $JEV_HOME if it is set and names a directory,
#     otherwise the directory two levels above this file.
#
# Validation is `is_dir()` and nothing more, deliberately. A richer rule (look
# for config/tiers.json, look for hooks/) is a rule two implementations have to
# keep in step, and the failure it would catch is already handled downstream by
# fail-to-frontier plus the circuit breaker.
#
# `tests/test_jev_home.sh` runs both halves and asserts they print the same
# absolute path, under an env var and without one.


def resolve_jev_home(environ: dict[str, str] | None = None) -> tuple[Path, str]:
    """(home, which arm fired). The canonical JEV_HOME rule, in Python."""
    env = os.environ if environ is None else environ
    declared = env.get("JEV_HOME") or ""
    if declared:
        p = Path(declared)
        if p.is_dir():
            return p.resolve(), "env"
    return Path(__file__).resolve().parent.parent, "self"


JEV_HOME, JEV_HOME_SOURCE = resolve_jev_home()

# ROOT is JEV_HOME. Kept as a name because every path below and most of the
# repo already reads it, and because "the root of the jev install" is exactly
# what it has always meant -- it is only the derivation that changed.
ROOT = JEV_HOME


def jev_home_source() -> str:
    """Which arm of the rule produced JEV_HOME: "env" or "self"."""
    return JEV_HOME_SOURCE


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

# JEV-35 / W1. The static router's assignment ledger and circuit-breaker log,
# written by hooks/agent_route_actuator.sh. Under data/ for the same reason
# DROPS is: an assignment that cannot be joined to an outcome is attrition, and
# attrition has to outlive a log rotation. The ledger row is written BEFORE the
# spawn -- a ledger written afterwards is missing exactly when it matters most,
# which is when the task crashed. See src/assignment_ledger.py.
AGENT_ROUTE = DATA / "agent_route"
AGENT_ROUTE_ASSIGNMENTS = AGENT_ROUTE / "assignments"

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
    AGENT_ROUTE,
    AGENT_ROUTE_ASSIGNMENTS,
    LOGS,
    REPORTS,
]

SURFACES = ("pre_bash", "stop", "user_prompt", "post_edit", "agent_route")


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


# W2. The two switches, named, because "the switch" stopped being one thing the
# moment jev could be installed into a repo it does not live in.
#
#   GLOBAL         $JEV_HOME/.jev-disabled   -- stops jev everywhere at once.
#                  $HOME/.claude/jev-disabled -- machine-wide, honoured even if
#                  the install itself is unreachable. Read-only; never written.
#   PER-PROJECT    $CLAUDE_PROJECT_DIR/.jev-disabled -- an opt-out for ONE repo.
#
# When jev runs in its own repo the first and the third are the same file, which
# is why this distinction did not exist before and why it has to now.
GLOBAL_KILL_SWITCH = KILL_SWITCH
HOME_KILL_SWITCH = Path.home() / ".claude" / "jev-disabled"


def _switch_set(p: Path) -> bool:
    """The hooks' own fail-safe test: ANY entry at the path means OFF.

    `-e` or `-L`, never `-f`. A directory, a dangling symlink and an unreadable
    file all read as SET, because a switch whose state cannot be established is
    never given the benefit of the doubt.
    """
    return p.exists() or p.is_symlink()


def project_opt_out(project_dir: Path | str) -> Path:
    """The per-project opt-out path for a given project directory."""
    return Path(project_dir) / ".jev-disabled"


def routing_disabled(project_dir: Path | str | None = None) -> tuple[bool, str]:
    """(disabled, which switch). Mirrors the actuator's order exactly.

    The actuator tests the global switches first and the per-project opt-out
    second, so a report that claims to describe the hook has to test them in
    the same order or it will name the wrong file.
    """
    if _switch_set(GLOBAL_KILL_SWITCH):
        return True, f"global: {GLOBAL_KILL_SWITCH}"
    if _switch_set(HOME_KILL_SWITCH):
        return True, f"machine-wide: {HOME_KILL_SWITCH}"
    if project_dir is not None and _switch_set(project_opt_out(project_dir)):
        return True, f"per-project: {project_opt_out(project_dir)}"
    return False, "no switch is set"
