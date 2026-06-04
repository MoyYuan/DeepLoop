"""Tests for deeploop.mission.agent_dialogue.AgentDialogue."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.mission.agent_dialogue import AgentDialogue, DialogueTurn


class AgentDialogueTests(unittest.TestCase):
    """Test AgentDialogue."""

    def setUp(self):
        self.roles = ["designer", "executor", "critic"]
        self.dialogue = AgentDialogue(roles=self.roles)

    # ------------------------------------------------------------------
    # add_turn
    # ------------------------------------------------------------------

    def test_add_turn_returns_dialogue_turn(self):
        """add_turn returns a DialogueTurn with correct fields."""
        turn = self.dialogue.add_turn(
            role="designer",
            content="Let's use a transformer.",
        )
        self.assertIsInstance(turn, DialogueTurn)
        self.assertEqual(turn.role, "designer")
        self.assertEqual(turn.content, "Let's use a transformer.")
        self.assertEqual(turn.artifacts, [])
        self.assertIsNotNone(turn.timestamp)

    def test_add_turn_appends_to_turns(self):
        """add_turn appends to the internal turns list."""
        self.dialogue.add_turn("designer", "First")
        self.dialogue.add_turn("executor", "Second")
        self.assertEqual(len(self.dialogue.turns), 2)

    def test_add_turn_with_artifacts(self):
        """add_turn stores artifacts when provided."""
        turn = self.dialogue.add_turn(
            role="executor",
            content="Here is the code.",
            artifacts=["/path/to/code.py"],
        )
        self.assertEqual(turn.artifacts, ["/path/to/code.py"])

    # ------------------------------------------------------------------
    # last_turn
    # ------------------------------------------------------------------

    def test_last_turn_returns_most_recent(self):
        """last_turn returns the most recently added turn."""
        self.dialogue.add_turn("designer", "First")
        last = self.dialogue.add_turn("critic", "Second")
        self.assertIs(self.dialogue.last_turn(), last)
        self.assertEqual(self.dialogue.last_turn().content, "Second")

    def test_last_turn_empty_dialogue(self):
        """last_turn returns None for an empty dialogue."""
        self.assertIsNone(self.dialogue.last_turn())

    # ------------------------------------------------------------------
    # summary
    # ------------------------------------------------------------------

    def test_summary_contains_all_turns(self):
        """summary() includes all turns with index and role."""
        self.dialogue.add_turn("designer", "Plan A")
        self.dialogue.add_turn("executor", "Code B")
        self.dialogue.add_turn("critic", "Review C")
        summary = self.dialogue.summary()
        self.assertIn("1. [designer] Plan A", summary)
        self.assertIn("2. [executor] Code B", summary)
        self.assertIn("3. [critic] Review C", summary)

    def test_summary_shows_artifact_count(self):
        """summary() includes artifact count when artifacts exist."""
        self.dialogue.add_turn(
            "executor",
            "Code",
            artifacts=["a.py", "b.py"],
        )
        summary = self.dialogue.summary()
        self.assertIn("(2 artifact(s))", summary)

    def test_summary_empty_dialogue(self):
        """summary() returns a placeholder for empty dialogue."""
        self.assertEqual(self.dialogue.summary(), "[no dialogue turns]")

    # ------------------------------------------------------------------
    # protocol_message
    # ------------------------------------------------------------------

    def test_protocol_message_plan(self):
        """protocol_message produces a structured PLAN message."""
        self.dialogue.add_turn("designer", "Use attention mechanism")
        msg = self.dialogue.protocol_message("designer", "PLAN")
        expected = (
            "<protocol role='designer' type=PLAN>\n"
            "Use attention mechanism\n"
            "</protocol>"
        )
        self.assertEqual(msg, expected)

    def test_protocol_message_code(self):
        """protocol_message produces a structured CODE message."""
        self.dialogue.add_turn("executor", "import torch")
        msg = self.dialogue.protocol_message("executor", "CODE")
        expected = (
            "<protocol role='executor' type=CODE>\n"
            "import torch\n"
            "</protocol>"
        )
        self.assertEqual(msg, expected)

    def test_protocol_message_review(self):
        """protocol_message produces a structured REVIEW message."""
        self.dialogue.add_turn("critic", "Looks good")
        msg = self.dialogue.protocol_message("critic", "REVIEW")
        expected = (
            "<protocol role='critic' type=REVIEW>\n"
            "Looks good\n"
            "</protocol>"
        )
        self.assertEqual(msg, expected)

    def test_protocol_message_empty_dialogue(self):
        """protocol_message uses '[dialogue start]' when no turns exist."""
        msg = self.dialogue.protocol_message("designer", "PLAN")
        expected = (
            "<protocol role='designer' type=PLAN>\n"
            "[dialogue start]\n"
            "</protocol>"
        )
        self.assertEqual(msg, expected)

    def test_protocol_message_invalid_type(self):
        """protocol_message raises ValueError for unknown message type."""
        with self.assertRaises(ValueError):
            self.dialogue.protocol_message("designer", "INVALID")

    def test_protocol_message_lowercase_type(self):
        """protocol_message accepts lowercase message_type and uppercases it."""
        self.dialogue.add_turn("designer", "hello")
        msg = self.dialogue.protocol_message("designer", "plan")
        self.assertIn("type=PLAN", msg)

    # ------------------------------------------------------------------
    # to_dict / from_dict round-trip
    # ------------------------------------------------------------------

    def test_round_trip_preserves_turns(self):
        """to_dict() / from_dict() round-trip preserves all turns."""
        self.dialogue.add_turn("designer", "Plan", artifacts=["plan.md"])
        self.dialogue.add_turn("executor", "Implement")
        self.dialogue.add_turn("critic", "Review", artifacts=["review.txt"])

        data = self.dialogue.to_dict()
        restored = AgentDialogue.from_dict(data)

        self.assertEqual(len(restored.turns), 3)
        for original, restored_turn in zip(self.dialogue.turns, restored.turns):
            self.assertEqual(original.role, restored_turn.role)
            self.assertEqual(original.content, restored_turn.content)
            self.assertEqual(original.artifacts, restored_turn.artifacts)
            self.assertEqual(original.timestamp, restored_turn.timestamp)

    def test_round_trip_preserves_roles(self):
        """to_dict() / from_dict() round-trip preserves the roles list."""
        data = self.dialogue.to_dict()
        restored = AgentDialogue.from_dict(data)
        self.assertEqual(restored.roles, ["designer", "executor", "critic"])

    def test_round_trip_empty_dialogue(self):
        """to_dict() / from_dict() round-trip works for empty dialogue."""
        data = self.dialogue.to_dict()
        restored = AgentDialogue.from_dict(data)
        self.assertEqual(len(restored.turns), 0)
        self.assertEqual(restored.roles, ["designer", "executor", "critic"])
