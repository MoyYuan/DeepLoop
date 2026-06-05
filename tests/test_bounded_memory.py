"""Tests for the BoundedMemory two-tier fixed-size memory module."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.bounded_memory import BoundedMemory


class BoundedMemoryTests(unittest.TestCase):
    """Suite of tests for ``BoundedMemory``."""

    DEFAULTS = dict(
        max_brief_chars=3000,
        max_log_chars=2000,
        max_decisions=15,
    )

    # ------------------------------------------------------------------
    # Basic construction
    # ------------------------------------------------------------------

    def test_empty_brief_and_log(self) -> None:
        """Edge case: empty brief and no results/decisions recorded."""
        mem = BoundedMemory(project_brief="", **self.DEFAULTS)
        self.assertEqual(mem.project_brief, "")
        self.assertEqual(mem.memory_log(), "### Key Results")
        block = mem.context_block()
        self.assertIn("## Project Brief", block)
        self.assertIn("## Memory Log", block)
        self.assertLessEqual(len(block), 3000 + 2000 + 200)

    def test_brief_truncated_at_max(self) -> None:
        """Very long briefs are truncated to max_brief_chars."""
        long_brief = "x" * 5000
        mem = BoundedMemory(project_brief=long_brief, max_brief_chars=100, max_log_chars=2000)
        self.assertEqual(len(mem.project_brief), 100)

    # ------------------------------------------------------------------
    # Recording results
    # ------------------------------------------------------------------

    def test_record_result(self) -> None:
        """Recording results appends them to the key results list."""
        mem = BoundedMemory(project_brief="Brief", **self.DEFAULTS)
        mem.record_result("Result A")
        mem.record_result("Result B")
        log = mem.memory_log()
        self.assertIn("Result A", log)
        self.assertIn("Result B", log)

    def test_record_result_auto_compresses_when_over_budget(self) -> None:
        """When results exceed max_log_chars, oldest are compressed."""
        mem = BoundedMemory(
            project_brief="Brief",
            max_brief_chars=3000,
            max_log_chars=100,
            max_decisions=15,
        )
        # Each result is a long string so we trigger compression.
        for i in range(20):
            mem.record_result(f"Long result number {i} that takes up significant space " * 3)

        log = mem.memory_log()
        self.assertLessEqual(len(log), 100)
        self.assertIn("earlier results summarized", log)

    def test_compression_summarizes_oldest_results(self) -> None:
        """After compression, the summary line appears before the remaining results."""
        mem = BoundedMemory(
            project_brief="Brief",
            max_brief_chars=3000,
            max_log_chars=500,
            max_decisions=15,
        )
        for i in range(10):
            mem.record_result(f"Result number {i} with enough text to eat budget quickly ")

        log = mem.memory_log()
        self.assertLessEqual(len(log), 500)
        # The compressed summary should be present.
        self.assertRegex(log, r"\(\d+ earlier results summarized\)")

    # ------------------------------------------------------------------
    # Recording decisions
    # ------------------------------------------------------------------

    def test_record_decision_rolls_off_at_max(self) -> None:
        """Decisions beyond max_decisions are discarded (oldest first)."""
        mem = BoundedMemory(
            project_brief="Brief",
            max_brief_chars=3000,
            max_log_chars=2000,
            max_decisions=3,
        )
        mem.record_decision("Decision 1")
        mem.record_decision("Decision 2")
        mem.record_decision("Decision 3")
        mem.record_decision("Decision 4")

        log = mem.memory_log()
        self.assertNotIn("Decision 1", log)
        self.assertIn("Decision 2", log)
        self.assertIn("Decision 3", log)
        self.assertIn("Decision 4", log)

    def test_no_decisions_renders_no_decisions_section(self) -> None:
        """When no decisions are recorded, the Recent Decisions section is absent."""
        mem = BoundedMemory(project_brief="Brief", **self.DEFAULTS)
        log = mem.memory_log()
        self.assertNotIn("### Recent Decisions", log)

    # ------------------------------------------------------------------
    # Context block budget guarantees
    # ------------------------------------------------------------------

    def test_context_block_stays_under_budget_after_many_cycles(self) -> None:
        """Simulate 100+ record cycles and verify context_block stays under budget."""
        mem = BoundedMemory(
            project_brief="This is a test project brief for the research mission. "
            "It describes the overall goals and objectives.",
            max_brief_chars=500,
            max_log_chars=500,
            max_decisions=15,
        )

        for i in range(150):
            mem.record_result(
                f"Experiment iteration {i}: fine-tuned with learning rate "
                f"1e-4 and achieved accuracy improvement of "
                f"{0.5 + (i % 100) * 0.01:.2f}% on the validation set."
            )
            if i % 3 == 0:
                mem.record_decision(
                    f"Decision at iteration {i}: proceed with "
                    f"hyperparameter search along the learning rate axis."
                )

            block = mem.context_block()
            # Budget: max_brief_chars + max_log_chars + ~200 formatting overhead
            budget = mem._max_brief_chars + mem._max_log_chars + 200
            self.assertLessEqual(
                len(block),
                budget,
                f"context_block exceeded budget ({len(block)} > {budget}) at iteration {i}",
            )

    def test_context_block_budget_with_defaults(self) -> None:
        """With default budgets, context_block stays within ~5200 chars."""
        mem = BoundedMemory(project_brief="Brief " * 100)
        for i in range(100):
            mem.record_result(f"Result {i}: " + "data " * 20)
            if i % 2 == 0:
                mem.record_decision(f"Decision {i}: " + "choice " * 10)

        block = mem.context_block()
        budget = 3000 + 2000 + 200
        self.assertLessEqual(len(block), budget)

    # ------------------------------------------------------------------
    # String truncation edge case
    # ------------------------------------------------------------------

    def test_memory_log_truncation_when_still_over_budget(self) -> None:
        """If compression cannot get under max_log_chars, the log is
        forcibly truncated with ``...``."""
        mem = BoundedMemory(
            project_brief="Brief",
            max_brief_chars=3000,
            max_log_chars=10,
            max_decisions=2,
        )
        mem.record_result("Very long result that cannot possibly fit")
        log = mem.memory_log()
        self.assertLessEqual(len(log), 10)
        self.assertTrue(log.endswith("..."))

    # ------------------------------------------------------------------
    # Immutability of Tier 1
    # ------------------------------------------------------------------

    def test_project_brief_immutable(self) -> None:
        """project_brief does not change after construction."""
        mem = BoundedMemory(project_brief="Original brief", **self.DEFAULTS)
        mem.record_result("Some result")
        mem.record_decision("Some decision")
        self.assertEqual(mem.project_brief, "Original brief")

    # ------------------------------------------------------------------
    # Debug: internal state consistency
    # ------------------------------------------------------------------

    def test_context_block_includes_both_tiers(self) -> None:
        """context_block contains both the project brief and memory log sections."""
        mem = BoundedMemory(project_brief="Test brief", **self.DEFAULTS)
        mem.record_result("Key finding")
        mem.record_decision("Key decision")
        block = mem.context_block()
        self.assertIn("## Project Brief", block)
        self.assertIn("Test brief", block)
        self.assertIn("## Memory Log", block)
        self.assertIn("Key finding", block)
        self.assertIn("Key decision", block)


if __name__ == "__main__":
    unittest.main()
