#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The accuracy gate -- the thing that lets us say an optimization did not make
the agent worse, and refuses to say it when the evidence is too weak.

SPEC §6. Two classes, because one is nearly free and one costs real money.

    Class 1 -- judge-side. Replay the captures already on disk under the
               changed code path and compare against recorded baselines.
               Unit: (decision_id, question_name). Scored on band-flip rate at
               tau, AUC, and kappa.  ~600-2,000 Jev calls, pennies.

    Class 2 -- agent-side. Re-execute a fixture suite, score the FINAL DIFF.
               Unit: the task. Lives in `fixture_executor.py`; this module owns
               its CLI, its exit code and its power statement.

THE EXIT CODES ARE THE MOST IMPORTANT MECHANICAL DETAIL IN THIS FILE.

    0  ran clean, nothing to act on
    1  COULD NOT RUN (no key, no network, timeout, a required input absent
                      from disk, a criterion that could not be evaluated)
    2  invoked wrong
    3  ran and found a regression

A guard that could not run must never be readable as a guard that passed.
Collapsing 1 into 0 is the single failure that would make the whole of SPEC §6
decorative, so it is spelled out here, asserted in `tests/test_accuracy_gate.py`
for every path that can produce it, and never defaulted.

Precedence when several apply: 2 beats everything (we cannot trust an
invocation we did not understand), then 3 (a regression found is a fact, and it
stays a fact even if some other criterion could not be evaluated), then 1, then
0. `3 > 1` is deliberate: finding a regression IS running.

### Why "not evaluable" is a first-class status and not a shrug

Class 1 has three criteria. AUC needs a labelled subset. `data/labels/` is
EMPTY today, so on this repository, right now, the AUC criterion is
NOT_EVALUABLE and this gate exits 1 -- not 0. That is not a bug to be smoothed
over with a default; it is the gate reporting, accurately, that it is currently
two-thirds of a gate. The moment someone adds `--allow-unevaluable` to make
CI green, the gate is decorative again.

### What this gate does NOT claim

It does not prove equivalence. Green means "no large regression found", never
"quality preserved". `power_statement()` prints that sentence itself, computed
for the actual n and k rather than quoted from the SPEC, so nobody has to
remember it.

Usage:

    uv run src/accuracy_gate.py class1 \\
        --baseline data/runs/2026-09-20.jsonl \\
        --treatment /tmp/replay-under-change.jsonl \\
        --arm jev --tau destructive=0.36 --tau needs_review=0.95 \\
        --labels data/labels

    uv run src/accuracy_gate.py class2 \\
        --suite tests/fixtures/accuracy/suite-v1 \\
        --baseline-arm baseline --treatment-arm treatment

Class 2 runs its (task, arm, seed) units in a RANDOMISED, arm-interleaved
order (JEV-29). The seed is printed; pass `--order-seed N` to reproduce a run
exactly. Running the arms in blocks would let a sequence-aware judge learn the
arm by counting rather than by reading, which is a broken blind that no
payload check can see.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stats  # noqa: E402

# ---------------------------------------------------------------------------
# Exit codes. Named once, never inlined.
# ---------------------------------------------------------------------------

EXIT_CLEAN = 0
EXIT_COULD_NOT_RUN = 1
EXIT_INVOKED_WRONG = 2
EXIT_REGRESSION = 3

EXIT_NAMES = {
    EXIT_CLEAN: "CLEAN (ran, nothing to act on)",
    EXIT_COULD_NOT_RUN: "COULD NOT RUN (this is NOT a pass)",
    EXIT_INVOKED_WRONG: "INVOKED WRONG",
    EXIT_REGRESSION: "REGRESSION FOUND",
}

# Precedence: the worse news wins, and "invoked wrong" is the worst news
# because it means we do not know what we measured.
_PRECEDENCE = [EXIT_INVOKED_WRONG, EXIT_REGRESSION, EXIT_COULD_NOT_RUN, EXIT_CLEAN]


def worst(*codes: int) -> int:
    for code in _PRECEDENCE:
        if code in codes:
            return code
    return EXIT_CLEAN


class InvokedWrong(RuntimeError):
    """Exit 2. The invocation was not understood, so nothing was measured."""


class CouldNotRun(RuntimeError):
    """Exit 1. The gate was invoked correctly and still could not produce a
    verdict -- no key, no network, no corpus, a criterion with no input."""


# ---------------------------------------------------------------------------
# SPEC §6 Class 1 thresholds, frozen here so a reader can find them in one place
# ---------------------------------------------------------------------------

BAND_FLIP_BLOCK = 0.05      # > 5% of paired units blocks
BAND_FLIP_WARN = 0.02       # 2-5% is report-only
AUC_DROP_BLOCK = 0.03       # a drop larger than this blocks
# Minimum labelled units PER QUESTION before AUC on that question means
# anything. Without this, two hand-written labels satisfy the criterion.
# See `_auc_coverage` for the exploit this closes.
AUC_MIN_LABELLED = 30
KAPPA_BLOCK = 0.80          # below this blocks

PASS = "pass"
WARN = "warn"
FAIL = "fail"
NOT_EVALUABLE = "not_evaluable"


@dataclass
class Criterion:
    """One SPEC §6 criterion and how it came out.

    `status` is four-valued on purpose. A three-valued status forces
    "could not evaluate" to be encoded as either a pass or a failure, and both
    of those are lies.
    """
    name: str
    status: str
    value: float | None = None
    threshold: float | None = None
    detail: str = ""

    @property
    def exit_code(self) -> int:
        if self.status == FAIL:
            return EXIT_REGRESSION
        if self.status == NOT_EVALUABLE:
            return EXIT_COULD_NOT_RUN
        return EXIT_CLEAN

    def line(self) -> str:
        mark = {PASS: "ok  ", WARN: "WARN", FAIL: "FAIL", NOT_EVALUABLE: "n/a "}[self.status]
        value = "        -" if self.value is None else f"{self.value:9.4f}"
        thr = "" if self.threshold is None else f"  (threshold {self.threshold})"
        return f"  {mark}  {self.name:<28}{value}{thr}  {self.detail}"


# ---------------------------------------------------------------------------
# kappa, written here rather than imported
# ---------------------------------------------------------------------------

def cohens_kappa_bool(a: Sequence[bool], b: Sequence[bool]) -> float:
    """Cohen's kappa for two paired boolean raters.

    `src/stats.py` has `cohens_kappa`, and it is not used here. Its agreement
    functions were written for the pre-pivot inter-rater question ("do Jev and
    Opus agree?") and the SPEC's pivot retired that question; the brief for this
    work says explicitly not to build on them. This is ten lines, it is tested
    against hand-computed values, and it does not couple this gate to a dead
    analysis. Duplication is the cheaper of the two mistakes available here.

    Returns nan for an empty input, and 1.0 for the degenerate case where both
    raters are constant and identical (perfect agreement with no variance to
    correct for). The degenerate 0/0 is resolved to 1.0 rather than nan because
    "baseline and treatment both answered False everywhere" is genuinely total
    agreement, and a nan there would silently become NOT_EVALUABLE.
    """
    n = len(a)
    if n == 0 or n != len(b):
        return float("nan")
    agree = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(1 for x in a if x) / n
    pb = sum(1 for x in b if x) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected >= 1.0:
        return 1.0 if agree >= 1.0 else 0.0
    return (agree - expected) / (1 - expected)


# ---------------------------------------------------------------------------
# Class 1
# ---------------------------------------------------------------------------

@dataclass
class Class1Result:
    unit: str = "(decision_id, question_name)"
    arm: str = ""
    question_set_ids: list[str] = field(default_factory=list)
    n_paired: int = 0
    n_baseline_units: int = 0
    n_treatment_units: int = 0
    attrition: dict[str, int] = field(default_factory=dict)
    band_flips: int = 0
    band_flip_rate: float = 0.0          # pooled, reported but NEVER blocked on
    flips_by_question: dict[str, int] = field(default_factory=dict)
    n_by_question: dict[str, int] = field(default_factory=dict)
    flip_rate_by_question: dict[str, float] = field(default_factory=dict)
    kappa_by_question: dict[str, float] = field(default_factory=dict)
    kappa: float = float("nan")          # pooled, reported but NEVER blocked on
    auc_baseline: dict[str, float] = field(default_factory=dict)
    auc_treatment: dict[str, float] = field(default_factory=dict)
    auc_n_labelled: dict[str, int] = field(default_factory=dict)
    criteria: list[Criterion] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return worst(*(c.exit_code for c in self.criteria)) if self.criteria else EXIT_COULD_NOT_RUN


def boolean_answers(row: dict) -> dict[str, float]:
    """The boolean questions of one run row, as {question: probability}.

    Non-boolean answers are skipped: a band is only defined against a tau, and
    a tau is only defined for a probability.
    """
    out: dict[str, float] = {}
    for question, answer in (row.get("answers") or {}).items():
        if isinstance(answer, dict) and answer.get("type") == "boolean":
            probability = answer.get("probability")
            if isinstance(probability, (int, float)):
                out[question] = float(probability)
    return out


def index_units(rows: Iterable[dict], arm: str | None) -> tuple[dict, dict[str, int], set[str]]:
    """Index run rows by (decision_id, question) for one arm.

    Returns (units, counters, question_set_ids). `units` maps the pair to the
    probability. Rows with `ok: false` are NOT indexed -- they are counted as
    attrition, because a failed call has no answer to compare and pretending
    otherwise would quietly shrink the denominator.

    The last attempt wins on a duplicate key. Rows carry `attempt`, and a retry
    is the answer that stood.
    """
    units: dict[tuple[str, str], float] = {}
    attempts: dict[tuple[str, str], int] = {}
    counters = {"rows": 0, "not_ok": 0, "other_arm": 0, "no_boolean_answers": 0}
    question_sets: set[str] = set()
    for row in rows:
        if arm is not None and row.get("arm") != arm:
            counters["other_arm"] += 1
            continue
        counters["rows"] += 1
        decision_id = row.get("decision_id")
        if not decision_id:
            continue
        question_sets.add(str(row.get("question_set_id")))
        if not row.get("ok"):
            counters["not_ok"] += 1
            continue
        answers = boolean_answers(row)
        if not answers:
            counters["no_boolean_answers"] += 1
            continue
        attempt = int(row.get("attempt") or 0)
        for question, probability in answers.items():
            key = (decision_id, question)
            if key in units and attempts.get(key, -1) > attempt:
                continue
            units[key] = probability
            attempts[key] = attempt
    return units, counters, question_sets


def load_labels(source: Path | None) -> dict[tuple[str, str], bool]:
    """Ground-truth labels, keyed the same way the units are.

    A label row is {decision_id, question, label} where label is truthy/falsy.
    Absent or empty -> {} -> the AUC criterion is NOT_EVALUABLE, which is exit 1.
    """
    if source is None:
        return {}
    files: list[Path]
    if source.is_dir():
        files = sorted(source.glob("*.jsonl"))
    elif source.exists():
        files = [source]
    else:
        raise InvokedWrong(f"--labels path does not exist: {source}")
    out: dict[tuple[str, str], bool] = {}
    for path in files:
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            decision_id = row.get("decision_id")
            question = row.get("question") or row.get("question_name")
            if decision_id and question and "label" in row:
                out[(str(decision_id), str(question))] = bool(row["label"])
    return out


def class1_compare(
    baseline_rows: Iterable[dict],
    treatment_rows: Iterable[dict],
    taus: dict[str, float],
    *,
    arm: str | None = None,
    labels: dict[tuple[str, str], bool] | None = None,
) -> Class1Result:
    """Compare a recorded baseline against a replay under the changed code path.

    Pure: takes rows, returns a result. No file reads, no exits, no printing --
    so every branch below is reachable from a unit test with a list literal.

    Raises InvokedWrong (exit 2) when the comparison is not well-formed:
      - the two sides are not the same question-set version. A variant is a NEW
        ROW, not a comparison; scoring across versions would report a
        deliberate change of question as a regression.
      - a question is present in the data with no tau supplied. There is no
        frozen tau file in this repository (`verdict.py` derives Youden taus at
        analysis time, `canary.py` defaults to 0.5, `determinism.py` carries
        {destructive: 0.36, needs_review: 0.95} as ITS defaults). Picking one
        of those silently would make the band-flip number depend on which file
        the author happened to read. tau is an input.

    Raises CouldNotRun (exit 1) when nothing could be paired.

    Note on the join key: the pair is (decision_id, question_name) and NEVER
    state_sha256. State trimming changes the state hash BY DESIGN -- that is the
    optimization under test -- so a hash join would find zero pairs and report a
    clean run over an empty set.
    """
    labels = labels or {}
    base_units, base_counts, base_qsets = index_units(baseline_rows, arm)
    treat_units, treat_counts, treat_qsets = index_units(treatment_rows, arm)

    if base_qsets and treat_qsets and base_qsets != treat_qsets:
        raise InvokedWrong(
            "question_set_id differs between baseline and treatment "
            f"({sorted(base_qsets)} vs {sorted(treat_qsets)}). A question-set "
            "variant is a new row, not a comparison."
        )

    paired = sorted(set(base_units) & set(treat_units))
    questions = sorted({question for _, question in paired})
    missing_tau = [q for q in questions if q not in taus]
    if missing_tau:
        raise InvokedWrong(
            f"no tau supplied for question(s) {missing_tau}. There is no frozen "
            "tau file in this repository; tau is a required input, not a default."
        )

    result = Class1Result(
        arm=arm or "(all)",
        question_set_ids=sorted(base_qsets | treat_qsets),
        n_paired=len(paired),
        n_baseline_units=len(base_units),
        n_treatment_units=len(treat_units),
        attrition={
            "baseline_rows_not_ok": base_counts["not_ok"],
            "treatment_rows_not_ok": treat_counts["not_ok"],
            "in_baseline_missing_from_treatment": len(set(base_units) - set(treat_units)),
            "in_treatment_missing_from_baseline": len(set(treat_units) - set(base_units)),
        },
    )

    if not paired:
        raise CouldNotRun(
            "no (decision_id, question_name) pair is present and ok in both arms "
            f"(baseline units {len(base_units)}, treatment units {len(treat_units)}). "
            "Nothing was compared."
        )

    # --- band flips at tau, PER QUESTION -----------------------------------
    #
    # Every criterion below is scored per question and blocked on the WORST
    # question, with the pooled figure kept only as a report line.
    #
    # Pooling is not a stylistic choice here, it is a hole. Take this corpus's
    # own shape -- and note that a firing rate is meaningless without the tau
    # it was measured at, because it IS a function of tau. Measured over
    # data/runs/2026-09-20.jsonl, arm=jev, ok rows deduplicated to units,
    # n=567 per question:
    #
    #     destructive    at its tau of 0.36    fires on  5.6% of units
    #     needs_review   at its tau of 0.95    fires on  4.6% of units
    #     needs_review   at tau 0.5            fires on 52.9% of units
    #
    # This comment used to read "`destructive` fires on roughly 5% of units,
    # `needs_review` on roughly half", which quietly took its first figure at
    # one tau and its second at another: "roughly half" is needs_review at
    # tau=0.5, NOT at the 0.95 this gate actually uses. At the taus in play the
    # two questions fire at nearly the SAME rate, so the asymmetry below is
    # carried by the worked example, not by a difference in base rates.
    #
    # The hole is real either way. Suppose a change turns `destructive` into noise while
    # leaving `needs_review` byte-identical. Per question that is kappa ~ 0 on
    # `destructive` -- the question the gate most exists to protect, destroyed.
    # Pooled it is kappa ~ 0.88 and a ~4.75% flip rate: a PASS and a WARN. The
    # gate would go green on the one failure it was built to catch, because the
    # untouched majority question drowns the broken minority one.
    base_bands: list[bool] = []
    treat_bands: list[bool] = []
    bands_by_question: dict[str, tuple[list[bool], list[bool]]] = {}
    for decision_id, question in paired:
        tau = taus[question]
        b = base_units[(decision_id, question)] >= tau
        t = treat_units[(decision_id, question)] >= tau
        base_bands.append(b)
        treat_bands.append(t)
        pair = bands_by_question.setdefault(question, ([], []))
        pair[0].append(b)
        pair[1].append(t)
        if b != t:
            result.band_flips += 1
            result.flips_by_question[question] = result.flips_by_question.get(question, 0) + 1
    result.band_flip_rate = result.band_flips / len(paired)

    for question, (b_list, t_list) in bands_by_question.items():
        result.n_by_question[question] = len(b_list)
        result.flips_by_question.setdefault(question, 0)
        result.flip_rate_by_question[question] = (
            result.flips_by_question[question] / len(b_list))
        result.kappa_by_question[question] = cohens_kappa_bool(b_list, t_list)

    worst_question = max(result.flip_rate_by_question,
                         key=lambda q: result.flip_rate_by_question[q])
    worst_rate = result.flip_rate_by_question[worst_question]
    where = (f"worst question {worst_question} "
             f"{result.flips_by_question[worst_question]}/{result.n_by_question[worst_question]}"
             f"; pooled {result.band_flip_rate:.4f} over {len(paired)}")
    if worst_rate > BAND_FLIP_BLOCK:
        status, detail = FAIL, where
    elif worst_rate >= BAND_FLIP_WARN:
        status, detail = WARN, where + " -- report-only band (2-5%), not a block"
    else:
        status, detail = PASS, where
    result.criteria.append(
        Criterion("band-flip rate at tau (worst q)", status, worst_rate,
                  BAND_FLIP_BLOCK, detail))

    # --- kappa, PER QUESTION, blocked on the worst -------------------------
    result.kappa = cohens_kappa_bool(base_bands, treat_bands)
    evaluable_kappas = {q: k for q, k in result.kappa_by_question.items()
                        if not math.isnan(k)}
    if not evaluable_kappas:
        result.criteria.append(
            Criterion("kappa (worst question)", NOT_EVALUABLE, None, KAPPA_BLOCK,
                      "undefined on every question in this sample"))
    else:
        worst_kappa_q = min(evaluable_kappas, key=lambda q: evaluable_kappas[q])
        worst_kappa = evaluable_kappas[worst_kappa_q]
        k_status = FAIL if worst_kappa < KAPPA_BLOCK else PASS
        result.criteria.append(Criterion(
            "kappa (worst question)", k_status, worst_kappa, KAPPA_BLOCK,
            f"worst question {worst_kappa_q} n={result.n_by_question[worst_kappa_q]}"
            f"; pooled {result.kappa:.4f}"))

    # --- AUC, on the labelled subset only ----------------------------------
    worst_drop: float | None = None
    # PER QUESTION, not a single global flag. The single flag was a hole: any
    # one question with one positive and one negative label turned the whole
    # criterion from NOT_EVALUABLE to PASS -- including for questions carrying
    # no labels at all. Reproduced 2026-09-21 with TWO fabricated labels on
    # `needs_review`, with `destructive` (the safety-critical question)
    # entirely unlabelled: the gate printed `exit 0 -- CLEAN`.
    evaluable: set[str] = set()
    under_labelled: list[str] = []
    unlabelled: list[str] = []
    for question in questions:
        pos_b: list[float] = []
        neg_b: list[float] = []
        pos_t: list[float] = []
        neg_t: list[float] = []
        for decision_id, q in paired:
            if q != question:
                continue
            label = labels.get((decision_id, q))
            if label is None:
                continue
            (pos_b if label else neg_b).append(base_units[(decision_id, q)])
            (pos_t if label else neg_t).append(treat_units[(decision_id, q)])
        n_labelled = len(pos_b) + len(neg_b)
        result.auc_n_labelled[question] = n_labelled
        if not pos_b or not neg_b:
            # AUC needs both classes present. One-class labels are not a
            # degenerate 0.5 -- they are no measurement at all.
            continue
        if n_labelled < AUC_MIN_LABELLED:
            # Labelled, but not enough to mean anything. This is NOT a pass and
            # NOT silence -- it is recorded and it makes the criterion
            # unevaluable, exactly like no labels at all.
            under_labelled.append(f"{question} n={n_labelled}<{AUC_MIN_LABELLED}")
            continue
        evaluable.add(question)
        a_b = stats.auc(pos_b, neg_b)
        a_t = stats.auc(pos_t, neg_t)
        result.auc_baseline[question] = a_b
        result.auc_treatment[question] = a_t
        drop = a_b - a_t
        worst_drop = drop if worst_drop is None else max(worst_drop, drop)

    # EVERY question in the paired data must be adequately labelled. A question
    # that is simply absent from the labels used to vanish from this loop and
    # was therefore invisible -- the gate reported on the questions it could
    # see and said nothing about the ones it could not.
    for question in questions:
        if question in evaluable:
            continue
        if result.auc_n_labelled.get(question, 0) == 0:
            unlabelled.append(question)

    gaps = unlabelled + under_labelled
    if gaps:
        detail = (
            f"NOT evaluable on {len(gaps)} of {len(questions)} question(s): "
            + "; ".join(sorted(gaps))
            + f". Every question needs >= {AUC_MIN_LABELLED} labelled units "
              "with both classes present. A question with no labels is a "
              "MEASUREMENT GAP, not a pass"
        )
        if evaluable:
            detail += (f". {len(evaluable)} question(s) WERE evaluable "
                       "-- that does not cover the rest")
        result.criteria.append(Criterion(
            "AUC drop vs baseline", NOT_EVALUABLE, None, AUC_DROP_BLOCK, detail))
    else:
        a_status = FAIL if worst_drop > AUC_DROP_BLOCK else PASS
        labelled = ", ".join(f"{q} n={result.auc_n_labelled[q]}" for q in result.auc_baseline)
        result.criteria.append(Criterion(
            "AUC drop vs baseline", a_status, worst_drop, AUC_DROP_BLOCK,
            f"worst over questions ({labelled})"))

    return result


def render_class1(result: Class1Result) -> str:
    out: list[str] = []
    out.append("=== Class 1 -- judge-side regression (SPEC §6) ===")
    out.append(f"  unit                {result.unit}")
    out.append(f"  arm                 {result.arm}")
    out.append(f"  question set(s)     {', '.join(result.question_set_ids) or '(none)'}")
    out.append(f"  paired units        {result.n_paired} "
               f"(baseline {result.n_baseline_units}, treatment {result.n_treatment_units})")
    out.append("  attrition           " + ", ".join(
        f"{k}={v}" for k, v in sorted(result.attrition.items())))
    if result.flips_by_question:
        out.append("  per question        " + "; ".join(
            f"{q}: {result.flips_by_question[q]}/{result.n_by_question.get(q, 0)} flipped, "
            f"kappa={result.kappa_by_question.get(q, float('nan')):.3f}"
            for q in sorted(result.flips_by_question)))
        out.append("  (blocked on the WORST question -- pooling lets a minority")
        out.append("   question be destroyed while the majority one carries the score)")
    out.append("")
    for criterion in result.criteria:
        out.append(criterion.line())
    out.append("")
    out.append(class1_limitation(result))
    return "\n".join(out)


def class1_limitation(result: Class1Result) -> str:
    """Class 1's own limitation, printed by Class 1 itself.

    The resolution figure is computed from the SMALLEST question, not from the
    pooled total, because the block is per question. Quoting the pooled number
    would overstate what the gate can see on the rarest question -- which, on
    this corpus, is the safety-critical one.
    """
    if result.n_by_question:
        question = min(result.n_by_question, key=lambda q: result.n_by_question[q])
        n = result.n_by_question[question]
        where = f"its smallest question ({question}, n={n})"
    else:
        question, n, where = "", result.n_paired, f"n={result.n_paired}"
    return (
        "  LIMITATION: Class 1 replays captures that ALREADY EXIST. It measures\n"
        "  the judge under a changed code path -- it does not re-run the coding\n"
        "  agent and says nothing about what the agent would now do.\n"
        f"  {result.n_paired} paired units over {len(result.n_by_question)} question(s). On\n"
        f"  {where}, a change affecting fewer than roughly "
        f"{max(1, int(BAND_FLIP_BLOCK * n)) + 1} units\n"
        "  cannot cross the 5% band-flip block.")


# ---------------------------------------------------------------------------
# The power statement -- computed, not quoted
# ---------------------------------------------------------------------------

def detection_probability(n_affected: int, k: int, per_seed_fail: float) -> float:
    """P(the Class 2 block rule fires) for a regression affecting n_affected tasks.

    The block rule is: a task that passes in ALL baseline seeds and fails in ALL
    treatment seeds. For one affected task with per-seed failure probability p
    under treatment, that is p**k. Over m independent affected tasks,
    P(at least one) = 1 - (1 - p**k)**m.

    This assumes the baseline passes the task in all k seeds -- i.e. it is an
    upper bound on power, and the real number is lower wherever the baseline is
    itself flaky. Stated rather than hidden.
    """
    if k <= 0 or n_affected <= 0:
        return 0.0
    p = max(0.0, min(1.0, per_seed_fail))
    return 1.0 - (1.0 - p ** k) ** n_affected


def power_statement(n_tasks: int, k: int) -> str:
    """The sentence the SPEC requires, plus the arithmetic behind it.

    SPEC §2: "Not 'quality is preserved.' The guard FAILS TO DETECT a regression
    at a stated power." This states it for the actual n and k rather than
    quoting the ~20-task figure, because a 6-task smoke run has very different
    power from a 20-task nightly and both use this function.
    """
    rows = []
    for p in (1.0, 0.7):
        for m in sorted({1, max(1, n_tasks // 3), n_tasks}):
            rows.append((m, p, detection_probability(m, k, p)))
    lines = [
        "  POWER -- what this run could and could not have detected:",
        f"    n = {n_tasks} tasks, k = {k} seeds per arm.",
        "    A regression is DETECTED only when a task passes in every baseline",
        "    seed and fails in every treatment seed.",
        "",
        "      affected tasks   per-seed failure   P(detected)",
    ]
    for m, p, prob in rows:
        lines.append(f"      {m:>14}   {p:>16.2f}   {prob:>11.3f}")
    lines += [
        "",
        "    (Upper bound: it assumes the baseline itself passes all k seeds.",
        "     Where the baseline is flaky, the real power is lower.)",
        "",
        "  A GREEN CLASS 2 MEANS \"NO LARGE REGRESSION FOUND\", NEVER \"QUALITY",
        "  PRESERVED\". At this suite size the gate reliably catches only",
        "  regressions affecting roughly a third of tasks or more.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise CouldNotRun(f"corpus not on disk: {path}")
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw:
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    if not rows:
        raise CouldNotRun(f"corpus is empty: {path}")
    return rows


def _parse_taus(values: list[str] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in values or []:
        if "=" not in item:
            raise InvokedWrong(f"--tau expects question=value, got {item!r}")
        question, _, raw = item.partition("=")
        try:
            out[question.strip()] = float(raw)
        except ValueError:
            raise InvokedWrong(f"--tau value is not a number: {item!r}") from None
    return out


def _epilogue(code: int) -> str:
    banner = f"VERDICT: exit {code} -- {EXIT_NAMES[code]}"
    if code == EXIT_COULD_NOT_RUN:
        banner += ("\n  The gate did not run to a verdict. DO NOT READ THIS AS A PASS.\n"
                   "  Nothing about this change has been cleared.")
    return banner


def cmd_class1(args: argparse.Namespace) -> int:
    taus = _parse_taus(args.tau)
    if not taus:
        raise InvokedWrong("at least one --tau question=value is required; see --help")
    baseline = _read_rows(Path(args.baseline))
    treatment = _read_rows(Path(args.treatment))
    labels_path = Path(args.labels) if args.labels else None
    result = class1_compare(baseline, treatment, taus, arm=args.arm,
                            labels=load_labels(labels_path))
    print(render_class1(result))
    code = result.exit_code
    print()
    print(_epilogue(code))
    return code


def cmd_class2(args: argparse.Namespace) -> int:
    import fixture_executor as fx  # local import: Class 1 must not need it

    suite = fx.load_suite(Path(args.suite), smoke=args.smoke)
    executor = fx.build_executor(args)
    try:
        report = fx.run_class2(
            suite, executor,
            baseline_arm=args.baseline_arm,
            treatment_arm=args.treatment_arm,
            judge=fx.build_judge(args),
            order_seed=args.order_seed,
        )
    except fx.HarnessFailure as exc:
        # The harness broke. That is an ABSENCE of measurement, and it is
        # reported as exit 1 -- never as a failed task, and never as a pass.
        raise CouldNotRun(f"the Class 2 harness failed: {exc}") from None
    print(fx.render_class2(report))
    print()
    print(power_statement(len(suite.tasks), suite.seeds))
    code = report.exit_code
    print()
    print(_epilogue(code))
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="accuracy_gate",
        description="SPEC §6 accuracy gate. Exit 0 clean / 1 COULD NOT RUN / "
                    "2 invoked wrong / 3 regression found.")
    sub = parser.add_subparsers(dest="command")

    c1 = sub.add_parser("class1", help="judge-side replay comparison (pennies)")
    c1.add_argument("--baseline", required=True, help="recorded baseline runs .jsonl")
    c1.add_argument("--treatment", required=True, help="replay-under-change runs .jsonl")
    c1.add_argument("--arm", default=None, help="restrict to one arm, e.g. jev")
    c1.add_argument("--tau", action="append", metavar="QUESTION=VALUE",
                    help="band threshold per question. Required: there is no "
                         "frozen tau file in this repository.")
    c1.add_argument("--labels", default=None,
                    help="labels .jsonl or directory. Without it the AUC "
                         "criterion is NOT EVALUABLE and the gate exits 1.")
    c1.set_defaults(func=cmd_class1)

    c2 = sub.add_parser("class2", help="agent-side fixture re-execution (costs money)")
    c2.add_argument("--suite", required=True, help="fixture suite directory")
    c2.add_argument("--baseline-arm", default="baseline")
    c2.add_argument("--treatment-arm", default="treatment")
    c2.add_argument("--executor", default="recorded", choices=("recorded", "live"),
                    help="'recorded' replays fixture outcomes (free, the tested "
                         "path). 'live' re-executes and is UNEXERCISED.")
    c2.add_argument("--judge", default="none", choices=("none", "recorded", "live"),
                    help="tiers 2 and 3. 'none' runs hard checks only.")
    c2.add_argument("--i-understand-this-spends-money", action="store_true",
                    help="required by --executor live / --judge live")
    c2.add_argument("--smoke", type=int, default=None,
                    help="run only the first N tasks (the ~6-task per-change subset)")
    c2.add_argument("--order-seed", type=int, default=None,
                    help="seed for the randomised, arm-interleaved execution "
                         "order (JEV-29). Omit for a fresh random order; the "
                         "seed used is printed so any run reproduces exactly. "
                         "Task order is part of the blind: run the arms in "
                         "blocks and a sequence-aware judge learns the arm by "
                         "counting.")
    c2.set_defaults(func=cmd_class2)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_INVOKED_WRONG
    try:
        return args.func(args)
    except InvokedWrong as exc:
        print(f"INVOKED WRONG: {exc}", file=sys.stderr)
        print(_epilogue(EXIT_INVOKED_WRONG), file=sys.stderr)
        return EXIT_INVOKED_WRONG
    except CouldNotRun as exc:
        print(f"COULD NOT RUN: {exc}", file=sys.stderr)
        print(_epilogue(EXIT_COULD_NOT_RUN), file=sys.stderr)
        return EXIT_COULD_NOT_RUN


if __name__ == "__main__":
    raise SystemExit(main())
