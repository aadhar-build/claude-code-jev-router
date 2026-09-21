# Pre-registration

> ## ⚠️ NO LONGER A LIVE COMMITMENT — retired 2026-09-21
>
> The publication this document governed was cancelled. **Nothing here binds
> current work**, and no new analysis should cite it as a commitment.
>
> It is retained for two reasons, both real:
>
> 1. **It is the honest record of what was believed, and when.** Deleting a
>    pre-registration after the result stops being wanted is precisely the
>    behaviour pre-registration exists to prevent. It stays.
> 2. **Amendments 5–8 contain measured facts the cost pipeline still depends
>    on** — in particular the auth path and the cache-write multiplier (1-hour
>    TTL at 2× on subscription vs 5-minute on API key). Get that wrong and every
>    dollar figure in the new goal is wrong.
>
> The live spec is `SPEC.md`. See `ISSUES.md` for the pivot and its triage.


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
- **Pricing snapshot**: `pricing-2026-09-20`, verified against source (`FINDINGS.md` Appendices B and A — the same content, moved 2026-09-20 when the `docs/` findings files were merged; no commitment changed, only a path).

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

# Amendment 2 — the routing A/B — **RATIFIED except A2.4**

**Status: ratified 2026-09-20**, with one exception stated immediately so it
cannot be overlooked: **A2.4's stopping rule is still a placeholder** (60 tasks,
chosen by eye). A stopping rule chosen by eye is not a stopping rule. It must be
replaced with a number derived from the observed per-task cost variance **before
the first routed task runs**. Until then this amendment is not in force, and a
task run before that point makes the A/B exploratory rather than
pre-registered.

**Why it exists.** The study's thesis moved from "is Jev a good classifier?" to
"does routing make Claude Code cheaper?" The original registration above covers
only `pre_bash` PABAK. The headline experiment was unregistered — which is the
most damaging gap a reviewer could find in a paper whose methodological argument
is that it pre-registered everything.

## A2.0 — The five design questions, and how they were answered

Four of these (Q9–Q12) were asked during the 2026-09-20 grilling and never
reached the owner; the round was overtaken and the interview moved on. The
fifth was never asked. All five were put again and answered on 2026-09-20.

| # | question | answer |
|---|---|---|
| **Q9** | unit of randomisation | **per delegation** — coin flip at every `Agent` spawn |
| **Q10** | quality measurement | **blinded grader**, with friction proxies retained as secondary |
| **Q11** | primary outcome | **raw net cost**; rework-adjusted cost demoted to secondary |
| **Q12** | concurrent with the `pre_bash` window | **yes**, with the `is_sidechain` split reported |
| **Q13** | control arm | **the current default** (`inherit`, i.e. Opus on every task) |

### A2.0.1 — Q9: per-delegation randomisation, and what it does not give us

Randomisation is a coin flip at each `Agent` spawn. Per-session assignment would
need dozens of sessions to balance and the window does not contain them;
blocking on `subagent_type` would balance the assignment of an experiment using
the very signal the classifier is deciding on, which is circular.

**Two limitations, recorded now rather than discovered in review.**

1. **This is not the paired comparison per-turn randomisation would have been.**
   Two delegated tasks in one session are different tasks. Within-session
   assignment removes the between-session confound (same repository, same hour,
   same broad workload) but it does not put the two arms on identical inputs.
2. **Carryover is real and is not removed by randomisation.** A poor result from
   a cheaply-routed task pollutes the orchestrator's context for tasks that
   follow, some of which will land in the other arm. The contamination therefore
   runs **treatment → control**, which biases *against* the treatment. That is
   the safe direction, and it is why this is acceptable rather than fatal. It is
   disclosed in the writeup, and it means a **null result is weaker evidence
   than a positive one** here: a positive survives the bias, a null may be
   caused by it.

### A2.0.2 — Q10: a blinded grader is the primary quality measure

The author is not blind to arm assignment, and interruption counts and
permission denials are behaviours the author produces. They are kept — they are
free — but they cannot carry a quality verdict.

**Primary quality measure: a blinded grader.** A separate session scores each
delegated task's output against its task prompt, **never seeing which tier
ran it**. Registered now, because a grading procedure specified after seeing
results is not evidence:

- The grader receives the task prompt and the output, with `resolvedModel`,
  `modelsUsed` and any tier-identifying text stripped.
- Task order is randomised; the grader is not told the arm ratio.
- The rubric is fixed before grading begins and does not change once grading
  starts.
- A sample is **double-graded** to measure the grader's own consistency; an
  inconsistent grader is reported as such rather than averaged.
- **Leakage is expected and must be checked, not assumed away.** Output style
  can identify a model tier. The check: the grader is asked to guess the tier on
  a held-out subset; if it guesses well above chance, the blind failed and the
  measure is reported as compromised.

Friction proxies remain, labelled secondary and labelled unblinded.

### A2.0.3 — Q11: raw net cost is primary

> **Primary outcome: raw net cost in USD per delegated task**, treatment vs
> control.

Rework-adjusted cost — charging an escalated task for the run it replaced — is
**secondary**. The reason is mechanical, not philosophical: the adjustment needs
a link from an escalation to the run it replaces, and nothing in the harness
produces that link. The candidate is a convention (a `replaces: <agentId>` line
in the re-delegating prompt, parsed by the hook), and it is not enforceable. A
**missed** link silently converts an escalation into a cheap new task, which
biases the treatment arm **in its own favour** — the one direction the study
cannot afford.

So: raw net cost is computable from transcripts with no convention and no
judgement call, and is therefore primary. The rework adjustment is
pre-registered as a secondary that is reported **only if** the convention's
compliance rate is itself measured and stated. Escalation is reported as an
**unadjusted count** regardless.

### A2.0.4 — Q12: concurrent, and what it costs `pre_bash`

The A/B runs concurrently with the `pre_bash` collection window. Sequential
collection would be cleaner and would probably mean the A/B never runs: 30
sessions by the 2026-10-20 hard stop is already a stretch, and the A/B is the
headline.

**The cost is accepted in advance, not discovered later.** Delegation moves
`pre_bash` captures into subagent sessions, where §4 excludes them from the
headline. The most likely outcome for the `pre_bash` primary metric is
**inconclusive by rule** under A1.1. That was written to make such an outcome an
honest result rather than a failure, and it is reported as one. See A2.7.

### A2.0.5 — Q13: the control is the default, and the objection is on the record

**Control = the current default**, which for a subagent is `inherit` — Opus on
every task.

**The owner's reasoning, which is the stronger argument for it:** Opus-on-
everything is what most people actually run for everyday work, so it is the
realistic counterfactual, and a result measured against it is a result about the
world rather than about a rule we invented for the paper.

**The objection, recorded because it does not go away by being outvoted.** A
two-line static rule — `subagent_type → tier`, no classifier at all — would
capture much of the available saving. Measuring only against the default
conflates two claims: *routing helps* and *Jev helps*. A reader who suspects the
second is doing no work is entitled to, and this design cannot separate them by
randomisation.

**Mitigation, registered now, and it costs nothing.** Every delegated task
records both Jev's assignment and its `subagent_type`, so the assignment a
static rule *would* have made is computable offline for every task. Two figures
go in the writeup:

1. **Agreement between Jev's assignment and the static rule.** If Jev agrees
   with two lines of `if` on, say, 95% of tasks, the classifier is adding
   approximately nothing, and **that is stated plainly as a headline caveat**
   whatever the cost result says.
2. **Where they disagree**, the distribution of Jev's assignment by
   `subagent_type` — which shows what, if anything, the classifier is seeing
   that the static rule cannot.

This does not recover a randomised comparison and is not presented as one. It
bounds the claim: if the classifier is redundant, the data says so.

## A2.1 — What is being compared

| arm | assignment | role |
|---|---|---|
| treatment | model tier for each delegated task chosen by `jev` from the task prompt | |
| control | **the current default** — `inherit`, i.e. Opus on every task | Q13 |

The control is the realistic counterfactual: Opus-on-everything is what an
ordinary user runs. The objection to it — that it cannot separate "routing
helps" from "Jev helps" — and the offline mitigation that partly answers it are
in A2.0.5.

**Mechanism, verified 2026-09-20.** A `PreToolUse` hook matched on the `Agent`
tool returns `permissionDecision: "allow"` together with `updatedInput`, which
replaces the tool input before the subagent spawns; the `Agent` tool's input
carries a `model` field. Jev is therefore **in the loop on live traffic**, not
inferred. A counterfactual treatment and an applied treatment are different
studies, and which one this is must be fixed before data rather than after.

**The treatment must be verified, not assumed.** Every delegated task records the
model reported by the subagent's own transcript, and a mismatch against the
assigned tier is a hard failure, not a dropped row. An assignment that is
silently ignored would make the treatment arm identical to the control arm and
produce a null result caused by a bug.

## A2.2 — Primary outcome

> **Raw net cost in USD per delegated task**, treatment vs control, with a 95%
> bootstrap CI clustered on `session_id`.

**Directional hypothesis: cost per delegated task is lower in the treatment
arm.** A superiority test; one primary outcome, so no multiplicity correction.

Computed from the subagent's own transcript under `<session>/subagents/`, with
the cost formula already reconciled against `cost-state` — **not** from
`PostToolUse`, which on a background launch (the default since v2.1.198) returns
`resolvedModel` and no usage fields at all.

**Why "raw" and not "including rework".** See A2.0.3: the rework adjustment
needs an escalation→predecessor link that nothing in the harness produces, and
a missed link biases the treatment arm in its own favour. Raw net cost needs no
convention and no judgement call.

**Definition of escalation, fixed now because it is the term most open to
post-hoc redefinition.** An escalation is a delegated task **re-delegated with
substantially the same objective to a higher tier within the same session**. It
is reported as an **unadjusted count per arm**, and it is *never* recovered
afterwards by matching prompts, which would be a judgement made with the outcome
already visible.

**Rework-adjusted cost is a pre-registered secondary**, reported only if the
`replaces: <agentId>` prompt convention is in force *and* its compliance rate is
measured and stated alongside. Without that rate, the adjusted figure is not
reported at all.

## A2.3 — Secondary outcomes

**Quality — blinded grader (primary quality measure, per Q10).** Specified in
full in A2.0.2: stripped outputs, randomised order, fixed rubric, a
double-graded sample for grader consistency, and an explicit blind-integrity
check in which the grader is asked to guess the tier — if it guesses above
chance, the measure is reported as compromised.

**Friction proxies — secondary and unblinded.** User interruptions, permission
denials, error `tool_result` rows. The author is not blind to arm assignment and
these are behaviours the author produces; the expectation bias is not removable
at n=1. Reported as weak evidence, never as a quality verdict.

**Self-rating is excluded by design.** An unblinded author scoring their own
experiment at n=1 is the weakest evidence available, and its absence is a
feature to be stated rather than a limitation to apologise for.

Also secondary, none headline-eligible: escalation rate; rework-adjusted cost
(conditional, above); wall-clock per delegated task; token counts by class;
per-tier assignment distribution; **agreement between Jev's assignment and the
static `subagent_type → tier` rule** (A2.0.5).

## A2.4 — Stopping rule — **STILL OPEN, and it blocks ratification**

> *(placeholder)* 60 delegated tasks with a recorded outcome, or 2026-10-20,
> whichever comes first.

**The 60 was chosen by eye and a stopping rule chosen by eye is not a stopping
rule.** It must be replaced by a number derived from the observed per-task cost
variance in the existing transcript corpus, computed **before the first routed
task runs**, and committed as **Amendment 4**, which ratifies Amendments 2 and 3 in full.

The derivation is specified now so that it cannot be tuned afterwards: estimate
the per-delegated-task cost distribution from existing subagent transcripts by
tier, take the minimum effect size worth detecting from the break-even
arithmetic already in the spec, and report the N at 80% power — clustered on
session, since per-delegation randomisation within a session does not make the
tasks independent. **If the required N exceeds what the window can produce, that
is reported as the finding**, the A/B runs anyway as a descriptive exercise, and
no inferential claim is made from it.

Once fixed: blind to the statistic, and no interim analysis of the primary
outcome before the stopping condition is met.

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


---

# Amendment 3 — routing A/B operational specification — **PROPOSED**

Not in force. Ratified together with Amendment 4 (the power-derived stopping
rule), which is the last open clause of Amendment 2. Settled in the 2026-09-20
grilling round on the specs.

## A3.1 — Analysis population: intention-to-treat

The routing hook must fail open, and failing open means **not** rewriting the
model — which is the default, which is the control condition. A classifier
outage therefore converts treatment tasks into control tasks silently.

> **Primary analysis is intention-to-treat: every delegated task is analysed
> under the routing arm the coin flip assigned, whatever actually ran.**

A failed Jev call is a cost of deploying Jev and counts against the treatment.
This is the only version that answers "should I deploy this?", because
deployment includes the outages.

**Per-protocol — analysis by `resolvedModel`, dropping tasks where the hook did
not take effect — is secondary**, and the **hook failure rate is reported
beside both**. A per-protocol figure published alone is a number that cannot be
reproduced in production.

## A3.2 — Routing choice set: all four tiers, including Fable

Jev may assign any of `haiku45`, `sonnet5`, `opus5`, `fable51`.

**This makes an unverified price a component of the primary outcome, and that
must be closed before collection rather than disclosed afterwards.** Fable's
rates come from documentation and its 2.5% cache-read multiplier contradicts the
10% verified empirically for three other models. Since the primary outcome is
net cost in USD, a wrong Fable rate is a wrong headline.

> **Blocking prerequisite: Fable's pricing must be reconciled against a real
> session's `cost-state` before the first routed task runs.** If it cannot be
> reconciled, Fable is removed from the choice set and the amendment is revised
> before collection, not after.

**Second limitation, registered now.** Fable's advantage is shape-dependent —
cache-heavy, terse turns — and a one-dimensional complexity score cannot express
that. Until the `verbosity` question is live, any routing to Fable rests on a
signal that cannot justify it. The writeup reports the share of tasks routed to
Fable and states this explicitly.

## A3.3 — The blinded grader

**Grader model: `claude-fable-5-1`.** Fixed in advance so that a mid-study model
change cannot be mistaken for a quality change.

**Placement: out of band.** The grader runs in a separate session after
collection closes, and is excluded from the A/B **structurally** by a guard on
the routing hook — the same shape as the existing `JEV_ARM_SUBPROCESS` guard.
An exclusion that must be remembered at analysis time is one that is eventually
forgotten, and grading inside the collection window would let the grader's own
delegations enter the experiment it is measuring.

**Self-preference bias is a known hazard here and is checked, not assumed
away.** Fable is both the grader and a routable tier, and language models
reliably favour their own outputs. The check: the share of tasks graded highest
is reported **by tier**, and if Fable-run tasks score systematically above
others while the blind-integrity check also shows above-chance tier
identification, the grader's verdict is reported as compromised rather than
used.

### The rubric, fixed before grading begins

Four dimensions, each scored 1–5 against the task prompt alone. Fixed now so
that criteria cannot drift once results are visible:

| dimension | question |
|---|---|
| **completeness** | Was every part of the task carried out, or only the easy parts? |
| **correctness** | Is what it reports actually true of the artifacts it claims to have produced? |
| **evidence** | Are claims supported by something checkable, or asserted? |
| **efficiency** | Did it reach the result without unnecessary work, or wander? |

**Anti-drift commitments:**

- The rubric text, the anchor descriptions for each 1–5 point, and the grader
  model are **frozen at this commit** and quoted in the writeup.
- Grading runs in **one batch**, not incrementally, so no early results can
  reshape later judgements.
- Task order is randomised and the grader is not told the arm ratio.
- `resolvedModel`, `modelsUsed` and tier-identifying text are stripped from the
  graded material.
- A **10% double-graded sample** measures the grader's own consistency;
  quadratic-weighted kappa between the two passes is reported. An inconsistent
  grader is reported as inconsistent, never averaged into a verdict.
- **Blind-integrity check**: on a held-out subset the grader is asked to name
  the tier. Above chance means the blind failed and the measure is reported as
  compromised.
- Overall quality is the **unweighted mean of the four dimensions**. The
  weighting is fixed now precisely because choosing it later, with the cost
  result already visible, is the easiest way to manufacture "quality was
  unchanged".

## A3.4 — Gates the routing hook must pass before registration

It is the study's first **actuator**: every hook until now only observed, and
the worst case for an observer is a lost record. This one rewrites tool input.

All existing gates apply — isolation, fail-open, kill switch, and the GATE 4
future-leakage test — plus two written for this hook:

1. **Input fidelity.** `updatedInput` replaces the *entire* tool input object.
   The hook must echo `prompt`, `description` and `subagent_type` back
   byte-identically while changing only `model`. Asserted, because a hook that
   drops `subagent_type` spawns a subagent of the wrong type — which is
   indistinguishable, in the results, from a routing quality effect.
2. **Assignment ledger before spawn.** The assignment is durably recorded
   *before* the subagent starts. A ledger written afterwards is missing exactly
   when it matters most: when the task crashed.

## A3.5 — Wall-clock is a co-primary outcome, not a secondary

**Amended 2026-09-20, before any routed task.** A2.2 named raw net cost as the
sole primary and A2.3 listed wall-clock among the secondaries. That split was
not defensible and is corrected here.

**The reasoning that was wrong.** Speed had been argued away as "a property of
the model, not a contribution of the classifier" — Haiku is simply faster than
Opus, so a speedup is not Jev's doing. **The same sentence is true of cost**, and
cost was kept as the headline anyway. A correct downgrade earns its dollars and
its seconds by exactly the same mechanism: picking the right tier for the task.
One cannot be credited and the other dismissed.

> **Co-primary: net wall-clock seconds per delegated task**, treatment vs
> control, with a 95% bootstrap CI clustered on `session_id`.
>
> **Hypothesis: wall-clock per delegated task is lower in the treatment arm.**

**"Net" carries the same discipline as it does for cost.** The routing hook is
synchronous on the spawn critical path and its latency is charged to the
treatment arm — measured in the A/B, never assumed from the ~624ms p50 the
enforce-overhead bench produced. Escalation wall-clock is charged the same way
cost is: the retry *plus* the run it replaced, because those elapse in sequence.

**The two primaries are correlated and that is disclosed, not corrected for.**
Cheaper tiers are faster tiers, so this is substantially one effect reported in
two units, not two independent findings. Two commitments follow:

1. **Both are reported regardless of outcome.** Neither is selected after the
   fact as the one that looked better — reporting whichever of two correlated
   outcomes won is the multiplicity failure this clause exists to prevent.
2. **Their correlation is reported**, so a reader can see how much independent
   information the second number carries.

No multiplicity correction is applied, because success is not claimed on "either
one wins". They are two separate pre-specified claims, each standing or falling
on its own interval.

### Measured duration is not felt duration

Subagents run in the background by default. A delegated task that finishes in
15s instead of 48s has objectively sped up — and if the session was not blocked
on it, **the human experienced no speedup at all.** Reporting task duration as
though it were user-perceived time would overstate the result.

So both are recorded per delegated task:

| measure | what it is |
|---|---|
| **task duration** | subagent wall-clock, from the subagent's own transcript |
| **blocking duration** | the portion the orchestrator actually waited on |

Task duration is the co-primary. **Blocking duration is reported beside it every
time**, and if the two diverge sharply — a large task speedup with little
blocking time saved — that divergence *is* the finding, and it is stated plainly
rather than left for a reader to infer.

---

# Amendment 5 — concurrent arm dispatch, and the bias it introduces

**2026-09-20.** A change made to the collection machinery mid-window, recorded
here because it alters the meaning of a reported metric and, more seriously,
**alters it in a direction that favours the treatment arm.**

## A5.1 — What changed, and why it could not wait

Arms were evaluated **serially** in a randomised order until
**2026-09-20T14:24:13Z**. From that moment they are **dispatched concurrently**,
in a randomised submission order.

The change was forced, not chosen. Serial four-arm evaluation took a median
**20.1s** of arm time per capture, and captures arrived faster than that during
active work. Past the backpressure cap the hook fails open and **drops captures
silently** — attrition that never reaches the attrition count §4 commits to
reporting. Waiting would have traded a known measurement change for an unknown
and unmeasurable data loss.

The realised gain is smaller than the ticket claimed. That estimate was ~4×; it
was never reachable, because concurrency is bounded by the slowest arm and the
arms are wildly unequal (`jev` 0.57s, `cc_sonnet5` 2.9s, `cc_opus5` 4.9s,
`cc_haiku45` 11.6s), putting the theoretical floor at ~1.76×. **Measured:
20.1s → 16.5s, about 1.2×**, the remaining gap being contention between four
simultaneous process spawns. The 4× figure is not quoted anywhere.

## A5.2 — The era marker

`arm_dispatch` is recorded on every run row from the boundary onward, with the
value `concurrent`. **Its absence means the prior sequential era.** `replay.py`
and `canary.py` remain sequential and correctly omit it.

Three new fields make the change auditable rather than merely declared:
`dispatch_offset_ms` (when each arm's call actually started, relative to the
decision), `dispatch_wall_ms` (the decision's total), and `concurrent_arms`
(how many were in flight, so contention is conditionable).

`arm_order` and `arm_order_position` are **narrowed, not redefined**: they now
record the randomised *submission* order. The invariant
`arm == arm_order[arm_order_position]` holds in both eras.

**The randomisation requirement is satisfied more strongly, not relaxed.** It
existed so that no arm systematically occupied the late slots of a ~20s serial
window, or the cold first slot. Concurrency removes that hazard rather than
guarding against it: there are no late slots, because there are no slots.
`dispatch_offset_ms` lets the analysis *verify* the residual stagger is
negligible — measured max **5.25ms** — instead of trusting the design.

## A5.3 — The bias, stated plainly

**Concurrent dispatch biases per-arm wall-clock in favour of `jev`, which is the
treatment arm.**

The mechanism is not subtle. Under contention, `jev` is a single HTTP request
and barely competes for local CPU, while each `cc_*` arm pays a process spawn.
Running them simultaneously therefore inflates the baselines' measured latency
more than the treatment's. **A change made mid-study that flatters the
treatment on a reported metric is exactly what a sceptical reader should
suspect**, and it would be indefensible to leave it implicit.

Three commitments follow:

1. **Latency is never pooled across the boundary.** Per-arm latency is reported
   separately for the sequential and concurrent eras, with the era stated and
   the row counts given.
2. **The bias is quantified, not just disclosed.** Every `cc_*` row carries
   `raw.duration_api_ms`, which separates API time from process spawn. The
   spawn-contention component is therefore **measurable**, and the writeup
   reports it rather than asserting it is small.
3. **No latency comparison between `jev` and a `cc_*` arm is a headline claim**
   from concurrent-era data. The sequential era already contains enough rows for
   that comparison, and it is the era in which the comparison is fair.

**Agreement, answers, cost and attrition pool freely across the boundary** — the
arms received identical bytes and identical questions in both eras, and none of
those quantities depends on dispatch timing.

## A5.4 — The collection window now contains two boundaries

Recorded together, because an analyst who finds one and not the other will draw
a wrong conclusion:

| timestamp | change | what it affects |
|---|---|---|
| **2026-09-20T12:07:24Z** | three arms → four (`cc_sonnet5` added; the worker had been holding stale config) | rows before it have no `cc_sonnet5`; the `jev` vs `cc_opus5` primary spans both sides unaffected |
| **2026-09-20T14:24:13Z** | sequential → concurrent dispatch | per-arm latency only; marked by `arm_dispatch` |

Neither boundary touches the primary metric, which is PABAK between `jev` and
`cc_opus5` on `pre_bash.destructive` — both arms are present, on identical
bytes, throughout.

---

# Amendment 6 — declared attrition, a correction, and the retention clock

**2026-09-20.** Three items, one of which is a disclosure that reflects badly on
the conduct of the study and is recorded for that reason.

## A6.1 — Live captures were destroyed by our own test suite

`tests/test_hook.sh` calls `rm -f "$ROOT"/spool/ready/*.json` **between
assertion blocks**, against the real project root, while the worker drains that
directory. `tests/run_all.sh` invokes it — so "run the test suite", the
instruction in every agent brief written that day, was the destructive command.

**Two agents disclosed running it against the live tree, on request, after the
defect was found:**

| approx. time (UTC, 2026-09-20) | what ran |
|---|---|
| 14:10Z, 14:44Z, 14:46Z | `run_all.sh` x3 |
| ~14:40Z – 15:05Z | `test_hook.sh` x4 (one direct, three via `run_all.sh`), plus one run of the **pre-fix** `gates.sh`, which additionally moved `spool/ready` aside and wrote 501 filler files into the directory the worker was draining |

**At least seven invocations across roughly 14:10Z–15:05Z**, each wiping
`spool/ready/` several times over. A third agent confirmed it had never run
either, which is how the window is bounded at all.

Both disclosures were volunteered in response to a direct request to report
rather than repair. That is recorded because the alternative — an agent quietly
tidying up — would have left this undiscoverable, and the study's whole claim to
credibility is that losses of this shape get declared.

**The number of captures lost is unknown and unrecoverable.** A file deleted
from the spool leaves no capture row and no run row; there is nothing to count
afterwards. It is bounded above by the spool depth at those moments.

**Correction, 2026-09-20.** This paragraph first stated the observed high-water
mark for the window as **20**. That figure was wrong. `data/spool_watermark.json`
records `max_total: 71` at **14:36:24Z** — inside the destruction window, and a
genuine backlog rather than a test artifact (56 captures drained between 14:30Z
and 14:50Z at roughly 3/min). The bound is therefore **71, not 20**.

**And the instrument does not cover the whole window.** `spool_watch` was added
by JEV-33 and its `first_sample_at` is **14:24:06Z** — fourteen minutes after the
window opened at ~14:10Z. Depth during 14:10Z–14:24Z was never sampled, so 71 is
an upper bound on the *observed* portion only and the true maximum depth over the
full window is unknown. The loss is stated as **bounded above by 71 over the
sampled portion, unbounded over the first fourteen minutes**, which is weaker
than the original claim in both directions. It remains of unknown size, and is
not estimated away.

**It is reported as attrition of unknown size, not estimated away.** §4 commits
to counting failed runs in attrition; this is a loss that structurally cannot
enter that count, which is precisely why it is declared here instead. The
writeup states the three timestamps and the bound.

**What it does not affect.** Losses are of *whole captures* before any arm saw
them, so no arm is differentially affected and no comparison is biased. The
mechanism is blind to content: it deletes whatever is waiting, and what is
waiting is a function of drain timing, not of the command being classified. The
primary metric loses a small amount of power and nothing else.

**Cause, stated plainly.** The test suite was written before the surface went
live, when there was no live spool to destroy, and was never revisited when
collection opened. The instruction that triggered it — "the full test suite must
pass" — was written into four agent briefs by the study's own author on the day
it happened. Tracked as JEV-42.

**One further capture pair was forgone deliberately**, not lost: the live probe
that established whether a running session honours the kill switch necessarily
suppressed the two Bash calls made while the switch was set. Those are recorded
in `docs/REVERSIBILITY.md` as an intentional gap rather than left to look like
attrition.

## A6.2 — Correction to A2.6 #1

A2.6 #1 states that the pre-rule delegation rate must be computed "before the
rule takes effect" because "once the rule is in force that baseline is
unrecoverable."

**That reasoning is wrong.** Billable requests carry timestamps, so the rate is
recoverable by cutting the corpus at the adoption moment — it was in fact
computed roughly 3.5 hours *after* adoption, cleanly. What makes the baseline
unrecoverable is **transcript rotation**, not rule adoption. The urgency was
real; the stated reason for it was not.

The commitment itself stands and has been met. A further deviation is recorded:
**the cut is per billable request and per delegated task, not per session.** The
rule was adopted *mid-session*, inside the only sustained work session this
repository has, so a session-level cut would have either discarded the entire
real corpus or silently admitted its post-rule half.

**The pre-rule delegation rate, frozen:**

| measure | value |
|---|---|
| by spend | **0.1624** ($11.04 delegated of $68.00) |
| by task count | **0.1591** (7 delegated tasks / 37 typed prompts) |
| cut at | 2026-09-20T11:11:49Z |

## A6.3 — The retention clock, and how close it ran

Transcript retention was an unstated assumption this study depended on. It is
now established from primary sources rather than guessed: the setting is
**`cleanupPeriodDays`**, its default is **30 days**, it is **unset** in both the
user and project settings, and the documented cleanup covers
`projects/<project>/<session>/subagents/` on the same clock. Claude Code
2.1.278.

**The collision that implies.** The earliest sessions in this corpus begin
2026-09-19T19:58Z, so they are swept from approximately **2026-10-19**. The
pre-registered hard stop for collection is **2026-10-20**. The source
transcripts for the entire "before" baseline would have rotated **the day before
the window closed**, and JEV-06 had recorded that baseline as collected when
nothing was accumulating at all.

It is now persisted in-repo as derived numbers, under version control, at
`data/baseline/`. **Snapshotting is not optional and must continue** — a session
not snapshotted before its thirtieth day is gone.

**A limit on the loss figure, stated rather than rounded off.** Zero sessions
were found already unrecoverable, and that is a **lower bound, not a proof of
zero loss**: the index used to detect missing transcripts records only sessions
that received a *typed* prompt, so a reaped non-interactive session would be
invisible to it.


---

# Amendment 7 — a misconfigured Haiku arm, and the third boundary it creates

**2026-09-20.** A defect in the `cc_haiku45` arm's configuration, found and fixed
mid-window, recorded here because it changes what two reported quantities mean
and because **the arm it damages is a baseline, not the treatment — which is the
direction a reader is least likely to suspect and most entitled to be told
about.**

## A7.1 — What was wrong

`cc_haiku45` ran at `effort: low` and emitted a median **741 thinking tokens**
per call, where `cc_opus5` and `cc_sonnet5` emitted **0** on identical bytes at
the same setting.

The cause is a model-generation split inside Claude Code, read out of the shipped
2.1.278 binary rather than inferred. Claude Code **enables thinking by default
for every model** — there is no "off" default to fall back to. It resolves to
`{type: "adaptive"}` on 4.6+ models and to a **fixed `budget_tokens`** on
pre-4.6 models. Haiku 4.5 is pre-4.6. Adaptive thinking spends nothing on a
two-question classification; a fixed budget is spent. And `output_config.effort`
is a 4.6+ control that is **not supported on Haiku 4.5 at all**, so `--effort
low` could never have reached it.

So the zeros on Opus and Sonnet were honest adaptive behaviour, not a flag
working — and the lever we believed was controlling all three arms was
structurally inert on one of them.

Fixed by `max_thinking_tokens: 0`, which Claude Code maps to
`thinking: {type: "disabled"}`, on that arm alone.

## A7.2 — What was NOT fixed, and why

`cache_read_input_tokens` is **0 on every `cc_haiku45` call** while `cc_opus5`
reads 10,777. Haiku 4.5's minimum cacheable prefix is **4,096 tokens** against
512 on Opus 5. The stable prefix of our deliberately lean invocation falls below
it, so the only cache entry created sits *after* the per-decision state and no
two decisions ever share one.

This is **fixable** — padding the system prompt past 4,096 tokens produces
12,744-token cross-state reads immediately, and API time falls to 1.8–4.1s — and
it is **deliberately not fixed.** Padding a classifier's prompt with 9K tokens of
filler to buy cache reads would change what the arm measures, and the arm exists
to measure Claude Code as it ships. It is published as a finding about deploying
a pre-4.6 model behind `claude -p` on short prompts, not engineered away.

## A7.3 — The measured effect, and what it does not rescue

Paired on 9 existing synthetic states, old and new interleaved on the same state
so hour-of-day and machine load are paired:

| | v1 probe | **v2 fix** | `cc_opus5` |
|---|---|---|---|
| output tokens | 764 | **333** | 174 |
| thinking tokens | 647 | **0** | 0 |
| API ms | 9,254 | **4,557** | 3,476 |

**`cc_haiku45` remains slower than `cc_opus5` after the fix.** Roughly half the
original gap was our misconfiguration and half is the cache miss that remains.

"The cheaper tier is the faster tier" is therefore **not** restored by this
correction. A3.5's decision to make wall-clock a **co-primary outcome measured
rather than assumed** stands on stronger ground than when it was written.

## A7.4 — The third boundary

| timestamp | change | what it affects |
|---|---|---|
| **2026-09-20T12:07:24Z** | three arms → four (`cc_sonnet5` added) | rows before it carry no `cc_sonnet5` |
| **2026-09-20T14:24:13Z** | sequential → concurrent dispatch | per-arm latency only; marked by `arm_dispatch` |
| **2026-09-20T15:15:33Z** | `cc_haiku45` thinking disabled | `cc_haiku45` cost and latency only; marked by `arm_config_id` |

The third boundary is the **worker restart**, not the commit that changed the
config — the worker reads `arms.json` once at startup (JEV-30), so until it
restarted every new row was still v1. Its marker is the row's own
`arm_config_id`: `cc-haiku45-cli-v1` before, **`cc-haiku45-cli-v2-nothink`**
after. That is a stronger marker than a clock, because the row carries it.

**334 live and 60 synthetic rows carry v1.** Live v1 window:
2026-09-20T06:34:47Z → 14:51:21Z.

**`cc_haiku45` cost and latency are never pooled across this boundary.** Both are
reported per `arm_config_id`, with row counts, and no `cc_haiku45` cost or
latency figure is quoted without its configuration named. These are not
known-bad numbers — they are correct measurements of a configuration nobody
would deploy.

## A7.5 — Agreement is treated more cautiously here than at Amendment 5's boundaries

At those boundaries the arms received identical bytes and identical questions,
and nothing about dispatch timing could touch an answer, so agreement pooled
freely. **Here it cannot: thinking is part of the inference, not decoration.**

On 18 paired answers the change produced **1 decision flip at τ=0.5** and a mean
|Δp| of **0.078**, with one large move (0.85 → 0.02). That is small — and it is
**not distinguishable from run-to-run noise**, because `cc_haiku45` has no
determinism baseline: JEV-16 has never been run on it. Without one, "the
configuration changed the answer" and "the model is non-deterministic" are the
same number.

So: v1 agreement is **retained and labelled a v1-era measurement**; v1 and v2
answers are **not pooled as one arm**; and the writeup states that the two eras
were **not shown to be equivalent**, rather than implying they were. The cheap
purchase that would close this properly is a determinism sweep on `cc_haiku45`
at v2, and it is named as such rather than left implicit.

## A7.6 — The primary metric is untouched

It is PABAK between `jev` and `cc_opus5` on `pre_bash.destructive`. Neither arm
is involved in this defect and neither changed configuration at this boundary.

# Amendment 8 — the auth path, the cache-write multiplier it implies, and the reconciliation we cannot close alone

JEV-49. Every number in this amendment was measured from this machine's own
files; nothing is inferred from habit or assumption. Identifiers (account and
organisation UUIDs, email, organisation name) were never read into the record —
only billing *type* fields.

## A8.1 — The auth path, declared

A reader cannot reproduce a cost figure without it, because **cache-write
pricing depends on TTL and TTL availability depends on the auth path**: 1-hour
writes bill at 2× the input rate and 5-minute writes at 1.25×.

There are **three** auth paths in this study, not one, and they must not be
conflated:

| what | auth | evidence | billing surface |
|---|---|---|---|
| The Claude Code sessions that ARE the baseline (`data/baseline/`, `session_metrics.py`) | **Claude Max 5× subscription**, OAuth | `~/.claude.json` → `oauthAccount.billingType: stripe_subscription`, `organizationType: claude_max`, `organizationRateLimitTier: default_claude_max_5x`, subscription opened 2025-10-26; `hasExtraUsageEnabled: true` with `cachedExtraUsageDisabledReason: out_of_credits` | plan, not per-token invoice |
| The `cc_opus5` / `cc_sonnet5` / `cc_haiku45` arms | **the same subscription, deliberately** | `src/arms/claude_cli.py` pops `ANTHROPIC_API_KEY` from the subprocess environment with the comment "force subscription auth, not a key" | plan |
| The `jev` arm | **Vercel AI Gateway key** (`AI_GATEWAY_API_KEY`, the only key in `.env`) | `.env`, `src/arms/jev.py` | Vercel invoice, not Anthropic |

`src/arms/claude.py` (direct Anthropic API, `x-api-key`) exists but **has
produced no rows**: all 2,005 run rows are `jev`, `cc_opus5`, `cc_haiku45`,
`cc_sonnet5`, and no `ANTHROPIC_API_KEY` is present in `.env` or the
environment. **This study has made no Anthropic API-key spend at all.**

## A8.2 — The multiplier is read per row, not inferred from the path

Declaring the auth path explains *which TTLs can occur*; it does not license
assuming one. Every assistant row carries `usage.cache_creation`
`{ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}`, and this corpus
contains **both**, concentrated rather than mixed: across the whole project
corpus (unbounded), 12,334,854 tokens of 5-minute writes spread over 27
sessions against **5,161,696 tokens of 1-hour writes in exactly one**
(`4ba49645`, the sustained collection session — every one of its rows is
1-hour, every other session is 5-minute). **Inside the bounded baseline window
of A8.4 the 1-hour figure is 1,800,137 tokens**; the two numbers differ only in
scope. A flat multiplier cannot be right for a corpus shaped like that, and an
auth-level declaration would have hidden the split. No row in this corpus mixes
the two TTLs.

So: **`config/pricing.json` now carries both multipliers (1.25 and 2.0) and
`session_metrics.call_cost` selects per row from the transcript's own split.**

**Not independently verified:** the 2.0 figure is the published rate card
(`ccusage#899`). No session in this corpus that used 1-hour writes has written a
`cost-state` line, so we could not reconcile 2.0 against first-party accounting
the way 1.25 was reconciled. It moves the baseline total by **+$6.75**
and that sensitivity is published rather than buried: if 1-hour writes in fact
bill at 1.25×, subtract exactly that.

## A8.2b — Deduplication must keep the COMPLETED copy, not the first one

Found while measuring the other two, and it is larger than either. Claude Code
writes the same `(requestId, message.id)` **several times** as a turn streams —
up to 9 copies here. The early copies are placeholders: `input_tokens: 2`, no
`iterations[]`. Only the final copy carries the completed breakdown. A dedupe
that keeps the **first** copy — which is what every implementation we have seen,
including ours, did — keeps the placeholder and throws the turn away.

**48 keys in this corpus grow across their copies, all 48 monotonically, all 48
inside subagent transcripts**, for 4,889,713 input tokens in one session.
Inside the baseline window it recovers **2,586,255 input tokens, worth
+$29.84** — the single largest correction in this ticket, and the one that
lands hardest on *delegated* work, because that is where it occurs.

`session_metrics.merge_copies` therefore folds every copy of a key together by
per-field maximum (equivalent to "last wins" on all 48 observed keys, and
immune to a non-monotonic sequence).

**Partial first-party support.** Across 67 sessions with a `cost-state` line,
the rule changes nothing in 57. Of the 10 where it bites it moves our totals
**closer** to Claude Code's own figures in **7** and further in **3** — and in
all 3 the `cost-state` is itself truncated (it reports 0, 12,079 and 25,981
output tokens against 105k–2.2M in the transcript, i.e. it was written before
most of the session's work). On the fixture session the residual against
first-party accounting improves from **−27.55% to −21.68%** and stays negative,
which is the direction a lower bound must move in.

## A8.3 — `claude-opus-4-7` is priced by measurement, not by guessing

It was absent from `config/pricing.json`, so **14 of the 15 baseline sessions
contributed exactly $0.00 to the published $125.58** — they are 100%
`claude-opus-4-7`. "Excluded and noted in the manifest" is **not** acceptable
for a published headline when the exclusion is that large.

The rate was not guessed and not substring-matched from "opus" — that is
`claude-spend#31`'s 437% over-report. It was **solved**: `$5/MTok` input and
`$25/MTok` output is the unique pair that reproduces
`cost-state.modelUsage['claude-opus-4-7'].costUSD` **to the cent in every session
of this project that reports one — 40 at the time of writing, and the corpus
is still growing, so the claim is universal rather than a count**, with cache writes at 1.25× and reads at 0.10× — the
same method `pricing.json:_verification` already used for Haiku 4.5 and Sonnet
5. Worked example (session `0982af7b`): in 9, out 4,969, cache write 49,379,
cache read 126,594 → $0.49618575 computed against $0.49618575 reported.

**Unknown model IDs remain a hard failure**, now literally:
`session_metrics.analyse(..., strict=True)` raises `UnpricedModelError` rather
than returning a partial total, and `render()` prints `LOWER BOUND` on the cost
line itself whenever anything is excluded. A model with a rate is priced; a
model without one stops the report. Neither is a footnote.

## A8.4 — The reconciliation: what we did, and the criterion that stays OPEN

**What we could do.** Over the bounded window
**2026-09-19T19:58:56Z → 2026-09-20T14:50:13Z** (15 sessions, 1,161 billable
requests, the same window `data/baseline/manifest.json` snapshots), the
transcript-derived total is **$175.36** post-fix against **$125.58** pre-fix —
**+$49.77, +39.6%** — decomposing as iterations **+$4.69**, completed-copy
dedupe **+$29.84**, 1-hour cache writes **+$6.75**, `claude-opus-4-7` priced
**+$8.50**.

For the 14 sessions that carry a `cost-state` line, our post-fix figure is
**$8.4958 against Claude Code's own $8.7191 — a residual of −$0.2234, −2.56%.**

**What that residual does and does not validate — stated plainly, because it is
easy to read it as more than it is.** Those 14 sessions are 100%
`claude-opus-4-7` and carry no iteration under-count, no multi-copy key and no
1-hour cache write. **The residual therefore validates the derived rate and the
1.25× multiplier, and nothing else.** Every dollar of the iterations, copy and
1-hour corrections falls in `4ba49645`, the one session with no `cost-state`
line at all. The copy rule has partial independent support (A8.2b, 7 sessions
of 10); the iteration rule and the 2.0 multiplier have **none in this corpus**,
and are adopted on mechanism and on the published rate card respectively.
**The sign is negative and it is expected to be**: Claude Code bills for
background models it never writes into a transcript, so a transcript-derived
figure is a **lower bound**, and a positive residual would indicate
double-counting. Method: dedupe on `(requestId, message.id)`; token fields
summed from `iterations[]`, cache scalars from the top level; every copy of a
key folded together rather than the first kept; 1-hour writes at
2×; web search added from `cost-state.modelUsage[*].webSearchRequests` at
$0.01 (it is **$0.00 in this window** — no web search occurred).

**What we could not do, and will not fake.** This is a reconciliation against
*Claude Code's own estimate*, which Anthropic's documentation describes as
computed "from token counts at list price" — an estimate, not a billing record —
and whose cache-statistics line "covers the main conversation only, not
subagents", i.e. first-party instrumentation goes silent exactly where this
study lives. **It is not the Console reconciliation the ticket asks for, and it
cannot be run from this process: there is no browser here, and the spend is on a
subscription rather than per-token API billing, so it may not appear on the
Console usage page at all.**

**The criterion therefore stays OPEN.** What the operator must supply, exactly:

1. Console → Usage, UTC range **2026-09-19T19:58Z to 2026-09-20T14:50Z**,
   grouped by model, showing input / cache-write (5m and 1h separately if
   offered) / cache-read / output tokens and USD.
2. A statement of **whether Claude Max subscription usage from Claude Code
   appears on that page at all**, or whether it is billed to the plan and
   therefore invisible there. If invisible, say so in the writeup: the honest
   finding is then "a transcript-derived figure for subscription-authenticated
   Claude Code cannot be reconciled against the Console by construction", which
   is itself the contribution and is stronger than a number.
3. If any **extra-usage credits** were consumed in the window
   (`hasExtraUsageEnabled: true` on this account), the credit-consumption figure
   for it — that portion *is* per-token billed and *is* reconcilable.
4. The **Vercel AI Gateway** invoice line for the same window, which is the only
   independent check available on the `jev` arm's spend.

Until (1)–(4) arrive, the published number is the transcript-derived total with
its method and its **−2.56% residual against first-party accounting**, labelled
a lower bound, with the scope of that residual stated as in A8.4. No Console
figure is asserted, estimated, or implied.

## A8.5 — The pricing table changed, so its version string changed

`config/pricing.json` gained `cache_write_multiplier_1h` and a
`claude-opus-4-7` rate. Under the old version string `pricing-2026-09-20` the
same name would have covered two different tables — exactly the hole the
JEV-30/31b prep names ("an operator can edit a rate without bumping
`version`"). The table is now **`pricing-2026-09-20b`**.

**Consequence, stated rather than left to be discovered:** all 2,005 existing
run rows and `data/baseline/manifest.json` carry `pricing-2026-09-20`, and
their `cost_usd` values were computed under it. They are not re-costed by this
ticket and **must not be pooled with anything stamped `-b` without saying so**.
Run rows are unaffected in substance — they carry only the four scalar usage
fields, with no `iterations[]` and no TTL split, so none of A8.2/A8.2b can be
applied to them retroactively at all (see the JEV-49 prep for the one-line
change to `src/arms/claude_cli.py` that would persist both going forward).
