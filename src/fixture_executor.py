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

  3. BLIND BY CONSTRUCTION, NOT BY PROCEDURE (`judge_payload`, `blind_check`,
     `Judge.score`, `RefMint`). The payload is {task, file, diff} and is BUILT
     from those three fields -- the conversation and the arm label are never in
     scope to be stripped.

     THE PAYLOAD WAS NEVER THE WHOLE INTERFACE. Until the W5 audit, `Judge`
     required `score(payload, *, task_id, arm, seed)`: the arm label was handed
     to the judge as a REQUIRED KEYWORD ARGUMENT, beside the payload it was
     meant to be blind to. A clean payload and a `arm="treatment"` kwarg is not
     a blind; it is one implementation's good manners. `RecordedJudge` happened
     not to look, and a blind that depends on an implementation not looking is
     not a guard.

     The judge is now addressed by an OPAQUE REFERENCE (`RefMint`): a salted
     hash of (task, arm, seed) whose salt is minted fresh per run, never
     recorded and never rendered. `RecordedJudge` resolves it through an index
     it builds by scanning its own fixture tree -- it can only resolve refs for
     runs it already holds on disk. `LiveJudge` is given no way to receive the
     salt, so for it the ref is a 32-hex opaque handle and the arm is not
     recoverable. The blind is now a property of the INTERFACE.

     Three things can still leak the arm, and all three are checked:
     the payload contents (`blind_check`), the tier and model names that
     identify the arm indirectly (`tier_tokens`), and the ORDER of the calls
     (see `run_class2` -- a stateful judge reading a BBBTTT block structure
     learns the arm without reading a single token).

Attrition (requirement 8): a tier that fails more often must not look cheaper
because its failures are cheap. `Class2Report.attrition` counts non-completing
executions per arm and per tier, and `cost_per_success` is reported beside
`cost_per_attempt` -- the first is the number that stops a cheap failure from
reading as a saving.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import secrets
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


def tier_tokens(tiers: Sequence[str] = ()) -> list[str]:
    """Arm-identifying names for the tiers ACTUALLY IN USE in this run.

    The arm label is not the only way a judge could learn which arm it is
    looking at. A diff carrying `# routed to claude-haiku-4-5`, or a prompt
    mentioning the `sonnet` alias, identifies the tier and therefore the arm
    just as effectively. Checking only for "baseline"/"treatment" would pass
    that payload and the blind would be broken in a way the check was blind to.

    W5 AUDIT -- THIS FUNCTION USED TO TAKE NO ARGUMENT, and that was both a
    false negative and a false positive at once:

      FALSE NEGATIVE. It enumerated `config/tiers.json` -- haiku45, sonnet5,
      opus5 -- while the tiers this suite's fixtures actually record are
      `cheap` and `frontier`. Those two names were in NO token list, so a diff
      reading "# cheap tier" passed the blind check cleanly. The check was
      guarding names that were not in play and ignoring the ones that were.

      FALSE POSITIVE. Enumerating every configured tier meant every run
      carried `opus`, `haiku` and `sonnet` as tokens whether or not any of
      them was in use, so prose naming a model the run never touched tripped
      a blind failure and forced exit 1.

    So the tiers are now passed IN, taken from the executions the run actually
    produced, and the config is consulted only to expand a tier that is in use
    into its alias and resolved model prefix. A tier added to `tiers.json` and
    never used costs nothing; a tier used and never configured is still
    covered by its own name.
    """
    tokens: set[str] = {str(t) for t in tiers if t}
    try:
        import tier_map
        config = tier_map.load()
    except Exception:
        # A missing config is `tier_map`'s problem to report, not this
        # function's. The names of the tiers in use still apply.
        return sorted(tokens)
    configured = config.get("tiers") or {}
    for name in list(tokens):
        spec = configured.get(name)
        if isinstance(spec, dict):
            for key in ("alias", "resolved_prefix"):
                if spec.get(key):
                    tokens.add(str(spec[key]))
    return sorted(tokens)


def blind_tokens(baseline_arm: str, treatment_arm: str,
                 tiers: Sequence[str] = (),
                 extra: Sequence[str] = ()) -> list[str]:
    """Words whose presence in a payload would break the blind.

    Note what is NOT here any more: the hardcoded literals "baseline",
    "treatment" and "control". The first two arrive as the arm PARAMETERS --
    hardcoding them as well did nothing except guarantee they were checked
    for even when the arms were named something else. "control" was pure
    false positive: it is not an arm name this harness ever uses, and it made
    every diff touching a variable named `control` a blind failure.
    """
    tokens = {baseline_arm, treatment_arm, "arm="}
    tokens.update(tier_tokens(tiers))
    tokens.update(extra)
    return sorted(t for t in tokens if t)


def _token_pattern(token: str) -> re.Pattern[str]:
    """Match `token` as a WHOLE WORD, not as a substring.

    W5 AUDIT. The check used to be `token.lower() in blob`, which flagged
    `controller` for containing "control" and `haikus` for containing "haiku".
    It erred safe -- a spurious blind failure is exit 1, not a false pass --
    but a guard that fires on ordinary code is a guard that gets switched off,
    and on real mined tasks it would have produced COULD-NOT-RUNs that have
    nothing to do with the blind.

    The boundary is applied only to the ends of the token that are word
    characters, so `arm=` still matches `arm=treatment` (and not `warm=`), and
    `claude-haiku-4-5` still matches the dated `claude-haiku-4-5-20251001`.
    """
    word = r"[0-9A-Za-z_]"
    prefix = rf"(?<!{word})" if re.match(word, token[:1] or " ") else ""
    suffix = rf"(?!{word})" if re.match(word, token[-1:] or " ") else ""
    return re.compile(prefix + re.escape(token) + suffix, re.IGNORECASE)


def blind_check(payload: dict[str, Any], tokens: Sequence[str]) -> list[str]:
    """Return the tokens found in the serialised payload. Empty = blind holds.

    A non-empty result is exit 1, not exit 3: the judge's verdict is UNUSABLE,
    which is a failure to measure, not a measured regression.
    """
    blob = json.dumps(payload, ensure_ascii=False)
    return [t for t in tokens if _token_pattern(t).search(blob)]


# ---------------------------------------------------------------------------
# Tiers 2 and 3 -- rule compliance and dimension scores
# ---------------------------------------------------------------------------

@dataclass
class JudgeVerdict:
    rule_violations: list[str] = field(default_factory=list)
    dimensions: dict[str, float] = field(default_factory=dict)


class RefMint:
    """Mints the OPAQUE REFERENCE that stands in for (task, arm, seed).

    The judge has to be told WHICH verdict it is being asked for -- a scorer
    that cannot address its subject cannot be replayed, cached or audited. The
    audit's finding was not that an identifier is wrong, it is that the
    identifier we used WAS THE ARM ITSELF.

    A ref is `sha256(salt || task || arm || seed)` truncated to 32 hex. The
    salt is 16 random bytes minted per run, is never written to the report,
    never rendered, and never leaves the harness except to a judge that is
    explicitly handed the mint. Without the salt the mapping is not invertible
    by inspection and not enumerable by guessing arm names: a live judge
    holding a ref holds 32 hex characters.

    The mint is deliberately NOT derived from `order_seed`. `order_seed` IS
    recorded, so that a run can be reproduced; deriving the salt from it would
    publish the decoder beside the ciphertext.
    """

    def __init__(self, salt: str | None = None) -> None:
        self.salt = salt or secrets.token_hex(16)

    def ref(self, task_id: str, arm: str, seed: int) -> str:
        material = f"{self.salt}\x00{task_id}\x00{arm}\x00{seed}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()[:32]


class Judge(Protocol):
    # `arm` is ABSENT and must stay absent. See the module docstring, point 3:
    # handing the judge the arm label beside a payload it is meant to be blind
    # to made the blind a property of RecordedJudge's good behaviour rather
    # than of this signature. `tests/test_accuracy_gate.py` asserts the
    # parameter list of this method, so re-adding it fails the suite.
    def score(self, payload: dict[str, Any], *, ref: str) -> JudgeVerdict: ...


class NoJudge:
    """Tier 1 only. The default, because tier 1 carries most of the weight."""
    enabled = False

    def score(self, payload, *, ref: str) -> JudgeVerdict:  # pragma: no cover
        return JudgeVerdict()


@dataclass
class RecordedJudge:
    """A fake judge reading recorded verdicts. Zero API calls.

    It is handed the SAME blind payload the live judge would get, so the blind
    check exercises the real payload shape rather than a test-only one.

    It resolves the opaque ref through an index it builds by SCANNING ITS OWN
    FIXTURE TREE: every `recorded/judge/<arm>/<task>/<seed>.json` on disk is
    minted through the same `RefMint` and filed under the resulting ref. The
    fixtures did not move. Note what this gives for free -- the recorded judge
    can only resolve refs for runs it ALREADY HOLDS, so a ref for a task it
    has no verdict for is a `HarnessFailure`, never a fabricated verdict.
    """
    root: Path
    enabled: bool = True
    _index: dict[str, Path] = field(default_factory=dict, repr=False)
    _bound: bool = field(default=False, repr=False)

    def bind(self, mint: RefMint) -> None:
        """Receive the run's mint and index the fixture tree under it.

        `run_class2` calls this ONLY for a judge it has type-checked as a
        recorded one. It is a named method rather than a duck-typed attribute
        so that a live judge cannot acquire the decoder by accident.
        """
        self._index = {}
        judge_root = self.root / "recorded" / "judge"
        for path in sorted(judge_root.glob("*/*/*.json")):
            arm = path.parent.parent.name
            task_id = path.parent.name
            try:
                seed = int(path.stem)
            except ValueError:
                continue
            self._index[mint.ref(task_id, arm, seed)] = path
        self._bound = True

    def score(self, payload, *, ref: str) -> JudgeVerdict:
        if not self._bound:
            raise HarnessFailure(
                "the recorded judge was asked to score before it was bound to "
                "a ref mint, so it cannot resolve the reference. This is a "
                "harness error (exit 1), not a verdict.")
        path = self._index.get(ref)
        if path is None:
            # Deliberately reports the hex and the index size and NOT the
            # task/arm/seed: an error message is not a side channel.
            raise HarnessFailure(
                f"no recorded judge verdict for ref {ref} "
                f"({len(self._index)} verdicts indexed under {self.root})")
        blob = json.loads(path.read_text(encoding="utf-8"))
        return JudgeVerdict(
            rule_violations=list(blob.get("rule_violations", [])),
            dimensions={k: float(v) for k, v in (blob.get("dimensions") or {}).items()},
        )


@dataclass
class LiveJudge:
    """The real model-backed judge. UNEXERCISED; refuses unless armed.

    It has NO `bind` method, and that absence is the blind. It never receives
    the salt, so the `ref` it is handed is 32 opaque hex characters and the
    arm is not recoverable from it.
    """
    armed: bool = False
    enabled: bool = True

    def score(self, payload, *, ref: str) -> JudgeVerdict:
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
    # The shuffle seed for the execution order. RECORDED so a run reproduces;
    # see `run_class2`. This is NOT the ref-mint salt, which is never recorded.
    order_seed: int = 0
    # The permutation actually executed, and the order the judge was driven
    # in. Kept so a reviewer can SEE that the arms interleave rather than
    # having to trust that they did.
    execution_order: list[tuple[str, str, int]] = field(default_factory=list)
    # The tiers this run actually produced. The blind token set is derived
    # from these rather than from every tier that happens to be configured.
    tiers_in_use: list[str] = field(default_factory=list)
    outcomes: list[TaskOutcome] = field(default_factory=list)
    attrition_by_arm: dict[str, int] = field(default_factory=dict)
    attrition_by_tier: dict[str, dict[str, int]] = field(default_factory=dict)
    cost_by_tier: dict[str, dict[str, float]] = field(default_factory=dict)
    blind_failures: list[str] = field(default_factory=list)
    # Median seconds per arm, {arm: (task_duration, blocking_duration)}. Both,
    # never one: a background subagent can get objectively faster while the
    # human waits exactly as long, and the SPEC's goal is "no added FELT
    # latency". Reported here so a Class 2 run carries its own S2 evidence.
    #
    # Each median carries its OWN `n_*`. The two are not always over the same
    # runs -- a run can report a task duration and no blocking duration -- and
    # two medians over two different denominators printed side by side with one
    # implied n is how a reader comes to compare numbers that are not
    # comparable. See `subagent_outcomes.py`, where exactly that happened.
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
               treatment_arm: str, judge: Judge | None = None,
               order_seed: int | None = None) -> Class2Report:
    """Execute both arms over the suite and score the final diffs.

    Raises CouldNotRun (exit 1) if the executor or judge cannot run at all, and
    HarnessFailure (also surfaced as exit 1) if the harness itself breaks.
    Neither is ever converted into a failed task.

    ### Order is part of the blind (JEV-29, W5 audit)

    This used to walk the suite in manifest order and run `baseline_arm` to
    completion -- all k seeds -- before starting `treatment_arm`. Every payload
    the judge saw arrived in a perfectly regular block: `BBBTTTBBBTTT...`. A
    stateful or sequence-aware judge does not need to read a single token to
    know the arm; it only needs to count to three. JEV-29's "randomise task
    order" box was unticked and it was unticked truthfully.

    So the (task, arm, seed) units are shuffled ONCE and both the executor and
    the judge are driven in that same shuffled order. This randomises task
    order and interleaves the arms in one move -- the two are not separate
    knobs, they are the same permutation.

    `order_seed` is recorded on the report so a run reproduces exactly. That
    is the whole reason it is a seeded `random.Random` and not `secrets`.

    Three phases, and the split is load-bearing rather than tidiness:

      1. EXECUTE every unit in shuffled order, keeping the executions.
      2. JUDGE every unit in THE SAME shuffled order. It has to be a separate
         pass because the blind token set is derived from the tiers the run
         actually produced (see `tier_tokens`), which is not known until every
         execution is in hand. Judging inside phase 1 would mean the first
         payloads were checked against a token set built from an incomplete
         view of the run.
      3. AGGREGATE in suite order, so that the REPORT is deterministic and
         diffable no matter which permutation produced it. Randomising what
         the judge sees is the point; randomising the output would only make
         the gate harder to read.
    """
    judge = judge or NoJudge()
    judging = bool(getattr(judge, "enabled", False))
    if order_seed is None:
        order_seed = secrets.randbits(32)
    report = Class2Report(
        suite_id=suite.suite_id,
        synthetic=suite.synthetic,
        provenance=suite.provenance,
        n_tasks=len(suite.tasks),
        seeds=suite.seeds,
        baseline_arm=baseline_arm,
        treatment_arm=treatment_arm,
        judged=judging,
        order_seed=order_seed,
    )

    # A ref mint per run. The salt is fresh, is not derived from order_seed,
    # and is never stored on the report -- so reproducing the ORDER of a run
    # does not reproduce the ability to decode its refs.
    mint = RefMint()
    # Only a judge we have type-checked as recorded is handed the decoder.
    # Duck-typing on a `bind` attribute would mean a live judge that happened
    # to grow one silently received the salt.
    if isinstance(judge, RecordedJudge):
        judge.bind(mint)

    # --- phase 1: execute, in shuffled order -------------------------------
    units = [(task, arm, seed)
             for task in suite.tasks
             for arm in (baseline_arm, treatment_arm)
             for seed in range(suite.seeds)]
    random.Random(order_seed).shuffle(units)
    report.execution_order = [(t.task_id, a, s) for t, a, s in units]

    executions: dict[tuple[str, str, int], Execution] = {}
    for task, arm, seed in units:
        executions[(task.task_id, arm, seed)] = executor.run(task, arm, seed)

    # --- phase 2: judge, in THE SAME shuffled order ------------------------
    tiers_in_use = sorted({e.tier for e in executions.values() if e.tier})
    report.tiers_in_use = tiers_in_use
    tokens = blind_tokens(baseline_arm, treatment_arm, tiers=tiers_in_use)

    verdicts: dict[tuple[str, str, int], JudgeVerdict] = {}
    if judging:
        for task, arm, seed in units:
            key = (task.task_id, arm, seed)
            payload = judge_payload(task, executions[key])
            found = blind_check(payload, tokens)
            if found:
                report.blind_failures.append(
                    f"{task.task_id}/{arm}/seed{seed}: arm-identifying "
                    f"token(s) {found} present in the judge payload")
                continue
            verdicts[key] = judge.score(payload, ref=mint.ref(task.task_id, arm, seed))

    # --- phase 3: aggregate, in suite order --------------------------------
    seconds: dict[str, dict[str, list[float]]] = {}
    for task in suite.tasks:
        outcome = TaskOutcome(task_id=task.task_id)
        dims: dict[str, list[float]] = {}
        for arm, passes, reasons in (
            (baseline_arm, outcome.baseline_pass, outcome.baseline_reasons),
            (treatment_arm, outcome.treatment_pass, outcome.treatment_reasons),
        ):
            for seed in range(suite.seeds):
                key = (task.task_id, arm, seed)
                execution = executions[key]
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

                verdict = verdicts.get(key)
                if verdict is not None:
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
        # Each median carries its own n. They are not always equal.
        report.durations[arm] = {"task_s": median(buckets["task"]),
                                 "n_task": len(buckets["task"]),
                                 "blocking_s": median(buckets["blocking"]),
                                 "n_blocking": len(buckets["blocking"])}
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
    order = "".join("B" if a == report.baseline_arm else "T"
                    for _, a, _ in report.execution_order)
    out.append(f"  execution order     RANDOMISED, arms interleaved; "
               f"order_seed = {report.order_seed}")
    out.append(f"                      reproduce with --order-seed {report.order_seed}")
    if order:
        out.append(f"                      arm sequence {order[:48]}"
                   + ("..." if len(order) > 48 else ""))
        out.append("                      (a judge that sees a regular BBBTTT block "
                   "learns the arm")
        out.append("                       by counting, without reading a token)")
    if report.tiers_in_use:
        out.append(f"  tiers in use        {', '.join(report.tiers_in_use)}  "
                   "(the blind token set is derived from these)")
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
        out.append("  subagent can get faster while the human waits exactly as long.")
        out.append("  Each median carries its OWN n: they are not always the same runs,")
        out.append("  and two medians over two denominators under one implied n is how")
        out.append("  a reader comes to compare numbers that are not comparable.")
        out.append(f"    {'arm':<14}{'task_s':>10}{'n':>6}{'blocking_s':>13}{'n':>6}")
        for arm in sorted(report.durations):
            d = report.durations[arm]
            task_s = "-" if d["task_s"] is None else f"{d['task_s']:.1f}"
            block_s = "-" if d["blocking_s"] is None else f"{d['blocking_s']:.1f}"
            out.append(f"    {arm:<14}{task_s:>10}{int(d.get('n_task') or 0):>6}"
                       f"{block_s:>13}{int(d.get('n_blocking') or 0):>6}")
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
