#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-43. Write the wall-clock decomposition report.

Not a second `analyze.py`. This script computes nothing about answers, labels,
agreement, cost or thresholds; it reports one thing -- how `cc_*` wall-clock
divides between the arm and the operator's machine -- and it exists because
that number has to be re-derivable on demand rather than pasted into a ticket
once.

    uv run src/latency_report.py            # writes reports/jev43-wallclock.{md,json}
    uv run src/latency_report.py --stdout   # prints the markdown instead

Era boundaries are passed in rather than inferred, because they are facts about
the collection window recorded in ISSUES.md, not properties of the rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyversion  # noqa: E402

pyversion.require()

import latency as L  # noqa: E402
import paths  # noqa: E402

# From ISSUES.md, "Both era boundaries in the collection window, in one place",
# plus the cc_haiku45 arm_config_id boundary that JEV-41's fix created.
ERA_FOUR_ARM = "2026-09-20T12:07:24"
ERA_CONCURRENT = "2026-09-20T14:24:13"
ERA_HAIKU_NOTHINK = "2026-09-20T15:15:49"


ATTRIBUTION = """## Where the second mode comes from — identified, not bounded

The 18.5-22.0s mode is the **`security-guidance` plugin's `Stop` hook**, which
is enabled in the operator's user-level settings and therefore loads inside
every `claude -p` the `cc_*` arms spawn.

The mechanism, read out of the plugin's own source and its own log:

1. On `Stop` the hook diffs the working tree and, when the diff is non-empty,
   runs an LLM code review over the changed files.
2. On this machine those review requests fail TLS certificate verification, so
   the hook burns a fixed retry ladder and gives up.
3. Its log prints the elapsed time itself. Over 309 recorded firings the
   printed value is 18.3s in 253 of them, with a short tail to 20.4s.

Four independent lines of evidence, none of which rests on the others:

- **The printed number matches.** Hook 18.3s + ~0.3s of subprocess overhead is
  the 18.5-18.8s band that holds 58 of the 67 rows, and the hook's own tail
  (19.3/19.7/20.4s) matches the rows' tail (19.5/19.8/21.5/21.9/22.0s).
- **The gap.** Zero rows between 1.24s and 18.53s. A contention or load tail
  fills in; a discrete subprocess does not.
- **Timing correlation, at decision grain.** `evaluated_at` is stamped after
  `_dispatch` returns, so it is per **decision**, not per row — every arm in a
  decision shares one value, and the test must be run at that grain or it
  double-counts. Restricted to the window the hook's log still covers and to
  `live` decisions: **20 of 20** contaminated decisions have a hook completion
  0.47-0.69s before the decision's `evaluated_at`, a tight one-sided offset,
  against **3 of 118** clean decisions (2.5%). Chance alone gives 1.6% at the
  observed event density, so the clean matches are the operator's own
  interactive session firing the same hook, and the contaminated ones are not
  consistent with anything else. Decisions with two contaminated arms show two
  completions in the preceding 4s, as they should. (The three `replay`
  decisions the JEV-16 sweep wrote are excluded: `replay.py` stamps
  `evaluated_at` per row, so the decision-grain alignment does not apply.)
- **It is inside Claude Code's clock.** `Stop` fires before the CLI emits its
  result JSON, so the cost lands in `duration_ms` and not in `duration_api_ms`
  — exactly the signature observed.

**Why only ~5% of rows, and why the rate is not a constant.** The hook returns
early on an empty diff. It only pays the 18.3s when the arm's `cwd` — this
repo — had uncommitted changes at that instant. So the trigger is *the
operator editing the repo*, not anything about the arm, the model or the
decision. The measured hourly rate over the window runs from 0% to 35%. Any
figure quoted as "the contamination rate" is a statement about how busy the
operator was, and does not forecast a future window.

**Two caveats on the magnitude.** First, 18.3s is contingent on a broken
certificate chain: with working TLS the same hook would make a real LLM call —
variable latency, and the operator's plugin would be spending API budget inside
every arm subprocess. Fix the certificate and the signature changes; it does
not go away. Second, the hook is declared `asyncRewake: true`, i.e. its author
intended it to be non-blocking. In `claude -p` it blocks. That is worth knowing
before anyone concludes "no hook can affect a print-mode run".

**Provenance note.** The hook's log only reaches back to 14:44Z. The 42
contaminated rows before that are attributed by signature identity — the same
discrete band, the same gap, the same absence from `duration_api_ms` — not by
correlation. Only derived counts and durations were taken from outside this
repo; no third-party log content was copied in."""


DECISION = """## Which number is publishable

`raw.duration_api_ms` is the only clean clock on a `cc_*` row, and it is the
one that is actually comparable with `jev` — both are a single HTTP round trip
to a model. It is the primary latency quantity. But A5.3 commits to reporting
spawn, and `api_ms` excludes it, so it cannot be the only one.

The decision:

1. **Primary: `api_ms`, per `(arm, arm_config_id, arm_dispatch, run_context)`.**
   Uncontaminated by construction. Compare against `jev`'s `total_ms`.
2. **Co-primary wall-clock: `total_ms` over clean rows only**, with the
   contaminated rows dropped and `n` dropped stated in every table. Dropping is
   unbiased *here* because the trigger is the operator's repo state, which is
   independent of the decision being classified and of the arm — the one thing
   it is not independent of is wall-clock time of day, so any time-sliced
   comparison must re-check the rate rather than inherit this one.
3. **Never publish a pooled `cc_*` `total_ms`.** It mixes three eras and one
   machine artefact.

**No intervals.** The live corpus is 1,783 rows across exactly one
`session_id`, and `PREREGISTRATION.md` A1.1 makes fewer than 30 clusters
inconclusive by rule. Everything here is a quantile, a count or a distribution
shape — a description of this corpus, not an inference about a population. No
confidence interval or p-value is quoted, and none should be read in.

**On the arm-set era.** The three-arm/four-arm boundary does not need a
separate key for these clocks: within the serial era the two cohorts give spawn
p50 1089ms vs 1083ms and in-session p50 292ms vs 284ms. `arm_dispatch` subsumes
it, and `concurrent_arms` is exactly collinear with `arm_dispatch`.

`adjusted_total_ms` (subtract the excess over the arm's clean in-session
baseline, keep the row) exists for one job: propagating the correction into
per-decision quantities like `dispatch_wall_ms`, where dropping a row would
drop the whole decision. It is not the published per-arm number.

### What is NOT removed, and the bound on it

Removing the second mode does not make the remainder clean. Two residues stay,
and neither is separable from a row:

- **In-session, clean mode.** The operator has at least four `SessionStart`
  hooks registered that fire in every arm subprocess. They are fast, so they
  sit inside the clean mode alongside Claude Code's own preamble and the tool
  round trip, and nothing on the row distinguishes them. The **ceiling** on
  this residue is the whole clean `in_session_ms` distribution: p50 0.28-0.35s,
  p95 0.39-0.62s across every group. So: **at most ~0.6s per row at p95**, and
  in practice less, because the preamble and tool round trip are genuinely the
  arm's.
- **Spawn.** `spawn_ms` (p50 1.08s serial, 1.26s concurrent) covers our own
  fork/exec and Node startup — the study's — but also Claude Code loading the
  operator's settings, marketplace list and plugin manifests, which happens
  before Claude Code starts its own clock. Unresolvable from rows. **Bound the
  whole of it at ~1.1-1.3s per row** and disclose that an unknown fraction is
  environmental. The serial-to-concurrent difference, ~0.18s, is contention and
  is the quantity A5.3 asked to be measured rather than asserted; it is
  computed on `total_ms - duration_ms` and so is untouched by the hook.

### Can the arm suppress the hooks?

Note first what would **not** work. The hook is **plugin-registered**, through
`enabledPlugins` in the operator's user settings; the `hooks` block in those
settings is already empty. A `--settings` override supplying an empty `hooks`
map — the obvious move, and the one that mirrors the `--strict-mcp-config
'{"mcpServers":{}}'` the arm already passes — would change nothing. That is the
same wrong turn the earlier MCP diagnosis took.

The flag that does reach it is **`--bare`**, documented by the installed CLI as
"Minimal mode: skip hooks, LSP, plugin sync, attribution, auto-memory,
background prefetches, keychain reads, and CLAUDE.md auto-discovery" (read from
`claude --help`; zero spend). It is **not** proposed, for two concrete reasons
on top of the one the ticket names:

1. **It would change the arm's auth model.** `--bare` makes Anthropic auth
   "strictly `ANTHROPIC_API_KEY` or `apiKeyHelper`". `src/arms/claude_cli.py`
   does the opposite on purpose — it *pops* `ANTHROPIC_API_KEY` to force
   subscription auth. Adopting `--bare` would silently move which credential,
   and therefore which billing surface, the arm measures.
2. **It suppresses far more than the hook.** Skipping LSP, auto-memory,
   prefetches and CLAUDE.md discovery makes the arm much less representative of
   Claude Code as deployed — which is the whole reason a `cc_*` arm shells out
   to the real CLI instead of calling the API directly.

So the trade-off the ticket anticipated is real, and sharper than expected: the
only lever that reaches this hook is a blunt one. The chosen
answer is to measure the contamination, remove the identified mode, and bound
the rest — which is what this report does. `src/arms/claude_cli.py` is
untouched.
"""


MOVES = """## Which published numbers move

| claim | where | was | is | verdict |
|---|---|---|---|---|
| serial sum per capture | JEV-33 | 20.1s | **19.7s** | survives — a sum of medians; the mode is too rare per arm to reach a median |
| per-arm serial medians | JEV-33, JEV-41 | 0.57 / 2.9 / 4.9 / 11.6s | 0.57 / 2.87 / 4.98 / 11.26s | survive, medians move by <0.15s |
| concurrent `dispatch_wall_ms` | JEV-33 | 16.5s | **9.7s** | **does not survive** |
| "realised gain 20.1s -> 16.5s, ~1.2x" | JEV-33 | 1.2x | **~2.0x** | **restate** |
| "the ~6s above the slowest-arm floor is contention" | JEV-33 | ~6s contention | **~0.2s** | **withdraw** |
| "wall-minus-API ~3.5s Haiku vs ~1.4s Opus" | JEV-41 | 3.5 / 1.4s | **1.41 / 1.52s** | **withdraw the ordering** |
| Haiku median API / wall | JEV-41 | 8.1s / 11.6s (n=335) | 10.13s / 11.55s clean (n=401, v1) | survives — see note |
| ~170ms spawn contention | A5.3 prep | ~170ms | **~180ms** | survives — computed on `total_ms - duration_ms`, which excludes the hook |
| jev sequential vs concurrent null | A5.3 prep | 565.7 vs 564.6ms | unchanged | survives — `jev` spawns nothing and cannot be contaminated |

**JEV-33's 16.5s.** It was measured over the first 17 concurrent decisions.
**7 of those 17** contain a contaminated arm — a 41% rate against 5% over the
corpus, because that sample sits inside the busiest editing burst of the day.
A per-decision wall is a max over arms, so one contaminated arm carries the
whole decision. Adjusted, the median is 9.7s; over the 116 concurrent decisions
before the `cc_haiku45` config boundary it is 9.4s. Both are well inside the
slowest arm's own latency, which is the substantive correction: **the wall sits
at the slowest arm, and the "~6s of contention" above it was the operator's
hook.** The contention that genuinely exists is the ~0.2s of extra spawn time
in the table above, not 6s. The realised gain restates as **19.7s -> ~9.7s,
about 2.0x**.

Two cautions on that restatement. n=17 is small and `cc_haiku45`'s API time is
heavy-tailed, so quote it with the n. And the full concurrent era must not be
pooled for this purpose: `cc_haiku45` changed `arm_config_id` at 15:15:49Z and
got much faster, so the 235-decision figure (6.9s) is measuring JEV-41's fix as
much as concurrency.

**On Haiku's medians.** JEV-41 printed 8.1s median API and 11.6s median wall
at n=335. Those are not directly comparable to anything here: the corpus has
since grown and `cc_haiku45` crossed an `arm_config_id` boundary. The only
question this ticket answers is how much of the difference is contamination,
and the answer is **at most ~0.5s**: on `cc-haiku45-cli-v1` the median API time
moves 10.45s -> 10.13s and median wall 12.23s -> 11.55s when the mode is
removed. Everything else is corpus growth and the config boundary. Haiku's
medians are safe to quote once the cut is stated.

**JEV-41's wall-minus-API gap.** It was a **mean**, and Haiku had the highest
contamination rate, so the mode moved it hardest. Clean, the gap is
`cc_haiku45` 1.41s vs `cc_opus5` 1.52s vs `cc_sonnet5` 1.59s — i.e. it is
**flat across arms**, as a fixed process-spawn cost should be. JEV-41 used the
gap to argue that spawn does not explain Haiku's slowness. That conclusion is
**right, and now much better supported**: the gap is not 2.5x larger for Haiku,
it is very slightly smaller. The two root causes JEV-41 found (fixed thinking
budget, no cache reads) are untouched by this ticket, and the headline that the
cheap tier was the slow tier stands."""


def _ms(v):
    return None if v is None else round(v, 1)


def _s(v):
    return "--" if v is None else f"{v / 1000:.2f}s"


def build(rows: list[dict]) -> dict:
    live = [r for r in rows if r.get("run_context") == "live"]
    baselines = L.clean_baselines(rows)
    cc_ok = [r for r in rows if L.is_cc(r) and r.get("ok")]
    residuals = [L.decompose(r).in_session_ms for r in cc_ok]
    gap = L.empirical_gap(residuals)
    n_dirty = sum(1 for v in residuals if L.is_contaminated(v))

    groups = L.summarise(rows)

    # --- JEV-33's serial-era per-arm medians and their sum -------------------
    serial4 = [r for r in live if ERA_FOUR_ARM <= r["evaluated_at"] < ERA_CONCURRENT]
    serial = {}
    sum_raw = sum_clean = 0.0
    for arm in sorted({r["arm"] for r in serial4}):
        sel = [r for r in serial4
               if r["arm"] == arm and r.get("ok")
               and (r.get("timing_ms") or {}).get("total_ms") is not None]
        raw = [r["timing_ms"]["total_ms"] for r in sel]
        clean = [r["timing_ms"]["total_ms"] for r in sel
                 if not L.is_cc(r)
                 or not L.is_contaminated(L.decompose(r).in_session_ms)]
        serial[arm] = {"n": len(raw), "median_raw_ms": _ms(L.quantile(raw, 0.5)),
                       "n_clean": len(clean),
                       "median_clean_ms": _ms(L.quantile(clean, 0.5))}
        sum_raw += L.quantile(raw, 0.5)
        sum_clean += L.quantile(clean, 0.5)

    # --- JEV-33's concurrent figure, on the sample it was computed from ------
    conc = [r for r in live if r["evaluated_at"] >= ERA_CONCURRENT]
    by_dec = sorted({r["decision_id"]: r["evaluated_at"] for r in conc}.items(),
                    key=lambda kv: kv[1])

    def wall_block(sel):
        raw = L.dispatch_walls(sel, baselines, adjusted=False)
        adj = L.dispatch_walls(sel, baselines, adjusted=True)
        dirty = {r["decision_id"] for r in sel
                 if L.is_cc(r) and r.get("ok")
                 and L.is_contaminated(L.decompose(r).in_session_ms)}
        clean = [v for k, v in raw.items() if k not in dirty]
        return {
            "n_decisions": len(raw),
            "median_raw_ms": _ms(L.quantile(list(raw.values()), 0.5)),
            "median_adjusted_ms": _ms(L.quantile(list(adj.values()), 0.5)),
            "n_contaminated_decisions": len(dirty),
            "n_clean_decisions": len(clean),
            "median_clean_only_ms": _ms(L.quantile(clean, 0.5)),
        }

    first17 = {k for k, _ in by_dec[:17]}
    walls = {
        "jev33_first_17_concurrent_decisions":
            wall_block([r for r in conc if r["decision_id"] in first17]),
        "concurrent_era_haiku_v1_only":
            wall_block([r for r in conc
                        if r["evaluated_at"] < ERA_HAIKU_NOTHINK]),
        "concurrent_era_all_pools_haiku_config_boundary":
            wall_block(conc),
    }

    return {
        "ticket": "JEV-43",
        "source": "data/runs/2026-09-20.jsonl",
        "n_rows": len(rows),
        "n_cc_ok": len(cc_ok),
        "floor_ms": L.CONTAMINATION_FLOOR_MS,
        "contamination": {
            "n": n_dirty,
            "rate": n_dirty / len(cc_ok) if cc_ok else 0.0,
            "total_seconds_lost": round(
                sum(v for v in residuals if L.is_contaminated(v)) / 1000, 1),
            "gap_below_ms": _ms(gap.below),
            "gap_above_ms": _ms(gap.above),
            "gap_width_ms": _ms(gap.width_ms),
        },
        "clean_baseline_in_session_ms": {
            f"{k[0]}|{k[1]}": _ms(v) for k, v in sorted(baselines.items())},
        "groups": [
            {**g, "key": f"{k[0]}|{k[1]}|{k[2]}|{k[3]}"}
            for k, g in sorted(groups.items(),
                               key=lambda kv: (kv[0][3], kv[0][0], kv[0][1],
                                               str(kv[0][2])))
        ],
        "jev33_serial_sum": {
            "per_arm": serial,
            "sum_raw_ms": _ms(sum_raw),
            "sum_clean_ms": _ms(sum_clean),
        },
        "jev33_dispatch_wall": walls,
    }


def render(d: dict) -> str:
    c = d["contamination"]
    out: list[str] = []
    w = out.append
    w("# JEV-43 — `cc_*` wall-clock, decomposed")
    w("")
    w(f"Generated by `src/latency_report.py` from `{d['source']}` "
      f"({d['n_rows']} rows, {d['n_cc_ok']} successful `cc_*` rows).")
    w("Derived numbers only. Nothing here is copied from outside the repo.")
    w("")
    w("## The three clocks")
    w("")
    w("```")
    w("total_ms      = spawn_ms + in_session_ms + api_ms      (exactly, by construction)")
    w("spawn_ms      = total_ms - raw.duration_ms             fork/exec, Node + CLI boot, teardown")
    w("in_session_ms = raw.duration_ms - raw.duration_api_ms  preamble, tool round trip, OPERATOR HOOKS")
    w("api_ms        = raw.duration_api_ms                    the model call. clean.")
    w("```")
    w("")
    w("## The contamination")
    w("")
    w(f"- **{c['n']} of {d['n_cc_ok']}** successful `cc_*` rows ({c['rate'] * 100:.2f}%) "
      f"carry a second-mode in-session residual, totalling **{c['total_seconds_lost']}s**.")
    w(f"- The classifier cuts inside an empty interval: largest clean residual "
      f"**{_s(c['gap_below_ms'])}**, smallest contaminated residual **{_s(c['gap_above_ms'])}**, "
      f"width **{_s(c['gap_width_ms'])}**, zero rows in between.")
    w(f"- Any floor inside that interval gives identical classification "
      f"(asserted in `tests/test_latency.py`). The one used is "
      f"{L.CONTAMINATION_FLOOR_MS / 1000:.0f}s.")
    w("")
    w(ATTRIBUTION)
    w("")
    w("## Per arm, per config, per dispatch era")
    w("")
    w("Never pooled across `arm_config_id` (two `cc_haiku45` configurations), "
      "`arm_dispatch` (spawn contention differs) or `run_context` "
      "(`data/runs/` is shared and append-only; the JEV-16 determinism sweep "
      "writes `replay` rows into the same file).")
    w("")
    w("| context | arm | arm_config_id | dispatch | n | contam | rate | clean total p50 | clean total p95 | api p50 | spawn p50 | clean in-session p50 | clean in-session p95 |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for g in d["groups"]:
        w(f"| {g['run_context']} | `{g['arm']}` | `{g['arm_config_id']}` "
          f"| {g['arm_dispatch'] or 'serial'} "
          f"| {g['n']} | {g['n_contaminated']} | {g['contamination_rate'] * 100:.1f}% "
          f"| {_s(g['clean_total_ms']['p50'])} | {_s(g['clean_total_ms']['p95'])} "
          f"| {_s(g['api_ms']['p50'])} | {_s(g['spawn_ms']['p50'])} "
          f"| {_s(g['clean_in_session_ms']['p50'])} | {_s(g['clean_in_session_ms']['p95'])} |")
    w("")
    w("## JEV-33's serial sum")
    w("")
    w("| arm | n | median (raw) | n clean | median (clean) |")
    w("|---|---|---|---|---|")
    for arm, v in d["jev33_serial_sum"]["per_arm"].items():
        w(f"| `{arm}` | {v['n']} | {_s(v['median_raw_ms'])} | {v['n_clean']} "
          f"| {_s(v['median_clean_ms'])} |")
    w(f"| **serial sum** | | **{_s(d['jev33_serial_sum']['sum_raw_ms'])}** | "
      f"| **{_s(d['jev33_serial_sum']['sum_clean_ms'])}** |")
    w("")
    w("A sum of medians barely moves: the contaminated mode is rare enough per arm "
      "that it cannot reach the median. This number survives.")
    w("")
    w("## JEV-33's concurrent `dispatch_wall_ms`")
    w("")
    w("A per-decision wall is the **max** over arms, so one contaminated arm "
      "inflates the whole decision. This number does not survive.")
    w("")
    w("| sample | decisions | raw median | adjusted median | contaminated decisions | clean-only median (n) |")
    w("|---|---|---|---|---|---|")
    for name, v in d["jev33_dispatch_wall"].items():
        w(f"| {name} | {v['n_decisions']} | {_s(v['median_raw_ms'])} "
          f"| {_s(v['median_adjusted_ms'])} | {v['n_contaminated_decisions']} "
          f"| {_s(v['median_clean_only_ms'])} ({v['n_clean_decisions']}) |")
    w("")
    w("")
    w(MOVES)
    w("")
    w(DECISION)
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=str(paths.RUNS / "2026-09-20.jsonl"))
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args(argv)

    data = build(L.load_rows(args.runs))
    md = render(data)
    if args.stdout:
        sys.stdout.write(md)
        return 0
    paths.REPORTS.mkdir(parents=True, exist_ok=True)
    (paths.REPORTS / "jev43-wallclock.json").write_text(
        json.dumps(data, indent=2) + "\n")
    (paths.REPORTS / "jev43-wallclock.md").write_text(md)
    print(f"wrote {paths.REPORTS / 'jev43-wallclock.md'}")
    print(f"wrote {paths.REPORTS / 'jev43-wallclock.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
