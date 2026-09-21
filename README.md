# `jev` — a per-project Claude Code accelerator

**Goal:** lower realised cost per delegated task, at equal task success, with no
added felt latency. Assembled from existing open-source work rather than written
from scratch.

[Jev](https://docs.typesafe.ai/api) is TypeSafe AI's non-generative "System One"
model: state plus typed questions in, calibrated probabilities out. It never
writes prose, so it cannot replace Claude as the coding model. What it can do is
sit at a decision point and choose — at $0.042/1M input tokens.

> **This repository pivoted on 2026-09-21.** It was built as a *measurement
> harness* to publish agreement statistics comparing Jev against Claude Code's
> decision layer. That goal is retired. The apparatus is not: it becomes the
> **regression gate** that proves an optimization did not make the agent worse.
> The old spec is preserved at `docs/SPEC-measurement-harness-ARCHIVED.md`, and
> `FINDINGS.md` remains the record of what was measured.

## What is actually being built

A `PreToolUse` hook on the `Agent` tool that chooses the model tier for a
delegated task before it spawns, opt-in per project, reversible in one command.

**The first shippable thing contains no Jev at all** — a static
`subagent_type → tier` map, zero classifier calls, zero added latency. Five
independent sources find classifier routers frequently fail to beat exactly that
trivial baseline, while published static heuristics already deliver 46% and 28%
savings. Jev enters as increment two, aimed at the majority of delegated tasks typed
`general-purpose` where the static rule has no signal, and **it ships only if it
beats the static rule on realised cost at equal task success.**

## Three numbers that bound the whole project

| | |
|---|---|
| **3,674×** | leverage of one routing decision: a delegation moved Opus→Haiku saves $0.0520 against a $0.000014 Jev call. This is why the project is worth doing |
| **~24%** | of the bill is addressable — delegated work. Per-turn routing is impossible; only `Agent` calls can be routed. *(Corrected 2026-09-21: the frozen baseline's rate of 0.162 understated delegated spend by 45%; the rule-corrected figure is **0.238**. See `data/baseline/delegation-pre-rule-v1-corrected.json`.)* |
| **+337 tokens, +557ms** | what a synchronous Jev call in a hook *costs*, per call, measured here. Any per-tool-call optimization must remove far more than it adds |

## What we do not claim

Not that Jev is accurate — we never establish ground truth. Not that quality is
preserved — the gate *fails to detect* a regression at a stated power, and says
so in its own output. Token *count* may go up even as cost goes down, because a
subagent starts with empty context and trades cheap cache-reads for expensive
cache-writes.

## Reading order

| File | What it is |
|---|---|
| `SPEC.md` | **Start here.** The reworked spec: goal, non-negotiables, the harvest ledger, the guard |
| `ISSUES.md` | The tracker. Every ticket carries a `PIVOT TRIAGE` verdict; the workstream table is at the top |
| `FINDINGS.md` | What was actually measured. Still authoritative, still the source of the three numbers above |
| `docs/SPEC-measurement-harness-ARCHIVED.md` | The retired spec — a question that was answered, not a document that was wrong |
| `PREREGISTRATION.md` | **No longer a live commitment.** Retained as a record; its Amendments 5–8 contain measured facts the cost pipeline still depends on |

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
touch .jev-disabled     # kill switch: every hook exits on line one
rm .jev-disabled        # resume

./teardown.sh --dry-run # the full way back: see what it would change
./teardown.sh --yes     # set the switch AND unregister the hooks
```

A session that is already running honours the switch at its very next hook
invocation — verified live, not assumed, because the switch is a file test made
by the hook script rather than hook configuration. A hook already in flight
finishes. It stops *these* hooks because *these scripts* test it; the
harness-native equivalent is `"disableAllHooks": true`.

`uv run src/doctor.py` prints the whole reversibility state in one block.
`docs/REVERSIBILITY.md` has the detail, including how "OFF equals vanilla" is
proved rather than asserted — which is what JEV-35 is gated on.

## Claim discipline

Phase 1 measures **agreement between arms**, not accuracy. Opus 5 is a
pseudo-label, not truth. The word "accuracy" is banned from Phase 1 output;
ground-truth labels and real calibration metrics arrive in Phase 2, from a
human-labelled gold set.
