"""Tests for resolve_model_for_role."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import yaml

from deeploop.runtime.provider_launcher import resolve_model_for_role


class TestResolveModelForRole(unittest.TestCase):
    """Test model tier resolution via resolve_model_for_role."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_tiers(self, config: dict, filename: str = "model-tiers.yaml") -> Path:
        path = self.temp_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)
        return path

    def test_planner_role_resolves_to_reasoning(self):
        """role='planner' resolves to the reasoning tier model 'deepseek-reasoner'."""
        model = resolve_model_for_role(role="planner")
        self.assertEqual(model, "deepseek-reasoner")

    def test_execution_operator_role_resolves_to_execution(self):
        """role='execution-operator' resolves to the execution tier model 'deepseek-chat'."""
        model = resolve_model_for_role(role="execution-operator")
        self.assertEqual(model, "deepseek-chat")

    def test_explicit_model_overrides(self):
        """explicit_model='custom-model' bypasses tier resolution and returns it directly."""
        model = resolve_model_for_role(
            role="planner", explicit_model="custom-model"
        )
        self.assertEqual(model, "custom-model")

        model = resolve_model_for_role(
            role="execution-operator", explicit_model="custom-model"
        )
        self.assertEqual(model, "custom-model")

    def test_unknown_role_falls_back_to_default_tier(self):
        """An unknown role falls back to the default tier model ('deepseek-chat')."""
        model = resolve_model_for_role(role="unknown-role-xyz")
        self.assertEqual(model, "deepseek-chat")

    def test_custom_tiers_config_resolves_correctly(self):
        """A custom tiers_config YAML file is used for resolution."""
        custom_config = {
            "tiers": {
                "research": {
                    "label": "Research tier",
                    "model_identifier": "gpt-4o",
                    "intended_roles": ["researcher"],
                },
                "coding": {
                    "label": "Coding tier",
                    "model_identifier": "gpt-4o-mini",
                    "intended_roles": ["coder"],
                },
            },
            "default_tier": "coding",
        }
        tiers_path = self._write_tiers(custom_config)

        model = resolve_model_for_role(
            role="researcher", tiers_config=tiers_path
        )
        self.assertEqual(model, "gpt-4o")

        model = resolve_model_for_role(
            role="coder", tiers_config=tiers_path
        )
        self.assertEqual(model, "gpt-4o-mini")

        model = resolve_model_for_role(
            role="planner", tiers_config=tiers_path
        )
        self.assertEqual(model, "gpt-4o-mini")  # default_tier=coding

    def test_custom_tiers_unknown_role_uses_default(self):
        """With a custom config, an unknown role falls back to the configured default_tier."""
        custom_config = {
            "tiers": {
                "special": {
                    "label": "Special",
                    "model_identifier": "special-model",
                    "intended_roles": ["specialist"],
                },
            },
            "default_tier": "special",
        }
        tiers_path = self._write_tiers(custom_config)

        model = resolve_model_for_role(
            role="nonexistent", tiers_config=tiers_path
        )
        self.assertEqual(model, "special-model")

    def test_empty_tiers_config_falls_back_to_env_var(self):
        """An empty tiers config (no tiers dict) falls back to OPENAI_MODEL env var."""
        empty_config = {"tiers": {}, "default_tier": "execution"}
        tiers_path = self._write_tiers(empty_config)

        with patch.dict(
            os.environ, {"OPENAI_MODEL": "env-var-model"}, clear=True
        ):
            model = resolve_model_for_role(
                role="planner", tiers_config=tiers_path
            )
            self.assertEqual(model, "env-var-model")

    def test_env_var_fallback_with_custom_tiers(self):
        """OPENAI_MODEL env var is used when custom config has no matching tier."""
        weird_config = {
            "tiers": {
                "some_tier": {
                    "label": "Some",
                    "model_identifier": "some-model",
                    "intended_roles": ["some-role"],
                },
            },
            "default_tier": "nonexistent-tier",
        }
        tiers_path = self._write_tiers(weird_config)

        with patch.dict(
            os.environ, {"OPENAI_MODEL": "env-fallback-model"}, clear=True
        ):
            model = resolve_model_for_role(
                role="some-role", tiers_config=tiers_path
            )
            self.assertEqual(model, "some-model")

            # Unknown role with missing default tier → env var
            model = resolve_model_for_role(
                role="unknown", tiers_config=tiers_path
            )
            self.assertEqual(model, "env-fallback-model")

    def test_last_resort_fallback(self):
        """When nothing matches and no env var, returns 'deepseek-chat'."""
        empty_config = {"tiers": {}, "default_tier": "execution"}
        tiers_path = self._write_tiers(empty_config)

        with patch.dict(os.environ, {}, clear=True):
            model = resolve_model_for_role(
                role="planner", tiers_config=tiers_path
            )
            self.assertEqual(model, "deepseek-chat")

    def test_experiment_designer_role(self):
        """role='experiment-designer' should resolve to the reasoning tier."""
        model = resolve_model_for_role(role="experiment-designer")
        self.assertEqual(model, "deepseek-reasoner")

    def test_literature_scout_role(self):
        """role='literature-scout' should resolve to the execution tier."""
        model = resolve_model_for_role(role="literature-scout")
        self.assertEqual(model, "deepseek-chat")


if __name__ == "__main__":
    unittest.main()
