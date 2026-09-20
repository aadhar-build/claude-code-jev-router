"""Load the versioned config and question sets. Config is data, not code."""

from __future__ import annotations

import functools
import json
from typing import Any

import paths
from arms.base import ArmConfig


@functools.cache
def surfaces() -> dict[str, Any]:
    return json.loads((paths.CONFIG / "surfaces.json").read_text())


@functools.cache
def arms_config() -> dict[str, Any]:
    return json.loads((paths.CONFIG / "arms.json").read_text())


@functools.cache
def pricing() -> dict[str, Any]:
    return json.loads((paths.CONFIG / "pricing.json").read_text())


@functools.cache
def question_set(surface: str, version: str = "v1") -> dict[str, Any]:
    return json.loads((paths.QUESTIONS / surface / f"{version}.json").read_text())


def arm(name: str) -> ArmConfig:
    return ArmConfig.from_json(name, arms_config()["arms"][name])


def enabled_arms() -> list[ArmConfig]:
    return [arm(n) for n in arms_config()["enabled"]]


def surface_mode(surface: str) -> str:
    return surfaces()["surfaces"].get(surface, {}).get("mode", "off")


def questions_for(surface: str, version: str = "v1", phrasing: str | None = None) -> dict[str, Any]:
    """Resolve a question set into the {name: {type, instructions, ...}} shape
    the arms consume, with one phrasing selected.

    The phrasing is part of the replay key: the same decision re-evaluated under
    a different phrasing is a different row, never an overwrite.
    """
    spec = question_set(surface, version)
    chosen = phrasing or spec["primary_phrasing"]
    out: dict[str, Any] = {}
    for name, q in spec["questions"].items():
        if chosen not in q["phrasings"]:
            raise KeyError(f"{surface}/{version}:{name} has no phrasing '{chosen}'")
        entry: dict[str, Any] = {
            "type": q["type"],
            "instructions": q["phrasings"][chosen],
        }
        if q["type"] == "choice":
            entry["options"] = q["options"]
        elif q["type"] == "score":
            entry["anchors"] = q["anchors"]
        out[name] = entry
    return out


def question_set_id(surface: str, version: str = "v1", phrasing: str | None = None) -> str:
    spec = question_set(surface, version)
    return f"{spec['question_set_id']}#{phrasing or spec['primary_phrasing']}"


def cost_usd(model: str, usage: dict[str, Any]) -> float | None:
    """Cost for one call, from version-pinned rates keyed by exact model string.

    Returns None for an unknown model rather than guessing -- a silently wrong
    cost is worse than a missing one, and the analysis reports coverage.
    """
    table = pricing()["models"]
    rate = table.get(model)
    if rate is None:
        return None
    cw = pricing()["cache_write_multiplier"]
    cr = pricing()["cache_read_multiplier"]
    return (
        usage.get("input_tokens", 0) * rate["input"]
        + usage.get("cache_creation_input_tokens", 0) * rate["input"] * cw
        + usage.get("cache_read_input_tokens", 0) * rate["input"] * cr
        + usage.get("output_tokens", 0) * rate["output"]
    )
