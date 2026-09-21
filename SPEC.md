# SPEC (reworked 2026-09-21) — `jev`: a per-project Claude Code accelerator

> **Status: ADOPTED 2026-09-21.** Replaces the measurement-harness SPEC, which
> is preserved verbatim at `docs/SPEC-measurement-harness-ARCHIVED.md` — it is
> the record of a question that was answered, not a document that was wrong.
>
> Built from four parallel harvest passes (context reduction, provider +
> routing, quality guard, repo audit) and four operator decisions recorded in
> §9. Every repo named here was verified to exist and its licence read; two
> licence hazards and one disproven mechanism are recorded in §7.

---

## 1. What changed, and why this document exists

The old SPEC described a **scientific instrument**: a shadow-mode harness that
compared Jev against Claude Code's decision layer, with a pre-registration,
frozen analysis code, and a publishable agreement statistic as the deliverable.

The operator retired that goal on 2026-09-21 — *"we have missed the trend"*.
The new goal is a **tool**:

> **Reduce token usage and wall-clock time in day-to-day coding work, without
> degrading output quality — assembled from existing open-source code rather
> than written from scratch.**

### ⚠️ That statement was mis-specified in two places — corrected and ACCEPTED

`FINDINGS.md` had already answered part of the new question, and the answer was
uncomfortable. The corrected statement below was **put to the operator and
accepted on 2026-09-21**; it is the target this SPEC is built on. The original
wording is preserved above so the change is visible rather than silent.

**(a) "Reduces token usage" is wrong for routing — it reduces *cost*.** Routing
a delegated task Opus→Haiku consumes roughly the same token count at a lower
price. Worse, `JEV-47` records AqueGen's 7-day telemetry: **`$1.36` inline <
`$1.68` delegated-and-routed < `$2.01` delegated at session tier.** Delegating
and routing came out **~24% more expensive than not delegating at all**, because
a subagent starts with empty context and trades cheap cache-*reads* for
expensive cache-*writes*. Token count may go **up**.

**(b) "Reduces execution time" is unproven and partly contradicted.** `JEV-41`
measured `cc_haiku45` as the **slowest** arm. The latency case for routing is
arithmetic ("removes a frontier turn from the critical path") and has never been
measured. `JEV-34`'s spawn-latency box is explicitly deferred and unmeasured —
and it is the one place in the design where a Jev call is *not* free.

**(c) A synchronous Jev call in a hook is not free, and we measured it.**
`FINDINGS.md:563`: *"gating cannot make Claude Code faster or more
token-efficient, by construction."* A `pre_bash` gate adds **+337 tokens and
+557ms p50 / +2,681ms p99 per call**, and removes nothing. Across one real
session (179 Bash calls) that is **+60,323 tokens and ~100s the user waits
through.** Any per-tool-call Jev hook must therefore *remove far more than it
adds*, which means it may only fire on large payloads, never by default.

**(d) The addressable surface is ~a third of the bill.**
delegated work is **~24%** of spend by the rule-corrected figure
(`delegation_rate_by_spend` 0.238, up from the frozen record's 0.162 — see §11).
The frozen manifest's 34% was computed under a defective costing rule.
`agent_route` fires only on `Agent` calls; everything the main session does
itself is out of reach, and per-turn routing is impossible.

**The honest restatement, which this SPEC adopts:**

> **Lower realised cost per delegated task, at equal task success, with no added
> felt latency** — plus context reduction where it removes more than it costs.

**And the asymmetry that makes the project worth doing anyway** — stated with
the unit it was actually measured in, after an audit found it quoted wrongly in
three files:

`FINDINGS.md:546` measures **$0.0520 saved per TURN correctly downgraded** (a
representative turn: 30K cache read, 2K write, 1.5K out — $0.0650 on Opus,
$0.0130 on Haiku), against a **$0.000014** Jev call: **3,674× leverage on one
decision.**

The routing decision is taken **once per delegated task**, and a delegated task
is a median **38 requests** (§10). So the leverage on a *delegation* is larger
than 3,674× — but **how much larger is unmeasured**, because it depends on how
many of those 38 turns would actually have been downgraded, which nothing has
counted. **Do not multiply these numbers together and publish the result.**
Routing remains the only mechanism in the repo with this sign.

The difference is not cosmetic. The old deliverable was *a number about Jev*.
The new deliverable is *a faster, cheaper session that is no worse*. Almost all
the engineering survives; almost all the framing dies.

**The one clause that keeps the old work alive:** "without degrading quality" is
a measurement requirement. It is now a **gate on shipping an optimization**, not
a result to publish. The harness stops being the product and becomes the brake.

---

## 2. Success criteria

**REORDERED 2026-09-21 on the operator's correction: the goal is SPEED and
AVOIDING REWORK. Cost is a consequence, not the target.** The previous ordering
led with token and cost reduction, which measured the wrong thing well.

| # | Criterion | Measured how | Ships if |
|---|---|---|---|
| **R1** | **Rework rate** — how often a task has to be redone | escalations, retries, and task-level failures per delegated task, baseline vs treatment | **no increase.** This is the primary criterion |
| **R2** | **Felt latency** — time the human actually waits | **blocking** duration p50/p95, measured separately from task duration | no regression; reduction where claimed |
| **R3** | **Quality non-regression** | the two-class guard in §6, per-task pass/fail | Class 1 and Class 2 both pass |
| **R4** | **Net win after the layer's own cost** | the layer's added latency and spend, subtracted from R1/R2 | net positive |
| **R5** | **Realised cost per delegated task** | against the corrected $2.88 anchor (§11) | reported, **not** a gate |

### Why rework is the primary criterion, and why it is expensive

Operator decision 3 is **RESTART on escalation**: a task sent to a higher tier
starts from the original task, not from the first attempt's reasoning. So **an
escalation pays for the work twice — and makes the human wait twice.** One wrong
downgrade therefore wipes out the saving from many correct ones, and it wipes
out the *time* saving completely, because the second attempt is serial with the
first.

That inverts the usual routing intuition: **down-routing is the risky direction
and must be gated harder than up-routing.** The asymmetric down-route guard
harvested from `tzachbon/claude-model-router-hook` (§7) is not a refinement, it
is the core of the policy.

### ⚠️ Routing delegated tasks CANNOT improve felt latency

Measured, W3: median task duration **794.6 s** against median **blocking**
duration **1.5 s** — a **530×** gap, because every observed delegation is
`requestShape: background`. **A background subagent could be made twice as fast
and the human's wait would not move.**

So routing is a **cost** lever and a **rework** lever. It is not a speed lever,
and no claim that it is one may be made. The speed levers are:

1. **Not doing the work twice** (R1) — a redo costs the whole task again.
2. **Context reduction on the MAIN thread**, where the human is actually
   blocked. Fewer input tokens means faster time-to-first-token on the turns
   that are synchronous with the user. This is why W6 exists and why it is no
   longer bottom of the list.
3. **Compaction that does not lose file paths and errors** — when it does, the
   agent re-reads and re-derives, which *is* rework. It is the exact failure
   `fast-jev-compaction` demonstrated by fabricating nine turns of completed
   work (§5).

### R4 is not optional and is the criterion most likely to be quietly skipped

The old README learned this the hard way and published an attribution table for
it: a layer that saves 5,000 tokens but adds 250 ms to every tool call has not
obviously helped. `FINDINGS.md:563` is the measured version — a synchronous gate
adds **+337 tokens and +557 ms per call and removes nothing**. Every
optimization reports its own overhead in the same units as its win.

### What we explicitly do not claim

- Not "Jev is accurate." We never establish ground truth for Jev's judgments.
- Not "quality is preserved." The guard **fails to detect** a regression at a
  stated power. Green means "no large regression found". §6 puts that sentence
  in the gate's own output so nobody has to remember it.
- Not a benchmark, not a paper, not a model comparison.

---

## 3. Non-negotiables

These are hard constraints. A design that violates one is wrong, not a tradeoff.

1. **Fail safe, then fail to frontier.** Two separate properties; conflating
   them is how this repo previously shipped a kill switch that stopped one
   writer and not the other.

   **(a) Fail safe — absolute.** Every hook exits 0 and never breaks or blocks a
   session, whatever happens. `trap 'exit 0' EXIT` before anything that can
   fail. We reject the fail-**closed** pattern seen in prior art: defensible for
   a deliberate dispatch tool, indefensible in the path of daily work.

   **(b) Fail to frontier — the routing decision.** *Operator decision,
   2026-09-21, overriding the default recommendation.* When the router cannot
   decide — provider down, malformed answer, missing config, timeout — the task
   goes to the **frontier tier**, never to a cheap one. Quality is protected on
   the error path; cost is not.

   **The risk this accepts, stated plainly:** a sustained provider outage
   silently bills frontier rates for as long as it lasts. **Therefore a circuit
   breaker is mandatory, not optional**: after N consecutive failures the router
   stops rewriting entirely, leaves the input untouched, and makes the condition
   loudly visible. Breaker state persists to disk, because every hook invocation
   is a fresh process and an in-memory counter would reset every time.
2. **Never rewrite content.** Compaction **deletes whole stale items**; it never
   paraphrases, summarises or regenerates. Surviving bytes are identical to the
   originals. File paths, error strings, diffs and stack traces are preserved
   exactly. This single property is what makes compaction the low-risk win.
3. **Opt-in, per project, reversible in one command.** `jev install` **merges
   into** `./.claude/settings.local.json` in a repo you choose — it does not
   write the file, and that distinction is load-bearing: the file holds the
   user's other settings, so removal is a surgical edit rather than a move.
   `jev uninstall` takes it out. **Nothing is ever written to
   `~/.claude/settings.json`**, and a test asserts no write verb in the
   installer is even *aimed* at `$HOME`.

   **Teardown is therefore tiered and names its tier**: *Tier A,
   byte-reversible* when the file is untouched since install (the bytes are
   restored and the sha256 verified); *Tier B, structurally verified and
   explicitly weaker* when the user has edited it since — we edit, then verify
   three ways against the file re-read from disk, and Tier B never claims
   byte-reversibility.
4. **One kill switch, honoured on line one** of every hook, tested not assumed.
5. **Hard latency budget on the synchronous path.** Anything that blocks a tool
   call has a timeout and a fail-open default. Budget is stated per surface and
   enforced by a test, not by intention.
6. **No optimization is enabled by default until its gate passes.** Build behind
   a flag, measure, then flip.
7. **Every mechanism must beat a trivial constant control, or it is not a
   mechanism.** This is the most expensive lesson available to us and it was
   bought with someone else's 5,405 stars. `fast-jev-compaction` asks Jev two
   questions per tool call and achieves **87.7%** reduction; a fake asker
   answering **0 to every question** achieves **88.5%** on the same 256 calls,
   with the same 6.7% of dropped results needed again later. The model was
   contributing nothing, and nobody noticed for a month because the output
   *looked* like judgement. **Every optimization ships with its constant control
   measured alongside it, in the same table.**
8. **Never act on an unvalidated model answer.** Probabilities must be checked —
   finite, in range, summing to 1, argmax consistent with the returned choice —
   and a malformed response must raise, never proceed. `fast-jev-compaction`
   checks only that a number is finite, which means a malformed response can
   delete transcript history.
9. **Compressed output must carry its own completeness signal.** Any layer that
   shows the model less than it would have seen must make truncation
   distinguishable from absence, and must leave a handle to retrieve the full
   original. A model that mistakes "I was shown 40 of 400 matches" for "there
   are 40 matches" will confidently conclude something false.

### Note on prior art and constraint 3

`coldteadotai/abide` — from which we harvest substantially — **installs itself
into `~/.claude/settings.json`** (`hosts.ts`, `settings.ts`). That is the global
model the operator rejected. **We take its code, not its installer.**

---

## 4. Architecture

```
jev  (CLI, the only user-facing surface)
 │
 ├─ install / uninstall      per-project hook registration; never global   [W2, done]
 ├─ provider/                Jev client: gateway | local backend           [W4, not started]
 ├─ optimizations/
 │   ├─ compact/             PreCompact: score and DROP stale tool results [W6, not started]
 │   ├─ route/               pre-dispatch (model, effort) selection        [W1 built, NOT ARMED;
 │   │                                                                     Jev half is W4]
 │   └─ trim/                tool-output reduction before it hits context  [W6, not started]
 ├─ guard/                   the two-class regression gate  (§6)           [W3 built; exits 1
 │                                                                         until W5 lands labels]
 └─ report/                  before/after tokens, latency, and S4 overhead [W5, has never existed]
```

*(The three `⏳` markers that used to sit in this tree were removed on
2026-09-21. They meant "unresolved" in a document that had since resolved two of
the three, and a placeholder nobody can date is worse than a stated state.)*

### The provider layer — resolved 2026-09-21

**The wire format is public and stable, and that is our insulation.**
`https://docs.typesafe.ai/api` fetches **without a waitlist** — the API is gated,
the spec is not. So we code against a documented contract, not against mutual
agreement between clones.

**Five independent servers agree**: `POST /v1/systemone`,
`{state, model, questions}` → `{model, answers, usage}`, three question types
(`noul` / `choice` / `score`), identical answer shapes. One client talks to all
of them.

**Three portability hazards, and they are the whole reason for the abstraction:**

1. **`model` is not portable.** `jev-latest` works on most, but one requires the
   exact HF model id it was launched with. Per-endpoint config value; never
   hardcode.
2. **`confidence` is not portable — do not threshold on it.** Three mutually
   incompatible formulas are in the wild: normalized entropy, margin-from-
   uniform, and bare max-probability. **Policy thresholds go on
   `probabilities` / `noul`, with our own statistic computed client-side.** A
   routing rule tuned against one backend's `confidence` would silently mean
   something different on another.
3. **Bounds differ.** Portable intersection: **choice 2–50 options, score 2–10
   levels, ≤64 questions per request.** Stay inside it and every implementation
   accepts the request.

**Chosen stack:**

| role | choice | why |
|---|---|---|
| local runtime | **`razorback16/openjev`**, `OPENJEV_BACKEND=mlx` | Apache-2.0. Reads probabilities off logits, no generation. Bug-for-bug checked against the live API **with the five known differences published**. Native MLX on Apple silicon: ~0.2–0.4 s for a 3-question request. Needs ~16 GB free RAM |
| free hosted | `api.codiv.ai` (100M input tokens, no card) | CI, and machines without 16 GB to spare |
| zero-auth | Featherless demo endpoint (no key at all) | write and test the client before committing to a runtime |
| low-RAM fallback | `jaredpalmer/kev` | Apache-2.0, far smaller models, first-class MPS support |

**Two zero-cost escape hatches from the waitlist exist today**, which retires the
old "blocked on access" position entirely.

**Maturity risk, stated plainly:** every server in this set was created between
2026-09-16 and 2026-09-18 — **three to five days old.** High star counts are
novelty, not battle-testing. Expect breaking changes; our defence is that the
*contract* is TypeSafe's and is documented, so each server stays swappable. We
write one contract test suite and run it against all four.

---

## 5. The waves

> **⚠️ Scheme correction, 2026-09-21 (W5 doc sweep).** This section used to be
> called "the four phases" and was written in a **P0–P4** scheme. That scheme is
> **dead**: this project has **W-waves, W0–W7, and nothing else.** The section
> was left half-converted by the pivot — a W-table, then three orphaned `P2`/
> `P3`/`P4` table rows from the deleted phase table, then prose arguing about
> "P1/P2 ordering". A reader could not tell which scheme was live. Everything
> below is now on the W-scheme. **The reasoning is unchanged and was worth
> keeping** — the argument for demoting compaction and for choosing
> ingestion-time trim is the substance of this section; only the labels moved.
> The mapping used, recorded so the older commits still read:
>
> | dead label | what it was | where it went |
> |---|---|---|
> | **P0** | replay harness + constant control | **cross-cutting**, every wave (below the table) |
> | **P1** | context reduction / compaction | **W6** |
> | **P1b** | compaction plumbing | **W6** |
> | **P2** | the guard | **W3** (the accuracy gate) |
> | **P3** | routing | **W1** (static floor) then **W4** (Jev) |
> | **P4** | tool-output trim | **W6** — P1 and P4 converged on one mechanism |
>
> The wave list itself also drifted: this table stopped at W6 while `ISSUES.md`
> had already inserted **W5 "unstick the gate"** and pushed context reduction to
> **W6** and operate to **W7**. `ISSUES.md`'s numbering is the live one and is
> what is reproduced here.

Operator's sequencing decision, 2026-09-21: compaction first, guard second,
routing third, trim fourth — each gated on the one before.

**Revised again after the repo audit.** The operator's chosen order was
compaction → guard → routing → trim. Two findings move routing to the front and
insert a Jev-free wave before everything:

- Routing has **3,674× leverage**; a per-tool-call Jev hook has *negative*
  leverage by our own measurement (§2c).
- **Five independent sources say classifier routers frequently fail to beat a
  trivial static rule** (LLMRouterBench over 400K instances across 21 datasets:
  *"several recent approaches, including commercial routers, fail to reliably
  outperform a simple baseline"*; RouterArena's "routing plateau"; kNN beating
  MLP and GNN routers; RouteLLM near-random on MMLU). Meanwhile published static
  heuristics already deliver **46%** (9/9 SWE-bench tasks resolved in both arms,
  $2.82→$1.51) and **28%** savings. **So we ship the rule first and make Jev
  earn its place against it.**

| wave | what | why this order | risk |
|---|---|---|---|
| **W0** | **Measure inline vs delegated on our own corpus** | Operator decision 4. **Blocks W4.** Read-only over the existing baseline; costs nothing | none |
| **W1** | **The static floor — no Jev call at all.** A `PreToolUse` hook on `Agent` applying a `subagent_type → tier` map, rewriting `tool_input.model` | **The first shippable thing.** Zero classifier calls, **zero added latency**, and the prior art says it captures most of the available saving. It also builds every piece of scaffolding W4 needs and produces the "after" corpus that nothing in this repo has ever produced | low |
| **W2** | **Safe install + teardown**, opt-in per project | Must work *before* the router is armed, not after | — |
| **W3** | **The accuracy gate** — per-task pass/fail, blinded | Nothing in this repo has ever measured whether a routed subagent did the work correctly | — |
| **W4** | **Jev enters, as increment two** — targeted at the **`general-purpose` residue (65–79%, see §10)** where the static rule has no signal | **Ship gate: Jev must beat the two-line rule on realised cost at equal task success.** If it cannot, we keep the rule and stop | high |
| **W5** | **Unstick the gate and produce the first "after"** — the before/after reporter, the ledger's `project` field, the labels the accuracy gate needs, the re-snapshot under the corrected rule, then arm it | **THE CRITICAL PATH.** W1's actuator exists and has never fired, so nothing this SPEC claims has ever been measured | — |
| **W6** | **Context reduction** — ingestion-time trim of oversized tool results, and/or rebuilt compaction | Demoted from first place (it was P1) to here. Must clear §2c's bar: remove far more than the +337 tokens / +557ms it costs, so it fires only on large payloads. **This is the SPEED lever** — the main thread is where the human actually waits | medium |
| **W7** | **Operate** — canary on a schedule, latency SLO, weekly report on rework rate and felt latency, against the frozen baseline | — | — |

**The replay harness applies to every wave, not to one of them:** the harness and
its **constant control** (non-negotiable 7). Offline, no key required. It was
labelled "P0" when it was thought of as a phase; it is not a phase, it is the
instrument every wave is measured on.

**The optimization/guard ordering is deliberate and slightly counter-intuitive,
and it survives the relabelling.** An optimization wave (W1's static floor, W6's
trim) builds the mechanism and measures the win **behind a flag, off by
default**. W3 builds the guard. The optimization is only *enabled* once the
guard passes against it — which is exactly why W1 shipped **built, not armed**
(`bcd982f`) and why W5 exists at all: W3's gate currently exits 1 ("could not
run") for want of labels, so nothing may be armed yet. Shipping an optimization
before its brake exists is the exact failure this sequencing prevents.

**The guard's own bar, carried over from the deleted P2 row:** the gate **must
be shown to catch a deliberately injected regression before it is trusted.** A
verifier that has never been seen catching anything is not evidence.

### Context reduction was rewritten on evidence, 2026-09-21

*(This subsection was headed "P1 was rewritten on evidence". Context reduction
was P1 — first in the operator's order — and is now **W6**. It was not merely
renumbered: it was demoted on the evidence below, and then its **mechanism** was
replaced too.)*

The original plan was "adopt `tamaratran/fast-jev-compaction`" — 5,405 stars, MIT,
clean TypeScript, 29/29 tests passing. **Its core mechanism is empirically shown
not to work**, by four independent reporters using the repo's own code against
the live API. Detail is in the agent's harvest report (summarised here rather than
stored separately — the standalone file was never written); the three findings
that matter:

1. **No signal.** 87.7% reduction with Jev vs **88.5% with a constant-0 asker**
   on the same 256 tool calls. Every `keepResult` score was below 0.3. Cause is
   structural: the state replaces every tool result with a stub
   (`ok, N chars (omitted)`), so **Jev is asked to judge content it cannot
   see**, using a question ("would re-running not do?") that measures
   irrecoverability rather than usefulness.
2. **It induced fabrication.** `drop_result` leaves a marker; **`drop_call`
   leaves nothing** — it strips the `tool_use` block and keeps the assistant's
   narration verbatim. Past turns become "I created the issue / opened the PR"
   with the evidence removed, which is a few-shot demonstration of asserting
   outcomes without acting. A live session produced **9 consecutive turns
   reporting completed work with zero tool calls, all fabricated.**
3. **It degenerates under repetition.** Retained tokens climbed 36K → 52K → 59K
   → 74K → 87K over five rounds, because only tool calls made *since* the last
   round are candidates and the 70–90% of context that is plain text never is.
   Day-to-day coding means long sessions and many compactions, so any harness we
   build must be **multi-round from the start** — and text, not tool results,
   may turn out to be the thing that actually needs pruning.

**The one encouraging datapoint, and it defines the open question.** With
reworded questions on a 120-message replay, Jev produced a *defensible*
selection — kept the state file the user asked about, three greps and the
relevant `Read`; kept all 10 `Edit` calls while truncating their worthless
"file updated" results; dropped `ls`, `git log`, `git add` — at **40% reduction
versus 81% for the drop-everything rule.** Nobody has measured whether 40% with
intact retention beats the built-in summary at ~85% with lossy rewriting. **That
is the first question the replay harness must answer, and it is answerable in a
day.**

**Why context reduction became ingestion-time trim instead.** Compaction only fires at ~60%
context. But every turn re-sends the whole context, so an oversized tool result
is paid for on *every* subsequent turn until compaction runs. Trimming at
`PostToolUse` shapes the context **before it enters the cached prefix**, so it is
cache-neutral by construction, whereas pruning mid-session invalidates the
prompt cache from the edit point onward and is not automatically a win. It is
also the one place none of the surveyed repos has built for a coding agent.

**This is why the old scheme had two trim entries and the new one has one.**
"P4 — tool-output trim before it enters context" was a separate, later phase
from "P1 — compaction". Once P1 was rewritten into ingestion-time trim the two
became the same mechanism at the same hook, so they collapse into **W6**. The
old P4 row's own rationale — *"same mechanism class, applied earlier in the
pipeline"* — is, read today, the argument for the merge.

*(Provider and routing choices landed in §4 and §7.)*

---

## 6. The guard — how we prove an optimization didn't hurt quality

Harvested from `abide`, `perch` and `NiazMorshed2007/jev-review` (all MIT,
verified present). The key insight from that harvest: **`abide`'s replay harness
is only half of what we need.** It is a *scorer over diffs that already exist in
transcripts* — it never re-runs the agent. Our optimizations change **what the
agent does**, so replaying old transcripts measures the old agent. We harvest
its **reader and its scorer** and supply our own **re-executor**.

Hence two classes, because one is nearly free and one costs real money.

### Class 1 — judge-side regression (every change, pennies, mostly already built)

Applies when the optimization changes **what our own Jev gate sees**: state
trimming, compaction upstream of a hook, tool-output truncation.

- **Unit:** `(decision_id, question_name)` — already the replay key, already
  joined to the original capture, with question-set version in the key so a
  variant is a new row rather than an overwrite.
- **Corpus:** the 578 captures and ~2,095 rows already on disk. Fixed, free.
- **Run:** the existing replay path under the new code, against recorded
  baselines. The built-in truncation stress case (50%/75%) is already an
  ablation of "what if the state were smaller".
- **Scored on:** band-flip rate at each question's τ; AUC (invariant to monotone
  rescaling, so it separates "miscalibrated, fix a constant" from "ranking
  destroyed"); and κ between baseline and treatment answers.
- **Blocks if:** band-flip > 5% of decisions, **or** AUC drops > 0.03 below
  baseline, **or** κ < 0.8. Report-only between 2% and 5%.
- **Cost:** ~600–2,000 Jev calls. Comparable published run: $0.22 in ~2 minutes.
  This is a pre-commit gate, not a research project.

### Class 2 — agent-side regression (needs re-execution)

Applies when the optimization changes **what the coding agent sees, or which
model answers**: compaction, routing, trimming.

**Do not try to replay real past sessions.** Reproducing them needs the repo
state at session start, which the transcript does not carry. That is the
research-project trap. Instead:

- **Fixture suite:** 12–20 fixed, self-contained tasks in a pinned fixture repo,
  each with a written acceptance note. *Mined* from real transcripts (that is
  the one legitimate use of `abide`'s transcript reader here — task mining, not
  scoring).
- **Execution:** headless, k=3 seeds per task per arm, baseline and treatment,
  paired on task. Full suite nightly; a ~6-task smoke subset per change.
- **Unit: the task. Scored on the final `git diff` of the turn — never
  per-edit-call.** Two independent reasons, and the second is sharp:
  1. `abide`'s own published precision is **73% turn-phase vs 26% edit-phase**.
  2. Its `EDIT_TOOLS` set is `{Edit, Write, MultiEdit}` — **Bash-written changes
     are invisible to it.** This very repo's working style pushes edits into
     `sed` and heredocs, so an "optimized" agent that shifted edits into Bash
     would show fewer flagged edits and look *falsely better*. Score the diff.
- **Scored by three tiers, cheapest first:**
  1. **Hard checks, free and deterministic** — tests pass, build succeeds, the
     acceptance note's named assertion exists. These carry most of the weight.
     No model involved.
  2. **Rule compliance** — a rubric compiled from the fixture repo's CLAUDE.md,
     run turn-phase over the final diff. Screen the rubric first and drop rules
     that never discriminate, so we are not measuring against dead questions.
  3. **Dimension scores** — applicability check, then an anchored 1–10 score,
     then a closed-vocabulary weakness choice, over correctness / changeability
     / modularity / tests. **Regression declared only at |Δ| ≥ 0.75**; smaller
     moves on a 10-point ladder are noise.
- **Blind by construction, not by procedure.** The judge sees `{task, file,
  diff}` and never the conversation, so it structurally cannot know which arm
  produced the diff. The blind-integrity check reduces to asserting the arm
  label is absent from the payload.
- **Blocks if:** any task passes tests in *all* baseline seeds and fails in
  *all* treatment seeds — one instance, no statistics. Soft-blocks if treatment
  rule violations exceed baseline on more than a third of tasks, paired and
  clustered on task.

### Exit codes — the most important mechanical detail

```
0  ran clean, nothing to act on
1  COULD NOT RUN (no key, no network, timeout)
2  invoked wrong
3  ran and found a regression
```

**A guard that could not run must never be readable as a guard that passed.**
Collapsing 1 into 0 is the single failure that would make this whole section
decorative.

### What the guard does not claim

It does not prove equivalence. At ~20 fixture tasks it reliably catches only
regressions affecting roughly a third of tasks or more. Class 1 is strong
evidence and nearly free; Class 2 is weak evidence and costs real money. **A
green Class 2 means "no large regression found", never "quality preserved" —
and the gate prints that sentence itself.**

---

## 7. Harvest ledger

Every adopted line records where it came from and under what licence.
All five guard repos verified present; **all MIT**.

| take | from | licence | into |
|---|---|---|---|
| transcript reader (Claude Code JSONL → turn-bucketed edits) | `coldteadotai/abide` | MIT | task mining for the fixture suite |
| turn-snapshot → whole-turn-diff scoring path | `coldteadotai/abide` | MIT | Class 2 scorer |
| band thresholds (act ≥0.8 / flag 0.5–0.8 / clear <0.5) and violation-mass folding | `coldteadotai/abide` | MIT | one gate number from boolean/choice/score |
| rule-health screen (drop non-discriminating questions) | `coldteadotai/abide` | MIT | screening our own question sets |
| rubric schema (rule ↔ source file + line, scope, phase) | `coldteadotai/abide` | MIT | our rule format |
| `MEANINGFUL_DELTA = 0.75`; applicability-check-before-score | `NiazMorshed2007/jev-review` | MIT | Class 2 tier 3 |
| exit-code taxonomy, `--since` diff scoping, record-without-acting, committed dismissals | `lakeday-org/perch` | MIT | gate ergonomics |
| two-stage screening at 0.7 before spending calls | `devagrawal09/jev-review` | MIT | cost control |
| tool-call pairing, batching, decision application, object-identity reuse, tokenizer-free token estimate, `session.compact`/`turn.complete` hook skeleton with fallback | `tamaratran/fast-jev-compaction` | MIT | W6 plumbing |
| replay harness with fake askers (~80 lines, offline, no key) | `yelban/fast-jev-compaction@replay-eval` (fork) | MIT | **cross-cutting: the replay harness, every wave** |
| rule protection: never ask about `Edit`/`Write`, failed calls, `Agent`/`Task` results, newest `Read` before an edit | `yelban/fast-jev-compaction@rule-protection` (fork) | MIT | W6 |
| `validate_choice()` — finite, in-range, sums to 1, argmax consistent; **raises rather than acting** | `browser-use/jev-ultrafast` | MIT | **non-negotiable 8, everywhere** |
| `action_space()` — huge blob → numbered typed index table → one `choice` over indices → one round trip | `browser-use/jev-ultrafast` | MIT | **W6** |
| "Jev chooses, a small cheap model writes" — never ask the non-generative model to generate, never ask the expensive model to choose | `browser-use/jev-ultrafast` | MIT | architecture |
| the 64 KiB return-path contract: only what you return enters context; write big intermediates to disk and grep them | `lidge-jun/aside-codemode` | MIT | W6 |
| `{rows, complete, truncated, partial, scope}` envelope with per-source coverage flags | `lidge-jun/aside-codemode` | MIT | **non-negotiable 9** |
| MLX local runtime; the published list of known divergences from live Jev | `razorback16/openjev` | Apache-2.0 | provider |
| schema validator emitting spec-shaped 422s; in-flight/queue caps with 529; question chunking | `githubnext/localjev` | MIT | contract tests, ops |
| whole Jev contract on one "pointer" primitive (~160 lines); JSON-state flattening; deterministic date preprocessing | `jaredpalmer/kev` | Apache-2.0 | provider fallback |
| the written contract reference; `messages[]` state input | `featherless-ai/simple-jev` | Apache-2.0 | client |
| MLX backend with a unified-memory allocator cap; direct-logit scorer | `TheoLeeCJ/SemIf` | MIT | Apple silicon path |
| circuit breaker on 401/402 (cross-process, TTL); SQLite payload cache; in-flight dedupe; **secret redaction before send**; telemetry that never logs state text | `notque/vexjoy-agent` | MIT | **provider client, wholesale** |
| **asymmetric down-route guard** (up-routing free; cheapening requires margin ≥ 4); `abstain` class; effort floors by regex; anti-churn distance | `tzachbon/claude-model-router-hook` | MIT | **W1 / W4 routing policy** |
| policy ladder: `needs_human` evaluated **first**, safety and hard limits before productivity; post-steering grace period; conjunctive finish gate; strict response validation that raises on a missing key | `thruwire/foreman` | MIT | W1 / W4 routing policy |

**Rejected, with reasons:**

- **`fast-jev-compaction` as a dependency.** Harvest only. Its mechanism is
  disproven (above), 59 issues are open against 1 closed, the maintainer has
  merged 13 PRs of which the most recent is a README tagline, and two reporters'
  fixes-with-replay-scripts were never landed. Building on it means owning it.
- **`abide`'s installer** — writes `~/.claude/settings.json`; contradicts
  non-negotiable 3. Its code is harvested, its installer is not.
- **`aside-codemode`'s MCP server and sandbox** — targets a different agent
  entirely, and **uses no Jev at all** (zero matches for `typesafe|jev` in the
  repo). Its measured win came from shipping ripgrep access to an agent that
  lacked it; Claude Code already has `Grep`, `Glob`, parallel `Read` and `Bash`.
  Our baseline is the ceiling it was measuring toward. Ideas only.
- **Building a code-mode tool.** `Bash` is already Claude Code's code mode.
- **`thruwire/foreman` as a runtime** — not a Claude Code integration. Its
  *policy ladder* is harvested; its harness is not.
- **⚠️ `ekzhang/openjev-sglang` — NO LICENCE.** The GitHub API reports
  `license: null` and there is no LICENSE file. That is **all rights reserved,
  not open source.** Its Pydantic models are the best-annotated rendering of the
  contract anywhere and may be **read as documentation**; no code may be copied.
  Requires a B200 via Modal in any case — no local path.
- **⚠️ `manaflow-ai/cmux`** — licence `NOASSERTION`/"Other". Read for design
  (its session-sticky account selection is the real source of the
  "stickiness keeps the prompt cache warm" idea); copy nothing.
- **`githubnext/localjev` as the probability source.** Its own README states it
  **asks the model to emit a JSON probability and self-report it** — prompted,
  not read from logits, "not mathematically equivalent", with retries on
  malformed JSON. That defeats the entire latency and token premise. Its schema
  validator and ops furniture are excellent and are harvested; its numbers are
  not what we want.

### Provenance note

typesafe.ai's own pricing page states **"$42 Per Billion input tokens"** —
i.e. $0.042/1M, confirming the figure the old README carried, now from the
vendor directly rather than via an AI-generated summary. **"Output free" remains
unverified**; no output price is stated anywhere found. Keys are obtainable
(`console.typesafe.ai`, plus OpenRouter and LiteLLM passthrough), so provider
access is not the blocker previously recorded.

---

## 8. What dies from the old SPEC

- The pre-registration **as a publication commitment**. The file is retained as
  a record of what was believed and when, not as a live obligation.
- Agreement-against-Opus as a headline metric.
- The five-surface shadow matrix as a deliverable.
- The routing A/B as a *science experiment* — routing survives as **W1** (the
  static floor) and **W4** (Jev), an optimization with a ship gate, not a
  randomised trial. With the A/B goes `random_matched`, the third routing arm
  that only ever made sense inside it.
- The writeup.
- The clustered-bootstrap blocker: with one session there is one cluster and no
  computable interval. That killed a *publishable* claim. It does not block a
  personal tool — but it does mean **before/after numbers from a single
  operator's sessions are indicative, not inferential**, and the report must say
  so rather than printing a confident interval.

*The full triage landed 2026-09-21 and is summarised in §9; every ticket in `ISSUES.md` carries a `PIVOT TRIAGE` line. There are **58** headings, not 57.*

---

## 9. What the repo audit changed, and the open decisions it leaves

### The uncomfortable findings, recorded rather than smoothed

1. **`agent_route` — the entire product surface — has zero rows.** All 2,095
   run rows are `pre_bash`. `config/surfaces.json` has `agent_route` at
   `mode: "off"` and only `pre_bash` is registered. **The routing hook has never
   fired live.** JEV-24a's frozen pre-rule baseline is the only "before" that
   exists — and it records **7** delegated tasks, not the 120 quoted elsewhere
   (§10), and no instrument here has ever produced an "after".
2. **The cheapest lever may be *fewer* delegations, not smarter ones.** AqueGen
   has delegate-and-route at $1.68 against $1.36 inline. **JEV-24b — the
   standing "delegate where possible" rule — is actively harmful under the new
   goal**: it grows the surface Jev routes while raising the total bill. It is
   killed, not parked.
3. **The old corpus is not a "before" for the product.** It is worth two things:
   a real Jev latency distribution, and the evidence that **τ=0.5 has been wrong
   on every boolean question asked of Jev, three independent times**. Both are
   design inputs for the router's thresholds. The cost baseline
   (`data/baseline/`) *is* usable — as a **lower bound**, running ~27.6% under
   Claude Code's own total, and only if the "after" goes through the same
   pipeline with JEV-49's fixes applied.
4. **A count discrepancy — ✅ SOURCE IDENTIFIED 2026-09-21 (W5 doc sweep), and
   it is not what it looked like.** On disk: 2,095 run rows and **578** captures.
   The board's freeze figures are 2,005 / 571. *This item used to end "the
   7-capture gap is not [explained]. Neither number should be quoted until it
   is."*

   **Both gaps are JEV-16 Run A**, and the arithmetic is exact:

   | | live | synthetic | canary | replay | total |
   |---|---|---|---|---|---|
   | captures on disk | 490 | **67** | 21 | — | **578** |
   | freeze figure 571 implies | 490 | **60** | 21 | — | 571 |
   | run rows on disk | 1,783 | 180 | 42 | **90** | **2,095** |
   | freeze figure 2,005 implies | 1,783 | 180 | 42 | **0** | 2,005 |

   Run A needed nine paired synthetic states; seven of the nine had to be
   materialised into `data/captures/` before the sweep could run
   (`.scratch/a3-prep/jev16.md`: *"Seven of nine states had to be materialised
   from the synthetic file before the sweep could run, and two pre-existing ones
   were checked to hash identically to a rebuild today"*). Those seven are
   identifiable — `picked_at` all within **2026-09-20T17:26:15**,
   `run_context: synthetic`, `decision_id`s
   `syn-syn-0000/0001/0002/0120/0122/0240/0241` — and **70 of Run A's 90 replay
   rows reference them.** The remaining 60 synthetic captures are the original
   stress set, written 06:51–07:10Z.

   **⚠️ But the obvious story is wrong, and the correction is the finding.** The
   natural reading — "Run A ran after the freeze" — **does not survive the
   timestamps.** Run A ran at **17:26–17:37Z**; the collection freeze is declared
   at **21:42Z**, four hours later. The newest row of any kind in either file is
   **17:36:57Z**. Nothing in this corpus post-dates the freeze.

   So **571 / 2,005 was already an undercount at the moment it was written.**
   Those figures are not a freeze-time count of the files; they are a figure
   carried forward from before Run A landed — or taken by a method that counted
   the synthetic component as "the 60-item stress set" and skipped
   `run_context: replay` entirely. The two omissions are exactly Run A's output,
   which is what makes a carried-forward number the likelier of the two. **Which
   of the two it was is not resolved here**, and it is recorded as open rather
   than guessed.

   **Consequences.** 578 / 2,095 is the count, and it was the count at 21:42Z
   too. **571 / 2,005 should stop being quoted as "standing totals at the
   freeze"** — it is a pre-Run-A total wearing a post-Run-A timestamp. This is a
   mild instance of the house pattern: an inventory that was *reported* rather
   than *counted* reads exactly like one that was counted.

### Why "opt-in per project" was the right call

The audit found that a **global install silently disables the kill switch.**
Every hook derives its root from `$CLAUDE_PROJECT_DIR`; installed globally that
resolves to whatever repo the user is in, so `.jev-disabled` names a file that
does not exist — **the switch is permanently off and there is no way to stop the
tool.** The spool directory is likewise absent, so `capture.sh` exits 0 silently
everywhere, and the stderr log never resolves, so failures are invisible.

The operator chose opt-in-per-project, which dodges this entirely. Two
requirements survive from the analysis anyway:

- **`JEV_HOME` resolved independently of `$CLAUDE_PROJECT_DIR`**, read
  identically by the bash hooks and by `paths.py` — which today derive their
  roots by two different mechanisms that would disagree.
- **Two switches**: a global one and a per-project opt-out, both fail-safe.
  There will be repos where you do not want delegations re-routed, and the
  current design has no concept of "off in this repo only".

### JEV-56 is promoted to a shipping blocker

Under the old goal it was gate hygiene. Under "install this in your repos" it is
non-negotiable: **you cannot distribute a tool whose suite cannot go green on a
clean checkout.**

### Ticket triage, summarised

**24 KEEP · 10 REPURPOSE · 4 PARK · 20 KILL** across the 58 headings that carry a
verdict. (The board is now **63** headings; JEV-57–61 are post-pivot and carry
no triage line. Its long-standing "57" was always off by one.)

> **Updated 2026-09-21 (W5 doc sweep): JEV-09, JEV-23 and JEV-46 re-verdicted
> REPURPOSE → KILL**, moving the tally from 13/17 to 10/20. Same reason in all
> three cases, and it is worth naming because it will recur: **the repurposed
> value had already shipped.** JEV-09's script is the ancestor of W1's actuator;
> JEV-23's surviving boxes are built in W1 and W3, with its sharpest one
> promoted to W4's ship gate; JEV-46's inversion *is* `config/tiers.json`.
> REPURPOSE means there is work left to redirect — when there is not, it leaves
> a shipped thing sitting on the board looking unbuilt.

> **⚠️ The "what dies" sentence here was an ESTIMATE written before anything had
> been deleted, and it was wrong in five places. Rewritten 2026-09-21 against
> the actual removal.** It read: *"Roughly 1,500 lines of Python and the top
> third of `ISSUES.md` go: the agreement statistics, `PREREGISTRATION.md` as a
> live document, `tests/test_board.py`, the `cc_*` arms as arms, the `stop` /
> `post_edit` / `user_prompt` surfaces, `random_matched`, and the clustering and
> power-analysis line of work."* Kept visible because **a forecast of a deletion
> is not a record of one**, and this one was being read as a record.

**What actually went: 1,315 gross / 1,206 net lines of Python** —
`src/analyze.py`, `src/latency_report.py`, `tests/test_analyze_config_join.py`:
the agreement statistics and the reporting built on them. `PREREGISTRATION.md`
stops being a live document. Two more die **as plans rather than as code,
because they were never built**: `random_matched` (zero references anywhere in
`src/`, `tests/`, `config/`) and the power analysis (no module ever existed).

**Four things the estimate said would go, and which STAY. All four are
load-bearing:**

- **The `cc_*` arms and `src/arms/claude_cli.py` — KEEP.** They die *as a
  headline comparison*; the harness is retained, and is still referenced by nine
  modules, `config/arms.json` and two tests. Two **live** tickets need it:
  **JEV-16 Run B** — now a W4 blocker — runs through it, and **JEV-43** measured
  with it. *Killed-ticket code retained by live tickets* is a real category, and
  deleting on the triage label alone would have broken the W4 gate.
- **`tests/test_board.py` — KEEP.** Live, required, and currently catching real
  defects. It reads the wave tables and the `Blocked by:` lines out of
  `ISSUES.md` and asserts they agree; it is the test written so that the gate
  being blocked eight times over by KILLed tickets cannot recur (an audit found
  that instance — this test is why it cannot come back). It is merely *named*
  for a superseded plan; what it checks is scheme-agnostic and more useful after
  a pivot than before one.
- **`stats.clustered_bootstrap` — KEEP.** Live via `validate_threshold.py:412`,
  for JEV-17.
- **`stats.naive_bootstrap` — KEEP**, but not for the reason first given. It is
  **test-only**: `validate_threshold.py` calls `clustered_bootstrap` and never
  this one. It is kept because its test is the **only demonstration of why
  clustering is mandatory**, which is load-bearing for JEV-17 — a deliberate
  retention for a stated reason, not a live caller. Recording the right reason
  matters: "it has a caller" is a fact the next cleanup pass will re-check and
  find false.

**Two clauses of the original remain UNVERIFIED and are not restated as done.**
Only the Python clause was audited. (i) The `stop` / `post_edit` / `user_prompt`
surfaces: their `config/surfaces.json` entries and their `questions/`
directories are all still present at `mode: off`, so what died is the *plan to
collect on them*, not any artifact. (ii) "The top third of `ISSUES.md`" — nobody
has measured it.

None of it was bad work; it was the right build for a question no longer being
asked.

Three verdicts worth flagging because they **invert**:

- **JEV-45** (the ~245ms gateway hop) — was park-worthy; under a *latency* goal
  it is the single largest recoverable chunk of Jev's own 437ms.
- **JEV-46** — `random_matched` dies with the A/B, but the thing that ticket
  *rejected* — a static `subagent_type→tier` map — **became W1, the product's
  zero-cost floor that Jev must beat.** (The ticket is KILLed as of 2026-09-21
  *because* that inversion has shipped, not because the inversion was wrong.)
- **JEV-16** (determinism) — was a safety blocker; now a product rule. A flip
  near τ means **the same task gets a different model on retry**, injecting
  noise into the accuracy gate and, under RESTART-on-escalation, causing the
  same work to be paid for twice. Rule: **do not route inside the flip band.**
  Consequently **Run B — the `jev` determinism sweep, ~$0.018 — is promoted from
  "deferred to Phase B" to a blocker on W4**: Run A measured `cc_haiku45`, the
  wrong arm, so the band this rule depends on has never been measured on the
  model that will be doing the deciding.

### Decisions — all four settled by the operator, 2026-09-21

1. **The corrected goal statement is ACCEPTED.** The adopted target is *lower
   realised cost per delegated task, at equal task success, with no added felt
   latency.* "Reduce tokens" and "reduce execution time" are retired as
   headline claims — the first is wrong for routing, the second is unmeasured
   and partly contradicted by our own JEV-41 result.

2. **Fail to FRONTIER, not open** — see non-negotiable 1(b). The operator
   accepted the cost risk explicitly, in exchange for never silently
   downgrading work on an error path. **The circuit breaker is the condition of
   that acceptance** and is mandatory.

3. **RESTART on escalation, do not continue.** When a task is escalated to a
   higher tier, the higher-tier model starts from the original task, **not**
   from the first attempt's output or reasoning. Rationale, from SWE-Router:
   *"conditioning m2 on m1's reasoning has been seen to bias m2 toward m1's
   mistakes."* The cost consequence is real and must be carried in the
   accounting: **an escalation pays for the work twice.** That is what makes
   escalation expensive and *uplift* (choosing the higher tier before anything
   runs) cheap — the distinction `CONTEXT.md` draws, now load-bearing for cost
   rather than for vocabulary.

4. **Measure inline-vs-delegated FIRST.** This is now **W0** and it **blocks
   W4**. If AqueGen's result replicates on our corpus — delegate-and-route
   costing ~24% more than staying inline — then the correct first
   recommendation is *delegate less*, and optimising the delegated path is
   optimising the wrong thing. W1 proceeds in parallel because the static floor
   is needed either way and adds no cost, but **its tier map may be rewritten
   by W0's answer.**

---

## 10. W0's result, and a corpus-size dispute it exposed

### The AqueGen threat does NOT replicate. Keep delegating.

W0 asked: is delegating to subagents cheaper or dearer than working inline?
`JEV-47` cited AqueGen's telemetry claiming delegate-and-route costs **~24%
more** than staying inline, which would have made "route better" the wrong
project. **It does not replicate here**, and for a mechanical reason we can
point at.

| | measured |
|---|---|
| Delegated vs inline at matched turn count | **$171.94 vs $357.53** — negative net on **30/30** tasks |
| Cost per delegated task | median **$4.50** (IQR $1.72–$7.28, range $0.11–$13.35) |
| Requests per task | median **38** (IQR 20–59, max 107) |
| Cold-start prefix write — *AqueGen's actual mechanism* | **2.0%** of delegated cost ($3.46 of $171.94) |

**Why the mechanism fails here.** The cold-start write is 2.0% of a task's cost
and is amortised over a median 38 turns. **A 2% component cannot produce a 24%
penalty.** And the expensive multiplier does not apply: subagent cache writes
measured **100% 5-minute TTL (1.25×)** while main-session writes are **100%
1-hour (2×)** — 4,431,529 / 0 tokens versus 8,798 / 2,163,568. *The
auth-dependent 2× multiplier applies to **zero** delegated tokens.* This also
refines `PREREGISTRATION` A8.2, whose claim that every row in the work session
is 1-hour TTL is true of the main transcript and **false of its subagents**.

**What the conclusion actually hinges on — and it is not the cache arithmetic.**
Break-even turn ratio `k* = D / (D − penalty + saving)`: **median 0.47** (0.59
with the main context hard-capped). Inline would have to finish the median task
in **~47–59% of the turns** for delegation to lose — plausible for an agent
already holding the context. **That turn ratio is unmeasured.** The highest-value
cheap experiment now on the board is a paired inline-vs-delegated run that
measures it.

**A second reason not to "delegate less":** every task sampled is
`requestShape: background`. Moving that work inline puts it on the **blocking**
main thread, spending against this SPEC's own *no added felt latency*
constraint — a cost AqueGen never prices.

### ⚠️ The delegated-corpus size is disputed by a factor of 17

Three sources, three answers, none reconciled:

| source | count | window |
|---|---|---|
| `data/baseline/delegation-pre-rule-v1.json` | **7** | cut at 2026-09-20T11:11:49Z — *deliberately pre-rule only* |
| counted on disk, 2026-09-21 | **33** | today, method: subagent transcripts |
| `ISSUES.md` JEV-46 / `src/state_builders.py:101`, against `sessions.jsonl` | **120** | full window |

Type distribution is disputed too: JEV-46 says `general-purpose` **78 (65%)**,
today's count says **26 of 33 (79%)**.

**Nothing may be fitted to these numbers until they are reconciled.** The tier
map in W1 is therefore a **declared policy choice, explicitly not data-derived**.
The only claim all three support — and the only one this SPEC leans on — is that
`general-purpose` is the **large majority** of delegated tasks, so the static
rule has no signal on most traffic and addresses **somewhere between a fifth and
a third** of the surface. State the range, never a point.

*How this got into the SPEC:* the 120/78/65% figure was propagated into §5, the
README and the board from an audit that attributed it to the wrong file. It is
not fabricated — JEV-46 sources it to `sessions.jsonl` — but it was quoted
against a file containing 7. Recorded rather than quietly repaired.

### New defect found by W0, needs a ticket

`src/baseline.py:197` — `requests()` keeps the **first** copy of a duplicated
request and never reads `iterations[]`, while `session_metrics.py` keeps the
**last/COMPLETED** copy (early copies are placeholders with `input_tokens: 2`).
All 48 growing keys are inside **subagent** transcripts. Re-running both rules
over identical files: delegated cost **$105.09 frozen vs $171.94 corrected —
+38.9%.** **Superseded by §11 — the real figure under the frozen record's own
cut is +45.2%, and 38.9% must not be quoted against it.**

### Consequences for the board

- **W0 is answered. W4 is unblocked** on this axis.
- **`JEV-47`'s acceptance criteria stay; its 24%-penalty premise must not be
  carried into any writeup unqualified.**
- **`JEV-24b` remains killed** — but on the grounds that it is a confound and an
  unmeasured behaviour change, *not* on the AqueGen cost argument, which has now
  failed to replicate.

---

## 11. The "before" anchor was wrong by 45%, and is now corrected

**Found 2026-09-21, fixed in `98979a7`.** This is the most consequential number
in the pivot, because it is the baseline every future saving is measured
against.

`src/baseline.py:197` kept the **first** copy of a duplicated request and never
read `iterations[]`; `src/session_metrics.py` keeps the **last / COMPLETED**
copy, because early copies are placeholders carrying `input_tokens: 2`. Two
costing rules that had to agree, didn't.

### Why it mattered more than a costing bug

| | frozen | corrected | movement |
|---|---|---|---|
| **cost per delegated task** | **$1.58** | **$2.88** | **+82.6%** |
| delegated spend | $11.04 | $20.16 | +82.6% *(frozen understates by 45.2%)* |
| main-session spend | $56.96 | $64.56 | +13.4% |
| total | $68.00 | $84.72 | +24.6% |
| `delegation_rate_by_spend` | 0.162356 | **0.237947** | +46.6% relative |

**A real 20% saving, measured against the old $1.58 anchor, would have been
published as a 46% *increase*.** Counts do not move — 7 tasks / 37 prompts, and
`delegation_rate_by_task_count` is unchanged, so this is purely a pricing-rule
effect.

### ⚠️ $2.88 and $5.21 are different windows and must NEVER be quoted against each other

The anchor moved twice — $1.58 → $2.88 — and there is a **third** per-delegated-
task figure in the repo that is not a third version of the anchor:

| figure | window | what it is |
|---|---|---|
| **$2.88** | **under the JEV-24a cut** (`delegation-pre-rule-v1.json`'s window, 7 tasks) | **THE ANCHOR.** The "before" every future saving is measured against |
| **$5.21** | **whole corpus, no cut** (33 tasks, mean; median $4.50 — §10) | a description of today's corpus, **not** an anchor |

They differ by **corpus and cut, not by costing rule** — both are computed under
the corrected rule. Putting them in one sentence produces an 81% "increase" that
is entirely an artefact of the window, and it is the same class of error as
quoting W0's +38.9% against the frozen record (above). **Any before/after claim
states which window it is in.** Checked across this SPEC on 2026-09-21: $5.21
does not appear here, and $2.88 appears only in §2 R5 and in the table above —
both correctly labelled as the JEV-24a-cut anchor.

### Two corrections to what was recorded in §10

1. **W0's "+38.9%" is the wrong window.** Those figures ($105.09 vs $171.94)
   reproduce exactly but are **whole-corpus, no cut** — not the frozen record's
   window. Under the JEV-24a cut the effect is **+45.2%**. Do not quote 38.9%
   against `delegation-pre-rule-v1.json`.
2. **The addressable surface is ~24%, not 34%.** The 34% came from the frozen
   manifest, computed under the defective rule.

### How we know it is the rule and not drift

The corrected companion carries **three** scopes: `as_frozen`,
`frozen_rule_today`, and `corrected`. The middle one re-runs the *old* rule
today and is **bit-identical to the published record** — which is the proof
that the movement is the rule, not corpus growth or pricing drift. The
`all_sessions` scope differs from `interactive_sessions_only` only because
`config/pricing.json` later priced `claude-opus-4-7`; the two effects are kept
separate rather than blended.

### What is protected

- **The frozen record is not rewritten.** `delegation-pre-rule-v1.json` is
  verified byte-identical, and `delegation_baseline(force=True)` now **raises**
  rather than overwriting it. Analysis reads the `-corrected.json` companion.
- **The divergence cannot silently recur.** `baseline.requests()` is now a thin
  projection of `session_metrics.billable_requests()` and owns no counting rules;
  a source-level test asserts it re-implements none of them, and a guard
  compares both modules on a fixture and on every fully priced real transcript.

### A second bug, which would have bitten us today

`project_dir()` built Claude Code's transcript slug with `replace("/", "-")`.
Claude Code replaces **every** non-alphanumeric character — so any path
containing a dot, **which is every git worktree under `.claude/worktrees/`**,
resolved to a directory that does not exist, `transcripts()` returned `[]`, and
the module would have written **a baseline of zeros that looks like a finished
answer**. All current work happens in such a worktree.

That is the **fourth** failure-that-looks-like-success in this repository's
history, after the inert config fields, the kill switch that stopped one writer
of two, and the jq-comment apostrophe that made a broken hook exit 0 silently.
The pattern is now explicit enough to be a design rule: **every silent path
needs a positive assertion that it did something, not merely that it did not
error.**

### Open, needs a ticket

`data/baseline/sessions.jsonl` and `manifest.json` still carry costs computed
under the defective rule, and because they are **fingerprint-idempotent** a
re-snapshot appends nothing for an unchanged session — **the wrong numbers will
not self-correct.** Wants a `costing_rule` field on the row schema plus a
one-off forced re-snapshot. That is a schema change to a committed append-only
stream, so it is its own ticket, not a footnote.
