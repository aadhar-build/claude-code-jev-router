#!/usr/bin/env python3
"""JEV-41 paired A/B verification on existing synthetic states.

A = current config (--effort low, thinking left to Claude Code's default)
B = candidate fix (MAX_THINKING_TOKENS=0 -> thinking:{type:"disabled"})

Same states, interleaved A,B per state, so hour-of-day and machine load are paired.
Writes .scratch/jev41/results.jsonl. Does NOT write data/runs/.
"""
import json, os, sys, time
ROOT="/Users/aadharagarwal/projects/JEV-experiments"
sys.path.insert(0, ROOT+"/src"); sys.path.insert(0, ROOT+"/.scratch/jev41")
import state_builders as sb
from probe import run

items=[json.loads(l) for l in open(ROOT+"/data/synthetic/pre_bash-v1.jsonl")]
by={}
for it in items: by.setdefault(it["stratum"],[]).append(it)
sample=[]
for s in ("destructive","borderline","benign"):
    sample += by[s][:3]

out=open(ROOT+"/.scratch/jev41/results.jsonl","a")
for it in sample:
    state=sb.build_pre_bash(it["payload"])
    for label,envx in (("A_current",None),("B_mtt0",{"MAX_THINKING_TOKENS":"0"})):
        r=run(label,"claude-haiku-4-5","low",(),envx,state=state)
        r["synthetic_id"]=it["synthetic_id"]; r["stratum"]=it["stratum"]
        r.pop("stdout",None)
        out.write(json.dumps(r)+"\n"); out.flush()
        print(json.dumps({k:r.get(k) for k in ("synthetic_id","label","api_ms","wall_ms","out_tok","think","cache_read","cache_write","turns","so")}), flush=True)
out.close()
