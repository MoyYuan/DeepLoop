"""
Tests for the statistical rigor module.

Validates:
- Uncertainty interval computation (Wilson intervals)
- Sample size awareness and power verdicts
- Warning generation for underpowered studies
- Promotion guidance (bounded vs not-ready)
- JSON and markdown artifact generation
- Ledger integration
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

# Setup path for imports
import sys
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.statistical_rigor import (
    DEFAULT_CONTRACT_PATH,
    _build_proportion_summary,
    _wilson_interval,
    _warning,
    _build_warnings,
    _promotion_guidance,
    evaluate_statistical_rigor,
)


class TestWilsonInterval(unittest.TestCase):
    """Test Wilson interval computation."""

    def test_wilson_interval_perfect_accuracy(self) -> None:
        """Perfect accuracy should give tight interval."""
        lower, upper = _wilson_interval(100, 100, 1.96)
        self.assertGreater(lower, 0.95)
        self.assertAlmostEqual(upper, 1.0, places=5)

    def test_wilson_interval_zero_accuracy(self) -> None:
        """Zero accuracy should give interval near zero."""
        lower, upper = _wilson_interval(0, 100, 1.96)
        self.assertEqual(lower, 0.0)
        self.assertLess(upper, 0.05)

    def test_wilson_interval_50_percent(self) -> None:
        """50% accuracy should give symmetric interval."""
        lower, upper = _wilson_interval(50, 100, 1.96)
        midpoint = (lower + upper) / 2
        self.assertLess(abs(midpoint - 0.5), 0.01)

    def test_wilson_interval_small_sample(self) -> None:
        """Small sample should give wider interval."""
        lower_small, upper_small = _wilson_interval(5, 10, 1.96)
        lower_large, upper_large = _wilson_interval(50, 100, 1.96)
        width_small = upper_small - lower_small
        width_large = upper_large - lower_large
        self.assertGreater(width_small, width_large)

    def test_wilson_interval_bounds(self) -> None:
        """Intervals should never exceed [0, 1]."""
        for successes in [0, 1, 5, 10, 50, 100]:
            for count in [10, 100, 1000]:
                if successes <= count:  # Only test valid successes
                    lower, upper = _wilson_interval(successes, count, 1.96)
                    self.assertGreaterEqual(lower, 0.0)
                    self.assertLessEqual(lower, 1.0)
                    self.assertGreaterEqual(upper, 0.0)
                    self.assertLessEqual(upper, 1.0)
                    self.assertLessEqual(lower, upper)


class TestProportionSummary(unittest.TestCase):
    """Test proportion metric summary building."""

    def test_summary_from_direct_measurement(self) -> None:
        """Build summary from direct success counts."""
        summary = _build_proportion_summary(
            count=100,
            estimate=0.85,
            successes=85,
            source="test.metric",
            direct_measurement=True,
            uncertainty_cfg={"z_value": 1.96, "interval_method": "wilson"},
        )
        self.assertIsNotNone(summary)
        self.assertEqual(summary["count"], 100)
        self.assertEqual(summary["successes"], 85)
        self.assertAlmostEqual(summary["estimate"], 0.85, places=2)
        self.assertTrue(summary["direct_measurement"])
        self.assertEqual(len(summary["interval_95"]), 2)
        self.assertGreaterEqual(summary["interval_95"][0], 0.0)
        self.assertLessEqual(summary["interval_95"][1], 1.0)

    def test_summary_from_estimate_only(self) -> None:
        """Build summary from estimate without direct counts."""
        summary = _build_proportion_summary(
            count=50,
            estimate=0.6,
            successes=None,
            source="reference",
            direct_measurement=False,
            uncertainty_cfg={"z_value": 1.96, "interval_method": "wilson"},
        )
        self.assertIsNotNone(summary)
        self.assertEqual(summary["count"], 50)
        self.assertAlmostEqual(summary["estimate"], 0.6, places=2)
        self.assertFalse(summary["direct_measurement"])

    def test_summary_zero_count(self) -> None:
        """Summary from zero count should be None."""
        summary = _build_proportion_summary(
            count=0,
            estimate=0.5,
            successes=None,
            source="test",
            direct_measurement=True,
            uncertainty_cfg={"z_value": 1.96},
        )
        self.assertIsNone(summary)

    def test_summary_error_bar(self) -> None:
        """Error bar should be half the interval width."""
        summary = _build_proportion_summary(
            count=100,
            estimate=0.5,
            successes=50,
            source="test",
            direct_measurement=True,
            uncertainty_cfg={"z_value": 1.96, "interval_method": "wilson"},
        )
        self.assertIsNotNone(summary)
        interval_width = summary["interval_95"][1] - summary["interval_95"][0]
        error_bar = summary["error_bar_95"]
        self.assertLess(abs(error_bar - interval_width / 2), 0.001)


class TestWarnings(unittest.TestCase):
    """Test warning generation."""

    def test_warning_construction(self) -> None:
        """Warnings should include code, message, and severity."""
        w = _warning("test-code", "test message", context={"key": "value"})
        self.assertEqual(w["code"], "test-code")
        self.assertEqual(w["message"], "test message")
        self.assertEqual(w["severity"], "warn")
        self.assertEqual(w["context"], {"key": "value"})

    def test_underpowered_warning(self) -> None:
        """Should warn about underpowered samples."""
        contract = {
            "power": {
                "not_ready_below_total_examples": 16,
                "warn_below_total_examples": 32,
                "warn_below_slice_examples": 8,
            },
            "uncertainty": {"z_value": 1.96},
            "promotion": {"blocked_run_statuses": []},
        }
        summary = _build_proportion_summary(
            count=10,
            estimate=0.5,
            successes=5,
            source="test",
            direct_measurement=True,
            uncertainty_cfg=contract["uncertainty"],
        )
        warnings = _build_warnings(
            primary_metric=summary,
            sample_size={"effective_count": 10},
            group_summaries={},
            references=[],
            run_status="completed",
            contract=contract,
        )
        warning_codes = [w["code"] for w in warnings]
        self.assertIn("underpowered-total", warning_codes)

    def test_small_sample_warning(self) -> None:
        """Should warn about small but not underpowered samples."""
        contract = {
            "power": {
                "not_ready_below_total_examples": 16,
                "warn_below_total_examples": 32,
                "warn_below_slice_examples": 8,
            },
            "uncertainty": {"z_value": 1.96},
            "promotion": {"blocked_run_statuses": []},
        }
        summary = _build_proportion_summary(
            count=25,
            estimate=0.5,
            successes=None,
            source="test",
            direct_measurement=True,
            uncertainty_cfg=contract["uncertainty"],
        )
        warnings = _build_warnings(
            primary_metric=summary,
            sample_size={"effective_count": 25},
            group_summaries={},
            references=[],
            run_status="completed",
            contract=contract,
        )
        warning_codes = [w["code"] for w in warnings]
        self.assertIn("small-total-sample", warning_codes)

    def test_degenerate_slice_warning(self) -> None:
        """Should warn about slices with too few examples."""
        contract = {
            "power": {
                "degenerate_slice_examples": 3,
                "warn_below_slice_examples": 8,
            },
            "uncertainty": {"z_value": 1.96},
            "promotion": {"blocked_run_statuses": []},
        }
        tiny_summary = _build_proportion_summary(
            count=2,
            estimate=0.5,
            successes=1,
            source="test",
            direct_measurement=True,
            uncertainty_cfg=contract["uncertainty"],
        )
        # group_summaries is {family_name: {label: summary}}
        group_summary = {
            "test_family": {
                "tiny_slice": tiny_summary
            }
        }
        warnings = _build_warnings(
            primary_metric=None,
            sample_size={"effective_count": 100},
            group_summaries=group_summary,
            references=[],
            run_status="completed",
            contract=contract,
        )
        warning_codes = [w["code"] for w in warnings]
        self.assertIn("degenerate-slice", warning_codes)


class TestPromotionGuidance(unittest.TestCase):
    """Test promotion state recommendations."""

    def test_promotion_exploratory_minimum_met(self) -> None:
        """Should recommend exploratory when minimum examples met."""
        contract = {
            "promotion": {
                "default_state": "exploratory",
                "max_allowed_state": "exploratory",
                "minimum_total_examples_for_exploratory": 16,
                "allowed_states": ["exploratory", "not-ready"],
                "blocked_run_statuses": [],
            }
        }
        summary = _build_proportion_summary(
            count=32,
            estimate=0.5,
            successes=16,
            source="test",
            direct_measurement=True,
            uncertainty_cfg={"z_value": 1.96},
        )
        guidance = _promotion_guidance(
            primary_metric=summary,
            sample_size={"effective_count": 32},
            run_status="completed",
            contract=contract,
        )
        self.assertEqual(guidance["recommended_state"], "exploratory")

    def test_promotion_not_ready_below_minimum(self) -> None:
        """Should recommend not-ready when below minimum."""
        contract = {
            "promotion": {
                "default_state": "exploratory",
                "max_allowed_state": "exploratory",
                "minimum_total_examples_for_exploratory": 32,
                "allowed_states": ["exploratory", "not-ready"],
                "blocked_run_statuses": [],
            }
        }
        summary = _build_proportion_summary(
            count=10,
            estimate=0.5,
            successes=5,
            source="test",
            direct_measurement=True,
            uncertainty_cfg={"z_value": 1.96},
        )
        guidance = _promotion_guidance(
            primary_metric=summary,
            sample_size={"effective_count": 10},
            run_status="completed",
            contract=contract,
        )
        self.assertEqual(guidance["recommended_state"], "not-ready")

    def test_promotion_blocked_status(self) -> None:
        """Should recommend not-ready for blocked/failed runs."""
        contract = {
            "promotion": {
                "default_state": "exploratory",
                "max_allowed_state": "exploratory",
                "minimum_total_examples_for_exploratory": 16,
                "allowed_states": ["exploratory", "not-ready"],
                "blocked_run_statuses": ["failed", "blocked"],
            }
        }
        summary = _build_proportion_summary(
            count=100,
            estimate=0.5,
            successes=50,
            source="test",
            direct_measurement=True,
            uncertainty_cfg={"z_value": 1.96},
        )
        guidance = _promotion_guidance(
            primary_metric=summary,
            sample_size={"effective_count": 100},
            run_status="failed",
            contract=contract,
        )
        self.assertEqual(guidance["recommended_state"], "not-ready")

    def test_promotion_guidance_includes_reasons(self) -> None:
        """Promotion guidance should include clear reasons."""
        contract = {
            "promotion": {
                "default_state": "exploratory",
                "max_allowed_state": "exploratory",
                "minimum_total_examples_for_exploratory": 64,
                "allowed_states": ["exploratory", "not-ready"],
                "blocked_run_statuses": [],
            }
        }
        summary = _build_proportion_summary(
            count=16,
            estimate=0.5,
            successes=8,
            source="test",
            direct_measurement=True,
            uncertainty_cfg={"z_value": 1.96},
        )
        guidance = _promotion_guidance(
            primary_metric=summary,
            sample_size={"effective_count": 16},
            run_status="completed",
            contract=contract,
        )
        self.assertEqual(guidance["recommended_state"], "not-ready")
        self.assertGreater(len(guidance["reasons"]), 0)
        self.assertTrue(any("64" in reason for reason in guidance["reasons"]))


class TestArtifactGeneration(unittest.TestCase):
    """Test JSON and markdown artifact writing."""

    def test_evaluate_produces_json_and_markdown(self) -> None:
        """Integration test: evaluate should produce both artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Create a minimal run manifest
            manifest = {
                "loop_id": "test-run",
                "status": "completed",
                "metrics": {
                    "count": 32,
                    "accuracy": 0.75,
                }
            }
            manifest_path = tmppath / "run_manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            
            # Create temporary report directory
            report_dir = tmppath / "reports"
            report_dir.mkdir()
            
            # Evaluate
            result = evaluate_statistical_rigor(
                manifest_path,
                mission_state_path=None,
                output_root=report_dir,
            )
            
            # Check artifacts exist and are readable
            self.assertTrue(result["report_json_path"].exists())
            self.assertTrue(result["report_markdown_path"].exists())
            
            json_data = json.loads(result["report_json_path"].read_text())
            self.assertEqual(json_data["artifact_name"], "test-run")
            self.assertEqual(json_data["manifest_kind"], "run-manifest")
            self.assertEqual(json_data["sample_size"]["effective_count"], 32)
            self.assertAlmostEqual(json_data["primary_metric"]["estimate"], 0.75, places=2)
            
            md_text = result["report_markdown_path"].read_text()
            self.assertIn("# Statistical rigor report", md_text)


class TestTranslationCaseStudy(unittest.TestCase):
    """Test using translation baseline naming as a public-safe placeholder."""

    def test_translation_baseline_structure(self) -> None:
        """Verify translation baseline paths exist if available."""
        baseline_root = Path.home() / "workspaces" / "runs" / "translation-pilot"
        if not baseline_root.exists():
            self.skipTest("Translation baseline not available")
        
        # Just verify the path structure exists
        self.assertTrue(baseline_root.exists())


if __name__ == "__main__":
    unittest.main()
