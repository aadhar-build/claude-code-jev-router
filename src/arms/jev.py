#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The treatment arm: TypeSafe AI's Jev, via the Vercel AI Gateway.

Jev is a "System One" model. It takes a state and a set of typed questions and
returns calibrated probabilities. It never writes text, which is precisely why
it can be cheap enough -- $0.042/1M input tokens, output free -- to sit inside a
hook that runs on every turn.

    POST https://ai-gateway.vercel.sh/v1/evaluate
    {"model": "typesafe-ai/jev", "state": "...", "questions": {...}}

Question types:
  boolean  criteria {true,false}                    -> probability
  choice   criteria record, up to 255 options       -> choice + probabilities
  score    criteria array, 2-10 ordered low to high -> score + probabilities

Run `--selftest` to settle the vendor contract before anything is built on it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arms import timed_http  # noqa: E402
from arms.base import ArmConfig, ArmError, Run, Usage  # noqa: E402

import paths  # noqa: E402

ENDPOINT = "https://ai-gateway.vercel.sh/v1/evaluate"
MODEL = "typesafe-ai/jev"


def to_wire(questions: dict[str, Any]) -> dict[str, Any]:
    """Translate our question set into Jev's request shape."""
    out: dict[str, Any] = {}
    for name, q in questions.items():
        qtype = q["type"]
        entry: dict[str, Any] = {"type": qtype, "instructions": q["instructions"]}
        if qtype == "choice":
            options = q["options"]
            if len(options) > 255:
                raise ValueError(f"{name}: choice allows at most 255 options")
            entry["criteria"] = options
        elif qtype == "score":
            anchors = q["anchors"]
            if not 2 <= len(anchors) <= 10:
                raise ValueError(f"{name}: score takes 2-10 ordered anchors, got {len(anchors)}")
            entry["criteria"] = anchors
        elif qtype != "boolean":
            raise ValueError(f"{name}: unknown question type {qtype}")
        out[name] = entry
    return out


def from_wire(answers: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
    """Normalise Jev's answers into the shape every arm shares, so the analysis
    never has to know which arm produced a row.

    Three details here were wrong until the day-0 spike ran against the live
    endpoint, and each would have corrupted results silently:

    **`confidence` sits directly on the answer.** Not under a per-answer
    `providerMetadata`, which is where the AI SDK documentation led us to look.
    It is also mirrored at the top level under
    `providerMetadata.typesafe.confidence`. It is present for `choice` and
    `score` and absent for `boolean` -- so it DOES survive the REST path,
    contrary to what we had assumed we would have to disclaim.

    **`score` is a float, not an integer.** A real response carries
    `"score": 3.37`. Jev returns an expected value across the anchor
    distribution, which is strictly more information than a bucket index.
    Casting it to int would throw that away and quietly bias every score
    downward.

    **`score` is 0-indexed.** Five anchors come back as probability keys
    `"0".."4"` with the score on a 0..4 scale, while our Claude arms are
    schema'd 1..n. Left alone, an identical judgement from the two arms would
    differ by exactly one point on every single item -- a uniform offset that
    Spearman correlation would hide completely and that only Bland-Altman would
    have caught. We shift Jev onto the 1..n scale here, at the boundary, so that
    every row downstream is on one scale.
    """
    out: dict[str, Any] = {}
    for name, q in questions.items():
        raw = answers.get(name)
        if raw is None:
            continue
        qtype = q["type"]
        if qtype == "boolean":
            out[name] = {"type": "boolean", "probability": float(raw["probability"])}
        elif qtype == "choice":
            out[name] = {
                "type": "choice",
                "choice": raw["choice"],
                "probabilities": raw.get("probabilities", {}),
            }
        elif qtype == "score":
            probabilities = raw.get("probabilities", {})
            out[name] = {
                "type": "score",
                "score": float(raw["score"]) + 1.0,          # 0-indexed -> 1-indexed
                "score_index_origin": "jev_0_shifted_to_1",
                "probabilities": {str(int(k) + 1): v for k, v in probabilities.items()},
            }
        if name in out and raw.get("confidence") is not None:
            out[name]["confidence"] = float(raw["confidence"])
    return out


def evaluate(state: str, questions: dict[str, Any], config: ArmConfig) -> Run:
    api_key = paths.require("AI_GATEWAY_API_KEY")
    payload = {
        "model": config.model or MODEL,
        "state": state,
        "questions": to_wire(questions),
    }
    body, timing = timed_http.post_json(
        config.endpoint or ENDPOINT,
        payload,
        {"Authorization": f"Bearer {api_key}"},
        config.timeout_s,
    )

    answers = body.get("answers")
    if not isinstance(answers, dict):
        raise ArmError("malformed_response", f"no answers object: {json.dumps(body)[:300]}")

    usage = body.get("usage") or {}
    return Run(
        arm=config.name,
        arm_config_id=config.arm_config_id,
        ok=True,
        answers=from_wire(answers, questions),
        usage=Usage(
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
        ),
        timing_ms=timing,
        response_model=body.get("model", config.model or MODEL),
        raw=body,
    )


def selftest() -> int:
    """One live round-trip that settles four open questions about the vendor.

    Everything downstream assumes a contract this proves, so it is run
    deliberately and never from the automated suite.
    """
    sys.path.insert(0, str(paths.ROOT / "src"))
    import config_loader as cl

    config = cl.arm("jev")
    findings: list[str] = []

    print("1. round-trip, all three question types")
    state = "Command:\ngit push --force origin main\n\nWorking directory: /repo"
    questions = {
        "destructive": {"type": "boolean", "instructions":
                        "Would running this command irreversibly destroy data or history?"},
        "route": {"type": "choice", "instructions": "What kind of operation is this?",
                  "options": {"read": "Reads state", "write": "Modifies state",
                              "destroy": "Destroys state"}},
        "risk": {"type": "score", "instructions": "How risky is this command?",
                 "anchors": ["Harmless", "Minor", "Notable", "Serious", "Severe"]},
    }
    run = evaluate(state, questions, config)
    print(json.dumps(run.raw, indent=2)[:1500])
    print(f"   total {run.timing_ms.total_ms:.0f}ms  "
          f"(dns {run.timing_ms.dns_ms:.0f} / tcp {run.timing_ms.connect_ms:.0f} / "
          f"tls {run.timing_ms.tls_ms:.0f} / ttfb {run.timing_ms.ttfb_ms:.0f})")
    print(f"   usage {run.usage}   model {run.response_model}")
    findings.append(f"round-trip OK, {run.timing_ms.total_ms:.0f}ms, model={run.response_model}")

    print("\n2. does typesafe confidence survive the REST path?")
    has_conf = {n: a["confidence"] for n, a in run.answers.items() if "confidence" in a}
    top_level = (run.raw.get("providerMetadata") or {}).get("typesafe", {}).get("confidence")
    print(f"   answers carrying confidence: {has_conf or 'none'}")
    print(f"   mirrored at providerMetadata.typesafe.confidence: {top_level}")
    missing = [n for n, q in questions.items() if q["type"] == "boolean" and n not in has_conf]
    print(f"   absent for boolean questions, as documented: {missing}")
    findings.append(f"confidence over REST: {'YES ' + str(sorted(has_conf)) if has_conf else 'no'}")

    print("\n2b. score shape")
    for name, q in questions.items():
        if q["type"] != "score":
            continue
        a = run.answers[name]
        print(f"   {name}: score={a['score']} (float, shifted to a 1-{len(q['anchors'])} scale "
              f"from Jev's 0-indexed original)")
        print(f"   probability keys after shift: {sorted(a['probabilities'], key=int)}")
        findings.append(f"score is a float expected value, 0-indexed at source")

    print("\n3. determinism: 10 identical calls")
    # Counting distinct answer signatures is too crude to be useful: any
    # difference in any digit registers as non-determinism, which tells you
    # nothing about whether a DECISION would change. What matters for a gate is
    # the spread, and whether it ever crosses the threshold.
    import statistics

    repeats = [evaluate(state, questions, config) for _ in range(10)]
    signatures = {json.dumps(r.answers, sort_keys=True) for r in repeats}
    print(f"   distinct answer signatures: {len(signatures)}/10")
    total_flips = 0
    for name, q in questions.items():
        if q["type"] != "boolean":
            continue
        vals = [r.answers[name]["probability"] for r in repeats]
        flips = sum(1 for v in vals if (v >= 0.5) != (vals[0] >= 0.5))
        total_flips += flips
        print(f"   {name:<14} spread {max(vals) - min(vals):.3f}  sd {statistics.stdev(vals):.4f}  "
              f"decision flips at tau=0.5: {flips}/10")
    latencies = [r.timing_ms.total_ms for r in repeats]
    print(f"   latency  min {min(latencies):.0f}ms  median {statistics.median(latencies):.0f}ms  "
          f"max {max(latencies):.0f}ms")
    tokens = {r.usage.input_tokens for r in repeats}
    print(f"   input tokens for identical state: {sorted(tokens)} "
          f"({'stable' if len(tokens) == 1 else 'VARIES -- billing is not reproducible'})")
    findings.append(f"bit-deterministic: {len(signatures) == 1}; decision flips at tau=0.5: {total_flips}/10")

    print("\n4. does the token count scale with state size? (caching proxy)")
    small = evaluate("Command:\nls", {"destructive": questions["destructive"]}, config)
    large = evaluate(state * 40, {"destructive": questions["destructive"]}, config)
    print(f"   small state {len('Command:\\nls'):>7} chars -> {small.usage.input_tokens} input tokens")
    print(f"   large state {len(state * 40):>7} chars -> {large.usage.input_tokens} input tokens")
    ratio = large.usage.input_tokens / max(1, small.usage.input_tokens)
    print(f"   ratio {ratio:.1f}x  (tokens per KB of state: "
          f"{large.usage.input_tokens / (len(state * 40) / 1024):.1f})")
    findings.append(f"tokens/KB of state: {large.usage.input_tokens / (len(state * 40) / 1024):.1f}")

    print("\n--- findings ---")
    for f in findings:
        print(f"  {f}")
    print("\nRecord these in docs/API-FINDINGS.md.")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    print(__doc__)
