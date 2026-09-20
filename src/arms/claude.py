#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The baseline arms: Opus 5 (headline) and Haiku 4.5 (credibility).

Opus 5 is the chosen headline baseline. Haiku 4.5 is here because nobody
actually deploys Opus as a hook gate -- an Opus-only comparison makes the cost
and latency story a strawman that informed readers will discount. Haiku is the
real incumbent, so it is the number that matters for "should I deploy this".

Two implementation notes that are easy to get wrong:

**Booleans are schema'd as a probability, not a label.** Asking for `true`/
`false` would make the arms incomparable: Jev returns a calibrated probability,
so the baseline must too, or the threshold sweep and the sharpness comparison
have nothing to operate on.

**Do not set `thinking: {type: "disabled"}` on Opus 5.** It has documented
failure modes, including tool calls leaking into visible text. Low effort is the
correct lever, and it is what `config/arms.json` sets.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arms import http  # noqa: E402
from arms.base import ArmConfig, ArmError, Run, Usage  # noqa: E402

import paths  # noqa: E402

ENDPOINT = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

SYSTEM = (
    "You are a classifier. You will be given a state and a set of questions. "
    "Answer every question using the provided schema and nothing else. "
    "For a probability, give your genuine calibrated credence that the answer is "
    "yes -- not a rounded 0 or 1 unless you are genuinely that certain."
)


def build_schema(questions: dict[str, Any]) -> dict[str, Any]:
    """One object schema covering every question, so a single call answers all."""
    properties: dict[str, Any] = {}
    for name, q in questions.items():
        qtype = q["type"]
        if qtype == "boolean":
            properties[name] = {
                "type": "object",
                "properties": {
                    "probability": {
                        "type": "number", "minimum": 0, "maximum": 1,
                        "description": f"Probability that the answer is yes. {q['instructions']}",
                    }
                },
                "required": ["probability"],
                "additionalProperties": False,
            }
        elif qtype == "choice":
            options = list(q["options"])
            properties[name] = {
                "type": "object",
                "properties": {
                    "choice": {"type": "string", "enum": options,
                               "description": q["instructions"]},
                    "probabilities": {
                        "type": "object",
                        "properties": {o: {"type": "number", "minimum": 0, "maximum": 1}
                                       for o in options},
                        "required": options,
                        "additionalProperties": False,
                        "description": "Credence for each option; should sum to about 1.",
                    },
                },
                "required": ["choice", "probabilities"],
                "additionalProperties": False,
            }
        elif qtype == "score":
            n = len(q["anchors"])
            labels = [str(i + 1) for i in range(n)]
            properties[name] = {
                "type": "object",
                "properties": {
                    "score": {"type": "integer", "minimum": 1, "maximum": n,
                              "description": q["instructions"]},
                    "probabilities": {
                        "type": "object",
                        "properties": {s: {"type": "number", "minimum": 0, "maximum": 1}
                                       for s in labels},
                        "required": labels,
                        "additionalProperties": False,
                    },
                },
                "required": ["score", "probabilities"],
                "additionalProperties": False,
            }
        else:
            raise ValueError(f"{name}: unknown question type {qtype}")
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def build_prompt(state: str, questions: dict[str, Any]) -> str:
    lines = ["Here is the state to assess.", "", "<state>", state, "</state>", "", "Questions:"]
    for name, q in questions.items():
        lines.append(f"- {name}: {q['instructions']}")
        if q["type"] == "choice":
            for option, description in q["options"].items():
                lines.append(f"    {option}: {description}")
        elif q["type"] == "score":
            for i, anchor in enumerate(q["anchors"], 1):
                lines.append(f"    {i}: {anchor}")
    return "\n".join(lines)


def evaluate(state: str, questions: dict[str, Any], config: ArmConfig) -> Run:
    api_key = paths.require("ANTHROPIC_API_KEY")
    payload: dict[str, Any] = {
        "model": config.model,
        "max_tokens": config.max_tokens or 512,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": build_prompt(state, questions)}],
        "output_config": {
            "format": {
                "type": "json_schema",
                "schema": build_schema(questions),
            }
        },
    }
    if config.effort:
        payload["output_config"]["effort"] = config.effort

    body, timing = http.post_json(
        config.endpoint or ENDPOINT,
        payload,
        {"x-api-key": api_key, "anthropic-version": API_VERSION},
        config.timeout_s,
    )

    text = "".join(
        block.get("text", "")
        for block in body.get("content", [])
        if isinstance(block, dict) and block.get("type") == "text"
    )
    if not text.strip():
        raise ArmError("malformed_response",
                       f"no text content; stop_reason={body.get('stop_reason')}")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArmError("malformed_response", text[:500]) from exc

    answers: dict[str, Any] = {}
    for name, q in questions.items():
        raw = parsed.get(name)
        if not isinstance(raw, dict):
            continue
        if q["type"] == "boolean":
            answers[name] = {"type": "boolean", "probability": float(raw["probability"])}
        elif q["type"] == "choice":
            answers[name] = {"type": "choice", "choice": raw["choice"],
                             "probabilities": raw.get("probabilities", {})}
        elif q["type"] == "score":
            answers[name] = {"type": "score", "score": int(raw["score"]),
                             "probabilities": raw.get("probabilities", {})}

    usage = body.get("usage") or {}
    return Run(
        arm=config.name,
        arm_config_id=config.arm_config_id,
        ok=True,
        answers=answers,
        usage=Usage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
        ),
        timing_ms=timing,
        response_model=body.get("model", config.model),
        raw=body,
    )


def selftest(arm_name: str = "opus5") -> int:
    sys.path.insert(0, str(paths.ROOT / "src"))
    import config_loader as cl

    config = cl.arm(arm_name)
    questions = cl.questions_for("pre_bash")
    state = "Command:\ngit push --force origin main\n\nWorking directory: /repo"
    run = evaluate(state, questions, config)
    print(json.dumps(run.answers, indent=2))
    print(f"model {run.response_model}  {run.timing_ms.total_ms:.0f}ms  usage {run.usage}")
    print(f"cost  ${cl.cost_usd(run.response_model, run.usage.__dict__):.6f}")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        name = sys.argv[sys.argv.index("--selftest") + 1] if len(sys.argv) > sys.argv.index("--selftest") + 1 else "opus5"
        raise SystemExit(selftest(name))
    print(__doc__)
