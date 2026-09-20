# 1. The routing A/B's control arm is the default, not a static rule

Date: 2026-09-20

## Status

Accepted.

## Context

The routing A/B compares Jev-chosen model tiers against some baseline. Two
baselines were available.

**The current default.** Claude Code resolves a subagent's model to `inherit`,
so the default runs Opus on every delegated task. This is what an ordinary user
actually gets, because it is what happens when nobody configures anything.

**A static rule.** Two lines mapping `subagent_type` to a tier — `Explore` to
haiku, `Plan` to opus, `general-purpose` to sonnet — capturing much of the
available saving with no classifier involved at all.

These test different claims. Against the default, the question is *does routing
help?* Against the static rule, the question is *does the classifier help?* —
and the second is the harder question, because a classifier that merely
reproduces a two-line rule has earned nothing.

There is not enough of a collection window to run both as randomised arms. A
three-arm design at the achievable sample size resolves neither comparison.

## Decision

**The control arm is the current default.**

The reasoning is external validity: Opus-on-everything is the realistic
counterfactual, so a result measured against it is a result about what a reader
would actually experience, rather than about a rule invented for the paper.

## Consequences

**The study cannot separate "routing helps" from "Jev helps" by
randomisation.** This is a real limit and is not recoverable after the fact. A
reader who suspects the classifier is doing no work is entitled to that
suspicion, and this design cannot refute it.

**The registered mitigation is offline and costs nothing.** Every delegated task
records both Jev's assignment and the task's `subagent_type`, so the assignment
a static rule *would* have made is computable for every task without running it.
Two figures go in the writeup: how often Jev agrees with the static rule, and —
where they disagree — the distribution of Jev's choices by `subagent_type`.

**If that agreement is high, it is reported as a headline caveat regardless of
what the cost result says.** A cost win alongside 95% agreement with two lines
of `if` is a finding about routing, not about Jev, and must be presented as one.

This is the same failure mode the study already caught once, when Haiku 4.5 was
added beside Opus 5 because Opus-as-hook-gate was not a baseline anyone would
deploy. It is recorded here rather than in the pre-registration because a reader
asking "why is there no static-rule arm?" will look for an ADR, not for an
amendment clause.
