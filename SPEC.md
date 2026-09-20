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

### Open — must be answered before the routing A/B starts

| # | question | status |
|---|---|---|
| **Q9** | **What is the unit of randomisation, and how is it kept unconfounded?** Offered: (a) per session, coin flip at session start; (b) per turn, within session; (c) per session blocked by task type. The recommendation was **(b) per turn**, because within a session both arms see the same task mix, repository and hour, which is the one place n=1 helps. | **OPEN — and the recommendation is now void.** Q17 established that a turn is not a routable unit; the only routable unit is the delegated task. Q9 must be re-asked as **per-delegation randomisation**, and (b)'s pairing argument has to be re-earned: two delegated tasks in one session are *not* the same task, so the paired-comparison logic that justified (b) does not carry over unchanged. |
| **Q10** | Quality measured by friction proxies + escalation rate, as a pre-registered composite; explicitly not self-rating. | **UNRATIFIED** (recommendation only) |
| **Q11** | Primary outcome: net cost including rework. | **UNRATIFIED** (recommendation only) |
| **Q12** | Routing A/B runs concurrently with the `pre_bash` window; arm recorded on every capture. | **UNRATIFIED** (recommendation only) |

### Framing

| # | decision |
|---|---|
| Q1 | **Thesis: "routing is where harness savings live."** Not "is Jev a good classifier" — that question is answered (it is) and it turned out not to be the interesting one. |
| Q2 | **Audience: rigorous single-author case study / preprint.** Pre-registration hash cited, every CI clustered, falsification conditions explicit. Not a benchmark — not honestly reachable at n=1. |
| Q3 | **Budget: ~1 week.** Land routing properly; do not attempt Phase 2 gold labels. |
| Q6 | **Let the pre-registered `pre_bash` week run to completion** rather than shortening or dropping it when the thesis moved to routing. Breaking one's own pre-registration is the first thing a reviewer looks for; an "inconclusive" pre-registered result strengthens the methodology section rather than weakening it. *Partly superseded by Q14, which replaced the seven-day rule with a cluster-count rule — the commitment not to abandon the gating experiment stands.* |
| Q18 | **Thesis narrowed, not pivoted:** "routing *delegated tasks* is where the savings live." The mechanism constraint (below) bounds it. |

### The routing experiment

| # | decision |
|---|---|
| Q5 | **A/B with actual routing**, not shadow-mode inference. |
| **Q9** | **unit of randomisation — OPEN, see above.** Nothing else in this table is safe to build on until it is settled. |
| Q17 | **Unit of routing is the delegated task, not the turn** — forced by the mechanism constraint, which still holds for turns. The *selection* mechanism is amended: the three listed here (`CLAUDE_CODE_SUBAGENT_MODEL`, `--agents`, frontmatter) are all static per-session or per-agent-type, so none of them lets Jev decide anything per task. The mechanism that does is a **`PreToolUse` hook on the `Agent` tool rewriting `tool_input.model` via `updatedInput`** — see *Four things a reader should be told plainly* §1. |
| Q17b | **Adopt a global "delegate to a subagent where possible" working rule**, to increase the share of spend that is routable. *See the confound note below.* |
| Q10 *(UNRATIFIED)* | **Quality measured by friction proxies + escalation rate**, pre-registered as a composite. Explicitly NOT self-rating: unblinded self-assessment at n=1 on one's own experiment is the weakest available evidence. |
| Q11 *(UNRATIFIED)* | **Primary outcome: net cost including rework** — an escalated turn is charged at its full cost plus the wasted one, so the treatment arm pays for its own mistakes and cannot win by being recklessly cheap. |
| Q12 *(UNRATIFIED)* | **Runs concurrently with the `pre_bash` window.** Arm assignment must be recorded on every `pre_bash` capture so the analysis can condition on it — routing changes which model generates the commands, so the capture stream is no longer stationary. |
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
| Q19 | **Fable stays, and `v2` gains a `verbosity` question.** Fable is *not* a cheap tier — at $10/$50 it is twice Opus — but its cache reads are half Opus's in absolute terms, so it wins only on cache-heavy *terse* turns. A one-dimensional complexity score cannot express that; routing to Fable needs a prediction of the turn's **shape**. |

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
the superseded version and must be corrected before publication.

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
**`Agent` tool's `prompt`**, not the user's prompt. That was never written down,
and the only question set that exists is `questions/user_prompt/v2.json`, where
the `verbosity` question (Q19) also landed. Two surfaces were quietly sharing one
specification.

**`agent_route` — a new surface.**

| | |
|---|---|
| hook | `PreToolUse` matched on `Agent` |
| state | `tool_input.prompt` + `tool_input.subagent_type`, and nothing else |
| questions | `questions/agent_route/v1.json` — `complexity` (choice, tier) and `verbosity` (score) |
| output | `updatedInput` with `model` rewritten, everything else echoed unchanged |
| outcome | `PostToolUse` on `Agent`: `resolvedModel`, `usage`, `totalDurationMs` |

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

**2. Surface priority is reversed.** `pre_bash` was staged first because it was
simplest to measure. **`user_prompt` / routing should have been first**: one turn
moved Opus→Haiku saves 3,674× the cost of the Jev call that decided it, and it is
the only mechanism in the study that could make Claude Code genuinely faster.
See `docs/PLAN-SURFACES.md`.

**3. The baseline is a harness, not a model.** The study runs entirely on a
Claude subscription via `claude -p`, with no `ANTHROPIC_API_KEY`. The `cc_*` arms
bundle the model with ~10K tokens of preamble and a process spawn, so every claim
is about **Claude Code as deployed**, not about Opus as a classifier. Every
surface section prints an attribution table decomposing harness from model. See
`docs/SUBSCRIPTION-ARM.md`.

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
| **ready now** (no unmet blockers) | **JEV-15, 16, 17, 22, 24a, 26** |
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

**JEV-23 (the routing A/B) carries a prerequisite that is not a ticket:** Q9 must
be answered and Amendment 2 ratified. A blocker that lives outside the board is
the kind that gets missed, so it is named here as well.

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
