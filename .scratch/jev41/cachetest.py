"""JEV-41 defect B diagnostic: does padding the stable prefix above Haiku 4.5's
4,096-token cache minimum make cache reads appear across DISTINCT states?

Three calls, three distinct states, one padded SYSTEM prompt. If the 4,096
minimum is the mechanism, call 1 writes and calls 2 and 3 read the stable block.
"""
import json, sys
ROOT="/Users/aadharagarwal/projects/JEV-experiments"
sys.path.insert(0, ROOT+"/src"); sys.path.insert(0, ROOT+"/.scratch/jev41")
import probe, state_builders as sb

PAD = ("Reference notes for the classifier, included to lengthen the stable "
       "system prefix. They carry no instruction and must not change any answer. ") * 340
probe.SYSTEM = probe.SYSTEM + "\n\n" + PAD

items=[json.loads(l) for l in open(ROOT+"/data/synthetic/pre_bash-v1.jsonl")]
picks=[items[0], items[40], items[200]]
for it in picks:
    st=sb.build_pre_bash(it["payload"])
    r=probe.run("padded","claude-haiku-4-5","low",(),{"MAX_THINKING_TOKENS":"0"},state=st)
    print(it["synthetic_id"], "cr",r.get("cache_read"),"cw",r.get("cache_write"),
          "inp",r.get("inp"),"api",r.get("api_ms"),"turns",r.get("turns"), flush=True)
