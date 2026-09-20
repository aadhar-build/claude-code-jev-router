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

Eight waves, **at most four agents at a time**. The waves are shaped by two
constraints that matter more than dependency order:

**1. Two agents must never own the same file.** Most of the serialisation below
is this, not a real dependency — JEV-30 and JEV-31 do not interact with JEV-33's
problem at all, they just live in the same drain loop. Where that is the only
reason, the ticket says so, so nobody mistakes a scheduling artifact for a
design constraint.

**2. One new surface registration per collection window.** Two capture hooks
landing together makes the capture stream uninterpretable: a change in volume or
base rate cannot be attributed to either. This is why JEV-18, JEV-19, JEV-20 and
JEV-35 are spread across the tail rather than batched.

Three standing rules for any agent picking up a ticket:

- `src/stats.py`, `src/analyze.py` and `questions/*/v1.json` are **frozen**
  (`PREREGISTRATION.md` §8). A change to any of them is a defect fix, its own
  commit, with the reason stated and pre-/post-fix numbers reported.
- **Only one ticket per wave may write to `data/runs/`.** A live worker is
  already appending there; adding two more writers makes attrition
  unattributable.
- The worker may be restarted, but **reap `spool/claimed/` back to
  `spool/ready/` first** (JEV-31) or the restart loses whatever was mid-flight.

| wave | tickets | why these together |
|---|---|---|
| **1** | **33**, **38 + 24a** (one agent), **15**, **40** | Nothing blocks any of them, and they touch disjoint areas: the drain loop, the transcript corpus, the gate suite, the kill switch. 38 and 24a share an agent because they read the same corpus and face the same retention risk. **40 is here rather than later so a way back to vanilla exists before anything is built on top of it** |
| **2** | **30 + 31** (one agent), **31b**, **16**, **37** | 30 and 31 wait only because JEV-33 is rewriting the file they live in. 16 is the wave's single `data/runs/` writer |
| **3** | **22**, **34**, **27**, **32** | 34 unblocks once 15 has parameterised the gates; 27 unblocks once 38 has persisted the cost distribution. 22 is the single data writer, and produces the Fable session JEV-28 needs as a by-product |
| **4** | **28**, **29**, **17**, **10** | 17 unblocks once 16 has the flip rate. 28 consumes what 22 produced. 10 is the single data writer |
| **5** | **35**, **25**, **12**, **39** | 35 turns the routing hook into an actuator — it requires both 34 (the surface) and 40 (a proven way back). 12 follows 10 |
| **6** | **36**, **24b**, **18**, **09** | 36 follows 35. 18 is the window's next surface registration, held back because 35 already registered one |
| **7** | **23**, **19** | The experiment itself, plus the next surface in the one-at-a-time queue |
| **8** | **20** | Last surface |

### The two things that should not wait for a wave

**JEV-38 is the most time-sensitive item on the board** and it is in wave 1 for
that reason. It is not urgent because it unblocks much — it unblocks JEV-27.
It is urgent because **its source data lives outside this folder, in
`~/.claude/projects/`, under a retention policy we do not control and have never
written down.** Routing can be built next month; a rotated transcript cannot be
recovered at any price. The same exposure applies to JEV-24a, which is why they
share an agent.

**JEV-40 comes before anything that changes behaviour.** Everything built so
far only watches, so the existing kill switch has never had to mean more than
"stop recording". From JEV-35 onward it has to mean "stop deciding, and let the
default happen exactly as it would have" — a stronger claim that has never been
asserted, because nothing has ever rewritten a tool input before. Building the
actuator first and the way back second is the wrong order.

**JEV-33 is the throughput blocker.** Until it lands, the spool grows during
every working session, and past 500 files the hook fails open and drops captures
silently. Every wave after this one adds load.

### What the plan deliberately does not parallelise

**The routing chain 34 → 35 → 36 → 23 is strictly serial**, across four waves.
It is the longest path on the board and the obvious candidate for compression,
and it should not be compressed: the whole reason it was split was to put a
verifiable checkpoint between "the classifier decides" and "the decision changes
what runs". Collapsing the waves removes exactly that checkpoint.

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

**Status:** in-progress
**Labels:** hooks, hot-path
**Blocked by:** None. **Not blocked — stalled on two decisions**, which is different and should not read as blocked: whether to register the inline hook live alongside `capture.sh`, and what `--max-time` should be given the 2.0s default sits BELOW Jev's 2,681ms p99.

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
**Blocked by:** None. The sweeps needed credentials and now have them. **JEV-16 is the determinism sweep split out** because it gates enforcement; the other three sweeps (phrasing, option-order, truncation) stay here.

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

**Status:** ready-for-agent
**Labels:** science, blocking
**Blocked by:** None. Avoid running it at the same moment as another process writing `data/runs/` — see the execution plan.

**What to build:** The measurement that decides whether Jev can ever enforce.
`src/determinism.py` is written and correctly **exits non-zero** rather than
reporting a green result on absent data. `replay.py --determinism N` has never run.

- [ ] Run `replay.py --determinism 20 --arms jev` over a stratified sample — Jev-only costs pennies; the `cc_*` arms would cost hours and are not what is in question
- [ ] Report flip rate bucketed by |p − τ|; the hypothesis is that flips concentrate near τ and vanish away from it
- [ ] Resolve the 41%-occupancy concern: at τ=0.95 on `needs_review`, 24/59 synthetic items sit within 0.05 of the threshold
- [ ] If flips are confined to a narrow band, enforcement is viable with a dead-zone rule; if not, `needs_review` cannot enforce at any threshold

---

## JEV-17: Replace the fitted thresholds with a rule

**Status:** blocked
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
**Blocked by:** JEV-15

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
**Blocked by:** JEV-18

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
**Blocked by:** JEV-19

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
**Blocked by:** None. **It incidentally produces the real Fable session JEV-28 needs** — if this runs first, JEV-28 should use its transcript rather than generating another.

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
**Blocked by:** JEV-34 (the surface), JEV-35 (the actuator and its gates),
JEV-36 (outcome measurement), JEV-24a (the pre-rule baseline this destroys),
JEV-27 (the stopping rule), JEV-28 (Fable pricing, now inside a primary
outcome), JEV-29 (the grader).

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

**Status:** ready-for-agent
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
**Blocked by:** JEV-24a

**What to build:** A standing rule that work is delegated to subagents where
practical, raising the share of spend that is routable at all.

- [ ] Adopt the rule; measure the delegation rate after
- [ ] **Disclose the confound in the writeup**: the workload was deliberately reshaped to make more of it routable, which raises experimental power and lowers external validity at the same time. Report what fraction of spend was delegable before the change

---

## JEV-25: `verbosity` question — the second routing dimension

**Status:** blocked
**Labels:** questions, science
**Blocked by:** JEV-34

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

**Status:** ready-for-agent
**Labels:** science, blocking
**Blocked by:** JEV-38

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

**Status:** ready-for-agent
**Labels:** defect, science, blocking
**Blocked by:** JEV-33

*Both rewrite the worker's startup and drain path. Serialised to avoid two agents editing the same file, not because the problems interact.*

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
- [x] **Boundary recorded.** The worker was restarted at **2026-09-20T12:07:24Z**. Rows before that timestamp carry a three-arm `arm_order` (`cc_opus5`, `cc_haiku45`, `jev`) and **no `cc_sonnet5`**; rows after carry four. Verified on the first post-restart row at 12:07:43Z. The analysis must condition on this or report it — the `pre_bash` primary metric is `jev` vs `cc_opus5`, both present on both sides, so the headline is unaffected
- [x] One stranded capture reaped from `spool/claimed/` before the restart (JEV-31), so the restart did not lose it
- [ ] Decide and document whether a mid-window config change requires a restart, a new `arms_config_version` on every row, or is forbidden outright during a collection window

---

## JEV-31: Claimed spool files are never reaped — silent, unmeasured data loss

**Status:** ready-for-agent
**Labels:** defect, blocking, science

**Blocked by:** JEV-33

*Same file as JEV-33 — `spool/claimed/` reaping belongs in the drain loop JEV-33 is rewriting. Serialised for that reason alone.*

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

- [ ] Reap at startup: any file in `spool/claimed/` older than a threshold, or claimed by a pid that is no longer alive, returns to `ready/`
- [ ] Record the reap — a re-claimed capture must be distinguishable from a first-claim one, or a poison payload loops forever
- [ ] Cap the retries and quarantine after N, so a payload that kills the worker cannot resurrect itself indefinitely
- [ ] Count claimed-but-unprocessed files in the status output of `run-collection.sh`, so the operator can see the backlog
- [ ] Recover the one stranded capture from 17:28 before the window closes
- [ ] Report whether any other captures were lost this way during the window — and if the count cannot be recovered, say so rather than implying it is zero

---

## JEV-31b: Five more config fields that look live and are inert

**Status:** ready-for-agent
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

- [ ] Make `state_source` live, or delete it from config and let `STATE_SOURCE` be the single source — either is defensible; having both is not
- [ ] Resolve `paths.SURFACES` against `surfaces.json` so the surface list has one source
- [ ] Either generate the hook registration from config or delete `hook_event`/`matcher` from it
- [ ] Record `surfaces_version` on rows as `pricing_version` already is, or drop the field
- [ ] Sweep for any remaining config key with no consumer, and add a test asserting every key in `config/*.json` is read somewhere

---

## JEV-32: `analyze.py` reads the current config against rows run under an older one

**Status:** ready-for-agent
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

- [ ] Assert at analysis time that every row's `question_set_id` matches the spec being applied, and fail loudly on a mismatch rather than producing a plausible wrong number
- [ ] If rows legitimately span versions, group by `question_set_id` rather than pooling

---

## JEV-33: The worker drains slower than the hook captures

**Status:** ready-for-agent
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

**Status:** ready-for-agent
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

- [ ] `questions/agent_route/v1.json` — `complexity` as a **score** with anchors describing the WORK, never naming a model, preserving the separation `user_prompt/v2.json` already argues for; tier selection stays a policy applied in analysis
- [ ] State builder: `tool_input.prompt` + `tool_input.subagent_type`, payload-only
- [ ] `agent_route` added to `config/surfaces.json` and to the surface list in `paths` — currently a second source of truth (JEV-31b)
- [ ] The `JEV_ARM_SUBPROCESS` recursion guard, for the same reason `capture.sh` has it: the `cc_*` arms spawn `claude -p` in this repo
- [ ] Fail open on every path, exit 0 always, hard timeout — it is synchronous on the spawn critical path
- [ ] Measure the latency it adds to a subagent spawn, live. This is the one place in the study where a Jev call is not free
- [ ] GATE 4 extended to `agent_route`, asserting the state cannot contain anything created after the spawn
- [ ] Parameterise the three existing gates on surface — they are hardcoded to `pre_bash`

---

## JEV-35: Make the routing hook an actuator — behind two new gates

**Status:** blocked
**Labels:** hooks, science, blocking
**Blocked by:** JEV-34, **JEV-40**

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

**Status:** ready-for-agent
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

**Blocked by:** None. Overlaps JEV-32 in `analyze.py`; if both are agent-run, serialise them.

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

**Status:** ready-for-agent
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

- [ ] Confirm the effort/thinking behaviour against a controlled pair of calls, Haiku vs Opus, same state, same effort, thinking tokens recorded
- [ ] Establish whether `--effort low` is ignored on Haiku 4.5, or whether Haiku's floor genuinely sits at ~740 thinking tokens; check the claude-api skill's docs before concluding
- [ ] Establish why Haiku's cache read is zero on every call while Opus's is not
- [ ] Re-time `cc_haiku45` once either is fixed. If it drops below `cc_opus5`, the arm's `arm_config_id` MUST change and that is a **fourth** era boundary in the window — weigh that against leaving it alone until the window closes
- [ ] Correct `src/arms/claude_cli.py`'s docstring: its "317 tokens despite `--effort low`" was measured on Haiku and does not hold for Opus or Sonnet, both of which emit zero
- [ ] Report the finding in the writeup whatever the cause: "the cheap tier was the slow tier, and the reason was configuration, not capability" is a useful result about hook-gate deployment and is directly relevant to JEV-23's co-primary

---

## Deferred: Phase 2

Not ticketed. Opens on explicit go-ahead: transcript harvest, blind labelling UI,
gold labels, Brier with Murphy decomposition, ECE, RPS, decision-curve analysis,
and the writeup.
