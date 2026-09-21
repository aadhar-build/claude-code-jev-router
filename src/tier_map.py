"""W1, the static floor: the `subagent_type -> tier` map, as data plus a decision.

This module is the PYTHON half of a rule that also exists in `jq` inside
`hooks/agent_route_actuator.sh`. Two implementations of one format is a hazard
this repo already knows (`state_builders.build_pre_bash` vs the inline hook's
`jq`), and the way it is kept honest is the same: a test feeds both the same
input and asserts they agree, including on the config fingerprint.

The hook is the deployed path; this module is what the tests, the verifier and
any future analysis read. Neither contains a tier literal -- `config/tiers.json`
does, and `config_sha256()` is what a ledger row carries so a decision can later
be joined to the exact rule text that produced it.

WHY A STATIC MAP AND NOT A CLASSIFIER
-------------------------------------
Five independent sources find learned routers frequently fail to beat a trivial
static rule, while published static heuristics already deliver real savings. The
floor ships first, costs nothing, and is the baseline anything cleverer has to
beat. Zero network calls, zero added latency.

THE MAP IS A POLICY CHOICE AND IS NOT FITTED TO DATA
-----------------------------------------------------
Three of the four rules sit on cells of n=2, n=3 and n=12. Those are anecdotes.
Each tier assignment in `config/tiers.json` is a written policy judgement about
what that agent type's job description implies, revisable the moment outcome
data exists -- not a number read off a distribution. The counts in that file
are evidence about COVERAGE only, never about which tier a type should get.

THE CEILING, WHICH IS IN THE CODE AND NOT ONLY IN THE PROSE
-----------------------------------------------------------
`general-purpose` is the large majority of delegated work -- 78/120 (65%) by the
best-sourced full-window snapshot, 55-79% by counts taken on disk today. It is
the catch-all type and carries no routing signal, so `config/tiers.json` maps it
to `None` and `decide()` returns `no_rule`, leaving the input untouched.

The static floor therefore addresses somewhere between an eighth and a third of
delegated traffic: 35% full-window, 12-17% by today's count. That is a RANGE and
it is deliberately not collapsed to a point -- four counts of "a delegated task"
circulate for this project and they differ by a factor of 17 because they count
different things over different windows. `config/tiers.json:_counts_and_their_rules`
records all four with their counting rules; `.scratch/pivot/count_reconcile.py`
reproduces them. Any saving claimed for this layer must be quoted against that
denominator, never against total spend.

THE THREE OUTCOMES, WHICH ARE NOT THE SAME THING
------------------------------------------------
  * `routed`       -- a rule fired; rewrite `model` to that tier's ALIAS.
  * `no_rule` / `explicit_model_kept` -- nothing to say; leave the input alone.
    A MISS IS NOT AN ERROR and must never fail to frontier: routing an unknown
    type upward is a cost decision made on no information.
  * `fail_to_frontier` -- the router broke (missing config, unreadable rules).
    Rewrite to the frontier tier. Operator decision 2026-09-21: quality is
    protected on the error path, cost is not. This is the branch the circuit
    breaker exists to bound.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import paths

CONFIG_FILE = paths.CONFIG / "tiers.json"

# The assignment ledger and the breaker log. Imported from paths.py rather than
# rebuilt here: the repo rule (doctor.py's check_no_outside_writes_in_source) is
# that every writer takes its destination from paths, so there is one place a
# path can be wrong. Under data/ rather than logs/ for the reason data/drops is:
# an assignment that cannot be joined to an outcome is attrition, and attrition
# has to outlive a log rotation.
AGENT_ROUTE_DIR = paths.AGENT_ROUTE

#: Outcomes that mean "the input was rewritten".
REWRITING = frozenset({"routed", "fail_to_frontier"})

#: Outcomes that count as a router FAILURE for the circuit breaker. Note what is
#: absent: `no_rule` and `explicit_model_kept` are successful decisions to do
#: nothing, and counting them would trip the breaker on the 65% majority.
FAILURES = frozenset({"fail_to_frontier", "ledger_write_failed", "unparseable_payload"})


class TierConfigError(RuntimeError):
    """The rule table is missing or unusable. Callers fail to frontier."""


@dataclass(frozen=True)
class Decision:
    """What the hook decided, and everything a ledger row needs to explain it."""

    outcome: str           # routed | no_rule | explicit_model_kept | fail_to_frontier
    tier: str | None       # the tier key, e.g. "haiku45"
    alias: str | None      # what goes into tool_input.model, e.g. "haiku"
    rule: str              # the rule that fired, verbatim, or why none did
    original_model: str | None
    subagent_type: str | None

    @property
    def rewrites(self) -> bool:
        return self.outcome in REWRITING and self.alias is not None


def load(path: Path | None = None) -> dict:
    """Read the rule table.

    Deliberately NOT routed through `config_loader`: `tiers.json` is not added
    to `config_loader.WATCHED`, because doing so would change
    `config_fingerprint()` for every already-collected row and silently break
    the config-join JEV-32 built. The routing rule carries its own separate
    fingerprint instead.
    """
    path = path or CONFIG_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TierConfigError(f"{path}: {exc}") from exc
    for required in ("tiers", "rules", "frontier_tier"):
        if required not in data:
            raise TierConfigError(f"{path}: no {required!r}")
    frontier = data["frontier_tier"]
    if frontier not in data["tiers"]:
        raise TierConfigError(f"{path}: frontier_tier {frontier!r} is not a tier")
    return data


def config_sha256(path: Path | None = None) -> str:
    """Content hash of the rule table, as it appears on disk.

    Bytes, not parsed JSON: the hook computes the same digest with
    `openssl dgst -sha256` and has no parser to agree with. A test asserts the
    two agree, which is the only thing that keeps them from drifting.
    """
    path = path or CONFIG_FILE
    return hashlib.sha256(path.read_bytes()).hexdigest()


def alias_for(config: dict, tier: str) -> str:
    entry = config["tiers"].get(tier)
    if not entry or not entry.get("alias"):
        raise TierConfigError(f"tier {tier!r} has no alias")
    return entry["alias"]


def tier_for_alias(config: dict, alias: str | None) -> str | None:
    """The tier key whose `alias` is `alias`, or None.

    The inverse of `alias_for`, and it exists for one reason: the hook's
    fail-to-frontier branch writes `tier: null` on the ledger row. It has to --
    that branch is reached exactly when `config/tiers.json` could not be read,
    so there is no tier key it could honestly name -- but it DOES rewrite
    `model`, to `FRONTIER_FALLBACK_ALIAS`. A reader that keys off `tier` alone
    therefore scores every frontier failure as "left alone", which is the
    control arm, which is the branch that bills frontier rates going invisible.

    Returns None rather than raising: this is a reader on a reporting path, and
    an alias no tier claims is a fact to report (`unverifiable`), not a crash.
    """
    if not alias:
        return None
    for key, entry in (config.get("tiers") or {}).items():
        if isinstance(entry, dict) and entry.get("alias") == alias:
            return key
    return None


def decide(tool_input: dict, config: dict) -> Decision:
    """Apply the static map to one `Agent` tool input. Pure; touches nothing."""
    # NOTE ON QUOTING: every `rule` string below is built with json.dumps,
    # not Python's repr. The jq half of this rule emits the same strings via
    # `tojson`, and tests/test_agent_actuator.py compares them byte for byte;
    # repr's single quotes would make two correct implementations disagree.
    subagent_type = tool_input.get("subagent_type")
    original_model = tool_input.get("model")

    # The caller's own choice comes first. ~20% of real spawns name a model, and
    # clobbering a deliberate human choice with a static table is the one way
    # this hook can make quality worse on purpose. Recorded either way, so the
    # kept choice is still attributable.
    # `inherit` is in tool_input.model but expresses no tier preference -- it
    # means "use the parent's model". Treating it as a deliberate choice would
    # exclude those spawns from routing forever while looking like deference.
    ignored = config.get("explicit_model_ignored_values", ["inherit"])
    chose_a_model = bool(original_model) and original_model not in ignored

    if chose_a_model and config.get("explicit_model_action", "keep") == "keep":
        return Decision(
            outcome="explicit_model_kept",
            tier=None,
            alias=None,
            rule=("explicit_model_action=keep; caller asked for "
                  + json.dumps(original_model)),
            original_model=original_model,
            subagent_type=subagent_type,
        )

    rule = config["rules"].get(subagent_type) if subagent_type else None

    if rule is None:
        # A type with no row. NOT an error: see the module docstring.
        action = config.get("unmapped_action", "leave")
        if action == "frontier":
            tier = config["frontier_tier"]
            return Decision(
                outcome="routed", tier=tier, alias=alias_for(config, tier),
                rule=("unmapped_action=frontier for subagent_type="
                      + json.dumps(subagent_type)),
                original_model=original_model, subagent_type=subagent_type)
        return Decision(
            outcome="no_rule", tier=None, alias=None,
            rule=("unmapped_action=leave; no rule for subagent_type="
                  + json.dumps(subagent_type)),
            original_model=original_model, subagent_type=subagent_type)

    tier = rule.get("tier")
    if tier is None:
        # An explicit null tier -- `general-purpose`. Mapped on purpose, to
        # nothing. This row is the static floor's ceiling and it is a rule that
        # fired, not a rule that was missing, so it is reported as such.
        return Decision(
            outcome="no_rule", tier=None, alias=None,
            rule=(f"rules[{json.dumps(subagent_type)}].tier=null (no routing signal)"),
            original_model=original_model, subagent_type=subagent_type)

    if tier not in config["tiers"]:
        raise TierConfigError(
            f"rules[{subagent_type!r}].tier={tier!r} names no tier in `tiers`")

    return Decision(
        outcome="routed", tier=tier, alias=alias_for(config, tier),
        rule=f"rules[{json.dumps(subagent_type)}].tier={json.dumps(tier)}",
        original_model=original_model, subagent_type=subagent_type)


def frontier_decision(config: dict, why: str) -> Decision:
    """The error path. Quality protected, cost not -- and breaker-counted."""
    tier = config["frontier_tier"]
    return Decision(
        outcome="fail_to_frontier", tier=tier, alias=alias_for(config, tier),
        rule=f"fail_to_frontier: {why}", original_model=None, subagent_type=None)


def apply(tool_input: dict, decision: Decision) -> dict:
    """Produce the object that becomes `updatedInput`.

    `updatedInput` REPLACES THE ENTIRE TOOL INPUT. Every field the caller sent
    must come back, byte-for-byte, or the spawn silently gets the wrong agent
    type -- a failure indistinguishable in the results from a routing-quality
    effect. Hence `dict(tool_input)` and a single keyed assignment: there is no
    construction here that could omit a field it did not know about.
    """
    out = dict(tool_input)
    if decision.alias is not None:
        out["model"] = decision.alias
    return out


def coverage(config: dict, observed: dict[str, int]) -> dict:
    """What share of observed traffic this map can actually address.

    Exists so the ceiling is computable rather than quoted. `observed` is
    {subagent_type: count}.
    """
    total = sum(observed.values())
    routed = 0
    for subagent_type, count in observed.items():
        rule = config["rules"].get(subagent_type)
        if rule and rule.get("tier"):
            routed += count
    return {
        "total": total,
        "routable": routed,
        "unroutable": total - routed,
        "share_routable": (routed / total) if total else 0.0,
    }
