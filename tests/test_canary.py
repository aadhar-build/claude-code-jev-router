#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Offline exercise of src/canary.py. Zero spend, temp storage, real data untouched."""
import json, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pyversion  # noqa: E402

# JEV-44: assert the floor BEFORE importing anything that does not parse
# below it. The PEP-723 header above binds `uv run` only; `python3
# tests/<this file>` ignores it entirely, and that is the invocation that
# produced 16 SyntaxErrors out of src/arms/jev.py:237.
pyversion.require()

import paths, canary, store

tmp = Path(tempfile.mkdtemp(prefix="canary-test-"))
for name in ("FIXTURES", "RUNS", "CAPTURES", "STATES", "LABELS", "REPORTS", "LOGS"):
    setattr(paths, name, tmp / name.lower())
paths.WRITABLE_DIRS = [getattr(paths, n) for n in
                       ("FIXTURES", "RUNS", "CAPTURES", "STATES", "LABELS", "REPORTS", "LOGS")]
paths.ensure_dirs()
print(f"temp storage: {tmp}\n")

fails = []
def check(label, cond):
    print(f"  [{'ok ' if cond else 'FAIL'}] {label}")
    if not cond: fails.append(label)

# ---- (a) selection is deterministic across a delete/recreate -----------------
print("A. freeze is deterministic")
f1 = canary.freeze("pre_bash")
a = canary.fixture_path().read_text()
canary.fixture_path().unlink()
f2 = canary.freeze("pre_bash")
b = canary.fixture_path().read_text()
strip = lambda t: "\n".join(l for l in t.splitlines() if '"created_at"' not in l)
check("byte-identical apart from created_at", strip(a) == strip(b))
check("same canary_set_id", f1["canary_set_id"] == f2["canary_set_id"])
check("21 states", len(f1["states"]) == 21)
from collections import Counter
check("7 per stratum", Counter(s["stratum"] for s in f1["states"]) ==
      {"destructive": 7, "borderline": 7, "benign": 7})
check("21 distinct state_sha256", len({s["state_sha256"] for s in f1["states"]}) == 21)
check("21 distinct commands",
      len({s["payload"]["tool_input"]["command"] for s in f1["states"]}) == 21)
check("id is content-derived", f1["canary_set_id"] ==
      canary._set_id([s["state_sha256"] for s in f1["states"]]))
print(f"  canary_set_id: {f1['canary_set_id']}")

# ---- edited fixture is rejected ---------------------------------------------
print("\nB. a hand-edited fixture is refused")
blob = json.loads(canary.fixture_path().read_text())
blob["states"][0]["state_sha256"] = "0" * 64
canary.fixture_path().write_text(json.dumps(blob))
try:
    canary.load_or_freeze("pre_bash"); check("raised", False)
except ValueError as e:
    check("raised ValueError", "has been edited" in str(e))
canary.fixture_path().write_text(b)

# ---- (b)/(c) sweep with the fake arm ----------------------------------------
print("\nC. first sweep -> exit 2 (baseline), second -> exit 0 (clean)")
argv = sys.argv
sys.argv = ["canary.py", "--arms", "fake"]
rc1 = canary.main()
check("first sweep exits 2 (no reference)", rc1 == canary.EXIT_NO_REFERENCE)
rc2 = canary.main()
check("second sweep exits 0 (clean)", rc2 == canary.EXIT_CLEAN)
sys.argv = ["canary.py", "--arms", "fake", "--report-only"]
rc3 = canary.main()
check("--report-only exits 0 and calls nothing", rc3 == canary.EXIT_CLEAN)
sys.argv = argv

rows = [r for r in store.runs() if r.get("run_context") == "canary"]
check("42 canary rows on disk (2 sweeps x 21)", len(rows) == 42)
check("all rows carry canary_set_id", all(r.get("canary_set_id") == f1["canary_set_id"] for r in rows))
check("all rows carry sweep='canary'", all(r.get("sweep") == "canary" for r in rows))
check("two distinct canary_sweep_ids", len({r["canary_sweep_id"] for r in rows}) == 2)
caps = [c for c in store.captures() if c.get("run_context") == "canary"]
check("21 capture rows, written once not twice", len(caps) == 21)

# schema identity against a synthetic row written by replay
import replay, random, config_loader as cl, state_builders as sb
replay.run_synthetic([cl.arm("fake")], "pre_bash", 1, random.Random(1))
syn = [r for r in store.runs() if r.get("run_context") == "synthetic"][0]
can = rows[0]
extra_keys = {"canary_set_id", "canary_sweep_id", "sweep"}
check("canary row keys == synthetic row keys + canary extras",
      set(can) - set(syn) == extra_keys and set(syn) - set(can) == set())

# ---- (d) the flag paths, on hand-built rows ---------------------------------
print("\nD. drift flags, on hand-built rows (fake can never drift from itself)")
def row(did, p, model="m1", ok=True, sweep="S1"):
    return {"decision_id": did, "arm": "jev", "ok": ok, "response_model": model,
            "canary_sweep_id": sweep, "evaluated_at": "2026-09-20T00:00:00.000+00:00",
            "stratum": "benign", "answers": {"destructive": {"type": "boolean", "probability": p}}}
ref = [row("can-syn-0000", 0.10), row("can-syn-0001", 0.90)]

r = canary.compare(ref, [row("can-syn-0000", 0.10, sweep="S2"), row("can-syn-0001", 0.90, sweep="S2")], "jev")
check("identical rows -> no flags", r.flags(0.5, 0.05) == [] and r.mean_abs_delta == 0.0)

r = canary.compare(ref, [row("can-syn-0000", 0.10, model="m2", sweep="S2"),
                         row("can-syn-0001", 0.90, model="m2", sweep="S2")], "jev")
check("(a) response_model change flags", any(f.startswith("(a)") for f in r.flags(0.5, 0.05)))

r = canary.compare(ref, [row("can-syn-0000", 0.18, sweep="S2"), row("can-syn-0001", 0.98, sweep="S2")], "jev")
fl = r.flags(0.5, 0.05)
check("(b) mean |delta| 0.08 > 0.05 flags", any(f.startswith("(b)") for f in fl))
check("... and nothing else", len(fl) == 1)

r = canary.compare(ref, [row("can-syn-0000", 0.52, sweep="S2"), row("can-syn-0001", 0.90, sweep="S2")], "jev")
fl = r.flags(0.5, 0.05)
check("(c) decision flip at tau=0.5 flags", any(f.startswith("(c)") for f in fl))
check("flip outside the jitter band is marked as such",
      not r.flips(0.5)[0].near_tau(0.5))
r = canary.compare([row("can-syn-0000", 0.49)], [row("can-syn-0000", 0.51, sweep="S2")], "jev")
check("flip inside the jitter band is marked as such", r.flips(0.5)[0].near_tau(0.5))

r = canary.compare(ref, [row("can-syn-0000", 0.10, sweep="S2")], "jev")
check("a missing state is reported, not silently skipped", r.missing == ["can-syn-0001/destructive"])

# ---- reference selection skips an all-failed first sweep --------------------
print("\nE. a failed first sweep never becomes the reference")
import store as st
bad_sweep = store.ulid()
for s in f1["states"]:
    st.append_run({"decision_id": f"can-{s['synthetic_id']}", "arm": "jev", "ok": False,
                   "error_kind": "connection", "run_context": "canary",
                   "canary_set_id": f1["canary_set_id"], "canary_sweep_id": bad_sweep,
                   "sweep": "canary", "answers": {}})
by_sweep, usable = canary.sweeps_for(f1["canary_set_id"], "jev", 21)
check("the all-failed sweep is on disk", bad_sweep in by_sweep)
check("but is not usable as a reference", bad_sweep not in usable)

print("\n" + ("FAILURES: " + "; ".join(fails) if fails else "all offline checks passed"))
sys.exit(1 if fails else 0)
