# W5 doc sweep — prose and board, 2026-09-21

Error-correction pass over the documents the six post-pivot waves left behind.
Prose and board only; nothing under `src/`, `hooks/`, `config/`, `tests/` was
touched. Zero API calls, nothing armed.

`uv run tests/test_board.py` — **green** at start and at finish (8 tests).

Every item below was verified against the tree before it was changed. Where a
document stated something **true when written and false now**, the correction is
recorded visibly beside the original rather than silently rewritten — that
convention is the reason this repo's findings are still readable.

---

## The one finding worth reading first

### The 7-capture gap: source identified, and the obvious explanation is wrong

`SPEC.md` §9 carried *"a count discrepancy nobody has explained"* — 578 captures
on disk against the board's frozen 571 — with a standing instruction that
**neither number be quoted**. The runs gap (2,005 → 2,095) was already
attributed to JEV-16 Run A's 90 replay rows; the captures gap was not.

**Both gaps are JEV-16 Run A.** The arithmetic is exact:

| | live | synthetic | canary | replay | total |
|---|---|---|---|---|---|
| captures on disk | 490 | **67** | 21 | — | **578** |
| freeze figure 571 implies | 490 | **60** | 21 | — | 571 |
| run rows on disk | 1,783 | 180 | 42 | **90** | **2,095** |
| freeze figure 2,005 implies | 1,783 | 180 | 42 | **0** | 2,005 |

Run A needed nine paired synthetic states; seven had to be materialised into
`data/captures/` before the sweep could run, the other two already existed and
were checked to hash identically to a rebuild (`.scratch/a3-prep/jev16.md`).
Those seven are identifiable — `picked_at` all within **2026-09-20T17:26:15**,
`run_context: synthetic`, `decision_id`s
`syn-syn-0000/0001/0002/0120/0122/0240/0241` — and **70 of Run A's 90 replay
rows reference them**. The other 60 synthetic captures are the original stress
set, written 06:51–07:10Z.

#### ⚠️ My first version of this said "Run A ran after the freeze." It did not.

I wrote that, and it was wrong; the advisor caught it and the timestamps settle
it. **Run A ran 17:26–17:37Z. The freeze is stamped 21:42Z — four hours later.**
The newest row of any kind in either file is **17:36:57Z**. Nothing in this
corpus post-dates the freeze. (Cross-checked against the history: Run A's report
commits are `8b77edc` / `80128d9`, 2026-09-20 23:10–23:14 +0530 = 17:40–17:44Z,
minutes after the rows were written. `data/captures/` is untracked, so the rows'
own timestamps are the only evidence there, and they agree.)

**So the real finding is a different and slightly worse one:**

> **571 / 2,005 was already an undercount at the moment it was written.** It is
> not a freeze-time count of the files. It is either a figure **carried forward
> from before Run A landed**, or one taken by a method that counted the
> synthetic component as "the 60-item stress set" and skipped
> `run_context: replay` entirely. The two omissions are exactly Run A's output,
> which makes carried-forward the likelier of the two. **Which it was is open**,
> and is recorded as open rather than guessed.

**Consequence: stop quoting 571 / 2,005 as "standing totals at the freeze."**
The standing totals at the freeze were 578 / 2,095, and they still are. This is
a mild instance of the house pattern — **an inventory that was *reported* rather
than *counted* reads exactly like one that was counted.** Which is the argument
for JEV-52 step 7's dated live inventory being produced by counting the files.

Recorded in `SPEC.md` §9 item 4, on JEV-52's frozen-state paragraph, and beside
the superseded execution plan's copy of the same figures.

---

## SPEC.md

### §5 was structurally broken — reconciled onto the W-scheme

The section was left half-converted by the pivot: a W-table, then a stray
"P0 applies to every phase" line, then **three orphaned `| **P2** | … | **P3** |
… | **P4** |` rows** from a deleted phase table, then prose arguing about
"P1/P2 ordering", "P1 was rewritten", "Why P1 became ingestion-time trim". A
reader could not tell whether the project had P-phases or W-waves. The harvest
ledger routed items into "P1", "P1b", "P4", "P0" and "P3 policy" — none of which
exist.

**The reasoning was the valuable part and is preserved in full**; only the labels
moved. The mapping is now written into the section as a table, so the older
commits still read:

| dead label | what it was | where it went |
|---|---|---|
| P0 | replay harness + constant control | cross-cutting, every wave |
| P1 / P1b | context reduction / compaction | **W6** |
| P2 | the guard | **W3** |
| P3 | routing | **W1** then **W4** |
| P4 | tool-output trim | **W6** |

Specifically:

- The three orphan rows are **gone**, and each one's distinct reasoning was
  folded in rather than dropped — P2's *"must be shown to catch a deliberately
  injected regression before it is trusted"* is now a standing bar on the guard;
  P4's *"same mechanism class, applied earlier in the pipeline"* is now the
  stated **argument for merging P1 and P4 into W6**, which is what actually
  happened once P1 was rewritten as ingestion-time trim.
- "The P1/P2 ordering is deliberate" → the optimization/guard ordering, with the
  point sharpened: it is why W1 shipped **built, not armed**, and why W5 exists
  at all (W3's gate exits 1 for want of labels, so nothing may be armed).
- "P1 was rewritten on evidence" → "Context reduction was rewritten on
  evidence", noting it was demoted *and* had its mechanism replaced.
- Harvest ledger `into` column relabelled throughout (7 rows).
- §8's *"routing survives as P3"* → W1 then W4.

**A second drift found while doing this, and fixed:** SPEC's wave table stopped
at **W6** while `ISSUES.md` had already inserted **W5 "unstick the gate"** and
pushed context reduction to **W6** and operate to **W7**. `ISSUES.md` is the live
numbering; SPEC now reproduces it. Without this the two documents disagreed
about what "W5" means, which is worse than either being stale.

### `⏳` placeholders — removed

All three were in §4's architecture tree (`provider/`, `route/`, `trim/`). Two of
the three had been resolved since they were written. Replaced with dated states —
`[W2, done]`, `[W1 built, NOT ARMED]`, `[W3 built; exits 1 until W5 lands
labels]`, `[W6, not started]`, `[W5, has never existed]` — with a note on why: a
placeholder nobody can date is worse than a stated state.

### Numbers checked against §10 and §11

**Result: no cross-window comparison found in SPEC.** $5.21 does not appear in
the file; $2.88 appears in §2 R5 and §11's movement table, both correctly labelled
as the JEV-24a-cut anchor. The existing guard against quoting W0's +38.9%
against the frozen record's +45.2% is intact.

A **standing guard was added to §11** anyway, because the trap is one step away:

| figure | window | what it is |
|---|---|---|
| **$2.88** | under the JEV-24a cut (7 tasks) | **the anchor** |
| **$5.21** | whole corpus, no cut (33 tasks, mean; median $4.50) | a description of today's corpus, **not** an anchor |

They differ by **corpus and cut, not by costing rule** — both are computed under
the corrected rule. Quoting them against each other produces an 81% "increase"
that is entirely an artefact of the window.

*(For the record: `.scratch/pivot/w5-data-fixes.md` already states this
correctly and was not the source of any defect. I do not own that file and did
not change it.)*

### Triage tally corrected

13 REPURPOSE / 17 KILL → **10 REPURPOSE / 20 KILL** after the three re-verdicts
below.

### §9's "what dies" sentence was an estimate, and was wrong in five places

*(Added on the coordinator's relay from the cleanup agent, then verified here
against the tree.)* That sentence was written **before anything was deleted**
and was being read as a record of what had been. **A forecast of a deletion is
not a record of one.** The original is preserved in the doc; the rewrite says:

- **What actually went: 1,315 gross / 1,206 net lines** (`src/analyze.py`,
  `src/latency_report.py`, `tests/test_analyze_config_join.py`) — not "roughly
  1,500".
- **Never built, so they die as plans not as code:** `random_matched` (verified:
  zero references in `src/`, `tests/`, `config/`) and the power analysis (no
  module ever existed).
- **Four KEEPs the estimate got wrong**, all verified here:
  - **`cc_*` arms / `src/arms/claude_cli.py`** — referenced by 9 modules,
    `config/arms.json` and 2 tests, and needed by two *live* tickets: **JEV-16
    Run B** (which I just made a W4 blocker) and JEV-43. *Killed-ticket code
    retained by live tickets* is a real category; deleting on the triage label
    alone would have broken the W4 gate.
  - **`tests/test_board.py`** — live, required, currently catching real defects
    (including two of mine, this session).
  - **`stats.clustered_bootstrap`** — live via `validate_threshold.py:412`.
  - **`stats.naive_bootstrap`** — kept, but the reason in my brief was wrong.
    `validate_threshold.py` calls `clustered_bootstrap` only, so this is
    **test-only**. It is retained because its test is the **only demonstration
    of why clustering is mandatory**, load-bearing for JEV-17. Recording the
    right reason matters — "it has a caller" is a claim the next cleanup pass
    will re-check and find false.
- **Two clauses left explicitly UNVERIFIED rather than restated as done**, since
  only the Python clause was audited: that the `stop` / `post_edit` /
  `user_prompt` surfaces "go" (their config entries and `questions/` dirs are
  all still present at `mode: off` — what died is the *plan to collect*, not an
  artifact), and "the top third of `ISSUES.md`", which nobody has measured.

---

## README.md

### `.env.example` — created

`cp .env.example .env` pointed at a file that did not exist. **Created it**
rather than removing the instruction: the instruction is the right one, the file
is three lines of real content, and a `doctor.py` that expects `.env` should
have a template next to it.

It is credentials-free: `AI_GATEWAY_API_KEY=` empty, plus comments explaining
(a) that `ANTHROPIC_API_KEY` is deliberately absent and must stay absent, and
(b) that `JEV_HOME` is *not* set there on purpose, because a stale absolute path
in a copied `.env` is one of the ways the global kill switch ends up naming a
file that cannot exist.

> ### ⚠️ ACTION NEEDED FROM WHOEVER COMMITS — one line in `.gitignore`
>
> `.gitignore:3` is `.env.*`, which **matches `.env.example`**. Verified:
> `git check-ignore -v .env.example` → `.gitignore:3:.env.*`. So `git add` will
> skip the new file **in silence**, and the README instruction stays broken on a
> fresh clone — a failure that looks exactly like success, which is this repo's
> signature defect.
>
> It needs `!.env.example` after the `.env.*` line. **I did not make that edit:
> `.gitignore` is not in my owned set.** The requirement is also written into
> the footer of `.env.example` itself so it cannot be lost with this report.

### "Claim discipline" — rewritten

It banned the word "accuracy" from output while the repo ships
`src/accuracy_gate.py`. The old text is **quoted in place** and the reversal
explained: the ban was right for a study whose deliverable was an agreement
statistic against an Opus pseudo-label, and wrong for a product that measures
*task outcomes*. Replaced with four narrower rules that do the work the ban was
doing — never call agreement "accuracy"; a gate that cannot run exits non-zero
rather than passing; the gate states its own power; a firing rate is always
quoted with its τ.

### W2's user-facing surface — added

`jev install` / `uninstall` / `status`, `JEV_HOME`, and tier A vs tier B
teardown were entirely absent. Added as a new section, plus:

**The switches now agree with `docs/REVERSIBILITY.md`.** README documented **one**
kill switch; REVERSIBILITY documents **three**. README now carries the same
table — global (`$JEV_HOME/.jev-disabled`), machine-wide
(`~/.claude/jev-disabled`), per-project (`<repo>/.jev-disabled`) — with the W5
finding recorded: the machine-wide switch was the one `jev install` *prints* and
it stopped nothing, because the block lived in one hook script of three.

"Two hard constraints" was also updated: isolation and self-containment were
written for a single-repo experiment and said things that are no longer true
once `jev install` exists.

---

## CONTEXT.md

### Header

Pointed at `PREREGISTRATION.md` for "commitments". That document is retired.
There is no commitments file now — the SPEC's non-negotiables are the standing
constraints and `ISSUES.md` is the plan. Added the convention that dead terms
are marked **RETIRED** and kept, because they still appear in `data/runs/` rows
and in frozen reports.

### Entries corrected

| term | what was wrong |
|---|---|
| **classifier arm** | the `cc_*` set is KILLed. Marked RETIRED; recorded what survives (Jev's latency distribution; τ=0.5 wrong three independent times) and that the rows are now the **Class 1 corpus**, not an experiment |
| **routing arm** | the randomised A/B is retired — no coin flip, no control arm. Marked RETIRED with a reading key for old documents |
| **surface** | three of five KILLed. Replaced the flat list of five with a table giving each one's state today |
| **decision point** | *"every classifier arm answers the same decision point on the same bytes"* presumed the matrix. Now stated as a fact about rows on disk, not about live behaviour |
| **run** | the `(decision_id, classifier arm, …)` tuple is now a description of `data/runs/`, not of anything new |
| **assignment** | said *"allocated by the coin flip"* and *"falls open to the default"*. **Both false** — the second is the *reverse* of operator decision 2 (fail to FRONTIER). A doc saying "falls open" describes a design where a router outage quietly downgrades your work |
| **delegated task** | "the unit of randomisation" — nothing is randomised |
| section heading | "The routing experiment" → "Routing" |

### **shadow** — verified against `config/surfaces.json`, and the old claim is wrong

The entry ended *"The `pre_bash` surface is shadow; `agent_route` is not."*
Checked against the config today, that second clause is **false, and false in
the direction that matters** — it reads as though the product surface were live.

What is actually true, and is now written:

- `agent_route` is **`mode: "off"`**, and the file's own comment calls it a
  *"SHADOW SURFACE, not registered and not armed"*. `mode: off` means **no hook
  entry exists in `.claude/settings.local.json` at all** — so it is not shadowing
  either; it is absent.
- `pre_bash` is `mode: "shadow"` and is the only surface that has ever run.
- The distinction the old clause was reaching for is real and was kept:
  **`agent_route` is the one surface designed to ACT** — it rewrites
  `tool_input.model` — which is what makes arming it a gated act.
- **`enforce` is not reachable from `config/surfaces.json` at all**: it requires
  registering a *different script*, so a passive observer can never become a
  blocker via a config typo. "Shadow" is a property of which script is
  registered, not of a mode string.

### Operator decision 3 added to uplift/escalation

**RESTART on escalation, do not continue** — the higher tier starts from the
original task, so **an escalation pays twice, in money and in time**, the second
attempt being serial with the first. That is what makes uplift cheap and
escalation expensive, why rework is R1, and why **down-routing must be gated
harder than up-routing**.

### Eleven terms added, all in daily use and none defined

`JEV_HOME` · frontier tier · circuit breaker · static floor / tier map ·
assignment ledger · miss-vs-error · Class 1 / Class 2 · fixture suite ·
constant control · Tier A / Tier B teardown · INERT marker

Each is written from the source of truth (`config/tiers.json`,
`src/assignment_ledger.py`, `src/doctor.py`, SPEC §6), not from memory. The
section closes on the rule they all point at: **every silent path needs a
positive assertion that it did something, not merely that it did not error** —
with the four recorded instances.

---

## docs/PLAN.md

The freeze header said it was superseded by *"`SPEC.md`, whose **Status** section
names each reversal"*. **The current SPEC has no Status section** — that sentence
was written against the old spec, now archived. So the single pointer telling a
reader how to use a 706-line frozen document pointed at nothing.

- Pointer repaired with a **table of where the reversals actually are** (SPEC §1,
  §8, §9, §10–11), plus the two reversals a reader hits in the first two pages:
  the publication goal is retired, and gating is *refuted*, not merely
  superseded.
- The header's "nothing will be edited" rule is amended to permit exactly one
  kind of edit: a bracketed `[CORRECTED 2026-09-21: …]` note **beside** — never
  replacing — a sentence the repo has since measured to be false.
- **`:20`** *"$0.042/1M input tokens (output free)"* — SPEC §7 records the input
  price as vendor-confirmed and **"output free" as unverified**; no output price
  is stated anywhere found. It is asserted as fact **three times** in this file
  (Context, the cost model, Motivation); all three are now flagged. The same note
  records that the paragraph's *conclusion* — "cheap and fast enough to sit
  inside Claude Code hooks" — was tested and came out negative.
- **`:509`** *"Nobody has measured whether it does. The user wants to find out
  and publish it."* — **both halves false.** We measured it (`FINDINGS.md`), and
  JEV-50 retracted the novelty claim (eleven prior Jev evaluations existed).
  There is no publication: the goal was retired and JEV-53 is KILLed.

---

## docs/REVERSIBILITY.md

Tier B's claim that re-install reproduces the document **"exactly"** was
**overclaiming**. `src/install.py`'s docstring (`:61`) and its printed output
(`:769`) were corrected when the check was written; this document was missed, so
for a while the doc promised a stronger guarantee than the code delivers.

Corrected to the code's own wording: *up to the order of the groups within one
hook event* — which is not a behaviour (Claude Code runs every matching group)
and which `merge_entries` cannot reconstruct, since it always appends ours last.
**The user's own groups are checked in exact order separately.**

Not cosmetic: "exactly" invites a reader to treat tier B as byte-identity, which
is precisely what tier B is not — that is tier A, and the whole reason the two
tiers are named and printed apart.

---

## ISSUES.md

### JEV-52

- **Step 1 fixed in the ticket body.** It read *"Green from a clean checkout, not
  from a working tree with uncommitted fixes"* — a rule in prose, which is the
  failure mode this very ticket warns about. An earlier commit claimed to have
  pointed it at `tests/test_clean_checkout.sh` and **edited a different,
  superseded paragraph**, so the live sequence never changed. Now names the
  script (verified present). Logged as a fifth instance of the house pattern:
  a fix that reported success while leaving the named thing untouched.
- **Step 6 (pre-registration) dropped**, struck through with the reason. The
  ticket's own PIVOT TRIAGE line already said to drop it and the step outlived
  the instruction. It was unsatisfiable on its own terms — it required committing
  the `random_matched` procedure, and `random_matched` died with the A/B. Two
  clauses worth keeping were relocated, not lost: fail-to-FRONTIER semantics
  (operator decision 2 / non-negotiable 1(b)) and the era rules for pre-gate rows
  (a property of `arm_config_id` on the rows, where they were always enforced).
- **The pre-registration acceptance box dropped.** An untickable box on a gate
  ticket is the shape of a gate that can never close — exactly the defect the
  blocker list was rewritten to remove.
- Frozen inventory: the 7-capture gap explained (top of this report).

### JEV-16

- **Run C dropped as CANCELLED.** It was referenced in the status line and
  defined only in `.scratch/wave2-prep.md` and in a section marked SUPERSEDED, so
  from the live board it read as a run that exists somewhere and does not. It is
  `cc_opus5`, N=5, 20 items nearest τ — the frontier **reference-arm** wobble
  sweep. Cancelled rather than defined, because the `cc_*` set is KILLed: there
  is no reference arm left to characterise, and nothing depends on it.
- **Run B promoted to blocking W4**, in the ticket, in the checkbox, in the
  "limit" paragraph, in the W4 row of the workstream table, and in SPEC §9:
  - it is the **only** source for Jev's flip band — Run A measured `cc_haiku45`,
    the wrong arm, and there is still **no determinism baseline for `jev` at
    all**;
  - under a *rework* goal a flip means the same task gets a different tier on
    retry, and with RESTART-on-escalation that is the same work paid for twice —
    the router would manufacture the exact failure the project exists to reduce;
  - it is ~$0.018 and ~12 minutes of offline replay, and blocks nothing.

  Without it, a W4 "win" could be a win or could be noise re-rolled until it
  looked like one.

### Three tickets re-verdicted REPURPOSE → KILL

Same reason in all three, and it is worth naming because it will recur:
**the repurposed value had already shipped.** REPURPOSE means there is work left
to redirect; when there is not, it leaves a shipped thing on the board looking
unbuilt.

- **JEV-09** — `hooks/inline_shadow_bash.sh` is the ancestor of W1's
  `agent_route_actuator.sh` (byte-identical state, exit-0-on-every-path, hard
  timeout, `-e`-or-`-L` switch test). W1 shipped. What the ticket still *asks
  for* is registering a synchronous Jev gate on `pre_bash` — the mechanism SPEC
  §2c refutes. Carried forward, so it is not lost: the default `--max-time 2.0s`
  sits **below Jev's 2,681ms p99**, turning the top 1–3% of the tail into silent
  attrition. That is a live hazard for **W4's** router call.
- **JEV-23** — 19 boxes. Counted: the mechanism, the `updatedInput` echo, the
  `resolvedModel` assertion, transcript-sourced outcomes and the
  `JEV_ARM_SUBPROCESS` guard are **W1**; the blinded grader is **W3**; the coin
  flip, `routing_arm` fields, `random_matched`, ITT/clustering, co-primaries and
  the stopping rule are **cancelled with the A/B**. Its sharpest box —
  *"report agreement between Jev's assignment and a static rule; if Jev agrees
  with two lines of `if`, the classifier is adding nothing"* — was **promoted to
  W4's entire ship gate**. Nothing left that is both live and unbuilt.
- **JEV-46** — the inversion **is** `config/tiers.json`; all five remaining boxes
  are `random_matched` (implement it, freeze its mix from `jev_routed`'s realised
  distribution, record the seed, amend the pre-registration, write it into the
  writeup) and every one is dead. Two arguments it made that the product still
  relies on are called out: the 65% degeneracy as a **coverage ceiling** rather
  than a refutation, and that **liteLLM's 46% does not port** to a surface that
  decides once at delegation time.

**Two machine-readability traps caught while doing this**, both the same shape —
a strikethrough that still parses as the thing it strikes out:

1. **The verdict line.** Formatted `— KILL.` with the history in a following
   italic, so `test_board.py`'s `PIVOT TRIAGE … — (\w+)` regex parses it. A
   `~~REPURPOSE~~ → KILL` form made all three tickets **invisible** to the test,
   silently weakening the "no live ticket is blocked by a dead one" guard.
2. **JEV-46's `Status:` line.** My first version was
   `Status: ~~ready-for-agent~~ **killed 2026-09-21** — …`. `STATUS_RE` captures
   the whole line, so that still machine-reads as **ready-for-agent** — a killed
   ticket advertising itself as workable, the exact outcome the re-verdict
   exists to prevent. Now `Status: blocked` (matching JEV-09 and JEV-53), with
   the history in prose below and a note on why it is not struck through.

Checked after both fixes: every dependent on a newly-killed ticket
(JEV-23→46, JEV-27→46, JEV-53→23) is itself KILLed, so nothing is left stuck.

### JEV-32 — its enforcement is now unowned (added on the coordinator's relay)

`src/analyze.py` was deleted this wave and took
`tests/test_analyze_config_join.py` (7 tests) with it. **Those were the only
enforcement anywhere of JEV-32's invariant — *never compare two policy versions
as if they were one*.** JEV-32 is REPURPOSE, not KILL: only the implementation
died, and `Status: done` refers to the original `analyze.py` defect, not to the
principle being protected.

Recorded on the ticket, with the obvious re-pin named: **JEV-57's assignment
ledger**, which already refuses to pool across repos (`ProjectsWouldBePooled`) —
a sibling of the same rule. This gets *more* urgent under the corrected goal,
not less: the ledger spans every repo `jev` is installed in, and pooling two
policy versions or two repos is **a confound that looks like a result** — a
tier-map change and a second project arriving are both invisible in a pooled
before/after and both move the number. W5 exists to produce the first "after";
this rule decides whether that "after" means anything.

A breadcrumb comment was left at the removal site in `tests/run_all.sh` — the
right place for a breadcrumb, the wrong place to track work.

### Header

Triage tally 13/17 → **10/20**. Heading-count note corrected: 58 headings carry
a verdict, but the board now has **63** — JEV-57–61 are post-pivot and correctly
carry no triage line.

---

## .scratch/pivot/w3-accuracy-gate.md

The **two-taus error**. It read *"`destructive` fires on ~5% of units,
`needs_review` on about half"*, taking its two figures at two different τ:

| question | τ | fires on |
|---|---|---|
| `destructive` | **0.36** | **5.6%** |
| `needs_review` | **0.95** | **4.6%** |
| `needs_review` | 0.5 — *not this gate's τ* | 52.9% |

"Roughly half" is `needs_review` at **τ=0.5**, not at its own **τ=0.95**. At the
τ in play the two questions are **comparably rare**, not 10× apart. The source
comment in `src/accuracy_gate.py` was fixed when this was found; this file was
missed.

Corrected with the table and a note that the argument is unaffected — the hole
pooling leaves does not need one question to be a majority, only for the
*untouched* question to carry the pooled score, which two equally-sized question
blocks (567 units each) do just as well. The trailing phrase "the untouched
**majority** question carries the score" was fixed too; "majority" was an
artefact of the mis-stated rates and was never the mechanism.

---

## Files changed

| file | |
|---|---|
| `SPEC.md` | §5 reconciled onto W0–W7; orphan P-rows removed, reasoning folded in; harvest ledger relabelled; `⏳` removed; §9 count discrepancy resolved; §11 window guard added; triage tally and `test_board.py` correction |
| `README.md` | `.env.example` note; install/uninstall/`JEV_HOME` section; three switches; isolation + self-containment updated; "Claim discipline" rewritten |
| `CONTEXT.md` | header; 8 entries corrected or retired; `shadow` verified against config and rewritten; operator decision 3; 11 terms added |
| `docs/PLAN.md` | freeze-header pointer repaired; correction-note convention; `:20` and `:509` annotated |
| `docs/REVERSIBILITY.md` | tier B "exactly" corrected to match `src/install.py` |
| `ISSUES.md` | JEV-52 (step 1, step 6, acceptance box, frozen inventory); JEV-16 (Run C cancelled, Run B promoted); JEV-09 / JEV-23 / JEV-46 re-verdicted; **JEV-32 enforcement gap logged**; W4 row; header tally; superseded-plan freeze figures |
| `.scratch/pivot/w3-accuracy-gate.md` | two-taus error corrected |
| **`.env.example`** | **new** — credentials-free template |
| `.scratch/pivot/w5-doc-sweep.md` | this report |

Nothing under `src/`, `hooks/`, `config/` or `tests/` was modified.

## Open, not mine to fix

1. **`.gitignore` needs `!.env.example`** (see above). Without it the new file is
   silently uncommittable and the README instruction stays broken on a fresh
   clone.
2. **JEV-16's wave membership is still `B1`** in the machine-readable wave table
   (the superseded A/B plan), while the promotion of Run B lives in prose and in
   the W4 row. `test_board.py` skips cross-scheme edges and exempts `done`
   tickets, so this passes — but if Run B is ever wanted as a *parsed* edge it
   needs a W-wave home.
3. **`data/baseline/sessions.jsonl` and `manifest.json`** still carry costs under
   the defective rule and are fingerprint-idempotent, so they will not
   self-correct — already logged in SPEC §11 "Open, needs a ticket" and as
   JEV-59.
4. **JEV-32's invariant has no enforcing test.** Logged on the ticket with the
   re-pin named (JEV-57's ledger), but re-pinning it means touching `src/` or
   `tests/`, which this pass may not do.
5. **Which of the two explanations for the 571 / 2,005 undercount is correct** —
   carried-forward figure, or a counting method that skipped replay — is stated
   as open. Resolving it means finding how that inventory was produced; the
   commit that recorded it is the place to look.
6. **`.env.example`'s footer note goes stale** the moment `!.env.example` is
   added to `.gitignore`. Trim it in the same commit.
