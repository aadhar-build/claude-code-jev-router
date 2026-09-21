"""The test double. Deterministic, offline, free.

Answers are derived from a hash of the state so they are stable across runs but
vary across inputs -- enough structure for the worker, the storage layer and the
statistics to be exercised end to end without a network.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .base import ArmConfig, Clock, Run, Timing, Usage


def _unit(state: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}:{state}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


def evaluate(state: str, questions: dict[str, Any], config: ArmConfig) -> Run:
    clock = Clock()
    answers: dict[str, Any] = {}
    for name, spec in questions.items():
        qtype = spec["type"]
        p = _unit(state, f"{config.name}:{name}")
        if qtype == "boolean":
            answers[name] = {"type": "boolean", "probability": round(p, 6)}
        elif qtype == "choice":
            options = list(spec["options"])
            weights = [_unit(state, f"{config.name}:{name}:{o}") for o in options]
            total = sum(weights) or 1.0
            probs = {o: w / total for o, w in zip(options, weights)}
            answers[name] = {
                "type": "choice",
                "choice": max(probs, key=probs.__getitem__),
                "probabilities": {o: round(p_, 6) for o, p_ in probs.items()},
            }
        elif qtype == "score":
            n = len(spec["anchors"])
            weights = [_unit(state, f"{config.name}:{name}:{i}") for i in range(n)]
            total = sum(weights) or 1.0
            probs = [w / total for w in weights]
            answers[name] = {
                "type": "score",
                "score": 1 + max(range(n), key=probs.__getitem__),
                "probabilities": {str(i + 1): round(p_, 6) for i, p_ in enumerate(probs)},
            }
        else:
            raise ValueError(f"unknown question type: {qtype}")

    return Run(
        arm=config.name,
        arm_config_id=config.arm_config_id,
        ok=True,
        answers=answers,
        usage=Usage(input_tokens=max(1, len(state) // 4), output_tokens=0),
        timing_ms=Timing(total_ms=clock.elapsed_ms()),
        response_model="fake/deterministic-v1",
        raw={"fake": True},
    )
