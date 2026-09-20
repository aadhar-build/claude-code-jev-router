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

**Status:** ready-for-agent
**Labels:** spike, blocking
**Blocked by:** JEV-01

**What to build:** A single live round-trip against the Jev endpoint that settles
the vendor contract every later ticket assumes. Run deliberately, never from the
automated test suite.

- [ ] `arms/jev.py --selftest` performs one live evaluate call and prints the raw response
- [ ] Confirms the shape of `answers` and `usage` matches what the design assumes
- [ ] Determines empirically whether `providerMetadata.typesafe.confidence` survives the REST path (documented for the AI SDK only)
- [ ] Determines whether repeated identical calls return identical probabilities
- [ ] Determines whether prompt caching fires for short classifier prefixes
- [ ] Findings recorded in `docs/API-FINDINGS.md` with the date and the response model string

---

## JEV-03: Offline tracer bullet

**Status:** ready-for-agent
**Labels:** core, test
**Blocked by:** JEV-01

**What to build:** The entire pipeline working end to end with no network at all,
so the shape is proven before any money or any live session is involved.

- [ ] `capture.sh` accepts a recorded hook payload on stdin, spools it atomically, and exits 0 in under 10ms
- [ ] Kill switch, cwd guard, backpressure and fail-open all behave correctly at the process boundary
- [ ] `worker.py --once` drains the spool, builds state, evaluates through `FakeArm`, and writes a `runs` row
- [ ] `analyze.py --report` reads the resulting jsonl and prints a per-surface table
- [ ] Seam 1 (hook process boundary) and seam 2 (`evaluate` with a fake arm) both have tests
- [ ] The whole path runs from a single command with zero API spend

---

## JEV-04: Three real arms, interleaved

**Status:** blocked
**Labels:** core
**Blocked by:** JEV-02, JEV-03

**What to build:** Replace the fake arm with the three real ones and make the
comparison between them fair by construction.

- [ ] `jev`, `opus5` and `haiku45` all implement `evaluate(state, questions, config) -> Run`
- [ ] Arm order is randomised per decision point so no arm systematically pays time-of-day network drift
- [ ] All three arms receive byte-identical state; `state_sha256` recorded per run
- [ ] Timings decomposed into DNS, TCP, TLS and TTFB
- [ ] Failures and timeouts are written as rows with `ok:false` and an `error_kind`, never dropped
- [ ] Cost computed per exact model string with cache multipliers, from version-pinned rates
- [ ] Demo: one captured command produces three rows and a latency-and-cost table

---

## JEV-05: Statistics and report v1

**Status:** blocked
**Labels:** analysis, test
**Blocked by:** JEV-03

**What to build:** The analysis that turns rows into defensible numbers, verified
against known answers before any real data exists.

- [ ] Every metric reported per surface; nothing pooled across surfaces
- [ ] Boolean agreement at tau=0.5 with Cohen's kappa and PABAK reported together
- [ ] The majority-class baseline and the base rate printed beside every agreement number
- [ ] Confidence intervals bootstrapped clustered on `session_id`, with the naive interval shown once for comparison
- [ ] Hard assertion that all arms for a decision share a `state_sha256`
- [ ] The word "accuracy" appears nowhere in generated output
- [ ] Known-answer tests over hand-built fixtures for kappa, PABAK and the clustered bootstrap

---

## JEV-06: The "before" baseline

**Status:** ready-for-agent
**Labels:** metrics, test
**Blocked by:** JEV-01

**What to build:** Per-session cost, token and wall-clock metrics harvested from
Claude Code's own transcripts. This is the only thing a later enforce phase can
ever be differenced against, so it starts collecting on day 0.

- [ ] Transcript lines deduplicated by `requestId`; `usage.iterations[]` ignored
- [ ] Tokens reported by class -- input, cache-write, cache-read, output, thinking -- never as one sum
- [ ] Cost computed with cache multipliers per exact model string including any context suffix
- [ ] Cost reconciled against the session's own `cost-state.totalCostUSD`, with the delta reported
- [ ] Wall-clock, assistant turns, tool calls by name, and `is_error` tool results counted
- [ ] Friction proxies counted: user interruptions and permission denials
- [ ] Runs against a frozen completed transcript copied into `data/fixtures/` with expected counts recorded beside it

---

## JEV-07: Pre-registration

**Status:** blocked
**Labels:** science, blocking
**Blocked by:** JEV-04, JEV-05

**What to build:** The commitment document, committed to git before a single live
record is collected. Blocked on 4 and 5 deliberately: you can only honestly
pre-register metrics you have already demonstrated you can compute.

- [ ] Primary metric and directional hypothesis stated per surface
- [ ] Secondary metrics explicitly marked as secondary
- [ ] Stopping rule is calendar-based; N is explicitly not a stopping criterion
- [ ] Exclusions decided in advance: sidechains, failed runs, canary and synthetic rows
- [ ] The synthetic/live split stated, and which claims rest on which
- [ ] Pricing snapshot date recorded
- [ ] States plainly that Phase 1 makes no accuracy or calibration claim
- [ ] Committed; its git hash is the citation used in the writeup

---

## JEV-08: Go live on pre_bash

**Status:** blocked
**Labels:** hooks, verification, blocking
**Blocked by:** JEV-07

**What to build:** The first real capture from a real session -- gated behind
three verification tests that must all pass before the hook is enabled.

- [ ] Hook registered in `.claude/settings.local.json` for `pre_bash` only, with `$CLAUDE_PROJECT_DIR`-anchored paths
- [ ] Isolation gate: a control directory produces nothing; the worktree-subagent case is exercised and its spool destination recorded; `settings.local.json` confirmed gitignored
- [ ] Fail-open gate: bogus key, unreachable host and a read-only spool all leave the session unaffected and the hook exiting 0
- [ ] Kill-switch gate: `.jev-disabled` produces zero activity
- [ ] A real session in this repo produces exactly one capture with a matching `session_id`

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

**Status:** blocked
**Labels:** science
**Blocked by:** JEV-04, JEV-05

**What to build:** The discrimination story, which the live base rate is too
degenerate to provide on its own.

- [ ] ~300 stratified items across destructive, borderline and benign
- [ ] Replayed offline through all arms; reported separately and labelled synthetic, never pooled with live
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
- [ ] `stop` state built from the transcript truncated at `transcript_bytes_at_capture`, never the tail
- [ ] Each capture records its `state_source`
- [ ] Per-surface switches verified independently

---

## Deferred: Phase 2

Not ticketed. Opens on explicit go-ahead: transcript harvest, blind labelling UI,
gold labels, Brier with Murphy decomposition, ECE, RPS, decision-curve analysis,
and the writeup.
