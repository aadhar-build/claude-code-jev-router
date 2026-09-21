# The baseline costing defect: verified, fixed, and what it moves

Worktree: `.claude/worktrees/jev-critical-path`. No API calls; everything below is
a re-read of transcripts already on disk. **Every dollar figure here is a LOWER
BOUND** — FINDINGS.md Part 1 establishes that transcript-derived cost runs about
27.6% under Claude Code's own first-party total for the same window, and this
correction does not close that gap. It removes a *second*, independent undercount
sitting on top of it.

## 1. The defect reproduces exactly

`src/baseline.py:197` `requests()` had its own request walk that (a) deduped on
`requestId` alone rather than the `(requestId, message.id)` pair, (b) kept the
**first** copy of a duplicated request — the streaming placeholder carrying
`input_tokens: 2` — and (c) never read `usage.iterations[]`, pricing cache writes
at one flat multiplier with no 5m/1h TTL split.

Re-run over the same corpus (`~/.claude/projects/-Users-aadharagarwal-projects-JEV-experiments`,
2,197 deduplicated billable requests):

| rule | delegated | main | total |
|---|---|---|---|
| `baseline.py` (frozen) | **$105.09** | $127.75 | $232.83 |
| `session_metrics.py` | **$171.94** | $140.55 | $312.49 |

Both W0 numbers reproduce to the cent. **Confirmed.**

**One correction to the W0 write-up:** those two figures are *whole-corpus, no
cut*. They are not the frozen record's window. Under the JEV-24a cut
(`2026-09-20T11:11:49Z`) the effect on the frozen record is **larger**, because
the pre-cut window is more delegation-heavy: delegated $11.04 → $20.16, i.e. the
frozen figure understates by **45.2%** (not 38.9%). The 38.9% figure should not
be quoted as if it applied to `delegation-pre-rule-v1.json`.

Supporting facts, measured not assumed:
- 0 of 2,197 request keys have copies on both sides of the cut, so the
  first-copy-timestamp rule does not move the window.
- Max 9 copies of a single key in this corpus.
- The frozen record's delegated figure reproduces *exactly* ($11.039621) under the
  old rule, so the divergence is the rule and nothing else.

## 2. Both numbers, before and after, at the frozen cut

Cut, sessions and code are identical across all three rows; only the per-request
rule (and, in `all_sessions`, `config/pricing.json`) changes.

### `interactive_sessions_only` — the pure rule effect

| | main | delegated | total | rate by spend | $/delegated task |
|---|---|---|---|---|---|
| as frozen (published) | 56.95676 | 11.039621 | 67.996381 | **0.162356** | 1.5771 |
| frozen rule, re-run today | 56.95676 | 11.039621 | 67.996381 | 0.162356 | 1.5771 |
| **corrected** | **64.559806** | **20.158486** | **84.718292** | **0.237947** | **2.8798** |

The middle row is bit-identical to the published one. That is the proof that the
whole movement is the costing rule — not corpus drift, not pricing drift.

### `all_sessions`

| | main | delegated | total | rate by spend |
|---|---|---|---|---|
| as frozen | 56.95676 | 11.039621 | 67.996381 | 0.162356 |
| frozen rule, re-run today | 57.570205 | 11.039621 | 68.609826 | 0.160904 |
| **corrected** | **65.173251** | **20.158486** | **85.331737** | **0.236237** |

`all_sessions` additionally absorbs a **pricing** change: `config/pricing.json`
moved `pricing-2026-09-20` → `pricing-2026-09-20b`, which priced
`claude-opus-4-7`. Six requests in the tool-invoked session `20299ea6` were
counted as *unpriced* at freeze time and now cost $0.6134. That is why
`all_sessions` differs from `interactive_sessions_only` and why the two are kept
apart in the companion.

## 3. The corrected `delegation_rate_by_spend`

**0.237947** (interactive-only, the scope the frozen record's headline came from)
or **0.236237** (all sessions). Frozen value **0.162356**.

Both numerator and denominator were recomputed by the same function over the same
cut, which matters: the denominator moves too. The main session is entirely
1-hour-TTL cache writes, under-priced by the flat multiplier, so main spend rises
$7.60 (+13.3%) — but delegated spend rises $9.12 (+82.6%), so the rate still goes
**up** by 46.6% relative, from 0.162 to 0.238.

## 4. How much of the "before" baseline moves

This is the number that matters, because every future saving is measured against it.

| headline figure | frozen | corrected | movement |
|---|---|---|---|
| total pre-rule spend | $67.9964 | $84.7183 | **+24.6%** (frozen understates by 19.7%) |
| delegated spend | $11.0396 | $20.1585 | **+82.6%** (frozen understates by 45.2%) |
| main-session spend | $56.9568 | $64.5598 | **+13.4%** (understates by 11.8%) |
| `delegation_rate_by_spend` | 0.162356 | 0.237947 | **+46.6% relative** |
| cost per delegated task | $1.5771 | $2.8798 | **+82.6%** |
| delegated tasks / human prompts | 7 / 37 | 7 / 37 | unchanged |
| `delegation_rate_by_task_count` | 0.159091 | 0.159091 | unchanged |

The pivoted goal is *"lower realised cost per delegated task."* Its "before"
anchor was **$1.58 per delegated task**. It is actually **$2.88 (lower bound)**.
Any saving reported against $1.58 would be measured against a starting line 45%
too low — a real 20% reduction would have looked like a 46% *increase*.

Counts are untouched: only costs move, so every task/prompt-denominated figure in
the frozen record survives intact.

## 5. What changed in the code

- **`src/session_metrics.py`** — new `billable_requests(path)`: THE per-request
  unit. One record per deduplicated billable request, already carrying the dedupe
  pair, the `iterations[]` asymmetry, the keep-the-completed-copy merge and the
  TTL-split pricing. Nothing else in the module changed; `analyse()` and
  `cost_decomposition()` are untouched.
- **`src/baseline.py`** —
  - `requests()` is now a thin projection of `sm.billable_requests`. It owns no
    counting rules at all.
  - `legacy_v1_requests()` added and loudly quarantined: it exists only so the
    companion can state what the frozen rule yields *today* and thereby separate
    rule effect from pricing drift. Its three defects are named in its docstring.
  - `per_session_pre_cut()` / `totals_of()` extracted so numerator and denominator
    always come from one pass. `totals_of` now also emits
    `cost_per_delegated_task_usd`.
  - `delegation_baseline(force=True)` now **raises** instead of overwriting.
    The frozen record was one flag away from destruction, and discovering this
    defect is precisely the moment someone reaches for that flag.
  - New `delegation_baseline_corrected()` / `--corrected`, writing the companion.
  - New `$JEV_BASELINE_PROJECT` / `--transcript-dir` override (see §7).
  - `project_dir()` slug bug fixed (see §7).
- **`data/baseline/delegation-pre-rule-v1-corrected.json`** — new companion.
  Frozen file untouched (verified byte-identical). The companion records the rule
  that produced it, the superseded rule, the corpus it read, all three passes, the
  attributed movement, and the lower-bound caveat.
- **`.gitignore` / `src/doctor.py`** — the companion added to the data allowlist
  in both, or `doctor.py`'s git-tracked check would fail once it is committed.
- **`tests/test_baseline.py`** — four new classes (18 tests).

## 6. Tests

`tests/test_baseline.py` — already wired into `tests/run_all.sh`, **no new
`guarded` line needed**.

- `TestTheCompletedCopyIsTheOneThatCounts` — pins first-vs-last on a fabricated
  3-copy transcript (placeholder, placeholder, completed). Asserts the corrected
  cost, and asserts the quarantined rule yields exactly the `input_tokens: 2`
  placeholder cost — the bug preserved as a number so it cannot come back.
- `TestTheTwoModulesMayNotDiverge` — the divergence guard. Asserts
  `sum(baseline.requests(p).cost_usd) == session_metrics.analyse(p).computed_cost_usd`
  minus the web-search line, on a fixture *and* on every fully priced real
  transcript on disk; plus a source-level assertion that `requests()` calls
  `sm.billable_requests` and does not re-implement `dedupe_key`,
  `normalise_usage`, `merge_copies` or `cl.cost_usd`.
- `TestTheFrozenRecordIsImmutable` — `--force` is refused and the file is unchanged.
- `TestCorrectedCompanion` — the companion names its rule, preserves the frozen
  record, uses the same cut, recomputes both sides, is labelled a lower bound, and
  records the corpus it read.

`python3 tests/test_baseline.py` → **34 passed, 0 skipped**.

**Red proven.** Monkeypatching `baseline.requests = baseline.legacy_v1_requests`
(i.e. restoring the defect) and re-running the new assertions:
`test_the_cost_is_the_completed_copy_not_the_placeholder` fails with
`1e-05 != 0.68299` — the placeholder's two tokens against the completed turn —
and the fixture divergence assertion fails by the same $0.68. The real-corpus
divergence assertion still passes under the old rule, because the five sessions
in this worktree's own slug happen to carry no multi-copy growing keys; that is
why the fabricated fixture, not the live corpus, is the binding test.

The real-corpus assertion copies each session's files (main transcript plus
`subagents/`) to a temp dir before reading, so both passes see the same bytes.
The corpus is live and `run_all.sh` runs while sessions are being written, so
without that the test could go red for an appended request rather than a
divergence.

## 7. A second bug found on the way (fixed)

`project_dir()` built Claude Code's transcript-directory slug with
`str(root).replace("/", "-")`. Claude Code replaces **every** non-alphanumeric
character. For a path containing a dot — e.g. any git worktree under
`.claude/worktrees/` — the slug was wrong, the directory did not exist, and
`transcripts()` returned `[]`. That does not error: it produces **a baseline of
zeros that looks like a finished answer**. Running `baseline.py --delegation` from
this worktree would have silently written an all-zero record.

Fixed two ways: the slug now uses `re.sub(r"[^a-zA-Z0-9]", "-", ...)` (with the
naive form kept as a fallback so no existing directory is orphaned), and
`$JEV_BASELINE_PROJECT` / `--transcript-dir` lets a worktree name the project root
it should read. One knob drives **both** the transcript directory and the
`history.jsonl` prompt-index filter, so the two can never disagree; the resolved
value is recorded in the companion.

The companion was generated with:

```
JEV_BASELINE_PROJECT=/Users/aadharagarwal/projects/JEV-experiments \
  python3 src/baseline.py --corrected
```

## 8. Not fixed — reported instead

1. **`data/baseline/sessions.jsonl` and `manifest.json` are stale.** Both were
   computed under the defective rule (`delegated_cost_usd` per row,
   `total_delegated_cost_usd` in the manifest). They are *fingerprint*-idempotent,
   so a re-snapshot appends nothing for an unchanged session — the wrong numbers
   will not self-correct. Suggest a `costing_rule` field on the row schema plus a
   one-off forced re-snapshot, as its own ticket. Not done here: it is a schema
   change to a committed append-only stream and outside this defect's scope.
2. **The corpus grew 15 → 44 sessions** since the freeze. Only 2 carry any pre-cut
   spend, so the comparison is apples-to-apples; this is recorded in the
   companion's `corpus` block rather than assumed.
3. **Stale prose I did not touch** (`ISSUES.md` / `SPEC.md` / `README.md` /
   `PREREGISTRATION.md` are the orchestrator's): anything quoting
   `delegation_rate_by_spend: 0.162` or pre-rule spend of `$68` as the "before"
   anchor now needs the corrected figures and a pointer to the companion. A2.6's
   registered anchor in particular.

## 9. Suite status

`bash tests/run_all.sh` was **green before my changes** (`rc=0`, logged at
`.scratch/pivot/runall-before.txt`).

After my changes it exits 1 on `tests/reversibility.sh` — **not from this work**:

```
FAIL  hooks/agent_route_actuator.sh: references .jev-disabled outside the canonical block
FAIL  2 different switch blocks across 3 hook scripts -- they have drifted
```

`hooks/agent_route_actuator.sh`, `src/paths.py` and `tests/test_agent_actuator.*`
are modified in this shared worktree by another agent this wave and are on the
do-not-touch list. Evidence, not assertion:

- `hooks/agent_route_actuator.sh` mtime `1789971315`; my green `run_all.sh` log
  mtime `1789971112`. The hook was modified **203 seconds after** the suite was
  last green here.
- The other agent's uncommitted diff to that hook touches `.jev-disabled` in
  four places — the exact construct the failure names.
- My diff touches no file under `hooks/`.

**Stated plainly: the suite is NOT green, and I cannot make it green without
editing a file the brief forbids me to touch.** The acceptance criterion
`bash tests/run_all.sh` fully green is therefore blocked, and the block is owned
by the agent holding `hooks/`. Everything else in the suite passes, including
`test_baseline.py` (34/34), `test_session_metrics.py` and `doctor.py`.
