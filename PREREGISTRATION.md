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

---

# Amendment 1 — 2026-09-20

Committed the same day as the original, **before the collection window closed**
and before any live analysis was run. Both changes are recorded here rather than
edited into the text above, so the original commitments remain readable and the
diff is the audit trail.

## A1.1 — Degenerate-interval guard (an addition, not a relaxation)

A power analysis run after the original registration found a trap in the test as
written. Below roughly 40 sessions, **6–67% of simulated bootstrap intervals come
back degenerate and zero-width**: every resample happens to draw sessions that
agree completely, the interval collapses to a point, and that point sits above
0.80. **It would pass the hypothesis trivially.**

A narrow interval at small N is more likely degenerate than precise. So, fixed
now, before any live interval has been computed:

1. **Minimum-cluster rule.** Fewer than **30 distinct `session_id` clusters** →
   the result is **inconclusive by rule**, whatever the interval says.
2. **Zero-width rule.** Any interval of zero width is **inconclusive by rule**,
   whatever the cluster count.
3. **The cluster count is printed beside every interval**, always.

This is strictly *harder* to pass than the original test. It cannot manufacture a
positive result; it can only prevent one. Implemented in
`stats.Interval.inconclusive_reason`.

## A1.2 — Stopping rule changed from calendar to cluster count

**The original rule was seven calendar days, with N explicitly not a stopping
criterion.** That is amended. The new rule:

> **Collect until 30 distinct sessions have contributed live `pre_bash`
> decisions, or until 2026-10-20, whichever comes first.**

**Why, stated plainly.** The original rule was written to prevent stopping early
when the numbers looked good — the classic garden-of-forking-paths failure. The
power analysis showed it has the opposite problem here: at the observed rate
(37 decisions in **one** session) seven days plausibly yields 5–20 sessions
against the 30–40 needed, and below 30 clusters the primary metric is not merely
imprecise but **undefined** — `clustered_bootstrap` returns `nan` with one
cluster, verified directly.

**What protects against the original hazard.** The new rule is still blind to
the *result*: it fixes a **cluster count**, not a target for the statistic, and
30 was derived from a power analysis run before any live interval was computed.
The hard calendar stop at 2026-10-20 prevents indefinite extension. **No interim
analysis of the live primary metric will be run before the stopping condition is
met** — the guard in A1.1 makes any such interim look inconclusive anyway.

**The honest cost of this amendment.** Changing a stopping rule mid-study is a
recognised way to bias a result, and a sceptical reader is right to discount it.
The mitigation is that it is recorded here, dated, committed before the window
closed, with the reasoning and the arithmetic that motivated it — and that it
moves the bar **up**, not down. A reader who rejects the amendment can read the
seven-day result instead; it will be reported alongside, and it will almost
certainly say "inconclusive".

---

# Amendment 2 — the routing A/B — **PROPOSED, NOT RATIFIED**

**Status: DRAFT.** This amendment is *not* in force. It must be ratified — and
the open question in §A2.0 answered — **before the first routed task runs**.
Nothing below may be cited as a pre-registered commitment until that happens,
and if a routed task runs before ratification, the A/B is reported as
exploratory rather than pre-registered.

**Why it exists.** The study's thesis moved from "is Jev a good classifier?" to
"does routing make Claude Code cheaper?" The original registration above covers
only `pre_bash` PABAK. **The headline experiment is currently unregistered** —
which is the single most damaging gap a reviewer could find in a paper whose
methodological argument is that it pre-registered everything.

## A2.0 — The open questions that block ratification

**Five, not one.** Q10, Q11 and Q12 below were asked in the grilling and never
answered — what appears in this amendment as "the outcome is net cost including
rework" and "quality is friction proxies plus escalation rate" is a
*recommendation*, not a ratified decision. Q9 was likewise never answered. And a
fifth question was never asked at all.

### A2.0.1 — Q9: the unit of randomisation

**Not decided.** It was asked (grilling Q9) and
never answered, and the recommendation offered at the time — randomise per
*turn* — was subsequently invalidated: a turn is not a routable unit, because no
mechanism exists to change the model for one turn of a running session. Q9 must
be re-answered as **per-delegation randomisation**, and the paired-comparison
argument that justified per-turn randomisation does not survive the move: two
delegated tasks within one session are different tasks, so assignment is no
longer a within-subject comparison over identical context.

### A2.0.2 — Q10, Q11, Q12: unratified

The outcome definition (net cost including rework), the quality composite
(friction proxies plus escalation rate) and the decision to run concurrently
with the `pre_bash` window are all recommendations that were offered and never
confirmed. They are written below as if settled because that is the form a
pre-registration takes — but **they are not settled**, and ratifying this
amendment means ratifying them.

### A2.0.3 — What is the control arm? (never asked)

As drafted, A2.1's control is "the model tier fixed at the current default".
The default for a subagent is `inherit`, so the control is **Opus 5 on every
task**, and the finding would be "Jev-routing beats always-using-the-most-
expensive-model". Nobody disputes that. It is the same strawman this study
already caught once, when Haiku was added beside Opus precisely because
Opus-as-hook-gate was not a baseline anyone would deploy.

The competitor that actually threatens the thesis is a **two-line static rule**:
map `subagent_type` to a tier — `Explore`→haiku, `Plan`→opus,
`general-purpose`→sonnet — and route on that, with no classifier at all. If Jev
does not beat the static rule, the classifier adds nothing and the honest
finding is that routing helps but *Jev* does not. If it does beat it, that is
the paper.

**Recommendation to be ratified or overridden:** static rule as the **primary
control**, current default carried as a **descriptive third arm** so the
"versus Claude Code as deployed" number still exists. This makes it a three-arm
design, which feeds directly into the power analysis A2.4 already owes — a
three-arm comparison at 60 tasks is very unlikely to resolve anything.

Everything below is conditional on these answers.

## A2.1 — What is being compared

| arm | assignment |
|---|---|
| treatment | model tier for each delegated task chosen by `jev` from the task prompt |
| control | model tier fixed at the current default |

**Mechanism, verified 2026-09-20.** A `PreToolUse` hook matched on the `Agent`
tool returns `permissionDecision: "allow"` together with `updatedInput`, which
replaces the tool input before the subagent spawns; the `Agent` tool's input
carries a `model` field. Jev is therefore **in the loop on live traffic**, not
inferred. This matters for the registration because a counterfactual treatment
and an applied treatment are different studies, and the difference must be fixed
before data rather than after.

**The treatment must be verified, not assumed.** Every delegated task records the
model reported by the subagent's own transcript, and a mismatch against the
assigned tier is a hard failure, not a dropped row. An assignment that is
silently ignored would make the treatment arm identical to the control arm and
produce a null result caused by a bug.

## A2.2 — Primary outcome

> **Net cost in USD per delegated task, including rework**, treatment vs control,
> with a 95% bootstrap CI clustered on `session_id`.

"Including rework" is what stops the treatment winning by being recklessly cheap:
when a task is escalated, the arm is charged the **full cost of the escalated
run plus the wasted cost of the run it replaced**.

**Definition of escalation — fixed now, because it is the term most open to
post-hoc redefinition.** An escalation is recorded when, within the same session,
a delegated task is **re-delegated with substantially the same objective to a
higher tier**, linked to the `agentId` of the run it replaces. It is *not*
recovered afterwards by matching prompts, which would be a judgement call made
with the outcome already visible.

**UNRESOLVED — and ratification blocks on it.** That definition names a link
field with no producer. The `Agent` tool input has no `replaces` field; the
orchestrator would have to declare the link, which is a model judgement made
after seeing the first run's output, and the orchestrator is the same model in
both arms. The primary outcome currently depends on data nothing generates.

The candidate mechanism, to be ratified or replaced: a **convention** that a
re-delegating prompt opens with a `replaces: <agentId>` line, required by the
orchestrator's standing instruction and parsed by the `PreToolUse` hook that
already reads `tool_input.prompt`. Its weaknesses are stated rather than
discovered later — compliance is not enforceable, a missed line silently
converts an escalation into a cheap new task and **biases the treatment arm in
its own favour**, and the rate of missed links is itself unmeasurable by the
same mechanism. If no better answer is found, the honest fallback is to demote
net-cost-including-rework to secondary and make **raw net cost** the primary
outcome, with escalation reported as an unadjusted count.

**Directional hypothesis: net cost per delegated task in the treatment arm is
lower than in the control arm.** A superiority test, one primary outcome, no
multiplicity correction needed because there is exactly one.

## A2.3 — Secondary outcomes

**The author is not blind to arm assignment.** Interruption counts and permission
denials are behavioural measures produced by the same person who wants a
particular answer; they are cheap and worth collecting, and they carry
expectation bias that no amount of care removes at n=1. They are reported as
weak evidence and never as a quality verdict.

All labelled secondary, none headline-eligible: escalation rate; friction proxies
(user interruptions, permission denials, error `tool_result` rows); wall-clock per
delegated task; token counts by class; per-tier assignment distribution.

**Quality is measured by friction proxies and escalation rate only.** Self-rating
is excluded by design: an unblinded author scoring their own experiment at n=1 is
the weakest evidence available, and its absence is a feature to be stated, not a
limitation to be apologised for.

## A2.4 — Stopping rule

> **60 delegated tasks with a recorded outcome, or 2026-10-20, whichever comes
> first.**

Fixed in advance and blind to the statistic. No interim analysis of the primary
outcome before the stopping condition is met.

*(The 60 is a placeholder pending a power analysis on the observed per-task cost
variance. It must be replaced with a derived number before ratification — a
stopping rule chosen by eye is not a stopping rule.)*

## A2.5 — Exclusions

- Tasks whose subagent transcript is missing or truncated: excluded, counted in
  attrition, reported by arm. **Attrition that differs by arm is itself reported
  as a threat**, since a tier that fails more often would otherwise look cheaper.
- Tasks belonging to work on this experiment's own infrastructure: **not**
  excluded, but flagged, and the analysis is reported with and without them.
- No exclusion may be introduced after the stopping condition is met.

## A2.6 — The confound, registered before it can be spun

The "delegate where possible" working rule (grilling Q17b) deliberately changes
how the work is done in order to make more of it routable. It raises the
experiment's power and lowers its external validity at the same time.

Registered commitments:

1. The pre-rule delegation rate — the fraction of spend that was delegated
   *before* the rule was adopted — is computed from existing transcripts
   **before the rule takes effect**. Once the rule is in force that baseline is
   unrecoverable.
2. The writeup states plainly that the delegation rate was deliberately raised.
3. The result is framed as a claim about a **workload deliberately shaped to be
   routable**, not about ordinary Claude Code use.

## A2.7 — Interaction with the `pre_bash` primary metric

The two experiments share a collection window. Delegation moves `pre_bash`
captures into subagent sessions, where §4 above excludes them from the headline —
so the routing experiment can starve the gating experiment of the very clusters
A1.2 requires.

**The exclusion is not relaxed.** Live `pre_bash` captures are reported split by
`is_sidechain`, so the size of the effect is visible. If the main-session stream
does not reach 30 sessions by the hard stop, the `pre_bash` primary metric is
**inconclusive by rule** and published as such. It is not rescued by pooling.

## A2.8 — What would falsify it

The hypothesis is falsified if the clustered 95% interval on the net-cost
difference lies entirely at or above zero. An interval spanning zero is reported
as **inconclusive at this sample size** — and at 60 tasks, given the variance in
per-task cost, that is the most probable outcome. Saying so now is the point.

## A2.9 — Arms added since the original registration

§1 above lists three arms. Two more have since been added (grilling Q8):
`cc_sonnet5` and `cc_fable51`. The original text is left as written; this is the
amendment.

**The reference arm does not change.** `cc_opus5` remains the reference for the
`pre_bash` primary metric, and `jev` remains the treatment. Both added arms are
**secondary**, and adding them does not create a multiplicity problem for the
primary metric because it is a single pre-specified comparison.

Two disclosures attach to `cc_fable51`:

- **Its pricing is unverified.** Every other rate in `config/pricing.json` was
  reconciled to the cent against Claude Code's own `cost-state`. Fable's comes
  from documentation, and its 2.5% cache-read multiplier contradicts the uniform
  10% verified empirically for three other models. **No Fable cost figure is
  published until one real Fable session is reconciled.**
- **It is not a cheap tier.** At roughly twice Opus's headline rate it cannot
  appear as the low end of a routing ladder. Its plausible advantage is narrow
  and shape-dependent (cache-heavy, terse turns), which is why routing to it
  requires a second dimension — the `verbosity` question, JEV-25 — rather than a
  position on a one-dimensional complexity score.
