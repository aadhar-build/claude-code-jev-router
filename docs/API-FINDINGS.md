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

## Still unanswered — blocked on the billing gate

These are the questions the spike exists to settle. Everything downstream
assumes an answer, so none of them should be guessed:

- [ ] Does `providerMetadata.typesafe.confidence` survive the REST path? It is
      documented for the AI SDK, on `choice` and `score` only, and never for
      `boolean`. `from_wire` records it when present and omits it otherwise, so
      the code is correct either way — but the writeup cannot claim a confidence
      signal exists over REST until this is seen.
- [ ] Is Jev deterministic? If it is, and temperature-zero LLMs are not, that
      earns its own section.
- [ ] Does prompt caching fire for short classifier prefixes? Likely under the
      minimum. Uncached is reported as primary regardless.
- [ ] What does `usage` actually report, and what is tokens-per-KB of state?
      This decides whether the cheap per-token rate is partly offset by Jev
      charging for more tokens than a comparable prompt would.
- [ ] Real latency distribution against the claimed 70-500ms, decomposed into
      DNS / TCP / TLS / TTFB so a server-side claim can be compared like for like.

Re-run with `uv run src/arms/jev.py --selftest` once the gate clears.
