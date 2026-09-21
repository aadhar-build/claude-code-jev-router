"""One-off: generate recorded judge verdicts for the Class 2 fixture suite."""
import json
import pathlib

root = pathlib.Path(__file__).resolve().parents[2] / "tests/fixtures/accuracy/suite-v1"
manifest = json.loads((root / "suite.json").read_text())
tasks = [t["id"] for t in manifest["tasks"]]
WORSE = {"dedupe-config-keys", "csv-quote-escaping"}  # 2 of 12 -- under the 1/3 soft block

for tid in tasks:
    for arm in ("baseline", "treatment"):
        for seed in range(3):
            d = root / "recorded" / "judge" / arm / tid
            d.mkdir(parents=True, exist_ok=True)
            violations = []
            dims = {"correctness": 8.0, "changeability": 7.5,
                    "modularity": 7.0, "tests": 7.0}
            if arm == "treatment" and tid in WORSE:
                violations = ["no test accompanies the change"]
                dims["tests"] = 6.6  # delta -0.4: under the 0.75 noise floor
            (d / f"{seed}.json").write_text(
                json.dumps({"rule_violations": violations, "dimensions": dims}, indent=2) + "\n",
                encoding="utf-8")

print("judge files", sum(1 for _ in (root / "recorded" / "judge").rglob("*.json")))
