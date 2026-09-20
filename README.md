# Jev shadow-mode measurement harness

Does replacing Claude Code's *decision layer* with [Jev](https://vercel.com/docs/ai-gateway)
— TypeSafe AI's non-generative "System One" model — actually work? This folder
is the apparatus built to find out and publish the answer.

Jev takes state plus typed questions and returns calibrated probabilities. It
never writes text, so it cannot replace Claude as the coding model. What it can
do is sit inside a **hook** — which runs synchronously on every turn and has
therefore never been able to afford an LLM call — at $0.042/1M input tokens with
output free.

**Shadow mode: this harness observes and never blocks.** It records the decision
each arm *would* have made. No tool call is ever gated by it.

## Reading order

| File | What it is |
|---|---|
| `SPEC.md` | Problem, solution, user stories, implementation and testing decisions |
| `ISSUES.md` | The issue tracker — thirteen vertical slices with blocking edges |
| `docs/PLAN.md` | The full design, including the nine decisions that shaped it |
| `PREREGISTRATION.md` | Analysis commitments, committed before collection starts (ticket 7) |

## What is being compared

**Jev** against **Claude Code as it actually ships** — invoked headless on a
subscription via `claude -p`, no `ANTHROPIC_API_KEY` anywhere.

This is a deliberate choice and it bounds the claim. A `cc_*` arm bundles the
model with a ~5.2K-token preamble, its tool definitions, a structured-output
tool round trip and a process spawn. Measured on a real decision: **10 tokens of
actual state against 5,460 tokens of harness**, and 1.5s of process startup on
top of 4.6s of API time.

So the finding is about **the deployed system**, not about Opus 5 or Haiku 4.5 as
classifiers. A bare Messages API call answers the same question in roughly 386
tokens, in under a second. Every surface section of the report prints an
**attribution table** decomposing harness overhead from model work, because a
reader is entitled to know which one is producing the gap — and because without
it the cost and latency ratios flatter Jev for reasons that have nothing to do
with Jev.

The metered-API arms (`opus5`, `haiku45`) remain defined in `config/arms.json`
but disabled. Enabling them turns the headline back into a model-vs-model
comparison and requires an API key. See `FINDINGS.md Appendix C`.

## Getting started

```sh
cp .env.example .env && chmod 600 .env   # AI_GATEWAY_API_KEY only
uv run src/doctor.py                     # layout, credentials, isolation, self-containment
```

`doctor.py` exits non-zero if anything is wrong. Run it first. It treats a
missing `ANTHROPIC_API_KEY` as the expected state.

## Two hard constraints

**Isolation.** Only Claude Code sessions in this folder are affected. Hooks are
registered in `.claude/settings.local.json`, which is project-scoped *and*
gitignored — so it does not travel to cloud sessions and does not ship live
hooks to anyone who clones this repo. Nothing is ever written to
`~/.claude/settings.json`.

**Self-containment.** Every artifact lives under this folder: code, hooks, spool,
credentials, data, logs, reports. Nothing goes to `~/.config`, `~/.claude`,
`/tmp`, or launchd. The single path outside is read-only —
`~/.claude/projects/*.jsonl`, where Claude Code keeps its own transcripts.
Deleting this folder reverts the machine completely.

## Stopping it

```sh
touch .jev-disabled     # kill switch: every hook exits immediately
rm .jev-disabled        # resume
```

## Claim discipline

Phase 1 measures **agreement between arms**, not accuracy. Opus 5 is a
pseudo-label, not truth. The word "accuracy" is banned from Phase 1 output;
ground-truth labels and real calibration metrics arrive in Phase 2, from a
human-labelled gold set.
