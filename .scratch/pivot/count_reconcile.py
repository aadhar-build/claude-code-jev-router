"""Throwaway: reconcile the disputed delegated-task counts (7 / 33 / 42 / 120).

Run: python3 .scratch/pivot/count_reconcile.py
"""
import json
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
rows = [json.loads(l) for l in (ROOT / "data/baseline/sessions.jsonl").read_text().splitlines() if l.strip()]

print(f"A. sessions.jsonl -- {len(rows)} sessions, FULL window")
print(f"   sum(delegated_tasks)  = {sum(r['delegated_tasks'] for r in rows)}")
print(f"   sum(len(subagent_files)) = {sum(len(r['source']['subagent_files']) for r in rows)}")
print("   => counting rule: SUBAGENT TRANSCRIPT FILES on disk, one per delegated task")

types = collections.Counter()
for r in rows:
    v = r.get("delegated_task_agent_types")
    if isinstance(v, dict):
        types.update(v)
    elif isinstance(v, list):
        types.update(v)
tot = sum(types.values())
print(f"\n   delegated_task_agent_types, aggregated ({tot} total):")
for k, v in types.most_common():
    print(f"     {str(k):30s} {v:4d}  {v/tot:.1%}")

depths = collections.Counter()
for r in rows:
    v = r.get("delegated_task_spawn_depths")
    if isinstance(v, dict):
        depths.update(v)
    elif isinstance(v, list):
        depths.update(str(x) for x in v)
print(f"\n   spawn depths: {dict(depths)}")

routable = sum(v for k, v in types.items() if k in ("Explore", "Plan", "claude-code-guide"))
print(f"\n   routable by the W1 map (Explore+Plan+claude-code-guide) = {routable}/{tot} = {routable/tot:.1%}")
