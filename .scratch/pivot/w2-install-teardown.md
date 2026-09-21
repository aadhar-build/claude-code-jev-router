# W2 — safe install, safe removal, and JEV-56

**Built 2026-09-21. Nothing is armed.** `agent_route` is still `mode: "off"`,
this repo's own `.claude/settings.local.json` still registers only
`capture.sh`, and `~/.claude/settings.json` was never opened. Zero API calls,
zero network primitives added.

`bash tests/run_all.sh` is green, including the live-write audit and
`tests/reversibility.sh`.

---

## 1. What a user actually types

```
./jev status                       what is installed here, and the switches
./jev install  <repo> --dry-run    print exactly what would change
./jev install  <repo> --yes        register jev's hooks in <repo>
./jev uninstall <repo> --yes       remove them, and restore <repo>'s settings
```

`<repo>` is the repo you want routed; jev stays where it is and is never
copied. `--yes` or `--dry-run` is mandatory, for `teardown.sh`'s reason: a
change that can happen by accident — a stray test, a tab-complete, an agent
being helpful — is its own kind of hazard.

Both commands are idempotent. A second `install` changes not one byte and says
so; a second `uninstall` says there is nothing registered and exits 0.

**Install from a stable checkout.** The registration names
`$JEV_HOME/hooks/agent_route_actuator.sh` **verbatim and absolutely** — it has
to, because a foreign repo cannot anchor on a `$CLAUDE_PROJECT_DIR` the script
does not live in. `install` refuses if that script is missing or not executable
at install time, but it cannot protect against the directory moving afterwards:
install from a git worktree and the path dangles the day the worktree is
removed. (A dangling hook command is inert — Claude Code cannot exec it — so
this fails safe, but it fails silently.)

**Do not `export JEV_HOME` in the shell you run the suite from.** Every Python
test imports `paths`, so a stray value re-roots all of them, and
`tests/test_install.sh` would register hooks from the wrong install.
`tests/test_jev_home.sh` uses `env -u JEV_HOME` where it matters; the others
assume it is unset.

**Nothing is ever written to `~/.claude/settings.json`.** The SPEC's
non-negotiable 3, and the audit's reason for it: a global install resolves every
hook's root from whatever repo the session happens to be in, so the kill switch
names a file that cannot exist — permanently off, no way to stop the tool. That
is also the shape `coldteadotai/abide` ships. We took its code, not its
installer.

---

## 2. `JEV_HOME` — one mechanism, two readers

Before W2, `src/paths.py` derived its root from `__file__` and every bash hook
derived its root from `$CLAUDE_PROJECT_DIR`. In jev's own repo those are the
same directory, so the disagreement was invisible. `jev install` makes them
different, permanently.

There is now one rule, written twice:

> **`$JEV_HOME` if it is set and names a directory; otherwise the directory two
> levels above this file.**

- `hooks/agent_route_actuator.sh` — a canonical `# --- jev home` block.
- `src/paths.py` — `resolve_jev_home()`, and `ROOT` **is** `JEV_HOME`.
  `paths.jev_home_source()` reports which arm fired (`"env"` / `"self"`).

Validation is `is_dir()` and nothing more, deliberately: a richer rule is a rule
two implementations have to keep in step, and the failure it would catch is
already handled by fail-to-frontier plus the breaker.

`tests/test_jev_home.sh` §1 runs both halves — the bash one **extracted from the
shipped hook at test time**, not retyped — and requires the same absolute path
from each: with no env var, with one, and with a bogus one.

### The load-bearing consequence, which was a live defect

Every asset the actuator touches moved from `$CLAUDE_PROJECT_DIR` to
`$JEV_HOME`: `config/tiers.json`, the assignment ledger, the breaker log, the
stderr log.

This was not tidying. **Installed into a foreign repo, the actuator as W1
shipped it would have looked for `config/tiers.json` in the user's repo, not
found it, and failed to frontier on every single delegation** until the breaker
tripped — while writing `data/agent_route/` into their working tree, where they
would have found it in `git status`. `tests/test_jev_home.sh` §2 is the first
test in this repo to exercise the foreign-install shape at all, and it asserts
both halves: the rule table is found, and the routed repo gets nothing.

---

## 3. Two switches, and the one this repo keeps confusing

| switch | path | stops | set by |
|---|---|---|---|
| **global** | `$JEV_HOME/.jev-disabled` | jev, everywhere at once | `touch`, `./teardown.sh` |
| **machine-wide** | `~/.claude/jev-disabled` | the same, honoured even if the install is unreachable | `touch`. Read-only to us |
| **per-project opt-out** | `<repo>/.jev-disabled` | jev in that one repo | `touch`, `jev uninstall` |

All fail-safe: `-e` **or** `-L`, never `-f`, so a directory, a dangling symlink
and an unreadable file all read as **OFF**. An unset `$HOME` reads as OFF too.

The global switch is now **JEV_HOME-anchored**, which is the point: it is a real
path in every install shape, including the one where a project-anchored switch
names a file that can never exist.

**Nothing was inherited by assumption.** JEV-51 shipped a switch that stopped
one writer and not another, so `tests/test_jev_home.sh` §3–4 assert each switch
against `hooks/agent_route_actuator.sh` itself, in the shape where JEV_HOME and
the project are different directories, in every fail-safe form, with a control
run proving the actuator routes when no switch is set. The assertion is the
strong one for an actuator: **zero bytes on stdout *and* no ledger directory** —
it stopped *deciding*, not merely stopped logging.

### "The switch is off" is not "the tool is quiescent"

Stated in the code, in the CLI output, in `docs/REVERSIBILITY.md`, and asserted
in `tests/test_jev_home.sh` §5:

| state | what is true |
|---|---|
| **switch set** | the hook is still registered. A process is spawned on every matching tool call, exits on line one, writes nothing, leaves the tool input untouched. `jev status` still reports **INSTALLED** |
| **uninstalled** | no process is created at all. That is quiescent |

`./teardown.sh` reaches quiescence for **jev's own repo only**. It does not walk
foreign installs and cannot know about them; each is removed with
`jev uninstall <that repo>`.

---

## 4. Teardown: what is guaranteed now versus before

**Before.** `teardown.sh` is byte-reversible because it **never edits — it
moves**: switch first, then `mv` the whole settings file to a timestamped
`.disabled-<ts>`, then print the restore command. That file was entirely ours.

**Now**, per-project install may have to remove one key from a file holding the
user's other settings. That is categorically weaker, and `src/install.py` does
not pretend otherwise. It gets as close as it can, in this order:

1. **The switch first, always.** `uninstall` creates `<repo>/.jev-disabled`
   before it touches the settings file, for `teardown.sh`'s exact reason: the
   docs say direct edits to settings files are *"normally picked up
   automatically by the file watcher"*, and "normally" is not a guarantee. The
   switch is the guaranteed path; the unregistration follows. It is **left in
   place** and the `rm` is printed. If the switch cannot be created, uninstall
   **refuses to unregister at all** rather than proceed without the guaranteed
   stop.
2. **A verbatim backup before anything is written** — at install *and* at
   uninstall, under distinct names, bytes copied and never re-serialised.
3. **Tier A — byte-reversible.** If the file with our entries removed is the
   same document we backed up at install time, nothing is edited: the
   install-time **bytes** are restored and the sha256 is verified.
   `teardown.sh`'s guarantee, intact. This is the normal case.
4. **Tier B — structurally verified, and weaker.** If the file changed after
   install, tier A is the *wrong* answer (restoring would silently revert the
   user's own edits). We write the stripped document and verify it three ways
   against the file **re-read from disk**:
   - nothing outside `"hooks"` moved;
   - every handler that disappeared is one of ours, and no handler appeared;
   - **re-applying `install` to the result reproduces the pre-uninstall
     document exactly**, so nothing was *lost* rather than merely moved.

   Any failure restores the backup and stops loudly. The tier is named in the
   output every time — tier B explicitly does **not** claim byte-reversibility,
   and a test asserts it never prints that word.

**What tier B cannot promise, stated plainly:** the user's original
*formatting*. `install` re-serialises the file (`json.dumps(indent=2)`) the
moment it merges into it. Keys and values survive exactly and are checked; the
original bytes live in the verbatim backup. This is the one guarantee that is
genuinely weaker than before, and it is printed, documented and tested.

### Design choices that make removal possible at all

- **Our own group, always.** If the target already has a `PreToolUse` group on
  matcher `Agent`, we do not join it. A group we created is a group we can
  remove whole; Claude Code runs every matching group, so a separate one is
  behaviourally identical and structurally reversible.
- **Identified by script path, not by a marker key.** Claude Code parses the
  `hooks` array; an unknown key there is not ours to add, and a marker the
  harness might strip is a marker that leaves an entry we can no longer find.
- **`config/registration.json`** is the single committed description of what
  `jev install` registers. The installer reads it, and so does
  `tests/reversibility.sh` — there is no second hand-written copy to rot.

### Refusals, all whole

Unparseable JSON · a settings file that is a symlink · a `"hooks"` key that is
not an object · a target directory that does not exist · a hook script that is
missing or not executable · a backup that does not read back identical. Each
refuses before writing anything; `tests/test_install.sh` §6 asserts the file is
byte-unchanged and that no partial backup is left behind.

### A real bug the tests found

The backup filename carried a **second-resolution** timestamp. An install
followed immediately by an uninstall landed in the same second, the second
backup overwrote the first, the install-time bytes were gone — and uninstall
**silently downgraded from tier A to tier B**. A degradation of the central
guarantee, caused by a filename. Fixed with `unique_path()` plus distinct
prefixes (`.jev-backup-` vs `.jev-preuninstall-`); the comment says why.

---

## 5. JEV-56 — how it was resolved

The ticket's own suggestion was to commit `settings.local.example.json`. That is
a hand-copied second registration, which is precisely the drift the actuator
fixture exists to avoid. So instead:

- **The fixture is materialised by the real installer.** When no
  `.claude/settings.local.json` exists, the gate runs `jev install` into its
  sandbox (with `JEV_HOME` pointed at the sandbox, so the registration names the
  sandbox's hooks, not the live repo's). Its content comes from the committed
  `config/registration.json`. It cannot drift, and it tests the installer inside
  the gate for free.
- **The two questions are separated.** §0 is now "THE REGISTRATION UNDER TEST"
  and prints **LIVE** or **FIXTURE**. "Is a registration present and correct?"
  needs a real file and is not a failure without one. "Does OFF equal vanilla?"
  needs only *a* registration. **An empty registration is still always a
  failure** — the non-vacuity guard every one of those four gates was written
  for is intact.
- **The silent `cp` is gone.** `cp ... 2>/dev/null` at the old line 257 failed
  silently on a clean checkout and the damage surfaced three sections later.
  Every copy in the sandbox build now fails loudly, at the missing input.
- **§3's "it ran" oracle is chosen, not assumed.** A spool capture is the right
  oracle for an *observer* on `Bash` and the wrong one for an *actuator* on
  `Agent`, which writes no spool file — and the fixture registration is exactly
  that shape. The oracle is now picked from what is registered: spool count for
  capture.sh, changed tool input for the actuator. If neither applies the gate
  fails, because then nothing has been shown to run.
- **`tests/test_clean_checkout.sh`** builds an actual clean checkout (`git
  ls-files` + untracked-not-ignored, so no registration and no switch) and runs
  the whole gate inside it, asserting exit 0, that §0 reported FIXTURE, that the
  run asserted 45 gates rather than a handful, and that the registration it
  enumerated was not empty.

Verified both ways: **44/44 in LIVE mode, 45/45 in FIXTURE mode on a genuine
clean checkout.**

`docs/REVERSIBILITY.md` now has a table saying exactly what the proof is made
against in each mode, including the sentence that was previously left implicit:
in LIVE mode `OFF IS PROVEN EQUAL TO VANILLA` is a claim about **the operator's
own registration, not the one a reader cloning this repo would get.**

### The enumeration gate grew with the surface

§1 now knows **two** canonical switch blocks plus the `JEV_HOME` block; requires
the global and `JEV_HOME` blocks of every hook `config/registration.json` says
is *installable* (read from the installer's config, so a new installable surface
cannot be added without them); rejects `.jev-disabled` outside any of them;
checks both block sets are byte-identical across the scripts that carry them;
requires `$JEV_HOME` to be derived before the global block (the same
"structurally dead switch" check that already existed for `$ROOT`); measures
"effectful before the switch" from the *first* block; and accepts the
installer's absolute-path command shape alongside the `$CLAUDE_PROJECT_DIR`
one — a foreign install cannot anchor on a project dir the script does not live
in.

---

## 6. Files

**New**
`jev` · `src/install.py` · `config/registration.json` ·
`tests/test_install.sh` (42 assertions) · `tests/test_jev_home.sh` (26) ·
`tests/test_clean_checkout.sh` (8) · this report.

**Modified**
`hooks/agent_route_actuator.sh` (JEV_HOME block, global switch block, assets
moved to `$JEV_HOME`) · `src/paths.py` (`resolve_jev_home`, `JEV_HOME`,
`routing_disabled`, the named switches) · `src/doctor.py` (one line:
`HOME_KILL_SWITCH` added to `ALLOWED_OUTSIDE_READS`) ·
`tests/reversibility.sh` (JEV-56) · `docs/REVERSIBILITY.md` ·
`tests/test_agent_actuator.sh` + `tests/test_agent_actuator.py` (both W1's:
`JEV_HOME` now points at their sandbox — see the handback note).

**Deliberately untouched**
`.claude/settings.local.json` · `~/.claude/settings.json` ·
`config/surfaces.json` (`agent_route` stays `off`) · `tests/run_all.sh` ·
`ISSUES.md` / `SPEC.md` / `README.md` · `src/baseline.py` ·
`src/session_metrics.py` · `hooks/capture.sh` · `hooks/inline_shadow_bash.sh`
(neither is installable, so neither needs the new blocks, and leaving them
untouched keeps the per-project block byte-identical across all three).

---

## 7. Deliberately left for later

- **Arming anything.** Still JEV-52.
- **A `project` field on the assignment ledger row.** The ledger now lives under
  `$JEV_HOME` and will interleave rows from every installed repo; the
  `agent-route-assignment-v1` schema has no way to tell them apart. That is a
  schema change to `src/assignment_ledger.py`, which W1 owns.
- **`jev install` into jev's own repo.** Capable, but untested and unexercised
  here by instruction. Someone should decide whether the in-repo registration
  should keep its `$CLAUDE_PROJECT_DIR`-anchored form (§1 accepts both).
- **Uninstalling every install at once.** There is no registry of which repos
  jev is installed in; `jev uninstall` is one repo at a time, on purpose. A
  registry is state outside the folder, which is its own reversibility problem.
- **`jev` on `$PATH`.** It is `./jev` today, and **symlinking it into
  `/usr/local/bin` would break it**: `BASH_SOURCE[0]` is the *link's* path, and
  `pwd -P` resolves directories rather than the file, so `JEV_HOME` would come
  out as `/usr/local/bin`. If this ever needs to be on `$PATH` the answer is a
  wrapper that exports `JEV_HOME`, not a symlink. Noted rather than fixed,
  because putting anything on `$PATH` is a footprint outside the folder and an
  operator decision.

---

## 8. Known edges, stated rather than fixed

- **An original with an explicit `"hooks": {}`** is pruned to *no* `hooks` key,
  so tier A misses and tier B fires. A false **downgrade** of the guarantee,
  never a false upgrade — the safe direction, and the structural verify still
  passes — but it means a file that could have been byte-restored gets edited.
- **FIXTURE-mode enumeration lists four scripts**, because the sandbox's copy of
  the actuator is registered by absolute path *and* the sweep of `hooks/*.sh`
  picks up the repo's own. Correct, slightly noisy to read.
- **`resolve()` in `tests/reversibility.sh` now pins `HOME` at the sandbox.**
  Without it, an operator who had set the machine-wide switch this work
  introduces would have found the gate red for a reason unrelated to its claim.
  `tests/test_agent_actuator.py` already pinned `HOME` for this reason; the fix
  had not travelled.
