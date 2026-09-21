# W5 — `src/report.py`: the module that finally compares a before to an after

**Status:** built, tested, green. Nothing armed, no API call, `agent_route`
untouched at `mode: "off"`.

**Files I own and changed:**

| file | state |
|---|---|
| `src/report.py` | **new** |
| `tests/test_report.py` | **new**, 88 tests, all passing |

Nothing else was touched. `tests/run_all.sh` is owned elsewhere — see
"the guarded line I need" below.

---

## What it is

JEV-06's unticked box says it plainly: *"`session_metrics.py` is a viewer"*.
Nothing in this repository has ever differenced a before against an after.
`src/report.py` is that thing, and it reports **R1–R5 in SPEC §2's corrected
order** — rework first, cost last and ungated.

It **reuses and re-implements nothing**:

- `session_metrics.billable_requests` / `analyse` for all costing, reached
  through `subagent_outcomes` (a source-level test asserts `report.py` contains
  no pricing constant and no `call_cost`)
- `subagent_outcomes.outcomes_for_session` / `join_outcomes` for per-task
  outcomes, both durations, retries, truncation and attrition
- `assignment_ledger.read_ledger` / `partition_by_project` /
  `ProjectsWouldBePooled` for which arm a task was assigned to, per repo
- `baseline`'s corrected companion for the frozen "before"
- `stats.quantiles` for p50/p95
- `accuracy_gate`'s `EXIT_*`, `worst()` and `Criterion` — **imported, not
  redefined**, and a test asserts the taxonomy is not re-declared locally

---

## Exactly what a developer types

**The before/after, once an after corpus exists:**

```bash
uv run src/report.py \
    --before data/baseline/delegation-pre-rule-v1-corrected.json \
    --before-scope interactive_sessions_only \
    --after-session ~/.claude/projects/<slug>/<session>.jsonl \
    --after-ledger data/agent_route/assignments \
    --project "$PWD" \
    --gate-exit "$ACCURACY_GATE_EXIT"
```

**With R1 and R2 on the before side too** (the corrected JSON carries costs and
counts only — no durations, no retries, no completion states). The session
supplied must end **at or before** the anchor's JEV-24a cut
(`2026-09-20T11:11:49Z`) or the invocation is refused, exit 2 — post-cut work
labelled "before" is the trap one step out:

```bash
uv run src/report.py \
    --before data/baseline/delegation-pre-rule-v1-corrected.json \
    --before-session ~/.claude/projects/<slug>/<pre-cut-session>.jsonl \
    --after-session ~/.claude/projects/<slug>/<post-arm-session>.jsonl \
    --after-ledger data/agent_route/assignments \
    --project "$PWD" --gate-exit 0
```

**Freezing a side so it can be re-read later:** `--json` emits a
`jev-report-side-v1` snapshot; `--before-json` / `--after-json` read one back.

**Exit codes**, the `accuracy_gate.py` taxonomy unchanged:
`0` ran clean · `1` COULD NOT RUN (**not a pass**) · `2` invoked wrong ·
`3` ran and found a regression (R1 rework increased, or R3 failed).
This module *does* judge, unlike `subagent_outcomes.py`, so exit 3 is live.

---

## What it says on the day it is first run for real

`data/agent_route/assignments` is empty, `agent_route` is `mode: "off"`, and
nothing is registered. Verified by running the real command above — note that
the output reports the path it **read** and the row count it **found**, rather
than asserting anything about the config it did not open:

```
=== SPEC §2 R1-R5 before/after report ===

  NO AFTER CORPUS EXISTS.

  Nothing has been measured. This is NOT a report that the after side
  cost nothing, took no time and reworked nothing -- there is no after
  side.

  What was checked: --after-ledger data/agent_route/assignments
  Ledger directory read: data/agent_route/assignments -- 0 assignment rows.

  What exists is the BEFORE anchor, printed here so it is visible:
    source  data/baseline/delegation-pre-rule-v1-corrected.json
    window  before: pre-rule, JEV-24a cut [scope=interactive_sessions_only ...
            window=2026-09-19T19:58:56.537000+00:00 .. 2026-09-20T11:11:49Z]
    delegated tasks                7
    delegated spend               $20.1585 (LOWER BOUND)
    realised cost / delegated task    $  2.8798 (LOWER BOUND)  n=7  ...
    realised cost / outcome           $  2.8798 (LOWER BOUND)  n=7  ...
    R1 / R2 on the before side: NOT CARRIED by this record.

VERDICT: exit 1 -- COULD NOT RUN (this is NOT a pass)
  This report did not reach a verdict. DO NOT READ IT AS A PASS.
  Nothing has been shown to have helped, or to have harmed.
```

`$2.8798` is the corrected anchor to six places. A test asserts this output
contains **none** of `$0.00`, `$0.0000`, `0 tasks`, `0.00%`.

---

## The five criteria, and what each refuses to do

**R1 rework — PRIMARY.** `retries = attempts - 1` (summed per assignment, so a
retried task counts its earlier attempt), `failures = outcome_found and not
completed`. **Attrition is printed beside R1 and never folded into it** — it is
a measurement gap, not a redo. The header states the reason the criterion leads:
operator decision 3 is RESTART, so a redo pays the whole task again, serially.
An increase → exit 3.

**Escalations report `NOT OBSERVABLE`, never `0`.** I grepped `src/`,
`config/` and `hooks/` for `escalat`: **zero hits.** `tier_map.FAILURES` has no
escalation outcome and RESTART is unimplemented, so no field in
assignment-ledger schema v2 records one. On the unrouted before side it prints
`0 BY CONSTRUCTION`. A `0` on the routed side would be a guard that could not
run reading as a guard that passed, one level down.

**R2 felt latency.** Blocking p50/p95 and task p50/p95 in **two separate
tables, each with its own n**, followed per side by the literal line *"the two
denominators are N (task) and M (blocking). They are both true and they are NOT
A RATIO. Do not divide one by the other."* The criterion is driven by the
**blocking** number only; the caveat that routing cannot improve felt latency
(794.6s vs 1.5s, background) is printed above both tables, and a blocking
reduction prints *"needs a mechanism other than routing before it may be
claimed as a win."* A test feeds a fixture whose task duration halves and
asserts the verdict does not move on it.

**R3 quality.** Taken from `accuracy_gate`'s verdict via `--gate-exit` or
`--gate-verdict <json with exit_code>`. **Absent → NOT_EVALUABLE → the whole
report exits 1.** Gate exit 1 or 2 is likewise not a pass. A verdict file
without an integer `exit_code` is exit 2, with *"cannot be read as a pass"*.

**R4 the layer's own cost, in the win's units.** `hook_ms` from the ledger rows
→ p50/p95 in ms, stated to be **on the blocking path** (the hook runs before the
spawn returns), converted to seconds and added to the R2 blocking delta as
`NET LATENCY`. `NET SPEND` is R5's delta, and the output says so — a routed
task's cost already contains whatever the layer billed, fail-to-frontier
premium included, so it is not a second subtraction. Unrecorded `hook_ms`
prints *"NOT zero"*. The before side prints `0 BY CONSTRUCTION`. A net latency
worse than zero fails; **a missing latency or spend term is `NOT_EVALUABLE`,
not a pass** — SPEC §2 R4 is plural. Unattributed delegated spend (the
`unassigned` mirror) is real spend and is in the R5 numerator, not a footnote.

**R5 realised cost — reported, NOT a gate.** Its status is never `FAIL` in
either direction. The numerator is attributed **plus** unattributed delegated
spend, and **both denominators** are printed — `$/assignment` (attrition
included) and `$/outcome` (attrition excluded) — because they move in opposite
directions when a tier's tasks die. Every `$` figure carries `(LOWER BOUND)`
and a test walks the rendered lines asserting it.

---

## The trap, made structural

`$2.88` is the JEV-24a cut; `$5.21` is the whole corpus. Two cuts of **one**
corpus, and this project has compared them twice.

Every number is a `Figure` carrying a `Window`:
`(label, scope, costing_rule, pricing_version, project, starts_at, ends_at)`.
`diff()` is the **only** path from two figures to one number, and it calls
`comparable()` first, which raises `WindowsDiffer` unless scope, costing rule,
pricing version and project all match **and the time ranges are provably
disjoint**. `label` is deliberately excluded — renaming a window does not make
it a different population.

**A `None` bound can never be proven disjoint, so it refuses.** That is the
`project_dir()` lesson applied: a missing fact must not read as a benign
default.

R5 prints the $5.21 figure only to name it as a different cut that must never
be differenced, and the exception message quotes both numbers so the reader who
hits it learns why.

---

## Lower bounds

`LOWER_BOUND_NOTE` (27.6%, FINDINGS.md Part 1) is in the header, in R5's
header, and in the `--json` payload; `(LOWER BOUND)` tags every dollar figure.
The before side additionally surfaces the corrected record's own `lower_bound`
string verbatim.

## Power, printed rather than inferred

A `=== POWER ===` block states n on both sides, gives R1's minimum detectable
**increase** (two-proportion normal approx, α=0.05, 80% power), R2 blocking,
R2 task and R5 minimum detectable shifts (`(z_α+z_β)·σ·√(1/n₁+1/n₂)`), says the
approximations are approximations, and ends with **"DO NOT READ SIGNIFICANCE OFF
THE TABLES ABOVE."** On the 7-task baseline it reports that the smallest
detectable rework increase is around **+69 percentage points** — which is the
point. A zero-variance before side returns *not computable*, explicitly **not**
`0.0s`, because `0.0s` would read as "any difference is detectable".

## Project partition (JEV-57)

`--project <dir>` scores one repo; `--pool-projects` pools on the record; the
two are mutually exclusive (exit 2). With neither, rows from two repos raise
`ProjectsWouldBePooled` → **exit 2** with the fix in the message.

> **Defect found and fixed while testing this.** The first cut defaulted the
> unspecified project to `assignment_ledger.LEGACY_PARTITION`, which made
> `_ledger_rows_for` *select* the legacy partition and return `[]` instead of
> raising — a pooling refusal defeated by its own default, reading as "no after
> corpus". The filter and the display label are now separate values: the filter
> stays `None` so it raises. `tests/test_report.py` pins it.

---

## The `guarded` line I need in `tests/run_all.sh`

Place it beside the other measurement tests (after `test_assignment_ledger.py`
is the natural home — it depends on that module):

```bash
echo
echo "=== JEV-06 / W5: the before/after report -- R1-R5, and 'no after corpus' is not \$0.00 ==="
guarded "test_report.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_report.py' 2>&1 | tail -4" || exit 1
```

The test binds only to `data/baseline/*.json` (read-only) and temporary
directories; it writes nothing to `spool/`, `data/` or `logs/`, and the full
suite's live-window guard confirms it.

## Suite state

`bash tests/run_all.sh` — **fully green**, run twice. `test_clean_checkout.sh`
emits `tar: src/analyze.py: Cannot stat` noise because another agent is
deleting `src/analyze.py`, `src/latency_report.py` and
`tests/test_analyze_config_join.py` in this worktree right now; that test still
reports `8 passed, 0 failed`. Not my files, not worked around.

---

## Six defects found in review, fixed before handback

All six printed a number or a sentence a reader could not have detected as
wrong. Each has a test.

1. **Orphan spend was missing from the after side's R5 numerator.** The
   anchor's `delegated_cost_usd` is *every* subagent transcript in its window;
   the live side summed only spend that joined to an assignment. Before = all
   delegated spend, after = attributed spend only — a systematic undercount of
   the treatment arm, in the one direction that flatters the layer, and exactly
   the $3.93 that `join_outcomes`' docstring records disappearing.
   `total_delegated_cost_usd` is now attributed **+** unattributed, and the
   figure's own note names the split.
2. **The no-after message asserted facts it never checked.** It printed
   *"`agent_route` is mode: off, nothing is registered, and
   `data/agent_route/assignments` holds no rows"* as a literal, whatever was
   actually passed — and it fired when a ledger held rows and the user had
   merely forgotten `--after-session`. There are now **three** states: empty
   ledger → no after corpus; rows and no transcripts → **exit 2** naming the
   count and the missing flag; and rows that join to nothing, which **cannot
   happen** because the join is intention-to-treat and an unjoined row is an
   attrition row (the branch I had written for it was unreachable code
   pretending to be a guard, and is gone). The message now prints the path it
   read and the row count it found.
3. **`--before-session` reopened the cut trap.** A transcript running past
   `cut.timestamp_utc` is post-rule work wearing a pre-rule label — still
   disjoint from a later after, so `comparable()` waved it through and the
   "before" silently contained the treatment. Now refused, exit 2, with both
   timestamps in the message.
4. **The disjointness guard was comparing timestamps as strings.** The corrected
   JSON itself mixes spellings: `2026-09-19T19:58:56.537000+00:00` and
   `2026-09-20T11:11:49Z`. `Z` (0x5A) sorts after both `.` and `+`, so an after
   side starting the same instant the before side ends compared the wrong way
   round. `parse_stamp()` now normalises both to UTC instants, and
   `side_from_sessions` takes min/max over parsed instants rather than strings.
   The whole "structurally impossible" claim rested on this comparison; it
   should not have rested on string luck.
5. **The two sides used different R5 denominators silently.** The anchor's
   count is outcomes; the live side's is assignments. Both `$/assignment` and
   `$/outcome` are now printed for both sides, with `attrition_by_tier`'s
   reason stated — they move in opposite directions when a tier's tasks die,
   and showing only the first is how a failing tier looks cheaper. The
   aggregate side's figure says in its note that its count is outcomes.
6. **R4 passed on an unmeasured latency term.** With `hook_ms` absent but an R5
   delta present, the body said "NOT zero" while the criterion said `ok`. SPEC
   §2 R4 is "added latency **and** spend" — plural — so a missing term is now
   `NOT_EVALUABLE`, which carries exit 1.

Two smaller notes taken at the same time: the R1 header now says the verdict
fires on any increase and is **descriptive at the N in the POWER block**, and
R4 states that `NET SPEND` *is* R5's delta rather than a second subtraction —
a routed task's cost already contains whatever the layer's decision billed,
fail-to-frontier premium included. A zero-variance before side returns
*not computable* from the MDE rather than `0.0s`.

## Left for whoever arms the router

- There is still no after corpus, and this module does not create one. Arming
  is a separate gated decision.
- The escalation term stays unobservable until something records an escalation.
  If RESTART is implemented, the ledger needs a field and `Side.rework` needs
  one line.
- `--before-session` does not *filter* a transcript to the pre-cut window; it
  refuses one that runs past the cut. Filtering a session mid-flight is an
  analysis decision the module does not make on the reader's behalf.
