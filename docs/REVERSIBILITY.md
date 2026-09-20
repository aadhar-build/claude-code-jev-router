# Reversibility: the way back to stock Claude Code

JEV-40. What this folder does to the machine, what stops it, and — the part
that needed proving rather than asserting — what "stopped" actually means once
a hook is an actuator rather than an observer.

Run `uv run src/doctor.py` for the live state. Run `./tests/reversibility.sh`
for the gate that keeps every claim below true.

---

## The switch

`touch .jev-disabled` in the repo root. Every hook tests it before doing
anything else, `$CLAUDE_PROJECT_DIR`-anchored, in a block that is byte-identical
across every hook script:

```bash
{ [ -e "$ROOT/.jev-disabled" ] || [ -L "$ROOT/.jev-disabled" ]; } && exit 0
```

`rm .jev-disabled` resumes.

### It fails safe

The test is `-e` **or** `-L`, not `-f`, and that is deliberate. A switch whose
state cannot be established must read as **ON**, never OFF:

| what is at the path | `[ -f ]` would say | what the hooks say |
|---|---|---|
| a regular file | present | **OFF** |
| a **directory** (`mkdir .jev-disabled`) | absent | **OFF** |
| a **dangling symlink** | absent | **OFF** |
| a file that cannot be read (mode 000) | present | **OFF** |

The directory case is not hypothetical bookkeeping: an operator who types
`mkdir` instead of `touch`, or an `install -d` in a script, would otherwise
believe the experiment was off while every hook kept firing. All four cases are
asserted in `tests/reversibility.sh` §2, on both hook scripts, against a control
that proves the sandbox captures when the switch is genuinely absent.

Everything that *reports* the switch uses the same rule, or the operator would
be told the opposite of what the hooks are doing: `run-collection.sh status`,
`paths.killed()` (and through it `bench_inline.py`), and
`src/reversibility.py`. Those three are the only places the rule is encoded
outside the hook scripts themselves.

There is one case the block does not cover, and it does not need to: if the
project root cannot be traversed at all, Claude Code cannot `exec`
`$CLAUDE_PROJECT_DIR/hooks/capture.sh` either. That reduces to "the hook never
ran", which is the same thing as vanilla.

### Does a RUNNING session honour it? **Yes.** Established, not assumed

Probed live on **2026-09-20**, in a session that was already running, with the
hook already registered and no restart at any point:

| time (local) | action | captured? |
|---|---|---|
| 20:05 | Bash call, switch absent | **yes** |
| 20:06:09 | `touch .jev-disabled` | yes (the switch was not yet set when this call fired) |
| 20:06:~12 | Bash call, switch **present** | **no** |
| 20:06:~15 | `rm -f .jev-disabled`, switch present | **no** |
| 20:06:17 | Bash call, switch absent again | **yes** |

Two captures were deliberately forgone in that window (the probe and the `rm`),
and they are noted here rather than left as a silent gap in the collection.

**Why it generalises, which matters more than the probe.** The switch is not
hook *configuration*. It is a file test performed by the hook *script*, and
Claude Code spawns a fresh process that reads that script from disk on every
invocation. Whether the harness caches its hook config cannot affect it. The
offline reproduction of exactly that mechanism — one unchanged registration,
the switch toggled underneath it, three invocations — is asserted in
`tests/reversibility.sh` §5.

**Unregistering** — editing or removing `.claude/settings.local.json` — is the
other way to stop the hooks, and it *also* takes effect mid-session: "Direct
edits to hooks in settings files are normally picked up automatically by the
file watcher" (`code.claude.com/docs/en/hooks.md`, read 2026-09-20), which
matches JEV-08's observation that *registration* was picked up mid-session with
no restart. But "normally" is not a guarantee, which is why `teardown.sh` sets
the switch **first** and unregisters second.

### The bound on the claim

It is fair to call this an immediate stop, with two qualifications that should
travel with it:

1. It takes effect at the **next** hook invocation. A hook already in flight
   finishes; it is not killed.
2. It stops **these** hooks because **these scripts** test it. It is not
   enforced by Claude Code. The harness-native equivalent, which stops every
   hook from every source, is `"disableAllHooks": true` in a settings file, or
   `--settings '{"disableAllHooks": true}'` for a single run.

---

## Fully quiescent — the one command, and what it stops (JEV-51)

The switch above stops the **hook**. Until JEV-51 it did **not** stop the
**worker**: `worker.py`'s drain loop never consulted it, so with the switch
engaged and a non-empty spool the worker kept draining and kept calling every
enabled arm. "Disabled" meant *stops recording new decisions*, not *stops
spending money*, and `run-collection.sh status` printed `capture: DISABLED`
while API calls were still going out. JEV-40 proves OFF means vanilla **for the
session**; it never proved OFF means **quiescent**.

Three states, and they are now three separate facts:

| state | what is stopped | how |
|---|---|---|
| **capture disabled** | the hook writes no new spool files | `touch .jev-disabled` |
| **worker quiescent** | no arm is called for files already spooled | the same switch — the worker reads it at the top of every cycle **and before every claim** |
| **worker stopped** | the process is gone | `./run-collection.sh stop` |

### The one command

```
touch .jev-disabled
```

That is the full stop for **spending**. Within one poll interval the worker
logs `QUIESCENT`, claims nothing, calls nothing and quarantines nothing; the
spool is left exactly as it was, so `rm .jev-disabled` **resumes** rather than
recovers. Proven by a test that counts arm invocations with the switch engaged
and a non-empty spool (`tests/test_worker_lifecycle.py`,
`TestKillSwitchStopsDispatch`), against a control in which the switch is absent
and the same drain calls the arm every time — without that control the
assertion would pass on a drain that was merely broken.

The switch is re-read before **every** claim, not once per cycle: at a 30s poll
the cycle-top check alone would keep spending for up to 30s after the operator
believed they had stopped it, and draining a deep backlog is far longer than
that. It is never read *between* the claim and the dispatch — a capture that
has left `ready/` is finished, not abandoned.

To also stop the **process**, which is a separate act:

```
./run-collection.sh stop
```

### Why `stop` now takes time, and is not hung

`stop` sent a bare SIGTERM and returned immediately. Nothing in the worker
handled it, so the default disposition killed the process instantly — possibly
mid-dispatch, with a capture already renamed into `spool/claimed/` and nothing
in the tree that ever moves it back. **That is the unnamed cause of JEV-31's
stranded claims**, and it is why two hand-reaps are recorded on the board.

SIGTERM and SIGINT now both set a flag: the in-flight capture finishes, its
claim is released, the process exits 0. SIGINT gets an **explicit handler**
rather than relying on `except KeyboardInterrupt`, because the worker is
started as a background job and the shell sets SIGINT to `SIG_IGN` — the only
graceful exit that existed was unreachable in the way the worker is actually
run.

The honest cost: a stop can take up to one dispatch, bounded by the slowest
enabled arm's `timeout_s` — **180s for the `cc_*` arms, 240s for
`cc_fable51`**. `stop` prints that bound, reports progress every 15s, waits up
to 300s, and then **checks `spool/claimed/` and exits non-zero if anything was
stranded** rather than printing "stopped" and walking away. It removes the
pidfile only once the process is actually gone.

Asserted end to end in `tests/test_worker_lifecycle.py::TestGracefulStop`,
which SIGTERMs and SIGINTs a **real** worker process **mid-dispatch** and
requires exit 0, an empty `claimed/`, a completed run row for the capture that
was in flight, and the unclaimed captures still sitting in `ready/`.

### If a worker dies anyway — the startup reap (JEV-31)

A kill -9, an OOM or a crash still strands a claim, so the recovery is not
optional. On every start the worker scans `spool/claimed/` and returns files to
`ready/` whose owning pid is gone. A claim now records its owner —
`{base}__p{pid}__t{epoch}__r{retries}.json` — because the number in the old
name was `capture.sh`'s `$$`, the **hook's** pid, which told a reaper nothing.

- a claim owned by a **live** pid is never reaped, at any age;
- the reap runs at **startup only**, never inside the drain loop;
- a re-claim carries a retry counter, and after 3 it is quarantined to
  `spool/dead/` with the reason, so a payload that kills the worker cannot
  resurrect itself forever.

Both restrictions exist for the same reason: reaping a claim whose owner is
still working produces two full sets of well-formed rows under two
`decision_id`s sharing one `state_sha256`. That is **inflation, not attrition**,
and it is invisible — the §5 same-state assertion passes because the duplicates
are legitimately identical, while the clustered bootstrap counts one decision
point as two. The residual risk is stated rather than engineered away: pid
reuse can make a dead owner look alive, in which case the file stays in
`claimed/` and is reported in `status` instead of being reaped.

---

## OFF equals vanilla — proved, not asserted

The existing gates assert that with the switch on, no spool file appears. For an
**observer** that is the whole claim. For an **actuator** it is not: a hook that
exits early *still ran*, and the only thing separating it from a hook that never
existed is whether the tool input it leaves behind is the untouched one.

`src/hook_dispatch.py` models Claude Code's documented `PreToolUse` dispatch —
matcher regexes, stdin payload, `hookSpecificOutput.updatedInput` replacing the
**entire** input object, empty or unparseable stdout leaving it unchanged — and
returns the tool input that survives. "Byte-identical" means identity of the
canonical serialisation, `json.dumps(..., sort_keys=True,
separators=(",", ":"))`, because the comparison is between an object that passed
through a hook's JSON round-trip and one that did not, and key order is not part
of the claim.

The whole gate runs inside a throwaway sandbox project directory, with
`CLAUDE_PROJECT_DIR` pointed at it. It never writes to the real `spool/`,
`data/` or `logs/`, and it re-checks the live `.claude/settings.local.json`'s
sha256 at the end — that file is the registration a collection window is
currently running on.

`tests/reversibility.sh` §3 runs four arms over an `Agent`-shaped payload —
`prompt`, `description`, `subagent_type`, and no `model` key, the case where a
routing hook *adds* a field:

| arm | registration | switch | expected |
|---|---|---|---|
| **B** | none at all | — | the control: the vanilla input |
| **A** | the live one | ON | **== B** |
| **A'** | the live one | OFF | == B, *and the hook demonstrably ran* |
| **C** | an actuator fixture | OFF | **≠ B** — the positive control |
| **D** | an actuator fixture | ON | **== B** — the claim JEV-35 is gated on |

Every arm is run for **both** payloads where it is meaningful, and §3 first
asserts that every matcher in the live registration has a payload here at all —
otherwise the day JEV-35 registers a hook on matcher `Agent`, a Bash-only
comparison would pass without the routing hook ever running. (The Agent payload
with the switch **off** is deliberately *not* asserted equal: after JEV-35 it is
supposed to differ.)

Arm **C** is the load-bearing one. Without it every other row would pass on a
test incapable of detecting a rewrite at all, which is precisely the state the
repo was in before this file existed. Arm **A'** plays the same role for the
observer: it asserts a capture *was* written, so arm A is not passing because
the hook silently failed. Arm D is repeated with the switch in each of its three
fail-safe forms.

The actuator fixture's kill-switch block is **extracted from
`hooks/capture.sh` at test time**, not retyped, so the fixture cannot drift away
from the thing it stands in for.

When JEV-35 lands, the same definition transfers to a live session unchanged:
the oracle there is the `tool_input` echoed by `PostToolUse` (which reflects
`updatedInput`), serialised the same way, checked against `resolvedModel`.

---

## One switch, all surfaces

`tests/reversibility.sh` §1 **enumerates the registered hooks** from
`.claude/settings.local.json` — every event, not just `PreToolUse` — resolves
each command to its script, and fails if any of them:

- is not `$CLAUDE_PROJECT_DIR`-anchored,
- does not resolve to a script that exists,
- lacks the canonical switch block,
- carries the block but never derives `$ROOT` from `$CLAUDE_PROJECT_DIR`
  before it — a copy-paste that tests `/.jev-disabled` is a switch that is
  structurally dead, and a negative fixture asserts the checker rejects it,
- mentions `.jev-disabled` anywhere outside that block (a second, drifting copy),
- has anything effectful before it — a network call, a write, a `jq`, an emitted
  decision. Comments, the fail-open `trap`, stderr redirection, locale pinning
  and plain assignments are allowed; everything else is not.

It also sweeps `hooks/*.sh`, because a hook is written before it is registered
and the block has to be there on the day it is written. And it fails loudly if
the settings file is absent, rather than passing by enumerating an empty set.

`uv run src/doctor.py` carries the same check as `switch-coverage`.

---

## Teardown

```
./teardown.sh --dry-run    # print exactly what would change, change nothing
./teardown.sh --yes        # do it
```

`--yes` is required: a teardown that can fire by accident is its own hazard in a
folder with a live collection window.

It sets the switch, then moves `.claude/settings.local.json` to a timestamped
`.disabled-<ts>` file — moved, not deleted, so the restore command it prints
puts the registration back byte-for-byte. `tests/reversibility.sh` §4 exercises
all of it in a sandbox, including the restore.

**What it does not undo**, stated by the command itself every time it runs:

| change | reversible? |
|---|---|
| hooks firing | **yes** — the switch, or unregistering |
| data collected | **yes** — it is all inside this folder; delete the folder |
| the machine's config outside this folder | **nothing to undo**; nothing is written there |
| work already produced by a routed model | **no** |
| the "delegate where possible" working rule (JEV-24b) | **no** |

The last two are why this experiment is pre-registered and staged rather than
merely flagged. The full statement lives in `ISSUES.md`, JEV-40, and is not
restated here so that there is one copy of it.

---

## What is written outside this folder

Nothing. `uv run src/doctor.py` prints the audit in one block: the hooks
registered, the switch state, what is inside the folder, and what is outside it
— `~/.claude/settings.json` (never given a `hooks` key),
`~/.claude/projects/` and `~/.claude/history.jsonl` (both read-only), and
`.claude/settings.json`, the file that *would* travel to a clone or a cloud
session, which is asserted absent.
