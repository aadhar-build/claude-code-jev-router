#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-34: the `agent_route` surface, in shadow -- state, config, questions.

Three things are asserted here and nothing else:

  * the state builder, which is payload-only and must stay that way;
  * the agreement between `config/surfaces.json`, `state_builders.STATE_SOURCE`
    and `paths.SURFACES` for this surface;
  * the question set, including the lint that no anchor or phrasing names a
    model -- the separation `questions/user_prompt/v2.json` argues for.

The surface is built in SHADOW. It is deliberately NOT registered and NOT
enabled, and the last test in this file asserts that, so "we only built the
surface" is a property of the tree rather than a claim in a commit message.
Arming is JEV-52; the actuator is JEV-35.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pyversion  # noqa: E402

pyversion.require()

import config_loader as cl  # noqa: E402
import paths  # noqa: E402
import state_builders as sb  # noqa: E402

SURFACE = "agent_route"

# A PreToolUse/Agent payload. Shape verified against 202 real `Agent` tool_use
# blocks in ~/.claude/projects (tool_input keys: description 202/202, prompt
# 202/202, subagent_type 190/202, model 39/202, run_in_background 8/202) and
# against the documented common hook input fields (session_id, prompt_id,
# transcript_path, cwd, permission_mode, effort, hook_event_name, plus
# agent_id/agent_type inside a subagent).
def payload(
    prompt: str = "Find every call site of drain_once and report which ones swallow exceptions.",
    subagent_type: str | None = "Explore",
    *,
    agent_id: str | None = None,
    agent_type: str | None = None,
    model: str | None = None,
    background: bool | None = None,
    description: str | None = "audit drain_once call sites",
    transcript_path: str | None = None,
) -> dict:
    tool_input: dict = {"prompt": prompt}
    if description is not None:
        tool_input["description"] = description
    if subagent_type is not None:
        tool_input["subagent_type"] = subagent_type
    if model is not None:
        tool_input["model"] = model
    if background is not None:
        tool_input["run_in_background"] = background
    out = {
        "session_id": "s1",
        "prompt_id": "p1",
        "tool_use_id": "toolu_01",
        "hook_event_name": "PreToolUse",
        "cwd": str(ROOT),
        "permission_mode": "auto",
        "effort": {"level": "high"},
        "tool_name": "Agent",
        "tool_input": tool_input,
    }
    if agent_id is not None:
        out["agent_id"] = agent_id
    if agent_type is not None:
        out["agent_type"] = agent_type
    if transcript_path is not None:
        out["transcript_path"] = transcript_path
    return out


class TestAgentRouteState(unittest.TestCase):
    def test_the_builder_exists_and_is_reachable_through_build(self):
        self.assertIn(SURFACE, sb.BUILDERS)
        self.assertIsInstance(sb.build(SURFACE, payload()), str)

    def test_the_task_text_is_in_the_state(self):
        """JEV-54 / SWE-Router: the delegation prompt is the richest thing the
        payload carries and the closest proxy we have to a trajectory."""
        state = sb.build(SURFACE, payload(prompt="UNIQUE_TASK_TEXT"))
        self.assertIn("UNIQUE_TASK_TEXT", state)
        self.assertIn("audit drain_once call sites", state)

    def test_the_requested_agent_type_and_the_invoking_agent_type_are_both_present_and_distinguishable(self):
        """`tool_input.subagent_type` is the type being SPAWNED; the envelope's
        `agent_type` is the type doing the spawning. Rendering them under one
        label would make a nested delegation indistinguishable from a top-level
        one -- the exact confusion `spawn_depth` was supposed to resolve."""
        state = sb.build(
            SURFACE, payload(subagent_type="Explore", agent_id="a1", agent_type="general-purpose"))
        self.assertIn("Explore", state)
        self.assertIn("general-purpose", state)
        spawned = state.index("Explore")
        invoker = state.index("general-purpose")
        self.assertNotEqual(spawned, invoker)
        # Each appears on its own labelled line, and the labels differ.
        lines = {line.split(":")[0] for line in state.splitlines() if ":" in line}
        self.assertTrue(any("Requested agent type" in l for l in lines), lines)
        self.assertTrue(any("Delegating agent" in l for l in lines), lines)

    def test_a_missing_subagent_type_does_not_crash(self):
        """12 of 202 real Agent spawns carry no `subagent_type`. A builder that
        raised on 6% of traffic would drop exactly the unusual spawns."""
        state = sb.build(SURFACE, payload(subagent_type=None))
        self.assertIn("unspecified", state)

    def test_nesting_is_recorded_as_a_proxy_and_never_called_spawn_depth(self):
        """Real spawn depth lives in transcript meta (`baseline.py:266` reads
        `spawnDepth`), which is forbidden at worker time. `agent_id` presence is
        the payload-only proxy for depth 1 vs depth >= 2, and it must be named
        as a proxy."""
        top = sb.build(SURFACE, payload())
        nested = sb.build(SURFACE, payload(agent_id="a1", agent_type="general-purpose"))
        self.assertNotEqual(top, nested)
        self.assertNotIn("spawn_depth", top)
        self.assertIn("top level", top)
        self.assertIn("nested", nested)

    def test_the_invoking_context_reaches_the_state(self):
        state = sb.build(SURFACE, payload())
        self.assertIn("auto", state)          # permission_mode
        self.assertIn(str(ROOT), state)       # cwd
        self.assertIn("high", state)          # effort.level

    def test_the_requested_model_is_NOT_in_the_state(self):
        """37 of 202 real spawns already name `sonnet` and 2 name `opus`. That
        field is the one JEV-35's actuator overwrites; putting it in the state
        would let the classifier copy the answer it is being asked for, and
        would re-couple a model-free score to a model name."""
        state = sb.build(SURFACE, payload(model="sonnet"))
        for token in ("sonnet", "opus", "haiku", "fable"):
            self.assertNotIn(token, state.lower(), token)

    def test_whether_the_task_runs_in_the_background_is_in_the_state(self):
        fg = sb.build(SURFACE, payload(background=False))
        bg = sb.build(SURFACE, payload(background=True))
        self.assertNotEqual(fg, bg)

    def test_an_empty_prompt_is_a_build_error_not_an_empty_state(self):
        with self.assertRaises(sb.StateBuildError):
            sb.build(SURFACE, {"tool_input": {"description": "x"}})

    def test_identical_payloads_hash_identically_and_different_ones_do_not(self):
        self.assertEqual(sb.sha256(sb.build(SURFACE, payload())),
                         sb.sha256(sb.build(SURFACE, payload())))
        self.assertNotEqual(sb.sha256(sb.build(SURFACE, payload("a"))),
                            sb.sha256(sb.build(SURFACE, payload("b"))))

    def test_the_state_is_payload_only_and_survives_the_transcript_growing(self):
        """The unit-level half of GATE 4. The worker builds this state minutes
        after the spawn; nothing it reads may have moved in between."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "t.jsonl"
            transcript.write_text('{"type":"user","message":{"role":"user","content":"past"}}\n')
            p = payload(transcript_path=str(transcript))
            before = sb.sha256(sb.build(SURFACE, p))
            transcript.write_text(
                transcript.read_text()
                + '{"type":"assistant","message":{"role":"assistant","content":"FUTURE"}}\n')
            after = sb.sha256(sb.build(SURFACE, p))
            self.assertEqual(before, after)
            transcript.unlink()
            self.assertEqual(before, sb.sha256(sb.build(SURFACE, p)))

    def test_the_head_of_a_long_prompt_is_what_survives_truncation(self):
        """Unlike a transcript, a delegation prompt leads with the task. The
        cap is not reached by real traffic (max observed 13.8k chars of a
        60k budget), but the direction must be right if it ever is."""
        long_prompt = "HEAD_OF_TASK " + ("x" * sb.MAX_STATE_CHARS) + " TAIL_OF_TASK"
        state = sb.build(SURFACE, payload(prompt=long_prompt))
        self.assertLessEqual(len(state), sb.MAX_STATE_CHARS + 200)
        self.assertIn("HEAD_OF_TASK", state)
        self.assertNotIn("TAIL_OF_TASK", state)


class TestAgentRouteConfig(unittest.TestCase):
    def test_state_source_is_payload_in_both_places(self):
        self.assertEqual(sb.STATE_SOURCE[SURFACE], "payload")
        entry = cl.surfaces()["surfaces"][SURFACE]
        self.assertEqual(entry["state_source"], "payload")

    def test_the_surface_list_agrees_everywhere(self):
        self.assertIn(SURFACE, cl.surface_names())
        self.assertIn(SURFACE, paths.SURFACES)
        self.assertIn(SURFACE, sb.STATE_SOURCE)

    def test_the_hook_event_and_matcher_name_the_tool_that_actually_fires(self):
        entry = cl.surfaces()["surfaces"][SURFACE]
        self.assertEqual(entry["hook_event"], "PreToolUse")
        # 202/202 real delegations in ~/.claude/projects are tool_use `Agent`.
        self.assertEqual(entry["matcher"], "Agent")

    def test_the_question_set_resolves_through_the_loader(self):
        self.assertEqual(cl.surface_question_version(SURFACE), "v1")
        self.assertEqual(cl.question_set_id(SURFACE), "agent_route/v1#a")
        questions = cl.questions_for(SURFACE)
        self.assertIn("complexity", questions)
        self.assertEqual(questions["complexity"]["type"], "score")
        self.assertEqual(len(questions["complexity"]["anchors"]), 5)


class TestAgentRouteQuestions(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(
            (paths.QUESTIONS / SURFACE / "v1.json").read_text(encoding="utf-8"))

    def test_no_anchor_or_phrasing_names_a_model(self):
        """The score must describe the WORK. A model name in an anchor bakes
        one tier lineup into the measurement and makes every row unusable the
        day the choice set changes -- which JEV-28 may still do."""
        banned = ("haiku", "sonnet", "opus", "fable", "gpt", "claude", "llm")
        blob = json.dumps({k: v for k, v in self.spec["questions"].items()}).lower()
        for token in banned:
            self.assertNotIn(token, blob, f"question text names a model: {token}")

    def test_every_question_carries_the_primary_phrasing(self):
        primary = self.spec["primary_phrasing"]
        for name, q in self.spec["questions"].items():
            self.assertIn(primary, q["phrasings"], name)
            self.assertGreaterEqual(len(q["phrasings"]), 2, name)

    def test_the_tier_policy_is_not_one_of_the_questions(self):
        """Tier selection is a policy applied in analysis. It lives beside the
        question set so it is versioned with it, and NOT inside `questions`."""
        self.assertIn("_tier_mapping", self.spec)
        self.assertNotIn("_tier_mapping", self.spec["questions"])
        self.assertNotIn("tier", self.spec["questions"])
        self.assertNotIn("model", self.spec["questions"])


class TestTheSurfaceIsNotArmed(unittest.TestCase):
    """Scope discipline, asserted rather than promised."""

    def test_the_surface_is_off_in_config(self):
        self.assertEqual(cl.surface_mode(SURFACE), "off")

    def test_no_hook_is_registered_for_it(self):
        settings = ROOT / ".claude" / "settings.local.json"
        if not settings.is_file():
            self.skipTest("no settings.local.json in this tree")
        self.assertNotIn(SURFACE, settings.read_text())

    def test_the_only_actuator_is_the_one_jev_35_deliberately_built(self):
        """DELIBERATELY UPDATED BY JEV-35. Read the reason before changing it.

        JEV-34 wrote this test as `test_there_is_no_actuator_in_this_repo_yet`,
        asserting that no hook in `hooks/` contained the string `updatedInput`.
        It was written to FAIL the moment an actuator existed, so that "we only
        built the surface" stayed a property of the tree rather than a claim in
        a commit message. JEV-35 is the ticket that makes an actuator exist, so
        that test has now done its job and fired exactly as designed.

        It is NOT deleted and NOT weakened, because the thing it really guards
        is still live: an actuator must never appear by accident. What changes
        is the assertion it makes. "No hook rewrites input" becomes "EXACTLY ONE
        hook rewrites input, it is the one named in JEV-35, and every other hook
        in this repo is still an observer". A second actuator -- or a rewrite
        quietly added to `capture.sh` -- fails this test just as loudly as the
        first one used to.

        What the surface being ARMED would look like is asserted separately, by
        the two tests above: `mode` is still `off`, and no hook entry exists in
        settings.local.json. Building the actuator is JEV-35; arming it is
        JEV-52.
        """
        ACTUATOR = "agent_route_actuator.sh"
        rewriting = sorted(
            hook.name for hook in (ROOT / "hooks").glob("*.sh")
            if "updatedInput" in hook.read_text())
        self.assertEqual(
            rewriting, [ACTUATOR],
            "exactly one hook may rewrite tool input, and it must be the one "
            f"JEV-35 built; found: {rewriting}")

        # The observers must still be observers. This is the half of the old
        # assertion that survives unchanged.
        for hook in (ROOT / "hooks").glob("*.sh"):
            if hook.name == ACTUATOR:
                continue
            self.assertNotIn("updatedInput", hook.read_text(), hook.name)

    def test_the_actuator_is_built_but_not_armed(self):
        """The scope line JEV-35 must not cross: it may build the thing, and it
        may not register it or flip the surface on."""
        actuator = ROOT / "hooks" / "agent_route_actuator.sh"
        self.assertTrue(actuator.is_file(), "JEV-35's actuator is missing")
        settings = ROOT / ".claude" / "settings.local.json"
        if settings.is_file():
            self.assertNotIn("agent_route_actuator", settings.read_text())
        self.assertEqual(cl.surface_mode(SURFACE), "off")

    def test_the_actuator_carries_the_canonical_kill_switch_block(self):
        """An actuator changes what runs, not merely what is recorded, so the
        switch matters more here than on any observer. Compared against
        capture.sh byte for byte rather than pattern-matched, which is the same
        thing tests/reversibility.sh does when it builds its fixture."""
        import re
        block = re.compile(
            r"# --- jev kill switch: canonical block.*?# --- end jev kill switch[^\n]*\n",
            re.S)
        canonical = block.search((ROOT / "hooks" / "capture.sh").read_text())
        mine = block.search((ROOT / "hooks" / "agent_route_actuator.sh").read_text())
        self.assertIsNotNone(canonical)
        self.assertIsNotNone(mine)
        self.assertEqual(canonical.group(0), mine.group(0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
