# Using the subscription instead of an API key

`claude -p` authenticates with whatever credentials Claude Code already holds,
so the baseline can run on a Pro/Max subscription with no `ANTHROPIC_API_KEY`.
This works, and it is implemented as the `cc_opus5` and `cc_haiku45` arms.

What follows is what it costs you in measurement terms, because it is not free.

## Measured, not assumed

One `pre_bash` question set (two boolean questions), Haiku 4.5, leanest
invocation we could construct — custom system prompt, empty settings, no MCP
servers, every tool disallowed, `--effort low`:

| | direct Messages API | `claude -p` on the subscription |
|---|---|---|
| input tokens | ~386 | **5,214** cache-creation + 10 |
| output tokens | ~25 | **1,374**, of which 997 thinking |
| turns | 1 | **2** (structured output goes through a tool round trip) |
| latency | well under 1s | **21.0s** wall, 16.7s API, 12.9s to first token |
| cost | $0.0005 | $0.0173 list-basis (billed to the subscription) |

Thirteen times the input tokens, fifty times the output, roughly twenty times
the latency. None of it is attributable to the model. It is Claude Code's system
prompt, its tool definitions, its thinking budget and its process spawn.

`--effort low` did not suppress thinking, and `--disallowed-tools` prevents tools
being *used*, not *defined* — the definitions are still in the preamble. `--bare`
would trim it further but explicitly refuses OAuth and requires an API key, so it
is not available on this path.

## What this means for the study

**These arms measure Claude Code as it actually ships, and that is worth
measuring.** "Could I gate my hooks with the subscription I already pay for?"
is a real question with a real answer, and the answer this produces is a strong
one: at 21 seconds per decision, a headless Claude Code call **cannot be a hook
gate at any latency budget.** That is a finding, and it is published as one.

**They cannot be the headline baseline.** The headline claim is Jev against
Opus 5 *as a classifier*. Routing that through the CLI would compare Jev to a
5K-token preamble and a process spawn, which flatters Jev enormously for reasons
having nothing to do with Jev. It is the same strawman the design review
rejected, pointing the other way — and a reader who spots it discards the whole
paper.

So the arms are named `cc_*`, carry `role: deployment_realism`, and are reported
in their own section.

## Practical limits

Serial, at ~21s per call, both `cc_*` arms:

| workload | calls | wall clock |
|---|---|---|
| synthetic stress set (360 items) | 720 | ~4.2 hours |
| one week of live `pre_bash` (~200) | 400 | ~2.3 hours |
| determinism sweep, 20x on 50 states | 2,000 | ~11.7 hours |

Two things follow. Subscription rate limits will bind long before the statistics
do, so the `cc_*` arms should run on a **subsample** — a hundred or so stratified
items is plenty to establish "21 seconds, therefore not deployable" — while the
metered arms carry the full set. And a published benchmark driving thousands of
automated subscription calls is worth a glance at your plan's terms first; the
consumer subscription is sold for interactive use, and this is not that.

## Recursion guard

These arms spawn a real Claude Code session. With this project's hooks
registered, that session would fire them and capture its own decisions back into
the dataset. The worker exports `JEV_ARM_SUBPROCESS=1` to every arm subprocess
and `capture.sh` exits on sight of it, on line one. Environment variables are
inherited, so the guard holds however deep the spawn goes. Covered by a test.
