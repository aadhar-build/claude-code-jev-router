"""Agreement statistics. Pure functions, no I/O -- tested against known answers.

Three commitments are encoded here rather than left to the person writing the
report:

**Cohen's kappa and PABAK are always returned together.** Kappa collapses under
a skewed base rate while raw agreement stays high; reporting whichever flatters
the result is the easiest way to mislead with a real statistic. Both, with the
base rate, is the honest presentation.

**The majority-class baseline comes back in the same structure as the score.**
If a constant "no" scores 97% and an arm scores 97.5%, those two numbers belong
in the same sentence.

**Bootstrap resampling is clustered on session_id.** Decision points within a
session are massively correlated -- the same `npm test` eleven times. Naive
row-level intervals would be five to eight times too narrow, which is the first
thing a stats-literate reader would attack.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable, Hashable, Sequence

Cluster = Hashable


@dataclass
class Interval:
    point: float
    lo: float
    hi: float
    n: int
    n_clusters: int

    def __str__(self) -> str:
        return f"{self.point:.3f} [{self.lo:.3f}, {self.hi:.3f}]"


def raw_agreement(a: Sequence[bool], b: Sequence[bool]) -> float:
    if not a:
        return float("nan")
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def cohens_kappa(a: Sequence[bool], b: Sequence[bool]) -> float:
    """Chance-corrected agreement. Returns nan for fewer than 2 observations."""
    n = len(a)
    if n < 2:
        return float("nan")
    po = raw_agreement(a, b)
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if math.isclose(pe, 1.0):
        # Both raters constant and identical: chance agreement is total, so
        # kappa is undefined. PABAK is the statistic that still says something.
        return float("nan")
    return (po - pe) / (1 - pe)


def pabak(a: Sequence[bool], b: Sequence[bool]) -> float:
    """Prevalence-adjusted bias-adjusted kappa: 2 * po - 1. Stable under skew."""
    if not a:
        return float("nan")
    return 2 * raw_agreement(a, b) - 1


def majority_baseline(reference: Sequence[bool]) -> float:
    """What a constant predictor of the most common class would score."""
    if not reference:
        return float("nan")
    counts = Counter(reference)
    return max(counts.values()) / len(reference)


def base_rate(reference: Sequence[bool]) -> float:
    if not reference:
        return float("nan")
    return sum(reference) / len(reference)


def confusion(a: Sequence[bool], b: Sequence[bool]) -> dict[str, int]:
    """Rows = arm under test (a), columns = reference (b)."""
    out = {"tt": 0, "tf": 0, "ft": 0, "ff": 0}
    for x, y in zip(a, b):
        out[("t" if x else "f") + ("t" if y else "f")] += 1
    return out


def categorical_agreement(a: Sequence[str], b: Sequence[str]) -> float:
    if not a:
        return float("nan")
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def categorical_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    n = len(a)
    if n < 2:
        return float("nan")
    po = categorical_agreement(a, b)
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    if math.isclose(pe, 1.0):
        return float("nan")
    return (po - pe) / (1 - pe)


def quadratic_weighted_kappa(a: Sequence[int], b: Sequence[int], k: int) -> float:
    """For ordered scores: disagreeing by 3 is worse than disagreeing by 1."""
    n = len(a)
    if n < 2:
        return float("nan")
    denom = (k - 1) ** 2
    observed = sum((x - y) ** 2 for x, y in zip(a, b)) / (n * denom)
    ca, cb = Counter(a), Counter(b)
    expected = sum(
        (ca[i] / n) * (cb[j] / n) * ((i - j) ** 2) / denom
        for i in range(1, k + 1)
        for j in range(1, k + 1)
    )
    if math.isclose(expected, 0.0):
        return float("nan")
    return 1 - observed / expected


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
    interval, purely to show the reader how much clustering matters."""
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
