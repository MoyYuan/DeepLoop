"""Integration test: validate the DeepSeek API contract through the provider launcher.

Requires DEEPLOOP_INTEGRATION_API_KEY env var. Some tests skip if not set.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.provider_launcher import (
    build_provider_prompt_command,
    resolve_model_for_role,
    run_provider_prompt,
)
from deeploop.core.bounded_memory import BoundedMemory


class ProviderCommandContractTest(unittest.TestCase):
    """Validate that provider command construction works without an API key."""

    def test_build_command_returns_list_of_strings(self):
        """build_provider_prompt_command returns a non-empty list of strings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "prompt.md"
            prompt_file.write_text("Hello", encoding="utf-8")
            command = build_provider_prompt_command(
                prompt_file=prompt_file,
                result_json_path=Path(tmpdir) / "result.json",
                model="deepseek-chat",
            )
        self.assertIsInstance(command, list)
        self.assertGreater(len(command), 0)
        self.assertTrue(all(isinstance(part, str) for part in command))

    def test_build_command_includes_model(self):
        """The model identifier appears in the command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "prompt.md"
            prompt_file.write_text("Hello", encoding="utf-8")
            command = build_provider_prompt_command(
                prompt_file=prompt_file,
                result_json_path=Path(tmpdir) / "result.json",
                model="deepseek-chat",
            )
        self.assertIn("deepseek-chat", command)

    def test_build_command_includes_prompt_file_and_result_path(self):
        """--prompt-file and --result-json-path appear in the command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "prompt.md"
            prompt_file.write_text("Hello", encoding="utf-8")
            result_path = Path(tmpdir) / "result.json"
            command = build_provider_prompt_command(
                prompt_file=prompt_file,
                result_json_path=result_path,
            )
        self.assertIn("--prompt-file", command)
        self.assertIn(str(prompt_file), command)
        self.assertIn("--result-json-path", command)
        self.assertIn(str(result_path), command)


class TieredModelResolutionTest(unittest.TestCase):
    """Validate the model tier resolution logic."""

    def test_planner_role_resolves_to_reasoning_tier(self):
        """role='planner' resolves to deepseek-reasoner."""
        model = resolve_model_for_role(role="planner")
        self.assertEqual(model, "deepseek-reasoner")

    def test_execution_operator_resolves_to_execution_tier(self):
        """role='execution-operator' resolves to deepseek-chat."""
        model = resolve_model_for_role(role="execution-operator")
        self.assertEqual(model, "deepseek-chat")

    def test_experiment_designer_resolves_to_reasoning_tier(self):
        """role='experiment-designer' resolves to deepseek-reasoner."""
        model = resolve_model_for_role(role="experiment-designer")
        self.assertEqual(model, "deepseek-reasoner")

    def test_literature_scout_resolves_to_execution_tier(self):
        """role='literature-scout' resolves to deepseek-chat."""
        model = resolve_model_for_role(role="literature-scout")
        self.assertEqual(model, "deepseek-chat")

    def test_unknown_role_falls_back_to_default(self):
        """An unknown role falls back to the default tier model."""
        model = resolve_model_for_role(role="nonexistent-role")
        self.assertEqual(model, "deepseek-chat")

    def test_explicit_model_overrides_tier(self):
        """explicit_model bypasses tier resolution."""
        model = resolve_model_for_role(
            role="planner", explicit_model="custom-model"
        )
        self.assertEqual(model, "custom-model")

    @patch.dict(os.environ, {"OPENAI_MODEL": "env-override"}, clear=True)
    def test_env_var_fallback_when_tier_unavailable(self):
        """OPENAI_MODEL is used when no tier matches and default tier is missing."""
        # Use a custom tiers config with broken default
        with tempfile.TemporaryDirectory() as tmpdir:
            import yaml
            tiers_path = Path(tmpdir) / "model-tiers.yaml"
            with open(tiers_path, "w") as f:
                yaml.dump(
                    {
                        "tiers": {
                            "special": {
                                "model_identifier": "special-model",
                                "intended_roles": ["specialist"],
                            },
                        },
                        "default_tier": "missing-tier",
                    },
                    f,
                )
            model = resolve_model_for_role(
                role="specialist", tiers_config=tiers_path
            )
            self.assertEqual(model, "special-model")

            model = resolve_model_for_role(
                role="unknown", tiers_config=tiers_path
            )
            self.assertEqual(model, "env-override")


@unittest.skipIf(
    not os.environ.get("DEEPLOOP_INTEGRATION_API_KEY"),
    "DEEPLOOP_INTEGRATION_API_KEY not set",
)
class LiveAPIContractTest(unittest.TestCase):
    """Tests that send real API calls through the provider launcher."""

    def setUp(self):
        self.test_root = Path(tempfile.mkdtemp())
        self.env = os.environ.copy()
        existing_pp = self.env.get("PYTHONPATH", "")
        self.env["PYTHONPATH"] = (
            str(SRC_ROOT) + os.pathsep + existing_pp
            if existing_pp
            else str(SRC_ROOT)
        )
        self.env["OPENAI_API_KEY"] = os.environ["DEEPLOOP_INTEGRATION_API_KEY"]
        self.env["OPENAI_BASE_URL"] = "https://api.deepseek.com/v1"
        self.env["OPENAI_MODEL"] = "deepseek-chat"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_root, ignore_errors=True)

    def test_prompt_to_result_roundtrip(self):
        """Send a simple prompt and get a valid JSON result back.

        This exercises the full provider pipeline: command building, subprocess
        launch, API call, result parsing, and payload validation.
        """
        prompt_text = (
            "Return a JSON object with keys: status, summary. "
            'status must be "complete". summary must be a one-sentence '
            "description of what you did. No markdown fences."
        )
        prompt_file = self.test_root / "prompt.md"
        prompt_file.write_text(prompt_text, encoding="utf-8")

        result_json_path = self.test_root / "result.json"

        completed = run_provider_prompt(
            prompt_file,
            result_json_path=result_json_path,
            model="deepseek-chat",
            cwd=self.test_root,
        )

        # Process should have exited cleanly
        self.assertEqual(
            completed.returncode,
            0,
            f"Provider subprocess failed:\nstdout: {completed.stdout}\nstderr: {completed.stderr}",
        )

        # Result file must exist and be valid JSON
        self.assertTrue(
            result_json_path.exists(),
            "result.json was not written by the provider",
        )
        payload = json.loads(result_json_path.read_text(encoding="utf-8"))
        self.assertIsInstance(payload, dict)
        self.assertIn("status", payload)
        self.assertIn("summary", payload)
        self.assertIsInstance(payload["summary"], str)
        self.assertGreater(len(payload["summary"]), 0)

    def test_prompt_with_continuation_contract(self):
        """Verify the provider can handle a continuation/agent-action payload."""
        prompt_text = (
            "Return a JSON object with keys: status, summary, continuation. "
            'status must be "continue". summary must describe the next step. '
            'continuation must be an object with "role" and "task" keys. '
            "No markdown fences."
        )
        prompt_file = self.test_root / "continuation_prompt.md"
        prompt_file.write_text(prompt_text, encoding="utf-8")

        result_json_path = self.test_root / "continuation_result.json"

        completed = run_provider_prompt(
            prompt_file,
            result_json_path=result_json_path,
            model="deepseek-chat",
            cwd=self.test_root,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(result_json_path.exists())

        payload = json.loads(result_json_path.read_text(encoding="utf-8"))
        self.assertIn("continuation", payload)
        continuation = payload["continuation"]
        self.assertIsInstance(continuation, dict)
        self.assertIn("role", continuation)
        self.assertIn("task", continuation)
        self.assertIsInstance(continuation["role"], str)
        self.assertIsInstance(continuation["task"], str)


class BoundedMemoryContractTest(unittest.TestCase):
    """Validate the bounded-memory context contract.

    These tests are unit-level (no API key required) and ensure the memory
    module correctly enforces size budgets.
    """

    DEFAULTS = {
        "max_brief_chars": 3000,
        "max_log_chars": 2000,
        "max_decisions": 15,
    }

    def test_context_under_budget_after_multiple_results(self):
        """The context_block stays within budget after recording many results."""
        mem = BoundedMemory(
            project_brief="Test brief: explore the effect of temperature on LLM output quality.",
            **self.DEFAULTS,
        )
        for i in range(20):
            mem.record_result(f"Iteration {i}: tested temperature={0.1 * i:.1f}, accuracy={0.95 - 0.01 * i:.3f}")
            mem.record_decision(f"decision-{i}: Temperature sweep step {i}")

        block = mem.context_block()
        budget = self.DEFAULTS["max_brief_chars"] + self.DEFAULTS["max_log_chars"] + 500
        self.assertLessEqual(
            len(block),
            budget,
            f"Context block ({len(block)} chars) exceeds budget ({budget} chars)",
        )
        self.assertIn("## Project Brief", block)
        self.assertIn("## Memory Log", block)
        self.assertIn("### Recent Decisions", block)

    def test_brief_truncation_keeps_context_under_budget(self):
        """A very long brief is truncated and the total stays under budget."""
        mem = BoundedMemory(
            project_brief="x" * 5000,
            max_brief_chars=100,
            max_log_chars=2000,
            max_decisions=15,
        )
        self.assertEqual(len(mem.project_brief), 100)
        block = mem.context_block()
        budget = 100 + 2000 + 500
        self.assertLessEqual(len(block), budget)

    def test_log_auto_compresses_when_over_budget(self):
        """Auto-compression keeps the log under max_log_chars."""
        mem = BoundedMemory(
            project_brief="Brief.",
            max_brief_chars=200,
            max_log_chars=500,
            max_decisions=5,
        )
        for i in range(50):
            mem.record_result(f"Long result entry number {i}: " + "data " * 20)
        log = mem.memory_log()
        self.assertLessEqual(len(log), 600)

    def test_decision_log_capped_at_max_decisions(self):
        """The decision log never exceeds max_decisions entries."""
        mem = BoundedMemory(
            project_brief="Brief.",
            **self.DEFAULTS,
        )
        for i in range(30):
            mem.record_decision(f"d-{i}: Decision {i}")
        # memory_log() should contain at most max_decisions decision entries
        log = mem.memory_log()
        # Count decision entries in the rendered log
        decision_count = log.count("### Recent Decisions\n")
        if decision_count > 0:
            decision_lines = [line for line in log.splitlines() if line.startswith("- d-")]
            self.assertLessEqual(len(decision_lines), self.DEFAULTS["max_decisions"])

    def test_empty_state_does_not_crash(self):
        """Edge case: empty brief and no results."""
        mem = BoundedMemory(project_brief="", **self.DEFAULTS)
        block = mem.context_block()
        self.assertIn("## Project Brief", block)
        self.assertIn("## Memory Log", block)
        # No decisions recorded, so header renders only Key Results
        self.assertIn("### Key Results", block)
        # context_block should always be valid text
        self.assertIsInstance(block, str)
        self.assertGreater(len(block), 0)

    def test_decision_log_render_in_memory_log(self):
        """record_decision entries appear in the memory_log output."""
        mem = BoundedMemory(project_brief="Brief.", **self.DEFAULTS)
        mem.record_decision("d-1: switched optimizer")
        mem.record_decision("d-2: increased batch size")
        log = mem.memory_log()
        self.assertIn("### Recent Decisions", log)
        self.assertIn("switched optimizer", log)
        self.assertIn("increased batch size", log)


if __name__ == "__main__":
    unittest.main()
