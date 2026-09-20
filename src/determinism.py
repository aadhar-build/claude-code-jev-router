#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The same bytes, N times: how often does the decision change?

Jev is not bit-deterministic (PREREGISTRATION.md section 7, FINDINGS.md 2.3).
The day-0 spike saw one decision flip in twenty calls on a command sitting at
p~0.50. That is the single specific blocker for ever enforcing on Jev's output:
a borderline command gated inconsistently is worse for the user than one gated
always or never, because the behaviour is unreproducible.

The rate itself is not the interesting quantity, and quoting one ("1 in 10")
is explicitly ruled out by the pre-registration. The interesting quantity is:

    flip rate AS A FUNCTION OF DISTANCE FROM THE THRESHOLD

If flips concentrate in a narrow band around tau and vanish outside it, then
enforcement is safe everywhere except that band, and the deployment question
becomes the answerable one: how many real decisions land in the band? If instead
flips are spread across the whole score range, no operating point is safe and
the classifier cannot gate anything.

Two things this tool refuses to do:

* invent a flip rate from a bucket with three items in it. Every bucket prints
  its n, and a bucket below the minimum prints "n<k" where the rate would go.
* print anything at all resembling a rate when no repeat data exists. With no
  `--determinism` sweep on disk it degrades to OCCUPANCY ONLY -- how many
  decisions sit near tau, which single-shot data does answer -- and says which
  half of the picture is missing and exactly how to collect it.

Both arms are measured, not just Jev. "Temperature-zero LLMs wobble too" is the
fair comparison and the reason this sweep exists in the form it does.

Usage:
    uv run src/determinism.py
    uv run src/determinism.py --tau 0.5 --tau destructive=0.36 --tau needs_review=0.95
    uv run src/determinism.py --arm jev --out determinism.txt
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_loader as cl  # noqa: E402
import paths  # noqa: E402
import stats  # noqa: E402
import store  # noqa: E402

# Operating points quoted in FINDINGS 4b, plus the default nobody chose. All
# three are evaluated side by side because the whole point of the exercise is
# that the answer depends on where tau sits.
DEFAULT_TAUS = {"destructive": [0.5, 0.36], "needs_review": [0.5, 0.95]}

# |p - tau| buckets. Deliberately fine near zero: the hypothesis is that
# everything interesting happens in the first two.
BANDS: list[tuple[float, float]] = [
    (0.00, 0.02), (0.02, 0.05), (0.05, 0.10),
    (0.10, 0.20), (0.20, 0.50), (0.50, 1.01),
]

MIN_REPEATS = 3        # below this a "group" is not a measurement
MIN_BUCKET = 5         # below this a bucket prints its n instead of a rate
MIN_GROUPS = 5         # below this the whole analysis is withheld


# --------------------------------------------------------------------------
# collection
# --------------------------------------------------------------------------

@dataclass
class Group:
    """One (decision, arm, question) evaluated repeatedly on identical bytes."""
    decision_id: str
    arm: str
    question: str
    stratum: str | None
    probabilities: list[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.probabilities)

    @property
    def mean(self) -> float:
        return sum(self.probabilities) / self.n

    @property
    def spread(self) -> float:
        return max(self.probabilities) - min(self.probabilities)

    @property
    def sd(self) -> float:
        return statistics.stdev(self.probabilities) if self.n > 1 else 0.0

    def fraction_above(self, tau: float) -> float:
        return sum(1 for p in self.probabilities if p >= tau) / self.n

    def unanimous(self, tau: float) -> bool:
        q = self.fraction_above(tau)
        return q in (0.0, 1.0)

    def pairwise_disagreement(self, tau: float) -> float:
        """Probability two independent calls disagree: 2q(1-q).

        This is what a user actually experiences -- they do not see the
        distribution, they see this command allowed on Tuesday and blocked on
        Wednesday. Unanimity is the headline; this is the severity.
        """
        q = self.fraction_above(tau)
        return 2 * q * (1 - q)


def collect(surface: str, *, min_repeats: int = MIN_REPEATS
            ) -> tuple[list[Group], dict[str, dict[str, dict[str, list[float]]]], dict[str, Any]]:
    """Return (repeat groups, single-shot score distribution, diagnostics).

    A repeat group is keyed on (decision_id, arm, question_set_id,
    state_sha256): identical bytes, identical question, same arm. Rows written
    by `replay.py --determinism` are preferred, because those were produced on
    purpose; if none exist, any group of >=2 rows on identical state is used
    instead and the report says loudly that it is not a designed sweep.

    The single-shot distribution is built from the ordinary (non-sweep) runs and
    is what the occupancy analysis needs. It is available even with zero repeat
    data, which is why this function returns both.
    """
    captures = {c["decision_id"]: c for c in store.captures() if c["surface"] == surface}
    primary_qsid = cl.question_set_id(surface)

    designed: dict[tuple, Group] = {}
    incidental: dict[tuple, Group] = {}
    single: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list)))
    seen_single: set[tuple[str, str, str]] = set()
    diagnostics: dict[str, Any] = {
        "run_rows": 0, "failed": 0, "sweep_rows": 0, "contexts": set()}

    for r in store.runs():
        did = r.get("decision_id")
        if did not in captures:
            continue
        diagnostics["run_rows"] += 1
        if not r.get("ok"):
            diagnostics["failed"] += 1
            continue
        sweep = r.get("sweep")
        if sweep == "determinism":
            diagnostics["sweep_rows"] += 1
        elif sweep is not None:
            continue                       # phrasing / truncation change the input
        diagnostics["contexts"].add(r.get("run_context"))
        stratum = captures[did].get("stratum")

        for q, a in (r.get("answers") or {}).items():
            if a.get("type") != "boolean":
                continue
            p = a["probability"]
            key = (did, r["arm"], r.get("question_set_id"), r.get("state_sha256"), q)
            target = designed if sweep == "determinism" else incidental
            g = target.get(key)
            if g is None:
                g = target[key] = Group(did, r["arm"], q, stratum)
            g.probabilities.append(p)

            if sweep is None and r.get("question_set_id") == primary_qsid:
                sk = (did, r["arm"], q)
                if sk not in seen_single:
                    seen_single.add(sk)
                    # Keyed by run_context: PREREGISTRATION section 4 forbids pooling
                    # live with synthetic, and the occupancy number is exactly where
                    # pooling would mislead -- the synthetic set is balanced by
                    # design and the live stream is not.
                    context = r.get("run_context") or "unknown"
                    single[context][r["arm"]][q].append(p)

    if designed:
        groups = [g for g in designed.values() if g.n >= min_repeats]
        diagnostics["source"] = "designed determinism sweep"
    else:
        groups = [g for g in incidental.values() if g.n >= min_repeats]
        diagnostics["source"] = ("incidental repeats (NOT a designed sweep)"
                                 if groups else "none")
    diagnostics["contexts"] = sorted(x for x in diagnostics["contexts"] if x)
    return groups, single, diagnostics


# --------------------------------------------------------------------------
# analysis (pure)
# --------------------------------------------------------------------------

@dataclass
class BandRow:
    lo: float
    hi: float
    n_groups: int
    n_flipping: int
    mean_pairwise: float

    @property
    def flip_rate(self) -> float | None:
        if self.n_groups < MIN_BUCKET:
            return None
        return self.n_flipping / self.n_groups


@dataclass
class ArmQuestion:
    arm: str
    question: str
    tau: float
    groups: list[Group]
    bands: list[BandRow]

    @property
    def n_groups(self) -> int:
        return len(self.groups)

    @property
    def n_calls(self) -> int:
        return sum(g.n for g in self.groups)

    @property
    def flipping(self) -> list[Group]:
        return [g for g in self.groups if not g.unanimous(self.tau)]

    @property
    def flip_rate(self) -> float:
        return len(self.flipping) / self.n_groups if self.groups else float("nan")

    @property
    def call_flip_rate(self) -> float:
        """Fraction of individual calls that dissent from their group's majority."""
        total = dissent = 0
        for g in self.groups:
            q = g.fraction_above(self.tau)
            minority = min(q, 1 - q)
            dissent += round(minority * g.n)
            total += g.n
        return dissent / total if total else float("nan")


def bucket(groups: Sequence[Group], tau: float) -> list[BandRow]:
    rows = []
    for lo, hi in BANDS:
        members = [g for g in groups if lo <= abs(g.mean - tau) < hi]
        flipping = [g for g in members if not g.unanimous(tau)]
        pw = ([g.pairwise_disagreement(tau) for g in members] or [float("nan")])
        rows.append(BandRow(lo, hi, len(members), len(flipping),
                            sum(pw) / len(pw) if members else float("nan")))
    return rows


def analyse(groups: Sequence[Group], arm: str, question: str, tau: float) -> ArmQuestion:
    subset = [g for g in groups if g.arm == arm and g.question == question]
    return ArmQuestion(arm, question, tau, list(subset), bucket(subset, tau))


def occupancy(scores: Sequence[float], tau: float) -> list[BandRow]:
    """How a realistic workload distributes around tau, from single-shot data.

    No repeats needed. This is the half of the picture that is available today:
    it cannot say how often a near-threshold item flips, only how many items are
    near the threshold at all. If that count is zero, the flip rate barely
    matters; if it is a third of the workload, it matters enormously.
    """
    rows = []
    for lo, hi in BANDS:
        n = sum(1 for p in scores if lo <= abs(p - tau) < hi)
        rows.append(BandRow(lo, hi, n, 0, float("nan")))
    return rows


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _taus(question: str, overrides: dict[str, list[float]], flat: list[float]) -> list[float]:
    if question in overrides:
        return overrides[question]
    if flat:
        return flat
    return DEFAULT_TAUS.get(question, [0.5])


def _band_table(rows: Sequence[BandRow], L: list[str], *, rates: bool) -> None:
    header = f"    {'|p - tau|':<14} {'items':>6}"
    if rates:
        header += f" {'flipped':>8} {'flip rate':>10} {'P(2 calls differ)':>18}"
    L.append(header)
    for r in rows:
        label = f"{r.lo:.2f} - {r.hi:.2f}" if r.hi <= 1.0 else f">= {r.lo:.2f}"
        line = f"    {label:<14} {r.n_groups:>6}"
        if rates:
            if r.n_groups == 0:
                line += f" {'-':>8} {'-':>10} {'-':>18}"
            elif r.flip_rate is None:
                line += (f" {r.n_flipping:>8} {'n<' + str(MIN_BUCKET):>10} "
                         f"{'n too small':>18}")
            else:
                line += (f" {r.n_flipping:>8} {r.flip_rate:>9.0%} "
                         f"{r.mean_pairwise:>17.1%}")
        L.append(line)


def render(results: list[ArmQuestion],
           single: dict[str, dict[str, dict[str, list[float]]]],
           diagnostics: dict[str, Any], *, surface: str,
           tau_map: dict[tuple[str, str], list[float]]) -> str:
    L: list[str] = []
    L.append("=" * 78)
    L.append("HOW OFTEN DOES THE SAME COMMAND GET A DIFFERENT ANSWER?")
    L.append("=" * 78)
    L.append("")
    L.append("Identical bytes, repeated calls. The question is not 'what is the flip rate'")
    L.append("-- there is no single flip rate -- but 'where in the score range do flips")
    L.append("live, and how much of a real workload lands there'.")
    L.append("")
    L.append(f"surface={surface}   repeat source: {diagnostics.get('source', 'none')}")
    L.append("")

    if not results:
        _render_no_repeats(L, single, diagnostics, tau_map)
        return "\n".join(L)

    if diagnostics.get("source", "").startswith("incidental"):
        L.append("!! These repeats were NOT produced by a determinism sweep. They are")
        L.append("   whatever duplicate rows happen to exist on identical state. Treat")
        L.append("   every rate below as indicative only.")
        L.append("")

    for r in sorted(results, key=lambda x: (x.question, x.arm, x.tau)):
        L.append("-" * 78)
        L.append(f"ARM {r.arm}   QUESTION {r.question}   tau={r.tau:.2f}")
        L.append("-" * 78)
        if r.n_groups < MIN_GROUPS:
            L.append(f"  only {r.n_groups} repeated item(s) -- below the {MIN_GROUPS} "
                     f"needed to say anything. Withheld.")
            L.append("")
            continue
        reps = [g.n for g in r.groups]
        L.append(f"  {r.n_groups} items x {min(reps)}-{max(reps)} repeats "
                 f"= {r.n_calls} calls")
        spreads = [g.spread for g in r.groups]
        sds = [g.sd for g in r.groups]
        sq = stats.quantiles(spreads, [0.5, 0.95])
        L.append(f"  probability spread (max-min) per item: median {sq['p50']:.3f}  "
                 f"p95 {sq['p95']:.3f}  worst {max(spreads):.3f}")
        L.append(f"  standard deviation per item          : median "
                 f"{stats.quantiles(sds, [0.5])['p50']:.3f}  worst {max(sds):.3f}")
        L.append("")
        L.append(f"  DECISION FLIP RATE at tau={r.tau:.2f}")
        L.append(f"    {len(r.flipping)}/{r.n_groups} items did not decide unanimously "
                 f"({r.flip_rate:.1%} of items)")
        L.append(f"    {r.call_flip_rate:.2%} of individual calls dissented from their "
                 f"item's majority")
        L.append("")
        L.append("  FLIP RATE BY DISTANCE FROM THE THRESHOLD -- the whole question:")
        _band_table(r.bands, L, rates=True)
        L.append("")
        L.append("  " + _interpret_bands(r))
        L.append("")

    _render_occupancy(L, single, tau_map)
    return "\n".join(L)


def _interpret_bands(r: ArmQuestion) -> str:
    measured = [b for b in r.bands if b.flip_rate is not None]
    if not measured:
        return ("every bucket is below the minimum count; the shape of the "
                "relationship is unmeasured. More repeats, not more analysis.")
    flipping = [b for b in measured if b.flip_rate > 0]
    if not flipping:
        return (f"no flips anywhere in {r.n_calls} calls. At this tau the arm is "
                f"decision-stable on this sample -- which is the precondition for "
                f"enforcing on it.")
    edge = max(b.hi for b in flipping)
    clean = [b for b in measured if b.lo >= edge]
    if clean and all(b.flip_rate == 0 for b in clean):
        return (f"flips are CONFINED to |p - tau| < {edge:.2f}; every measured bucket "
                f"beyond it is stable. Enforcement outside that band is reproducible, "
                f"and inside it the honest move is to ask rather than to decide.")
    return (f"flips reach out to |p - tau| >= {edge:.2f} and the far buckets are not "
            f"clean. That is the bad case: no band is safe, and the arm should not "
            f"gate anything until this is understood.")


def _render_no_repeats(L: list[str],
                       single: dict[str, dict[str, dict[str, list[float]]]],
                       diagnostics: dict[str, Any],
                       tau_map: dict[tuple[str, str], list[float]]) -> None:
    L.append("NOT ENOUGH REPEAT DATA. THE FLIP RATE IS UNMEASURED.")
    L.append("")
    L.append(f"  Scanned {diagnostics.get('run_rows', 0)} run rows across contexts "
             f"{diagnostics.get('contexts') or ['-']}.")
    L.append(f"  Found 0 items with >= {MIN_REPEATS} calls on byte-identical state.")
    L.append("")
    L.append("  This is the expected state until the determinism sweep is scheduled;")
    L.append("  it has never been run. Nothing below is a flip rate and no number here")
    L.append("  should be quoted as one.")
    L.append("")
    L.append("  To collect it (this spends real money on the cc_* arms -- estimate first):")
    L.append("      uv run src/replay.py --estimate")
    L.append("      uv run src/replay.py --determinism 20 --limit 10 --arms jev")
    L.append("")
    L.append("  20 repeats resolves a flip rate to 5 percentage points, which is enough")
    L.append("  to separate 'never' from 'sometimes' and not enough to put a decimal on")
    L.append("  'sometimes'. FINDINGS 2.3's two ten-call runs disagreed with each other,")
    L.append("  which is why the rate is quoted as uncharacterised rather than as 1-in-20.")
    L.append("")
    _render_occupancy(L, single, tau_map)


def _render_occupancy(L: list[str],
                      single: dict[str, dict[str, dict[str, list[float]]]],
                      tau_map: dict[tuple[str, str], list[float]]) -> None:
    L.append("-" * 78)
    L.append("BAND OCCUPANCY -- how much of the workload sits near the threshold")
    L.append("-" * 78)
    L.append("  Single-shot scores; no repeats required. This says how much the flip rate")
    L.append("  would matter, not what it is. A classifier that is unstable only within")
    L.append("  0.02 of tau is harmless if nothing lands there and unusable if a third of")
    L.append("  the workload does.")
    L.append("")
    if not single:
        L.append("  no scored decisions on disk.")
        return
    for context in sorted(single):
        L.append(f"  [{context}] -- reported separately; contexts are never pooled.")
        if context == "live":
            L.append("       THIS is the realistic-workload number. The others are not.")
        L.append("")
        for arm in sorted(single[context]):
            for question in sorted(single[context][arm]):
                scores = single[context][arm][question]
                for tau in (tau_map.get((arm, question))
                            or DEFAULT_TAUS.get(question, [0.5])):
                    L.append(f"  {context} / {arm} / {question} / tau={tau:.2f}   "
                             f"n={len(scores)} decisions")
                    rows = occupancy(scores, tau)
                    _band_table(rows, L, rates=False)
                    near = sum(r.n_groups for r in rows if r.hi <= 0.05)
                    if len(scores) < MIN_GROUPS:
                        L.append(f"    -> {near}/{len(scores)} within 0.05 of tau, but "
                                 f"n={len(scores)} is too small to call a workload.")
                    else:
                        L.append(f"    -> {near}/{len(scores)} decisions "
                                 f"({near / len(scores):.0%}) sit within 0.05 of tau: "
                                 f"the band where flips were seen.")
                    L.append("")
    L.append("  The synthetic set is balanced 1:1:1 by design, so its occupancy figure is")
    L.append("  an artefact of how it was written, not a workload. The live base rate is")
    L.append("  far more skewed and the live occupancy number is the one that decides")
    L.append("  whether enforcement is safe. It needs live captures, not more synthetic")
    L.append("  ones.")


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def parse_tau(values: Sequence[str]) -> tuple[list[float], dict[str, list[float]]]:
    """`--tau 0.5` applies everywhere; `--tau destructive=0.36` is per question."""
    flat: list[float] = []
    per_question: dict[str, list[float]] = defaultdict(list)
    for raw in values or []:
        if "=" in raw:
            q, _, v = raw.partition("=")
            per_question[q.strip()].append(float(v))
        else:
            flat.append(float(raw))
    return flat, dict(per_question)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Flip rate as a function of distance from the threshold.")
    ap.add_argument("--surface", default="pre_bash")
    ap.add_argument("--arm", help="default: every arm found")
    ap.add_argument("--question", help="default: every boolean question found")
    ap.add_argument("--tau", action="append", metavar="[QUESTION=]VALUE",
                    help="repeatable; defaults to 0.5 plus the FINDINGS 4b value")
    ap.add_argument("--min-repeats", type=int, default=MIN_REPEATS)
    ap.add_argument("--out", help="also write to reports/<name>")
    args = ap.parse_args()

    groups, single, diagnostics = collect(args.surface, min_repeats=args.min_repeats)
    flat, per_question = parse_tau(args.tau)

    arms = sorted({g.arm for g in groups}
                  | {a for ctx in single.values() for a in ctx})
    if args.arm:
        arms = [a for a in arms if a == args.arm]
    questions = sorted({g.question for g in groups}
                       | {q for ctx in single.values() for a in ctx.values() for q in a})
    if args.question:
        questions = [q for q in questions if q == args.question]

    tau_map: dict[tuple[str, str], list[float]] = {}
    results: list[ArmQuestion] = []
    for arm in arms:
        for question in questions:
            taus = _taus(question, per_question, flat)
            tau_map[(arm, question)] = taus
            for tau in taus:
                r = analyse(groups, arm, question, tau)
                if r.n_groups:
                    results.append(r)

    filtered = {
        ctx: {a: {q: v for q, v in per_arm.items() if q in questions}
              for a, per_arm in by_arm.items() if a in arms}
        for ctx, by_arm in single.items()
    }
    text = render(results, {c: v for c, v in filtered.items() if any(v.values())},
                  diagnostics, surface=args.surface, tau_map=tau_map)
    print(text)
    if args.out:
        paths.REPORTS.mkdir(parents=True, exist_ok=True)
        (paths.REPORTS / args.out).write_text(text, encoding="utf-8")
        print(f"\nwritten: {paths.REPORTS / args.out}")
    # Exit 1 when the flip rate remains unmeasured: this is the blocker for
    # enforcement, and a green exit code would misreport it as cleared.
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
