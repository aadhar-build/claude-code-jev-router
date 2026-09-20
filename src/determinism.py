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
FAR = 0.10             # |p - tau| beyond which a flip is no longer a boundary effect


# --------------------------------------------------------------------------
# collection
# --------------------------------------------------------------------------

@dataclass
class Group:
    """One (decision, arm, arm_config_id, question) repeated on identical bytes.

    `arm_config_id` and `origin_context` are part of the identity, not
    decoration. Without the first, a re-run under a changed configuration is
    reported as non-determinism -- which is precisely the conflation
    PREREGISTRATION A7.5 is stuck in ("the configuration changed the answer"
    and "the model is non-deterministic" are the same number), reproduced
    inside the instrument built to resolve it. Without the second, live and
    synthetic repeats pool, while the occupancy half of this same report is
    carefully keyed on run_context because section 4 forbids exactly that.

    `origin_context` is the CAPTURE's run_context -- where the decision point
    came from -- not the run row's. Every designed-sweep row has
    run_context == "replay", so keying on the row's own value separates
    nothing at all.
    """
    decision_id: str
    arm: str
    question: str
    stratum: str | None
    # `probabilities` keeps its position: it was the fifth positional field
    # before JEV-16 and existing callers construct Groups positionally.
    probabilities: list[float] = field(default_factory=list)
    arm_config_id: str | None = None
    origin_context: str | None = None

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

    A repeat group is keyed on (decision_id, arm, arm_config_id,
    origin_context, question_set_id, state_sha256, question): identical bytes,
    identical question, same arm IN THE SAME CONFIGURATION, from the same kind
    of capture. Dropping either of the middle two -- as this did until JEV-16 --
    reports a config change, or the difference between the balanced synthetic
    set and live traffic, as non-determinism. Rows written
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
        origin = captures[did].get("run_context") or "unknown"

        for q, a in (r.get("answers") or {}).items():
            if a.get("type") != "boolean":
                continue
            p = a["probability"]
            key = (did, r["arm"], r.get("arm_config_id"), origin,
                   r.get("question_set_id"), r.get("state_sha256"), q)
            target = designed if sweep == "determinism" else incidental
            g = target.get(key)
            if g is None:
                g = target[key] = Group(did, r["arm"], q, stratum,
                                        arm_config_id=r.get("arm_config_id"),
                                        origin_context=origin)
            g.probabilities.append(p)

            if sweep is None and r.get("question_set_id") == primary_qsid:
                sk = (did, r["arm"], q)
                if sk not in seen_single:
                    seen_single.add(sk)
                    # Keyed by run_context: PREREGISTRATION section 4 forbids pooling
                    # live with synthetic, and the occupancy number is exactly where
                    # pooling would mislead -- the synthetic set is balanced by
                    # design and the live stream is not.
                    # Keyed by (arm, arm_config_id), not by arm: 371 live
                    # cc_haiku45 rows are v1 and 119 are v2 (A7.4), and an
                    # occupancy table that pools them describes a
                    # configuration nobody ran. Same defect as the group key
                    # above, one table further down.
                    context = r.get("run_context") or "unknown"
                    single[context][(r["arm"], r.get("arm_config_id"))][q].append(p)

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
    arm_config_id: str | None = None
    origin_context: str | None = None

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


def analyse(groups: Sequence[Group], arm: str, question: str, tau: float, *,
            arm_config_id: str | None, origin: str | None) -> ArmQuestion:
    """One arm, one configuration, one origin, one question, one tau.

    `arm_config_id` and `origin` are REQUIRED keyword arguments and there is no
    "all" value, deliberately. This function used to filter on (arm, question)
    alone, which silently pooled two configurations of one arm and pooled live
    with synthetic; a default that restored either would restore the defect for
    every caller that forgot to pass it.
    """
    subset = [g for g in groups
              if g.arm == arm and g.question == question
              and g.arm_config_id == arm_config_id
              and g.origin_context == origin]
    return ArmQuestion(arm, question, tau, list(subset), bucket(subset, tau),
                       arm_config_id=arm_config_id, origin_context=origin)


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

    for r in sorted(results, key=lambda x: (x.question, x.arm,
                                           x.arm_config_id or "", x.origin_context or "", x.tau)):
        L.append("-" * 78)
        L.append(f"ARM {r.arm} [{r.arm_config_id}]   from {r.origin_context} captures")
        L.append(f"QUESTION {r.question}   tau={r.tau:.2f}")
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
    """Read the shape, using EVERY bucket.

    Deliberately counts flips in thin buckets too. A bucket with 4 items, all of
    which flipped, is not enough to put a rate on -- the table correctly refuses
    -- but it is emphatically not evidence of stability, and an earlier version
    of this function that ignored thin buckets reported "no flips anywhere"
    over a sample in which every flip had occurred.
    """
    populated = [b for b in r.bands if b.n_groups]
    if not populated:
        return "no items at all at this threshold."
    flipping = [b for b in populated if b.n_flipping]
    if not flipping:
        thin = [b for b in populated if b.flip_rate is None]
        tail = (f" ({len(thin)} bucket(s) hold fewer than {MIN_BUCKET} items, so "
                f"'stable' there means 'no flip seen', not 'flip rate near zero')"
                if thin else "")
        return (f"no flips anywhere in {r.n_calls} calls. At this tau the arm is "
                f"decision-stable on this sample{tail} -- which is the precondition "
                f"for enforcing on it.")

    # "Far" is fixed at 0.10 rather than derived, so the bad case is reachable:
    # an edge computed from the flipping buckets themselves can never have flips
    # beyond it, and a test for "flips everywhere" against such an edge would
    # always pass vacuously.
    far_flipping = [b for b in flipping if b.lo >= FAR]
    edge = max(b.hi for b in flipping)
    beyond = [b for b in populated if b.lo >= edge]
    resolved = all(b.flip_rate is not None for b in flipping)
    caveat = "" if resolved else (
        f" The affected bucket(s) hold fewer than {MIN_BUCKET} items, so the"
        f" concentration is visible but the rate inside the band is not yet"
        f" resolvable -- that needs more repeated items near tau, not more analysis.")

    if far_flipping:
        return (f"flips occur out at |p - tau| >= {min(b.lo for b in far_flipping):.2f}, "
                f"far from the threshold. That is the bad case: the wobble is not a "
                f"boundary effect, no band is clean, and the arm should not gate "
                f"anything until this is understood.{caveat}")
    if beyond and all(b.n_flipping == 0 for b in beyond):
        return (f"flips are CONFINED to |p - tau| < {edge:.2f}; every populated bucket "
                f"beyond it was unanimous. Enforcement outside that band is "
                f"reproducible, and inside it the honest move is to ask rather than "
                f"to decide.{caveat}")
    if not beyond:
        return (f"every populated bucket reaches only to |p - tau| < {edge:.2f}, so "
                f"there is no far region to compare against. The concentration "
                f"hypothesis is untested here.{caveat}")
    return (f"flips reach |p - tau| < {edge:.2f} and there is no clean region beyond "
            f"them to compare against. Inconclusive on the concentration "
            f"hypothesis.{caveat}")


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
    L.append("      uv run src/replay.py --determinism 20 --arms jev \\")
    L.append("          --context synthetic --ids syn-syn-0121,syn-syn-0242")
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
        for key in sorted(single[context], key=lambda t: (t[0], t[1] or "")):
            arm, acid = key
            label = f"{arm} [{acid}]" if acid else arm
            for question in sorted(single[context][key]):
                scores = single[context][key][question]
                for tau in (tau_map.get((arm, question))
                            or DEFAULT_TAUS.get(question, [0.5])):
                    L.append(f"  {context} / {label} / {question} / tau={tau:.2f}   "
                             f"n={len(scores)} decisions")
                    rows = occupancy(scores, tau)
                    _band_table(rows, L, rates=False)
                    near = sum(r.n_groups for r in rows if r.hi <= 0.05)
                    if len(scores) < MIN_GROUPS:
                        L.append(f"    -> {near}/{len(scores)} within 0.05 of tau, but "
                                 f"n={len(scores)} is too small to call a workload.")
                    else:
                        L.append(f"    -> {near}/{len(scores)} decisions "
                                 f"({near / len(scores):.0%}) sit within 0.05 of tau.")
                    L.append("")
    L.append("  What 'within 0.05 of tau' is and is not: FINDINGS 2.3 saw flips within")
    L.append("  0.05 of tau=0.50, on items whose probability was genuinely uncertain. It")
    L.append("  also measured sd 0.000 at p=0.97 -- Jev does not wobble when it is")
    L.append("  confident. Distance from tau and intrinsic uncertainty coincide at")
    L.append("  tau=0.50 and come apart at tau=0.95, where a crowded band may be crowded")
    L.append("  with items that are perfectly stable. Read occupancy as an EXPOSURE")
    L.append("  UPPER BOUND, not as a flip count; only the sweep separates the two, and")
    L.append("  when it lands the flip-rate-versus-distance table must be read per tau,")
    L.append("  never pooled across them.")
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
                  | {a for ctx in single.values() for (a, _acid) in ctx})
    if args.arm:
        arms = [a for a in arms if a == args.arm]
    questions = sorted({g.question for g in groups}
                       | {q for ctx in single.values() for per in ctx.values() for q in per})
    if args.question:
        questions = [q for q in questions if q == args.question]

    # The cells are (arm, arm_config_id, origin) triples, never (arm) alone.
    cells = sorted({(g.arm, g.arm_config_id, g.origin_context) for g in groups})
    if args.arm:
        cells = [c for c in cells if c[0] == args.arm]

    tau_map: dict[tuple[str, str], list[float]] = {}
    results: list[ArmQuestion] = []
    for arm in arms:
        for question in questions:
            taus = _taus(question, per_question, flat)
            tau_map[(arm, question)] = taus
    for arm, acid, origin in cells:
        for question in questions:
            for tau in tau_map.get((arm, question)) or _taus(question, per_question, flat):
                r = analyse(groups, arm, question, tau,
                            arm_config_id=acid, origin=origin)
                if r.n_groups:
                    results.append(r)

    filtered = {
        ctx: {key: {q: v for q, v in per_arm.items() if q in questions}
              for key, per_arm in by_arm.items() if key[0] in arms}
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
