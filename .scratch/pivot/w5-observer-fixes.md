# JEV-60 and JEV-61 — the two residuals W5 left deliberately

Both were left deliberately, with reasoning. Both are now resolved; the W5
reasoning was taken as a constraint on HOW, not as an argument for leaving them.

---

## JEV-60 — the observer hooks dropped every capture on a symlinked or trailing-slash project dir

### Reproduced first

`.scratch/repro60.sh`, against a sandbox under `/tmp` (which on macOS IS a
symlink to `/private/tmp`, so this is the ordinary case, not an exotic one):

```
--- control (byte-identical root, cwd=root)      rc=0 spooled=1
--- trailing slash CLAUDE_PROJECT_DIR            rc=0 spooled=0
--- symlinked (cwd physical, ROOT symlinked)     rc=0 spooled=0
--- any record of the drops?                     (nothing: no data/drops, no capture.err)
--- inline shadow, symlinked                     rc=0, no row anywhere
```

Silent, total, and on both hooks. Exactly the shape the repo has now been bitten
by five times: a failure that is byte-identical to "nothing happened".

### The decision: a TWO-STAGE guard, not a flat `pwd -P`

The ticket offered three options (pay the two subshells / resolve once and cache
/ accept the miss but make it loud). The cost objection is real, and it is
avoidable rather than payable:

```bash
case "$PWD/" in
  "$ROOT"/*) ;;          # stage 1: the byte match. ZERO forks, as before.
  *)                     # stage 2: only when that misses, resolve both sides
    ROOT_P=$(cd "$ROOT" 2>/dev/null && pwd -P) || ROOT_P=""
    PWD_P=$(pwd -P 2>/dev/null) || PWD_P="$PWD"
    ...                  # stage 3: a genuine miss leaves a drop row
esac
```

A normal macOS session under `/Users/...` takes stage 1 and pays nothing. The
two subshells are paid only by the installs that were previously recording
nothing at all — for them the alternative is not "cheaper", it is "no data".
Caching was rejected: every hook invocation is a fresh process, so the cache
would have to be a file, and a stale cache of "where the project is" is a worse
failure than the one being fixed.

`agent_route_actuator.sh` keeps its unconditional `pwd -P` — 250ms budget, once
per Agent spawn, and W5's comment there explains why. It was not touched.

### Measured critical-path cost

Method is `tests/test_hook.sh`'s own: best of three windows, 30 spawns each,
wall clock **including** the process spawn. Two independent runs, 2026-09-21
(`.scratch/measure60.sh`):

| configuration                   | run 1 | run 2 | captured |
|---------------------------------|-------|-------|----------|
| pre-fix, byte-match path        | 6.71  | 6.85  | 30 / 30  |
| **post-fix, byte-match path**   | 6.54  | 6.84  | 30 / 30  |
| post-fix, resolved (symlink)    | 7.78  | 8.00  | 30 / 30  |
| post-fix, trailing slash        | 7.99  | 8.26  | 30 / 30  |
| pre-fix, symlinked root         | 3.54  | —     | **0 / 30** |

Budget is 10ms. The hot path is unchanged (same instructions; the difference is
inside the noise). Correctness costs ~1.2ms and only where the byte match
misses, leaving ~1.7ms of headroom. The last row is the defect stated as a
number: the broken configuration was the *fastest* one, because it did nothing
and said nothing about doing nothing.

These numbers are stated in `hooks/capture.sh` — once in the top-of-file header
next to W5's kill-switch note, in full at the guard itself.

### A dropped capture now leaves a record — always

`capture.sh` grew one `drop()` writer, shared with the JEV-33 backpressure path
(which was the only refusal that already recorded itself). Function definitions
are parsed, not executed: the happy path pays nothing. New reasons:

- `cwd_outside_project` — with the resolved cwd and project dir in the row
- `project_dir_unresolvable` — `[ -d ]` passed but `cd` failed; a permissions
  story, wanting a different fix from a missing directory

`inline_shadow_bash.sh` got the same guard and its own `drop()`. Its refusal
rows go to `data/drops` and **not** to `data/inline`: an inline row describes a
decision (probabilities, timings, `error_kind` from `timed_http`'s deliberately
shared vocabulary) and a guard that refused to run took no decision to describe.
`data/drops` is the stream the attrition count already reads, and the rows carry
`surface`, so the two writers do not collide.

Checked before adding reasons: nothing consumes `data/drops` with a closed enum.
`src/spool_watch.py` counts lines; `src/store.py` only documents the stream.
`tests/test_pipeline.py` greps `capture.sh`'s TEXT for two cap literals and
asserts both match `config/surfaces.json`. The first refactor broke that
**silently**: inside double quotes the cap key was written `\"cap\":500`, which
reads the same to bash and is invisible to the regex, so the assertion would
have found one literal instead of two — the test protecting the literal stops
biting with nothing going red. The fragment is now single-quoted around the
expansion; replicating the assertion by hand gives `['500', '500']` against a
configured cap of 500. The suite did NOT catch this: the cleanup agent's
in-flight `tests/test_pipeline.py` does not currently run that assertion.

`tests/test_hook_mutations.sh` (not mine) deletes the guard with
`/^case "\$PWD\/" in/,/^esac/d`. The restructure deliberately keeps that opening
line and a column-0 `esac`, with the whole two-stage body between them, so the
mutation still applies and is still caught.

### Red before green

`tests/test_hook.sh`: 3 new red assertions → green (trailing slash captures,
symlinked root captures, the outside-cwd drop is recorded).
`tests/test_inline_shadow.sh`: the same 3, plus stdout still empty → green.

---

## JEV-61 — `doctor.py` was blind to the INERT marker

`src/doctor.py` now has `check_routing_inert()`, a **separate check** from
`check_routing_breaker()` rather than a branch inside it, called from `main()`.
It reports `WARN` (matching the breaker's severity — the live repo has no marker,
but a `FAIL` here would turn `run_all.sh`'s guarded doctor line red for anyone
who does) with:

- the marker's timestamp and age (`INERT since <ts> (3d 4h ago)`), parsed from
  the marker's first token, falling back to the file's mtime and saying so
- the recorded cause (`no_jq`, `ledger_write_failed`, `cwd_outside_project`, …)
  and the detail line beneath it
- the remedy, which is the distinguishing fact: **`rm <marker>` after fixing the
  cause**

The asymmetry W5 chose is preserved and now stated in the output rather than
only in a docstring: *this marker does not self-clear (an inert hook writes no
decisions that could)*. The breaker derives its state from a log that keeps
being written and clears itself; an inert hook writes nothing, so nothing could
honestly clear it. A stale false alarm beats a false negative. A test asserts
the check does not remove the marker, so a later "cleanup" has to argue with it.

Tests live in `tests/test_agent_actuator.py::TestDoctorSeesTheInertMarker` (6,
red first). They patch `doctor.paths.AGENT_ROUTE` at a tmpdir and call the check
directly, rather than subprocessing `doctor.py` against a sandbox where every
other check would fail and the assertion would be a grep through the noise.

---

## Suite

`bash tests/run_all.sh` → exit 0, no failures. The clean-checkout gate prints
`tar: src/analyze.py: Cannot stat` for three files another agent has in flight;
its own assertions still pass (`8 passed, 0 failed`) and that file is not mine.

## Files changed

- `hooks/capture.sh` — two-stage cwd guard, shared `drop()` writer, measured
  cost in the header
- `hooks/inline_shadow_bash.sh` — the same guard and its own `drop()`
- `src/doctor.py` — `check_routing_inert()`, `_age_since()`, called from `main()`
- `tests/test_hook.sh`, `tests/test_inline_shadow.sh` — new assertions
- `tests/test_agent_actuator.py` — `TestDoctorSeesTheInertMarker`
- `.scratch/repro60.sh`, `.scratch/measure60.sh` — the reproduction and the
  measurement behind the header's numbers

Not touched: `hooks/agent_route_actuator.sh` (already correct), `tests/run_all.sh`
(no new `guarded` line needed), and nothing was armed or registered.
