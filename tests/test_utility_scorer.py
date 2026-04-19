"""
Tests for the utility scorer module.

Validates:
- Multi-factor score computation
- Evidence quality calculation
- Replication gap assessment
- Cost/risk profiling
- Novelty proxy scoring
- Expected information gain
- Recommendation logic
- Deterministic output
- JSON and markdown artifact generation
- Ledger integration
"""

from __future__ import annotations

import json
import shutil
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

from deeploop.research.utility_scorer import (
    DEFAULT_CROSS_BRANCH_VARIANCE,
    DEFAULT_CONTRACT_PATH,
    BranchScore,
    ScoreFactors,
    _compute_cost_risk_profile,
    _compute_evidence_quality,
    _compute_expected_information_gain,
    _compute_novelty_proxy,
    _compute_overall_score,
    _compute_replication_gap,
    _get_recommendation,
    _load_branch_artifacts,
    _round_float,
    evaluate_utility_score,
    score_branch,
)


class TestEvidenceQuality(unittest.TestCase):
    """Test evidence quality factor computation."""

    def test_high_evidence_quality(self) -> None:
        """High effective count and narrow CI should yield high score."""
        bundle = {
            "metadata": {
                "effective_count": 500,
                "warning_count": 0,
            },
            "metrics": {
                "primary_estimate": {
                    "confidence_interval_width": 0.1,
                }
            },
        }
        quality, _ = _compute_evidence_quality(bundle)
        self.assertGreater(quality, 0.7)
        self.assertLessEqual(quality, 1.0)

    def test_low_evidence_quality(self) -> None:
        """Low effective count should yield low score."""
        bundle = {
            "metadata": {
                "effective_count": 10,
                "warning_count": 3,
            },
            "metrics": {
                "primary_estimate": {
                    "confidence_interval_width": 0.8,
                }
            },
        }
        quality, _ = _compute_evidence_quality(bundle)
        self.assertLess(quality, 0.5)

    def test_evidence_deterministic(self) -> None:
        """Same input should always produce same score."""
        bundle = {
            "metadata": {
                "effective_count": 100,
                "warning_count": 1,
            },
            "metrics": {
                "primary_estimate": {
                    "confidence_interval_width": 0.2,
                }
            },
        }
        score1, _ = _compute_evidence_quality(bundle)
        score2, _ = _compute_evidence_quality(bundle)
        self.assertEqual(score1, score2)


class TestReplicationGap(unittest.TestCase):
    """Test replication gap factor computation."""

    def test_high_replication(self) -> None:
        """High consistency and pass rate should yield high score."""
        bundle = {
            "metadata": {
                "self_correction_consistency": 0.9,
                "sanity_pass_rate": 0.95,
                "cross_branch_variance": 0.05,
            }
        }
        gap, _ = _compute_replication_gap(bundle)
        self.assertGreater(gap, 0.8)

    def test_low_replication(self) -> None:
        """Low consistency and high variance should yield low score."""
        bundle = {
            "metadata": {
                "self_correction_consistency": 0.3,
                "sanity_pass_rate": 0.4,
                "cross_branch_variance": 0.7,
            }
        }
        gap, _ = _compute_replication_gap(bundle)
        self.assertLess(gap, 0.4)


class TestCostRiskProfile(unittest.TestCase):
    """Test cost/risk profile computation."""

    def test_efficient_branch(self) -> None:
        """Low resource usage should yield high score."""
        bundle = {
            "runtime_metrics": {
                "gpu_hours": 0.5,
                "peak_memory_gb": 10.0,
                "retry_count": 0,
                "total_seconds": 1800,
            }
        }
        cost, _ = _compute_cost_risk_profile(bundle)
        self.assertGreater(cost, 0.7)

    def test_expensive_branch(self) -> None:
        """High resource usage should yield low score."""
        bundle = {
            "runtime_metrics": {
                "gpu_hours": 10.0,
                "peak_memory_gb": 40.0,
                "retry_count": 5,
                "total_seconds": 36000,
            }
        }
        cost, _ = _compute_cost_risk_profile(bundle)
        self.assertLess(cost, 0.5)


class TestNoveltyProxy(unittest.TestCase):
    """Test novelty proxy factor computation."""

    def test_high_novelty(self) -> None:
        """Large deviation and high unexpectedness should yield high score."""
        bundle = {
            "metrics": {
                "finding_deviation_from_baseline": 0.25,
                "unexpectedness_factor": 0.9,
            },
            "findings": {
                "total_count": 10,
                "baseline_count": 3,
            }
        }
        novelty, _ = _compute_novelty_proxy(bundle)
        self.assertGreater(novelty, 0.6)

    def test_low_novelty(self) -> None:
        """Small deviation and low unexpectedness should yield low score."""
        bundle = {
            "metrics": {
                "finding_deviation_from_baseline": 0.01,
                "unexpectedness_factor": 0.2,
            },
            "findings": {
                "total_count": 1,
                "baseline_count": 2,
            }
        }
        novelty, _ = _compute_novelty_proxy(bundle)
        self.assertLess(novelty, 0.3)


class TestExpectedInformationGain(unittest.TestCase):
    """Test expected information gain computation."""

    def test_high_information_gain(self) -> None:
        """High confound pass rate and clarity should yield high score."""
        bundle = {
            "metadata": {
                "confound_pass_rate": 0.95,
                "mechanistic_clarity": 0.85,
                "gap_closure_potential": 0.8,
            }
        }
        eig, _ = _compute_expected_information_gain(bundle)
        self.assertGreater(eig, 0.8)

    def test_low_information_gain(self) -> None:
        """Low pass rate and clarity should yield low score."""
        bundle = {
            "metadata": {
                "confound_pass_rate": 0.3,
                "mechanistic_clarity": 0.2,
                "gap_closure_potential": 0.15,
            }
        }
        eig, _ = _compute_expected_information_gain(bundle)
        self.assertLess(eig, 0.3)


class TestOverallScore(unittest.TestCase):
    """Test overall score computation with penalties."""

    def test_well_supported_branch(self) -> None:
        """High factors should yield high overall score."""
        factors = ScoreFactors(
            evidence_quality=0.85,
            replication_gap=0.80,
            cost_risk_profile=0.75,
            novelty_proxy=0.70,
            expected_information_gain=0.80,
        )
        bundle = {
            "runtime_metrics": {
                "gpu_hours": 0.5,
            }
        }
        score, alerts = _compute_overall_score(factors, bundle)
        self.assertGreater(score, 0.75)
        self.assertEqual(len(alerts), 0)

    def test_low_evidence_penalty(self) -> None:
        """Low evidence quality should trigger penalty."""
        factors = ScoreFactors(
            evidence_quality=0.20,
            replication_gap=0.80,
            cost_risk_profile=0.80,
            novelty_proxy=0.80,
            expected_information_gain=0.80,
        )
        bundle = {
            "runtime_metrics": {
                "gpu_hours": 0.5,
            }
        }
        score, alerts = _compute_overall_score(factors, bundle)
        self.assertTrue(any("evidence" in a.lower() for a in alerts))
        # Score should be reduced by penalty
        weighted = (
            0.25 * 0.20 +
            0.20 * 0.80 +
            0.20 * 0.80 +
            0.20 * 0.80 +
            0.15 * 0.80
        )
        self.assertLess(score, weighted)

    def test_high_confound_risk_penalty(self) -> None:
        """High confound risk should trigger penalty."""
        factors = ScoreFactors(
            evidence_quality=0.80,
            replication_gap=0.80,
            cost_risk_profile=0.80,
            novelty_proxy=0.80,
            expected_information_gain=0.20,  # Low EIG -> high confound risk
        )
        bundle = {
            "runtime_metrics": {
                "gpu_hours": 0.5,
            }
        }
        score, alerts = _compute_overall_score(factors, bundle)
        self.assertTrue(any("confound" in a.lower() for a in alerts))


class TestRecommendations(unittest.TestCase):
    """Test recommendation logic."""

    def test_prioritize_recommendation(self) -> None:
        """High score with strong evidence should recommend PRIORITIZE."""
        factors = ScoreFactors(
            evidence_quality=0.85,
            replication_gap=0.80,
            cost_risk_profile=0.75,
            novelty_proxy=0.70,
            expected_information_gain=0.80,
        )
        score = 0.85
        alerts: list[str] = []
        rec, _ = _get_recommendation(score, factors, alerts)
        self.assertEqual(rec, "PRIORITIZE")

    def test_continue_recommendation(self) -> None:
        """Moderate-high score should recommend CONTINUE."""
        factors = ScoreFactors(
            evidence_quality=0.70,
            replication_gap=0.65,
            cost_risk_profile=0.60,
            novelty_proxy=0.55,
            expected_information_gain=0.60,
        )
        score = 0.65
        alerts: list[str] = []
        rec, _ = _get_recommendation(score, factors, alerts)
        self.assertEqual(rec, "CONTINUE")

    def test_defer_recommendation(self) -> None:
        """Low-moderate score should recommend DEFER."""
        factors = ScoreFactors(
            evidence_quality=0.45,
            replication_gap=0.45,
            cost_risk_profile=0.45,
            novelty_proxy=0.45,
            expected_information_gain=0.45,
        )
        score = 0.45
        alerts: list[str] = []
        rec, _ = _get_recommendation(score, factors, alerts)
        self.assertEqual(rec, "DEFER")

    def test_prune_recommendation(self) -> None:
        """Very low score should recommend PRUNE."""
        factors = ScoreFactors(
            evidence_quality=0.20,
            replication_gap=0.20,
            cost_risk_profile=0.20,
            novelty_proxy=0.20,
            expected_information_gain=0.20,
        )
        score = 0.20
        alerts: list[str] = []
        rec, _ = _get_recommendation(score, factors, alerts)
        self.assertEqual(rec, "PRUNE")

    def test_continue_high_novelty(self) -> None:
        """Moderate score with high novelty should recommend CONTINUE."""
        factors = ScoreFactors(
            evidence_quality=0.50,
            replication_gap=0.50,
            cost_risk_profile=0.50,
            novelty_proxy=0.80,  # High novelty
            expected_information_gain=0.50,
        )
        score = 0.55
        alerts: list[str] = []
        rec, _ = _get_recommendation(score, factors, alerts)
        self.assertEqual(rec, "CONTINUE")


class TestBranchScoring(unittest.TestCase):
    """Test full branch scoring."""

    def test_score_branch_creates_score(self) -> None:
        """Scoring a branch should produce BranchScore object."""
        with tempfile.TemporaryDirectory() as tmpdir:
            branch_dir = Path(tmpdir) / "test_branch"
            branch_dir.mkdir()

            # Create minimal manifest
            manifest = {
                "artifacts": {
                    "runtime": {
                        "gpu_hours": 1.0,
                        "peak_memory_gb": 20.0,
                        "retry_count": 0,
                        "total_seconds": 3600,
                    }
                }
            }
            (branch_dir / "manifest.json").write_text(
                json.dumps(manifest) + "\n"
            )

            score = score_branch("test_branch", branch_dir)
            self.assertIsInstance(score, BranchScore)
            self.assertEqual(score.branch_id, "test_branch")
            self.assertGreaterEqual(score.overall_score, 0.0)
            self.assertLessEqual(score.overall_score, 1.0)
            self.assertIn(
                score.recommendation,
                ["PRIORITIZE", "CONTINUE", "DEFER", "PRUNE"]
            )

    def test_score_branch_deterministic(self) -> None:
        """Scoring same branch twice should yield identical scores."""
        with tempfile.TemporaryDirectory() as tmpdir:
            branch_dir = Path(tmpdir) / "test_branch"
            branch_dir.mkdir()

            manifest = {
                "artifacts": {
                    "runtime": {
                        "gpu_hours": 1.0,
                        "peak_memory_gb": 20.0,
                        "retry_count": 0,
                        "total_seconds": 3600,
                    }
                }
            }
            (branch_dir / "manifest.json").write_text(
                json.dumps(manifest) + "\n"
            )

            score1 = score_branch("test_branch", branch_dir)
            score2 = score_branch("test_branch", branch_dir)

            self.assertEqual(score1.overall_score, score2.overall_score)
            self.assertEqual(score1.recommendation, score2.recommendation)
            self.assertEqual(
                score1.factors.to_dict(),
                score2.factors.to_dict()
            )


class TestArtifactLoading(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_root = REPO_ROOT / "reports" / "test-fixtures" / "utility-scorer"
        shutil.rmtree(self.fixture_root, ignore_errors=True)
        self.fixture_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.fixture_root, ignore_errors=True)

    def test_load_branch_artifacts_records_warning_and_uses_named_variance_default(
        self,
    ) -> None:
        branch_dir = self.fixture_root / "branch-a"
        branch_dir.mkdir(parents=True, exist_ok=True)
        (branch_dir / "sanity-gates.json").write_text("{not-json\n", encoding="utf-8")

        bundle = _load_branch_artifacts(branch_dir)

        self.assertEqual(
            bundle["metadata"]["cross_branch_variance"],
            DEFAULT_CROSS_BRANCH_VARIANCE,
        )
        self.assertEqual(len(bundle["artifact_warnings"]), 1)
        self.assertIn("sanity-gates artifact", bundle["artifact_warnings"][0])

    def test_score_branch_surfaces_artifact_warnings_in_metadata(self) -> None:
        branch_dir = self.fixture_root / "branch-b"
        branch_dir.mkdir(parents=True, exist_ok=True)
        (branch_dir / "manifest.json").write_text("{bad-json\n", encoding="utf-8")

        score = score_branch("branch-b", branch_dir)

        self.assertIsInstance(score, BranchScore)
        self.assertEqual(len(score.metadata["artifact_warnings"]), 1)
        self.assertIn("manifest artifact", score.metadata["artifact_warnings"][0])


class TestEvaluateUtilityScore(unittest.TestCase):
    """Test full utility score evaluation."""

    def test_evaluate_multiple_branches(self) -> None:
        """Evaluating multiple branches should produce ranked results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            branches_dir = Path(tmpdir) / "branches"
            branches_dir.mkdir()

            # Create three branches
            for i in range(1, 4):
                branch_dir = branches_dir / f"branch_{i}"
                branch_dir.mkdir()
                manifest = {
                    "artifacts": {
                        "runtime": {
                            "gpu_hours": float(i),  # Vary by cost
                            "peak_memory_gb": 20.0,
                            "retry_count": 0,
                            "total_seconds": 3600 * i,
                        }
                    }
                }
                (branch_dir / "manifest.json").write_text(
                    json.dumps(manifest) + "\n"
                )

            result = evaluate_utility_score(branches_dir)

            self.assertEqual(result["total_branches"], 3)
            self.assertEqual(len(result["ranked_branches"]), 3)
            self.assertGreater(
                result["ranked_branches"][0].overall_score,
                result["ranked_branches"][1].overall_score
            )

    def test_generate_reports(self) -> None:
        """Evaluation should generate JSON and markdown reports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            branches_dir = Path(tmpdir) / "branches"
            branches_dir.mkdir()

            branch_dir = branches_dir / "branch_1"
            branch_dir.mkdir()
            manifest = {
                "artifacts": {
                    "runtime": {
                        "gpu_hours": 1.0,
                        "peak_memory_gb": 20.0,
                        "retry_count": 0,
                        "total_seconds": 3600,
                    }
                }
            }
            (branch_dir / "manifest.json").write_text(
                json.dumps(manifest) + "\n"
            )

            result = evaluate_utility_score(branches_dir)

            self.assertTrue(result["report_json_path"].exists())
            self.assertTrue(result["report_markdown_path"].exists())

            # Verify JSON report format
            report_json = json.loads(
                result["report_json_path"].read_text()
            )
            self.assertIn("created_at", report_json)
            self.assertIn("summary", report_json)
            self.assertIn("ranked_branches", report_json)

            # Verify markdown is readable
            report_md = result["report_markdown_path"].read_text()
            self.assertIn("# Utility Score Report", report_md)
            self.assertIn("Summary Statistics", report_md)
            self.assertIn("branch_1", report_md)

    def test_summary_statistics(self) -> None:
        """Summary should contain correct statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            branches_dir = Path(tmpdir) / "branches"
            branches_dir.mkdir()

            # Create branches with known costs
            for i in range(1, 4):
                branch_dir = branches_dir / f"branch_{i}"
                branch_dir.mkdir()
                manifest = {
                    "artifacts": {
                        "runtime": {
                            "gpu_hours": 1.0,
                            "peak_memory_gb": 20.0,
                            "retry_count": 0,
                            "total_seconds": 3600,
                        }
                    }
                }
                (branch_dir / "manifest.json").write_text(
                    json.dumps(manifest) + "\n"
                )

            result = evaluate_utility_score(branches_dir)
            summary = result["summary"]

            self.assertEqual(summary["total_branches"], 3)
            self.assertGreaterEqual(summary["mean_score"], 0.0)
            self.assertLessEqual(summary["mean_score"], 1.0)
            self.assertGreaterEqual(summary["median_score"], 0.0)
            self.assertLessEqual(summary["median_score"], 1.0)
            self.assertIn("recommendations_count", summary)


class TestRoundFloat(unittest.TestCase):
    """Test floating point rounding."""

    def test_round_float_basic(self) -> None:
        """Basic rounding should work."""
        self.assertEqual(_round_float(0.123456), 0.123456)
        self.assertEqual(_round_float(0.1234567), 0.123457)

    def test_round_float_custom_places(self) -> None:
        """Custom decimal places should work."""
        self.assertEqual(_round_float(0.123456, 2), 0.12)
        self.assertEqual(_round_float(0.123456, 3), 0.123)

    def test_round_float_none(self) -> None:
        """None should remain None."""
        self.assertIsNone(_round_float(None))


if __name__ == "__main__":
    unittest.main()
