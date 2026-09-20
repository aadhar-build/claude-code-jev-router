# ISSUES

The issue tracker for this experiment. One `##` heading per ticket. Tickets are
numbered `JEV-nn` and never renumbered. Git history is issue history.

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

**Status:** blocked
**Labels:** hooks, hot-path
**Blocked by:** JEV-08

**What to build:** The script you would actually deploy, running live but never
blocking -- because a capture-and-replay harness never exercises it.

- [ ] `inline_shadow_bash.sh` calls Jev synchronously with a hard `--max-time`
- [ ] Logs the decision it would have made; never emits a permission decision
- [ ] Exits 0 on every path including timeout, network failure and malformed response
- [ ] Yields a measured inline p99 under live session conditions

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

**Status:** blocked
**Labels:** metrics, science
**Blocked by:** JEV-08

**What to build:** Two small instruments: what enforcement would actually cost in
latency, and whether the vendor changed the model underneath you mid-collection.

- [ ] `bench_inline.py` invokes the real hook N=200 times over recorded states and reports end-to-end wall-clock including process spawn
- [ ] Reported as projected enforce overhead, clearly separated from API latency
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

## Deferred: Phase 2

Not ticketed. Opens on explicit go-ahead: transcript harvest, blind labelling UI,
gold labels, Brier with Murphy decomposition, ECE, RPS, decision-curve analysis,
and the writeup.
