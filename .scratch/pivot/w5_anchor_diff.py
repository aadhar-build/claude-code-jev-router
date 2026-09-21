"""JEV-59: how far the "before" numbers move, and which effect moved them.

Reproduces from the REPO ALONE -- no /tmp, no backup file. The pre-JEV-59 rows
are still in the committed stream and are identified by the thing the ticket
added: a row with no `costing_rule` was written under the withdrawn first-copy
rule. That is the same test `baseline.row_costing_rule()` applies.

Three effects are in play and they are kept apart, the way SPEC.md 11 kept
`frozen_rule_today` apart from `corrected`:

  (a) rule + pricing, isolated to the sessions whose transcript is
      byte-identical to the old reading;
  (b) sessions that also GREW -- not separable, reported as such;
  (c) the corrected whole-corpus totals.

Run from the repo root:  python3 .scratch/pivot/w5_anchor_diff.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import baseline as bl  # noqa: E402

rows = bl.stream_rows()
old_rows = [r for r in rows if "costing_rule" not in r]
new_rows = [r for r in rows if "costing_rule" in r]


def latest(subset):
    out = {}
    for r in subset:
        out[r["session_id"]] = r
    return out


old, new = latest(old_rows), latest(new_rows)
common = sorted(set(old) & set(new))
same_file = [i for i in common
             if old[i]["source"]["digest"] == new[i]["source"]["digest"]]
grew = [i for i in common if i not in same_file]

print(f"stream: {len(rows)} rows -- {len(old_rows)} pre-JEV-59, "
      f"{len(new_rows)} corrected")
print(f"sessions: {len(old)} old, {len(new)} new, {len(common)} in both "
      f"({len(same_file)} byte-identical, {len(grew)} grew)")

F = [("computed_cost_usd", lambda r: r["computed_cost_usd"]),
     ("delegated_cost_usd", lambda r: r["delegated_cost_usd"]),
     ("main_session_cost_usd", lambda r: r["main_session_cost_usd"]),
     ("delegated_tasks", lambda r: r["delegated_tasks"]),
     ("human_prompts", lambda r: r["human_prompts"]),
     ("unpriced_requests", lambda r: r.get("unpriced_requests", 0))]


def table(ids, title):
    print()
    print(f"=== {title} ({len(ids)} sessions) ===")
    for label, fn in F:
        o = round(sum(fn(old[i]) for i in ids), 6)
        n = round(sum(fn(new[i]) for i in ids), 6)
        mv = f"{(n - o) / o * 100:+.1f}%" if o else "n/a"
        print(f"  {label:<24} old {o:>13}   new {n:>13}   {mv}")


table(same_file, "(a) PURE RULE + PRICING -- transcript byte-identical")
table(grew, "(b) ALSO GREW -- rule + pricing + growth, NOT separable")

print()
print("=== (c) corrected whole-corpus totals (latest row per session) ===")
L = list(bl.latest_per_session().values())
for label, fn in F:
    print(f"  {label:<24} {round(sum(fn(r) for r in L), 6)}")
tasks = sum(r["delegated_tasks"] for r in L)
deleg = sum(r["delegated_cost_usd"] for r in L)
print(f"  {'cost per delegated task':<24} "
      f"{round(deleg / tasks, 4) if tasks else 'n/a'}")

print()
print("=== positive assertions ===")
zero = [r for r in new_rows if r["computed_cost_usd"] == 0.0]
print(f"  zero-cost corrected rows: {len(zero)}")
for r in zero:
    print(f"    {r['session_id'][:8]} assistant_lines={r['assistant_lines']} "
          f"models={r['models']} reported={r['reported_cost_usd']}")
print(f"  unpriced models: "
      f"{sorted({m for r in new_rows for m in r['unpriced_models']})}")
print(f"  coverage-hole requests: "
      f"{sum(r['unpriced_requests'] for r in new_rows)}")
