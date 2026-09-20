# Spec

Written to `SPEC.md` in the folder on implementation. There is no external issue tracker; per your
instruction the tracker is **`ISSUES.md`** in this folder — a flat markdown file, one `##` heading
per issue, with `Status:` (`ready-for-agent` | `in-progress` | `blocked` | `done`), `Labels:`, and a
body. It lives in git, so issue history and code history are the same history, which for a
single-author study is the whole point. Issues are numbered `JEV-nn` and never renumbered.

## Design decisions settled by the 2026-09-20 grilling

Twenty decisions, taken in five rounds. Recorded here because several reverse
earlier choices in this spec, and the reversals are themselves results.

### Framing

| # | decision |
|---|---|
| Q1 | **Thesis: "routing is where harness savings live."** Not "is Jev a good classifier" — that question is answered (it is) and it turned out not to be the interesting one. |
| Q2 | **Audience: rigorous single-author case study / preprint.** Pre-registration hash cited, every CI clustered, falsification conditions explicit. Not a benchmark — not honestly reachable at n=1. |
| Q3 | **Budget: ~1 week.** Land routing properly; do not attempt Phase 2 gold labels. |
| Q18 | **Thesis narrowed, not pivoted:** "routing *delegated tasks* is where the savings live." The mechanism constraint (below) bounds it. |

### The routing experiment

| # | decision |
|---|---|
| Q5 | **A/B with actual routing**, not shadow-mode inference. |
| Q17 | **Unit of routing is the delegated task, not the turn** — forced by the mechanism constraint. Model selected per subagent via `CLAUDE_CODE_SUBAGENT_MODEL` / `--agents` / frontmatter. |
| Q17b | **Adopt a global "delegate to a subagent where possible" working rule**, to increase the share of spend that is routable. *See the confound note below.* |
| Q10 | **Quality measured by friction proxies + escalation rate**, pre-registered as a composite. Explicitly NOT self-rating: unblinded self-assessment at n=1 on one's own experiment is the weakest available evidence. |
| Q11 | **Primary outcome: net cost including rework** — an escalated turn is charged at its full cost plus the wasted one, so the treatment arm pays for its own mistakes and cannot win by being recklessly cheap. |
| Q12 | **Runs concurrently with the `pre_bash` window.** Arm assignment must be recorded on every `pre_bash` capture so the analysis can condition on it — routing changes which model generates the commands, so the capture stream is no longer stationary. |
| Q16 | **Aggressive thresholds.** Break-even is 37.5–44.4%; the economics have slack. |

### Statistical discipline

| # | decision | status |
|---|---|---|
| Q13, Q20 | **Degenerate-interval guard**: <30 clusters OR zero width → inconclusive by rule; cluster count always printed | **IMPLEMENTED** — `stats.Interval`, Amendment A1.1 |
| Q14 | **Stopping rule amended** from 7 calendar days to 30 distinct sessions or 2026-10-20 | **IMPLEMENTED** — Amendment A1.2 |
| Q15 | **Run all 360 synthetic items through all arms** to close the threshold overfit (gap 0.097 at n=59 → ~0.020 at n=300) | pending — see cost note |

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

## Three things a reader should be told plainly

**1. The mechanism is the binding constraint, not the classifier.** No hook event
accepts a `model` field; `PreModelSwitch` can veto a switch Claude initiates but
never start one. There is no per-request model override in the SDK or headless.
**Per-turn routing inside an interactive session is impossible today.** The
classifier is cheap, fast and good enough — and the harness has nowhere to put
the answer. See `FINDINGS.md` Part 5c.

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

A shadow-mode measurement harness living entirely in one folder. Claude Code hooks capture real
decision points as they occur and write them to a spool in under 10ms, never blocking and never
changing session behaviour. An offline worker replays each captured state against three arms — Jev,
Opus 5, Haiku 4.5 — interleaved with randomised arm order so no arm pays a latency cost the others
don't. Everything is stored append-only and content-addressed, so a single human labelling pass in
Phase 2 applies to every question phrasing ever replayed, with zero re-running.

The output is a set of per-surface tables and figures: latency distributions, cost per decision,
inter-arm agreement with clustered confidence intervals, sharpness, and robustness sweeps — plus a
pre-registration committed before the first record, so the analysis choices are on the record rather
than chosen after seeing the numbers.

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
8. As a researcher, I want all three arms to receive byte-identical state, so that no difference
   between them can be blamed on input drift.
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
22. As a researcher, I want a calendar-based stopping rule, so that I can't stop collecting when the
    numbers happen to look good.
23. As a researcher, I want a daily canary over fixed states, so that a mid-collection vendor model
    change is detected rather than silently averaged in.
24. As a researcher, I want `response_model` recorded on every call, so that model substitution is
    auditable after the fact.
25. As a researcher, I want a stratified synthetic stress set replayed offline, so that the ROC
    curve has resolution my live base rate can never provide.
26. As a researcher, I want synthetic results reported separately and labelled, so that they are
    never pooled with live data.
27. As a researcher, I want determinism measured by repeating identical calls, so that "Jev is
    deterministic and the LLMs aren't" becomes a finding rather than an anecdote.
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
- **Module boundaries.** `hooks/` is bash and owns only spooling. `src/arms/` owns all network I/O
  and is the only place an HTTP client appears. `src/worker.py` owns orchestration and is the sole
  writer of `data/runs/`. `src/analyze.py` and `src/figures.py` are pure functions over jsonl and
  perform no I/O beyond reading inputs and writing `reports/`.
- **The arm interface is one function**: `evaluate(state: str, questions: dict, config: ArmConfig)
  -> Run`. Both arms implement it. Adding a fourth arm means adding one file.
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

Live API calls appear in exactly one place: the day-0 `--selftest` spike, run deliberately and never
in the automated suite.

## Tickets — vertical slices

Thirteen tracer-bullet slices. Each cuts a complete path through hook → spool → worker → arm → row →
report rather than finishing one layer at a time, so every ticket ends in something you can run and
look at. All live in `ISSUES.md` in this folder (a single file, per your instruction — the skill's
default is one file per ticket under `.scratch/`; noting the deviation, not silently taking it).

| # | Title | Blocked by | What it delivers |
|---|---|---|---|
| 1 | **Skeleton & self-containment** | — | `git init`, `.gitignore`, folder layout, `.env` at mode 600 + loader, `SPEC.md`/`ISSUES.md`/`docs/PLAN.md`. Run `doctor.py`: it prints the layout, confirms credentials load, and asserts nothing outside this folder was written. |
| 2 | **Jev API spike** | 1 | One live round-trip. Answers the four open vendor questions — does `providerMetadata.typesafe.confidence` survive the REST path, is Jev deterministic, does caching fire, what does `usage` actually report — and records the findings. Everything downstream assumes a contract this proves. |
| 3 | **Offline tracer bullet** | 1 | The whole pipeline end to end with zero network: pipe a recorded payload into `capture.sh` → `worker --once` drains it through `FakeArm` → a `runs` row lands → `analyze --report` prints a per-surface table. Hook not yet registered; invoked by hand. Both test seams appear here. |
| 4 | **Three real arms, interleaved** | 2, 3 | Swap `FakeArm` for `jev`, `opus5`, `haiku45`. Randomised arm order per decision point, decomposed DNS/TCP/TLS/TTFB timings, failures recorded as rows. Demo: one captured command, three arms, a latency and cost table. |
| 5 | **Statistics & report v1** | 3 | Per-surface agreement, κ *and* PABAK, majority-class baseline beside every number, session-clustered bootstrap CIs — with known-answer tests over hand-built fixtures, so the maths is verified before real data exists. |
| 6 | **The "before" baseline** | 1 | `session_metrics.py` over a frozen completed transcript in `data/fixtures/`: cost reconciled against `cost-state.totalCostUSD`, dedupe by `requestId`, tokens by class, wall-clock, friction proxies. Independent of everything else; this is the only thing enforce mode can ever be differenced against. |
| 7 | **Pre-registration** | 4, 5 | `PREREGISTRATION.md` committed, with its git hash. Deliberately blocked on 4 and 5: you can only honestly pre-register metrics you have already demonstrated you can compute. **Nothing may be captured live before this lands.** |
| 8 | **Go live on `pre_bash`** | 7 | Register the hook in `.claude/settings.local.json` and pass all three gates before it is enabled: isolation (control dir, worktree subagent, gitignore), fail-open (bogus key, unreachable host, read-only spool), kill switch (`.jev-disabled` → zero activity). First real capture from a real session. |
| 9 | **True inline shadow** | 8 | `inline_shadow_bash.sh` calls Jev synchronously with `--max-time`, logs what it would have decided, never blocks. Exercises the script you would actually deploy and yields a *measured* enforce overhead. |
| 10 | **Synthetic stress set & robustness** | 4, 5 | ~300 stratified items replayed offline, plus determinism N=20, phrasing, option-order and truncation sweeps. This is where the ROC curve gets resolution the live base rate can't provide. Reported separately, labelled synthetic. |
| 11 | **Enforce-overhead bench & drift canary** | 8 | `bench_inline.py` (N=200, including process spawn) and `canary.py` (daily fixed-state check so a mid-collection vendor model change is caught, not averaged in). |
| 12 | **Figures & publishable export** | 5, 10 | Latency CDFs, sharpness histograms, pseudo-reliability curves; export-time scrubber with `redaction_version`; packaging that excludes `data/states/` by default. The artifact you'd actually publish. |
| 13 | **Remaining three surfaces** | 8 + ~1 week of `pre_bash` data | Register `stop`, `user_prompt`, `post_edit`. Held deliberately until the analysis path is proven end to end on one surface — otherwise you collect 2,000 records you can't use. |

Tickets 1 and 6 have no blockers between them and can run in parallel. Phase 2 — labelling UI, gold
labels, Brier/ECE/RPS, decision curves, writeup — is not ticketed here; it opens on your go.

## Out of Scope

Enforce mode and any enforce hook script. Registration of `stop`, `user_prompt` and `post_edit`
(their question sets and state builders are written; only registration waits). Phase 2 in its
entirety — the labelling UI, gold labels, Brier/ECE/RPS, decision-curve analysis, and the writeup.
Multi-repo collection, ruled out by the isolation requirement. Any launchd or auto-start mechanism.
Any claim about accuracy, calibration, or productivity improvement.

## Further Notes

Three things still need ratification and are flagged as deviations or recommendations rather than
settled: **Haiku 4.5** as a third arm was declined and added back anyway, because Opus-as-hook-gate
is a strawman — it is droppable at a word. **Three of four surfaces are deferred**, which is
sequencing rather than scope reduction, and is a recommendation to accept or override. And the
**synthetic stress set carries the statistical load** as a direct consequence of the isolation
requirement — a narrower claim than a multi-repo study, stated as such in the writeup.
