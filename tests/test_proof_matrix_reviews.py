from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.testing.proof_matrix_reviews import (
    build_multi_substrate_proof_review,
    materialize_proof_matrix_review,
)


class ProofMatrixReviewTests(unittest.TestCase):
    def test_build_review_marks_passing_multi_shape_campaign_as_promotable(self) -> None:
        review = build_multi_substrate_proof_review(
            {
                "campaign_id": "demo-proof-campaign",
                "status": "passed",
                "case_summaries": [
                    {
                        "case_id": "translation-budget-ladder",
                        "title": "Translation budget ladder",
                        "workflow_shape": "benchmark-heavy",
                        "status": "passed",
                        "autonomy_claims": ["claim-a"],
                        "failures": [],
                        "mission_state": {
                            "operator_inbox_status": "clear",
                            "final_report_outputs": ["findings summary"],
                        },
                        "operator_request": {},
                        "boundary_check": {"project_tree_unchanged": True},
                    },
                    {
                        "case_id": "literature-gap-map",
                        "title": "Literature gap map",
                        "workflow_shape": "literature-heavy",
                        "status": "passed",
                        "autonomy_claims": ["claim-b"],
                        "failures": [],
                        "mission_state": {
                            "operator_inbox_status": "clear",
                            "final_report_outputs": ["findings summary"],
                        },
                        "operator_request": {},
                        "boundary_check": {"project_tree_unchanged": True},
                    },
                    {
                        "case_id": "replication-heavy-redteam",
                        "title": "Replication-heavy redteam",
                        "workflow_shape": "execution-heavy",
                        "status": "passed",
                        "autonomy_claims": ["claim-c"],
                        "failures": [],
                        "mission_state": {
                            "operator_inbox_status": "clear",
                            "final_report_outputs": ["findings summary"],
                        },
                        "operator_request": {},
                        "boundary_check": {"project_tree_unchanged": True},
                    },
                ],
            }
        )

        self.assertEqual(review["decision"], "eligible-for-promotion")
        self.assertEqual(review["counts"]["workflow_shapes"], 3)
        self.assertEqual(review["failed_gate_ids"], [])

    def test_build_review_classifies_operator_review_and_boundary_gap(self) -> None:
        review = build_multi_substrate_proof_review(
            {
                "campaign_id": "demo-proof-campaign",
                "status": "failed",
                "case_summaries": [
                    {
                        "case_id": "demo-case",
                        "title": "Demo case",
                        "workflow_shape": "benchmark-heavy",
                        "status": "failed",
                        "autonomy_claims": ["claim-a"],
                        "failures": ["project folder changed during proof run"],
                        "mission_state": {
                            "operator_inbox_status": "open",
                            "final_report_outputs": [],
                        },
                        "operator_request": {
                            "blocker": {
                                "kind": "operator-review",
                            }
                        },
                        "boundary_check": {"project_tree_unchanged": False},
                    }
                ],
            }
        )

        self.assertEqual(review["decision"], "remediation-needed")
        self.assertIn("operator-review", review["case_reviews"][0]["failure_categories"])
        self.assertIn("substrate-gap", review["case_reviews"][0]["failure_categories"])
        self.assertIn("product-gap", review["case_reviews"][0]["failure_categories"])

    def test_build_review_prefers_embedded_snapshot_over_reused_live_mission_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stale_state_path = Path(tmpdir) / "mission_state.json"
            stale_state_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "current_phase": "question-design",
                        "operator_inbox": {"status": "open"},
                        "phase_outputs_by_phase": {
                            "literature-review": ["prior-art memo"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            review = build_multi_substrate_proof_review(
                {
                    "campaign_id": "demo-proof-campaign",
                    "status": "passed",
                    "case_summaries": [
                        {
                            "case_id": "literature-gap-map",
                            "title": "Literature gap map",
                            "workflow_shape": "literature-heavy",
                            "status": "passed",
                            "autonomy_claims": ["claim-a"],
                            "failures": [],
                            "mission_state": {
                                "operator_inbox_status": "clear",
                            },
                            "run_project_result": {
                                "mission_state_path": str(stale_state_path),
                                "snapshot": {
                                    "mission": {
                                        "status": "completed",
                                        "current_phase": "final-report",
                                    },
                                    "operator_inbox": {"status": "clear"},
                                    "evidence": {
                                        "phase_outputs_by_phase": {
                                            "final-report": [
                                                "findings summary",
                                                "paper-candidate recommendation",
                                            ]
                                        }
                                    },
                                    "outer_loop": {
                                        "runtime": {
                                            "status": "completed",
                                        }
                                    },
                                },
                            },
                            "operator_request": {},
                            "boundary_check": {"project_tree_unchanged": True},
                        }
                    ],
                }
            )

        self.assertEqual(review["counts"]["final_report_cases"], 1)
        self.assertTrue(review["case_reviews"][0]["gate_results"]["final_report_outputs_present"])
        self.assertEqual(review["case_reviews"][0]["failure_categories"], [])

    def test_materialize_review_writes_json_and_markdown(self) -> None:
        review = build_multi_substrate_proof_review(
            {
                "campaign_id": "demo-proof-campaign",
                "status": "passed",
                "case_summaries": [],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = materialize_proof_matrix_review(review, Path(tmpdir))
            payload = json.loads(Path(paths["review_json_path"]).read_text(encoding="utf-8"))
            rendered = Path(paths["review_markdown_path"]).read_text(encoding="utf-8")

        self.assertEqual(payload["campaign_id"], "demo-proof-campaign")
        self.assertIn("# Plain-folder proof matrix review", rendered)


if __name__ == "__main__":
    unittest.main()
