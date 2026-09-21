# W5 — actuator safety: the machine-wide switch, three silent no-ops, and a blind verifier

2026-09-21. Defect-fix wave. Every defect below was **reproduced by running the
code** before it was touched, and the reproduction is quoted verbatim.

Nothing was armed. `agent_route` is still `mode: "off"`, nothing was registered,
`~/.claude/settings.json` was not written, zero API calls were made.

---

## The distinction this whole report turns on

> **FAIL SAFE** — the hook exits 0, changes nothing, and cannot wedge a session.
> **FAIL SILENTLY** — the hook exits 0, changes nothing, *and leaves no trace
> that it was ever there.*

The first is a requirement. The second is the failure mode this repo has now
been bitten by four times, and it is dangerous for one specific reason: a
registered hook that is a permanent no-op is **byte-identical to the control
arm while appearing installed**. That is exactly what the `resolvedModel` check
exists to catch, arriving through a door the check does not watch.

The rule applied throughout: **every path either fails to frontier, or leaves a
durable, visible record that it did nothing and why.**

---

## 1. The machine-wide kill switch was a lie (JEV-40 box 1, regressed)

### Reproduced

    $ bash tests/reversibility.sh | grep GLOBAL
    ok  the GLOBAL switch block is byte-identical across all 1 hook script(s) that carry it

One. `config/registration.json` names exactly one installable hook, and the gate
only required the global block of installable hooks — so it asserted
byte-identity **across a set of one**, which is the vacuity pattern JEV-56 exists
to forbid. Meanwhile:

| hook | GLOBAL block |
|---|---|
| `hooks/agent_route_actuator.sh` | yes |
| `hooks/capture.sh` | **no** |
| `hooks/inline_shadow_bash.sh` | **no** |

`touch ~/.claude/jev-disabled` — the path `jev install` prints to the operator as
the machine-wide switch — did not stop `capture.sh`.

### Fixed

* The canonical `jev home` and `jev GLOBAL kill switch` blocks are now in **all
  three hooks**, **extracted** from `hooks/agent_route_actuator.sh` by script
  rather than retyped. The `jev home` header line changed from *"byte-identical
  in every installable hook"* to *"…in every hook"*, which is now true.
* **The gate can no longer pass vacuously.** `tests/reversibility.sh`:
  * the global and `JEV_HOME` blocks are required of **every hook script on
    disk**, not the installable subset;
  * `n_have < n_scripts` fails;
  * **`n_have <= 1` fails** — a set of one asserts nothing, same as the empty
    registration already did;
  * `n_inst == 0` still fails.
* **A run check, not only a text check.** New §2f fires all three hooks under a
  fake `$HOME` with `~/.claude/jev-disabled` set and requires each to do
  nothing — with a **positive control first**, because "nothing happened" is
  also what a hook that never ran looks like.

Now: `ok the GLOBAL switch block is byte-identical across all 3 hook script(s),
which is every hook there is`. Gate: **48 passed, 0 failed** (was 44).

### Cost, stated rather than hidden

`capture.sh` is the only thing on the critical path. The canonical `JEV_HOME`
block costs **one subshell** (`cd … && pwd -P`) when `$JEV_HOME` is not already
exported. Measured by `tests/test_hook.sh`'s own budget check: **5.37ms →
6.48ms**, against a 10ms budget. The header comment in `capture.sh` now says so
out loud, including the fact that exporting `$JEV_HOME` removes it. A kill
switch that is cheap and false is worth less than one that is true.

### Docs

`docs/REVERSIBILITY.md` no longer merely asserts the claim — it **records that
the claim was false**, for how long, why the gate missed it, and what now
enforces it.

---

## 2. Three actuator paths failed open or failed silently

### 2a. A tier that exists with no `alias` — failed **OPEN**

Reproduced, with `tiers.haiku45.alias = null`:

    ledger : {"decision":"routed","tier":"haiku45","assigned_alias":null,…}
    breaker: {"ts":…,"ok":true,"error":null}
    stdout : (empty)

`routed` with no alias: nothing rewritten, nothing emitted, and the breaker line
said **`ok:true`** — the one condition that makes routing a permanent no-op was
counted as a **success** and could never trip the breaker.
`src/tier_map.alias_for()` has always **raised** on the same config, so the jq
half and the Python half disagreed, and the parity test did not cover it.

Fixed in `hooks/agent_route_actuator.sh` (three guards, defence in depth):

* the up-front config check now rejects a frontier tier with no alias;
* a rule naming a tier with no alias `error`s, same as a rule naming an unknown
  tier;
* a final assertion: `routed` with a null alias raises.

All three route to `JQ_FRONTIER`, which is what non-negotiable 1(b) requires.
Now:

    ledger : {"decision":"fail_to_frontier","tier":null,"assigned_alias":"opus",…}
    breaker: {"ts":…,"ok":false,"error":"fail_to_frontier: tiers.json missing or unusable"}
    stdout : …"updatedInput":{…,"model":"opus"}

### 2b. `CLAUDE_PROJECT_DIR` not byte-equal to `$PWD` — **total silence**

Reproduced with a trailing slash (`CLAUDE_PROJECT_DIR=/tmp/…/proj/`):

    rc=0, stdout empty, and $JEV_HOME/data did not exist at all.

The guard compared **bytes** (`case "$PWD/" in "$ROOT"/*`), so a trailing slash
or a symlinked checkout made a session squarely inside its project fail the
guard on **every** invocation — installed, and permanently inert, with nothing
anywhere to say so.

Two fixes, and the second is the one that matters:

1. Both sides are now resolved (`cd … && pwd -P`), which normalises the trailing
   slash and the symlink at once. Two subshells per Agent spawn, against a 250ms
   budget.
2. A genuine out-of-scope fire no longer exits silently. Doing nothing is still
   the right action — this hook routes nothing outside the project it was
   registered for — but it now goes through `inert`.

### 2c. `$JEV_HOME/data/agent_route/` unwritable — **silent no-op**

Reproduced with `chmod 500` on `$JEV_HOME/data`: `rc=0`, nothing on stdout,
nothing on disk. `mkdir -p` was unchecked, the ledger append failed, and the
breaker line that was supposed to record *that* failed for the same reason.

The comment that used to justify it said *"its absence from the ledger is itself
the honest record."* **An absence is not a record.** That sentence is gone.

### The mechanism: `inert()`

A single function in the actuator that every can't-decide-can't-frontier path
now calls (`cwd_outside_project`, `project_dir_unresolvable`, `no_jq`,
`ledger_dir_unwritable`, `ledger_write_failed`). Its contract:

> a **durable** record — a `data/agent_route/inert.jsonl` row naming the reason,
> the resolved `$JEV_HOME`, project dir and cwd, plus a sticky
> `data/agent_route/INERT` marker file in the style of `BREAKER-OPEN` — **or**,
> if the disk will not take one, a **`systemMessage`**, the loudest channel a
> hook has.

Never both-fail quietly. The `systemMessage` variants are **assembled from
literals with no interpolated paths**, so a directory name cannot turn stdout
(which is a permission decision on a PreToolUse hook) into malformed JSON. The
jsonl row does carry the paths, with `"` and `\` escaped by parameter expansion
— no fork on an already-unhappy path.

Observed after the fix:

    cwd outside project → inert.jsonl row + INERT marker, stdout empty
    data/ unwritable    → {"systemMessage":"jev agent_route is INERT (it cannot
                           write its assignment ledger …)"}

`no_jq` was **not** in the audit's list but is the same class — a router that
silently stops routing because `jq` is missing is a router nobody fixes — so it
was brought under the same contract.

### Tests

`tests/test_agent_actuator.py::TestNoPathIsAllowedToBeSilent`, 8 cases: the
aliasless tier fails to frontier and is **not** scored as a success; no `routed`
row ever carries a null alias; jq and Python agree on the aliasless config;
trailing slash and symlinked project dirs no longer kill the hook; a genuinely
outside cwd leaves a row **and** a marker; an unwritable ledger dir says so out
loud and emits no `hookSpecificOutput`; and **a control** asserting the happy
path is still silent about being inert — without which every other assertion
here could pass for the wrong reason.

---

## 3. `verify()` was blind to the hook's own error rows

`JQ_FRONTIER` writes **`tier: null`** — it must, since that branch is reached
precisely when `config/tiers.json` could not be read — while rewriting `model`
to the frontier alias. `verify()` read `if not tier … → not_routed`. So **every
real fail-to-frontier assignment was classified "we deliberately left the input
alone"**: the branch that bills frontier rates scored as the *control arm*, and
was invisible.

The test that claimed to cover it hand-built
`{"decision":"fail_to_frontier","tier":"opus5"}` — **a row the hook has never
produced.**

Fixed:

* `verify()` now keys "did we rewrite?" on what the hook actually records about
  itself: **a rewriting decision with a non-null `assigned_alias`**. The tier,
  when absent, is recovered via the new `tier_map.tier_for_alias()`.
* A fifth class, **`unverifiable`**: we rewrote, but nothing in `config` maps the
  row to a `resolved_prefix`. Never folded into `honoured` (a lie) and never into
  `not_routed` (hides a rewrite that happened). It counts toward `routed_total`.
* A legacy `routed` row with a null alias rewrote nothing and is correctly
  `not_routed` — the hook can no longer emit one, but append-only ledgers keep
  the ones already written.
* `test_a_frontier_failure_is_verified_too` now **generates the row by running
  the hook** against a broken config, asserts the shape the hook actually emits
  (`tier: null`, `assigned_alias: "opus"`), then checks both honoured and
  overridden. Plus two new cases for `unverifiable` and the null-alias row.
* The `rows()` fixture in `TestVerifyAgainstResolvedModel` gained
  `assigned_alias` on every row, because the writer always emits it. A fixture
  missing a field the writer always writes is a fixture that can agree with a
  reader the writer disagrees with — which is precisely how this survived a
  test that claimed to cover it.

### What gate 3's live half still needs (asked for explicitly)

`verify()` has **zero callers outside tests**, and **nothing in this repo
produces a `resolvedModel`**. It is a correct join with no left-hand side. To
make the live half work you would need, in order:

1. **A producer of `{tool_use_id: resolvedModel}`.** Two candidate sources, and
   neither exists yet:
   * a `PostToolUse` hook on `Agent` that records the resolved model from the
     tool result, keyed by `tool_use_id` — the cheap option, but only if the
     PostToolUse payload actually carries a resolved model, which is **unverified
     and must be checked against a real payload before anything is built on it**;
   * a transcript reader over `~/.claude/projects/**/*.jsonl` joining the
     subagent's own session to the parent's `tool_use` block id. This works
     offline but is subject to a retention policy we do not control — the same
     reaping that already shrank the delegated-task corpus from 120 to 42.
2. **A caller.** Nothing invokes `verify()`. It needs to be wired into
   `src/doctor.py` or the accuracy gate, and its `honour_rate` reported with its
   scope (`project`, `pooled`) attached — a rate printed without its scope is the
   JEV-57 confound.
3. **Rows to verify.** `data/agent_route/assignments/` is empty, because
   `agent_route` is `mode: "off"` and nothing is registered. Until W1 is armed
   (JEV-52) the live half has no input at all.

Until (1) exists, gate 3 can only assert what the hook *asked for*, which is the
exact distinction — asking for a model and getting it — that this function was
written to refuse to blur. That limitation should be stated in the gate's own
output rather than remembered.

---

## 4. Relative `$JEV_HOME` (handover from the install agent)

Bash uses `$JEV_HOME` **verbatim** after an `is_dir` test, so `JEV_HOME=.` makes
every jev asset cwd-relative — including `$JEV_HOME/.jev-disabled`, the global
kill switch. A switch whose path depends on where the caller happened to be
standing is exactly what the per-project block's own comment forbids.

The canonical `jev home` block now carries
`case "$JEV_HOME" in ""|/*) ;; *) exit 0 ;; esac`, byte-identical in all three
hooks. It **refuses** rather than falling back: `paths.resolve_jev_home()`
**raises** on the same value, and falling back to the derived path would be one
reader guessing where the other declines to. `jev` and `paths.py` already reject
it loudly where a human sets it; the hook is the backstop.

Three new tests in `test_agent_actuator.py`: the hook refuses and — the part
that matters — writes **nothing under the cwd**; `paths.resolve_jev_home({"JEV_HOME": "."})`
raises; and an absolute `$JEV_HOME` still works (the control).

`tests/test_jev_home.sh` §1 was left alone: its bash-vs-python comparison is
"same absolute path", and this is the case where agreement means *both refuse* —
a different assertion shape. The behavioural version lives in my file instead.

## 5. `project` on the ledger row (handover from the JEV-57 data agent)

The hook now emits `-v2` rows carrying `project`, taken from **`$ROOT` raw** —
not the `pwd -P`-resolved `$ROOT_P` the cwd guard uses, because the path of a
worktree is not the path of its repository and collapsing them is an analysis
decision the hook cannot make. Both jq programs (`JQ_DECIDE` and `JQ_FRONTIER`)
take `--arg project "$ROOT"`; the frontier path needs it just as much, since an
unattributable frontier-rate assignment is the expensive branch pooling
silently. `LEDGER_SCHEMA` flipped to `LEDGER_SCHEMA_V2` in the same change.

`tests/test_assignment_ledger.py::test_the_deployed_schema_constant_tracks_the_hook_not_the_reader`
hard-coded `V1`. Rather than re-point the literal, it now **reads the hook** and
asserts the constant matches what the hook actually emits — a literal there is a
second copy of the same fact, hand-edited at exactly the moment a drift detector
is most likely to be edited into agreement rather than fixed.

### The apostrophe, and a guard that could not see it

Writing §5 shipped, briefly, **the worst bug in this whole report**: a jq comment
containing `worktree's`. The jq programs are **single-quoted shell strings**, so
one apostrophe closed the string early and the hook emitted **nothing at all** —
no rewrite, no ledger row, no breaker line. A total silent no-op, the exact class
W5 exists to remove, introduced by a *comment*. Caught by the behavioural tests
in under a minute.

The existing guard claimed to cover this: *"the hook is syntactically valid bash
(an apostrophe inside an embedded jq program would fail here, and nowhere
else)"*. **It does not.** Two apostrophes in one comment pair with each other,
the file stays valid bash, and `bash -n` passes while the hook is dead. That
claim is removed and replaced by an explicit scan of the three jq programs in
`tests/test_agent_actuator.sh` §11. A guard that names a failure it cannot see is
worse than no guard, because it stops anyone looking for a real one.

## Test status

`bash tests/run_all.sh` is green through every step I touched:

    test_hook.sh              27 passed, 0 failed   (was failing: see below)
    test_hook_mutations.sh    17 passed, 0 failed
    test_inline_shadow.sh     40 passed, 0 failed   (was failing: see below)
    test_agent_actuator.py    50 tests, OK          (+11 new)
    test_agent_actuator.sh    61 passed, 0 failed
    test_jev_home.sh          37 passed, 0 failed
    test_install.sh           55 passed, 0 failed
    reversibility.sh          48 passed, 0 failed   (was 44)
    test_clean_checkout.sh     8 passed, 0 failed
    doctor.py                 14 passed, 1 warned, 0 failed
    + analyze_config_join, worker_lifecycle, collection_control, validation,
      jev16, latency, session_metrics, baseline, canary — all OK

### Two suites needed fixing, and the reason is worth recording

Adding the global switch to `capture.sh` and `inline_shadow_bash.sh` made them
anchored on `$JEV_HOME` and `$HOME` as well as `$CLAUDE_PROJECT_DIR`. Neither
`tests/test_hook.sh` nor `tests/test_inline_shadow.sh` sandboxed those, so both
suites started reading **the live repo's `.jev-disabled`** — which is currently
set — and went red for a reason that had nothing to do with the hook.
`tests/test_agent_actuator.py` had already solved this (`SandboxHook` sets both);
the two older suites were simply behind. Both now point `$JEV_HOME` (and
`$HOME`) at their own sandbox.

In `test_inline_shadow.sh` this is done **per hook invocation, never
`export`ed**, and that is not fastidiousness — both were exported first and both
broke the test:

* `export HOME` stopped the loopback fake from starting at all, because a
  `$HOME`-relative interpreter shim does not resolve under a fake home;
* `export JEV_HOME` made `src/bench_inline.py --serve` look for `hooks/` inside
  the sandbox.

Four red assertions each time, none of them about the hook. The env a hook is
given belongs to the hook's invocation, not to the test process.

`bash tests/run_all.sh` runs to completion with **zero failures**, ending on
`ok spool, data/ and logs/ are as the suite found them`.

Mid-run, `test_accuracy_gate.py` was red with 5 `SessionOutcomes` errors from
another agent's in-flight W3 work. That agent has since landed and it is green.
Verified independent of me either way: neither `tests/test_accuracy_gate.py` nor
`src/accuracy_gate.py` references `assignment_ledger`, `tier_map` or `verify()`.

**No new `guarded` line is needed in `tests/run_all.sh`.** Every test added here
lives in `tests/test_agent_actuator.py`, `tests/test_agent_actuator.sh` or
`tests/reversibility.sh`, all three of which `run_all.sh` already runs.
`tests/test_assignment_ledger.py` was added to `run_all.sh` by the JEV-57 agent,
not by me.

---

## Concurrency note

This worktree is shared with at least two other agents working right now.
`src/assignment_ledger.py` was rewritten underneath me mid-edit (JEV-57, project
partitioning). My `verify()` changes merged cleanly with theirs — the classifier
body is mine, the `project` / `pool_projects` scoping is theirs, and the two are
orthogonal — but **this should be re-checked at merge time**, since the module
docstring and `LEDGER_SCHEMA` constants are theirs and were still moving.

---

## Known residual, deliberately not fixed

`hooks/capture.sh` and `hooks/inline_shadow_bash.sh` still use the **byte**
comparison for their cwd guard (`case "$PWD/" in "$ROOT"/*`), so a trailing
slash or symlinked `CLAUDE_PROJECT_DIR` silently drops every capture on those
two surfaces — the same defect as 2b, on the observer hooks. It was left because
the fix costs two subshells on `capture.sh`, which is the only thing on the
critical path and is already paying one for `$JEV_HOME`, and because a capture
miss is attrition rather than a treatment/control collapse. **It is still a
silent loss and should be a ticket.**

`src/doctor.py` reads `data/agent_route/BREAKER-OPEN` but knows nothing about
the new `data/agent_route/INERT` marker. Teaching it to is a one-line change in
a file I do not own this wave.

## A decision worth stating: the `INERT` marker does not self-clear

`BREAKER-OPEN` is removed (`rm -f "$MARKER"`) on every non-breaker decision.
`INERT` is **not**: it is rewritten on each occurrence and stays until a human
removes it, which the file's own text says. That is a deliberate divergence from
the precedent it copies. The reasoning: the breaker's condition is *derived from
a log that keeps being written*, so a stale marker would contradict readable
state — whereas an inert hook by definition writes no decisions, so there is no
later event that could honestly clear the marker. In this repo a stale false
alarm is cheaper than a false negative. One `rm -f "$INERT_MARKER"` after a
successful ledger append would make it symmetric if a reviewer prefers that.

## Files changed

Mine, as briefed:

- `hooks/agent_route_actuator.sh`
- `hooks/capture.sh`
- `hooks/inline_shadow_bash.sh`
- `src/tier_map.py` (added `tier_for_alias`)
- `tests/test_agent_actuator.py`
- `tests/test_agent_actuator.sh`
- `tests/reversibility.sh`
- `docs/REVERSIBILITY.md`
- `.scratch/pivot/w5-actuator-safety.md` (this file)
- `config/tiers.json` — **untouched**, though it was in my list. No policy
  change was needed; the aliasless-tier defect was in the reader, not the table.

Co-edited, must be eyeballed at commit time:

- `src/assignment_ledger.py` — the `verify()` classifier body (`unverifiable`,
  the alias-keyed rewrite test, `tier_for_alias` recovery) and the
  `LEDGER_SCHEMA = LEDGER_SCHEMA_V2` flip are mine. The `-v1`/`-v2` constants,
  `ProjectsWouldBePooled`, `row_project`, `partition_by_project`, the
  `<v1:no-project>` fence and the `project` / `pool_projects` scoping are the
  JEV-57 agent's. Both are present and the merged file is green
  (`test_assignment_ledger.py` 15/15, `test_agent_actuator.py` 55/55).

Outside my ownership list, and not in the forbidden list — flagged so the
orchestrator knows they moved:

- `tests/test_hook.sh`, `tests/test_inline_shadow.sh` — had to be sandboxed.
  Adding the global switch anchored both hooks on `$JEV_HOME`/`$HOME`; neither
  suite isolated those, so both started reading the live repo's `.jev-disabled`
  (which is currently SET) and went red for a reason unrelated to the hook. The
  suite cannot be green without this.
- `tests/test_assignment_ledger.py` — one test (`..._tracks_the_hook_not_the_reader`)
  re-pointed from a `V1` literal to reading the hook, required by the JEV-57
  handover that flipped the schema.

Not mine, and present in the working tree — do **not** attribute to me:

- `.scratch/pivot/repro_w5.sh`, `.scratch/pivot/w5_anchor_diff.py`,
  `.scratch/pivot/w5_anchor_diff2.py`, `.scratch/pivot/w5_suite_mine_only.sh`
  (untracked, appeared mid-run from another agent despite the `w5` names)
- `src/install.py`, `jev`, `src/paths.py`, `config/registration.json`,
  `tests/test_install.sh`, `tests/test_jev_home.sh` (install agent)
- `src/accuracy_gate.py`, `src/subagent_outcomes.py`, `src/fixture_executor.py`,
  `tests/test_accuracy_gate.py` (W3 agent)
- `data/baseline/*`, `src/baseline.py`, `src/session_metrics.py`,
  `tests/test_baseline.py` (not touched by me)

Nothing was armed: `agent_route` is still `mode: "off"`, nothing was registered,
`~/.claude/settings.json` was never written, and zero API calls were made.
