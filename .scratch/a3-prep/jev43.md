# A3 prep, from the JEV-43 agent (wall-clock decomposition and contamination)

Written for wave A3 — **JEV-27** (power analysis), **JEV-46**, **JEV-47**,
**JEV-48**. Everything below is offline, from `data/runs/2026-09-20.jsonl`,
measured 2026-09-20. The full report is `reports/jev43-wallclock.md`; the
machine-readable form is `reports/jev43-wallclock.json`; the code is
`src/latency.py` (pure functions) and `src/latency_report.py` (the writer).

---

## 0. The one-paragraph version

`cc_*` `total_ms` splits exactly into `spawn_ms + in_session_ms + api_ms`.
`api_ms` is clean. `in_session_ms` is bimodal, and the second mode is the
operator's `security-guidance` plugin `Stop` hook burning a TLS retry ladder —
**identified, not bounded**, 67 of 1,322 rows, 18.5-22.0s each, 1,266s total.
It is removed by dropping those rows. What remains is bounded, not clean:
≤~0.6s/row of fast operator `SessionStart` hooks hiding inside the clean
in-session mode, plus ~1.1-1.3s/row of `spawn_ms` of which an unknown
fraction is Claude Code loading the operator's config.

**One published number does not survive: JEV-33's concurrent
`dispatch_wall_ms` of 16.5s becomes 9.7s, and the realised concurrency gain
restates from ~1.2x to ~2.0x.** Details in `reports/jev43-wallclock.md`.

---

## 1. For JEV-27 — the wall-clock variance structure, not a point estimate

A power analysis needs the spread and the shape. Here is the **clean** `total_ms`
distribution (contaminated rows dropped), **live rows only**, never pooled
across `arm_config_id` or `arm_dispatch`. `mean(log)`/`sd(log)` are of
`ln(ms)` and are there because every one of these is right-skewed; a lognormal
is a far better working model than a normal, and `sd(log)` is the effect-size
denominator you actually want.

| arm | config | dispatch | n clean | p05 | p25 | p50 | p75 | p90 | p95 | p99 | mean | sd | CV | mean(log) | sd(log) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cc_haiku45 | cc-haiku45-cli-v1 | concurrent | 72 | 5785 | 8139 | 10965 | 15886 | 18606 | 19936 | 21729 | 11985 | 4625 | 0.39 | 9.314 | 0.398 |
| cc_haiku45 | cc-haiku45-cli-v1 | serial | 240 | 6105 | 8824 | 11228 | 15158 | 19399 | 22075 | 26768 | 12403 | 4958 | 0.40 | 9.351 | 0.387 |
| cc_haiku45 | cc-haiku45-cli-v2-nothink | concurrent | 112 | 3204 | 5012 | 6013 | 7581 | 8569 | 9542 | 15563 | 6270 | 2407 | 0.38 | 8.677 | 0.366 |
| cc_opus5 | cc-opus5-cli-v1 | concurrent | 186 | 3409 | 4672 | 5004 | 5376 | 5785 | 6253 | 7383 | 4979 | 844 | 0.17 | 8.499 | 0.171 |
| cc_opus5 | cc-opus5-cli-v1 | serial | 250 | 3561 | 4585 | 4921 | 5191 | 5782 | 6638 | 10397 | 5090 | 1968 | 0.39 | 8.503 | 0.221 |
| cc_sonnet5 | cc-sonnet5-cli-v1 | concurrent | 199 | 2922 | 3045 | 3122 | 3377 | 3668 | 3723 | 4122 | 3237 | 281 | 0.09 | 8.079 | 0.083 |
| cc_sonnet5 | cc-sonnet5-cli-v1 | serial | 78 | 2708 | 2796 | 2870 | 3018 | 3357 | 3520 | 3889 | 2967 | 292 | 0.10 | 7.991 | 0.090 |
| jev | jev-gateway-v1 | concurrent | 233 | 484 | 519 | 567 | 627 | 712 | 785 | 1200 | 615 | 369 | 0.60 | 6.378 | 0.227 |
| jev | jev-gateway-v1 | serial | 254 | 473 | 530 | 565 | 632 | 765 | 989 | 2139 | 653 | 485 | 0.74 | 6.410 | 0.293 |

**What JEV-27 should take from this.**

- **The arms have wildly unequal variance.** `sd(log)` runs from 0.083
  (`cc_sonnet5` concurrent) to 0.40 (`cc_haiku45`). Any power calculation that
  assumes a common variance across arms will be badly wrong for whichever arm
  it did not calibrate on. Use the per-arm `sd(log)`.
- **Use log scale.** CV is 0.09-0.74 and every arm is right-skewed; on the raw
  scale the p99/p50 ratio reaches 2.4x for `cc_haiku45`. A t-test on raw ms
  will be dominated by the tail.
- **`cc_haiku45` is the sample-size binding constraint**, at `sd(log)`≈0.39
  against `cc_opus5`'s 0.17-0.22 concurrent. If A3's design powers on a pooled
  variance it will under-power Haiku by roughly a factor of 4 in n.
- **`jev` has the highest raw CV (0.60-0.74) and a low `sd(log)` (0.23-0.29).**
  That is one heavy tail on a very tight body — a few slow HTTP requests, not a
  wide distribution. Do not read the raw CV as "jev is noisy".
- **Concurrency tightens the `cc_*` distributions rather than widening them**
  (`cc_opus5` `sd(log)` 0.221 serial -> 0.171 concurrent). The serial era's
  extra spread is the p99 tail, not contention.
- **Do not pool the two `cc_haiku45` configs.** `v2-nothink` has p50 6.0s
  against v1's 11.0s. They are different arms for every purpose except the name.

## 2. The contamination rate is a fact about the operator, not the arms

The `Stop` hook returns early on an empty git diff. It only costs 18.3s when
the arm's `cwd` — this repo — was dirty at that instant. Consequences A3 must
not get wrong:

- **The rate is not a constant and must not be extrapolated.** Measured by
  hour over the window: 0%, 1.3%, 1.9%, 3.3%, 4.5%, 5.4%, 11.0%, **34.6%**.
  The corpus-wide 5.07% is an average over how busy the operator happened to be.
- **It is independent of the decision and of the arm**, which is what makes
  dropping the rows unbiased. It is *not* independent of wall-clock time, so a
  time-sliced or before/after comparison must recompute the rate inside each
  slice rather than inherit the corpus figure. JEV-33's 16.5s is exactly this
  failure: its 17-decision sample sat in the busiest burst and carried a 41%
  rate.
- **It will recur if collection resumes**, at whatever rate the operator's
  editing produces. It is not a one-off. See §4 for the options.

## 3. Which clock to use for which question

| question | clock | why |
|---|---|---|
| "how fast is this classifier" | `api_ms` | the only clean clock; directly comparable with `jev`'s `total_ms`, both one HTTP round trip |
| A3.5's co-primary wall-clock | `total_ms`, clean rows only, `n` dropped stated | includes spawn, which A5.3 commits to reporting |
| per-decision wall | `latency.dispatch_walls(rows, baselines, adjusted=True)` | a max over arms; dropping a row would drop the decision, so adjust rather than drop |
| spawn contention (A5.3) | `spawn_ms` serial vs concurrent | ~1.08s -> ~1.26s, **~180ms**, and it is untouched by the hook because it is computed on `total_ms - duration_ms` |

Never publish a pooled `cc_*` `total_ms`: it mixes three eras and one machine
artefact.

## 4. Things I did not do, that A3 may want to

- **I did not touch `src/arms/claude_cli.py`.** It is not mine this wave, and
  suppressing the operator's hooks with a `--settings` override would buy a
  cleaner number by measuring a Claude Code nobody deploys. If A3 decides the
  trade-off goes the other way, the change is: add
  `"--settings", '{"hooks":{}}'` alongside the existing
  `--strict-mcp-config`, and note that it creates a **fourth** `arm_config_id`
  era boundary in the window. Verify against the installed CLI's flag surface
  before relying on it; I did not, because verifying would have meant spending.
- **I did not propose disabling the operator's plugin.** `~/.claude/` is
  read-only to this study and it is the operator's machine.
- **I did not re-measure anything live.** Phase A is offline, collection is
  stopped, and zero API was spent on this ticket.
- **The hook's own log only reaches back to 14:44Z.** The 42 contaminated rows
  before that are attributed by signature identity, not by timing correlation.
  If someone wants a stronger claim for the early window, it cannot be had from
  what is on disk.
- **Queue time in `spool/ready/` is still unrecoverable** (per the A2 prep).
  None of the three clocks includes it, so "decision to answer" end-to-end
  does not exist for this corpus and A3 should not promise it.

---

## 5. Three questions the JEV-32 agent raised, answered against the rows

**(a) Must the two arm-set eras be conditioned on separately for latency?**
For the *spawn* and *in-session* clocks, **no — `arm_dispatch` already subsumes
it**, and this is measured rather than argued. Within the serial era the
three-arm and four-arm cohorts give spawn p50 **1089ms vs 1083ms** and
in-session p50 **292ms vs 284ms** (n=336, n=232). That is the expected result:
serial dispatch runs one subprocess at a time, so how many arms exist does not
change what any one of them contends with. `concurrent_arms` is **4 on every
concurrent row and absent on every serial row**, i.e. exactly collinear with
`arm_dispatch`, and adds no information as a separate key.

The caution still stands for anything pooled over **calendar time** rather than
over dispatch regime, because the contamination rate moves with the hour (§2)
and `cc_haiku45` changed config at 15:15:49Z. So: condition on `arm_dispatch`
for contention, on `arm_config_id` for the arm, and re-check the contamination
rate inside any time slice.

**(b) `analyze.py`'s `_operational_table` / `_attribution_table` aggregating
`$/1k` and `p50ms` across eras.** From this ticket's side the latency half of
that is a **real defect and worse than the era problem alone**: a `p50ms`
aggregated over all `cc_*` rows is contaminated as well as era-pooled. But note
which way it bites — a median is robust to a 5% mode (§ the serial sum
survived), so the era pooling is likely the larger error of the two, not the
contamination. `analyze.py` is frozen and I did not touch it. **It needs its
own ticket**, and that ticket should fix both together: split on
`(arm_config_id, arm_dispatch)` and drop contaminated rows via
`latency.is_contaminated`, which is importable and has no dependencies.

**(c) `config_fingerprint` is on zero historical rows.** Confirmed as
irrelevant to this ticket: the decomposition keys on `arm_config_id`, which is
present on every row and is set by the arm rather than recomputed at analysis
time. Nothing here needs `config_fingerprint`.

## 6. A constraint on any interval JEV-27 computes from these numbers

The live corpus is **1,783 rows across exactly one `session_id`**, and
`PREREGISTRATION.md` A1.1 makes fewer than 30 clusters inconclusive by rule.
**This report therefore quotes no confidence intervals and no p-values** — only
quantiles, counts and distribution shape, which are descriptions of the corpus
rather than inferences about a population. §1's `sd(log)` is offered as an
*input* to a power calculation, not as evidence that any difference is
significant. If JEV-27 computes a clustered interval on wall-clock it inherits
the same disqualification, and should say so rather than quoting the interval.
