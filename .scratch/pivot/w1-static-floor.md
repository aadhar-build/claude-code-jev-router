# W1 — the static floor

**JEV-35, built 2026-09-21. Built, not armed.**
`mode: "off"`, nothing registered, zero API calls, zero network primitives.

The first shippable routing thing, containing **no classifier at all**: a
`PreToolUse` hook on the `Agent` tool that applies a static
`subagent_type → tier` map by rewriting `tool_input.model`. It is the baseline
Jev must later beat, and the scaffolding — ledger, breaker, verifier — that
everything after it needs.

---

## 1. The count problem, settled

My brief, a correction to it, and a follow-up all gave different numbers. I
measured rather than picked. **Four counts of "a delegated task" circulate for
this project and they differ by a factor of 17 — not because anyone was wrong,
but because they count different things over different windows.** All four are
now recorded in `config/tiers.json:_counts_and_their_rules`, and
`.scratch/pivot/count_reconcile.py` reproduces the two that come from the repo.

| n | source | counting rule | window |
|---|---|---|---|
| **120** | `data/baseline/sessions.jsonl` | one **subagent transcript file** per task | full, snapshot 2026-09-20 |
| 7 | `data/baseline/delegation-pre-rule-v1.json` | delegated tasks per billable request | **pre-rule cut only**, 15 sessions |
| 42 | measured here | distinct `Agent` `tool_use` blocks, dedup by id, this project + worktrees | on disk today |
| 33 | second agent | not fully stated | on disk today |

**Two things I got wrong along the way, stated plainly:**

1. I reported that "no baseline file carries `subagent_type`". **That was
   wrong.** `sessions.jsonl` carries the field under a different name —
   `delegated_task_agent_types` — and my grep missed it. Aggregated over the 29
   session rows it gives **exactly** `general-purpose 78 / claude-code-guide 18
   / Plan 12 / Explore 12`, total 120. The 120/78/65% table is **real,
   sourced and reproducible**; it is not fabricated, and the correction that
   said it was is itself wrong.
2. `delegated_tasks` and `source.subagent_files` in that same file **both**
   independently sum to 120, which is why I treat it as the best-sourced count:
   largest window, two agreeing fields, frozen *before* transcript reaping.
   `data/baseline` is the one directory committed to git precisely because
   transcripts live outside the repo under a retention policy we do not control.

**Why 42 ≠ 120 is not a contradiction:** 120 is a 2026-09-20 snapshot of
subagent files; 42 is what is countable on disk today, a lower bound on a
corpus that has since been reaped. Different unit, different day.

### What this means for coverage

**The static floor addresses between an eighth and a third of delegated work.**

- **35%** by the full-window snapshot (42 of 120 routable).
- **12–17%** by what is countable today (7 of 42 in-project; 26 of 208 corpus-wide).

This is stated as a **range**, not a point, and the tests assert the range
(`test_the_addressable_share_is_a_range_between_an_eighth_and_a_third`). With
the corpus size disputed by 17×, a single number would be false precision.

The one thing every source agrees on is the only thing leaned on:
**`general-purpose` is the large majority** — 65% full-window, 55% / 79% by the
two counts taken today. It is the catch-all type, so the type name says nothing
about the work. It is mapped to `tier: null` and left untouched.

**A category no earlier estimate mentions:** 12 of 42 spawns on disk carry **no
`subagent_type` field at all**. They are unroutable for exactly the reason
`general-purpose` is, and they are now counted and tested.

### The map is a policy choice, not a fitted one

Three of four rules sit on cells of n=2, n=3, n=12. Those are anecdotes.
**Nothing in the map is fitted to them.** Every routed rule in
`config/tiers.json` carries a `basis` field saying it is a policy judgement
about the agent type's job description, and a test enforces that. The counts in
that file are evidence about **coverage only** — never about which tier a type
should get.

| type | tier | basis |
|---|---|---|
| `general-purpose` | — (null) | data: every source agrees it is the uninformative majority |
| `Explore` | haiku45 | policy: read-only, tool-restricted, retrieval-shaped, checkable output |
| `claude-code-guide` | haiku45 | policy: bounded doc lookup, answer checkable against cited docs |
| `Plan` | sonnet5 | policy, **lowest confidence** — harder than retrieval so not haiku, but read-only and human-reviewed before execution, so one step down not two |

`Plan` is flagged in the config as the first row to revisit and the first to
revert.

### On `ISSUES.md:2348`, which rejected this exact map

That paragraph rejected a `subagent_type → tier` map "so it is not re-proposed".
It rejected it **as an experimental arm** competing for a fixed run budget,
where degenerating to a constant on the majority of traffic would burn a third
of the budget reproducing the `default` arm. The pivot retired that study. As a
**production floor** the same majority is a stated coverage limit rather than a
confound, and it costs no run budget because it makes no calls. Measured
coverage is *worse* than the figure that rejection argued against — which
strengthens the case against it as an arm and does not weaken the case for a
free floor. Recorded in the config so the board and the tree do not appear to
contradict each other.

---

## 2. JEV-35's five gates

| # | gate | status |
|---|---|---|
| 1 | **Input fidelity** — `updatedInput` replaces the ENTIRE object | ✅ **satisfied** |
| 2 | **Assignment ledger before spawn** | ✅ **satisfied** |
| 3 | **Verify against `resolvedModel`** | ⚠️ **half** — mechanism built and tested; live half impossible until armed |
| 4 | **Fail open → the default, which IS the control arm** | ⚠️ **superseded** — fail-safe half satisfied; fail-to-*default* half replaced by fail-to-frontier |
| 5 | **Kill switch proven on THIS hook** | ✅ **satisfied**, two switches × three shapes |

### Gate 1 — input fidelity ✅

The rewrite is `$ti + {model: $alias}` — a right-biased merge over the whole
object. **There is no field list that could fall out of date.** Tested with a
field the hook has never heard of (`weird_future_field`), and specifically on
`subagent_type`, whose loss would spawn the wrong agent type and be
indistinguishable in the results from a routing-quality effect.
`tier_map.apply()` is the same one-key copy in Python and a test asserts the two
produce identical objects.

### Gate 2 — ledger before spawn ✅

The hook is synchronous; the spawn cannot begin until it exits. So "the row
exists at exit" *is* "the row exists before the spawn". What makes the ordering
load-bearing rather than incidental is the failure branch: **when the ledger
cannot be written, nothing is rewritten.** `chmod 500` on the ledger dir →
zero bytes on stdout, input untouched, breaker failure recorded. Of three
options — rewrite anyway (unattributable), block (never; fail-safe is absolute),
leave untouched — untouched wins, because untouched *is* the control arm and its
absence from the ledger is itself the honest record.

Each row carries all five required fields: decision, tier, rule that fired
(verbatim), config fingerprint, original model — plus `hook_ms`.

### Gate 3 — verify against `resolvedModel` ⚠️ half

Built and tested: `assignment_ledger.verify()` joins ledger rows to observed
`resolvedModel` and classifies **honoured / overridden / unobserved /
not_routed**. `overridden` is the one that matters — an assignment silently
ignored by an `availableModels` allowlist or `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`
makes the treatment arm identical to the control arm while still looking like a
treatment. `unobserved` is counted as attrition, never assumed honoured.

**The contract check that this gate is really about, and which I did verify
against real data:** `tool_input.model` takes an **alias**, not a model id.
Two independent sources agree. The Agent tool schema is primary —
`model` is `enum: ["sonnet","opus","haiku","fable"]`, and it is the *only*
evidence for `haiku`, which no observed spawn happens to use. Observed traffic
is corroborating: of **208 distinct spawns (deduplicated by `tool_use` block
id)**, 29 carry `"sonnet"`, 2 carry `"opus"`, 2 carry `"inherit"` and 177 carry
none. No observed spawn carries a dated id. *(An earlier draft of this report
quoted "66 sonnet / 4 opus" — that was the raw grep, including transcript
replays and non-Agent `"model":` matches. In a report whose first section is
about counting rules, that needed fixing.)*

Meanwhile `resolvedModel` is always a full, sometimes dated, sometimes suffixed
id (`claude-haiku-4-5-20251001`, `claude-opus-5[1m]`). So the hook emits the
alias and the verifier does a **prefix match** — equality would report every
honoured assignment as a mismatch. Had the hook emitted
`claude-haiku-4-5-20251001` (as the reversibility *fixture* does), every
assignment would have been silently unhonoured. This is exactly the failure gate
3 exists to catch, and it was caught before arming.

**Not satisfied:** no live `resolvedModel` has been observed, because observing
one requires the hook registered and firing. That is JEV-52.

### Gate 4 — ⚠️ superseded, and the board is now stale

**This gate is not simply "satisfied" and I should not claim it is.** As written
in `ISSUES.md`, gate 4 says: *"Fail open means fall back to the default, which
IS the control arm."* The hook does that on three of its four failure paths —
unparseable payload, unwritable ledger, breaker open. On the **config-broken**
path it goes to **frontier**, which is *not* the control arm.

That is correct per the operator's decision of 2026-09-21
(`SPEC-draft.md` §3 non-negotiable 1b), which explicitly overrides the default
recommendation. So: **the fail-safe half of gate 4 is satisfied; the
fail-to-default half is deliberately replaced by fail-to-frontier, bounded by
the circuit breaker.**

> **⚠️ For the orchestrator — a board/tree mismatch `test_board.py` cannot
> see.** `ISSUES.md` JEV-35's gate-4 box and its prior-art amendment
> (*"Ours is fail-open by design; say so explicitly and state what it costs"*)
> are now **stale** against `SPEC-draft.md` §3. The ticket still describes the
> pre-pivot semantics. It needs updating to match, or the two documents will
> keep disagreeing about what this hook is supposed to do on error. I have not
> edited `ISSUES.md`.

### The distinction the repo has already been bitten by

**Fail safe and fail to frontier are not the same thing**, and the hook
separates them structurally:

- **Fail safe (absolute).** `trap 'exit 0' EXIT` on line one, before the stderr
  redirect — capture.sh's discipline transplanted verbatim. No `set -e`. Every
  unhandled error is inert; the input is untouched.
- **Fail to frontier (a routing decision only).** Operator decision 2026-09-21.
  Config missing or unparseable → rewrite to **frontier**, never a cheap tier.

**The boundary between them is the payload**, and this is the part worth
reading:

| condition | behaviour |
|---|---|
| payload parsed, config broken | frontier rewrite, **every field echoed** |
| payload **unparseable** | **zero bytes on stdout**, input untouched |

Fail-to-frontier requires echoing every field back, so it is reachable *only*
after `tool_input` has parsed. Before that there is no faithful `updatedInput`
to build, and a partial one would spawn the wrong agent type. Both count as
router failures; neither can break a session. Both directions are tested side by
side.

**A miss is not an error.** `general-purpose` and unmapped types produce
`no_rule` → no rewrite → **the control arm**. They record a *success* outcome,
never a failure. Escalating an unknown type to frontier would be a cost decision
made on no information, and would make the no-signal majority *more* expensive
than doing nothing.

### Gate 5 — kill switch, proven on this hook ✅

This repo has already shipped a switch that stopped one writer and not the
other, so nothing is inherited by assumption. **Two switches, both fail-safe,
each tested in three shapes** (regular file, directory, dangling symlink):

- **Per-project** `$ROOT/.jev-disabled` — the canonical block, verified
  **byte-identical** to `capture.sh`'s by both a `diff` and a unit test.
- **Global** `$HOME/.claude/jev-disabled` — stops routing in every project at
  once. Read-only; nothing here ever writes to `$HOME`.
- **Unset `$HOME` reads as OFF** — a switch whose state cannot be established is
  never given the benefit of the doubt.

The assertion is the strong one for an actuator: not "it stopped logging" but
**"it stopped deciding"** — zero bytes on stdout *and* no ledger directory.

Also guarded: `JEV_ARM_SUBPROCESS`, `JEV_GRADER`, the cwd guard, and a
defensive `tool_name == "Agent"` check.

---

## 3. The circuit breaker

Mandated because **fail-to-frontier protects quality and does not protect
cost**: a sustained outage silently bills frontier rates indefinitely.

After **3 consecutive failures inside a 900s TTL**, the hook stops rewriting
entirely, leaves the input untouched, drops a sticky `BREAKER-OPEN` marker, and
emits a **`systemMessage`** — the loudest channel a hook actually has, since
stdout is a permission decision and stderr is a log nobody reads. `doctor.py`
surfaces the marker, so the condition is still visible tomorrow morning.

**State is an append-only outcome log, never a counter file.** Parallel `Agent`
spawns are the normal case and a read-modify-write counter loses increments
under exactly the conditions that matter. One short `O_APPEND` line per outcome,
well under `PIPE_BUF` — the property `capture.sh` already relies on.

**Open/closed is derived, never stored**, which buys three things free:
half-open (past the TTL the newest failure is stale, one probe is allowed, its
own outcome decides), no stuck state, and no reset step anyone can forget. While
open **nothing is appended**, so the TTL can actually expire. Shape harvested
from `/tmp/jevharvest/vexjoy/scripts/jev_router_common.py` (MIT) — its TTL and
cross-process discipline; the append-only log is a change, made because that
implementation's single-file read-modify-write would race here.

Tested: consecutive-not-total, TTL expiry, half-open, out-of-order appends, torn
lines, zero-threshold-disables, and **survival across process boundaries** —
which matters because every hook invocation *is* a fresh process.

---

### Verified under the repo's own byte-identity oracle

`tests/reversibility.sh` 3c/3d exercise a *fixture* of roughly the right shape.
The **shipped** hook is now also run through `src/hook_dispatch.py` — the
model of Claude Code's documented `PreToolUse` dispatch, and the repo's
designated definition of "the tool input that survives". Two assertions:
switch **ON** → resolved input byte-identical to vanilla; switch **OFF** →
byte-identical to vanilla plus exactly `{"model":"haiku"}`. Plus: the actuator
never sets `blocked`, whatever it is fed.

### One caller-choice subtlety

`model: "inherit"` (2 of 208 spawns) sits in `tool_input.model` but expresses
**no tier preference** — it means "use whatever the parent is on". Treating it
as a deliberate choice would exclude those spawns from routing forever while
looking like deference to the caller. It is therefore **routed**, via a
configurable `explicit_model_ignored_values` list, and still recorded as
`original_model`.

---

## 4. Two implementations, kept honest

The rule exists twice: in `jq` inside the hook (what ships) and in
`src/tier_map.py` (what tests and analysis read). This repo already knows that
hazard from `build_pre_bash` vs the inline hook's jq. A test feeds both the same
payload for every known type and compares `decision`, `tier`, `alias` and the
**rule text byte for byte** — which is why the Python half builds rule strings
with `json.dumps` rather than `repr`. The config fingerprint is checked the same
way: `openssl dgst -sha256` in bash against `hashlib` in Python.

The hook contains **no tier literal and no subagent-type literal** — asserted by
test. The single exception is `FRONTIER_FALLBACK_ALIAS="opus"`, the
fail-to-frontier target used when the *config* is what failed: a fail-safe value
cannot depend on the thing that failed. A test pins it to the config's frontier
alias so it cannot drift.

---

## 5. Latency

Non-negotiable 5 requires a budget enforced by a test. Budget: **250 ms**,
declared in config. Measured: **~25 ms mean** over 20 invocations — process
spawn plus four forks (`jq -n now`, `tail`, `jq`, `openssl`). No network call
exists to time out. Every ledger row carries its own `hook_ms` and the test
asserts none exceeds budget.

---

## 6. Files

**New:** `config/tiers.json` · `hooks/agent_route_actuator.sh` ·
`src/tier_map.py` · `src/assignment_ledger.py` ·
`tests/test_agent_actuator.py` (40 tests) ·
`tests/test_agent_actuator.sh` (61 assertions) ·
`.scratch/pivot/count_reconcile.py` · this report.

**`PREREGISTRATION.md` A3.4 checked:** it specifies the two gates in prose only
— no ledger field list, no ledger location, no alternative fidelity definition.
No deviation. What is built exceeds it (config fingerprint, original model, and
the rule text are recorded beyond what A3.4 asks for).

**Modified:** `tests/test_agent_route.py` (tripwire rewritten, +2 tests) ·
`tests/run_all.sh` (wired) · `src/paths.py` · `src/doctor.py` (breaker check).

**Deliberately untouched:** `.claude/settings.local.json`,
`~/.claude/settings.json`, `config/surfaces.json` (`agent_route` stays `off`),
`config_loader.WATCHED` (adding `tiers.json` would change `config_fingerprint()`
for every already-collected row and break JEV-32's config join).

---

## 7. Deliberately left for later

- **Arming it (JEV-52).** Built, not armed, on purpose.
- **The live half of gate 3.** No `resolvedModel` observed; needs a live window.
- **Live spawn latency** — JEV-34's deferred box. ~25 ms is measured in a test
  loop, not on a real spawn's critical path.
- **Any claim that this saves money.** The map is unvalidated policy; coverage
  is 12–35%. W1 establishes the floor and the measurement scaffolding — it does
  not yet establish a win.
- **`fable51`.** Absent from the choice set; JEV-28 has not cleared it.
- **Escalation semantics** (SWE-Router restart-vs-continue). Not applicable: the
  static floor decides once and never escalates. Must be pre-registered before
  anything that *does* escalate.
- **Revisiting `Plan → sonnet5`** the moment outcome data exists.
