# Context

The glossary for this project. Terms first: the rule is **only as much
implementation as the term cannot be understood without** — a circuit breaker
that does not say what trips it is not defined. Rationale, sequencing and schema
still live elsewhere: decisions in `SPEC.md`, the board in `ISSUES.md`,
hard-to-reverse choices in `.scratch/adr/`.

> **Updated 2026-09-21 (W5 doc sweep).** This header used to point at
> `PREREGISTRATION.md` for "commitments". **That document is retired** — it is a
> record of what was believed and when, not a live obligation. There is no
> commitments file any more: the SPEC's non-negotiables are the standing
> constraints, and the waves in `ISSUES.md` are the plan.
>
> Several entries below described the **retired measurement experiment** and
> have been corrected rather than deleted. Where a term is dead, it is marked
> **RETIRED** and kept, because it still appears in `data/runs/` rows, in frozen
> reports and in the archived spec, and a reader who meets it there needs to
> know what it meant and that it is over.

---

## The two kinds of "arm" — one of them is RETIRED

The bare word **arm** is ambiguous in this project and should not be used
unqualified in prose. It carried two unrelated meanings at two different levels.

**classifier arm — RETIRED as a live concept, 2026-09-21.** One system being
compared as a classifier, on byte-identical state, in the shadow-mode
measurement harness. The set was `jev`, `cc_opus5`, `cc_sonnet5`, `cc_haiku45`,
`cc_fable51`. A classifier arm answered questions; it never changed what a
session did.

> **The `cc_*` comparison set is KILLed.** Agreement-against-Opus was the old
> deliverable and the pivot retired it: Opus 5 was only ever a *pseudo-label*,
> and the product does not need one. What survives of that work is **not the
> comparison** but two by-products the router still uses — a real Jev latency
> distribution, and the finding that **τ=0.5 has been wrong on every boolean
> question asked of Jev, three independent times**.
>
> The arms are still *defined* in `config/arms.json` and the 2,095 rows on disk
> are still real responses; they are now a corpus for the **Class 1** gate
> (below), not an experiment. `jev` itself is not retired — it is the classifier
> W4 will put in the loop.

**routing arm — RETIRED, 2026-09-21.** One randomised assignment given to a
delegated task in the routing A/B: `jev_routed` or `default`, plus a third arm
`random_matched` that was designed and never built.

> **The randomised A/B is retired.** Routing survives as an **optimization with
> a ship gate** (W1's static floor, then W4's Jev), not as a trial: there is no
> coin flip, no control arm, and no per-delegation randomisation. Read
> `jev_routed` / `default` in an old document as "routed" and "left alone".
> The thing a routing arm used to be is now an **assignment** on the
> **assignment ledger** (below), which is a record of what was decided, not of
> what a coin said.

*On disk:* the field `arm` on a `data/runs/` row always means **classifier
arm**. It is left unqualified because renaming it would orphan every row already
written. New fields use qualified names.

## Decisions and their records

**surface** — a point in a Claude Code session where a decision is made, and the
hook event that fires there. One surface has one state shape and one question
set. Five were defined; **three are KILLed** and two survive:

| surface | hook event | state today |
|---|---|---|
| `agent_route` | `PreToolUse` on `Agent` | **the product surface.** `mode: off` — built, not registered, not armed |
| `pre_bash` | `PreToolUse` on `Bash` | **the only one that has ever fired live.** `mode: shadow`. All 2,095 run rows are its rows. Kept as a corpus and as the latency measurement; *as a gate* it is refuted — a synchronous gate here costs +337 tokens and +557ms p50 per call and removes nothing |
| `stop` | `Stop` | **KILLed.** `mode: off` |
| `user_prompt` | `UserPromptSubmit` | **KILLed.** `mode: off` |
| `post_edit` | `PostToolUse` on `Edit\|Write\|NotebookEdit` | **KILLed** as a risk-scoring surface. The *hook point* is where W6's ingestion-time trim will live, which is a different job |

"The five-surface shadow matrix" was a deliverable of the retired study. It is
not a plan any more.

**decision point** — one occurrence of a surface firing. Identified by
`decision_id`.

> The definition used to end *"every classifier arm answers the same decision
> point on the same bytes"*, which presumed the multi-arm matrix. That property
> is a fact about the **rows already on disk** — and it is exactly why they are
> still useful as the Class 1 corpus — but it is no longer a thing the system
> does. Going forward a decision point has **one** answer: the tier the router
> chose.

**state** — the exact bytes a classifier arm is given for a decision point,
content-addressed by `state_sha256`. Built only from what existed at capture
time; never from the live transcript.

**capture** — the durable record that a decision point occurred. Written by the
worker, never by the hook.

**question set** — the questions put to a classifier arm for a surface, pinned
by version. Its canonical identity is **`<surface>/<version>`** — `pre_bash/v1`.
That exact string appears in three places and they must agree: the question
file declares it, `config/surfaces.json` selects the version half of it, and
every run row records it. The row's copy carries one addition, a
**`#<phrasing>`** suffix naming which of the 2–3 independently written
phrasings was actually used: `pre_bash/v1#a`. Nothing else is a valid form, and
the agreement between file and config is asserted at load time rather than
assumed.

**run** — one result: a `(decision_id, classifier arm, question set, attempt)`
tuple. Not a collection session, and not a subagent execution.

> **This is now a description of `data/runs/`, not of live behaviour.** The
> tuple has a `classifier arm` in it because it was minted for the multi-arm
> matrix. The word is still the right one for reading those rows; nothing new is
> a "run" in this sense. A delegated task's record today is a **ledger row**
> plus its outcome.

**run context** — how a run was produced, never pooled across values: `live`
(a real session), `replay` (a recorded state re-sent), `synthetic` (an item we
wrote), `canary` (a fixed state re-sent daily to detect vendor drift).

## Routing

*(This section was headed "The routing experiment". There is no experiment;
there is a product with a ship gate.)*

**delegated task** — one unit of work handed to a subagent. **The unit of
routing**, and the unit the cost anchor and the accuracy gate are both quoted
per. It used to be "the unit of randomisation" as well; nothing is randomised
any more. A turn is *not* a routable unit: no mechanism exists to change the
model for a single turn of a running session, which is why per-turn routing is
impossible and why only `Agent` calls are addressable.

**tier** — a model a delegated task can be assigned to. A tier is a position in
the routing choice set, not a synonym for a classifier arm, even where the two
name the same model. The choice set is `haiku45` / `sonnet5` / `opus5`, ranked,
with `opus5` as the **frontier tier**. What goes into `tool_input.model` is the
tier's **alias** (`haiku`/`sonnet`/`opus`), never a dated model ID — and what
comes back in `resolvedModel` is a full, sometimes dated ID, so verification is
a prefix match and never equality. **Asking for a model and getting it are
different events.**

**escalation** — a delegated task re-delegated to a higher tier, with
substantially the same objective, within the same session, **after** the first
attempt has run. Never inferred after the fact by matching prompts.

**uplift** — routing a task one tier higher **at decision time**, before it
runs, because the classifier is not confident enough to trust its own choice.
The mechanism named `escalate_on_low_confidence` in `questions/user_prompt/v2.json`
is an *uplift*, not an escalation: it costs nothing wasted, because nothing has
run yet. The two were sharing one word, and only escalation carries rework
cost — conflating them would put a free decision and an expensive failure in the
same statistic.

> **Operator decision 3, 2026-09-21: RESTART on escalation, do not continue.**
> *Added here because this distinction stopped being a naming nicety and became
> load-bearing for the product's primary criterion.*
>
> The higher tier starts from **the original task**, not from the first
> attempt's reasoning. So **an escalation pays for the work twice — in money,
> and in time**, because the second attempt is serial with the first. That is
> what makes uplift the cheap option and escalation the expensive one, and it is
> why **rework**, not cost, is criterion R1.
>
> The consequence for policy, which is the whole reason it is written down:
> **down-routing is the risky direction and must be gated harder than
> up-routing.** One wrong downgrade wipes out the saving from many correct ones,
> and wipes out the *time* saving completely. Up-routing is free in this
> asymmetry; cheapening requires margin.

**assignment** — the **tier** a delegated task was routed to, recorded on the
**assignment ledger** before the subagent spawns. Distinct from what actually
ran: an `availableModels` allowlist or `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` can
override the hook, so assignment and outcome can disagree — which is why the
ledger row and the `resolvedModel` check are two separate records and both are
kept.

> **Corrected 2026-09-21.** This read *"the routing arm a delegated task was
> allocated by the coin flip"*, and *"a failed classifier call falls open to the
> default"*. Both are now false. There is no coin flip, and the failure
> behaviour was **reversed by operator decision 2: fail to FRONTIER, not open.**
> A doc that still says "falls open" describes a design where a router outage
> quietly downgrades your work — the opposite of what ships.

**label** — an outcome derived from what happened *after* a decision point,
used to score an answer. The distinction from state is the project's sharpest
rule and is easy to get backwards: **future turns are forbidden as state and
permitted as labels.** An arm may never see the future it is asked to predict;
the analysis may read it to find out what actually happened.

**shadow** — observing and recording the decision that *would* have been made,
changing nothing.

> **Corrected 2026-09-21.** This entry used to end *"The `pre_bash` surface is
> shadow; `agent_route` is not."* Verified against `config/surfaces.json` today,
> that second clause is wrong, and wrong in the direction that matters — it
> reads as though the product surface were live.
>
> **What is actually true.** `agent_route` is `mode: "off"`, and the file's own
> comment calls it a *"SHADOW SURFACE, not registered and not armed"*.
> `mode: off` means **no hook entry exists in `.claude/settings.local.json` at
> all** — so it is not shadowing either; it is absent. `pre_bash` is
> `mode: "shadow"`, and is the only surface that has ever run.
>
> The old clause was reaching for a real distinction, so keep the distinction
> and drop the false tense: **`agent_route` is the one surface designed to
> ACT** — it rewrites `tool_input.model` on the way through, which is what makes
> it the product and what makes arming it a deliberate, gated act (W5). Every
> other surface can only ever observe.
>
> **`enforce` is not reachable from `config/surfaces.json`.** Switching a
> surface from shadow to acting requires registering a *different script*, by
> design, so a passive observer can never become a blocker by way of a typo in a
> config file. "Shadow" is therefore a property of which script is registered,
> not of a mode string.

---

## The product — terms added 2026-09-21

*These eleven were in daily use in the code, the config and the board, and in
none of them was defined here. A glossary that lags the thing it describes is
how two people end up meaning different things by "tier".*

### Where things live

**`JEV_HOME`** — **where jev itself lives.** An absolute directory, resolved by
the `jev` wrapper from its own location and **never from
`$CLAUDE_PROJECT_DIR`**. Everything that belongs to jev hangs off it:
`config/`, the spool, the logs, `data/`, and the global kill switch
`$JEV_HOME/.jev-disabled`. `paths.ROOT` **is** `JEV_HOME`; the bash hooks resolve
it with the same rule (`resolve_jev_home()`), which before W2 they did not.

Distinct from the **project dir**, which is whatever repo the session is in. The
distinction is not pedantry: the hooks used to derive their root from
`$CLAUDE_PROJECT_DIR`, so under a global install the kill switch named a file
that *could not exist* and the tool could not be stopped. A **relative**
`JEV_HOME` is rejected outright rather than normalised, for the same reason — a
switch that is cheap and false is worth less than no switch.

### Routing

**static floor** — W1: the routing rule with **no Jev call in it at all**. A
`PreToolUse` hook on `Agent` that applies the **tier map** and rewrites
`tool_input.model`. Zero classifier calls, zero network, zero added latency. It
is both the first shippable thing and **the baseline Jev must beat** — five
independent sources find learned routers frequently fail to beat exactly this.

**tier map** — `config/tiers.json`: an exact, case-sensitive
`subagent_type → tier` table. **The file is the rule**; the hook contains no tier
literal, so changing routing policy is editing config, not editing a script. The
map is a **declared policy choice, explicitly not data-derived** — the per-type
counts in this corpus are n=2 and n=3, which are anecdotes. It covers **between
an eighth and a third** of delegated work, and any saving claimed for it is
quoted against that denominator, never against total spend.

**frontier tier** — the tier the router sends a task to **when it cannot
decide**: `opus5`. Operator decision 2, 2026-09-21: **fail to FRONTIER, not
open.** Quality is protected on the error path and cost is not — which is
precisely why the circuit breaker is mandatory rather than nice to have. Note
`fable51` is deliberately *absent* from the choice set: a choice set is not
something to widen by accident.

**circuit breaker** — the bound on fail-to-frontier. After
`max_consecutive_failures` (3) router failures whose newest is inside `ttl_s`
(900), the hook **stops rewriting entirely**, leaves the input untouched, and
says so in a `systemMessage`. Without it a sustained outage silently bills
frontier rates for as long as it lasts. Its state is an **append-only outcome
log**, not a counter file — parallel `Agent` spawns are the normal case and a
read-modify-write counter loses increments under exactly those conditions.
Half-open falls out for free: past the TTL the newest failure is stale, one
attempt is allowed, and that attempt's own line decides.

**assignment ledger** — `data/agent_route/assignments/<date>.jsonl`. One row per
routing decision, written **before the spawn, never after** — a ledger written
afterwards is missing exactly when it matters most, which is when the task
crashed. Each row carries the decision, the tier, **the rule that fired
verbatim**, the fingerprint of the rule table, and the model the caller
originally asked for: the five things without which an outcome observed an hour
later cannot be attributed to anything.

**miss vs error** — a distinction the ledger and the breaker both depend on. A
`subagent_type` with **no rule in the map is a MISS**: expected, routine,
governed by `unmapped_action` (`leave` — emit no rewrite), and **a miss never
fails to frontier.** An **ERROR** is the router failing to do its job, and that
is what fails to frontier and what the breaker counts. Collapsing the two would
either bill frontier rates for the uninformative 65% majority, or hide real
outages inside a normal-looking rate.

### The guard

**Class 1 — judge-side regression.** Applies when a change alters **what our own
Jev gate sees** (state trimming, truncation, compaction upstream of a hook). The
unit is `(decision_id, question_name)`; the corpus is the 578 captures and
~2,095 rows **already on disk**, so it is fixed and free. Scored on band-flip
rate at each question's τ, AUC and κ. Cheap enough to be a pre-commit gate —
hundreds to a couple of thousand Jev calls, pennies.

**Class 2 — agent-side regression.** Applies when a change alters **what the
coding agent sees, or which model answers** (routing, compaction, trimming).
It needs **re-execution**, because replaying an old transcript measures the old
agent — the optimization changes what the agent *does*. Costs real money, so it
runs on a fixture suite rather than on everything.

**fixture suite** — the small, fixed set of mined real tasks Class 2 re-executes
against, with the repo state needed to run them. It exists because you **cannot**
replay real past sessions: reproducing one needs the repo state at session
start, which the transcript does not carry. Reaching for that is the
research-project trap; the fixture suite is the way around it.

**constant control** — non-negotiable 7: **every mechanism must beat a trivial
constant control, or it is not a mechanism.** The canonical case is
`fast-jev-compaction`, which reported 87.7% context reduction with Jev against
**88.5% with a constant-0 asker** on the same 256 tool calls — all the apparent
judgement was the harness. Every optimization ships with its constant control,
and the control is run, not imagined.

### Reversibility

**Tier A / Tier B teardown** — the two guarantees `jev uninstall` can offer, and
it **says which one it achieved**.

- **Tier A — byte-reversible.** The settings file has not changed since
  `jev install` ran, so the install-time bytes are **restored**, not edited, and
  the sha256 is verified.
- **Tier B — structurally verified.** The file changed after install, so our
  entries are **edited out** and the result is checked three ways against the
  file re-read from disk. **Weaker: your original formatting is not restored**,
  2-space JSON is. This is printed every time, and a verbatim backup is what
  makes it reversible anyway.

Tier B exists because `install` re-serialises the file the moment it merges into
it. An install immediately followed by an uninstall used to collide their
second-resolution backup names and silently downgrade A to B; the test suite
found that.

**INERT marker** — `data/agent_route/INERT`. The actuator's own admission that
it is **registered and routing nothing** — no `jq`, an unreadable tier map, or
another cause that leaves it unable to route *and* unable to record. It exists
because this repo's characteristic failure is the silent one: a hook that exits
0 having done nothing looks exactly like a hook with nothing to do. The marker
is the positive assertion that turns that into a visible state, and `doctor.py`
reports it with its cause and its age.

---

## The standing design rule these terms keep pointing at

**Every silent path needs a positive assertion that it did something, not merely
that it did not error.** Four instances are on the record: the inert config
fields, the kill switch that stopped one writer of two, the jq-comment
apostrophe that made a broken hook exit 0, and `project_dir()`'s slug bug, which
would have written a baseline of zeros that looks like a finished answer. The
INERT marker, the ledger's write-before-spawn, the breaker's outcome log and the
switch's `-e`-or-`-L` test are all the same rule applied.
