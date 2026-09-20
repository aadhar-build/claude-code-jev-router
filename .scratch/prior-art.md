# Prior-art and landscape review

**Compiled 2026-09-20 by a research subagent. Not committed yet; not folded into SPEC.md or
PREREGISTRATION.md. Nothing here has been independently re-verified by me except where noted.**

Read this alongside `.scratch/wave2-prep.md`. Where a finding demands a pre-registration change it is
tagged **[AMENDMENT]**; where it demands a design decision from the user it is tagged **[DECISION]**.

---

## Headline: three of our framing assumptions came back inverted

1. **"Nobody has published measured numbers on Jev."** False. At least **11 independent Tier-A
   benchmarks** exist within 5 days of launch, several pre-registered. Writing "no independent
   evaluation of Jev exists" would be **factually wrong and publicly checkable**. The true and more
   useful statement: *independent evaluations exist, are mixed-to-unfavourable, and none measures
   tier routing end-to-end.*
2. **"A sceptic will say a two-line static rule captures most of the gain."** The sceptic has
   evidence. Static heuristics have already produced **46%, 28%, and ~17%** measured savings in
   agentic coding harnesses, and **four independent benchmark papers** find learned routers fail to
   reliably beat a trivial baseline.
3. **"We independently found transcript cost under-reports by ~27.6%."** Documented by others first,
   with mechanisms. One reconciliation puts the ceiling for any `~/.claude`-reading tool at **~72% of
   the real bill** — i.e. ~28% under-report, almost exactly our number.

**Surviving novelty:** wall-clock as a **co-primary** outcome (nobody reports it), and
**decision-curve / net-benefit analysis** applied to routing (nobody has done it, in any vocabulary).
Both are narrower than the brief assumed, and both are real.

---

## 1. Jev / TypeSafe AI

Launched **2026-09-15**. TypeSafe AI, SF, $40M seed, founder Diogo Almeida (ex-OpenAI). HN launch
thread 1,655 points / 456 comments (`news.ycombinator.com/item?id=49717558`). On Vercel AI Gateway
from 2026-09-16 (changelog publishes no adoption or latency numbers) and Cloudflare Workers AI.
Model IDs in the wild: `jev-latest`, `jev-preview`, `jev-1.13`, `jev-1.13.0`.

### Vendor claims, and the caveats to quote instead of the headline

Vendor: 70–500ms end-to-end, "most around 100ms"; $0.042/MTok input, output free; **193.6× faster,
444.6× cheaper**; "0% type errors, mathematically impossible."

- Reference answers are the **average of GPT-6 Astra and Fable 5.1**, not ground truth. TypeSafe's
  own footnotes concede this "biases towards OpenAI and Anthropic's models."
- The four workflows were **built by TypeSafe's own capabilities team**.
- TypeSafe's own dashboard reportedly discloses **Jev 67.8% vs comparison models 74.1%** — a 6.3pp
  deficit on their own evals. ⚠️ Via explainx.ai fact-check citing the dashboard; **not re-confirmed
  on typesafe.ai**.

### Independent measurements — mixed

`jevbench.xyz/benchmarks`, 11 Tier-A runs:

| Task | Author | n | Date | Jev | Comparator |
|---|---|---|---|---|---|
| Phishing detection | anisselbd | 2,000 | 09-17 | **62.6%** | Haiku 4.5 **81.3%** |
| Email classification | bitnovus | 5,733 | — | 93.6–99.3% | — |
| Banking77 intent | ickma2311 | 208 | 09-18 | **83.2%** | BGE encoder **93.3%**, Terra 87.5%, nano 79.3% |
| CLINC150 routing | ickma2311 | 200 | 09-18 | **87.0%** | Terra **91.5%**, nano 79.5% |
| Tool-call risk | themsquared | 60 | 09-17 | 91.7% | — |
| ORDER BY probability (hard) | yodablocks | 306 | 09-18 | **FAIL 4 of 6 pre-registered gates** | — |
| Confidence routing | FirasSX914 | 500 | — | 80.2% cascade | — |
| Agent workloads | iammrduncan | 424 | 09-17 | withheld | — |

JevBench's own caveat: **"no run here has been independently reproduced yet."**

**Most damaging** — `github.com/anisselbd/jev-phishing-bench`, n=2,000: accuracy 62.6% vs Haiku 4.5's
81.3%, **McNemar p < 0.0001**; recall on phishing 43.2% vs 76.4%; **ECE 0.154 vs Haiku's 0.097** —
Jev *worse calibrated* than a cheap LLM, contradicting the RLCD marketing; latency p50 239ms vs
687ms; cost $0.038 vs $0.462/1,000.
**★ "Jev's best single signal achieved 89.4%, underperforming a simple regex rule at 91.8%."**
Cite in threats-to-validity.

**Counter-evidence on calibration** — `github.com/themsquared/jev-benchmark`, n=60 hand-labelled
tool-call risks: 91.7% overall (100% clear / 71.4% ambiguous / 91.7% adversarial); p50 421.6ms, p95
542.0ms. **Every incorrect answer came with hedged confidence** — no wrong prediction at confidence
1.000; errors spanned 0.130–0.785.
→ **Calibration is task-dependent. Neither the vendor claim nor either independent result transfers.
We must measure calibration on our own task.**

**Pre-registered baselines eval** — `github.com/ickma2311/jev-baselines-eval`. Both experiments
returned **AMBIGUOUS**. Two findings that bear directly on our design:
- **Threshold degeneracy: at exact accuracy parity with the frontier model, Jev requires 100%
  escalation — the routing policy collapses to "always use the expensive model."** At 1pp below
  parity it escalates 22% (vs nano's 48.5%).
- **Confidence-ranking quality does not replicate:** AUROC 0.853 (Jev) vs 0.795 (LLM) on Banking77,
  **reversed** on CLINC150 (0.734 vs 0.816), paired CI including zero.

**Crowd-sourced** — `openchamber.dev/blog/jev-typesafe-ai/`, 12,759 tweets: user-reported **median 7×
speed** (IQR 2–20×) vs vendor's 193.6×, **median 30× cost** (IQR 5–85×) vs vendor's 444.6×. A ~25×
gap between marketing and the field. 62 "running in production" claims, none with verified metrics.

**HN critiques worth citing** (thread 49717558): `jrickert` — "70ms vs 329s is not apples-to-apples
if the LLM baseline is doing full chain-of-thought"; `8note`/`bigglebear` — type-safety ≠
correctness, conceded by the CEO (`CompleteSkeptic`); `jceg` — refusing to publish benchmarks is
itself a signal. CEO confirmed they avoid benchmarks in favour of "one-off evals" and keep the
architecture "close to the chest."

⚠️ **Every.to** reportedly measured ~25× faster / ~580× cheaper on extraction (0.35s vs 8.83s),
missing 1 of 7 planted defects. **Primary article not located** — all sources are aggregators.

---

## 2. Classifiers inside Claude Code hooks — not novel

### ★ The cold-connection trap — the single most important finding for our wall-clock endpoint

`github.com/clownware/bouncer` PR #33, merged **2026-09-19**. The project's docs cited ~190ms for
Jev. That number came from a script making one call then **looping inside the same process, where
Node keeps the connection open**. A hook is a **new process per tool call**, so every call opens its
own. Measured from the installed plugin over 66 judged calls:

**median 437ms, p95 549ms, range 382–653ms** — socket ~95ms + TLS ~193ms (two round trips) +
request/model/response ~245ms. Warm-up calls in production (426ms, 479ms) were *no faster*,
disproving connection reuse.

This reconciles the entire spread in the field: vendor 70–500ms, crowd median 76ms (server-side),
themsquared 421.6ms p50, RahulBalakavi 230.8ms p50, bouncer 437ms.

**[AMENDMENT] If we measure Jev latency anywhere other than inside the actual hook process, we
under-report by roughly 2×.** Our `bench_inline.py` and `inline_shadow_bash.sh` are the right
instruments; the worker-side arm timings are *not* a proxy for enforce-mode cost.

### Jev as a PreToolUse permission gate

`github.com/RahulBalakavi/claude-code-jev`, `typesafe/jev-1.13` via OpenRouter, 18 labelled tool
calls × 5 passes = 90 decisions: **p50 230.8ms, p95 459.2ms**; $0.0000227/decision; ~$0.25/month at
500 calls/day; **80–81% match** with reference decisions; 0 dangerous actions allowed; threshold
0.85. Author's own caveat: *"The fixture is synthetic and good for smoke testing. Replace it with
blindly labeled real tool calls before you claim anything about accuracy on your traffic."* The "~93%
lower latency" claim is against a published LLM-judge reference, **not** a controlled A/B.

### ★ First-party prior art we cannot miss

Anthropic, **"How we built Claude Code auto mode"** (`anthropic.com/engineering/claude-code-auto-mode`,
**2026-03-25**). Anthropic shipping exactly our architecture — a classifier as Claude Code's decision
layer:
- **Two-stage cascade**: stage 1 is a *single-token* decision (no reasoning, instructed to err toward
  blocking); stage 2 applies reasoning only to flagged actions, with a near-identical prompt so
  **stage 2 is almost entirely a cache hit from stage 1**. Cheaper than a separate classifier vendor.
  **We must explain why Jev beats this.**
- Runs on **Sonnet 4.6 regardless of session model**.
- Measured: real traffic n=10,000, stage 1 FPR 8.5% → stage 2 **0.4%**; real overeager n=52, FNR 6.6%
  → **17%** after stage 2, which they call "the honest number"; synthetic exfil n=1,000, FNR 1.8% →
  5.7%. No latency numbers published.
- **Fail-closed**; session terminates after 3 consecutive or 20 total denials.

### ★ [AMENDMENT] Fail semantics differ and have opposite cost signatures

- Claude Code's documented hook behaviour is **fail-open** (a PreToolUse hook that exceeds its
  timeout is cancelled and does not block the tool).
- Auto mode is **fail-closed**.
- togishima's dispatcher **fails to frontier** (Jev outage → everything routes to Opus, cost blows up
  silently).

Three regimes, three failure costs. **Pre-register ours.** (Ours is fail-open, per plan decision;
say so explicitly and note the cost signature.)

Other ecosystem patterns: CloneGuard (ONNX embedding classifier), claude-injection-guard (regex →
local Ollama), Morph Reflexes (fine-tuned classifiers from hooks). Reported hook overheads: command
hooks ~5ms spawn (10–50ms on macOS), prompt hooks 300–2000ms, agent hooks 2–10s.

---

## 3. LLM routing literature — the failure modes

| Work | Date | Routes on | Savings | **Limitation that matters** |
|---|---|---|---|---|
| **FrugalGPT** (2305.05176) | 2023-05 | Learned scorer on cheap answer, cascade | up to 98% | **Latency strictly additive and unparallelizable.** When all models agree it can't tell if the cheap one was right, so it queries the whole chain anyway. Needs per-task ground truth. |
| **Hybrid LLM** (2404.14618, ICLR'24) | 2024-04 | BERT difficulty predictor | 22% to 13B at <1% drop | **Quality metric is BART score**, a cheap proxy. Useless for a coding study. |
| **AutoMix** (2310.12963, NeurIPS'24) | 2023 | Self-verification + POMDP | ~50% | The POMDP exists *because* self-verification is "noisy and ill-calibrated, particularly for reasoning tasks." |
| **RouteLLM** (2406.18665, ICLR'25) | 2024-06 | Chatbot Arena preference data | 3.66× MT-Bench @95% PGR | **★ Trained only on Arena data; routers "perform poorly at the level of the random router" on MMLU.** Router overhead ≤0.4% of GPT-4 cost. |
| **RouterBench** (2403.12031) | 2024-03 | 405k inferences | oracle 2–5× headroom | **Authored by Martian, a router vendor.** |

2025–2026: **MTRouter** (2604.23530, ACL'26) multi-turn cost-aware routing — 58.7% cheaper on
ScienceWorld, 43.4% on HLE; win attributed to **fewer model switches** and **tolerance for transient
errors**. **RouterXBench** (2602.11877) makes OOD robustness first-class. "Learning to Route LLMs
from Bandit Feedback" (2510.07429): RouterDC and GraphRouter **"struggle to generalize, with
performance dropping sharply on out-of-distribution tasks."** "When Efficiency Backfires"
(2605.17288): cascades are strictly more attackable than single models.

### ★ Routing inside agent loops — error compounding is documented

**SWE-Router (arXiv:2607.00053, 2026-06-30)** — two findings that should change our design:
- *"Existing LLM routers operate on the task description alone, which inherits an
  information-theoretic Bayes-error floor in agentic settings: a similar issue can hide either a
  localized typo or a multi-module refactor, and the prompt does not separate the two."* Their fix:
  let the cheap model run K=3 exploratory turns and route on the **partial trajectory**. Route-AUC
  0.780, **+15.3pp over the K=0 description-only router.**
  → **Our `user_prompt`/`route` surface is exactly the K=0 router this paper says has a Bayes-error
  floor. This is a stated limitation we should own, and possibly a second arm that routes on partial
  trajectory.**
- **★ On escalation the strong model restarts from the original query rather than continuing the
  cheap model's trajectory, "because conditioning m2 on m1's reasoning has been seen to bias m2
  toward m1's mistakes."** Primary-source statement that cheap-model output poisons downstream
  context. Forces a binary: restart (throw away cheap work) or continue (inherit errors).
  **[AMENDMENT] Pre-register which.**
- Exploratory turns are **"paid up-front and counted in any escalated run's cost."**
- Routing curves can pass *above* the all-strong endpoint: weak and strong models solve non-identical
  subsets, so a router can in principle beat pure Opus.

**TwinRouterBench (arXiv:2605.18859, 2026-05)** — built because "existing router benchmarks evaluate
routers only on one-shot prompts… never test whether a cheaper replacement preserves downstream task
success."
- **Compounding quantified: "even one under-routed step in an 8–13 call trajectory fails the
  instance."**
- **Claude Opus 4.6 as LLM-router identified only 7 of 147 verified-high steps as needing the top
  tier — and all 40 SWE trajectories failed.**
- Trained router **$25.66 vs $54.73 unrouted Opus** at comparable resolve rate (~53% saving).
- Static track: trained SR-KNN 77.89 vs **rule-based routers 52.76–56.96**.
- **Only source that prices the switching penalty: "cache writes on tier switch are charged at the
  incoming tier's rate."**

**"How Do AI Agents Spend Your Money?" (arXiv:2604.22750)**:
- **"Runs on the same task can differ by up to 30× in total tokens."**
- **"Higher token usage does not translate into higher accuracy; accuracy often peaks at intermediate
  cost and saturates at higher costs."** Corroborated by HAL: *"in only 1 of 9 benchmarks do we
  observe the most costly model run on the Pareto frontier."*
  → **★ Our control — everything on Opus — is probably off the Pareto frontier, which makes it a
  weak control and a flattering comparator. Say so before a reviewer does.**
- **"Models fail to predict their own token usage"** (correlation ≤0.39, systematically
  underestimating) — never let the router use a self-estimate.

**MAST (arXiv:2503.13657, NeurIPS'25)** taxonomises 14 multi-agent failure modes over 200+ traces
(Specification 41.8%, Inter-Agent Misalignment 36.9%, Verification 21.3%). **It does not name
model-tier heterogeneity as a failure cause, and no paper isolates it.** A legitimate novelty claim.

### Router overhead budget

RouteLLM ≤0.4%; liteLLM's phase heuristic "well under a millisecond, no extra LLM call"; kNN 65.69s
vs >866s for graph/attention routers. Field-wide: **<1% of end-to-end latency for lightweight
routers, up to ~5% tolerated, >10% a problem.** Jev at 437ms cold inside a hook, against delegated
subtasks lasting tens of seconds to minutes, sits comfortably inside that — *if we route once per
delegation rather than once per tool call*. (We do: `agent_route`.)

**★ The overhead that actually bites is cache invalidation, not classifier latency.** Input tokens
dominate agentic cost and Claude Code leans hard on prompt caching, so mid-session tier switching
invalidating the cache is plausibly the dominant cost term. (Argument piece: Avi Chawla, "LLM Routing
Can Cost More Than Not Routing," 2026-09-07 — illustrative; TwinRouterBench independently confirms
and prices the mechanism.)

---

## 4. Does a cheap classifier beat a trivial heuristic? **The sceptic is currently winning.**

Five independent sources.

1. **★ LLMRouterBench (arXiv:2601.07206, ACL 2026 Findings; 400K+ instances, 21 datasets, 33 models,
   10 routers).** Verbatim: *"many routing methods exhibit similar performance under unified
   evaluation, and several recent approaches, including commercial routers, fail to reliably
   outperform a simple baseline."* Baseline = **Best Single**. **OpenRouter at −24.7% vs Best
   Single.** HybridLLM and FrugalGPT "struggle to trade cost for savings while preserving Best Single
   accuracy." Best routers managed only **+4% accuracy / −31.7% cost**. Diagnosis: model-recall
   failure — on queries where ≤3 of 33 candidates are correct, routers pick right only **24.6%** of
   the time.
2. **★ RouterArena (arXiv:2510.00202, ~8,400 queries, 21 routing methods).** The **"routing
   plateau"**: methods converge to a narrow band far below oracle, caused by a *predictability
   bottleneck* — "routers mainly learn global averaged model-performance trends rather than
   fine-grained query-specific routing signals." *"Most routers cluster near baseline performance,
   suggesting they over-rely on the strongest model."* **NotDiamond ranks #12 "because it frequently
   selects expensive models"**; NIRT-BERT achieves "only baseline-level accuracy while incurring 378%
   of the cost."
3. **★ "When Simple kNN Beats Complex Learned Routers" (arXiv:2505.12601).** kNN (k=100) AUC 52.68 vs
   MLP 51.71, GNN 51.82. **Under distribution shift kNN degrades least (−2.63), matrix factorization
   most (−6.67).** 13–14× cheaper to compute. ⚠️ arXiv ID implies May 2025; one fetcher reported
   2026 — likely a v2 date.
4. **Lynkr's own write-up** (dev.to, "the numbers we'd rather hide"): their router ranks **15th of
   27** on RouterArena; **RouteLLM 48.07, NotDiamond 57.29**. Their **Opt.Sel = 10.97** — when
   multiple models could answer correctly, it picked the cheapest **~11%** of the time. Conclusion:
   "identifying when escalation is necessary matters more than optimizing leaderboard position."
5. **RouteLLM's own near-random-on-MMLU result** (above).

### The heuristics already work, in our exact setting

- **★ liteLLM, "Subtask-Specific Routing" (2026-09-07) — the closest thing to our study that already
  exists.** mini-SWE-agent, **12 SWE-bench Verified tasks**, fixed `claude-opus-5` vs a router.
  **9/9 resolved in both arms. $2.82 → $1.51, a 46% saving.** The router is a **static heuristic, not
  a classifier**: classify tool calls into Explore/Implement/Verify, switch phase after two
  consecutive matching calls, **"well under a millisecond per request with no extra LLM call."**
  Their caveats: 12 tasks is small, mini-SWE-agent is a simpler loop than production agents, the
  phase taxonomy is a first cut. **Wall-clock not measured.**
  → **This is our control arm, not our treatment.**
- **`github.com/Bijaykars/claude-code-autoroute`** (running since 2026-09-14): pure heuristics,
  escalation one rung at a time on an `ESCALATE` block. One working day, 22 delegated tasks:
  **delegated work cost 28% of what the same tokens would have cost on the top model** (17% Haiku /
  65% Sonnet / 10% Opus / 8% Fable by token). Author: *"One day, one project, one operator. It is the
  order of magnitude, not a benchmark."*
- **★ `github.com/AqueGen/model-routing`** — static pinned subagents (scout→sonnet/low,
  test-runner→haiku/low, implementer→sonnet/med, reviewer→opus/high), no classifier. 7-day telemetry:
  "98% of dispatches (82 of 84) and 283.1M of 285.2M tokens ran below the session tier."
  **The three-way cost comparison is the important bit:**
  `$1.36 doing it inline` < `$1.68 routed` < `$2.01 for the same subagent work at session tier`.
  **Delegating-and-routing is ~24% *more expensive* than not delegating at all.** Cause: subagents
  start with empty context, so you trade cheap cache-reads in the main session for expensive
  cache-writes in the subagent.
- **Kapoor et al.'s escalation/retry/warming baselines** Pareto-dominate Reflexion/LDB/LATS. Their
  own footnote: *"we are not aware of any papers that compare their proposed agent architectures with
  any of the last three of our simple baselines."*

**★ [DECISION] Verdict: a two-arm study (`jev_routed` vs `default`) cannot answer our question.** It
can only tell us whether *any* tiering helps — already known to be yes. Without a static-heuristic
arm we reproduce exactly the methodological gap five papers criticise.

---

## 5. Cost / latency measurement of agentic harnesses

### Our 27.6% finding: real, correct, already documented

**The `input_tokens:2` trap is publicly filed by a third party.** `anthropics/claude-code#95555`,
opened **2026-09-19** by GitHub user **`yocyber-code`** — *not* us (verified via `gh`). Near-identical
record:
```
input_tokens: 2, cache_creation_input_tokens: 977, cache_read_input_tokens: 316685
```
Bug: some assistant rows **zero every top-level usage counter while `usage.cache_creation` retains
real values**, breaking Anthropic's documented invariant. Prevalence on one machine 2026-07-10→09-19:
540,177 rows, 153 messages affected (0.03%), **17 messages with no consistent row at all**; largest
affected row 417,471 tokens reported as 0. Status **open**, labelled `area:cost`, `has repro`.

**Documented mechanisms — do not conflate their magnitudes:**
1. **`usage.iterations[]` omission** — jverhoeks/claudecounter PR #26. A multi-round-trip turn logs
   `in=4/out=691` at top level against iterations of `(2,357)`, `(88762,1249)`, `(2,334)` — **88,762
   input tokens invisible in one record.** August 2026 aggregate: 170,529 counted vs 83.7M actual.
   **★ Asymmetry trap: cache fields must NOT be summed from iterations (top-level already equals the
   sum); token fields must be.** *Our plan says "ignore `iterations[]`" — that is half right and half
   wrong. Revisit.*
2. **1-hour cache writes billed at 2×, not 1.25×.** `ccusage#899` (closed, fixed in PR #1221): across
   ~40,000 records, **$479 / 19% under-reported** (Opus 18%, Haiku 21%, Sonnet 38%). ⚠️ If we
   measured 27.6% on a post-fix ccusage this is **not** our mechanism.
3. **Server-side tokens never recorded.** jverhoeks' reconciliation after both fixes: August
   $8,462.79 → $9,509.92 (+12%); author concludes the **"practical ceiling for any tool reading
   `~/.claude` is ~72% of the real bill for this usage pattern."**
4. **~8.7% aggregate residual** even in careful academic work (PointFive), attributed to hidden
   thinking tokens.
5. **Data-residency 1.1× multiplier** omitted from session cost before Claude Code v2.1.239.

**Naive tooling can also OVER-report by ~437%** (`claude-spend#31`): duplicate `requestId`/
`message.id` rows (22,759 → 12,067 on dedupe) plus **model-pricing substring fallthrough** —
`getPricing()` matches "opus" in `claude-opus-5`, fails the version check, falls back to Opus 4.0
pricing ($15/$75 vs $5/$25), a 3× error on 96% of usage.
**★ A router study introduces new model IDs into the transcript by definition — precisely the
condition that triggers this. Dedupe by `requestId`+`message.id`; hard-fail on unknown model IDs.**
(Our `cost_usd()` already returns `None` on unknown models rather than guessing. Good. But verify the
analysis surfaces that as a hard failure, not just a coverage stat.)

**Anthropic primary sources:** `code.claude.com/docs/en/costs` states **"Claude Code computes the
dollar figure locally from token counts at list price"** — an estimate, not a billing record (this
corrects ccusage's docs, which call `costUSD` "Claude's official billing calculation"). And the
prompt-cache stats line **"covers the main conversation only, not subagents"** — first-party
instrumentation goes silent exactly where our measurement lives.

**★ Two auth-path traps:** on Pro/Max/Team there is **no billed dollar cost at all** — every figure
is imputed list price. And **cache TTL is 1 hour on a subscription but 5 minutes on usage credits /
API key**, which changes *which write multiplier applies* (2× vs 1.25×). Two runs of the identical
experiment on different auth paths will not produce the same cost. **[AMENDMENT] Declare our auth
path.**

### The methodology to adopt

**★ PointFive, "Token Reduction Is Not Cost Reduction" (arXiv:2607.12161, July 2026).** ⚠️ PointFive
sells cost-optimisation tooling — but the methodology is the best available and the headline cuts
against their own interest. 103 tasks × 7 repos, 4 arms, 712 runs/arm, 2,908 paired runs,
block-randomised from identical fresh working copies.
- Takes the harness's `total_cost_usd` **and independently reconstructs it** from four components
  (uncached 1.0 / cache-write 1.25 / cache-read 0.1 / output), reporting the residual: median
  +0.0–0.9% per run, **8.7% in aggregate**.
- Task-level bootstrap, 10,000 resamples. *"Repeated runs of the same task are never treated as
  independent."*
- **★ ICC 0.37–0.55 for cost repetitions → effective sample ~38–45 tasks despite 712 runs/arm. Spend
  budget on more distinct subtasks, not more reps.**
- **★ Prompt-cache carryover between arms as a threat to validity:** *"per-run `$HOME` isolation does
  not isolate the provider's cache, and the median gap between consecutive runs in a block is
  10.8s"* — 100% of consecutive pairs fell inside the 5-minute TTL. Three mitigations applied, still
  carried as a limitation. A cache hit is **12.5× cheaper** than a miss for the same prefix, so
  whichever arm runs second gets an unearned discount.
- Headline: aggressive compression "reduced delivered tool-output tokens by 38.4% but **increased
  billed cost by 6.8%**"; token↔cost correlation r = 0.154 [−0.051, +0.356]. **Cache traffic is ~80%
  of the bill; tool outputs only 3.3%. Do not use token counts as a cost proxy.**
- Does **not** measure wall-clock.

**Kapoor et al., "AI Agents That Matter" (arXiv:2407.01502):** fixed vs variable cost split
(classifier labelling = fixed; per-subtask inference = variable — most routing claims omit the fixed
cost); dollar cost not proxies; publish raw token counts; **convex** Pareto frontier (you can always
randomise between two agents); K=5 runs with 95% CIs; §6 — "agent evaluations are rarely accompanied
by error bars."

**HAL (arXiv:2510.11977, ICLR 2026):** 21,730 rollouts, ~$40,000. **Pin the price table with a date.**
Include the origin (0,0) on the frontier "since one can always choose not to deploy an agent." Agents
can be **"100× more expensive while only 1% better."** *"Log analysis must become a necessary
component"* — agents with identical scores exhibit vastly different behaviours; a cost/latency-only
study may miss that the cheap tier reached the same score by shortcutting.

**Miller (Anthropic), arXiv:2411.00640:** paired tests, **clustered standard errors** (our subtasks
from the same parent task/repo are a cluster), power analysis before running.

**Artificial Analysis coding-agents leaderboard** — the one public source reporting **both** cost per
task and **wall time per task**, pass@1 over 3 attempts. Order-of-magnitude anchor.

**Where nothing exists:** no published reconciliation of transcript-derived cost against the Claude
Console usage page or an invoice; no rigorous characterisation of agent wall-clock variance with a
derived repetition count (K=3–5 is convention, unjustified); no independent academic cost measurement
of Claude Code before 2026.

⚠️ Unverified leads: The New Stack, "Aider, Claude Code, and OpenClaw ran an identical model. Token
use varied 70-fold"; arXiv:2607.13080 "Inference Economics of Enterprise Coding Agents";
arXiv:2607.01418 (Microsoft's Claude Code rollout).

---

## 6. Calibration of gating classifiers

**★ Decision curve analysis applied to LLM routing / gating / cascades / abstention: NOTHING.
Searched across several vocabularies. A genuine, claimable gap — the strongest novelty angle in this
report.**

The mapping is clean:
- **"treat none" ↔ everything on the cheap tier**
- **"treat all" ↔ everything on Opus (our control)**
- **threshold probability p_t ↔ (Opus cost − cheap cost) / (cost of a cheap-tier failure)**

Net benefit at the operating threshold answers "does the classifier beat *both* trivial policies" —
which accuracy and AUC cannot. **Caveat to state explicitly:** clinical net benefit assumes the harm
of a false positive is a fixed multiple of a true positive's benefit; for routing, the harm of
under-routing is a failed subtask whose cost is itself stochastic (retries, human intervention).

Origin: Vickers & Elkin, *Medical Decision Making* 26(6), 2006. CIs/hypothesis tests for net benefit:
`doi.org/10.1186/s41512-023-00148-y` (2023). Closest ML-side: arXiv:2604.04241 optimises area under
the net-benefit curve, but clinically. scikit-learn has an **open, unimplemented** issue for
net-benefit curves (#22136).

**Calibration in routing — exists but thin.** UCCI (arXiv:2605.18796, ⚠️ single-author unreviewed
v1): per-token margin → **isotonic regression** → threshold by constrained cost minimisation. ECE
0.12 → 0.03 on 75,000 production NER queries; 31% cost reduction [27%, 35%] at F1=0.91; beat entropy
thresholding (2.31), conformal (2.18) and FrugalGPT-style (2.24) at cost 2.08. **Theorem 1: threshold
policies on calibrated error probabilities are cost-optimal — under assumptions including access to
the true calibrated error probability.** Its own limitation: "static calibration… online or continual
recalibration would be needed" under shift, **not evaluated empirically**. Also: Theorem 1 assumes
large-model accuracy is invariant to which queries escalate — which fails when queries hard for the
small model are also hard for the large one.

**RouteLLM gives us the reporting metrics:** **CPT(x%)** = minimum % of strong-model calls needed to
reach a target performance-gap-recovered, and **APGR** = average PGR across cost constraints. The
threshold α is an operator knob, swept, not fitted.

### Four documented ways thresholds degrade

1. **★ Threshold non-transfer — the best single citation available.** Shafran, Schuster, Ristenpart,
   Shmatikov (Cornell Tech), "Rerouting LLM Routers" (arXiv:2501.01818), §5: *"We observed that the
   Chatbot Arena-based threshold did not transfer well to MMLU and GSM8K, resulting in the majority
   of queries (≈98%) routed to the strong model."* An independent party calibrated a published
   router, changed distribution, and the cost saving collapsed to ~zero — **while the router still
   appeared to work.** Corroborated by ickma2311's Jev finding (100% escalation at accuracy parity).
   **[AMENDMENT] Report the realised strong-model call rate per task family, not just in aggregate.**
2. **★ Calibration collapses under shift, and post-hoc fixes make it worse.** Ovadia et al., NeurIPS
   2019: *"while temperature scaling improved calibration on standard test data, it often made things
   worse on shifted data"*; deep ensembles most shift-robust.
   **★ Paired with UCCI's Theorem 1 this is the core argument: the cost-optimality guarantee holds
   only in-distribution, because the assumption it needs is exactly the one that fails under shift.
   The research agent saw nobody make this pairing in print.**
3. **Deferral changes the distribution the threshold was fitted on** (ReDAct, arXiv:2604.07036):
   realised deferral rate diverges from planned. In an agent loop this compounds.
4. **Cheap- and expensive-tier errors are correlated** ("Cost-Saving LLM Cascades with Early
   Abstention," arXiv:2502.09054: "error patterns of small and large models are correlated"; 2.2%
   average loss reduction, 13.0% cost reduction, 5.0% error reduction).
   **★ If Opus fails the same subtasks Haiku fails, our classifier is measuring task difficulty, not
   tier fit. Measure this correlation explicitly or we may attribute to routing what is really
   difficulty.**

Also: "Decision-Making under Miscalibration" (arXiv:2203.09852) bounds utility loss from acting on a
miscalibrated probability at a fixed threshold. Classical lineage: Madras/Pitassi/Zemel 2018,
Mozannar & Sontag 2020, Geifman & El-Yaniv (SelectiveNet). Production practice reports weekly-to-
monthly recalibration cadences.

---

## What should change about the study — ranked

**1. [DECISION] Add a static-heuristic arm. Without it the study cannot answer its own question.**
Five independent benchmark papers find learned routers fail to beat trivial baselines; three separate
projects have *already* measured 46%, 28% and ~17% savings from static rules in this exact setting.
Pre-register the two-line rule *before* running — liteLLM's Explore/Implement/Verify taxonomy or
AqueGen's task-type→tier map are ready-made. Also consider: **random routing at a matched cheap-model
call rate** (makes the Pareto frontier convex-comparable), **escalate-on-failure with no classifier**
(Kapoor's baseline), **all-cheap**, and a post-hoc **per-subtask oracle**. Costs four extra arms;
without them a reviewer stops reading at the design section.

**2. [AMENDMENT] Measure Jev latency inside the hook process or the wall-clock endpoint is wrong by
~2×.** bouncer PR #33: ~95ms socket + ~193ms TLS + ~245ms request = **437ms median, 549ms p95** in a
fresh process. Routing once per *delegation* makes this tolerable — but say so, and measure it.

**3. [AMENDMENT] Check whether the control delegates, because delegation itself costs money.**
AqueGen: `$1.36 inline` < `$1.68 routed` < `$2.01 delegated-at-session-tier`. **If our `default` arm
runs inline while `jev_routed` delegates, we measure the delegation penalty, not routing.** Both arms
must delegate identically; only the tier may differ. Plus TwinRouterBench: **cache writes on tier
switch are charged at the incoming tier's rate** — budget for it and report switches-per-trajectory.
*(Our design randomises assignment over the same delegated task, so this may already hold — verify
explicitly rather than assume.)*

**4. [AMENDMENT] Pre-register escalation semantics and fail behaviour.** SWE-Router restarts the
strong model from the original query rather than continuing the cheap model's trajectory, *"because
conditioning m2 on m1's reasoning has been seen to bias m2 toward m1's mistakes."* Restart = throw
away cheap work; continue = inherit errors. Separately: Claude Code hook timeout is **fail-open**,
auto mode is **fail-closed**, togishima's dispatcher **fails to frontier**.

**5. [AMENDMENT] Choose the threshold on held-out data and report the whole curve, never a point.**
Jev needs 100% escalation at accuracy parity (ickma2311); a transferred threshold sent ≈98% of queries
to the strong model (Rerouting LLM Routers §5). Report CPT/APGR or a cost–quality Pareto curve, and
the **realised strong-model call rate per task family**.

**6. [AMENDMENT] Fix the sample-size plan: more distinct subtasks, fewer reps.** PointFive's ICC
0.37–0.55 means 712 runs/arm bought ~38–45 effective tasks. Up to **30× run-to-run token variance on
the same task**. Target many distinct subtasks, ~3–5 reps each, **paired across arms**, task-level
bootstrap CIs, clustered SEs, power analysis before running.

**7. Guard the cost pipeline against three known bugs, then reconcile against the Console.**
(a) Sum `usage.iterations[]` for token fields but **not** for cache fields; (b) **dedupe by
`requestId`+`message.id`** and **hard-fail on unknown model IDs**; (c) apply **2×** for 1-hour cache
writes, 1.25× for 5-minute, noting TTL depends on auth path. Then do **what nobody has published:
reconcile transcript-derived cost against the Console usage page or an invoice, and report the
residual.** That inoculates our headline number and is a contribution in itself.

**8. Reframe the Jev novelty claim — the current version is false.** Write: *eleven independent
evaluations exist within five days of launch; results are mixed (beats a nano-class LLM, loses to
Haiku 4.5 on phishing by 18.7pp, loses to a supervised BGE encoder by 10pp on Banking77, loses to a
regex on its best single phishing signal); calibration is task-dependent and contradicts the vendor's
claim on at least one task; none has been independently reproduced; and none measures tier routing
end-to-end.* **Our real gap is tier routing with measured outcomes — five public Jev tier-routers
exist (`andrei10k/claude-jev-model-router`, `leftspace89/jevsubrouter`, `flaviusapop/jev-router`,
`0x7067/claude-jev` PR#4, `togishima/subagent-dispatcher` PR#1) and none reports a single measured
cost, wall-clock, or quality number.**

**9. [DECISION] Consider running togishima's platform rather than building a sixth harness.**
`togishima/subagent-dispatcher` PR #1 merged **today (2026-09-20)** with exactly our three arms —
**fixed-high (A) / jev-direct (B) / policy-graph (C)** — versioned routing policy as data,
deterministic verification rather than worker self-reports, 95% cache-read ratio measured, honest
limitations documented (*"each worker pays a fresh ~15–25k cache-creation charge; delegation adds
latency; a Jev outage routes everything to the frontier worker"*). Ships with **no aggregate
results** — two anecdotal cost points only. "First to publish results on an existing pre-built
three-arm platform" is a stronger position than "sixth implementation with a two-arm design."

**10. Add decision-curve / net-benefit analysis — our clearest unclaimed contribution.** Nothing in
the literature applies net benefit to LLM routing, and the mapping onto our design is exact. Report
alongside ECE, Brier, and a reliability diagram using **equal-mass quantile bins** (routing
probabilities pile up near the ends).

**11. Two cheap measurements that pre-empt obvious objections.** (a) **Correlate cheap-tier and Opus
failures per subtask** — if they fail the same things, the classifier is measuring difficulty, not
tier fit. (b) **Report a per-step "was this step under-routed" diagnostic** alongside
trajectory-level success — one under-routed step fails an 8–13-call trajectory, and Opus-as-router
flagged only 7 of 147 high-risk steps.

**12. Note in related work, don't spend budget on:** Anthropic's auto mode (2026-03-25) is first-party
prior art with a cheaper two-stage design and published FPR 8.5%→0.4% / a frank 17% FNR — **explain
why an external classifier beats that architecture.** Also flag that HAL found the most expensive
model on the Pareto frontier in **only 1 of 9 benchmarks**, so our all-Opus control is probably
off-frontier and flattering. Say so before a reviewer does.

---

## Flagged as unverified

- **Every.to's Jev test** — primary article not located; all numbers via aggregators.
- **TypeSafe's self-disclosed 67.8% vs 74.1%** — via explainx.ai citing the dashboard; not re-confirmed.
- **arXiv:2505.12601 date** — ID implies May 2025, one fetcher reported 2026; likely a v2 date.
- **Aider architect mode "30–50% cheaper"** — secondary sources only.
- **The New Stack "70-fold token variation"** and **Arena.ai "harness tax"** — headlines only.
- **Per-system router-overhead percentages** (ParetoBandit 9.0ms, DiSRouter <5%, PA-MoE 1.3ms,
  GreenServ 6.68–7.77ms) — from search summaries, not primary PDFs.
- **AqueGen's two token columns** (1.77B vs 285.2M) appear to be a cohort figure; the dollar figures
  $1.36/$1.68/$2.01 are quoted verbatim from the README.
- **typesafe.ai vendor blog shows "Sep 20, 2026"** — almost certainly an updated-on date.

## Where nothing was found

- No independent reproduction of *any* Jev benchmark.
- No verified production deployment of Jev with metrics.
- No measured cost/wall-clock/quality results from **any** of the five Jev tier-routing
  implementations for Claude Code.
- No live head-to-head of a learned router against a tool-type static heuristic **inside** an agent
  loop.
- **No paper reporting wall-clock as a co-primary outcome for agentic routing.**
- **No decision curve analysis / net benefit applied to LLM routing, gating, cascades or abstention.**
- No paper isolating **model-tier heterogeneity** as a multi-agent failure cause.
- No published reconciliation of transcript-derived Claude Code cost against the Console or an invoice.
- No rigorous characterisation of agent wall-clock variance with a derived repetition recommendation.
