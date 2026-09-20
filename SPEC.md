# Spec

**Read the Status section before the body.** This document is written in layers: the
original spec (written before any measurement), then the decisions and evidence that
superseded parts of it. Superseded passages are *annotated in place*, never deleted —
the reversals are results, and a reader who cannot see what we believed first cannot
judge what changed our minds.

There is no external issue tracker; the tracker is **`ISSUES.md`** in this folder — a flat markdown file, one `##` heading
per issue, with `Status:` (`ready-for-agent` | `in-progress` | `blocked` | `done`), `Labels:`, and a
body. It lives in git, so issue history and code history are the same history, which for a
single-author study is the whole point. Issues are numbered `JEV-nn` and never renumbered.

## Design decisions settled by the 2026-09-20 grilling

Five rounds of twenty questions were asked. **Sixteen were answered; four were
not.** The distinction matters and was previously lost: an earlier version of
this section presented all twenty as settled decisions. Q9–Q12 were asked in
Round 3 and **never answered** — the round was overtaken by a sub-agent report
and the interview moved on to Round 4. What appears below for Q10, Q11 and Q12
is therefore the *recommendation as offered*, marked **UNRATIFIED**, and Q9 —
the unit of randomisation, the single most consequential design choice in the
A/B — is **still open**.

Recorded here because several answered decisions reverse earlier choices in this
spec, and the reversals are themselves results.

### Answered 2026-09-20 — the round that never reached the owner

Q9–Q12 were asked in Round 3 and **never answered**; the round was overtaken by
a sub-agent report and the interview moved on to Round 4. An earlier version of
this spec presented them as settled decisions, which they were not. They were
put again, together with a fifth question (Q13) that had never been asked at
all, and answered.

| # | question | answer |
|---|---|---|
| **Q9** | unit of randomisation | **per delegation** — coin flip at every `Agent` spawn. Not a paired comparison, and carryover runs treatment→control, so a null result is weaker evidence here than a positive one |
| **Q10** | quality measurement | **blinded grader** as the primary quality measure, with an explicit blind-integrity check; friction proxies retained as secondary and labelled unblinded |
| **Q11** | primary outcome | **raw net cost**. Rework-adjusted cost is demoted to a conditional secondary because the escalation→predecessor link has no producer and a missed link biases the treatment in its own favour |
| **Q12** | concurrent with `pre_bash` | **yes.** The accepted cost is that the `pre_bash` primary metric most likely returns *inconclusive by rule* |
| **Q13** | control arm | **the current default** (`inherit` = Opus on every task) — the realistic counterfactual, since Opus-on-everything is what an ordinary user runs |

**The objection to Q13 stands on the record.** Measuring only against the
default conflates *routing helps* with *Jev helps*: a two-line static
`subagent_type → tier` rule would capture much of the saving with no classifier
at all. This design cannot separate the two by randomisation. The registered
mitigation costs nothing — the static rule's assignment is computable offline
for every task, so the writeup reports **how often Jev agrees with two lines of
`if`**, and if that agreement is high, it is stated as a headline caveat
whatever the cost result says.

Full reasoning for each in `PREREGISTRATION.md` §A2.0.

### The routing experiment

| # | decision |
|---|---|
| Q5 | **A/B with actual routing**, not shadow-mode inference. |
| Q9 | **Randomise per delegation** — coin flip at every `Agent` spawn. |
| Q13 | **Control arm is the current default** (`inherit` = Opus on every task), chosen for external validity. See the objection above. |
| Q17 | **Unit of routing is the delegated task, not the turn** — forced by the mechanism constraint, which still holds for turns. The *selection* mechanism is amended: the three listed here (`CLAUDE_CODE_SUBAGENT_MODEL`, `--agents`, frontmatter) are all static per-session or per-agent-type, so none of them lets Jev decide anything per task. The mechanism that does is a **`PreToolUse` hook on the `Agent` tool rewriting `tool_input.model` via `updatedInput`** — see *Four things a reader should be told plainly* §1. |
| Q17b | **Adopt a global "delegate to a subagent where possible" working rule**, to increase the share of spend that is routable. *See the confound note below.* |
| Q10 | **Quality measured by a blinded grader** (primary), with friction proxies and escalation rate as unblinded secondaries. Explicitly NOT self-rating. |
| Q11 | **Two co-primary outcomes: raw net cost and net wall-clock, per delegated task** (A3.5). The original answer named cost alone; speed was reinstated 2026-09-20 because the argument for excluding it applied just as well to cost. Net-of-rework was the original recommendation and is now a conditional secondary — the link it needs has no producer, and a missed link flatters the treatment. |
| Q12 | **Runs concurrently with the `pre_bash` window.** Arm assignment must be recorded on every `pre_bash` capture so the analysis can condition on it — routing changes which model generates the commands, so the capture stream is no longer stationary. |
| Q16 | **Aggressive thresholds.** Break-even is 37.5–44.4%; the economics have slack. |

### Statistical discipline

| # | decision | status |
|---|---|---|
| Q13, Q20 | **Degenerate-interval guard**: <30 clusters OR zero width → inconclusive by rule; cluster count always printed | **IMPLEMENTED** — `stats.Interval`, Amendment A1.1 |
| Q14 | **Stopping rule amended** from 7 calendar days to 30 distinct sessions or 2026-10-20 | **IMPLEMENTED** — Amendment A1.2 |
| Q15 | **Overridden 2026-09-20: 60 items, not 360.** The scope had changed under the decision — Q8's fifth arm turned it into 1,440 calls and 4.1 hours. Cut to completing the five-arm matrix on the existing 60. **The threshold-overfit gap does not close and becomes a stated limitation.** | **DECIDED** — JEV-22 |

### Scope of publication

| # | decision |
|---|---|
| Q4, Q7 | **Code + aggregate results + the 360-item synthetic set.** No live data, no state text, no run rows. The synthetic set carries no private data and is the project's most reusable artifact. |

### Arms and questions

| # | decision |
|---|---|
| Q8 | **Four baseline arms**: `cc_opus5`, `cc_sonnet5`, `cc_haiku45`, `cc_fable51`, plus `jev`. |
| Q19 | **Fable stays, and a `verbosity` question is added.** *(Recorded earlier as "`v2` gains" it — inaccurate: no `verbosity` question has ever been written, in v2 or anywhere. It is specified for `questions/agent_route/v1.json`, which does not exist yet either. JEV-25.)* Fable is *not* a cheap tier — at $10/$50 it is twice Opus — but its cache reads are half Opus's in absolute terms, so it wins only on cache-heavy *terse* turns. A one-dimensional complexity score cannot express that; routing to Fable needs a prediction of the turn's **shape**. |

---

## Four things a reader should be told plainly

**1. The mechanism is the binding constraint — but it binds more narrowly than
we first wrote, and the correction is a finding in its own right.**

The earlier claim was "no hook event accepts a `model` field; the harness has
nowhere to put the answer." The first half is now **refuted against primary
source**, and the second half was too strong.

*What is still true.* **Per-turn routing inside an interactive session remains
impossible.** Every model-switching mechanism is session-scoped (`/model`,
`--model`, `ANTHROPIC_MODEL`, SDK `set_model`) — they change the model from that
point forward, not for one turn. `PreModelSwitch` fires only on a switch someone
else initiates and can `allow`, `deny` or `ask`; the documentation states
explicitly that it does **not** accept `updatedInput`, so it cannot redirect a
switch to a different model, let alone start one.

*What is false.* A `PreToolUse` hook matched on the **`Agent`** tool can return
`permissionDecision: "allow"` together with **`updatedInput`**, which replaces
the tool's input before it runs — and the `Agent` tool's input includes a
`model` field. So a hook can read `tool_input.prompt`, ask Jev which tier the
task needs, and rewrite `model` on the way through. **Jev can be in the loop,
deciding, on live traffic.** This is a genuine routing mechanism, and the study
had written it off.

*Why this changes the experiment and not just the prose.* Without it, the A/B
compares fixed tiers and Jev's contribution is counterfactual — inferred from a
shadow classification that never touched anything. With it, the treatment arm is
**actually Jev-routed**, which is the experiment the thesis claims to be running.

*What comes free with it — less than it first appears.* The matching
`PostToolUse` on `Agent` returns `resolvedModel`, which is exactly the field the
verification assertion in *Testing Decisions* §5 needs. **The outcome fields do
not come free.** Since v2.1.198 subagents run in the **background by default**,
and a background launch returns `status: "async_launched"` with no usage fields
at all — `usage`, `totalTokens`, `totalDurationMs` and `totalToolUseCount` are
present only on a `completed` (foreground) response. So the verification
assertion survives on the default path and the **outcome measurement does not**.
Cost and timing per delegated task must come from the subagent's own transcript
under `<session>/subagents/` — which this study already reads for cost
reconciliation — or from a `SubagentStop` hook. Assuming otherwise would have
produced an A/B whose primary outcome was silently missing on most tasks.

*Four caveats, none fatal, all to be handled in JEV-23:*

1. **`updatedInput` replaces the entire input object.** `prompt`, `description`
   and `subagent_type` must be echoed back unchanged or the delegation is
   corrupted. A hook that silently drops a field would look like a routing effect.
2. **`resolvedModel` can differ from the requested `model`** — an
   `availableModels` allowlist or a `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` session
   setting overrides the hook. This is precisely why the assertion is written
   against `resolvedModel` and not against what we asked for.
3. **This hook is synchronous on the critical path of every subagent spawn.** It
   is the one place in the study where a Jev call is not free. At the measured
   ~624ms p50 enforce overhead against a subagent run measured in tens of
   seconds, the ratio is favourable — but it must be *measured in the A/B*, not
   assumed, and it must fail open.
4. **Multi-hook precedence is unverified.** If more than one `PreToolUse` hook
   returns `updatedInput` for the same call, which one wins is not something we
   have confirmed from source. Only one such hook will be registered; noted so
   that a future second one is not added casually.
5. **It needs the `JEV_ARM_SUBPROCESS` recursion guard**, for the same reason
   `capture.sh` does: the `cc_*` arms spawn `claude -p` inside this repository,
   and a routing hook without the guard would classify — and rewrite the model
   of — delegations made by the study's own measurement subprocesses.

**Verified 2026-09-20 against `code.claude.com/docs/en/hooks.md`** (the `Agent`
tool input table, the `PreToolUse` decision-control table, and the
`PreModelSwitch` section), on Claude Code v2.1.278. `FINDINGS.md` Part 5c states
the superseded version. **Corrected 2026-09-20** — Part 5c now carries the
surviving half precisely, keeps the refuted text verbatim as superseded, and
records the correction as a dated finding. The error is worth reading: it was a
category error, not a misreading. `model` genuinely is not a hook *output* key —
it is an `Agent` tool *input* key, and `updatedInput`, which the superseded text
itself listed among the available outputs a few lines above its own conclusion,
replaces the entire tool input. **The evidence that refuted the section was
inside the section**, and it took re-reading primary source rather than
reasoning harder about what was already written down.

**2. The "delegate where possible" rule is a confound, and must be disclosed.**
Adopting it changes how the work is done in order to make more of it routable.
That improves the experiment's power and simultaneously makes the measured
workload less representative of ordinary use. The writeup must state that the
delegation rate was deliberately raised, and report what fraction of spend was
delegable **before** the rule was adopted, from the existing transcripts.

**3. Fable's pricing is unverified.** Every other rate in `config/pricing.json`
was reconciled against Claude Code's own `cost-state` to the cent. Fable's comes
from documentation, and its 2.5% cache-read multiplier contradicts the uniform
10% verified empirically for three other models. No published Fable figure until
one real Fable session is reconciled.

**4. The delegation rule and the primary metric pull against each other.** This
is not a presentational point; it is a live threat to the headline number, and it
was found by reading the two decisions side by side rather than by either one
alone. Q17b routes work into subagents. Subagent `pre_bash` captures carry
`is_sidechain: true`, and pre-registration §4 excludes those from the headline.
So the more successfully Q17b runs, the faster the *main-session* `pre_bash`
stream drains — at exactly the moment the A1.2 stopping rule starts counting
sessions towards 30. **Adopting the routing experiment can starve the gating
experiment.** Resolution is specified under *Interaction: Q17b × the `pre_bash`
primary metric* below; whichever way it is resolved, the writeup states that the
two experiments shared a collection window and how that was handled.

---

## Cost note on Q15 — resolved 2026-09-20

Q15 (run all 360 synthetic items through all arms) was agreed when there were
**four** arms. Q8 made it **five**, and the arithmetic changed underneath the
decision:

| | Jev only | five arms x 360 | **five arms x 60 (chosen)** |
|---|---|---|---|
| wall clock, serial | ~4 minutes | ~4.1 hours | **~20 minutes** |
| subscription calls | 0 | 1,440 | **120** |

The binding cost was never dollars — it is **subscription quota in the same week
as the routing A/B**, which is the headline experiment and needs the same quota.

**Decision: 60.** `cc_sonnet5` and `cc_fable51` have never run on anything, so
the 120 calls complete a clean five-arm matrix on items already collected, with
the same `state_sha256` and therefore direct pairing against the existing rows.

**Its cost, stated rather than buried: the threshold-overfit question does not
close.** The optimism gap stays at 0.097 at n=59 instead of falling to ~0.020 at
n=300. It becomes a limitation the writeup declares, and the weight shifts to
JEV-17's rule-based operating point — which is what a rule is for. The 300 unrun
items stay on disk; the larger run is deferred, not discarded.

## The routing state — and why JEV-18 and JEV-23 are different claims

The unit of routing is the delegated task, so the state Jev classifies is the
**`Agent` tool's `prompt`**, not the user's prompt. That was never written down.

**Two corrections to the previous text, found by audit.** It claimed the
`verbosity` question "landed in `questions/user_prompt/v2.json`" — **it did
not**; v2 contains `complexity`, `needs_frontier` and `route`, and no
`verbosity` question exists anywhere. And it described `complexity` as a
`choice` over tiers — it is a **`score`**, deliberately, and the file states the
reason: *"Anchors describe the WORK, never the model — naming models in the
anchors would leak the policy into the measurement."* Tier selection is a policy
applied in analysis (`_tier_mapping`), not a question put to the classifier.
That separation is correct and `agent_route` must preserve it.

**`agent_route` — a new surface.**

| | |
|---|---|
| hook | `PreToolUse` matched on `Agent` |
| state | `tool_input.prompt` + `tool_input.subagent_type`, and nothing else |
| questions | `questions/agent_route/v1.json` — `complexity` (**score**, 1–5, anchors describing the work and never naming a model) and `verbosity` (**score**, predicted output length). Tier selection stays a policy in `_tier_mapping`, applied in analysis |
| output | `updatedInput` with `model` rewritten, everything else echoed unchanged |
| verification | `PostToolUse` on `Agent`: `resolvedModel` — the only field present on a background launch |
| outcome | the subagent's own transcript under `<session>/subagents/`, or a `SubagentStop` hook. **Not `PostToolUse`** — since v2.1.198 subagents run in the background by default, and an `async_launched` response carries no usage, token or timing fields at all |

**GATE 4 is satisfied by construction here, and that is worth stating rather
than assuming.** The state is the hook payload and only the hook payload. There
is no transcript read, no byte offset, no truncation marker — so the
future-leakage question that makes `stop` hard does not arise at all. `stop` is
the surface where leakage is a real risk; `agent_route` is the surface where it
is structurally impossible. The gate should still assert it, because "impossible
by construction" is a claim about code that changes.

**The two tickets make different claims, and merging them would overclaim.**

| | JEV-18 (`user_prompt`) | JEV-23 (`agent_route`) |
|---|---|---|
| mode | shadow | live intervention |
| state | the user's prompt | the delegated task's prompt |
| claim | *"if per-turn routing existed, here is what it would have saved"* | *"here is what routing delegated tasks did save"* |
| evidence | counterfactual, unfalsifiable by design | measured, with a control arm |

JEV-18's claim is the weaker one and must be labelled as such wherever it
appears: it is a **potential-savings estimate against a mechanism that does not
exist**, and no amount of data makes it more than that. JEV-23's claim is the
headline. If only one gets done in the budget, it is JEV-23.

---

## Interaction: Q17b × the `pre_bash` primary metric

Three things are underdefined where the routing experiment touches the gating
experiment. Fixed here, before the A/B starts, because all three are choices that
could otherwise be made after seeing which way they push the number.

**1. `is_sidechain` exclusion stands, and its cost is reported.** Pre-registration
§4 excludes sidechain captures from the headline, and that exclusion is *not*
relaxed — relaxing an exclusion mid-study to recover sample size is precisely the
move pre-registration exists to prevent. Instead the writeup reports, for the
collection window, the count of live `pre_bash` captures **split by
`is_sidechain`**, so a reader can see how much of the stream the delegation rule
moved out of the headline. If the main-session stream fails to reach 30 sessions
by 2026-10-20, the primary metric is **inconclusive by rule** (A1.1) and is
published as such. It is not rescued by pooling sidechains.

**2. The clustering key does not change.** `session_id` remains the cluster. A
subagent runs under its own session; those rows are excluded from the headline
anyway, so no cluster is split or merged by the delegation rule.

**3. `arm` on a `pre_bash` capture is a per-task attribute, and most captures do
not have one.** Q12 says "record arm assignment on every `pre_bash` capture",
which is not literally possible: arms are assigned per *delegated task*, whereas
`pre_bash` fires per *command*, and a command issued by the main session belongs
to no arm. Definition, fixed now:

| field | value |
|---|---|
| `routing_arm` | the model tier assigned to the delegated task, or `null` |
| `routing_context` | `main_session` \| `delegated` \| `unassigned_delegated` |

`main_session` is the correct value for a command Claude runs directly, and it is
**not** a missing value — it is a distinct stratum. `unassigned_delegated` covers
subagent commands captured before or outside the A/B, and exists so that an
absent assignment can never be silently read as `main_session`. The analysis
conditions on `routing_context`; the headline uses `main_session` only.

---

## Status — 2026-09-20

This spec was written before any measurement. Four things in it have since been
**superseded by evidence**, and are recorded here rather than silently edited,
because the changes are themselves results.

**1. The question changed.** The spec asks whether Jev is a good classifier. The
article asks whether **Claude Code becomes faster, more accurate and
token-optimised** with Jev. Those are different, and separating them reversed a
conclusion: a gate is *additive* on every axis — it adds ~337 tokens and 557ms
per decision and removes neither — so **gating cannot make Claude Code faster or
more token-efficient, by construction.** It can only make it safer, and this
repository's near-zero destructive base rate cannot demonstrate that. See
`FINDINGS.md` Part 4c.

**Read that as a statement about gating only.** It was briefly over-extended into
"speed is not reachable at all", on the grounds that routing's speedup is a
property of the smaller model rather than a contribution of the classifier.
**That argument is equally true of cost**, which was kept as the headline
regardless — so it proves too much. Everything currently runs on Opus; moving
delegated tasks onto smaller tiers makes them finish sooner, by the same act of
picking the right tier that makes them cost less. Wall-clock is a **co-primary
outcome** of the routing A/B (`PREREGISTRATION.md` A3.5), measured net of the
hook's own latency, with felt time reported beside measured time.

**2. Surface priority is reversed.** `pre_bash` was staged first because it was
simplest to measure. **`user_prompt` / routing should have been first**: one turn
moved Opus→Haiku saves 3,674× the cost of the Jev call that decided it, and it is
the only mechanism in the study that could make Claude Code genuinely faster.
See *Surface plans* below.

**3. The baseline is a harness, not a model.** The study runs entirely on a
Claude subscription via `claude -p`, with no `ANTHROPIC_API_KEY`. The `cc_*` arms
bundle the model with ~10K tokens of preamble and a process spawn, so every claim
is about **Claude Code as deployed**, not about Opus as a classifier. Every
surface section prints an attribution table decomposing harness from model. See
`FINDINGS.md` Appendix C.

**4. "Choose a threshold" became "choose a rule".** Fitted constants (τ=0.36,
τ=0.95) do not survive train/test validation — optimism gap ≈ +0.10, and 0.36 is
an unstable constant selecting anywhere in 0.36–0.63. Operating points must be
selected by a rule that re-derives itself as data accumulates. See Part 4d.

### What is built and measured

| | state |
|---|---|
| `pre_bash` surface | **live**, 16 live + 60 synthetic captures |
| `agent_route` surface | **specified 2026-09-20, not built.** The mechanism is verified; the hook, question set and state builder do not exist |
| Jev vs Claude Code discrimination | **measured** — AUC 0.977 vs 0.980, indistinguishable |
| Enforce overhead | **measured** — 624ms p50 / 929ms p99, ~69ms irreducible |
| Threshold validation | **measured** — neither fitted constant survives |
| Cost reconciliation | **measured** — transcripts under-report by 27.6% |
| Determinism rate | **NOT measured** — the one blocker for enforcement |
| Future-leakage guarantee | **NOT tested** — asserted in three documents, verified nowhere |
| `stop`, `user_prompt`, `post_edit` | specified and planned; **never run** |
| Gold labels, calibration metrics | Phase 2, untouched |

---

## Surface plans — taking `stop`, `user_prompt` and `post_edit` live

**Status: plan only. Nothing here is implemented.** Merged into this spec from
`docs/PLAN-SURFACES.md` on 2026-09-20; tracked as JEV-13, and read beside the
nine design-review decisions in `docs/PLAN.md`.

`pre_bash` is live with 62+ captures. The other three have question sets and
state builders that have **never executed against a real payload**. Everything
below treats that as the primary fact: these are not "register and go", they are
three unvalidated code paths. A fourth surface, `agent_route`, is **sequenced**
in §0.1 because it comes first — but it is **specified** in *The routing
state* above and built under JEV-23, outside this plan's scope.

> **Verification note.** The defects in §6 were independently confirmed against
> the source before this plan was accepted — except §6.1, which is *contested*;
> see the note there. Claims not yet checkable against a live payload are marked.

---

### 0. Cross-cutting decisions (do these before any surface)

#### 0.1 Sequencing

**Order: `agent_route` → `user_prompt` → `stop` → `post_edit`. Staged, never simultaneous.**

**The mechanism is named and resolved — it is not a pending thing this plan
waits on.** An earlier version of this section sequenced an undefined "mechanism"
first, on the belief that no hook could carry a routing decision. That belief is
**refuted**: a `PreToolUse` hook matched on the **`Agent`** tool returns
`permissionDecision: "allow"` plus `updatedInput`, which replaces the tool input
— including its `model` field — before the subagent spawns. Per-**turn** routing
inside an interactive session is still impossible (every switch is
session-scoped; `PreModelSwitch` accepts only allow/deny/ask and explicitly not
`updatedInput`), but per-**task** routing is available today.
`code.claude.com/docs/en/hooks.md`, Claude Code v2.1.278, verified 2026-09-20;
see `FINDINGS.md` Part 5c and *The routing state* above.

**So the two routing surfaces make different claims, and the order follows from
that.** `agent_route` (JEV-23) is a **live intervention** with a control arm —
*"here is what routing delegated tasks did save"* — and it is the headline.
`user_prompt` (JEV-18) is a **shadow counterfactual** — *"if per-turn routing
existed, here is what it would have saved"* — a potential-savings estimate
against a mechanism that does not exist, **unfalsifiable by design**, and no
amount of data makes it more than that. If only one gets done in the budget, it
is `agent_route`.

| # | Surface | Why here |
|---|---|---|
| 1 | `agent_route` | The only surface where Jev's decision **changes what the harness does**, so the only one that can produce a measured routing result rather than an estimate. Its state is the hook payload and nothing else (`tool_input.prompt`, `tool_input.subagent_type`), so GATE 4 is satisfied by construction. Specified in *The routing state* above — do not redesign it here. Its question set `questions/agent_route/v1.json` **does not exist yet** and is the build cost (JEV-25). |
| 2 | `user_prompt` | `FINDINGS.md` Part 4c is an explicit course correction: **gating is additive on every axis; routing is the only surface that can make Claude Code faster or cheaper.** Strongest economics (one correct downgrade in ~4,000 pays for itself), thinnest evidence (8 prompts, outside the harness, confidently wrong on the hardest item). Payload-only and shadow-only — it depends on no mechanism and never will, because the mechanism it would need is the per-turn one that does not exist. |
| 3 | `stop` | Riskiest mechanism; do it while the hook change is fresh. Lowest volume, so all three arms on 100% is affordable. Its Step 0 unknowns are cheap to learn and could kill the surface — learn that early, not last. |
| 4 | `post_edit` | Payload-only and low-risk, but the only `score` question, and it needs a synthetic set before live data means anything. The build cost is in the stress set, not the registration. |

**Why not simultaneously.** `worker.py` drains serially. At `cc_opus5` 4.2s p50 /
32s p99 and `cc_haiku45` 12.7s p50, one decision costs **20–40s of worker
wall-clock**. Four surfaces at ~50/day × 30s ≈ **100 min/day** of serial draining,
arriving in bursts far faster than it drains. `capture.sh` stops writing above 500
spool files and **exits 0 silently** — the failure mode is invisible data loss.
Stage them, and watch `ls spool/ready | wc -l` during the first session of each.

#### 0.2 Per-surface arms (the `cc_*` arms are too slow to *drain*, not too slow to *observe*)

Nothing is on the critical path in shadow mode; the problem is drain throughput.
**`agent_route` is the exception and is not covered by this table.** It is a live
intervention, synchronous on the critical path of every subagent spawn, so it
must fail open and its added latency must be *measured* in the A/B rather than
assumed free. Its arms are an A/B treatment and control over delegated tasks,
not this table's jev-plus-subsampled-baseline shadow structure — stated here
rather than given an invented row.

1. **Add a per-surface `arms` list to `config/surfaces.json`**, defaulting to
   `arms.json:enabled`:

   | surface | arms | rationale |
   |---|---|---|
   | `pre_bash` | jev, cc_opus5, cc_haiku45 | unchanged; the primary metric depends on it |
   | `stop` | jev, cc_opus5, cc_haiku45 | low volume, high value per row |
   | `user_prompt` | jev 100%, cc_opus5 subsampled | highest volume, cheapest question |
   | `post_edit` | jev 100%, cc_opus5 subsampled | large states (whole diffs); drop cc_haiku45 |

2. **Deterministic baseline subsampling**, not random: run the `cc_*` arms only
   when `int(sha256(decision_id)[:8], 16) % k == 0`, `k=3`. Deterministic so a
   replay reproduces exactly which rows are paired, and so it can be
   pre-registered as a *rule* rather than a seed. Jev runs on 100% always — those
   rows still carry sharpness, latency, base rate and realised-cost correlation.
   Paired agreement is computed on the sampled subset only, and the report must
   print `n_paired` beside `n_rows`. Record `baseline_sample_rate` on the capture.

#### 0.3 These surfaces are outside the current pre-registration

`PREREGISTRATION.md` §1 scopes Phase 1 to **one surface (`pre_bash`)**, and §8
freezes `questions/*/v1.json` at that commit. Two non-optional consequences:

- **Any question-set change is a new version file, never an edit.** The
  `complexity` question below goes in `questions/user_prompt/v2.json`.
- **Write and commit `PREREGISTRATION-SURFACES.md` before the first capture of
  each surface**, stating that surface's primary metric, directional hypothesis,
  expected base rate and falsification condition. A surface registered after its
  data exists is not pre-registered, and a hostile reader will say so.

#### 0.4 GATE 4 — the leakage test that does not currently exist

The gate itself is specified under *Testing Decisions* §4 and tracked as JEV-15;
it is not restated here. What this plan adds is the measurement that motivates
it: **`tests/gates.sh` has 21 assertions and none of them test decision #7.** The
study's most load-bearing methodological claim is asserted in three documents and
verified nowhere.

Its negative control is worth keeping in view while building the `stop` surface:
strip the byte offset and assert the capture is **quarantined**, not processed.
`build_stop` already refuses without the offset; the gate proves that refusal is
wired through the worker rather than merely present in the builder.

Build it with the mechanism, before `stop` is registered. **This gate applies to
the already-live `pre_bash` surface too** and should not wait for `stop`.

#### 0.5 The rule that resolves most of the confusion below

> **Future turns are forbidden as STATE. Future turns are permitted as LABELS.**

Decision #7 forbids *showing an arm* anything after the decision point. It says
nothing about the analysis deriving an *outcome* from later turns — that is what a
label is. This unlocks free, human-free labels on two surfaces (§1.7, §2.4). Write
**it here, not into `docs/PLAN.md`** — that document was frozen as a historical
record on 2026-09-20 and must not receive new rules. `CONTEXT.md` carries the
vocabulary; this spec carries the rule. It was previously implicit, and an
implicit rule about what an arm may see is exactly the kind someone gets wrong.

---

### 1. `stop` — the blocker, and how it is resolved

#### 1.1 The blocker

`build_stop` requires `payload["transcript_bytes_at_capture"]` and raises without
it. `capture.sh` is `cat > tmp; mv tmp ready/` — it never parses, so it cannot
find `transcript_path`, so it cannot `stat` it. Decision #7's mechanism has no
implementation route as written. The builder's refusal is currently the only thing
preventing a silent leak.

#### 1.2 Options

| Option | Verdict |
|---|---|
| **A. Filename-encoded offset, zero-fork extraction, one `stat`** | **RECOMMENDED** |
| B. Rewrite the JSON to inject the field | Rejected: makes the spooler a JSON writer in bash 3.2, and the payload is no longer byte-exact |
| C. `cp` the whole transcript at hook time | Rejected: MB-scale transcripts → 10–50ms, 5× over budget; duplicates third-party content into the repo (which JEV-06 deliberately avoided); and a `cp` racing an append has the *same* boundary problem, just with more bytes |
| D. Timestamp marker | Rejected: needs a `date` fork anyway, 1s resolution against a transcript gaining lines per second. Strictly fuzzier than bytes for the same cost |
| E. `last_assistant_message` only | Rejected by the question set's own reasoning: completion is relative to what was asked |

#### 1.3 STEP 0 — the two unknowns that decide viability

**Do this before writing any code.** Register `stop` as `capture_only` with the
*current unmodified* `capture.sh`, run one session, inspect the payload by hand:

1. **Does the Stop payload carry `last_assistant_message`?**
   > **CONTESTED.** The planning agent believed it "very likely absent". Earlier
   > research in this project recorded Stop stdin as carrying `stop_hook_active`
   > **and `last_assistant_message`**. One of these is wrong, and it is cheap to
   > settle by looking. Do not build on either belief.
2. **Is the final assistant message flushed to the transcript before Stop fires?**
   Compare `stat -f %z` at hook time against the transcript's last complete line.
   If the flush happens *after* the hook, the byte prefix ends before the message
   being judged and **no truncation marker fixes that.**

**If both go the wrong way, `stop` has no valid state and the surface is cancelled
with a written negative result.** "The Stop hook cannot see the message it is being
asked about" is a publishable finding about hook design, and far cheaper than a
week of uninterpretable rows.

#### 1.4 Option A in detail

**Hook.** Give `stop` its own registration line calling the same `capture.sh`
(the surface argument already selects behaviour). After `cat > "$STAGED"`:

- Slurp the staged file with the `read` **builtin** (no fork). Payloads are
  single-line compact JSON — confirmed against a real spool file.
- Extract `transcript_path` with parameter expansion only, tolerant of a space
  after the colon. **Zero forks.**
- `stat -f "%z %m" "$TP"` — **one fork, both fields**, ~1ms.
- Rename to `stop__<bytes>__<mtime>__$ID.json`.
- Every failure path falls through to `bytes=0`, which the worker quarantines.
  Fail-open preserved: the hook still exits 0 on every path.

**Latency:** ≈ **+1–2ms** on a measured 6.5ms hook, and only on `stop`. Re-time
with `bench_inline.py` at N=200; fail above 10ms.

**Worker.** `drain_once` currently does `name.split("__", 1)[0]`. Split all `__`
fields; for `stop`, inject them into the payload as
`transcript_bytes_at_capture` / `transcript_mtime_at_capture` before `sb.build`.
**Also write both onto the capture row** — the spool file is unlinked after
processing, so if the offset lives only in the filename it is gone forever and
decision #7's per-row auditability does not actually exist.

**Worker guards, each with a named quarantine reason:**

| condition | reason |
|---|---|
| current size < recorded offset | `transcript_rewritten` (compaction, or a new session file) |
| offset present, file missing | `transcript_gone` |
| prefix yields < 2 turns | `prefix_too_short` |
| prefix's last complete line is not an assistant message | `prefix_precedes_final_message` — **the flush-race detector, and its rate is a finding**; count it in attrition rather than skipping |

#### 1.5 State builder

**Must:** the prefix `[0:transcript_bytes_at_capture]` only, `errors="ignore"`,
partial trailing line discarded (already correct).

**Must not:** any read beyond the offset; any glob of `<session>/subagents/`; the
user's *next* message under any circumstance — that is the answer to
`task_complete`.

**Two defects to fix while in there** (both verified):

- **`_flatten_content` keeps `body[:500]` — the HEAD — of each tool result.**
  Test runners and linters print their verdict at the **tail**
  (`5 failed, 12 passed`). `has_unverified_claim` is specifically about whether
  tool output supports a claim, and the builder systematically discards the part
  that would settle it. Use head 250 + tail 250 with an elision marker.
- **`_truncate` front-truncates to keep the end** — right for a transcript, but
  `task_complete` depends on the user's request, which sits at the **front**. Add
  a head-preserving variant for `stop`: first user message verbatim + elided tail.

#### 1.6 Synthetic set: mandatory here

The live base rate is degenerate in the unhelpful direction — the assistant stops
when it thinks it is done. Expect `task_complete` ≈ 90–97% true,
`has_unverified_claim` ≈ 3–10%. PABAK ≈ 0.9, κ ≈ 0.0, neither meaning anything.
**Live `stop` data can measure agreement and latency but not discrimination.**

Build `data/synthetic/stop-v1.jsonl`: ~60 hand-written mini-transcripts, 20 per
stratum, each a small JSONL fixture plus a payload pointing at it with an explicit
byte offset (which also exercises the real code path):

- **complete** — request carried out, tool output present and supporting.
- **incomplete** — a multi-part request with one part silently dropped; a "let me
  know if you also want…" ending; an error in the last tool result followed by a
  confident summary.
- **unverified-claim** — "tests now pass" with no test run; "deployed" with no
  deploy command; "verified the fix" after only an Edit. **The interesting
  stratum, and the one no live week will produce.**

Include 5 adversarial items where the claim is *true and verified* but phrased
identically — separating "detects a claim" from "detects an unsupported claim",
as `destructive` vs `needs_review` did.

#### 1.7 Free labels

The user's **next** message after a Stop is a legitimate outcome label (§0.5): a
correction, a re-ask, or "you didn't…" means the task was not complete. Harvest in
analysis, never in state. Gives `stop` a semi-gold label with no human pass.

---

### 2. `user_prompt` — routing, in shadow only

**Everything in this section is a counterfactual.** Per-turn routing is not a
thing Claude Code can do (§0.1), so these captures can never move a turn to a
different model; they can only estimate what it would have saved if they could.
That is JEV-18's claim, it is weaker than `agent_route`'s, and it must be
labelled as such wherever it appears — a potential-savings estimate against a
mechanism that does not exist. The surface is still worth running: it is the
highest-volume, cheapest question in the study, and §2.4's realised-cost
correlation tests the economics the whole routing story rests on.

#### 2.1 Which question: both, as `v2`, and no model-choice question

1. **Keep `route`** (8-category `choice`). Pre-registered, and the only `choice`
   question in the study — so the only thing exercising option-order sensitivity
   and `categorical_kappa`. Its low-κ outcome is already pre-committed as a
   finding about task ambiguity.
2. **Add `complexity`** as a 5-anchor `score`, in a **new `v2.json`**. Part 5.1
   showed it cleanly monotone; Part 5.3 concluded the score question outperformed
   the choice question.
3. **Do not add a "which model" question.** It is the weaker formulation and it
   bakes a policy into the measurement. A complexity score plus a threshold lets
   you evaluate *every* routing policy offline from one set of rows; a
   model-choice answer lets you evaluate exactly one.

Both questions go in one Jev call — marginal cost near zero against ~278 tokens
of fixed scaffolding.

**Anchors** (low→high): mechanical // single-file localised // multi-file but
specified // requires diagnosis from symptoms // open-ended design, no stated
approach.

**The deployable policy, evaluated offline** (an analysis, not a question):
`route down only if complexity ≤ τ AND confidence ≥ c`. Part 5.3 showed confidence
catches *ambiguity* (0.46, 0.33) but **not** the confident p99 miss — report the
policy's miss rate explicitly rather than implying confidence closes the gap.

#### 2.2 State builder

**Must:** `payload["prompt"]`, `is_continuation`. That is what
`build_user_prompt` does today, and it is correct.

**Must not:** the transcript. This is the canonical leakage case named in
decision #7 — reading it at worker time shows the classifier Claude's answer to
the prompt it is routing.

**But flag the confound this creates.** The Part 5 probe was prompt-only, and the
item it got confidently wrong — *"3× p99 latency after a deploy, only a pool
config changed"* — is hard **because of the codebase**, not the sentence. A
prompt-only router may be failing for want of context rather than capability.
That is an argument for **recording the transcript offset on every surface**
(§6.8): ~1ms, and it lets a future context-aware `v3` builder replay the same
captures without re-collecting a week of data.

#### 2.3 Base rate: not degenerate, and that is the point

`route` will be dominated by `code_edit` and `debug` — modal class ~40–55%,
skewed but nowhere near `pre_bash.destructive`'s 1–5%. `complexity` will be broad.
Print the majority-class baseline beside every agreement number (already
enforced): a 50%-modal router agreeing 55% of the time is doing almost nothing.

#### 2.4 The free label that tests the study's strongest claim

**Realised turn cost is a future-derived label and is permitted** (§0.5). For each
`user_prompt` capture, join the turn that followed: output tokens, tool-call
count, `is_error` count, wall-clock. Correlate Jev's `complexity` against realised
cost.

This is the **strongest test of the economics that needs zero human labels**, and
until `agent_route` is live it is the only one — `agent_route` supersedes it as
evidence, because that surface measures realised cost against a control arm
instead of correlating a score against a turn nobody rerouted. If complexity does not predict realised cost, the $0.0520-per-
downgrade story never materialises regardless of how well Jev agrees with Opus.
Make it the surface's pre-registered secondary metric (Spearman ρ between
`complexity` and realised output tokens, clustered on session).

#### 2.5 Synthetic set: yes, small

Extend the 8-prompt probe to ~60 items, 12 per tier, deliberately including the
class the probe failed on: **symptom-only debugging prompts that are short and
plain-sounding but require deep diagnosis.** That class is the whole risk. If Jev
scores them low, the surface is not deployable at any threshold — and you want to
know that at n=12, not n=1.

#### 2.6 Registration

```json
"UserPromptSubmit": [{ "hooks": [{ "type": "command",
  "command": "\"$CLAUDE_PROJECT_DIR/hooks/capture.sh\" user_prompt", "timeout": 5 }] }]
```

**`UserPromptSubmit` stdout is injected into the session context.** The hook
already guarantees empty stdout and a gate asserts it — re-run that gate
specifically for this surface, because here a stray byte is not a permission
decision, it is **contamination of the prompt being measured**. Highest-stakes
stdout surface in the study.

---

### 3. `post_edit` — a 1–5 risk score on a diff

#### 3.1 Main risk: the builder has never seen a real payload, and one branch is probably dead

- **`isinstance(response, str)` (verified present at `state_builders.py:86`).**
  `tool_response` for Edit/Write is a **dict** (`filePath`, `originalFile`,
  `structuredPatch`…), not a string. If so the tool result is **silently
  dropped** — never raising, never logged. *Unverified against a live payload;
  confirm in `capture_only` before trusting a row.*
- **Matcher mismatch (verified).** `surfaces.json` declares
  `Edit|Write|NotebookEdit`, but the builder raises without
  `old_string`/`new_string`/`content`. NotebookEdit (`new_source`) and MultiEdit
  (`edits[]`) would **quarantine every time**. **Register `Edit|Write` only** and
  fix `surfaces.json`, or add the branches — do not ship the mismatch, it produces
  a quarantine stream that looks like a harness bug.
- **Write + front-truncation.** `_truncate` keeps the end. For a `Write` of a new
  file that discards imports, the docstring and top-level structure — precisely
  what separates anchor 1 from anchor 5. Use head-preserving truncation here.

#### 3.2 What the state must and must not include

**Must:** tool name, file path, old/new strings (or content), and — new — a
**bounded window of `tool_response.originalFile` around the edit** (±40 lines).
`originalFile` is the *pre-edit* file, so it is not future information, and it is
the context a risk score actually needs: the same three-line diff is anchor 2
inside a pure function and anchor 5 inside an auth check. Bound it; never paste
whole files.

**Must not:** the post-edit file as it exists at worker time (it may have been
edited again); any later tool result; any test run that happened after.

#### 3.3 `score` subtleties already paid for

`from_wire` shifts Jev 0→1-indexed and rounds to 2dp — done and regression-tested.
Two things to carry forward:

- `_score_section` already reports Spearman, QWK, MAE **and Bland–Altman mean
  bias**. The mean-bias line is the one that would have caught the off-by-one.
  Do not let it fall out of the report.
- Jev returns an **expected value** (3.37); the Claude arms return an integer.
  These are not the same kind of quantity. QWK needs integers — state **how Jev's
  float is binned** (round-half-even) and report Spearman on the *unbinned* float
  as primary, since binning discards the information the float carries.

#### 3.4 Base rate: degenerate in the boring direction

Live edits here are overwhelmingly markdown and small Python: expect **70%+ of
scores at 1–2**, essentially nothing at 5. Live data will measure agreement and
latency and nothing about discrimination at the top of the scale — where all the
value is.

**A synthetic set is mandatory here, more than anywhere else.** ~100 items, 20 per
anchor, each rendered in two forms (an `Edit` replacement and a `Write`
whole-file) so tool-shape sensitivity is measurable. Include the adversarial pairs
that matter: **a one-character diff flipping a comparison in an auth check**
(anchor 5, looks like anchor 1), and **a 200-line reformatting commit** (anchor 1,
looks like anchor 4). If Jev scores diff *size* rather than diff *consequence*,
those pairs expose it immediately.

#### 3.5 Registration

```json
"PostToolUse": [{ "matcher": "Edit|Write",
  "hooks": [{ "type": "command",
  "command": "\"$CLAUDE_PROJECT_DIR/hooks/capture.sh\" post_edit", "timeout": 5 }] }]
```

Largest states of the payload-only surfaces (whole-file Writes) — watch spool disk
and the 60k char cap.

---

### 4. Incremental cost and latency

Session latency impact is **0ms in shadow mode** for all three — the hook is a
spooler. The only session-visible cost is the hook itself: 6.5ms today, +1–2ms on
`stop`. **`agent_route` is not in this table and does not share its premise**
(§0.2): it blocks each subagent spawn on a Jev call, so its session impact is a
full decision latency, not a spool write, and measuring it is part of the A/B.

| surface | est. rate | arms | worker load | session impact |
|---|---|---|---|---|
| `stop` | 30–60/day | 3 | ~25 min/day | +8ms/turn-end |
| `user_prompt` | 30–60/day | jev + 1-in-3 opus | ~6 min/day | +6.5ms/turn |
| `post_edit` | 30–80/day | jev + 1-in-3 opus | ~8 min/day | +6.5ms/edit |

With per-surface arm lists, all four sit at **60–75 min/day** of worker time in
bursts — drainable, but only just. Without them, ~2.5 hours/day and backpressure
loss during any heavy session.

---

### 5. Definition of done, per surface

1. `capture_only` for one full session; payload keys inspected by hand and
   recorded in `docs/`.
2. State builder run against ≥5 real payloads; every `StateBuildError` or
   silently dropped field fixed.
3. The three existing gates re-run **parameterised on the surface** (they are
   hardcoded to `pre_bash` today); **GATE 4** passes.
4. `bench_inline.py` re-timed; hook p99 < 10ms.
5. Surface section added to `PREREGISTRATION-SURFACES.md` and **committed**.
6. Synthetic set built and replayed; AUC / monotonicity / Spearman reported and
   labelled synthetic.
7. Flip to `shadow`. Watch `spool/ready` count and `spool/dead` reasons for the
   first session.

---

### 6. Defects in the existing design

Verified against source unless marked otherwise.

1. **CONTESTED — `build_stop` reads `last_assistant_message`.** The planning agent
   believed the Stop payload probably lacks it; earlier research in this project
   recorded it as present. Settle by looking (§1.3), build on neither belief.
2. **VERIFIED — `_flatten_content` keeps the head (`body[:500]`) of tool results.**
   Verdicts are at the tail. Directly undermines `has_unverified_claim`.
3. **PLAUSIBLE, unverified — `build_post_edit`'s `isinstance(response, str)`** is
   likely always false, silently dropping the tool result.
4. **VERIFIED — `surfaces.json` matcher `Edit|Write|NotebookEdit` contradicts the
   builder**, which quarantines NotebookEdit and MultiEdit unconditionally.
5. **VERIFIED — front-truncation is right for transcripts and wrong for `Write`
   payloads**, where it discards exactly what determines the risk anchor.
6. **VERIFIED — `tests/gates.sh` never tests the future-leakage guarantee.** 21
   assertions covering isolation, fail-open and the kill switch; zero covering
   decision #7, which is the study's most load-bearing methodological claim.
   Asserted in three documents, verified nowhere. **Applies to the already-live
   `pre_bash` surface and should not wait for `stop`.**
7. **Decision #7 conflates state-leakage with label-derivation.** As written it
   discourages the future-derived labels that are the only free ground truth
   available in Phase 1. Add the STATE/LABEL distinction (§0.5) explicitly.
8. **`transcript_bytes_at_capture` should be recorded on all four surfaces**, not
   just `stop`. ~1ms, and it makes every capture replayable under a future
   context-aware builder instead of requiring a fresh collection window.

---

## Problem Statement

> **Superseded in part by Q1 and Q18.** This section poses the question the study
> *started* with — "is Jev a good classifier?" — and it is left standing because
> the answer turned out to be yes and uninteresting. The question the study now
> answers is in *Status* §1 and §2 above: whether routing makes Claude Code
> cheaper. Read this as background, not as the thesis.

Claude Code makes dozens of consequential decisions per session — whether a Bash command is
dangerous, whether a task is actually finished, which route a prompt should take, how risky an edit
is — and today each one is either a hardcoded regex, a permission prompt aimed at the human, or
nothing at all. The reason is cost and latency: hooks run synchronously on every turn, and no LLM
has been cheap or fast enough to sit there. So the decision layer stays dumb, and the human absorbs
the cost — approving commands that were never risky, or missing the one that was.

Jev changes the economics: $0.042/1M input tokens, output free, a claimed 70–500ms. If it makes
those decisions as well as a frontier model does, an entire class of intelligence becomes affordable
in the hot path. **Nobody has measured whether it does.** The user wants to find out and publish it,
which means the answer has to survive a hostile reader — and most single-author LLM comparisons do
not, because they pool incomparable surfaces, report a mean latency, call agreement "accuracy", and
compute confidence intervals that ignore session clustering.

## Solution

Two experiments, not one. The original spec described only the first.

**A. The shadow-mode measurement harness (built, live).** A harness living
entirely in one folder. Claude Code hooks capture real decision points as they
occur and write them to a spool in under 10ms, never blocking and never changing
session behaviour. An offline worker replays each captured state against **five
arms** — `jev`, `cc_opus5`, `cc_sonnet5`, `cc_haiku45`, `cc_fable51` (Q8; the
original three-arm text is superseded) — interleaved with randomised arm order so
no arm pays a latency cost the others don't. Everything is stored append-only and
content-addressed, so a single human labelling pass in Phase 2 applies to every
question phrasing ever replayed, with zero re-running.

Its output is a set of per-surface tables and figures: latency distributions,
cost per decision, inter-arm agreement with clustered confidence intervals,
sharpness, and robustness sweeps — plus a pre-registration committed before the
first record.

**B. The routing A/B (Q5, Q17 — specified, not yet started).** This one is **not
shadow mode**: it changes session behaviour on purpose. Delegated tasks are
assigned a model tier and actually run on it, and the outcome is net cost
including rework. It is the headline experiment, and it is why *Out of Scope*
below has been amended. It has no pre-registration yet — see
`PREREGISTRATION.md` Amendment 2 (PROPOSED), which must be ratified before its
first task runs.

## User Stories

1. As a researcher, I want captured decision points written to disk without touching session
   behaviour, so that observation doesn't contaminate the thing observed.
2. As a researcher, I want the capture hook to finish in under 10ms, so that adding it costs the
   session nothing I'd notice.
3. As a researcher, I want the hook to fail open on every error path, so that a bad API key or a
   full disk can never wedge my editor.
4. As a researcher, I want a single-file kill switch, so that I can stop the experiment instantly
   without editing config or restarting a session.
5. As a researcher, I want hooks registered only for this folder, so that my other projects and my
   cloud sessions are provably untouched.
6. As a researcher, I want every artifact under one directory, so that deleting the directory
   reverts my machine completely.
7. As a researcher, I want each captured state stored content-addressed, so that identical states
   deduplicate and every run is traceable to exact bytes.
8. As a researcher, I want all arms to receive byte-identical state, so that no difference
   between them can be blamed on input drift. *(Amended by Q8: five arms, not three.)*
9. As a researcher, I want arm order randomised per decision point, so that time-of-day network
   drift doesn't systematically favour one arm.
10. As a researcher, I want per-call timings decomposed into DNS, TCP, TLS and TTFB, so that I can
    tell a slow model from a slow network.
11. As a researcher, I want failed and timed-out calls recorded as rows rather than dropped, so that
    attrition is measurable instead of invisible.
12. As a researcher, I want cost computed with cache multipliers and per exact model string, so that
    the headline cost ratio isn't off by orders of magnitude.
13. As a researcher, I want my cost formula reconciled against Claude Code's own `totalCostUSD`, so
    that I can publish the delta instead of asserting correctness.
14. As a researcher, I want session-level baseline metrics collected from day 0, so that a later
    enforce phase has a genuine "before" to be compared against.
15. As a researcher, I want transcript lines deduplicated by `requestId`, so that a 3.1× duplication
    factor doesn't triple every token count I publish.
16. As a researcher, I want agreement reported separately per surface, so that a 99%-agreement gate
    doesn't launder a 60%-agreement router into a good headline number.
17. As a researcher, I want the majority-class baseline printed beside every agreement number, so
    that a degenerate base rate can't masquerade as skill.
18. As a researcher, I want both Cohen's κ and PABAK, so that skewed base rates are presented
    honestly rather than by whichever statistic flatters the result.
19. As a researcher, I want confidence intervals bootstrapped clustered on `session_id`, so that
    correlated repeats within a session don't produce intervals 5–8× too narrow.
20. As a researcher, I want the word "accuracy" absent from Phase 1 output, so that agreement with
    Opus is never mistaken for truth.
21. As a researcher, I want a pre-registration committed before the first record, so that my
    analysis choices are verifiably not post-hoc.
22. As a researcher, I want a stopping rule fixed in advance, so that I can't stop collecting when
    the numbers happen to look good. *(Amended by A1.2: the rule is now 30 distinct sessions or the
    hard calendar stop at 2026-10-20, whichever comes first. A pure calendar rule was found to
    produce an* undefined *primary metric at the observed session rate.)*
23. As a researcher, I want a daily canary over fixed states, so that a mid-collection vendor model
    change is detected rather than silently averaged in.
24. As a researcher, I want `response_model` recorded on every call, so that model substitution is
    auditable after the fact.
25. As a researcher, I want a stratified synthetic stress set replayed offline, so that the ROC
    curve has resolution my live base rate can never provide.
26. As a researcher, I want synthetic results reported separately and labelled, so that they are
    never pooled with live data.
27. As a researcher, I want determinism measured by repeating identical calls, so that I know how
    much **both** arms wobble. *(The original story assumed the finding — "Jev is deterministic and
    the LLMs aren't". The day-0 spike* falsified *that: Jev is not bit-deterministic. See
    `PREREGISTRATION.md` §7. The measurement stands; the expected answer does not, and the sweep
    (JEV-16) is still the blocker on enforcement.)*
28. As a researcher, I want each question asked in 2–3 independent phrasings, so that a lazily
    written baseline prompt can't manufacture my result.
29. As a researcher, I want option order shuffled for `choice` questions, so that known LLM position
    bias is measured instead of inherited.
30. As a researcher, I want state truncation swept at 50/75/100%, so that I know how much context
    each arm actually needs.
31. As a researcher, I want one surface additionally running true inline shadow, so that the script
    I would actually deploy is exercised under live conditions.
32. As a researcher, I want a separate enforce-overhead microbenchmark, so that projected deployment
    cost is measured including process spawn rather than inferred from API latency.
33. As a researcher, I want enforce mode to require editing a different registered script, so that
    a passive observer can never become a blocker by way of a typo.
34. As a researcher, I want each surface switchable independently, so that I can run one without
    committing to four.
35. As a researcher, I want state built only from what existed at capture time, so that no arm can
    see the future it is supposed to predict.
36. As a researcher, I want each capture to record its `state_source`, so that the leakage argument
    is auditable per row rather than asserted once.
37. As a researcher, I want gold labels joined on `(decision_id, question_name)`, so that one
    labelling pass applies to every phrasing variant forever.
38. As a labeller, I want a blind labelling UI showing state only, so that I can't unconsciously
    ratify whichever arm I'm rooting for.
39. As a labeller, I want 15% of items double-labelled, so that my own consistency is measurable.
40. As a reader of the paper, I want the data path to third-party APIs disclosed, so that I can
    judge the privacy tradeoff myself.
41. As a reader of the paper, I want the n=1 scope stated in the abstract, so that I'm not misled
    into reading a benchmark.
42. As a reader of the paper, I want base rates printed with every agreement statistic, so that I
    can recompute the claim myself.
43. As the folder's owner, I want `.env` gitignored and checked before commit, so that publishing
    the repo can't leak an API key.

## Implementation Decisions

Architecture, arms, storage, metrics, switches, and the nine design-review decisions are specified
in full above and are not restated here. The additions this spec makes:

- **Issue tracker is `ISSUES.md`** in the folder. Flat markdown, `##` per issue, `JEV-nn` ids,
  `Status:` and `Labels:` lines, never renumbered. No external tracker; git history is issue history.
- **`data/` has five streams and one deliberate boundary violation.** `store.py`
  writes `captures/`, `states/`, `runs/` and `labels/`. `data/inline/` is written
  **directly by `hooks/inline_shadow_bash.sh`**, bypassing Python entirely — and
  the bypass is the measurement, not a violation: that hook exists to exercise
  the script you would actually deploy, so adding a ~30–60ms interpreter start to
  every row would destroy the number it is there to produce. It carries its own
  schema and is analysed separately, never pooled. Separately, `captures/` rows
  come in **two shapes** — live rows carry five payload-derived context keys
  (`prompt_id`, `tool_use_id`, `agent_type`, `permission_mode`, `cwd`) that
  synthetic rows cannot have, because a synthetic item never passed through a
  hook. Absent, not null; readers must treat them as optional and must not read
  an absent key as an absent fact.
- **Module boundaries.** `hooks/` is bash and owns only spooling. `src/arms/` owns all **outbound
  calls to a model** and is the only place either an HTTP client or a `claude -p` subprocess spawn
  appears. (The original wording said "the only place an HTTP client appears", which stopped being
  accurate when the baseline moved to the subscription: the `cc_*` arms reach their model by
  spawning a process, not by opening a socket. The boundary is the same; its description was
  wrong.) `src/worker.py` owns orchestration and is the sole
  writer of `data/runs/`. `src/analyze.py` and `src/figures.py` are pure functions over jsonl and
  perform no I/O beyond reading inputs and writing `reports/`.
- **The arm interface is one function**: `evaluate(state: str, questions: dict, config: ArmConfig)
  -> Run`. Every arm implements it; adding an arm means adding one file — which is how the study
  went from three arms to five (Q8) without touching the worker.
- **Versioning is explicit everywhere**: `question_set_id`, `state_builder_version`,
  `pricing_version`, `arm_config_id`, `redaction_version` on the rows they apply to. Nothing is
  "current"; everything is pinned.
- **Config is data, not code**: `config/surfaces.json`, `config/arms.json`, `config/pricing.json`.
  Changing an arm's model or effort is a config edit, not a code edit — except `enforce`, which is
  deliberately not reachable from config at all.

## Testing Decisions

A good test here asserts **external behaviour at a process or module boundary** and never reaches
into internals. Two seams plus pure functions — ratified with you:

1. **The hook's process boundary** (highest, and unavoidable since the hook is bash): feed a
   recorded JSON payload on stdin, assert on exit code, stdout, and the files that appear in
   `spool/`. This covers the kill switch, the cwd guard, fail-open on unwritable spool, backpressure,
   and atomic rename — all without a network or a running Claude Code.
2. **The arm interface** `evaluate(state, questions, config) -> Run`: a fake arm returning canned
   responses lets the worker's orchestration, interleaving, randomisation, retry and row-writing be
   tested with zero API spend and zero flakiness. This is the single seam that most of the suite
   should sit behind.
3. **Analysis is pure functions over fixtures** — no seam needed. `session_metrics.py` runs against a
   frozen completed transcript in `data/fixtures/` with expected counts recorded beside it; the
   statistics run against small hand-built jsonl where κ, PABAK and the clustered bootstrap have
   known answers.

4. **The future-leakage gate (GATE 4)** is a testing decision, not merely a ticket. Decision #7 —
   state is built only from what existed at capture time — is the study's most load-bearing
   methodological claim, and leakage would help *both* arms equally, so **no agreement metric can
   ever reveal it**. It must be asserted directly, at the hook/worker boundary: append lines to a
   fixture transcript after capture, drain, and assert `state_sha256` is unchanged; plus a negative
   control asserting that a capture with a stripped byte offset is quarantined rather than
   processed. Offline, `FakeArm`, no spend. Tracked as JEV-15.

5. **The routing A/B needs one assertion, and it is a verification of the experiment itself:**
   for every delegated task, the model recorded in the subagent's own transcript matches the tier
   the randomiser assigned. Without it, a silently ignored `model` argument would be indistinguishable
   from a treatment that simply doesn't help — the treatment arm would quietly *be* the control arm,
   and the study would publish a null result caused by a bug. Asserted per task, from the transcript,
   not from the request.

Live API calls appear in exactly one place: the day-0 `--selftest` spike, run deliberately and never
in the automated suite.

## Tickets

**`ISSUES.md` is authoritative.** The thirteen-row table that used to sit here was
written before collection started; it has been removed rather than maintained in
parallel, because two copies of a ticket list diverge and the copy in the spec is
the one nobody updates. It had already drifted in three ways worth recording: it
named three arms (Q8 makes five), it carried a single "remaining three surfaces"
row (now JEV-18/19/20, with the priority order reversed), and it predated
JEV-14 through JEV-25 entirely.

Tickets are vertical slices, `JEV-nn`, never renumbered. Current shape of the
board — counts, not a second list:

| state | tickets |
|---|---|
| done | JEV-01…08, 14, 21 |
| in-progress | JEV-09, 10, 11 |
| **ready now** (no unmet blockers) | **JEV-15, 16, 17, 22, 24a, 26, 27** |
| blocked | JEV-12, 13, 18, 19, 20, 23, 24b, 25 |

Two of the four ready tickets gate almost everything else:

- **JEV-16 (determinism sweep)** is the enforcement blocker. Until the flip rate
  is known, no surface can move from shadow to enforce, and JEV-17's dead-zone
  rule has nothing to be derived from.
- **JEV-24a (pre-rule delegation baseline)** is urgent for a different reason: it
  measures something that ceases to exist the moment the delegation rule or the
  A/B starts. It was previously a checkbox inside JEV-24, which was blocked by
  JEV-23 — an ordering inversion that would have destroyed the measurement.
- **JEV-15 (GATE 4, future-leakage)** verifies the study's most load-bearing
  methodological claim, which is currently asserted in three documents and tested
  in none. It applies to the *already-live* surface, so it is overdue rather than
  upcoming.

**JEV-23 (the routing A/B) is now design-complete** — all five open questions
were answered on 2026-09-20 — and blocked on exactly two things: **JEV-24a**
(the pre-rule baseline, which the A/B destroys) and **JEV-27** (the
power-derived stopping rule, the last unratified clause of Amendment 2).

## Out of Scope

**Amended by Q5.** The original exclusions listed below were written for a
shadow-mode-only study. Two of them no longer hold:

- **"Enforce mode"** — the routing A/B *is* an intervention that changes session
  behaviour. It does not block a tool call (no `enforce_*.sh` hook is written, and
  the rule that enforcement requires a deliberately different registered script
  stands), but calling it out-of-scope would be false. What remains out of scope
  is **enforcement on `pre_bash`**, which JEV-16 blocks.
- **"Any claim about productivity improvement"** — superseded. Net cost including
  rework *is* a productivity claim, and it is now the headline. The discipline
  that replaces the blanket ban: the claim is pre-registered before the first
  routed task (Amendment 2), the outcome is net-of-rework so the treatment pays
  for its own mistakes, and quality is measured by friction proxies rather than
  self-rating.

Still out of scope, unchanged: Phase 2 in its entirety — the labelling UI, gold
labels, Brier/ECE/RPS, decision-curve analysis and the writeup. Multi-repo
collection, ruled out by the isolation requirement. Any launchd or auto-start
mechanism. Any claim about **accuracy or calibration**, which need gold labels
this study does not have.

## Further Notes

Three things still need ratification and are flagged as deviations or recommendations rather than
settled: **Haiku 4.5** as a third arm was declined and added back anyway, because Opus-as-hook-gate
is a strawman — it is droppable at a word. **Three of four surfaces are deferred**, which is
sequencing rather than scope reduction, and is a recommendation to accept or override. And the
**synthetic stress set carries the statistical load** as a direct consequence of the isolation
requirement — a narrower claim than a multi-repo study, stated as such in the writeup.
