"""Three append-only streams, joined by keys. Nothing is ever updated in place.

    data/captures/YYYY-MM-DD.jsonl   immutable decision points
    data/states/<sha256>.json        content-addressed state blobs
    data/runs/YYYY-MM-DD.jsonl       one row per (decision_id, arm, question_set_id, attempt)
    data/labels/*.jsonl              Phase 2, appended by a human

`data/states/` holds the EXACT bytes sent to every arm. Redaction is a
publish-time export step (decision #9), not a capture-time one -- scrubbing the
stored copy would mean replay scored different bytes than the live run did, and
the state_sha256 equality assertion would either fail or, worse, silently
compare different inputs.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import paths

_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """Lexicographically sortable id. Timestamp prefix, random suffix."""
    ms = int(time.time() * 1000)
    ts = ""
    for _ in range(10):
        ms, rem = divmod(ms, 32)
        ts = _ULID_ALPHABET[rem] + ts
    rand = "".join(secrets.choice(_ULID_ALPHABET) for _ in range(16))
    return ts + rand


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _daily(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """Append one row and flush to disk.

    O_APPEND on a single line under the pipe buffer size is atomic enough that
    concurrent writers interleave cleanly rather than corrupting each other.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def append_capture(row: dict[str, Any]) -> None:
    append_jsonl(_daily(paths.CAPTURES), row)


def append_run(row: dict[str, Any]) -> None:
    append_jsonl(_daily(paths.RUNS), row)


def write_state(state: str, state_sha256: str) -> Path:
    """Content-addressed, write-once. Identical states deduplicate for free."""
    paths.STATES.mkdir(parents=True, exist_ok=True)
    target = paths.STATES / f"{state_sha256}.json"
    if target.exists():
        return target
    staged = paths.STATES / f".{state_sha256}.tmp"
    staged.write_text(json.dumps({"state": state}, ensure_ascii=False), encoding="utf-8")
    staged.replace(target)  # atomic within the same filesystem
    return target


def read_state(state_sha256: str) -> str:
    target = paths.STATES / f"{state_sha256}.json"
    if not target.exists():
        raise FileNotFoundError(f"no stored state for {state_sha256}")
    return json.loads(target.read_text(encoding="utf-8"))["state"]


def read_jsonl(directory: Path) -> Iterator[dict[str, Any]]:
    """Read every jsonl row in a directory, oldest file first."""
    if not directory.exists():
        return
    for f in sorted(directory.glob("*.jsonl")):
        for raw in f.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue


def captures() -> Iterator[dict[str, Any]]:
    return read_jsonl(paths.CAPTURES)


def runs() -> Iterator[dict[str, Any]]:
    return read_jsonl(paths.RUNS)


def labels() -> Iterator[dict[str, Any]]:
    return read_jsonl(paths.LABELS)
