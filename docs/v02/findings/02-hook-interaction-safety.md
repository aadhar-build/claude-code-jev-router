# 02. Hook interaction and rollout safety audit

Source: research subagent report, 2026-09-24; claims marked (unverified) were not independently confirmed.

Read-only audit of what else can fire on an `Agent` call on the research box, how Claude Code combines PreToolUse hooks, and what a per-repo rollout would expose. Line numbers for docs refer to the fetched copies of https://code.claude.com/docs/en/hooks, /settings and /hooks-guide on 2026-09-24 (they may shift).

## 1. Other hooks that can fire on Agent
- Most user-level and project-level hooks on the research box use matchers such as `Bash|Grep`, `Read|Glob`, `Edit|Write`, or SessionStart/Stop; none of these match `Agent`.
- One user-level PostToolUse hook has no matcher (fires on every tool, including Agent). It is observational: it logs tool name, session id and cwd, classifies Agent as "other", logs no prompt, and always exits 0.
- **A PreToolUse plugin with no matcher fires on every tool, including Agent.** For Agent it loads all of its rules without event filtering; rules are read from `./.claude/<plugin>.*.local.md` relative to the session cwd. A rule whose condition names an Agent input key (`prompt`, `subagent_type`, `model`) would match. It can emit `permissionDecision: "deny"`. It never emits `updatedInput` (0 hits when grepped). On the research box no rule files existed anywhere shallow under the home directory, so it returned `{}` on Agent. Resolved plan item U4: it fires on Agent, cannot rewrite, and can deny only if a rule file exists in the session cwd.
- A third-party observability plugin ships whole transcripts (prompts included) on Stop/SessionEnd. This is existing exposure, not something the router adds, but a rollout should be aware of it.

## 2. Two PreToolUse hooks with `updatedInput` or deny (verified from docs)
- hooks.md ~L416: "All matching hooks run in parallel." Identical handlers are deduplicated (per that line).
- hooks.md ~L1819: precedence when hooks disagree is `deny` > `defer` > `ask` > `allow`.
- hooks.md ~L1816: `updatedInput` "replaces the entire input object".
- hooks-guide.md ~L963: when several PreToolUse hooks return `updatedInput`, "the last one to finish takes effect. Since hooks run in parallel, the order is non-deterministic. Avoid having more than one hook modify the same tool's input."

Implications:
- Two rewriters on one call give an order-dependent result with no merge. On the research box no other hook emitted `updatedInput` for Agent, so there was no clobber risk today.
- Silent clobber could come from a future second rewriter, or from the router hook installed twice (for example once in user settings and once in a project file with a different command string, which defeats dedup).
- Build requirement: assert at most one `updatedInput` emitter on Agent (the doctor check can scan every loaded hook source), and assert no plugin rule files exist in an allowlisted repo.
- A deny from any hook overrides the router's allow. That is fail-safe (the rewrite is suppressed, not the spawn).

## 3. Scope of `settings.local.json`
Verified from https://code.claude.com/docs/en/settings (~L405-410, ~L477):
- User scope is `~/.claude/settings.json` only. `.claude/settings.local.json` is project-local ("in this one project only"). There is no user-level `settings.local.json`.
- A session started in a subdirectory of a git repo uses the file at the repo root.
Assumed, not tested (plan item U1): the project root for a non-git directory is the cwd rather than the nearest ancestor holding `.claude/`. Resolve with `/status` -> "Setting sources" in a fresh session under an allowlisted repo before relying on it. Practical rule: never allowlist a home directory or any directory that doubles as a config or workspace root.

## 4. Candidate-repo selection (method and result, no inventory)
Method: distinct `tool_use` ids for Agent in `~/.claude/projects/**/*.jsonl`, counted by event timestamp (not file mtime, which over-counts old spawns) over the last 21 days. `tools/count_spawns.sh` reproduces this.
Findings:
- Delegation ran at a few spawns per day, with a burst on one day and 0-4 per day afterwards.
- About 94% of recent spawns came from two directories that must be excluded from any allowlist (a home directory and an agent workspace holding memory files).
- Low-risk code repositories had roughly 0-3 spawns each over 21 days. A 6-hour window on a sensitivity-safe allowlist therefore yields about zero routing data. It can prove install and teardown safety only (consistent with plan decision D6).
Selection rule: allowlist only code repos with no personal data, credentials or agent workspaces; grep for secrets before including any; keep to five or fewer; record a sha256 pre-state for any repo that already has a `settings.local.json`.

## 5. Session types
- Hooks load per session from that session's project settings, so background or fleet sessions are affected only if they start in an allowlisted repo.
- The `subagent_type` rewrite is planned for general-purpose/absent spawns only (`unmapped_action: leave`, `explicit_model_action: keep`); this is (unverified): taken from plan text, the actuator was not re-read for this audit. The C3 test must prove specialised types pass through byte-identical, and confirm that the `model` rewrite is guarded the same way.
- Hooks also fire inside subagents (hooks.md ~L768 lists `agent_type`), so nested spawns from a routed subagent can be re-routed.

Residual risks:
- (a) Copying tier agent files into `~/.claude/agents/` makes them machine-wide immediately, selectable in sensitive sessions even though the hook is per-repo. Prefer per-repo `.claude/agents/`.
- (b) `build_agent_route` sends the full prompt and cwd with no redaction (see 04-master-delta.md for the truncation nuance).
- (c) Third-party transcript export (section 1) is pre-existing.

## Verdict: SAFE WITH CONDITIONS
1. Allowlist only low-risk code repos; never a home directory, agent workspace, personal-data repo or a directory holding secrets.
2. No send to Jev during the window, or redaction plus a cwd denylist enforced in code and tested (plan item D2).
3. Doctor or staging asserts exactly one Agent `updatedInput` emitter and no plugin rule files in allowlisted repos.
4. Resolve U1 with `/status` in a fresh session.
5. Test that specialised types and an explicit `model` pass through unchanged.
6. Install tier agent files only for the window and remove them at teardown with sha256 verification, or accept that they are machine-wide.
7. Accept that the window yields about zero routing data.
