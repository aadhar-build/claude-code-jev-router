#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Spool depth, its high-water mark, and the backpressure-drop count (JEV-33).

Three numbers an operator needs to see BEFORE the spool hits the backpressure
cap, and that the writeup needs afterwards:

    depth       how many captures are waiting right now (ready + claimed)
    high-water  the deepest the spool has ever been in this window
    drops       how many captures the hook refused to write because the spool
                was already at the cap

The high-water mark is sampled by the worker on every claim, not once per poll
cycle: the depth peaks while the worker is mid-capture, and a 30s poll would
step straight over the peak it exists to catch.

`drops` is read, never written, here. It is a line count over the jsonl stream
that `hooks/capture.sh` appends to -- the hook is bash 3.2 with no jq, no
python and a 10ms budget, so its rows are printf'd by hand and this module
tolerates whatever it finds rather than assuming well-formed JSON.

Written as a single small JSON file rather than an append-only stream because a
high-water mark is a maximum, not a history: every past sample is implied by it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import paths
import pyversion

# JEV-44: this module has a __main__ and is invoked from
# run-collection.sh. The PEP-723 header above binds `uv run` only.
pyversion.require()


def _count(directory) -> int:
    try:
        return sum(1 for _ in directory.glob("*.json"))
    except OSError:
        return 0


def depth() -> tuple[int, int]:
    """(ready, claimed). Claimed files are still undrained work -- JEV-31 --
    so an operator watching only `ready/` would under-read the backlog."""
    return _count(paths.SPOOL_READY), _count(paths.SPOOL_CLAIMED)


def read() -> dict[str, Any]:
    try:
        return json.loads(paths.SPOOL_WATERMARK.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def sample() -> dict[str, Any]:
    """Record the current depth against the running maximum. Monotonic.

    Never raises: this runs inside the drain loop and a failure to record a
    statistic must not cost a capture.
    """
    ready, claimed = depth()
    total = ready + claimed
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        mark = read()
        if total > int(mark.get("max_total", -1)):
            mark.update({"max_total": total, "max_ready": ready,
                         "max_claimed": claimed, "max_at": now})
        mark.setdefault("first_sample_at", now)
        mark["last_sample_at"] = now
        mark["last_total"] = total
        mark["backpressure_cap"] = cap()
        paths.SPOOL_WATERMARK.parent.mkdir(parents=True, exist_ok=True)
        tmp = paths.SPOOL_WATERMARK.with_suffix(".tmp")
        tmp.write_text(json.dumps(mark, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, paths.SPOOL_WATERMARK)
        return mark
    except OSError:
        return {}


def cap() -> int:
    """The backpressure cap. Read from config so the reported number is the
    configured one -- note JEV-31b: capture.sh still hardcodes the literal, so
    this is the value an operator BELIEVES is in force. They agree today."""
    try:
        blob = json.loads((paths.CONFIG / "surfaces.json").read_text(encoding="utf-8"))
        return int(blob.get("spool_backpressure_max_files", 500))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 500


def drops() -> tuple[int, str | None]:
    """(count, last_iso8601). Counts lines across the drop stream."""
    count = 0
    last: str | None = None
    if not paths.DROPS.is_dir():
        return 0, None
    for f in sorted(paths.DROPS.glob("*.jsonl")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in text.splitlines():
            if not raw.strip():
                continue
            count += 1
            try:
                last = json.loads(raw).get("at", last)
            except json.JSONDecodeError:
                pass  # a half-written hook line is still a drop; count it
    return count, last


def report() -> str:
    ready, claimed = depth()
    mark = read()
    n_drops, last_drop = drops()
    limit = cap()
    lines = [
        f"spool ready   : {ready}",
        f"spool claimed : {claimed}   (undrained; JEV-31 -- reap before a restart)",
        f"spool depth   : {ready + claimed} / {limit} backpressure cap",
        "spool peak    : {} at {} (window from {})".format(
            mark.get("max_total", "unknown"),
            mark.get("max_at", "-"),
            mark.get("first_sample_at", "-"),
        ),
        f"dropped       : {n_drops}" + (f"   last {last_drop}" if last_drop else ""),
    ]
    if n_drops:
        lines.append("                ^ captures the hook refused on backpressure; "
                     "these are attrition and have no run row")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if "--sample" in sys.argv:
        sample()
    print(report())
