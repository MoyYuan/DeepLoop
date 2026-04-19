"""Tests for the fresh-context redteam engine.

Validates deterministic red-team analysis, alternative explanation generation,
falsification check operationalization, and destructive sanity checks
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

from deeploop.fresh_context_redteam import (
    evaluate_fresh_context_redteam,
    RedteamReport,
    AlternativeExplanation,
    FalsificationCheck,
    DestructiveSanityCheck,
    AssumptionNode,
    ConfoundCatalogItem,
)
from deeploop.core.paths import MISSIONS_DIR


class TestFreshContextRedteamConfiguration(unittest.TestCase):
    """Test fresh-context redteam configuration and structure."""

    def test_config_file_exists(self):
        """Test that fresh-context-redteam config file exists."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "fresh-context-redteam.yaml"
        self.assertTrue(config_path.exists(), f"Config not found at {config_path}")

    def test_design_doc_exists(self):
        """Test that design documentation exists."""
        doc_path = REPO_ROOT / "docs" / "design" / "fresh-context-redteam.md"
        self.assertTrue(doc_path.exists(), f"Design doc not found at {doc_path}")

    def test_mission_script_exists(self):
        """Test that mission script exists."""
        script_path = REPO_ROOT / "scripts" / "mission" / "run_fresh_context_redteam.py"
        self.assertTrue(script_path.exists(), f"Script not found at {script_path}")

    def test_config_yaml_loadable(self):
        """Test that config YAML is valid."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "fresh-context-redteam.yaml"
        import yaml

        content = yaml.safe_load(config_path.read_text())
        self.assertIsInstance(content, dict)
        self.assertIn("version", content)
        self.assertIn("challenge_modes", content)

    def test_config_has_required_structure(self):
        """Test that config has required structure."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "fresh-context-redteam.yaml"
        import yaml

        content = yaml.safe_load(config_path.read_text())

        required_keys = [
            "version",
            "policy_name",
            "artifact_dir_name",
            "challenge_modes",
            "adversarial_tactics",
            "evidence_standards",
            "report_structure",
            "substrates",
        ]
        for key in required_keys:
            self.assertIn(key, content, f"Missing key: {key}")

    def test_challenge_modes_defined(self):
        """Test that challenge modes are properly defined."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "fresh-context-redteam.yaml"
        import yaml

        content = yaml.safe_load(config_path.read_text())
        modes = content.get("challenge_modes", {})

        expected_modes = [
            "fresh_reading",
            "alternative_explanations",
            "falsification_checks",
            "destructive_sanity",
            "assumption_audit",
            "confound_surface",
        ]
        for mode in expected_modes:
            self.assertIn(mode, modes, f"Missing challenge mode: {mode}")

    def test_adversarial_tactics_defined(self):
        """Test that adversarial tactics are available."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "fresh-context-redteam.yaml"
        import yaml

        content = yaml.safe_load(config_path.read_text())
        tactics = content.get("adversarial_tactics", {})

        expected_tactics = [
            "measurement_attacks",
            "cherry_picking_audit",
            "confound_blindness",
            "interaction_pathologies",
            "alternate_causal_routes",
        ]
        for tactic in expected_tactics:
            self.assertIn(tactic, tactics, f"Missing tactic: {tactic}")


class TestRedteamDataClasses(unittest.TestCase):
    """Test redteam data class definitions."""

    def test_alternative_explanation_creation(self):
        """Test creating alternative explanation objects."""
        alt = AlternativeExplanation(
            hypothesis="Alternative mechanism",
            plausibility_score=0.45,
            mechanism="Different causal pathway",
            supporting_observations=["obs1", "obs2"],
        )
        self.assertEqual(alt.hypothesis, "Alternative mechanism")
        self.assertAlmostEqual(alt.plausibility_score, 0.45)
        self.assertEqual(len(alt.supporting_observations), 2)

    def test_falsification_check_creation(self):
        """Test creating falsification check objects."""
        check = FalsificationCheck(
            check_id="check_1",
            primary_claim="Effect is positive",
            falsification_condition="Effect reverses in subset A",
            operationalization="Measure effect separately in subset A",
            expected_result_if_true="Positive effect in subset A",
            expected_result_if_false="Negative effect in subset A",
            feasibility="medium",
        )
        self.assertEqual(check.check_id, "check_1")
        self.assertTrue(check.operationalization.startswith("Measure"))

    def test_destructive_sanity_check_creation(self):
        """Test creating destructive sanity check objects."""
        check = DestructiveSanityCheck(
            tactic="measurement_attacks",
            check_description="Test robustness to ±10% measurement error",
            severity="high",
            concern="Effect may disappear under measurement noise",
            mitigation_if_present="Effect remains significant after ±10% perturbation",
            status="unclear",
        )
        self.assertEqual(check.tactic, "measurement_attacks")
        self.assertEqual(check.severity, "high")

    def test_assumption_node_creation(self):
        """Test creating assumption nodes."""
        assume = AssumptionNode(
            assumption_id="a1",
            text="Measurements are unbiased",
            justification="Validated through calibration",
            criticality="high",
        )
        self.assertEqual(assume.assumption_id, "a1")
        self.assertEqual(assume.criticality, "high")

    def test_confound_catalog_item_creation(self):
        """Test creating confound catalog items."""
        confound = ConfoundCatalogItem(
            confound_name="Unmeasured age effect",
            mechanism_description="Age correlates with treatment",
            expected_direction="negative",
            estimated_effect_magnitude="medium",
            control_status="unmeasured",
            adjustment_estimate=None,
        )
        self.assertEqual(confound.confound_name, "Unmeasured age effect")
        self.assertEqual(confound.control_status, "unmeasured")

    def test_redteam_report_serialization(self):
        """Test that redteam report serializes to dict correctly."""
        report = RedteamReport(
            report_id="test_1",
            mission_id="translation-full-mission",
            artifact_name="test_artifact",
            created_at="2024-01-01T00:00:00Z",
            primary_finding_summary="Test finding",
        )
        report_dict = report.to_dict()
        self.assertEqual(report_dict["report_id"], "test_1")
        self.assertIsInstance(report_dict, dict)
        self.assertIn("alternative_explanations", report_dict)


class TestFreshContextRedteamExecution(unittest.TestCase):
    """Test fresh-context redteam execution."""

    def test_evaluation_runs_deterministically(self):
        """Test that evaluation runs without errors."""
        result = evaluate_fresh_context_redteam(
            artifact_name="test-artifact",
            mission_state_path=None,
        )
        self.assertIsInstance(result, dict)
        self.assertIn("report_id", result)
        self.assertIn("status", result)
        self.assertEqual(result["status"], "complete")

    def test_evaluation_creates_artifacts(self):
        """Test that evaluation creates durable artifacts."""
        result = evaluate_fresh_context_redteam(
            artifact_name="test-artifact-2",
            mission_state_path=None,
        )
        report_json_path = Path(result["report_json_path"])
        report_md_path = Path(result["report_markdown_path"])
        
        self.assertTrue(report_json_path.exists(), "JSON report not created")
        self.assertTrue(report_md_path.exists(), "Markdown report not created")

    def test_evaluation_writes_valid_json(self):
        """Test that generated JSON is valid."""
        result = evaluate_fresh_context_redteam(
            artifact_name="test-artifact-3",
            mission_state_path=None,
        )
        report_json_path = Path(result["report_json_path"])
        
        content = json.loads(report_json_path.read_text())
        self.assertIsInstance(content, dict)
        self.assertIn("report_id", content)
        self.assertIn("alternative_explanations", content)

    def test_evaluation_creates_ledger_entry(self):
        """Test that ledger entry is created."""
        result = evaluate_fresh_context_redteam(
            artifact_name="test-artifact-4",
            mission_state_path=None,
        )
        ledger_entry = result.get("ledger_entry")
        self.assertIsNotNone(ledger_entry)
        self.assertEqual(ledger_entry["kind"], "fresh-context-redteam")
        self.assertIn("related_paths", ledger_entry)


class TestTranslationSupportCase(unittest.TestCase):
    """Test fresh-context redteam for the translation mission."""

    def test_translation_config_substrate_defined(self):
        """Test that the translation example is defined in substrates."""
        config_path = REPO_ROOT / "configs" / "autonomy" / "fresh-context-redteam.yaml"
        import yaml

        content = yaml.safe_load(config_path.read_text())
        substrates = content.get("substrates", {})
        
        self.assertIn("translation-pilot", substrates)
        asym_config = substrates["translation-pilot"]
        self.assertEqual(asym_config["project"], "translation-pilot")


if __name__ == "__main__":
    unittest.main()
