# JEV v0.2 decisions

Owner decisions are final as of **2026-09-24**. Where the owner chose differently from the
research recommendation, both are recorded. Open items each carry a recommended default that
applies until the owner says otherwise.

## Decided (2026-09-24)

### D1. Base ref is `master`
`master` (83340ba) is the development line. `main` is a one-commit v0.1 publish that lacks
`ISSUES.md` and `data/baseline/`, which explained most test failures seen on the research box.

### D2. `fable51` (alias `fable`) becomes a router-selectable top tier; frontier stays `opus5`
- Added to `config/tiers.json` as a choice above `opus5` (chunk C1). The tier name follows the
  repo's vocabulary (`fable51`, resolved prefix `claude-fable-5`).
- `frontier_tier` (the fail-to-frontier target) **stays `opus5`**. Reason: every error, breaker
  and unreadable-config path lands on the frontier tier, so making fable the frontier would raise
  the cost of every failure, not just of the tasks that need it. The owner can revisit this.
- JEV-28 (fable clearance) is still open; C1 records that in the tier comment.

### D3. The hook may rewrite `subagent_type` to tiered agents, with a guard
- Only for `general-purpose` or an absent/empty type. Never for a specialised type, never for a
  plugin-namespaced type (`x:y`), never when the caller set `model`.
- Targets: `gp-lite`, `gp`, `gp-hard`, plus the control `gp-same`.
- This **contradicts** the JEV-35 input-fidelity gate (`ISSUES.md:1782`, `PREREGISTRATION.md` A3.4),
  which treats a changed type as a defect. C3 amends that gate to "byte-identical except
  `subagent_type` when the rule is `gp_arms`" and records this decision in both places.
- Depends on the Chunk 0 spike passing. If it fails, v0.2 is model-only.

### D4. Install is per-repo on an allowlist
- Never machine-wide. Never in repos holding personal data, credentials or agent workspaces.
- The allowlist is computed on the owner's Mac with `docs/v02/tools/count_spawns.sh`. The plan uses
  placeholders (`<repo-A>`, …) and names no repo.
- Tiered agent files go in each allowlisted repo's `.claude/agents/`, not `~/.claude/agents/`.

### D5. Jev is called asynchronously; prompts go to the hosted Jev during the window
- A hook cannot use an async answer for the spawn that triggered it, so the instant decision comes
  from the type table and tiered types; Jev advises in shadow.
- **Owner chose** to send prompts to the hosted Jev (Vercel AI Gateway) during the window.
  Research recommendation was record-only (capture locally, decide later).
- **Condition (hard gate):** redaction, the cwd denylist and the per-prompt cap live in code with
  tests (C5). The Jev arm refuses to send a state that has not passed redaction.
- **Owner option kept open:** switch to the local `openjev` MLX runtime (Apple silicon, ~16 GB free
  RAM, `SPEC.md:289`), which keeps prompts on the Mac. Whether it accepts the `/v1/evaluate` body
  unchanged is UNVERIFIED. **Recommendation:** evaluate it first (C-OFF part 1) before any hosted send.

### D6. The 6-hour window is safety-only
Real evidence comes from an offline replay of historical prompts (redacted, exclusions applied) and
the repo's 12-task fixture suite. Pre-registered minimums: 30 per arm for cost, 100 per arm for
rework, 30 paired items for agreement. Below them the verdict is INCONCLUSIVE.

### D7. Work proceeds in waves via subagents; the owner runs Chunk 0
The spike needs fresh interactive sessions started by the owner. Never `claude -p`.

### D8. Run target is the owner's Mac
- macOS first: no `systemd-run`, no `at`, no launchd (the spec rules out auto-start), no GNU-only flags.
- Expiry = `$JEV_HOME/.jev-deadline` (epoch seconds) checked by every hook with `date -u +%s`,
  plus `$JEV_HOME/.jev-disabled` and per-repo `./jev uninstall`.
- Nothing in the repo writes under `~/.claude/` (`docs/REVERSIBILITY.md:22`). The owner may touch
  `~/.claude/jev-disabled` by hand as an extra switch.

## Open items (recommended defaults apply until changed)

| # | Question | Recommended default | Why |
|---|---|---|---|
| O1 | Per-prompt char cap for what is sent to Jev | **4,000 chars**, start kept, `truncated` flag | Limits exposure; the routing signal is mostly in the brief's opening. Master's 60,000 cap stays for local capture |
| O2 | Treat a deny from another PreToolUse hook as expected? | **Yes**: log it as `denied_by_other`, not a router failure | Other hooks may legitimately block; counting them as errors would trip the breaker |
| O3 | Keep `permissionDecision: "allow"` on the type rewrite? | **No for type rewrites**: omit `permissionDecision` so the normal prompt flow applies; keep v0.1 behaviour for model-only rewrites | "allow" skips the permission prompt for a spawn whose type the router changed |
| O4 | Treat an unreadable deadline file as expired? | **Yes** (fail closed = off) | Off is the safe state |
| O5 | Ledger schema bump for original/rewritten type | **v3**, with a reader that accepts v2 | Needed to analyse arms |
| O6 | Arm split during the window | static / tiered / gp-same equal thirds by `tool_use_id` hash; no live constant-sonnet | Constant-sonnet would downgrade real work that currently inherits a larger model |
| O7 | What JEV-62's existing install does during the build | **Disabled** (`<repo>/.jev-disabled`) until go-live, then allowlisted like any other repo or uninstalled | Avoids a second rewriter and a polluted baseline |
| O8 | Denylist contents | directories holding personal data, credentials, agent workspaces, `.env*`, key stores; owner fills the concrete list on the Mac | The repo is public; the list stays local (gitignored config) |
