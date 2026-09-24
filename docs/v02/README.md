# JEV v0.2: Mac quick start

Plan: [PLAN.md](PLAN.md). Decisions: [DECISIONS.md](DECISIONS.md). Nothing here arms anything.

## Prerequisites
- macOS, Apple silicon. Python 3.12+ (`python3 --version`; Apple's `/usr/bin/python3` is too old,
  install a newer one and set `JEV_PYTHON` if needed). `jq`. Bash 3.2 is fine.
- Only if trying local Jev: ~16 GB free RAM for `openjev` (MLX).
- A key only if you send to the hosted Jev: put it in `.env` at the JEV repo root:
  ```
  cp .env.example .env && chmod 600 .env    # then set AI_GATEWAY_API_KEY in it
  git check-ignore -v .env                   # must print a match; NEVER commit .env
  ```
  No `ANTHROPIC_API_KEY` is needed or wanted.

## Order of operations (owner)
1. `git checkout master && ./jev status`. Check the JEV-62 project for `.claude/jev-install.json`; if armed and no `.jev-disabled`, `touch <that-repo>/.jev-disabled`.
2. `tests/run_all.sh` (run `python3 src/make_synthetic.py` first). Save results in `docs/v02/findings/`.
3. Chunk 0: follow `docs/v02/spike-c0/RUNBOOK.md` in fresh interactive `claude` sessions. Never `claude -p`.
4. Hand waves 2-6 to subagents (below). Review and merge each wave before starting the next.
5. After C6: run the 60-second deadline drill (PLAN §5).
6. After C-OFF part 1: decide hosted vs local Jev.
7. `docs/v02/tools/count_spawns.sh` → allowlist. Go-live and teardown per PLAN §5.

## Handing a wave to Claude Code
Start `claude` in the JEV repo on a branch, then paste:

**Wave 2 (C1 and C2 in parallel)**
```
Read docs/v02/PLAN.md and docs/v02/DECISIONS.md. Launch two subagents in one message:
one for chunk C1, one for chunk C2, exactly as specified in PLAN §3. Each: write the failing
test first and show it red, implement, show it green, run tests/reversibility.sh, do a mutation
check, stay within 10 minutes of tool calls, edit only the files listed for its chunk.
Do not install, push, write under ~/.claude, or call any network service. Report the diff and
test output; do not claim done without showing green output.
```

**Later waves:** same prompt, replace the chunk names with the wave's row in PLAN §4
(W3: C3 and C4 in parallel; W4: C5 alone; W5: C6 alone; W6: C7 and C-OFF part 1).

## Emergency off
`touch $JEV_HOME/.jev-disabled` stops every hook in every repo on the next call.
Per repo: `./jev uninstall <repo> --yes`.
