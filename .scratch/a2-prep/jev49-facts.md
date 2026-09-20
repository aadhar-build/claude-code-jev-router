# JEV-49 prep — the three cost bugs, measured on OUR corpus

Read-only analysis, 2026-09-20, over
`~/.claude/projects/-Users-aadharagarwal-projects-JEV-experiments/*.jsonl`.
Nothing was written outside this folder. Numbers below are ours, not the
third-party reports — where they differ, ours govern.

| quantity | value |
|---|---|
| transcript files | 23 |
| lines | 5,058 |
| assistant rows | 1,301 |
| unique `requestId` | **659** |
| unique `message.id` | 660 |
| **duplication factor** | **1.97x** |
| rows carrying `usage.iterations[]` | 1,293 of 1,301 (**99.4%**) |
| rows where `sum(iterations[].input_tokens)` **exceeds** top level | **30** |
| models seen | `claude-opus-5` 1,080, `claude-opus-4-7` **217**, `<synthetic>` 4 |

## 1. `iterations[]` hides input tokens — confirmed, and worse here than reported

The worked example from our own corpus:

```
top-level input_tokens : 4
iterations[]           : (2, 80), (158467, 7255), (2, 615)
sum of iteration input : 158,471
```

**158,467 input tokens invisible in a single record.** The third-party report
(jverhoeks/claudecounter PR #26) quotes 88,762 for its worst case; ours is 1.8x
that. 30 rows are affected.

**The asymmetry is the part that is easy to get backwards**, and `docs/PLAN.md`
currently states the wrong half:
- **token fields** (`input_tokens`, `output_tokens`) **MUST** be summed from
  `iterations[]`
- **cache fields** (`cache_creation_input_tokens`, `cache_read_input_tokens`)
  **MUST NOT** be — the top-level value already equals the sum

`docs/PLAN.md` says "ignore `usage.iterations[]`". That is correct for cache
fields and **wrong for token fields**, and it is wrong on 30 rows by up to
158k tokens each. Fixing that line is in JEV-49's acceptance criteria.

Note 99.4% of rows carry `iterations[]`, so this is not an exotic path.

## 2. Duplication — confirmed at 1.97x, NOT the 3.1x in the plan

`docs/PLAN.md` records 3.1x from an older, corpus-wide sample. **Our project
corpus is 1.97x** (1,301 assistant rows / 659 unique `requestId`). Dedupe is
still mandatory; the *number* in the plan is stale and should be corrected to
ours, with both stated and the difference attributed to corpus, not to a change
in Claude Code.

`message.id` gives 660 unique against `requestId`'s 659 — they are not
interchangeable. Dedupe on the pair, per `claude-spend#31`.

## 3. `input_tokens: 2` — real, but DO NOT overclaim it

1,050 of 1,301 assistant rows (81%) have `input_tokens <= 2` alongside a
`cache_read_input_tokens` above 1,000.

**This is normal Claude Code behaviour, not a defect.** Almost every turn is a
cache read. The correct claim is the one the plan already makes: **summing
`input_tokens` to estimate cost is meaningless** and yields a figure wrong by
orders of magnitude.

It is **not** the same thing as `anthropics/claude-code#95555`, which is a
genuine defect where *every* top-level counter is zeroed while
`usage.cache_creation` retains real values. **Whether that distinct defect is
present in our corpus has NOT been checked** — JEV-49 should check it
separately and not inherit this row count as evidence for it.

## 4. An unpriced model is silently excluded — 217 rows

`claude-opus-4-7` appears on **217 assistant rows** and is absent from
`config/pricing.json`. `data/baseline/manifest.json` records
`unpriced_models: ['claude-opus-4-7']`, `unpriced_requests: 78`, and states that
this spend is **not included** in `total_computed_cost_usd` ($125.58).

This is the right behaviour — `config_loader.cost_usd()` returns `None` rather
than guessing, which is exactly the guard that prevents `claude-spend#31`'s
437% over-report from substring-matching "opus". **But JEV-49 must decide
whether "excluded and noted" is good enough for a published total**, because
today a reader sees a cost figure that omits 217 rows unless they open the
manifest. Options: price the model, or promote the exclusion into the headline
rather than the manifest.

## What A2 can skip

- Do not re-derive any of the above; cite this file and spot-check one row.
- The duplication factor, the `iterations[]` example, and the unpriced-model
  count are all reproducible from the one-screen script in this commit's
  message; re-running it costs nothing and no API calls.

## What A2 still has to find out

- Is `#95555`'s actual defect (all top-level counters zero, `usage.cache_creation`
  populated) present here? Not checked.
- **Our auth path**, which decides whether cache writes bill at 2x (1-hour TTL,
  subscription) or 1.25x (5-minute TTL, credits/API key). Undeclared today and
  required by the pre-registration.
- The Console reconciliation. Nobody has published one; it is the contribution.
