# Prep for wave A3 — from JEV-32 (the analysis-side config join)

For **JEV-27** (power analysis), **JEV-46** (`random_matched` arm), **JEV-47**
(delegation-shape equality) and **JEV-48** (cheap/frontier failure
correlation). All four consume analysis output, so this is about *joins, keys
and entry points* rather than statistics.

Everything below was checked against the tree at the commit that closed JEV-32
(`src/analyze.py` only). Line numbers move; the `grep` anchors do not.

---

## 0. The one thing to read first

**A row's config identity is what the row carries, not what `config/` says
today.** `analyze.py` used to resolve the question spec and the pricing version
from current config at analysis time and pool everything into one figure. It no
longer does. If you write a new analysis and call `cl.question_set(surface)`
or `cl.pricing()` and then iterate rows, **you have reintroduced JEV-32**.

The correct shape, now present in three modules, is:

```python
primary_qsid = cl.question_set_id(surface)          # what config says
...
if r.get("question_set_id") != primary_qsid:        # what the ROW says
    diagnostics["off_question_set"] += 1            # count it
    continue                                        # never pool it
```

`src/validate_threshold.py:collect`, `src/determinism.py:collect` and now
`src/analyze.py:report` all do this. Copy one of them; do not invent a fourth
shape.

---

## 1. Key reliability: old rows versus new

This is the table to consult before designing any join.

| key | on the 2,005 existing rows | on rows written from wave A2 onward | safe to join on? |
|---|---|---|---|
| `decision_id` | yes, all | yes | **yes** — the primary join key, runs ↔ captures |
| `question_set_id` | yes, all (`pre_bash/v1#a`, 2005/2005) | yes | **yes** — partition on it, never pool |
| `state_sha256` | yes | yes | **yes** — and it is asserted equal across arms |
| `session_id` | on captures | yes | yes, but see §5 — it is the clustering unit |
| `pricing_version` | yes, all (`pricing-2026-09-20`) | yes | **weak** — hand-maintained, see §3 |
| `cost_usd` | yes, stamped at write time | yes | yes as a *value*; never recompute it |
| `arm_order` | yes | yes | **yes, with care** — see §2 |
| `arm_config_id` | yes | yes | yes, per-arm config identity |
| `arm_dispatch` | **absent on the sequential era**, `"concurrent"` after | yes | absence is meaningful, not missing |
| `config_fingerprint` | **absent on all 2,005** | yes (`worker.py`) | **no — cannot be a join key for old data** |
| `evaluated_at` | yes | yes | **do not bisect the dataset on it** — see §2 |

### `config_fingerprint`, stated plainly

It is the strongest key that exists *going forward* and it is **unusable on
every row collected so far**, because it was added after they were written.
Treat absence as "the pre-fingerprint era" (the convention `arm_dispatch`
already uses) and keep it silent. Use it for the one assertion nothing else can
make: **two different non-null fingerprints inside one otherwise-identical
group means the config changed without its version string changing.** That is
implemented at `analyze.py:_provenance` and is the only check that catches a
pricing *rate* edited without a `pricing.json:version` bump. JEV-49 should care
about this; JEV-27 should care about it a great deal, because it sizes a study
against a cost distribution.

---

## 2. The arm-set eras — and why we did not bisect on the clock

This matters most to **JEV-46** and **JEV-47**.

There is no row-level version for the enabled-arm set. `arm_order` is its only
trace. The live corpus is therefore two eras, and it is visible now in every
report header:

```
  question set: pre_bash/v1#a   (the configured pin)
    arm set cc_haiku45+cc_opus5+cc_sonnet5+jev   rows=1252
    arm set cc_haiku45+cc_opus5+jev   rows=531
```

Plus `arm set jev rows=42`, which is **entirely `run_context: canary`** and is
already excluded from the live report by context. Verified — do not spend time
re-deriving it.

**Key on `set(row["arm_order"])`, which is intrinsic to the row.** Do *not*
bisect the corpus on `evaluated_at` against the 12:07:24Z restart recorded in
JEV-30. A dataset partitioned on a wall clock is the exact contamination JEV-43
exists to remove, and it silently mis-assigns any row written by a process that
started before the restart and finished after it. The intrinsic key needs no
external timestamp and cannot drift.

**JEV-32 disclosed the eras; it deliberately did NOT partition the statistics
on them.** Splitting the live report into a three-arm and a four-arm section
would move every `n` and every interval in the study — that is a
stop-and-report event under PREREGISTRATION §8, not a defect fix. If **JEV-46**
or **JEV-47** needs era-separated figures, that is a *new* analysis with its
own pre-registered justification, not an edit to `report()`. Say so in the
ticket before writing code.

---

## 3. `pricing_version` is not a config identity

`pricing_version` and `cost_usd` come from the same cached blob
(`config_loader._pricing()`), so within a process they are always mutually
consistent. But the version string is **hand-maintained**: an operator can edit
a rate without bumping it, and two rows then carry the same
`pricing-2026-09-20` over different numbers. `config_fingerprint` closes this
for new rows and nothing closes it for old ones.

Consequences for **JEV-27**, which sizes a study against a cost distribution:

- `cost_usd` is stamped at write time and **must never be recomputed** from
  `pricing_version` plus today's `config/pricing.json`. The report prints the
  stamped version with the current one beside it precisely so the two cannot
  diverge unnoticed.
- Per-call run rows **exclude web search**; `web_search_usd_per_request` is
  consumed only in `src/session_metrics.py` (grep it). Session baselines
  include it. Do not reconcile run rows against session costs without
  accounting for that — it is a real, signed gap, not noise.
- JEV-49 is fixing three cost-pipeline defects this wave and JEV-27 is blocked
  on it. Read JEV-49's prep before deriving any N.

---

## 4. Which entry point to extend, per ticket

**Extend, do not duplicate.** Four modules already read the row streams and
each has a `collect`-shaped function that does the filtering correctly. A fifth
reader that re-does the join is a fifth place for JEV-32 to come back.

| ticket | extend this | not this |
|---|---|---|
| **JEV-27** power analysis | `src/baseline.py:delegated_tasks` + `delegation_baseline` for the per-task cost distribution; `src/session_metrics.py:cost_decomposition` for the session side | do not read `data/runs/` for cost — those are per-call decision rows, not delegated tasks, and they are a different unit entirely |
| **JEV-46** `random_matched` | the arm interface (`src/arms/base.py`, `ArmConfig`) and `config/arms.json`; the analysis side needs nothing new if the arm writes ordinary run rows | do not add an arm-set partition to `analyze.report` — see §2 |
| **JEV-47** delegation shape | `src/baseline.py:delegated_tasks` — it already returns `agent_type`, `spawn_depth`, `tool_use_id`, `requests`, `cost_usd` per task, read from `subagents/*.meta.json` rather than from `Agent` tool-call tallies | do not count `Agent` tool_use blocks in the main transcript: a task spawned at `spawnDepth > 1` never appears there and the tally under-counts. `delegated_tasks`'s docstring says so; believe it |
| **JEV-48** failure correlation | `src/validate_threshold.py:collect` — it already returns `(items, scores, diagnostics)` with one score per `(decision_id, arm, question_set_id)` and duplicates counted rather than averaged away; and the JEV-29 grader's scores for outcomes | do not build a fresh runs-to-captures join; `Joined` in `analyze.py` and `collect` in `validate_threshold.py` both exist and both already exclude sweeps, sidechains and context mismatches |

### The assertion shape JEV-47 asked for

JEV-47 wants "a per-row assertion and a report line, not an argument". The
sibling to copy is `analyze.py:Joined._check_state_identity`: it collects
violations into a list, returns them, and `report()` prints a `!!` banner
naming the count and the first five. It does **not** raise. That is the house
style for a hard finding — loud, specific, and it still produces the rest of
the report so the reader can see the context the violation sits in.

`_provenance()` (new in JEV-32) is the same shape for config identity, and is
where a delegation-shape mismatch line would naturally sit if it is about the
rows' provenance rather than their content.

---

## 5. Clustering — the trap all four will hit

`session_id` is the clustering unit and the live corpus currently has **one
distinct session across 1,783 live rows**. Every clustered interval in the
report therefore reads:

```
PABAK  [clustered 95%]  0.991 [nan, nan] (n=459, clusters=1)
  INCONCLUSIVE BY RULE: only 1 cluster(s); 30 pre-committed as the minimum
```

Amendment A1.1 makes fewer than 30 clusters **inconclusive by rule**, whatever
the interval says, and A1.2 makes 30 sessions the stopping rule. So:

- **JEV-27** must size in *clusters*, not rows. The naive interval beside the
  clustered one in every section shows the gap: 459 rows buy you the precision
  of 1 cluster. The two prior-art results in the ticket (ICC 0.37–0.55; 30x
  run-to-run token variance) point the same way — buy breadth.
- **JEV-48** asks for a "session-clustered CI". `stats.clustered_bootstrap`
  takes the cluster labels directly; use `p.get("session_id") or
  p["decision_id"]` as `analyze.py` does, and report `ci.n_clusters` beside the
  interval, because A1.1 requires the count to be printed beside every interval
  always.

---

## 6. What the report now prints that you can rely on

Per surface, per question-set group:

```
  question set: pre_bash/v1#a   (the configured pin)
    arm set <arms joined by +>   rows=<n>
    (more than one arm set contributed; rows are NOT partitioned on it)
  operational
  ...
```

And, when they fire:

- `!! QUESTION SET '<qsid>' named by N row(s) cannot be resolved against
  questions/ on disk.` — those rows are **excluded**, not scored under another
  spec.
- `  question set: <other>   (NOT the configured pin <primary>; reported
  separately, never pooled)` — a full section, under the spec that pin names.
- `!!  CONFIG FINGERPRINT DISAGREEMENT: <a>, <b>` — byte-different config
  inside one question set.

The header's pricing line now reads
`pricing : <stamped on rows>   (as stamped on rows; config now: <current>)`.
If those two ever differ, that is your signal, and it is in the first 20 lines
of every report.

---

## 7. Deliberately not done — report, don't repair

Found while working JEV-32, **not fixed**, because each is outside the ticket
and two of them would move numbers:

1. **`analyze.py --context all` pools `live`, `synthetic` and `canary` into one
   surface section.** PREREGISTRATION §4 forbids pooling live with synthetic,
   and `determinism.py` keys its single-shot distribution on `run_context`
   explicitly for that reason with a comment saying so. `--context all` is an
   explicit opt-in flag rather than a default, and the header does print
   `run context : all`, so it is a foot-gun rather than a live defect — but it
   is the same defect class as JEV-32 one axis over. **Worth its own ticket.**
   Note it now prints all three arm-set eras in one group, which makes the
   pooling visible for the first time.
2. **`_operational_table` and `_attribution_table` aggregate across arm-set
   eras.** Both are descriptive rather than inferential, so no interval is
   affected, but the `$/1k` and `p50ms` figures for `cc_opus5` mix a three-arm
   and a four-arm concurrency regime — and per-arm latency under concurrency is
   exactly the thing that changes between those eras. JEV-46/47 should not
   quote `p50ms` across the boundary without splitting it first.
3. **`session_metrics.py` and `baseline.py` were not audited for the JEV-32
   defect class** — they read transcripts rather than run rows, so the
   question-set pin does not apply, but `baseline.py` stamps `pricing_version`
   on three different record shapes (grep `pricing_version`) and reads it back
   in one place. Whether those three agree is unverified. **JEV-49's problem,
   flagged here so it is not assumed.**
4. **`hooks/inline_shadow_bash.sh` derives `question_set_id` in jq on every
   hook fire**, so it picks up a mid-window config edit *immediately*, while
   `worker.py` pins config per process and never does until restart. Two row
   streams can therefore disagree about the pin within the same wall-clock
   second, and `run_context` does not separate them — both write `live`. This
   was JEV-30/31b's finding; JEV-32 did not change it and no analysis currently
   checks it.
