from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.novelty_refresh import (
    LiteratureCategory,
    NoveltyRefreshEvaluator,
    NoveltyReport,
    BranchShift,
)
from deeploop.core.paths import MISSIONS_DIR

from deeploop.core.paths import WORKSPACE_ROOT

TRANSLATION_REPO = WORKSPACE_ROOT / "repos" / "translation-pilot"
MISSION_CONFIG_PATH = REPO_ROOT / "configs" / "autonomy" / "novelty-refresh.yaml"


class NoveltyRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        """Set up test fixtures."""
        self.evaluator = NoveltyRefreshEvaluator(contract_path=MISSION_CONFIG_PATH)
        self.translation_repo = TRANSLATION_REPO

    def test_required_files_exist(self) -> None:
        """Test that all required files exist."""
        self.assertTrue((REPO_ROOT / "configs" / "autonomy" / "novelty-refresh.yaml").exists())
        self.assertTrue((REPO_ROOT / "docs" / "design" / "novelty-refresh.md").exists())
        self.assertTrue((REPO_ROOT / "src" / "deeploop" / "research" / "novelty_refresh.py").exists())
        self.assertTrue((REPO_ROOT / "scripts" / "mission" / "run_novelty_refresh.py").exists())

    def test_config_loads_and_validates(self) -> None:
        """Test that configuration loads and has required fields."""
        config = yaml.safe_load(MISSION_CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(config["artifact_dir_name"], "novelty_refresh")
        self.assertIn("mission_contexts", config)
        self.assertIn("literature_staleness_thresholds", config)
        self.assertIn("novelty_assessment_dimensions", config)
        self.assertGreater(len(config["mission_contexts"]), 0)
        self.assertGreater(len(config["literature_staleness_thresholds"]), 0)

    def test_literature_category_staleness_fresh(self) -> None:
        """Test that recent literature is marked as fresh."""
        cat = LiteratureCategory(
            category="mechanistic_interpretability",
            max_age_months=12,
            warn_before_months=6,
        )
        # Use a date ~2 months ago (should be fresh)
        now = datetime.now(timezone.utc)
        two_months_ago = (now - timedelta(days=60)).strftime("%Y-%m")
        status, note = cat.check_staleness(two_months_ago)
        self.assertEqual(status, "fresh", f"Expected fresh but got {status}: {note}")
        self.assertIn("acceptable range", note)

    def test_literature_category_staleness_warning(self) -> None:
        """Test that approaching-limit literature is marked as warning."""
        cat = LiteratureCategory(
            category="mechanistic_interpretability",
            max_age_months=12,
            warn_before_months=6,
        )
        # Use a date ~7 months ago (within warn threshold but not stale)
        now = datetime.now(timezone.utc)
        seven_months_ago = (now - timedelta(days=210)).strftime("%Y-%m")
        status, note = cat.check_staleness(seven_months_ago)
        self.assertEqual(status, "warning", f"Expected warning but got {status}: {note}")
        self.assertIn("approaching", note)

    def test_literature_category_staleness_stale(self) -> None:
        """Test that old literature is marked as stale."""
        cat = LiteratureCategory(
            category="mechanistic_interpretability",
            max_age_months=12,
            warn_before_months=6,
        )
        # Use a date ~13 months ago (exceeds max_age)
        now = datetime.now(timezone.utc)
        thirteen_months_ago = (now - timedelta(days=395)).strftime("%Y-%m")
        status, note = cat.check_staleness(thirteen_months_ago)
        self.assertEqual(status, "stale", f"Expected stale but got {status}: {note}")
        self.assertIn("exceeds", note)

    def test_novelty_report_to_json(self) -> None:
        """Test NoveltyReport can serialize to JSON."""
        report = NoveltyReport(
            timestamp="2024-04-12T17:30:00Z",
            mission_id="test-mission",
            overall_score=3.5,
            dimension_scores={
                "behavioral_characterization": 4.0,
                "mechanistic_localization": 3.0,
                "intervention_novelty": 3.0,
                "empirical_rigor": 2.5,
            },
            branch_shifts=[
                BranchShift(
                    detected_at="2024-04-12T17:25:00Z",
                    shift_type="scope_expansion",
                    from_state="baseline",
                    to_state="baseline_plus_intervention",
                    impact="Increases novelty",
                    severity="moderate",
                )
            ],
            literature_staleness=[
                {
                    "category": "mechanistic_interpretability",
                    "last_update": "2024-04",
                    "max_age_months": 12,
                    "status": "fresh",
                    "note": "Recent work available",
                }
            ],
            prior_art_alignments=[
                {
                    "reference": "ROME",
                    "coverage": "factual_memory",
                    "differentiation": "We specialize to asymmetry",
                }
            ],
            recommendations=[
                {
                    "priority": "high",
                    "type": "replication",
                    "action": "Replicate across model scales",
                }
            ],
            caveats={
                "evaluation_scope": "Test scope",
                "assumed_constraints": "Test assumptions",
            },
        )

        json_str = report.to_json()
        parsed = json.loads(json_str)

        self.assertEqual(parsed["mission_id"], "test-mission")
        self.assertEqual(parsed["novelty_status"]["overall_score"], 3.5)
        self.assertEqual(len(parsed["branch_shifts"]), 1)
        self.assertEqual(parsed["branch_shifts"][0]["shift_type"], "scope_expansion")

    def test_novelty_report_to_markdown(self) -> None:
        """Test NoveltyReport can serialize to Markdown."""
        report = NoveltyReport(
            timestamp="2024-04-12T17:30:00Z",
            mission_id="test-mission",
            overall_score=3.5,
            dimension_scores={
                "behavioral_characterization": 4.0,
            },
            branch_shifts=[
                BranchShift(
                    detected_at="2024-04-12T17:25:00Z",
                    shift_type="scope_expansion",
                    from_state="baseline",
                    to_state="baseline_plus_intervention",
                    impact="Increases novelty",
                    severity="moderate",
                )
            ],
            literature_staleness=[],
            prior_art_alignments=[],
            recommendations=[],
            caveats={},
        )

        md_str = report.to_markdown()

        self.assertIn("# Novelty Delta Memo: test-mission", md_str)
        self.assertIn("3.5", md_str)
        self.assertIn("Branch Shift", md_str)
        self.assertIn("scope_expansion", md_str)

    def test_interpret_score_high(self) -> None:
        """Test score interpretation for high novelty."""
        report = NoveltyReport(
            timestamp="2024-04-12T17:30:00Z",
            mission_id="test",
            overall_score=4.7,
            dimension_scores={},
            branch_shifts=[],
            literature_staleness=[],
            prior_art_alignments=[],
            recommendations=[],
            caveats={},
        )
        self.assertIn("High novelty", report._interpret_score())

    def test_interpret_score_moderate(self) -> None:
        """Test score interpretation for moderate novelty."""
        report = NoveltyReport(
            timestamp="2024-04-12T17:30:00Z",
            mission_id="test",
            overall_score=3.5,
            dimension_scores={},
            branch_shifts=[],
            literature_staleness=[],
            prior_art_alignments=[],
            recommendations=[],
            caveats={},
        )
        self.assertIn("Moderate", report._interpret_score())

    def test_interpret_score_low(self) -> None:
        """Test score interpretation for low novelty."""
        report = NoveltyReport(
            timestamp="2024-04-12T17:30:00Z",
            mission_id="test",
            overall_score=2.0,
            dimension_scores={},
            branch_shifts=[],
            literature_staleness=[],
            prior_art_alignments=[],
            recommendations=[],
            caveats={},
        )
        self.assertIn("Low novelty", report._interpret_score())

    def test_evaluator_initialization(self) -> None:
        """Test that evaluator initializes with contract."""
        self.assertIsNotNone(self.evaluator.contract)
        self.assertIn("artifact_dir_name", self.evaluator.contract)
        self.assertGreater(len(self.evaluator.literature_categories), 0)

    def test_evaluator_assess_translation_mission(self) -> None:
        """Test full evaluation on the translation example mission."""
        if not self.translation_repo.exists():
            self.skipTest(f"Translation example repo not found: {self.translation_repo}")

        result = self.evaluator.evaluate(
            mission_id="translation-full-mission",
            artifact_name="test-novelty-delta",
        )

        self.assertEqual(result["verdict"], "success")
        self.assertIn("report_json_path", result)
        self.assertIn("report_markdown_path", result)
        self.assertGreater(result["novelty_score"], 0)
        self.assertLessEqual(result["novelty_score"], 5)

        # Check JSON report exists and is valid
        self.assertTrue(result["report_json_path"].exists())
        json_content = json.loads(result["report_json_path"].read_text(encoding="utf-8"))
        self.assertEqual(json_content["mission_id"], "translation-full-mission")
        self.assertIn("novelty_status", json_content)
        self.assertIn("dimension_scores", json_content)
        self.assertGreater(len(json_content["dimension_scores"]), 0)

        # Check markdown report exists
        self.assertTrue(result["report_markdown_path"].exists())
        md_content = result["report_markdown_path"].read_text(encoding="utf-8")
        self.assertIn("Novelty Delta Memo", md_content)
        self.assertIn("translation-full-mission", md_content)

    def test_evaluator_missing_mission_context(self) -> None:
        """Test that evaluator raises error for unknown mission."""
        with self.assertRaises(ValueError):
            self.evaluator.evaluate(mission_id="nonexistent-mission")

    def test_ledger_integration(self) -> None:
        """Test that ledger entry is created."""
        if not self.translation_repo.exists():
            self.skipTest(f"Translation example repo not found: {self.translation_repo}")

        result = self.evaluator.evaluate(
            mission_id="translation-full-mission",
            artifact_name="test-ledger-integration",
        )

        from deeploop.core.paths import LEDGER_DIR

        ledger_path = LEDGER_DIR / "novelty_refresh.jsonl"
        if ledger_path.exists():
            entries = [
                json.loads(line)
                for line in ledger_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            # Check that at least one ledger entry exists
            self.assertGreater(len(entries), 0)
            latest = entries[-1]
            self.assertEqual(latest["kind"], "novelty-refresh")
            self.assertEqual(latest["mission_id"], "translation-full-mission")
            self.assertIn("novelty_score", latest["metadata"])

    def test_design_doc_exists_and_readable(self) -> None:
        """Test that design documentation is complete."""
        design_doc = (REPO_ROOT / "docs" / "design" / "novelty-refresh.md").read_text(encoding="utf-8")
        self.assertIn("Novelty-Refresh Loop Design", design_doc)
        self.assertIn("deterministic", design_doc.lower())
        self.assertIn("branch shift", design_doc.lower())
        self.assertIn("staleness", design_doc.lower())

    def test_script_is_executable(self) -> None:
        """Test that runner script is present and executable."""
        script_path = REPO_ROOT / "scripts" / "mission" / "run_novelty_refresh.py"
        self.assertTrue(script_path.exists())
        content = script_path.read_text(encoding="utf-8")
        self.assertIn("def main", content)
        self.assertIn("argparse", content)


if __name__ == "__main__":
    unittest.main()
