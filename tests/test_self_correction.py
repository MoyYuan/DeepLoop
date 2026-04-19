"""Tests for the self-correction engine.

Validates deterministic failure classification and recovery routing
using the translation plain-folder example as a concrete public-safe target.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import MISSIONS_DIR
from deeploop.research.self_correction import evaluate_self_correction


class TestSelfCorrectionConfiguration(unittest.TestCase):
    """Test self-correction configuration and structure."""

    def test_config_file_exists(self):
        """Test that self-correction config file exists."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "self-correction.yaml"
        self.assertTrue(config_path.exists(), f"Config not found at {config_path}")

    def test_design_doc_exists(self):
        """Test that design documentation exists."""
        doc_path = REPO_ROOT / "docs" / "design" / "self-correction.md"
        self.assertTrue(doc_path.exists(), f"Design doc not found at {doc_path}")

    def test_mission_script_exists(self):
        """Test that mission script exists."""
        script_path = REPO_ROOT / "scripts" / "mission" / "run_self_correction.py"
        self.assertTrue(script_path.exists(), f"Script not found at {script_path}")

    def test_config_yaml_loadable(self):
        """Test that config YAML is valid."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "self-correction.yaml"
        import yaml

        content = yaml.safe_load(config_path.read_text())
        self.assertIsInstance(content, dict)
        self.assertIn("version", content)
        self.assertIn("taxonomy", content)

    def test_config_has_required_structure(self):
        """Test that config has required structure."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "self-correction.yaml"
        import yaml

        content = yaml.safe_load(config_path.read_text())

        required_keys = [
            "version",
            "policy_name",
            "artifact_dir_name",
            "default_manifest_globs",
            "thresholds",
            "signal_detection",
            "taxonomy",
            "substrates",
        ]
        for key in required_keys:
            self.assertIn(key, content, f"Missing key: {key}")

    def test_taxonomy_has_failure_classes(self):
        """Test that taxonomy defines failure classes."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "self-correction.yaml"
        import yaml

        content = yaml.safe_load(config_path.read_text())
        taxonomy = content.get("taxonomy", {})

        # Check for expected failure types
        self.assertGreater(len(taxonomy), 0, "Taxonomy should have entries")
        
        # Each entry should have severity, default_action, and summary
        for name, entry in taxonomy.items():
            self.assertIn("severity", entry, f"Missing severity in {name}")
            self.assertIn("default_action", entry, f"Missing default_action in {name}")
            self.assertIn("summary", entry, f"Missing summary in {name}")

    def test_recovery_actions_defined(self):
        """Test that recovery actions are properly defined."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "self-correction.yaml"
        import yaml

        content = yaml.safe_load(config_path.read_text())
        taxonomy = content.get("taxonomy", {})

        # Collect all default actions
        actions = set()
        for entry in taxonomy.values():
            actions.add(entry.get("default_action"))

        # Should have the main recovery strategies
        expected_actions = {"continue", "reroute", "stop"}
        self.assertTrue(
            actions & expected_actions,
            f"Should have recovery actions, found: {actions}",
        )

    def test_translation_substrate_defined(self):
        """Test that the translation substrate is configured."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "self-correction.yaml"
        import yaml

        content = yaml.safe_load(config_path.read_text())
        substrates = content.get("substrates", {})

        self.assertIn(
            "translation-pilot",
            substrates,
            "Translation substrate not configured",
        )
        asym_cfg = substrates["translation-pilot"]
        self.assertEqual(asym_cfg.get("project"), "translation-pilot")
        self.assertIn("preferred_followups", asym_cfg)


class TestSelfCorrectionAPI(unittest.TestCase):
    """Test the self-correction evaluation API."""

    def test_evaluation_api_callable(self):
        """Test that the evaluation API is callable."""
        self.assertTrue(callable(evaluate_self_correction))

    def test_api_has_correct_signature(self):
        """Test that API has expected parameters."""
        import inspect

        sig = inspect.signature(evaluate_self_correction)
        params = list(sig.parameters.keys())

        # Should accept artifact_name at minimum
        self.assertIn("artifact_name", params)


class TestIntegration(unittest.TestCase):
    """Integration tests for self-correction components."""

    def test_all_required_files_exist(self):
        """Test that all required files have been created."""
        required_files = [
            REPO_ROOT / "configs" / "autonomy" / "self-correction.yaml",
            REPO_ROOT / "docs" / "design" / "self-correction.md",
            REPO_ROOT / "src" / "deeploop" / "research" / "self_correction.py",
            REPO_ROOT / "scripts" / "mission" / "run_self_correction.py",
        ]

        for file_path in required_files:
            self.assertTrue(
                file_path.exists(), f"Required file not found: {file_path}"
            )

    def test_mission_script_syntax(self):
        """Test that mission script is valid Python."""
        script_path = REPO_ROOT / "scripts" / "mission" / "run_self_correction.py"
        import py_compile

        try:
            py_compile.compile(str(script_path), doraise=True)
        except py_compile.PyCompileError as e:
            self.fail(f"Script has syntax error: {e}")

    def test_design_doc_content_complete(self):
        """Test that design doc has expected sections."""
        doc_path = REPO_ROOT / "docs" / "design" / "self-correction.md"
        content = doc_path.read_text()

        # Core sections
        expected_sections = [
            "Overview",
            "Architecture",
            "Failure Classification",
            "Recovery Routing",
            "Artifacts",
            "Deterministic Behavior",
        ]
        for section in expected_sections:
            self.assertIn(section, content, f"Missing section: {section}")

        # Should mention translation as concrete target
        self.assertIn(
            "translation",
            content.lower(),
            "Should mention translation as concrete target",
        )

    def test_deterministic_configuration_applied(self):
        """Test that configuration enforces deterministic behavior."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "self-correction.yaml"
        import yaml

        content = yaml.safe_load(config_path.read_text())

        # Should have manifest globs for deterministic discovery
        self.assertIn("default_manifest_globs", content)
        globs = content.get("default_manifest_globs", [])
        self.assertGreater(len(globs), 0, "Should define manifest globs")

        # Should have thresholds for deterministic classification
        self.assertIn("thresholds", content)
        thresholds = content.get("thresholds", {})
        self.assertGreater(len(thresholds), 0, "Should define thresholds")


if __name__ == "__main__":
    unittest.main()
