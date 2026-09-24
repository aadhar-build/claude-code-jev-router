# 04. Delta review of the v0.2 plan against `origin/master`

Source: research subagent report, 2026-09-24; claims marked (unverified) were not independently confirmed.

Read-only comparison of the plan's assumptions (written against `main`, a one-commit "v0.1" squash) with `origin/master` (HEAD 83340ba, development line). Only grep/sed/diff/git log were run; no tests, no network. "M" = master, "C" = the `main` clone.

## 0. Headline
Code differences between M and C are tiny: the actuator header comment (M:11-41) and `config/registration.json:4` (`_not_armed` note), both from 83340ba, plus redaction of one session id in a few files. `capture.sh`, `tiers.json`, `surfaces.json`, `state_builders.py`, `arms/jev.py`, `install.py`, `jev`, `REVERSIBILITY.md`, `worker.py` are byte-identical. Master adds `ISSUES.md`, `FINDINGS.md`, `PREREGISTRATION.md`, the SPEC archive, `data/baseline/*` and `reports/*`. Most plan claims survive; what changes is semantics that 83340ba makes explicit.

## 1. Actuator (`hooks/agent_route_actuator.sh`, 664 lines)
| Claim | Verdict | Evidence |
|---|---|---|
| sync PreToolUse on Agent | Confirmed | `config/registration.json:8-11` (timeout 10) |
| `trap 'exit 0' EXIT`, always exits 0 | Confirmed | :97, :664; no `set -e` :98 |
| switch order: `JEV_HOME` block, then three switches | Confirmed | :155-159, :203-204, :222; recursion guards :172, :176 |
| jq check, then `updatedInput: $ti + {model}` | Confirmed | :323-324 (missing jq goes inert, not silent), :522/:579 |
| hardcoded "opus" fail-to-frontier | Nuance | One literal `FRONTIER_FALLBACK_ALIAS="opus"` at :332, used only when `tiers.json` is unreadable (:596-606). The normal frontier path reads `tiers[frontier_tier].alias` (:430, :456). A test already asserts the literal equals the tier alias (comment :329-331 cites `tests/test_agent_actuator.py`), so the plan's proposed "pin test" already exists |
| explicit model kept; `inherit` ignored | Confirmed | :442-450; `config/tiers.json:129,132` |
| unmapped leave | Confirmed | :452-460; `tiers.json:126` |
| breaker 3 failures / 900 s | Confirmed | `tiers.json:135-138`; :336-337, :386, :655 |
| 250 ms budget | Confirmed | `tiers.json:141`; `hook_ms` on each row :498 |
| ledger | Confirmed and changed | `$JEV_HOME/data/agent_route`, schema `agent-route-assignment-v2` with `project` (:486, :499+; JEV-57 closed in 8f80d24). Ledger is written before the rewrite is emitted; unwritable ledger means no rewrite and inert (:615-646) |
| `subagent_type` rewrite or effort actuation | Not present on master | The actuator only ever sets `model`. ISSUES.md has no ticket for a type rewrite or effort actuation; JEV-35 treats a changed `subagent_type` as a defect. Effort appears only as arm config (JEV-41: `effort` unsupported on Haiku 4.5) |
| New in 83340ba | Header :11-41 | "THERE IS NO SHADOW MODE FOR THIS ACTUATOR. Registering it IS arming it." `surfaces.json` `mode` is read by neither the actuator nor `install.py` |

## 2. `config/tiers.json`
Unchanged: version `tiers-w1-2026-09-21`; tiers haiku45/sonnet5/opus5; `frontier_tier: opus5` (:99); the frontier-plus tier is "deliberately absent ... JEV-28 has not cleared it" (:98); `general-purpose` has tier null (:103-107). JEV-28 is still open. The plan names that tier `fable5` / prefix `claude-fable-5`; repo vocabulary is `fable51` / `claude-fable-5-1`. Pick one; the prefix `claude-fable-5` matches both.

## 3. Async and shadow machinery
- `capture.sh` is a JSON-free spooler (no network), with `drop()` attrition rows (:169-174) and a cwd guard (:200-236). It spools to `$CLAUDE_PROJECT_DIR/spool/{tmp,ready}` (:53, :240-243) and exits silently if those directories are absent, while the worker reads `paths.ROOT == JEV_HOME` (`src/paths.py:72-77`). In a foreign install it would write into the routed repo or nowhere, and the worker never sees it. Not foreign-install-ready; JEV-60 (open) also tracks a cwd-guard residual.
- `capture.sh` is not registered by install: `registration.json` entries contain the actuator only, and `install.py` has no `async` support (0 grep hits).
- `surfaces.json` `agent_route.mode: "off"` (:26-32) is read only by the worker (`worker.py:569-572`; `capture_only` skips arms :594). The plan's "`surfaces.json capture_only` plus install emits async" is two unrelated switches; the install half needs `registration.json` and `install.py` work.
- `build_agent_route` fields confirmed (`src/state_builders.py:91-184`), model withheld. Contradicting the plan: truncation exists (`_truncate_tail`, `MAX_STATE_CHARS=60_000`, :29, :184-191). No redaction, and cwd is sent verbatim (:175).
- `src/arms/jev.py` confirmed: hosted gateway endpoint and model (:38-39), key via `paths.require("AI_GATEWAY_API_KEY")` (:124); endpoint, model and timeout are overridable in `config/arms.json`.
- A local runtime is chosen in SPEC (SPEC.md:289: `razorback16/openjev`, MLX backend, Apache-2.0, about 0.2-0.4 s per 3-question request on Apple silicon, needs about 16 GB free RAM; a low-RAM fallback `jaredpalmer/kev` at :291) but is not wired. Whether openjev speaks the same `/v1/evaluate` body so that only `arms.json` `endpoint` changes is (unverified).

## 4. Installer and reversibility
- Per-project install into `<DIR>/.claude/settings.local.json`, absolute `$JEV_HOME/<script>` command, record `.claude/jev-install.json`, Tier A byte-restore / Tier B structural (`src/install.py:16-80`, :105-106, :158-182). CLI: `./jev install DIR --yes`, one DIR per call (`jev:4-7`); a multi-repo allowlist is a loop over the CLI (no batch mode; a thin wrapper, not a new build).
- Switches (`REVERSIBILITY.md:21-23`): `$JEV_HOME/.jev-disabled` (global), `~/.claude/jev-disabled` (machine-wide; "Read-only to us; nothing here ever writes it"), per-project. Since ca8ae71 all three hooks honour all three. Switch set is not the same as quiescent (`install.py:64-80`). Global install is rejected (`install.py:16-27`).
- **JEV-62 (83340ba, `ISSUES.md`):** on 2026-09-23 the owner ran `./jev install <project> --yes` on a Mac with no `.jev-disabled`, so the actuator is or was live there, and `doctor.py` falsely FAILs `switch-coverage` for absolute-path foreign registrations (`reversibility.py:94`, `doctor.py:246-250`). `tests/test_jev_home.sh` passes 37/0 on the foreign shape. The plan assumed nothing was armed; that is true only of the research box.

## 5. Commits that matter
bcd982f W1 static floor; 0f5901f W2 install/`JEV_HOME`/switches; b460b30 W5 uninstall fix; 8f80d24 JEV-57 ledger `project` (v2); ca8ae71 machine-wide switch in all hooks; cc1f7fc/6058638 JEV-60/61 residuals; 83340ba arming-doc correction plus JEV-62; df79e67 W3 accuracy gate; 652d3e8 JEV-34 shadow surface. W4 (ISSUES.md:43) is "Jev enters, aimed at the general-purpose residue", ship gate beats static rule on realised cost at equal task success. JEV-37 (`worker.py:9`) rules out launchd or any auto-start on purpose. JEV-51: the kill switch must stop the worker too.

## 6. Portability
- Already portable: openssl for sha (actuator :371-377), `jq -n now` for sub-second time (bash 3.2), `stat -f || stat -c` (`tests/lib/live_guard.sh:61-62`), `date -u +fmt` only.
- Test-only hazards: `shasum -a 256` in `reversibility.sh:53`, `test_install.sh:32`, `test_agent_actuator.sh:233`; `tests/test_python_floor.py:46` pins `/usr/bin/python3` (see 03-test-triage.md). No systemd, at or launchd anywhere in `hooks/` or `src/`, so a plan step using `systemd-run` is Linux-only and a launchd one-shot would violate JEV-37. No deadline file exists on master (only the breaker TTL). Recommendation: a hook-checked `$JEV_HOME/.jev-deadline` (epoch seconds, compared with `date -u +%s`) in the canonical switch block of every hook. It needs no scheduler and survives reboots; teardown stays manual.

## 7. Amendments per chunk
- C0: do not frame as "only if nothing is live"; check the install state of any machine that ran JEV-62's install. On macOS run the spike in a throwaway repo.
- C1: use one tier name consistently; frontier stays opus5; drop the "pin test" (it exists); add a pricing check and a JEV-28 note.
- C2: also allow per-project `<repo>/.claude/agents/`, the only way to honour "never machine-wide".
- C3: contradicts JEV-35 (type change is a defect). Record the owner's decision in ISSUES, and change the input-fidelity gate to "byte-identical except `subagent_type` when rule=gp_arms". The ledger row must carry original and rewritten type (schema v3?).
- C4: rewrite. Needs a `registration.json` capture entry, `install.py` `async` support, the capture spool moved to `$JEV_HOME/spool`, `surfaces.json` `agent_route` -> `capture_only`, and the JEV-60 fix.
- C5: truncation already exists at 60k (head kept), so 4k is a new decision. Redaction and cwd basename are new. Reuse `capture.sh drop()` for exclusion rows. Add the JEV-62 doctor fix.
- C6: never write `~/.claude/jev-disabled` from a script (repo invariant; install test forbids `$HOME` writes). Use `$JEV_HOME/.jev-disabled` plus per-repo `jev uninstall`; replace `systemd-run` with the deadline file.
- C7: unchanged; rerun `test_report`/`test_jev16`/`test_board` on master before treating them as blockers.
- New C-offline: evaluate openjev as a local backend via an `arms.json` endpoint override if the target Mac has enough free RAM; otherwise redacted gateway replay only on approval.

## Plan claims found wrong
1. "No redaction and no truncation": truncation exists (`state_builders.py:29,184-191`).
2. Hardcoded "opus" as a new sync risk: the sync test exists and the literal is fallback-only.
3. C4's `surfaces.json capture_only` plus install emitting async: install ignores `surfaces.json` and registers no capture hook; `capture.sh` would spool into the routed repo.
4. C6 writing `~/.claude/jev-disabled`: violates a stated invariant.
5. "Nothing is armed anywhere": JEV-62 shows a live foreign install (2026-09-23).
6. `test_python_floor` cause: Apple-`/usr/bin/python3`-specific; others need `data/baseline/` (rerun on master).
