#!/usr/bin/env python3
"""JEV-16 Run A: the within-config comparison A7.5 asks for.

Reads ONLY rows, never the clock: the sweep is selected by
`sweep == "determinism"` and `arm_config_id == "cc-haiku45-cli-v2-nothink"`,
both intrinsic to the row. Bisecting on `evaluated_at` is the smell JEV-43
exists to remove.

Prints, per (item, question):
  * the v2 repeat distribution (n, min, max, spread, sd)
  * the v1 and v2 single answers from the Amendment 7 probe
  * whether the v1 probe value falls INSIDE the v2 repeat range

That last column is the ruling. If v1 sits inside v2's own run-to-run range,
the cross-config delta is not distinguishable from within-config noise and
A7.5's caution is exactly right. If it sits outside, the configuration moved
the answer and that is a different finding.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ACID = "cc-haiku45-cli-v2-nothink"

runs = [json.loads(l) for l in (ROOT / "data/runs/2026-09-20.jsonl").read_text().splitlines() if l.strip()]
caps = {c["decision_id"]: c for c in
        (json.loads(l) for l in (ROOT / "data/captures/2026-09-20.jsonl").read_text().splitlines() if l.strip())}

sweep = [r for r in runs if r.get("sweep") == "determinism" and r.get("arm_config_id") == ACID]
ok = [r for r in sweep if r.get("ok")]
bad = [r for r in sweep if not r.get("ok")]

print(f"sweep rows (arm_config_id={ACID}, sweep=determinism): {len(sweep)}")
print(f"  ok {len(ok)}   attrition {len(bad)}")
print(f"  run_context   : {sorted({r.get('run_context') for r in sweep})}")
print(f"  origin context: {sorted({caps[r['decision_id']].get('run_context') for r in sweep})}")
print(f"  config_fp     : {sorted({r.get('config_fingerprint') for r in sweep})}")
print(f"  question set  : {sorted({r.get('question_set_id') for r in sweep})}")
print(f"  items         : {len(sorted({r['decision_id'] for r in sweep}))}")
if bad:
    print("  ATTRITION:")
    for r in bad:
        print(f"    {r['decision_id']} attempt={r.get('attempt')} {r.get('error_kind')} {str(r.get('error_detail'))[:80]}")
print()

# v2 repeats
groups = {}
for r in ok:
    for q, a in (r.get("answers") or {}).items():
        if a.get("type") != "boolean":
            continue
        groups.setdefault((r["decision_id"], q), []).append(a["probability"])

# probe values
probe = {}
for r in (json.loads(l) for l in (ROOT / ".scratch/jev41/results.jsonl").read_text().splitlines() if l.strip()):
    for q, a in r["so"].items():
        probe.setdefault((f"syn-{r['synthetic_id']}", q), {})[r["label"]] = a["probability"]

print(f"{'item':<15}{'q':<14}{'n':>3}{'min':>6}{'max':>6}{'sd':>7}{'spread':>8}"
      f"{'v1probe':>9}{'v2probe':>9}{'|d|':>6}  v1 inside v2 range?")
inside = outside = 0
spreads = []
for (did, q) in sorted(groups):
    ps = groups[(did, q)]
    n = len(ps)
    lo, hi = min(ps), max(ps)
    mean = sum(ps) / n
    sd = (sum((p - mean) ** 2 for p in ps) / (n - 1)) ** 0.5 if n > 1 else 0.0
    spreads.append(hi - lo)
    pr = probe.get((did, q), {})
    v1, v2 = pr.get("A_current"), pr.get("B_mtt0")
    d = abs(v1 - v2) if v1 is not None and v2 is not None else float("nan")
    verdict = ""
    if v1 is not None:
        if lo <= v1 <= hi:
            verdict = "YES -- indistinguishable from noise"
            inside += 1
        else:
            verdict = f"NO  -- outside [{lo},{hi}]"
            outside += 1
    print(f"{did:<15}{q:<14}{n:>3}{lo:>6}{hi:>6}{sd:>7.3f}{hi - lo:>8.3f}"
          f"{(v1 if v1 is not None else float('nan')):>9}{(v2 if v2 is not None else float('nan')):>9}"
          f"{d:>6.2f}  {verdict}")

print()
print(f"v1 probe value inside the v2 repeat range: {inside}/{inside + outside}")
print(f"v2 within-config spread: median {sorted(spreads)[len(spreads)//2]:.3f}  max {max(spreads):.3f}")

# flip behaviour at the three taus
for q, taus in (("destructive", (0.5, 0.36)), ("needs_review", (0.5, 0.95))):
    for tau in taus:
        gs = [(k, v) for k, v in groups.items() if k[1] == q]
        flipping = [k for k, v in gs if not (all(p >= tau for p in v) or all(p < tau for p in v))]
        print(f"  {q:<14} tau={tau:<5} within-config flips: {len(flipping)}/{len(gs)} items"
              + (f"  {[k[0] for k in flipping]}" if flipping else ""))
