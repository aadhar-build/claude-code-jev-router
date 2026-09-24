# 03. Wave-0 test failure triage

Source: research subagent report, 2026-09-24; claims marked (unverified) were not independently confirmed.

Method: the `main` branch (one squashed "v0.1" commit) and a worktree of `origin/master` (development line, about 120 commits) were copied and tested. No hooks installed, no network.

## Headline (ran)
The clone under test was `main`. It lacks `ISSUES.md` and `data/baseline/*` (tracked on `origin/master`, absent on `main`; `data/*` is gitignored there). That one fact explains the `test_report` and `test_board` failures. On `origin/master`, `test_report` passes 88/88 (1 skipped). Decision needed: which ref is the v0.2 base.

## Per test
| test | root cause (ran) | class | touches hook / installer / ledger / breaker | verdict |
|---|---|---|---|---|
| `test_python_floor` (3 fail) | Premise is macOS: it assumes `/usr/bin/python3` is Apple's 3.9.6. On a box where it is 3.12 the guard correctly passes, so tests expecting rejection fail | Environment (test premise) | `src/pyversion.py`, `tests/lib/require_python.sh` only | Safe to waive |
| `test_jev16` (1 fail, 2 err) | `data/synthetic/` absent (gitignored, generated); `replay.seed_synthetic` KeyError | Missing data | `replay.py`, worker stamps; not the hook | Safe to waive after generating; 13/13 pass once generated |
| `test_accuracy_gate` | `data/synthetic/pre_bash-v1.jsonl` missing | Missing data | none | Safe to waive after generating; 114 tests pass |
| `test_board` (rc=2) | `ISSUES.md` absent on `main` (`tests/test_board.py:43`). On `origin/master` it runs 7/8; the failure is `test_every_open_ticket_is_in_exactly_one_wave` (a newly filed ticket, JEV-62, is in no wave table) | Missing data on `main`; stale bookkeeping on `master` | reads `ISSUES.md` only | Safe to waive; add the ticket to a wave table |
| `test_report` (10F, 6E) | `CouldNotRun: the before anchor is not on disk: data/baseline/delegation-pre-rule-v1-corrected.json` (`report.py:583`) | Missing data | uses temp ledgers only | Blocks only the report chunk, and only if the base is `main`; 88/88 on `master` |
| `src/doctor.py` (2 fail) | `.env` absent; user-level settings already contain a `hooks` key (`doctor.py:193-194`) | Environment | read-only breaker-marker check (`doctor.py:256`) | Safe to waive; the user-settings FAIL is a real property of a box with its own hooks, so any router install must be project-local |
| `test_hook.sh` timing | 24 ms vs 10 ms budget on the old capture hook (taken from the brief, not re-run) | Environment (slow disk, inferred) | old capture hook, not the actuator | Safe to waive |

## `test_python_floor`: guard vs premise (ran)
- With a genuinely old interpreter (CPython 3.11), `src/pyversion.py` prints the WRONG PYTHON message and exits 78. Sourcing `tests/lib/require_python.sh` with `JEV_PYTHON=<3.11>` also returns 78. A shim reporting 3.9.6 gives 78 too.
- Rerunning the test file with `SYSTEM_PY` pointed at the real 3.11 leaves only two failures, both hardcoded `assertIn("3.9.", ...)` literals. The guard is sound; the tests bake in the macOS version string.
- Minimal fix: point `SYSTEM_PY` at a real old interpreter, or skip when `/usr/bin/python3` is at or above the floor.

## Router-path check
None of the failing tests import or call `hooks/agent_route_actuator.sh`, `./jev install` or `src/install.py`. Ledger is touched only by `test_report` (temp dirs); the breaker only by `doctor` (read-only). Router core suites passed earlier per the brief (61/61, 62/62, 49/49, 55/55) (unverified here).

## Recommendation
Nothing here blocks the v0.2 router build. Fix the base ref (`origin/master`), run `python3 src/make_synthetic.py` per clone before `test_accuracy_gate` and `test_jev16`, waive `test_python_floor` (and fix its premise), the doctor user-settings FAIL and the `test_hook.sh` timing, and fix `test_board` via the wave table.

## Not verified
`test_hook.sh` timing was not re-run. The doctor `.env` fix was not applied. `test_board` on `master` was checked only for the one failing assertion. Whether `main` vs `master` is intentional (`main` is the public v0.1 publish) is inferred.
