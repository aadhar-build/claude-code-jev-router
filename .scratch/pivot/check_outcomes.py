"""One-off read-only probe: does subagent_outcomes work against real transcripts?"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import subagent_outcomes as so  # noqa: E402

session = (Path.home() / ".claude/projects/-Users-aadharagarwal-projects-JEV-experiments"
           / "4ba49645-fb8d-4fb2-b496-c274f6ed1490.jsonl")
blocking = so.blocking_intervals(session)
print("delegations in parent:", len(blocking))
async_n = sum(1 for b in blocking.values() if b.async_launched)
with_usage = [b for b in blocking.values() if b.usage_fields_in_result]
print("async_launched:", async_n, " results carrying usage fields:", len(with_usage))
blocks = [b.blocking_duration_s for b in blocking.values() if b.blocking_duration_s is not None]
print("blocking durations n=%d min=%.2fs max=%.2fs" % (len(blocks), min(blocks), max(blocks))
      if blocks else "no blocking durations")

outs = so.read_session_subagents(session)
print("subagent transcripts:", len(outs))
joined = [o for o in outs if o.tool_use_id in blocking]
print("joinable on toolUseId:", len(joined))
for o in outs[:4]:
    print(f"  {o.agent_id} type={o.agent_type} shape={o.request_shape} "
          f"task_s={o.task_duration_s} cost=${o.cost_usd:.4f} models={o.models} "
          f"unpriced={o.unpriced_models}")
tasks = [o for o in outs if o.task_duration_s]
if tasks and blocks:
    med_task = sorted(x.task_duration_s for x in tasks)[len(tasks) // 2]
    med_block = sorted(blocks)[len(blocks) // 2]
    print(f"median task duration {med_task:.1f}s vs median blocking {med_block:.1f}s")
