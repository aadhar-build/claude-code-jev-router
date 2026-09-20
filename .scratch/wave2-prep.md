# Wave 2 pre-work

Investigation done ahead of wave 2 so each agent implements rather than
investigates. **Fold into `ISSUES.md` once wave 1 lands** — this lives in
`.scratch/` only because four agents currently have `ISSUES.md` open.

Facts below were verified read-only against the repo on 2026-09-20. Nothing here
was executed beyond `replay.py --estimate`, which writes nothing.

---

## JEV-16 — determinism sweep: a contradiction to resolve before running

**The ticket and the pre-registration disagree, and the pre-registration wins.**

`ISSUES.md` JEV-16 says: *"Run `replay.py --determinism 20 --arms jev` — Jev-only
costs pennies; the `cc_*` arms would cost hours and are not what is in
question."*

`PREREGISTRATION.md` §7 says: *"the determinism sweep measures how much **both**
arms wobble, which is the fairer question."*

Those are different studies. §7 is a pre-registered commitment made when the
"Jev is deterministic and the LLMs are not" hypothesis was **falsified** — the
whole point of the amended wording was that measuring only Jev would be the
unfair version. A Jev-only sweep would quietly restore the framing §7 was
written to prevent.

**Measured cost of each option** (`--estimate`, 390 stored captures, 4 enabled
arms, `--limit` default 50):

| option | calls | rough time | spend |
|---|---|---|---|
| all four arms, N=20 | **4,000** | hours | large subscription draw |
| `--arms jev`, N=20, 50 items | 1,000 | ~10 min | ~$0.012 |
| **jev N=20 (50 items) + cc_opus5 N=5 (20 items)** | **1,100** | **~20 min** | ~$0.012 + 100 subscription calls |

**Recommendation: the third.** Jev gets the full sweep because its flip rate is
the enforcement blocker and needs resolution. `cc_opus5` gets a reduced sweep
sized to answer *"does the reference wobble too?"* — which is the §7 question —
and explicitly **not** sized to say how much. State that limit in the report
rather than letting a thin estimate read as a precise one.

**Do not include `cc_haiku45` until JEV-41 lands.** Its thinking-token defect
would be measured as instability.

Other notes for the agent:
- `--limit` defaults to 50; pass it explicitly so the sample size is a decision, not a default.
- Report flip rate **bucketed by |p − τ|**. The hypothesis is that flips concentrate near τ and vanish away from it; if true, a dead-zone rule makes enforcement viable and JEV-17 has something to build on.
- 24/59 synthetic `needs_review` items sit within 0.05 of τ=0.95. That occupancy is the reason the sweep matters.
- This is wave 2's **only** `data/runs/` writer. Nothing else in the wave may write there.

---

## JEV-31b — five inert config fields: the decision for each

The hard part of this ticket is deciding what each field *should* be, not editing
it. Consumers were traced; decisions below, with reasoning.

### 1. `state_source` — **delete it from config. Do not make it live.**

Config declares it per surface; `worker.py`, `replay.py` and `canary.py` all read
the hardcoded `state_builders.STATE_SOURCE` dict. They agree today.

The instinct is to make config authoritative. **That would be actively
dangerous.** `state_source` is a *property of the state builder* — whether that
builder reads the payload or a truncated transcript — and it is written onto
every capture row as the audit trail for the future-leakage guarantee. Making it
operator-settable would let someone declare `payload` for a surface whose builder
actually reads the transcript, and the row would then *assert* leakage-safety
that does not hold. The one field that must never be configurable is this one.

Delete from `config/surfaces.json`; keep `STATE_SOURCE` beside the builders it
describes; add a comment saying why it is not configurable.

### 2 & 3. `hook_event`, `matcher` — **rename to `_hook_event` / `_matcher`, add a drift test**

Zero consumers. `.claude/settings.local.json` is hand-written and duplicates
them. Generating the registration from config is the tidier fix and is the wrong
call mid-window: it would rewrite live hook registration to remove a
documentation duplicate.

The file already uses a `_`-prefix convention for non-functional keys
(`_comment`). Renaming makes inertness visible at a glance. Then add a test
asserting the config values **match** what is registered in
`settings.local.json` — drift detection at zero runtime cost, which is the
actual risk.

### 4. `spool_backpressure_max_files` — **cannot be made live; assert agreement instead**

`capture.sh` hardcodes `500` in **two** places (the threshold test and the drop
row's `"cap":500` field). The hook is bash 3.2, no `jq`, no Python, 10ms budget —
reading JSON there is not affordable, and that constraint is correct.

So: add a test that asserts the config value equals **both** literals in
`capture.sh`. `spool_watch.cap()` already reads the config value and its
docstring already says it is the number an operator *believes* is in force;
the test makes the belief true or fails loudly.

### 5. `surfaces.json → "version"` — **record it on capture rows**

No consumer, while `pricing()["version"]` *is* recorded on every run row. Surface
config affects what is captured, so the same versioning discipline applies.
Add `surfaces_version` to the capture row rather than deleting the field.

### 6. `paths.SURFACES` — **derive it from `surfaces.json`**

A second source of truth for the surface list, iterated by tests. Derive at
import. This matters immediately: JEV-34 adds `agent_route`, and a hardcoded
tuple is one more place to forget.

---

## JEV-30 + JEV-31 — one agent, and the reap design

`JEV-33` rewrote the drain loop; read it before editing. `spool/claimed/` has
**one stranded file right now**.

**Reap design (JEV-31):**
- At startup, scan `spool/claimed/`. Return a file to `ready/` if its owning pid is dead, or it is older than a threshold.
- **A re-claimed file must be distinguishable from a first-claim one**, or a payload that kills the worker resurrects itself forever. Filename suffix is simplest and safe: the surface is parsed with `split("__", 1)[0]`, so a suffix before `.json` does not disturb it.
- **Cap the retries** (3 is reasonable) then quarantine to `dead/` with the reason recorded. A poison payload must terminate.
- `run-collection.sh status` already shows the claimed count (JEV-33 did that half).
- Recover the currently stranded capture before the window closes.

**JEV-30 (same file, same agent):**
- Log the resolved arm set, config version and each config file's mtime at startup — an operator should be able to see what the process actually loaded.
- Warn on every drain cycle if a config file's mtime is newer than the process start time. This is the defect that silently cost us `cc_sonnet5` for 1h35m.
- Document whether a mid-window config change requires a restart, or forbids itself.

**Note:** a restart is pending anyway for JEV-41's Haiku fix. Coordinate — one restart, not three, and reap `claimed/` first.

---

## JEV-37 — canary scheduler

`src/canary.py` exists and works; exit codes are already defined
(`0` clean / `1` drift / `2` baselined / `3` incomplete / `4` flip inside the τ
jitter band). The gap is only that nothing runs it.

- The wrapper is the operator's cron, outside the folder — `SPEC.md` rules out launchd deliberately, and that constraint stands.
- `canary.txt` currently **overwrites itself** and has already lost its own history. Date it like `determinism-2026-09-20.txt`.
- **A missed day must be visible.** A gap in the canary record is drift evidence lost, and an unrecorded gap silently becomes "no drift observed". Append one row per *attempted* sweep, so days covered can be counted against days in the window.
- The writeup reports the sweep calendar, and states plainly that drift is bounded only over the days actually sampled.

---

## Standing rules for every wave-2 agent

Repeated here so prompts can be shorter and no agent can miss them:

- `src/stats.py`, `src/analyze.py` and `questions/*/v1.json` are **frozen** (`PREREGISTRATION.md` §8). Any change is a defect fix, its own commit, reason stated, pre-/post-fix numbers reported.
- **Stage only your own files by explicit path.** Never `git add -A`. Other agents' work is in the same tree.
- **One `data/runs/` writer per wave.** In wave 2 that is JEV-16 and nothing else.
- Do not restart the worker without reaping `spool/claimed/` first, or the restart loses whatever was mid-flight.
- `uv run src/doctor.py` must pass; the full suite must pass before and after.
- Nothing is ever written outside this folder.

---

## JEV-42 (new, URGENT) — the test suite destroys live collection data

Found by the JEV-15 agent on 2026-09-20 while it was working around the problem.

**`tests/test_hook.sh` is destructive against a live collection window.**

- line 18: `reset(){ rm -f "$ROOT"/spool/ready/*.json ... }` — run **between assertions**
- line 58: `chmod 500 "$ROOT/spool/tmp"`

`$ROOT` is the real project root. A live worker drains real captures out of that
exact directory. **62 live captures were pending when the JEV-15 agent started
work.** `tests/run_all.sh` invokes it, so "run the test suite" is the dangerous
command — which is exactly what every agent brief tells an agent to do.

**Why it is worse than ordinary data loss, and why it belongs with JEV-31/32/33
rather than in a tidy-up pile:** a capture deleted from `spool/ready/` produces
no run row and no capture row. It never existed as far as the analysis is
concerned, so it **cannot appear in the attrition count the pre-registration
commits to reporting**. It is the fourth instance of the same shape — loss
invisible to the measurement built to catch it.

The pre-change `gates.sh` had the same defect plus worse: it moved `spool/ready`
and `logs/` aside and wrote 501 filler files into the directory a running worker
was draining. **That half is fixed** — `gates.sh` now points
`CLAUDE_PROJECT_DIR` at a throwaway root under `logs/`, and because the hook's
guards are `CLAUDE_PROJECT_DIR`-anchored the behaviour under test is unchanged.
`test_hook.sh` was left alone because another agent was active in the tree.

- [x] Give `test_hook.sh` the same sandbox treatment `gates.sh` now has
- [x] Audit **every** test file for writes to the real `spool/`, `data/` or `logs/` — `test_inline_shadow.sh` touches the kill switch and should be checked
- [x] Add a guard that makes this class of mistake loud: a test that writes to the real spool while a worker pid is live should **fail**, not silently succeed
- [x] Decide whether `run_all.sh` should refuse to run at all while a collection window is open, or always sandbox

**FIXED 2026-09-20. The standing rule below is retired:** `test_hook.sh`,
`test_inline_shadow.sh` and `run_all.sh` all sandbox now, `run_all.sh` refuses
to start if any shell test writes to the live window, and a runtime tripwire
re-checks the window after every test. Full write-up in ISSUES.md JEV-42.

~~Until it is fixed, the standing rule for every agent is: run `test_hook.sh` and
`run_all.sh` only from a throwaway copy of the tree.~~ All three wave-1 agents
still running were warned directly and asked to disclose if they had already run
it.

### Related, from the same report — a spec claim with no implementation

`docs/PLAN.md` decision #7 states the spooler records
`stat -f %z "$transcript_path"` as `transcript_bytes_at_capture`. **Nothing
produces that field.** `capture.sh` parses no JSON and cannot `stat` a path it
never reads, so GATE 4 had to *inject* the offset the hook cannot emit.

The consequence, stated plainly: the `stop` leakage path is now **verified but
not reachable in production.** The guard holds — an offsetless `stop` capture is
quarantined, which is the safe outcome — but no real `stop` capture could ever
carry the offset as the pipeline stands. This is JEV-19's known blocker seen
from the gate's side, and it should be recorded in JEV-19 as independent
confirmation rather than rediscovered a third time.

---
---

# Part 2 — re-plan, and the four tickets wave 2 has not prepared

Appended 2026-09-20, read-only against the repo at `b523902` plus the working
tree. Nothing was executed that writes: the numbers below come from reading
`data/runs/2026-09-20.jsonl` and `data/captures/2026-09-20.jsonl` with a
throwaway `python3 -c`, and from `ls`/`git`. **Part 1 above stands except where
this part names a correction** — several of its claims were true when written
and are not true now.

## 0. Corrections to Part 1 and to the tickets, before anything is planned

Each of these changes what a wave-2 agent should do, so they come first.

**`spool/claimed/` is NOT stranded right now.** Part 1 says "one stranded file
right now" and JEV-31 says "one sitting there right now, claimed at 17:28".
Neither holds. `claimed/` currently contains exactly one file which is the
capture *being dispatched*: it was `pre_bash__2474-20808.json` at 15:30Z and
`pre_bash__4263-221.json` ninety seconds later. `spool/dead/` is empty.
**The wave-2 agent must not assume a file in `claimed/` is stranded** — see §3,
where this is the whole reason an age-based reap is unsafe.

**The JEV-41 restart has already happened.** Part 1 says "a restart is pending
anyway for JEV-41's Haiku fix. Coordinate — one restart, not three." It is
done: the running worker is pid 94441, started 15:15Z, and **26 rows already
carry `cc-haiku45-cli-v2-nothink`**. `PREREGISTRATION.md` A7.4 records the
boundary correctly; **ISSUES.md JEV-41 still says "the boundary is the worker
restart, which has NOT happened", and is stale.** The 30+31 agent therefore
owns a restart of its own — a cheap one, because it changes no arm config and
so creates no fourth era boundary.

**`canary.py` is a `data/runs/` writer.** Part 1 and the execution plan both
treat JEV-16 as wave 2's single writer. `canary.run_sweep` calls
`store.append_capture` and emits run rows with `run_context: "canary"`
(`src/canary.py:278-298`), 21 rows per sweep per arm. JEV-37's whole deliverable
is *running that daily*. The one-writer rule cannot survive JEV-37 as literally
written; §1 amends it rather than quietly breaking it.

**`PREREGISTRATION.md` A6.1's loss bound is wrong by 3.5x.** A6.1 bounds the
test-suite data loss with "the observed high-water mark for the window is
**20**". `data/spool_watermark.json` records **`max_total: 71` at
2026-09-20T14:36:24Z** — inside the 14:10Z–15:05Z destruction window. It is a
real backlog, not a test artifact: 56 captures were drained between 14:30Z and
14:50Z at a steady ~3/min, which is a queue being worked off after concurrent
dispatch went live at 14:24Z, and `dead/` is empty so no filler file was ever
claimed. The bound is "at most ~71 per reset", not "at most 20". *This is the
operator's file to amend; it is reported, not fixed.*

**`tests/test_hook.sh` is worse than Part 1 records.** Part 1 says the
501-filler-file behaviour was gates.sh's and "that half is fixed". It moved
rather than died: **`tests/test_hook.sh:85` writes 501 filler files straight
into the live `spool/ready/`.** Consequences, in order of how badly they are
missed: the live worker quarantines all 501 into `spool/dead/` (harmless —
`surface_mode("filler")` returns `"off"`, it does not crash); but
`spool_watch.sample()` fires on every claim, so the run **permanently poisons
the monotonic high-water mark** — the exact statistic A6.1 uses to bound the
earlier loss. And `test_hook.sh:40` plus `test_inline_shadow.sh:178-180`
`rm -f` the real `.jev-disabled`, so running the suite **silently turns capture
back on for an operator who had deliberately switched it off.**

**The canary's own docstring is one exit code short.** `src/canary.py` defines
`EXIT_JITTER_ONLY = 4` and returns it, and the `argparse` description names it —
but the module docstring lists only 0-3. A JEV-37 wrapper written from the
docstring would treat a τ-band flip as an unhandled code.

**`determinism.py` pools live and synthetic repeat groups.** `analyse()`
(`src/determinism.py:265`) filters groups on `(arm, question)` only, while the
single-shot occupancy half is carefully keyed by `run_context` with a comment
citing §4's no-pooling rule. The repeat half has no such guard. §2 works around
it by drawing the sweep from one context.

**`replay.py --determinism` cannot select its items.** `run_determinism` takes
`store.captures()` filtered by surface and sliced `[:limit]` — file order, all
contexts pooled, no stratification, no `--sample`. JEV-16 says "over a
stratified sample"; **the code has no such affordance.** §2 makes adding one a
prerequisite.

**`replay._emit` is sequential and correctly omits `arm_dispatch`** — checked,
because `worker.py`'s docstring asserts it and a JEV-33 regression there would
have silently mislabelled the era on every sweep row. It is a plain `for` loop
over `worker.evaluate_one`. The docstring is true.

**JEV-42's heading is absent from `ISSUES.md` as I read it.** Another agent has
it out of the file right now. Everything this document says about wave 1b's
scope comes from the briefing prompt and from reading the code, **not from the
board** — re-check it against `ISSUES.md` once that edit lands.

**`git add -A` would sweep `.scratch/` in.** `.scratch/` is not in
`.gitignore`; `.scratch/wave2-prep.md` is *tracked*, `.scratch/jev41/` is
untracked. This is in the standing brief for a reason.

---

## 1. Revised wave plan

Five tickets arrived after the plan was written: 41 (done), 42 (in progress
now), 43, 44, and this document's own 31b. The constraints are unchanged — at
most four agents, no two agents on one file, one `data/runs/` writer per wave,
one new surface registration per collection window — with the third one amended
below because JEV-37 makes it unsatisfiable as written.

### The amendment to the one-writer rule

The rule as written is already false: **the live worker is an unconditional,
permanent `data/runs/` writer** and has been since 2026-09-20T06:34Z. What the
rule actually protects is attributability of attrition — that when rows are
missing, you can name the process that should have written them. So:

> **One *additional, unlabelled* `data/runs/` writer per wave.** Rows carrying
> a `run_context` other than `"live"` and a `sweep` tag are exempt: they are
> excluded by §4 from every analysis, they join to nothing, and their absence
> or presence cannot move an attrition count.

Under that reading `canary.py` is exempt (21 `run_context: "canary"` rows per
day, `jev` only, ~$0.005) and JEV-37 can be scheduled. **This is a rule change,
not a reading of the old rule**, and it should go into `ISSUES.md`'s execution
plan as such.

### The table

| wave | tickets | agents | writer | why |
|---|---|---|---|---|
| **1** | 33, 38+24a, 15, 40 | — | — | **landed.** 41 also landed out of band |
| **1b** | **42** | 1 | none | **running now.** It owns `tests/` exclusively, and it is the ticket that makes every other agent's "run the suite" instruction safe. Nothing may share `tests/` with it |
| **2** | **30+31** (one agent), **31b**, **16**, **37** | 4 | **16** | membership deliberately UNCHANGED — see below |
| **3** | **44**, 22, 34, 27 | 4 | 22 | 44 trails 42 (same files). 32 displaced. **`tests/gate4_drain.py` belongs to 34**, not 44 — 34 extends GATE 4 to `agent_route`; 44 hands it the PEP-723 header text to paste |
| **4** | 28, 29, 17, 10 | 4 | 10 | unchanged. 17 unblocks from 16 in wave 2 |
| **5** | 35, 25, 39, **43** | 4 | none | 43 lands the wave *before* 36 needs it. 12 displaced |
| **6** | 36, 24b, 18, **32** | 4 | none | 18 is this window's surface registration |
| **7** | 23, 19, **12** | 3 | 23 | 19 is this window's surface registration |
| **8** | 20, 09 | 2 | — | see the caveat below |

**Wave 2's membership does not change, and that is a decision.** I considered
swapping JEV-43 in for JEV-37, on the grounds that 43 is analysis-only, has zero
file conflicts and gates the publication of latency numbers that JEV-33 and
JEV-41 are *already quoting*. I decided against: **every day JEV-37 waits is a
day of the drift window that can never be sampled**, and the window runs to
2026-10-20. JEV-43's inputs are rows on disk that are not going anywhere. An
unsampled day is the only irreversible item in the set.

**What moved, and why — nothing is reshuffled silently:**

- **42 gets its own slot (1b) rather than joining wave 2.** It is in progress
  as of now and it owns `tests/run_all.sh`, `tests/test_hook.sh` and
  `tests/test_inline_shadow.sh`. JEV-44 touches `tests/run_all.sh` and the
  PEP-723 headers of every test module. Those are the same files. They cannot
  be concurrent, so 44 goes to wave 3.
- **43 goes to wave 5, taking JEV-12's slot; 12 slips to wave 7.** 43 blocks
  JEV-36 (wave 6), which reports wall-clock as a co-primary; landing 43 in the
  wave immediately before 36 is the latest point at which it is still free.
  JEV-12 draws figures from JEV-10's sweeps (wave 4) and is indifferent to
  which later wave it sits in.
- **32 slips from wave 3 to wave 6.** It is the lowest-urgency ticket on the
  board by its own admission — "harmless today: nothing has moved, and all 660
  rows carry `pre_bash/v1#a`" — and it touches frozen `analyze.py`, so it needs
  a solo commit with pre-/post-fix numbers whenever it lands. Wave 6 also keeps
  it away from JEV-39, the other `analyze.py` ticket, which stays in wave 5.
- **The routing chain 34 → 35 → 36 → 23 is untouched**, across waves 3, 5, 6, 7.
  It was already the plan's deliberate non-parallelisation and nothing here
  gives a reason to compress it.

**One unresolved hazard, flagged rather than papered over.** Wave 8 pairs
JEV-20 (registers `post_edit`) with JEV-09 (registers `inline_shadow_bash.sh`
alongside `capture.sh` on the already-live `pre_bash`). That is arguably two
registrations in one window. My reading is that it is not: 09's hook emits
nothing, writes no row and adds no capture stream, so it cannot make the
capture stream uninterpretable — which is what the one-at-a-time rule exists to
prevent. But it *does* add ~624ms to every Bash call in the operator's own
sessions, which is a live-behaviour change landing in the same window as a new
surface. **If the owner reads the rule as being about live-behaviour changes
rather than capture streams, 09 needs a wave 9 of its own.** I do not have
enough to decide that for them.

### File ownership in wave 2, explicitly

| agent | owns | must not touch |
|---|---|---|
| **30+31** | `src/worker.py`, `run-collection.sh`, `src/spool_watch.py` | `config/*`, `src/paths.py` |
| **31b** | `config/surfaces.json`, `src/paths.py`, `src/state_builders.py`, new tests | `src/worker.py` |
| **16** | `src/replay.py`, `src/determinism.py`, `reports/` | `src/worker.py`, `config/*` |
| **37** | new `bin/canary-daily.sh`, `src/canary.py`, `docs/`, `reports/window/` | everything above |

**One handoff, because two tickets want one line of `worker.py`.** JEV-31b's
"record `surfaces_version` on rows" item lands in `process_capture`'s
`capture_row` dict (`src/worker.py:195-211`), which the 30+31 agent owns.
**The 31b agent specifies the field and the 30+31 agent adds the line**, in the
30+31 commit, credited to 31b. Everything else in 31b — deleting `state_source`
from config, `paths.SURFACES`, the `_hook_event`/`_matcher` rename, the
backpressure-literal test — stays clear of `worker.py`, because `worker.py`
already reads `sb.STATE_SOURCE[surface]` and not the config value.

---

## 2. JEV-16 — the run plan, reconciled with Amendment 7

**This supersedes Part 1's JEV-16 section.** Part 1's three-row option table
recommended "jev N=20 (50 items) + cc_opus5 N=5 (20 items)" and said to hold
`cc_haiku45` back until JEV-41 landed. JEV-41 has landed, A7.5 was written
after Part 1, and the item-selection problem below was not known then. **Run
the plan in this section, not that one.**

**The ticket is now wrong twice over, in opposite directions.** Part 1 recorded
the first contradiction: the ticket says `--arms jev` while §7 commits to
measuring how much *both* arms wobble. A7.5, written later the same day, adds
the second: **`cc_haiku45` has no determinism baseline, and without one "the
configuration changed the answer" and "the model is non-deterministic" are the
same number.** That is the only thing on the board blocking a clean ruling on
whether the 334 live v1 Haiku rows are usable for agreement. A7.5 names the
remedy explicitly — "the cheap purchase that would close this properly is a
determinism sweep on `cc_haiku45` at v2".

So JEV-16 is not one sweep. It is three, with different purposes, different N
and different item sets, and the ticket's single line understates it by a lot.

### Prerequisite: a one-function change to `replay.py`, before any spend

`run_determinism` (`src/replay.py:190`) selects items as
`[c for c in store.captures() if c["surface"] == surface][:limit]` — **file
order, every `run_context` pooled, no stratification.** There is no `--ids` and
no `--sample`. Today the first 50 `pre_bash` captures happen to be 48 synthetic
and 2 live, because the synthetic run was written first; that is an accident of
file order that one more synthetic run destroys, and it silently mixes 2 live
items into a synthetic sweep either way.

`replay.py` is **not** frozen (§8 freezes `stats.py`, `analyze.py` and
`questions/*/v1.json` only). Add:

```
--ids ID[,ID...]         explicit decision_ids, in the order given
--context {live,synthetic,canary}   filter store.captures() before --limit
```

and thread both through `run_determinism` **only**. Do not change `_emit`'s
signature: `canary.py` calls it, and JEV-37 owns that file in the same wave.
~15 lines. **Do this first**, so
that which items were swept is a recorded decision rather than a property of
file ordering.

### Why the item set matters more than N, with the numbers

Occupancy within 0.05 of τ, from the single-shot `jev` rows on disk:

| question | τ | synthetic (n=59) | **live (n=426)** |
|---|---|---|---|
| `destructive` | 0.36 | 3 (5.1%) | **0** |
| `needs_review` | 0.95 | **24 (40.7%)** | **9 (2.1%)** |
| `needs_review` | 0.50 | 5 | 62 (14.6%) |

**The 41%-occupancy concern JEV-16 is written to resolve is a property of the
balanced synthetic set, and the live workload sits at 2.1%.** That is a finding
in itself and it changes the enforcement conclusion: even a bad flip rate
inside the band costs little if the band is 2% of real traffic. The sweep must
run on the **synthetic** set — it is where the near-τ items are, live
`destructive` has literally none — and the report must state the live occupancy
beside the synthetic flip rate rather than letting the 41% carry the argument.
Drawing from one context also sidesteps `analyse()`'s live/synthetic pooling.

### The three runs

**Run A — `cc_haiku45` at v2, N=10, the nine JEV-41 paired states. 90 calls,
~10 min, subscription.**
`--ids syn-0000,syn-0001,syn-0002,syn-0120,syn-0121,syn-0122,syn-0240,syn-0241,syn-0242`
— the exact states `.scratch/jev41/results.jsonl` used for the v1-vs-v2 paired
probe, three per stratum. **This must be v2 (`cc-haiku45-cli-v2-nothink`), and
the report must say so**; the arm has been v2 since the 15:15:33Z restart and
`config/arms.json` already carries `max_thinking_tokens: 0`, so a plain run
gets v2 — but the `arm_config_id` on the rows is the thing to assert, not the
clock. Purpose: a **within-configuration** |Δp| and flip rate on the same nine
states where the cross-configuration figures are 0.078 and 1-in-18. Anything
else is a proxy; these nine make the comparison exact. If within-config |Δp| on
these states is comparable to 0.078, the v1 rows survive as a labelled v1-era
measurement and A7.5's caveat can be tightened from "not distinguishable" to a
number. At N=10 the flip estimate is coarse and the report must say so.

**Run B — `jev`, N=20, the 60 synthetic items. 1,200 calls, ~12 min, ~$0.018.**
`--context synthetic --limit 60 --determinism 20 --arms jev`. There are **60**
synthetic `pre_bash` captures; the 59 that appears throughout the board and in
the occupancy table above is the count of `ok: true` `jev` rows, one item
having failed. Sweep all 60 and let the sweep say whether the 60th is
reproducibly bad. This is the
enforcement blocker and the input JEV-17 (wave 4) needs. Jev's median wall is
0.57s and `_emit` is serial, so ~11 minutes. Report flip rate bucketed by
|p − τ| at all of τ=0.5, 0.36 and 0.95 — `determinism.py` already evaluates
`DEFAULT_TAUS` side by side and prints `n<5` instead of a rate in a thin
bucket, which is the behaviour that makes a 59-item sweep publishable at all.

**Run C — `cc_opus5`, N=5, the 20 items nearest τ. 100 calls, ~9 min,
subscription.** This is §7's commitment and nothing else — it answers *"does
the reference wobble too?"* and is explicitly **not** sized to say how much.
State that limit in the report rather than letting a thin estimate read as
precise. Selection rule, stated so it is a decision rather than a default: **the 10
items nearest τ=0.95 on `needs_review` plus the 10 nearest τ=0.36 on
`destructive`**, ranked by |p − τ| over the synthetic single-shot `jev` rows,
ties broken by `synthetic_id`. Pass them with `--ids` and record the list.

| | calls | wall | spend |
|---|---|---|---|
| A `cc_haiku45` v2, N=10 x 9 | 90 | ~10 min | subscription |
| B `jev`, N=20 x 60 | 1,200 | ~12 min | **~$0.018** |
| C `cc_opus5`, N=5 x 20 | 100 | ~9 min | subscription |
| **total** | **1,390** | **~31 min** | ~$0.018 + 190 subscription calls |

For contrast, all four arms at N=20 over 50 items is **4,000 calls and several
hours** — that is the option the ticket rules out, and it is right to.

**Order: A, then B, then C.** A first because it is the only one unblocking a
ruling that is live today (A7.5, 334 rows). B second because it is cheap and it
is the ticket's own stated blocker. C last because it is the one that can be
shortened if subscription quota is tight — and **if it is shortened, the report
says so**, rather than reporting a thinner sweep as if it were the planned one.

### Two hazards inside `determinism.py` the agent must know

1. **The group key omits `arm_config_id`.** `collect()` keys on
   `(decision_id, arm, question_set_id, state_sha256, question)`
   (`src/determinism.py:168`). Re-running a Haiku sweep on the same nine states
   after any future config bump would pool v1 and v2 repeats into one group and
   **report the configuration change as non-determinism** — precisely the
   conflation A7.5 is about, reproduced inside the instrument built to resolve
   it. `determinism.py` is not frozen: **add `arm_config_id` to the key.** Two
   lines, and it makes the tool correct rather than merely correct-today.
2. **`if designed:` is global per surface** (`src/determinism.py:189`). The
   moment Run A lands, every incidental repeat group for *every* arm on
   `pre_bash` is discarded in favour of designed sweep rows. That is the right
   behaviour and it is worth knowing: after Run A and before Runs B and C, a
   `determinism.py` report shows Haiku and nothing else. Do not read that as a
   regression.

---

## 3. JEV-30 + JEV-31 — the reap, designed against the post-JEV-33 worker

### Where the claim happens, and what is and is not recorded

`src/worker.py:275-279`, inside `drain_once`:

```python
spooled = claimed_dir / candidate.name
candidate.rename(spooled)
```

The claimed name is `candidate.name` unchanged — which `hooks/capture.sh:102,110`
built as `{SURFACE}__{hookpid}-{RANDOM}.json`. **The pid in that filename is the
*hook's* pid, not the worker's**, so Part 1's reap rule ("return a file to
`ready/` if its owning pid is dead") cannot be implemented: there is no owning
pid on disk anywhere. That is the first thing to fix, and it is what makes the
rest possible.

Nothing else in the tree moves a file out of `claimed/`. `drain_once:303`
unlinks on success; `_quarantine:324` renames to `dead/`. `spool_watch.depth()`
counts the directory and `report()` prints it with the JEV-31 warning, so
`run-collection.sh status` *does* already surface the backlog — Part 1 is right
about that half.

### Why files strand at all — the root cause the tickets do not name

`run-collection.sh:38` stops the worker with a bare `kill`, i.e. **SIGTERM**.
`worker.main()` catches **only `KeyboardInterrupt`** (`src/worker.py:366`),
which is SIGINT. Python's default SIGTERM disposition terminates the process
immediately — mid-`_dispatch`, with the file already renamed into `claimed/`
and a thread pool holding four in-flight `claude -p` calls. **A stop that lands
mid-dispatch strands exactly one capture, by construction** — a stop during an
idle poll strands nothing, but dispatch is ~16.5s of every 30s cycle during
active work, so most stops land badly. That is why the board records a
hand-reap at the 12:07Z restart *and* another at the 14:24Z restart — "again",
as JEV-33 puts it.

So the fix has two halves and a startup reap is only the crash half:

**(a) A graceful stop.** Install a `SIGTERM` handler that sets a flag checked
between captures in `drain_once`'s loop; the in-flight capture finishes and the
process exits with `claimed/` empty. Honest cost, which `run-collection.sh`
must print rather than appearing hung: a stop can now take up to one dispatch,
bounded by the slowest arm's `timeout_s` — **180s for the `cc_*` arms, 240s for
`cc_fable51`**. Give `stop` a bounded wait loop and a message saying so.

**(b) A startup reap**, for the case where the worker was killed, OOM'd or
crashed.

### The claim marker, and how a retry counter survives `__`

Encode ownership on the rename:

```
{original_stem}__p{worker_pid}__t{claim_epoch}__r{retries}.json
```

This is safe against every existing consumer, all checked:

- `worker.py:281` parses the surface as `spooled.name.split("__", 1)[0]` —
  **non-greedy from the left**, so it still yields `pre_bash` regardless of how
  many `__` groups follow. This is exactly the property Part 1 identified, and
  it holds for a suffix as well as for the simple one it imagined.
- `spool_watch._count` globs `*.json`; the extension is preserved.
- `_quarantine` renames the whole name into `dead/` and writes
  `{name}.reason` beside it, so a quarantined re-claim carries its retry count
  into `dead/` for free — which is the audit trail JEV-31's last checkbox asks
  for.

Parse it back with
`^(?P<base>.+?)__p(?P<pid>\d+)__t(?P<t>\d+)__r(?P<r>\d+)\.json$` (non-greedy
base). **A file in `claimed/` that does not match is a pre-JEV-31 claim** —
there is one there right now on every drain — and is treated as
`pid=unknown, r=0`.

### The reap rule — pid liveness first, age never on its own

1. `pid == os.getpid()` → skip. Ours, in flight.
2. `os.kill(pid, 0)` succeeds → **never touch it, at any age.** Another worker
   owns it.
3. pid dead → reap: strip `__p/__t/__r`, `r+1`, rename back to `ready/`.
4. `r+1 >= 3` → `_quarantine(..., "reaped 3x without completing")` to `dead/`.
5. unparseable name (the legacy case — **including the one file the 30+31
   agent's own restart will create**, since that restart runs the old code) →
   **reap unconditionally, with a log line.** Do **not** gate it on age:
   `rename()` preserves `mtime`, so a capture that waited in a 71-deep `ready/`
   backlog is claimed carrying an mtime twenty minutes old, and any threshold
   reaps it while it is live. `st_ctime` does move on rename under APFS and
   would work, but the simpler argument is the better one: the reap runs at
   **startup only**, and `run-collection.sh` pidfile-guards against a second
   worker, so an unparseable claim seen at startup is stranded *by definition*.
   Gating it on age is how JEV-31 survives its own fix — the legacy file this
   very restart creates has a fresh mtime and would sit in `claimed/` until the
   restart after next.

**Age alone is wrong, and I watched it be wrong.** With a live worker draining,
`claimed/` went `pre_bash__2474-20808.json` → `pre_bash__4263-221.json` inside
ninety seconds; any threshold under ~5 minutes would eventually catch a capture
that was mid-dispatch. State the residual risk rather than engineering it away:
**pid reuse can make a dead owner look alive**, in which case the file is left
in `claimed/` and reported in the status line rather than reaped. A stranded
file that is *visible* is a much smaller problem than the one this ticket is
about.

### What breaks if a reap races a live claim — the reason for rule 2

Reaper renames F back to `ready/` while its owner is still dispatching. The
owner finishes, writes its rows, and calls `spooled.unlink(missing_ok=True)` —
**which does not raise**, because the reaper already moved the file. Meanwhile
the next drain cycle claims F again and evaluates the identical bytes a second
time.

**The result is not attrition, it is inflation, and it is invisible.** Two full
sets of well-formed run rows exist under two `decision_id`s, sharing a
`state_sha256`. The §5 assertion that all arms for a decision share a state hash
still passes — the duplicates are *legitimately* identical. The clustered
bootstrap counts one decision point as two and its independence assumption is
quietly false. This is the fourth instance of the shape the board keeps
finding, and it is worth saying that the fix introduces it rather than
discovering it later.

Two mitigations, both cheap: **rule 2 above**, and **reap at startup only**,
before the first `drain_once`, when nothing in this process is in flight. Each
drain cycle then does a *read-only* count of `claimed/` for the status line and
reaps nothing.

### JEV-30, whose scope is wider than the ticket says

JEV-30 is written as though only `config/arms.json` goes stale. **Three files
do.** `config_loader.surfaces()`, `pricing()` and `question_set()` are all
`@functools.cache`d (`src/config_loader.py:23,97,102`), so a mid-window change
to a surface's `mode`, to the backpressure cap, or to a pricing rate is stale
until restart just as the arm set was — and `pricing()["version"]` is written
onto every row, so a stale pricing cache mislabels provenance as well as
arithmetic. `arms_config()` is the one that is *not* cached, and it is still
stale, because `worker.main():347` resolves the arm list once at startup.

- **At startup**, log: process start time, resolved arm names with their
  `arm_config_id`s, and for each of `arms.json`, `surfaces.json`,
  `pricing.json` the mtime (ISO/UTC), size and `sha256[:12]`.
- **Every drain cycle**, `stat` the three and print a WARNING naming any file
  whose mtime is newer than process start, with the delta. **Every cycle, not
  once** — a warning printed once at 04:00 scrolls out of a multi-day log,
  which is the same failure mode as the original defect. Three `stat`s per 30s
  is free.
- **Document the policy**, which the evidence has already chosen: *a mid-window
  config change requires a restart, and the restart is an era boundary that is
  recorded in `PREREGISTRATION.md` before it is made.* Not forbidden — A7.4's
  Haiku fix was right to happen — but never silent. Three boundaries exist for
  exactly this reason.
- **JEV-31's last checkbox — "report whether any other captures were lost this
  way" — has an answer, and it is "unknowable".** `dead/` is empty; `claimed/`
  holds only in-flight work; two strandings are recorded in the board and both
  were hand-reaped. But a hand-reap leaves no trace either, and nothing has ever
  counted a claim. **Report "at least two, both recovered; no mechanism existed
  to count the rest", not zero.**

---

## 4. JEV-37 — the canary scheduler

`src/canary.py` works and is baselined on `jev` (reference sweep
`01M2ZB4HDS8NTJZ3CX0P9FGNJX`; 42 canary rows on disk = two sweeps). The gap is
only that nothing runs it — and, as §0 notes, that its docstring is a code
short.

### The exit-code contract, read from the code

`src/canary.py:98-102` and the return order in `main():687-700`:

| code | constant | means |
|---|---|---|
| **0** | `EXIT_CLEAN` | a reference existed, today's sweep matched within tolerance |
| **1** | `EXIT_DRIFT` | model string changed, mean \|Δ\| over `--threshold`, or a flip at τ outside the jitter band |
| **2** | `EXIT_NO_REFERENCE` | nothing usable to compare against; today's sweep is now the baseline |
| **3** | `EXIT_INCOMPLETE` | today's sweep has failed or missing rows. **Not a comparison** |
| **4** | `EXIT_JITTER_ONLY` | a flip within ±0.05 of τ and nothing else. Surfaced deliberately, not suppressed, and deliberately not 0 |

Precedence is `incomplete → drift → jitter → unbaselined → clean`, which is
load-bearing: **an incomplete sweep must never be readable as clean.** The
wrapper must not collapse 2 into success (it means "had nothing to check") and
must not collapse 4 into failure (it is consistent with the non-determinism
already on the record). Anything else is a wrapper bug and exits distinctly.

### The wrapper

`bin/canary-daily.sh`, in the repo; the crontab line lives outside it, which is
the point SPEC.md is making by ruling out launchd.

```bash
#!/bin/bash
# JEV-37. The operator's daily drift check. Cron owns the schedule; this owns
# the record. Exits 0 on clean/baselined/jitter, 1 on drift or incomplete, so a
# cron MAILTO fires on exactly the two states a human must look at.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DAY="$(date -u +%Y-%m-%d)"
START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
LOGDIR="$ROOT/reports/window"
SWEEPLOG="$LOGDIR/canary-sweeps.jsonl"
mkdir -p "$LOGDIR" "$ROOT/logs"      # canary.py --out does NOT mkdir a subdir

rc=99                                 # "the wrapper died"; overwritten below
# The trap, not the happy path, writes the record: a day that crashed, was
# killed, or ran out of disk must still appear as an ATTEMPT. A missing line
# means nobody tried, and that is the only thing it may mean.
record() {
  case $rc in
    0) v=clean ;; 1) v=DRIFT ;; 2) v=baselined ;; 3) v=incomplete ;;
    4) v=jitter_flip ;; 77) v=disabled ;; *) v=wrapper_error ;;
  esac
  printf '{"day":"%s","started_at":"%s","exit":%d,"verdict":"%s","report":"window/canary-%s.txt"}\n' \
    "$DAY" "$START" "$rc" "$v" "$DAY" >> "$SWEEPLOG"
}
trap record EXIT

# The kill switch means the experiment is off. A suppressed day is a RECORDED
# day, not a silent one -- otherwise the calendar cannot tell "switched off"
# from "cron broke". Same fail-safe test as every hook (JEV-40).
if [ -e "$ROOT/.jev-disabled" ] || [ -L "$ROOT/.jev-disabled" ]; then
  rc=77; exit 0
fi

cd "$ROOT" || { rc=99; exit 1; }
# NOT bare `python3`. Cron's PATH is /usr/bin:/bin, so that is Apple's pre-3.12
# python3 -- under which src/arms/jev.py:237 is a SyntaxError (JEV-44). It is
# swallowed by evaluate_one's `except Exception`, every call becomes ok:false,
# the sweep exits 3, and the operator gets a DAILY "incomplete" alarm that
# spends nothing and means nothing. Absolute path, matching the live worker.
PY="${JEV_PYTHON:-/opt/homebrew/bin/python3}"
[ -x "$PY" ] || { rc=99; exit 1; }

"$PY" src/canary.py --out "window/canary-$DAY.txt" \
  >> "$ROOT/logs/canary-$DAY.log" 2>&1
rc=$?

# "the canary failed to start" must not share a verdict with "the canary found
# something". If no report was written, no sweep happened, whatever rc says.
[ -s "$LOGDIR/canary-$DAY.txt" ] || rc=99

case $rc in 1|3|99) exit 1 ;; *) exit 0 ;; esac
```

Crontab, which the ticket should print for the operator to paste:

```
17 9 * * * /Users/aadharagarwal/projects/JEV-experiments/bin/canary-daily.sh
```

Three details that are not obvious from the ticket:

- **`--out` takes a name relative to `reports/` and the code only `mkdir`s
  `reports/` itself** (`src/canary.py:681`), so `window/canary-$DAY.txt`
  requires the wrapper's `mkdir -p`. Without it the sweep runs, spends, prints
  — and then throws on the write.
- **`--out` overwrites.** This is the defect JEV-39 records against
  `reports/canary.txt`, which "has already lost its own history". Dating the
  name is the fix, and `reports/` is tracked, so the series lands in git.
- **The kill switch deserves a verdict of its own.** Nothing in the ticket says
  what the canary should do when the experiment is switched off. Spending
  subscription quota on a switched-off experiment is wrong; so is a silent gap.
  `verdict: "disabled"` is an attempted, recorded, unsampled day.

### How a MISSED day becomes visible

`reports/window/canary-sweeps.jsonl`, **one line per attempt**, written by the
trap so it survives a crash or a kill. A day with no line is a day nobody tried
— and that is the only thing it can mean.

Then a `--calendar` mode (20 lines, in `canary.py` or beside it) that reads the
sweep log against the pre-registered window (2026-09-20 → 2026-10-20) and
prints days attempted / clean / drifted / jitter / incomplete / disabled /
**MISSED**. It must **refuse to print "no drift observed"** as a bare phrase.
The only sentence it may emit is:

> no drift observed on N of M days; M−N days were not sampled and drift over
> those days is not bounded by this instrument.

That is the honest answer JEV-37's last checkbox asks for, and writing it into
the tool rather than into the writeup is what stops it being dropped when
someone is summarising. The writeup then quotes the calendar rather than
restating it.

---

## 5. JEV-43 — what is computable today, measured

**Short answer: the decomposition the ticket asks for is fully computable from
rows already on disk, and the contamination is larger and more structured than
the ticket assumes. No new collection is needed for the primary deliverable.**

### Field availability, checked on all 1,633 rows

`raw.duration_api_ms` is present on **every `ok: true` `cc_*` row** — 1,047 of
1,047. The 90 `cc_*` rows lacking it are **all** `ok: false` (30 per arm),
which is correct: a failed call has no API duration. So A5.3's premise holds.

**The ticket understates what is on the row: there are three clocks, not two.**

| field | what it measures |
|---|---|
| `timing_ms.total_ms` | our `subprocess.run` wall, spawn to exit |
| `raw.duration_ms` | the CLI's **own** self-reported total |
| `raw.duration_api_ms` | API time only |

That third clock splits the residual the ticket treats as one lump:

- **`total_ms − duration_ms` = process spawn + teardown**, outside anything the
  CLI can see. This is A5.3's spawn-contention term, and it is now *measured*
  rather than asserted.
- **`duration_ms − duration_api_ms` = in-session, non-API time** — where the
  operator's hooks live, because a hook fires inside the spawned session.

### The numbers, per arm, per era, per `arm_config_id`

Medians in ms; "spawn" = `total−duration`, "in-session" = `duration−api`.

| arm / config / era | n | total | api | spawn | in-session p50 | p95 | max |
|---|---|---|---|---|---|---|---|
| `cc_haiku45` v1 seq | 315 | 12,090 | 10,452 | 1,079 | 294 | 18,526 | 22,035 |
| `cc_haiku45` v1 conc | 86 | 12,786 | 10,514 | 1,252 | 341 | 18,772 | 19,293 |
| `cc_haiku45` **v2** conc | 26 | 5,749 | 4,196 | 1,248 | 342 | 432 | 765 |
| `cc_opus5` seq | 315 | 4,891 | 3,476 | 1,087 | 286 | 574 | 21,893 |
| `cc_opus5` conc | 112 | 5,013 | 3,321 | 1,258 | 347 | 18,682 | 18,730 |
| `cc_sonnet5` seq | 78 | 2,870 | 1,462 | 1,086 | 276 | 547 | 625 |
| `cc_sonnet5` conc | 112 | 3,123 | 1,508 | 1,260 | 340 | 628 | 18,798 |

Three results fall straight out:

**1. A5.3's spawn-contention term is ~170ms, not seconds.** Spawn is 1,079-1,087ms
sequential and 1,248-1,260ms concurrent, on all three arms alike. The commitment
to "quantify the bias rather than assert it is small" is discharged: it *is*
small, and now it is measured. **This makes A5.3's disclosure stronger, not
weaker** — the bias it flagged is real and bounded at ~0.17s per `cc_*` call.

**2. The in-session residual is bimodal, not a distribution with a fat tail.**
The p50 is ~0.3s across every arm and era, and the outliers cluster at
**18.5-18.8s** — a near-constant value, which is the signature of a fixed-cost
operation or a timeout, not of variable load. 55 of 1,047 rows (**5.3%**) exceed
5s of in-session residual, totalling **1,041 seconds** of wall-clock that
belongs to nothing in this study.

**3. It fires per subprocess, not per decision.** 55 contaminated rows across 46
distinct decisions: 39 decisions had exactly one arm hit, 5 had two, 2 had
three. So it is not a machine-wide stall that the concurrency would spread
evenly — each `claude -p` rolls its own dice.

Incidence by arm: `cc_haiku45` 30/428 (7.0%), `cc_opus5` 20/428 (4.7%),
`cc_sonnet5` 5/191 (2.6%). **Do not report that ordering as a finding** — the
counts are small and the obvious mechanism (a longer-lived session has more
opportunity to trip it) is confounded with the arm. It is a hypothesis for the
agent to test, not a result.

### Two corrections to the ticket's diagnosis

**The source is not a user-level settings hook.** JEV-43 attributes it to "a
user `Stop` hook". Both `~/.claude/settings.json` and
`~/.claude/settings.local.json` have an **empty `hooks` block**. And the arm
already passes `--strict-mcp-config --mcp-config '{"mcpServers":{}}'`
(`src/arms/claude_cli.py:141`), so MCP server startup is ruled out too. That
leaves a **plugin-registered hook** (`~/.claude/plugins/` is populated) or
something else inside the spawned session. **The agent's first step is to
identify it, not to assume it** — and the near-constant 18.7s is the strongest
clue available.

**It is not historical.** The contamination continues after the 15:15:33Z
restart: 2 of 152 post-restart `cc_*` rows are hit, both at 15:35:58Z, both at
18.7s, **and both in the same decision**. The rate dropped from 5.3% to 1.3%,
which is either a real change or 152 rows of noise. The ticket's "no `cc_*`
wall-clock figure is published until the residual is characterised" therefore
binds on rows still being collected, not only on the back catalogue.

### The publishable number — a decision, with its cost

**Report `total_ms`, with rows whose in-session residual exceeds 5s excluded and
counted, per arm and per era.** Not `duration_api_ms`, which drops the ~1.1s
spawn A5.3 commits to reporting; not raw `total_ms`, which carries 1,041s of
somebody else's automation; and **not `total_ms` minus the whole in-session
term**, which over-corrects by the ~0.3s of legitimate CLI startup that a real
deployment would pay. The 5s cut is defensible because the distribution is
bimodal with nothing between ~0.8s and ~18s — it is a gap, not a percentile.
State the excluded count beside every figure.

### What needs new collection, and it is not much

Only the causal half: *which* hook fires, and whether an arm can suppress it
without changing what it measures. That is a handful of instrumented `claude -p`
invocations (`--debug`, or a settings override), not a collection window. And
the trade-off in the ticket is real and should be resolved **toward not
suppressing**: the arm exists to measure Claude Code as it ships on this
machine, and an arm that disables the operator's automation measures a
configuration nobody runs — the same argument A7.2 already used to decline the
Haiku cache padding. **Characterise it, exclude it from the published figure,
and leave the arm alone.**

---

## 6. The standing agent brief

Copy-pasteable. Paste it verbatim into every wave-2+ agent prompt; do not
paraphrase it, because the paraphrase is where the qualifier gets dropped.

```
=== STANDING CONSTRAINTS — JEV-experiments — read before your first tool call ===

FROZEN FILES. src/stats.py, src/analyze.py and questions/*/v1.json are frozen
by PREREGISTRATION.md section 8. If your ticket needs a change to one of them,
it is a DEFECT FIX: its own commit, the reason stated in the message, and the
pre- and post-fix numbers reported. Never bundled with other work. PREREGISTRATION.md
and FINDINGS.md are the owner's files: propose amendments in your handover, do
not write them.

GIT. Stage ONLY your own files, by explicit path: `git add src/worker.py
run-collection.sh`. NEVER `git add -A`, `git add .`, `git commit -a` or
`git stash`. Other agents are working in this tree right now and their
half-finished work is in it. Note that .scratch/ is NOT gitignored and
.scratch/wave2-prep.md is tracked — `git add -A` sweeps it in.

THE WORKER IS LIVE. A collection window is open until 2026-10-20 and
src/worker.py is running as a real process appending to data/runs/. Before you
restart it, reap spool/claimed/ or you lose whatever is mid-flight. Do not
`kill -9` it. Do not edit config/*.json without deciding whether the change is
an era boundary — the worker reads config ONCE at startup, and three boundaries
are already on the record (PREREGISTRATION A7.4).

TESTS — SOME OF THEM DESTROY LIVE DATA. Until JEV-42 lands:

  SAFE, run freely (all sandbox themselves into tempfiles):
    python3 tests/test_pipeline.py
    python3 tests/test_validation.py
    python3 tests/test_canary.py
    python3 tests/test_baseline.py
    python3 tests/test_session_metrics.py
    ./tests/gates.sh          (sandboxed under logs/ since JEV-15)
    ./tests/reversibility.sh  (sandboxed since JEV-40)
    uv run src/doctor.py

  DESTRUCTIVE against the live tree — run ONLY from a throwaway copy:
    ./tests/test_hook.sh      rm -f spool/ready/*.json between assertions;
                              chmod 500 spool/tmp; writes 501 filler files
                              into the live spool; rm -f .jev-disabled
    ./tests/test_inline_shadow.sh   touches and removes the real .jev-disabled
    ./tests/run_all.sh        invokes both of the above

  "Run the full test suite" is the instruction that destroyed live captures on
  2026-09-20 (PREREGISTRATION A6.1). It is not a safe default here.

PYTHON 3.12 IS REQUIRED. src/arms/jev.py:237 has a backslash inside an f-string
expression, which is a SyntaxError before 3.12. tests/test_pipeline.py carries
no requires-python header, so a bare `uv run` picks 3.11 and reports 16 spurious
errors that have nothing to do with your change. Invoke tests with `python3`
(3.12+) or an explicit `uv run --python 3.12`. Sixteen red errors are the known
version defect (JEV-44), not your regression — and if you see a DIFFERENT count,
that IS your regression.

REPORT, DO NOT REPAIR. If you discover that you have already broken something —
run a destructive test, deleted a capture, written outside the folder, committed
someone else's file — SAY SO IN YOUR HANDOVER, immediately and specifically,
with timestamps. Do not quietly restore it and carry on. This study's entire
claim to credibility is that losses of this shape get declared; two agents
disclosed on request on 2026-09-20 and that disclosure is what bounds the
attrition window at all. A repair you do not mention is indistinguishable from
a loss nobody found. You will not be penalised for a disclosure; a concealment
is the only unrecoverable error here.

NOTHING IS WRITTEN OUTSIDE THIS FOLDER, ever. ~/.claude/ is READ-ONLY.

ONE data/runs/ WRITER PER WAVE, over and above the live worker. If your ticket
is not the designated writer, do not run replay.py, canary.py or worker.py in a
mode that spends or appends.
=== END STANDING CONSTRAINTS ===
```
