# W5 data fixes — JEV-57, JEV-59, and two ticket defects

Agent: W5 (data). Worktree `.claude/worktrees/jev-critical-path`. No git writes.
**Zero API calls.** Nothing armed. Everything below re-reads files already on disk.

---

## 0. What I changed

| file | why |
|---|---|
| `src/assignment_ledger.py` | JEV-57: `project` on the row, `verify()` partitions and refuses to pool |
| `tests/test_assignment_ledger.py` | **NEW** — 15 tests for the above. Needs a `guarded` line (§5) |
| `src/session_metrics.py` | JEV-59: `COSTING_RULE` / `_DESCRIPTION` / `_LEGACY`; §3 figure qualifier |
| `src/baseline.py` | JEV-59: `baseline-v2`, idempotency key, manifest scope, coverage-hole split; §3 figure qualifier |
| `tests/test_baseline.py` | 19 new tests across 4 new classes |
| `data/baseline/sessions.jsonl` | 44 rows appended under the corrected rule. **29 old rows untouched** |
| `data/baseline/manifest.json` | regenerated; now states its own scope |

Not touched: `data/baseline/delegation-pre-rule-v1.json` and
`-corrected.json` — verified byte-identical (`git diff` empty).

---

## 1. JEV-57 — the ledger can now tell one repo from another

**Verified first, as instructed.** `grep -n project src/assignment_ledger.py`
returned nothing; `data/agent_route/assignments/` was empty. Both true.

**Schema.** `LEDGER_SCHEMA_V1` (no `project`) and `LEDGER_SCHEMA_V2` (adds it).
`ledger_row(project=None)` emits v1, `ledger_row(project="/path")` emits v2.

**`LEDGER_SCHEMA` still points at v1, deliberately.** It names *what the
deployed writer emits*, and the deployed writer is `hooks/agent_route_actuator.sh`,
owned by another agent this wave. Bumping it ahead of the hook would mean a
version string claiming a field the rows do not carry — and would break
`test_agent_actuator.py::test_the_hooks_row_and_the_python_row_have_the_same_keys`,
which I do not own. Leaving it pinned keeps that test green **and** keeps it a
live drift detector: the moment the hook emits `project`, it goes red and names
this file. That is the handover, not a workaround.

**Migration decision: fenced, not backfilled.** A `-v1` row never carried a
project and cannot be given one honestly — the ledger is *shared*, so "it must
have been this repo" is exactly the unsafe inference. Legacy rows land in
partition `<v1:no-project>`, which never merges with a named one. Zero such
rows exist in this install; the partition exists for installs where they do.

**`verify()` refuses to pool.** Three call shapes:

- `project="/path"` — score that repo. Everything else lands in
  `projects_excluded`, so the exclusion is visible rather than assumed.
- `pool_projects=True` — pool deliberately; result says `pooled: True` and
  names every partition it swallowed.
- neither — fine for one project; raises `ProjectsWouldBePooled` the moment
  there is more than one. **Raised, not returned**: a confounded rate is
  indistinguishable from a real one once it is a number on a page.

Every return path now carries `project` / `pooled` / `projects_in_ledger` /
`rows_scored`, so a caller printing a rate without its scope had to discard it
on purpose.

### HANDOVER to the hook owner (I did not edit `hooks/*.sh`)

In `hooks/agent_route_actuator.sh`, two places:

1. Both `jq` invocations (~line 414 `JQ_DECIDE`, ~line 423 `JQ_FRONTIER`) gain
   one argument: `--arg project "$ROOT"`.
   `$ROOT` is already `${CLAUDE_PROJECT_DIR:-}` at line 88. Use it **raw** — no
   `pwd -P`, no realpath. A worktree's path is not its repo's path and
   normalising them is an analysis decision the hook lacks the knowledge to
   make. JEV-57 says "at decision time, not inferred later".
2. Both row objects (`{schema: "agent-route-assignment-v1", ...}`, ~line 329 and
   ~line 387) change to:
   - `schema: "agent-route-assignment-v2"`
   - add `project: (if $project == "" then null else $project end)`
     — placed anywhere; the parity test compares key *sets*.

Then, in the same change, flip `LEDGER_SCHEMA = LEDGER_SCHEMA_V2` in
`src/assignment_ledger.py` and pass `project=` in the parity test's
`al.ledger_row(...)` call. `tests/test_assignment_ledger.py::
test_the_deployed_schema_constant_tracks_the_hook_not_the_reader` pins the
current state and must be updated in that same commit.

---

## 2. JEV-59 — the committed baseline no longer records $0.00 for real spend

### Every claim verified

| claim | verdict |
|---|---|
| `grep -c costing_rule` → 0 and 0 | **true** |
| 23 of 29 rows `computed_cost_usd: 0.0` | **true**; 21 with `unpriced_models: ["claude-opus-4-7"]` |
| `claude-opus-4-7` is priced by `pricing-2026-09-20b` | **true** (`config/pricing.json`) |
| a row with `0.0` against `reported 0.41605` | **true** — session `1d926ee0` |
| all 29 `snapshot_at` 14:42–14:50, manifest `pricing-2026-09-20` | **true** |
| fingerprint-idempotent, will not self-correct | **true** |

### One claim in the brief is wrong, and it matters

> "`manifest.json` says `sessions_captured: 15` while `sessions.jsonl` carries
> **29 rows**… the stream sums to roughly $724 / 120 delegated tasks."

**The 29 rows are 15 sessions.** Seven session_ids appear 2–6 times: the stream
is an append-only *history*, one row per reading of a growing session, exactly
as designed. Summing all 29 rows **double-counts** — that is where $724 and 120
tasks come from. Taking the last row per `session_id` reproduces the manifest's
$125.582946 / 20 tasks / 58 prompts *to the cent*.

So the manifest was **not** describing a subset. It was correct and
**unlabelled** — nothing in either file said how to aggregate the stream, which
is how "$724" gets computed by a careful reader doing the obvious thing. Fixed
by stating the rule in the file (below), not by regenerating a subset.

### The fix: the rule is in the idempotency key, not behind a flag

A row is not a function of the transcript. It is a function of **(transcript,
costing rule, pricing snapshot)**. Keyed on the fingerprint alone, correcting
the costing rule changed nothing on disk — the transcripts were untouched, so
the stream said "nothing to do" and went on carrying withdrawn numbers.
*Idempotent and wrong is worse than stale, because it looks current.*

`snapshot_identity()` is now that triple, so:

- every session re-snapshots **exactly once** under a new rule, then settles;
- the **next** rule or pricing change corrects itself instead of needing
  another ticket;
- no `--force` flag. `main()` defaults `args.snapshot=True`, so a `--force`
  would have been a second switch with the same blast radius and no memory.

`baseline-v2` rows carry `costing_rule` (short id) and `pricing_version`. The
description lives once, in the manifest and in
`session_metrics.COSTING_RULE_DESCRIPTION` — repeating a sentence in 44 rows is
bloat and trips `test_no_row_carries_a_long_free_text_string`, which is right.

**History preserved by distinguishability, not deletion.** The 29 `-v1` rows
are still there, unedited and un-back-stamped. `row_costing_rule()` reads an
absent field as `COSTING_RULE_LEGACY` — a claim about what is *missing*, which
is honest, rather than a value invented retrospectively.

### The manifest's totals are over the STREAM, not over what is on disk

The two coincide today (44 = 44) and diverge the moment a snapshotted session
is reaped — which is **no longer hypothetical**: `already_unrecoverable` went
0 → 1 on this very run. Totalled over on-disk transcripts, `manifest.json`
would silently *shrink* as Claude Code's 30-day sweep ran, while the stream
still held the spend. A "before" baseline that decays with the source it was
built to outlive is precisely what JEV-38 exists to prevent. `sessions_captured`
stays the on-disk count (the number that can fall); the totals and the activity
window come from `latest_per_session()`, the durable record.

`unpriced_requests` and `unpriced_zero_token_requests` are summed only over
rows that *carry* those fields — reading a missing field as 0 would report
"no coverage hole" for rows whose coverage was never measured.

### The manifest now states its own scope

Added: `costing_rule`, `costing_rule_description`, `totals_scope`,
`aggregation_rule` ("take the LAST row per session_id … never sum all rows"),
`stream_rows_total`, `sessions_in_stream`, `corpus_root`, `jev_home`.

`project_root` used to record `paths.ROOT` — **the worktree** — beside totals
derived from a completely different directory. `corpus_root` now records where
the numbers actually came from.

### A third defect found while verifying

The manifest published `unpriced_requests: 5` beside `unpriced_models: []` —
two fields contradicting each other. `session_metrics` counts an unpriced
request only when it carried tokens (a real coverage hole); `baseline`'s row
counted every unpriced projection, including zero-token `<synthetic>` rows.
Split into `unpriced_requests` (the hole, matched to `unpriced_models`) and
`unpriced_zero_token_requests` (the harmless remainder), with the note saying
which is which.

### Positive assertions after the run

Per the repo's own rule — *every silent path needs a positive assertion that it
did something*:

- 44 appended, 0 unchanged on the first run; **0 appended, 44 unchanged on the
  second** (idempotent again);
- zero-cost rows among the 44: **1**, and it is justified — `a25cd7d2`, one
  assistant line, model `<synthetic>`, `reported_cost_usd: 0`. Down from 23/29;
- `unpriced_requests: 0`, `unpriced_models: []` across all 44;
- `already_unrecoverable.count` moved **0 → 1**: session
  `5b18f33f-e38e-4be1-a4b6-c058dc0c491e` is in `~/.claude/history.jsonl` and no
  longer on disk. Still a lower bound. **The retention risk JEV-38 was filed
  for is now observed, not hypothetical.**

---

## 3. HOW FAR THE "BEFORE" ANCHOR MOVES

**The headline anchor does not move.** The number SPEC §11 names — **$1.58 →
$2.88 per delegated task under the JEV-24a cut** — lives in
`delegation-pre-rule-v1-corrected.json`, which this task left byte-identical.
Nothing published against it needs re-deriving. What moved is the *stream*, the
`sessions.jsonl` / `manifest.json` half that §11's closing note flagged as
still-wrong and which nobody had yet re-derived.

Three effects are in play there and I have kept them apart, the way SPEC §11
kept `frozen_rule_today` apart from `corrected`. **Do not quote $125.58 →
$313.03 as the movement** — that blends a rule fix with 29 new sessions.

Of the 15 sessions in the old stream, **14 have a byte-identical transcript**
today and 1 grew.

### (a) Pure rule + pricing effect — 14 byte-identical transcripts

| | old | new |
|---|---|---|
| `computed_cost_usd` | **$0.000000** | **$8.495763** |
| `unpriced_requests` | 78 | 0 |
| delegated cost / tasks | $0 / 0 | $0 / 0 |

**$0.00 → $8.50 on files that did not change by one byte.** The old reading was
not an approximation of these sessions' cost; it was a *null*, published as a
number. This is JEV-49's "$0.00 sessions: 14 of 15 → 0 of 15" finally reaching
the committed artifact. Dominated by pricing (`-20b` prices
`claude-opus-4-7`); the costing rule contributes nothing here because these
sessions have no delegated work.

### (b) The one session that grew — not separable, reported as such

`4ba49645` (the main work session, 275KB → 11.7MB between the two snapshots):

| | old | new | move |
|---|---|---|---|
| computed | $125.582946 | $291.507437 | +132.1% |
| delegated | $42.569944 | $171.944749 | +303.9% |
| main-session | $83.013002 | $119.022688 | +43.4% |
| delegated tasks | 20 | 33 | +65.0% |
| human prompts | 58 | 76 | +31.0% |

Rule, pricing and growth are entangled here. **These percentages are not the
anchor movement** and must not be quoted as one.

### (c) The corrected totals — what future savings are measured against

Whole corpus, 44 sessions, last row per `session_id`, rule
`billable-requests-2026-09-21`, pricing `pricing-2026-09-20b`:

| | |
|---|---|
| `total_computed_cost_usd` | **$313.029798** |
| `total_delegated_cost_usd` | **$171.944749** |
| `total_delegated_tasks` | **33** |
| **cost per delegated task** | **$5.2104** (whole corpus, no cut) |
| `total_human_prompts` | **76** |
| `unpriced_requests` | **0** |
| stream rows / sessions | 73 / 44 |

$5.21 is the whole-corpus, no-cut per-task figure and is **not** the anchor.
The anchor is $2.88, under the JEV-24a cut, unchanged — different window,
different denominator. Same trap §11 documented for 38.9% vs 45.2%.

$171.944749 over 33 tasks reproduces SPEC §10's whole-corpus delegated figure
**exactly** — an independent confirmation that the corrected rule is the one
§11 describes.

### What must be re-derived downstream

The "34% addressable" figure came from the old manifest, computed under the
defective rule. SPEC §11 already superseded it with **~24%**. Whatever quotes
it should now quote the corpus it came from — and the corpus-size dispute in
§10 is **not** resolved by this: 44 sessions / 33 delegated tasks is a *fourth*
count, over a fourth window. State the range, never a point.

---

## 4. The two ticket defects

**JEV-06's first checkbox is ticked and wrong — confirmed, both halves.**
It reads *"Transcript lines deduplicated by `requestId`; `usage.iterations[]`
ignored"*. Today `session_metrics.dedupe_key` (line 321) returns the
`(requestId, message.id)` **pair**, and `normalise_usage` (line 225) **sums**
`iterations[]` into the token fields. Both halves describe the rule JEV-49
withdrew. **For the orchestrator: this checkbox needs to be un-ticked and
rewritten on the board. I did not edit `ISSUES.md`.** Suggested text:

> - [x] Transcript lines deduplicated by the `(requestId, message.id)` pair;
>   `usage.iterations[]` **summed** into the token fields (corrected by
>   JEV-49 / `98979a7` — the original rule understated delegated spend by
>   45.2% under the JEV-24a cut)

**`src/baseline.py:252-257` — fixed.** It quoted `38.9% / $105.09 / $171.94`
with no window. Now both figures appear with their windows: the whole-corpus
+38.9% *labelled as such*, and the +45.2% that actually describes the frozen
record. **The same unqualified quote existed in `src/session_metrics.py:353`**
(`billable_requests`) and is fixed identically.
`TestTheAnchorFigureIsNeverQuotedWithoutItsWindow` now fails if either number
loses its qualifier again.

---

## 5. For the orchestrator

**One `guarded` line to add to `tests/run_all.sh`** (I did not edit it). Put it
directly after the `test_agent_actuator.py` line:

```bash
echo
echo "=== JEV-57: the ledger can tell one repo from another, and refuses to pool ==="
guarded "test_assignment_ledger.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_assignment_ledger.py' 2>&1 | tail -4" || exit 1
```

**`bash tests/run_all.sh` is GREEN** as of the final run, including the live-window
guard ("spool, data/ and logs/ are as the suite found them"). Mid-task it was
red in four places — all of it other agents' uncommitted in-flight work
(`hooks/capture.sh`, `hooks/inline_shadow_bash.sh`, `tests/test_agent_actuator.py`,
`src/subagent_outcomes.py`), and all of it resolved by them before I finished.
Nothing of mine ever failed it.

```
run_all.sh                  green end to end
test_baseline.py            50 tests  OK
test_session_metrics.py     36 tests  OK
test_assignment_ledger.py   15 tests  OK   <-- not yet in run_all.sh
test_agent_actuator.py      50 tests  OK
src/doctor.py               14 passed, 1 warned, 0 failed
```

The new file is the one gap: until the `guarded` line above is added,
`test_assignment_ledger.py` is green but unrun by the suite.

**Concurrent-edit warning.** `src/assignment_ledger.py` was rewritten by
another agent *while I was editing it* (the `unverifiable` verdict and
`tier_for_alias` recovery appeared mid-task). I merged onto their version and
removed one duplicated docstring paragraph the collision produced. Worth a
look at the final diff: two agents were told they own that file.

`.scratch/pivot/w5_anchor_diff.py` reproduces every number in §3 **from the
repo alone** — no `/tmp`, no backup file. The 29 pre-JEV-59 rows are still in
the committed stream and are identified by the absence of `costing_rule`, the
same test `baseline.row_costing_rule()` applies. Run it from the repo root.
