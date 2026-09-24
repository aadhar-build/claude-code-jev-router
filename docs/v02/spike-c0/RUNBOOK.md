# Spike C0 runbook: does a PreToolUse `updatedInput` rewrite of `subagent_type` really spawn the custom agent?

Run this yourself in a fresh terminal. Do NOT use `claude -p`; use an interactive session. Needs bash + jq; works on Linux and macOS.

**Scope: this directory arms NOTHING machine-wide.** Everything is project-scoped (`.claude/` in this directory only). It never touches `~/.claude/settings.json` or `~/.claude/agents/`. The hook only fires for sessions started inside this directory.

## Files (everything that exists; nothing else is created except `probe/probe.log` and, during step 8, `.probe-off`)
```
spike-c0/.claude/agents/gp-lite.md     model: haiku, effort: low, no tools line
spike-c0/.claude/agents/gp-same.md     control: model: inherit, no effort
spike-c0/.claude/settings.json         one PreToolUse hook, matcher "Agent"
spike-c0/probe/rewrite_probe.sh        the hook (always exits 0)
spike-c0/probe/probe.log               created on first hook run
spike-c0/check.sh  selftest.sh  RUNBOOK.md
~/.claude/projects/<encoded spike path>/   Claude Code's own transcripts (created by your sessions)
```
Doc facts (fetched from code.claude.com/docs/en/sub-agents.md): frontmatter has an `effort` field: "Options: `low`, `medium`, `high`, `xhigh`, `max`; available levels depend on the model", default inherits from session. An agent file's body "becomes the system prompt" and replaces the Claude Code system prompt, so gp-lite is NOT a clone of general-purpose's prompt (harmless here; matters for the real build).

## Steps
Prereq. On macOS, confirm bash and jq are installed (`brew install jq` if missing).
0. (optional, no Claude) `./selftest.sh` should end `passed=7 failed=0`.
1. Optional: copy the dir anywhere (`cp -R spike-c0 ~/spike-c0`). Ensure no `.probe-off` file and `probe/probe.log` is absent/empty.
2. `cd` into the directory, then start `claude` (interactive). Accept the workspace-trust prompt (project hooks need trust).
3. Run `/status`. Record the "Setting sources" line. Expected: User settings, Project settings (this dir's `.claude/settings.json`), and maybe Local/managed if present. Note: your `~/.claude/settings.json` (user scope) is loaded too, so its hooks/env are active in the spike. Non-git dir: the project root is the cwd. Also run `/hooks` (Agent matcher should list the probe) and `/agents` (gp-lite and gp-same should be listed as project agents).
4. Give this one prompt:
   `Use the Agent tool exactly once with subagent_type "general-purpose" and prompt "Reply with the single word: ok". Then stop.`
5. `/exit`.
6. `./check.sh gp-lite claude-haiku-4-5` -> expect `PASS`. It prints the newest subagent's `agentType`, first-assistant-model and `effort` (the effort recorded on each transcript line), plus the last probe.log lines. `probe.log` should show `decision=rewrote orig=general-purpose new=gp-lite`.
7. Read effort: on the same output, `effort=low` means the frontmatter effort took effect; `effort=<your session level>` (e.g. high) means it was ignored.
8. NEGATIVE CONTROL: `touch .probe-off`, start a fresh `claude` in the dir, same prompt from step 4, `/exit`, then `./check.sh general-purpose`. It prints the resolved model on the `newest:` line (e.g. `model=claude-sonnet-5 effort=high`); that is the default general-purpose resolves to. Expect type `general-purpose`, model NOT haiku, and a probe.log line `decision=off`.
9. SECOND CONTROL (specialised type untouched): `rm .probe-off`, fresh `claude`, prompt:
   `Use the Agent tool exactly once with subagent_type "Explore" and prompt "Reply with the single word: ok". Then stop.`
   `/exit`, `./check.sh Explore`. Expect `agentType=Explore` and a probe.log line `decision=skipped-type orig=Explore`.

If in step 6 the type is `fork`, or probe.log has no new line, the spike is invalid (parent chose another route or the hook did not run; check `/hooks` and trust) - report it, do not read it as a FAIL of the rewrite.

## Decision table
| Observation | Meaning for the plan |
|---|---|
| Step 6 PASS (`gp-lite`, `claude-haiku-4-5*`) and `effort=low` | Type rewrite works AND effort actuates. Tiered gp-lite/std/hard types are viable (model and effort). |
| Type `gp-lite`, model haiku, but effort = session level | Rewrite works, `effort:` frontmatter ignored or not recorded. Tiered types viable for MODEL only; effort stays unactuatable. |
| Type `gp-lite` but model not haiku | Rewrite spawns the type but its `model:` is overridden (e.g. by settings/env model override). Investigate `/status` and env before deciding; treat model routing via types as unproven. |
| Type stays `general-purpose`, probe.log says `rewrote` | Rewrite ignored (A1 false). Drop tiered types; v0.2 routes by `model` only. |
| Type stays `general-purpose`, probe.log has no line | Hook did not run (trust, matcher, or path). Fix and re-run; inconclusive. |
| Negative control not general-purpose, or Explore rewritten | Something else rewrites (plugin hook / logic bug). Inconclusive; inspect `/hooks`. |

## Cleanup
1. `rm -f .probe-off probe/probe.log`
2. Delete the spike directory (`rm -rf spike-c0`, or your copy).
3. Optional: delete the transcripts Claude Code made: `rm -rf ~/.claude/projects/<encoded spike path>` (the encoded path is what `./check.sh` prints as `project dir`).
Nothing was installed in any repo, and nothing was written to `~/.claude/settings.json` or `~/.claude/agents/`.
