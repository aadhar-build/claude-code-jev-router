# JEV-16 → wave A3 (JEV-27, 46, 47, 48)

What Run A measured, and what it means for a power analysis. Written for
JEV-27 first, because variance and repeat structure are what it needs.

Source of every number: `reports/jev16-runA-2026-09-20.md` and
`reports/determinism-runA-2026-09-20.txt`. 90 calls, `cc_haiku45` at
`cc-haiku45-cli-v2-nothink`, 9 synthetic states x 10 repeats, 0 attrition.

---

## For JEV-27 — the power analysis

### 1. Repeat variance is NOT a small correction on this arm. It is bimodal.

Per-item probability spread (max−min) over 10 calls on byte-identical state:

| question | median spread | p95 | worst | median sd | worst sd |
|---|---|---|---|---|---|
| `destructive` | 0.010 | 0.130 | 0.130 | 0.005 | 0.048 |
| `needs_review` | 0.100 | 0.850 | **0.850** | 0.033 | **0.393** |

The distribution is not unimodal and a single variance parameter will
misrepresent it. **Six of nine items have spread ≤ 0.01 and three have spread
0.13–0.85.** Confident items are essentially deterministic (sd 0.000–0.005);
borderline items are close to uninformative on a single call. Any N derived
from a pooled sd will be far too small for the borderline stratum and far too
large for the confident one.

**Recommendation: size on the borderline stratum, or size per stratum.** A
pooled figure is the wrong instrument here.

### 2. Repeats buy very little per item — the PointFive result reproduces

PointFive (arXiv:2607.12161) measured ICC 0.37–0.55 for cost repetitions and
concluded: buy breadth, not reps. Run A points the same way for *answers*, and
harder: within an item, repeated calls on the confident majority are perfectly
correlated (sd 0.000), so a repeat on those items adds **zero** effective
sample. Repeats only inform on the three borderline items.

**Effective-sample arithmetic for this sweep**: 90 calls bought 9 items; six of
them were resolved by call 1. The marginal value of repeats 2–10 was
concentrated in three items. If JEV-27 budgets repetitions, they should be
allocated adaptively (repeat only what is near τ, or what disagreed on the
first two calls), not uniformly.

**Do not carry the 3–5 reps/task figure over unexamined.** It was derived for
*cost* variance (arXiv:2604.22750's up-to-30x run-to-run token variance). For
*answers*, Run A says 1 rep suffices on confident items and 10 is not clearly
enough on borderline ones.

### 3. There is a reproducibility ceiling on any statistic using `cc_haiku45 / needs_review`

10% of individual calls dissent from their own item's majority at τ=0.5. A
second identical run of the same analysis does not reproduce the same number,
and the residual is the arm disagreeing with itself. **This caps the maximum
attainable agreement** with any other arm on that question, independent of N —
more data does not remove it. JEV-27 should treat it as a variance floor, not
as something power can overcome.

`cc_haiku45 / destructive` has no such ceiling on this sample: 0/9 items
flipped in 90 calls at either τ=0.36 or τ=0.50.

### 4. The base-rate problem is worse than the sample-size problem

Across **487 live `jev` decisions**, `destructive` never once crossed τ=0.5
(max 0.16). Live occupancy within 0.05 of τ=0.36 is **0/487**. The synthetic
set, balanced 1:1:1 by construction, gives 3/59.

A study sized on the synthetic base rate will be badly wrong about live. State
the design base rate explicitly and separately for each context; never size on
a pooled one. `PREREGISTRATION.md` section 4 already forbids pooling them in
analysis — the same rule has to apply to the power calculation that precedes it.

### 5. Do not bisect on the clock

The corpus has three known boundaries (A7.4) and two of them are invisible in
any timestamp a reader has. Use the row's own `arm_config_id`, and JEV-32's
`set(arm_order)` for the arm-set era (531 three-arm rows, 1,252 four-arm rows;
JEV-32 deliberately did not partition statistics on it). `config_fingerprint`
now exists on `worker.py`, `replay.py` and `canary.py` rows but **zero of the
2,005 pre-existing rows carry one**, so it is an assertion, not a join key, for
anything collected before 2026-09-20.

---

## For JEV-46 (`random_matched`, the third routing arm)

The measurement to copy: Run A is a **within-configuration** control against a
**cross-configuration** comparison, on identical bytes. `random_matched` is the
same move one level up — a within-design control against a cross-design
comparison — and it exists for the same reason: without it, "tiering helps" and
"Jev helps" are the same number, exactly as "the config changed the answer" and
"the model wobbles" were. Run A is a worked precedent that the control changes
the conclusion: the cross-config effect vanished entirely once the within-config
envelope was measured.

## For JEV-47 (delegation-shape equality)

Run A pairs on `state_sha256` and asserts it rather than assuming it. Seven of
nine states had to be materialised from the synthetic file before the sweep
could run, and two pre-existing ones were checked to hash identically to a
rebuild today. Do the equivalent check on delegation shape **before** spending,
not after: `replay.py --seed-synthetic` and `--ids` exist now and make an exact
item set selectable rather than accidental.

## For JEV-48

Nothing specific from Run A beyond the reporting discipline: every figure in
`reports/jev16-runA-2026-09-20.md` names its `arm_config_id` and its
`run_context`, and the two occupancy numbers (41% synthetic, 2.3% live) are
always quoted together. That is the format to inherit.

---

## Instrument changes A3 can now rely on

- `replay.py --ids ID[,ID]` and `--context {live,synthetic,canary}` on all four
  sweeps; `--estimate` honours both, so a call budget is checkable before it is
  spent.
- `replay.py --seed-synthetic SID[,SID]` — capture rows for named synthetic
  items, zero API calls.
- `determinism.analyse()` requires `arm_config_id=` and `origin=`. There is no
  "all" value on purpose.
- Occupancy tables are keyed `(arm, arm_config_id)` and print
  `cc_haiku45 [cc-haiku45-cli-v2-nothink]`.
- `config_fingerprint` is on replay and canary rows, and on the capture rows
  both write.

## Open, and deliberately not done in A2

- **Run B** (`jev`, N=20, all 60 synthetic) and **Run C** (`cc_opus5`) are
  deferred to Phase B. Until Run B lands there is **no determinism baseline for
  `jev` at all**, which means the 2.3% live occupancy figure remains an
  exposure upper bound and cannot be converted into a flip rate.
- No live determinism baseline exists for any arm — Run A is synthetic-origin
  only. The live/synthetic difference in *instability* is unmeasured, and the
  occupancy difference (41% vs 2.3%) is strong reason to expect one.
- `replay.py` builds synthetic ids as `syn-syn-0121` (double prefix). Reported,
  not repaired: fixing it orphans 60 captures from their 180 rows.
