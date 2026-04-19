"""Tests for confound contamination guard."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.confound_guard import evaluate_confound_guard


class ConfoundGuardTests(unittest.TestCase):
    """Test confound contamination guard."""

    def setUp(self) -> None:
        """Create temporary directory for test artifacts."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmppath = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.tmpdir.cleanup()

    def _write_config(self, name: str, config: dict) -> Path:
        """Write a test config to temp directory."""
        path = self.tmppath / f"{name}.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        return path

    def test_confound_guard_baseline_config_passes(self) -> None:
        """Test baseline config passes evaluation."""
        config = {
            "dataset": "wikitext",
            "model": "test-model",
            "run": "test-run-1",
        }
        config_path = self._write_config("baseline", config)

        result = evaluate_confound_guard(config_path, artifact_name="test-baseline")

        self.assertIn("verdict", result)
        self.assertIn("report_json_path", result)
        self.assertIn("report_markdown_path", result)
        self.assertTrue(result["report_json_path"].exists())
        self.assertTrue(result["report_markdown_path"].exists())

        # Check JSON report structure
        report = json.loads(result["report_json_path"].read_text(encoding="utf-8"))
        self.assertIn("verdict", report)
        self.assertIn("config_kind", report)
        self.assertIn("checks", report)

    def test_confound_guard_invalid_config_blocks(self) -> None:
        """Test invalid config is blocked."""
        config_path = self.tmppath / "nonexistent.yaml"

        result = evaluate_confound_guard(config_path, artifact_name="test-missing")

        self.assertEqual(result["verdict"], "block")
        report = json.loads(result["report_json_path"].read_text(encoding="utf-8"))
        self.assertIn("block", [c["status"] for c in report["checks"]])

    def test_confound_guard_with_mission_state_creates_ledger(self) -> None:
        """Test that mission state integration creates ledger entries."""
        mission_state = {
            "mission_id": "test-mission-123",
            "timestamp": "2024-04-12T00:00:00Z",
        }
        mission_state_path = self.tmppath / "mission_state.json"
        mission_state_path.write_text(json.dumps(mission_state), encoding="utf-8")

        config = {
            "dataset": "wikitext",
            "model": "test-model",
            "run": "test-run-1",
        }
        config_path = self._write_config("baseline", config)

        result = evaluate_confound_guard(
            config_path,
            mission_state_path=mission_state_path,
            artifact_name="test-with-mission",
        )

        # Check ledger was created
        ledger_path = mission_state_path.parent / "ledger.jsonl"
        self.assertTrue(ledger_path.exists())

        # Check ledger has entry
        lines = ledger_path.read_text(encoding="utf-8").strip().split("\n")
        self.assertTrue(len(lines) > 0)
        entry = json.loads(lines[-1])
        self.assertEqual(entry["kind"], "confound-guard")
        self.assertEqual(entry["mission_id"], "test-mission-123")

    def test_confound_guard_report_artifacts_complete(self) -> None:
        """Test that all report artifacts are generated."""
        config = {
            "dataset": "wikitext",
            "model": "test-model",
            "run": "test-run-1",
        }
        config_path = self._write_config("baseline", config)

        result = evaluate_confound_guard(config_path, artifact_name="test-artifacts")

        # Check all keys present
        self.assertIn("verdict", result)
        self.assertIn("report", result)
        self.assertIn("report_json_path", result)
        self.assertIn("report_markdown_path", result)

        # Check files exist
        self.assertTrue(result["report_json_path"].exists())
        self.assertTrue(result["report_markdown_path"].exists())

        # Check report structure
        report = result["report"]
        self.assertEqual(report["schema_version"], 1)
        self.assertIn("created_at", report)
        self.assertIn("config_path", report)
        self.assertIn("verdict", report)
        self.assertIn("summary", report)
        self.assertIn("checks", report)

    def test_confound_guard_markdown_report_readable(self) -> None:
        """Test markdown report is human-readable."""
        config = {
            "dataset": "wikitext",
            "model": "test-model",
            "run": "test-run-1",
        }
        config_path = self._write_config("baseline", config)

        result = evaluate_confound_guard(config_path, artifact_name="test-markdown")

        # Read and check markdown
        md_content = result["report_markdown_path"].read_text(encoding="utf-8")
        self.assertIn("# Confound guard", md_content)
        self.assertIn("verdict:", md_content)
        self.assertIn("config_path:", md_content)
        self.assertIn("Checks", md_content)


if __name__ == "__main__":
    unittest.main()
