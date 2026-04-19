from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.self_optimization import (
    OptimizationReport,
    Recommendation,
    SignalSummary,
    _apply_constraints,
    _build_rationale,
    _classify_branch_health,
    _infer_phase,
    _load_json,
    _load_yaml,
    _make_recommendations,
    _risk_level_to_score,
    optimize_from_artifacts,
)
from deeploop.core.paths import MISSIONS_DIR, RUNS_DIR


# Test configuration constants
CONTRACT_PATH = REPO_ROOT / "configs" / "autonomy" / "self-optimization.yaml"
MISSION_STATE = MISSIONS_DIR / "translation-full-mission" / "mission_state.json"


class SelfOptimizationEngineTests(unittest.TestCase):
    """Tests for core self-optimization engine logic."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.contract = _load_yaml(CONTRACT_PATH)
        self.maxDiff = None

    def test_contract_loads_successfully(self) -> None:
        """Verify self-optimization contract is valid YAML."""
        self.assertIsInstance(self.contract, dict)
        self.assertEqual(self.contract.get("version"), 1)
        self.assertEqual(self.contract.get("policy_name"), "deeploop-self-optimization")

    def test_contract_has_required_sections(self) -> None:
        """Verify contract includes all required configuration sections."""
        required = ["data_sources", "thresholds", "strategies", "artifacts", "substrates"]
        for section in required:
            self.assertIn(section, self.contract, f"Missing section: {section}")

    def test_data_sources_configured(self) -> None:
        """Verify all data sources are defined in contract."""
        sources = self.contract.get("data_sources", {})
        expected = ["utility_scorer", "self_correction", "statistical_rigor", "confound_guard", "sanity_gates"]
        for source in expected:
            self.assertIn(source, sources)
            self.assertIn("artifact_patterns", sources[source])

    def test_thresholds_are_reasonable(self) -> None:
        """Verify optimization thresholds make sense."""
        thresholds = self.contract.get("thresholds", {})
        
        # Expansion should be higher utility than shrinkage
        high_floor = thresholds.get("high_utility_floor", 0)
        low_floor = thresholds.get("low_utility_floor", 1)
        self.assertGreater(high_floor, low_floor)
        
        # Both should be in 0-1 range
        self.assertGreaterEqual(high_floor, 0)
        self.assertLessEqual(high_floor, 1)
        self.assertGreaterEqual(low_floor, 0)
        self.assertLessEqual(low_floor, 1)

    def test_classify_branch_health(self) -> None:
        """Verify branch health classification from self-correction actions."""
        self.assertEqual(_classify_branch_health("continue"), "healthy")
        self.assertEqual(_classify_branch_health("reroute"), "degraded")
        self.assertEqual(_classify_branch_health("stop"), "degraded")
        self.assertEqual(_classify_branch_health("unknown"), "unknown")

    def test_risk_level_to_score(self) -> None:
        """Verify risk level conversion to numeric score."""
        self.assertEqual(_risk_level_to_score("low"), 0.2)
        self.assertEqual(_risk_level_to_score("medium"), 0.5)
        self.assertEqual(_risk_level_to_score("high"), 0.8)
        self.assertEqual(_risk_level_to_score("critical"), 1.0)
        self.assertEqual(_risk_level_to_score("unknown"), 0.5)

    def test_signal_summary_creation(self) -> None:
        """Verify SignalSummary dataclass works correctly."""
        summary = SignalSummary(
            timestamp="2024-04-12T15:00:00+00:00",
            utility_score=0.75,
            evidence_quality=250,
            cost_efficiency=0.65,
            confound_risk=0.3,
            branch_health="healthy",
            consistency_signal=0.8,
            sources_consulted=["utility_scorer", "self_correction"],
        )
        
        self.assertEqual(summary.utility_score, 0.75)
        self.assertEqual(summary.branch_health, "healthy")
        self.assertEqual(len(summary.sources_consulted), 2)
        
        # Verify to_dict works
        d = summary.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["utility_score"], 0.75)

    def test_recommendation_creation(self) -> None:
        """Verify Recommendation dataclass works correctly."""
        rec = Recommendation(
            recommendation_id="rec-test-1",
            category="expansion",
            target="branch_count",
            action="recommend_branch_expansion",
            confidence_level=0.85,
            rationale="Test recommendation",
            estimated_impact={"new_branches": 2},
            fallback_action="maintain_current_strategy",
        )
        
        self.assertEqual(rec.recommendation_id, "rec-test-1")
        self.assertEqual(rec.category, "expansion")
        self.assertEqual(rec.confidence_level, 0.85)
        
        d = rec.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["category"], "expansion")

    def test_infer_phase_unknown(self) -> None:
        """Verify phase inference returns 'unknown' for missing state."""
        phase = _infer_phase(None)
        self.assertEqual(phase, "unknown")
        
        phase = _infer_phase(Path("/nonexistent/path"))
        self.assertEqual(phase, "unknown")

    def test_build_rationale_with_signals(self) -> None:
        """Verify rationale building includes signal information."""
        summary = SignalSummary(
            timestamp="2024-04-12T15:00:00+00:00",
            utility_score=0.78,
            evidence_quality=250,
            cost_efficiency=0.65,
            confound_risk=0.7,
            branch_health="degraded",
            consistency_signal=0.8,
            sources_consulted=["utility_scorer"],
        )
        rec = Recommendation(
            recommendation_id="rec-test",
            category="adjustment",
            target="branch_config",
            action="test_action",
            confidence_level=0.75,
            rationale="Test",
            estimated_impact={},
        )
        
        rationale = _build_rationale(summary, [rec])
        self.assertIn("0.78", rationale)  # Utility score
        self.assertIn("degraded", rationale)  # Branch health
        self.assertIn("confound", rationale)  # Confound risk highlighted
        self.assertIn("adjustment", rationale)  # Recommendation category

    def test_make_recommendations_expansion(self) -> None:
        """Verify recommendations for high-utility, consistent branches."""
        summary = SignalSummary(
            timestamp="2024-04-12T15:00:00+00:00",
            utility_score=0.80,  # High
            evidence_quality=400,
            cost_efficiency=0.70,
            confound_risk=0.2,
            branch_health="healthy",
            consistency_signal=0.85,  # Strong
            sources_consulted=["utility_scorer"],
        )
        
        recs = _make_recommendations(summary, self.contract)
        
        # Should have at least one expansion recommendation
        expansion_recs = [r for r in recs if r.category == "expansion"]
        self.assertGreater(len(expansion_recs), 0)
        
        # Expansion confidence should be high
        for rec in expansion_recs:
            self.assertGreaterEqual(rec.confidence_level, 0.75)

    def test_make_recommendations_shrinkage(self) -> None:
        """Verify recommendations for low-utility, low-evidence branches."""
        summary = SignalSummary(
            timestamp="2024-04-12T15:00:00+00:00",
            utility_score=0.25,  # Low
            evidence_quality=50,  # Low
            cost_efficiency=0.30,
            confound_risk=0.4,
            branch_health="degraded",
            consistency_signal=0.4,
            sources_consulted=["utility_scorer"],
        )
        
        recs = _make_recommendations(summary, self.contract)
        
        # Should have shrinkage or adjustment recommendations
        non_expansion = [r for r in recs if r.category != "expansion"]
        self.assertGreater(len(non_expansion), 0)

    def test_make_recommendations_confound_mitigation(self) -> None:
        """Verify recommendations for high confound risk."""
        summary = SignalSummary(
            timestamp="2024-04-12T15:00:00+00:00",
            utility_score=0.60,
            evidence_quality=200,
            cost_efficiency=0.65,
            confound_risk=0.85,  # High
            branch_health="healthy",
            consistency_signal=0.7,
            sources_consulted=["confound_guard"],
        )
        
        recs = _make_recommendations(summary, self.contract)
        
        # Should have confound mitigation recommendation
        confound_recs = [r for r in recs if "confound" in r.action.lower()]
        self.assertGreater(len(confound_recs), 0)

    def test_apply_constraints_max_recommendations(self) -> None:
        """Verify constraints limit total recommendations."""
        recs = [
            Recommendation(
                recommendation_id=f"rec-{i}",
                category="expansion",
                target="branch_count",
                action="test",
                confidence_level=0.8,
                rationale="Test",
                estimated_impact={},
            )
            for i in range(10)
        ]
        
        constrained, applied = _apply_constraints(recs, self.contract)
        
        # Should be capped at max from contract (likely 5)
        max_allowed = self.contract.get("output_constraints", {}).get("max_recommendations_per_run", 5)
        self.assertLessEqual(len(constrained), max_allowed)
        self.assertGreater(len(applied), 0)  # Constraints should have been applied

    def test_apply_constraints_preserves_rationale(self) -> None:
        """Verify constraints preserve recommendation quality."""
        recs = [
            Recommendation(
                recommendation_id="rec-1",
                category="expansion",
                target="branch_count",
                action="expand",
                confidence_level=0.95,  # High confidence
                rationale="Strong signal",
                estimated_impact={"impact": "high"},
            ),
            Recommendation(
                recommendation_id="rec-2",
                category="adjustment",
                target="profile",
                action="tune",
                confidence_level=0.50,  # Low confidence
                rationale="Weak signal",
                estimated_impact={"impact": "low"},
            ),
        ]
        
        constrained, _ = _apply_constraints(recs, self.contract)
        
        # High-confidence rec should be preserved
        high_conf = [r for r in constrained if r.confidence_level > 0.8]
        self.assertGreater(len(high_conf), 0)

    def test_optimization_report_creation(self) -> None:
        """Verify OptimizationReport dataclass construction."""
        summary = SignalSummary(
            timestamp="2024-04-12T15:00:00+00:00",
            utility_score=0.75,
            evidence_quality=300,
            cost_efficiency=0.65,
            confound_risk=0.3,
            branch_health="healthy",
            consistency_signal=0.8,
            sources_consulted=["utility_scorer"],
        )
        recs = [
            Recommendation(
                recommendation_id="rec-1",
                category="expansion",
                target="branch_count",
                action="expand",
                confidence_level=0.8,
                rationale="Test",
                estimated_impact={},
            ),
        ]
        
        report = OptimizationReport(
            timestamp="2024-04-12T15:00:00+00:00",
            mission_id="translation-full",
            optimization_phase="post-baseline",
            signal_summary=summary,
            recommendations=recs,
            decision_rationale="Test rationale",
            bounded_constraints_applied=["test_constraint"],
            next_observation_window_days=6,
        )
        
        self.assertEqual(report.mission_id, "translation-full")
        self.assertEqual(report.optimization_phase, "post-baseline")
        self.assertEqual(len(report.recommendations), 1)
        
        d = report.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["mission_id"], "translation-full")
        self.assertIsInstance(d["signal_summary"], dict)
        self.assertIsInstance(d["recommendations"], list)


class SelfOptimizationIntegrationTests(unittest.TestCase):
    """Integration tests for self-optimization engine with real artifacts."""

    def test_engine_handles_missing_artifacts_gracefully(self) -> None:
        """Verify engine works with minimal or missing artifacts."""
        # Create a temp directory with no artifacts
        test_dir = RUNS_DIR / "test_self_optimization_missing"
        test_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            result = optimize_from_artifacts(
                artifact_dir=test_dir,
                mission_id="test-mission",
                contract_path=CONTRACT_PATH,
            )
            
            # Should still produce output
            self.assertIn("report_json_path", result)
            self.assertIn("recommendations_yaml_path", result)
            
            # Report should exist
            self.assertTrue(result["report_json_path"].exists())
            
            # Should have handled missing signals gracefully
            report = result.get("report", {})
            self.assertEqual(report.get("mission_id"), "test-mission")
        finally:
            # Cleanup
            import shutil
            if test_dir.exists():
                shutil.rmtree(test_dir)

    def test_output_artifacts_are_valid_json(self) -> None:
        """Verify generated JSON artifacts are valid."""
        test_dir = RUNS_DIR / "test_self_optimization_json"
        test_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            result = optimize_from_artifacts(
                artifact_dir=test_dir,
                mission_id="test-json",
                contract_path=CONTRACT_PATH,
            )
            
            # Load and validate JSON
            report_path = result["report_json_path"]
            report_json = json.loads(report_path.read_text(encoding="utf-8"))
            
            self.assertIsInstance(report_json, dict)
            self.assertEqual(report_json["mission_id"], "test-json")
            self.assertIn("timestamp", report_json)
            self.assertIn("signal_summary", report_json)
            self.assertIn("recommendations", report_json)
            self.assertIsInstance(report_json["recommendations"], list)
        finally:
            import shutil
            if test_dir.exists():
                shutil.rmtree(test_dir)

    def test_ledger_entry_structure(self) -> None:
        """Verify ledger entry has correct structure."""
        test_dir = RUNS_DIR / "test_self_optimization_ledger"
        test_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            result = optimize_from_artifacts(
                artifact_dir=test_dir,
                mission_id="test-ledger",
                contract_path=CONTRACT_PATH,
            )
            
            entry = result.get("ledger_entry", {})
            
            # Verify ledger structure
            self.assertEqual(entry.get("kind"), "self-optimization")
            self.assertEqual(entry.get("mission_id"), "test-ledger")
            self.assertIn("created_at", entry)
            self.assertIn("summary", entry)
            self.assertIn("status", entry)
            self.assertIn("metadata", entry)
            self.assertIn("signals_sources", entry.get("metadata", {}))
        finally:
            import shutil
            if test_dir.exists():
                shutil.rmtree(test_dir)


class SelfOptimizationConfigTests(unittest.TestCase):
    """Tests for configuration file validity and consistency."""

    def setUp(self) -> None:
        """Load contract for validation."""
        self.contract = _load_yaml(CONTRACT_PATH)

    def test_weights_sum_to_one(self) -> None:
        """Verify multi-factor weights sum to 1.0 (if present)."""
        weights = self.contract.get("weights", {})
        if weights:
            total = sum(weights.values())
            self.assertAlmostEqual(total, 1.0, places=5)

    def test_all_strategies_have_conditions(self) -> None:
        """Verify strategy entries have required structure."""
        strategies = self.contract.get("strategies", {})
        for strategy_type, strategies_dict in strategies.items():
            self.assertIsInstance(strategies_dict, dict)
            for strategy_name, strategy_config in strategies_dict.items():
                self.assertIn("condition", strategy_config)
                self.assertIn("action", strategy_config)
                self.assertIn("parameters", strategy_config)

    def test_substrates_have_valid_structure(self) -> None:
        """Verify substrate configurations are well-formed."""
        substrates = self.contract.get("substrates", {})
        for substrate_name, substrate_config in substrates.items():
            self.assertIn("project", substrate_config)
            self.assertIn("run_roots", substrate_config)
            self.assertIn("optimization_targets", substrate_config)

    def test_artifact_output_config_valid(self) -> None:
        """Verify artifact output configuration is well-formed."""
        artifacts = self.contract.get("artifacts", {})
        for artifact_type, artifact_config in artifacts.items():
            # Report and recommendations should have filename_pattern
            # Ledger entry is just metadata
            if artifact_type != "ledger_entry":
                self.assertIn("filename_pattern", artifact_config)

    def test_required_files_exist(self) -> None:
        """Verify all required files for self-optimization exist."""
        repo_root = Path(__file__).resolve().parents[1]
        self.assertTrue((repo_root / "configs" / "autonomy" / "self-optimization.yaml").exists())
        self.assertTrue((repo_root / "docs" / "design" / "self-optimization.md").exists())
        self.assertTrue((repo_root / "scripts" / "mission" / "run_self_optimization.py").exists())
        self.assertTrue((repo_root / "src" / "deeploop" / "research" / "self_optimization.py").exists())


if __name__ == "__main__":
    unittest.main()
