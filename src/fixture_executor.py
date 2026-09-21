"""Class 2 -- agent-side regression. The fixture suite, its executor, and the
scorer that only ever looks at the final diff.

SPEC §6, Class 2. This is the half of the guard that needs RE-EXECUTION, and
therefore the half that costs real money. Everything in this file is built and
tested against RECORDED fixtures; the live path is present, clearly marked, and
UNEXERCISED -- `agent_route` is `mode: "off"` and there is no live routing data.

Three things in here exist because of a specific prior finding, and each is
labelled with it:

  1. PER-TASK PASS/FAIL, NEVER AN AGGREGATE (`Class2Report.hard_regressions`).
     TwinRouterBench: one under-routed step in an 8-13 call trajectory fails the
     instance, and Opus-4.6-as-router flagged 7 of 147 verified-high steps while
     failing all 40 SWE trajectories. An aggregate score hides exactly that.

  2. SCORE THE FINAL `git diff` OF THE TURN, NEVER PER-EDIT-CALL (`final_diff`,
     `judge_payload`). Two reasons: published precision is 73% turn-phase vs 26%
     edit-phase, and an edit-tool scorer whose EDIT_TOOLS is {Edit, Write,
     MultiEdit} MISSES BASH-WRITTEN CHANGES ENTIRELY. This repository's own
     working style pushes edits into `sed` and heredocs, so an "optimized" agent
     that shifted its edits into Bash would show fewer flagged edits and look
     FALSELY BETTER. There is no code path in this file that reads a tool call.

  3. BLIND BY CONSTRUCTION, NOT BY PROCEDURE (`judge_payload`, `blind_check`).
     The payload is {task, file, diff} and is BUILT from those three fields --
     the conversation and the arm label are never in scope to be stripped. The
     blind-integrity check therefore reduces to asserting the arm label is
     absent from the payload, and it is asserted rather than assumed.

Attrition (requirement 8): a tier that fails more often must not look cheaper
because its failures are cheap. `Class2Report.attrition` counts non-completing
executions per arm and per tier, and `cost_per_success` is reported beside
`cost_per_attempt` -- the first is the number that stops a cheap failure from
reading as a saving.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

from accuracy_gate import (
    EXIT_CLEAN,
    EXIT_COULD_NOT_RUN,
    EXIT_REGRESSION,
    CouldNotRun,
    InvokedWrong,
    worst,
)

# |delta| below this on the 1-10 dimension ladder is noise, not a regression.
DIMENSION_REGRESSION_DELTA = 0.75
# Soft-block when treatment rule violations exceed baseline on more than this
# share of tasks.
RULE_SOFT_BLOCK_SHARE = 1.0 / 3.0

COMPLETED = "completed"


# ---------------------------------------------------------------------------
# The suite
# ---------------------------------------------------------------------------

@dataclass
class Task:
    task_id: str
    prompt: str
    acceptance_note: str
    # The acceptance note's NAMED ASSERTION: a substring that must be present in
    # the added lines of the final diff. Free, deterministic, no model involved.
    must_contain: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)
    target_file: str = ""


@dataclass
class Suite:
    suite_id: str
    root: Path
    seeds: int
    tasks: list[Task]
    synthetic: bool = True
    provenance: str = ""


def load_suite(root: Path, *, smoke: int | None = None) -> Suite:
    manifest_path = root / "suite.json"
    if not manifest_path.exists():
        raise InvokedWrong(f"no suite.json under {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tasks = []
    for entry in manifest.get("tasks", []):
        tasks.append(Task(
            task_id=entry["id"],
            prompt=entry.get("prompt", ""),
            acceptance_note=entry.get("acceptance_note", ""),
            must_contain=list(entry.get("must_contain", [])),
            must_not_contain=list(entry.get("must_not_contain", [])),
            target_file=entry.get("target_file", ""),
        ))
    if smoke is not None:
        tasks = tasks[:smoke]
    if not tasks:
        raise CouldNotRun(f"suite {root} has no tasks to run")
    return Suite(
        suite_id=manifest.get("suite_id", root.name),
        root=root,
        seeds=int(manifest.get("seeds", 3)),
        tasks=tasks,
        synthetic=bool(manifest.get("synthetic", True)),
        provenance=manifest.get("provenance", ""),
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

@dataclass
class Execution:
    """One (task, arm, seed) run. `diff` is the FINAL diff of the turn."""
    task_id: str
    arm: str
    seed: int
    status: str = COMPLETED        # completed | crashed | timeout | refused
    diff: str = ""
    tests_passed: bool = False
    tier: str | None = None
    cost_usd: float = 0.0
    task_duration_s: float | None = None
    blocking_duration_s: float | None = None

    @property
    def completed(self) -> bool:
        return self.status == COMPLETED


class HarnessFailure(RuntimeError):
    """The executor itself broke -- NOT the agent failing a task.

    These two must never be collapsed. An agent that crashes on a task is a
    DATA POINT (a failed seed, counted in attrition by tier). A harness that
    crashes is an ABSENCE of data, and absence of data is exit 1. Letting the
    second masquerade as the first turns a broken harness into evidence of a
    regression -- or, worse, into a green run over tasks that never executed.
    """


class Executor(Protocol):
    def run(self, task: Task, arm: str, seed: int) -> Execution: ...


@dataclass
class RecordedExecutor:
    """Replays recorded fixture outcomes. Free, deterministic, the tested path.

    Layout: <suite>/recorded/<arm>/<task_id>/<seed>.json, each carrying
    {status, tests_passed, tier, cost_usd, task_duration_s,
     blocking_duration_s, diff | diff_file}.
    """
    root: Path

    def run(self, task: Task, arm: str, seed: int) -> Execution:
        path = self.root / "recorded" / arm / task.task_id / f"{seed}.json"
        if not path.exists():
            raise HarnessFailure(
                f"no recorded outcome for task={task.task_id} arm={arm} seed={seed} "
                f"(looked in {path}). Missing fixture data is an ABSENCE of a "
                "measurement, not a failed task.")
        blob = json.loads(path.read_text(encoding="utf-8"))
        diff = blob.get("diff")
        if diff is None and blob.get("diff_file"):
            diff_path = path.parent / blob["diff_file"]
            if not diff_path.exists():
                raise HarnessFailure(f"recorded outcome references a missing diff: {diff_path}")
            diff = diff_path.read_text(encoding="utf-8")
        return Execution(
            task_id=task.task_id,
            arm=arm,
            seed=seed,
            status=blob.get("status", COMPLETED),
            diff=diff or "",
            tests_passed=bool(blob.get("tests_passed", False)),
            tier=blob.get("tier"),
            cost_usd=float(blob.get("cost_usd", 0.0)),
            task_duration_s=blob.get("task_duration_s"),
            blocking_duration_s=blob.get("blocking_duration_s"),
        )


@dataclass
class LiveExecutor:
    """Re-executes the fixture task for real. UNEXERCISED.

    This path has never been run. `agent_route` is `mode: "off"`, there is no
    live routing data, and the brief for this work forbids arming anything. It
    is here so that the shape of the live call is reviewable, and it REFUSES
    rather than pretending: without the explicit spend acknowledgement it raises
    CouldNotRun (exit 1), which is the honest answer to "did the gate pass?".
    """
    suite_root: Path
    workspace: Path
    armed: bool = False
    command_template: Sequence[str] = ("claude", "-p", "{prompt}")

    def planned_command(self, task: Task, arm: str, seed: int) -> list[str]:
        return [part.format(prompt=task.prompt, arm=arm, seed=seed)
                for part in self.command_template]

    def run(self, task: Task, arm: str, seed: int) -> Execution:
        planned = self.planned_command(task, arm, seed)
        if not self.armed:
            raise CouldNotRun(
                "the live executor is not armed and nothing was executed. It "
                "would have run:\n    " + " ".join(planned) +
                "\n  Pass --i-understand-this-spends-money to arm it. Until "
                "then this is exit 1 (COULD NOT RUN), never exit 0.")
        raise CouldNotRun(  # pragma: no cover - unexercised by construction
            "the live executor is armed but has no verified implementation in "
            "this repository. Nothing was executed, and this is exit 1.")


def final_diff(worktree: Path) -> str:
    """The final `git diff` of the turn, including files git does not track yet.

    UNEXERCISED live-path helper; the recorded executor supplies the diff
    directly. Untracked files are included deliberately: a change the agent
    created as a NEW file is still a change, and omitting it would reproduce the
    edit-phase blind spot in a different disguise.
    """
    def git(*args: str) -> str:
        proc = subprocess.run(["git", "-C", str(worktree), *args],
                              capture_output=True, text=True)
        if proc.returncode not in (0, 1):
            raise HarnessFailure(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout

    tracked = git("diff", "HEAD")
    untracked = git("ls-files", "--others", "--exclude-standard").split()
    parts = [tracked]
    for rel in untracked:
        parts.append(git("diff", "--no-index", "/dev/null", rel))
    return "".join(parts)


def added_lines(diff: str) -> str:
    """Only the lines the turn ADDED. Assertions are checked against these."""
    return "\n".join(line[1:] for line in diff.splitlines()
                     if line.startswith("+") and not line.startswith("+++"))


# ---------------------------------------------------------------------------
# Tier 1 -- hard checks. Free, deterministic, and they carry most of the weight.
# ---------------------------------------------------------------------------

@dataclass
class HardCheck:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def hard_check(task: Task, execution: Execution) -> HardCheck:
    """tests pass, and the acceptance note's named assertion exists in the diff.

    No model is involved, and no tool call is read -- only the final diff.
    """
    reasons: list[str] = []
    if not execution.completed:
        return HardCheck(False, [f"execution did not complete: {execution.status}"])
    if not execution.tests_passed:
        reasons.append("tests did not pass")
    added = added_lines(execution.diff)
    for needle in task.must_contain:
        if needle not in added:
            reasons.append(f"acceptance assertion absent from the diff: {needle!r}")
    for needle in task.must_not_contain:
        if needle in added:
            reasons.append(f"forbidden content present in the diff: {needle!r}")
    return HardCheck(not reasons, reasons)


# ---------------------------------------------------------------------------
# Blindness -- by construction, then asserted
# ---------------------------------------------------------------------------

def judge_payload(task: Task, execution: Execution) -> dict[str, Any]:
    """Everything the judge is allowed to see: {task, file, diff}.

    Built from three fields. The conversation, the arm, the tier, the model and
    the seed are not omitted from a larger object -- they are never in scope.
    That is what "blind by construction" means, and it is why `blind_check`
    below is a one-line assertion rather than a redaction pipeline.
    """
    return {
        "task": task.prompt,
        "file": task.target_file,
        "diff": execution.diff,
    }


def tier_tokens() -> list[str]:
    """Tier names, aliases and resolved model prefixes from `config/tiers.json`.

    The arm label is not the only way a judge could learn which arm it is
    looking at. A diff carrying `# routed to claude-haiku-4-5`, or a prompt
    mentioning the `sonnet` alias, identifies the tier and therefore the arm
    just as effectively. Checking only for "baseline"/"treatment" would pass
    that payload and the blind would be broken in a way the check was blind to.

    Reads the config rather than hardcoding, so a tier added to `tiers.json`
    is covered without anyone remembering to update this list. Returns [] if
    the config cannot be read -- the arm-label tokens still apply, and a
    missing config is `tier_map`'s problem to report, not this function's.
    """
    try:
        import tier_map
        config = tier_map.load()
    except Exception:
        return []
    tokens: set[str] = set()
    for name, spec in (config.get("tiers") or {}).items():
        tokens.add(name)
        if isinstance(spec, dict):
            for key in ("alias", "resolved_prefix"):
                if spec.get(key):
                    tokens.add(str(spec[key]))
    if config.get("frontier_tier"):
        tokens.add(str(config["frontier_tier"]))
    return sorted(tokens)


def blind_tokens(baseline_arm: str, treatment_arm: str,
                 extra: Sequence[str] = ()) -> list[str]:
    """Substrings whose presence in a payload would break the blind."""
    tokens = {baseline_arm, treatment_arm, "baseline", "treatment",
              "control", "arm="}
    tokens.update(tier_tokens())
    tokens.update(extra)
    return sorted(t for t in tokens if t)


def blind_check(payload: dict[str, Any], tokens: Sequence[str]) -> list[str]:
    """Return the tokens found in the serialised payload. Empty = blind holds.

    A non-empty result is exit 1, not exit 3: the judge's verdict is UNUSABLE,
    which is a failure to measure, not a measured regression.
    """
    blob = json.dumps(payload, ensure_ascii=False).lower()
    return [t for t in tokens if t.lower() in blob]


# ---------------------------------------------------------------------------
# Tiers 2 and 3 -- rule compliance and dimension scores
# ---------------------------------------------------------------------------

@dataclass
class JudgeVerdict:
    rule_violations: list[str] = field(default_factory=list)
    dimensions: dict[str, float] = field(default_factory=dict)


class Judge(Protocol):
    def score(self, payload: dict[str, Any], *, task_id: str, arm: str, seed: int
              ) -> JudgeVerdict: ...


class NoJudge:
    """Tier 1 only. The default, because tier 1 carries most of the weight."""
    enabled = False

    def score(self, payload, *, task_id, arm, seed) -> JudgeVerdict:  # pragma: no cover
        return JudgeVerdict()


@dataclass
class RecordedJudge:
    """A fake judge reading recorded verdicts. Zero API calls.

    It is handed the SAME blind payload the live judge would get, so the blind
    check exercises the real payload shape rather than a test-only one.
    """
    root: Path
    enabled: bool = True

    def score(self, payload, *, task_id: str, arm: str, seed: int) -> JudgeVerdict:
        path = self.root / "recorded" / "judge" / arm / task_id / f"{seed}.json"
        if not path.exists():
            raise HarnessFailure(f"no recorded judge verdict at {path}")
        blob = json.loads(path.read_text(encoding="utf-8"))
        return JudgeVerdict(
            rule_violations=list(blob.get("rule_violations", [])),
            dimensions={k: float(v) for k, v in (blob.get("dimensions") or {}).items()},
        )


@dataclass
class LiveJudge:
    """The real model-backed judge. UNEXERCISED; refuses unless armed."""
    armed: bool = False
    enabled: bool = True

    def score(self, payload, *, task_id, arm, seed) -> JudgeVerdict:
        raise CouldNotRun(
            "the live judge is not armed; no API call was made and no verdict "
            "exists. This is exit 1 (COULD NOT RUN), never exit 0."
            if not self.armed else
            "the live judge is armed but has no verified implementation here.")


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

@dataclass
class TaskOutcome:
    task_id: str
    baseline_pass: list[bool] = field(default_factory=list)
    treatment_pass: list[bool] = field(default_factory=list)
    baseline_reasons: list[str] = field(default_factory=list)
    treatment_reasons: list[str] = field(default_factory=list)
    baseline_violations: int = 0
    treatment_violations: int = 0
    dimension_delta: dict[str, float] = field(default_factory=dict)

    @property
    def hard_regression(self) -> bool:
        """Passes in ALL baseline seeds, fails in ALL treatment seeds.

        Per-task, not aggregate. One instance blocks; no statistics are applied
        to it and none are needed.
        """
        return (bool(self.baseline_pass) and all(self.baseline_pass)
                and bool(self.treatment_pass) and not any(self.treatment_pass))


@dataclass
class Class2Report:
    suite_id: str = ""
    synthetic: bool = True
    provenance: str = ""
    n_tasks: int = 0
    seeds: int = 0
    baseline_arm: str = ""
    treatment_arm: str = ""
    judged: bool = False
    outcomes: list[TaskOutcome] = field(default_factory=list)
    attrition_by_arm: dict[str, int] = field(default_factory=dict)
    attrition_by_tier: dict[str, dict[str, int]] = field(default_factory=dict)
    cost_by_tier: dict[str, dict[str, float]] = field(default_factory=dict)
    blind_failures: list[str] = field(default_factory=list)
    # Median seconds per arm, {arm: (task_duration, blocking_duration)}. Both,
    # never one: a background subagent can get objectively faster while the
    # human waits exactly as long, and the SPEC's goal is "no added FELT
    # latency". Reported here so a Class 2 run carries its own S2 evidence.
    durations: dict[str, dict[str, float | None]] = field(default_factory=dict)

    @property
    def hard_regressions(self) -> list[TaskOutcome]:
        return [o for o in self.outcomes if o.hard_regression]

    @property
    def rule_soft_block(self) -> bool:
        if not self.judged or not self.outcomes:
            return False
        worse = sum(1 for o in self.outcomes
                    if o.treatment_violations > o.baseline_violations)
        return worse > RULE_SOFT_BLOCK_SHARE * len(self.outcomes)

    @property
    def dimension_regressions(self) -> list[tuple[str, str, float]]:
        out = []
        for o in self.outcomes:
            for name, delta in sorted(o.dimension_delta.items()):
                if delta <= -DIMENSION_REGRESSION_DELTA:
                    out.append((o.task_id, name, delta))
        return out

    @property
    def exit_code(self) -> int:
        codes = [EXIT_CLEAN]
        if self.hard_regressions:
            codes.append(EXIT_REGRESSION)
        if self.blind_failures:
            codes.append(EXIT_COULD_NOT_RUN)
        return worst(*codes)


def run_class2(suite: Suite, executor: Executor, *, baseline_arm: str,
               treatment_arm: str, judge: Judge | None = None) -> Class2Report:
    """Execute both arms over the suite and score the final diffs.

    Raises CouldNotRun (exit 1) if the executor or judge cannot run at all, and
    HarnessFailure (also surfaced as exit 1) if the harness itself breaks.
    Neither is ever converted into a failed task.
    """
    judge = judge or NoJudge()
    report = Class2Report(
        suite_id=suite.suite_id,
        synthetic=suite.synthetic,
        provenance=suite.provenance,
        n_tasks=len(suite.tasks),
        seeds=suite.seeds,
        baseline_arm=baseline_arm,
        treatment_arm=treatment_arm,
        judged=getattr(judge, "enabled", False),
    )
    tokens = blind_tokens(baseline_arm, treatment_arm)
    seconds: dict[str, dict[str, list[float]]] = {}

    for task in suite.tasks:
        outcome = TaskOutcome(task_id=task.task_id)
        dims: dict[str, list[float]] = {}
        for arm, passes, reasons in (
            (baseline_arm, outcome.baseline_pass, outcome.baseline_reasons),
            (treatment_arm, outcome.treatment_pass, outcome.treatment_reasons),
        ):
            for seed in range(suite.seeds):
                execution = executor.run(task, arm, seed)
                if not execution.completed:
                    # Agent attrition: a failed seed, and a data point. It is
                    # counted by tier so that a tier which fails more often
                    # cannot look cheaper because its failures are cheap.
                    report.attrition_by_arm[arm] = report.attrition_by_arm.get(arm, 0) + 1
                tier = execution.tier or "(unrouted)"
                bucket = report.attrition_by_tier.setdefault(
                    tier, {"attempts": 0, "did_not_complete": 0, "hard_check_failed": 0})
                bucket["attempts"] += 1
                if not execution.completed:
                    bucket["did_not_complete"] += 1
                costs = report.cost_by_tier.setdefault(
                    tier, {"cost_usd": 0.0, "attempts": 0.0, "successes": 0.0})
                costs["cost_usd"] += execution.cost_usd
                costs["attempts"] += 1

                arm_seconds = seconds.setdefault(arm, {"task": [], "blocking": []})
                if execution.task_duration_s is not None:
                    arm_seconds["task"].append(execution.task_duration_s)
                if execution.blocking_duration_s is not None:
                    arm_seconds["blocking"].append(execution.blocking_duration_s)

                check = hard_check(task, execution)
                if not check.passed:
                    bucket["hard_check_failed"] += 1
                else:
                    costs["successes"] += 1
                passes.append(check.passed)
                reasons.extend(check.reasons)

                if getattr(judge, "enabled", False):
                    payload = judge_payload(task, execution)
                    found = blind_check(payload, tokens)
                    if found:
                        report.blind_failures.append(
                            f"{task.task_id}/{arm}/seed{seed}: arm-identifying "
                            f"token(s) {found} present in the judge payload")
                        continue
                    verdict = judge.score(payload, task_id=task.task_id, arm=arm, seed=seed)
                    if arm == baseline_arm:
                        outcome.baseline_violations += len(verdict.rule_violations)
                    else:
                        outcome.treatment_violations += len(verdict.rule_violations)
                    for name, value in verdict.dimensions.items():
                        dims.setdefault(f"{arm}::{name}", []).append(value)
        if dims:
            names = {k.split("::", 1)[1] for k in dims}
            for name in sorted(names):
                b = dims.get(f"{baseline_arm}::{name}", [])
                t = dims.get(f"{treatment_arm}::{name}", [])
                if b and t:
                    outcome.dimension_delta[name] = sum(t) / len(t) - sum(b) / len(b)
        report.outcomes.append(outcome)

    def median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[len(ordered) // 2]

    for arm, buckets in seconds.items():
        report.durations[arm] = {"task_s": median(buckets["task"]),
                                 "blocking_s": median(buckets["blocking"])}
    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_class2(report: Class2Report) -> str:
    out: list[str] = []
    out.append("=== Class 2 -- agent-side regression (SPEC §6) ===")
    out.append(f"  suite               {report.suite_id}"
               + ("  [SYNTHETIC FIXTURES]" if report.synthetic else ""))
    if report.provenance:
        out.append(f"  provenance          {report.provenance}")
    out.append(f"  tasks x seeds       {report.n_tasks} x {report.seeds} per arm")
    out.append(f"  arms                {report.baseline_arm} vs {report.treatment_arm}")
    out.append(f"  scored on           the FINAL DIFF of the turn "
               f"(never per-edit-call; Bash-written changes included)")
    out.append(f"  tiers 2/3 judge     {'on' if report.judged else 'off (hard checks only)'}")
    out.append("")
    out.append("  per-task pass/fail (never an aggregate):")
    for o in report.outcomes:
        b = "".join("P" if p else "f" for p in o.baseline_pass)
        t = "".join("P" if p else "f" for p in o.treatment_pass)
        mark = "REGRESSION" if o.hard_regression else "          "
        out.append(f"    {mark}  {o.task_id:<28} baseline[{b}]  treatment[{t}]")
        if o.hard_regression and o.treatment_reasons:
            for reason in sorted(set(o.treatment_reasons)):
                out.append(f"                  why: {reason}")
    out.append("")
    out.append("  attrition by tier (a tier that fails more often must not look")
    out.append("  cheaper because its failures are cheap):")
    out.append(f"    {'tier':<20}{'attempts':>9}{'no-complete':>13}{'hard-fail':>11}"
               f"{'$/attempt':>11}{'$/success':>11}")
    for tier in sorted(report.attrition_by_tier):
        a = report.attrition_by_tier[tier]
        c = report.cost_by_tier.get(tier, {"cost_usd": 0.0, "attempts": 0.0, "successes": 0.0})
        per_attempt = c["cost_usd"] / c["attempts"] if c["attempts"] else float("nan")
        per_success = (c["cost_usd"] / c["successes"] if c["successes"]
                       else float("inf"))
        out.append(f"    {tier:<20}{a['attempts']:>9}{a['did_not_complete']:>13}"
                   f"{a['hard_check_failed']:>11}{per_attempt:>11.4f}{per_success:>11.4f}")
    if report.durations:
        out.append("")
        out.append("  median seconds per run -- BOTH durations, never one. A background")
        out.append("  subagent can get faster while the human waits exactly as long:")
        out.append(f"    {'arm':<14}{'task_s':>10}{'blocking_s':>13}")
        for arm in sorted(report.durations):
            d = report.durations[arm]
            task_s = "-" if d["task_s"] is None else f"{d['task_s']:.1f}"
            block_s = "-" if d["blocking_s"] is None else f"{d['blocking_s']:.1f}"
            out.append(f"    {arm:<14}{task_s:>10}{block_s:>13}")
    if report.judged:
        out.append("")
        worse = sum(1 for o in report.outcomes
                    if o.treatment_violations > o.baseline_violations)
        out.append(f"  rule compliance     treatment worse on {worse}/{len(report.outcomes)} "
                   f"tasks (soft-block above {RULE_SOFT_BLOCK_SHARE:.0%})"
                   + ("  SOFT-BLOCK" if report.rule_soft_block else ""))
        for task_id, name, delta in report.dimension_regressions:
            out.append(f"  dimension           {task_id} {name} delta={delta:+.2f} "
                       f"(|delta| >= {DIMENSION_REGRESSION_DELTA})")
    if report.blind_failures:
        out.append("")
        out.append("  BLIND INTEGRITY FAILED -- the judge could have known the arm.")
        out.append("  The verdict is UNUSABLE (exit 1), not a measured regression:")
        for line in report.blind_failures:
            out.append(f"    {line}")
    out.append("")
    out.append(f"  hard regressions    {len(report.hard_regressions)} "
               "(a task passing every baseline seed and failing every treatment seed)")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI wiring, called from accuracy_gate.py
# ---------------------------------------------------------------------------

def build_executor(args) -> Executor:
    suite_root = Path(args.suite)
    if args.executor == "recorded":
        return RecordedExecutor(suite_root)
    return LiveExecutor(
        suite_root=suite_root,
        workspace=suite_root / "workspace",
        armed=bool(getattr(args, "i_understand_this_spends_money", False)),
    )


def build_judge(args) -> Judge:
    if args.judge == "none":
        return NoJudge()
    if args.judge == "recorded":
        return RecordedJudge(Path(args.suite))
    return LiveJudge(armed=bool(getattr(args, "i_understand_this_spends_money", False)))
