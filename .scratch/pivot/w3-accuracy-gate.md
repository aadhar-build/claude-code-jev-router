# W3 — the accuracy gate

**JEV-29 + JEV-36, repurposed. SPEC §6. Built 2026-09-21. Nothing armed, zero
API calls, zero network primitives.**

Before this, nothing in this repository had ever measured whether a routed
subagent did the work correctly. This is the thing that lets us say an
optimization did not make the agent worse — and, more often than not today,
**refuses to say it**, because the evidence is too weak.

---

## 1. What a developer types before shipping a change

```bash
# Class 1 — judge-side. Pennies. Run this on every change that alters what the
# Jev gate sees (state trimming, compaction, tool-output truncation).
uv run src/accuracy_gate.py class1 \
    --baseline  data/runs/2026-09-20.jsonl \
    --treatment /tmp/replay-under-your-change.jsonl \
    --arm jev \
    --tau destructive=0.36 --tau needs_review=0.95 \
    --labels data/labels

# Class 2 — agent-side. Costs real money when armed; free against fixtures.
# The ~6-task smoke subset per change:
uv run src/accuracy_gate.py class2 --suite tests/fixtures/accuracy/suite-v1 --smoke 6
# The full suite, with tiers 2 and 3:
uv run src/accuracy_gate.py class2 --suite tests/fixtures/accuracy/suite-v1 --judge recorded

# Outcomes (JEV-36): both durations, cost, and attrition by tier, for one session.
uv run src/subagent_outcomes.py \
    --session ~/.claude/projects/<project>/<session>.jsonl \
    --ledger data/agent_route/assignments          # --ledger is optional
```

The treatment file for Class 1 is produced by the existing replay path
(`src/replay.py`) run under the changed code. Class 1 does not run the replay
for you — it compares two recorded row-sets, which keeps it usable against any
pair of runs, including two nightlies.

**Read the exit code, never the last line of output.**

```
0  ran clean, nothing to act on
1  COULD NOT RUN  (no key, no network, timeout, missing input, a criterion
                   that could not be evaluated)  ← THIS IS NOT A PASS
2  invoked wrong
3  ran and found a regression
```

Precedence when several apply: `2 > 3 > 1 > 0`. `3` beats `1` deliberately —
finding a regression *is* running.

---

## 2. What was built

| file | what it is |
|---|---|
| `src/accuracy_gate.py` | Class 1 scoring (pure), the exit-code CLI, the power statement |
| `src/fixture_executor.py` | Class 2: the suite, the executor seam, the diff scorer, the blind payload |
| `src/subagent_outcomes.py` | JEV-36 outcomes: cost, **both** durations, attrition by tier, and its own CLI |
| `tests/test_accuracy_gate.py` | 68 tests, all offline, all in tempdirs |
| `tests/fixtures/accuracy/suite-v1/` | 12 tasks × 2 arms × 3 seeds, **synthetic** |

Reused rather than reimplemented: `src/stats.py` (`auc`), `src/session_metrics.py`
(all costing), `src/assignment_ledger.py` row shape. `stats.py`'s agreement
functions are **not** used — they were written for the pre-pivot inter-rater
question and the brief says not to build on them; Cohen's κ is ten tested lines
inside `accuracy_gate.py` instead.

### Class 1

Unit `(decision_id, question_name)`, joined **never on `state_sha256`** — state
trimming changes the state hash by design, so a hash join would pair nothing and
then report a clean run over an empty set. Scored on band-flip rate at τ
(block >5%, report-only 2–5%), AUC drop (block >0.03), κ (block <0.8).

**Every criterion is scored PER QUESTION and blocked on the worst one.** This
started out pooled, and pooling is a hole rather than a style choice. Take this
corpus's own shape: `destructive` fires on ~5% of units, `needs_review` on about
half. A change that turns `destructive` into noise while leaving `needs_review`
byte-identical scores, pooled, at κ ≈ 0.89 and a 4.5% flip rate — a PASS and a
WARN. The gate would go green on the one failure it most exists to catch,
because the untouched majority question carries the score. The test
`test_a_minority_question_destroyed_blocks_even_though_pooling_would_pass`
constructs exactly that case and asserts exit 3. The pooled figures are kept as
a report line and are never blocked on.

Three more things worth knowing:

- **τ is a required input, not a default.** There is no frozen τ file in this
  repository: `verdict.py` derives Youden τ at analysis time, `canary.py`
  defaults to 0.5, `determinism.py` carries `{destructive: 0.36,
  needs_review: 0.95}` as *its* defaults. Picking one silently would make the
  band-flip number depend on which file the author happened to read. A missing
  τ is exit 2.
- **A question-set mismatch is exit 2, not a regression.** A question variant is
  a new row, not a comparison.
- **Rows that failed are attrition, printed, never silently dropped from the
  denominator.**

### Class 2

Unit is the task. **Per-task pass/fail, never an aggregate** — TwinRouterBench's
finding that one under-routed step in an 8–13 call trajectory fails the instance
is the whole reason. The test
`test_a_single_regressing_task_blocks_even_though_the_aggregate_barely_moves`
makes it concrete: one regressing task out of twelve blocks, while the aggregate
pass rate still reads 97% and would have shipped.

**Scored on the final diff of the turn, never per-edit-call.** Nothing in
`fixture_executor.py` reads a tool call, and a test greps the module to keep it
that way. The sharp reason: an edit-tool scorer's `EDIT_TOOLS` is
`{Edit, Write, MultiEdit}`, so Bash-written changes are invisible to it — and
**this repository's own working style pushes edits into `sed` and heredocs**, so
an "optimized" agent that shifted its edits into Bash would show fewer flagged
edits and look *falsely better*. The test
`test_scoring_reads_the_diff_and_an_edit_made_by_bash_is_not_invisible` pins it.

**Blind by construction.** `judge_payload()` builds `{task, file, diff}` from
three fields; the conversation, arm, tier, model and seed are never in scope to
be stripped. The integrity check is therefore one assertion — arm-identifying
tokens absent from the serialised payload — and it is asserted on every payload
on every run. The token set is **not** just the arm labels: tier names, aliases
and resolved model prefixes are read out of `config/tiers.json`, because a diff
carrying `# routed to claude-haiku-4-5` identifies the arm just as effectively
as the word "treatment". Reading the config means a tier added there is covered
without anyone remembering this code exists. **A broken blind is exit 1, not exit 3**: the verdict is unusable,
which is a failure to measure, not a measured regression.

### Outcomes (JEV-36) — verified against real transcripts, not assumed

I checked the premise before building on it
(`.scratch/pivot/check_outcomes.py`, read-only, reproducible):

- On session `4ba49645-…`, **30 of 30** delegations returned `async_launched`,
  and **0 of 30** of those tool results carried a single usage-bearing field.
  `PostToolUse` genuinely cannot supply an outcome. JEV-36 is right.
- `<session>/subagents/agent-<id>.jsonl` carries per-call `message.usage`,
  `message.model` and timestamps; `agent-<id>.meta.json` carries
  `{agentType, description, toolUseId, spawnDepth, requestShape,
  requestNonInteractive}`. **`toolUseId` is the join key to W1's assignment
  ledger**, whose rows carry `tool_use_id` and `tier`. Assignment meets outcome
  there. `SubagentStop` is not needed.
- 33 subagent transcripts on that session, 30 joinable on `toolUseId`; the other
  3 are attrition and are reported as such.

**Both durations, and the divergence is enormous.** On that same real session:

> **median task duration 794.6 s vs median blocking duration 1.5 s — a factor of
> about 530.**

Every delegation was `requestShape: "background"`. A background subagent can be
made twice as fast and the human's wait will not move by a millisecond. The
SPEC's goal says "no added *felt* latency", so reporting one number would answer
a different question from the one asked. `DelegatedTask` carries
`task_duration_s` and `blocking_duration_s` separately, plus `request_shape` so
the divergence is interpretable rather than mysterious.

**Attrition by tier**, in two places and two forms:
- `Class2Report`: attempts / did-not-complete / hard-fail per tier, with
  `$/attempt` **and** `$/success` side by side. On the shipped fixtures, `cheap`
  costs `$0.0077` per attempt and `$0.0082` per success — the gap is the whole
  point.
- `attrition_by_tier()`: assignments, outcomes, attrition rate,
  `cost_per_assignment` **and** `cost_per_outcome`. Intention-to-treat: every
  ledger row survives the join, including the ones with no transcript. A tier
  whose tasks die early has cheap rows and an expensive truth.

---

## 3. What it can detect, and what it cannot

### Class 1 — strong evidence, nearly free

**Can detect:** any change to what the judge sees that moves ≥ 5% of paired
units across a band, destroys ranking (AUC), or drops agreement below κ 0.8.
Against the corpus on disk (`data/runs/2026-09-20.jsonl`, arm `jev`) that is
**1,134 paired units** for `pre_bash/v1#a` — 567 each for `destructive` and
`needs_review`. Because the block is per question, the resolution that matters
is the smallest question's: a change affecting fewer than ~29 `destructive`
units cannot cross the 5% block.

**Cannot detect:** anything about the coding agent. It replays captures that
already exist. `abide`'s replay harness is a scorer over diffs already in
transcripts — it never re-runs the agent — and our optimizations change what the
agent *does*. Class 1 measures the judge, full stop.

**Its current honest state: it exits 1 on this repository.** `data/labels/` is
empty, so the AUC criterion is `NOT_EVALUABLE`, and the gate returns 1 rather
than 0 even on a byte-identical replay with zero band flips and κ = 1.0. That is
the gate reporting, accurately, that it is two-thirds of a gate.
`test_class1_over_the_real_corpus_replayed_against_itself_exits_one` pins it: if
that test ever starts failing with exit 0, someone has either added labels
(good) or added a default (bad).

### Class 2 — weak evidence, costs real money

**Power, computed for the actual n and k rather than quoted.** Detection
requires a task that passes in *all* k baseline seeds and fails in *all* k
treatment seeds, so for an affected task with per-seed failure probability `p`,
`P(detect) = 1 − (1 − p^k)^m` over `m` affected tasks. At **n = 12, k = 3**:

| affected tasks | per-seed failure | P(detected) |
|---|---|---|
| 1 | 1.00 | 1.000 |
| 4 | 1.00 | 1.000 |
| 12 | 1.00 | 1.000 |
| **1** | **0.70** | **0.343** |
| 4 | 0.70 | 0.814 |
| 12 | 0.70 | 0.994 |

Read the bolded row. **A regression that breaks one task 70% of the time is
missed about two runs in three.** A fully deterministic regression on a single
task is always caught; a *flaky* one usually is not. The shipped fixture suite
contains exactly such a task (`clamp-probability`, failing 1 treatment seed of
3) which passes the gate, and a test asserts that it passes — the gate
demonstrating its own blind spot rather than describing it.

These numbers are an **upper bound**: they assume the baseline itself passes all
k seeds. Where the baseline is flaky the real power is lower, and nothing here
measures baseline flakiness yet.

**What slips through, concretely:**
- a regression affecting < ~4 of 12 tasks and not deterministic;
- any quality loss that does not change tests-pass or the acceptance assertion —
  worse structure, worse naming, lost comments. Tiers 2 and 3 exist for exactly
  this, and their dimension threshold (|Δ| ≥ 0.75 on a 10-point ladder) means a
  uniform half-point degradation across every dimension is invisible;
- rule-compliance drift on up to a third of tasks (soft-block threshold);
- anything the fixture suite does not resemble. The suite is 12 synthetic
  single-file bug fixes. A regression that only shows up in long multi-file
  trajectories has nothing here to fail.

**The gate prints this itself.** `power_statement()` emits the table above
followed by the mandated sentence:

> A GREEN CLASS 2 MEANS "NO LARGE REGRESSION FOUND", NEVER "QUALITY PRESERVED".

---

## 4. What it costs to run

| | cost | wall clock | when |
|---|---|---|---|
| Class 1 | ~600–2,000 Jev calls; comparable published run $0.22 | ~2 min | every change that alters what the gate sees |
| Class 2, recorded fixtures | **$0.00**, no network | < 1 s | every change, and in CI |
| Class 2, smoke (6 tasks × 3 seeds × 2 arms = 36 runs) | *unmeasured — never executed* | — | per change, once armed |
| Class 2, full (12 × 3 × 2 = 72 runs) | *unmeasured — never executed* | — | nightly, once armed |

The Class 2 live figures are blank because **the live path has never run**. A
plausible extrapolation from the real subagent costs measured above (median
delegated task ≈ $0.8–13 on `claude-opus-5`) would put a 72-run full suite in
the tens of dollars, but that is arithmetic on someone else's workload, not a
measurement, and I am not going to dress it up as one.

---

## 5. What is NOT built, and what is unexercised

Stated plainly, because a gate that hides its gaps is the failure mode this
whole document exists to avoid.

1. **The live executor has never run.** `LiveExecutor.run()` refuses without
   `--i-understand-this-spends-money` and, even armed, raises rather than
   executing: there is no verified headless-execution implementation in this
   repository. `agent_route` is `mode: "off"`, there is no live routing data,
   and arming anything was out of scope. It is exit 1, always, today.
2. **The live judge has never run.** `LiveJudge` refuses identically. Tiers 2
   and 3 are exercised only through `RecordedJudge`, which reads fixture
   verdicts — but it is handed the *same* blind payload the live judge would
   get, so the blind check tests the real payload shape.
3. **`final_diff()` is unexercised.** The recorded executor supplies diffs
   directly; the git-based extraction (including untracked files, deliberately —
   a new file is still a change) is written and reviewable but never called by a
   test.
4. **The fixture suite is synthetic.** Twelve hand-written tasks with
   hand-written diffs, declared `"synthetic": true` in `suite.json` and printed
   as `[SYNTHETIC FIXTURES]` on every run. The SPEC calls for tasks *mined* from
   real transcripts using `abide`'s reader (task mining, never scoring). That
   mining is **not done** and is the single highest-value follow-up: it is what
   would make Class 2's "does not resemble our work" gap smaller.
5. **Tier 1 does not run tests.** In recorded mode `tests_passed` comes from the
   fixture. Actually executing a fixture repo's test suite is part of the live
   path.
6. **The rubric is not screened.** SPEC §6 says to screen the tier-2 rubric and
   drop rules that never discriminate. With a recorded judge there is nothing to
   screen yet.
7. **Baseline flakiness is not measured**, so the power table is an upper bound.
8. **No self-preference check.** JEV-29's original ticket asks for one (Fable is
   both grader and a routable tier). It is meaningless without a live judge and
   is deferred with the live judge.

---

## 6. Staleness found, reported rather than fixed

- **`ISSUES.md` JEV-36** says the outcome "cannot come from `PostToolUse` …
  Cost and duration come from the subagent's own transcript under
  `<session>/subagents/`, **or from a `SubagentStop` hook**." The first half is
  confirmed (30/30, 0 usage fields). The `SubagentStop` half is **untested and
  unnecessary** — the transcript files carry everything, and `toolUseId` in
  `meta.json` gives a clean join to the ledger that a hook would have to
  reconstruct. Suggest the ticket record the file path as the verified route.
- **JEV-36's checkbox** "Agreement between Jev's assignment and a static
  `subagent_type -> tier` rule" is now partly overtaken: W1 shipped the static
  rule as the *baseline arm*, so the comparison is an A/B, not an offline
  agreement statistic. Not my file to change.
- **JEV-29** still describes a 1–5 four-dimension rubric graded in one batch on
  `claude-fable-5-1`. The repurposed gate uses the SPEC §6 three-tier scheme
  (hard checks / rule compliance / 1–10 dimensions at |Δ| ≥ 0.75). The ticket
  body and SPEC §6 now disagree on the rubric scale; SPEC §6 is the authority
  and the code follows it.
- **`data/labels/` is empty**, which is why Class 1 cannot reach exit 0 today.
  That is a data gap, not a code gap, but it is the single thing that would most
  improve this gate's strength per dollar.

---

## 7. Test suite

`bash tests/run_all.sh` — the line to add (I did not edit that file):

```bash
echo
echo "=== JEV-29 + JEV-36 / W3: the accuracy gate -- both classes, and 1 never reads as 0 ==="
guarded "test_accuracy_gate.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_accuracy_gate.py' 2>&1 | tail -4" || exit 1
```

`python3 tests/test_accuracy_gate.py` → **77 tests, 0 failures, 0 errors**, in
about a second, with no network and no writes outside `tempfile.mkdtemp()`.

`bash tests/run_all.sh` is green end to end, and the live-window guard confirms
`spool/`, `data/` and `logs/` are untouched. One non-blocking item is **not
mine**: `src/doctor.py` reports `[ FAIL ] paths-under-root
HOME_KILL_SWITCH=~/.claude/jev-disabled`. `HOME_KILL_SWITCH` is defined in
`src/paths.py`, which another agent is editing in this tree this wave (it and
`src/install.py` appear in `git status`; I touched neither). `run_all.sh` does
not gate on `doctor.py`.

Earlier in this session `tests/reversibility.sh` also failed, with
`hooks/agent_route_actuator.sh: references .jev-disabled outside the canonical
block` and `2 different switch blocks across 3 hook scripts`. That agent has
since fixed it; the file now passes 44/44.
