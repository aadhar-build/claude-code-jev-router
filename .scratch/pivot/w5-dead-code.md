# W5 dead-code cleanup — making SPEC §9's claim true

**Agent:** critical-path / dead-code. **Date:** 2026-09-21.
**Suite state on finish:** `bash tests/run_all.sh` → **exit 0, fully green.**

SPEC §9 promised *"roughly 1,500 lines of Python and the top third of `ISSUES.md`
go: the agreement statistics, `PREREGISTRATION.md` as a live document,
`tests/test_board.py`, the `cc_*` arms as arms…"*. None of it had happened.

Three of the named items turned out to be **wrong to execute**. They are kept,
with reasons, in §4 below. The claim is now true for the parts that were right,
and §4 lists the exact corrections the doc agent must apply to make it true for
the rest. **I did not edit `SPEC.md`.**

---

## 0. TWO THINGS THE ORCHESTRATOR MUST CONFIRM — READ FIRST

**(a) I deleted a file outside my ownership list: `tests/test_analyze_config_join.py`.**
The brief's rule "deleting a module means deleting its tests" forced it —
that file imports `analyze` at module scope and *every* class in it exercises
`analyze.py` and nothing else. Leaving it would have made the suite red on
import; removing only its `run_all.sh` line would have been a test silently
lost, which the brief forbids. It was not on my owned list. Flagging rather
than assuming.

**(b) JEV-32's principle now has no enforcing test, and JEV-32 is REPURPOSE, not KILL.**
Those 7 tests were the only enforcement of *"never compare two policy versions
as if they were one."* The **ticket survives the pivot**; only its 2026-era
implementation died. This needs re-pinning on live code.
**Suggested home: JEV-57's assignment ledger**, which already refuses to pool
across repos — a direct sibling of the same rule. This is a real coverage loss,
not bookkeeping.

---

## 1. Deleted — each with the search that justifies it

### `src/latency_report.py` — 451 lines. DELETED.

Zero-importer claim **verified independently**:

```
$ grep -rn "latency_report" . --exclude-dir=__pycache__ --exclude-dir=.git \
      | grep -v "^./src/latency_report.py"
ISSUES.md:2393              <- descriptive table row
.scratch/a3-prep/jev43.md:7 <- scratch note
reports/jev43-wallclock.md:3 <- provenance line in the frozen output
```

Plus three self-references inside the file itself (lines 14, 15, 355). **No
importer, no test, no `run_all.sh` line, no CLI caller** (checked `jev`,
`run-collection.sh`, `teardown.sh` — no hits). JEV-43 is closed.

**The reports survive**, as required — `reports/jev43-wallclock.md` and
`.json` are both still on disk and untouched.

### `src/analyze.py` — 497 lines. DELETED.

Non-test callers: **none.** Only importers were the two test files below.
It serves JEV-05 (KILL — *"Agreement statistics for a publication that is
cancelled"*) and JEV-12 (KILL — *"Publication artifact"*). Not reachable from
`jev`, `run-collection.sh` or any other module. `src/figures.py`, its sibling
in the same path, does not exist any more.

### `tests/test_analyze_config_join.py` — 190 lines, 7 tests. DELETED.

Forced by the above — see §0(a)/(b). `run_all.sh` line removed, with a comment
at that spot recording what went and why, so the removal is legible in the file
that used to run it.

### The agreement half of `src/stats.py` — 93 lines. DELETED.

Removed: `raw_agreement`, `cohens_kappa`, `pabak`, `majority_baseline`,
`confusion`, `categorical_agreement`, `categorical_kappa`,
`quadratic_weighted_kappa`. Per-function caller map, computed before deleting:

| function | non-test callers |
|---|---|
| `raw_agreement`, `pabak`, `majority_baseline`, `quadratic_weighted_kappa` | `analyze.py` only |
| `categorical_agreement`, `categorical_kappa` | `analyze.py` only — **no test at all** |
| `cohens_kappa` | `analyze.py` only (see false positive below) |
| `confusion` | `analyze.py` only (see false positive below) |

**Two grep hits checked and confirmed false positives** — both were in files I
do not own, so I verified rather than assumed:

- `confusion` in `tests/test_agent_route.py:105` and
  `tests/test_python_floor.py:232` is **the English word** ("the exact
  confusion `spawn_depth` was supposed to resolve"), not `stats.confusion`.
- `cohens_kappa` in `tests/test_accuracy_gate.py` is
  `gate.cohens_kappa_bool` — `accuracy_gate.py`'s own re-implementation, exactly
  as its note at `accuracy_gate.py:179` says.
  `grep -n "stats\.confusion\|stats\.cohens_kappa" <those three files>` returns
  **nothing**.

**Chance-corrected agreement did not leave the codebase.**
`accuracy_gate.cohens_kappa_bool` is live on the product path and tested. This
removal does not leave kappa untested — it removes the *retired* copy.

`Counter` became an unused import and was dropped. `math` and `defaultdict` are
still used and stayed.

---

## 2. Test accounting — before/after, nothing silently lost

| file | before | after | delta |
|---|---|---|---|
| `tests/test_pipeline.py` | 104 | **92** | −12 |
| `tests/test_analyze_config_join.py` | 7 | **0 (file deleted)** | −7 |
| `tests/test_validation.py` | 33 | **33** | 0 (touched? no — see §3) |
| `tests/test_board.py` | 8 | **8** | 0 (**kept** — §4) |
| **total** | | | **−19** |

The 12 removed from `test_pipeline.py`, named individually in comments left at
both removal sites:

- **`TestReport` (5)** — `report_runs_end_to_end`, `report_never_says_accuracy`,
  `report_prints_the_base_rate_beside_agreement`,
  `state_identity_violation_is_reported_loudly`,
  `report_survives_an_empty_dataset`.
- **`TestStatistics` (7)** — `perfect_and_chance_agreement`,
  `total_disagreement_is_negative_kappa`, `pabak_is_two_po_minus_one`,
  `skewed_base_rate_splits_kappa_from_raw_agreement`,
  `both_raters_constant_makes_kappa_undefined_not_perfect`,
  `confusion_counts_sum_to_n`, `quadratic_weighted_kappa_penalises_distance`.

### Two things I protected rather than let fall out

**(a) A live-code test nearly died as collateral.**
`test_clustered_intervals_are_wider_than_naive_ones` used `stats.pabak` as its
bootstrap statistic. `pabak` was being deleted — but the test covers
**`clustered_bootstrap`, which is live** (JEV-17 via `validate_threshold.py`).
Deleting the test because it broke would have dropped coverage of live code.
**Rewritten** to compute raw agreement inline. `pabak` is `2·po − 1`, an affine
transform of what it now computes, so both assertions mean exactly what they
meant before: point estimates still coincide, and the width comparison is
unaffected because an affine map scales both intervals equally. Same test, same
count, same assertions.

**(b) `analyze.py` held a state-identity check whose only test was `TestReport`.**
`Joined._check_state_identity` ("every arm for a decision must have seen the
same bytes"). The **write-side** half of that invariant is still covered by
`TestWorkerOrchestration.test_all_arms_see_byte_identical_state` and
`test_state_hash_matches_the_stored_blob`, which assert it where it is actually
enforced. What is gone is the read-side detector — and with no report reading
the rows, there is nothing left to detect into. Recorded in the file.

---

## 3. One suite failure, its cause, and why I fixed it in my own file

Mid-task, `test_pipeline.py` went red on
`test_capture_sh_backpressure_literals_match_the_configured_cap` — a test about
**`hooks/capture.sh`, which I do not own.** I re-ran and investigated rather
than working around it.

Cause: another agent's in-flight **JEV-60 drop-record refactor** of
`hooks/capture.sh`. `git show HEAD:hooks/capture.sh` has both literals bare
(`[ "$#" -gt 500 ]`, `"cap":500`). The rewrite moved the second into a shell
fragment passed to a new `drop` helper, where it reads `\"cap\":500`. The test's
regex `"cap":(\d+)` cannot see through the backslashes.

**`hooks/capture.sh` is functionally correct** — both numbers are still 500 and
the emitted JSON is still `"cap":500`. The other agent even left a comment
saying this test asserts the two numbers; they just did not re-run it.

**⚠️ I initially widened the regex to `\\?"cap\\?":(\d+)` to accept both forms,
and then REVERTED that. Recording both the error and the correction.**

My stated reason for widening was that the strict regex "silently stopped
checking the `cap` field." **That was wrong, and my own failure output
disproves it:** the test failed loudly with
`AssertionError: 1 != 2 : capture.sh no longer has both literals`. The
`assertEqual(len(literals), 2)` guard is precisely what makes strictness safe —
an unreadable literal *cannot* quietly drop out of the comparison, it fails
first. The guard worked exactly as designed. I misread a loud failure as a
silent one and nearly weakened a working assertion because of it.

**Final state: the original strict regex is restored, unchanged.** The observer
agent has since reverted `hooks/capture.sh` to single-quoted form
(`,"cap":500` at line 266), so the bare literal is greppable again and the test
passes on its own terms rather than because I loosened it.

Widening was reconsidered and **rejected on the merits**: `capture.sh` is a
fork-free bash 3.2 hot path that cannot read JSON at runtime, so this text grep
is *the only thing* binding that literal to `config/surfaces.json`. Tolerating a
form the grep cannot see buys a green suite by giving up the property the
assertion exists for. A comment at the assertion now says so, so the next person
to hit this red does not repeat my mistake.

**Sanity check run (coordinator's request) — the restored assertion bites:**

| capture.sh form | literals found | verdict |
|---|---|---|
| current (single-quoted, `,"cap":500`) | `['500','500']` vs cap 500 | **passes** ✓ |
| escaped (`\"cap\":500`) | `['500']`, len 1 ≠ 2 | **fails loudly** ✓ |
| genuine divergence (`"cap":400`) | `['500','400']` ≠ `['500','500']` | **fails loudly** ✓ |

**Net: I made no lasting change to this assertion.** It is byte-identical to
HEAD apart from an added explanatory comment.

**The general lesson, which is the theme of this task:** the question when
deleting or editing a test is not only *"does this belong to a killed ticket"*
but *"is this test the only thing holding a live invariant in place."* A text
assertion about a shell literal looks incidental and is not — it is load-bearing
precisely because the hook it guards cannot check itself.

`tests/test_validation.py` needed **no change** — it uses only
`vt.stats.quantiles`, which survives. I own it but did not touch it.

### `tar: Error exit delayed from previous errors` in `test_clean_checkout.sh` — benign, self-resolving

Appears in the post-change suite run. **Caused by my deletions, and harmless.**
`tests/test_clean_checkout.sh:47–52` builds its file list with `git ls-files`
and pipes it through `tar`. `src/analyze.py`, `src/latency_report.py` and
`tests/test_analyze_config_join.py` are still **tracked in HEAD** but absent
from the working tree, so tar fails three reads, warns, and continues. The test
still reports **8 passed, 0 failed** and the suite exits 0.

**It disappears the moment the orchestrator commits the deletions.** Recorded so
nobody chases it as a defect. No action needed and I did not touch that file.

### `src/report.py` is not in `run_all.sh` — checked by hand, and it is clean

`src/report.py` is new and untracked this wave (report agent) and has **no
`run_all.sh` line**, so the green suite does not exercise it — meaning my
`stats.py` removals could have broken it invisibly. Checked directly:

```
$ grep -n "import stats\|stats\.\|analyze\|latency_report" src/report.py
96:  import stats
803: return stats.quantiles(values, [0.5, 0.95])
```

**`quantiles` survives; no reference to any deleted name.** Not affected.

`tests/test_report.py` also appeared this wave, also untracked, also **not in
`run_all.sh`**. Checked the same way: **no reference to any deleted name**, and
it runs standalone at **75 tests, OK**.

**Gap flagged, not closed:** 75 tests and a new `src/report.py` are currently
outside the suite. I own `run_all.sh` and **nobody requested a `guarded` line
for them this wave**, so I did not add one — adding another agent's test to the
suite unasked is their call, not mine. Orchestrator should route this to the
report agent.

---

## 4. KEPT — where SPEC §9 is wrong. Corrections for the doc agent.

The SPEC is wrong in **four** places (the brief predicted three; `naive_bootstrap`
is a fourth, and the line count is a fifth).

### (i) `src/arms/claude_cli.py` and the `cc_*` arms — KEPT

Killed-ticket code retained by **live** tickets. JEV-04 is KILL, but JEV-16 Run A
ran on `cc_haiku45`, JEV-43 (KEEP) measured it, and **JEV-16 Run B needs the same
harness**. Still referenced by `worker.py`, `latency.py`, `determinism.py`,
`canary.py`, `verdict.py`, `doctor.py`, `config/arms.json`, `tests/test_jev16.py`,
`tests/test_latency.py`. Deleting them would break a live test and a deferred run.

### (ii) `tests/test_board.py` — KEPT

§9's claim is **stale**. The file has been rewritten since and is actively
catching real defects — three in the last two waves, two of them the
orchestrator's own. 8 tests, green, still in `run_all.sh`. Deleting a test that
is currently catching defects because a month-old triage line named it would be
the single worst outcome available here.

### (iii) `stats.clustered_bootstrap` — KEPT (live)

`src/validate_threshold.py:398` calls it for **JEV-17, a KEEP ticket** that W4's
tier thresholds depend on. Not dead. Not touched.

### (iv) `stats.naive_bootstrap` — KEPT, **and the brief's reason for it is wrong**

The brief said `naive_bootstrap`'s callers include `validate_threshold.py`.
**They do not.** `validate_threshold.py:398` calls `clustered_bootstrap` and
nothing else; `naive_bootstrap`'s only callers were `analyze.py` and its own
test. After this cleanup it is **test-only**.

Kept anyway, per the brief's stated bias: it is a five-line wrapper over
`clustered_bootstrap` with no independent logic to rot, and the test it serves
is the only place the project demonstrates *why* clustering is mandatory — which
is load-bearing for JEV-17, whose thresholds read a clustered interval. Removing
the contrast would leave the live function's justification unexercised to save
five lines. Recorded in its docstring.

**Also now test-only, and also left alone** (not in the named eight; flagging
rather than chasing): `base_rate`, `spearman_rho`, `entropy_bits`.

### (v) `PREREGISTRATION.md` — KEPT on disk

Not deleted, per the brief. Already banner-marked retired. Deleting a
pre-registration once its result stops being wanted is precisely what
pre-registration exists to prevent, and Amendments 5–8 still carry measured
facts the cost pipeline depends on (the auth path, the cache-write multiplier).

### (vi) The line figure is wrong

**Actual Python removed: 1,315 lines gross deleted** (`analyze.py` 497 +
`latency_report.py` 451 + `test_analyze_config_join.py` 190 + `stats.py` 93 +
`test_pipeline.py` 84), **1,206 net** after the ~109 lines of comments and
docstrings added to record what went and why. Not "roughly 1,500".

### Suggested replacement sentence for SPEC §9 — doc agent to apply

> Roughly **1,300** lines of Python and the top third of `ISSUES.md` go: the
> agreement statistics (`stats.py`'s boolean-agreement half), the report-v1 and
> figures path (`analyze.py`), the one-shot `latency_report.py`, and
> `PREREGISTRATION.md` as a *live* document — the file itself stays on disk,
> retired-banner intact, because deleting a pre-registration when its answer
> stops being wanted is the behaviour pre-registration exists to prevent.
>
> **Three things this list previously named do not go.** `tests/test_board.py`
> was rewritten and is catching real defects, so it stays. The `cc_*` arms stay
> as a *harness* even though JEV-04 is killed — JEV-16 Run B and JEV-43 both
> need them; this is killed-ticket code retained by live tickets, and the
> pattern is worth naming. `stats.clustered_bootstrap` stays because JEV-17, a
> KEEP ticket feeding W4's tier thresholds, calls it.

**⚠️ SCOPE LIMIT ON THAT REPLACEMENT — doc agent must read this before applying.**
My text covers **only the Python clause** of §9's sentence. The original
continues past what I addressed: *"…the `stop` / `post_edit` / `user_prompt`
surfaces, `random_matched`, and the clustering and power-analysis line of
work"*, and it also claims **"the top third of `ISSUES.md`"** goes. **None of
those were in this cleanup and I have verified none of them.** If you apply my
replacement verbatim, those claims vanish from the SPEC with nobody having
checked whether they are true. Either carry them forward unchanged or verify
them separately.

---

## 5. Recorded findings

### JEV-55: `analyze.py` was publishing a number its own ticket says cannot exist

`analyze.py:152–153` computed `stats.clustered_bootstrap(...)` over session
clusters and published the interval beside every agreement statistic. **JEV-55
established that on the collected corpus the clustered bootstrap has ONE
cluster, so that primary interval is uncomputable.** The deletion removes a path
that computed and published a number the project's own ticket says cannot be
computed on this corpus.

**Correction to an earlier draft of this note, checked against
`git show HEAD:src/analyze.py`.** I first wrote that `analyze.py` printed the
interval "regardless of `Interval.conclusive`". **That is wrong and I am
retracting it.** Line 159 formatted it as `f"...{ci}"` — i.e. via
`Interval.__str__`, which *does* append `INCONCLUSIVE BY RULE: <reason>` when
`MIN_CLUSTERS_FOR_INFERENCE` fires. **The caveat was present.** The honest
version of the finding is narrower: `analyze.py` spent the computation and
surfaced a bound that was always going to be degenerate on this corpus — not
that it hid the degeneracy. `stats.py`'s guard worked as designed.

I carried the warning forward to the surviving caller: `validate_threshold.py`'s
docstring now states the JEV-55 limit explicitly, since it is the one place
still computing such an interval and its thresholds feed W4.

### Dangling string references — recorded, not touched

`uv run src/analyze.py --report` survives as an **example command string** in
`data/fixtures/canary-set-v1.json:34,41` and `src/make_synthetic.py:160`. It now
names a file that does not exist. **Neither is a code path** — they are sample
shell commands fed to arms as test *content*. The canary set is **frozen** and I
did not touch it; changing the bytes would invalidate the frozen comparison. No
action recommended, recorded so nobody rediscovers it as a bug.

### Prose references left for the doc agent

`src/latency.py:10` and `ISSUES.md:2393` describe `analyze.py` / `latency_report.py`
in prose. `src/latency.py` is not on my owned list; `ISSUES.md` is the doc
agent's. Both now reference deleted files.

---

## 6. Files changed or deleted — complete list

**Deleted (3):**
- `src/latency_report.py` (451 lines)
- `src/analyze.py` (497 lines)
- `tests/test_analyze_config_join.py` (190 lines, 7 tests) — ⚠️ outside my owned list, see §0(a)

**Modified (4):**
- `src/stats.py` — 8 agreement functions removed; `Counter` import dropped; module docstring rewritten to record the §8 freeze break and what remains live; `naive_bootstrap` docstring records the brief's error and the keep decision. 307 → 262 lines.
- `src/validate_threshold.py` — stale "§8 freezes `stats.py`" note corrected; JEV-55 one-cluster warning added. +15/−1.
- `tests/test_pipeline.py` — `import analyze` removed; `TestReport` removed (5 tests); 7 `TestStatistics` tests removed; bootstrap statistic rewritten off `pabak`; `capture.sh` cap regex fixed (§3). 104 → 92 tests.
- `tests/run_all.sh` — `test_analyze_config_join.py` line removed, replaced with a comment recording the JEV-32 coverage gap.

**Not touched, deliberately:** `SPEC.md`, `README.md`, `CONTEXT.md`, `ISSUES.md`,
`docs/*`, `hooks/*`, `src/doctor.py`, `src/report.py`, `src/accuracy_gate.py`,
`src/fixture_executor.py`, `src/subagent_outcomes.py`, `PREREGISTRATION.md`,
`src/arms/claude_cli.py`, `tests/test_board.py`, `tests/test_validation.py`,
`data/fixtures/canary-set-v1.json`.

**Zero API calls made. Nothing armed.** No git write commands run.
