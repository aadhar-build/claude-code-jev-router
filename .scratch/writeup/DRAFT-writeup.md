# A router with no model in it

*First draft. Audience: product managers. Every number below is cited to the
file in this repository that measured it.*

---

## Three uncomfortable parts, first

One. The first thing this project shipped contains no AI. It is a lookup table
with three rows.

Two. The obvious way to make an AI coding agent cheaper is to put a small model
in front of its decisions and have it approve or veto each one. That was
measured here, and it goes the wrong way. A check in front of every tool call
adds **337 tokens and 557 ms** to each call and removes nothing (`FINDINGS.md`
Part 4c). Across one real session of 179 shell commands that is 60,323 extra
tokens and about 100 seconds the human sits through.

Three, and this one must not be softened: **nothing has been measured in
production. Not one saving.** The router was built and tested, and at the time
of writing it was being switched on for the first time. There is no
before/after number yet, and a write-up claiming one would be false.

That third point is why the rest is worth reading. The useful output of this
project is not a savings figure. It is a log of seven occasions where the
project caught itself believing something untrue, five of them in its own
code.

---

## What was built, in one paragraph

Claude Code, the coding agent, often *delegates*. Instead of doing a piece of
work in the main conversation, it spawns a *subagent*: a separate, short-lived
agent with its own empty memory that goes off and does one job (search this
codebase, draft a plan) and reports back a summary. Each delegation names a
type, such as `Explore`, `Plan` or `general-purpose`.

A *hook* is a small script the agent runs at a fixed moment, like a pre-commit
hook in git. This project's entire product is one hook. It runs just before a
delegation is created and rewrites which model that subagent will use.
Read-only searching goes to the cheap model. Planning goes to the middle one.
Anything the table has no rule for is left exactly as it was. It is opt-in per
repository, writes into one project-scoped settings file, and comes out again
in one command.

That is the whole of version 0.1. Three rules in a JSON file.

```
  YOU
   │
   ▼
  main session ─────────────▶ reply to you
   │
   │  "go search the repo for X"
   ▼
  ┌─────────────────────────┐
  │  HOOK: pick the model   │◀── 3-row table
  └─────────────────────────┘
   │
   ▼
  subagent runs in background
   │
   └──▶ summary returns to main session
```

*The tool is one script in the gap between "delegate this" and "start the
helper". It picks which model the helper uses, then gets out of the way.*

---

## Why three rules and not a classifier

This started as a research question: can a cheap, non-generative model stand in
for the agent's own judgement? The measurements came back and reshaped the
project twice.

First, checking every tool call loses by construction. `FINDINGS.md` says it
flatly: a synchronous check in front of every tool call "cannot make Claude
Code faster or more token-efficient, by construction." It adds the numbers
above and subtracts nothing, because the question it asks is *may this
proceed?*, and "yes" is not a saving. (A *token* is the unit models are billed
and rate-limited in, roughly three-quarters of a word.)

The place the arithmetic inverts is delegation. One decision, taken once,
governs an entire subagent task, a median of 38 model requests (`SPEC.md`
section 10). On a representative turn, moving work from the frontier model to
the cheap one saves **$0.0520**, against **$0.000014** to make the decision:
3,674x leverage on one decision (`FINDINGS.md` Part 4c). The leverage over a
whole delegation is larger, and the repo explicitly forbids multiplying the two
figures together, because nobody has counted how many of those 38 turns would
actually have been downgraded.

One caveat the repo insists on: routing cuts cost, not tokens. A subagent
starts with empty memory, so it pays for fresh *cache writes* (storing context
the model can cheaply re-read later) instead of the cheap *cache reads* the
main conversation was already enjoying. Token count can go up while the bill
goes down (`SPEC.md` section 1, and "What we do not claim" in `README.md`).

```
PER TOOL CALL  -- rejected
   call ─▶[check]─▶ run
            ▲          +337 tokens
            │          +557 ms
      every single time, and it
      removes nothing

PER DELEGATION -- shipped
   spawn ─▶[pick tier]─▶ 38 requests
             once          run at the
                           chosen price
   decision cost $0.000014
   saved per downgraded turn $0.0520
```

*Checking every tool call adds cost and removes none. Choosing a model once per
delegated task spreads one cheap decision over a median of 38 requests.*

Second, the goal later changed to speed and avoiding rework, and routing cannot
deliver speed either. Measured on this project's own session corpus: median
delegated-task duration **794.6 s** against median *blocking* duration
**1.5 s**. The repo puts that at a 530x gap, while noting the two medians are
counted over different sets. Every delegation observed ran in the background,
so a subagent could be made twice as fast and nobody would feel it.

So routing is a cost lever and a rework lever. It is not a speed lever. The
repo's generated reports print that sentence themselves, so the claim cannot be
made by accident.

```
  how long a delegated task takes
  ████████████████████████ 794.6 s

  how long you actually wait
  ▏ 1.5 s

  the work runs in the background,
  so making it faster changes
  nothing you can feel
```

*The median delegated task runs for 794.6 seconds. The median time a human is
blocked on it is 1.5 seconds.*

Third, the literature says the clever version usually loses to the dumb one.
Five independent sources, four papers and one vendor's own write-up, find that
learned routers frequently fail to beat a trivial baseline
(`README-public.md`). RouteLLM describes routers performing "at the level of
the random router." So the trivial baseline is what ships, and it becomes the
thing any classifier has to beat before it is allowed in.

```
  [3] classifier
      ships only if it beats [1]
       ▲
  [2] measure on real traffic
      (this is where we are now,
       with nothing measured yet)
       ▲
  [1] static table -- SHIPPED
       ▲
  [0] do nothing -- the control
      every layer is measured against
```

*The trivial rule ships first and becomes the bar the clever version has to
clear.*

---

## How big is this, honestly

Small, and saying so is the point.

Delegated work is about 24% of spend (`SPEC.md` section 11). Everything the
main conversation does itself cannot be routed at all. Within that 24%, most
delegations are typed `general-purpose`, which the static table deliberately
leaves alone. The repo puts the rule's reach at "somewhere between a fifth and
a third" of delegated tasks and refuses a point estimate, because three sources
in the repo disagree about the corpus size by a factor of 17 (`SPEC.md` section
10).

Multiply it out, assuming those tasks cost roughly what the others do (24% is
a share of spend, the fifth-to-a-third is a share of tasks, so the two
denominators are not the same): **roughly 5-8% of the bill is what version 0.1
can touch.** That is the ceiling, before any question of whether the cheap
model does the work as well.

```
  whole bill    ████████████████████ 100%
  delegated     █████ ~24%
  v0.1 reaches  █ ~5-8%
  measured      (nothing yet)
```

*Routing can only touch delegated work, and version 0.1's rules cover part of
that.*

---

## The failure log, which is the actual product

1. **A popular tool whose model was contributing nothing.** The plan was to
adopt an open-source context-compaction tool: 5,405 GitHub stars, MIT licence,
clean TypeScript, 29 of 29 tests passing. It asks a small model two questions
per tool call to decide what to drop, and achieves 87.7% context reduction. A
fake asker that answers 0 to every question achieves 88.5% on the same 256
calls (`SPEC.md` sections 3 and 5). The model did no better than a constant.
The output looked like judgement, so nobody noticed for a month.

2. **The same tool led a model to fabricate.** Its "drop the call" path removes
the record of a tool being used but keeps the agent's own narration of it. So
"I created the issue / I opened the PR" survives with the evidence deleted: a
worked example, sitting inside the model's own context, of claiming outcomes
without acting. A live session then produced nine consecutive turns reporting
completed work with zero tool calls, all fabricated (`SPEC.md` section 5).

3. **An off-switch that stopped one writer of two.** Engaging the kill switch
stopped the recording hook. The background worker never checked it and kept
draining its queue and calling paid APIs, while the status command printed
`capture: DISABLED` (`ISSUES.md` JEV-51). "Disabled" meant "stops recording",
not "stops spending".

4. **Config that looked live and was inert.** Five configuration fields a
reader would take for live controls were read by nothing (`ISSUES.md` JEV-31b).
There is now a test asserting that every key in every config file is consumed
somewhere.

5. **The same pattern, arriving through the safety ceremony itself.** The
activation checklist said to set the router to shadow mode, meaning record the
decision without acting on it, and then remove the kill switch. There is no
shadow mode. The router never reads that config file at all, and a sandbox run
with the field still set to `off` rewrote the model anyway. Following the
checklist as written would have produced a fully armed, model-rewriting hook
running against real sessions while the config said it was only observing. The
sequence was stopped at that step rather than worked around
(`.scratch/pivot/jev52-activation.md`).

6. **A baseline wrong by 45%, in the flattering direction.** Two modules costed
the same transcripts under different rules: one kept the first copy of a
duplicated request, the other the completed copy. Cost per delegated task moved
from $1.58 to $2.88 once they were reconciled (`SPEC.md` section 11). In
product terms, a real 20% saving measured against the old anchor would have
been published as a 46% increase.

7. **The cheapest way to pass the quality gate was to measure less.** The gate
that blocks a change for hurting output quality scores each of its questions
separately, but its "can we evaluate this at all?" flag was one global yes/no.
A single question carrying one positive and one negative label flipped the
whole criterion from "could not run" to "pass", covering questions that had no
labels at all. Reproduced against the real 2,095-row corpus: two hand-written
labels on `needs_review`, and `destructive` (the safety-critical one, the whole
reason the scoring is per question) left entirely unlabelled. The gate printed
`exit 0 - CLEAN`.

Read that as an incentive and it is worse than a bug. The fastest route to a
green quality gate was to label less, so a team under deadline pressure would
have been rewarded for weakening the check meant to stop them shipping a
regression. Found by our own audit and fixed two ways, because one was not
enough: evaluability is now per question, and a question present in the data
but missing from the labels is named as a measurement gap instead of
disappearing; plus a floor of 30 labels per question, so two well-behaved
labels are not a measurement. The same exploit now exits 1 and names both gaps.
Two regression tests hold it there (`src/accuracy_gate.py`,
`tests/test_accuracy_gate.py:164` and `:187`).

The repo turned this into a standing rule: every silent path needs a positive
assertion that it did something, not merely that it did not error.

---

## What is still broken

The quality gate cannot pass today. Its labels directory is empty, so one of
its three criteria is not evaluable and it exits 1, "could not run", even on a
replay that agrees with itself perfectly (`ISSUES.md` JEV-58). A test pins that
behaviour, so nobody can "fix" it by adding a default, and since failure 7 the
gate names each unlabelled question rather than skipping it. Two-thirds of a
brake is not a brake.

The before/after report trusts a file. Its quality verdict is read from a JSON
document whose only required content is an integer `exit_code`
(`src/report.py:1327-1347`); the report does not re-run the gate itself. The
guard is thin but real: an absent or malformed verdict is refused and reads as
could-not-run, never as a pass (`tests/test_report.py:998`).

The router's own latency has never been measured live. Declared budget 250 ms,
measured about 25 ms mean over 20 invocations, in a test loop, never on a real
spawn.

The kill switches do not make it quiescent. They make it decide nothing and
write nothing, but a process is still created per delegation; it exits on line
one and leaves the input untouched. `uninstall` is what makes it quiescent, and
the status command says so rather than claiming the stronger thing.

---

## What happens when it cannot decide

There is a single path where the router escalates to the frontier model: a router error on
a task type it has a rule for, after the input has parsed. Quality is protected
on that path and cost is not, which is why a circuit breaker is mandatory.
After N consecutive failures the router stops rewriting entirely and makes the
condition visible, so a provider outage cannot quietly bill frontier rates for
hours.

Every other not-deciding path leaves the input untouched: no rule for this
type, the caller already chose a model, breaker open, missing dependency,
garbage input. The repo's own phrasing is the better sentence: we never
up-route on no information, because that is a cost decision made on no
evidence.

```
  Agent call arrives
    │
    ├ caller already set a model ─▶ leave alone
    ├ no rule for this type      ─▶ leave alone
    ├ breaker open               ─▶ leave alone
    ├ input unreadable           ─▶ leave alone
    │
    ├ rule exists, router errored ─▶ FRONTIER
    │                                (expensive,
    │                                 safe)
    └ rule exists, all fine       ─▶ mapped tier

  Off switch = decides nothing, writes
               nothing (still spawns)
  Uninstall   = gone
```

*Almost every way this can fail ends in "change nothing". One narrow path
escalates to the expensive model.*

---

## Should a PM care?

If you want a cost lever, this one reaches maybe 5-8% of spend and has produced
no measured saving yet. Set expectations there, or wait for version 0.2.

If you want a way to evaluate AI features, that is the part worth taking away.
Four of the seven failures above share one shape: something that looked like
it was working and was doing nothing at all. A compaction model answering
questions that turned out not to matter. A config field with no reader. A
disabled switch next to a process still spending money. A quality gate that
went green on two hand-written labels. None of them produce an error. All of
them produce output that looks exactly like success.

The defence this project settled on costs very little and works anywhere:
before you ship the clever version, measure the stupid version, in the same
table, in the same units. If the model does not beat the constant, you did not
need the model. And check which way your gates point: if measuring less makes
the light go green, the light is not telling you anything.

---

## Sources

| Claim | Where |
|---|---|
| +337 tokens / +557 ms per gated call; 179 Bash calls | `FINDINGS.md` Part 4c |
| $0.0520 saved per downgraded turn vs $0.000014 to decide | `FINDINGS.md` Part 4c |
| 794.6 s task vs 1.5 s blocking (530x) | `SPEC.md` section 2, W3 |
| median 38 requests per delegated task | `SPEC.md` section 10 |
| 24% of spend delegated; $1.58 to $2.88 anchor | `SPEC.md` section 11 |
| static rule reaches a fifth to a third; corpus disputed 17x | `SPEC.md` section 10 |
| 87.7% vs 88.5% constant asker; nine fabricated turns | `SPEC.md` sections 3, 5 |
| five independent sources on router baselines | `README-public.md` |
| kill switch stopped one writer of two | `ISSUES.md` JEV-51 |
| five inert config fields | `ISSUES.md` JEV-31b |
| no shadow mode; activation stopped at step 7 | `.scratch/pivot/jev52-activation.md` |
| labels empty, gate exits 1 | `ISSUES.md` JEV-58 |
| two fabricated labels passed the whole AUC criterion | `src/accuracy_gate.py`, `tests/test_accuracy_gate.py:164`, `:187` |
| verdict file needs only an integer exit_code | `src/report.py`, `tests/test_report.py` |
| fail-to-frontier is one branch, not the default | `.scratch/pivot/release-plan.md` section 2 |
