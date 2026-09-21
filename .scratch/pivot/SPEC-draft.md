# SPEC (reworked 2026-09-21) — `jev`: a per-project Claude Code accelerator

> **Status: DRAFT, complete, awaiting the owner's sign-off on §9's four open
> decisions.** Replaces the measurement-harness SPEC. All four harvest agents
> have reported: context reduction, provider + routing, quality guard, and the
> repo audit. **Do not promote to `SPEC.md` until §9 decision 1 — accepting the
> corrected goal statement in §1 — is settled**, because the phase order in §5
> depends on it.
>
> Every repo named here was verified to exist and its licence read. Two
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

### ⚠️ The goal statement is mis-specified in two places, on our own evidence

This must be settled before anything is built on it. `FINDINGS.md` already
answered part of the new question, and the answer is uncomfortable.

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
`data/baseline/manifest.json`: total $125.58, delegated $42.57 — **34%**.
`agent_route` fires only on `Agent` calls; everything the main session does
itself is out of reach, and per-turn routing is impossible.

**The honest restatement, which this SPEC adopts:**

> **Lower realised cost per delegated task, at equal task success, with no added
> felt latency** — plus context reduction where it removes more than it costs.

**And the asymmetry that makes the project worth doing anyway:** one delegation
moved Opus→Haiku saves **$0.0520** against a **$0.000014** Jev call —
**3,674× leverage.** Routing is the only mechanism in the repo with that sign.

The difference is not cosmetic. The old deliverable was *a number about Jev*.
The new deliverable is *a faster, cheaper session that is no worse*. Almost all
the engineering survives; almost all the framing dies.

**The one clause that keeps the old work alive:** "without degrading quality" is
a measurement requirement. It is now a **gate on shipping an optimization**, not
a result to publish. The harness stops being the product and becomes the brake.

---

## 2. Success criteria

Four numbers. An optimization ships only when all four are satisfied.

| # | Criterion | Measured how | Ships if |
|---|---|---|---|
| **S1** | **Token reduction** | input tokens per turn and per session, baseline vs treatment on the fixture suite | material reduction, stated with its spread |
| **S2** | **Wall-clock reduction** | turn latency p50/p95 | no regression; reduction where claimed |
| **S3** | **Quality non-regression** | the two-class guard in §6 | Class 1 and Class 2 both pass |
| **S4** | **Net win after the layer's own cost** | Jev call latency + spend, subtracted from S1/S2 | net positive |

**S4 is not optional and is the criterion most likely to be quietly skipped.**
The old README already learned this lesson the hard way and published an
attribution table for it: a layer that saves 5,000 tokens but adds 250ms of
gateway latency to every tool call has not obviously helped. Every optimization
reports its own overhead in the same units as its win.

### What we explicitly do not claim

- Not "Jev is accurate." We never establish ground truth for Jev's judgments.
- Not "quality is preserved." The guard **fails to detect** a regression at a
  stated power. Green means "no large regression found". §6 puts that sentence
  in the gate's own output so nobody has to remember it.
- Not a benchmark, not a paper, not a model comparison.

---

## 3. Non-negotiables

These are hard constraints. A design that violates one is wrong, not a tradeoff.

1. **Fail open, always.** Every hook exits 0. Jev down, slow, rate-limited, or
   returning nonsense ⇒ the session proceeds exactly as vanilla. *We explicitly
   reject the fail-closed pattern* seen in the `router` CLI from prior art: that
   is defensible for a deliberate dispatch tool and indefensible for something
   sitting in the path of daily work.
2. **Never rewrite content.** Compaction **deletes whole stale items**; it never
   paraphrases, summarises or regenerates. Surviving bytes are identical to the
   originals. File paths, error strings, diffs and stack traces are preserved
   exactly. This single property is what makes compaction the low-risk win.
3. **Opt-in, per project, reversible in one command.** `jev install` writes
   `./.claude/settings.local.json` in a repo you choose. `jev uninstall` removes
   it. **Nothing is ever written to `~/.claude/settings.json`.**
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
 ├─ install / uninstall      per-project hook registration; never global
 ├─ provider/                Jev client: gateway | local backend          ⏳
 ├─ optimizations/
 │   ├─ compact/             PreCompact: score and DROP stale tool results
 │   ├─ route/               pre-dispatch (model, effort) selection       ⏳
 │   └─ trim/                tool-output reduction before it hits context ⏳
 ├─ guard/                   the two-class regression gate  (§6)
 └─ report/                  before/after tokens, latency, and S4 overhead
```

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

## 5. The four phases

Operator's sequencing decision, 2026-09-21: compaction first, guard second,
routing third, trim fourth — each gated on the one before.

**Revised again after the repo audit.** The operator's chosen order was
compaction → guard → routing → trim. Two findings move routing to the front and
insert a Jev-free phase before everything:

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

| phase | what | why this order | risk |
|---|---|---|---|
| **W1** | **The static floor — no Jev call at all.** A `PreToolUse` hook on `Agent` applying a `subagent_type → tier` map, rewriting `tool_input.model` | **The first shippable thing.** Zero classifier calls, **zero added latency**, and the prior art says it captures most of the available saving. It also builds every piece of scaffolding W4 needs and produces the "after" corpus that nothing in this repo has ever produced | low |
| **W2** | **Safe install + teardown**, opt-in per project | Must work *before* the router is armed, not after | — |
| **W3** | **The accuracy gate** — per-task pass/fail, blinded | Nothing in this repo has ever measured whether a routed subagent did the work correctly | — |
| **W4** | **Jev enters, as increment two** — targeted at the **65% `general-purpose` residue** where the static rule has no signal | **Ship gate: Jev must beat the two-line rule on realised cost at equal task success.** If it cannot, we keep the rule and stop | high |
| **W5** | **Context reduction** — ingestion-time trim of oversized tool results, and/or rebuilt compaction | Demoted from P1. Must clear §2c's bar: remove far more than the +337 tokens / +557ms it costs, so it fires only on large payloads | medium |
| **W6** | **Operate** — canary on a schedule, latency SLO, weekly cost report against the frozen baseline | — | — |

**P0 applies to every phase, not just one:** the replay harness and its
**constant control** (non-negotiable 7). Offline, no key required.
| **P2** | **The guard** — the two-class gate of §6 | Proves P1 was safe. **Must be shown to catch a deliberately injected regression before it is trusted** | — |
| **P3** | **Routing** — per-phase (model, effort) selection before dispatch | Latency and cost win, but it changes *which model does your work*, so it needs P2 working | high |
| **P4** | **Tool-output trim** — reduce large tool results to typed rows before they enter context | Same mechanism class as P1, applied earlier in the pipeline | medium |

**The P1/P2 ordering is deliberate and slightly counter-intuitive.** P1 builds
the mechanism and measures the token win **behind a flag, off by default**. P2
builds the guard. P1 is only *enabled* once P2 passes against it. Shipping an
optimization before its brake exists is the exact failure this sequencing
prevents.

### P1 was rewritten on evidence, 2026-09-21

The original P1 was "adopt `tamaratran/fast-jev-compaction`" — 5,405 stars, MIT,
clean TypeScript, 29/29 tests passing. **Its core mechanism is empirically shown
not to work**, by four independent reporters using the repo's own code against
the live API. Detail is in `.scratch/pivot/harvest-compaction.md`; the three
findings that matter:

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
is the first question P0's harness must answer, and it is answerable in a day.**

**Why P1 became ingestion-time trim instead.** Compaction only fires at ~60%
context. But every turn re-sends the whole context, so an oversized tool result
is paid for on *every* subsequent turn until compaction runs. Trimming at
`PostToolUse` shapes the context **before it enters the cached prefix**, so it is
cache-neutral by construction, whereas pruning mid-session invalidates the
prompt cache from the edit point onward and is not automatically a win. It is
also the one place none of the surveyed repos has built for a coding agent.

⏳ *P3's concrete starting code pending the provider/routing agent.*

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
| tool-call pairing, batching, decision application, object-identity reuse, tokenizer-free token estimate, `session.compact`/`turn.complete` hook skeleton with fallback | `tamaratran/fast-jev-compaction` | MIT | P1b plumbing |
| replay harness with fake askers (~80 lines, offline, no key) | `yelban/fast-jev-compaction@replay-eval` (fork) | MIT | **P0** |
| rule protection: never ask about `Edit`/`Write`, failed calls, `Agent`/`Task` results, newest `Read` before an edit | `yelban/fast-jev-compaction@rule-protection` (fork) | MIT | P1b |
| `validate_choice()` — finite, in-range, sums to 1, argmax consistent; **raises rather than acting** | `browser-use/jev-ultrafast` | MIT | **non-negotiable 8, everywhere** |
| `action_space()` — huge blob → numbered typed index table → one `choice` over indices → one round trip | `browser-use/jev-ultrafast` | MIT | **P1** |
| "Jev chooses, a small cheap model writes" — never ask the non-generative model to generate, never ask the expensive model to choose | `browser-use/jev-ultrafast` | MIT | architecture |
| the 64 KiB return-path contract: only what you return enters context; write big intermediates to disk and grep them | `lidge-jun/aside-codemode` | MIT | P1 / P4 |
| `{rows, complete, truncated, partial, scope}` envelope with per-source coverage flags | `lidge-jun/aside-codemode` | MIT | **non-negotiable 9** |
| MLX local runtime; the published list of known divergences from live Jev | `razorback16/openjev` | Apache-2.0 | provider |
| schema validator emitting spec-shaped 422s; in-flight/queue caps with 529; question chunking | `githubnext/localjev` | MIT | contract tests, ops |
| whole Jev contract on one "pointer" primitive (~160 lines); JSON-state flattening; deterministic date preprocessing | `jaredpalmer/kev` | Apache-2.0 | provider fallback |
| the written contract reference; `messages[]` state input | `featherless-ai/simple-jev` | Apache-2.0 | client |
| MLX backend with a unified-memory allocator cap; direct-logit scorer | `TheoLeeCJ/SemIf` | MIT | Apple silicon path |
| circuit breaker on 401/402 (cross-process, TTL); SQLite payload cache; in-flight dedupe; **secret redaction before send**; telemetry that never logs state text | `notque/vexjoy-agent` | MIT | **provider client, wholesale** |
| **asymmetric down-route guard** (up-routing free; cheapening requires margin ≥ 4); `abstain` class; effort floors by regex; anti-churn distance | `tzachbon/claude-model-router-hook` | MIT | **P3 policy** |
| policy ladder: `needs_human` evaluated **first**, safety and hard limits before productivity; post-steering grace period; conjunctive finish gate; strict response validation that raises on a missing key | `thruwire/foreman` | MIT | P3 policy |

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
- The routing A/B as a *science experiment* — routing survives as P3, an
  optimization with a gate, not a randomised trial.
- The writeup.
- The clustered-bootstrap blocker: with one session there is one cluster and no
  computable interval. That killed a *publishable* claim. It does not block a
  personal tool — but it does mean **before/after numbers from a single
  operator's sessions are indicative, not inferential**, and the report must say
  so rather than printing a confident interval.

⏳ *Full 57-ticket triage pending the repo-audit agent.*

---

## 9. What the repo audit changed, and the open decisions it leaves

### The uncomfortable findings, recorded rather than smoothed

1. **`agent_route` — the entire product surface — has zero rows.** All 2,095
   run rows are `pre_bash`. `config/surfaces.json` has `agent_route` at
   `mode: "off"` and only `pre_bash` is registered. **The routing hook has never
   fired live.** JEV-24a's 120 delegated tasks are the only "before" that
   exists, and no instrument here has ever produced an "after".
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
4. **A count discrepancy nobody has explained.** On disk: 2,095 run rows and
   **578** captures. The board's freeze figures are 2,005 / 571. The runs gap is
   explained (2,005 + JEV-16 Run A's 90 replay rows). **The 7-capture gap is
   not.** Neither number should be quoted until it is.

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

**16 KEEP · 15 REPURPOSE · 6 PARK · 21 KILL** across the 58 headings (the
board's "57" is itself off by one). Roughly 1,500 lines of Python and the top
third of `ISSUES.md` go: the agreement statistics, `PREREGISTRATION.md` as a
live document, `tests/test_board.py`, the `cc_*` arms *as arms*, the `stop` /
`post_edit` / `user_prompt` surfaces, `random_matched`, and the clustering and
power-analysis line of work. None of it was bad work; it was the right build for
a question no longer being asked.

Three verdicts worth flagging because they **invert**:

- **JEV-45** (the ~245ms gateway hop) — was park-worthy; under a *latency* goal
  it is the single largest recoverable chunk of Jev's own 437ms.
- **JEV-46** — `random_matched` dies with the A/B, but the thing that ticket
  *rejected* — a static `subagent_type→tier` map — **becomes W1, the product's
  zero-cost floor that Jev must beat.**
- **JEV-16** (determinism) — was a safety blocker; now a product rule. A flip
  near τ means **the same task gets a different model on retry**, injecting
  noise into the accuracy gate. Rule: **do not route inside the flip band.**

### Open decisions, owner's call

1. **Accept the corrected goal statement** in §2, or reject it and say why.
2. **Fail-open vs fail-to-frontier.** A known dispatcher fails to frontier — a
   Jev outage then silently routes everything to Opus and the bill explodes.
   This SPEC's non-negotiable 1 says fail **open to the default**. Confirm.
3. **Restart vs continue on escalation.** SWE-Router restarts, *"because
   conditioning m2 on m1's reasoning has been seen to bias m2 toward m1's
   mistakes."*
4. **Measure inline-vs-delegated on our own corpus** before optimising the
   delegated path at all. If AqueGen's result replicates here, the first
   recommendation is to delegate less.
