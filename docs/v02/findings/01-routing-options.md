# 01. Routing options for the general-purpose residue

Source: research subagent report, 2026-09-24; claims marked (unverified) were not independently confirmed.

Scope: how to route `Agent` spawns that the v0.1 static floor leaves alone (type `general-purpose`, absent, or `fork`, no explicit `model`). Research only; nothing was installed or armed.

## Verified facts (read directly in the repo)
- `hooks/agent_route_actuator.sh` is a PreToolUse/Agent hook. It matches `subagent_type` exactly, emits `updatedInput: $ti + {model: alias}`, writes the ledger row before spawning, and fails to the frontier tier. `explicit_model_action=keep`, `unmapped_action=leave`, `latency_budget_ms: 250` (`config/tiers.json`).
- `config/tiers.json` calls keyword matching on the description "out of scope for the static floor". That is a scoping decision for the floor, not a ban on v0.2. The earlier ISSUES.md rejection of a type-to-tier map concerned run budget inside an experimental arm, and the file says that objection no longer applies once the map is a free production floor.
- `questions/agent_route/v1.json` already defines the question set for this surface: `complexity` (5-anchor score) and `needs_frontier` (boolean), thresholds tau_low 2.0 / tau_high 3.5 / tau_frontier 0.65. Anchors never name a model (test-linted).
- `src/state_builders.py:build_agent_route` builds state from description, prompt, `subagent_type`, `run_in_background`, invoker type/id, `permission_mode`, `effort.level`, `cwd`. `tool_input.model` is deliberately withheld. It is a pure function of the payload (no filesystem or transcript reads).
- `src/arms/jev.py` + `config/arms.json`: the Jev arm calls the hosted model `typesafe-ai/jev` through Vercel AI Gateway (`POST https://ai-gateway.vercel.sh/v1/evaluate`, timeout 10 s, key in `AI_GATEWAY_API_KEY`). It is non-generative: it returns calibrated probabilities for boolean / choice / score questions. Stated price: $0.042 per 1M input tokens, output free. SPEC section 4: `confidence` is not portable across Jev servers, so threshold on `probabilities` only.
- Only latency distribution in the repo (SPEC sections 1-2, pre_bash gate): +557 ms p50, +2,681 ms p99 per call. That exceeds the actuator's 250 ms budget. Whether it transfers to the Agent surface is (unverified).
- SPEC section 2 R1: rework is the primary criterion, and escalation means RESTART, so down-routing is the risky direction. SPEC section 7 harvested an asymmetric down-route guard from `tzachbon/claude-model-router-hook`: up is free, cheapening needs margin, an `abstain` class exists. Non-negotiable 7: every mechanism must beat a constant control, run side by side.
- SPEC section 5 W4 already plans "Jev as advisor for the general-purpose residue"; ship gate is beating the static rule on realised cost at equal task success.
- `src/subagent_outcomes.py` joins ledger `tool_use_id` to `agent-<id>.meta.json.toolUseId`; per-call usage, model and stop reason live in the subagent transcript.
- Class 2 fixture suite: `tests/fixtures/accuracy/suite-v1/suite.json` (12 tasks x 3 recorded baseline runs).
- The `main` clone had no `data/baseline/` and no ledger rows; measurement had to start from an armed install.

## Verified facts (Claude Code docs)
- Hooks (https://code.claude.com/docs/en/hooks): PreToolUse honours `permissionDecision` allow/deny/ask/defer, `permissionDecisionReason` (shown to Claude only on deny), `updatedInput` (replaces the entire input) and `additionalContext`. Exit 2 is a deny.
- Sub-agents (https://code.claude.com/docs/en/sub-agents): model resolution is per-invocation `model` > frontmatter `model` (`inherit` = main) > `CLAUDE_CODE_SUBAGENT_MODEL` > main model. `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` overrides all. Frontmatter `effort` (low/medium/high/xhigh/max) "overrides the session effort level"; default inherits. There is no per-subagent thinking setting. Omitted `subagent_type` falls back to `general-purpose`.
- No per-invocation `effort` parameter on the Agent tool is documented. Per-spawn effort is therefore settable only through an agent definition's `effort` frontmatter, that is, through the type.

## Corpus observations (research box, aggregate only)
- Roughly 350 subagent transcripts; about 80% typed `general-purpose`. Of about 270 distinct general-purpose/untyped spawns sampled, about 92% set no explicit model.
- Keyword separability is poor: about 87% of prompts contain a read-only phrase and about 95% contain write verbs; only about 3% are read-only with no write verb. Prompts are long briefs that mention both editing and not editing, so surface keywords do not partition the work.

## Options evaluated
| # | Option | Silent-downgrade risk | Build cost |
|---|---|---|---|
| A | Tiered custom agent types (e.g. `gp-lite` haiku/low, `gp` sonnet/medium, `gp-hard` opus/high) with frontmatter `model` + `effort`; parent picks the tier | Low-medium (parent may default to the middle tier; choice is on the ledger) | About 0 code: markdown files plus one instruction paragraph |
| B | Jev advisor on the residue only; actuate via `updatedInput.model`; effort actuatable only by also rewriting `subagent_type` to a tiered type from A | Medium, bounded by the asymmetric guard plus fail-to-frontier plus breaker | Medium: HTTP call in the hook; latency budget must rise from 250 ms or go async |
| C | Deny with feedback ("set `model` explicitly and retry") | Low | Small, but one extra parent turn per spawn, more than the 337-token gate the repo already rejected |
| D | Deterministic keyword rules on prompt text | High (misreads "do not edit ... then write the fix") | Small; corpus shows features co-occur |
| E | Cascade / escalate on failure | Low per task, but RESTART makes every escalation pay twice | Medium; needs a check runner |
| F | `CLAUDE_CODE_SUBAGENT_MODEL[_FORCE]` or a settings `model` | High if set low; a constant, not a router | 0 |

## Verdict
1. A first. It is the only supported per-spawn effort lever, it makes the type informative so the v0.1 table can route it, and it costs no inference.
2. B second, as W4 specifies, gated on A's types existing. Call Jev only on the residue with no explicit model; add an effort `score` question; keep `model` out of the state; run a constant-control arm alongside; do not arm until it beats v0.1 plus the constant on Class 2 and on live rework rate.
3. Not recommended: D (evidence above), C as a default, E as a general mechanism, F.

## Assumptions and open items
- Rewriting `subagent_type` to a custom type through `updatedInput` is documented as whole-object replacement but was untested; behavioural equivalence to `general-purpose` is an assumption. This is what the C0 spike (`spike-c0/`) tests.
- An agent file's body replaces the default system prompt, so a tier type is not a clone of `general-purpose`'s prompt (from the sub-agents doc).
- Open decisions for the owner: include the frontier-plus tier in the choice set (JEV-28 unresolved); accept a higher actuator latency budget or an async advisor; allow the hook to rewrite `subagent_type`; which repo to arm first.
