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
