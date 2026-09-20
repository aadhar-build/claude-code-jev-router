# Pre-registration

**Committed before any live decision point is captured.** Its git hash is the
citation used in the writeup. Everything below is a commitment made while the
dataset is empty; the point is that none of it can be chosen after seeing the
numbers.

Where a commitment was already falsified or made moot by the day-0 spike, it
says so here rather than being quietly dropped.

- **Study**: does replacing Claude Code's decision layer with Jev work?
- **Design**: shadow mode. Observed, never enforced. No session behaviour changes.
- **Scope**: n=1 user, one machine, one repository, one surface (`pre_bash`) in Phase 1.
- **Collection window opens**: on the commit following this file.
- **Pricing snapshot**: `pricing-2026-09-20`, verified against source (`docs/COST-RECONCILIATION.md`, `docs/API-FINDINGS.md`).

---

## 1. What is being compared

Three arms, all on byte-identical state, interleaved with randomised order per
decision point:

| arm | what it is | role |
|---|---|---|
| `jev` | `typesafe-ai/jev` via the Vercel AI Gateway | treatment |
| `cc_opus5` | Claude Code headless on the subscription, Opus 5 | **reference** |
| `cc_haiku45` | Claude Code headless on the subscription, Haiku 4.5 | secondary |

**The baseline is Claude Code as deployed, not a bare model call.** The `cc_*`
arms bundle the model with a ~5–10K-token preamble, a tool round trip and a
process spawn. Every claim in this study is therefore about **the deployed
system**, not about Opus 5 or Haiku 4.5 as classifiers. A bare Messages API call
answers the same question in ~386 tokens in under a second.

This is a deliberate choice and it is the study's principal limitation. It is
disclosed in the abstract, in the report header, and in an **attribution table
printed beside every latency and token figure** decomposing state tokens from
preamble tokens and process spawn from API time. The metered-API arms exist in
`config/arms.json` and are disabled; enabling them would change the claim.

## 2. Primary metric and directional hypothesis

**One primary metric, fixed now.**

> **Primary**: PABAK between `jev` and `cc_opus5` on `pre_bash.destructive`, at
> τ=0.5, on live captures, with a 95% bootstrap CI clustered on `session_id`.
>
> **Hypothesis**: PABAK ≥ 0.80.

Chosen over Cohen's κ as primary because the live base rate is expected to be
degenerate (~1–5% destructive), and κ collapses under skew in a way that would
make the headline unreadable. **Both are always reported together**, with the
base rate and the majority-class baseline beside them. A PABAK of 0.95 next to a
κ of 0.02 is the honest presentation of a skewed sample, and it is the
presentation we expect to be making.

**Everything else is secondary** and labelled as such: `needs_review` agreement,
all `cc_haiku45` comparisons, all latency and cost figures, sharpness, the
synthetic discrimination set, and every robustness sweep.

## 3. Stopping rule

> **Seven calendar days from the first live capture**, whatever N that yields.

**N is explicitly not a stopping criterion.** We will not stop when the interval
tightens, when the numbers look good, or when a round number is reached. If the
week yields too few positives for a usable interval — which is likely — that is
**reported as the result**, not fixed by collecting until it isn't.

Extending the window is permitted only for a logged infrastructure failure
(worker down, credential expiry), and the extension and its reason are recorded
in the writeup.

## 4. Exclusions, decided now

- `is_sidechain: true` — excluded from headline, reported separately.
- Failed runs (`ok: false`) — excluded from latency and agreement, **counted in
  attrition** and reported by `error_kind` and state-size bucket.
- `run_context` is never pooled. `live`, `replay`, `synthetic`, `canary` are
  reported in separate sections. The synthetic set **never** appears in a
  headline agreement number.
- Decisions where the arms did not receive an identical `state_sha256` — excluded
  and reported as a hard failure, not silently dropped.
- Captures from arm subprocesses — structurally impossible (`JEV_ARM_SUBPROCESS`
  guard), and asserted.

## 5. Claim discipline

- **The word "accuracy" will not appear in Phase 1 output.** A test enforces it.
- Every agreement axis reads "agreement with `cc_opus5`". The reference is a
  **pseudo-label, not truth.**
- **No calibration claim in Phase 1.** Brier, ECE, RPS and decision-curve
  analysis require gold labels and are deferred to Phase 2. Phase 1 publishes
  **sharpness only**, plus a pseudo-reliability curve whose axis reads
  "P(cc_opus5 agrees)".
- The synthetic set has *designed* strata, not gold labels. Discrimination on it
  is a claim about a set we wrote, stated as such wherever it appears.

## 6. Pre-committed outcomes

Registered now so that neither can be reported as a surprise:

- **If agreement is low**, that is published as a finding about the difficulty
  and ambiguity of the task, not buried or re-cut until it improves.
- **If the base rate is degenerate and κ is ~0 while raw agreement is ~98%**,
  both numbers are published in the same sentence with the majority-class
  baseline, and the honest conclusion — that the live sample cannot support a
  discrimination claim — is stated plainly.

## 7. Commitments already settled by the day-0 spike

Recorded here because they were live hypotheses that the spike resolved
**before** any data was collected, and a reader should be able to see which
questions were open at which point.

- **Determinism.** The design had carried a hypothesis that Jev would be
  deterministic where temperature-zero LLMs are not, and that this would earn
  its own section. **Falsified.** Jev is not bit-deterministic. It is stable when
  confident (sd 0.000 at p=0.97) and wobbles at sd≈0.015 when uncertain; on a
  command at p≈0.50 it produced a different decision at τ=0.5 **once in twenty
  calls across two runs**. The rate is not characterised, and **"1 in 10" will
  not be quoted** — the determinism sweep measures how much *both* arms wobble,
  which is the fairer question.
- **Caching.** `usage` carries no cache fields, so there is no cached-vs-uncached
  comparison. The "report uncached as primary" commitment is moot.
- **Confidence over REST.** Confirmed present on `choice` and `score`, absent on
  `boolean`. Whether it carries information beyond the probability vector is an
  open secondary question, registered now: we will test whether it is simply
  `max(p)`.
- **Cost unit.** ~278 tokens of every call is fixed scaffolding, so a short bash
  command is ~91% overhead. **Cost is reported per decision, not per KB of
  state**, because the latter is misleading at these state sizes.

## 8. Analysis code is frozen at this commit

`src/stats.py`, `src/analyze.py` and the question sets in `questions/*/v1.json`
are fixed as of this commit. Changes after collection begins are permitted only
for defects, must be committed separately with the reason stated, and the
writeup reports both the pre- and post-fix numbers.

Question phrasings are versioned (`pre_bash/v1#a` etc.) and the primary phrasing
is `a`. The phrasing sweep is secondary and pre-registered as such: **the best
baseline phrasing is reported as the headline**, so a weak baseline prompt
cannot manufacture the result.

## 9. What would falsify the headline

Stated so it cannot be reframed later. The hypothesis PABAK ≥ 0.80 is falsified
if the clustered 95% interval lies entirely below 0.80. An interval spanning
0.80 is reported as **inconclusive at this sample size** — which, given the
expected base rate, is the most probable outcome of a one-week single-repository
collection, and saying so now is the point of pre-registering it.
