"""Load the versioned config and question sets. Config is data, not code."""

from __future__ import annotations

import functools
import json
from typing import Any

import paths
from arms.base import ArmConfig


class QuestionSetError(RuntimeError):
    """A surface names a question set that cannot be resolved.

    Deliberately fatal. The question set is the replay key (PREREGISTRATION
    section 8), so a surface that silently fell back to a default version would
    score the study against a question set nobody chose -- and the rows would
    look perfectly well-formed while doing it.
    """


@functools.cache
def surfaces() -> dict[str, Any]:
    config = json.loads((paths.CONFIG / "surfaces.json").read_text())
    _validate_question_sets(config)
    return config


def _available_versions(surface: str) -> list[str]:
    directory = paths.QUESTIONS / surface
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def _validate_question_sets(config: dict[str, Any]) -> None:
    """Every surface in the config must name a question set file that exists.

    Checked at config-load time, for EVERY surface including `mode: off` ones.
    A dangling version on an off surface is the same latent defect: it only
    becomes visible on the day the surface is switched on, which is the worst
    possible day to discover it. functools.cache does not cache exceptions, so
    a broken config keeps raising rather than being papered over by the first
    successful call.
    """
    for surface, entry in config.get("surfaces", {}).items():
        version = entry.get("question_set")
        if not version:
            raise QuestionSetError(
                f"surface '{surface}' in config/surfaces.json has no 'question_set' key. "
                "There is no default: the question set is the replay key and must be pinned."
            )
        path = paths.QUESTIONS / surface / f"{version}.json"
        if not path.is_file():
            have = _available_versions(surface) or ["<none>"]
            raise QuestionSetError(
                f"surface '{surface}' is pinned to question set '{version}' but "
                f"{path} does not exist. Available for this surface: {', '.join(have)}."
            )
        # The file declares its own identity. Config selects a version. Those are
        # two representations of one fact, and nothing forced them to agree --
        # so a question file copied to a new version number while keeping the
        # old `question_set_id` inside would be selected by config, recorded on
        # every row under the WRONG id, and never noticed, because the id on the
        # row is the one thing the analysis trusts to say which questions were
        # asked. Assert the agreement instead of hoping for it.
        declared = json.loads(path.read_text(encoding="utf-8")).get("question_set_id")
        expected = f"{surface}/{version}"
        if declared != expected:
            raise QuestionSetError(
                f"{path} declares question_set_id '{declared}' but config/surfaces.json "
                f"selects '{expected}'. The canonical form is '<surface>/<version>', and "
                "the file, the config and the id recorded on every row must agree -- "
                "the row-level id additionally carries a '#<phrasing>' suffix."
            )


def surface_question_version(surface: str) -> str:
    """The question set version this surface is pinned to in config.

    Raises rather than defaulting for an unknown surface.
    """
    entry = surfaces()["surfaces"].get(surface)
    if entry is None:
        known = ", ".join(sorted(surfaces()["surfaces"])) or "<none>"
        raise QuestionSetError(
            f"surface '{surface}' is not declared in config/surfaces.json. Known: {known}."
        )
    return entry["question_set"]


@functools.cache
def arms_config() -> dict[str, Any]:
    return json.loads((paths.CONFIG / "arms.json").read_text())


@functools.cache
def pricing() -> dict[str, Any]:
    return json.loads((paths.CONFIG / "pricing.json").read_text())


@functools.cache
def question_set(surface: str, version: str | None = None) -> dict[str, Any]:
    """Load a surface's question set.

    `version=None` -- the default for every call site -- resolves the version
    from `config/surfaces.json`. Passing a version explicitly overrides the
    config and is how a sweep re-asks a stored state under a different set.

    There is no fallback default. A version that does not exist on disk is a
    hard error, not a silent reversion to v1.
    """
    resolved = version or surface_question_version(surface)
    path = paths.QUESTIONS / surface / f"{resolved}.json"
    if not path.is_file():
        have = _available_versions(surface) or ["<none>"]
        raise QuestionSetError(
            f"question set '{surface}/{resolved}' does not exist at {path}. "
            f"Available for this surface: {', '.join(have)}."
        )
    return json.loads(path.read_text())


def arm(name: str) -> ArmConfig:
    return ArmConfig.from_json(name, arms_config()["arms"][name])


def enabled_arms() -> list[ArmConfig]:
    return [arm(n) for n in arms_config()["enabled"]]


def surface_mode(surface: str) -> str:
    return surfaces()["surfaces"].get(surface, {}).get("mode", "off")


def questions_for(surface: str, version: str | None = None,
                  phrasing: str | None = None) -> dict[str, Any]:
    """Resolve a question set into the {name: {type, instructions, ...}} shape
    the arms consume, with one phrasing selected.

    `version=None` takes the version the surface is pinned to in
    `config/surfaces.json`.

    The phrasing is part of the replay key: the same decision re-evaluated under
    a different phrasing is a different row, never an overwrite.
    """
    version = version or surface_question_version(surface)
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


def question_set_id(surface: str, version: str | None = None,
                    phrasing: str | None = None) -> str:
    """The replay key for a surface. `version=None` takes the configured pin."""
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
    cw = rate.get("cache_write_multiplier", pricing()["cache_write_multiplier"])
    # Per-model override: Fable 5.1 reportedly reads cache at 2.5% of its input
    # rate rather than the 10% every other model uses. A single global constant
    # would misprice it by 4x on exactly the cache-heavy turns where it competes.
    cr = rate.get("cache_read_multiplier", pricing()["cache_read_multiplier"])
    return (
        usage.get("input_tokens", 0) * rate["input"]
        + usage.get("cache_creation_input_tokens", 0) * rate["input"] * cw
        + usage.get("cache_read_input_tokens", 0) * rate["input"] * cr
        + usage.get("output_tokens", 0) * rate["output"]
    )
