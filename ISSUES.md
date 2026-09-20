# ISSUES

The issue tracker for this experiment. One `##` heading per ticket. Tickets are
numbered `JEV-nn` and never renumbered. A ticket may be split into `nn-a` / `nn-b`
when an ordering hazard is found inside it; the number is preserved.

`Status:` is one of `ready-for-agent` | `in-progress` | `blocked` | `done`.
A ticket is workable when every ticket in its `Blocked by:` line is `done`.

Tickets are vertical slices: each cuts a complete path through the pipeline
(hook -> spool -> worker -> arm -> row -> report) and ends in something you can
run and look at, rather than finishing one layer at a time.

---

## JEV-01: Skeleton and self-containment

**Status:** done
**Labels:** setup
**Blocked by:** None (can start immediately)

**What to build:** A git repository whose layout is legible at a glance, whose
credentials load from a mode-600 file inside the folder, and which can prove on
demand that it writes nothing outside itself.

- [x] `git init`, `.gitignore` covering `.env`, `data/`, `spool/`, `logs/`, `reports/`, `.jev-disabled`, `.claude/settings.local.json`
- [x] Directory layout created for hooks, config, questions, src, tests, data, logs, reports, docs
- [x] `.env.example` committed; `.env` created at mode 600 and never tracked
- [x] `paths.py` is the single source of truth for every path; the only path outside the folder is the read-only transcript directory
- [x] `doctor.py` reports layout, credentials, gitignore coverage, tracked-file safety, user-level hook isolation, and a static no-outside-writes lint
- [x] `SPEC.md`, `ISSUES.md`, `docs/PLAN.md`, `README.md` present

---

## JEV-02: Jev API spike

**Status:** done
**Labels:** spike, blocking
**Blocked by:** JEV-01 (both cleared)

> **Resolved 2026-09-20.** The billing gate cleared and the spike ran in full.
> Three client bugs found, all fixed and regression-tested. Earlier note:
>
> **Run 2026-09-20.** The key authenticates, but the gateway returns
> `HTTP 403 customer_verification_required`: "AI Gateway requires a valid credit
> card on file to service requests." This is a billing gate, not an auth failure —
> a 401 would mean the key is wrong. Add a card at vercel.com to unlock the free
> credits, then re-run. The arm classified it correctly as `account_gated` and
> recorded it as an attrition row, which is the behaviour we wanted to see.

**What to build:** A single live round-trip against the Jev endpoint that settles
the vendor contract every later ticket assumes. Run deliberately, never from the
automated test suite.

- [x] `arms/jev.py --selftest` performs one live evaluate call and prints the raw response
- [x] Confirms the shape of `answers` and `usage` matches what the design assumes
- [x] Determines empirically whether `providerMetadata.typesafe.confidence` survives the REST path (documented for the AI SDK only)
- [x] Determines whether repeated identical calls return identical probabilities
- [x] Determines whether prompt caching fires for short classifier prefixes
- [x] Confirm `effort` belongs inside `output_config` for the Anthropic arms (check the claude-api skill's curl docs before spending)
- [x] Watch `stop_reason`: if thinking is on by default for Opus 5, `max_tokens: 256` may be consumed entirely by thinking and every call returns `malformed_response: no text content`. The code surfaces this correctly — read it rather than guessing
- [x] Print the EXACT `response_model` string each arm returns and add it to `config/pricing.json`. An unpriced model yields `cost_usd: null` and a `nan` in the cost column, by design — the table has to be populated from the spike rather than guessed
- [x] Findings recorded in `docs/API-FINDINGS.md` with the date and the response model string

---

## JEV-03: Offline tracer bullet

**Status:** done
**Labels:** core, test
**Blocked by:** JEV-01

**What to build:** The entire pipeline working end to end with no network at all,
so the shape is proven before any money or any live session is involved.

- [x] `capture.sh` accepts a recorded hook payload on stdin, spools it atomically, and exits 0 in under 10ms
- [x] Kill switch, cwd guard, backpressure and fail-open all behave correctly at the process boundary
- [x] `worker.py --once` drains the spool, builds state, evaluates through `FakeArm`, and writes a `runs` row
- [x] `analyze.py --report` reads the resulting jsonl and prints a per-surface table
- [x] Seam 1 (hook process boundary) and seam 2 (`evaluate` with a fake arm) both have tests
- [x] The whole path runs from a single command with zero API spend

---

## JEV-04: Three real arms, interleaved

**Status:** done
**Labels:** core
**Blocked by:** JEV-02, JEV-03

**What to build:** Replace the fake arm with the three real ones and make the
comparison between them fair by construction.

- [x] `jev`, `opus5` and `haiku45` all implement `evaluate(state, questions, config) -> Run`
- [x] Arm order is randomised per decision point so no arm systematically pays time-of-day network drift
- [x] All three arms receive byte-identical state; `state_sha256` recorded per run
- [x] Timings decomposed into DNS, TCP, TLS and TTFB
- [x] Failures and timeouts are written as rows with `ok:false` and an `error_kind`, never dropped
- [x] Cost computed per exact model string with cache multipliers, from version-pinned rates
- [x] Demo: one captured command produces three rows and a latency-and-cost table

---

## JEV-05: Statistics and report v1

**Status:** done
**Labels:** analysis, test
**Blocked by:** JEV-03

**What to build:** The analysis that turns rows into defensible numbers, verified
against known answers before any real data exists.

- [x] Every metric reported per surface; nothing pooled across surfaces
- [x] Boolean agreement at tau=0.5 with Cohen's kappa and PABAK reported together
- [x] The majority-class baseline and the base rate printed beside every agreement number
- [x] Confidence intervals bootstrapped clustered on `session_id`, with the naive interval shown once for comparison
- [x] Hard assertion that all arms for a decision share a `state_sha256`
- [x] The word "accuracy" appears nowhere in generated output
- [x] Known-answer tests over hand-built fixtures for kappa, PABAK and the clustered bootstrap

---

## JEV-06: The "before" baseline

**Status:** done
**Labels:** metrics, test
**Blocked by:** JEV-01

**What to build:** Per-session cost, token and wall-clock metrics harvested from
Claude Code's own transcripts. This is the only thing a later enforce phase can
ever be differenced against, so it starts collecting on day 0.

- [x] Transcript lines deduplicated by `requestId`; `usage.iterations[]` ignored
- [x] Tokens reported by class -- input, cache-write, cache-read, output, thinking -- never as one sum
- [x] Cost computed with cache multipliers per exact model string including any context suffix
- [x] Cost reconciled against the session's own `cost-state.totalCostUSD`, with the delta reported
- [x] Wall-clock, assistant turns, tool calls by name, and `is_error` tool results counted
- [x] Friction proxies counted: user interruptions and permission denials
- [x] Runs against a real completed transcript read in place; only DERIVED numbers are frozen into `data/fixtures/` — no third-party transcript content is copied into this folder
- [x] Subagent transcripts under `<session>/subagents/` are included (found via the reconciliation check; worth 4.4 points of delta)
- [x] Findings written up in `docs/COST-RECONCILIATION.md`

---

## JEV-07: Pre-registration

**Status:** done
**Labels:** science, blocking
**Blocked by:** JEV-04, JEV-05

**What to build:** The commitment document, committed to git before a single live
record is collected. Blocked on 4 and 5 deliberately: you can only honestly
pre-register metrics you have already demonstrated you can compute.

- [x] Primary metric and directional hypothesis stated per surface
- [x] Secondary metrics explicitly marked as secondary
- [x] Stopping rule is calendar-based; N is explicitly not a stopping criterion
- [x] Exclusions decided in advance: sidechains, failed runs, canary and synthetic rows
- [x] The synthetic/live split stated, and which claims rest on which
- [x] Pricing snapshot date recorded
- [x] States plainly that Phase 1 makes no accuracy or calibration claim
- [x] Committed; its git hash is the citation used in the writeup
- [x] Records which hypotheses the day-0 spike settled BEFORE collection — notably the falsified determinism hypothesis — so a reader can see which questions were open at which point
- [x] States what would falsify the headline, and that 'inconclusive at this sample size' is the most probable outcome

---

## JEV-08: Go live on pre_bash

**Status:** done
**Labels:** hooks, verification, blocking
**Blocked by:** JEV-07

**What to build:** The first real capture from a real session -- gated behind
three verification tests that must all pass before the hook is enabled.

- [x] Hook registered in `.claude/settings.local.json` for `pre_bash` only, with `$CLAUDE_PROJECT_DIR`-anchored paths
- [x] Isolation gate: a control directory produces nothing; the worktree-subagent case is exercised and its spool destination recorded; `settings.local.json` confirmed gitignored
- [x] Fail-open gate: bogus key, unreachable host and a read-only spool all leave the session unaffected and the hook exiting 0
- [x] Kill-switch gate: `.jev-disabled` produces zero activity
- [x] A real session in this repo produces a capture with a matching `session_id`
- [x] `tests/gates.sh` runs all three gates as one adversarial suite: 21 assertions, all passing
- [x] Live payload confirms the assumed schema (`session_id`, `prompt_id`, `tool_use_id`, `cwd`, `permission_mode`, `transcript_path`, `effort`); `agent_id`/`agent_type` are absent on a main-session call, so `is_sidechain` correctly reads false
- [x] Registration is picked up MID-SESSION — no restart needed
- [x] First live decisions drained end to end: 3/3 arms ok

---

## JEV-09: True inline shadow

**Status:** in-progress
**Labels:** hooks, hot-path
**Blocked by:** JEV-08

**What to build:** The script you would actually deploy, running live but never
blocking -- because a capture-and-replay harness never exercises it.

- [x] `inline_shadow_bash.sh` calls Jev synchronously with a hard `--max-time`
- [x] Logs the decision it would have made; never emits a permission decision
- [x] Exits 0 on every path including timeout, network failure and malformed response
- [x] State string verified BYTE-IDENTICAL to `state_builders.build_pre_bash` — without this, shadow and enforce would score different inputs
- [x] 40 assertions in `tests/test_inline_shadow.sh`; every path exits 0 with empty stdout
- [x] Measured via `bench_inline.py -n 100` live: **624ms p50 / 929ms p99 e2e**, of which ~69ms is scaffolding no faster model removes
- [ ] p99 under LIVE SESSION conditions — needs the inline hook registered alongside `capture.sh`, which is a separate decision
- [ ] Decide `--max-time`: the 2.0s default sits BELOW Jev's 2,681ms p99, so the top 1-3% of the tail becomes timeout attrition

---

## JEV-10: Synthetic stress set and robustness

**Status:** in-progress
**Labels:** science
**Blocked by:** JEV-04, JEV-05

**What to build:** The discrimination story, which the live base rate is too
degenerate to provide on its own.

- [x] 360 stratified items (120 distinct commands x 3 contexts), balanced 120/120/120 across destructive, borderline and benign
- [x] `replay.py --synthetic` runs them through all arms; `analyze.py --synthetic` reports AUC, Youden threshold and mean probability per stratum, labelled synthetic and never pooled with live
- [x] Sweep harnesses written: `--determinism N`, `--phrasings`, `--truncation`; `--estimate` prints call counts before spending
- [ ] Sweeps actually RUN (needs credentials)
- [ ] Determinism sweep: N=20 byte-identical repeats per arm
- [ ] Phrasing sensitivity across the 2-3 variants per question
- [ ] Option-order sensitivity for `choice` questions
- [ ] State-truncation sensitivity at 50/75/100%

---

## JEV-11: Enforce-overhead bench and drift canary

**Status:** in-progress
**Labels:** metrics, science
**Blocked by:** JEV-08

**What to build:** Two small instruments: what enforcement would actually cost in
latency, and whether the vendor changed the model underneath you mid-collection.

- [x] `bench_inline.py` invokes the real hook N=200 times over recorded states and reports end-to-end wall-clock including process spawn
- [x] Reported as projected enforce overhead, clearly separated from API latency
- [ ] `canary.py` evaluates ~20 fixed states daily and records `response_model` and answers
- [ ] A drift report flags any change in answers or model string across the collection window

---

## JEV-12: Figures and publishable export

**Status:** blocked
**Labels:** analysis, security
**Blocked by:** JEV-05, JEV-10

**What to build:** The artifact you would actually publish, with the redaction
step that makes publishing safe.

- [ ] Latency CDFs, sharpness histograms, pseudo-reliability curves whose axis reads "P(Opus agrees)"
- [ ] Per-bin counts shown on every reliability diagram
- [ ] Export-time scrubber with a recorded `redaction_version`
- [ ] `data/states/` excluded from the exported artifact by default
- [ ] The exported bundle contains the pre-registration hash and the collection window

---

## JEV-13: Remaining three surfaces

**Status:** blocked
**Labels:** hooks
**Blocked by:** JEV-08, plus roughly one week of pre_bash data analysed end to end

**What to build:** Registration of the other three surfaces, held deliberately
until the analysis path is proven on one -- otherwise you collect thousands of
records you cannot use.

- [ ] `stop`, `user_prompt` and `post_edit` capture hooks registered
- [ ] **Blocker found during JEV-03, resolve before building this.** `build_stop` requires `transcript_bytes_at_capture`, but `capture.sh` does no JSON parsing by design, so it cannot `stat` a path it never reads. Decision #7's mechanism has no implementation route as currently written. Two options: give `stop` its own hook line that extracts the path with a single `sed -n 's/.*"transcript_path":"\([^"]*\)".*/\1/p'` and calls `stat -f %z`, then re-time it against the 10ms budget; or find a different truncation marker. `build_stop` already refuses to run without the offset, so the leakage guard holds either way — the surface simply cannot be enabled until this is settled
- [ ] `stop` state built from the transcript truncated at `transcript_bytes_at_capture`, never the tail
- [ ] Each capture records its `state_source`
- [ ] Per-surface switches verified independently

---

## JEV-14: Subscription-only baseline, and the disclosure that makes it honest

**Status:** done
**Labels:** core, science
**Blocked by:** None

**What to build:** Run the entire study on the Claude subscription with no
Anthropic API key, and make the resulting confound impossible to miss.

- [x] `cc_opus5` and `cc_haiku45` arms via `claude -p --output-format json --json-schema`
- [x] Enabled set is subscription-only; `opus5`/`haiku45` stay defined but disabled
- [x] Recursion guard: `JEV_ARM_SUBPROCESS=1` makes `capture.sh` exit on line one, so a spawned session cannot capture its own decisions
- [x] Attribution table in every surface section, decomposing state tokens from preamble tokens and process spawn from API time
- [x] Scope disclosure in the report header, stating the claim is about Claude Code as deployed
- [x] `doctor.py` treats a missing `ANTHROPIC_API_KEY` as correct, and warns if a metered arm is ever enabled
- [x] 403 classified as `account_gated`, distinct from `auth` — different problems, and an attrition table that conflates them is useless
- [x] Verified live: 10 state tokens against 5,460 preamble tokens, 1.5s spawn on 4.6s API

## JEV-15: GATE 4 — the future-leakage test that does not exist

**Status:** ready-for-agent
**Labels:** verification, blocking, science
**Blocked by:** None (can start immediately)

**What to build:** A gate proving decision #7 actually holds. `tests/gates.sh`
has 21 assertions covering isolation, fail-open and the kill switch, and **zero
covering future-leakage** — the study's most load-bearing methodological claim,
asserted in `PLAN.md`, `SPEC.md` and `FINDINGS.md` and verified nowhere.

This applies to the already-live `pre_bash` surface. It should not wait for `stop`.

- [ ] Fixture transcript; fire the hook; record `state_sha256_expected`
- [ ] Append 20 more lines to the transcript; drain; assert the hash is UNCHANGED
- [ ] Negative control: strip the offset, assert the capture is QUARANTINED not processed
- [ ] Offline, `FakeArm` only, no network, no spend
- [ ] Parameterise the three existing gates on surface — they are hardcoded to `pre_bash`

---

## JEV-16: Determinism sweep — the enforcement blocker

**Status:** ready-for-agent
**Labels:** science, blocking
**Blocked by:** None

**What to build:** The measurement that decides whether Jev can ever enforce.
`src/determinism.py` is written and correctly **exits non-zero** rather than
reporting a green result on absent data. `replay.py --determinism N` has never run.

- [ ] Run `replay.py --determinism 20 --arms jev` over a stratified sample — Jev-only costs pennies; the `cc_*` arms would cost hours and are not what is in question
- [ ] Report flip rate bucketed by |p − τ|; the hypothesis is that flips concentrate near τ and vanish away from it
- [ ] Resolve the 41%-occupancy concern: at τ=0.95 on `needs_review`, 24/59 synthetic items sit within 0.05 of the threshold
- [ ] If flips are confined to a narrow band, enforcement is viable with a dead-zone rule; if not, `needs_review` cannot enforce at any threshold

---

## JEV-17: Replace the fitted thresholds with a rule

**Status:** ready-for-agent
**Labels:** science
**Blocked by:** JEV-16 (a dead-zone rule depends on the flip-rate result)

**What to build:** τ=0.36 and τ=0.95 do not survive validation (optimism gap
≈ +0.10, and 0.36 is an unstable constant selecting anywhere in 0.36–0.63). A
constant fitted to 59 synthetic items does not transfer; a rule re-derives itself
as data accumulates.

- [ ] Adopt a fixed-target-recall rule (weakly dominant on `destructive`: never worse across 500 paired splits, better on 11–13%)
- [ ] Re-derive on LIVE captures once the collection window closes, and report the live-vs-synthetic threshold difference as a finding
- [ ] State the rule in `PREREGISTRATION.md` as a dated amendment before it is used for any claim (one pre-registration file, not three)

---

## JEV-18: `user_prompt` / routing — FIRST of the remaining surfaces

**Status:** blocked
**Labels:** hooks, science
**Blocked by:** JEV-15, plus the mechanism work in `docs/PLAN-SURFACES.md` §0

**What to build:** Per `docs/PLAN-SURFACES.md` §2. Sequenced FIRST, reversing the
original order: Part 4c established that gating is additive on every axis and
**routing is the only surface that can make Claude Code faster or cheaper.**

**Scope correction — this ticket produces a weaker claim than JEV-23, and must
say so.** Per-turn routing has no mechanism (verified: every model switch is
session-scoped, and `PreModelSwitch` cannot redirect one). So `user_prompt`
routing can only ever be a **counterfactual**: "if per-turn routing existed,
here is what it would have saved." That estimate is unfalsifiable by design and
no amount of data promotes it. JEV-23 (`agent_route`) is the measurable version
and is the headline. If the budget takes only one, it takes JEV-23.
Strongest economics, thinnest evidence.

- [ ] `questions/user_prompt/v2.json` adding a `complexity` score (v1 is frozen; never edit it)
- [ ] No "which model" question — a complexity score plus a threshold evaluates every routing policy offline; a model-choice answer evaluates exactly one
- [ ] Per-surface arms: jev 100%, cc_opus5 on a deterministic 1-in-3 subsample
- [ ] **The realised-cost label**: correlate `complexity` against the ACTUAL cost of the turn that followed. Zero human labels, and the only Phase-1-feasible test of the $0.052-per-downgrade economics
- [ ] ~60-item synthetic set including the class the probe failed on: short, plain-sounding, symptom-only debugging prompts
- [ ] Re-run the empty-stdout gate specifically — `UserPromptSubmit` stdout is injected into session context, so a stray byte contaminates the prompt being measured

---

## JEV-19: `stop` — resolve the blocker, or cancel the surface

**Status:** blocked
**Labels:** hooks, science
**Blocked by:** JEV-18

**What to build:** Per `docs/PLAN-SURFACES.md` §1. **STEP 0 FIRST, before any
code**: register `capture_only` with the unmodified hook, run one session, and
settle two unknowns by looking — does the Stop payload carry
`last_assistant_message` (contested), and is the final message flushed to the
transcript before the hook fires?

- [ ] Step 0 payload inspection, recorded in `docs/`
- [ ] **If both unknowns go the wrong way, CANCEL the surface with a written negative result.** "The Stop hook cannot see the message it is being asked about" is a publishable finding about hook design and far cheaper than a week of uninterpretable rows
- [ ] Otherwise: filename-encoded byte offset, zero-fork extraction, one `stat` (~1–2ms)
- [ ] Fix `_flatten_content`, which keeps the HEAD of tool results while verdicts are at the TAIL — this directly undermines `has_unverified_claim`
- [ ] ~60 mini-transcript synthetic set; the unverified-claim stratum is the one no live week will produce

---

## JEV-20: `post_edit` — risk scoring

**Status:** blocked
**Labels:** hooks
**Blocked by:** JEV-19

**What to build:** Per `docs/PLAN-SURFACES.md` §3.

- [ ] Fix the verified matcher mismatch: `surfaces.json` says `Edit|Write|NotebookEdit`, the builder quarantines NotebookEdit and MultiEdit unconditionally. Register `Edit|Write` only
- [ ] Verify `isinstance(response, str)` against a real payload — `tool_response` is likely a dict, silently dropping the tool result
- [ ] Head-preserving truncation: front-truncation discards exactly what determines the risk anchor on a `Write`
- [ ] ~100-item synthetic set with the adversarial pairs: a one-character auth-check flip (anchor 5, looks like 1) and a 200-line reformat (anchor 1, looks like 4)

---

## JEV-21: Degenerate-interval guard and stopping-rule amendment

**Status:** done
**Labels:** science, blocking
**Blocked by:** None

**What to build:** A guard against the trap the power analysis found in our own
pre-registered test, plus the stopping-rule change it forced. Both committed the
same day as the original registration, before the window closed and before any
live analysis ran.

- [x] `<30` clusters OR zero-width → `INCONCLUSIVE BY RULE`, whatever the interval says
- [x] Cluster count printed beside every interval, always
- [x] Verified: one cluster and an all-agree 8-session set both report inconclusive; a real 40-session set reports a usable interval
- [x] `PREREGISTRATION.md` Amendment A1.1 (guard) and A1.2 (stopping rule: 30 sessions or 2026-10-20)
- [x] Amendment states its own honest cost — changing a stopping rule mid-study is a known bias route; the mitigations are that it is dated, pre-window, blind to the result, and moves the bar UP

---

## JEV-22: Complete the five-arm matrix on the existing 60 synthetic items

**Status:** ready-for-agent
**Labels:** science
**Blocked by:** None

**SCOPE CUT 2026-09-20, by the owner: 60 items, not 360.** Grilling Q15 chose
the full 360-item run. That decision was taken when there were four arms; Q8
made it five, which turned it into 1,440 subscription calls and 4.1 hours
serial, competing for the same quota as the routing A/B in the same week. The
owner cut it to 60.

**What this leaves to do — and it is not nothing.** `cc_sonnet5` and
`cc_fable51` have **never run, on anything**. Verified against `data/runs/`:
every existing row is `jev`, `cc_opus5` or `cc_haiku45`. The two arms added by
Q8 exist only in `config/arms.json`. So the work is to fill the gap and complete
a clean 5 x 60 matrix on the items already run.

| | |
|---|---|
| items | the existing 60 synthetic, unchanged — same `state_sha256`, so the new arms are directly paired with the old |
| new calls | **120** (60 x 2 arms) |
| wall clock | ~20 minutes serial |
| metered spend | $0 — subscription |

**What this ticket no longer delivers, stated plainly.** The threshold-overfit
question does **not** close. The optimism gap stays at **0.097 at n=59**; it
would have fallen to ~0.020 at n=300. That gap becomes a **stated limitation in
the writeup**, not a resolved question, and JEV-17's rule-based operating point
has to carry the weight instead — which is what it was designed for. The 300
unrun synthetic items remain on disk and the run remains available later at the
same cost; nothing is discarded, only deferred.

- [ ] Run the 60 existing synthetic items through `cc_sonnet5` and `cc_fable51` only
- [ ] Assert `state_sha256` matches the existing rows item-for-item — the pairing is the whole value of reusing these 60
- [ ] Report the five-arm discrimination table (AUC per arm) as the synthetic section
- [ ] **Publish no Fable cost figure** — its rates are unreconciled and its 2.5% cache-read multiplier contradicts the 10% verified for three other models. Latency and agreement are reportable; cost is not
- [ ] Record the optimism gap of 0.097 as an explicit limitation wherever a threshold is quoted

---

## JEV-23: Routing A/B — per delegated task

**Status:** blocked
**Labels:** science, hooks
**Blocked by:** JEV-24a (the pre-rule baseline is destroyed the moment this
starts), **JEV-27** (the power-derived stopping rule), **JEV-28** (Fable pricing
— it is now a component of the primary outcome), and **JEV-29** (the grader).

**What to build:** The article's central experiment, per SPEC "The routing
experiment". Per-turn routing is impossible (no hook sets a model, no
per-request override exists), so the unit is the **delegated task**.

**Design settled 2026-09-20** (`PREREGISTRATION.md` §A2.0): randomise **per
delegation**; control is **the current default** (`inherit` = Opus on every
task); primary outcome is **raw net cost**; quality is a **blinded grader**;
runs **concurrently** with the `pre_bash` window.

- [ ] Coin flip per `Agent` spawn; record the assignment on the capture
- [ ] Blinded grader per task: stripped output, randomised order, fixed rubric, double-graded sample, and the blind-integrity check (grader guesses the tier; above chance = compromised)
- [ ] Report **agreement between Jev's assignment and a static `subagent_type -> tier` rule** — if Jev agrees with two lines of `if`, the classifier is adding nothing and that is the headline caveat
- [ ] **The mechanism is now known and verified**: a `PreToolUse` hook matched on the `Agent` tool returns `permissionDecision: "allow"` plus `updatedInput` with `tool_input.model` rewritten. Jev is genuinely in the loop, not counterfactual
- [ ] Echo `prompt`, `description` and `subagent_type` back unchanged — `updatedInput` replaces the **entire** input object, and a dropped field would look like a routing effect
- [ ] **Assert the assignment took effect**: `PostToolUse` on `Agent` returns `resolvedModel`; it must equal the assigned tier per task, or the treatment arm is silently the control arm. An `availableModels` allowlist or `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` can override the hook
- [ ] **Outcomes do NOT come from `PostToolUse`.** Subagents run in the background by default since v2.1.198, and an `async_launched` response carries `resolvedModel` but no usage fields. The verification assertion works; the cost and timing measurement must come from the subagent transcript under `<session>/subagents/` or a `SubagentStop` hook
- [ ] **Fail open, and measure the cost of not failing**: this hook is synchronous on the critical path of every subagent spawn, the one place in the study where a Jev call is not free. Measure the added spawn latency in the A/B rather than assuming the ~624ms/48s ratio holds
- [ ] Build `questions/agent_route/v1.json` and the `agent_route` state builder (payload-only: `prompt` + `subagent_type`)
- [ ] Apply the `JEV_ARM_SUBPROCESS` recursion guard — the `cc_*` arms spawn `claude -p` in this repo, and an unguarded routing hook would rewrite the model of the study's own measurement subprocesses
- [ ] **Decide the control arm before anything runs** (`PREREGISTRATION.md` A2.0.3): the current default is `inherit`, i.e. Opus on every task, which is a strawman. The competitor that matters is a two-line static `subagent_type -> tier` rule with no classifier in it
- [ ] Randomise assignment per delegation; record `routing_arm` and `routing_context` on every capture including `pre_bash`
- [ ] Primary outcome: **net cost including rework** — an escalated task charged at full cost plus the wasted one
- [ ] Escalation logged **prospectively at the moment of re-delegation**, with the `decision_id` it replaces — never reconstructed afterwards by prompt matching
- [ ] Quality composite: friction proxies (interruptions, `is_error`, permission denials) + escalation rate
- [ ] Aggressive thresholds justified by the 37.5–44.4% break-even, with the break-even arithmetic restated in the pre-registration

**Note on the pre-registration file.** Earlier tickets referred to
`PREREGISTRATION-ROUTING.md` and `PREREGISTRATION-SURFACES.md`. There is **one**
pre-registration file, `PREREGISTRATION.md`, extended by dated amendments. Three
files would mean three places to check whether a commitment was made before or
after the data.

---

## JEV-24a: Pre-rule delegation baseline — **measure this first or lose it**

**Status:** ready-for-agent
**Labels:** science, blocking
**Blocked by:** None (can start immediately — and must, before JEV-23 or JEV-24b)

**What to build:** The fraction of spend that was delegated to subagents
**before** the "delegate where possible" rule is adopted, computed from the
existing transcripts.

This was previously a checkbox inside JEV-24, which was itself blocked by
JEV-23 — an ordering inversion that would have destroyed the measurement. The
moment the rule takes effect, or the A/B starts, the pre-rule baseline is
unrecoverable. It is split out here as its own ticket precisely so that it
cannot be scheduled after the thing that erases it.

- [ ] **Cut the corpus at a fixed timestamp: the moment Q17b was answered, 2026-09-20.** Sessions after that point are already post-rule. "The existing corpus" is not a definition — this session has used subagents heavily since the rule was adopted, so an uncut corpus silently includes the behaviour the baseline is supposed to precede
- [ ] Compute pre-rule delegation rate by task count and by spend, over the corpus up to that cut
- [ ] Freeze the result into `data/fixtures/` as a derived number with the transcript window recorded
- [ ] Report it in the writeup as the external-validity anchor for the confound

---

## JEV-24b: "Delegate where possible" working rule — and its confound

**Status:** blocked
**Labels:** science
**Blocked by:** JEV-24a

**What to build:** A standing rule that work is delegated to subagents where
practical, raising the share of spend that is routable at all.

- [ ] Adopt the rule; measure the delegation rate after
- [ ] **Disclose the confound in the writeup**: the workload was deliberately reshaped to make more of it routable, which raises experimental power and lowers external validity at the same time. Report what fraction of spend was delegable before the change

---

## JEV-25: `verbosity` question — the second routing dimension

**Status:** blocked
**Labels:** questions, science
**Blocked by:** JEV-18

**What to build:** Fable is cheaper than Opus only on cache-heavy **terse**
turns — below ~300 output tokens at 30k cache read, ~1,000 at 100k, ~3,000 at
300k. A one-dimensional complexity score cannot express that.

- [ ] Add `verbosity` to **`questions/agent_route/v1.json`** — the routing state is the *delegated task's* prompt, not the user's. It was previously specified against `questions/user_prompt/v2.json`, which is the shadow counterfactual surface, not the one that routes
- [ ] Two-dimensional routing policy: complexity picks the capability tier, verbosity picks between same-tier models with different cost shapes
- [ ] Validate against the realised-output-token label — free, derived from the turn that followed
- [ ] **Do not publish any Fable cost figure** until one real Fable session is reconciled against `cost-state`; its 2.5% cache multiplier contradicts the 10% verified for three other models

---

## JEV-28: Reconcile Fable pricing — it is now inside the primary outcome

**Status:** ready-for-agent
**Labels:** science, blocking, cost
**Blocked by:** None — and it blocks JEV-23

**What to build:** Fable is in the routing choice set, and the A/B's primary
outcome is **net cost in USD**. So an unverified Fable rate is a wrong headline,
not a footnote. Its rates come from documentation and its 2.5% cache-read
multiplier contradicts the 10% verified empirically for three other models.

This stopped being a disclosure and became a blocker the moment Fable became
routable.

- [ ] Run one real Fable session and reconcile the computed cost against its `cost-state.totalCostUSD`, to the same tolerance as the other three models
- [ ] Publish the delta % as a methodological check, as was done for Haiku and Sonnet
- [ ] **If it cannot be reconciled, remove Fable from the choice set** and revise Amendment 3 before collection, not after
- [ ] Note the convenient overlap: the blinded grader runs on Fable, so JEV-29 produces a real Fable session anyway

---

## JEV-29: The blinded grader — build it, freeze it, prove the blind holds

**Status:** ready-for-agent
**Labels:** science, blocking
**Blocked by:** None — and it blocks JEV-23

**What to build:** The primary quality measure for the routing A/B, specified in
`PREREGISTRATION.md` A3.3. It runs on `claude-fable-5-1`, out of band, after
collection closes.

The rubric is four dimensions (completeness, correctness, evidence, efficiency),
each 1-5, unweighted mean. All of it frozen before any grading runs — criteria
chosen after results are visible are not evidence.

- [ ] Write the rubric with anchor descriptions for every 1-5 point, and freeze it at a commit quoted in the writeup
- [ ] Strip `resolvedModel`, `modelsUsed` and tier-identifying text from graded material; randomise task order; do not disclose the arm ratio
- [ ] Add the `JEV_GRADER` structural guard to the routing hook so grader delegations cannot enter the A/B
- [ ] Grade in **one batch**, never incrementally
- [ ] 10% double-graded sample; report quadratic-weighted kappa between passes
- [ ] **Blind-integrity check**: ask the grader to name the tier on a held-out subset. Above chance = the blind failed, and the measure is reported as compromised
- [ ] **Self-preference check**: Fable is both grader and routable tier. Report the score distribution by tier; systematic favour toward Fable-run tasks alongside a failed blind check means the verdict is not used

---

## JEV-30: The worker reads config once, and nothing says so

**Status:** ready-for-agent
**Labels:** defect, science, blocking
**Blocked by:** None

**What happened, on live data.** The running worker started at **15:49:55**.
`config/arms.json` gained `cc_sonnet5` to its `enabled` list at **15:55:26** —
six minutes later. The worker loads config once at startup and has been running
on the stale three-arm set ever since, so **every row collected in that window
silently omits `cc_sonnet5`**. Nothing warned, nothing failed, and the omission
is invisible in the data: the rows look complete because `arm_order` records the
three arms the process knew about.

This is the same shape as the `question_set` field that looks like configuration
and is inert (JEV-31): a config change that appears to take effect and does not.

**The data consequence has to be recorded, not just fixed.** The collection
window now contains a configuration boundary. Rows before a restart carry a
different arm set from rows after it, and the analysis must condition on that or
report it.

- [ ] Log the resolved arm set, config version and config file mtime at worker startup — the operator should be able to see what the process actually loaded
- [ ] Fail loudly, or at minimum warn on every drain cycle, if a config file's mtime is newer than the process start time
- [ ] Record the configuration boundary in the collection log: which rows were collected under which arm set
- [ ] Decide and document whether a mid-window config change requires a restart, a new `arms_config_version` on every row, or is forbidden outright during a collection window

---

## JEV-27: Power analysis for the routing A/B stopping rule

**Status:** ready-for-agent
**Labels:** science, blocking
**Blocked by:** None — and it blocks JEV-23

**What to build:** The one piece of `PREREGISTRATION.md` Amendment 2 that is
still unratified. A2.4's "60 delegated tasks" was chosen by eye, and a stopping
rule chosen by eye is not a stopping rule.

The derivation is specified in A2.4 so it cannot be tuned after the fact.

- [ ] Estimate the per-delegated-task cost distribution by tier from existing subagent transcripts under `<session>/subagents/`
- [ ] Take the minimum effect worth detecting from the break-even arithmetic already in the spec (37.5-44.4%)
- [ ] Report N at 80% power, **clustered on session** — per-delegation randomisation within a session does not make the tasks independent
- [ ] Commit the result as **Amendment 4**, which ratifies Amendments 2 and 3 in full
- [ ] **If the required N exceeds what the window can produce, that is the finding.** The A/B runs anyway as a descriptive exercise and no inferential claim is made from it

---

## JEV-26: Correct the refuted mechanism claim in FINDINGS.md

**Status:** ready-for-agent
**Labels:** science, publication, blocking
**Blocked by:** None

**What to build:** `FINDINGS.md` Part 5c states that Claude Code cannot route at
all — that no hook accepts a `model` field and the harness has nowhere to put a
routing decision. **Half of that is now refuted against primary source**: a
`PreToolUse` hook on the `Agent` tool can rewrite `tool_input.model` through
`updatedInput`, so Jev can route delegated tasks on live traffic.

This is publication raw material with a false claim in it, and the claim is
load-bearing — it is the reason the thesis was narrowed. Correcting it is
blocking on any writeup.

- [ ] Rewrite Part 5c: per-**turn** routing is impossible (session-scoped switches only; `PreModelSwitch` cannot redirect); per-**task** routing is available via `PreToolUse` on `Agent`
- [ ] Record the correction as a dated finding rather than a silent edit — being wrong about the mechanism, and finding out by checking, is itself the most useful thing in the section
- [ ] Re-check every other document that repeats the claim (`SPEC.md` is done; `docs/PLAN-SURFACES.md` §0 is not)
- [ ] Cite the source: `code.claude.com/docs/en/hooks.md`, Claude Code v2.1.278, verified 2026-09-20

---

## Deferred: Phase 2

Not ticketed. Opens on explicit go-ahead: transcript harvest, blind labelling UI,
gold labels, Brier with Murphy decomposition, ECE, RPS, decision-curve analysis,
and the writeup.
