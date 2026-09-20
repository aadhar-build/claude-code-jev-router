# Jev API findings

Ticket JEV-02. Updated as the spike progresses. Anything not confirmed here is
still an assumption, and code that depends on it says so.

## Confirmed 2026-09-20

**The gateway serves Jev, and its own metadata matches our pricing table.**
`GET https://ai-gateway.vercel.sh/v1/models` returns 376 models including:

```json
{
  "id": "typesafe-ai/jev",
  "owned_by": "typesafe-ai",
  "name": "Jev",
  "type": "evaluation",
  "pricing": {"input": "0.000000042", "output": "0"},
  "context_window": 32000,
  "max_tokens": 0,
  "modalities": {"input": ["text"], "output": ["text"]}
}
```

Three things worth pinning down from that:

- **$0.042/1M input, output genuinely free.** `pricing.input` is `4.2e-8` per
  token, exactly what `config/pricing.json` carries, and `pricing.output` is a
  hard zero. The headline cost ratio does not rest on a marketing page.
- **`context_window` is 32,000, not 64,000.** Secondary sources describe a 64K
  window with a 32K state limit. The gateway itself reports 32,000, and the
  gateway is what we call, so `state_builders.MAX_STATE_CHARS` is sized against
  32K. Our cap of 60,000 characters is roughly 16K tokens — comfortably inside
  it, and the truncation sweep will show whether that is even necessary.
- **`max_tokens: 0` and `type: "evaluation"`.** Jev is not a generative model in
  the gateway's own taxonomy. It cannot emit text, which is the structural
  reason it cannot replace Claude as the coding model and can only ever own the
  decision layer.

**Authentication works; inference is billing-gated.** The key authenticates
cleanly — `GET /v1/models` returns 200 — but `POST /v1/evaluate` returns:

```
HTTP 403 {"error": {"type": "customer_verification_required",
  "message": "AI Gateway requires a valid credit card on file to service requests."}}
```

This is a billing gate on the key's Vercel **team scope**, not a bad credential;
a wrong key returns 401. Adding a card to a different team or personal scope
than the one the key belongs to will not clear it. Still returning 403 after a
card was added, so the card and the key are most likely on different scopes.

The arm classifies this as `error_kind: "account_gated"`, distinct from `"auth"`,
and records it as a normal attrition row — which is the behaviour we wanted, and
the first real confirmation that the fail-loud path works end to end.

## Spike complete — 2026-09-20

The billing gate cleared and `uv run src/arms/jev.py --selftest` ran in full.
Five results, three of which were bugs in our client that would have corrupted
the study silently.

### 1. Confidence DOES survive the REST path — and we were parsing it wrong

We had assumed we might have to disclaim this, since it is documented only for
the AI SDK. It is present, in two places at once:

```json
"answers": {"route": {"type": "choice", "choice": "write",
                      "probabilities": {...}, "confidence": 0.92}},
"providerMetadata": {"typesafe": {"confidence": {"route": 0.92, "risk": 0.67}}}
```

Present for `choice` and `score`, absent for `boolean`, exactly as the SDK docs
describe. Our parser looked for a per-answer `providerMetadata` key that does not
exist, so it was silently discarding the confidence signal on every call. **Fixed.**

### 2. `score` is a float, not a bucket index

A real response carries `"score": 3.37`. Jev returns the **expected value across
the anchor distribution**, which is strictly more information than a discrete
bucket. Our parser cast it to `int`, which both threw that away and biased every
score downward by up to a whole point. **Fixed** — the float is preserved.

### 3. `score` is 0-indexed at source, and our Claude arms are 1-indexed

Five anchors come back with probability keys `"0".."4"` and the score on a 0–4
scale. The Claude arms are schema'd 1–5. Left alone, **an identical judgement
from the two arms would have differed by exactly one point on every single
item** — a uniform offset that Spearman correlation would hide completely, and
that only the Bland–Altman plot would ever have caught. Jev is now shifted onto
the 1–n scale at the parsing boundary, so everything downstream is on one scale.
Rows carry `score_index_origin: "jev_0_shifted_to_1"` so the conversion is
auditable rather than invisible. **Fixed.**

This one is worth dwelling on: all three arms would have "worked", produced
plausible numbers, and been wrong. It is the strongest argument for running the
spike before building on the contract rather than after.

### 4. Jev is not bit-deterministic, and on borderline items it flips decisions

Ten identical calls on byte-identical state. The crude test — counting distinct
answer signatures — reports 10/10 distinct, but that registers any difference in
any digit and says nothing about whether a *decision* would change. What matters
for a gate is the spread and the threshold crossings:

| state | spread | sd | decision flips at τ=0.5 |
|---|---|---|---|
| `git reset --hard HEAD~10` (p≈0.56) | 0.04 | 0.015 | 0/10 |
| `git reset --hard HEAD~10` (p≈0.97 question) | 0.00 | 0.000 | 0/10 |
| `git push --force origin main` (p≈0.50) | 0.06 | 0.018 | **1/10** |

So: when Jev is confident it is perfectly stable, and the wobble is confined to
genuinely uncertain items — but on a command sitting near the threshold, **the
same command produced a different decision on 1 call in 10.** For a shadow-mode
study that is a measurable property. For enforce mode it is a deployment
hazard: a borderline command would be gated inconsistently, which is worse than
being gated always or never, because it is unreproducible for the user.

**Second run, after the parser fixes.** All three fixes verified live:
confidence captured (`{route: 0.90, risk: 0.62}`), score a float on the 1–5
scale, probability keys shifted. Determinism on the same borderline command came
back **0/10 flips** this time, against 1/10 on the first run.

That difference is itself the point. Two runs, one flip in twenty — the flip
rate is a property of how close an item sits to the threshold, not a fixed
constant, and a ten-call sample cannot pin it down. **Do not quote "1 in 10"**;
quote "observed at least once in twenty calls on a p≈0.50 item, rate not yet
characterised." The determinism sweep exists to characterise it properly, and
it now has a clear job.

This also kills a hypothesis the design had been carrying — that Jev might be
deterministic where temperature-zero LLMs are not, and that this would earn its
own section. It does not. The determinism sweep now measures how much both
wobble, which is a fairer question anyway.

Input token counts *are* stable across identical calls (412 every time), so
billing is reproducible even though answers are not.

One data-hygiene note: the 0→1 shift is applied with `round(x + 1.0, 2)` to the
precision the API itself reports. Without the rounding, `3.44 + 1.0` stores as
`4.4399999999999995` — binary float noise that is not a measurement and would
make two identical replays compare unequal.

### 5. Token cost is dominated by fixed overhead, not by state

| state size | input tokens | fixed share |
|---|---|---|
| 12 chars | 281 | — |
| 120 chars (a short bash command) | 307 | **91%** |
| 330 chars (command + cwd, typical) | 357 | 78% |
| 2,520 chars | 877 | 32% |

Solving the two endpoints: **~278 tokens of fixed overhead per call**, plus
0.238 tokens per character of state (≈4.2 chars/token, unremarkable).

For the `pre_bash` gate — the whole point of this study — roughly **90% of every
call's tokens are scaffolding, not the command being judged.** That does not
threaten the cost story, since 307 tokens at $0.042/1M is $0.000013 a call. But
it does mean "tokens per KB of state" is a misleading unit for short states, and
the report should quote cost per decision instead.

**Caching does not apply.** `usage` contains only `inputTokens` and
`outputTokens` — no cache fields at all — so there is no cached-vs-uncached
comparison to report, and the "report uncached as primary" plan is moot.

### 6. Latency

535ms on a cold connection for a three-question call; 479–664ms across ten
repeats of a two-boolean call, median 511ms. Decomposed: DNS 5ms, TCP 8ms,
TLS 58ms — so **~71ms of setup and ~440ms genuinely server-side.**

Against the claimed 70–500ms, the low end is not reachable from here and the
median sits just above the top of the range. That is a single-machine, single
-location sample and will be characterised properly over the collection window.

## Still unanswered## Still unanswered — blocked on the billing gate

These are the questions the spike exists to settle. Everything downstream
assumes an answer, so none of them should be guessed:

All five spike questions are now answered above. What remains needs volume
rather than another spike:

- [ ] Latency distribution over the full collection window, not one machine on
      one afternoon — p50/p90/p99 with a time-of-day drift plot.
- [ ] Whether the 1-in-10 decision flip rate at τ=0.5 holds across a stratified
      sample, and how it varies with distance from the threshold. This is the
      determinism sweep, and it is now a headline result rather than a footnote.
- [ ] Whether `confidence` on `choice`/`score` carries information beyond the
      probability vector itself — i.e. is it just max(p), or something more?
