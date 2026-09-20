# JEV-44 prep note — the interpreter, for anything cron, a wrapper or a script invokes

Written 2026-09-20 by the JEV-44 agent (wave A1). Audience: **JEV-37** (A7, the
cron-scheduled canary) and **JEV-16** (A2, the replay sweep run from a script),
and anyone else who writes an entry point a human does not type by hand.

This note supersedes the interpreter paragraph in `.scratch/wave2-prep.md:995-1005`.
That paragraph says *"invoke tests with `python3` (3.12+)… sixteen red errors
are the known version defect, and if you see a DIFFERENT count, that IS your
regression."* **Both halves of that are now wrong.** See §1 and §5.

---

## 1. The one line you need

Do not write `python3`. In any file that cron, launchd, a hook, a `Makefile`,
a CI step or another script can invoke, write:

```sh
PY="${JEV_PYTHON:-/opt/homebrew/bin/python3}"
"$PY" "$ROOT/src/pyversion.py" || exit 1     # refuses <3.12, exits 78, says why
"$PY" "$ROOT/src/canary.py" ...              # only now do the work
```

`/opt/homebrew/bin/python3` → `../Cellar/python@3.14/3.14.7/bin/python3`,
**Python 3.14.7**. It is a symlink, so it survives Homebrew minor upgrades; it
does **not** survive a major-version bump (`python@3.15`), which is precisely
why line 2 exists rather than a comment saying "this is 3.14".

If you are inside a `tests/`-adjacent shell script and can source the repo's
library, use that instead — it does the same thing and also fixes PATH for
everything you then invoke:

```sh
. "$ROOT/tests/lib/require_python.sh" || exit 1
"$JEV_PY" ...
```

`$JEV_PYTHON` is the override. It is honoured **strictly**: if you name an
interpreter below 3.12 you get a refusal, not a silent substitution
(`tests/lib/require_python.sh:41-84`).

---

## 2. What cron actually gives you, and what it does not

**Verified on this machine, 2026-09-20.**

| | |
|---|---|
| `python3` on an interactive shell | `/opt/homebrew/bin/python3` → **3.14.7** |
| `python3` with `PATH=/usr/bin:/bin` | `/usr/bin/python3` → **3.9.6** |
| `/usr/local/bin/python3` | a third one; `/usr/local/bin/python3.12` also exists |

Reproduce the cron case without installing anything:

```sh
env -i PATH=/usr/bin:/bin HOME="$HOME" /bin/sh -c 'command -v python3; python3 -V'
# /usr/bin/python3
# Python 3.9.6
```

**Correction to the brief.** The interpreter cron resolves to here is **3.9.6,
not 3.11**. The 3.11 figure comes from `uv`: a bare `uv run` on a script with
no `requires-python` header selected **3.11.15** (verified before the fix;
after it, the same command selects 3.14.7). Two different wrong interpreters,
two different provenances. A fix aimed at 3.11 would not have covered cron.

**What cron provides.** `man 5 crontab` on macOS (the environment section,
lines 37-50 of the rendered page) documents exactly four variables:
`SHELL=/bin/sh`, `LOGNAME`, `HOME` (both from `/etc/passwd`), and `MAILTO`.

**What it does not provide, and this is the part worth internalising:**

- **`PATH` is not documented at all on macOS.** The `/usr/bin:/bin` default is
  Vixie-cron folklore; it is not in this man page. It is what this machine
  behaves like, but JEV-37 should **not** depend on it — set `PATH` explicitly
  in the crontab, or better, do not depend on `PATH` at all and use absolute
  paths for every binary (`python3`, `jq`, `curl`, `git`).
- **No shell profile.** `SHELL=/bin/sh`, invoked non-login and non-interactive:
  `~/.zshrc`, `~/.zprofile`, `/etc/paths` and `/etc/paths.d` are all skipped.
  Homebrew's `shellenv` never runs. This is the whole mechanism.
- **No `cwd` you can rely on.** Cron starts you in `$HOME`. Every hook and arm
  in this repo has a cwd guard (`hooks/capture.sh`), so a wrapper must `cd
  "$ROOT"` — `.scratch/wave2-prep.md:772` already does.
- **No `.env`.** `src/` reads credentials from the repo's `.env`; cron will not
  have loaded it.
- **No TTY.** Anything that probes `isatty` behaves differently.
- **Output goes to mail, or nowhere.** Redirect to `logs/` explicitly.
- **There is currently no crontab for this user** (`crontab -l` → "no crontab
  for aadharagarwal"), so JEV-37 is starting from zero. Per SPEC, the scheduler
  stays outside the folder and is the operator's to install — JEV-37 prints it,
  it does not install it.

---

## 3. Detecting the wrong interpreter *before* doing work

This is the property the ticket was really about, and it is now available three
ways. Pick by what your entry point is.

### (a) Shell preflight — for a cron wrapper

```sh
"$PY" "$ROOT/src/pyversion.py" || exit 1
```

`src/pyversion.py` costs one process spawn, touches no network, writes nothing,
and prints nothing on success. On failure it writes a block naming the floor,
the version found, the path, and the `JEV_PYTHON=` line that fixes it.

### (b) Python guard — for a `__main__` you own

```python
sys.path.insert(0, str(ROOT / "src"))
import pyversion; pyversion.require()
```

Put it **immediately after the `sys.path` line and before every project
import**. That ordering is the whole point: below the floor, `import worker` →
`from arms import jev` → `SyntaxError`, and you never reach a guard placed
after it. See `tests/test_pipeline.py` and `src/doctor.py` for the pattern.

`src/pyversion.py` is deliberately written in pre-3.12 syntax — no f-strings,
no annotations, no `match`, imports only `sys` — and
`tests/test_python_floor.py` byte-compiles it with `/usr/bin/python3` (3.9.6)
on every suite run, so that stays true. **A guard that raises `SyntaxError` is
a second copy of the bug.** Do not "modernise" that file.

### (c) PEP-723 header — for `uv run` only

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
```

**This binds `uv run` and nothing else.** `python3 yourscript.py` ignores it
completely, and that is exactly the invocation that produced the 16 errors. A
header is necessary and *not sufficient*; ship (b) with it.

### Exit code 78, and why not 1

`src/pyversion.py:EXIT_WRONG_PYTHON = 78` (`EX_CONFIG`, sysexits(3)).

**JEV-37 specifically: do not let a guard exit 1.** `src/canary.py:101-105`
owns `0` clean / `1` drift / `2` baselined / `3` incomplete / `4` jitter-flip,
and your wrapper reads those codes. A misconfigured PATH exiting 1 would be
reported to the operator as **drift** — a false scientific finding manufactured
by an environment problem. `.scratch/wave2-prep.md:769,779` already reserves
`77` (kill-switch suppressed) and `99` (failed to start); 78 is disjoint from
all of them. `tests/test_python_floor.py` asserts
`EXIT_WRONG_PYTHON not in range(5)` so this cannot silently regress.

---

## 4. What JEV-44 changed, so you build on it rather than around it

| file | note |
|---|---|
| `src/pyversion.py` | new. `MIN = (3, 12)`, `explain(found, executable)`, `require()`, `EXIT_WRONG_PYTHON = 78`. The single definition of the floor in the project |
| `tests/lib/require_python.sh` | new. Sourced; sets `$JEV_PY` and prepends its dir to `PATH` |
| `tests/run_all.sh:42-54` | sources the resolver **before** `audit_live_writes.sh`; all six `python3` invocations became `"$JEV_PY"` |
| `tests/test_python_floor.py` | new, 14 tests, wired into `run_all.sh` |
| `tests/{test_pipeline,test_validation,test_session_metrics,test_baseline,test_canary,gate4_drain}.py` | PEP-723 header + `pyversion.require()` |
| `src/doctor.py` | `pyversion.require()` added (it already had the header) |
| `src/arms/jev.py` | **unchanged, deliberately.** Line 237 is still a pre-3.12 `SyntaxError`. Fixing it would make the suite go green on an interpreter the study has never been measured on, while every `src/` header still says 3.12 — a loud failure turned silent. It is also the only pre-3.12 syntax in `src/`, `tests/` or `hooks/`: `python3.9 -m compileall src tests hooks` flags it and nothing else |

---

**The self-maintaining part, observed working.** `tests/test_python_floor.py`
derives its module list from `run_all.sh` rather than from a hand-written list.
Minutes after this ticket committed, the JEV-51 agent added
`tests/test_worker_lifecycle.py` to `run_all.sh`; the pin test went red naming
that file, and it was pinned and guarded within minutes. **If you add a module
to `run_all.sh` you must add the header and `pyversion.require()` — the suite
will tell you, and the failure message contains the exact lines to paste.**

---

## 5. The 16-error rule is dead — do not propagate it

Measured at HEAD, `tests/test_pipeline.py`:

| interpreter | tests | errors |
|---|---|---|
| `/usr/bin/python3` 3.9.6 | 89 → 104 | **16** |
| `python3.11` 3.11.15 | 89 → 104 | **16** |
| `/opt/homebrew/bin/python3` 3.14.7 | 104 | **0** |

Every one of the 16 is the same `SyntaxError`, reached through the lazy
`from arms import claude, jev` in `TestLiveArmWireFormats.setUp`
(`tests/test_pipeline.py:445`).

Three reasons the rule cannot work:

1. **It does not discriminate.** 16 on 3.9.6 and 16 on 3.11.15 — two
   interpreters five minor versions apart, same number. The count tells you
   nothing about which interpreter you were on.
2. **It moves.** `test_pipeline.py` grew from **89 to 104 tests during this
   ticket's own wave** (JEV-31b, in flight in the same tree). Add one test to
   that one class and 16 becomes 17, with zero regression anywhere.
3. **It inverts.** An agent on the *correct* interpreter, mid-wave, saw **13**
   errors from unrelated in-flight work. Under the rule, "13 ≠ 16, therefore my
   regression" — the opposite of the truth.

Nobody should have to memorise a number. Run the suite; if the interpreter is
wrong it now says so in one sentence and stops.

---

## 6. Report-not-repair: what is still fragile, and not mine to touch

Ordered by how much it matters. **None of these is broken today**; all are
invocation fragility that the next wave will meet.

### 6.1 `run-collection.sh` — owned by another agent this wave

- `run-collection.sh:29` — `nohup python3 -u "$ROOT/src/worker.py" --interval 30 …`
- `run-collection.sh:54` — `python3 "$ROOT/src/spool_watch.py" --sample`

Bare `python3`, resolved from the invoker's `PATH`. This is fine from a human
shell and wrong from anything else. It matters more than the test case: the
**worker daemonises**, so a wrong interpreter here means a long-lived process
running under an unintended runtime, or an immediate `SyntaxError` into
`logs/worker.log` that nobody reads until captures stop arriving. **The exact
change I would want**, at the top of `run-collection.sh` after `ROOT` is set:

```sh
. "$ROOT/tests/lib/require_python.sh" || exit 1
```

then `python3 -u` → `"$JEV_PY" -u` on line 29 and `python3` → `"$JEV_PY"` on
line 54. (If depending on a file under `tests/` from a production script is
unwanted, the §1 two-liner against `src/pyversion.py` is equivalent.)

### 6.2 `src/worker.py` — owned by another agent this wave

It has the PEP-723 header but no runtime guard, and it is the longest-lived
`__main__` in the project. **The exact change I would want**, after its
`sys.path` line and before any project import:

```python
import pyversion; pyversion.require()
```

### 6.3 `src/spool_watch.py` — owned by a third agent this wave

**Weakest of the three.** It is a `__main__` entry point with **no shebang and
no PEP-723 header at all** (`src/spool_watch.py:1` is the docstring), and it is
invoked bare at `run-collection.sh:54`. It needs the same four-line header
every other `src/` entry point carries, plus `pyversion.require()`.

### 6.4 Other unpinned executables, unowned this wave

`src/canary.py`, `src/replay.py`, `src/analyze.py`, `src/baseline.py`,
`src/bench_inline.py`, `src/determinism.py`, `src/hook_dispatch.py`,
`src/make_synthetic.py`, `src/reversibility.py`, `src/session_metrics.py`,
`src/validate_threshold.py`, `src/verdict.py`, `src/arms/*.py` all carry
`requires-python = ">=3.12"` headers and the `uv run --script` shebang, but
none calls `pyversion.require()`. They are therefore protected under `uv run`
and unprotected under `python3`. **Two that matter next wave:**

- **`src/canary.py` (JEV-37).** Add `pyversion.require()`. Your cron wrapper
  should *also* preflight (§3a) so the failure happens before the log file is
  opened and before the exit-code mapping runs.
- **`src/replay.py:1-5` (JEV-16).** Header present, guard absent. A replay
  sweep driven from a script is exactly the "invoked by something other than a
  human shell" case. Add `pyversion.require()` and drive it with `"$JEV_PY"`.

Library modules (`paths.py`, `store.py`, `stats.py`, `state_builders.py`,
`config_loader.py`, `arms/base.py`, `arms/fake.py`, `arms/timed_http.py`,
`arms/__init__.py`) correctly have no headers — they are imported, never run.
`src/stats.py` is FROZEN (PREREGISTRATION §8) in any case.

### 6.5 Shell tests that still shell out to bare `python3`

`tests/audit_live_writes.sh:54`, `tests/test_hook.sh:129,196-204`,
`tests/test_inline_shadow.sh:86,113,127,131,170-176`.

**Under `run_all.sh` these are now safe** — the resolver prepends `$JEV_PY`'s
directory to `PATH`, so their bare `python3` resolves to the checked
interpreter. That was a deliberate design choice: patching nineteen call sites
across three files I do not own would have been a large diff for no extra
safety. **Run standalone, they are still unprotected.**
`tests/test_inline_shadow.sh:86` is the sharpest: it launches
`src/bench_inline.py`, which declares `>=3.12`. `tests/test_hook.sh:199,175`
use f-strings inside `python3 -c`, which is how you get a `SyntaxError` out of
a one-liner on an old interpreter.

I did not add a rule to `tests/audit_live_writes.sh` for bare `python3` even
though it is the natural home for such a scan — it is a JEV-42 artefact with a
declared scope ("live-window writes"), and widening it is a decision for its
owner, not a side effect of this ticket. `test_python_floor.py` enforces the
no-bare-`python3` rule for `run_all.sh` only.

### 6.6 A `pyproject.toml` would be the tidy answer, and I did not add one

`requires-python` in a `pyproject.toml` is where this belongs in a normal
project. There is no `pyproject.toml` in this repo, and creating one flips `uv`
into **project mode** for every `uv run` in the tree — including
`README.md:52,88` and `docs/PLAN.md:423-427`, which are other people's
invocations. That is a repo-wide behaviour change bought for nothing the
PEP-723 headers do not already deliver. If someone later wants one, the
decision needs its own ticket.

### 6.7 Three interpreters on this machine, and nothing records which one ran

`/opt/homebrew/bin/python3` (3.14.7), `/usr/bin/python3` (3.9.6),
`/usr/local/bin/python3` (plus `python3.12`, `python3.11`, and a `~/.local/bin`
3.11). No run row, capture row or canary report records the interpreter that
produced it. For a study whose whole claim is reproducibility, "which Python
wrote these 2,005 rows" is currently unanswerable from the data. Not my ticket;
flagging it for whoever writes the dated go-live inventory (JEV-52 step 7) —
`sys.version` and `sys.executable` next to `arm_config_id` would close it.

---

## 7. Things I deliberately did not do

- Did not touch `src/worker.py`, `run-collection.sh`, `src/spool_watch.py`,
  `src/config_loader.py`, `config/*.json` — other agents' files this wave.
- Did not touch `src/stats.py`, `src/analyze.py`, `questions/*/v1.json` — FROZEN.
- Did not fix `src/arms/jev.py:237`. See §4.
- Did not create a `pyproject.toml`. See §6.6.
- Did not start the worker, remove `.jev-disabled`, register a hook, or enable
  any surface. `.jev-disabled` present and untouched; spool empty; the
  `live_guard.sh` conservation check was run around every manual test
  invocation in this session and passed every time.
- Did not install a crontab, and did not make any network call.
