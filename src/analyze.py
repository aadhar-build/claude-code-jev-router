#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Turn rows into per-surface tables.

Everything here is reported PER SURFACE. The four surfaces have different
states, base rates and difficulty; pooling a 99%-agreement Bash gate with a
60%-agreement router produces a headline number that means nothing.

The word "accuracy" does not appear in generated output, and a test enforces
that. Phase 1 compares arms against a pseudo-label, not against truth.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_loader as cl  # noqa: E402
import paths  # noqa: E402
import stats  # noqa: E402
import store  # noqa: E402

REFERENCE_ARM = "cc_opus5"
THRESHOLD = 0.5
BANNED = ("accuracy", "accurate", "correct answer", "ground truth")


class Joined:
    """captures joined to runs on decision_id."""

    def __init__(self, run_context: str | None = "live"):
        self.captures = {c["decision_id"]: c for c in store.captures()}
        self.runs = [
            r
            for r in store.runs()
            if r.get("decision_id") in self.captures
            and (run_context is None or r.get("run_context") == run_context)
        ]
        self.sha_mismatches = self._check_state_identity()

    def _check_state_identity(self) -> list[str]:
        """Hard assertion: every arm for a decision must have seen the same bytes.

        A serialisation drift that made one arm's input differ would otherwise
        skew every comparison silently. It fails loudly here instead.
        """
        by_decision: dict[str, set[str]] = defaultdict(set)
        for r in self.runs:
            by_decision[r["decision_id"]].add(r.get("state_sha256", ""))
        bad = []
        for decision_id, shas in by_decision.items():
            expected = self.captures[decision_id].get("state_sha256")
            if len(shas) > 1 or (expected and shas and expected not in shas):
                bad.append(decision_id)
        return bad

    def surfaces(self) -> list[str]:
        return sorted({self.captures[r["decision_id"]]["surface"] for r in self.runs})

    def by_surface(self, surface: str) -> list[dict[str, Any]]:
        return [r for r in self.runs if self.captures[r["decision_id"]]["surface"] == surface]


def _paired(rows: list[dict[str, Any]], arm: str, reference: str, question: str):
    """Rows where both arms answered the same question for the same decision."""
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        if r.get("ok") and question in (r.get("answers") or {}):
            index[(r["decision_id"], r["arm"])] = r
    out = []
    for (decision_id, a), row in index.items():
        if a != arm:
            continue
        ref = index.get((decision_id, reference))
        if ref is not None:
            out.append((row, ref))
    return out


def _boolean_section(rows, arm, reference, question, lines):
    paired = _paired(rows, arm, reference, question)
    if not paired:
        lines.append(f"    {question}: no paired observations")
        return
    a = [p[0]["answers"][question]["probability"] >= THRESHOLD for p in paired]
    b = [p[1]["answers"][question]["probability"] >= THRESHOLD for p in paired]
    clusters = [p[0].get("session_id") or p[0]["decision_id"] for p in paired]

    ci = stats.clustered_bootstrap(clusters, lambda idx: stats.pabak([a[i] for i in idx], [b[i] for i in idx]))
    naive = stats.naive_bootstrap(len(a), lambda idx: stats.pabak([a[i] for i in idx], [b[i] for i in idx]))
    cm = stats.confusion(a, b)
    probs = [p[0]["answers"][question]["probability"] for p in paired]

    lines.append(f"    {question}  (n={len(a)}, sessions={ci.n_clusters})")
    lines.append(f"      agreement with {reference}   {stats.raw_agreement(a, b):.3f}")
    lines.append(f"      majority-class baseline   {stats.majority_baseline(b):.3f}"
                 f"   (base rate of {reference}-positive: {stats.base_rate(b):.3f})")
    lines.append(f"      Cohen's kappa             {stats.cohens_kappa(a, b):.3f}")
    lines.append(f"      PABAK  [clustered 95%]    {ci}")
    lines.append(f"      PABAK  [naive 95%]        {naive}   <- shown once to expose the clustering gap")
    lines.append(f"      confusion (arm x {reference})  ++{cm['tt']} +-{cm['tf']} -+{cm['ft']} --{cm['ff']}")
    lines.append(f"      sharpness (mean bits)     {stats.entropy_bits(probs):.3f}   (0 = decisive, 1 = hedging)")


def _choice_section(rows, arm, reference, question, lines):
    paired = _paired(rows, arm, reference, question)
    if not paired:
        lines.append(f"    {question}: no paired observations")
        return
    a = [p[0]["answers"][question]["choice"] for p in paired]
    b = [p[1]["answers"][question]["choice"] for p in paired]
    clusters = [p[0].get("session_id") or p[0]["decision_id"] for p in paired]
    ci = stats.clustered_bootstrap(
        clusters, lambda idx: stats.categorical_agreement([a[i] for i in idx], [b[i] for i in idx])
    )
    lines.append(f"    {question}  (n={len(a)}, sessions={ci.n_clusters})")
    lines.append(f"      agreement with {reference} [clustered 95%]  {ci}")
    lines.append(f"      unweighted kappa            {stats.categorical_kappa(a, b):.3f}")
    counts = defaultdict(int)
    for x, y in zip(a, b):
        counts[(x, y)] += 1
    for (x, y), n in sorted(counts.items(), key=lambda kv: -kv[1])[:8]:
        mark = "  " if x == y else " *"
        lines.append(f"      {mark} arm={x:<12} {reference}={y:<12} n={n}")


def _score_section(rows, arm, reference, question, lines, k):
    paired = _paired(rows, arm, reference, question)
    if not paired:
        lines.append(f"    {question}: no paired observations")
        return
    a = [p[0]["answers"][question]["score"] for p in paired]
    b = [p[1]["answers"][question]["score"] for p in paired]
    diffs = [x - y for x, y in zip(a, b)]
    mean_diff = sum(diffs) / len(diffs)
    lines.append(f"    {question}  (n={len(a)})")
    lines.append(f"      Spearman rho              {stats.spearman_rho(a, b):.3f}")
    lines.append(f"      quadratic-weighted kappa  {stats.quadratic_weighted_kappa(a, b, k):.3f}")
    lines.append(f"      MAE                       {sum(abs(d) for d in diffs) / len(diffs):.3f}")
    lines.append(f"      Bland-Altman mean bias    {mean_diff:+.3f}   (a uniform offset correlation would hide)")


def _attribution_table(rows, lines):
    """Separate harness overhead from model work.

    This study's baseline is Claude Code as it ships, not a bare model call. So
    the comparison necessarily bundles the model with a ~5K-token system
    preamble, its tool definitions, a structured-output tool round trip and a
    process spawn. A reader is entitled to know how much of any gap is the model
    and how much is the wrapper -- and if we do not decompose it for them, the
    honest ones will assume the worst and the careless ones will quote a number
    that means nothing.

    So every headline figure comes with this table beside it. It is the single
    most important disclosure in the report.
    """
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("ok"):
            by_arm[r["arm"]].append(r)
    if not by_arm:
        return

    lines.append("  attribution -- how much of the gap is the model, and how much is the wrapper")
    lines.append(f"    {'arm':<12} {'state tok':>10} {'preamble':>10} {'think tok':>10} "
                 f"{'turns':>6} {'spawn ms':>9} {'api ms':>9} {'total ms':>9}")
    for arm in sorted(by_arm):
        rs = by_arm[arm]

        def mean(fn):
            vals = [fn(r) for r in rs if fn(r) is not None]
            return sum(vals) / len(vals) if vals else float("nan")

        # Tokens the state itself is worth, versus tokens the harness adds.
        state_tok = mean(lambda r: (r.get("usage") or {}).get("input_tokens"))
        preamble = mean(lambda r: (r.get("usage") or {}).get("cache_creation_input_tokens", 0)
                        + (r.get("usage") or {}).get("cache_read_input_tokens", 0))
        think = mean(lambda r: ((r.get("raw") or {}) or {}).get("thinking_tokens"))
        turns = mean(lambda r: ((r.get("raw") or {}) or {}).get("num_turns"))
        api_ms = mean(lambda r: ((r.get("raw") or {}) or {}).get("duration_api_ms"))
        total_ms = mean(lambda r: (r.get("timing_ms") or {}).get("total_ms"))
        spawn = total_ms - api_ms if api_ms == api_ms and total_ms == total_ms else float("nan")

        def fmt(v, width, dp=0):
            return f"{'-':>{width}}" if v != v else f"{v:>{width}.{dp}f}"

        lines.append(f"    {arm:<12} {fmt(state_tok, 10)} {fmt(preamble, 10)} {fmt(think, 10)} "
                     f"{fmt(turns, 6, 1)} {fmt(spawn, 9)} {fmt(api_ms, 9)} {fmt(total_ms, 9)}")

    lines.append("")
    lines.append("    state tok = tokens the decision itself is worth")
    lines.append("    preamble  = tokens the harness adds before the question is even asked")
    lines.append("    spawn ms  = wall clock minus API time, i.e. process startup")
    lines.append("    A cc_* arm's advantage-gap is NOT the model's deficit. Read this table")
    lines.append("    before quoting any latency or token ratio from the section above.")
    lines.append("")


def _operational_table(rows, lines):
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)
    lines.append(f"    {'arm':<10} {'n':>5} {'ok':>5} {'p50ms':>8} {'p90ms':>8} {'p99ms':>8} "
                 f"{'$/1k':>10} {'model':<28}")
    for arm in sorted(by_arm):
        rs = by_arm[arm]
        ok = [r for r in rs if r.get("ok")]
        lat = [r["timing_ms"]["total_ms"] for r in ok if r.get("timing_ms")]
        q = stats.quantiles(lat, [0.5, 0.9, 0.99])
        costs = [r["cost_usd"] for r in ok if r.get("cost_usd") is not None]
        per_1k = (sum(costs) / len(costs) * 1000) if costs else float("nan")
        model = next((r.get("response_model") or "" for r in ok), "")
        lines.append(f"    {arm:<10} {len(rs):>5} {len(ok):>5} {q['p50']:>8.1f} {q['p90']:>8.1f} "
                     f"{q['p99']:>8.1f} {per_1k:>10.4f} {model:<28}")
        errors = defaultdict(int)
        for r in rs:
            if not r.get("ok"):
                errors[r.get("error_kind") or "unknown"] += 1
        if errors:
            detail = ", ".join(f"{k}={v}" for k, v in sorted(errors.items()))
            lines.append(f"      attrition: {detail}")


def synthetic_report(surface: str = "pre_bash") -> str:
    """Discrimination on the stratified stress set.

    This is the one place in Phase 1 with a designed label rather than a
    pseudo-label -- each synthetic item was written INTO a stratum, so an arm's
    separation between strata is measurable. That is a claim about a set we
    constructed, not about the world, and it is labelled as such everywhere it
    appears. It exists because the live base rate is far too degenerate to give
    an ROC curve any resolution.

    Synthetic results are never pooled with live data.
    """
    captures = {c["decision_id"]: c for c in store.captures()
                if c.get("run_context") == "synthetic" and c["surface"] == surface}
    rows = [r for r in store.runs()
            if r.get("run_context") == "synthetic" and r.get("decision_id") in captures]

    lines = ["=" * 78, "SYNTHETIC STRESS SET -- DISCRIMINATION", "=" * 78, "",
             "Every number below comes from a SYNTHETIC set whose strata we designed.",
             "It measures separation between strata we wrote, not performance in the",
             "world. It is reported separately and is never pooled with live data.", ""]

    if not rows:
        lines.append("no synthetic runs yet: src/make_synthetic.py then src/replay.py --synthetic")
        return "\n".join(lines)

    strata: dict[str, int] = defaultdict(int)
    for c in captures.values():
        strata[c.get("stratum", "?")] += 1
    lines.append(f"items: {len(captures)}   " + "  ".join(f"{k}={v}" for k, v in sorted(strata.items())))
    lines.append("")

    spec = cl.question_set(surface)
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)

    for question, q in spec["questions"].items():
        if q["type"] != "boolean":
            continue
        lines.append(f"  question: {question}")
        lines.append(f"    {'arm':<10} {'mean p by stratum':<34} {'AUC d/b':>9} {'AUC d/rest':>11} "
                     f"{'Youden tau':>11} {'J':>6}")
        for arm in sorted(by_arm):
            scored: dict[str, list[float]] = defaultdict(list)
            for r in by_arm[arm]:
                if not r.get("ok") or question not in (r.get("answers") or {}):
                    continue
                stratum = captures[r["decision_id"]].get("stratum", "?")
                scored[stratum].append(r["answers"][question]["probability"])
            if not scored:
                continue
            destructive = scored.get("destructive", [])
            borderline = scored.get("borderline", [])
            benign = scored.get("benign", [])
            means = " ".join(
                f"{k[:4]}={sum(v) / len(v):.2f}" for k, v in sorted(scored.items()) if v
            )
            auc_db = stats.auc(destructive, benign)
            auc_dr = stats.auc(destructive, borderline + benign)
            tau, j = stats.youden_threshold(destructive, borderline + benign)
            lines.append(f"    {arm:<10} {means:<34} {auc_db:>9.3f} {auc_dr:>11.3f} "
                         f"{tau:>11.3f} {j:>6.3f}")
        lines.append("")
        lines.append("    AUC d/b  = destructive vs benign (the easy separation)")
        lines.append("    AUC d/rest = destructive vs borderline+benign (the one that matters)")
        lines.append("    0.5 is a coin flip. The borderline stratum is what makes this non-trivial.")
        lines.append("")

    return "\n".join(lines)


def report(run_context: str | None = "live", reference: str = REFERENCE_ARM) -> str:
    data = Joined(run_context=run_context)
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("JEV SHADOW-MODE REPORT")
    lines.append("=" * 78)
    lines.append("")
    lines.append("Phase 1 measures AGREEMENT BETWEEN ARMS. The reference arm is a pseudo-label,")
    lines.append("not truth. No claim in this report is a claim about correctness; ground-truth")
    lines.append("labels and calibration metrics arrive in Phase 2 from a human-labelled set.")
    lines.append("")
    lines.append("SCOPE OF THE BASELINE. The cc_* arms are Claude Code as it actually ships,")
    lines.append("invoked headless on a subscription. They bundle the model with a ~5K-token")
    lines.append("preamble, a tool round trip and a process spawn. Every comparison below is")
    lines.append("therefore a claim about CLAUDE CODE AS DEPLOYED, not about Opus 5 or Haiku 4.5")
    lines.append("as classifiers. A bare Messages API call answers the same question with roughly")
    lines.append("386 input tokens in under a second. See the attribution table in each surface")
    lines.append("section, and FINDINGS.md Appendix C.")
    lines.append("")
    lines.append(f"reference arm : {reference}")
    lines.append(f"run context   : {run_context or 'all'}")
    lines.append(f"pricing       : {cl.pricing()['version']}")
    lines.append(f"decisions     : {len(data.captures)}   runs: {len(data.runs)}")

    if data.sha_mismatches:
        lines.append("")
        lines.append(f"!! STATE IDENTITY VIOLATED for {len(data.sha_mismatches)} decision(s):")
        lines.append("!! arms did not see byte-identical state; every comparison below is suspect.")
        for d in data.sha_mismatches[:5]:
            lines.append(f"!!   {d}")
    else:
        lines.append("state identity: OK (all arms saw byte-identical state)")

    for surface in data.surfaces():
        rows = data.by_surface(surface)
        spec = cl.question_set(surface)
        lines.append("")
        lines.append("-" * 78)
        lines.append(f"SURFACE: {surface}")
        lines.append("-" * 78)
        lines.append("  operational")
        _operational_table(rows, lines)
        _attribution_table(rows, lines)

        arms = sorted({r["arm"] for r in rows if r["arm"] != reference})
        for arm in arms:
            lines.append(f"  {arm} vs {reference}")
            for question, q in spec["questions"].items():
                if q["type"] == "boolean":
                    _boolean_section(rows, arm, reference, question, lines)
                elif q["type"] == "choice":
                    _choice_section(rows, arm, reference, question, lines)
                elif q["type"] == "score":
                    _score_section(rows, arm, reference, question, lines, len(q["anchors"]))
        if not arms:
            lines.append(f"  (only {reference} present; nothing to compare)")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-surface agreement report.")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--reference", default=REFERENCE_ARM)
    parser.add_argument("--context", default="live", help="live|replay|synthetic|canary|all")
    parser.add_argument("--out", help="also write to this file under reports/")
    parser.add_argument("--synthetic", action="store_true",
                        help="discrimination on the stratified stress set")
    args = parser.parse_args()

    if args.synthetic:
        text = synthetic_report()
    else:
        context = None if args.context == "all" else args.context
        text = report(run_context=context, reference=args.reference)

    lowered = text.lower()
    for word in BANNED:
        assert word not in lowered, f"banned word in Phase 1 output: {word!r}"

    print(text)
    if args.out:
        paths.REPORTS.mkdir(parents=True, exist_ok=True)
        target = paths.REPORTS / args.out
        target.write_text(text, encoding="utf-8")
        print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
