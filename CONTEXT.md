# Context

The glossary for this project. Terms only — no implementation details, no
decisions, no schema. Decisions live in `SPEC.md`, commitments in
`PREREGISTRATION.md`, work in `ISSUES.md`, and hard-to-reverse choices in
`docs/adr/`.

---

## The two kinds of "arm"

The bare word **arm** is ambiguous in this project and should not be used
unqualified in prose. It carries two unrelated meanings at two different levels,
and the collision is sharp enough that `config/arms.json` gives the `jev` entry
`role: "treatment"` while the routing experiment has a *different* treatment
entirely.

**classifier arm** — one system being compared as a classifier, on
byte-identical state, in the shadow-mode measurement harness. The set is `jev`,
`cc_opus5`, `cc_sonnet5`, `cc_haiku45`, `cc_fable51`. A classifier arm answers
questions; it never changes what a session does.

**routing arm** — one randomised assignment given to a delegated task in the
routing A/B: `jev_routed` or `default`. A routing arm determines which model
actually runs the task, and therefore changes session behaviour.

*On disk:* the field `arm` on a `data/runs/` row always means **classifier
arm**. It is left unqualified because the analysis code is frozen at the
pre-registration commit and renaming it would break that claim for cosmetic
gain. New fields use the qualified names.

## Decisions and their records

**surface** — a point in a Claude Code session where a decision is made, and the
hook event that fires there. One surface has one state shape and one question
set. The five: `pre_bash`, `stop`, `user_prompt`, `post_edit`, `agent_route`.

**decision point** — one occurrence of a surface firing. Identified by
`decision_id`. Every classifier arm answers the same decision point on the same
bytes.

**state** — the exact bytes a classifier arm is given for a decision point,
content-addressed by `state_sha256`. Built only from what existed at capture
time; never from the live transcript.

**capture** — the durable record that a decision point occurred. Written by the
worker, never by the hook.

**run** — one result: a `(decision_id, classifier arm, question set, attempt)`
tuple. Not a collection session, and not a subagent execution.

**run context** — how a run was produced, never pooled across values: `live`
(a real session), `replay` (a recorded state re-sent), `synthetic` (an item we
wrote), `canary` (a fixed state re-sent daily to detect vendor drift).

## The routing experiment

**delegated task** — one unit of work handed to a subagent. The unit of routing,
and the unit of randomisation. A turn is *not* a routable unit: no mechanism
exists to change the model for a single turn of a running session.

**tier** — a model a delegated task can be assigned to. A tier is a position in
the routing choice set, not a synonym for a classifier arm, even where the two
name the same model.

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

**assignment** — the routing arm a delegated task was allocated by the coin
flip, recorded before the subagent spawns. Distinct from what actually ran: a
failed classifier call falls open to the default, so assignment and outcome can
disagree, and the primary analysis follows the assignment.

**shadow** — observing and recording the decision that *would* have been made,
changing nothing. The `pre_bash` surface is shadow; `agent_route` is not.
