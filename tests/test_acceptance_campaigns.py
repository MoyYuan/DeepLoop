from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.testing.acceptance_campaigns import (
    DEFAULT_ACCEPTANCE_CAMPAIGN,
    build_acceptance_review,
    materialize_acceptance_review,
)


class AcceptanceCampaignReviewTests(unittest.TestCase):
    def _artifact_root(self, name: str) -> Path:
        root = REPO_ROOT / "tests" / "_runtime_artifacts" / "acceptance_campaigns" / name
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def _summary_template(self, artifact_root: Path) -> dict:
        review_json_path = artifact_root / "proof_matrix_review.json"
        review_markdown_path = artifact_root / "proof_matrix_review.md"
        summary_json_path = artifact_root / "campaign_summary.json"
        review_json_path.write_text(json.dumps({"decision": "eligible-for-promotion"}) + "\n", encoding="utf-8")
        review_markdown_path.write_text("# Proof review\n", encoding="utf-8")
        summary_json_path.write_text(json.dumps({"status": "passed"}) + "\n", encoding="utf-8")
        case_summaries = [
            {
                "case_id": case_id,
                "status": "passed",
                "boundary_check": {"project_tree_unchanged": True},
                "mission_state": {"final_report_outputs": ["final-report.md"]},
            }
            for case_id in (
                "translation-budget-ladder",
                "literature-gap-map",
                "replication-heavy-redteam",
            )
        ]
        return {
            "campaign_root": str(artifact_root),
            "summary_json_path": str(summary_json_path),
            "status": "passed",
            "cases_run": [case_summary["case_id"] for case_summary in case_summaries],
            "failed_case_ids": [],
            "case_summaries": case_summaries,
            "proof_review": {
                "decision": "eligible-for-promotion",
                "workflow_shapes": ["benchmark-heavy", "execution-heavy", "literature-heavy"],
                "failed_gate_ids": [],
            },
            "review_json_path": str(review_json_path),
            "review_markdown_path": str(review_markdown_path),
            "caveats": ["bounded public acceptance bootstrap"],
        }

    def test_acceptance_review_passes_when_gates_are_green(self) -> None:
        review = build_acceptance_review(self._summary_template(self._artifact_root("green")))
        self.assertEqual(review["campaign_id"], DEFAULT_ACCEPTANCE_CAMPAIGN)
        self.assertEqual(review["decision"], "passed")
        self.assertTrue(review["eligible_for_milestone_gate"])
        self.assertEqual(review["failed_gate_ids"], [])

    def test_acceptance_review_fails_when_proof_review_or_cases_fail(self) -> None:
        summary = self._summary_template(self._artifact_root("failing"))
        summary["status"] = "failed"
        summary["failed_case_ids"] = ["literature-gap-map"]
        summary["proof_review"]["decision"] = "remediation-needed"
        summary["case_summaries"][1]["boundary_check"]["project_tree_unchanged"] = False
        summary["case_summaries"][2]["mission_state"]["final_report_outputs"] = []
        review = build_acceptance_review(summary)

        self.assertEqual(review["decision"], "failed")
        self.assertIn("all-cases-passed", review["failed_gate_ids"])
        self.assertIn("boundary-integrity", review["failed_gate_ids"])
        self.assertIn("final-report-evidence-present", review["failed_gate_ids"])
        self.assertIn("proof-review-eligible", review["failed_gate_ids"])

    def test_materialize_acceptance_review_writes_json_and_markdown(self) -> None:
        root = self._artifact_root("materialize")
        review = build_acceptance_review(self._summary_template(root))
        paths = materialize_acceptance_review(review, output_root=root)

        self.assertTrue(paths["json_path"].exists())
        self.assertTrue(paths["markdown_path"].exists())
        payload = json.loads(paths["json_path"].read_text(encoding="utf-8"))
        markdown = paths["markdown_path"].read_text(encoding="utf-8")

        self.assertEqual(payload["campaign_id"], DEFAULT_ACCEPTANCE_CAMPAIGN)
        self.assertIn("Acceptance review", markdown)
        self.assertIn("proof-review-eligible", markdown)


if __name__ == "__main__":
    unittest.main()
