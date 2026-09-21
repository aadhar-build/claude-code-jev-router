#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""W2. `jev install` / `jev uninstall` -- opt-in per project, and removable.

    jev install   [DIR] {--dry-run|--yes}
    jev uninstall [DIR] {--dry-run|--yes}
    jev status    [DIR]

DIR defaults to the current directory. It is the repo you want jev's hooks to
run in; jev itself stays where it is (`$JEV_HOME`) and is never copied.

---------------------------------------------------------------------------
WHY PER-PROJECT, AND WHY NOTHING IS EVER WRITTEN TO ~/.claude/settings.json
---------------------------------------------------------------------------
Operator decision, 2026-09-21, and the audit found the reason. A global install
resolves every hook's root from whatever repo the session happens to be in. In
that shape the kill switch names a file that will never exist -- **the switch
is permanently off and there is no way to stop the tool** -- the rule table is
looked for in the wrong repo, and the stderr log never resolves, so the
failures are invisible too. `coldteadotai/abide`, from which this project
harvests substantially, installs itself that way. We take its code, not its
installer.

So: one target repo at a time, into `./.claude/settings.local.json`, which is
the project-scoped file that does not travel to a clone or a cloud session.

---------------------------------------------------------------------------
THE TEARDOWN GUARANTEE, AND HOW IT IS WEAKER THAN IT WAS
---------------------------------------------------------------------------
`teardown.sh` is byte-reversible because it never edits: it sets the switch and
then MOVES the whole settings file aside. Per-project install cannot always do
that, because the file may hold settings that are not ours -- other hooks,
`permissions`, `env`. Removing one key from somebody else's file is a
categorically weaker act than moving a file we own, and this module does not
pretend otherwise. It gets as close as it can, in this order:

  1. THE SWITCH FIRST, always. `uninstall` creates the per-project opt-out
     `<DIR>/.jev-disabled` before it touches the settings file, for the same
     reason `teardown.sh` does: the docs say direct edits to settings files are
     "normally picked up automatically by the file watcher", and "normally" is
     not a guarantee. The switch is the guaranteed path; the unregistration
     follows. The switch is LEFT IN PLACE and the `rm` is printed.
  2. A VERBATIM BACKUP before anything is written, both at install and at
     uninstall. Bytes, copied, never re-serialised.
  3. TIER A -- BYTE-REVERSIBLE. If the file, with our entries removed, is the
     same document as the one we backed up at install time, we do not edit at
     all: we restore the install-time backup BYTES and verify the sha256. This
     is the `teardown.sh` guarantee, intact.
  4. TIER B -- STRUCTURALLY VERIFIED, AND WEAKER. If the file changed after we
     installed (the user added a hook, edited `permissions`), tier A is not
     available. We then write the stripped document and verify it three ways
     against the file re-read from disk: every difference from the pre-uninstall
     file is one of our entries; nothing outside `hooks` moved; and re-applying
     `install` to the result reproduces the pre-uninstall document -- up to the
     order of the groups within one hook event, which is not a behaviour (Claude
     Code runs every matching group) and which `merge_entries` cannot
     reconstruct, since it always appends ours at the end. The order that IS
     checked exactly is the user's own groups relative to each other. Together
     those say nothing was lost rather than merely moved. If any of those fails
     we say so LOUDLY and name the verbatim backup.

Tier B cannot promise byte-identity of the user's own formatting, because
`install` re-serialises the file (`json.dumps(indent=2)`) the moment it merges
into it. That is stated in the output every time, and in docs/REVERSIBILITY.md.

---------------------------------------------------------------------------
"THE SWITCH IS OFF" IS NOT "THE TOOL IS QUIESCENT"
---------------------------------------------------------------------------
This repo has been bitten by the distinction (JEV-51: a kill switch that
stopped one writer and not another). Stated here so the two are never confused:

  switch set        the hook still SPAWNS on every Agent call and exits on line
                    one. Nothing is decided, nothing is written, the tool input
                    is untouched -- but a process is created per call.
  uninstalled       no process is created. That is quiescent, and only
                    `jev uninstall` (or removing the registration by hand) gets
                    there.

`teardown.sh` reaches quiescence for JEV_HOME's own repo only. It does not walk
foreign installs, and it does not know about them -- each one is removed with
`jev uninstall <that repo>`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths  # noqa: E402

REGISTRATION = paths.ROOT / "config" / "registration.json"

SETTINGS_REL = Path(".claude") / "settings.local.json"
RECORD_REL = Path(".claude") / "jev-install.json"

EX_OK = 0
EX_REFUSED = 1
EX_USAGE = 2


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def canonical(obj: Any) -> str:
    """The serialisation every comparison in this file is made about.

    The same one `src/hook_dispatch.py` uses, and for the same reason: the
    claim is about the set of keys and their values, never about key order.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def unique_path(path: Path) -> Path:
    """A path that does not exist, derived from `path`.

    Found by the test suite, which is the only reason it is here: the backup
    name carries a SECOND-resolution timestamp, and an install followed
    immediately by an uninstall lands in the same second. The second backup
    then overwrote the first, the install-time bytes were gone, and the
    uninstall silently fell back from byte-restore to the weaker structural
    edit -- a downgrade of the central guarantee, caused by a filename.
    """
    if not path.exists() and not path.is_symlink():
        return path
    for n in range(1, 1000):
        cand = path.with_name(f"{path.name}-{n}")
        if not cand.exists() and not cand.is_symlink():
            return cand
    raise Refused(f"cannot find an unused backup name next to {path}")


def load_registration(path: Path | None = None) -> dict:
    return json.loads((path or REGISTRATION).read_text())


def desired_entries(jev_home: Path, reg: dict | None = None) -> list[dict]:
    """What `install` writes: one handler record per entry, absolute-pathed.

    ABSOLUTE, not `$CLAUDE_PROJECT_DIR`-anchored, and that is deliberate. The
    in-repo registration is `$CLAUDE_PROJECT_DIR`-anchored because there the
    project IS jev. An install into another repo cannot be: the script does not
    live in that repo, and Claude Code does not promise to expand arbitrary
    environment variables in a hook command. The hook then resolves `$JEV_HOME`
    from its own path, so the runtime needs no environment variable either.
    """
    reg = reg or load_registration()
    out = []
    for e in reg["entries"]:
        script = (jev_home / e["script"]).resolve()
        out.append({
            "event": e["event"],
            "matcher": e["matcher"],
            "script": script,
            "rel": e["script"],
            "timeout": e.get("timeout", 10),
            "command": shlex.quote(str(script)),
        })
    return out


def read_record(record_path: Path) -> dict | None:
    """This repo's `.claude/jev-install.json`, or None. Never raises."""
    try:
        doc = json.loads(record_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def owned_commands(jev_home: Path | None = None, reg: dict | None = None,
                   record: dict | None = None) -> set[str]:
    """The EXACT command strings that are jev's, in this repo.

    W5, and this was a real defect. Ownership used to be `e["script"] in
    command` -- a SUBSTRING test. Somebody else's
    `/my/own/hooks/agent_route_actuator.sh --mine` on matcher `Write` matched
    it, and `jev install` deleted their handler out of their own settings file
    without saying a word. Silent data loss in a stranger's repo is the one
    failure category a tool people install may not have.

    So ownership is now exact and has exactly two sources, both of them
    absolute paths jev itself produced:

      1. what THIS install would write -- `desired_entries()`, anchored to
         `$JEV_HOME`;
      2. what an install into THIS repo actually wrote -- the `entries[]` of
         `.claude/jev-install.json`. This is the only thing that can still
         recognise an entry after `$JEV_HOME` has moved, and it is repo-local,
         so it cannot claim ownership of anything in anybody else's tree.

    A handler that merely *mentions* one of our script names is not ours, is
    left alone, and `install` says so out loud (see `lookalikes`).
    """
    jev_home = jev_home or paths.ROOT
    reg = reg or load_registration()
    out: set[str] = set()
    for e in desired_entries(jev_home, reg):
        out.add(e["command"])
        # The unquoted form too: `shlex.quote` is a no-op for an ordinary path,
        # but a path with a space in it is quoted here and a user who retyped
        # the line by hand may not have quoted it. Still an EXACT path match.
        out.add(str(e["script"]))
    for e in (record or {}).get("entries") or []:
        c = e.get("command")
        if isinstance(c, str) and c.strip():
            out.add(c.strip())
    return out


def is_ours(command: str, owned: set[str] | None = None) -> bool:
    """Is this registered handler one of jev's? EXACT match, never substring.

    Identified by the absolute script path jev wrote, not by a marker key
    inside the `hooks` array: Claude Code parses that array, an unknown key
    there is not ours to add, and a marker the harness might strip is a marker
    that leaves an entry we can no longer identify at uninstall time.

    `owned` comes from `owned_commands()`. Passing it in matters: it is the
    only way the set can include this repo's install record.
    """
    owned = owned_commands() if owned is None else owned
    return (command or "").strip() in owned


def lookalikes(settings: dict, owned: set[str], reg: dict | None = None) -> list[dict]:
    """Handlers that NAME one of our scripts but are not ours.

    The exact population the old substring test would have deleted. We leave
    them alone and print them, because "we noticed and did nothing" is the only
    honest thing to say about somebody else's hook that shares our filename.
    """
    reg = reg or load_registration()
    names = {Path(e["script"]).name for e in reg["entries"]}
    out = []
    for event, groups in (settings.get("hooks") or {}).items():
        for g in groups or []:
            if not isinstance(g, dict):
                continue
            for h in (g.get("hooks") or []):
                if not isinstance(h, dict):
                    continue
                c = (h.get("command") or "")
                if c.strip() in owned:
                    continue
                if any(n in c for n in names):
                    out.append({"event": event, "matcher": g.get("matcher"),
                                "command": c})
    return out


def split_hooks(settings: dict, owned: set[str] | None = None) -> tuple[dict, list[dict]]:
    """(settings with every jev handler removed, the handlers removed).

    Groups and events that become empty are pruned, and so is `hooks` itself --
    an install into a file that had no `hooks` key must be able to leave it with
    no `hooks` key, or tier A is unreachable for the commonest case of all.
    """
    owned = owned_commands() if owned is None else owned
    out = json.loads(json.dumps(settings))  # deep copy, no aliasing surprises
    removed: list[dict] = []
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out, removed

    for event in list(hooks.keys()):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                kept_groups.append(group)
                continue
            kept = []
            for h in handlers:
                if isinstance(h, dict) and is_ours(h.get("command") or "", owned):
                    removed.append({"event": event, "matcher": group.get("matcher"),
                                    "handler": h})
                else:
                    kept.append(h)
            if not kept:
                # The whole group was ours. Drop it -- but only if it was ours
                # entirely; a group we merely shared would keep its other
                # handlers above and survive here.
                if handlers:
                    continue
            new_group = dict(group)
            new_group["hooks"] = kept
            kept_groups.append(new_group)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        out.pop("hooks", None)
    return out, removed


def merge_entries(settings: dict, entries: list[dict]) -> dict:
    """Add jev's handlers to a settings document, touching nothing else.

    OUR OWN GROUP, ALWAYS. If the target already has a `PreToolUse` group on
    matcher `Agent`, we do not join it: appending into somebody else's group
    means uninstall has to reason about whose group it now is, and a group we
    created is a group we can remove whole. Claude Code runs every matching
    group, so a separate one is behaviourally identical and structurally
    reversible.
    """
    out = json.loads(json.dumps(settings))
    hooks = out.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is present and is not an object')
    for e in entries:
        groups = hooks.setdefault(e["event"], [])
        if not isinstance(groups, list):
            raise ValueError(f'"hooks.{e["event"]}" is present and is not an array')
        groups.append({
            "matcher": e["matcher"],
            "hooks": [{"type": "command", "command": e["command"],
                       "timeout": e["timeout"]}],
        })
    return out


def render(settings: dict) -> bytes:
    """The bytes `install` writes. Pretty, stable, newline-terminated."""
    return (json.dumps(settings, indent=2) + "\n").encode("utf-8")


def write_atomically(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + f".jev-tmp-{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def diff_paths(a: Any, b: Any, prefix: str = "") -> list[str]:
    """Every location at which two JSON documents differ. Independent of how
    either was produced -- which is the whole point: a verification computed by
    the same code that made the change verifies nothing."""
    if type(a) is not type(b):
        return [prefix or "$"]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{prefix}.{k}")
            else:
                out += diff_paths(a[k], b[k], f"{prefix}.{k}")
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [prefix or "$"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, f"{prefix}[{i}]")
        return out
    return [] if a == b else [prefix or "$"]


# ---------------------------------------------------------------------------
# the switch -- always first
# ---------------------------------------------------------------------------


def switch_set(p: Path) -> bool:
    """ANY entry at the path means OFF. The hooks' own test, verbatim."""
    return p.exists() or p.is_symlink()


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


class Refused(Exception):
    """A refusal. Nothing has been written when this is raised."""


def _target(dirpath: Path) -> tuple[Path, Path, Path]:
    target = Path(dirpath).expanduser()
    if not target.exists():
        raise Refused(f"{target} does not exist")
    if not target.is_dir():
        raise Refused(f"{target} is not a directory")
    target = target.resolve()
    return target, target / SETTINGS_REL, target / RECORD_REL


def _read_settings(settings_path: Path) -> tuple[bytes | None, dict]:
    """(original bytes or None, parsed document). Refuses rather than guessing."""
    if settings_path.is_symlink():
        raise Refused(
            f"{settings_path} is a symlink. Refusing: following it would write "
            "through to a file the user did not point us at, and moving it "
            "aside would break whatever else reads it.")
    if not settings_path.exists():
        return None, {}
    raw = settings_path.read_bytes()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refused(
            f"{settings_path} is not valid JSON ({exc}). Refusing, and nothing "
            "has been changed. Fix or move the file, then run this again -- "
            "merging into a file we cannot parse is how an unrelated setting "
            "gets silently dropped.") from None
    if not isinstance(doc, dict):
        raise Refused(f"{settings_path} is valid JSON but not an object")
    if "hooks" in doc and not isinstance(doc["hooks"], dict):
        raise Refused(f'{settings_path} has a "hooks" key that is not an object')
    return raw, doc


def install(dirpath: Path, apply: bool, out=print) -> int:
    jev_home = paths.ROOT
    reg = load_registration()
    entries = desired_entries(jev_home, reg)

    for e in entries:
        if not e["script"].is_file():
            raise Refused(f"{e['script']} does not exist -- refusing to register "
                          "a hook that cannot run")
        if not os.access(e["script"], os.X_OK):
            raise Refused(f"{e['script']} is not executable -- refusing to "
                          "register a hook that cannot run")

    target, settings_path, record_path = _target(dirpath)
    original, doc = _read_settings(settings_path)

    # The record is read BEFORE the strip, because it is half of what ownership
    # means: an entry written by an install whose $JEV_HOME has since moved is
    # recognisable from the record and from nothing else.
    prior_record = read_record(record_path)
    owned = owned_commands(jev_home, reg, prior_record)
    stripped, existing = split_hooks(doc, owned)
    want = merge_entries(stripped, entries)

    out("")
    out(f"jev install — {target}")
    out(f"  jev home    {jev_home}")
    out(f"  settings    {settings_path}"
        f"{'' if original is not None else '  (does not exist yet)'}")
    _warn_if_worktree(jev_home, out)
    out("")

    # Loud, always, and before anything is written: a handler that names one of
    # our scripts but is not this install's is somebody else's, and the old
    # substring ownership test would have deleted it in silence.
    near = lookalikes(doc, owned, reg)
    for n in near:
        out(f"  NOT OURS    {n['event']} / matcher {n['matcher']}")
        out(f"              {n['command']}")
        out("              names one of jev's scripts but is not an entry this")
        out("              install wrote. LEFT EXACTLY AS IT IS — not replaced,")
        out("              not removed. If it is yours, nothing to do.")
    if near:
        out("")

    if existing and canonical(want) == canonical(doc):
        out(f"  already installed — {len(existing)} jev entry(ies), exactly as we "
            "would write them.")
        out("  Nothing to do. `jev install` is idempotent.")
        _report_switches(target, jev_home, out)
        return EX_OK

    if existing:
        # One line per entry, not a count. A removal nobody can name is a
        # removal nobody can check.
        out(f"  REPLACING   {len(existing)} jev entry(ies) already registered here. "
            "Each is removed and rewritten:")
        for r in existing:
            out(f"              {r['event']} / matcher {r['matcher']}")
            out(f"              {r['handler'].get('command')}")
        out("              (verbatim backup below; nothing outside these lines "
            "is touched)")

    if apply and not os.access(target / ".claude" if (target / ".claude").exists()
                               else target, os.W_OK):
        raise Refused(f"{target} is not writable")

    if not apply:
        out("  DRY RUN. Nothing below has been done.")
        out("")
        for e in entries:
            out(f"  would register  {e['event']} / matcher {e['matcher']}")
            out(f"                  {e['command']}")
        if original is not None:
            out(f"  would back up   {settings_path}")
            out(f"                  verbatim, then rewrite it with our entries merged in")
            out("  NOTE            the merge re-serialises the file (2-space JSON).")
            out("                  Your keys and values survive exactly; your")
            out("                  FORMATTING does not. The verbatim backup is what")
            out("                  makes that reversible.")
        else:
            out("  would create    the settings file (uninstall then removes it again)")
        out("")
        out("  Run again with --yes to apply.")
        _report_switches(target, jev_home, out)
        return EX_OK

    (target / ".claude").mkdir(parents=True, exist_ok=True)

    backup_path = None
    if original is not None:
        backup_path = unique_path(settings_path.with_name(
            settings_path.name + f".jev-backup-{stamp()}"))
        # Bytes. Copied, never re-serialised -- this is the artefact the whole
        # reversibility claim rests on.
        backup_path.write_bytes(original)
        if backup_path.read_bytes() != original:
            raise Refused("the verbatim backup did not read back identical -- "
                          "refusing to touch the settings file")

    write_atomically(settings_path, render(want))

    record = {
        "schema": "jev-install-v1",
        "installed_at": stamp(),
        "jev_home": str(jev_home),
        "settings": str(settings_path),
        "original_existed": original is not None,
        "original_sha256": sha256_bytes(original) if original is not None else None,
        "backup": str(backup_path) if backup_path else None,
        "registration_version": reg.get("version"),
        "entries": [{"event": e["event"], "matcher": e["matcher"],
                     "command": e["command"]} for e in entries],
    }
    write_atomically(record_path, (json.dumps(record, indent=2) + "\n").encode())

    for e in entries:
        out(f"  registered  {e['event']} / matcher {e['matcher']}")
        out(f"              {e['command']}")
    if backup_path:
        out(f"  backed up   {backup_path}")
        out("              verbatim, byte for byte, before anything was written")
        out("  NOTE        the merge re-serialised the file as 2-space JSON. Every")
        out("              key and value you had is preserved exactly; the original")
        out("              FORMATTING is in the backup above, and `jev uninstall`")
        out("              restores those bytes when nothing else has changed.")
    else:
        out("  created     the settings file (there was none; uninstall removes it)")
    out(f"  record      {record_path}")
    out("")
    out("  To remove:")
    out(f"    jev uninstall {target} --yes")
    _report_switches(target, jev_home, out)
    return EX_OK


def _warn_if_worktree(jev_home: Path, out=print) -> None:
    """A git WORKTREE has `.git` as a FILE, not a directory.

    The registration names `$JEV_HOME/hooks/...` verbatim and absolutely -- it
    has to, because a foreign repo cannot anchor on a `$CLAUDE_PROJECT_DIR` the
    script does not live in. So installing from a worktree pins a path that
    dangles the day the worktree is removed. A dangling hook command is inert,
    which is fail-safe, but it is also silent: the hook simply stops existing
    and nothing says so. Warn at the only moment anybody is looking.
    """
    if not (jev_home / ".git").is_file():
        return
    out("  WARNING     this jev home looks like a git WORKTREE — its `.git` is a")
    out("              file, not a directory. The command registered below names")
    out(f"              {jev_home}")
    out("              absolutely. Remove the worktree and that path dangles:")
    out("              the hook silently stops existing (inert, but silent), and")
    out("              `jev uninstall` can no longer find its own script either.")
    out("              Prefer installing from a stable checkout; if you keep this")
    out("              one, uninstall BEFORE you remove the worktree.")


def _report_switches(target: Path, jev_home: Path, out=print) -> None:
    out("")
    out("  The two switches — both fail-safe, ANY entry at the path means OFF:")
    g = jev_home / ".jev-disabled"
    p = target / ".jev-disabled"
    out(f"    global        touch {g}")
    out(f"                  {'SET — jev is off everywhere' if switch_set(g) else 'not set'}")
    out(f"    this project  touch {p}")
    out(f"                  {'SET — jev is off in this repo' if switch_set(p) else 'not set'}")
    out("    machine-wide  touch ~/.claude/jev-disabled")
    out("")
    out("  A switch stops the hook DECIDING. It does not stop it being spawned:")
    out("  a process is still created per Agent call, exits on line one, writes")
    out("  nothing and leaves the tool input untouched. `jev uninstall` is what")
    out("  makes it quiescent.")


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------


def uninstall(dirpath: Path, apply: bool, out=print) -> int:
    jev_home = paths.ROOT
    reg = load_registration()
    target, settings_path, record_path = _target(dirpath)

    out("")
    out(f"jev uninstall — {target}")
    out("")

    original, doc = _read_settings(settings_path)

    # The record first: it is half of what ownership means (see
    # `owned_commands`), so it has to be in hand before anything is stripped.
    record = read_record(record_path)
    owned = owned_commands(jev_home, reg, record)
    stripped, removed = split_hooks(doc, owned)

    near = lookalikes(doc, owned, reg)
    for n in near:
        out(f"  NOT OURS    {n['event']} / matcher {n['matcher']}")
        out(f"              {n['command']}")
        out("              names one of jev's scripts but is not an entry we")
        out("              wrote. LEFT IN PLACE.")

    if not removed:
        out("  hooks       no jev entries registered here — nothing to unregister")
        if original is None:
            out(f"  settings    {settings_path} does not exist")
        if record_path.exists() and apply:
            record_path.unlink()
            out(f"  record      removed stale {record_path}")
        out("")
        out("  `jev uninstall` is idempotent. Nothing was changed.")
        return EX_OK

    if not apply:
        out("  DRY RUN. Nothing below has been done.")
        out("")
        out(f"  would set     {target / '.jev-disabled'}   (the switch, FIRST)")
        for r in removed:
            out(f"  would remove  {r['event']} / matcher {r['matcher']}")
            out(f"                {r['handler'].get('command')}")
        out(f"  would back up {settings_path} verbatim first")
        tier = _tier_forecast(record, stripped, settings_path)
        out(f"  reversal      {tier}")
        out("")
        out("  Run again with --yes to apply.")
        return EX_OK

    # --- 1. THE SWITCH, FIRST ------------------------------------------------
    # Before the settings file is touched, for the reason teardown.sh gives:
    # unregistration relies on a file watcher the docs describe as picking
    # changes up "normally", and "normally" is not a guarantee. The switch is
    # the guaranteed path, it takes effect at the next hook invocation in a
    # session that is already running, and it is left in place afterwards.
    switch = target / ".jev-disabled"
    switch_was_set = switch_set(switch)
    if not switch_was_set:
        try:
            switch.write_bytes(b"")
        except OSError as exc:
            out(f"  switch      COULD NOT CREATE {switch} ({exc})")
            out("              Refusing to unregister: the guaranteed stop is not")
            out("              available, so the only remaining stop would be a")
            out("              file-watcher we do not control.")
            return EX_REFUSED
        out(f"  switch      created {switch} — every jev hook in this repo now exits")
        out("              on line one, at the next invocation, no restart")
    else:
        out(f"  switch      already set ({switch})")

    # --- 2. the verbatim backup ---------------------------------------------
    pre = settings_path.read_bytes()
    # A DIFFERENT prefix from install's backup, not just a different timestamp:
    # these two are different artefacts (the file before jev ever touched it,
    # and the file as uninstall found it) and one must never overwrite the other.
    backup = unique_path(settings_path.with_name(
        settings_path.name + f".jev-preuninstall-{stamp()}"))
    backup.write_bytes(pre)
    if backup.read_bytes() != pre:
        out("  backup      THE VERBATIM BACKUP DID NOT READ BACK IDENTICAL.")
        out("              Refusing to edit the settings file. The switch above is")
        out("              set, so nothing is deciding anything; fix the disk and")
        out("              run this again.")
        return EX_REFUSED
    out(f"  backed up   {backup}")

    # --- 3. tier A: restore install-time bytes, if that IS the answer --------
    tier_a = (record is not None
              and record.get("settings") == str(settings_path)
              and _tier_a_available(record, stripped))

    if tier_a and not record.get("original_existed"):
        settings_path.unlink()
        if settings_path.exists():
            out("  hooks       FAILED to remove the settings file")
            return EX_REFUSED
        out("  hooks       unregistered by REMOVING the settings file — jev created")
        out("              it and jev held the only entries in it")
        out("  reversal    BYTE-REVERSIBLE: there is nothing left to be identical to")
        _finish(record_path, backup, switch, switch_was_set, out)
        return EX_OK

    if tier_a:
        src = Path(record["backup"])
        data = src.read_bytes()
        write_atomically(settings_path, data)
        got = sha256_bytes(settings_path.read_bytes())
        if got != record["original_sha256"]:
            out("  hooks       RESTORE DID NOT REPRODUCE THE ORIGINAL BYTES")
            out(f"              expected sha256 {record['original_sha256']}")
            out(f"              got            {got}")
            out(f"              your file as it was a moment ago: {backup}")
            return EX_REFUSED
        out("  hooks       unregistered by RESTORING the install-time bytes — not")
        out("              by editing. The file is byte-for-byte what it was before")
        out("              `jev install` ever ran.")
        out(f"  reversal    BYTE-REVERSIBLE (sha256 {got[:16]}… verified)")
        _finish(record_path, backup, switch, switch_was_set, out)
        return EX_OK

    # --- 4. tier B: edit, then verify three ways ----------------------------
    write_atomically(settings_path, render(stripped))
    after_raw = settings_path.read_bytes()
    try:
        after = json.loads(after_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        out(f"  hooks       WROTE A FILE THAT DOES NOT PARSE ({exc})")
        out(f"              restoring {backup}")
        write_atomically(settings_path, pre)
        return EX_REFUSED

    problems = verify_removal(json.loads(pre.decode("utf-8")), after, reg,
                              jev_home=jev_home, record=record)
    if problems:
        out("  VERIFY      THE REST OF THE FILE IS NOT WHAT IT WAS.")
        for p in problems:
            out(f"              {p}")
        out(f"              Restoring your file from {backup} and stopping.")
        write_atomically(settings_path, pre)
        out("              The switch is set, so nothing is deciding anything.")
        out("              Remove the entries by hand, or report this.")
        return EX_REFUSED

    for r in removed:
        out(f"  removed     {r['event']} / matcher {r['matcher']}")
    out("  verified    every difference from the file as we found it is one of our")
    out("              entries; nothing outside \"hooks\" moved; your own hook groups")
    out("              are still in the order you had them; and re-applying")
    out("              `install` to the result reproduces the file — up to the order")
    out("              of the groups inside one event, which is not a behaviour")
    out("              (every matching group runs) and which we cannot reconstruct,")
    out("              because install always appends ours last. So nothing was lost")
    out("              rather than merely moved.")
    out("  reversal    STRUCTURALLY VERIFIED, WHICH IS WEAKER THAN BYTE-IDENTICAL.")
    out("              This file changed after `jev install` ran, so the")
    out("              install-time bytes are no longer the right answer and we")
    out("              had to edit. Your keys and values are intact and checked;")
    out("              your ORIGINAL FORMATTING is not restored — 2-space JSON is.")
    out(f"              The bytes as we found them: {backup}")
    _finish(record_path, backup, switch, switch_was_set, out)
    return EX_OK


def _tier_a_available(record: dict, stripped: dict) -> bool:
    """Is restoring the install-time bytes the SAME ACT as removing our entries?

    Only if the document we would be left with is the document we backed up.
    Anything else and restoring would silently revert the user's own edits --
    a far worse failure than the weaker tier B guarantee.
    """
    if not record.get("original_existed"):
        return canonical(stripped) in (canonical({}),)
    b = record.get("backup")
    if not b or not Path(b).is_file():
        return False
    try:
        was = json.loads(Path(b).read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if sha256_bytes(Path(b).read_bytes()) != record.get("original_sha256"):
        return False
    return canonical(stripped) == canonical(was)


def _tier_forecast(record, stripped, settings_path) -> str:
    if record is not None and record.get("settings") == str(settings_path) \
            and _tier_a_available(record, stripped):
        return ("BYTE-REVERSIBLE — the install-time bytes would be restored "
                "verbatim, not edited")
    return ("STRUCTURALLY VERIFIED (weaker) — this file has changed since "
            "install, so our entries would be edited out and the result checked")


def _is_subsequence(small: list[str], big: list[str]) -> bool:
    """Is `small` `big` with zero or more elements deleted, order preserved?"""
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


def _groups_sorted(doc: dict) -> dict:
    """`doc` with the GROUP LIST of each hook event put in canonical order.

    W5, and this is the fix for a defect that aborted the single most likely
    uninstall there is. Within one event Claude Code runs EVERY matching group
    -- the order of the groups in that array is not a behaviour, it is a record
    of who appended last. `merge_entries` always appends jev's group at the END,
    so the moment the user added a `PreToolUse` hook of their own AFTER
    installing, the original order stopped being reconstructable and the
    POSITIONAL comparison this check used to make fired on a removal that was
    entirely correct. Uninstall then restored the backup and stopped -- leaving
    jev REGISTERED, which is the one outcome uninstall exists to prevent.

    So check 3b is order-insensitive exactly where order does not matter. The
    order that DOES matter -- the user's own groups relative to each other, and
    the handlers inside any one group -- is held by check 3a, which compares
    `after` against `before` directly and so never reconstructs anything.
    """
    out = json.loads(json.dumps(doc))
    hooks = out.get("hooks")
    if isinstance(hooks, dict):
        for event, groups in list(hooks.items()):
            if isinstance(groups, list):
                hooks[event] = sorted(groups, key=canonical)
    return out


def _describe_group(g: Any) -> str:
    if not isinstance(g, dict):
        return canonical(g)[:80]
    handlers = g.get("hooks") or []
    first = ""
    if handlers and isinstance(handlers[0], dict):
        first = str(handlers[0].get("command") or "")
    return (f"matcher {g.get('matcher')!r}, {len(handlers)} handler(s), "
            f"first command {first[:60]!r}")


def _group_level_diff(before: dict, again: dict) -> list[str]:
    """Where `before` and `again` differ, described in GROUPS, not in indices.

    `diff_paths` over two group-sorted documents would report indices into a
    sorted list, which mean nothing to whoever is reading the refusal.
    """
    out: list[str] = []
    b_rest = {k: v for k, v in before.items() if k != "hooks"}
    a_rest = {k: v for k, v in again.items() if k != "hooks"}
    for loc in diff_paths(b_rest, a_rest):
        out.append(f"outside \"hooks\", at {loc or '$'}")
    b_hooks = before.get("hooks") or {}
    a_hooks = again.get("hooks") or {}
    for event in sorted(set(b_hooks) | set(a_hooks)):
        b_groups = [canonical(g) for g in (b_hooks.get(event) or [])]
        a_groups = [canonical(g) for g in (a_hooks.get(event) or [])]
        for g in b_groups:
            if b_groups.count(g) > a_groups.count(g):
                out.append(f"hooks.{event}: a group we found is LOST — "
                           f"{_describe_group(json.loads(g))}")
        for g in a_groups:
            if a_groups.count(g) > b_groups.count(g):
                out.append(f"hooks.{event}: re-install produces a group that was "
                           f"not there — {_describe_group(json.loads(g))}")
    return list(dict.fromkeys(out))


def installer_triples(reg: dict | None = None, jev_home: Path | None = None,
                      record: dict | None = None) -> set[str]:
    """Every (event, matcher, command) that `install` has written or would write.

    W5. THIS IS WHERE THE SELF-REFERENCE IS BROKEN. Check 2 used to ask
    `is_ours()` -- the very predicate `split_hooks` had just used to decide what
    to remove -- whether the things `split_hooks` removed were ours. Such a
    check can only ever agree with the stripper, and it agreed most loudly at
    exactly the point the stripper was wrong: a foreign handler whose command
    merely CONTAINED one of our script names was removed by the predicate and
    then blessed by the same predicate.

    So this set is CONSTRUCTED rather than RECOGNISED. It is what the installer
    emits -- `config/registration.json` under this `$JEV_HOME`, plus the entries
    this repo's own install record says were actually written. A handler that
    disappeared and is not in this set is reported, whatever any ownership
    predicate happens to think of it.
    """
    reg = reg or load_registration()
    out: set[str] = set()
    for e in desired_entries(jev_home or paths.ROOT, reg):
        out.add(canonical([e["event"], e["matcher"], e["command"]]))
        out.add(canonical([e["event"], e["matcher"], str(e["script"])]))
    # Every record entry, unfiltered -- the record IS what the installer wrote,
    # by definition, and `owned_commands` trusts it on exactly those terms. A
    # filter here and not there would mean an entry written under an older
    # registration (a matcher that has since changed, say) got stripped as ours
    # and then reported as NOT ours, and uninstall would refuse for no reason.
    for e in (record or {}).get("entries") or []:
        ev, m, c = e.get("event"), e.get("matcher"), e.get("command")
        if isinstance(c, str) and c.strip():
            out.add(canonical([ev, m, c.strip()]))
    return out


def verify_removal(before: dict, after: dict, reg: dict | None = None,
                   jev_home: Path | None = None,
                   record: dict | None = None) -> list[str]:
    """Three independent checks that we removed ours and only ours.

    Independent is the operative word, and it is meant twice: these are
    computed from the file RE-READ FROM DISK rather than from the document we
    wrote, and check 2 asks what the INSTALLER writes rather than what the
    REMOVER recognises, so a mistake in the ownership predicate cannot be
    ratified by the ownership predicate.
    """
    reg = reg or load_registration()
    jev_home = jev_home or paths.ROOT
    problems: list[str] = []

    # 1. Nothing outside "hooks" moved.
    b_rest = {k: v for k, v in before.items() if k != "hooks"}
    a_rest = {k: v for k, v in after.items() if k != "hooks"}
    for loc in diff_paths(b_rest, a_rest):
        problems.append(f"changed outside \"hooks\": {loc or '$'}")

    # 2. Every handler that disappeared is one the INSTALLER WROTE, and no
    #    handler appeared -- compared as a multiset, so a handler that moved
    #    between groups is caught as well as one that vanished.
    def handlers(doc):
        out = []
        for event, groups in (doc.get("hooks") or {}).items():
            for g in groups or []:
                if not isinstance(g, dict):
                    continue
                for h in (g.get("hooks") or []):
                    out.append(canonical({"event": event,
                                          "matcher": g.get("matcher"),
                                          "handler": h}))
        return out

    written = installer_triples(reg, jev_home, record)
    b_h, a_h = handlers(before), handlers(after)
    for h in a_h:
        if h not in b_h:
            problems.append(f"a handler APPEARED that was not there before: {h[:120]}")
    for h in b_h:
        gone = b_h.count(h) - a_h.count(h)
        if gone <= 0:
            continue
        rec = json.loads(h)
        handler = rec["handler"] if isinstance(rec["handler"], dict) else {}
        triple = canonical([rec["event"], rec["matcher"],
                            (handler.get("command") or "").strip()])
        if triple not in written:
            problems.append(f"a handler that is NOT ours was removed: {h[:120]}")

    # 3a. The groups that SURVIVED are the groups we found, in the order we
    #     found them -- a subsequence, exactly. Nothing is reconstructed here,
    #     so it holds wherever our own group happened to sit, and it catches a
    #     group that appeared, was reordered, was rewritten, or moved between
    #     events.
    b_hooks = before.get("hooks") or {}
    a_hooks = after.get("hooks") or {}
    for event in sorted(set(a_hooks) | set(b_hooks)):
        a_groups = [canonical(g) for g in (a_hooks.get(event) or [])]
        b_groups = [canonical(g) for g in (b_hooks.get(event) or [])]
        if not _is_subsequence(a_groups, b_groups):
            problems.append(
                f"hooks.{event}: the surviving groups are not the groups we "
                f"found, in the order we found them — something was added, "
                f"reordered or rewritten rather than merely removed")

    # 3b. Re-applying install to the result reproduces the file we found, so
    #     nothing was LOST rather than merely removed -- a sibling key on our
    #     group, a matcher someone had edited, somebody else's whole group.
    #     Compared with each event's groups in canonical order: see
    #     `_groups_sorted` for why a positional comparison here was a defect,
    #     and why 3a is what carries the order claim.
    try:
        again = merge_entries(after, desired_entries(jev_home, reg))
    except ValueError as exc:
        problems.append(f"the result cannot be re-installed into: {exc}")
        return problems
    if canonical(_groups_sorted(again)) != canonical(_groups_sorted(before)):
        for loc in _group_level_diff(before, again)[:6]:
            problems.append(f"re-install does not reproduce the original: {loc}")
    return problems


def _finish(record_path: Path, backup: Path, switch: Path,
            switch_was_set: bool, out=print) -> None:
    if record_path.exists():
        record_path.unlink()
        out(f"  record      removed {record_path}")
    out("")
    out("  jev is now QUIESCENT in this repo: no hook is registered, so no jev")
    out("  process is spawned at all. That is a stronger statement than \"the")
    out("  switch is set\", and it is the one you wanted.")
    out("")
    out("  What this does NOT undo:")
    out("    - work already produced by a routed model. No flag reverses that.")
    out("    - jev itself, which is untouched and still installed elsewhere if")
    out("      you put it there. `jev uninstall` is per repo, one at a time.")
    out("    - anything outside this repo. Nothing was ever written to")
    out("      ~/.claude/settings.json.")
    out("")
    out("  Left behind on purpose:")
    if not switch_was_set:
        out(f"    {switch}")
        out("      the switch, set BEFORE the unregistration and deliberately not")
        out("      cleaned up: it is the guaranteed stop, and removing it in the")
        out("      same breath would undo the one thing that does not depend on a")
        out("      file watcher. Remove it when you are satisfied:")
        out(f"        rm '{switch}'")
    out(f"    {backup}")
    out("      your settings file exactly as this command found it.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def status(dirpath: Path, out=print) -> int:
    jev_home = paths.ROOT
    reg = load_registration()
    target, settings_path, record_path = _target(dirpath)
    out("")
    out(f"jev status — {target}")
    out(f"  jev home    {jev_home}  (resolved from ${'JEV_HOME' if paths.jev_home_source() == 'env' else '0 — this file'})")
    if not settings_path.exists():
        out("  hooks       not installed here (no .claude/settings.local.json)")
    else:
        try:
            _, doc = _read_settings(settings_path)
        except Refused as exc:
            out(f"  hooks       UNREADABLE: {exc}")
            return EX_REFUSED
        _, ours = split_hooks(doc, owned_commands(jev_home, reg,
                                                  read_record(record_path)))
        total = len(load_registration()["entries"])
        if ours:
            out(f"  hooks       INSTALLED — {len(ours)} of jev's {total} entry(ies) registered")
            for r in ours:
                out(f"              {r['event']} / {r['matcher']}")
        else:
            out("  hooks       not installed here (settings file exists, no jev entries)")
    if record_path.exists():
        out(f"  record      {record_path}")
    _report_switches(target, jev_home, out)
    return EX_OK


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jev", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["install", "uninstall", "status"])
    ap.add_argument("dir", nargs="?", default=".")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", "-y", action="store_true")
    args = ap.parse_args(argv)

    if args.command != "status" and not (args.dry_run or args.yes):
        # teardown.sh's rule, and for teardown.sh's reason: a change that can
        # happen by accident -- a stray test, a tab-complete, an agent being
        # helpful -- is its own kind of hazard.
        print(f"usage: jev {args.command} [DIR] {{--dry-run|--yes}}", file=sys.stderr)
        print("  --dry-run  print what would change and change nothing", file=sys.stderr)
        print(f"  --yes      actually {args.command}", file=sys.stderr)
        return EX_USAGE
    if args.dry_run and args.yes:
        print("usage: --dry-run and --yes are mutually exclusive", file=sys.stderr)
        return EX_USAGE

    try:
        if args.command == "status":
            return status(Path(args.dir))
        if args.command == "install":
            return install(Path(args.dir), apply=args.yes)
        return uninstall(Path(args.dir), apply=args.yes)
    except Refused as exc:
        print("")
        print(f"jev {args.command}: REFUSED")
        print(f"  {exc}")
        print("  Nothing has been changed.")
        return EX_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
