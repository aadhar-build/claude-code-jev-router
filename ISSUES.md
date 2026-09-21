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

## Execution plan

**Restructured 2026-09-20 on a new constraint from the operator: the system is
dev-complete before ANY part of it goes live.** The previous eight-wave plan
interleaved building and collecting — JEV-35 turned the routing hook into an
actuator in wave 5 while waves 6-8 were still building surfaces. That is now
explicitly out.

**Collection is STOPPED as of 2026-09-20T21:42Z.** `.jev-disabled` engaged,
worker (pid 94441) terminated, spool empty in all four directories, hook
verified to exit 0 without capturing. Standing totals at the freeze: **571
captures, 2,005 run rows**. Nothing restarts until the activation gate below.

### The shape

```
  PHASE A  (dev, offline)        build everything, register nothing,
                                 call nothing. 5 waves.
        |
  GATE   (JEV-52)                one deliberate act: full suite, reversibility
                                 proof, canary baseline, THEN enable.
        |
  PHASE B  (live)                collect and analyse. 3 waves.
```

The gate exists because the failure mode we keep hitting is *partial* live
state: a hook registered while another is half-built, a config field that looks
live and is inert (JEV-31b), a kill switch that stops one writer and not the
other (JEV-51). Every one of those was cheap to find offline and expensive to
find live.

### Standing rules (unchanged except where noted)

- `src/stats.py`, `src/analyze.py` and `questions/*/v1.json` are **frozen**
  (`PREREGISTRATION.md` §8). A change is a defect fix, its own commit, reason
  stated, pre-/post-fix numbers reported.
- **Two agents must never own the same file.** Most serialisation below is
  this, not a real dependency; where that is the only reason, it says so.
- **Only one ticket per wave may write to `data/runs/`** — amended: rows with a
  non-`live` `run_context` (canary, synthetic, replay) are exempt, since
  `canary.py` is a standing writer by design and the rule as originally written
  could not survive JEV-37.
- **NEW — no ticket in Phase A may register a hook, enable a surface, start the
  worker, or remove `.jev-disabled`.** Building the actuator is Phase A;
  arming it is the gate. An agent that believes it needs live data to finish is
  wrong or the ticket is mis-scoped — say so rather than turning something on.
- **One new surface registration per collection window** still holds, and now
  applies inside Phase B only.

### Phase A — dev, offline, at most four agents at a time

**Waves renumbered 2026-09-21** so the table is topologically valid. The previous
numbering placed three tickets in waves that ran *before* their own blockers, and
left two tickets in no wave at all. Every move is listed in "The 2026-09-21
reconciliation" below. A1 and A2 are unchanged, because they have already run.

| wave | tickets | why these together |
|---|---|---|
| **A1** | **51**, **30 + 31** (one agent), **31b**, **44** | The shutdown/config-staleness cluster. 51 first because until it lands "stopped" is four manual steps and a belief. 30+31 share an agent (same drain loop); 31b is the same class of defect in five more fields. 44 pins the interpreter |
| **A2** | **49**, **16** (run A only, 90 calls), **32**, **43** | The measurement instruments, before anything depends on their numbers. 49 corrects the cost pipeline **before** JEV-27 sizes a study on its output. 16 is a replay writer (`run_context: replay`). 43 resolves the contaminated wall-clock that 33 and 41 already quote |
| **A3** | **34**, **29**, **17**, **28** | **Moved ahead of the science-design wave, because 34 is the head of the longest chain**: 46, 47, 25 and 35 all wait on it, and in the old numbering they sat in a wave that ran first. 34 builds `agent_route` **in shadow, deciding nothing** — buildable offline against replayed states. 29 builds and freezes the blinded grader. 17 replaces fitted thresholds with a rule. 28 reconciles Fable pricing, now inside a primary outcome |
| **A4** | **55**, **46**, **47**, **25** | The science design, downstream of a corrected cost distribution (49), a known flip rate (16) and the surface (34). **55 leads the wave**: until the clustering unit is decided the primary interval cannot be computed from any amount of data, and 27 cannot be sized. 46 replaces the rejected static-heuristic arm; 47 makes both routing arms delegate identically; 25 adds the second routing dimension |
| **A5** | **27**, **35**, **50** | 27 sizes a **three**-arm study on **clusters, not rows** — which is why it follows both 46 and 55. 35 writes the actuator **and its two gates** but does not arm it. 50 is the writeup correction and touches no code |
| **A6** | **36**, **39**, **37** | 36 writes outcome measurement against fixtures, and needs 35's actuator to exist. 39 reads rows already on disk. 37 builds the canary scheduler and wrapper so JEV-52 step 5 has something to run |
| **A7** | **48**, **45**, **56** | The last three, and the gate's remaining prerequisites. 48 asks whether we are measuring tier fit or task difficulty, and needs 36's outcome measurement. 45 records the endpoint limitation and checks whether Cloudflare access is open. 56 makes the gate's own step 1 satisfiable |

**Spend decision (operator, 2026-09-20): minimise API spend, keep the analysis.**
Offline replay is permitted in Phase A but is cut to the minimum that still
exercises the analysis path against real arm responses:

| ticket | as planned | **cut to** | rationale |
|---|---|---|---|
| **JEV-16** | 1,390 calls (~$0.018 + ~190 subscription) | **run A only — 90 calls** | Run A is the only one unblocking a ruling that is live today: A7.5's verdict on the 334 live v1 rows. Runs B (1,200 calls, Jev N=20 over all 60) and C (100, Opus reference wobble) **defer to Phase B**, where they cost the same and block nothing |
| **JEV-22** | 5 arms x 60 items = 300 calls | **defer to B1** | Nothing in Phase A reads its output. Its only Phase-A value was producing a Fable session for JEV-28, which JEV-28 can generate itself at a fraction of the cost |
| **JEV-10** | 3 sweeps x 60 items x N | **defer to B1** | Phrasing, option-order and truncation sweeps inform the writeup, not the build |
| **JEV-32, 39, 12, 49** | — | **unchanged, zero new calls** | All four read the **2,005 rows already on disk**. This is the analysis validation, and it is free |

**Phase A therefore costs ~90 API calls total.** The analysis path is still
exercised end to end on real responses, because the 2,005 existing rows are real
responses. What is deferred is *additional* sweeps, not *any* validation.

### The gate — JEV-52 (to be written)

A single ticket, done by one agent, no parallelism:

1. Full test suite green, run from the sandbox (JEV-42's guarantee).
2. `tests/reversibility.sh` green — OFF provably means vanilla (JEV-40).
3. JEV-51's proof: switch engaged + non-empty spool ⇒ zero API calls.
4. A canary baseline sweep recorded **before** the window opens, so drift has a
   reference (JEV-37).
5. Pre-registration amended and committed with its hash: three routing arms,
   the auth path, the Jev endpoint limitation (JEV-45), the corrected loss bound,
   **and the clustering unit JEV-55 decides** — without which the amendment
   cannot state what the primary interval is.
6. Only then: remove `.jev-disabled`, start the worker, register the first
   surface.

Step 1's "from a clean checkout" is **currently impossible** and JEV-56 exists to
resolve it: `tests/reversibility.sh` needs `.claude/settings.local.json`, which
is gitignored by design, so four of its gates fail on any fresh clone.

### Phase B — live

| wave | tickets | why |
|---|---|---|
| **B1** | **09**, **22**, **10**, **16** (runs B+C), **54** | Alone. The inline shadow hook is the window's first live registration, and the one-registration-per-window rule makes it a wave by itself. **54 joins this wave**: it is a replay sweep like 22, 10 and 16 B+C, it needs the same `replay.py` and the same spend, and the Phase A cut deferred every *additional* sweep for exactly this reason |
| **B2** | **23**, **18**, **24b** | The routing A/B itself. 18 is the next surface in the queue. 24b adopts the working rule whose baseline 24a already froze |
| **B3** | **19**, **20** | The last two surfaces |
| **B4** | **12**, **53** | **12 joins the writeup wave**, and strictly before 53. It draws its figures from JEV-10's sweeps, and 10 is in B1 — so 12 could never have run in Phase A, whatever the old table said. 53 depends on everything and owns no code |

### What moved, and why

- **JEV-38 and JEV-24a are already done** (wave 1) — which is fortunate, because
  they were the only genuinely time-sensitive items on the board: their source
  lives in `~/.claude/projects/` under a retention policy we do not control.
  Nothing else on the board can be lost by waiting.
- **JEV-35 moved from wave 5 to A5, and no longer arms anything.** It was the
  ticket that used to cross the dev/live line invisibly.
- **JEV-09, 18, 19, 20 all moved into Phase B**, because each one is a live
  registration and Phase A forbids those.
- **JEV-49 moved ahead of JEV-27.** Sizing a study on a cost distribution that
  is wrong in three known ways is worse than sizing it late.
- **JEV-46 was added and inserted before JEV-27**, because a three-arm study
  needs a different N than a two-arm one.
- **JEV-51 is now the first ticket on the board.** Until it lands, "the
  experiment is stopped" is a claim that took four manual steps to make true and
  cannot be re-asserted by a script.

### The 2026-09-21 reconciliation

A board audit found **five inconsistencies between the wave table and the
tickets' own `Blocked by:` lines**, plus two tickets in no wave at all. The wave
table was wrong in every case and the `Blocked by:` lines were right, so the
table moved. Recorded here rather than silently corrected, because a plan that
changes without saying so is how JEV-32's era boundary happened.

1. **A3 could not run in its old slot.** It held 27, 46, 47 and 48. But 46 and
   47 are `Blocked by: JEV-34`, which sat in A4 — *after* them — and 48 is
   `Blocked by: JEV-36`, which sat in A5. Only 27 was genuinely downstream of
   A2. **Fix:** 34's wave moved up to A3; 46 and 47 moved to A4 behind it; 48
   moved to A7 behind 36. The old A3 was not a wave, it was three tickets
   waiting on work scheduled after them.
2. **JEV-12 was in A6 and blocked by JEV-10, which the spend cut had already
   deferred to B1.** Both could not hold: a Phase A wave cannot depend on a
   Phase B ticket. **Fix:** 12 moved to B4, immediately before 53.
3. **The A6 row's prose was stale.** It read *"all four are offline… 22 and 10
   replay the existing 60 synthetic items"* while the wave listed only 39 and
   12 — text left over from before the spend cut removed 22 and 10. **Fix:**
   rewritten to describe the tickets actually in the wave.
4. **JEV-54 and JEV-55 were in no wave.** 55 states that it gates 27, 52 and the
   primary metric itself, yet appeared nowhere in the plan and nowhere in 52's
   blocker list — the single most load-bearing open ticket on the board was
   invisible to anyone reading the plan alone. **Fix:** 55 now *leads* A4, ahead
   of 27. 54 moved to B1 with the other deferred replay sweeps.
5. **JEV-52's `Blocked by:` line stopped at A5 tickets.** It omitted 37, 39, 45,
   12, 54 and 55 — including **37, which the gate's own step 5 depends on** for
   the canary baseline, and **55, without which step 6's amendment cannot state
   what the primary interval even is.** **Fix:** the line is now generated from
   the wave table and says so.

**One new defect was found during the audit and is filed as JEV-56**: the gate's
step 1 requires the suite green *from a clean checkout*, and
`tests/reversibility.sh` cannot be green on one — four of its gates need
`.claude/settings.local.json`, which is gitignored by design.

### What the plan still deliberately does not parallelise

**34 → 35 → 36 → 23 remains strictly serial**, now across A3 → A5 → A6 → B2.
The 2026-09-21 renumbering spread it across four waves instead of three, which
lengthens the path and is the correct trade: 35 and 36 were sharing a wave while
36 depends on 35, so the "wave" was never runnable in parallel anyway.
It is the longest path and the obvious candidate for compression, and it should
not be compressed: the split exists to put a verifiable checkpoint between "the
classifier decides" and "the decision changes what runs". The dev/live gate now
adds a second checkpoint in the same chain, which is the point.

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
- [x] Findings recorded in `FINDINGS.md` Appendix A with the date and the response model string

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
- [x] Findings written up in `FINDINGS.md` Appendix B
- [ ] **NOT DONE, and the ticket said it was.** "It starts collecting on day 0" never happened. `session_metrics.py` is a *viewer*: it reads a transcript on demand and prints. Nothing accumulates. There is no `data/baseline/`, and `--freeze` writes to `data/fixtures/` as a **test regression fixture**, not as a growing record. Split out as **JEV-38**, which is urgent for a reason this ticket did not state: the source transcripts live in `~/.claude/projects/`, outside this folder, under retention we do not control

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

**Status:** blocked
**Labels:** hooks, hot-path
**Blocked by:** **JEV-52** (the activation gate — this registers a hook, so it cannot happen in Phase A). **Two decisions are also still open** and must be settled during Phase A rather than at the gate: whether to register the inline hook live alongside `capture.sh`, and what `--max-time` should be given the 2.0s default sits BELOW Jev's 2,681ms p99

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

**Status:** ready-for-agent
**Labels:** science
**Blocked by:** None. The sweeps needed credentials and now have them. **JEV-16 is the determinism sweep split out** because it gates enforcement; the other three sweeps (phrasing, option-order, truncation) stay here

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

**Status:** done
**Labels:** metrics, science
**Blocked by:** JEV-08

**What to build:** Two small instruments: what enforcement would actually cost in
latency, and whether the vendor changed the model underneath you mid-collection.

- [x] `bench_inline.py` invokes the real hook N=200 times over recorded states and reports end-to-end wall-clock including process spawn
- [x] Reported as projected enforce overhead, clearly separated from API latency
- [x] `canary.py` evaluates 21 fixed states (7 per stratum, frozen to `data/fixtures/canary-set-v1.json` as `canary-set-v1:2f4a6f6a9ea1`) and records `response_model` and answers under `run_context: "canary"`
- [x] A drift report flags any change in answers or model string across the collection window — `response_model` change, mean `|delta|` over threshold, or a decision flip at tau. Exit codes 0 clean / 1 drift / 2 no reference / 3 incomplete, so a cron wrapper cannot read "nothing to compare" as "nothing wrong"

Baselined 2026-09-20 on `jev`: reference sweep `01M2ZB4HDS8NTJZ3CX0P9FGNJX`. A sweep is 21 calls,
~$0.0006, ~11s. **Open limitation**: the gateway reports only `typesafe-ai/jev` with no version
field anywhere in `providerMetadata`, so the model-string check catches a rename and not a silent
retrain. The probability deltas are the only signal for the latter.

---

## JEV-12: Figures and publishable export

**Status:** blocked
**Labels:** analysis, security
**Blocked by:** JEV-10 (the sweeps it draws figures from). JEV-05 is done.
**Moved to wave B4 on 2026-09-21**: it was listed in Phase A wave A6 while JEV-10
had already been deferred to B1, so it was scheduled ahead of its own blocker.
It now sits in B4, immediately before JEV-53, which consumes its figures.

**Prior-art amendment (2026-09-20).** Add **decision-curve / net-benefit
analysis**. The sweep found **nothing** applying it to LLM routing, gating,
cascades or abstention, in any vocabulary — it is the clearest unclaimed
contribution on the board. The mapping is exact: *treat none* = all-cheap,
*treat all* = our all-Opus control, threshold probability p_t = (Opus cost -
cheap cost) / (cost of a cheap-tier failure). It answers the question accuracy
and AUC cannot: **does the classifier beat BOTH trivial policies?**
Origin: Vickers & Elkin, *Medical Decision Making* 26(6), 2006; CIs at
`doi.org/10.1186/s41512-023-00148-y`. scikit-learn has an open, unimplemented
issue for net-benefit curves (#22136), so this is hand-rolled.
**State the assumption honestly:** clinical net benefit fixes the harm of a
false positive as a constant multiple of a true positive's benefit, whereas our
under-routing harm is a failed subtask whose cost is itself stochastic.
Also: reliability diagrams use **equal-mass quantile bins, not equal-width** —
routing probabilities pile up near 0 and 1, and equal-width bins will be empty
in the middle and overloaded at the ends.

**What to build:** The artifact you would actually publish, with the redaction
step that makes publishing safe.

- [ ] Latency CDFs, sharpness histograms, pseudo-reliability curves whose axis reads "P(Opus agrees)"
- [ ] Per-bin counts shown on every reliability diagram
- [ ] Export-time scrubber with a recorded `redaction_version`
- [ ] `data/states/` excluded from the exported artifact by default
- [ ] The exported bundle contains the pre-registration hash and the collection window

---

## JEV-13: Remaining three surfaces — **SUPERSEDED**

**Status:** done
**Labels:** hooks, superseded
**Blocked by:** —

**Superseded 2026-09-20 by JEV-18, JEV-19 and JEV-20**, which stage the three
surfaces individually with the priority order reversed — routing first, because
Part 4c established that gating is additive on every axis. This ticket bundled
all three, which is not a vertical slice and could never be verified as a whole.

Its one piece of irreplaceable content — the `stop` capture blocker discovered
during JEV-03 — **has been migrated into JEV-19** rather than lost with the
ticket. Nothing else here is unique.

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

**Status:** done
**Labels:** verification, blocking, science
**Blocked by:** None (can start immediately). **Start it early anyway**: its last item parameterises the three existing gates on surface, which JEV-19, JEV-20 and JEV-34 all need before they can gate anything.

**What to build:** A gate proving decision #7 actually holds. `tests/gates.sh`
has 21 assertions covering isolation, fail-open and the kill switch, and **zero
covering future-leakage** — the study's most load-bearing methodological claim,
asserted in `PLAN.md`, `SPEC.md` and `FINDINGS.md` and verified nowhere.

This applies to the already-live `pre_bash` surface. It should not wait for `stop`.

- [x] Fixture transcript; fire the hook; record `state_sha256_expected`
- [x] Append 20 more lines to the transcript; drain; assert the hash is UNCHANGED
- [x] Negative control: strip the offset, assert the capture is QUARANTINED not processed
- [x] Offline, `FakeArm` only, no network, no spend
- [x] Parameterise the three existing gates on surface — they are hardcoded to `pre_bash`

**Done 2026-09-20.** `./tests/gates.sh [surface]`, default `pre_bash`. **38
assertions on `pre_bash`** (was 21), of which **16 are GATE 4**: 6 on the surface
under test, 6 on `stop`, 3 on the negative control and 1 asserting the gate did
not touch the live window. On `stop` itself the run is 32/10 — the same GATE 4
minus the surface's own 6, which `stop` already contributes. `tests/gate4_drain.py`
is the drain step: it repoints every writable path in `paths` at a sandbox,
drains through the **real** `worker.drain_once()` with `FakeArm` only, and
reports what happened as JSON.

**The gate has teeth, and proves it on every run.** `--mutate` wraps every entry
of `state_builders.BUILDERS` in the exact decision-#7 violation — read
`transcript_path` live, at worker time — and the gate asserts the hash it calls
stable DOES move and that the leaked state DOES carry the later turns. A
leakage test that cannot fail proves nothing, so the demonstration is part of the
suite rather than a one-off. Verified additionally against two deliberately
broken copies of the real source: a `build_pre_bash` that reads the transcript
(2 failures), and a `build_stop` whose missing-offset refusal is replaced by a
whole-file read (negative control, 2 failures).

**`stop` is always exercised, whatever surface is passed.** On a payload-only
surface the leakage assertion is true by construction; a gate that only ever
tests the easy case is not a gate. GATE 4 **fails loudly** on a surface with no
state builder (`agent_route` today) rather than skipping.

**The gates no longer run against the live spool.** They used to
`rm -f spool/ready/*.json` between assertions, `chmod 500` the live `spool/tmp`,
move `spool/ready` and `logs/` aside, and write 501 filler files into the path a
running worker drains — silent destruction of live captures, which is JEV-31/33's
failure shape (a loss with no run row, no capture row and therefore no entry in
the attrition count). Every hook invocation now runs with `CLAUDE_PROJECT_DIR`
pointed at a throwaway root under `logs/`, and the last assertion greps the real
`spool/` and `data/captures/` for the gate's own session id.

**Three contradictions found, none fixed here.** (1) `docs/PLAN.md` decision #7
says the spooler records `stat -f %z` as `transcript_bytes_at_capture` — it does
not, and cannot: `capture.sh` parses no JSON. GATE 4 injects the offset the hook
is unable to produce. That is JEV-19's blocker seen from the gate's side, and it
means the `stop` leakage path is verified but **not reachable in production**.
(2) `surfaces.json` → `state_source` is inert (JEV-31b) while `state_source` on
every row comes from `state_builders.STATE_SOURCE`; GATE 4 asserts the row's
value, i.e. the live one. (3) `paths.SURFACES` lists four surfaces, `CONTEXT.md`
lists five — `agent_route` exists in the glossary and nowhere in code.

**`tests/run_all.sh` does not call `gates.sh`** and was not changed (not this
ticket's file). Now that the gates are sandboxed they are safe to add.

---

## JEV-16: Determinism sweep — the enforcement blocker

**Status:** done (Run A). **Runs B and C deferred to Phase B / B1.**
**Labels:** science, blocking
**Blocked by:** None. Avoid running it at the same moment as another process writing `data/runs/` — see the execution plan.

**What to build:** The measurement that decides whether Jev can ever enforce.
`src/determinism.py` is written and correctly **exits non-zero** rather than
reporting a green result on absent data. `replay.py --determinism N` has never run.

**Scope cut by the operator, 2026-09-20: Run A only, 90 calls.** The checkboxes
below were written for a Jev-only N=20 sweep. They are annotated rather than
ticked as written, because the run that happened is not the run they describe:
Run A is **`cc_haiku45` at `cc-haiku45-cli-v2-nothink`, N=10 over nine paired
synthetic states**, chosen because it is the only sweep that unblocks a ruling
live today (A7.5's verdict on the 334 live v1 rows). The Jev sweep those
checkboxes describe is **Run B, deferred to B1**.

- [ ] ~~Run `replay.py --determinism 20 --arms jev` over a stratified sample~~ → **deferred to Phase B as Run B.** There is still **no determinism baseline for `jev`**, and nothing in Phase A needs one
- [x] **Run A executed**: `--determinism 10 --arms cc_haiku45 --context synthetic --ids <9>`, **90 calls, 0 attrition**, $0 metered. Selected and reported on `arm_config_id` carried by the row, never on `evaluated_at`
- [x] Report flip rate bucketed by |p − τ| — `reports/determinism-runA-2026-09-20.txt`. **The hypothesis is FALSIFIED on this arm's `needs_review`**: flips occur at |p − τ| ≥ 0.10 (τ=0.50) and ≥ 0.20 (τ=0.95), far from the threshold. On `destructive` there are **0 flips in 90 calls** at either τ
- [x] Resolve the 41%-occupancy concern: **it is a synthetic artefact.** At τ=0.95 on `needs_review`, 24/59 (41%) **synthetic** against **11/487 (2.3%) live**; at τ=0.36 on `destructive`, 3/59 synthetic against **0/487 live**. Across 487 live `jev` decisions `destructive` never once crossed τ=0.5 (max 0.16). **Both numbers are quoted together everywhere; neither is quoted alone**
- [x] Dead-zone verdict, **per question rather than per arm**: viable for `destructive` (no flips anywhere), **not viable for `needs_review` on `cc_haiku45`** — the wobble is not a boundary effect and no threshold removes it. This is JEV-17's input
- [x] Three defects fixed in the instrument first, red test before each (`tests/test_jev16.py`, 13 tests): `replay.py` did not stamp `config_fingerprint` (replay rows could not join live rows); `--determinism` could not select its items; `determinism.analyse()` pooled live with synthetic and omitted `arm_config_id` from the group key. A fourth instance of the last was found in the occupancy table and fixed
- [x] **A7.5 ruling written**: the 334 live v1 rows are **retained and usable for agreement**, on stronger grounds than A7.5 could state. 17 of 18 probe cells fall inside the v2 configuration's own 10-repeat range, and the cell that produced the whole 0.078 effect (0.85→0.02) spans [0.00, 0.85] **within one configuration**. **Amendment 8 is required** and is drafted, not applied — `reports/jev16-runA-2026-09-20.md` §6

**Artefacts:** `reports/jev16-runA-2026-09-20.md` (the ruling),
`reports/determinism-runA-2026-09-20.txt` (band tables),
`.scratch/a3-prep/jev16.md` (variance and repeat structure for JEV-27).

---

## JEV-17: Replace the fitted thresholds with a rule

**Status:** ready-for-agent — **unblocked 2026-09-21, with a stated limit**
**Labels:** science
**Blocked by:** ~~JEV-16~~ — **partially cleared.** JEV-16 Run A delivered the
flip-rate result this ticket waited on and says so in its own words: the
per-question dead-zone verdict "is JEV-17's input". The rule can be written now.

**The limit, and it must be carried into the rule's wording.** Run A measured
**`cc_haiku45` only**. There is still **no determinism baseline for `jev`** —
that is Run B, deferred to B1. So the dead-zone verdict currently reads: viable
for `destructive` (0 flips in 90 calls at either τ), not viable for
`needs_review` on `cc_haiku45` (flips at |p − τ| ≥ 0.10, so the wobble is not a
boundary effect and no threshold removes it). A rule written now is a rule
written on the reference arm's wobble, not on Jev's, and must say so rather than
implying the sweep covered both. Wave A3.

**Prior-art amendment (2026-09-20).** Two independent results say a single
fitted threshold will degenerate, and both should be cited in the rule's
rationale:
- **Threshold non-transfer.** Shafran et al., "Rerouting LLM Routers"
  (arXiv:2501.01818) §5: a Chatbot-Arena-calibrated threshold moved to MMLU and
  GSM8K routed **~98% of queries to the strong model** — the saving vanished
  while the router still looked like it worked.
- **Jev specifically.** ickma2311's pre-registered eval found that at exact
  accuracy parity with the frontier model, **Jev requires 100% escalation**; at
  1pp below parity it escalates 22%.
Therefore: choose on held-out data, **report the whole curve, never a point**,
and prefer RouteLLM's reporting metrics — **CPT(x%)** (minimum strong-model call
share to reach a target performance-gap-recovered) and **APGR** (average PGR
across cost constraints). The threshold is an operator knob to be swept, not a
parameter to be fitted once.

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
**Blocked by:** **JEV-52** (the activation gate), JEV-15

*(The old second blocker — "the mechanism work in `SPEC.md` *Surface plans* §0" —
is removed. That mechanism question was answered by JEV-26: per-turn routing is
impossible and per-task routing works. Nothing about `user_prompt` waits on it,
because `user_prompt` is payload-only and shadow-only and depends on no
mechanism at all.)*

**What to build:** Per `SPEC.md` *Surface plans* §2. Sequenced FIRST, reversing the
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
**Blocked by:** **JEV-52** (the activation gate), JEV-18

*The gate is operational, not technical: **register one new surface at a time.** Two new capture hooks landing in the same window makes the capture stream uninterpretable, because you cannot attribute a change in volume or base rate to either. Step 0's payload inspection does not depend on JEV-18 and can be done any time.*

**THE BLOCKER, migrated from JEV-13 when that ticket was superseded.** Found during JEV-03; resolve before building anything else here. `build_stop` requires `transcript_bytes_at_capture`, but `capture.sh` does no JSON parsing by design, so it cannot `stat` a path it never reads. Decision #7's mechanism has no implementation route as currently written. Two options: give `stop` its own hook line that extracts the path with a single `sed -n 's/.*"transcript_path":"\([^"]*\)".*/\1/p'` and calls `stat -f %z`, then re-time it against the 10ms budget; or find a different truncation marker. `build_stop` already refuses to run without the offset, so the leakage guard holds either way — the surface simply cannot be enabled until this is settled

**What to build:** Per `SPEC.md` *Surface plans* §1. **STEP 0 FIRST, before any
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
**Blocked by:** **JEV-52** (the activation gate), JEV-19

*Same one-surface-at-a-time rule as JEV-19.*

**What to build:** Per `SPEC.md` *Surface plans* §3.

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
**Blocked by:** None. **It incidentally produces the real Fable session JEV-28 needs** — if this runs first, JEV-28 should use its transcript rather than generating another

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
**Blocked by:** **JEV-52** (the activation gate), JEV-34 (the surface), JEV-35 (the actuator and its gates),
JEV-36 (outcome measurement), JEV-24a (the pre-rule baseline this destroys),
JEV-27 (the stopping rule), JEV-28 (Fable pricing, now inside a primary
outcome), JEV-29 (the grader), **JEV-46** (the third routing arm), **JEV-47**
(delegation-shape equality), **JEV-52** (the activation gate — this ticket needs live collection, which does not exist until the gate opens).

**Prior-art amendment (2026-09-20).** Three changes from `.scratch/prior-art.md`:
1. **A third routing arm, `random_matched` (JEV-46), is now required.** Two arms
   cannot separate "tiering helps" from "Jev helps", and five independent
   sources find the second effect is often zero. Add JEV-46 to Blocked by.
2. **The wall-clock co-primary is confirmed novel.** No paper reports wall-clock
   as a co-primary outcome for agentic routing — the sweep found none in any
   vocabulary. This vindicates A3.5 and should be stated as a contribution.
3. **Report the realised strong-model call rate PER TASK FAMILY, not just in
   aggregate.** "Rerouting LLM Routers" (arXiv:2501.01818 §5) found a
   transferred threshold sent ~98% of queries to the strong model while the
   router still appeared to work; ickma2311 found Jev needs 100% escalation at
   accuracy parity. An aggregate rate hides both.

**Rescoped 2026-09-20.** This ticket previously carried the whole of building
the `agent_route` surface *and* running the experiment on it. That is not a
vertical slice — it is three, and there was no point in the middle at which
anything could be verified before the hook began changing which model your work
ran on. The build is now JEV-34/35/36; **this ticket is the experiment only.**

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
- [ ] **Two co-primary outcomes**: raw net cost AND net wall-clock per delegated task, each with its own interval, both reported regardless of which looks better
- [ ] Charge the hook's own spawn latency to the treatment arm — measured in the A/B, not assumed from the enforce bench
- [ ] Record **task duration** and **blocking duration** separately. A subagent that runs in the background can get objectively faster while the human waits exactly as long; if the two diverge, that divergence is the finding
- [ ] Report the correlation between the two primaries — cheaper tiers are faster tiers, so this is largely one effect in two units
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

**Status:** done
**Labels:** science, blocking
**Blocked by:** None (can start immediately — and must, before JEV-23 or JEV-24b). **Do it in the same pass as JEV-38**: both read the same transcript corpus, both are destroyed by the same retention risk, and reading it twice is wasted work on data that may not survive.

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
**Blocked by:** **JEV-52** (the activation gate), JEV-24a

**What to build:** A standing rule that work is delegated to subagents where
practical, raising the share of spend that is routable at all.

- [ ] Adopt the rule; measure the delegation rate after
- [ ] **Disclose the confound in the writeup**: the workload was deliberately reshaped to make more of it routable, which raises experimental power and lowers external validity at the same time. Report what fraction of spend was delegable before the change

---

## JEV-25: `verbosity` question — the second routing dimension

**Status:** ready-for-agent — **unblocked 2026-09-21**, JEV-34 landed (`652d3e8`)
**Labels:** questions, science
**Blocked by:** ~~JEV-34~~ — cleared. Wave A4.

*(Was JEV-18. The `verbosity` question belongs to `questions/agent_route/v1.json`
— the surface that routes — not to `user_prompt`, which is a shadow
counterfactual. Re-pointed 2026-09-20.)*

**What to build:** Fable is cheaper than Opus only on cache-heavy **terse**
turns — below ~300 output tokens at 30k cache read, ~1,000 at 100k, ~3,000 at
300k. A one-dimensional complexity score cannot express that.

- [ ] Add `verbosity` to **`questions/agent_route/v1.json`** — the routing state is the *delegated task's* prompt, not the user's. It was previously specified against `questions/user_prompt/v2.json`, which is the shadow counterfactual surface, not the one that routes
- [ ] Two-dimensional routing policy: complexity picks the capability tier, verbosity picks between same-tier models with different cost shapes
- [ ] Validate against the realised-output-token label — free, derived from the turn that followed
- [ ] **Do not publish any Fable cost figure** until one real Fable session is reconciled against `cost-state`; its 2.5% cache multiplier contradicts the 10% verified for three other models

---

## JEV-26: Correct the refuted mechanism claim in FINDINGS.md

**Status:** done
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

- [x] Rewrite Part 5c: per-**turn** routing is impossible (session-scoped switches only; `PreModelSwitch` cannot redirect); per-**task** routing is available via `PreToolUse` on `Agent`
- [x] Record the correction as a dated finding rather than a silent edit — being wrong about the mechanism, and finding out by checking, is itself the most useful thing in the section
- [x] Re-check every other document that repeats the claim — `SPEC.md`, `SPEC.md` *Surface plans* §0/§2/§4 all corrected; a paraphrase sweep over every `.md` found no further hits
- [x] Cite the source: `code.claude.com/docs/en/hooks.md`, Claude Code v2.1.278, verified 2026-09-20

**Done 2026-09-20.** The correction is recorded as a dated finding rather than a
silent edit, and the superseded text is kept verbatim beside it. The finding
worth publishing is *how* the error happened: it was a category error, not a
misreading. `model` is not a hook output key — that reading was correct — it is
an `Agent` tool *input* key, and `updatedInput`, which the superseded text
itself lists among the available outputs a few lines above its own conclusion,
replaces the entire tool input. The evidence sat inside the section that drew
the wrong conclusion from it.

---

## JEV-27: Power analysis for the routing A/B stopping rule

**Status:** blocked
**Labels:** science, blocking
**Blocked by:** JEV-38, **JEV-49** (the cost pipeline it sizes against has three
known defects), **JEV-46** (a three-arm study needs a different N)

**Prior-art amendment (2026-09-20).** The power analysis must now size a
**three**-arm study (JEV-46), and two empirical results change how the budget
should be spent:
- **PointFive (arXiv:2607.12161) measured ICC 0.37-0.55 for cost repetitions:
  712 runs per arm bought only ~38-45 effective tasks.** Buy breadth, not reps.
  Target many distinct delegated tasks at ~3-5 reps each, paired across arms.
- **"How Do AI Agents Spend Your Money?" (arXiv:2604.22750) measured up to 30x
  run-to-run token variance on the same task.** Any N derived without that
  variance in the model is wrong.
Use task-level bootstrap and clustered SEs (Miller, arXiv:2411.00640). Also:
this ticket is now blocked on **JEV-49**, because sizing a study on a cost
distribution with three known defects in it is worse than sizing it late.

*A real data dependency, not sequencing: the power analysis needs the per-delegated-task cost distribution, which is exactly what JEV-38 persists. Doing it first means reading the transcript corpus once instead of twice.*

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

## JEV-28: Reconcile Fable pricing — it is now inside the primary outcome

**Status:** ready-for-agent
**Labels:** science, blocking, cost
**Blocked by:** None. Cheapest path is to let JEV-22 or JEV-29 produce the Fable session as a by-product rather than generating one for this alone.

**What to build:** Fable is in the routing choice set, and the A/B's primary
outcome is **net cost in USD**. So an unverified Fable rate is a wrong headline,
not a footnote. Its rates come from documentation and its 2.5% cache-read
multiplier contradicts the 10% verified empirically for three other models.

This stopped being a disclosure and became a blocker the moment Fable became
routable.

- [ ] Run one real Fable session and reconcile the computed cost against its `cost-state.totalCostUSD`, to the same tolerance as the other three models
- [ ] Publish the delta % as a methodological check, as was done for Haiku and Sonnet
- [ ] **If it cannot be reconciled, remove Fable from the choice set** and revise Amendment 3 before collection, not after
- [ ] Record a second reconciliation datapoint found by the canary: the gateway reports `marketCost` 0.000013692/call, i.e. $0.000575 for 42 calls, against $0.000592 computed from `pricing.json` — **+3.0%**. Small, but this project reconciles to the cent, so it belongs in `FINDINGS.md` Appendix B beside the other deltas
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

**Status:** in-review — config side done 2026-09-20, one box is the worker agent's
**Labels:** defect, science, blocking
**Blocked by:** None (JEV-33 is done)

*Originally serialised behind JEV-33 to avoid two agents editing the worker's
startup and drain path. The fix landed in `src/config_loader.py` instead and
touches no worker file; the one remaining box is a line for whoever owns
`src/worker.py`.*

**Scope was wider than the ticket said.** The ticket is written as if only
`arms.json` goes stale. `surfaces()`, `pricing()` and `question_set()` are all
`@functools.cache`d too, so a mid-window edit to a surface mode, the
backpressure cap or a price is equally stale until restart. Worse:
`pricing()["version"]` is stamped on every row, so an operator who edits a
**rate** without bumping the version string produces two processes stamping the
same `pricing-2026-09-20` over different numbers — and nothing in the data
distinguishes them.

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

- [ ] Log the resolved arm set, config version and config file mtime at worker startup — the operator should be able to see what the process actually loaded. **Handed to the worker-owning agent**: `src/config_loader.config_fingerprint()` supplies the value; the exact lines are in `.scratch/a2-prep/jev30-31b.md` §6
- [x] Fail loudly, or at minimum warn on every drain cycle, if a config file's mtime is newer than the process start time. **Done, and stronger than asked.** `cl.assert_config_fresh()` raises `ConfigStaleError` and is called by **every** config accessor, so the refusal fires on the first config touch of the next capture — before any arm is called and before any row is written. mtime is only the cheap pre-filter: the decision is on a content hash, so a `touch`, a checkout or a no-op re-save does not stop collection
- [x] **Boundary recorded.** The worker was restarted at **2026-09-20T12:07:24Z**. Rows before that timestamp carry a three-arm `arm_order` (`cc_opus5`, `cc_haiku45`, `jev`) and **no `cc_sonnet5`**; rows after carry four. Verified on the first post-restart row at 12:07:43Z. The analysis must condition on this or report it — the `pre_bash` primary metric is `jev` vs `cc_opus5`, both present on both sides, so the headline is unaffected
- [x] One stranded capture reaped from `spool/claimed/` before the restart (JEV-31), so the restart did not lose it
- [x] Decide and document whether a mid-window config change requires a restart, a new `arms_config_version` on every row, or is forbidden outright during a collection window. **Decided: it requires a restart, and the process refuses to continue until it gets one.** Reasoning is in the `src/config_loader.py` module docstring. Hot-reloading was rejected: config is the definition of what is being measured, so reloading mid-window would let rows either side of an unremarkable text edit come from different definitions while looking identical — a silent, unreconstructable confounder in place of a loud operator error. JEV-30's boundary was recoverable at all only because a restart left a process-start timestamp to bisect on. A per-cycle *warning* was also rejected: a warning that repeats every 30 seconds for hours is one nobody reads, and the rows keep being written wrong throughout. **And `config_fingerprint()` does both**: a content hash of all three config files, meant to be stamped on every row so the boundary is intrinsic to the data rather than reconstructed from two log timestamps — see the handoff

---

## JEV-31: Claimed spool files are never reaped — silent, unmeasured data loss

**Status:** done
**Labels:** defect, blocking, science

**Blocked by:** None — JEV-33 landed.

*Same file as JEV-33 — `spool/claimed/` reaping belongs in the drain loop JEV-33 rewrote. Serialised for that reason alone.*

**Resolved 2026-09-20 with JEV-51**, whose ungraceful SIGTERM was the unnamed
cause of the strandings. A claim now records its **owning worker pid** and a
claim timestamp in its filename — the number in the old name was `capture.sh`'s
`$$`, the *hook's* pid, so "is the owner alive?" could not be asked and a
liveness-keyed reap could not be built at all. See `src/worker.py` (the
lifecycle note at the top) and `docs/REVERSIBILITY.md`.

**What is wrong.** The worker claims a spool file by renaming it into
`spool/claimed/` before doing any work — the atomicity fix that made two workers
safe. **Nothing ever moves it back.** If the process dies between claim and
completion, that decision point is lost permanently, and no code path notices:
`spool/claimed/` is not scanned at startup, not scanned on drain, and not
counted anywhere.

There is one sitting there right now, claimed at 17:28 and never processed.

**Why this is worse than ordinary data loss.** The pre-registration commits to
measuring attrition — *"log every attempt including failures; report attrition
by state-size bucket"*. A capture lost in `claimed/` is attrition that never
appears in the attrition count, because no run row was ever written for it. It
is invisible to the very number designed to catch it.

- [x] Reap at startup: any file in `spool/claimed/` older than a threshold, or claimed by a pid that is no longer alive, returns to `ready/` — **amended: pid liveness only, age never.** `rename()` preserves mtime, so a capture that waited in a deep `ready/` backlog is claimed already looking old and any threshold would eventually reap a file that was mid-dispatch. A **live** pid is never reaped at any age; a claim with no owner recorded (every pre-fix file) is reaped unconditionally, because the reap runs at startup only and `run-collection.sh` pidfile-guards against a second worker, so such a file is stranded by definition. `worker.reap_claimed()`
- [x] Record the reap — a re-claimed capture must be distinguishable from a first-claim one, or a poison payload loops forever — `{base}__p{pid}__t{epoch}__r{retries}.json` on claim, `{base}__r{n}.json` back in `ready/`. The surface still parses off the front (`split("__", 1)[0]` is non-greedy from the left) and `_quarantine` carries the counter into `dead/` for free
- [x] Cap the retries and quarantine after N, so a payload that kills the worker cannot resurrect itself indefinitely — `MAX_CLAIM_RETRIES = 3`, then `dead/` with the reason. Asserted end to end by `test_a_poison_payload_terminates_rather_than_looping`
- [x] Count claimed-but-unprocessed files in the status output of `run-collection.sh` — `spool_watch.report()` already printed it (JEV-33); `stop` now also verifies `claimed/` is empty and **exits non-zero** naming the count if it is not
- [x] Recover the one stranded capture from 17:28 before the window closes — **it was already gone when this ticket was picked up.** `spool/claimed/` was empty, and `logs/worker.log` records no reap and no removal, so **whether it was hand-reaped or deleted is not recoverable from the tree** — do not read the empty directory as "recovered". The consequence for this ticket is that the reap ships **never having run against a real stranded file**; it will first do so at the next sanctioned restart
- [x] Report whether any other captures were lost this way during the window — **the honest answer is "unknowable", not zero.** `dead/` is empty and two strandings are recorded on the board, both hand-reaped. But a hand-reap leaves no trace either, and nothing has ever counted a claim. **Report: at least two, both recovered; no mechanism existed to count the rest.** The mechanism now exists — every reap logs a line and every exhausted re-claim lands in `dead/` with its reason

**The defect the fix introduces, named rather than discovered later.** Reaping
a claim whose owner is still working produces two full sets of *well-formed*
run rows under two `decision_id`s sharing one `state_sha256`. That is
**inflation, not attrition**, and it is invisible to the §5 assertion — the
duplicates are legitimately identical — while making the clustered bootstrap's
independence assumption quietly false. Two mitigations, both cheap and both
tested: a live pid is never reaped, and the reap runs at startup only, before
this process has anything in flight. Residual risk, stated rather than
engineered away: **pid reuse can make a dead owner look alive**, in which case
the file is left in `claimed/` and reported in `status` rather than reaped. A
stranded file that is *visible* is a much smaller problem than this ticket's.

---

## JEV-31b: Five more config fields that look live and are inert

**Status:** done 2026-09-20 (one follow-up line handed to the worker agent)
**Labels:** defect, science
**Blocked by:** None.

**What is wrong.** Fixing the `question_set` defect turned up five more
instances of the same class. A config field that looks like configuration and
does nothing is not a cosmetic problem — it is a field an operator will edit,
observe no error, and reasonably believe took effect.

| field | reality |
|---|---|
| `surfaces.json` → `state_source` | **Inert.** `worker.py` and `replay.py` read the hardcoded `state_builders.STATE_SOURCE` dict. The config values happen to agree today — and this value is written onto **every capture row**, so a divergence would silently mislabel the provenance of the leakage-safety argument |
| `surfaces.json` → `hook_event`, `matcher` | **Inert.** `.claude/settings.local.json` is hand-written and duplicates them |
| `surfaces.json` → `spool_backpressure_max_files: 500` | **Inert.** `capture.sh` uses a bare literal `500` |
| `surfaces.json` → `"version": "surfaces-v1"` | **Inert.** No consumer. Note `pricing()["version"]` *is* recorded on every row; this one is not |
| `paths.SURFACES` tuple | A **second source of truth** for the surface list, independent of `surfaces.json`. Tests iterate it |

`state_source` is the one that matters most and it needs its own decision,
because making it live changes what gets written to the row schema.

- [x] Make `state_source` live, or delete it from config and let `STATE_SOURCE` be the single source — either is defensible; having both is not. **Both kept, and the divergence made impossible**: `config_loader._validate_state_sources()` asserts config against `state_builders.STATE_SOURCE` at load, the same shape as the existing `question_set_id` agreement check. Making config authoritative was rejected — a builder that reads the payload does not become a transcript reader because a JSON file says so, and `STATE_SOURCE` lives next to the builders that decide the answer
- [x] Resolve `paths.SURFACES` against `surfaces.json` so the surface list has one source. `cl.surface_names()` added and the test callers moved onto it. `paths.SURFACES` cannot be derived *in* `paths.py` (config_loader imports paths), so deleting it is a one-line handoff; until then a test asserts the two agree
- [x] Either generate the hook registration from config or delete `hook_event`/`matcher` from it. **Neither**: `.claude/settings.local.json` is gitignored and machine-local, and generating it would mean this repo writes its own hook registration — a capability the reversibility argument (JEV-40) depends on *not* existing. Instead a test asserts every non-`off` surface is registered with a matching event and matcher, and every `off` surface is not. Verified to fail on divergence before it was made to pass
- [x] Record `surfaces_version` on rows as `pricing_version` already is, or drop the field. Kept and made live: it is a field of `config_fingerprint()`, alongside a **content hash** that does not depend on anyone remembering to bump a version string. Stamping it on the row is the worker-side handoff
- [x] Sweep for any remaining config key with no consumer, and add a test asserting every key in `config/*.json` is read somewhere. Scope: top-level keys plus per-surface keys. One genuine survivor, `pricing.json:as_of`, allow-listed **with a reason** in the test, so the next inert key fails the suite instead of going unnoticed
- [x] `spool_backpressure_max_files` — `hooks/capture.sh` hardcodes the cap in **two** places (the threshold at `:72` and the `"cap":500` written onto every drop row at `:93`, which would misreport attrition). The literal stays: capture.sh is a fork-free bash 3.2 hot path with a 10ms budget and cannot parse JSON. A test asserts both literals equal the configured cap, and was verified to fail when they diverge

---

## JEV-32: `analyze.py` reads the current config against rows run under an older one

**Status:** done
**Labels:** defect, science
**Blocked by:** None. Touches frozen `analyze.py`, so it must be its own commit with the reason stated and pre-/post-fix numbers reported (PREREGISTRATION §8).

**What is wrong.** `analyze.py` resolves the question spec from **current**
config at analysis time, while every row carries the `question_set_id` it was
actually run under. If a pin moves mid-collection, the analysis reads one
question list against rows produced by another — and nothing detects it.

Harmless today: nothing has moved, and all 660 rows carry `pre_bash/v1#a`. But
it is precisely the failure the pre-registration's question-set freeze exists to
prevent, and it is latent rather than absent.

`analyze.py` is frozen by `PREREGISTRATION.md` §8, so any change here is a
defect fix committed separately with its reason stated, reporting pre- and
post-fix numbers.

- [x] Assert at analysis time that every row's `question_set_id` matches the spec being applied, and fail loudly on a mismatch rather than producing a plausible wrong number
- [x] If rows legitimately span versions, group by `question_set_id` rather than pooling

**Done 2026-09-20** in `ce9cdc7` (`src/analyze.py` alone) with tests in
`0016a58` (`tests/test_analyze_config_join.py`, written red first).

`report()` now partitions each surface's rows by the row's own
`question_set_id`, loads each group's spec from that pin via `_spec_for()`, and
gives a non-primary pin its own section rather than pooling it. A pin that
cannot be resolved against `questions/` is excluded with a `!!` banner rather
than scored under another spec — excluded, not raised, so one unreadable row
cannot suppress the whole report. `synthetic_report()` names its pin and
excludes off-pin rows with a count. The pricing header reports what the rows
were **stamped** with, with current config beside it.

**Pre-/post-fix numbers: IDENTICAL, and that is the point.** All 2,005 rows
carry `pre_bash/v1#a`, so exactly one group exists and every statistic is
computed over exactly the rows it was before. Full diffs for all five entry
points (`--context live|synthetic|canary|all`, `--synthetic`) are in the commit
message; artefacts in `.scratch/jev32/{pre,post}/`. Every agreement figure,
kappa, PABAK interval, confusion cell, cluster count, sharpness value, quantile,
cost and attribution row is byte-identical. The single deleted line is the
pricing header, same value on both sides.

**Two decisions recorded so they are not relitigated:**

* **Arm-set eras are DISCLOSED, not partitioned.** Keyed on `set(arm_order)`,
  which is intrinsic to the row, rather than bisecting on `evaluated_at`
  against JEV-30's 12:07:24Z restart — bisecting a dataset on a wall clock is
  the contamination JEV-43 exists to remove. The live corpus is 531 three-arm
  and 1252 four-arm rows (the 42 `jev`-only rows are all `canary`). Partitioning
  the statistics on the boundary would move every n and every interval, which is
  a stop-and-report event under §8, not a defect fix. Header line only.
* **`config_fingerprint` does not supersede this.** Zero of the 2,005 rows carry
  one; it cannot be a join key for existing data. It is used for the one
  assertion nothing else can make — two *different* fingerprints inside one
  question set mean config changed without its version string changing.
  Absence stays silent and means the pre-fingerprint era.

**Reported, not repaired** (see `.scratch/a3-prep/jev32.md` §7): `--context all`
pools `live`, `synthetic` and `canary` into one surface section, which
PREREGISTRATION §4 forbids for live-vs-synthetic; and `_operational_table` /
`_attribution_table` aggregate `$/1k` and `p50ms` across the two arm-set eras,
which differ in concurrency regime. Both want their own tickets.

---

## JEV-33: The worker drains slower than the hook captures

**Status:** done
**Labels:** defect, science, blocking

**Blocked by:** None

**What is wrong.** Observed immediately after the four-arm restart: `spool/ready/`
went 19 → 22 → 26 in about a minute while the worker was draining continuously.
Each capture now costs four sequential `cc_*` calls at roughly 20s each, so a
capture takes ~80s to process while captures arrive faster than that during
active work.

**Why it is not merely slow.** `capture.sh` implements backpressure: past
`spool_backpressure_max_files` (500) the hook **stops writing and fails open**.
That is correct behaviour for a hook — it must never wedge a session — but the
consequence is that captures are dropped **silently**, with no run row, no
capture row and therefore no entry in the attrition count the pre-registration
commits to reporting. It is the third instance of the same failure shape as
JEV-31 and JEV-32: a loss that is invisible to the measurement built to catch it.

With a window running to 2026-10-20, a backlog that grows during every working
session will reach 500.

- [x] Count and log the drop: when the hook refuses on backpressure, record that it happened somewhere durable, so dropped captures appear in attrition instead of vanishing
- [x] Evaluate arms **concurrently** rather than sequentially — they are independent HTTP/subprocess calls and the interleaving requirement is about *order randomisation*, not serialisation. ~~This alone should cut per-capture time by ~4x~~ **The 4x was wrong; see below.**
- [x] Decide whether every capture needs every arm. **Decided: every capture keeps every arm** (owner, 2026-09-20). Sampling would create a *third* configuration boundary stacked on JEV-30's arm-set boundary, and a third era is worse than 16.5s per capture. The drop counter now makes any future loss visible rather than silent, so sampling can be decided on evidence later instead of on fear. Not implemented.
- [x] Report the spool high-water mark for the window, whatever is decided

**Done 2026-09-20.** What changed:

| | |
|---|---|
| `src/worker.py` | `_dispatch()` runs every arm in a thread pool. Results are indexed by submission position, never collected with `as_completed()` — pairing a future with the wrong arm would mislabel `arm_order_position` silently, and the row would still look well-formed |
| `hooks/capture.sh` | a backpressure refusal appends one line to `data/drops/YYYY-MM-DD.jsonl`. Two forks, paid **only** on the drop path; the happy path is still fork-free at 6.0ms, the drop path is 9.1ms, both inside the 10ms budget |
| `src/spool_watch.py` | new. Spool depth (ready **and** claimed), a monotonic high-water mark in `data/spool_watermark.json`, and the drop count |
| `run-collection.sh` | `status` reports depth, peak and drops; `start` now uses `python3 -u`, because the worker had been block-buffering `logs/worker.log` under `nohup` and an operator tailing it saw nothing for hours |

### The ~4x estimate was wrong, and the realised gain is ~1.2x

The estimate in this ticket was mine and it was never reachable. Concurrency is
bounded by the **slowest** arm, not by the mean, and the arms are wildly
unequal. Measured on the 78 four-arm serial-era live decisions:

| arm | median wall-clock |
|---|---|
| `jev` | 0.57s |
| `cc_sonnet5` | 2.9s |
| `cc_opus5` | 4.9s |
| `cc_haiku45` | **11.6s** |
| **serial sum per capture** | **20.1s** |

So the theoretical floor was ~11.4s — a **1.76x** ceiling, not 4x. Measured
after the change, over 17 concurrent decisions: `dispatch_wall_ms` median
**16.5s**. The realised gain is **20.1s → 16.5s, ~1.2x**.

The ~6s above the slowest-arm floor is **contention**: four simultaneous
`claude -p` invocations each pay a Node startup and compete for CPU. That
contention is systematic **by arm kind** — `jev` is one HTTP call and barely
contends, the three `cc_*` arms each spawn a process — so it biases per-arm
wall-clock **toward Jev**. `raw.duration_api_ms` is recorded on every `cc_*` row
and separates API time from spawn, so the bias is measurable rather than assumed.

The backlog does drain: `spool/ready` fell 20 → 10 over 3.7 minutes while new
captures kept arriving. But 4x does not appear anywhere and should not be quoted.
The remaining lever is arm sampling, deliberately not taken (above). **See JEV-41:
`cc_haiku45` alone accounts for most of the floor, and the reason is fixable.**

### Both era boundaries in the collection window, in one place

An analyst needs these together, so they are recorded together rather than one
per ticket:

| boundary | at | before | after | ticket |
|---|---|---|---|---|
| arm set | **2026-09-20T12:07:24Z** | 3 arms (`cc_opus5`, `cc_haiku45`, `jev`) — no `cc_sonnet5` | 4 arms | JEV-30 |
| arm dispatch | **2026-09-20T14:24:13Z** | serial, randomised order | concurrent, randomised submission order | JEV-33 |

**The pooling rule.** Across the *dispatch* boundary: **wall-clock latency is
NOT poolable** and must be reported per era, because concurrent `claude -p`
spawns contend and the contention is arm-kind-dependent. **Agreement, answers,
cost and attrition ARE poolable** — every arm sees byte-identical state and
identical questions in both eras, and neither the state nor the question set
changed. Across the *arm-set* boundary, condition on the arm set or report it;
the `pre_bash` primary metric is `jev` vs `cc_opus5`, both present on both
sides, so the headline is unaffected.

Split the eras on the **presence of `arm_dispatch`** on a run row. Its absence
means the sequential era — that is a definition, not an inference, and it is
correct for `replay.py` and `canary.py` rows too, which remain sequential.

### What `arm_order` means now

The randomisation never protected *order*; it protected against one arm
systematically occupying the late slots of a ~20s serial window (a slice of
time-of-day network drift) or the first slot (cold-connection cost).
**Concurrency removes that hazard rather than relaxing it: there are no late
slots because there are no slots.** The requirement is satisfied more strongly.

But the field's meaning narrows, and it is on 750+ committed rows, so it is
marked rather than silently redefined. Post-boundary rows carry:

| field | meaning |
|---|---|
| `arm_dispatch` | `"concurrent"`. **Absent = sequential era.** The era marker |
| `arm_order` | the randomised **submission** order. No longer a latency-confound control. Kept because the stagger is real, merely tiny |
| `arm_order_position` | index into it. `row["arm"] == row["arm_order"][row["arm_order_position"]]` holds in **both** eras and is now tested |
| `dispatch_offset_ms` | measured ms from the decision's t0 to this arm's call starting. The **empirical** replacement for the order control: analysis can now verify the stagger is negligible instead of trusting the design. Measured max **5.25ms** |
| `dispatch_wall_ms` | t0 to the last arm finishing. The drain-rate instrument |
| `concurrent_arms` | how many were in flight, so contention is conditionable |

Full statement in `src/worker.py`'s module docstring. `PREREGISTRATION.md`
Amendment 5 is the owner's to write; this ticket did not touch that file.

### Verified on live data

68 concurrent rows across 17 decisions: the `arm_order_position` invariant holds
on all 68, zero errors, and **no `rate_limit` or `cli_error`** — four concurrent
`claude -p` calls on one subscription did not hit a config-dir lock or a 429,
which was the risk worth checking before trusting this.

**Not fixed here, and still open:** JEV-31 (claimed files are never reaped —
one stranded file was reaped by hand before this restart, again), and JEV-31b
(`spool_backpressure_max_files` in config is still inert; `capture.sh` still
hardcodes `500`. They agree today; `spool_watch.cap()` reads the config value
and its docstring says plainly that it is the number an operator *believes* is
in force).

---

## JEV-34: `agent_route` in shadow — the surface, deciding nothing

**Status:** done 2026-09-21 (`652d3e8`) — **one box deferred to Phase B, stated below**
**Labels:** hooks, science
**Blocked by:** JEV-15

*JEV-15's last item parameterises the three existing gates on surface. Without it, `agent_route` would either ship ungated or duplicate three hardcoded `pre_bash` gates — and this is the surface that will later be allowed to change which model your work runs on.*

**What to build:** The routing surface, observing only. A `PreToolUse` hook
matched on the `Agent` tool builds state from the delegated task, asks Jev which
tier it would need, and **records the answer without rewriting anything**. The
model that runs is whatever would have run anyway.

This exists as a separate ticket so there is a point at which the surface is
verifiable *before* it can change what model your work runs on. Shipping the
classifier and the actuator together means the first time anything is observed
is also the first time something is altered.

**GATE 4 is satisfied by construction here and the gate should still assert it.**
State is the hook payload and nothing else — no transcript read, no byte offset,
no truncation marker — so the future-leakage question that makes `stop` hard
cannot arise. "Impossible by construction" is a claim about code that changes.

**Demoable:** spawn a subagent; a routing decision appears in the data with a
tier and a probability; `resolvedModel` is unchanged.

- [x] `questions/agent_route/v1.json` — `complexity` as a **score** with anchors describing the WORK, never naming a model, preserving the separation `user_prompt/v2.json` already argues for; tier selection stays a policy applied in analysis
- [x] State builder: `tool_input.prompt` + `tool_input.subagent_type`, payload-only. **Built wider than the box asked**, and the reasoning is in the `build_agent_route` docstring: SWE-Router measures a Bayes-error floor for prompt-plus-type alone, and 78 of 120 observed delegated tasks (65%) are `general-purpose`, the one agent type carrying no routing signal. `description`, `run_in_background`, the invoker's `agent_type`/`agent_id`, `permission_mode`, `effort.level` and `cwd` are added — all already in the payload, all free, each one justified against plan decision #7 per field. **`tool_input.model` is deliberately withheld**: it leaks nothing, but it names the answer and it is the field JEV-35 overwrites
- [x] `agent_route` added to `config/surfaces.json` and to the surface list in `paths` — **both in one commit**, which is the JEV-31b failure mode
- [x] The `JEV_ARM_SUBPROCESS` recursion guard, for the same reason `capture.sh` has it: the `cc_*` arms spawn `claude -p` in this repo
- [x] Fail open on every path, exit 0 always, hard timeout — it is synchronous on the spawn critical path
- [ ] ~~Measure the latency it adds to a subagent spawn, live~~ → **DEFERRED TO PHASE B, and it is a real deferral rather than a quiet drop.** It cannot be done in Phase A: measuring it requires the hook registered and firing, and no Phase A ticket may register a hook. This is **the one place in the study where a Jev call is not free** — every other surface observes a decision that has already been made, while this one sits on the spawn's critical path. It must be measured in the first live window and **JEV-52 must not treat this ticket as fully closed**: the surface is built and proven inert, not proven cheap
- [x] GATE 4 extended to `agent_route`, asserting the state cannot contain anything created after the spawn. **Satisfied by construction**: the builder is a pure function of the payload dict, so a worker running an hour late produces the same bytes the hook would have — asserted at unit level in `tests/test_agent_route.py` rather than assumed
- [x] Parameterise the three existing gates on surface — they are hardcoded to `pre_bash`. Done by JEV-15; `tests/gates.sh payload_for` now carries an `agent_route` case

**Landed:** `652d3e8`. `tests/test_agent_route.py`, 22 tests. Full suite green,
`mode: "off"` verified, no hook entry exists in `.claude/settings.local.json`.
`test_there_is_no_actuator_in_this_repo_yet` **is designed to fail once JEV-35
lands** — JEV-35 must update it deliberately, not delete it.

---

## JEV-35: Make the routing hook an actuator — behind two new gates

**Status:** ready-for-agent — **unblocked 2026-09-21**. Both blockers are done: JEV-34 landed (`652d3e8`) and JEV-40 prints `OFF IS PROVEN EQUAL TO VANILLA -- JEV-35 may proceed`
**Labels:** hooks, science, blocking
**Blocked by:** ~~JEV-34, JEV-40~~ — both cleared. Wave A5.

**Two things this ticket must not do, and one it must.** It may **not** register
a hook, change `agent_route`'s `mode: "off"`, or touch
`.claude/settings.local.json` — building the actuator is Phase A, arming it is
JEV-52. It **must** deliberately update
`tests/test_agent_route.py::test_there_is_no_actuator_in_this_repo_yet`, which
JEV-34 wrote to fail the moment an actuator exists ("Until then no…"). Deleting
that test or routing around it removes the only assertion that the shadow
surface stayed a shadow.

**Prior-art amendment (2026-09-20).** Two semantics must be pre-registered
before this is armed, because three shipped systems chose three different
answers and the cost signatures are opposite:
- **Fail behaviour.** Claude Code's documented hook timeout is **fail-open** (the
  tool proceeds). Anthropic's auto mode is **fail-closed**. togishima's
  dispatcher **fails to frontier** — a Jev outage silently routes everything to
  Opus and the bill explodes. Ours is fail-open by design; say so explicitly and
  state what it costs.
- **Escalation semantics.** SWE-Router (arXiv:2607.00053) restarts the strong
  model from the original query rather than continuing the cheap model's
  trajectory, *"because conditioning m2 on m1's reasoning has been seen to bias
  m2 toward m1's mistakes."* Restart discards the cheap work; continue inherits
  the errors. Both are defensible, they cost differently, and picking after
  seeing results is not allowed. **Pre-register which.**
**Scope change (dev/live gate):** this ticket now BUILDS the actuator and its
two gates and does **not** arm it. Arming happens only at JEV-52.

*JEV-40 is a hard gate, not a nicety. This is the first ticket that changes what
actually runs, and a way back to vanilla must exist and be proven **before** it
lands, not after.*

**What to build:** The hook stops observing and starts deciding. It returns
`permissionDecision: "allow"` together with `updatedInput`, with `model`
rewritten to the tier Jev chose.

**This is the study's first actuator.** Every hook until now only watched, and
the worst case for an observer is a lost record. The existing gates — isolation,
fail-open, kill switch, GATE 4 — all apply, plus two written for this one
(`PREREGISTRATION.md` A3.4).

**Demoable:** an `Explore` task assigned haiku reports `resolvedModel` haiku.

- [ ] **Input-fidelity gate.** `updatedInput` replaces the ENTIRE tool input object, so `prompt`, `description` and `subagent_type` must be echoed back byte-identically. Asserted — a hook that drops `subagent_type` spawns a subagent of the wrong type, which is indistinguishable in the results from a routing quality effect
- [ ] **Assignment-ledger-before-spawn gate.** The assignment is durably recorded *before* the subagent starts. A ledger written afterwards is missing exactly when it matters most: when the task crashed
- [ ] Verify against `resolvedModel`, not against what was requested — an `availableModels` allowlist or `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` overrides the hook, and a silently ignored assignment makes the treatment arm identical to the control arm
- [ ] **Fail open means fall back to the default, which IS the control arm.** Record that it happened; A3.1 charges it to the treatment under intention-to-treat
- [ ] Choice set `{haiku45, sonnet5, opus5, fable51}` per A3.2 — Fable blocked on JEV-28
- [ ] The `JEV_GRADER` guard, so the blinded grader's own delegations cannot enter the experiment measuring them
- [ ] Kill switch verified on this hook specifically: `.jev-disabled` must stop it routing, not merely stop it logging

---

## JEV-36: A/B outcome measurement — both primaries, per delegated task

**Status:** blocked
**Labels:** analysis, science, blocking
**Blocked by:** JEV-35

**Prior-art amendment (2026-09-20).** Two additions, both cheap and both
pre-empting an obvious objection:
- **A per-step "was this step under-routed" diagnostic**, reported alongside
  trajectory-level success. TwinRouterBench (arXiv:2605.18859) found that **one
  under-routed step in an 8-13 call trajectory fails the instance**, and that
  Claude Opus 4.6 used as a router flagged only **7 of 147** verified-high steps,
  failing all 40 SWE trajectories. Aggregate cost figures hide this completely.
- **Cache-write tokens and tier-switch counts per trajectory** — see JEV-47.
  TwinRouterBench is the only source that prices it: *"cache writes on tier
  switch are charged at the incoming tier's rate."*
See also **JEV-48**, which uses this ticket's outcomes to test whether we are
measuring tier fit or task difficulty.

**What to build:** The measurement the experiment reports. Two co-primary
outcomes per delegated task — **raw net cost** and **net wall-clock** — with
clustered intervals, computed from data the harness actually produces.

**It cannot come from `PostToolUse`.** Subagents run in the background by
default since v2.1.198, and an `async_launched` response carries `resolvedModel`
and no usage, token or timing fields at all. Cost and duration come from the
subagent's own transcript under `<session>/subagents/`, or from a `SubagentStop`
hook.

**Demoable:** a table of ten delegated tasks with both primaries, their
intervals, and the arm each was assigned.

- [ ] Per-task cost via the existing reconciled formula; per-task **task duration** AND **blocking duration** recorded separately (A3.5) — a background subagent can get objectively faster while the human waits exactly as long, and if the two diverge that divergence is the finding
- [ ] Charge the hook's own spawn latency to the treatment arm, measured not assumed
- [ ] **Intention-to-treat** population primary, per-protocol secondary, hook-failure rate reported beside both (A3.1)
- [ ] Report the correlation between the two primaries — cheaper tiers are faster tiers, so this is largely one effect in two units
- [ ] **Agreement between Jev's assignment and a static `subagent_type -> tier` rule**, computed offline. The ADR commits to this: if Jev agrees with two lines of `if`, the classifier is adding nothing and that is a headline caveat whatever the cost says
- [ ] Escalation counted unadjusted; rework-adjusted cost only if the `replaces:` convention's compliance rate is measured and stated
- [ ] Attrition by arm — a tier that fails more often would otherwise look cheaper

---

## JEV-37: The canary is pre-registered as daily and has no scheduler

**Status:** ready-for-agent
**Labels:** science, ops
**Blocked by:** None.

**What to build:** A way for the drift canary to actually run daily. The
pre-registration commits to a **daily** fixed-state check; `src/canary.py`
exists and works, and nothing runs it. It currently fires when someone
remembers, which is not a daily check and should not be reported as one.

The spec rules out launchd and any auto-start mechanism deliberately — "the
experiment is running" should be an observable state — so the scheduler is the
operator's, outside the folder. That constraint is fine; the gap is that no
wrapper, no instruction and no record of whether it ran exists.

- [ ] A one-line wrapper the operator can put in their own cron, reading the exit codes (0 clean / 1 drift / 2 baselined / 3 incomplete / 4 flip within the tau jitter band)
- [ ] Record each sweep's date so a **missed day is visible**. A gap in the canary record is itself drift evidence lost, and it must not be silently smoothed over
- [ ] Report the sweep calendar in the writeup: how many days of the window were actually covered, out of how many
- [ ] Decide and document what a missed day means for the drift claim — the honest answer is probably that drift can only be bounded over the days actually sampled

---

## JEV-38: Persist the "before" baseline — the source is outside the folder and not ours

**Status:** done
**Labels:** metrics, blocking, science
**Blocked by:** None — and it is the most time-sensitive ticket on the board. **Do it in the same pass as JEV-24a.**

**What to build:** An accumulating, append-only, **in-repo** record of
per-session metrics for every session in this repository, snapshotted from the
transcripts before they can go away.

**Why this is urgent rather than tidy.** JEV-06 claimed the "before" baseline
"starts collecting on day 0". It does not exist. `session_metrics.py` reads a
transcript on demand and prints; nothing accumulates anywhere. And the
transcripts it reads are in **`~/.claude/projects/` — outside this folder, under
a retention policy we neither control nor have written down.** Every other
artifact in this study is self-contained by design; the one number the entire
enforce-vs-shadow and before-vs-after comparison rests on is the exception, and
it is held somewhere we do not own.

**If those transcripts rotate, the "before" is gone and cannot be reconstructed
at any price.** JEV-24a's pre-rule delegation baseline has exactly the same
dependency and the same exposure.

- [ ] Append-only `data/baseline/sessions.jsonl`: one row per session, keyed by `session_id`, idempotent so re-running never double-counts
- [ ] Derived numbers only — **no third-party transcript content copied into the folder**, the rule that already governs `data/fixtures/`
- [ ] Snapshot every session in this repo **that still exists**, now, before anything else is scheduled
- [ ] Record, for each session, the transcript's mtime and size, so a later re-read can prove it is the same file
- [ ] Record the count of sessions that were **already unrecoverable** at first snapshot. An unknown gap reported as zero is worse than a gap reported honestly
- [ ] Establish what Claude Code's transcript retention actually is, and write it down — the study currently depends on an unstated assumption about someone else's storage
- [ ] Commit the baseline to git. `data/` is gitignored for state blobs; this is aggregate and is the one thing that must survive losing the folder

---

## JEV-39: Stats exist only as raw rows and ad-hoc reports

**Status:** ready-for-agent
**Labels:** analysis, ops

**Blocked by:** None. Overlaps JEV-32 in `analyze.py`; if both are agent-run, serialise them

**What to build:** A dated, committed snapshot of the collection's statistics,
produced on a schedule rather than when someone happens to run `analyze.py`.

**What persists today, precisely.** Raw rows survive in `data/runs/*.jsonl` and
friends — they are on disk across sessions, but `data/` is **gitignored**, so
nothing statistical is in version control. `reports/` *is* tracked, deliberately,
and contains seven files that are whatever someone ran by hand, with
inconsistent naming: some dated (`determinism-2026-09-20.txt`), some not
(`canary.txt`, which **overwrites itself** on every sweep and has already lost
its own history).

So the answer to "does it persist beyond sessions" is: the raw data does, on
this disk only; the *statistics* mostly do not.

- [ ] A dated snapshot — `reports/window/YYYY-MM-DD-analyze.txt` — produced on a cadence, covering the primary metric, cluster count, base rate, attrition and spool high-water mark
- [ ] Every generated report carries a **date and the git hash of the code that produced it**. A report that cannot say which code made it cannot be reproduced
- [ ] Fix the overwriting ones: `canary.txt` should be dated like the others
- [ ] Decide the cadence and write it into the pre-registration, so the snapshot series is not itself a post-hoc choice
- [ ] The snapshot must print `INCONCLUSIVE BY RULE` where the A1.1 guard applies, rather than a bare interval — an interim number read without its guard is exactly what the guard exists to prevent

---

## JEV-40: One master switch, and a proof that OFF means vanilla

**Status:** done
**Labels:** safety, blocking, hooks
**Blocked by:** None — and it blocks JEV-35

**What to build:** A single switch that returns this machine to stock Claude
Code, and a gate that proves it did.

**What already works.** `.jev-disabled` is checked on line one of both
`capture.sh` and `inline_shadow_bash.sh`, is `$CLAUDE_PROJECT_DIR`-anchored, is
asserted in four test files, and is surfaced by `run-collection.sh status` and
`doctor.py`. Hook registration lives only in the gitignored
`.claude/settings.local.json`, inside the folder, so deleting the folder removes
the hooks. Nothing is ever written to `~/.claude/settings.json` and nothing
outside the folder is written at all.

**Why that is no longer enough.** The switch was designed when every hook was an
**observer**, where OFF simply means "stop recording". JEV-35 makes a hook an
**actuator**, and OFF then has to mean something stronger: *stop deciding, and
let the default happen exactly as it would have.* Those are not the same claim.
A hook that exits early still ran; what matters is whether the tool input it
leaves behind is byte-identical to the one Claude Code would have produced
untouched. That has never been asserted, because until now nothing rewrote it.

- [x] **One switch, all surfaces.** Every current and future hook checks it on line one, anchored, before anything else — and a test that **enumerates the registered hooks and fails if any one of them lacks the check**, so a new surface cannot be added without it
- [x] **Prove OFF equals vanilla, do not assert it.** With the switch on, capture a subagent spawn's tool input and assert it is **byte-identical** to the same spawn with the hooks unregistered entirely. An actuator that "exits early" is not the same as one that never ran, and only the byte comparison can tell them apart
- [x] **A documented teardown** — one command, printed by `doctor.py`, that unregisters the hooks and states plainly what it does and does not undo
- [x] **Establish whether a RUNNING session honours the switch**, or whether hook config is read once at session start. If a live session keeps firing a hook after the switch is set, the switch is not an emergency stop and must not be described as one. This is a fact to check, not to assume
- [x] **Assert the switch fails safe**: if the file cannot be read — permissions, a full disk — the hook must behave as though it were present, not absent
- [x] `doctor.py` prints the full reversibility state in one place: which hooks are registered, whether the switch is set, what is inside the folder and what has been written outside it

**Done 2026-09-20.** `tests/reversibility.sh`, 42 assertions, offline, no spend,
entirely inside a sandbox project directory -- it never touches the real
`spool/`, `data/` or `logs/`, and it asserts the live
`.claude/settings.local.json` is byte-identical before and after.
Write-up in `docs/REVERSIBILITY.md`; teardown is `./teardown.sh --yes`
(`--dry-run` first), printed by `uv run src/doctor.py` alongside the full
reversibility state.

Four things are worth carrying forward:

1. **A running session DOES honour the switch**, at the very next hook
   invocation, with no restart. Probed live in an already-running session at
   20:05-20:06 on 2026-09-20 (captured / not captured / captured, across a
   touch and an `rm`), and two captures were deliberately forgone to get it.
   The reason it generalises is the mechanism, not the probe: the switch is not
   hook *configuration*, it is a file test made by the hook *script*, and a
   fresh process reads that script from disk on every fire. So the existing
   "instantly, without restarting a session" wording is correct and stays —
   with two bounds now attached to it wherever it appears: a hook already in
   flight finishes, and the switch stops THESE hooks because THESE scripts test
   it, not because Claude Code enforces it. The harness-native equivalent is
   `"disableAllHooks": true`.

2. **The switch did NOT fail safe, and now does.** `[ -f ]` reads a directory
   as absent, so an operator who typed `mkdir .jev-disabled` would have
   believed the experiment was off while every hook kept firing. The canonical
   block is now `{ [ -e ... ] || [ -L ... ]; } && exit 0` — any entry at the
   path means OFF, including a directory, a dangling symlink and an unreadable
   file. All four forms asserted, on both hooks, against a control that proves
   the sandbox captures when the switch is genuinely absent.

3. **OFF-equals-vanilla is now measured.** `src/hook_dispatch.py` models the
   documented `PreToolUse` dispatch and returns the tool input that survives;
   the gate compares its canonical serialisation across four arms. The
   load-bearing one is the POSITIVE CONTROL: an actuator fixture with the
   switch off must change the input. Without it every other assertion would
   pass on a test incapable of detecting a rewrite — which is the state the
   repo was in before this ticket.

4. **Two consumers were reporting the opposite of what the hooks do.**
   `run-collection.sh status` used `[ -f ]` and `paths.killed()` used
   `.exists()`, so after `mkdir .jev-disabled` the operator was told
   `capture: enabled` while every hook was exiting on line one. Both now use
   the hooks' rule. Those two, plus `src/reversibility.py`, are the only places
   the rule is encoded outside the hook scripts.

5. **`tests/gates.sh` line 10 still reads "one file stops everything,
   instantly"**, which is true for an observer and is now underspecified for an
   actuator. It was not edited because another agent owned that file during
   this work. `tests/reversibility.sh` is the superset.

### What a flag cannot undo, stated plainly

A switch is the wrong mental model for some of this, and pretending otherwise
would be the dangerous part:

| change | reversible? |
|---|---|
| hooks firing | **Yes** — switch, or unregister |
| data collected | **Yes** — delete the folder |
| the machine's config outside this folder | **Nothing to undo**; nothing is written there |
| **work already produced by a routed model** | **No.** Once a delegated task has run on haiku instead of opus, that output is in your repository and your history. Turning routing off stops future tasks; it does not re-do past ones |
| **the "delegate where possible" working rule (JEV-24b)** | **No.** It is a change in how the work is done, not a change to a program. No flag reverses a habit, and the pre-registration already records it as a confound |

The first three are what a master switch is for. The last two are why the
experiment is pre-registered and staged rather than simply flagged, and they
belong in the writeup's limitations rather than in a config file.

---

## JEV-41: `cc_haiku45` is the SLOWEST arm, not the fastest — and `--effort low` is not suppressing its thinking

**Status:** done — with one half fixed, the other half diagnosed and deliberately left alone
**Labels:** science, defect, cost
**Blocked by:** None

**What is wrong.** `config/arms.json` calls `cc_haiku45` "the actual incumbent"
on the premise that nobody deploys Opus as a hook gate. The measurement says the
opposite. Across **both** dispatch eras, so this is not a concurrency artefact:

| arm | median API time | median wall | output tokens | **thinking tokens** | cache read |
|---|---|---|---|---|---|
| `cc_haiku45` | **8.1s** (10.4s over all n=335) | 11.6s | **1,019** | **741** | **0** |
| `cc_opus5` | 3.4s | 4.9s | 174 | **0** | 10,777 |
| `cc_sonnet5` | 1.5s | 2.9s | 95 | **0** | 4,898 |

Haiku 4.5 is **2.4x slower than Opus 5** on the same question, on identical
state, at the same `effort: low`.

**Two candidate causes are already visible in the data and neither is asserted
as the answer.**

1. **`--effort low` appears not to suppress thinking on Haiku 4.5.** Opus and
   Sonnet emit **zero** thinking tokens; Haiku emits **741** — 73% of its
   output. `src/arms/claude_cli.py`'s docstring records "317 tokens, despite
   `--effort low`" from the JEV-02 spike, so this was seen on day 0, measured on
   Haiku, and generalised in prose to all the `cc_*` arms. It does not
   generalise: it is a Haiku-specific behaviour, and it is now 741 tokens rather
   than 317. Note this cuts **against** `arms.json`'s note that "low effort is
   the correct lever" — it is the correct lever on Opus and is not working on
   Haiku.
2. **Haiku gets no prompt caching at all.** `cache_read_input_tokens` is **0**
   on every one of 335 Haiku calls while it writes 5,524 cache-creation tokens
   every time; Opus reads 10,777 cached tokens per call. Haiku is paying a cold
   preamble on every single invocation.

Process spawn is a third candidate and is the least likely of the three — it is
common to all three `cc_*` arms, and the wall-minus-API gap is ~3.5s for Haiku
against ~1.4s for Opus, so spawn does not explain the ordering either.

**Why this matters beyond curiosity, and what it does NOT show.** JEV-23 makes
**net wall-clock a CO-PRIMARY outcome** of the routing A/B, and the whole
economic argument for routing down a tier rests on cheaper models also being
faster. This is direct evidence that **"smaller = faster" is not automatic in
this harness**.

It does **not** refute the routing thesis, and must not be quoted as if it did.
These are single classification calls — one short question, tiny state,
structured output — not delegated tasks. A delegated task is a long multi-turn
agentic loop where the tier's throughput dominates and a fixed per-call overhead
amortises away. What it does mean is that **the A/B has to MEASURE speed rather
than assume it**, which is exactly why wall-clock was made co-primary, and that
the configuration under test must be checked for this defect first — otherwise
the A/B measures a thinking-token misconfiguration and reports it as a property
of the tier.

- [x] Confirm the effort/thinking behaviour against a controlled pair of calls, Haiku vs Opus, same state, same effort, thinking tokens recorded
- [x] Establish whether `--effort low` is ignored on Haiku 4.5, or whether Haiku's floor genuinely sits at ~740 thinking tokens; check the claude-api skill's docs before concluding
- [x] Establish why Haiku's cache read is zero on every call while Opus's is not
- [x] Re-time `cc_haiku45` once either is fixed. If it drops below `cc_opus5`, the arm's `arm_config_id` MUST change and that is a **fourth** era boundary in the window — weigh that against leaving it alone until the window closes
- [x] Correct `src/arms/claude_cli.py`'s docstring: its "317 tokens despite `--effort low`" was measured on Haiku and does not hold for Opus or Sonnet, both of which emit zero
- [ ] Report the finding in the writeup whatever the cause: "the cheap tier was the slow tier, and the reason was configuration, not capability" is a useful result about hook-gate deployment and is directly relevant to JEV-23's co-primary — **still open, and it is now a two-part finding: half configuration, half a model property we chose not to engineer around**

---

### Resolved 2026-09-20. Two defects, two different answers.

**Defect A — thinking. Root cause found, fixed, measured.** It is not that
`--effort low` is "ignored" on Haiku 4.5, and it is not a ~740-token floor
either. It is a model-generation split inside Claude Code 2.1.278, read out of
the shipped binary rather than inferred:

- Claude Code turns thinking **on by default for every model**. The resolution
  is `thinking ??= supportsAdaptive(model) ? {type:"adaptive"} : {type:"enabled", budget_tokens: N}`.
- `supportsAdaptive()` returns **false** for `claude-haiku-4-5`, which the
  binary names explicitly alongside `claude-sonnet-4-5` and `claude-opus-4-5`.
- So Opus 5 and Sonnet 5 get **adaptive** thinking, which genuinely spends
  nothing on a two-question classification — hence their honest zeros. Haiku 4.5
  gets a **fixed budget**, and a fixed budget is spent.
- `output_config.effort` is a 4.6+ control and is not supported on Haiku 4.5 at
  all, so `--effort low` cannot lower anything there. `arms.json`'s note that
  "low effort is the correct lever" was right about Opus and wrong as a general
  rule. Both notes are now corrected.

The only lever that reaches a pre-4.6 model is turning thinking off outright.
`MAX_THINKING_TOKENS=0` maps to `thinking: {type:"disabled"}`; it is now a
per-arm config field, `max_thinking_tokens`, set on `cc_haiku45` only.

**Defect B — cache reads. Root cause found, fixable here, deliberately NOT
fixed.** Haiku 4.5's minimum cacheable prefix is **4,096 tokens** against 512 on
Opus 5. The stable system+tools block of this deliberately lean invocation sits
below that minimum, so that breakpoint silently creates no entry and the only
entry that exists sits **after** the per-decision state. Distinct states
therefore never hit. Two constructions, not one argument:

- the same state twice in a row **does** read (0 → 5,613), so caching is not off
  for this model;
- padding the system prompt past 4,096 tokens makes cross-state reads appear at
  once — **12,744 read** on two unrelated states, writes collapsing to ~1,735.

So it is fixable from our side, by padding a classifier's system prompt with
~9K tokens of filler. That is declined: it would change what the arm measures,
and the arm exists to measure Claude Code as it ships. Defect B is published as
a finding about deploying a pre-4.6 model behind `claude -p` on a short prompt.

**Measured, paired on 9 existing synthetic states (3 per stratum), same states,
interleaved old/new so hour-of-day and machine load are paired.** 18 calls.

| | v1 (334 live rows) | v1 paired probe | **v2 fix** | `cc_opus5` |
|---|---|---|---|---|
| output tokens | 986 | 764 | **333** | 174 |
| thinking tokens | 726 | 647 | **0** | 0 |
| cache read | 0 | 0 | **0** | 10,777 |
| cache write | 5,541 | 5,463 | **5,290** | 2,568 |
| API ms | 9,960 | 9,254 | **4,557** | 3,476 |

**Haiku is still not the fast arm.** Output tokens fall 56% and API time 51%,
and it *still* sits above `cc_opus5`. Half of the original gap was our
misconfiguration; the other half is the cache miss we are choosing to keep. The
"smaller = faster" premise is not rescued by the fix, which strengthens rather
than weakens the reason wall-clock was made co-primary in JEV-23.

**Era boundary.** `arm_config_id` goes `cc-haiku45-cli-v1` →
`cc-haiku45-cli-v2-nothink`. **The restart has now happened** — worker pid
94441, started 2026-09-20T15:15:33Z, and rows carrying
`cc-haiku45-cli-v2-nothink` began appearing immediately after. (This paragraph
previously said the restart had NOT happened; that was true when written and
went stale the same afternoon. `PREREGISTRATION.md` A7.4 has it right.) The
discriminator is the id on the row, not a wall-clock time, which is the more
robust form: 334 live + 60 synthetic rows carry v1 and none of them pool with
v2 on cost or latency.

**Are the 334 live rows still usable for agreement?** Probably yes, and the
caveat is honest rather than reassuring. Across 18 paired answers: **1 decision
flip at τ=0.5**, mean |Δp| 0.078, and one large move (`syn-0242`
`needs_review` 0.85 → 0.02). Thinking is part of the inference, so it *can*
change an answer and on this evidence sometimes does. But `cc_haiku45` has no
determinism baseline — JEV-16 has never run on it — so a 1-in-18 flip cannot be
attributed to the config change rather than to ordinary run-to-run variance.
The defensible position: keep v1 agreement as a v1-era measurement, label it,
and do not pool v1 and v2 answers as one arm. The `pre_bash` primary metric is
`jev` vs `cc_opus5` and is untouched either way.

**Restart required.** The fix takes effect on the worker's next start. Nothing
about this change reaches live collection until then.

**Amendment 7 is proposed in the handover, not written here** —
`PREREGISTRATION.md` is the operator's to amend.

---

## JEV-42: the test suite destroys live collection data

**Status:** done
**Labels:** defect, blocking, test, data-loss
**Blocked by:** None

**What was wrong.** `tests/test_hook.sh` ran every assertion against the REAL
project root while the worker drained it.

- `reset(){ rm -f "$ROOT"/spool/ready/*.json "$ROOT"/spool/tmp/* ...}` — called between assertion blocks
- `chmod 500 "$ROOT/spool/tmp"` for the fail-open case
- 501 filler files written into `$ROOT/spool/ready/` for the backpressure case
- `mv "$ROOT/logs" "$ROOT/logs.bak"` for the fresh-checkout case
- a snapshot-and-restore of the live `data/drops/` attrition stream, itself a hazard: a real drop landing between the two would have been overwritten

`tests/run_all.sh` invokes it, so "run the full test suite" — the instruction in
every agent brief — was the destructive command.

**It caused real, declared data loss.** `PREREGISTRATION.md` Amendment 6 (A6.1)
records at least seven invocations across roughly 14:10Z–15:05Z on 2026-09-20 by
two agents, each wiping `spool/ready/` several times over. The number of
captures lost is unknown and unrecoverable: a file deleted from the spool leaves
no capture row and no run row, so it cannot even enter the attrition count §4
commits to reporting. Fourth instance of the JEV-31/32/33 shape — loss invisible
to the measurement built to catch it.

**Two mechanisms beyond `rm`, both of which delete nothing and lose captures
anyway.** `chmod 500` on the live `spool/tmp` makes every hook that fires during
the window take its fail-open path and drop the capture, with no missing file to
notice afterwards. And `tests/test_inline_shadow.sh` did `touch
"$ROOT/.jev-disabled"` against the real kill switch: collection is OFF for the
duration, and a run interrupted between the `touch` and the `rm -f` leaves it
off indefinitely with nothing anywhere to say so.

- [x] Give `test_hook.sh` the same sandbox treatment `gates.sh` now has
- [x] Audit **every** test file for writes to the real `spool/`, `data/` or `logs/` — `test_inline_shadow.sh` touches the kill switch and should be checked
- [x] Add a guard that makes this class of mistake loud: a test that writes to the real spool while a worker pid is live should **fail**, not silently succeed
- [x] Decide whether `run_all.sh` should refuse to run at all while a collection window is open, or always sandbox

**What was done.**

*`tests/test_hook.sh` is sandboxed.* `CLAUDE_PROJECT_DIR` points at a throwaway
root created with `mktemp -d "$ROOT/logs/hooktest.XXXXXX"` — gitignored, inside
the folder, removed on a trap. The `data/drops/` snapshot dance is gone entirely
rather than made safer: in the sandbox the drop stream starts empty and belongs
to the run. The session id is now unique per run (`hooktest-$$`) and the final
assertion greps the live spool and `data/captures` for it, so an escape is a
visible failure instead of the expected outcome. `HOOK` is overridable via
`JEV_TEST_HOOK`; `hooks/capture.sh` is never edited, because a live session is
firing it.

*The claim that this does not weaken the test was verified, not assumed.* Every
path `capture.sh` touches derives from `${CLAUDE_PROJECT_DIR}`: `$ROOT/logs/capture.err`,
`$ROOT/.jev-disabled`, `$ROOT/spool/tmp`, `$ROOT/spool/ready`, `$ROOT/data/drops`,
and a cwd guard comparing `$PWD/` against `"$ROOT"/*`. A grep for `$HOME`,
`/tmp`, `dirname`, `$0` and `~` returns exactly one line, `TMP="$ROOT/spool/tmp"`,
matched on the substring `/tmp`. The hook cannot tell the difference. 27
assertions, all passing, same set as before.

*And it was proved the sandboxed test still bites.* `tests/test_hook_mutations.sh`
does to `test_hook.sh` what GATE 4 does to the state builder: it copies
`capture.sh` into a sandbox, breaks it eight ways, and requires the *specific*
assertion that should notice to be the one that fails — kill switch removed
→ "captured despite kill switch"; cwd guard removed → "captured from outside
cwd"; recursion guard removed → "captured from an arm subprocess";
`[ -s "$STAGED" ]` removed → "spooled an empty record"; cap raised to 999999 →
"wrote past cap"; `mv -f` → `cp` → "staging dir not clean"; a byte on stdout →
"stdout was"; `trap 'exit 0'` → `'exit 1'` → "exit code was 1". Plus an
unmutated control. All eight caught, control green.

One mutation is deliberately NOT run and says so in the file: a hook with the
real root hardcoded would escape the sandbox and be caught by the live-window
assertion, but running it means writing ~40 synthetic captures into `spool/ready`
for the worker to drain, bill and record as real decision points. Proving a
data-loss guard by contaminating the dataset is this bug with the sign flipped.
What is proved instead is that the detector expression finds a planted capture
in a decoy tree, so it is not vacuous.

*`tests/test_inline_shadow.sh` is sandboxed too* — same pattern, with `config/`,
`questions/` and `.env` symlinked in read-only (symlinked, not copied: a copy of
`.env` would be a second home for the API key). The kill-switch case now touches
the sandbox's switch. 40 assertions, all passing, unchanged set.

*The guard is two layers, and neither depends on a future test opting in.*

1. `tests/audit_live_writes.sh` — a static scan that ENUMERATES `tests/*.sh` and
   fails the suite if any line aims a destructive verb (`rm`/`mv`/`cp`/`chmod`/
   `chown`/`ln`/`truncate`/`touch`) or an output redirect at `$ROOT/spool`,
   `$ROOT/data`, `$ROOT/logs` or `$ROOT/.jev-disabled`, or sets
   `CLAUDE_PROJECT_DIR=$ROOT`, or `mkdir`s at the kill switch (any entry there
   means OFF, JEV-40). `touch` counts because of the kill switch specifically:
   it deletes nothing and still loses every capture fired while it is set.
   Read-only references stay legal — `gates.sh` greps the live spool precisely to
   prove it left no trace there — so the rule is verb-based, not path-based.
   `mkdir`/`mktemp` are not destructive verbs, because creating the sandbox under
   `logs/` is the sanctioned pattern and flagging it would train exemptions. It
   runs FIRST in `run_all.sh`, before any test executes. Its own mutation test is
   in `test_hook_mutations.sh`: pointed at the pre-fix `test_hook.sh` recovered
   from git at a PINNED commit — `HEAD` is now the fixed file, so pinning is
   what stops the proof inverting into a permanent false failure — and it must
   reject that file and name lines 18, 38, 58, 85 and 121.

2. `tests/lib/live_guard.sh` — a runtime tripwire run after EVERY test, naming
   the test that moved the window. A plain directory diff is useless here because
   the worker is supposed to be emptying `spool/ready`, so every invariant is one
   legitimate draining cannot violate: inodes of `spool/`, `spool/ready`,
   `spool/tmp`, `logs/`, `data/` unchanged (catches the `mv`-aside shape); modes
   of `spool/ready` and `spool/tmp` unchanged (catches the `chmod` shape); the
   kill switch in the same state before and after (catches the `touch` shape);
   the worker still alive if it was; `data/drops` and `data/inline` line counts
   non-decreasing; and the conservation law that catches deletion —
   `ready + claimed + dead + capture_rows` never falls, because the worker moves
   a file `ready → claimed → (capture row | dead/)` and a new capture only adds.

*`run_all.sh` always sandboxes; it does not refuse.* A suite that refuses to run
is a suite people stop running. The collection window is not a rare event to
wait out — it is the normal state of this repository until the study ends, and
"the full test suite must pass" is in every agent brief. Refusal means either
nobody tests for the duration or everybody learns the override, which is the
same thing with an audit trail that lies; Amendment 6 already shows the shape,
where an agent told not to use `run_all.sh` ran `test_hook.sh` directly.
Refusal would also make correctness depend on `logs/worker.pid`, which is stale
the moment the worker dies unexpectedly — a question the suite would get wrong
in both directions, where "never touch the live tree" is one it can get right
unconditionally. The one thing it does refuse is to continue after the runtime
guard fires.

**Audit of the other test files.**

| file | verdict |
|---|---|
| `tests/gates.sh` | already sandboxed (the fix this one follows). Clean. |
| `tests/reversibility.sh` | already sandboxed. Note: it uses a plain `mktemp -d`, so its sandbox is in `/tmp`, not "inside the folder" as `gates.sh`'s header describes the pattern. Correct either way; the inconsistency is worth knowing. |
| `tests/test_pipeline.py` | `TempStorage.setUp` repoints `CAPTURES`, `STATES`, `RUNS`, `LABELS`, `SPOOL*`, `DROPS` and `SPOOL_WATERMARK` at a tempdir and `tearDown` restores them. Classes that do not inherit it (`TestSyntheticSet`, `TestStateBuilders`, …) only READ under `data/`. Safe. |
| `tests/test_canary.py` | repoints `FIXTURES`, `RUNS`, `CAPTURES`, `STATES`, `LABELS`, `REPORTS`, `LOGS` at a `mkdtemp` before `ensure_dirs()`. Safe. |
| `tests/test_baseline.py` | repoints `bl.SESSIONS`/`bl.MANIFEST` at a tempdir, so the committed `data/baseline/sessions.jsonl` is never written. Reads the live transcript corpus, which is read-only by design. Safe. |
| `tests/test_validation.py` | tempdir-scoped. Safe. |
| `tests/test_session_metrics.py` | reads `paths.FIXTURES` and `NamedTemporaryFile`s. Safe. |
| `tests/gate4_drain.py` | repoints every writable path at its `--sandbox`. Safe. |
| `src/doctor.py` (run by the suite) | calls `ensure_dirs()` on the real directories — creates them if absent, touches nothing that exists. Benign; the guard's inode checks cover it. |

**The limit of the static scan, stated plainly.** It scans shell. The Python
tests are safe by CONVENTION — `tempfile` redirection in `setUp` — not by
enforcement, and a new Python test that forgets is caught only by the runtime
tripwire, after the fact. Making that structural (a `conftest`-style fixture
that repoints `paths` for every test by default, so opting OUT is the explicit
act) is the right next step and is not done here.

**Related.** The standing rule from the wave-2 prep note — "run `test_hook.sh`
and `run_all.sh` only from a throwaway copy of the tree" — can be retired. The
decision #7 / `transcript_bytes_at_capture` finding filed alongside JEV-42 in the
same report belongs to JEV-19 and is not addressed here.

---

## JEV-43: `cc_*` wall-clock is contaminated by the operator's own user-level hooks

**Status:** done
**Labels:** science, blocking, metrics
**Blocked by:** None

**What is wrong.** The `cc_*` arms spawn `claude -p`, and those sessions load
the operator's `~/.claude` settings — including their **user-level hooks**.
While diagnosing JEV-41, a user `Stop` hook was observed adding **18.5 seconds**
of wall-clock to a single invocation whose API time was 11.7s. Intermittently,
not uniformly.

So `timing_ms.total_ms` on **every `cc_*` row** carries a variable amount of
time that has nothing to do with the arm, the model, or the decision being
classified. `raw.duration_api_ms` is clean; `total_ms` is not.

**Why this is not a minor confound.** Wall-clock is now a **co-primary outcome**
of the routing A/B (`PREREGISTRATION.md` A3.5). A latency figure inflated by the
operator's unrelated automation, by an amount that varies per call, is not a
measurement of anything. And the contamination is **not symmetric**: `jev` is a
single HTTP request that spawns nothing and loads no user config, so it cannot
be affected at all — which means this biases every latency comparison **toward
the treatment arm**, the same direction as the concurrency bias A5.3 already
declares.

**The isolation constraint runs the other way here, and that is worth noting.**
This project took great care that nothing leaks *out* of the folder into the
user's environment. This is the reverse: the user's global environment leaking
*into* the measurement. Nothing in the isolation design was looking for it.

- [x] Quantify it: decompose `total_ms` against `raw.duration_api_ms` across all existing `cc_*` rows and report the spawn-plus-hooks residual, per arm, as a distribution rather than a mean — **three clocks, not two**, per `(arm, arm_config_id, arm_dispatch, run_context)`; `reports/jev43-wallclock.md`
- [x] Establish which user-level hooks fire inside an arm subprocess, and whether the arm can suppress them without altering what it is supposed to measure — **identified**: the `security-guidance` plugin's `Stop` hook. Suppression is possible and **deliberately not taken**; `src/arms/claude_cli.py` is untouched
- [x] **Decide which number is publishable.** `api_ms` primary; `total_ms` over **clean rows only** as the wall-clock co-primary, with `n` dropped stated; never a pooled `cc_*` `total_ms`
- [x] Re-check A5.3's commitment to "quantify the bias rather than assert it is small" — the spawn term is **~180ms** and survives (it is computed on `total_ms - duration_ms`, which excludes the hook); the second term is identified and removed rather than bounded
- [x] Whatever is decided, no `cc_*` wall-clock figure is published until the residual is characterised — characterised; **JEV-33's 16.5s is withdrawn**, see below

---

### Resolved 2026-09-20. The 18.7s was a plugin, not "a user hook", and one published number dies.

**The decomposition.** A `cc_*` row carries two independent clocks for the same
event, one outside the subprocess and one inside it, and the difference is the
whole ticket:

```
total_ms      = spawn_ms + in_session_ms + api_ms       exactly, by construction
spawn_ms      = total_ms - raw.duration_ms              fork/exec, Node + CLI boot, teardown
in_session_ms = raw.duration_ms - raw.duration_api_ms   preamble, tool round trip, OPERATOR HOOKS
api_ms        = raw.duration_api_ms                     the model call. clean.
```

**The source, identified rather than bounded.** `in_session_ms` is sharply
bimodal: 1,255 of 1,322 successful `cc_*` rows below 1.24s, **zero rows between
1.24s and 18.53s**, and 67 rows at 18.5-22.0s totalling 1,266s. That second
mode is the **`security-guidance` plugin's `Stop` hook**. It runs an LLM code
review over the working-tree diff; on this machine those requests fail TLS
certificate verification, so it burns a fixed retry ladder and gives up. **The
hook's own log prints the elapsed time: 18.3s in 253 of 309 recorded firings**,
with a tail to 20.4s that matches the rows' tail. `evaluated_at` is stamped
after `_dispatch` returns, so the correlation has to be run at **decision**
grain or it double-counts arms; run there, over `live` decisions in the window
the log still covers, **20 of 20** contaminated decisions have a hook
completion 0.47-0.69s before the decision's `evaluated_at`, against **3 of
118** clean decisions (2.5%) where chance alone gives 1.6%. The earlier MCP
diagnosis was already ruled out; the correct answer was a plugin-registered
hook, as suspected, and it is a *`Stop`* hook as originally observed.

Two things worth carrying forward. The hook declares `asyncRewake: true` — its
author intended it **not** to block — and in `claude -p` it blocks anyway. And
18.3s is contingent on a broken certificate chain: with working TLS the same
hook makes a real LLM call, which is variable latency *and* the operator's
plugin spending API budget inside every arm subprocess.

**Why only ~5%, and why that number does not forecast anything.** The hook
returns early on an empty diff, so it only fires when this repo had uncommitted
changes at that instant. The trigger is **the operator editing the repo** — not
the arm, not the model, not the decision. Measured hourly rate over the window:
0% to **34.6%**. The corpus-wide 5.07% is an average over how busy someone was.

**Which published numbers move.**

| claim | was | is | verdict |
|---|---|---|---|
| JEV-33 serial sum per capture | 20.1s | **19.7s** | survives — a sum of medians |
| JEV-33 concurrent `dispatch_wall_ms` | 16.5s | **9.7s** | **withdrawn** |
| JEV-33 "20.1s → 16.5s, ~1.2x" | 1.2x | **~2.0x** | **restated** |
| JEV-33 "the ~6s above the floor is contention" | ~6s | **~0.2s** | **withdrawn** |
| JEV-41 "wall-minus-API ~3.5s Haiku vs ~1.4s Opus" | 3.5 / 1.4s | **1.41 / 1.52s** | **ordering withdrawn** |
| A5.3 spawn contention | ~170ms | ~180ms | survives |
| `jev` sequential-vs-concurrent null | 565.7 / 564.6ms | unchanged | survives |

JEV-33's 16.5s was measured over the first 17 concurrent decisions, and **7 of
those 17** contain a contaminated arm — a 41% rate, because that sample sits
inside the busiest editing burst of the day. A per-decision wall is a **max**
over arms, so one contaminated arm carries the whole decision. The substantive
correction is that **the wall sits at the slowest arm and the "~6s of
contention" above it was the operator's hook.** Quote the restated 2.0x with
its n=17, and do not pool the full concurrent era for it: `cc_haiku45` changed
`arm_config_id` at 15:15:49Z and got much faster, so the 235-decision figure
(6.9s) measures JEV-41's fix as much as concurrency.

JEV-41's wall-minus-API gap was a **mean**, and Haiku had the highest
contamination rate. Clean, the gap is flat across arms — `cc_haiku45` 1.41s,
`cc_opus5` 1.52s, `cc_sonnet5` 1.59s — as a fixed spawn cost should be. JEV-41
used that gap to argue spawn does not explain Haiku's slowness; that conclusion
is **right and now much better supported**, and both its root causes stand.

**What is NOT removed.** Dropping the second mode does not leave a clean
number, and the report says so rather than implying otherwise:

- **≤~0.6s/row at p95** of fast operator `SessionStart` hooks, which sit inside
  the clean in-session mode alongside the preamble and are not separable from a
  row. The ceiling is the whole clean `in_session_ms` distribution (p50
  0.28-0.35s, p95 0.39-0.62s).
- **~1.1-1.3s/row of `spawn_ms`**, of which an unknown fraction is Claude Code
  loading the operator's settings and plugin manifests before it starts its own
  clock. Unresolvable from rows; bounded and disclosed.

**Rejected: suppressing the hooks — and note the obvious fix does not work.**
The hook is **plugin-registered** through `enabledPlugins`; the `hooks` block
in the operator's settings is already empty, so a `--settings '{"hooks":{}}'`
override — the move that mirrors the `--strict-mcp-config` the arm already
passes — would change nothing. That is the same wrong turn the earlier MCP
diagnosis took. The flag that *does* reach it is **`--bare`** ("skip hooks,
LSP, plugin sync, attribution, auto-memory, background prefetches, keychain
reads, and CLAUDE.md auto-discovery", from `claude --help`, zero spend). Not
taken, and now for three reasons rather than one: it makes auth **strictly
`ANTHROPIC_API_KEY` or `apiKeyHelper`** while the arm deliberately *pops*
`ANTHROPIC_API_KEY` to force subscription auth, so it would silently move which
billing surface is measured; it suppresses far more than the hook, making the
arm much less representative of Claude Code as deployed; and it would create a
fourth `arm_config_id` era boundary inside the window.
`src/arms/claude_cli.py` is untouched.

**What was built.**

| file | what it does |
|---|---|
| `src/latency.py` | the decomposition as pure functions over a row. `decompose` **refuses** a `jev` row, an `ok=False` row, or a row missing a clock, rather than returning zeros. `is_contaminated` cuts inside the empirical gap; `empirical_gap` is reported so a future corpus that fills the hole in invalidates the method loudly. `clean_baselines`, `adjusted_total_ms`, `dispatch_walls`, `summarise` |
| `src/latency_report.py` | writes `reports/jev43-wallclock.{md,json}`. **Not** a second `analyze.py`: it computes nothing about answers, labels, agreement, cost or thresholds |
| `tests/test_latency.py` | 19 tests, every number hand-computed. The two that matter: **threshold invariance** across 2/5/10/15/18s (the robustness argument, in code rather than in prose), and **`summarise` never pools across `run_context`** — which was a real defect, caught because the JEV-16 determinism sweep appends `replay` rows to the very file this report reads |

**For JEV-16, and it is not cosmetic.** The hook fired on the determinism
sweep's own rows while this analysis ran: `replay` / `cc-haiku45-cli-v2-nothink`
is **3 of 4 rows contaminated, 75%**, written at 17:26Z. That is independent
real-time confirmation of the mechanism, and a warning — **any latency quoted
from the determinism rows is contaminated at 75%**. An agreement result is
unaffected.

**Noticed, not repaired (not mine).** `data/runs/2026-09-20.jsonl` grew
mid-analysis: the JEV-16 determinism agent writing `replay` rows into the
shared append-only file. Nothing is wrong with that, but any
report over `data/runs/` that does not split on `run_context` is silently
pooling a live latency with a replay latency. Mine now does; `analyze.py` is
frozen and was not inspected for it.

---

## JEV-44: `src/arms/jev.py` does not parse under Python 3.11, and nothing pins the version

**Status:** done
**Labels:** defect, test

**Blocked by:** None

**What is wrong.** `src/arms/jev.py:237` uses a backslash inside an f-string
expression, which is a **SyntaxError before Python 3.12**. `tests/test_pipeline.py`
carries no `requires-python` header, so a bare `uv run` selects 3.11 and reports
**16 spurious errors** that have nothing to do with the code under test.

It fails identically at HEAD and was not introduced by any recent change.

**Why it matters more than a version nit.** A test suite that reports 16 errors
under a plausible default invocation trains its reader to ignore red. This study
already lost live captures to a test suite nobody had re-examined since the
surface went live (JEV-42); a suite that cries wolf is the same failure at one
remove.

- [x] Pin the Python version where it belongs — a PEP-723 `requires-python` header on the test modules, matching the convention already used elsewhere in `src/`
- [x] Either rewrite the f-string so it parses on 3.11, or state the floor explicitly and make the failure legible instead of a SyntaxError — **the floor is stated**; `src/arms/jev.py` is unchanged
- [x] Make `tests/run_all.sh` fail loudly on the wrong interpreter rather than producing 16 errors that look like real failures
- [x] Check every test module for the same missing pin

### Resolved: pin and assert, not raise the floor

**What was built.**

| file | what it does |
|---|---|
| `src/pyversion.py` | The floor in one place (`MIN = (3, 12)`), a pure `explain()` and a `require()` that exits **78** (`EX_CONFIG`) with a sentence. Imports nothing but `sys`, uses no f-strings and no annotations, so it **parses on 3.9.6** — a guard that raises `SyntaxError` is a second copy of the bug. Also runnable as a shell preflight: `"$PY" src/pyversion.py \|\| exit 1` |
| `tests/lib/require_python.sh` | Resolves `$JEV_PY` to an absolute interpreter (`$JEV_PYTHON`, else PATH), proves it against `src/pyversion.py`, and **prepends its directory to PATH** so the six shell tests underneath inherit it. Strict: a named interpreter below the floor fails, it is not silently replaced |
| `tests/run_all.sh` | Sources the resolver **before** `audit_live_writes.sh` — before any output a reader has to interpret. Every `python3` became `"$JEV_PY"` |
| `tests/*.py`, `tests/gate4_drain.py` | PEP-723 `requires-python = ">=3.12"` + `#!/usr/bin/env -S uv run --script`, matching `src/`, **plus** `pyversion.require()` at module scope. The header binds `uv run` only; `python3 tests/test_pipeline.py` ignores it, and that invocation is how the 16 errors were produced |
| `src/doctor.py` | `pyversion.require()` — it already had the header and is the entry point `README.md:52` tells people to run |
| `tests/test_python_floor.py` | 14 tests. The one that matters asserts the suite refuses **before doing any work**: not merely that it exits nonzero (it always did, after 16 errors), but that the `=== JEV-42 guard` banner never appears |

**Why not raise the floor.** Rewriting line 237 would make `test_pipeline.py`
*pass* under 3.11 while every header in `src/` still declares 3.12 — converting
a loud wrong-interpreter failure into a silent one, on an interpreter this
study has never been measured on. And it would not reach the case that
actually threatens JEV-37: `python3` under cron is `/usr/bin/python3`, which on
this machine is **3.9.6**, not 3.11. A 3.11 fix aims at the wrong target.
`src/arms/jev.py` is therefore untouched.

**Rejected: a `pyproject.toml`.** `requires-python` there would be the tidy
place for it, but no `pyproject.toml` exists, and adding one flips `uv` into
project mode for every `uv run` in the repo — a change to other people's
invocations, bought for nothing that the PEP-723 headers do not already give.

**The error count, measured rather than inherited.** Prior handover notes say
"16 errors is the known defect; a different count is your regression". Measured
at HEAD on 2026-09-20:

| interpreter | result |
|---|---|
| `/usr/bin/python3` 3.9.6 (**what cron gets**) | 16 errors |
| `/opt/homebrew/bin/python3.11` 3.11.15 (what a bare `uv run` got) | 16 errors |
| `/opt/homebrew/bin/python3` 3.14.7 | 0 errors |

All 16 are the same `SyntaxError`, reached through the lazy
`from arms import claude, jev` in `TestLiveArmWireFormats.setUp`
(`tests/test_pipeline.py:445`). So **16 is not diagnostic**: it is identical
across two interpreters five minor versions apart, and it tracks the size of
one test class — `test_pipeline.py` went from 89 tests to 104 during this
ticket's own wave, and the same 16 would have been 17 the moment anyone added
a test to that class. The rule was unusable; it has been replaced by a guard
that names the interpreter, so nobody needs to memorise a number.

`src/arms/jev.py:237` remains the only pre-3.12 syntax in `src/`, `tests/` or
`hooks/` — `python3.9 -m compileall` flags it and nothing else.

---

## Deferred: Phase 2

Not ticketed. Opens on explicit go-ahead: transcript harvest, blind labelling UI,
gold labels, Brier with Murphy decomposition, ECE, RPS, decision-curve analysis,
and the writeup.

## JEV-45: we may be paying ~245ms per Jev call for a gateway hop we never chose deliberately

Status: ready-for-agent
Labels: latency, arms, threat-to-validity, prior-art
Blocked by: none — but the decisive test is BLOCKED EXTERNALLY: `api.typesafe.ai` is waitlisted and we have no access

**Where this came from.** `clownware/bouncer` PR #33 (merged 2026-09-19) corrected
its own published Jev latency from ~190ms to a measured **437ms median / 549ms
p95** over 66 calls from an installed plugin, and decomposed it: ~95ms socket +
~193ms TLS + ~245ms request/model/response. The ~190ms had been measured by a
script that made one call and then looped **inside the same process over a
connection Node kept open**; a hook is a process per tool call, so every call is
the cold one. Their note: "it scales with distance to the host."

**The trap does not apply to us, and that is worth recording.**
`src/arms/timed_http.py:8` already says connection pooling "would hide exactly
the thing being measured", and opens a connection by hand per call.
`hooks/inline_shadow_bash.sh` shells out to `curl` — a fresh process, so a fresh
connection. `bench_inline.py` spawns the hook per iteration. All three
instruments measure cold. An independent party arriving at the same conclusion
from the opposite direction is a citation, not a correction.

**But the comparison surfaces something we did not know.** Our `jev` rows,
n=568 successful:

| | ours | bouncer |
|---|---|---|
| DNS + TCP + TLS (p50) | **72–79ms** | ~288ms |
| request + model + response | **~490ms** | ~245ms |
| total | **563ms p50 / 817ms p95** | 437ms p50 / 549ms p95 |

Our connection setup is **4× cheaper** than theirs and our server-side time is
**2× longer**. We are 29% slower overall on the metric that is co-primary.

**Three hypotheses, two already eliminated against our own data.**

1. ~~Concurrent dispatch (JEV-33) inflates it through contention.~~ **No.**
   Split by `arm_dispatch` on live rows: sequential **565.7ms** p50 (n=254) vs
   concurrent **564.6ms** p50 (n=213). Indistinguishable. This is also a partial
   discharge of A5.3's declared latency bias — for the API clock, concurrency
   costs nothing. (The ~170ms spawn contention measured under JEV-43 is a
   different clock and is unaffected by this.)
2. ~~Our payloads are bigger.~~ **No.** Pearson r(`input_tokens`, `total_ms`) =
   **0.046** across 568 rows. Median payload is 389 input tokens; the Q1 bucket
   sits at 548ms p50 and the Q3 bucket at 600ms. Jev's latency is near-constant
   in payload size over our range.
3. **The gateway hop.** We call `POST https://ai-gateway.vercel.sh/v1/evaluate`.
   Bouncer calls `POST https://api.typesafe.ai/v1/systemone` **directly**
   (their `CLAUDE.md:161`). That fits the decomposition exactly: a Vercel edge
   node is near us, so our TLS is fast; but our server-side time then contains
   the Vercel→TypeSafe leg that theirs does not. **~245ms — roughly half our
   Jev latency — may be a proxy we never chose deliberately.**

**Why this matters more than it looks.** Wall-clock is co-primary (A3.5). If the
treatment arm carries a ~245ms avoidable tax per call, every latency figure we
publish understates Jev and we will have made the classifier look worse than it
is — the mirror image of the mistake bouncer made in its own favour.

**We cannot test this. `api.typesafe.ai` is waitlisted and we do not have
access.** That converts JEV-45 from an experiment into a declared limitation
plus a finding, and the finding is arguably the more useful of the two.

**State it as a limitation, precisely.** The gateway hop is *consistent with*
the decomposition and is the only surviving hypothesis after concurrency and
payload size were eliminated — but it is **unproven**, because the one test that
would prove it requires an endpoint we cannot reach. The writeup says exactly
that: two causes excluded against 568 rows, one candidate remaining, untestable
from here. It does not assert the gateway as the cause.

**And state it as a finding, because it is one nobody has written down.** Every
Jev latency number in circulation — the vendor's 70-500ms, bouncer's measured
437ms — is against `api.typesafe.ai`. That endpoint is **not generally
available**. The path a member of the public can actually use today is the
Vercel AI Gateway, and on our machine it runs **563ms p50 / 817ms p95, ~29%
slower** than the number the ecosystem quotes. "The published latency figures
are for an endpoint most people cannot get" is a real deployment fact about
Jev-in-a-hook, and it is the kind of thing this study exists to surface.

**One cheap partial test we CAN run.** Jev is also served by Cloudflare Workers
AI. That is a second intermediary, not the direct path, so it cannot isolate the
vendor's own service time — but two intermediaries with different network
positions would show whether the ~490ms server-side term moves with the
intermediary at all. If it is identical on both, the gateway hypothesis weakens
considerably and the gap is more likely regional or contract-related. Worth one
canary-set sweep before the window closes, and worth nothing if access there is
also gated — check first, spend second.

**If access is granted mid-study, do not just switch.** Any endpoint change is a
new `arm_config_id` and a **third era boundary** after `cc-haiku45-cli-v1/v2`;
the paths differ (`/v1/evaluate` vs `/v1/systemone`) so JEV-02's four vendor
questions must be re-asked before a single row is trusted; and the gateway is
what `PREREGISTRATION.md`'s data-path disclosure describes, so who sees our
unredacted command text changes too.

**Acceptance criteria**

- [ ] The limitation written into `PREREGISTRATION.md`: two causes excluded, one
      candidate remaining, untestable because the endpoint is waitlisted. The
      gateway is **not** asserted as the cause.
- [ ] The finding written into the report: published Jev latency figures are
      against an endpoint that is not generally available; the publicly
      reachable path measures 563ms p50 / 817ms p95 here, ~29% above the best
      independent measurement of the direct path.
- [ ] Check whether Cloudflare Workers AI access is open to us. If yes, one
      canary-set sweep against it, decomposed, reported as a second
      intermediary and explicitly not as the direct path. If no, record that
      both alternatives are gated and stop.
- [ ] The eliminated hypotheses written into the report -- the null result on
      concurrency (565.7ms sequential vs 564.6ms concurrent) is itself the
      evidence A5.3 asks for, and the r = 0.046 on payload size bounds a
      confound we would otherwise have had to argue about.
- [ ] Waitlist status re-checked once before the writeup is frozen, so the
      claim "not generally available" is true as of publication, not as of today.

## JEV-46: `random_matched` — the third routing arm, and why it is NOT a static heuristic

Status: ready-for-agent — **unblocked 2026-09-21**, JEV-34 landed (`652d3e8`)
Labels: science, arms, prior-art
Blocked by: ~~JEV-34 (the surface)~~ — cleared. Wave A4, and it gates JEV-27.

*Not blocked by JEV-27, though JEV-27 is blocked by this. Building the arm is
independent of sizing the study: the mix is derived post hoc from `jev_routed`'s
realised behaviour, so no N is needed to implement it. The reverse direction is
real — you cannot size a three-arm study without knowing the third arm exists.
An earlier draft had both directions and was a cycle.*

**The problem this fixes.** With two routing arms — `default` (everything at
session tier) and `jev_routed` — a win confounds two effects: **(a)** the value
of tiering at all, and **(b)** the value of tiering *intelligently*. (a) is
already known to be large; (b) is the study's actual question. Five independent
sources (LLMRouterBench ACL'26, RouterArena, arXiv:2505.12601, Lynkr's own
RouterArena placement, RouteLLM's near-random MMLU result) find (b) is
frequently **zero or negative**. We currently cannot measure it.

**A static heuristic arm was considered and REJECTED on our own data.** Recorded
here so it is not re-proposed:

- The only static rule portable to `agent_route` is a subagent-type → tier map
  (AqueGen's design). Against `data/baseline/sessions.jsonl`, 29 sessions / 120
  delegated tasks: `general-purpose` **78 (65%)**, `claude-code-guide` 18 (15%),
  `Plan` 12 (10%), `Explore` 12 (10%). **On 65% of traffic the rule has no
  signal and degenerates to a constant** — it becomes `default` wearing a
  different label, and burns a third of the run budget reproducing an arm we
  already have.
- liteLLM's Explore/Implement/Verify rule — the one with the 46% saving — does
  **not** port. It switches phase after two consecutive matching *tool calls*,
  i.e. it observes a stream. `agent_route` decides **once, at delegation time**,
  on a task description. There is no phase sequence to observe. Citing that 46%
  for our surface would be carrying a number across a boundary where it does not
  apply.
- The only rule that *would* discriminate on our traffic is keyword-matching the
  task description — which is a worse Jev, hand-written by the party whose study
  benefits when it loses. That is precisely the strawman the plan's baseline-
  fairness commitment exists to forbid.

**What to build instead.** `random_matched`: a routing arm that assigns a tier
at random, with the tier **mix pinned post hoc to whatever mix `jev_routed`
actually produced**. Same cost profile, same cheap-model call rate, zero
information. It answers the sceptic's question directly — *is Jev's choice
better than chance at the same price?* — and there is no rule for a reviewer to
call badly written, because there is no rule.

It is also the convexity baseline Kapoor et al. (arXiv:2407.01502) require
before a Pareto comparison between two arms is legitimate at all: one can always
randomise between two policies, so any claimed frontier point must beat the
randomised interpolation.

**The cost, stated.** The mix cannot be pre-registered, because it is derived
from Jev's realised behaviour. Pre-register the **procedure**, not the numbers:
the arm runs in a second pass once `jev_routed`'s realised tier distribution is
known, with the seed, the mix and the freeze point recorded. An arm whose
parameters come from the data is a legitimate control only if it cannot be
re-tuned after seeing its own result — so the mix is frozen and committed
before the first `random_matched` run.

**Acceptance criteria**

- [ ] `random_matched` implemented as a routing arm (no classifier call, no
      network, no cost for the routing decision itself)
- [ ] Mix derived from `jev_routed`'s realised tier distribution, frozen and
      committed with its git hash before the first run
- [ ] Seed recorded on every row; assignment reproducible from the row
- [ ] Pre-registration amended: three routing arms, the procedure for deriving
      the mix, and the commitment that it is frozen before use
- [ ] The rejected static-heuristic option and its 65%-degeneracy evidence
      written into the writeup's design-rationale section — a reviewer WILL ask
      why there is no rule-based arm, and the answer is empirical, not lazy

## JEV-47: both routing arms must delegate identically, or we measure the delegation penalty

Status: ready-for-agent — **unblocked 2026-09-21**, JEV-34 landed (`652d3e8`)
Labels: science, threat-to-validity, prior-art
Blocked by: ~~JEV-34~~ — cleared. Wave A4.

**The finding.** `AqueGen/model-routing` published 7 days of telemetry with a
three-way comparison almost nobody makes: **`$1.36` doing the work inline <
`$1.68` routed to subagents < `$2.01` for the same subagent work at session
tier.** Delegating-and-routing came out **~24% MORE expensive than not
delegating at all.** Cause: a subagent starts with empty context, so you trade
cheap cache-*reads* in the main session for expensive cache-*writes* in the
subagent.

**Why this can invalidate our primary outcome.** If `default` ever runs work
inline while `jev_routed` delegates it, the cost difference we publish is the
delegation penalty with a routing label on it. Our design randomises assignment
*over the same delegated task*, so I believe both arms delegate identically —
**but that is currently a belief, not an assertion backed by a check.**

**What to build.** A per-row assertion and a report line, not an argument.

- Assert, in analysis, that every `decision_id` in the A/B has the **same
  delegation shape in both arms**: same number of spawned tasks, same spawn
  depth, same agent type. A mismatch is a hard failure, not a warning — this is
  the `state_sha256` equality assertion's sibling.
- Report **cache-write tokens per delegated task, per arm.** TwinRouterBench
  (arXiv:2605.18859) is the only source that prices the switching penalty:
  *"cache writes on tier switch are charged at the incoming tier's rate."* If
  one arm switches tiers more often, it pays more cache-writes at a higher rate,
  and that is a real cost of routing that belongs in the headline, not a
  footnote.
- Report **switches-per-trajectory** per arm.

**Acceptance criteria**

- [ ] Delegation-shape equality asserted per `decision_id`, failing loudly
- [ ] Cache-write tokens per delegated task reported per arm
- [ ] Switches-per-trajectory reported per arm
- [ ] If the shapes are not equal, the ticket stops and reports rather than
      normalising them away

## JEV-48: are we measuring tier fit, or just task difficulty?

Status: blocked
Labels: science, analysis, prior-art
Blocked by: JEV-36 (outcome measurement). **Moved from wave A3 to A7 on
2026-09-21**: JEV-36 sits in A6, so in the old numbering this ticket was
scheduled three waves before the ticket it depends on.

**The problem.** "Cost-Saving LLM Cascades with Early Abstention"
(arXiv:2502.09054) reports that *"error patterns of small and large models are
correlated, so small models can anticipate abstention decisions by large
models."* If the tasks Haiku fails are largely the tasks Opus also fails, then a
classifier that predicts "this needs the big model" is predicting **task
difficulty**, not **tier fit** — and routing cannot help, because there is no
tier at which the hard tasks succeed.

This is cheap to measure and expensive to be asked about after publication.

**What to build.** Per delegated task, the 2x2 of outcome by tier, and the
tetrachoric (or simple phi) correlation between cheap-tier failure and
frontier-tier failure, with a clustered CI. Plus the derived quantity that
actually matters: **the fraction of cheap-tier failures that the frontier tier
would have succeeded on** — that is the entire addressable headroom for routing,
and if it is small the study's ceiling is low regardless of how good Jev is.

**Acceptance criteria**

- [ ] Per-task outcome matrix by tier, from the JEV-29 blinded grader's scores
- [ ] Failure correlation with a session-clustered CI
- [ ] Addressable headroom reported as a headline-adjacent number
- [ ] Stated in the writeup whether the observed headroom bounds the result

## JEV-49: three known cost-pipeline bugs, and the reconciliation nobody has published

Status: done
Labels: cost, correctness, prior-art
Blocked by: JEV-38

**Three documented failure modes, each verified as filed by a third party.**

1. **`usage.iterations[]` asymmetry.** jverhoeks/claudecounter PR #26: a
   multi-round-trip turn logs `in=4/out=691` at top level against iterations of
   `(2,357)`, `(88762,1249)`, `(2,334)` — **88,762 input tokens invisible in one
   record.** The rule is asymmetric and easy to get backwards: **token fields
   MUST be summed from `iterations[]`; cache fields must NOT be, because the
   top-level value already equals the sum.** `docs/PLAN.md` and JEV-06 currently
   say "ignore `iterations[]`", which is half right and half wrong.
2. **Over-report by substring model matching.** `claude-spend#31`: `getPricing()`
   matched "opus" inside `claude-opus-5`, failed its version check, and fell
   back to **Opus 4.0 pricing ($15/$75 against the correct $5/$25)** — a 3x
   error across 96% of usage, compounded by duplicate rows (22,759 → 12,067 on
   dedupe by `requestId` + `message.id`). **A routing study introduces new model
   IDs into the transcript by definition, which is exactly the trigger
   condition.** `config_loader.cost_usd()` already returns `None` on an unknown
   model rather than guessing — verify the analysis treats that as a **hard
   failure**, not a coverage statistic quietly reported at the bottom.
3. **Cache-write multiplier depends on the auth path.** 1-hour cache writes bill
   at **2x**, not 1.25x (`ccusage#899`, $479 / 19% under-reported across ~40,000
   records before PR #1221 fixed it). And **TTL is 1 hour on a subscription but
   5 minutes on usage credits / an API key**, which decides *which multiplier
   applies*. Two runs of the identical experiment on different auth paths do not
   produce the same cost. **Our auth path must be declared in the
   pre-registration**, not inferred by a reader.

**And the thing nobody has done.** No published work reconciles
transcript-derived Claude Code cost against the **Claude Console usage page or
an invoice**. Anthropic's own docs state the local figure is computed "from
token counts at list price" — an estimate, not a billing record — and that the
prompt-cache stats line *"covers the main conversation only, not subagents"*,
i.e. first-party instrumentation goes silent exactly where this study lives.
One independent reconciliation puts the ceiling for any `~/.claude`-reading tool
at **~72% of the real bill**. Doing this reconciliation and publishing the
residual inoculates our headline cost number and is a contribution on its own.

**Acceptance criteria**

- [x] `iterations[]` handled asymmetrically, with a fixture proving both halves
      — `session_metrics.normalise_usage`, `TestUsageNormalisation`. The rule is
      **three-way, not two-way**: the `cache_creation` TTL sub-object follows
      the token rule, not the scalar rule. That third case is in no third-party
      report and is tested separately.
- [x] Dedupe by `requestId` + `message.id`; unknown model ID is a hard failure
      — `dedupe_key`, `UnpricedModelError`, `analyse(strict=True)`, and
      `render()` prints `LOWER BOUND` on the cost line itself. On this corpus
      the pair is equivalent to `requestId` alone (728 keys, 728 pairs); the
      659-vs-660 gap in the prep is `<synthetic>` rows, not retries.
- [x] Cache-write multiplier correct for our auth path; auth path declared in
      `PREREGISTRATION.md` — Amendment 8. **Claude Max 5× subscription** for the
      baseline and the `cc_*` arms (which `claude_cli.py` forces), Vercel AI
      Gateway for `jev`, and **no Anthropic API-key spend at all**. The
      multiplier is read per row from `usage.cache_creation`, not inferred from
      the path: both TTLs occur here.
- [x] Pre-/post-fix cost numbers reported for every row already collected —
      table below. **`data/runs/`'s 2,005 rows are NOT re-costed and cannot be**:
      they persist only the four scalar usage fields, with no `iterations[]` and
      no TTL split, so the corrections are inapplicable retroactively. The line
      that would persist them is handed to `claude_cli.py`'s owner in
      `.scratch/a3-prep/jev49.md`.
- [ ] **OPEN — Console.** Transcript-derived total reconciled against the
      Console usage page for a bounded window; residual published with its sign
      and its method. **What was done:** the bounded window is
      2026-09-19T19:58:56Z → 2026-09-20T14:50:13Z and the residual against
      **Claude Code's own `cost-state`** is **−$0.2234, −2.56%, negative by
      construction** (a transcript-derived figure is a lower bound: Claude Code
      bills background models it never transcribes). **What was not:** that is a
      reconciliation against a first-party *estimate*, not a billing record.
      There is no browser in this environment, and the spend is on a
      subscription, so it may not appear on the Console usage page at all.
      PREREGISTRATION A8.4 lists the four things the operator must supply. **No
      Console figure is asserted or estimated.**
- [x] `docs/PLAN.md`'s "ignore `iterations[]`" line corrected — all three sites,
      plus the stale 3.1× duplication factor (this corpus is 1.97×; 3.19× was a
      different corpus) and the `input_tokens: 2` overclaim.

**A fourth defect, found while measuring the other three and larger than any of
them.** Dedupe was keeping the **first** copy of a duplicated row. Claude Code
writes the same `(requestId, message.id)` repeatedly as a turn streams, and the
early copies are **placeholders** — `input_tokens: 2`, no `iterations[]`. Only
the last carries the completed breakdown. 48 keys here grow across their copies,
all 48 monotonically, **all 48 inside subagent transcripts**. See A8.2b.

**And one defect checked for and NOT found.** `anthropics/claude-code#95555`
(every top-level counter zeroed while `usage.cache_creation` stays populated)
occurs on **0 of 3,790 assistant rows**. The `input_tokens: 2` shape on 81% of
rows is normal cache-read behaviour and is **not** evidence for it.

**Pre-/post-fix cost, bounded window 2026-09-19T19:58:56Z → 2026-09-20T14:50:13Z
(15 sessions, 1,161 billable requests — the window `data/baseline/manifest.json`
snapshots):**

| figure | was | became | Δ |
|---|---|---|---|
| **baseline total** | **$125.582946** | **$175.354996** | **+$49.77 (+39.6%)** |
| — of which `iterations[]` summed | | | +$4.6857 |
| — of which completed-copy dedupe | | | +$29.8401 |
| — of which 1-hour cache writes at 2× | | | +$6.7505 |
| — of which `claude-opus-4-7` priced | | | +$8.4958 |
| sessions contributing $0.00 to the total | 14 of 15 | 0 of 15 | — |
| delegated-task total (n=20) | $42.5699 | $72.4099 | +$29.84 (+70.1%) |
| mean per delegated task | $2.1285 | $3.6205 | +$1.49 |
| SD per delegated task | $1.8119 | $2.7503 | — |
| fixture session (Redline `f0539211`) | $70.075211 | $75.756397 | +$5.68 (+8.1%) |
| — its residual vs Claude Code's own total | −27.55% | −21.68% | still negative |
| residual vs `cost-state`, 14 sessions | — | −$0.2234 (−2.56%) | — |
| `data/runs/` 2,005 run rows | $unchanged | $unchanged | not re-costable |
| web search | $0.00 | $0.00 | none in window |

**The +$29.84 lands almost entirely on delegated work**, which is why JEV-27 is
blocked on this ticket and not the other way round.

## JEV-50: retract the novelty claim — eleven independent Jev evaluations already exist

Status: ready-for-agent
Labels: writeup, correctness, prior-art
Blocked by: none

**We were going to publish something false.** The framing "nobody has measured
whether Jev can do this" appears in `docs/PLAN.md`'s problem statement and in
`SPEC.md`. Within five days of Jev's launch there are **at least 11 independent
Tier-A benchmarks** catalogued at `jevbench.xyz`, several pre-registered. The
claim is not merely overreaching; it is checkable and wrong, and a reader who
checks it stops trusting everything else.

**The replacement claim, which is both true and stronger.** Independent
evaluations exist and are **mixed-to-unfavourable**: Jev loses to Haiku 4.5 by
18.7pp on 2,000 phishing emails (McNemar p<0.0001) with **worse calibration**
(ECE 0.154 vs 0.097) and **loses to a regex on its own best single signal**
(89.4% vs 91.8%); loses to a supervised BGE encoder by 10pp on Banking77; and
returned AMBIGUOUS on a pre-registered baselines eval. Against that, an n=60
tool-call-risk benchmark found it well-behaved, with **no wrong answer at
confidence 1.000**. **Calibration is task-dependent and does not transfer** —
which is the justification for measuring it ourselves rather than citing anyone.
None of the eleven has been independently reproduced. **None measures tier
routing end-to-end**, and the five public Jev tier-routers for Claude Code
(`andrei10k/claude-jev-model-router`, `leftspace89/jevsubrouter`,
`flaviusapop/jev-router`, `0x7067/claude-jev` PR#4,
`togishima/subagent-dispatcher` PR#1) report **not one measured cost, wall-clock
or quality number between them.** That is the actual gap.

**Two pieces of first-party prior art must be cited or the paper looks naive.**
Anthropic's **"How we built Claude Code auto mode"** (2026-03-25) is Anthropic
shipping this architecture: a **single-token** stage-1 classifier, then a
reasoning stage 2 whose prompt is near-identical so it is **almost entirely a
cache hit from stage 1**, on Sonnet 4.6 regardless of session model, **fail-
closed**, with published FPR 8.5%→0.4% and a frank FNR of 17% they call "the
honest number". **We must explain why an external classifier beats that
design**, because it is cheaper than paying a vendor. Second: HAL
(arXiv:2510.11977) found the most expensive model on the Pareto frontier in
**only 1 of 9 benchmarks** — so our all-Opus control is probably off-frontier
and therefore a flattering comparator. Say it before a reviewer does.

**Acceptance criteria**

- [ ] The false claim removed from `docs/PLAN.md` and `SPEC.md`
- [ ] A related-work section citing the 11 benchmarks, the 5 tier-routers, and
      Anthropic's auto mode
- [ ] The off-frontier control acknowledged in limitations
- [ ] `.scratch/prior-art.md` folded in as the source, with its unverified items
      still flagged as unverified

## JEV-51: the kill switch does not stop the worker, and `stop` is ungraceful

Status: done
Labels: safety, reversibility, defect
Blocked by: none

**Found while stopping collection on 2026-09-20T21:42Z.** Three defects, all in
the shutdown path, all discovered because stopping the experiment took four
manual steps instead of one.

1. **`.jev-disabled` does not stop the worker.** The switch is checked by
   `hooks/capture.sh:53` and by `paths.killed()`, so capture stops — but
   `worker.py`'s main loop never consults it. With the switch engaged and a
   non-empty spool, the worker **keeps draining and keeps calling all four
   arms.** "Disabled" currently means "stops recording new decisions", not
   "stops spending money", and `run-collection.sh status` prints `capture:
   DISABLED` while the worker is still making API calls. JEV-40 proves OFF means
   vanilla *for the session*; it does not prove OFF means quiescent.
2. **SIGINT is ignored.** The worker is started as a background job, so the
   shell sets SIGINT to `SIG_IGN` and the `except KeyboardInterrupt` at
   `worker.py:366` — the only graceful exit that exists — is **unreachable in
   the way the worker is actually run.**
3. **`run-collection.sh stop` sends SIGTERM** (line 38) and nothing handles it,
   so the default disposition kills the process instantly, possibly mid-
   `_dispatch`, leaving a claimed file with no owner. **This is the unnamed
   cause behind JEV-31's stranded claims** — the startup reap addresses the
   crash half, and this is the other half.

**What to build.**

- `worker.py` consults the kill switch at the top of every cycle and before
  every dispatch: switch present → drain nothing, call nothing, log a single
  line, keep polling so it resumes when the switch is removed.
- A `signal.signal(SIGTERM, ...)` handler that sets a flag, finishes the
  in-flight capture, releases the claim, and exits 0. `SIGINT` mapped to the
  same handler so it works in a background job.
- `run-collection.sh stop` waits for the handler, verifies `spool/claimed/` is
  empty, and reports if it is not.
- `run-collection.sh status` distinguishes **capture disabled** from **worker
  quiescent**, because today it conflates them.

**Acceptance criteria**

- [x] Kill switch engaged + non-empty spool → zero API calls, proven by a test
      that counts arm invocations —
      `tests/test_worker_lifecycle.py::TestKillSwitchStopsDispatch`. The counter
      patches `arms.fake.evaluate`, which is what `worker.evaluate_one` actually
      reaches through `load_arm_module(config.kind)`; patching the wrapper would
      have counted the wrapper. Paired with a **control** in which the switch is
      absent and the same drain calls the arm every time, so the assertion
      cannot pass on a drain that is merely broken. Red before the fix:
      `Lists differ: ['fake', 'fake', 'fake'] != []`
- [x] SIGTERM and SIGINT both exit cleanly with `spool/claimed/` empty — both
      mapped to one flag-setting handler. SIGINT gets an **explicit** handler
      rather than `except KeyboardInterrupt`, because under `nohup ... &` the
      shell sets SIGINT to `SIG_IGN` and Python inherits it; `signal.signal`
      also resets that inherited disposition, which is what makes Ctrl-C work on
      a background job at all. The poll uses `Event.wait`, not `time.sleep` —
      PEP 475 retries an interrupted sleep once a non-raising handler returns,
      so a stop one second into an idle 30s poll would otherwise wait out the
      remaining 29
- [x] A test that SIGTERMs a worker mid-dispatch and asserts no stranded claim —
      `TestGracefulStop`, a **real** subprocess running the real `worker.main()`
      against a sandbox root (`tests/worker_driver.py`), signalled while an arm
      is provably in flight. Asserts exit 0, empty `claimed/`, a completed run
      row for the in-flight capture, and the unclaimed captures still in
      `ready/`. Red before the fix: `-15 != 0` and
      `stranded claim after SIGINT: ['pre_bash__80-0.json']`
- [x] `status` reports capture state and worker state as two separate facts —
      `worker: RUNNING (pid N), draining` vs `worker: RUNNING (pid N) but
      QUIESCENT`, printed independently of the `capture:` line.
      `tests/test_collection_control.sh` §1 asserts the distinction is driven by
      the switch
- [x] `docs/REVERSIBILITY.md` updated: the one-command path to fully quiescent —
      new section *"Fully quiescent"*, with the three states as a table and the
      honest cost of a graceful `stop`

**Also done, beyond the criteria.** `run-collection.sh stop` waits for the
handler (bounded at 300s — a dispatch is bounded by the slowest enabled arm's
`timeout_s`, 180s for the `cc_*` arms and 240s for `cc_fable51`), prints that
bound and a progress line every 15s so it does not read as hung, removes the
pidfile only once the process is gone, and **exits non-zero naming the count**
if `spool/claimed/` is not empty.

**A test-fixture defect surfaced by this work, fixed here.**
`tests/test_pipeline.py:TempStorage` never repointed `paths.KILL_SWITCH`, which
was harmless only while nothing in the worker read the switch — with
`.jev-disabled` present for the whole of Phase A, its two drain tests would have
run against the *live* switch and asserted on an empty result. It also laid
`claimed/` and `dead/` out as siblings of `spool/` while `drain_once` reached
them as `paths.SPOOL / "claimed"`: one directory in production, two in the
fixture, which is exactly how a test about `claimed/` passes while touching
nothing. Both corrected, and `worker.py` now uses `paths.SPOOL_CLAIMED` /
`paths.SPOOL_DEAD` rather than re-deriving the paths.

## JEV-52: the activation gate — the single deliberate act that turns the experiment on

Status: blocked
Labels: gate, safety, science
Blocked by: **every ticket in Phase A**, and as of 2026-09-21 the list below is
read off the wave table rather than maintained by hand — which is how it came to
omit six tickets, including two the gate's own steps depend on:

| wave | blockers |
|---|---|
| A1 | JEV-30, JEV-31, JEV-31b, JEV-44, JEV-51 |
| A2 | JEV-16 (Run A), JEV-32, JEV-43, JEV-49 |
| A3 | JEV-17, JEV-28, JEV-29, **JEV-34** |
| A4 | JEV-25, JEV-46, JEV-47, **JEV-55** |
| A5 | JEV-27, JEV-35, JEV-50 |
| A6 | JEV-36, JEV-37, JEV-39 |
| A7 | JEV-45, JEV-48, **JEV-56** |

**The six that were missing, and why two of them matter more than bookkeeping:**
JEV-37, JEV-39, JEV-45, JEV-55 were absent entirely; JEV-12 and JEV-54 were
absent and have since moved to Phase B, so they are correctly not blockers.

- **JEV-37 is a prerequisite of this ticket's own step 5.** The gate requires a
  canary baseline sweep recorded before the window opens, and 37 is the ticket
  that builds the scheduler and wrapper to record it. The gate was blocking on
  everything except the thing one of its steps runs.
- **JEV-55 is a prerequisite of this ticket's own step 6.** The amendment must
  state the primary interval, and 55 is the ticket deciding whether that
  interval can be computed at all. Amending the pre-registration before 55
  reports would commit us to a metric we already know is degenerate.

**JEV-34 is `done` but carries one deferred box** — the live spawn-latency
measurement, which Phase A cannot perform. This gate must not read 34 as fully
closed: the surface is proven inert, not proven cheap.

**Why this ticket exists.** The operator's constraint is that the system is
dev-complete before any part of it goes live. A rule in prose is not a gate — an
agent reads `Status: ready-for-agent` and starts, and the rule was in a section
it never opened. So the gate is a **ticket**, every Phase B ticket lists it as a
blocker, and turning anything on without it closing is a board violation
visible in `git diff`.

The failure mode this prevents is *partial* live state, and we have hit it four
times already: a test suite that destroyed live captures (JEV-42), five config
fields that looked live and were inert (JEV-31b), a kill switch that stopped one
writer and not the other (JEV-51), and an arm misconfigured for six hours before
anyone looked at its numbers (JEV-41). Every one was cheap offline and expensive
live.

**Current state, frozen 2026-09-20T21:42Z.** `.jev-disabled` engaged; worker
terminated; `spool/{ready,claimed,tmp,dead}` all empty; hook verified to exit 0
without capturing. **571 captures, 2,005 run rows** already collected under the
pre-gate configuration — these are NOT discarded, but they carry pre-gate
`arm_config_id`s and the era rules in `PREREGISTRATION.md` A7 govern whether
they pool with anything collected after.

**This ticket is done by ONE agent with no parallelism.** It is a sequence, and
a step that fails stops the sequence rather than being worked around.

**The sequence**

1. **Full suite green**, run through `tests/run_all.sh` so `audit_live_writes.sh`
   runs first. Green from a clean checkout, not from a working tree with
   uncommitted fixes.
2. **`tests/reversibility.sh` green** — OFF provably means vanilla (JEV-40).
3. **JEV-51's proof executed, not assumed**: kill switch engaged plus a
   non-empty spool ⇒ **zero arm invocations**, counted by a test rather than
   observed by eye. This is the step that was missing when collection was
   stopped by hand.
4. **`run-collection.sh status` reports capture state and worker state
   separately** and both read OFF.
5. **A canary baseline sweep recorded while still disabled**, so drift has a
   reference from the first live hour rather than from whenever someone
   remembers (JEV-37). Its `arm_config_id` and `canary_set_id` are recorded.
6. **`PREREGISTRATION.md` amended and committed, with its git hash quoted**,
   covering everything settled during Phase A: three routing arms and the
   `random_matched` procedure (JEV-46); the declared auth path and cache-write
   multiplier (JEV-49); the Jev endpoint limitation and the waitlist (JEV-45);
   the corrected Amendment 6 loss bound; fail-open and escalation semantics
   (JEV-35); the era rules for the 2,005 pre-gate rows.
7. **A dated inventory of what is about to become live**: which hooks are
   registered, which surfaces are in which mode, which arms are enabled, and
   the `arm_config_id` of each. Committed. This is the document that makes
   "what was running on day N" answerable later.
8. **Only then**: remove `.jev-disabled`, start the worker, register the first
   surface. In that order, one at a time, with `status` checked between each.

**What this ticket must NOT do.** It does not fix anything it finds. A failure
at any step reopens the relevant Phase A ticket and the gate stops. The
temptation to patch a small thing in order to finish the sequence is exactly how
partial live state gets created, and it would be the fifth instance.

**Acceptance criteria**

- [ ] Steps 1-5 executed and their output pasted into the ticket, not summarised
- [ ] Pre-registration amended, committed, hash recorded here
- [ ] Live inventory committed
- [ ] Kill switch removed, worker started, first surface registered — in that
      order, with `status` output recorded between each
- [ ] A named rollback: the exact command sequence that returns to this frozen
      state, tested once before the switch comes off

## JEV-53: the writeup — and the seven criteria across the board that have nowhere to land

Status: blocked
Labels: writeup, science
Blocked by: JEV-12 (figures and export), JEV-23 (the experiment), JEV-50
(related work and the retracted claim), JEV-48 (headroom), JEV-52

**The gap this closes.** Seven unchecked acceptance criteria on other tickets
say some version of "report it in the writeup" — JEV-24a's external-validity
anchor, JEV-45's endpoint limitation, JEV-46's rejected-arm rationale, JEV-47's
delegation check, JEV-48's headroom bound, JEV-50's related work, JEV-12's
figures. **There was no writeup ticket.** Those criteria could never be ticked,
which means seven tickets could never reach `done`, which means the board's
completion state was unreachable by construction. `docs/PLAN.md` deferred the
writeup to "Phase 2, on your go" and nothing carried it.

**What to build.** The paper, assembled from artifacts that already exist rather
than written fresh — if a number is not already in `reports/` or a committed
fixture, it is not in the paper.

**The non-negotiables, all already pre-registered and listed here so one
document owns them:**

- **The scope stated in the abstract**: n=1 operator, one machine, one repo. An
  honest n=1 study is publishable; one dressed as a benchmark is not.
- **"Accuracy" does not appear** in any Phase 1 claim. Every agreement axis
  reads "agreement with <arm>", and the disclaimer is in the abstract, not a
  footnote.
- **Base rate and majority-class baseline printed beside every agreement
  statistic.**
- **Synthetic and live never pooled**, and every synthetic result labelled.
- **The data path disclosed**: unredacted command text and prompts transit the
  Vercel AI Gateway and the Anthropic API.
- **The pre-registration's git hash quoted**, and every amendment listed with
  the date it was made and whether it preceded the data it governs.
- **Attrition reported**, including the losses that structurally cannot enter
  the attrition count — JEV-31, JEV-32, JEV-33, JEV-42 — and the corrected
  Amendment 6 bound with its unsampled first fourteen minutes.
- **The off-frontier control acknowledged**: HAL found the most expensive model
  on the Pareto frontier in only 1 of 9 benchmarks, so all-Opus is a flattering
  comparator and we say so first.
- **The price table pinned with a date** (HAL's rule), and raw token counts
  published so a reader can recompute at their own prices.

**Acceptance criteria**

- [ ] Every "report in the writeup" criterion elsewhere on the board is
      satisfied and its box ticked, with this ticket naming which section
      satisfies it
- [ ] Every non-negotiable above present and checkable by a reader
- [ ] No number in the paper that is not traceable to a committed artifact
- [ ] A reproduction section: what a reader would have to run, and what they
      cannot reproduce because it needs our transcripts or a waitlisted endpoint

## JEV-54: does Jev do better with richer input? Test it offline before changing the hook

Status: blocked — **on spend, not on the instrument**. Wave B1.
Labels: science, arms, state
Blocked by: ~~JEV-16 (owns `replay.py`, the instrument this needs)~~ — cleared.
JEV-16 Run A landed and `replay.py` exists, with `--determinism` selection and
`config_fingerprint` stamping fixed. **The instrument is ready; the sweep is
not funded.** This ticket postdates the 2026-09-20 spend decision that cut Phase
A to ~90 calls and it was never costed into it, so it moves to **B1** with the
other deferred replay sweeps (22, 10, 16 runs B+C) rather than quietly spending
against a budget that is already committed.

**Partly overtaken by JEV-34.** `agent_route`'s state builder adopted this
ticket's central argument — use the payload fields already captured and free —
and cites it in `build_agent_route`. What remains here is the *`pre_bash`*
question, which is the harder one, because `pre_bash` has a 487-row legacy
corpus and enriching it forks an era boundary that `agent_route` did not have.

**The question.** Jev currently receives three facts and nothing else. From
`state_builders.build_pre_bash` (`src/state_builders.py:52-60`):

```
Command:
ls && ls data 2>/dev/null | head -20

Working directory: /Users/aadharagarwal/projects/JEV-experiments
```

plus a `Stated purpose:` line when the tool call carries a description. Median
343 input tokens. The question is whether that is why answers look the way they
do.

**First, the thing enrichment will NOT fix.** Across 487 live decisions
`destructive` never crossed tau=0.5 — max **0.16**, median 0.01, 481 of 487 in
[0.0, 0.1). That is a **base rate** problem, not an information problem. No
amount of context makes `ls` destructive. Richer input cannot rescue the live
`destructive` signal and this ticket does not claim it will; that is what the
synthetic stress set (JEV-10) is for.

**Second, where it plausibly DOES help.** `needs_review` has median **0.49**
across the same 487 rows — Jev is hedging almost exactly at the coin flip. That
is the signature of a question it cannot discriminate on the evidence given,
which is a *candidate* information problem and worth testing.

**Third, the constraint that rules out the obvious approach.** `hooks/capture.sh`
is `cat > tmp; mv; exit 0` — it does no parsing at all and spools the raw payload
for the worker to interpret later. Adding `git status` to answer "is this
recoverable from version control" would cost 50-500ms on every Bash command
against a <10ms budget, and plan decision #1 exists precisely to forbid it. Any
enrichment must be free at capture time or it is not enrichment, it is a tax on
every tool call in the session.

**Fourth — the opening. We are already discarding context we captured.** Every
capture row carries `agent_type`, `permission_mode`, `is_sidechain`, `cwd`,
`prompt_id` and `tool_use_id`. **None of them reach Jev.** They cost nothing —
they are already on disk for all 571 captures — and they are exactly the kind of
fact that separates "a human should look at this" from "this is routine": a
command issued under `permission_mode: auto` inside a sidechain by a subagent is
a different object from the same bytes typed by a human at the top level.

**So this is testable offline, retroactively, for the price of a replay sweep,
with no era boundary and no hook change.**

## What to build

An A/B of state builders over the **existing** corpus:

- **arm A — `state-builders-v1`**: exactly what shipped. Already on disk; no
  calls needed for the control if existing rows are reused.
- **arm B — `state-builders-v2-context`**: v1 plus the capture-row fields listed
  above, rendered as labelled lines in the same shape as the existing state.

Re-ask the frozen `pre_bash/v1#a` question set over both, paired on
`decision_id`. Report: change in `needs_review` distribution (does the mass move
off 0.49?), change in `destructive` (expected: none — state it either way),
agreement between builders, and whether any decision flips at tau.

**This is a state-builder experiment, not a question-set change.**
`questions/*/v1.json` stays frozen. Two builders, one question set.

## Non-negotiables

- **v2 is a new `state_builder_version` and therefore a new `state_sha256`.**
  Rows from the two builders never pool. The §5 byte-identity assertion is
  per-builder, not across.
- **Both arms must see byte-identical state within a builder.** The existing
  cross-arm assertion still applies.
- **Do not change the live hook or the live builder on the strength of this.**
  Switching `pre_bash` to v2 in production is a separate decision with its own
  era boundary, and it would be taken at JEV-52 or not at all.
- **Leakage check.** Every field proposed must be present in the hook payload at
  capture time. `agent_type`, `permission_mode`, `is_sidechain` are. Anything
  requiring a read of the live transcript or the filesystem at worker time is
  **forbidden** under plan decision #7 — it would let the arm see a future the
  enforce path does not have.

## The enrichment this ticket deliberately does NOT attempt

**Git-relative recoverability** — whether the paths a command touches are
tracked, ignored, or absent. This is the single most relevant fact to the
`destructive` question as worded ("cannot be recovered from version control or a
backup") and Jev currently has no access to it whatsoever. It is excluded
because it cannot be computed inside the hook's budget. The viable design, if
this is ever pursued, is a **sidecar sampler**: a process writes a small git-state
summary to a file every N seconds and the hook `cat`s it, costing one file read.
That is a real piece of engineering with its own era boundary, and it should not
ride along on an experiment. Recorded here so the idea is not lost.

## Where richer input actually matters most, and it is not this surface

**`agent_route` (JEV-34, wave A3) was built on 2026-09-21 (`652d3e8`) and
adopted this argument — see the note at the top of this ticket.** SWE-Router
(arXiv:2607.00053) finds that routing on a task description alone "inherits an
information-theoretic Bayes-error floor in agentic settings: a similar issue can
hide either a localized typo or a multi-module refactor, and the prompt does not
separate the two" — and that routing on a partial trajectory instead was worth
**+15.3pp Route-AUC**. Our `agent_route` state is currently specified as
description-only, i.e. exactly the K=0 router that paper measures a floor for.

**Design `agent_route`'s state rich from the start.** There is no legacy corpus
to split, no era boundary to pay, and the literature says this is where the
information actually is. That is a change to JEV-34's scope and is filed as such
rather than smuggled in here.

**Acceptance criteria**

- [ ] `state-builders-v2-context` implemented alongside v1, both selectable
- [ ] Every v2 field verified present in the capture-time payload; the leakage
      argument written per field, not asserted once
- [ ] Paired A/B over the existing corpus on the frozen question set
- [ ] Reported: `needs_review` distribution shift, `destructive` shift (expected
      none), inter-builder agreement, flips at tau
- [ ] A recommendation with evidence on whether `pre_bash` should switch, and an
      explicit statement that switching is JEV-52's decision, not this ticket's
- [ ] JEV-34's state design revisited in light of the SWE-Router finding

## JEV-55: the clustered bootstrap has ONE cluster — the primary interval cannot be computed

Status: ready-for-agent — **leads wave A4**, ahead of JEV-27
Labels: science, blocking, threat-to-validity
Blocked by: none. **This gates JEV-27 (power analysis), JEV-52 (the gate) and
the primary metric itself.** Until 2026-09-21 it appeared in **no wave** and in
**none of JEV-52's blockers**, so the most load-bearing open ticket on the board
was invisible to anyone reading the execution plan alone. Both are now fixed.

**Measured 2026-09-20, verified directly.**

```
run rows by context : live 1783 | synthetic 180 | canary 42 | replay 38
DISTINCT session_id among LIVE rows : 1
   4ba49645-fb8d-4fb2-b496-c274f6ed1490   1783
```

All 1,783 live run rows carry **one** `session_id` — this session. The other
three "sessions" visible among captures (`synthetic-destructive`,
`synthetic-benign`, `synthetic-borderline`) are stratum labels on the synthetic
set, not real sessions.

**Why this is a headline problem, not a bookkeeping one.** The primary metric is

> PABAK between `jev` and `cc_opus5` on `pre_bash.destructive`, **with a 95%
> bootstrap CI clustered on `session_id`** (§2)

and §A1.1 rules an interval inconclusive below 30 clusters. **We have 1.**
Resampling clusters when there is one cluster returns the same cluster every
time: the interval is degenerate, not merely wide. The primary interval as
pre-registered **cannot be computed from any amount of data collected this way**
— collecting for seven days instead of one changes N and does not change the
number of clusters.

This is the exact failure the plan named as the thing "a stats-literate reader
would attack first" (`docs/PLAN.md`, metrics section), and the defence was
clustering. The defence does not currently exist.

**Cause, and it is structural rather than a bug.** The isolation requirement
confines the hook to this repository, and the work in this repository has been
one continuous operator session. Sessions are long here by nature: the unit that
makes decisions correlated — same repo, same task, same commands repeated — is
precisely the unit we have exactly one of.

## What this ticket must decide

Not "fix the bootstrap". Choose, with the reasoning recorded, between:

1. **Change the clustering unit.** `prompt_id` is already on every capture row.
   Decisions inside one user prompt are strongly correlated; across prompts much
   less so. That yields many clusters immediately. **The cost is that it is a
   weaker claim** — it controls for within-prompt correlation but not for
   within-session effects like a repeated `npm test`, which is the correlation
   §A1.1 was written about. Any change here is a pre-registration amendment and
   must be argued, not asserted.
2. **Collect across many sessions.** Honest, and changes the stopping rule from
   "seven calendar days" to something with a session count in it. Note the
   operator cannot be instructed to fragment their work without changing the
   behaviour being measured — that is itself a confound (cf. JEV-24a/24b).
3. **Report the primary interval as uncomputable** and demote PABAK's CI to a
   point estimate with the limitation stated. Permitted by §6, which already
   pre-commits to publishing "the live sample cannot support a discrimination
   claim" as a finding. Least satisfying, most honest, and **requires no
   amendment** because §6 anticipated it.
4. Some combination: e.g. report the point estimate as headline, a
   `prompt_id`-clustered interval as clearly-labelled secondary.

**Whatever is chosen, the naive-vs-clustered comparison the plan promised must
still be published**, because the gap between them is now the finding rather
than a footnote.

## Interacting facts already on the board

- **The live corpus is two arm-set eras** (JEV-32): 531 three-arm rows and 1,252
  four-arm rows. Any resampling scheme has to respect that boundary or it pools
  across a concurrency-regime change.
- **`destructive` never crossed tau in 487 live decisions** (max 0.16). Even with
  perfect clustering the live `destructive` signal is degenerate, so this ticket
  and the base-rate problem compound rather than substitute.
- **PointFive's ICC finding** (`.scratch/prior-art.md`): 712 runs per arm bought
  ~38-45 effective tasks at ICC 0.37-0.55. Our effective sample is smaller than
  our row count by a factor nobody has computed yet. **Compute it.**

**Acceptance criteria**

- [ ] The effective sample size computed and reported, not just the row count
- [ ] A decision among the options above, with the argument written down
- [ ] If the clustering unit changes, a drafted pre-registration amendment that
      states what the new unit does and does not control for
- [ ] Naive-vs-clustered intervals published side by side whatever is decided
- [ ] JEV-27's power analysis re-scoped to size on clusters, not rows
- [ ] The limitation stated in the abstract, not a footnote

---

## JEV-56: `reversibility.sh` cannot be green on a clean checkout, which is what the gate demands

Status: ready-for-agent
Labels: defect, gate, safety
Blocked by: none. **It blocks JEV-52 step 1 as that step is currently worded.**

**Found 2026-09-21** during the board reconciliation, by running the full suite
from a fresh worktree rather than from the working checkout.

**The contradiction.** JEV-52 step 1 requires the suite green *"from a clean
checkout, not from a working tree with uncommitted fixes"* — the right instinct,
and the step that would have caught JEV-42. But `tests/reversibility.sh`
**cannot** be green on a clean checkout. Four of its 42 gates fail:

```
FAIL  no .claude/settings.local.json -- the enumeration gate would pass vacuously
FAIL  no registered hook handlers found -- this gate must not pass on an empty set
FAIL  the hook did not run with the switch off; 3a would prove nothing (0 captures)
FAIL  the parked registration is missing or altered
```

All four have one cause: they need `.claude/settings.local.json`, and that file
is **gitignored by design** — deliberately, for the reason the README gives, so
live hooks never travel to a clone or a cloud session. The two requirements are
individually correct and jointly unsatisfiable.

**Why this is not pedantry.** The four gates are failing *correctly*. Each is a
guard against passing vacuously on an empty set, which is the discipline this
repo keeps everywhere else. The defect is in the gate's wording, not the tests.
As written, step 1 can only be satisfied by hand-copying an ignored file into a
clean checkout — an undocumented manual step in the middle of the one ceremony
the board designed to have none.

**It also weakens the proof we actually publish.** `OFF IS PROVEN EQUAL TO
VANILLA` is currently asserted against *the operator's own registration*, which
is not the registration a reader cloning this repo would get. That is a smaller
claim than `docs/REVERSIBILITY.md` implies.

**What to decide** — a wording-and-fixture ticket, not a test rewrite:

- [ ] Define what "clean checkout" means for a repo whose hook registration is
      intentionally untracked. Most likely: clean checkout **plus a committed
      fixture registration** the script materialises into a temp dir itself
- [ ] Commit `config/settings.local.example.json` or equivalent, and have
      `reversibility.sh` install it when no real registration exists — so the
      gates test a *known* registration rather than whatever the operator happens
      to have lying around
- [ ] Separate the two questions the four gates conflate: *"is a registration
      present and correct?"* (needs a real file) and *"does OFF equal vanilla?"*
      (needs only a registration, real or fixture)
- [ ] Reword JEV-52 step 1 to match, and state the manual step explicitly if one
      survives
- [ ] Note in `docs/REVERSIBILITY.md` what the proof is currently made against

**Blocks nothing but the gate.** Every other wave is unaffected; this only has to
land before JEV-52 runs.

