# Cost reconciliation: what a transcript does and does not tell you

Every cost number this study publishes depends on reading Claude Code's own
transcripts correctly. So before trusting any of them, we reconciled our cost
formula against Claude Code's own authoritative total — the undocumented
`cost-state` line, which carries `totalCostUSD` plus per-model token counts and
per-model `costUSD`.

Method: one real session, 2,684 lines, `claude-opus-5[1m]`, plus 382 subagent
lines. Reproduce with:

```sh
uv run src/session_metrics.py <transcript.jsonl> --reconcile
```

## What we confirmed exactly

Solving for the implied input rate from `cost-state.modelUsage`, assuming the
documented 1:5 input:output ratio and the 1.25× / 0.10× cache multipliers:

| model | implied input rate | verdict |
|---|---|---|
| `claude-haiku-4-5-20251001` | **$1.0000/1M** | exact — matches published pricing |
| `claude-sonnet-5` | **$2.0000/1M** | exact |
| `claude-opus-5[1m]` | $5.1990/1M | *not* flat $5.00 — see below |

Two things fell out of this that are worth stating plainly:

**Web search is billed at exactly $0.01 per request.** The Haiku line was off by
$0.48 until `webSearchRequests: 48` was priced in, at which point it matched to
the cent. Any cost model that ignores `webSearchRequests` is wrong by that much.

**The `[1m]` suffix does not mean every request was billed at the long-context
premium.** It means the 1M context window was *enabled*. Premium pricing is
applied per request, above a threshold, so the effective blended rate on a long
session lands between the standard and premium rates — here $5.199 against a
$5.00 standard rate. We price at the standard rate and publish the resulting
shortfall rather than fitting a blended constant that would not transfer to
another session.

## Four traps in the transcript format

**`input_tokens` is a trap.** A real line reads `"input_tokens": 2` beside
`"cache_creation_input_tokens": 17315, "cache_read_input_tokens": 30419`.
Summing `input_tokens` yields a cost figure wrong by four orders of magnitude.
In this session: 7,788 input tokens against 101,494,941 cache reads.

**Lines duplicate ~3.2×.** 1,047 assistant lines carry 328 unique `requestId`s.
Deduplication by `requestId` is mandatory.

**`usage.iterations[]` restates the same numbers.** A second, independent
double-counting hazard that looks like additional data.

**A session is not one file.** Claude Code writes the main transcript as
`<session-id>.jsonl` and every subagent it spawns into a sibling
`<session-id>/subagents/*.jsonl`. Those turns are billed to the session but
appear nowhere in the main file. On this session, folding them in moved the
reconciliation from **−32.0% to −27.6%** and added 38 requests, 1.95M cache
reads and 524K cache writes. On an agent-heavy session the omission would be
larger still.

We found this *because* of the reconciliation check, not before it. A cost
number that had never been compared against ground truth would have shipped 32%
low and looked entirely reasonable.

## The residual gap, and why we are not closing it

After subagents, **−27.6%** remains. It decomposes into two parts:

**Models that never appear on disk.** `cost-state` bills 929,938 Haiku input
tokens and 41,772 Sonnet input tokens for this session. Neither model appears in
any assistant line, in the main transcript or in any subagent file. These are
background calls — title generation (`ai-title` is its own line type), mode
classifiers, search summarisation — that Claude Code bills but does not
transcribe. Together they account for roughly $5.09.

**Opus work not written locally.** Our deduplicated Opus totals run about 10%
under on cache reads and 40% under on output tokens. We verified this is not a
parsing artefact: zero assistant lines carry usage without a `requestId`, and no
non-assistant line type carries token counts.

The honest conclusion is a limitation, not a bug:

> **A session's true cost cannot be reconstructed from its transcripts.** The
> transcript is a faithful record of the conversation, not a billing ledger.
> Any study quoting per-session cost from transcripts alone — including the
> "before" baseline in this one — is quoting a **lower bound**.

So the baseline reports both numbers side by side, always: what we computed from
the transcript, what Claude Code itself reported, and the delta between them. The
delta is a published figure, not a defect to be tuned away. For the arm
comparison this limitation does not apply at all — there we bill from each API
response's own `usage` field, which is exact.
