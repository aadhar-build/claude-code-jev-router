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
| **3,674×** | leverage of one routing decision, **per turn**: $0.0520 saved on a representative turn downgraded Opus→Haiku, against a $0.000014 Jev call. One decision covers a whole delegated task (median 38 requests), so the per-delegation figure is larger — by an amount nobody has measured. This is why the project is worth doing |
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

> `.env.example` was **missing** until 2026-09-21 — this instruction had been
> pointing at a file that did not exist. It is written now, credentials-free.
> Note that `.gitignore`'s `.env.*` rule matches it, so it needs an
> `!.env.example` negation to survive a commit; the file says so in its own
> footer.

## Installing it in another repo

`jev` is **opt-in per project**. Nothing is ever written to
`~/.claude/settings.json`; hooks are registered in the target repo's own
`.claude/settings.local.json`.

```sh
./jev status                     # what is installed here, and the state of all three switches
./jev install   <repo> --dry-run # print exactly what would change; change nothing
./jev install   <repo> --yes     # register jev's hooks in <repo>
./jev uninstall <repo> --yes     # remove them and restore <repo>'s settings file
```

`install` takes a verbatim backup before it touches anything. `uninstall` works
in **tiers and says which one it achieved**: tier A restores the install-time
bytes and verifies the sha256; tier B (the file changed after install) edits our
entries out and verifies the result three ways against the file re-read from
disk. Tier B is weaker — your original formatting is not restored — and it
prints that every time. `docs/REVERSIBILITY.md` has the detail.

**`JEV_HOME` is where jev itself lives**, resolved by the `jev` wrapper from its
own location, never from `$CLAUDE_PROJECT_DIR`. Every jev asset hangs off it:
`config/`, the spool, the logs, and the global kill switch. A relative
`JEV_HOME` is **rejected**, not normalised — because in the wrong install shape
the kill switch names a file that cannot exist, and a switch that is
permanently off is worse than no switch.

## Stopping it

There are **three** switches, not one. Each is a file; `touch` sets it, `rm`
clears it. Every hook tests all three on its first lines.

| switch | path | stops |
|---|---|---|
| **global** | `$JEV_HOME/.jev-disabled` | jev, **everywhere at once** |
| **machine-wide** | `~/.claude/jev-disabled` | the same, and honoured even if the install itself is unreachable. Read-only to us — nothing here ever writes it |
| **per-project opt-out** | `<repo>/.jev-disabled` | jev **in that one repo only** |

```sh
touch .jev-disabled     # in jev's own repo this is both the global and the local switch
rm .jev-disabled        # resume

./teardown.sh --dry-run # the full way back: see what it would change
./teardown.sh --yes     # set the switch AND unregister the hooks
```

> **This section used to document one switch.** The machine-wide switch was the
> one `jev install` *prints* — and W5 found it stopped nothing: the block was
> only in one of three hook scripts, so `touch ~/.claude/jev-disabled` did not
> stop `hooks/capture.sh` or `hooks/inline_shadow_bash.sh`. The canonical block
> is now in **every** hook and a test asserts it byte-identical across all of
> them, with a positive assertion that the sandbox *does* capture when the
> switch is absent.

A session that is already running honours a switch at its very next hook
invocation — verified live, not assumed, because the switch is a file test made
by the hook script rather than hook configuration. A hook already in flight
finishes. The test is `-e` **or** `-L`, not `-f`, so a dangling symlink or a
directory still counts as "set" — a switch that fails to stop the tool because
of what *kind* of file it is would be indistinguishable from no switch.

**A switch stops the hook DECIDING. It does not make jev quiescent** — the hook
still runs and still exits 0; it just does not capture or route. `teardown.sh`
reaches quiescence for **jev's own repo only**; it does not walk foreign
installs. Each of those is removed with `jev uninstall <that repo>`.

It stops *these* hooks because *these scripts* test the switches; the
harness-native equivalent is `"disableAllHooks": true`.

`uv run src/doctor.py` prints the whole reversibility state in one block.
`docs/REVERSIBILITY.md` has the detail, including how "OFF equals vanilla" is
proved rather than asserted — which is what JEV-35 is gated on.

## Two hard constraints

**Isolation.** Only Claude Code sessions in a folder you have explicitly run
`jev install` on are affected. Hooks are registered in that repo's
`.claude/settings.local.json`, which is project-scoped *and* gitignored — so it
does not travel to cloud sessions and does not ship live hooks to anyone who
clones the repo. **Nothing is ever written to `~/.claude/settings.json`.** A
global install would break the kill switch outright: every hook derives its
project root from `$CLAUDE_PROJECT_DIR`, so installed globally `.jev-disabled`
names a file that does not exist in whatever repo you happen to be in. That is
the finding behind opt-in-per-project, and behind anchoring the *global* switch
on `$JEV_HOME` instead.

**Self-containment.** Every artifact jev creates lives under `$JEV_HOME`: code,
hooks, spool, credentials, data, logs, reports. Nothing goes to `~/.config`,
`~/.claude`, `/tmp`, or launchd. Two paths outside it, both narrow: the
**read-only** `~/.claude/projects/*.jsonl`, where Claude Code keeps its own
transcripts; and, in a repo you installed into, that repo's own
`.claude/settings.local.json` plus its `.jev-disabled` — which is precisely what
`jev uninstall <repo>` removes and verifies. Deleting `$JEV_HOME` and running
`jev uninstall` on each installed repo reverts the machine completely.

## Claim discipline

> **Rewritten 2026-09-21. The previous version of this section was pre-pivot and
> is quoted here because the reversal is the point.** It read: *"Phase 1 measures
> agreement between arms, not accuracy. Opus 5 is a pseudo-label, not truth. The
> word 'accuracy' is banned from Phase 1 output; ground-truth labels and real
> calibration metrics arrive in Phase 2, from a human-labelled gold set."*
> That ban was correct for a study whose deliverable was an agreement statistic
> against a pseudo-label. It is wrong for this product, which ships
> `src/accuracy_gate.py` — and a repo that bans a word from its output while
> shipping a module named after it is telling a reader two different things.

The ban is lifted, and replaced by a narrower rule that does the work the ban
was doing.

**What "accuracy" now means here, and it is not the old meaning.** The accuracy
gate asks **did the routed subagent do the work correctly** — per-task
pass/fail, against labels in `data/labels/`, blinded by construction. That is a
*task outcome*, not agreement with another model's answer. Opus 5 is no longer a
reference label for anything; the `cc_*` comparison set is retired.

**The rules that survive, because they are what the ban was protecting:**

- **Never call agreement "accuracy".** Agreement between two arms on a question
  is agreement. It was never truth and is not truth now.
- **A gate that cannot run says so, and exits non-zero.** It does not report a
  pass. Today the gate exits **1 — "could not run"** because `data/labels/` is
  empty; that is the honest state and it blocks arming.
- **The gate states its own power.** It *fails to detect* a regression at a
  stated rate, and prints that rate in its own output. See "What we do not
  claim" above.
- **A firing rate is meaningless without the τ it was measured at**, because it
  *is* a function of τ. Quote both, always, in the same breath.
