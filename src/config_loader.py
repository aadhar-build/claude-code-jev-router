"""Load the versioned config and question sets. Config is data, not code.

Config is read ONCE per process and then pinned. That is deliberate, and it is
also how JEV-30 happened: the worker started at 15:49:55, `config/arms.json`
gained `cc_sonnet5` at 15:55:26, and every row collected afterwards silently
omitted the arm. Nothing warned. The rows looked complete, because `arm_order`
faithfully recorded the three arms the process knew about.

WHY THE FIX IS A REFUSAL AND NOT A HOT RELOAD
---------------------------------------------
Hot-reloading was rejected. A collection window is a measurement, and config is
the definition of what is being measured -- the arm set, the question-set pins,
the price table. Reloading mid-window would let rows either side of an
unremarkable text edit come from different definitions while looking identical,
which converts a loud operator error into a silent, unreconstructable
confounder. That is strictly worse than stopping: JEV-30's boundary was only
recoverable at all because a restart left a process-start timestamp to bisect
on.

So: a changed config file is a HARD ERROR on the next config touch
(`ConfigStaleError`), naming the files and telling the operator to restart. The
remedy -- restart -- is the thing that creates the visible boundary.

The check is GLOBAL, not per-file, and this is load-bearing. `worker.py` is
handed its arm list at startup and may never call `arms_config()` again, so a
per-file check would miss the actual JEV-30 incident entirely; and
`cl.pricing()` is only touched AFTER the arms have been called and the capture
row written, so a per-file check on pricing would refuse only once the budget
was already spent. Every accessor checks every watched file, so the refusal
fires on the first config touch of a capture -- before any arm runs and before
any row is written.

Also rejected:
  * mtime-only detection -- a checkout or a no-op re-save would stop collection
    for nothing. Content hash decides; the stat is only the cheap pre-filter.
  * a warning on every drain cycle -- a warning that appears every 30 seconds
    for hours is a warning nobody reads, and the rows keep being written wrong
    the whole time.
  * trusting the hand-maintained `version` strings. `pricing()["version"]` is
    stamped on every row, but an operator who edits a RATE without bumping the
    version produces two processes stamping the same `pricing-2026-09-20` on
    rows computed from different numbers. `config_fingerprint()` stamps a
    CONTENT hash for exactly that reason, and JEV-32 needs it to join rows to
    the config that actually produced them.
"""

from __future__ import annotations

import functools
import hashlib
import json
from typing import Any

import paths
import state_builders as sb
from arms.base import ArmConfig

# The files pinned for the life of the process. Question sets are not here:
# they are frozen by PREREGISTRATION section 8 and every row already carries
# the `question_set_id` it was run under.
WATCHED = ("surfaces.json", "arms.json", "pricing.json")

# path -> (st_mtime_ns, st_size, sha256). Seeded at the first freshness check,
# not at the first load, so a file the process never reads is still watched.
_SEEN: dict[str, tuple[int, int, str]] = {}


class ConfigStaleError(RuntimeError):
    """A config file changed after this process pinned it.

    Fatal on purpose. See the module docstring: the alternative is rows on
    either side of the edit that are indistinguishable and not comparable.
    """


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stale_config_files() -> dict[str, str]:
    """{filename: "<old sha12> -> <new sha12>"} for every watched file whose
    CONTENT changed since this process first saw it.

    Cheap: one stat per file, and a re-hash only when mtime or size moved, so a
    bare `touch` or a re-save with identical bytes is not a change.
    """
    changed: dict[str, str] = {}
    for name in WATCHED:
        path = paths.CONFIG / name
        try:
            stat = path.stat()
        except OSError:
            # A watched file that has been deleted or was never there. Not this
            # function's error to raise; the loader that needs it will say so
            # with a far better message.
            continue
        key = str(path)
        previous = _SEEN.get(key)
        if previous is None:
            _SEEN[key] = (stat.st_mtime_ns, stat.st_size, _sha256(path))
            continue
        if (stat.st_mtime_ns, stat.st_size) == previous[:2]:
            continue
        digest = _sha256(path)
        if digest == previous[2]:
            _SEEN[key] = (stat.st_mtime_ns, stat.st_size, digest)
            continue
        changed[name] = f"{previous[2][:12]} -> {digest[:12]}"
    return changed


def assert_config_fresh() -> None:
    """Raise if any watched config file changed since this process pinned it."""
    changed = stale_config_files()
    if not changed:
        return
    detail = "; ".join(f"{name} ({d})" for name, d in sorted(changed.items()))
    raise ConfigStaleError(
        f"config changed after this process loaded it: {detail}. "
        "Config is pinned for the life of a process ON PURPOSE -- reloading it "
        "mid-window would make rows either side of the edit silently "
        "incomparable (JEV-30). RESTART the worker to adopt the change; the "
        "restart is what makes the configuration boundary visible in the data."
    )


def reset_caches() -> None:
    """Forget everything this process pinned -- what a fresh process does.

    The supported way out of a ConfigStaleError inside one process, and the way
    tests point `paths.CONFIG` somewhere else.
    """
    for fn in (_surfaces, _arms_config, _pricing, question_set):
        fn.cache_clear()
    _SEEN.clear()


def config_fingerprint() -> dict[str, Any]:
    """The identity of the config this process is running on.

    Meant to be stamped on every row. `*_version` are the human-maintained pins
    and are the readable half; `config_sha256` is the half that cannot be
    forgotten, because it is derived from the bytes. Two rows with the same
    `config_sha256` were produced under byte-identical config; two rows that
    differ were not, whatever their version strings claim. This is the join key
    JEV-32 needs.
    """
    assert_config_fresh()
    _surfaces(), _arms_config(), _pricing()  # force the loads so hashes exist
    files = {}
    for name in WATCHED:
        seen = _SEEN.get(str(paths.CONFIG / name))
        files[name] = seen[2][:12] if seen else None
    combined = hashlib.sha256(
        "\n".join(f"{n}:{files[n]}" for n in WATCHED).encode()
    ).hexdigest()[:16]
    return {
        "config_sha256": combined,
        "files": files,
        "surfaces_version": _surfaces().get("version"),
        "arms_version": _arms_config().get("version"),
        "pricing_version": _pricing().get("version"),
    }


class QuestionSetError(RuntimeError):
    """A surface names a question set that cannot be resolved.

    Deliberately fatal. The question set is the replay key (PREREGISTRATION
    section 8), so a surface that silently fell back to a default version would
    score the study against a question set nobody chose -- and the rows would
    look perfectly well-formed while doing it.
    """


@functools.cache
def _surfaces() -> dict[str, Any]:
    config = json.loads((paths.CONFIG / "surfaces.json").read_text())
    _validate_question_sets(config)
    _validate_state_sources(config)
    return config


def surfaces() -> dict[str, Any]:
    assert_config_fresh()
    return _surfaces()


def surface_names() -> tuple[str, ...]:
    """The surface list, from config. The single source (JEV-31b).

    `paths.SURFACES` is a second, independent tuple of the same fact. It cannot
    be derived there -- paths.py is imported BY this module -- so callers move
    here instead.
    """
    return tuple(surfaces()["surfaces"])


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


def _validate_state_sources(config: dict[str, Any]) -> None:
    """`state_source` in config must agree with `state_builders.STATE_SOURCE`.

    JEV-31b. The field was inert: `worker.py` and `replay.py` write
    `sb.STATE_SOURCE[surface]` onto every capture row and never look at config.
    An operator editing config would see no error and reasonably believe it had
    taken effect -- and because the value IS written to every row, a divergence
    would silently mislabel the provenance of the leakage-safety argument.

    Two representations of one fact, so assert the agreement rather than hope
    for it, exactly as the question_set_id agreement is asserted above. Making
    the config side authoritative was rejected: STATE_SOURCE sits next to the
    builders that determine the answer, and a builder reading the payload does
    not become a transcript reader because a JSON file says so.
    """
    for surface, entry in config.get("surfaces", {}).items():
        declared = entry.get("state_source")
        actual = sb.STATE_SOURCE.get(surface)
        if actual is None:
            raise QuestionSetError(
                f"surface '{surface}' in config/surfaces.json has no state builder in "
                f"state_builders.STATE_SOURCE. Known: {', '.join(sorted(sb.STATE_SOURCE))}."
            )
        if declared != actual:
            raise QuestionSetError(
                f"surface '{surface}' declares state_source '{declared}' in "
                f"config/surfaces.json but state_builders.STATE_SOURCE says '{actual}', "
                "and it is STATE_SOURCE that is written onto every capture row. "
                "Change the builder, not the label."
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
def _arms_config() -> dict[str, Any]:
    return json.loads((paths.CONFIG / "arms.json").read_text())


def arms_config() -> dict[str, Any]:
    assert_config_fresh()
    return _arms_config()


@functools.cache
def _pricing() -> dict[str, Any]:
    return json.loads((paths.CONFIG / "pricing.json").read_text())


def pricing() -> dict[str, Any]:
    assert_config_fresh()
    return _pricing()


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


# Existing callers (tests/test_pipeline.py, tests/gate4_drain.py) reach for
# `cl.surfaces.cache_clear()`. Keep that working rather than rewriting call
# sites in files this ticket does not own -- but a shim that cleared the dict
# and left `_SEEN` populated would be a HALF reset: the next author to edit the
# same fixture config twice would get a ConfigStaleError out of their own test
# setup and have no idea why. Clearing a cache means forgetting the file too.
def _shim(cached, name):
    def clear() -> None:
        cached.cache_clear()
        _SEEN.pop(str(paths.CONFIG / name), None)
    return clear


surfaces.cache_clear = _shim(_surfaces, "surfaces.json")  # type: ignore[attr-defined]
arms_config.cache_clear = _shim(_arms_config, "arms.json")  # type: ignore[attr-defined]
pricing.cache_clear = _shim(_pricing, "pricing.json")  # type: ignore[attr-defined]


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
