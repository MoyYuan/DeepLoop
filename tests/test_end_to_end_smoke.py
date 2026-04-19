from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.testing.acceptance_campaigns import build_acceptance_review, materialize_acceptance_review
from deeploop.testing.plain_folder_proof_matrix import discover_plain_folder_proof_cases
from deeploop.testing.proof_matrix_reviews import build_multi_substrate_proof_review


class EndToEndSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "end_to_end_smoke"
        shutil.rmtree(self.runtime_root, ignore_errors=True)
        self.runtime_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def _passing_case(self, case_id: str, workflow_shape: str) -> dict:
        return {
            "case_id": case_id,
            "title": case_id.replace("-", " ").title(),
            "workflow_shape": workflow_shape,
            "status": "passed",
            "autonomy_claims": ["public proof claim"],
            "failures": [],
            "mission_state": {
                "operator_inbox_status": "clear",
                "final_report_outputs": ["final-report.md"],
                "current_phase": "final-report",
            },
            "operator_request": {},
            "boundary_check": {"project_tree_unchanged": True},
            "run_project_result": {"status": "completed"},
        }

    def test_mission_advance_generates_runtime_owned_followup_queue(self) -> None:
        cases = {case.case_id: case for case in discover_plain_folder_proof_cases()}
        self.assertIn("translation-budget-ladder", cases)
        self.assertEqual(cases["translation-budget-ladder"].workflow_shape, "benchmark-heavy")

    def test_canonical_runtime_starts_without_missing_executor_block(self) -> None:
        review = build_multi_substrate_proof_review(
            {
                "campaign_id": "demo-smoke",
                "status": "passed",
                "case_summaries": [
                    self._passing_case("translation-budget-ladder", "benchmark-heavy"),
                ],
            }
        )
        case_review = review["case_reviews"][0]
        self.assertEqual(case_review["status"], "passed")
        self.assertTrue(case_review["gate_results"]["operator_inbox_clear"])
        self.assertEqual(case_review["failure_categories"], [])

    def test_end_to_end_smoke_runs_followups_and_packages(self) -> None:
        review = build_multi_substrate_proof_review(
            {
                "campaign_id": "demo-smoke",
                "status": "passed",
                "case_summaries": [
                    self._passing_case("translation-budget-ladder", "benchmark-heavy"),
                    self._passing_case("literature-gap-map", "literature-heavy"),
                    self._passing_case("replication-heavy-redteam", "execution-heavy"),
                ],
            }
        )
        self.assertEqual(review["decision"], "eligible-for-promotion")
        self.assertEqual(review["counts"]["workflow_shapes"], 3)
        self.assertEqual(review["failed_gate_ids"], [])

    def test_long_run_profile_stages_canonical_followups_with_real_backend(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/testing/run_plain_folder_proof_matrix.py", "--list"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        listed = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        case_ids = {item["case_id"] for item in listed}
        self.assertEqual(case_ids, {"translation-budget-ladder", "literature-gap-map", "replication-heavy-redteam"})

    def test_acceptance_campaign_materializes_green_review(self) -> None:
        campaign_root = self.runtime_root / "acceptance"
        campaign_root.mkdir(parents=True, exist_ok=True)
        summary_json_path = campaign_root / "campaign_summary.json"
        review_json_path = campaign_root / "proof_matrix_review.json"
        review_markdown_path = campaign_root / "proof_matrix_review.md"
        summary = {
            "campaign_root": str(campaign_root),
            "summary_json_path": str(summary_json_path),
            "status": "passed",
            "cases_run": ["translation-budget-ladder", "literature-gap-map", "replication-heavy-redteam"],
            "failed_case_ids": [],
            "case_summaries": [
                self._passing_case("translation-budget-ladder", "benchmark-heavy"),
                self._passing_case("literature-gap-map", "literature-heavy"),
                self._passing_case("replication-heavy-redteam", "execution-heavy"),
            ],
            "proof_review": {
                "decision": "eligible-for-promotion",
                "workflow_shapes": ["benchmark-heavy", "execution-heavy", "literature-heavy"],
                "failed_gate_ids": [],
            },
            "review_json_path": str(review_json_path),
            "review_markdown_path": str(review_markdown_path),
        }
        summary_json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        review_json_path.write_text(json.dumps(summary["proof_review"], indent=2) + "\n", encoding="utf-8")
        review_markdown_path.write_text("# Proof review\n", encoding="utf-8")

        review = build_acceptance_review(summary)
        paths = materialize_acceptance_review(review, output_root=campaign_root)

        self.assertEqual(review["decision"], "passed")
        self.assertEqual(review["campaign_id"], "translation-paper-scale")
        self.assertTrue(paths["json_path"].exists())
        self.assertTrue(paths["markdown_path"].exists())


if __name__ == "__main__":
    unittest.main()
