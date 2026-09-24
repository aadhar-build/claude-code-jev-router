# JEV v0.2 router: execution plan

Base: `master` at 83340ba. Written 2026-09-24. Target machine: the owner's Mac (macOS, Apple silicon).
This folder is a plan, not code. Nothing in it is installed, armed or sent anywhere.
Decisions and open items: [DECISIONS.md](DECISIONS.md). Quick start: [README.md](README.md).

Citations are `file:line` on master 83340ba unless marked otherwise. Anything marked UNVERIFIED
was not checked on the Mac.

---

## 0. Status and how to use this folder

| Item | State |
|---|---|
| Research (options, audit, test triage, master delta) | done on the research box (Linux); not rerun on the Mac |
| Chunk 0 spike kit | `docs/v02/spike-c0/` (written in parallel by another agent) |
| Allowlist tool | `docs/v02/tools/count_spawns.sh` (same) |
| Findings | `docs/v02/findings/` (same) |
| Build chunks C1-C8 | not started |
| Live window | not scheduled; needs a separate owner go-ahead |

**Who runs what**

- **Owner (by hand):** W0 baseline on the Mac, the Chunk 0 spike in fresh interactive `claude`
  sessions (never `claude -p`), approving each wave, computing the allowlist, go-live and teardown.
- **Claude Code subagents:** each build chunk. One chunk per subagent, ≤10 minutes of tool calls,
  test written first, staged in a branch. Chunks marked "∥" may run at the same time.
  Two chunks never edit the same file at the same time.
- Nothing is pushed, installed or armed by a subagent. The owner reviews each wave's diff and merges it.

---

## 1. Verified facts, assumptions, unknowns

### Verified on master (read directly)

| # | Fact | Where |
|---|---|---|
| F1 | The actuator is a synchronous PreToolUse hook on `Agent`, timeout 10 s | `config/registration.json:8-11` |
| F2 | It always exits 0 (`trap 'exit 0' EXIT`, no `set -e`) | `hooks/agent_route_actuator.sh:97-98,664` |
| F3 | Switch order: JEV_HOME block, then `$JEV_HOME/.jev-disabled`, `~/.claude/jev-disabled`, `<repo>/.jev-disabled`. Recursion guards `JEV_ARM_SUBPROCESS`, `JEV_GRADER` | actuator `:155-159,172,176,203-204,222`; `docs/REVERSIBILITY.md:21-23` |
| F4 | It only ever rewrites `model`. `subagent_type` is read and echoed, never changed | actuator `:435,522,579` |
| F5 | The rewrite emits `permissionDecision: "allow"` | actuator `:521,578` |
| F6 | The `"opus"` literal is the fallback used ONLY when tiers.json is unreadable. The normal frontier path reads `tiers[frontier_tier].alias`. A pin test already exists | actuator `:329-332,430,456,596-606` |
| F7 | `frontier_tier` is `opus5`; `fable51` is deliberately absent pending JEV-28 | `config/tiers.json:98-99` |
| F8 | Breaker 3 failures / 900 s; 250 ms budget; `hook_ms` on each ledger row | `config/tiers.json:135-141`; actuator `:498` |
| F9 | Ledger is `$JEV_HOME/data/agent_route`, schema `agent-route-assignment-v2` with `project` (JEV-57 closed). Written before emit; unwritable ledger means no rewrite | actuator `:486,499,615-646` |
| F10 | Prompts sent to Jev are truncated at 60,000 chars (the start is kept). There is no redaction. `cwd` is sent in full | `src/state_builders.py:29,40,175,187` |
| F11 | Jev arm calls the Vercel AI Gateway (`/v1/evaluate`, model `typesafe-ai/jev`), key `AI_GATEWAY_API_KEY`; endpoint, model and timeout are overridable in `config/arms.json` | `src/arms/jev.py:38-39,124` |
| F12 | `capture.sh` spools to `$CLAUDE_PROJECT_DIR/spool/`, not `$JEV_HOME`, and exits 0 silently if absent; the worker reads `$JEV_HOME` | `hooks/capture.sh:240-241`; `src/paths.py:72-77` |
| F13 | `registration.json` registers the actuator only; `install.py` has no `async` support | `config/registration.json`; `src/install.py` (0 hits for `async`) |
| F14 | `surfaces.json` `agent_route.mode` is read only by the worker, never by install or the actuator | `src/worker.py:569-594` |
| F15 | Install is per-project into `<repo>/.claude/settings.local.json`; global install is rejected; one DIR per call | `src/install.py:16-27`; `jev:4-7` |
| F16 | Nothing in the repo may write `~/.claude/jev-disabled` ("Read-only to us") | `docs/REVERSIBILITY.md:22` |
| F17 | No deadline/expiry mechanism exists today (only the breaker TTL) | grep `deadline` in `hooks/`, `src/`: 0 hits |
| F18 | Three hooks exist: `agent_route_actuator.sh`, `capture.sh`, `inline_shadow_bash.sh` | `hooks/` |
| F19 | JEV-35's input-fidelity gate treats a changed `subagent_type` as a defect | `ISSUES.md:1782`; `PREREGISTRATION.md` A3.4 |
| F20 | JEV-62: the actuator has been installed on one of the owner's Mac projects since 2026-09-23 with no opt-out file; `doctor.py` falsely FAILs `switch-coverage` on foreign installs | `ISSUES.md:3922+` |
| F21 | W4 (Jev enters) is blocked on W0, W1, W3 and JEV-16 Run B only | `ISSUES.md:43` |
| F22 | The spec rules out launchd and any auto-start | `ISSUES.md:1897`; `src/worker.py:9` |
| F23 | Local runtime chosen in SPEC: `openjev` with `OPENJEV_BACKEND=mlx`, ~16 GB free RAM, Apple silicon | `SPEC.md:289` |

### Verified in Claude Code docs (code.claude.com/docs/en/hooks, /sub-agents)

- Async hooks cannot block or control behaviour: `decision`, `permissionDecision` and `updatedInput`
  have no effect. So Jev can never decide the spawn that triggered it.
- An agent file's body **replaces** the system prompt. A `gp-*` clone does not carry general-purpose's prompt.
- Agent frontmatter supports `model` (`sonnet|opus|haiku|fable|inherit|<id>`) and `effort`.
- When two hooks both return `updatedInput` for the same call, the order is not deterministic.
- SubagentStart cannot set the model.

### Assumptions (treated as true until a test says otherwise)

- A1. A PreToolUse `updatedInput` that changes `subagent_type` spawns the new type. **Chunk 0 tests this.**
- A2. Project-scoped agents in `<repo>/.claude/agents/` resolve for sessions started in that repo.
- A3. Apple's `/usr/bin/python3` on the Mac is 3.9.x, so `test_python_floor` behaves as designed there.

### Unknowns

- U1. Does frontmatter `effort` take effect for a subagent? (Chunk 0 step 7.)
- U2. Does any other PreToolUse plugin on the Mac also return `updatedInput` for `Agent`? (Chunk 0 + C3 check.)
- U3. Does `openjev` accept the `/v1/evaluate` request body unchanged? UNVERIFIED. (C-OFF.)
- U4. The Mac's full test-suite baseline. Not yet run. (W0.)
- U5. Is the `claude-fable-5-1` row present in `pricing.json`? (C1.)

---

## 2. Architecture and decision flow

```
Parent calls Agent(subagent_type?, model?, prompt)
 │
 ├─[SYNC PreToolUse, ≤250 ms, no network]  hooks/agent_route_actuator.sh
 │    1. JEV_HOME resolve → 3 kill switches → deadline file (new)   ── any hit: exit 0, no output
 │    2. jq present? no → exit 0 (inert)
 │    3. caller set model (≠ inherit)            → keep; no type rewrite
 │    4. subagent_type in tiers table            → model rewrite (v0.1, unchanged)
 │    5. subagent_type ∈ {general-purpose, absent/empty}
 │         AND gp_arms.enabled
 │         AND target file <repo>/.claude/agents/gp-*.md exists
 │                                              → arm = hash(tool_use_id) mod k (logged):
 │                                                   static  : leave (control)
 │                                                   tiered  : subagent_type := gp-lite|gp|gp-hard (fixed policy, not Jev)
 │                                                   gp-same : subagent_type := gp-same (isolates prompt swap)
 │    6. anything else (specialised, plugin-namespaced "x:y", fork, unknown) → leave, byte-identical
 │    error with a payload → fail to frontier_tier (opus5); breaker; ledger row first; exit 0 always
 │
 ├─[ASYNC PreToolUse, ~10 ms, cannot change the spawn]  hooks/capture.sh → $JEV_HOME/spool/
 │    cwd denylist applied at capture → drop row, no spool file
 │
 └─ offline / shadow: src/worker.py (started by hand) → build_agent_route → REDACT (new, hard gate)
        → Jev arm (hosted gateway, or local openjev) → "what Jev would have chosen" → joined to ledger
```

**Instant decision** = type table + fixed tiered-type policy. **Jev** advises in shadow only.

### Off-switch matrix

| Switch | Scope | Stops | Proof test |
|---|---|---|---|
| `$JEV_HOME/.jev-disabled` | every repo | all three hooks | existing `tests/reversibility.sh` |
| `<repo>/.jev-disabled` | one repo | all three hooks there | existing |
| `~/.claude/jev-disabled` | machine | all three hooks | existing; **owner touches it by hand only** |
| `$JEV_HOME/.jev-deadline` in the past | every repo | all three hooks | new, C6 |
| `gp_arms.enabled: false` | every repo | the type rewrite only | new, C3 |
| remove `<repo>/.claude/agents/gp-*.md` | one repo | type rewrite (guard skips) | new, C3 |
| `./jev uninstall <repo> --yes` | one repo | registration removed, quiescent | existing `tests/test_install.sh` |

---

## 3. Chunks

Rules for every chunk: write the failing test first and show it red; make it green; run the
chunk's suites plus `tests/reversibility.sh`; mutation check (revert the fix, test goes red,
restore). ≤10 minutes of tool calls. No network, no install, no `~/.claude` writes.

### C0: spike (owner-run, gates everything)

- **Goal:** prove A1 and read U1, U2 on the Mac.
- **Step 0 (before anything):** run `./jev status` in the JEV repo, then check the JEV-62 project for `.claude/jev-install.json` and a `.jev-disabled` file (`status` reports on the repo it is run from).
  Record whether it is armed. If it is, either `touch <that-repo>/.jev-disabled` or
  `./jev uninstall <that-repo> --yes` before the spike, because it changes the baseline and would be a
  second hook rewriting `Agent` input.
- **Files:** `docs/v02/spike-c0/` only, copied to a throwaway directory. Project scope only.
- **Test:** the kit's `check.sh` (RUNBOOK steps 1-9, including both negative controls).
- **Pass:** `agentType == gp-lite`, first model `claude-haiku-4-5*`, negative controls clean,
  probe log shows exactly one rewriter. **Fail:** drop tiered types; v0.2 becomes model-only
  (C2, C3 shrink to fable + guard tests). **Inconclusive:** re-run; do not read as fail.
- **Dependencies:** W0. **Parallel:** no.

### C1: fable as a selectable top tier

- **Files:** `config/tiers.json`, `tests/test_agent_actuator.py`.
- **Failing test first:** asserts `tiers.fable51 = {alias: "fable", resolved_prefix: "claude-fable-5", rank above opus5}`
  AND `frontier_tier == "opus5"`.
- **Acceptance:** green; the `_frontier_tier_comment` records the owner decision and JEV-28 status;
  a `pricing.json` row for `claude-fable-5-1` exists or its absence is reported (U5).
  The `"opus"` pin test is **not** rewritten (it exists, F6).
- **Deps:** C0. **Parallel:** ∥ C2.

### C2: tiered agent files

- **Files:** `agents/gp-lite.md`, `agents/gp.md`, `agents/gp-hard.md`, `agents/gp-same.md` (in the
  repo as templates), `tests/test_tier_agents.py`.
- **Failing test first:** each file has no `tools:`/`disallowedTools:` key, a model from the enum,
  an allowed effort; `gp-same` is `model: inherit` with no effort; body is a minimal general-purpose brief.
- **Acceptance:** green. The files are copied into `<repo>/.claude/agents/` only at go-live, never `~/.claude/agents/`.
- **Deps:** C0 pass. **Parallel:** ∥ C1.

### C3: guarded type rewrite + arm assignment + fidelity-gate amendment

- **Files:** `hooks/agent_route_actuator.sh`, `config/tiers.json` (`gp_arms` block, default **off**),
  `tests/test_agent_actuator.sh`, `tests/test_agent_actuator.py`, `ISSUES.md` (JEV-35 gate text),
  `PREREGISTRATION.md` (A3.4 amendment note).
- **Failing tests first:**
  - 15+ specialised types, plugin-namespaced `x:y` types, `fork`, and unknown types → byte-identical passthrough.
  - `general-purpose` with a caller `model` → untouched.
  - `general-purpose` with the target agent file missing → untouched.
  - arm assignment deterministic on `tool_use_id`; ledger row carries original and rewritten type (schema v3).
  - `gp_arms.enabled: false` → output byte-identical to v0.1.
  - Fidelity gate becomes "byte-identical except `subagent_type` when the rule is `gp_arms`".
  - **Exactly-one-rewriter check:** a doctor/test step lists every PreToolUse hook matching `Agent`
    across user, project and local settings and plugins, and FAILs if more than one can return `updatedInput`.
- **Acceptance:** actuator suites green; median hook time still ≤250 ms.
- **Deps:** C1 (shares `tiers.json`). **Parallel:** ∥ C4.

### C4: async capture surface

- **Files:** `config/registration.json` (capture entry, `async: true`), `src/install.py` (emit `async`),
  `hooks/capture.sh` (spool to `$JEV_HOME/spool`; JEV-60 cwd-guard residual), `config/surfaces.json`
  (`agent_route: capture_only`), `tests/test_install.sh`, `tests/test_hook.sh`.
- **Failing tests first:** install writes an `async: true` capture entry and the actuator stays sync;
  a foreign-install capture lands in `$JEV_HOME/spool/ready`, not the routed repo; uninstall removes both entries.
- **Acceptance:** install, hook, jev_home and reversibility suites green.
- **Deps:** C0. **Parallel:** ∥ C3 (no shared file).

### C5: redaction, denylist and cap (HARD GATE before any send)

- **Files:** `src/state_builders.py` (`redact_agent_route()`), `src/arms/jev.py` (refuse to send an
  unredacted state), `hooks/capture.sh` (cwd denylist), `src/doctor.py` (JEV-62 fix),
  `tests/test_agent_route.py`, `tests/test_hook.sh`.
- **Failing tests first:**
  - secret patterns (common API-token prefixes, cloud access-key IDs, `NAME_KEY` / `TOKEN` assignments, JWTs, private-key blocks, email addresses) replaced by tags; the test fixtures hold the concrete patterns;
  - `prompt` capped at the chosen N (default 4,000 chars, see DECISIONS O1) with a `truncated` flag;
  - `cwd` reduced to its basename;
  - a denylisted cwd (personal data, credentials, agent workspaces) leaves no spool file and one drop row;
  - the Jev arm raises if handed a state without the redaction marker (the gate lives in code, not docs);
  - doctor passes `switch-coverage` for an absolute-path foreign registration (JEV-62).
- **Acceptance:** green, with mutation check on each redaction rule.
- **Deps:** C4 (shares `capture.sh`). **Parallel:** no.

### C6: deadline file (Mac-portable expiry)

- **Files:** switch block in all three hooks (byte-identical rule), `jev` (`window-start <hours>` writes
  `$JEV_HOME/.jev-deadline` as epoch seconds; `window-stop` touches `$JEV_HOME/.jev-disabled` and prints
  per-repo `jev uninstall` commands), `.gitignore` (`.jev-deadline`), `tests/test_window.sh`.
- **Failing tests first:** deadline in the past → every hook exits 0 with no output; deadline in the
  future → normal; unreadable/garbage deadline → treated as expired (fail closed = off); check uses
  `date -u +%s` only (no GNU flags); nothing under `$HOME/.claude` is written.
- **Acceptance:** `tests/reversibility.sh` ends `OFF IS PROVEN EQUAL TO VANILLA` with the new path included.
- **Deps:** C3, C5 (touches all hooks). **Parallel:** no; runs alone.

### C7: report

- **Files:** `src/report.py` (agent_route section), `tests/test_report.py`.
- **Failing test first:** metrics of §6, and `INCONCLUSIVE` printed whenever a sample minimum is not met.
- **Deps:** C3 (ledger v3). **Parallel:** ∥ C-OFF.

### C-OFF: offline Jev evidence (local openjev first, then replay)

- **Goal:** get Jev evidence without the live window. Recommended to run **before** any hosted send.
- **Part 1 (≤10 min, owner's Mac):** start `openjev` with `OPENJEV_BACKEND=mlx` (~16 GB free RAM); point
  `config/arms.json` `endpoint` at it in a local override; send ONE synthetic fixture. Record whether the
  `/v1/evaluate` body and response parse unchanged (U3). If yes, prompts can stay on the Mac.
- **Part 2:** replay historical prompts (redacted by C5, exclusions applied) plus the 12-task fixture
  suite through static / tiered / Jev-policy / constant arms; write results to `$JEV_HOME/data/`.
- **Files:** `tests/test_openjev_compat.py` (skips when no local server), `config/arms.json` override
  documented, no source change unless the body differs.
- **Deps:** C5. **Parallel:** ∥ C7.

---

## 4. Wave schedule

| Wave | Runs | Owner does before the next wave |
|---|---|---|
| W0 | Owner: `./jev status`, JEV-62 check, full `tests/run_all.sh` on the Mac, record pass/fail per suite in `docs/v02/findings/` | Accept the baseline; generate `data/synthetic` (`python3 src/make_synthetic.py`) if needed |
| W1 | Owner: Chunk 0 spike | Record PASS / FAIL / INCONCLUSIVE; if FAIL, tell wave 2 "model-only" |
| W2 | Subagents: C1 ∥ C2 | Review diffs, merge |
| W3 | Subagents: C3 ∥ C4 | Review; confirm exactly-one-rewriter check passes on the Mac |
| W4 | Subagent: C5 | Review the redaction tests yourself |
| W5 | Subagent: C6 (alone) | Run the 60-second deadline drill (§5) |
| W6 | Subagents: C7 ∥ C-OFF part 1 | Decide hosted vs local Jev (DECISIONS D5) |
| W7 | Owner: allowlist (`tools/count_spawns.sh`), staging, go-live, 6-hour window | Teardown and sha256 checks |
| W8 | Subagent: C-OFF part 2 replay + report | Read the pre-registered verdict |

---

## 5. Staging gates, go-live, teardown

### Gates (all green on the Mac before go-live)

- Actuator, install, jev_home, hook, reversibility, window, tier-agents, agent_route and report suites.
- `OFF IS PROVEN EQUAL TO VANILLA` with the new paths.
- Any W0 failure is either fixed or waived with a written reason. `test_python_floor` is not waived blind:
  on the Mac it should pass (A3).
- Exactly-one-rewriter check: PASS.
- **60-second drill:** in one throwaway repo, install, copy gp-* agents, `./jev window-start` with a
  60-second deadline, spawn once (rewritten), wait 60 s, spawn again (untouched, hook silent), uninstall,
  sha256 matches the pre-state.

### Go-live (separate explicit owner confirmation)

1. For each allowlisted repo (`<repo-A>`, `<repo-B>`, …): record
   `shasum -a 256 <repo>/.claude/settings.local.json` (or "absent") and the listing of `<repo>/.claude/agents/`.
2. `./jev install <repo> --yes` per repo. Never a repo holding personal data, credentials or agent workspaces.
3. Copy `agents/gp-*.md` into `<repo>/.claude/agents/`.
4. `./jev window-start 6` (writes `$JEV_HOME/.jev-deadline` = now + 21600).
5. Only sessions started after this point are routed. Say so to yourself; old sessions keep old hooks.

### Teardown (at or after the deadline; the hooks are already silent)

1. `touch $JEV_HOME/.jev-disabled`.
2. `./jev uninstall <repo> --yes` for each allowlisted repo; note Tier A (byte restore) or Tier B (structural).
3. `rm <repo>/.claude/agents/gp-*.md`.
4. `shasum -a 256 <repo>/.claude/settings.local.json` equals the recorded value (Tier A), or the file is
   structurally equal (Tier B). The agents listing equals the pre-state.
5. `rm $JEV_HOME/.jev-deadline`. Leave `.jev-disabled` in place until the next deliberate run.

---

## 6. Measurement plan (pre-registered)

The 6-hour window is **safety only**. Expected volume is a few general-purpose spawns per day.

**Window pass criteria (all required):** 0 blocked spawns; 0 non-zero hook exits; p95 hook time
<250 ms; 0 rewrites of a non-allowlisted type; resolved model matches the assigned tier (prefix);
spool rows == ledger rows (minus logged drops); 0 unredacted sends. Any breach = FAIL and teardown.

**Evidence about Jev** comes from C-OFF: the redacted historical replay and the 12-task fixture suite
(3 runs each) under static, tiered, gp-same, Jev-policy, constant arms.

| Metric | Definition | Minimum n |
|---|---|---|
| Agreement | Jev shadow tier vs static/arm tier, Cohen's κ | 30 paired items |
| Cost per spawn at equal success | resolved-model cost; success = not re-delegated on the same objective within 30 min and no parent-reported failure | 30 per arm |
| Rework rate | re-delegation or parent-reported failure | 100 per arm |
| Attrition | unjoined or dropped rows by tier | report always |
| Fail-to-frontier / breaker | counts | report always |

**Outcomes:** PASS = Jev policy beats static on cost at equal success (W4 ship rule). FAIL = it does
not, at or above the minimums. **INCONCLUSIVE** = any minimum not met; this is not "Jev failed" or
"Jev works". **Controls:** `static` (vanilla), `gp-same` (separates the prompt swap from the model
change). No live constant-sonnet arm.

---

## 7. Risks and rollback

| Rank | Risk | Mitigation |
|---|---|---|
| 1 | Private prompt text reaches a third party | C5 hard gate in code; denylist; cap; local openjev first (C-OFF) |
| 2 | Tiered clones lose general-purpose's system prompt and behave differently | `gp-same` control; `gp_arms` default off |
| 3 | Two hooks rewrite `Agent` input, order nondeterministic | JEV-62 check in C0; exactly-one-rewriter check (C3) |
| 4 | Window is underpowered and someone quotes it | pre-registered INCONCLUSIVE |
| 5 | `permissionDecision: allow` skips the permission prompt for rewritten spawns | DECISIONS O3 |
| 6 | Expiry missed while the Mac sleeps | deadline is checked on every hook call, so it holds across sleep/reboot; agent files stay until teardown |
| 7 | fable costs more than opus5 on errors | frontier stays opus5 |

| Rollback lever | Effect | Proof |
|---|---|---|
| `touch $JEV_HOME/.jev-disabled` | all hooks silent everywhere | `tests/reversibility.sh` |
| `touch <repo>/.jev-disabled` | silent in one repo | same |
| deadline in the past | all hooks silent | `tests/test_window.sh` (C6) |
| `gp_arms.enabled: false` | v0.1 behaviour, byte-identical | C3 test |
| `rm <repo>/.claude/agents/gp-*.md` | rewrite skipped | C3 test |
| `./jev uninstall <repo> --yes` | quiescent, sha256 restored | `tests/test_install.sh` + teardown step 4 |
