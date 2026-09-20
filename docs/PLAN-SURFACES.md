# Plan: taking `stop`, `user_prompt` and `post_edit` live

Companion to `docs/PLAN.md` (design decisions) and `ISSUES.md` (JEV-13).
**Status: plan only. Nothing here is implemented.**

`pre_bash` is live with 62+ captures. The other three have question sets and
state builders that have **never executed against a real payload**. Everything
below treats that as the primary fact: these are not "register and go", they are
three unvalidated code paths.

> **Verification note.** The defects in §6 were independently confirmed against
> the source before this plan was accepted — except §6.1, which is *contested*;
> see the note there. Claims not yet checkable against a live payload are marked.

---

## 0. Cross-cutting decisions (do these before any surface)

### 0.1 Sequencing

**Order: mechanism → `user_prompt` → `stop` → `post_edit`. Staged, never simultaneous.**

| # | Surface | Why here |
|---|---|---|
| 1 | `user_prompt` | `FINDINGS.md` Part 4c is an explicit course correction: **gating is additive on every axis; routing is the only surface that can make Claude Code faster or cheaper.** Strongest economics (one correct downgrade in ~4,000 pays for itself), thinnest evidence (8 prompts, outside the harness, confidently wrong on the hardest item). Payload-only, so it ships the day the mechanism lands. |
| 2 | `stop` | Riskiest mechanism; do it while the hook change is fresh. Lowest volume, so all three arms on 100% is affordable. Its Step 0 unknowns are cheap to learn and could kill the surface — learn that early, not last. |
| 3 | `post_edit` | Payload-only and low-risk, but the only `score` question, and it needs a synthetic set before live data means anything. The build cost is in the stress set, not the registration. |

**Why not simultaneously.** `worker.py` drains serially. At `cc_opus5` 4.2s p50 /
32s p99 and `cc_haiku45` 12.7s p50, one decision costs **20–40s of worker
wall-clock**. Four surfaces at ~50/day × 30s ≈ **100 min/day** of serial draining,
arriving in bursts far faster than it drains. `capture.sh` stops writing above 500
spool files and **exits 0 silently** — the failure mode is invisible data loss.
Stage them, and watch `ls spool/ready | wc -l` during the first session of each.

### 0.2 Per-surface arms (the `cc_*` arms are too slow to *drain*, not too slow to *observe*)

Nothing is on the critical path in shadow mode; the problem is drain throughput.

1. **Add a per-surface `arms` list to `config/surfaces.json`**, defaulting to
   `arms.json:enabled`:

   | surface | arms | rationale |
   |---|---|---|
   | `pre_bash` | jev, cc_opus5, cc_haiku45 | unchanged; the primary metric depends on it |
   | `stop` | jev, cc_opus5, cc_haiku45 | low volume, high value per row |
   | `user_prompt` | jev 100%, cc_opus5 subsampled | highest volume, cheapest question |
   | `post_edit` | jev 100%, cc_opus5 subsampled | large states (whole diffs); drop cc_haiku45 |

2. **Deterministic baseline subsampling**, not random: run the `cc_*` arms only
   when `int(sha256(decision_id)[:8], 16) % k == 0`, `k=3`. Deterministic so a
   replay reproduces exactly which rows are paired, and so it can be
   pre-registered as a *rule* rather than a seed. Jev runs on 100% always — those
   rows still carry sharpness, latency, base rate and realised-cost correlation.
   Paired agreement is computed on the sampled subset only, and the report must
   print `n_paired` beside `n_rows`. Record `baseline_sample_rate` on the capture.

### 0.3 These surfaces are outside the current pre-registration

`PREREGISTRATION.md` §1 scopes Phase 1 to **one surface (`pre_bash`)**, and §8
freezes `questions/*/v1.json` at that commit. Two non-optional consequences:

- **Any question-set change is a new version file, never an edit.** The
  `complexity` question below goes in `questions/user_prompt/v2.json`.
- **Write and commit `PREREGISTRATION-SURFACES.md` before the first capture of
  each surface**, stating that surface's primary metric, directional hypothesis,
  expected base rate and falsification condition. A surface registered after its
  data exists is not pre-registered, and a hostile reader will say so.

### 0.4 GATE 4 — the leakage test that does not currently exist

**Verified: `tests/gates.sh` has 21 assertions and none of them test decision #7.**
The study's most load-bearing methodological claim is asserted in three documents
and verified nowhere. Add a fourth gate — offline, `FakeArm`, no network:

> **GATE 4 — NO FUTURE LEAKAGE.** Build a fixture transcript. Fire the hook.
> Record `state_sha256_expected` from the file as it is now. **Append 20 more
> lines.** Drain the spool. Assert the row's `state_sha256` still equals
> `state_sha256_expected`.
>
> Then the negative control: strip the offset and assert the capture is
> **quarantined**, not processed. `build_stop` already refuses without the
> offset; this proves the refusal is wired through.

Build it with the mechanism, before `stop` is registered. **This gate applies to
the already-live `pre_bash` surface too** and should not wait for `stop`.

### 0.5 The rule that resolves most of the confusion below

> **Future turns are forbidden as STATE. Future turns are permitted as LABELS.**

Decision #7 forbids *showing an arm* anything after the decision point. It says
nothing about the analysis deriving an *outcome* from later turns — that is what a
label is. This unlocks free, human-free labels on two surfaces (§1.7, §2.4). Write
it into `docs/PLAN.md` beside decision #7; it is currently implicit and someone
will get it wrong.

---

## 1. `stop` — the blocker, and how it is resolved

### 1.1 The blocker

`build_stop` requires `payload["transcript_bytes_at_capture"]` and raises without
it. `capture.sh` is `cat > tmp; mv tmp ready/` — it never parses, so it cannot
find `transcript_path`, so it cannot `stat` it. Decision #7's mechanism has no
implementation route as written. The builder's refusal is currently the only thing
preventing a silent leak.

### 1.2 Options

| Option | Verdict |
|---|---|
| **A. Filename-encoded offset, zero-fork extraction, one `stat`** | **RECOMMENDED** |
| B. Rewrite the JSON to inject the field | Rejected: makes the spooler a JSON writer in bash 3.2, and the payload is no longer byte-exact |
| C. `cp` the whole transcript at hook time | Rejected: MB-scale transcripts → 10–50ms, 5× over budget; duplicates third-party content into the repo (which JEV-06 deliberately avoided); and a `cp` racing an append has the *same* boundary problem, just with more bytes |
| D. Timestamp marker | Rejected: needs a `date` fork anyway, 1s resolution against a transcript gaining lines per second. Strictly fuzzier than bytes for the same cost |
| E. `last_assistant_message` only | Rejected by the question set's own reasoning: completion is relative to what was asked |

### 1.3 STEP 0 — the two unknowns that decide viability

**Do this before writing any code.** Register `stop` as `capture_only` with the
*current unmodified* `capture.sh`, run one session, inspect the payload by hand:

1. **Does the Stop payload carry `last_assistant_message`?**
   > **CONTESTED.** The planning agent believed it "very likely absent". Earlier
   > research in this project recorded Stop stdin as carrying `stop_hook_active`
   > **and `last_assistant_message`**. One of these is wrong, and it is cheap to
   > settle by looking. Do not build on either belief.
2. **Is the final assistant message flushed to the transcript before Stop fires?**
   Compare `stat -f %z` at hook time against the transcript's last complete line.
   If the flush happens *after* the hook, the byte prefix ends before the message
   being judged and **no truncation marker fixes that.**

**If both go the wrong way, `stop` has no valid state and the surface is cancelled
with a written negative result.** "The Stop hook cannot see the message it is being
asked about" is a publishable finding about hook design, and far cheaper than a
week of uninterpretable rows.

### 1.4 Option A in detail

**Hook.** Give `stop` its own registration line calling the same `capture.sh`
(the surface argument already selects behaviour). After `cat > "$STAGED"`:

- Slurp the staged file with the `read` **builtin** (no fork). Payloads are
  single-line compact JSON — confirmed against a real spool file.
- Extract `transcript_path` with parameter expansion only, tolerant of a space
  after the colon. **Zero forks.**
- `stat -f "%z %m" "$TP"` — **one fork, both fields**, ~1ms.
- Rename to `stop__<bytes>__<mtime>__$ID.json`.
- Every failure path falls through to `bytes=0`, which the worker quarantines.
  Fail-open preserved: the hook still exits 0 on every path.

**Latency:** ≈ **+1–2ms** on a measured 6.5ms hook, and only on `stop`. Re-time
with `bench_inline.py` at N=200; fail above 10ms.

**Worker.** `drain_once` currently does `name.split("__", 1)[0]`. Split all `__`
fields; for `stop`, inject them into the payload as
`transcript_bytes_at_capture` / `transcript_mtime_at_capture` before `sb.build`.
**Also write both onto the capture row** — the spool file is unlinked after
processing, so if the offset lives only in the filename it is gone forever and
decision #7's per-row auditability does not actually exist.

**Worker guards, each with a named quarantine reason:**

| condition | reason |
|---|---|
| current size < recorded offset | `transcript_rewritten` (compaction, or a new session file) |
| offset present, file missing | `transcript_gone` |
| prefix yields < 2 turns | `prefix_too_short` |
| prefix's last complete line is not an assistant message | `prefix_precedes_final_message` — **the flush-race detector, and its rate is a finding**; count it in attrition rather than skipping |

### 1.5 State builder

**Must:** the prefix `[0:transcript_bytes_at_capture]` only, `errors="ignore"`,
partial trailing line discarded (already correct).

**Must not:** any read beyond the offset; any glob of `<session>/subagents/`; the
user's *next* message under any circumstance — that is the answer to
`task_complete`.

**Two defects to fix while in there** (both verified):

- **`_flatten_content` keeps `body[:500]` — the HEAD — of each tool result.**
  Test runners and linters print their verdict at the **tail**
  (`5 failed, 12 passed`). `has_unverified_claim` is specifically about whether
  tool output supports a claim, and the builder systematically discards the part
  that would settle it. Use head 250 + tail 250 with an elision marker.
- **`_truncate` front-truncates to keep the end** — right for a transcript, but
  `task_complete` depends on the user's request, which sits at the **front**. Add
  a head-preserving variant for `stop`: first user message verbatim + elided tail.

### 1.6 Synthetic set: mandatory here

The live base rate is degenerate in the unhelpful direction — the assistant stops
when it thinks it is done. Expect `task_complete` ≈ 90–97% true,
`has_unverified_claim` ≈ 3–10%. PABAK ≈ 0.9, κ ≈ 0.0, neither meaning anything.
**Live `stop` data can measure agreement and latency but not discrimination.**

Build `data/synthetic/stop-v1.jsonl`: ~60 hand-written mini-transcripts, 20 per
stratum, each a small JSONL fixture plus a payload pointing at it with an explicit
byte offset (which also exercises the real code path):

- **complete** — request carried out, tool output present and supporting.
- **incomplete** — a multi-part request with one part silently dropped; a "let me
  know if you also want…" ending; an error in the last tool result followed by a
  confident summary.
- **unverified-claim** — "tests now pass" with no test run; "deployed" with no
  deploy command; "verified the fix" after only an Edit. **The interesting
  stratum, and the one no live week will produce.**

Include 5 adversarial items where the claim is *true and verified* but phrased
identically — separating "detects a claim" from "detects an unsupported claim",
as `destructive` vs `needs_review` did.

### 1.7 Free labels

The user's **next** message after a Stop is a legitimate outcome label (§0.5): a
correction, a re-ask, or "you didn't…" means the task was not complete. Harvest in
analysis, never in state. Gives `stop` a semi-gold label with no human pass.

---

## 2. `user_prompt` — routing

### 2.1 Which question: both, as `v2`, and no model-choice question

1. **Keep `route`** (8-category `choice`). Pre-registered, and the only `choice`
   question in the study — so the only thing exercising option-order sensitivity
   and `categorical_kappa`. Its low-κ outcome is already pre-committed as a
   finding about task ambiguity.
2. **Add `complexity`** as a 5-anchor `score`, in a **new `v2.json`**. Part 5.1
   showed it cleanly monotone; Part 5.3 concluded the score question outperformed
   the choice question.
3. **Do not add a "which model" question.** It is the weaker formulation and it
   bakes a policy into the measurement. A complexity score plus a threshold lets
   you evaluate *every* routing policy offline from one set of rows; a
   model-choice answer lets you evaluate exactly one.

Both questions go in one Jev call — marginal cost near zero against ~278 tokens
of fixed scaffolding.

**Anchors** (low→high): mechanical // single-file localised // multi-file but
specified // requires diagnosis from symptoms // open-ended design, no stated
approach.

**The deployable policy, evaluated offline** (an analysis, not a question):
`route down only if complexity ≤ τ AND confidence ≥ c`. Part 5.3 showed confidence
catches *ambiguity* (0.46, 0.33) but **not** the confident p99 miss — report the
policy's miss rate explicitly rather than implying confidence closes the gap.

### 2.2 State builder

**Must:** `payload["prompt"]`, `is_continuation`. That is what
`build_user_prompt` does today, and it is correct.

**Must not:** the transcript. This is the canonical leakage case named in
decision #7 — reading it at worker time shows the classifier Claude's answer to
the prompt it is routing.

**But flag the confound this creates.** The Part 5 probe was prompt-only, and the
item it got confidently wrong — *"3× p99 latency after a deploy, only a pool
config changed"* — is hard **because of the codebase**, not the sentence. A
prompt-only router may be failing for want of context rather than capability.
That is an argument for **recording the transcript offset on every surface**
(§6.8): ~1ms, and it lets a future context-aware `v3` builder replay the same
captures without re-collecting a week of data.

### 2.3 Base rate: not degenerate, and that is the point

`route` will be dominated by `code_edit` and `debug` — modal class ~40–55%,
skewed but nowhere near `pre_bash.destructive`'s 1–5%. `complexity` will be broad.
Print the majority-class baseline beside every agreement number (already
enforced): a 50%-modal router agreeing 55% of the time is doing almost nothing.

### 2.4 The free label that tests the study's strongest claim

**Realised turn cost is a future-derived label and is permitted** (§0.5). For each
`user_prompt` capture, join the turn that followed: output tokens, tool-call
count, `is_error` count, wall-clock. Correlate Jev's `complexity` against realised
cost.

This is **the only Phase-1-feasible test of the economics**, and it needs zero
human labels. If complexity does not predict realised cost, the $0.0520-per-
downgrade story never materialises regardless of how well Jev agrees with Opus.
Make it the surface's pre-registered secondary metric (Spearman ρ between
`complexity` and realised output tokens, clustered on session).

### 2.5 Synthetic set: yes, small

Extend the 8-prompt probe to ~60 items, 12 per tier, deliberately including the
class the probe failed on: **symptom-only debugging prompts that are short and
plain-sounding but require deep diagnosis.** That class is the whole risk. If Jev
scores them low, the surface is not deployable at any threshold — and you want to
know that at n=12, not n=1.

### 2.6 Registration

```json
"UserPromptSubmit": [{ "hooks": [{ "type": "command",
  "command": "\"$CLAUDE_PROJECT_DIR/hooks/capture.sh\" user_prompt", "timeout": 5 }] }]
```

**`UserPromptSubmit` stdout is injected into the session context.** The hook
already guarantees empty stdout and a gate asserts it — re-run that gate
specifically for this surface, because here a stray byte is not a permission
decision, it is **contamination of the prompt being measured**. Highest-stakes
stdout surface in the study.

---

## 3. `post_edit` — a 1–5 risk score on a diff

### 3.1 Main risk: the builder has never seen a real payload, and one branch is probably dead

- **`isinstance(response, str)` (verified present at `state_builders.py:86`).**
  `tool_response` for Edit/Write is a **dict** (`filePath`, `originalFile`,
  `structuredPatch`…), not a string. If so the tool result is **silently
  dropped** — never raising, never logged. *Unverified against a live payload;
  confirm in `capture_only` before trusting a row.*
- **Matcher mismatch (verified).** `surfaces.json` declares
  `Edit|Write|NotebookEdit`, but the builder raises without
  `old_string`/`new_string`/`content`. NotebookEdit (`new_source`) and MultiEdit
  (`edits[]`) would **quarantine every time**. **Register `Edit|Write` only** and
  fix `surfaces.json`, or add the branches — do not ship the mismatch, it produces
  a quarantine stream that looks like a harness bug.
- **Write + front-truncation.** `_truncate` keeps the end. For a `Write` of a new
  file that discards imports, the docstring and top-level structure — precisely
  what separates anchor 1 from anchor 5. Use head-preserving truncation here.

### 3.2 What the state must and must not include

**Must:** tool name, file path, old/new strings (or content), and — new — a
**bounded window of `tool_response.originalFile` around the edit** (±40 lines).
`originalFile` is the *pre-edit* file, so it is not future information, and it is
the context a risk score actually needs: the same three-line diff is anchor 2
inside a pure function and anchor 5 inside an auth check. Bound it; never paste
whole files.

**Must not:** the post-edit file as it exists at worker time (it may have been
edited again); any later tool result; any test run that happened after.

### 3.3 `score` subtleties already paid for

`from_wire` shifts Jev 0→1-indexed and rounds to 2dp — done and regression-tested.
Two things to carry forward:

- `_score_section` already reports Spearman, QWK, MAE **and Bland–Altman mean
  bias**. The mean-bias line is the one that would have caught the off-by-one.
  Do not let it fall out of the report.
- Jev returns an **expected value** (3.37); the Claude arms return an integer.
  These are not the same kind of quantity. QWK needs integers — state **how Jev's
  float is binned** (round-half-even) and report Spearman on the *unbinned* float
  as primary, since binning discards the information the float carries.

### 3.4 Base rate: degenerate in the boring direction

Live edits here are overwhelmingly markdown and small Python: expect **70%+ of
scores at 1–2**, essentially nothing at 5. Live data will measure agreement and
latency and nothing about discrimination at the top of the scale — where all the
value is.

**A synthetic set is mandatory here, more than anywhere else.** ~100 items, 20 per
anchor, each rendered in two forms (an `Edit` replacement and a `Write`
whole-file) so tool-shape sensitivity is measurable. Include the adversarial pairs
that matter: **a one-character diff flipping a comparison in an auth check**
(anchor 5, looks like anchor 1), and **a 200-line reformatting commit** (anchor 1,
looks like anchor 4). If Jev scores diff *size* rather than diff *consequence*,
those pairs expose it immediately.

### 3.5 Registration

```json
"PostToolUse": [{ "matcher": "Edit|Write",
  "hooks": [{ "type": "command",
  "command": "\"$CLAUDE_PROJECT_DIR/hooks/capture.sh\" post_edit", "timeout": 5 }] }]
```

Largest states of the payload-only surfaces (whole-file Writes) — watch spool disk
and the 60k char cap.

---

## 4. Incremental cost and latency

Session latency impact is **0ms in shadow mode** for all three — the hook is a
spooler. The only session-visible cost is the hook itself: 6.5ms today, +1–2ms on
`stop`.

| surface | est. rate | arms | worker load | session impact |
|---|---|---|---|---|
| `stop` | 30–60/day | 3 | ~25 min/day | +8ms/turn-end |
| `user_prompt` | 30–60/day | jev + 1-in-3 opus | ~6 min/day | +6.5ms/turn |
| `post_edit` | 30–80/day | jev + 1-in-3 opus | ~8 min/day | +6.5ms/edit |

With per-surface arm lists, all four sit at **60–75 min/day** of worker time in
bursts — drainable, but only just. Without them, ~2.5 hours/day and backpressure
loss during any heavy session.

---

## 5. Definition of done, per surface

1. `capture_only` for one full session; payload keys inspected by hand and
   recorded in `docs/`.
2. State builder run against ≥5 real payloads; every `StateBuildError` or
   silently dropped field fixed.
3. The three existing gates re-run **parameterised on the surface** (they are
   hardcoded to `pre_bash` today); **GATE 4** passes.
4. `bench_inline.py` re-timed; hook p99 < 10ms.
5. Surface section added to `PREREGISTRATION-SURFACES.md` and **committed**.
6. Synthetic set built and replayed; AUC / monotonicity / Spearman reported and
   labelled synthetic.
7. Flip to `shadow`. Watch `spool/ready` count and `spool/dead` reasons for the
   first session.

---

## 6. Defects in the existing design

Verified against source unless marked otherwise.

1. **CONTESTED — `build_stop` reads `last_assistant_message`.** The planning agent
   believed the Stop payload probably lacks it; earlier research in this project
   recorded it as present. Settle by looking (§1.3), build on neither belief.
2. **VERIFIED — `_flatten_content` keeps the head (`body[:500]`) of tool results.**
   Verdicts are at the tail. Directly undermines `has_unverified_claim`.
3. **PLAUSIBLE, unverified — `build_post_edit`'s `isinstance(response, str)`** is
   likely always false, silently dropping the tool result.
4. **VERIFIED — `surfaces.json` matcher `Edit|Write|NotebookEdit` contradicts the
   builder**, which quarantines NotebookEdit and MultiEdit unconditionally.
5. **VERIFIED — front-truncation is right for transcripts and wrong for `Write`
   payloads**, where it discards exactly what determines the risk anchor.
6. **VERIFIED — `tests/gates.sh` never tests the future-leakage guarantee.** 21
   assertions covering isolation, fail-open and the kill switch; zero covering
   decision #7, which is the study's most load-bearing methodological claim.
   Asserted in three documents, verified nowhere. **Applies to the already-live
   `pre_bash` surface and should not wait for `stop`.**
7. **Decision #7 conflates state-leakage with label-derivation.** As written it
   discourages the future-derived labels that are the only free ground truth
   available in Phase 1. Add the STATE/LABEL distinction (§0.5) explicitly.
8. **`transcript_bytes_at_capture` should be recorded on all four surfaces**, not
   just `stop`. ~1ms, and it makes every capture replayable under a future
   context-aware builder instead of requiring a fresh collection window.
