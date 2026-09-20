# JEV-49 → wave A3: the corrected cost pipeline, and what each ticket must use

Closed 2026-09-20. Every number below is reproducible offline from
`src/session_metrics.py` against `~/.claude/projects/` (read-only, derived
numbers only). No API spend, no network.

---

## 1. The one thing JEV-27 must take from this

**Size against the post-fix per-delegated-task cost, over the JEV-24a frozen
window (≤ 2026-09-20T14:50:14Z), one task = one subagent transcript:**

| | pre-fix | **post-fix (use this)** |
|---|---|---|
| n | 20 | **20** |
| total | $42.5699 | **$72.4099** |
| mean | $2.1285 | **$3.6205** |
| median | $1.7026 | **$3.2848** |
| SD | $1.8119 | **$2.7503** |
| min / max | $0.0787 / $5.7624 | **$0.1086 / $8.5952** |
| CV | 0.851 | **0.760** |

Post-fix values, sorted, so you can bootstrap rather than assume normality:
`0.11 0.38 0.44 0.48 0.70 0.81 1.95 2.22 2.45 2.75 3.82 4.10 4.50 6.00 6.17
6.24 6.40 7.03 7.28 8.60`
Requests per task: `6 7 8 9 14 19 20 22 22 24 26 34 38 40 41 47 52 58 59 78`.

**Three warnings, all of which change a power calculation:**

1. **n = 20 with a heavy right tail.** Max is 79× min. CV 0.76 even after the
   fix. A normal-theory calculation on this will lie; bootstrap the 20 values.
2. **The fix did not shift the distribution uniformly — it is +70% on the
   total.** The correction (completed-copy dedupe) occurs *only* in subagent
   transcripts, so delegated cost moved much more than session cost (+39.6%).
   Anything sized against the pre-fix delegated number is under-sized by a
   factor of ~1.7 in the mean and ~1.5 in the SD.
3. **The unbounded set is not stable.** Measured over all subagent transcripts
   on disk it is n=32, mean $5.0417, SD $3.5261 — but that set grows while
   agents work, including while you read this. Use the frozen window, or state
   your own cutoff.

Web search is **$0.00** in this corpus, so it is not a term in your variance.
`data/runs/` is **not** a cost source for delegated work — see §5.

## 2. What changed in the pipeline (JEV-46/47/48 inherit this)

Four corrections, all in `src/session_metrics.py`, all tested:

| | rule | effect on the $125.58 baseline |
|---|---|---|
| `normalise_usage` | token fields summed from `iterations[]`; cache scalars NOT; TTL sub-object summed | +$4.69 |
| `merge_copies` | duplicate copies folded per-field max — the **first** copy is a streaming placeholder (`input_tokens: 2`, no iterations) | **+$29.84** |
| `call_cost` | 1-hour cache writes at 2×, 5-minute at 1.25×, read per row | +$6.75 |
| `pricing.json` | `claude-opus-4-7` priced by solving cost-state (exact in every cost-state session; 40 at the time of writing) | +$8.50 |

Total **$125.582946 → $175.354996 (+39.6%)**. `config/pricing.json` is now
**`pricing-2026-09-20b`**; rows stamped `pricing-2026-09-20` were costed under
the old table and must not be pooled with `-b` rows silently.

Public API you can call: `normalise_usage`, `merge_copies`, `dedupe_key`,
`call_cost`, `analyse(path, strict=True)`, `cost_decomposition(path, since,
until)`, `reconciliation_window(paths, since, until)`, `UnpricedModelError`.

## 3. The reconciliation, and the criterion left open

Bounded window **2026-09-19T19:58:56Z → 2026-09-20T14:50:13Z**: residual against
Claude Code's own `cost-state` is **−$0.2234 (−2.56%)**, negative by
construction. **It validates the `claude-opus-4-7` rate and the 1.25×
multiplier and nothing else** — the 14 sessions carrying a `cost-state` contain
no iteration under-count, no multi-copy key and no 1-hour write. The Console
half is OPEN; PREREGISTRATION A8.4 lists exactly what the operator must pull.
**Do not quote a Console number; none exists.**

## 4. Lines this ticket needed in files it did not own

* **`src/baseline.py`** — `requests()` (~line 215) still uses first-copy
  `requestId` dedupe and raw top-level usage, so `manifest.json`'s
  `total_computed_cost_usd` and `total_delegated_cost_usd` are **pre-fix**.
  Three-line change, no new behaviour:
  ```python
  # in requests(): replace the rid/seen block and the bucket literal with
  key = sm.dedupe_key(line)
  if key is None:
      continue
  # accumulate per key with sm.merge_copies(...) and emit after the loop
  bucket = sm.normalise_usage(message.get("usage") or {})
  cost = sm.call_cost(model, bucket)      # not cl.cost_usd -- TTL-aware
  ```
  Until then `data/baseline/manifest.json` disagrees with `session_metrics` by
  the amounts in §2. Both are on disk; neither is silently wrong.
* **`src/arms/claude_cli.py:202`** — deliberately skips `iterations[]`, and run
  rows persist only four scalars. **Persist `usage.iterations` and
  `usage.cache_creation` verbatim** or no run row will ever be correctable.
* **`tests/test_pipeline.py`** — two assertions hard-coded
  `"pricing-2026-09-20"` and went red on the version bump. They now read the
  value from `config/pricing.json` instead. **That file also carries another
  agent's uncommitted `cl.reset_caches()` hunk, so JEV-49 did not commit it** —
  its owner must land both.
* Coordinator's question: `data/baseline/*.json*` carries **one**
  `pricing_version` value (`pricing-2026-09-20`) across all three record shapes,
  so they agree today. After the bump they will diverge from new rows unless
  baseline is regenerated.

## 5. Things you will otherwise get wrong

* **Never read `data/runs/` for a cost figure.** 2,005 rows, four scalar usage
  fields, no `iterations[]`, no TTL split, `model: null` on every row. The
  corrections cannot be applied retroactively. Session/subagent transcripts are
  the only correctable source.
* **`anthropics/claude-code#95555` is NOT present** — 0 of 3,790 rows. The
  `input_tokens: 2` shape on 81% of rows is ordinary cache-read behaviour.
  Do not cite one as the other.
* **`requestId` and `message.id` counts differ for a boring reason**:
  `<synthetic>` rows carry a `message.id`, no `requestId`, zero tokens.
* **Duplication is 1.97× here, 3.19× on Redline.** Corpus, not vendor change.
* **`test_validation.py` failed once, intermittently, in `run_all.sh`** and did
  not reproduce in 17 direct runs or 3 full-suite runs. Not JEV-49's file;
  flagged, not repaired. Suspect a randomised test in `OptimismGap`.

## 6. Where the stale $125.58 is quoted (checked, 2026-09-20)

`grep -rn "125\.58|42\.57|unpriced" FINDINGS.md SPEC.md README.md docs/ reports/`
returns **nothing**. The pre-fix headline lives in exactly two places, both of
which now say so: `data/baseline/manifest.json` (not regenerated — see §4) and
the ISSUES.md JEV-49 table, which shows it as the "was" column. No prose
anywhere quotes a cost figure that this ticket invalidated.
