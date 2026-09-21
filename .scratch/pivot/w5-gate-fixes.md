# W5 — five defects in the W3 accuracy gate

**Theme, and it is the same one five times: a guard that is a property of one
implementation's good behaviour is not a guard.**

Every defect below had a check that *looked* like a guarantee. In each case the
guarantee was being supplied by something other than the check — by
`RecordedJudge` happening not to read a keyword argument it was handed, by a
token list that guarded names not in play, by a docstring that promised a
mirror the code never implemented. The fix in each case is to move the
guarantee into a place where violating it takes work.

Each defect was reproduced before it was fixed. Reproductions are quoted.

---

## 1. The blind was enforced on the payload and broken at the interface

`judge_payload()` was genuinely clean — an audit over all 72 shipped fixture
payloads found 0 leaks, and I re-confirmed that. The leak was one level up.

**Reproduced.** A spy judge over a full run:

```
{'task_id': 'add-retry-backoff', 'arm': 'baseline', 'seed': 0}
arm values seen by judge: ['baseline', 'treatment']
```

The arm label was a **required keyword argument** of `Judge.score`. A clean
payload handed over beside `arm="treatment"` is not a blind. `judge_payload`'s
docstring said the arm was "never in scope"; at the interface that was false,
and a `LiveJudge` would have received it.

**Fixed.** `arm`, `task_id` and `seed` are gone from the protocol. The judge is
addressed by an **opaque reference**: `sha256(salt ‖ task ‖ arm ‖ seed)`
truncated to 32 hex, minted per run by `RefMint`.

- The salt is 16 fresh random bytes per run. It is **never recorded on the
  report and never rendered**.
- It is deliberately **not** derived from `order_seed`. `order_seed` *is*
  recorded so runs reproduce; deriving the salt from it would publish the
  decoder beside the ciphertext.
- `RecordedJudge.bind(mint)` builds an index by scanning the fixture tree it
  already owns — `recorded/judge/<arm>/<task>/<seed>.json`. **The fixtures did
  not move.**
- `run_class2` hands the mint over only after `isinstance(judge, RecordedJudge)`.
  Duck-typing on a `bind` attribute was rejected: a `LiveJudge` that later grew
  one would have silently received the decoder.
- `LiveJudge` has no `bind`, and that absence *is* the blind.
- An unknown ref raises `HarnessFailure` quoting only the hex and the index
  size. An error message is not a side channel.

Regression tests assert the *signature* (`inspect.signature(fx.Judge.score)` is
exactly `payload, ref`), so re-adding `arm` fails the suite; and assert that
over a full 72-unit run the judge receives neither arm name nor either tier
name in any argument.

## 2. Task order was not blinded either

**Reproduced.** A spy executor over a full run:

```
arm sequence: BBBTTTBBBTTTBBBTTTBBBTTTBBBTTTBBBTTT...  (12 x BBBTTT)
```

`run_class2` walked tasks in manifest order and ran `baseline_arm` to
completion before `treatment_arm`. A stateful or sequence-aware judge does not
need to read a token to know the arm — it needs to count to three. **JEV-29's
"randomise task order" box was unticked and it was unticked truthfully.**

**Fixed.** The 72 `(task, arm, seed)` units are shuffled once; task order and
arm interleaving are the same permutation, not two knobs. `order_seed` is
recorded and rendered (`reproduce with --order-seed N`), and `--order-seed` is
wired through the CLI.

`run_class2` is now three phases, and the split is load-bearing:

1. **Execute** every unit in shuffled order.
2. **Judge** every unit in *the same* shuffled order. This has to be a separate
   pass because the blind token set is derived from the tiers the run actually
   produced (see §3), which is not known until every execution is in hand.
3. **Aggregate** in suite order, so the *report* stays deterministic and
   diffable. Randomising what the judge sees is the point; randomising the
   output would only make the gate harder to read.

Phase 2 driving the *same* order matters: randomising only the executor would
fix nothing, because the executor legitimately knows the arm. It is the judge's
call sequence that has to be unpredictable.

**That trap is real and I nearly shipped an unguarded version of it.** My first
regression test for this asserted only that 72 refs were unique and that
`execution_order` matched the executor — both true even if phase 2 iterated in
suite order, i.e. the test would have passed the exact bug. It now compares the
judge's *actual payload sequence* to the executor's, and asserts it is not
suite order. **Mutation-checked**: forcing phase 2 back to suite order fails
exactly these two tests and no others.

## 3. `blind_tokens` had a false positive and a false negative

**Reproduced.**

```
FP  '+ self.controller = Controller()'   -> ['control']
FP  '+# an opusculum of haikus'          -> ['haiku', 'opus']
FN  '+# cheap tier was used'             -> []
FN  '+# frontier tier'                   -> []
```

- **False positive, two sources.** Substring matching flagged `controller` for
  containing `control`; and `tier_tokens()` enumerated *every* tier in
  `config/tiers.json` whether or not the run used it, so prose naming a model
  the run never touched tripped the blind and forced exit 1. It erred safe, but
  a guard that fires on ordinary code gets switched off, and on real mined
  tasks it would have produced COULD-NOT-RUNs unrelated to the blind.
- **False negative, and the sharp one.** The tiers the fixtures *actually
  record* are `cheap` and `frontier`. Neither is in `config/tiers.json`, so
  neither was ever a token. **The check was guarding names that were not in
  play and ignoring the two that were.**

**Fixed.**

- Word-boundary matching via `_token_pattern`, with the boundary applied only
  to the word-character *ends* of each token — so `arm=` still matches
  `arm=treatment` (not `warm=`), and `claude-haiku-4-5` still matches the dated
  `claude-haiku-4-5-20251001`.
- `tier_tokens(tiers)` now takes the tiers **in use**, collected from the
  executions the run produced. Config is consulted only to expand an in-use
  tier into its alias and resolved model prefix. A configured-but-unused tier
  costs nothing; a used-but-unconfigured tier is still covered by its own name.
- Dropped the hardcoded literals `"baseline"`, `"treatment"` (they arrive as
  the arm *parameters*) and `"control"` (never an arm name this harness uses —
  pure false positive).

I verified the stronger token set leaves all 72 shipped payloads clean before
changing it. `report.tiers_in_use` is rendered.

## 4. `subagent_outcomes.py` silently dropped transcripts and reported 0% attrition

**Reproduced**, on
`~/.claude/projects/<proj>/4ba49645-fb8d-4fb2-b496-c274f6ed1490.jsonl`:

| | before | after |
|---|---|---|
| transcripts on disk | 33 | 33 |
| rows printed | 30 | 30 assignments **+ 3 named orphans** |
| cost reported | $168.0171 | **$171.9447** ( = $168.0171 + $3.9277 ) |
| unattributed | *silently dropped* | **$3.9277 = 2.28%**, itemised |
| attrition printed | 0.00% | 0.00% **of 30 assignments**, stated |

The docstring promised "a ledger row with no matching transcript is ATTRITION,
not a zero" — one of the two ways a join can fail, and the only one
implemented. A transcript with no ledger row was read and joined against
nothing. The table then printed an attrition rate of **0.00%**: it asserted
nothing was missing, in the very table from which $3.93 was missing.

**Root cause confirmed, and it is irreducible.** All three orphans are
`spawnDepth: 2` — spawned by another *agent*, so their `tool_use` block is in
that agent's transcript, not the parent session's. `blocking_intervals` reads
only the parent, so the stand-in ledger **cannot** be made complete. The honest
move is not to fix the stand-in but to name what it fails to cover.

**Fixed.**

- `join_outcomes` returns `SessionOutcomes{rows, unassigned}` rather than a
  bare list — so the orphan side cannot be ignored by a caller that simply
  never asks for it. Rendered **even when empty** ("none — every transcript on
  disk is attributed"), because silence is the defect: a reader must be able to
  tell *none* from *not checked*.
- Orphans are itemised with agent id, type, `spawnDepth`, cost, and a
  *reason* ("nested spawn: its tool_use block is in agent X's transcript").
- A total-spend line splits attributed from unattributed.
- **Denominators made explicit** wherever medians render. `render_outcomes`
  previously printed no medians at all; it now prints both with their own `n`
  (task duration n=33 over every transcript incl. orphans, blocking duration
  n=30 over assignments) plus an explicit *"these are over DIFFERENT sets …
  they are not a ratio"*. `Class2Report.durations` gained `n_task` /
  `n_blocking` and `render_class2` prints both.

**A task that never completed** — `transcript_completion` reads the last
*assistant* message's `stop_reason` (terminal = `end_turn`, `stop_sequence`).
Surfaced as a **third state** — `completed` is separate from `outcome_found`,
because an outcome that exists but did not finish is neither attrition nor
success.

> **I made a defect-5-class error here and caught it in review.** I first
> justified "last assistant line, not last line of file" by claiming the
> corpus contained a transcript with an `attachment` after a clean final
> assistant turn. It does not. Re-measured: the one attachment-tailed file
> **is** the one genuinely truncated file, so the corpus does not discriminate
> between the two rules at all. The design choice stands, but on a *principle*
> — a transcript may legitimately carry trailing `attachment` / `tool_result` /
> system lines after a clean turn, and last-line-only would misread all of
> them — and the test for it is explicitly labelled synthetic. Real
> distribution across the 33: **31 `end_turn`, 1 `stop_sequence`, 1
> `tool_use`**. (My earlier "32/1/0" was a last-*line* scan, not a
> last-*assistant* scan.)

> **This one is not hypothetical.** The brief listed it as "not observed in the
> corpus". It is observed. `toolu_0183gLww96YQXN4AP56CoVUc` ("JEV-34:
> agent_route surface in shadow", 139 lines) ends on an assistant `tool_use`
> whose result came back at 18:47:53 and was never answered. The old code
> reported it as a finished outcome with a full cost of **$2.9927**.

**A retried task** — `{o.tool_use_id: o for o in outcomes}` kept the last file
and discarded the earlier attempt's cost. Outcomes are now grouped into lists
per id; cost and duration are **summed** across attempts, `attempts` travels on
the row and renders as `RETRIED xN (cost summed)`. A retry stays **one
assignment**, so the ITT denominator does not inflate. (No retry exists in the
current corpus — I verified zero duplicate `toolUseId`s — so this is guarded,
not observed.)

## 5. A claim in the source comment mixed two taus

`src/accuracy_gate.py:~393` said *"`destructive` fires on roughly 5% of units,
`needs_review` on roughly half"* — two figures taken at two different taus.

**I re-measured rather than trusting the brief**, and the first pass
*disagreed* (6.2% / 5.3% / 26.3%). The brief's numbers reproduce exactly only
on `arm=jev`, ok rows, deduplicated to units, n=567:

```
destructive   @ tau=0.36  ->  5.6%
needs_review  @ tau=0.95  ->  4.6%
needs_review  @ tau=0.5   -> 52.9%
```

So "roughly half" is `needs_review` at **τ=0.5**, not at the **τ=0.95** the
gate uses. At the taus actually in play the two questions fire at nearly the
**same** rate. The comment now states each tau beside its figure *and* the
denominator it was measured over, and notes that the asymmetry in the worked
example is carried by the example, not by a difference in base rates.

**Not fixed, not mine:** the same wrong sentence appears in
`.scratch/pivot/w3-accuracy-gate.md` and in W3's commit message (`df79e67`).
The commit message cannot be corrected without a rewrite; the scratch file is
someone else's to edit.

---

## Files changed

| file | what |
|---|---|
| `src/fixture_executor.py` | `RefMint`; `Judge.score(payload, *, ref)`; `RecordedJudge.bind` + scanned index; word-boundary `blind_check`; `tier_tokens(tiers)`; three-phase `run_class2` with `order_seed`; `execution_order`, `tiers_in_use`, `n_task`/`n_blocking` on the report; renderer |
| `src/accuracy_gate.py` | `--order-seed` wired through `cmd_class2`; the two-taus comment corrected; module docstring |
| `src/subagent_outcomes.py` | `SessionOutcomes`; orphans as a named category; `transcript_completion`; retry grouping; explicit denominators in `render_outcomes`; CLI |
| `tests/test_accuracy_gate.py` | 79 → 114 tests |

`tests/fixtures/accuracy/` unchanged — **the fixtures did not move.**

**The orchestrator should stage only these five paths.** This worktree is
shared and currently carries other agents' uncommitted edits to `hooks/*.sh`,
`src/baseline.py`, `src/assignment_ledger.py`, `src/session_metrics.py`,
`src/tier_map.py`, `tests/reversibility.sh`, `tests/run_all.sh`,
`data/baseline/*`, `docs/REVERSIBILITY.md` and others. None of those are mine.

## Verification

- `tests/test_accuracy_gate.py`: **114 passed, 0 failed** (was 79).
- Every other test in `run_all.sh` passes individually, including all of
  `test_hook.sh` (27/27), `test_agent_actuator.{py,sh}`, `test_pipeline.py`,
  `reversibility.sh`, `test_clean_checkout.sh`, `doctor.py`.
- Defects 1, 2 and 3 each have a regression test that fails against the old
  behaviour; defect 2's was **mutation-checked** by reintroducing the bug.
- Defect 4 verified against the real 33-transcript session, not only fixtures.
- No API calls. Nothing armed. No git write commands. No fixture moved.

## `run_all.sh` is currently red, and not because of this work

**`bash tests/run_all.sh` aborts at `test_assignment_ledger.py` (JEV-57).**
This is another agent's in-flight work, landing in this shared worktree while
I was running:

```
FAIL: test_the_deployed_schema_constant_tracks_the_hook_not_the_reader
AssertionError: 'agent-route-assignment-v2' != 'agent-route-assignment-v1'
```

`src/assignment_ledger.py` now declares schema **v2** while that file's own new
test asserts **v1**. Both `src/assignment_ledger.py` and
`tests/test_assignment_ledger.py` are outside my ownership — the former is on
my explicit do-not-edit list, the latter did not exist when I started and was
added to `run_all.sh` (also do-not-edit) mid-session. I have not touched either
and have not worked around it.

**No `guarded` line needs changing on my account.** The `test_accuracy_gate.py`
line already covers everything I changed, and it passes. Whoever owns JEV-57
needs to reconcile that constant before the suite goes green end-to-end.

**Also worth knowing:** the *first* `run_all.sh` of this session failed in
`tests/test_hook.sh` (7 failures on the capture path). It has passed on every
run since, including standalone runs (27/27). `hooks/capture.sh` carries
another agent's uncommitted edits, which is the likely cause. This suite can go
red transiently while the wave is in flight; a single red run is worth
re-running before it is believed.
