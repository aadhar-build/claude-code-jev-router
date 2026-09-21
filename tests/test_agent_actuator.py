#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-35 / W1: the static floor -- the rule, the ledger, the breaker, the check.

`tests/test_agent_actuator.sh` owns the process boundary: exit codes, the exact
bytes on stdout, the kill switches, the latency budget. This file owns the four
things that are easier to get wrong quietly than loudly:

  1. THE TWO IMPLEMENTATIONS AGREE. The rule exists twice -- in `jq` inside the
     hook, and in `src/tier_map.py` for the tests and any future analysis. This
     repo already knows that hazard (`build_pre_bash` vs the inline hook's jq)
     and the only thing that keeps two implementations of one format honest is a
     test that feeds both the same input and compares. Including the fingerprint:
     `openssl dgst` in bash and `hashlib` in Python must produce the same digest.

  2. THE CEILING IS COMPUTED, NOT QUOTED -- AND IT IS A RANGE. `general-purpose`
     is the large majority of delegated work and carries no routing signal, so
     the map cannot address it. `coverage()` recomputes the addressable share
     from a given mix, and it is exercised here against BOTH of the two mixes
     that can be sourced, because four counts of "a delegated task" circulate
     for this project and differ by a factor of 17 (see
     `config/tiers.json:_counts_and_their_rules`). Collapsing them to one number
     would be false precision, so the test asserts the range instead.

  3. THE BREAKER'S ARITHMETIC. Consecutive-not-total, TTL expiry, half-open, and
     the ordering hazard that made an append-only log the right shape.

  4. VERIFICATION AGAINST `resolvedModel`, NOT AGAINST WHAT WAS ASKED FOR. An
     assignment that was silently ignored makes the treatment arm identical to
     the control arm while still looking like a treatment. That is the failure
     this whole ticket most needs to be able to see.

Offline. No network, no API key, no Jev call -- the static floor makes none.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pyversion  # noqa: E402

pyversion.require()

import assignment_ledger as al  # noqa: E402
import tier_map  # noqa: E402

HOOK = ROOT / "hooks" / "agent_route_actuator.sh"
CONFIG = ROOT / "config" / "tiers.json"

#: The best-sourced mix: `data/baseline/sessions.jsonl`, field
#: `delegated_task_agent_types` aggregated over 29 sessions, summing to the same
#: 120 that `delegated_tasks` and `source.subagent_files` independently give.
#: Frozen as a snapshot on 2026-09-20, BEFORE transcript reaping -- which is why
#: it is larger than anything countable on disk today.
FULL_WINDOW_MIX = {
    "general-purpose": 78,
    "claude-code-guide": 18,
    "Plan": 12,
    "Explore": 12,
}

#: What is countable on disk today (2026-09-21): distinct `Agent` tool_use
#: blocks, deduplicated by block id, in this project's dir plus its worktrees.
#: A LOWER BOUND on a shrinking corpus, and it carries a category the snapshot
#: does not -- spawns with no `subagent_type` field at all, which are unroutable
#: for exactly the same reason `general-purpose` is.
ON_DISK_TODAY_MIX = {
    "general-purpose": 23,
    None: 12,
    "claude-code-guide": 3,
    "Explore": 2,
    "Plan": 2,
}


def payload(subagent_type: str | None = "Explore", **tool_input_extra) -> dict:
    ti: dict = {
        "prompt": "Audit every call site of drain_once.",
        "description": "audit drain_once",
        "run_in_background": False,
    }
    if subagent_type is not None:
        ti["subagent_type"] = subagent_type
    ti.update(tool_input_extra)
    return {
        "session_id": "s1",
        "tool_use_id": "toolu_01",
        "hook_event_name": "PreToolUse",
        "permission_mode": "auto",
        "tool_name": "Agent",
        "tool_input": ti,
    }


class SandboxHook:
    """Run the REAL hook against a throwaway project root.

    Every path the hook touches is derived from $CLAUDE_PROJECT_DIR and $HOME
    and there is no other anchor in the script, so the behaviour is identical
    and nothing can reach the live collection window.
    """

    def __init__(self, tmp: Path):
        # .resolve() is load-bearing on macOS: tempdirs land under /var, which
        # is a symlink to /private/var. The hook's cwd guard compares "$PWD/"
        # against "$ROOT"/*, and an unresolved root makes every invocation exit
        # on that guard -- which would make every assertion below pass for the
        # wrong reason. tests/test_agent_actuator.sh uses `pwd -P` for this.
        self.root = tmp.resolve()
        (self.root / "config").mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        (self.root / ".claude").mkdir(parents=True, exist_ok=True)
        shutil.copy(CONFIG, self.root / "config" / "tiers.json")

    def run(self, obj, cwd: str | None = None, project_dir: str | None = None,
            **env_extra) -> tuple[int, str]:
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = project_dir or str(self.root)
        # W2: $JEV_HOME is where jev lives and is resolved WITHOUT reference to
        # $CLAUDE_PROJECT_DIR. Point it at the sandbox too, or the hook resolves
        # it from its own path -- the real repo -- and reads the real repo's
        # config, the real repo's kill switch and the real repo's data/.
        env["JEV_HOME"] = str(self.root)
        env["HOME"] = str(self.root)
        env.pop("JEV_ARM_SUBPROCESS", None)
        env.pop("JEV_GRADER", None)
        env.update(env_extra)
        data = obj if isinstance(obj, str) else json.dumps(obj)
        proc = subprocess.run(
            [str(HOOK)], input=data, capture_output=True, text=True,
            cwd=cwd or str(self.root), env=env, timeout=30)
        return proc.returncode, proc.stdout

    def ledger(self) -> list[dict]:
        return al.read_ledger(self.root / "data" / "agent_route" / "assignments")

    def breaker(self) -> list[dict]:
        return al.breaker_outcomes(
            self.root / "data" / "agent_route" / "breaker.jsonl")

    def inert_rows(self) -> list[dict]:
        """The durable record a path that did nothing is obliged to leave."""
        path = self.root / "data" / "agent_route" / "inert.jsonl"
        if not path.is_file():
            return []
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def inert_marker(self) -> str | None:
        path = self.root / "data" / "agent_route" / "INERT"
        return path.read_text() if path.is_file() else None


class TestTheRuleExistsTwiceAndTheTwoAgree(unittest.TestCase):
    """The only thing that keeps a jq rule and a Python rule from drifting."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hook = SandboxHook(Path(self.tmp.name))
        self.config = tier_map.load()
        self.addCleanup(self.tmp.cleanup)

    def test_every_known_subagent_type_decides_identically_in_bash_and_in_python(self):
        cases = list(FULL_WINDOW_MIX) + ["fork", "claude", "impeccable:x", None]
        for subagent_type in cases:
            with self.subTest(subagent_type=subagent_type):
                p = payload(subagent_type)
                expected = tier_map.decide(p["tool_input"], self.config)
                rows = SandboxHook(Path(tempfile.mkdtemp(dir=self.tmp.name)))
                rc, _ = rows.run(p)
                self.assertEqual(rc, 0)
                row = rows.ledger()[-1]
                self.assertEqual(row["decision"], expected.outcome)
                self.assertEqual(row["tier"], expected.tier)
                self.assertEqual(row["assigned_alias"], expected.alias)
                # Byte-for-byte, not merely "both say Explore". The rule text is
                # what an analysis reads back to explain a decision, so a
                # disagreement in its wording is a disagreement that matters.
                self.assertEqual(row["rule"], expected.rule)

    def test_the_two_fingerprints_of_the_rule_table_agree(self):
        """`openssl dgst -sha256` in the hook, `hashlib` here. A ledger row that
        carries a fingerprint nothing else can reproduce is a fingerprint of
        nothing."""
        rc, _ = self.hook.run(payload("Explore"))
        self.assertEqual(rc, 0)
        row = self.hook.ledger()[-1]
        self.assertEqual(
            row["config_sha256"],
            tier_map.config_sha256(self.hook.root / "config" / "tiers.json"))

    def test_the_python_half_produces_the_same_updated_input_as_the_hook(self):
        p = payload("Explore", weird={"a": [1, 2, 3]})
        rc, out = self.hook.run(p)
        from_hook = json.loads(out)["hookSpecificOutput"]["updatedInput"]
        decision = tier_map.decide(p["tool_input"], self.config)
        from_python = tier_map.apply(p["tool_input"], decision)
        self.assertEqual(from_hook, from_python)


class TestNoPathIsAllowedToBeSilent(unittest.TestCase):
    """W5. FAIL SAFE and FAIL SILENTLY are not the same thing.

    SPEC non-negotiable 1(b): a router that cannot decide sends the task to
    FRONTIER. Three paths did neither that nor anything else -- they exited 0
    having written nothing anywhere, which is a registered hook that is a
    permanent no-op, byte-identical to the control arm while appearing
    installed. That is the failure mode the `resolvedModel` check exists to
    catch, arriving through a different door.

    The rule this class enforces: every path either fails to frontier, or
    leaves a durable, visible record that it did nothing and why.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hook = SandboxHook(Path(self.tmp.name))
        self.addCleanup(self.tmp.cleanup)

    def _break_alias(self):
        """A tier that exists and has no `alias`. `tier_map.alias_for()` has
        always RAISED on this; the hook used to sail straight through it."""
        cfg_path = self.hook.root / "config" / "tiers.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["tiers"]["haiku45"]["alias"] = None
        cfg_path.write_text(json.dumps(cfg))
        return cfg

    # -- path 1: a tier with no alias -------------------------------------
    def test_an_aliasless_tier_fails_to_frontier_and_is_not_scored_as_success(self):
        """It used to fail OPEN: decision `routed`, `assigned_alias: null`, no
        rewrite emitted -- and the breaker line said `ok: true`, so the one
        condition that makes routing a permanent no-op was counted as a
        SUCCESS and could never trip the breaker."""
        self._break_alias()
        rc, out = self.hook.run(payload("Explore"))
        self.assertEqual(rc, 0)

        row = self.hook.ledger()[-1]
        self.assertEqual(row["decision"], "fail_to_frontier")
        self.assertEqual(row["assigned_alias"], "opus")
        self.assertEqual(
            json.loads(out)["hookSpecificOutput"]["updatedInput"]["model"], "opus")

        outcome = self.hook.breaker()[-1]
        self.assertFalse(outcome["ok"], "an aliasless tier must not score as a success")

    def test_a_routed_row_never_carries_a_null_alias(self):
        """The invariant behind the fix, stated once: `routed` means the input
        was rewritten, so a `routed` row with no alias is a contradiction."""
        self._break_alias()
        self.hook.run(payload("Explore"))
        for row in self.hook.ledger():
            if row["decision"] == "routed":
                self.assertIsNotNone(row["assigned_alias"], row)

    def test_the_jq_half_and_the_python_half_agree_on_the_aliasless_config(self):
        """The parity test did not cover this, and the two implementations
        disagreed underneath it: Python raised, jq returned `routed`."""
        cfg = self._break_alias()
        with self.assertRaises(tier_map.TierConfigError):
            tier_map.alias_for(cfg, "haiku45")
        with self.assertRaises(tier_map.TierConfigError):
            tier_map.decide(payload("Explore")["tool_input"], cfg)
        self.hook.run(payload("Explore"))
        self.assertEqual(self.hook.ledger()[-1]["decision"], "fail_to_frontier")

    # -- path 2: the cwd guard --------------------------------------------
    def test_a_trailing_slash_on_the_project_dir_no_longer_kills_the_hook(self):
        """`CLAUDE_PROJECT_DIR=/repo/` is the same directory as `/repo`. The
        guard compared bytes, so the hook exited on EVERY invocation: zero
        bytes, no ledger row, no breaker line. Installed, and inert."""
        rc, out = self.hook.run(payload("Explore"),
                                project_dir=str(self.hook.root) + "/")
        self.assertEqual(rc, 0)
        self.assertEqual(
            json.loads(out)["hookSpecificOutput"]["updatedInput"]["model"], "haiku")
        self.assertEqual(self.hook.ledger()[-1]["decision"], "routed")

    def test_a_symlinked_project_dir_no_longer_kills_the_hook(self):
        link = Path(self.tmp.name).resolve().parent / (self.hook.root.name + "-link")
        link.symlink_to(self.hook.root)
        self.addCleanup(link.unlink)
        rc, out = self.hook.run(payload("Explore"), project_dir=str(link))
        self.assertEqual(rc, 0)
        self.assertIn("hookSpecificOutput", out)

    def test_a_cwd_genuinely_outside_the_project_leaves_evidence(self):
        """Doing nothing is right here. Doing nothing INVISIBLY is not."""
        outside = Path(tempfile.mkdtemp(dir=self.tmp.name)).resolve()
        project = self.hook.root / "inner"
        project.mkdir()
        rc, out = self.hook.run(payload("Explore"), cwd=str(outside),
                                project_dir=str(project))
        self.assertEqual(rc, 0)
        self.assertEqual(out, "", "the tool input must be left untouched")

        rows = self.hook.inert_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "cwd_outside_project")
        self.assertEqual(rows[0]["cwd"], str(outside))
        self.assertEqual(rows[0]["project_dir"], str(project))
        marker = self.hook.inert_marker()
        self.assertIsNotNone(marker, "a sticky marker, or nobody finds this tomorrow")
        self.assertIn("cwd_outside_project", marker)

    # -- path 3: the ledger cannot be written ------------------------------
    def test_an_unwritable_ledger_directory_says_so_out_loud(self):
        """No disk to write the evidence to, so the evidence goes down the
        loudest channel a hook has. What it must NOT do is exit 0 in silence,
        which is what it did: no rewrite, no ledger row, no breaker line, no
        marker -- a router that had quietly stopped routing."""
        data = self.hook.root / "data"
        data.mkdir(exist_ok=True)
        data.chmod(0o500)
        self.addCleanup(data.chmod, 0o700)

        rc, out = self.hook.run(payload("Explore"))
        self.assertEqual(rc, 0)
        self.assertNotEqual(out.strip(), "", "a silent no-op is never acceptable")
        emitted = json.loads(out)
        self.assertIn("systemMessage", emitted)
        self.assertIn("INERT", emitted["systemMessage"])
        # And it is a message, never a permission decision or a rewrite.
        self.assertNotIn("hookSpecificOutput", emitted)

    # -- path 4: a relative $JEV_HOME ---------------------------------------
    def test_a_relative_jev_home_is_refused_rather_than_resolved_against_the_cwd(self):
        """W5, from the install agent's finding. Bash uses `$JEV_HOME`
        VERBATIM after an `is_dir` test, so `JEV_HOME=.` makes every jev asset
        cwd-relative -- including `$JEV_HOME/.jev-disabled`, the GLOBAL kill
        switch. A switch whose path depends on where the caller happened to be
        standing is exactly what the per-project block says must never happen.

        `paths.resolve_jev_home()` RAISES on the same value. A hook cannot
        raise, so it refuses: no rewrite, and -- the part that matters -- no
        ledger, no config read and no switch test anywhere under the cwd.
        """
        rc, out = self.hook.run(payload("Explore"), JEV_HOME=".")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "", "a relative JEV_HOME must not produce a rewrite")
        # Nothing was resolved against the cwd. `self.hook.root` IS the cwd
        # here, so had the hook used "." verbatim it would have written its
        # ledger into ./data/agent_route/ -- which is what this asserts did
        # not happen.
        self.assertEqual(self.hook.ledger(), [])
        self.assertFalse((self.hook.root / "data" / "agent_route").exists())

    def test_the_python_half_refuses_the_same_relative_value(self):
        """One rule, both readers -- including on the value both must reject.
        `tests/test_jev_home.sh` §1 compares the two on paths they agree on;
        this is the case where agreement means BOTH refuse."""
        import paths
        with self.assertRaises(RuntimeError):
            paths.resolve_jev_home({"JEV_HOME": "."})

    def test_an_absolute_jev_home_is_still_accepted(self):
        """The control. Without it, the two assertions above would pass on a
        hook that had simply stopped working."""
        rc, out = self.hook.run(payload("Explore"), JEV_HOME=str(self.hook.root))
        self.assertEqual(rc, 0)
        self.assertIn("hookSpecificOutput", json.loads(out))

    def test_the_happy_path_is_still_silent_about_being_inert(self):
        """The control for all of the above. If `inert` fired on the ordinary
        path, every assertion here would pass for the wrong reason."""
        rc, out = self.hook.run(payload("Explore"))
        self.assertEqual(rc, 0)
        self.assertIn("hookSpecificOutput", json.loads(out))
        self.assertEqual(self.hook.inert_rows(), [])
        self.assertIsNone(self.hook.inert_marker())


class TestInputFidelity(unittest.TestCase):
    """`updatedInput` replaces the ENTIRE tool input object."""

    def setUp(self):
        self.config = tier_map.load()

    def test_apply_is_a_copy_plus_one_key_and_can_never_drop_a_field(self):
        ti = {"prompt": "p", "description": "d", "subagent_type": "Explore",
              "run_in_background": True, "a_field_invented_later": {"x": 1}}
        out = tier_map.apply(ti, tier_map.decide(ti, self.config))
        for key, value in ti.items():
            if key == "model":
                continue
            self.assertEqual(out[key], value, key)
        self.assertEqual(out["model"], "haiku")
        # The input itself is never mutated -- a hook that edited its argument
        # in place would be a different and much worse kind of bug.
        self.assertNotIn("model", ti)

    def test_a_decision_that_does_not_route_changes_nothing_at_all(self):
        ti = {"prompt": "p", "subagent_type": "general-purpose"}
        decision = tier_map.decide(ti, self.config)
        self.assertEqual(decision.outcome, "no_rule")
        self.assertEqual(tier_map.apply(ti, decision), ti)


class TestTheCeilingIsComputedNotQuoted(unittest.TestCase):
    def setUp(self):
        self.config = tier_map.load()

    def test_general_purpose_is_mapped_to_nothing_on_purpose(self):
        """The large majority of delegated traffic by every source that has
        counted it. It is the catch-all type, so the type name says nothing
        about the work. Mapped to null rather than guessed, and that row is the
        static floor's ceiling."""
        rule = self.config["rules"]["general-purpose"]
        self.assertIsNone(rule["tier"])
        self.assertIn("no routing signal", tier_map.decide(
            {"prompt": "p", "subagent_type": "general-purpose"}, self.config).rule)

    def test_the_addressable_share_is_a_range_between_an_eighth_and_a_third(self):
        """Not a point. Four counts of "a delegated task" circulate for this
        project and differ by a factor of 17, because they count different
        things over different windows. Both sourceable mixes are asserted; if a
        future edit maps `general-purpose` to a tier, both numbers move and this
        test says so."""
        full = tier_map.coverage(self.config, FULL_WINDOW_MIX)
        self.assertEqual(full["total"], 120)
        self.assertEqual(full["routable"], 42)      # 18 + 12 + 12
        self.assertEqual(full["unroutable"], 78)
        self.assertAlmostEqual(full["share_routable"], 0.35, places=2)

        today = tier_map.coverage(self.config, ON_DISK_TODAY_MIX)
        self.assertEqual(today["total"], 42)
        self.assertEqual(today["routable"], 7)      # 3 + 2 + 2
        self.assertAlmostEqual(today["share_routable"], 0.167, places=3)

        # The claim the report is allowed to make, and no stronger one.
        for cov in (full, today):
            self.assertTrue(0.10 < cov["share_routable"] < 0.40)

    def test_a_spawn_with_no_subagent_type_at_all_is_unroutable_too(self):
        """12 of 42 spawns on disk today carry no `subagent_type` field. That
        category appears in no earlier estimate of this map's coverage, and it
        is unroutable for exactly the reason `general-purpose` is."""
        decision = tier_map.decide({"prompt": "p"}, self.config)
        self.assertEqual(decision.outcome, "no_rule")
        self.assertIsNone(decision.alias)

    def test_the_map_declares_itself_a_policy_choice_rather_than_a_fitted_one(self):
        """With the corpus size disputed by a factor of 17, a map presented as
        data-derived would be false precision. Each routed rule has to say what
        it is."""
        self.assertIn("_THIS_MAP_IS_A_POLICY_CHOICE_AND_IS_NOT_DATA_DERIVED", self.config)
        for name, rule in self.config["rules"].items():
            self.assertIn("basis", rule, name)
            if rule.get("tier") is not None:
                self.assertIn("policy", rule["basis"], name)

    def test_an_unmapped_type_is_left_alone_and_is_not_an_error(self):
        """A MISS IS NOT AN ERROR. Routing an unknown type up to frontier would
        be a cost decision made on no information, and it would make the
        no-signal majority more expensive than doing nothing at all."""
        for subagent_type in ("fork", "claude", "impeccable:impeccable-documenter"):
            decision = tier_map.decide(
                {"prompt": "p", "subagent_type": subagent_type}, self.config)
            self.assertEqual(decision.outcome, "no_rule", subagent_type)
            self.assertNotIn(decision.outcome, tier_map.FAILURES)


class TestTheConfigIsInternallyConsistent(unittest.TestCase):
    def setUp(self):
        self.config = tier_map.load()
        self.hook_src = HOOK.read_text()

    def test_every_rule_names_a_tier_that_exists(self):
        for name, rule in self.config["rules"].items():
            tier = rule.get("tier")
            if tier is not None:
                self.assertIn(tier, self.config["tiers"], name)

    def test_every_tier_alias_is_one_the_agent_tool_actually_accepts(self):
        """The Agent tool's `model` field takes an ALIAS, not a dated model id.

        The tool schema is the primary source (`enum: ["sonnet","opus","haiku",
        "fable"]`) and is the only evidence for `haiku`, which no observed spawn
        uses. Observed traffic corroborates: of 208 distinct spawns in
        ~/.claude/projects, deduplicated by tool_use block id, 29 carry
        "sonnet", 2 "opus", 2 "inherit" and 177 none. None carries a full id.

        A hook that emitted `claude-haiku-4-5-20251001` would have every
        assignment silently ignored -- and a silently ignored assignment makes
        the treatment arm identical to the control arm while still looking like
        a treatment."""
        accepted = {"sonnet", "opus", "haiku", "fable", "inherit"}
        for name, tier in self.config["tiers"].items():
            self.assertIn(tier["alias"], accepted, name)

    def test_the_hooks_one_hardcoded_frontier_alias_agrees_with_the_config(self):
        """The fail-to-frontier target used when the CONFIG is what failed
        cannot itself be read from the config. That one literal is allowed, and
        this is the test that stops it drifting."""
        frontier_alias = self.config["tiers"][self.config["frontier_tier"]]["alias"]
        self.assertIn(f'FRONTIER_FALLBACK_ALIAS="{frontier_alias}"', self.hook_src)

    def test_the_frontier_is_the_top_tier_and_not_merely_a_named_one(self):
        ranks = {k: v["rank"] for k, v in self.config["tiers"].items()}
        self.assertEqual(self.config["frontier_tier"], max(ranks, key=ranks.get))

    def test_the_breaker_threshold_fits_inside_the_window_the_hook_reads(self):
        """The hook reads `tail -n 50` of the outcome log. A threshold above
        that could never be met and the breaker would never open."""
        self.assertIn("tail -n 50", self.hook_src)
        self.assertLessEqual(self.config["breaker"]["max_consecutive_failures"], 50)

    def test_the_map_is_configuration_and_the_hook_holds_no_tier_literal(self):
        for alias in ("haiku", "sonnet"):
            self.assertNotIn(f'"{alias}"', self.hook_src, alias)
        for subagent_type in self.config["rules"]:
            self.assertNotIn(subagent_type, self.hook_src, subagent_type)


class TestTheBreaker(unittest.TestCase):
    """Fail-to-frontier protects quality and does NOT protect cost. This bounds it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "breaker.jsonl"
        self.config = tier_map.load()
        self.addCleanup(self.tmp.cleanup)

    def write(self, rows):
        self.log.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_an_empty_log_is_closed(self):
        self.assertFalse(al.breaker_state(self.config, self.log)["open"])

    def test_n_consecutive_fresh_failures_open_it(self):
        now = time.time()
        self.write([{"ts": now - i, "ok": False, "error": "x"} for i in (3, 2, 1)])
        state = al.breaker_state(self.config, self.log)
        self.assertTrue(state["open"])
        self.assertEqual(state["consecutive_failures"], 3)

    def test_consecutive_not_total(self):
        """Three failures with a success among them is a flake, not an outage."""
        now = time.time()
        self.write([
            {"ts": now - 5, "ok": False, "error": "x"},
            {"ts": now - 4, "ok": False, "error": "x"},
            {"ts": now - 3, "ok": True},
            {"ts": now - 2, "ok": False, "error": "x"},
        ])
        self.assertFalse(al.breaker_state(self.config, self.log)["open"])

    def test_past_the_ttl_it_is_half_open_rather_than_open(self):
        """Half-open falls out of deriving state instead of storing it: the
        newest failure is stale, one attempt is allowed, and that attempt's own
        outcome line decides. There is no reset step anyone can forget."""
        old = time.time() - 100000
        self.write([{"ts": old - i, "ok": False, "error": "x"} for i in (3, 2, 1)])
        state = al.breaker_state(self.config, self.log)
        self.assertFalse(state["open"])
        self.assertTrue(state["half_open"])
        self.assertEqual(state["consecutive_failures"], 3)

    def test_out_of_order_appends_are_sorted_before_being_read(self):
        """Parallel Agent spawns are the normal case and they append in
        completion order, not start order. An append-only log tolerates that; a
        read-modify-write counter would have lost increments instead."""
        now = time.time()
        self.write([
            {"ts": now - 1, "ok": False, "error": "x"},
            {"ts": now - 3, "ok": False, "error": "x"},
            {"ts": now - 2, "ok": False, "error": "x"},
        ])
        self.assertTrue(al.breaker_state(self.config, self.log)["open"])

    def test_a_torn_line_does_not_lose_the_lines_around_it(self):
        now = time.time()
        self.log.write_text(
            json.dumps({"ts": now - 3, "ok": False, "error": "x"}) + "\n"
            + '{"ts": 17, "ok": fa\n'
            + json.dumps({"ts": now - 2, "ok": False, "error": "x"}) + "\n"
            + json.dumps({"ts": now - 1, "ok": False, "error": "x"}) + "\n")
        self.assertTrue(al.breaker_state(self.config, self.log)["open"])

    def test_a_zero_threshold_disables_the_breaker_rather_than_pinning_it_open(self):
        config = dict(self.config, breaker={"max_consecutive_failures": 0, "ttl_s": 900})
        now = time.time()
        self.write([{"ts": now - i, "ok": False, "error": "x"} for i in (3, 2, 1)])
        self.assertFalse(al.breaker_state(config, self.log)["open"])


class TestVerifyAgainstResolvedModel(unittest.TestCase):
    """Asking for a model and getting it are different events."""

    def setUp(self):
        self.config = tier_map.load()

    def rows(self):
        # `assigned_alias` is present on every row because THE HOOK PUTS IT
        # THERE, and because it is now what `verify()` keys "did we rewrite?"
        # on. A fixture missing a field the writer always emits is a fixture
        # that can agree with a reader the writer disagrees with -- which is
        # exactly how the fail-to-frontier misclassification survived a test
        # that claimed to cover it.
        return [
            {"tool_use_id": "a", "decision": "routed", "tier": "haiku45",
             "assigned_alias": "haiku"},
            {"tool_use_id": "b", "decision": "routed", "tier": "haiku45",
             "assigned_alias": "haiku"},
            {"tool_use_id": "c", "decision": "routed", "tier": "opus5",
             "assigned_alias": "opus"},
            {"tool_use_id": "d", "decision": "no_rule", "tier": None,
             "assigned_alias": None},
        ]

    def test_a_dated_resolved_model_still_counts_as_honoured(self):
        """`resolvedModel` is a full and sometimes dated id
        (`claude-haiku-4-5-20251001`); the hook emits the alias `haiku`.
        Equality would report every honoured assignment as a mismatch, so the
        comparison is a prefix match against the tier's `resolved_prefix`."""
        out = al.verify(self.rows(), {"a": "claude-haiku-4-5-20251001"}, self.config)
        self.assertEqual(out["summary"]["honoured"], 1)

    def test_a_suffixed_resolved_model_still_counts_as_honoured(self):
        out = al.verify(
            [{"tool_use_id": "c", "decision": "routed", "tier": "opus5",
              "assigned_alias": "opus"}],
            {"c": "claude-opus-5[1m]"}, self.config)
        self.assertEqual(out["summary"]["honoured"], 1)

    def test_an_ignored_assignment_is_visible_and_is_not_counted_as_success(self):
        """THE ONE THAT MATTERS. An `availableModels` allowlist or
        CLAUDE_CODE_SUBAGENT_MODEL_FORCE overrides the hook, and an assignment
        that was silently ignored makes the treatment arm identical to the
        control arm while still looking like a treatment."""
        out = al.verify(self.rows(), {"a": "claude-opus-5"}, self.config)
        self.assertEqual(out["summary"]["overridden"], 1)
        self.assertEqual(out["detail"][0]["verdict"], "overridden")
        self.assertEqual(out["detail"][0]["resolved_model"], "claude-opus-5")

    def test_an_unobserved_assignment_is_attrition_and_never_assumed_honoured(self):
        out = al.verify(self.rows(), {}, self.config)
        self.assertEqual(out["summary"]["unobserved"], 3)
        self.assertEqual(out["summary"]["honoured"], 0)
        self.assertEqual(out["honour_rate"], 0.0)

    def test_rows_we_deliberately_left_alone_are_not_scored_as_failures(self):
        out = al.verify(self.rows(), {"a": "claude-haiku-4-5", "b": "claude-haiku-4-5",
                                      "c": "claude-opus-5"}, self.config)
        self.assertEqual(out["summary"]["not_routed"], 1)
        self.assertEqual(out["routed_total"], 3)
        self.assertEqual(out["honour_rate"], 1.0)

    def test_a_frontier_failure_is_verified_too(self):
        """fail_to_frontier rewrites, so it is an assignment like any other and
        it has to be checked against what actually ran.

        THIS TEST USED TO HAND-BUILD ITS OWN ROW -- `{"decision":
        "fail_to_frontier", "tier": "opus5"}` -- and the hook has never
        produced one. `JQ_FRONTIER` writes **`tier: null`**, because that
        branch is reached exactly when `config/tiers.json` could not be read,
        so there is no tier key it could honestly name. Under the real row,
        `verify()` read `if not tier -> not_routed` and classified every real
        fail-to-frontier assignment as "we deliberately left the input alone":
        the branch that bills FRONTIER RATES scored as the control arm, and
        was invisible.

        So the row is now GENERATED BY RUNNING THE HOOK. A fixture that the
        writer cannot produce tests the fixture, not the writer.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        hook = SandboxHook(Path(tmp.name))
        (hook.root / "config" / "tiers.json").write_text("{ not json")
        rc, out = hook.run(payload("Explore"))
        self.assertEqual(rc, 0)

        row = hook.ledger()[-1]
        # The shape the hook actually emits, asserted before it is relied on.
        self.assertEqual(row["decision"], "fail_to_frontier")
        self.assertIsNone(row["tier"])
        self.assertEqual(row["assigned_alias"], "opus")
        self.assertEqual(
            json.loads(out)["hookSpecificOutput"]["updatedInput"]["model"], "opus")

        # Honoured: the frontier model is what ran.
        good = al.verify([row], {row["tool_use_id"]: "claude-opus-5[1m]"},
                         self.config)
        self.assertEqual(good["summary"]["honoured"], 1)
        self.assertEqual(good["summary"]["not_routed"], 0,
                         "a fail-to-frontier row is NOT the control arm")

        # Overridden: we rewrote to frontier and something else won.
        bad = al.verify([row], {row["tool_use_id"]: "claude-sonnet-5"},
                        self.config)
        self.assertEqual(bad["summary"]["overridden"], 1)
        self.assertEqual(bad["summary"]["not_routed"], 0)
        self.assertEqual(bad["detail"][0]["tier"], "opus5",
                         "the tier is recovered from the alias the row does carry")

    def test_a_routed_row_with_no_alias_rewrote_nothing_and_is_not_counted(self):
        """The mirror image, and the reason the test above is keyed on
        `assigned_alias` rather than on `decision` alone. A `routed` row with a
        null alias is a pre-W5 ledger row: the hook can no longer emit one, but
        the ones already on disk must not be counted as assignments that
        happened."""
        out = al.verify(
            [{"tool_use_id": "z", "decision": "routed", "tier": "haiku45",
              "assigned_alias": None}],
            {"z": "claude-opus-5"}, self.config)
        self.assertEqual(out["summary"]["not_routed"], 1)
        self.assertEqual(out["routed_total"], 0)

    def test_a_rewrite_we_cannot_join_to_a_prefix_is_never_read_as_honoured(self):
        """An alias no tier in `config` claims. The join cannot be made, and
        `unverifiable` says that -- rather than `honoured`, which would be a
        lie, or `not_routed`, which would hide a rewrite that did happen."""
        out = al.verify(
            [{"tool_use_id": "q", "decision": "fail_to_frontier", "tier": None,
              "assigned_alias": "a-tier-nobody-configured"}],
            {"q": "claude-opus-5"}, self.config)
        self.assertEqual(out["summary"]["unverifiable"], 1)
        self.assertEqual(out["summary"]["honoured"], 0)
        self.assertEqual(out["summary"]["not_routed"], 0)
        self.assertEqual(out["routed_total"], 1)


class TestTheLedgerRowSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hook = SandboxHook(Path(self.tmp.name))
        self.addCleanup(self.tmp.cleanup)

    def test_the_hooks_row_and_the_python_row_have_the_same_keys(self):
        """Two writers of one schema, kept honest the same way the rule is."""
        self.hook.run(payload("Explore"))
        from_hook = self.hook.ledger()[-1]
        decision = tier_map.decide(payload("Explore")["tool_input"], tier_map.load())
        from_python = al.ledger_row(
            decision, timestamp="t", session_id="s", tool_use_id="u",
            config_sha256="x", config_version="v", hook_ms=1.0,
            # JEV-57. `project` is passed because THE HOOK NOW EMITS IT, and
            # that is the whole point of this assertion: `LEDGER_SCHEMA` names
            # what the deployed writer writes, so the day the two disagree --
            # in either direction -- this test goes red and names both files.
            project="p")
        self.assertEqual(sorted(from_hook), sorted(from_python))
        self.assertEqual(from_hook["schema"], al.LEDGER_SCHEMA)
        self.assertEqual(from_hook["schema"], al.LEDGER_SCHEMA_V2)

    def test_the_hooks_row_records_the_project_the_decision_was_made_in(self):
        """JEV-57. The ledger is shared by every repo jev is installed in, so a
        row that cannot name its repo pools one project's delegations with
        another's -- the JEV-32 confound, and it would look like a result.

        Recorded RAW from $CLAUDE_PROJECT_DIR, never the `pwd -P`-resolved
        path: a worktree's path is not its repository's path, and collapsing
        the two is an analysis decision this hook cannot make.
        """
        self.hook.run(payload("Explore"))
        self.assertEqual(self.hook.ledger()[-1]["project"], str(self.hook.root))

    def test_a_fail_to_frontier_row_names_its_project_too(self):
        """The fallback path needs it just as much: an unattributable
        frontier-rate assignment is the expensive branch pooling silently."""
        (self.hook.root / "config" / "tiers.json").write_text("{ not json")
        self.hook.run(payload("Explore"))
        row = self.hook.ledger()[-1]
        self.assertEqual(row["decision"], "fail_to_frontier")
        self.assertEqual(row["project"], str(self.hook.root))
        self.assertEqual(row["schema"], al.LEDGER_SCHEMA_V2)

    def test_the_ledger_is_append_only_across_invocations(self):
        for _ in range(3):
            self.hook.run(payload("Explore"))
        self.assertEqual(len(self.hook.ledger()), 3)


class TestTheShippedHookUnderTheRepoByteIdentityOracle(unittest.TestCase):
    """The SHIPPED hook, run through `src/hook_dispatch.py`.

    Everything else in this file drives the hook through a subprocess and a
    parser written here. `tests/reversibility.sh` sections 3c/3d do use the
    oracle, but against a FIXTURE of roughly the right shape, built inline --
    not against `hooks/agent_route_actuator.sh`. So until this class existed,
    nothing had run the thing that actually ships through the model of Claude
    Code's documented PreToolUse dispatch, which is the repo's designated
    definition of "the tool input that survives".

    Byte-identity here means what `hook_dispatch.canonical` means:
    `json.dumps(sort_keys=True, separators=(",",":"))` of the resolved
    `tool_input`. Key order is not part of the claim; the set of keys and their
    exact values is.
    """

    def setUp(self):
        sys.path.insert(0, str(ROOT / "src"))
        import hook_dispatch  # noqa: E402
        self.dispatch = hook_dispatch
        self.tmp = tempfile.TemporaryDirectory()
        self.sandbox = Path(self.tmp.name).resolve()
        SandboxHook(self.sandbox)
        (self.sandbox / "hooks").mkdir(exist_ok=True)
        shutil.copy(HOOK, self.sandbox / "hooks" / HOOK.name)
        (self.sandbox / "hooks" / HOOK.name).chmod(0o755)
        self.settings = {
            "hooks": {
                "PreToolUse": [{
                    "matcher": "Agent",
                    "hooks": [{
                        "type": "command",
                        "command": f'"$CLAUDE_PROJECT_DIR/hooks/{HOOK.name}"',
                        "timeout": 10,
                    }],
                }]
            }
        }
        self.addCleanup(self.tmp.cleanup)

    def resolve(self, p):
        # run_pre_tool_use does not set HOME, and the actuator's GLOBAL kill
        # switch is anchored on it. Without this the hook would read the real
        # $HOME and the test would depend on the developer's machine.
        env = dict(os.environ)
        env["HOME"] = str(self.sandbox)
        return self.dispatch.run_pre_tool_use(
            self.settings, p, self.sandbox, env=env)

    def test_switch_off_the_oracle_sees_exactly_one_changed_field(self):
        p = payload("Explore")
        expected = dict(p["tool_input"], model="haiku")
        result = self.resolve(p)
        self.assertFalse(result["blocked"])
        self.assertEqual(result["resolved_canonical"], self.dispatch.canonical(expected))
        self.assertEqual(result["trace"][-1]["outcome"], "rewrote updatedInput")

    def test_switch_on_the_resolved_input_is_byte_identical_to_vanilla(self):
        """OFF must mean 'stop deciding, and let the default happen exactly as
        it would have' -- not merely 'stop recording'. A hook that exits early
        still ran, and only the surviving tool input can tell the two apart."""
        (self.sandbox / ".jev-disabled").write_text("")
        p = payload("Explore")
        result = self.resolve(p)
        self.assertEqual(result["resolved_canonical"],
                         self.dispatch.canonical(p["tool_input"]))
        self.assertFalse(result["blocked"])

    def test_the_actuator_never_blocks_a_tool_call_whatever_it_is_fed(self):
        """Fail safe is absolute: this hook may change what runs, and may never
        stop it running."""
        for p in (payload("Explore"), payload("general-purpose"), payload(None),
                  {"tool_name": "Agent", "tool_input": "not-an-object"},
                  {"tool_name": "Agent", "tool_input": {}}):
            with self.subTest(p=p):
                self.assertFalse(self.resolve(p)["blocked"])

    def test_a_non_routing_decision_leaves_the_oracle_seeing_vanilla(self):
        p = payload("general-purpose")
        self.assertEqual(self.resolve(p)["resolved_canonical"],
                         self.dispatch.canonical(p["tool_input"]))


class TestInheritIsNotACallerChoice(unittest.TestCase):
    """`model: "inherit"` means 'the parent's model'. It expresses no tier
    preference, so it must not suppress routing the way a real choice does --
    otherwise those spawns are excluded forever while it looks like deference."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hook = SandboxHook(Path(self.tmp.name))
        self.config = tier_map.load()
        self.addCleanup(self.tmp.cleanup)

    def test_inherit_is_routed_while_a_real_alias_is_kept(self):
        inherited = tier_map.decide(
            {"prompt": "p", "subagent_type": "Explore", "model": "inherit"}, self.config)
        self.assertEqual(inherited.outcome, "routed")
        self.assertEqual(inherited.alias, "haiku")
        # ...and it is still recorded, so nothing is hidden.
        self.assertEqual(inherited.original_model, "inherit")

        chosen = tier_map.decide(
            {"prompt": "p", "subagent_type": "Explore", "model": "opus"}, self.config)
        self.assertEqual(chosen.outcome, "explicit_model_kept")

    def test_the_hook_agrees_with_python_about_inherit(self):
        rc, out = self.hook.run(payload("Explore", model="inherit"))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["updatedInput"]["model"],
                         "haiku")
        self.assertEqual(self.hook.ledger()[-1]["original_model"], "inherit")


class TestScopeDisciplineForTheActuator(unittest.TestCase):
    """Building the actuator is this ticket. Arming it is not."""

    def test_the_actuator_is_not_registered_anywhere(self):
        for settings in (ROOT / ".claude" / "settings.local.json",
                         ROOT / ".claude" / "settings.json"):
            if settings.is_file():
                self.assertNotIn("agent_route_actuator", settings.read_text())

    def test_the_surface_is_still_off(self):
        import config_loader as cl
        self.assertEqual(cl.surface_mode("agent_route"), "off")

    def test_nothing_in_this_repo_writes_to_the_users_global_settings(self):
        """Non-negotiable 3: nothing is ever written to ~/.claude/settings.json.
        The actuator's GLOBAL kill switch lives next to that file, so this is
        worth re-asserting now that a hook references $HOME at all."""
        src = HOOK.read_text()
        self.assertNotIn("settings.json", src)
        # The only $HOME reference is a read-only kill-switch test.
        home_lines = [l for l in src.splitlines()
                      if "$HOME" in l and not l.lstrip().startswith("#")]
        self.assertTrue(home_lines)
        for line in home_lines:
            self.assertTrue(line.lstrip().startswith("[") or line.lstrip().startswith("{"),
                            f"a $HOME reference that is not a bare test: {line}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
