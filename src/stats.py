"""Discrimination and resampling statistics. Pure functions, no I/O.

**The agreement half of this module was removed on 2026-09-21 (W5 cleanup).**
`raw_agreement`, `cohens_kappa`, `pabak`, `majority_baseline`, `confusion`,
`categorical_agreement`, `categorical_kappa` and `quadratic_weighted_kappa`
existed to produce the publishable agreement statistic. The pivot retired that
question; their only non-test caller was `src/analyze.py`, serving JEV-05 and
JEV-12, both KILLed, and it went with them.

This was the FIRST edit to a file frozen by `PREREGISTRATION.md` §8. The freeze
did its job -- it is why the removal is a deliberate, recorded act rather than
drift. `PREREGISTRATION.md` stays on disk: deleting a pre-registration once its
result stops being wanted is the exact behaviour pre-registration exists to
prevent.

Chance-corrected agreement did NOT leave the codebase. `src/accuracy_gate.py`
carries `cohens_kappa_bool`, re-implemented there on purpose (see its note) and
tested in `tests/test_accuracy_gate.py`. That is the live one, on the product
path.

**What remains, and who needs it:**

**Bootstrap resampling is clustered on session_id.** Decision points within a
session are massively correlated -- the same `npm test` eleven times. Naive
row-level intervals would be five to eight times too narrow, which is the first
thing a stats-literate reader would attack. `clustered_bootstrap` is live:
`src/validate_threshold.py` calls it for **JEV-17**, a KEEP ticket that W4's
tier thresholds depend on.

⚠️ **But read `MIN_CLUSTERS_FOR_INFERENCE` below before quoting any interval
from it.** JEV-55 established that on the collected corpus the clustered
bootstrap has **one cluster**, so the primary interval is uncomputable and comes
back nan-width by rule. The guard is not decoration; it is the finding.

**ROC / AUC / Youden.** `auc`, `roc_curve` and `youden_threshold` serve
`validate_threshold.py`, `verdict.py` and `accuracy_gate.py`. `quantiles` is the
most-used function here (`bench_inline`, `determinism`, `validate_threshold`,
`verdict`): a bare mean latency hides everything that matters.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Hashable, Sequence

Cluster = Hashable


# Pre-committed guard, fixed BEFORE the collection window closed. Below roughly
# 40 sessions, 6-67% of simulated bootstrap intervals come back degenerate and
# zero-width, because every resample happens to draw sessions that agree
# completely. That point sits above the hypothesised threshold and would pass
# the test trivially. A narrow interval at small N is more likely degenerate
# than precise, so narrowness must never be read as precision.
MIN_CLUSTERS_FOR_INFERENCE = 30
ZERO_WIDTH_EPSILON = 1e-9


@dataclass
class Interval:
    point: float
    lo: float
    hi: float
    n: int
    n_clusters: int

    @property
    def width(self) -> float:
        if self.lo != self.lo or self.hi != self.hi:
            return float("nan")
        return self.hi - self.lo

    @property
    def inconclusive_reason(self) -> str | None:
        """Why this interval must NOT be read as a result. None means usable."""
        if self.n_clusters < MIN_CLUSTERS_FOR_INFERENCE:
            return f"only {self.n_clusters} cluster(s); {MIN_CLUSTERS_FOR_INFERENCE} pre-committed as the minimum"
        w = self.width
        if w != w:
            return "interval undefined (too few clusters to resample)"
        if w <= ZERO_WIDTH_EPSILON:
            return "zero-width interval — every resample agreed, which is degeneracy, not precision"
        return None

    @property
    def conclusive(self) -> bool:
        return self.inconclusive_reason is None

    def __str__(self) -> str:
        base = f"{self.point:.3f} [{self.lo:.3f}, {self.hi:.3f}] (n={self.n}, clusters={self.n_clusters})"
        reason = self.inconclusive_reason
        return base if reason is None else f"{base}  INCONCLUSIVE BY RULE: {reason}"


def base_rate(reference: Sequence[bool]) -> float:
    if not reference:
        return float("nan")
    return sum(reference) / len(reference)


def spearman_rho(a: Sequence[float], b: Sequence[float]) -> float:
    n = len(a)
    if n < 2:
        return float("nan")
    ra, rb = _rank(a), _rank(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def clustered_bootstrap(
    clusters: Sequence[Cluster],
    statistic: Callable[[Sequence[int]], float],
    *,
    n_resamples: int = 2000,
    alpha: float = 0.05,
    seed: int = 20260920,
) -> Interval:
    """Percentile bootstrap resampling whole clusters, not rows.

    `statistic` receives a list of row indices and returns a scalar. Resampling
    sessions rather than decisions is what keeps the interval honest when the
    same command appears eleven times in one session.
    """
    by_cluster: dict[Cluster, list[int]] = defaultdict(list)
    for idx, c in enumerate(clusters):
        by_cluster[c].append(idx)
    keys = list(by_cluster)
    n_rows = len(clusters)

    point = statistic(list(range(n_rows)))
    if len(keys) < 2:
        return Interval(point, float("nan"), float("nan"), n_rows, len(keys))

    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(n_resamples):
        idx: list[int] = []
        for _ in range(len(keys)):
            idx.extend(by_cluster[keys[rng.randrange(len(keys))]])
        value = statistic(idx)
        if not math.isnan(value):
            draws.append(value)

    if len(draws) < 20:
        return Interval(point, float("nan"), float("nan"), n_rows, len(keys))

    draws.sort()
    lo = draws[int((alpha / 2) * len(draws))]
    hi = draws[min(len(draws) - 1, int((1 - alpha / 2) * len(draws)))]
    return Interval(point, lo, hi, n_rows, len(keys))


def naive_bootstrap(
    n_rows: int,
    statistic: Callable[[Sequence[int]], float],
    *,
    n_resamples: int = 2000,
    alpha: float = 0.05,
    seed: int = 20260920,
) -> Interval:
    """Row-level resampling. Computed ONCE, published beside the clustered
    interval, purely to show the reader how much clustering matters.

    ⚠️ KEPT DELIBERATELY, AND IT IS NOW TEST-ONLY. The W5 brief asserted this
    function was live via `validate_threshold.py`. That is wrong on the
    evidence: `validate_threshold.py:398` calls `clustered_bootstrap` and
    nothing else. After `analyze.py` was deleted this function's only remaining
    caller is `tests/test_pipeline.py`.

    It stays anyway. It is a five-line wrapper over `clustered_bootstrap` with
    no independent logic to rot, and the test it serves --
    `test_clustered_intervals_are_wider_than_naive_ones` -- is the only place
    the project demonstrates *why* clustering is mandatory. That demonstration
    is load-bearing for JEV-17's thresholds, which read a clustered interval.
    Deleting the contrast would leave the live function's justification
    unexercised to save five lines.
    """
    return clustered_bootstrap(
        list(range(n_rows)), statistic, n_resamples=n_resamples, alpha=alpha, seed=seed
    )


def quantiles(values: Sequence[float], qs: Sequence[float]) -> dict[str, float]:
    """Nearest-rank quantiles. A bare mean latency hides everything that matters."""
    if not values:
        return {f"p{int(q * 100)}": float("nan") for q in qs}
    ordered = sorted(values)
    out = {}
    for q in qs:
        rank = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
        out[f"p{int(q * 100)}"] = ordered[rank]
    return out


def entropy_bits(probabilities: Sequence[float]) -> float:
    """Sharpness measure: does an arm commit near 0/1, or hedge at 0.5?"""
    total = 0.0
    for p in probabilities:
        for q in (p, 1 - p):
            if q > 0:
                total -= q * math.log2(q)
    return total / len(probabilities) if probabilities else float("nan")


def auc(scores_positive: Sequence[float], scores_negative: Sequence[float]) -> float:
    """Area under the ROC curve, via the Mann-Whitney U identity.

    Reads as: the probability that a randomly chosen positive item is scored
    above a randomly chosen negative one. 0.5 is a coin flip.
    """
    n_pos, n_neg = len(scores_positive), len(scores_negative)
    if not n_pos or not n_neg:
        return float("nan")
    combined = list(scores_positive) + list(scores_negative)
    ranks = _rank(combined)
    rank_sum = sum(ranks[:n_pos])
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def roc_curve(scores_positive: Sequence[float], scores_negative: Sequence[float]):
    """(fpr, tpr, threshold) points, coarse enough to print."""
    thresholds = sorted({round(s, 3) for s in list(scores_positive) + list(scores_negative)},
                        reverse=True)
    n_pos, n_neg = len(scores_positive), len(scores_negative)
    if not n_pos or not n_neg:
        return []
    out = []
    for t in thresholds:
        tpr = sum(1 for s in scores_positive if s >= t) / n_pos
        fpr = sum(1 for s in scores_negative if s >= t) / n_neg
        out.append((fpr, tpr, t))
    return out


def youden_threshold(scores_positive: Sequence[float], scores_negative: Sequence[float]):
    """The threshold maximising tpr - fpr. Reported because 0.5 is an arbitrary
    operating point that no one chose deliberately."""
    curve = roc_curve(scores_positive, scores_negative)
    if not curve:
        return float("nan"), float("nan")
    fpr, tpr, t = max(curve, key=lambda p: p[1] - p[0])
    return t, tpr - fpr
