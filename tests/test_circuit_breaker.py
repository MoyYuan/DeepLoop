"""Tests for circuit breaker pattern and _update_patterns_file."""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.recursive_agent_runtime import _update_patterns_file


class TestCircuitBreakerStateMachine(unittest.TestCase):
    """Test the circuit breaker pattern in isolation via the agent loop state dict.

    The circuit breaker in run_recursive_agent_loop works as follows:
    - On failure/blocked: consecutive_failures += 1
    - If consecutive_failures >= max_consecutive_failures (3): reset counter,
      clear pending_action, advance action_cursor
    - On success: consecutive_failures = 0
    """

    def setUp(self):
        self.state = {
            "consecutive_failures": 0,
            "pending_action": {"task": "some task"},
            "action_cursor": 0,
        }
        self.max_consecutive_failures = 3

    def _simulate_failure(self):
        """Simulate one iteration failure (copies the circuit breaker logic)."""
        self.state["consecutive_failures"] = (
            int(self.state.get("consecutive_failures", 0)) + 1
        )
        if self.state["consecutive_failures"] >= self.max_consecutive_failures:
            self.state["consecutive_failures"] = 0
            self.state["pending_action"] = None
            if self.state.get("selected_action_index") is not None:
                self.state["action_cursor"] = self.state["selected_action_index"] + 1

    def _simulate_success(self):
        """Simulate a successful iteration."""
        self.state["consecutive_failures"] = 0

    def test_consecutive_failures_increment(self):
        """Three consecutive failures increments counter to 3."""
        self.assertEqual(self.state["consecutive_failures"], 0)

        self._simulate_failure()
        self.assertEqual(self.state["consecutive_failures"], 1)
        self.assertIsNotNone(self.state["pending_action"])

        self._simulate_failure()
        self.assertEqual(self.state["consecutive_failures"], 2)
        self.assertIsNotNone(self.state["pending_action"])

        self._simulate_failure()
        # Circuit breaker should have tripped
        self.assertEqual(self.state["consecutive_failures"], 0)
        self.assertIsNone(self.state["pending_action"])

    def test_circuit_breaker_clears_pending_action_and_advances_cursor(self):
        """When circuit breaker trips, pending_action is cleared and cursor advanced."""
        self.state["selected_action_index"] = 2
        self.state["pending_action"] = {"task": "my task"}

        # Simulate 3 failures
        for _ in range(3):
            self._simulate_failure()

        # Circuit breaker reset counter, cleared pending, advanced cursor
        self.assertEqual(self.state["consecutive_failures"], 0)
        self.assertIsNone(self.state["pending_action"])
        self.assertEqual(self.state["action_cursor"], self.state["selected_action_index"] + 1)

    def test_success_resets_counter(self):
        """A success after failures resets the counter to 0."""
        self.state["consecutive_failures"] = 2
        self._simulate_success()
        self.assertEqual(self.state["consecutive_failures"], 0)
        self.assertIsNotNone(self.state["pending_action"])  # untouched

    def test_success_after_two_failures(self):
        """Simulate 2 failures then a success: counter resets to 0."""
        self._simulate_failure()  # 1
        self._simulate_failure()  # 2
        self.assertEqual(self.state["consecutive_failures"], 2)

        self._simulate_success()
        self.assertEqual(self.state["consecutive_failures"], 0)
        # pending_action and cursor should be untouched
        self.assertIsNotNone(self.state["pending_action"])
        self.assertEqual(self.state["action_cursor"], 0)

    def test_no_failure_does_not_increment(self):
        """Counter stays at 0 when there are no failures."""
        self._simulate_success()
        self.assertEqual(self.state["consecutive_failures"], 0)
        self._simulate_success()
        self.assertEqual(self.state["consecutive_failures"], 0)

    def test_state_dict_field_behavior(self):
        """Verify the state dict's consecutive_failures field behaves as expected."""
        # Start at 0
        self.assertEqual(self.state.get("consecutive_failures", 0), 0)
        # Increment
        self.state["consecutive_failures"] = (
            int(self.state.get("consecutive_failures", 0)) + 1
        )
        self.assertEqual(self.state["consecutive_failures"], 1)
        # Reset
        self.state["consecutive_failures"] = 0
        self.assertEqual(self.state["consecutive_failures"], 0)


class TestUpdatePatternsFile(unittest.TestCase):
    """Test _update_patterns_file for writing findings to a durable patterns file."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.progress_path = self.temp_dir / "progress.md"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_write_three_findings(self):
        """Writing 3 findings includes all of them in the file."""
        findings = ["Found pattern A", "Found pattern B", "Found pattern C"]
        _update_patterns_file(self.temp_dir, findings)

        content = (self.temp_dir / "progress.md").read_text(encoding="utf-8")
        for finding in findings:
            self.assertIn(finding, content)

    def test_timestamp_header_present(self):
        """Each entry has a timestamp header in the format ## Progress — YYYY-MM-DDTHH:MM:SS."""
        findings = ["Some finding"]
        _update_patterns_file(self.temp_dir, findings)

        content = self.progress_path.read_text(encoding="utf-8")
        self.assertTrue(
            re.search(r"## Progress — \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", content)
        )

    def test_exceeds_max_patterns_trims_oldest(self):
        """Writing 35 progress findings exceeds default max of 30, trims oldest."""
        for i in range(35):
            _update_patterns_file(self.temp_dir, [f"Finding {i}"])

        content = self.progress_path.read_text(encoding="utf-8")

        # The first entries should be trimmed
        self.assertNotIn("Finding 0", content)
        self.assertNotIn("Finding 4", content)
        # The last entry should be present
        self.assertIn("Finding 34", content)
        # Count the progress headers (max 30)
        header_count = len(re.findall(r"## Progress —", content))
        self.assertEqual(header_count, 30)

    def test_empty_findings_no_change(self):
        """Empty findings list leaves the file unchanged (or empty)."""
        # File doesn't exist yet — nothing is written
        _update_patterns_file(self.temp_dir, [])
        self.assertFalse(self.progress_path.exists())

        # File exists but empty findings — content preserved
        self.progress_path.write_text("Existing content\n", encoding="utf-8")
        _update_patterns_file(self.temp_dir, [])
        self.assertEqual(
            self.progress_path.read_text(encoding="utf-8"), "Existing content\n"
        )

    def test_multiple_batches_append(self):
        """Calling _update_patterns_file twice appends new entries."""
        _update_patterns_file(self.temp_dir, ["First finding"])
        _update_patterns_file(self.temp_dir, ["Second finding"])

        content = self.progress_path.read_text(encoding="utf-8")
        self.assertIn("First finding", content)
        self.assertIn("Second finding", content)
        # Two separate progress headers
        self.assertEqual(len(re.findall(r"## Progress —", content)), 2)

    def test_repeated_findings_not_deduplicated(self):
        """The same finding text can appear in separate entries."""
        _update_patterns_file(self.temp_dir, ["Duplicate text"])
        _update_patterns_file(self.temp_dir, ["Duplicate text"])

        content = (self.temp_dir / "progress.md").read_text(encoding="utf-8")
        # Should appear twice (two separate entries)
        self.assertEqual(content.count("Duplicate text"), 2)


if __name__ == "__main__":
    unittest.main()
