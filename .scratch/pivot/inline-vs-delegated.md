# Is delegating cheaper or dearer than working inline? — our own corpus

**Ticket context:** JEV-47 (`ISSUES.md:2397`), pivot goal "lower realised cost per
delegated task at equal success, no added felt latency".
**Script:** `.scratch/pivot/inline_vs_delegated.py` → `.scratch/pivot/inline-vs-delegated.json`
**Reproduce:** `python3 .scratch/pivot/inline_vs_delegated.py`
**Costing:** every dollar from `src/session_metrics.py:308` `call_cost`, fed by
`normalise_usage` (`:192`) and `merge_copies` (`:262`), keyed by `dedupe_key` (`:289`).
Nothing reimplemented. Pricing `config/pricing.json` v`pricing-2026-09-20b`.

---

## 0. READ THIS FIRST — the brief's premise does not match the corpus

The task brief describes `data/baseline/delegation-pre-rule-v1.json` as holding
**"120 delegated tasks across 29 sessions, general-purpose 78 (65%) / claude-code-guide 18 / Plan 12 / Explore 12."**

**No such record exists.** The file actually holds:

| source | delegated tasks | sessions |
|---|---|---|
| `data/baseline/delegation-pre-rule-v1.json` (`all_sessions.delegated_tasks`) | **7** | 15 (1 with any activity) |
| `data/baseline/manifest.json` (`total_delegated_tasks`) | **20** | 15 |
| `~/.claude/projects/…JEV-experiments/` on disk today | **33** | 1 session carries all 33 |
| …plus the post-pivot worktree project dir | **9** | 1 |

`grep` for `"120 delegated"`, `"general-purpose 78"`, `"claude-code-guide 18"`
across `ISSUES.md`, `SPEC.md`, `FINDINGS.md`, `PREREGISTRATION.md` returns
nothing. The *ordering* of the types is right; the counts are ~3.6× inflated.
The real type counts on disk are **general-purpose 26, claude-code-guide 3,
Plan 2, Explore 2** (spawn depth: 30 at 1, 3 at 2).

Consequence: the per-type breakdown below for `Plan`, `Explore` and
`claude-code-guide` is **n=2, n=2, n=3**. Those are anecdotes. Only
`general-purpose` (n=26) supports even a descriptive statement, and per JEV-55
(`ISSUES.md:3210`) all of it is **one `session_id`**, so no CI is computed
anywhere in this document and none should be quoted from it.

---

## 1. Headline answer

> **The AqueGen result does not replicate here.** The mechanism it blames — the
> subagent's cold-start cache write — is measurably **2.0%** of what a delegated
> task costs on our corpus, and it is charged at the *cheap* multiplier. Under a
> like-for-like comparison (same work, same number of turns) delegation is
> **cheaper**, not ~24% dearer.
>
> **But the margin is ~2×, not a landslide.** Delegation stops being cheaper if
> an inline agent can finish the same task in roughly **47–59% of the turns** the
> subagent took (§3.3). That is a plausible edge for an agent that already holds
> the context, and it is precisely the quantity this corpus cannot measure.
>
> Every dollar is a **lower bound** (FINDINGS.md:166 — transcript-derived cost
> runs ~27.6% under Claude Code's own total; measured coverage here **75.8%**).

Three measured facts carry it:

1. **The cold-start prefix write is 2.0% of delegated cost.** Median prefix
   16.5K tokens ≈ $0.10; median task cost $4.50. Across all 33 tasks the cold
   start totals **$3.46 of $171.94**. A 2% component cannot produce a 24% penalty.
2. **Every subagent cache write on this corpus is 5-minute TTL (1.25×); every
   main-session write is 1-hour (2×).** Measured: subagent files
   **4,431,529 tokens 5m / 0 tokens 1h**; main transcript **8,798 5m /
   2,163,568 1h**. The expensive multiplier applies to *zero* delegated tokens —
   i.e. the auth-dependent multiplier of JEV-14 / Amendment 8 **puts the cheap
   rate on the subagent side** and the dear one on the inline side. (This does
   not by itself flip the comparison — the sign is driven by term 3 — but it
   removes the amplifier AqueGen's argument relies on. It also refines
   Amendment 8's "every one of 4ba49645's rows is 1-hour": true of the *main*
   transcript, false of its subagents.)
3. **Delegated tasks are long.** Median **38 requests** per task (IQR 20–59,
   max 107). The one-off prefix write is amortised over dozens of turns, while
   the context those turns avoid re-reading is paid per turn.

---

## 2. The table — cost per delegated task

Corpus: `~/.claude/projects/-Users-aadharagarwal-projects-JEV-experiments/`,
33 tasks, all inside session `4ba49645`. Descriptives only (JEV-55).

### 2.1 Distribution of cost per task (USD)

| | min | p25 | median | p75 | max | mean | total |
|---|---|---|---|---|---|---|---|
| **all 33 tasks** | 0.109 | 1.720 | **4.500** | 7.275 | 13.354 | 5.211 | **171.94** |
| requests per task | 6 | 20 | **38** | 59 | 107 | 42.4 | 1,398 |

### 2.2 By `subagent_type` — n≤3 rows are anecdote, not estimate

| agent type | n | total $ | median $/task | cold-start share of cost |
|---|---|---|---|---|
| `general-purpose` | 26 | 164.51 | 6.204 | 1.8% |
| `Explore` | 2 | 3.45 | 1.725 | 6.8% |
| `Plan` | 2 | 3.03 | 1.513 | 7.5% |
| `claude-code-guide` | 3 | 0.96 | 0.375 | 7.4% |

Cold-start share is higher on the short task types purely because the prefix is
a fixed cost over fewer turns — the amortisation argument, visible directly.

### 2.3 Cost decomposition — cache-write isolated, as JEV-47 asks

Each component priced by calling `call_cost` with all other fields zeroed, so
the split is exact against the total by construction.

| component | $ | share of delegated cost | tokens |
|---|---|---|---|
| cache **read** | 76.02 | 44.2% | 154,198,704 |
| output | 42.62 | 24.8% | 1,735,881 |
| cache **write** (5m, 1.25×) | 27.19 | **15.8%** | 4,533,943 |
| cache **write** (1h, 2×) | **0.00** | **0.0%** | **0** |
| fresh input | 26.11 | 15.2% | 5,390,427 |
| — *of which cold-start prefix* | *3.46* | ***2.0%*** | *598,915* |

**All cache-write cost is the cheap TTL, and seven-eighths of it is not the cold
start at all** — it is ordinary mid-task context growth, which inline work pays
too (indeed pays *more* of, at 2×).

### 2.4 Post-pivot worktree corpus (9 tasks, separate — do not pool)

All `general-purpose`, all post-pivot, all post-rule: total **$26.23**, median
**$2.712**/task, median 18 requests, cache-write share 22.7%, cold-start share
**4.0%**, again **100% 5-minute TTL**. Same conclusion, independently.

⚠️ **This corpus is not stable across runs.** One of the 9 tasks is the agent
writing this document; its transcript grows while the script reads it, so the
worktree totals differ slightly on every invocation (delegated total moved
$26.23 → $29.78 between two runs an hour apart). Treat it as corroboration of
*direction* only. The 33-task main corpus is closed and does reproduce.

---

## 3. The counterfactual — and exactly how far it can be pushed

### 3.1 What is measurable and what is not

| quantity | status |
|---|---|
| subagent's cold-start prefix write | **measured** — first request's `cache_creation` |
| main-session context at the spawning turn (`C_main`) | **measured** — usage of the main-transcript assistant request carrying the `tool_use` whose id = `meta.toolUseId` |
| cache reads inline would have paid on that larger context | **estimable, under a stated assumption** |
| main-context bloat inline would impose on all *later* main turns | **NOT estimable** — depends on remaining session length |
| whether inline would take the same number of turns | **NOT measurable** — this is the assumption |
| whether inline would succeed equally | **NOT measurable here** — no outcome labels (JEV-36 open) |

### 3.2 The bound

For a task of N subagent turns spawned at main context `C_main`, with prefix `P`:

```
penalty(delegating) = P × write_multiplier(TTL read per row)      [measured]
saving(delegating)  = N × (C_main − P) × cache_read_multiplier    [assumes same N]
net = penalty − saving        → an UPPER BOUND on the delegation penalty
```

`net` is an **upper bound on the delegation penalty** because three further
terms are all omitted, and every one of them favours delegation:

- inline, each of those N turns' output also bloats the main context for the
  entire **remainder** of the session — not counted;
- inline turns write cache at the main session's **1-hour 2×** rate, where the
  subagent writes at 1.25× — not counted;
- `C_main` on many turns exceeds the 200K standard window (§3.4), so inline
  turns would attract **long-context premium** pricing, which
  `config/pricing.json` deliberately prices at standard.

`C_main` is measured as the **largest single `iterations[]` entry**, not the
turn's total, because `cache_read_input_tokens` at top level is the sum across
iterations (`session_metrics.py:192`). That is the conservative choice: a
smaller `C_main` shrinks the saving credited to delegation.

**Result: `net` is negative for 30 of 30 resolvable tasks.**

| | min | p25 | median | p75 | max |
|---|---|---|---|---|---|
| net $ (delegated − inline) | −13.54 | −9.66 | **−6.56** | −2.68 | −0.005 |

Sum over the corpus: **−$189.51**. Totalled the other way: the same 30 tasks
cost **$171.94 delegated** against **$357.53 inline at the same turn count** —
delegation ≈ **48%** of the inline bill. The three unresolved tasks are
`spawnDepth: 2` — they have no spawning `tool_use` block in the main transcript,
so `C_main` is reported unknown rather than guessed.

### 3.3 Sensitivity: how wrong can the "same N turns" assumption be?

This is the load-bearing question, and the answer is **not** comfortable.

If inline finishes the same task in a fraction `k` of the subagent's N turns,
its *whole* bill scales with `k` — output, reads and writes alike — not merely
the avoided context re-reads. So `inline(k) ≈ k × inline(1)` where
`inline(1) = D − penalty + saving`, and delegation stops being cheaper below

```
k* = D / (D − penalty + saving)
```

| break-even `k*` | min | p25 | median | p75 | max |
|---|---|---|---|---|---|
| as measured (n=30) | 0.081 | 0.430 | **0.470** | 0.532 | 0.993 |
| with `C_main` hard-capped at 200K (n=30) | — | — | **0.594** | — | 0.993 |

> **Inline would have to complete the median delegated task in roughly 47–59%
> of the turns the subagent took — about 18–22 turns where the subagent took
> 38 — before delegation stops being cheaper.** No task reaches `k* ≥ 1` under
> either variant, so delegation wins on every task at equal turn count; but a
> ~2× inline efficiency edge would erase the advantage entirely.

A ~2× edge is *plausible*: an inline agent already holds the repository in
context and skips the exploration turns a cold subagent must spend. Nothing in
this corpus measures whether it actually has one. **This, not the cache-write
arithmetic, is the real open question**, and it is what the paired run in §6
exists to settle.

*(An earlier draft of this document used `k = penalty / saving`, giving a median
of 0.0155. That is wrong: it scales only the extra-read term while leaving the
subagent's own turns in the inline arm. The figure above supersedes it.)*

### 3.4 An anomaly, disclosed rather than smoothed

**25 of 30 spawning turns report `C_main` above 200K** (range 45.9K–516.4K),
which exceeds `claude-opus-5`'s standard context window; the spawning model is
recorded as `claude-opus-5` on all 30, not `claude-opus-5[1m]`. This is
unexplained. It is why §3.3 carries the hard-capped variant: if those figures
are inflated, the capped row is the one to trust, and it still leaves
`k* ≈ 0.59`. Both spawning-side models are Opus 5, so the input rate is
common to both arms and does not itself bias the comparison.

### 3.5 Why AqueGen's three-way comparison only partly maps

AqueGen: `$1.36 inline < $1.68 routed to subagents < $2.01 same work at session tier`.
**30 of 33 tasks here ran on `claude-opus-5`** (3 on `claude-haiku-4-5-20251001`).
Our subagents already run *at session tier*. So this corpus speaks to AqueGen's
**$1.36 vs $2.01 leg — their widest gap — and finds the sign reversed.** The
middle "$1.68 routed" leg does not exist on our data at all; nothing here
measures the cost of routing, only the cost of delegating.

---

## 4. Attrition and retry cost

Retried delegated work would belong to delegation. **No retry signal is
detectable, and one class of retry is undetectable in principle.**

What was checked, on the main transcript of `4ba49645`:

| signal | result |
|---|---|
| `Agent` `tool_use` blocks in main vs depth-1 `meta.json` files | **30 vs 30** — every spawn has a transcript, every transcript has a spawn |
| spawns with no subagent transcript (task that died before writing) | **0** |
| `tool_result` for an `Agent` call carrying `is_error` | **0** |
| tasks with ≤1 request (abandoned immediately) | **0** (minimum is 6) |
| `SendMessage` `tool_use` blocks (continuations) | 11 — *continuations of live agents, not re-spawns; their cost is already inside the subagent transcripts and so already in §2* |

Within-task friction, already inside the costs above: 15 error `tool_result`s,
3 user interruptions, 3 permission denials across 33 tasks. Two `<synthetic>`
unpriced requests are zero-token artefacts (`session_metrics.py:289` documents
these) and contribute nothing either way.

**The limit:** a *semantic* retry — the owner reading a bad result and
re-delegating the same work under a fresh description — is indistinguishable
from a new task without reading prompt text, which the derived-numbers-only rule
(`manifest.json: derived_numbers_only`) forbids. So this is "no detectable retry
signal", not "no retries". Attrition does not rescue the AqueGen result here,
but it is not fully ruled out either.

*(A check in an earlier draft — "no `toolUseId` appears twice" — was removed:
tool-use ids are unique by construction and a retry would allocate a new one, so
that check could never have fired.)*

---

## 5. A side finding the owner should act on: the frozen baseline understates delegation

`src/baseline.py:197` `requests()` dedupes on `requestId` alone **keeping the
first copy**, and explicitly never reads `iterations[]`. PREREGISTRATION A8.2b
(`PREREGISTRATION.md:1103`) establishes that **all 48 keys that grow across
copies are inside subagent transcripts** — so this rule's error falls almost
entirely on *delegated* cost.

Re-running both rules over the identical files:

| | frozen JEV-24a rule | corrected (`session_metrics`) | gap |
|---|---|---|---|
| delegated cost, main corpus | $105.09 | **$171.94** | **+38.9%** |
| delegated cost, worktree corpus | $14.80 | **$26.23** | **+43.6%** |

**`delegation_rate_by_spend: 0.162` in `delegation-pre-rule-v1.json` is
therefore probably biased low** and should be recomputed under
`session_metrics`' rules before it anchors anything. *Probably*, not certainly:
the denominator moves too — the main session is 100% 1-hour TTL (2,163,568
tokens, worth roughly +$8 at the 2× vs 1.25× difference) plus whatever
`iterations[]` recovers on main rows. The numerator's +39% is measured; the
denominator's correction is not, and closing this properly means running
`session_metrics.cost_decomposition(..., until=cut_utc)` over the frozen
pre-cut window on both sides. (Either way it does not weaken §1 — a *larger*
delegated bill makes delegation look worse, and it is still cheaper.)

Also worth a ticket: `claude-opus-4-7` is now priced (`config/pricing.json`,
derived in JEV-49), so `manifest.json`'s `unpriced_requests: 78` is stale;
and the manifest's `pricing_version: pricing-2026-09-20` trails the config's
`pricing-2026-09-20b` (a JEV-32-style era boundary, harmless here because this
analysis re-reads transcripts and never touches run rows).

---

## 6. What this CANNOT tell us

1. **It is not a measurement of inline cost.** No inline execution of any of
   these 33 tasks exists. §3 is an *arithmetic bound* under an explicit
   assumption, not an observation. `src/bench_inline.py` is **not** the missing
   data — despite the name it benchmarks `hooks/inline_shadow_bash.sh` latency
   (fork/exec/jq/curl), and `data/inline/` holds its timing rows. Nothing in
   this repo contains a paired inline run of a delegated task.
2. **It cannot tell us how many turns inline would take** — and that single
   unmeasured number decides the answer. §3.3 shows the whole conclusion flips
   at a turn ratio of ~0.47–0.59. Everything else in this document is
   arithmetic; this is the assumption holding it up.
3. **No CI, ever, from this corpus.** JEV-55: one `session_id`. 33 tasks from
   one session is n=1 for any clustered interval. Descriptives only.
4. **Every figure is a lower bound.** Coverage against this session's own
   `cost-state.totalCostUSD`: computed $290.97 vs reported $383.78 = **75.8%**,
   in line with FINDINGS.md:166's ~72% ceiling. Missing spend is background
   models never written to disk plus under-reported Opus output.
5. **It says nothing about task success.** The pivot goal is cost *at equal
   success*. Outcome labels do not exist (JEV-36 open; JEV-48 notes routing
   headroom may be small regardless). If delegated tasks succeed less often, a
   per-task cost advantage is not a per-*unit-of-work* advantage.
6. **It says nothing about routing.** Everything ran at session tier. The
   cost of a tier switch — and TwinRouterBench's claim that cache writes on
   switch bill at the incoming tier's rate — is untested here.
7. **The per-type numbers are not comparable.** n=2/2/3 for three of four types,
   and the types are not assigned to comparable work.
8. **Single author, single repo, ~15h of one session.** The frozen record's own
   `limitations` field says it "bounds nothing and must be reported as an
   anchor, not a population rate." That applies to this document too.

**What would settle it:** paired runs — the same task, from the same session
state, executed once delegated and once inline, with a blinded grader on the
output. That is a modest experiment (the state fixtures in `data/states/` and
the canary set already exist) and it is the only thing that converts §3's bound
into a measurement.

---

## 7. Recommendation

**Do not delegate less on the strength of JEV-47 — but do not treat the
delegated path as settled either.** The AqueGen result does not replicate on our
corpus, and it fails for a mechanical reason we can point at rather than a
statistical one: their penalty is the cold-start cache *write*, and on our data
that write is **2.0%** of a delegated task's cost, is charged at the **cheap
1.25× 5-minute multiplier in 100% of cases** while the main session pays the
expensive 2× rate, and is amortised over a median of **38 turns**. At equal
work and equal turn count the 30 resolvable tasks cost **$171.94 delegated
against $357.53 inline** — delegation is roughly half, not 24% dearer, and the
sign holds on every single task. The honest qualification is that this is an
*arithmetic bound*, not a paired measurement, and its margin is ~2×, not a
landslide: **if an inline agent can do the same task in under ~47–59% of the
turns — plausible, since it already holds the context and skips a cold
subagent's exploration — the advantage vanishes.** And because outcome labels do
not exist (JEV-36 open), "cheaper per task" is not yet "cheaper per unit of
work". So: **keep the delegation rate, proceed with routing as planned, and add
three things to the plan** — (a) the paired inline-vs-delegated run in §6, now
the highest-value cheap experiment on the board, since it measures the turn
ratio that the entire conclusion hinges on; (b) recompute
`delegation-pre-rule-v1.json` under `session_metrics`' dedupe rules, because the
frozen delegated cost is ~39% low and it anchors the primary rate; (c) correct
JEV-47's framing — its acceptance criteria (delegation-shape equality per
`decision_id`, cache-writes per arm) remain worth building, but its premise that
delegation carries a ~24% cost penalty is not supported here and should not be
carried into the writeup unqualified. One further reason to resist "delegate
less": every task sampled here is `requestShape: background`. Moving that work
inline puts it back on the blocking main thread, spending directly against the
pivot's third constraint — *no added felt latency* — a cost AqueGen's comparison
does not price at all.
