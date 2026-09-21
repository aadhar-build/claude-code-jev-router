# W5 — two real defects in `jev install` / `jev uninstall`, reproduced and fixed

**Nothing is armed.** `agent_route` is still `mode: "off"`, this repo's own
`.claude/settings.local.json` is byte-unchanged, `~/.claude/settings.json` was
never opened. Zero API calls. The test that asserts no write verb in
`src/install.py` is even *aimed* at `$HOME` still passes.

Files changed: `src/install.py` · `jev` · `src/paths.py` ·
`config/registration.json` · `tests/test_install.sh` · `tests/test_jev_home.sh`.

---

## 1. Tier B aborted on the ordinary case, and left jev REGISTERED

### Reproduced first

`install` into an empty repo, add a `PreToolUse` hook of your own, `uninstall
--yes`:

```
VERIFY  THE REST OF THE FILE IS NOT WHAT IT WAS.
        re-install does not reproduce the original at .hooks.PreToolUse[0].hooks[0].command
        … Restoring your file from …jev-preuninstall… and stopping.
```

and the settings file still carries
`hooks.PreToolUse[0] = {matcher: "Agent", …/hooks/agent_route_actuator.sh}`.

**One correction to the audit's account, stated because it matters for how the
failure presents:** the exit code is **1**, not 0. `verify_removal` returning
problems takes the `EX_REFUSED` path. The *load-bearing* half of the claim is
exactly as reported and is worse than the exit code suggests — **jev is still
registered**, so only the `.jev-disabled` switch stops it, and JEV-51's lesson
("disabled must mean quiescent, not merely silent") was being violated by the
one command whose entire purpose is quiescence.

### Root cause

`verify_removal` check 3 compared `merge_entries(after, …)` against `before`
**positionally**. `merge_entries` always appends jev's group at the END of
`hooks.PreToolUse`, so as soon as the user appended a group after ours, the
original ordering was not reconstructable and the check fired on a removal that
was entirely correct. Check 1 and check 2 both passed. Only check 3 fired, and
only spuriously.

The suite was green because `tests/test_install.sh` §4 put the user's hook under
**`PostToolUse`** — the one arrangement in which `PreToolUse`'s group order is
unperturbed. The weaker tier was tested only where it worked.

### Fix — the relaxation is paid for, not given away

Check 3 was not deleted (it is the only check that catches loss). It was split
in two, so that each half checks something it can establish without
reconstructing anything:

- **3a — order, exactly.** The groups that survive in `after` must be an
  order-preserving **subsequence** of the groups in `before`, per event. This
  needs no reconstruction, so it holds wherever our own group happened to sit,
  and it catches a group that appeared, was reordered, was rewritten, or moved
  between events.
- **3b — loss, order-insensitively.** Re-applying `install` must reproduce
  `before` with each event's **group list in canonical order**
  (`_groups_sorted`). Group order within an event is not a behaviour — Claude
  Code runs every matching group — so this is the place where order genuinely
  does not matter, and the only place the comparison is relaxed.

Failure reporting is now at group level (`matcher …, N handler(s), first
command …`) rather than indices into a sorted list, which would have been
unreadable.

All four damages `test_install.sh` §5 feeds the verifier are still caught, plus
two new ones (below).

---

## 2. `is_ours` was a substring match, and it deleted on install

### Reproduced first

A repo whose only hook is
`/my/own/hooks/agent_route_actuator.sh --mine` on matcher `Write`. After
`jev install --yes` the handler was **gone**, install's output said only
`note  1 stale jev entry(ies) … will be replaced`, and the handler survived
nowhere but the backup. Silent data loss in somebody else's repository.

`src/install.py:174-176`, `e["script"] in command` — a substring test.
`verify_removal` check 2 could not catch it because the strip and the check
used the **same `is_ours` predicate**: the verification was self-referential at
exactly this point.

### Fix — three parts

**(a) Ownership is exact, never a substring.** `owned_commands()` builds the set
of exact command strings that are ours, from two sources and no others:

1. what **this** install would write — `desired_entries()`, absolute under
   `$JEV_HOME`;
2. what an install into **this repo** actually wrote — the `entries[]` of
   `./.claude/jev-install.json`. This is the only thing that can still recognise
   an entry after `$JEV_HOME` has moved, and it is repo-local, so it can never
   claim ownership of anything in a tree jev was not installed into.

No marker key was added to the `hooks` array; the W2 reasoning against that
still stands (Claude Code parses that array, and a marker a harness might strip
leaves an entry we can no longer find). An exact absolute path anchored to
`$JEV_HOME` gives the same unambiguity without adding a key.

**(b) Removal is loud.** `install` now prints one line per entry it replaces,
naming the command, instead of a bare count. And a handler that **names** one of
our scripts but is not ours is reported explicitly at both install and
uninstall:

```
NOT OURS    PreToolUse / matcher Write
            /my/own/hooks/agent_route_actuator.sh --mine
            names one of jev's scripts but is not an entry this
            install wrote. LEFT EXACTLY AS IT IS — not replaced, not removed.
```

"We noticed and did nothing" is the only honest thing to say about a stranger's
hook that shares our filename.

**(c) The self-reference is broken.** `verify_removal` check 2 no longer calls
`is_ours`. It asks `installer_triples()` — the set of `(event, matcher, command)`
the **installer emits**, constructed from `config/registration.json` under this
`$JEV_HOME` plus the repo's install record. Ownership is now *constructed*
rather than *recognised*, so a mistake in the removal predicate can no longer be
ratified by the removal predicate. A new §5 case proves it: strip a lookalike
along with ours and the verifier reports it.

---

## 3. Also fixed

- **Symlinked `jev` now works.** `jev` walks the symlink chain (`readlink`, max
  40 hops) before taking `dirname`, so `ln -s /path/to/jev/jev /usr/local/bin/jev`
  resolves `JEV_HOME` to the checkout, not to `/usr/local/bin`. A `jev` that was
  **copied** away from its install cannot be rescued and now refuses with a
  message naming `JEV_HOME` and both fixes (`export JEV_HOME=…`, or a one-line
  wrapper) instead of a raw Python `No such file`.
- **A relative `JEV_HOME` is rejected in both readers.** `jev` refuses it with
  the `pwd -P` one-liner; `paths.resolve_jev_home()` raises with the same reason.
  The reason is in both messages: bash uses the value verbatim after an `is_dir`
  test while Python calls `.resolve()`, so `JEV_HOME=.` makes the *global kill
  switch* cwd-relative — precisely what the switch block's own comment says must
  never happen.
  **Handoff:** `hooks/*.sh` are another agent's this wave, so the canonical bash
  `# --- jev home` block still accepts a relative value verbatim. The CLI and
  `paths.py` now reject it, which closes the practical route in, but whoever owns
  the hooks should add the same `case "$JEV_HOME" in /*)` guard to the canonical
  block for symmetry. `tests/test_jev_home.sh` §1's bash-vs-python comparison was
  deliberately **not** given a relative case, because it would diverge and this
  wave cannot fix the bash side.
- **Installing from a git worktree warns.** `_warn_if_worktree` fires when
  `$JEV_HOME/.git` is a **file** rather than a directory, and says that the
  registered command is absolute, that removing the worktree makes it dangle
  (inert but silent), and that `jev uninstall` should be run first. This repo is
  itself a worktree, so the warning fires here.

---

## 4. Tests

`tests/test_install.sh` 42 → **55 assertions**, `tests/test_jev_home.sh`
26 → **37**.

New in `test_install.sh`:

- **§4b, the W5 case.** The audit's shape verbatim: install into a bare repo,
  user appends a `PreToolUse` group, `uninstall --yes`. Asserts exit 0, that
  `THE REST OF THE FILE IS NOT WHAT IT WAS` does **not** appear, that the tier is
  still named `STRUCTURALLY VERIFIED`, that the user's hook survives, that **no
  `agent_route_actuator.sh` is left registered**, and that `jev status` agrees.
  This is the assertion that would have caught the defect.
- **§5 (e)** the user's own groups reordered → caught (the order that matters is
  still exact); **(f)** a lookalike removed along with ours → caught by the
  now-independent check 2; plus a false-positive guard on the shape where our
  group sits **first** in `PreToolUse`, and direct assertions that
  `is_ours(lookalike)` is false and `is_ours(ours)` is true.
- **§6b**, end to end: a lookalike survives `install` **and** `uninstall`,
  `install` prints `NOT OURS`, does **not** print `REPLACING`, and our own entry
  is still removed by exact path.

New in `test_jev_home.sh` **§6**: relative `JEV_HOME` rejected by the CLI *and*
by `paths.py`; symlinked `jev` works and resolves to the install; a detached copy
fails loudly naming `JEV_HOME`; the worktree warning fires on a synthetic
`.git`-as-a-file and — the non-vacuity half — does **not** fire without it.

---

## 5. Suite state, honestly

`bash tests/run_all.sh` in the shared worktree: **exit 0, every section green**,
re-verified at handback time. `tests/run_all.sh` itself is untouched and **no
`guarded` line needed changing.**

Mid-wave, `tests/test_hook.sh` was transiently red (7 of 27) against another
agent's in-flight edits to `hooks/capture.sh` — a file this wave is forbidden to
touch. It was confirmed green at HEAD via a clean `git archive HEAD` checkout,
and it is green again now that the other agent's work has landed. This wave's
changes were additionally verified in isolation over HEAD-plus-W5's-six-files
(`.scratch/pivot/w5_suite_mine_only.sh`), which was also green end to end.

---

## 5b. Handoffs — two wordings this wave could not reach

1. **`hooks/*.sh` (another agent this wave).** The canonical `# --- jev home`
   block still accepts a relative `$JEV_HOME` verbatim. The CLI and `paths.py`
   now reject it, which closes the practical route in, but the block should get
   the same `case "$JEV_HOME" in /*)` guard for symmetry.
2. **`docs/REVERSIBILITY.md` (off-limits this wave).** It almost certainly
   repeats tier B's old claim that re-applying `install` "reproduces the
   pre-uninstall document **exactly**". After this fix the claim is "reproduces
   it up to the order of groups within one event, which is not a behaviour; the
   user's own groups are checked in exact order separately". The installer's own
   output and docstring were corrected here; the doc needs the same sentence.

## 6. Known edges, stated rather than found later

- **A user handler added INSIDE jev's own `Agent` group.** Strip leaves
  `{Agent, [theirs]}` and re-install adds `{Agent, [ours]}`, so check 3a fires
  and uninstall refuses — the same "leaves jev registered" outcome as the defect
  above, for a genuinely restructured document. Pre-existing behaviour, not
  introduced here, and it refuses safely rather than editing blindly. The right
  fix is for `merge_entries` to rejoin a group it recognises as its own, which is
  a design change rather than a defect fix.
- **A `$JEV_HOME` that moved AND an install record that was deleted** leaves an
  entry no exact predicate can recognise. Previously the substring match would
  have found it; now `uninstall` reports nothing registered. That is the price of
  exactness, and it is the safe direction — we decline to remove a handler we
  cannot prove is ours, rather than removing one that is not.

## 7. Scratch left behind

`.scratch/pivot/repro_w5.sh` — the two defect reproductions plus the symlink and
relative-`JEV_HOME` probes, runnable as-is.
`.scratch/pivot/w5_suite_mine_only.sh` — the suite harness described in §5.
Both are throwaway.
