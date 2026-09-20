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
