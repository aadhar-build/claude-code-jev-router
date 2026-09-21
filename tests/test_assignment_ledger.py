#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""JEV-57: the assignment ledger has to be able to tell one repo from another.

`jev` installs PER PROJECT; since W2 the ledger lives in ONE directory under
`$JEV_HOME`, shared by every repo jev is installed in. Until this ticket the
row schema had no `project`, so `verify()` could not partition and two repos'
tasks pooled into one rate -- the JEV-32 confound wearing a different hat.

Everything here is in-process and reads no live state. The hook's own emission
of `project` is a separate change (`hooks/agent_route_actuator.sh`, owned
elsewhere this wave); what is pinned here is the reader's behaviour, which has
to be correct BEFORE a second repo installs, not after.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pyversion  # noqa: E402

pyversion.require()

import assignment_ledger as al  # noqa: E402
import tier_map  # noqa: E402


CONFIG = {
    "tiers": {
        "haiku45": {"alias": "haiku", "resolved_prefix": "claude-haiku-4-5"},
        "opus5": {"alias": "opus", "resolved_prefix": "claude-opus-5"},
    },
    "frontier_tier": "opus5",
}


def row(tool_use_id: str, project: str | None = None, **over) -> dict:
    r = {
        "tool_use_id": tool_use_id,
        "decision": "routed",
        "tier": "haiku45",
        "assigned_alias": "haiku",
    }
    if project is not None:
        r["project"] = project
    r.update(over)
    return r


class TestTheRowCarriesItsProject(unittest.TestCase):
    def _decision(self) -> tier_map.Decision:
        return tier_map.decide({"subagent_type": "Explore"}, tier_map.load())

    def test_a_row_given_a_project_is_v2_and_carries_it(self):
        r = al.ledger_row(
            self._decision(), timestamp="t", session_id="s", tool_use_id="u",
            config_sha256="x", config_version="v", hook_ms=1.0,
            project="/Users/x/projects/alpha")
        self.assertEqual(r["schema"], al.LEDGER_SCHEMA_V2)
        self.assertEqual(r["project"], "/Users/x/projects/alpha")

    def test_a_row_with_no_project_is_v1_and_does_not_invent_the_key(self):
        """The schema version is the fence. A `-v2` row without a project would
        be a version that claims a field the row does not carry, which is worse
        than no version at all."""
        r = al.ledger_row(
            self._decision(), timestamp="t", session_id="s", tool_use_id="u",
            config_sha256="x", config_version="v", hook_ms=1.0)
        self.assertEqual(r["schema"], al.LEDGER_SCHEMA_V1)
        self.assertNotIn("project", r)

    def test_the_deployed_schema_constant_tracks_the_hook_not_the_reader(self):
        """`LEDGER_SCHEMA` names what `hooks/agent_route_actuator.sh` writes.
        It flips to `-v2` in the same change that adds `project` to the hook's
        two jq row objects -- and `test_agent_actuator.py`'s key-parity test is
        what fails if the two ever get out of order."""
        self.assertEqual(al.LEDGER_SCHEMA, al.LEDGER_SCHEMA_V1)


class TestPartitioning(unittest.TestCase):
    def test_rows_are_grouped_by_the_repo_the_decision_was_made_in(self):
        parts = al.partition_by_project(
            [row("a", "/repo/one"), row("b", "/repo/two"), row("c", "/repo/one")])
        self.assertEqual(sorted(parts), ["/repo/one", "/repo/two"])
        self.assertEqual(len(parts["/repo/one"]), 2)

    def test_legacy_rows_get_their_own_partition_and_are_never_backfilled(self):
        """THE ONE THAT MATTERS for the migration decision. A `-v1` row never
        carried a project and cannot be given one honestly: the ledger is
        shared, so "it must have been this repo" is exactly the inference that
        is unsafe. It lands in `<v1:no-project>` and stays there."""
        parts = al.partition_by_project([row("a", "/repo/one"), row("b")])
        self.assertIn(al.LEGACY_PARTITION, parts)
        self.assertEqual(len(parts["/repo/one"]), 1)
        self.assertNotIn(al.LEGACY_PARTITION, ("/repo/one",))

    def test_an_empty_project_string_is_missing_not_a_repo(self):
        """`$CLAUDE_PROJECT_DIR` is empty when Claude Code did not set it, and
        "" is not a repository."""
        parts = al.partition_by_project([row("a", "")])
        self.assertEqual(list(parts), [al.LEGACY_PARTITION])


class TestVerifyRefusesToPool(unittest.TestCase):
    def test_two_projects_and_no_instruction_is_a_refusal_not_a_number(self):
        """A confounded rate is indistinguishable from a real one once it is a
        number on a page, so this raises rather than returning something."""
        rows = [row("a", "/repo/one"), row("b", "/repo/two")]
        with self.assertRaises(al.ProjectsWouldBePooled) as caught:
            al.verify(rows, {}, CONFIG)
        self.assertEqual(sorted(caught.exception.found), ["/repo/one", "/repo/two"])

    def test_a_legacy_row_beside_a_named_one_also_refuses(self):
        """Two partitions is two partitions. `<v1:no-project>` is not a free
        pass to pool -- it is the case the fence was built for."""
        with self.assertRaises(al.ProjectsWouldBePooled):
            al.verify([row("a", "/repo/one"), row("b")], {}, CONFIG)

    def test_one_project_needs_no_instruction(self):
        """The normal single-install case must not become ceremony."""
        out = al.verify([row("a", "/repo/one")], {"a": "claude-haiku-4-5"}, CONFIG)
        self.assertEqual(out["project"], "/repo/one")
        self.assertEqual(out["honour_rate"], 1.0)

    def test_naming_a_project_scores_only_that_project(self):
        rows = [row("a", "/repo/one"), row("b", "/repo/two"), row("c")]
        out = al.verify(rows, {"a": "claude-haiku-4-5", "b": "claude-haiku-4-5"},
                        CONFIG, project="/repo/one")
        self.assertEqual(out["rows_scored"], 1)
        self.assertEqual(out["routed_total"], 1)
        self.assertEqual(out["summary"]["honoured"], 1)

    def test_what_was_excluded_is_reported_rather_than_assumed(self):
        """An exclusion nobody can see is an exclusion nobody can argue with."""
        rows = [row("a", "/repo/one"), row("b", "/repo/two"), row("c")]
        out = al.verify(rows, {}, CONFIG, project="/repo/one")
        self.assertEqual(sorted(out["projects_excluded"]),
                         ["/repo/two", al.LEGACY_PARTITION])

    def test_pooling_is_available_but_has_to_be_asked_for_by_name(self):
        rows = [row("a", "/repo/one"), row("b", "/repo/two")]
        out = al.verify(rows, {"a": "claude-haiku-4-5"}, CONFIG, pool_projects=True)
        self.assertTrue(out["pooled"])
        self.assertIsNone(out["project"])
        self.assertEqual(out["rows_scored"], 2)
        self.assertEqual(out["honour_rate"], 0.5)

    def test_a_pooled_result_names_every_partition_it_swallowed(self):
        rows = [row("a", "/repo/one"), row("b", "/repo/two"), row("c")]
        out = al.verify(rows, {}, CONFIG, pool_projects=True)
        self.assertEqual(sorted(out["projects_in_ledger"]),
                         ["/repo/one", "/repo/two", al.LEGACY_PARTITION])

    def test_an_empty_ledger_is_not_an_error(self):
        out = al.verify([], {}, CONFIG)
        self.assertIsNone(out["project"])
        self.assertIsNone(out["honour_rate"])

    def test_the_result_always_names_its_own_scope(self):
        """Every return path carries `project`/`pooled`, so a caller that
        prints a rate without its scope had to discard it deliberately."""
        for kwargs in ({}, {"project": "/repo/one"}, {"pool_projects": True}):
            with self.subTest(kwargs=kwargs):
                out = al.verify([row("a", "/repo/one")], {}, CONFIG, **kwargs)
                self.assertIn("project", out)
                self.assertIn("pooled", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
