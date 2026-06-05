"""Tests for composable stop conditions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.mission.mission_runtime import (
    StopCondition,
    check_stop_conditions,
    default_stop_conditions,
    tokenCountIs,
    inputTokenCountIs,
    outputTokenCountIs,
    costIs,
    accumulate_cost,
    _MODEL_PRICING,
)


class TestStopConditions(unittest.TestCase):
    """Test composable stop conditions for the mission runtime loop."""

    def test_max_iterations_condition(self):
        """A max_iterations condition triggers when iterations_completed >= threshold."""
        condition = StopCondition(
            name="max_iterations",
            check=lambda ms, rs: rs.get("iterations_completed", 0) >= 5,
            reason="Reached 5 iterations.",
        )
        runtime_state = {"iterations_completed": 4}
        should_stop, reason = check_stop_conditions({}, runtime_state, [condition])
        self.assertFalse(should_stop)
        self.assertIsNone(reason)

        runtime_state = {"iterations_completed": 5}
        should_stop, reason = check_stop_conditions({}, runtime_state, [condition])
        self.assertTrue(should_stop)
        self.assertEqual(reason, "Reached 5 iterations.")

        runtime_state = {"iterations_completed": 6}
        should_stop, reason = check_stop_conditions({}, runtime_state, [condition])
        self.assertTrue(should_stop)
        self.assertEqual(reason, "Reached 5 iterations.")

    def test_no_progress_threshold(self):
        """A no_progress condition triggers when stalled iterations reach threshold."""
        condition = StopCondition(
            name="no_progress",
            check=lambda ms, rs: rs.get("no_progress_count", 0) >= 3,
            reason="No progress for 3 consecutive iterations.",
        )
        runtime_state = {"no_progress_count": 2}
        should_stop, _ = check_stop_conditions({}, runtime_state, [condition])
        self.assertFalse(should_stop)

        runtime_state = {"no_progress_count": 3}
        should_stop, reason = check_stop_conditions({}, runtime_state, [condition])
        self.assertTrue(should_stop)
        self.assertEqual(reason, "No progress for 3 consecutive iterations.")

        runtime_state = {"no_progress_count": 5}
        should_stop, _ = check_stop_conditions({}, runtime_state, [condition])
        self.assertTrue(should_stop)

    def test_custom_condition(self):
        """A custom condition is evaluated and can stop the loop."""
        triggered = False

        def custom_check(ms, rs):
            nonlocal triggered
            if rs.get("custom_flag"):
                triggered = True
                return True
            return False

        condition = StopCondition(
            name="custom",
            check=custom_check,
            reason="Custom condition triggered.",
        )

        # Not triggered
        should_stop, _ = check_stop_conditions({}, {}, [condition])
        self.assertFalse(should_stop)

        # Triggered
        should_stop, reason = check_stop_conditions(
            {}, {"custom_flag": True}, [condition]
        )
        self.assertTrue(should_stop)
        self.assertEqual(reason, "Custom condition triggered.")
        self.assertTrue(triggered)

    def test_multiple_conditions_first_wins(self):
        """When multiple conditions trigger, the first one's reason is returned."""
        cond_a = StopCondition(
            name="cond_a",
            check=lambda ms, rs: rs.get("a", False),
            reason="Condition A triggered.",
        )
        cond_b = StopCondition(
            name="cond_b",
            check=lambda ms, rs: rs.get("b", False),
            reason="Condition B triggered.",
        )
        cond_c = StopCondition(
            name="cond_c",
            check=lambda ms, rs: rs.get("c", False),
            reason="Condition C triggered.",
        )

        # Only A triggered
        should_stop, reason = check_stop_conditions(
            {}, {"a": True}, [cond_a, cond_b, cond_c]
        )
        self.assertTrue(should_stop)
        self.assertEqual(reason, "Condition A triggered.")

        # All triggered — first wins
        should_stop, reason = check_stop_conditions(
            {}, {"a": True, "b": True, "c": True}, [cond_a, cond_b, cond_c]
        )
        self.assertTrue(should_stop)
        self.assertEqual(reason, "Condition A triggered.")

        # Only C triggered
        should_stop, reason = check_stop_conditions(
            {}, {"c": True}, [cond_a, cond_b, cond_c]
        )
        self.assertTrue(should_stop)
        self.assertEqual(reason, "Condition C triggered.")

    def test_no_conditions(self):
        """With an empty condition list, check_stop_conditions returns (False, None)."""
        should_stop, reason = check_stop_conditions(
            {"status": "running"}, {"iterations_completed": 100}, []
        )
        self.assertFalse(should_stop)
        self.assertIsNone(reason)

    def test_default_stop_conditions_returns_list(self):
        """default_stop_conditions returns a list of StopCondition objects."""
        conditions = default_stop_conditions(max_iterations=10)
        self.assertIsInstance(conditions, list)
        self.assertTrue(all(isinstance(c, StopCondition) for c in conditions))
        # max_iterations + token_count + cost_limit + no_progress = 4
        self.assertEqual(len(conditions), 4)

    def test_default_stop_conditions_cost_limit(self):
        """When max_cost is provided, a cost-limit condition is included."""
        conditions = default_stop_conditions(max_iterations=10, max_cost=50.0)
        names = [c.name for c in conditions]
        self.assertIn("cost_limit", names)
        # max_iterations + token_count + cost_limit + no_progress = 4
        self.assertEqual(len(conditions), 4)

    def test_default_stop_conditions_time_limit(self):
        """When time_limit is provided, a time-limit condition is included."""
        conditions = default_stop_conditions(max_iterations=10, time_limit=300)
        names = [c.name for c in conditions]
        self.assertIn("time_limit", names)
        # max_iterations + token_count + cost_limit + no_progress + time_limit = 5
        self.assertEqual(len(conditions), 5)

    def test_integration_simulated_loop(self):
        """Simulate a loop with default_stop_conditions and verify it exits at max_iterations."""
        conditions = default_stop_conditions(max_iterations=5)

        runtime_state = {"iterations_completed": 0, "no_progress_count": 0}
        mission_state = {}

        for _ in range(10):
            should_stop, reason = check_stop_conditions(
                mission_state, runtime_state, conditions
            )
            if should_stop:
                self.assertIn("5", reason)
                self.assertIn("iteration limit", reason.lower())
                break
            runtime_state["iterations_completed"] += 1

        self.assertEqual(runtime_state["iterations_completed"], 5)

    def test_condition_exception_is_safe(self):
        """A misbehaving condition that raises does not crash check_stop_conditions."""

        def broken_check(ms, rs):
            raise RuntimeError("Boom!")

        good_cond = StopCondition(
            name="good",
            check=lambda ms, rs: rs.get("finished", False),
            reason="Good condition.",
        )
        broken_cond = StopCondition(
            name="broken",
            check=broken_check,
            reason="Broken condition.",
        )

        # Broken alone → no stop
        should_stop, reason = check_stop_conditions({}, {}, [broken_cond])
        self.assertFalse(should_stop)
        self.assertIsNone(reason)

        # Broken before good, good triggers
        should_stop, reason = check_stop_conditions(
            {}, {"finished": True}, [broken_cond, good_cond]
        )
        self.assertTrue(should_stop)
        self.assertEqual(reason, "Good condition.")


class TestTokenStopConditions(unittest.TestCase):
    """Test token-based stop condition factories."""

    def test_token_count_is_stops_at_threshold(self):
        """tokenCountIs stops when total_tokens >= max."""
        condition = tokenCountIs(1000)
        self.assertEqual(condition.name, "token_count")

        should_stop, _ = check_stop_conditions({}, {"total_tokens": 500}, [condition])
        self.assertFalse(should_stop)

        should_stop, _ = check_stop_conditions({}, {"total_tokens": 1000}, [condition])
        self.assertTrue(should_stop)

        should_stop, reason = check_stop_conditions({}, {"total_tokens": 1500}, [condition])
        self.assertTrue(should_stop)
        self.assertIn("1000", reason)

    def test_input_token_count_is_stops_at_threshold(self):
        """inputTokenCountIs stops when total_input_tokens >= max."""
        condition = inputTokenCountIs(500)
        self.assertEqual(condition.name, "input_token_count")

        should_stop, _ = check_stop_conditions({}, {"total_input_tokens": 200}, [condition])
        self.assertFalse(should_stop)

        should_stop, reason = check_stop_conditions({}, {"total_input_tokens": 500}, [condition])
        self.assertTrue(should_stop)
        self.assertIn("500", reason)

    def test_output_token_count_is_stops_at_threshold(self):
        """outputTokenCountIs stops when total_output_tokens >= max."""
        condition = outputTokenCountIs(300)
        self.assertEqual(condition.name, "output_token_count")

        should_stop, _ = check_stop_conditions({}, {"total_output_tokens": 100}, [condition])
        self.assertFalse(should_stop)

        should_stop, reason = check_stop_conditions({}, {"total_output_tokens": 300}, [condition])
        self.assertTrue(should_stop)
        self.assertIn("300", reason)

    def test_token_count_missing_key_does_not_stop(self):
        """tokenCountIs treats missing key as 0 and does not stop."""
        condition = tokenCountIs(100)
        should_stop, _ = check_stop_conditions({}, {}, [condition])
        self.assertFalse(should_stop)


class TestCostStopCondition(unittest.TestCase):
    """Test cost-based stop condition."""

    def test_cost_is_stops_at_threshold(self):
        """costIs stops when accumulated_cost >= max."""
        condition = costIs(5.0)
        self.assertEqual(condition.name, "cost_limit")

        should_stop, _ = check_stop_conditions({}, {"accumulated_cost": 3.0}, [condition])
        self.assertFalse(should_stop)

        should_stop, reason = check_stop_conditions({}, {"accumulated_cost": 5.0}, [condition])
        self.assertTrue(should_stop)
        self.assertIn("$5.00", reason)

        should_stop, _ = check_stop_conditions({}, {"accumulated_cost": 7.5}, [condition])
        self.assertTrue(should_stop)

    def test_cost_is_missing_key_does_not_stop(self):
        """costIs treats missing accumulated_cost as 0.0."""
        condition = costIs(0.01)
        should_stop, _ = check_stop_conditions({}, {}, [condition])
        self.assertFalse(should_stop)


class TestModelPricing(unittest.TestCase):
    """Test MODEL_PRICING and accumulate_cost."""

    def test_model_pricing_has_expected_models(self):
        """MODEL_PRICING contains expected keys."""
        self.assertIn("deepseek-chat", _MODEL_PRICING)
        self.assertIn("deepseek-reasoner", _MODEL_PRICING)
        chat = _MODEL_PRICING["deepseek-chat"]
        self.assertEqual(chat["input"], 0.27)
        self.assertEqual(chat["output"], 1.10)
        reasoner = _MODEL_PRICING["deepseek-reasoner"]
        self.assertEqual(reasoner["input"], 0.55)
        self.assertEqual(reasoner["output"], 2.19)

    def test_accumulate_cost_known_model(self):
        """accumulate_cost computes cost correctly for a known model."""
        state: dict[str, object] = {}
        total = accumulate_cost(state, "deepseek-chat", input_tokens=1_000_000, output_tokens=500_000)
        expected = 1.0 * 0.27 + 0.5 * 1.10  # = 0.27 + 0.55 = 0.82
        self.assertAlmostEqual(total, expected)
        self.assertAlmostEqual(total, state["accumulated_cost"])

    def test_accumulate_cost_multiple_calls(self):
        """accumulate_cost accumulates across multiple calls."""
        state: dict[str, object] = {}
        total1 = accumulate_cost(state, "deepseek-chat", input_tokens=1_000_000, output_tokens=0)
        self.assertAlmostEqual(total1, 0.27)
        total2 = accumulate_cost(state, "deepseek-chat", input_tokens=0, output_tokens=1_000_000)
        self.assertAlmostEqual(total2, 0.27 + 1.10)
        self.assertAlmostEqual(state["accumulated_cost"], total2)

    def test_accumulate_cost_unknown_model_returns_zero(self):
        """accumulate_cost returns 0 for unknown models and does not update state."""
        state: dict[str, object] = {}
        total = accumulate_cost(state, "unknown-model", input_tokens=1_000_000, output_tokens=1_000_000)
        self.assertEqual(total, 0.0)
        self.assertNotIn("accumulated_cost", state)

    def test_accumulate_cost_with_preexisting_cost(self):
        """accumulate_cost adds to an existing accumulated_cost."""
        state: dict[str, object] = {"accumulated_cost": 1.0}
        total = accumulate_cost(state, "deepseek-chat", input_tokens=1_000_000, output_tokens=0)
        self.assertAlmostEqual(total, 1.27)
        self.assertAlmostEqual(state["accumulated_cost"], 1.27)


if __name__ == "__main__":
    unittest.main()
