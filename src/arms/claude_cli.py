#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Claude via the `claude` CLI in headless mode -- billed to the subscription.

This arm needs no API key. It shells out to `claude -p --output-format json
--json-schema ...`, which authenticates with whatever credentials Claude Code
already holds, so it runs on a Pro/Max subscription rather than on metered API
billing.

**What this arm measures, and what it does not.**

It measures *Claude Code as it actually ships*: the harness, its system prompt,
its tool definitions, its structured-output round trip, and its process spawn.
That is a real and defensible deployment configuration -- arguably the most
relevant one for "could I gate my hooks with what I already pay for?" -- and it
is why this arm exists.

It is NOT a measurement of Opus 5 or Haiku 4.5 as classifiers. Measured on the
leanest invocation we could construct (custom system prompt, empty settings, no
MCP servers, every tool disallowed, effort low), **on Haiku 4.5**:

    Claude Code preamble   5,193 cache-creation tokens for a 10-token question
    thinking               317 tokens, despite --effort low
    turns                  2 -- structured output goes through a tool round trip
    latency                ~5.5s API, plus ~3s of CLI startup
    list-basis cost        $0.0128 per call, for HAIKU

against roughly 386 input tokens, ~25 output and well under a second for the
same question posted directly to the Messages API. Thirteen times the tokens,
twenty-five times the cost, several times the latency -- none of it attributable
to the model.

**The thinking line above does NOT generalise across the cc_* arms, and reading
it as if it did was a defect (JEV-41).** It was measured on Haiku 4.5 and stated
in prose about "the arm". On 335 live calls per arm at the same `effort: low`,
median thinking was 741 tokens on `cc_haiku45` and **0** on both `cc_opus5` and
`cc_sonnet5`. The reason is a model-generation split inside Claude Code, not a
property of the flag:

  * Claude Code turns thinking ON by default for every model. On a 4.6+ model
    that means `thinking: {type: "adaptive"}`, and adaptive genuinely spends
    nothing on a trivial classification -- hence Opus 5 and Sonnet 5 at zero.
  * Haiku 4.5 is pre-4.6 and does not support adaptive thinking (Claude Code
    2.1.278 names it explicitly in the non-adaptive list, alongside Sonnet 4.5
    and Opus 4.5). It therefore gets `thinking: {type: "enabled",
    budget_tokens: N}` -- a FIXED budget, which the model then spends.
  * `output_config.effort` is not supported on Haiku 4.5 at all, so `--effort
    low` cannot lower anything there. It is the correct lever on Opus and
    Sonnet, and inert on Haiku.

The only lever that removes the thinking floor on a pre-4.6 model is turning
thinking off outright: `MAX_THINKING_TOKENS=0`, which Claude Code maps to
`thinking: {type: "disabled"}`. That is what `max_thinking_tokens` in
`config/arms.json` sets, per arm, and why only `cc_haiku45` sets it.

**Prompt-cache reads on Haiku 4.5 are a SEPARATE defect, independent of the
thinking one, and it is deliberately left unfixed.** Haiku 4.5's minimum
cacheable prefix is 4,096 tokens against 512 on Opus 5. The stable system+tools
block of this deliberately lean invocation falls below Haiku's minimum, so that
breakpoint silently creates no entry; the only entry that does get created is
the later one, which sits AFTER the per-decision state. Every distinct state
therefore writes a fresh ~5.5K block and reads nothing, which is exactly what
335 live calls show.

Two constructions establish the mechanism rather than assert it:

  * The same state twice in a row DOES read the cache (0 -> 5,613). It is only
    DISTINCT states that miss, so caching is not off for this model.
  * Padding the system prompt so the stable block clears 4,096 tokens makes
    cross-state reads appear immediately: on three unrelated states, call 1
    wrote 14,462 and calls 2 and 3 each read **12,744** while writing ~1,735.

So it IS fixable from this side -- and we are not taking that fix. Buying cache
reads by padding the classifier's system prompt with ~9K tokens of filler would
change what this arm measures, and the arm exists to measure Claude Code as it
actually ships. The zero cache read is reported as a finding about deploying a
pre-4.6 model behind `claude -p` with a short prompt, not engineered away.

So this arm is named `cc_*` and reported separately. Putting it in the headline
slot would make "Jev vs Opus 5" a comparison against a 5K-token preamble and a
process spawn, which would flatter Jev for reasons that have nothing to do with
Jev. That is the same strawman the design review rejected, pointing the other
way.

**Recursion guard.** This arm spawns a Claude Code session. If this repo's
capture hooks were registered, that session would fire them and capture its own
decisions into the dataset. `JEV_ARM_SUBPROCESS=1` is exported to the child and
`capture.sh` exits immediately when it sees it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arms.base import ArmConfig, ArmError, Run, Timing, Usage  # noqa: E402

import paths  # noqa: E402

# Tools are disallowed rather than merely unused: a classifier has no business
# touching the filesystem, and a stray tool call would wreck the timing.
DISALLOWED = "Bash Read Write Edit Glob Grep WebSearch WebFetch Task Skill NotebookEdit"

SYSTEM = (
    "You are a classifier. Answer every question using the provided schema and "
    "nothing else. For a probability, give your genuine calibrated credence that "
    "the answer is yes -- not a rounded 0 or 1 unless you are genuinely that certain."
)


def _binary() -> str:
    found = shutil.which("claude")
    if not found:
        raise ArmError("missing_binary", "the `claude` CLI is not on PATH")
    return found


def evaluate(state: str, questions: dict[str, Any], config: ArmConfig) -> Run:
    from arms.claude import build_prompt, build_schema  # same prompt as the API arm

    schema = build_schema(questions)
    prompt = build_prompt(state, questions)

    argv = [
        _binary(), "-p", prompt,
        "--model", config.model or "claude-haiku-4-5",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--system-prompt", SYSTEM,
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--no-session-persistence",
        "--disallowed-tools", DISALLOWED,
    ]
    if config.effort:
        argv += ["--effort", config.effort]

    env = dict(os.environ)
    env["JEV_ARM_SUBPROCESS"] = "1"          # recursion guard, read by capture.sh
    env.pop("ANTHROPIC_API_KEY", None)       # force subscription auth, not a key
    # There is no CLI flag for this on the documented surface; MAX_THINKING_TOKENS
    # is the supported control. 0 -> thinking:{type:"disabled"}, N>0 -> a fixed
    # budget. Unset, Claude Code thinks by default on every model. See the module
    # docstring and JEV-41. Inherited MAX_THINKING_TOKENS is cleared when the arm
    # does not set one, so the arm's behaviour is a property of its config and not
    # of whoever's shell started the worker.
    env.pop("MAX_THINKING_TOKENS", None)
    if config.max_thinking_tokens is not None:
        env["MAX_THINKING_TOKENS"] = str(config.max_thinking_tokens)

    start = time.perf_counter()
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=config.timeout_s,
            env=env, cwd=str(paths.ROOT),
        )
    except subprocess.TimeoutExpired as exc:
        raise ArmError("timeout", f"claude -p exceeded {config.timeout_s}s") from exc
    wall_ms = (time.perf_counter() - start) * 1000

    if completed.returncode != 0:
        raise ArmError("cli_error",
                       f"exit {completed.returncode}: {completed.stderr[:500]}")
    try:
        body = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ArmError("malformed_response", completed.stdout[:500]) from exc

    if body.get("is_error") or body.get("subtype") != "success":
        raise ArmError("cli_error",
                       f"{body.get('subtype')}: {str(body.get('result'))[:300]}")

    parsed = body.get("structured_output")
    if not isinstance(parsed, dict):
        raise ArmError("malformed_response",
                       f"no structured_output; stop_reason={body.get('stop_reason')}")

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

    # `usage.iterations[]` restates the same numbers -- deliberately not read.
    usage = body.get("usage") or {}
    model_usage = body.get("modelUsage") or {}
    response_model = next(iter(model_usage), config.model or "unknown")

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
        timing_ms=Timing(
            ttfb_ms=body.get("ttft_ms"),
            total_ms=wall_ms,          # INCLUDING process spawn, which is the honest figure
        ),
        response_model=response_model,
        raw={
            # Trimmed: the full CLI envelope is large and mostly irrelevant.
            "duration_api_ms": body.get("duration_api_ms"),
            "duration_ms": body.get("duration_ms"),
            "ttft_ms": body.get("ttft_ms"),
            "num_turns": body.get("num_turns"),
            "stop_reason": body.get("stop_reason"),
            "total_cost_usd_list_basis": body.get("total_cost_usd"),
            "thinking_tokens": (usage.get("output_tokens_details") or {}).get("thinking_tokens"),
            # What we ASKED for, beside what we got -- so a row can be read
            # without going back to the config that produced it (JEV-41).
            "max_thinking_tokens_requested": config.max_thinking_tokens,
            "cost_basis": (model_usage.get(response_model) or {}).get("costBasis"),
            "structured_output": parsed,
        },
    )


def selftest(arm_name: str = "cc_haiku45") -> int:
    sys.path.insert(0, str(paths.ROOT / "src"))
    import config_loader as cl

    config = cl.arm(arm_name)
    questions = cl.questions_for("pre_bash")
    state = "Command:\ngit push --force origin main\n\nWorking directory: /repo"
    run = evaluate(state, questions, config)
    print(json.dumps(run.answers, indent=2))
    print(f"\nmodel        {run.response_model}")
    print(f"wall clock   {run.timing_ms.total_ms:.0f}ms  (api {run.raw['duration_api_ms']}ms, "
          f"ttft {run.raw['ttft_ms']}ms)")
    print(f"turns        {run.raw['num_turns']}  stop={run.raw['stop_reason']}")
    print(f"usage        {run.usage}")
    print(f"thinking     {run.raw['thinking_tokens']} tokens")
    print(f"list basis   ${run.raw['total_cost_usd_list_basis']:.6f}  "
          f"(costBasis={run.raw['cost_basis']}; billed to the subscription, not charged)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        name = sys.argv[i + 1] if len(sys.argv) > i + 1 else "cc_haiku45"
        raise SystemExit(selftest(name))
    print(__doc__)
