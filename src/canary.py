#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The daily drift canary: the same bytes, to the same arm, forever.

User story 23 and the risk table both register this instrument -- "vendor model
drift mid-collection -> daily canary over ~20 fixed states" -- and `run_context:
"canary"` has been a declared value in `replay.py`, in PREREGISTRATION section 4
and in the row schema since before the first live capture. Nothing ever wrote
one. This is that writer.

**What it is for.** A collection window that spans weeks sits on an assumption
nobody can check from the inside: that the model behind an arm did not change
under it. If it did, every cross-day comparison in the study silently pools two
different models, and no agreement statistic can reveal that -- the numbers
stay well-formed while meaning something else. The only defence is to keep
re-sending a *fixed* input and watch the output, which makes drift a difference
you can see rather than a variance you average in.

**Why the set is frozen to a file rather than re-selected.** A canary whose
states are re-chosen each day measures the selection, not the vendor. So the
set is chosen once, deterministically, from the synthetic stress set, and
written to `data/fixtures/canary-set-v1.json` with the exact state *bytes* in
it. Every later sweep sends those bytes -- it does not rebuild them from the
payload, because the state builder is versioned code and a builder change would
otherwise look exactly like vendor drift. If the builder does change, the sweep
says so and keeps sending the frozen bytes.

`canary_set_id` is derived from the content of the set (`canary-set-v1:<hash of
the sorted state hashes>`), so a hand-edited fixture cannot masquerade as the
original, and deliberately rebaselining is a fixture-version bump -- which
yields a new id and therefore a new reference sweep, rather than quietly moving
the thing the comparison is against.

**Jev only by default.** A sweep is ~20 states x 1 arm and costs about half a
cent. The `cc_*` arms are subscription calls at ~21s each, so a daily cc_opus5
canary would cost more quota than the experiment it protects. `--arms` overrides
it for the day you want a wider check.

**What it refuses to do.** It never reports "no drift" on absent data. With no
prior sweep on disk it records the baseline and exits **2**, in the same spirit
as `determinism.py` exiting 1 when the flip rate is unmeasured: a green exit
code from a cron wrapper must mean "checked and clean", never "had nothing to
check".

Exit codes, so a wrapper can act on them:

    0   reference exists, today's sweep matches it within tolerance
    1   DRIFT FLAGGED -- model string changed, mean |delta| over threshold,
        or a decision flipped at tau
    2   no usable reference sweep; today's sweep was recorded as the baseline
    3   today's sweep is incomplete -- failed or missing rows. Not a comparison.
    4   JITTER ONLY -- no hard flag, but at least one state crossed tau while
        staying inside the jitter band. Not drift; not clean either. A wrapper
        must handle this distinctly or it will read a tau-band flip as success.

Usage:
    uv run src/canary.py                      # daily: jev, sweep then compare
    uv run src/canary.py --arms jev,cc_opus5  # wider check, costs subscription quota
    uv run src/canary.py --report-only        # compare what is on disk, call nothing
    uv run src/canary.py --freeze-only        # create the fixture and stop
    uv run src/canary.py --out canary.txt     # also write reports/canary.txt
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_loader as cl  # noqa: E402
import paths  # noqa: E402
import replay  # noqa: E402
import state_builders as sb  # noqa: E402
import store  # noqa: E402
from arms.base import ArmConfig  # noqa: E402

# The fixture version is the rebaseline lever and the ONLY one. There is no
# --rebaseline flag on purpose: silently moving the reference is the single
# failure mode that would turn this instrument into decoration.
FIXTURE_VERSION = "v1"

# 7 per stratum x 3 strata = 21. "~20 fixed states" as registered, chosen as an
# exact multiple of the strata so the set is balanced by construction rather
# than by a remainder rule.
N_PER_STRATUM = 7

DEFAULT_TAU = 0.5
DEFAULT_MEAN_DELTA = 0.05     # mean |delta| above this flags drift
JITTER = 0.05                 # |p_ref - tau| below which a flip may be wobble

EXIT_CLEAN = 0
EXIT_DRIFT = 1
EXIT_NO_REFERENCE = 2
EXIT_INCOMPLETE = 3
EXIT_JITTER_ONLY = 4


# --------------------------------------------------------------------------
# the frozen set
# --------------------------------------------------------------------------

def fixture_path() -> Path:
    return paths.FIXTURES / f"canary-set-{FIXTURE_VERSION}.json"


def _set_id(state_shas: Sequence[str]) -> str:
    """Content-derived, so the id cannot survive an edit to the set."""
    digest = sb.sha256(json.dumps(sorted(state_shas), separators=(",", ":")))
    return f"canary-set-{FIXTURE_VERSION}:{digest[:12]}"


def _dedupe_key(surface: str, payload: dict[str, Any]) -> str:
    """What counts as 'the same item' for diversity purposes.

    The synthetic file is command-major -- each command appears once per context
    -- so an unfiltered head-of-list slice would spend a third of the canary
    re-asking about `rm -rf /` in three directories. Same reasoning as
    `replay.stratified_sample`, different mechanism: that one shuffles, this one
    must not.
    """
    if surface == "pre_bash":
        return (payload.get("tool_input") or {}).get("command", "")
    return json.dumps(payload, sort_keys=True)


def select(items: Sequence[dict[str, Any]], surface: str,
           n_per_stratum: int = N_PER_STRATUM) -> list[dict[str, Any]]:
    """Pick the fixed set. Deterministic, stable, and not random.

    Sorted by `state_sha256` rather than by file order or by a seeded shuffle.
    A seed is only as stable as the code that consumes it -- `random.Random`'s
    stream is a Python implementation detail and `stratified_sample` would
    return a different set the day its loop changed. A content hash is a
    property of the bytes and nothing else, which is the whole requirement here.
    """
    by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        state = sb.build(surface, item["payload"])
        by_stratum[item["stratum"]].append({
            "synthetic_id": item["synthetic_id"],
            "stratum": item["stratum"],
            "session_id": item["payload"].get("session_id", ""),
            "state_sha256": sb.sha256(state),
            "state": state,
            "payload": item["payload"],
            "_dedupe": _dedupe_key(surface, item["payload"]),
        })

    picked: list[dict[str, Any]] = []
    for stratum in sorted(by_stratum):
        seen: set[str] = set()
        for entry in sorted(by_stratum[stratum], key=lambda e: e["state_sha256"]):
            if entry["_dedupe"] in seen:
                continue
            seen.add(entry["_dedupe"])
            picked.append({k: v for k, v in entry.items() if k != "_dedupe"})
            if len(seen) >= n_per_stratum:
                break
    return picked


def freeze(surface: str) -> dict[str, Any]:
    """Create the fixture once. Never overwrites an existing one."""
    source = paths.DATA / "synthetic" / f"{surface}-v1.jsonl"
    if not source.exists():
        raise FileNotFoundError(
            f"no synthetic set at {source}; run src/make_synthetic.py first")
    raw = source.read_text(encoding="utf-8")
    items = [json.loads(line) for line in raw.splitlines() if line.strip()]
    states = select(items, surface)

    fixture = {
        "canary_set_id": _set_id([s["state_sha256"] for s in states]),
        "fixture_version": FIXTURE_VERSION,
        "surface": surface,
        "created_at": store.utcnow(),
        "source_file": str(source.relative_to(paths.ROOT)),
        "source_sha256": sb.sha256(raw),
        "state_builder_version": sb.STATE_BUILDER_VERSION,
        "n_per_stratum": N_PER_STRATUM,
        "selection_rule": (
            "per stratum, sorted ascending by state_sha256, keeping the first "
            f"entry for each distinct command, take {N_PER_STRATUM}"
        ),
        "_comment": (
            "The exact bytes re-sent on every canary sweep. `state` is "
            "authoritative; `payload` is kept only so the selection can be "
            "audited and re-derived. Re-selecting from the payload is NOT how "
            "a sweep works -- a state_builders change would then be "
            "indistinguishable from vendor drift."
        ),
        "states": states,
    }
    paths.FIXTURES.mkdir(parents=True, exist_ok=True)
    path = fixture_path()
    path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
    return fixture


def load_or_freeze(surface: str) -> tuple[dict[str, Any], bool]:
    """Return (fixture, was_created). Verifies the id against the content."""
    path = fixture_path()
    if not path.exists():
        return freeze(surface), True

    fixture = json.loads(path.read_text(encoding="utf-8"))
    recomputed = _set_id([s["state_sha256"] for s in fixture["states"]])
    if recomputed != fixture["canary_set_id"]:
        raise ValueError(
            f"{path} has been edited: it claims {fixture['canary_set_id']} but its "
            f"contents hash to {recomputed}. Every sweep ever recorded under the old "
            f"id compared different bytes. Restore the file from the selection rule, "
            f"or bump FIXTURE_VERSION to rebaseline deliberately."
        )
    if fixture["surface"] != surface:
        raise ValueError(
            f"{path} is frozen for surface '{fixture['surface']}', not '{surface}'. "
            f"Bump FIXTURE_VERSION rather than repointing an existing set."
        )
    return fixture, False


# --------------------------------------------------------------------------
# the sweep
# --------------------------------------------------------------------------

def run_sweep(fixture: dict[str, Any], arms: list[ArmConfig],
              rng: random.Random) -> tuple[str, list[str]]:
    """Send the frozen bytes to every arm. Returns (canary_sweep_id, warnings).

    Row writing goes through `replay._emit`, deliberately, rather than through a
    copy of it. That function is the single path by which a non-live row reaches
    `data/runs/`, so a canary row is schema-identical to a synthetic or replay
    row by construction -- and if the row schema changes, it changes here too
    instead of drifting apart from it.
    """
    surface = fixture["surface"]
    questions = cl.questions_for(surface)
    qsid = cl.question_set_id(surface)
    sweep_id = store.ulid()
    warnings: list[str] = []

    if fixture["state_builder_version"] != sb.STATE_BUILDER_VERSION:
        warnings.append(
            f"state builder is {sb.STATE_BUILDER_VERSION}, fixture was frozen under "
            f"{fixture['state_builder_version']}. The FROZEN BYTES are being sent, "
            f"which is correct -- but any comparison against a pre-change sweep is "
            f"still a comparison of the vendor only if the builder change did not "
            f"alter these states. Rebuilt-hash check below says whether it did."
        )

    known = {c.get("decision_id") for c in store.captures()}
    for entry in fixture["states"]:
        state = entry["state"]
        if sb.sha256(state) != entry["state_sha256"]:
            raise ValueError(
                f"{entry['synthetic_id']}: stored state does not hash to its recorded "
                f"state_sha256. The fixture is corrupt; do not compare against it.")
        rebuilt = sb.sha256(sb.build(surface, entry["payload"]))
        if rebuilt != entry["state_sha256"]:
            warnings.append(
                f"{entry['synthetic_id']}: rebuilding from payload now yields "
                f"{rebuilt[:12]}, not {entry['state_sha256'][:12]}. The builder changed "
                f"this state. Frozen bytes sent regardless.")

        decision_id = f"can-{entry['synthetic_id']}"
        if decision_id not in known:
            # Written once, on the first sweep. A capture is an immutable
            # decision point; the canary re-evaluates one daily, it does not
            # observe a new one each day.
            store.append_capture({
                "decision_id": decision_id,
                "picked_at": store.utcnow(),
                "surface": surface,
                "session_id": entry["session_id"],
                "state_sha256": entry["state_sha256"],
                "state_chars": len(state),
                "state_builder_version": fixture["state_builder_version"],
                "state_source": sb.STATE_SOURCE[surface],
                "run_context": "canary",
                "stratum": entry["stratum"],
                "canary_set_id": fixture["canary_set_id"],
                "is_sidechain": False,
            })
            known.add(decision_id)

        replay._emit(
            decision_id=decision_id, surface=surface,
            session_id=entry["session_id"], state=state,
            questions=questions, qsid=qsid, arms=arms,
            run_context="canary", rng=rng,
            extra={
                # `sweep` is read by determinism.py, which skips any row whose
                # sweep is set and is not "determinism". That is exactly right:
                # canary repeats are separated by a day and by a possible model
                # change, so pooling them into an incidental-repeat flip rate
                # would confound wobble with drift.
                "sweep": "canary",
                "canary_set_id": fixture["canary_set_id"],
                "canary_sweep_id": sweep_id,
                "stratum": entry["stratum"],
            },
        )
    return sweep_id, warnings


# --------------------------------------------------------------------------
# comparison (pure)
# --------------------------------------------------------------------------

@dataclass
class Delta:
    decision_id: str
    stratum: str | None
    question: str
    p_ref: float
    p_cur: float

    @property
    def delta(self) -> float:
        return self.p_cur - self.p_ref

    def flipped(self, tau: float) -> bool:
        return (self.p_ref >= tau) != (self.p_cur >= tau)

    def near_tau(self, tau: float) -> bool:
        """Was the reference already sitting in the jitter band?

        PREREGISTRATION section 7 records that Jev is not bit-deterministic and
        FINDINGS 2.3 saw flips within 0.05 of tau on genuinely uncertain items.
        A third of this set is the `borderline` stratum, designed to live there.
        A single-shot canary CANNOT separate that wobble from vendor drift, so
        the flip is reported either way and this field is printed beside it.
        """
        return abs(self.p_ref - tau) < JITTER


@dataclass
class ArmReport:
    arm: str
    reference_sweep: str
    current_sweep: str
    reference_at: str
    current_at: str
    models_ref: list[str]
    models_cur: list[str]
    deltas: list[Delta] = field(default_factory=list)
    other_changed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def model_changed(self) -> bool:
        return self.models_ref != self.models_cur

    @property
    def mean_abs_delta(self) -> float:
        return (sum(abs(d.delta) for d in self.deltas) / len(self.deltas)
                if self.deltas else 0.0)

    @property
    def max_abs_delta(self) -> float:
        return max((abs(d.delta) for d in self.deltas), default=0.0)

    def flips(self, tau: float) -> list[Delta]:
        return [d for d in self.deltas if d.flipped(tau)]

    def hard_flags(self, tau: float, threshold: float) -> list[str]:
        """Flags that are NOT explained by ordinary run-to-run jitter at tau.

        The `borderline` stratum is *designed* to sit at tau, and
        PREREGISTRATION.md section 7 already records that Jev is not
        bit-deterministic -- it wobbles at sd~0.015 when uncertain. So "any
        decision flip at tau" fires on items built to sit exactly where flips
        are expected, and a wrapper that pages on it would page on non-drift,
        probably within days. A canary that cries wolf gets muted, and a muted
        canary is worse than none.

        So a flip is only a *hard* flag when the reference sat clear of the
        jitter band. Flips inside it still appear in the report, still print
        their distance from tau, and still produce a distinct exit code -- they
        are surfaced, never suppressed.
        """
        hard = [f for f in self.flags(tau, threshold) if not f.startswith("(c)")]
        clear = [d for d in self.flips(tau) if not d.near_tau(tau)]
        if clear:
            hard.append(f"(c) {len(clear)} decision flip(s) at tau={tau:.2f}, "
                        f"clear of the jitter band")
        return hard

    def jitter_flips(self, tau: float) -> list[Delta]:
        return [d for d in self.flips(tau) if d.near_tau(tau)]

    def flags(self, tau: float, threshold: float) -> list[str]:
        out: list[str] = []
        if self.model_changed:
            out.append(f"(a) response_model changed: {self.models_ref} -> {self.models_cur}")
        if self.mean_abs_delta > threshold:
            out.append(f"(b) mean |delta| {self.mean_abs_delta:.4f} > {threshold:.4f}")
        flips = self.flips(tau)
        if flips:
            out.append(f"(c) {len(flips)} decision flip(s) at tau={tau:.2f}")
        if self.other_changed:
            out.append(f"(d) {len(self.other_changed)} non-boolean answer(s) changed")
        return out


def _answers(rows: Sequence[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(r["decision_id"], q): a
            for r in rows for q, a in (r.get("answers") or {}).items()}


def compare(reference: Sequence[dict[str, Any]], current: Sequence[dict[str, Any]],
            arm: str) -> ArmReport:
    """Pure function over two lists of run rows. No I/O, no clock, no config."""
    ref_ok = [r for r in reference if r.get("ok")]
    cur_ok = [r for r in current if r.get("ok")]
    strata = {r["decision_id"]: r.get("stratum") for r in reference}

    report = ArmReport(
        arm=arm,
        reference_sweep=(reference[0].get("canary_sweep_id") if reference else ""),
        current_sweep=(current[0].get("canary_sweep_id") if current else ""),
        reference_at=min((r.get("evaluated_at") or "" for r in reference), default=""),
        current_at=min((r.get("evaluated_at") or "" for r in current), default=""),
        models_ref=sorted({r.get("response_model") or "?" for r in ref_ok}),
        models_cur=sorted({r.get("response_model") or "?" for r in cur_ok}),
        failed=sorted(r["decision_id"] for r in current if not r.get("ok")),
    )

    ref_answers = _answers(ref_ok)
    cur_answers = _answers(cur_ok)
    for key in sorted(ref_answers):
        decision_id, question = key
        a_ref = ref_answers[key]
        a_cur = cur_answers.get(key)
        if a_cur is None:
            report.missing.append(f"{decision_id}/{question}")
            continue
        if a_ref.get("type") == "boolean" and a_cur.get("type") == "boolean":
            report.deltas.append(Delta(
                decision_id, strata.get(decision_id), question,
                float(a_ref["probability"]), float(a_cur["probability"])))
        else:
            before = a_ref.get("choice", a_ref.get("score"))
            after = a_cur.get("choice", a_cur.get("score"))
            if before != after:
                report.other_changed.append(
                    f"{decision_id}/{question}: {before} -> {after}")
    return report


# --------------------------------------------------------------------------
# reading sweeps off disk
# --------------------------------------------------------------------------

def sweeps_for(canary_set_id: str, arm: str, expected: int
               ) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Every canary sweep on disk for one (set, arm), and the usable sweep ids.

    A sweep is *usable as a reference* only if every one of its rows succeeded
    and it covers the whole set. Otherwise a day-one credential failure would
    install a reference with no answers in it, against which nothing could ever
    drift -- a permanently green canary, which is worse than none.
    """
    by_sweep: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in store.runs():
        if (r.get("run_context") == "canary"
                and r.get("canary_set_id") == canary_set_id
                and r.get("arm") == arm):
            by_sweep[r.get("canary_sweep_id") or "?"].append(r)
    usable = sorted(sid for sid, rows in by_sweep.items()
                    if len(rows) == expected and all(r.get("ok") for r in rows))
    return dict(by_sweep), usable


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def render(fixture: dict[str, Any], reports: list[ArmReport],
           unbaselined: list[tuple[str, str]], incomplete: list[tuple[str, str]],
           warnings: Sequence[str], *, tau: float, threshold: float) -> str:
    L: list[str] = []
    L.append("=" * 78)
    L.append("DID THE MODEL CHANGE UNDER US?")
    L.append("=" * 78)
    L.append("")
    L.append("The same bytes, re-sent. A difference here is not a measurement of the")
    L.append("states -- they never change -- so it is a measurement of the vendor, the")
    L.append("arm's own run-to-run wobble, or both. Those two are separated by the")
    L.append("jitter column, not by this tool.")
    L.append("")
    L.append(f"canary_set_id : {fixture['canary_set_id']}")
    L.append(f"surface       : {fixture['surface']}   "
             f"states: {len(fixture['states'])}   frozen: {fixture['created_at']}")
    L.append(f"source        : {fixture['source_file']} @ {fixture['source_sha256'][:12]}")
    L.append(f"thresholds    : tau={tau:.2f}   mean |delta| > {threshold:.4f}")
    L.append("")

    for w in warnings:
        L.append(f"!! {w}")
    if warnings:
        L.append("")

    for arm, reason in incomplete:
        L.append("-" * 78)
        L.append(f"ARM {arm}   SWEEP INCOMPLETE")
        L.append("-" * 78)
        L.append(f"  {reason}")
        L.append("  This is attrition, not a clean comparison, and it is NOT reported as")
        L.append("  'no drift'. Fix the arm and re-run before reading anything into today.")
        L.append("")

    for arm, reason in unbaselined:
        L.append("-" * 78)
        L.append(f"ARM {arm}   NO REFERENCE SWEEP")
        L.append("-" * 78)
        L.append(f"  {reason}")
        L.append("  A canary's first sweep can only ever be a baseline: there is nothing")
        L.append("  to compare it against, so no drift statement is made and none should")
        L.append("  be inferred from the exit code. Run again tomorrow.")
        L.append("")

    for r in sorted(reports, key=lambda x: x.arm):
        L.append("-" * 78)
        L.append(f"ARM {r.arm}")
        L.append("-" * 78)
        L.append(f"  reference sweep {r.reference_sweep}  {r.reference_at}")
        L.append(f"  current   sweep {r.current_sweep}  {r.current_at}")
        L.append(f"  response_model  reference {r.models_ref}")
        L.append(f"                  current   {r.models_cur}")
        L.append("")
        if r.deltas:
            L.append(f"  {'state':<12} {'stratum':<12} {'question':<14} "
                     f"{'p_ref':>7} {'p_now':>7} {'delta':>8}  flag")
            for d in sorted(r.deltas, key=lambda x: -abs(x.delta)):
                flag = ""
                if d.flipped(tau):
                    flag = ("FLIP (within jitter of tau)" if d.near_tau(tau)
                            else "FLIP (clear of the jitter band)")
                L.append(f"  {d.decision_id:<12} {str(d.stratum):<12} {d.question:<14} "
                         f"{d.p_ref:>7.3f} {d.p_cur:>7.3f} {d.delta:>+8.3f}  {flag}")
            L.append("")
            L.append(f"  mean |delta| {r.mean_abs_delta:.4f}   "
                     f"max |delta| {r.max_abs_delta:.4f}   "
                     f"n={len(r.deltas)} (state x question)")
        else:
            L.append("  no comparable boolean answers in the reference sweep.")
        if r.other_changed:
            L.append("")
            L.append("  non-boolean answers that changed:")
            for line in r.other_changed:
                L.append(f"    {line}")
        if r.missing:
            L.append("")
            L.append(f"  {len(r.missing)} reference answer(s) absent today: "
                     f"{', '.join(r.missing[:5])}"
                     + (" ..." if len(r.missing) > 5 else ""))
        L.append("")
        flags = r.flags(tau, threshold)
        if flags:
            L.append("  ** DRIFT FLAGGED **")
            for f in flags:
                L.append(f"     {f}")
        else:
            L.append(f"  no drift flagged: model string unchanged, mean |delta| "
                     f"{r.mean_abs_delta:.4f} <= {threshold:.4f}, no decision flip "
                     f"at tau={tau:.2f}.")
        L.append("")

    L.append("-" * 78)
    L.append("WHAT THIS CAN AND CANNOT TELL YOU")
    L.append("-" * 78)
    L.append("  * `response_model` catches a RENAMED model. It cannot catch a silently")
    L.append("    retrained one served under the same string -- that is what the")
    L.append("    probability deltas are for, and it is why they are reported per state")
    L.append("    rather than as a single mean.")
    L.append("  * One call per state per day. The `borderline` stratum sits near tau by")
    L.append("    design, and PREREGISTRATION section 7 records that Jev wobbles there.")
    L.append("    A flip inside the jitter band is consistent with ordinary run-to-run")
    L.append("    variance; a flip outside it is not. The tool prints which, and refuses")
    L.append("    to decide for you -- separating the two needs repeats, which is")
    L.append("    determinism.py's job, not this one's.")
    L.append("  * Canary rows carry run_context='canary' and are never pooled with live,")
    L.append("    replay or synthetic rows (PREREGISTRATION section 4).")
    return "\n".join(L)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Daily fixed-state drift check. Exit 0 clean / 1 drift / "
                    "4 flip within tau jitter band / "
                    "2 no reference / 3 incomplete.")
    ap.add_argument("--surface", default="pre_bash")
    ap.add_argument("--arms", default="jev",
                    help="comma-separated. Default jev: a sweep is ~$0.005, whereas "
                         "the cc_* arms are ~21s of subscription quota each")
    ap.add_argument("--tau", type=float, default=DEFAULT_TAU,
                    help="decision threshold for the flip check")
    ap.add_argument("--threshold", type=float, default=DEFAULT_MEAN_DELTA,
                    help="mean |delta| above which drift is flagged")
    ap.add_argument("--report-only", action="store_true",
                    help="compare the sweeps already on disk; call no arm")
    ap.add_argument("--freeze-only", action="store_true",
                    help="create the frozen set if absent, print it, and stop")
    ap.add_argument("--seed", type=int, default=20260920,
                    help="arm-order shuffle only; the state selection is not random")
    ap.add_argument("--out", help="also write to reports/<name>")
    args = ap.parse_args()

    paths.ensure_dirs()
    fixture, created = load_or_freeze(args.surface)
    if created:
        print(f"froze {len(fixture['states'])} states -> {fixture_path()}")
        print(f"canary_set_id {fixture['canary_set_id']}")
    if args.freeze_only:
        for s in fixture["states"]:
            print(f"  {s['synthetic_id']}  {s['stratum']:<12} {s['state_sha256'][:12]}  "
                  f"{s['state'].splitlines()[1][:56] if len(s['state'].splitlines()) > 1 else ''}")
        return EXIT_CLEAN

    arms = [cl.arm(n.strip()) for n in args.arms.split(",") if n.strip()]
    warnings: list[str] = []
    if not args.report_only:
        print(f"canary sweep: {len(fixture['states'])} states x "
              f"{[a.name for a in arms]}")
        sweep_id, warnings = run_sweep(fixture, arms, random.Random(args.seed))
        print(f"wrote {len(fixture['states']) * len(arms)} run rows "
              f"under canary_sweep_id {sweep_id}")

    set_id = fixture["canary_set_id"]
    expected = len(fixture["states"])
    reports: list[ArmReport] = []
    unbaselined: list[tuple[str, str]] = []
    incomplete: list[tuple[str, str]] = []

    for config in arms:
        by_sweep, usable = sweeps_for(set_id, config.name, expected)
        if not by_sweep:
            unbaselined.append((config.name, (
                "no canary rows at all for this set. Nothing was recorded either: "
                "re-run without --report-only to lay down a baseline."
                if args.report_only else "no canary rows at all for this set.")))
            continue
        latest = max(by_sweep)
        latest_rows = by_sweep[latest]
        bad = [r for r in latest_rows if not r.get("ok")]
        if bad or len(latest_rows) != expected:
            incomplete.append((config.name, (
                f"sweep {latest} has {len(latest_rows)}/{expected} rows, "
                f"{len(bad)} failed ("
                f"{', '.join(sorted({r.get('error_kind') or '?' for r in bad})) or '-'}).")))
            continue
        reference = [s for s in usable if s < latest]
        if not reference:
            unbaselined.append((config.name, (
                f"sweep {latest} is the only complete, all-ok sweep on disk "
                f"({len(by_sweep)} sweep(s) total).")))
            continue
        reports.append(compare(by_sweep[reference[0]], latest_rows, config.name))

    text = render(fixture, reports, unbaselined, incomplete, warnings,
                  tau=args.tau, threshold=args.threshold)
    print()
    print(text)
    if args.out:
        paths.REPORTS.mkdir(parents=True, exist_ok=True)
        (paths.REPORTS / args.out).write_text(text, encoding="utf-8")
        print(f"\nwritten: {paths.REPORTS / args.out}")

    # Order matters. An incomplete sweep is not a clean run that happened to
    # have no reference, and neither is a drift result -- a wrapper that sees 0
    # must be able to read it as "checked, and clean".
    if incomplete:
        return EXIT_INCOMPLETE
    if any(r.hard_flags(args.tau, args.threshold) for r in reports):
        return EXIT_DRIFT
    if any(r.jitter_flips(args.tau) for r in reports):
        # Surfaced, not suppressed, and deliberately not 0: something moved
        # across tau and a reader should see it. But it is consistent with the
        # non-determinism already on the record, so it does not deserve the
        # same exit code as a model that changed underneath us.
        return EXIT_JITTER_ONLY
    if unbaselined:
        return EXIT_NO_REFERENCE
    if not reports:
        return EXIT_NO_REFERENCE
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
