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

from deeploop.artifacts.release_automation import (
    build_package_release_automation,
    build_release_candidate_review,
    load_release_candidate_policy,
    materialize_release_candidate_promotion,
    materialize_release_candidate_review,
)


def _package_template(package_root: Path, claim_state: str = "paper-candidate") -> dict:
    return {
        "schema_version": 1,
        "package_id": "demo-package",
        "mission_id": "demo-mission",
        "package_root": str(package_root),
        "package_digest": "abc12345def67890",
        "claim_summary": {
            "package_claim_state": claim_state,
            "manifest_claim_counts": {claim_state: 2},
            "critique_ceiling": "release-candidate",
            "promotion_requirements": ["replicated evidence"],
            "paper_candidate_blockers": [],
            "release_candidate_blockers": [],
        },
        "artifact_map": {
            "mission_specs": ["m1"],
            "mission_configs": ["c1"],
            "ledgers": ["l1"],
            "findings": ["f1"],
            "manifests": ["r1", "r2"],
            "kernel_outputs": ["k1"],
            "critique_reports": ["q1"],
            "runtime_metadata": ["rt1"],
        },
        "summary": {
            "operator_handoff": {"headline": "operator", "bullets": [], "key_artifact_ids": []},
            "paper_drafting": {"headline": "paper", "bullets": [], "key_artifact_ids": []},
            "release_review": {"headline": "release", "bullets": [], "key_artifact_ids": []},
        },
        "checks": {
            "copy_complete": True,
            "outside_repo_outputs": True,
            "all_required_artifacts_present": True,
            "missing_required_artifacts": [],
            "validation_errors": [],
            "artifact_count_by_category": {
                "mission_specs": 1,
                "mission_configs": 1,
                "ledgers": 1,
                "findings": 1,
                "manifests": 2,
                "kernel_outputs": 1,
                "critique_reports": 1,
                "runtime_metadata": 1,
            },
        },
    }


class ReleaseAutomationTests(unittest.TestCase):
    def test_review_blocks_when_claim_floor_or_approvals_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir)
            package = _package_template(package_root, claim_state="replicated")
            package["claim_summary"]["paper_candidate_blockers"] = [
                "documented caveats",
                "human approval",
            ]
            review = build_release_candidate_review(
                package,
                package_manifest_path=package_root / "mission_artifact_package.json",
            )

        self.assertFalse(review["eligible_for_promotion"])
        self.assertEqual(review["decision"], "blocked")
        self.assertIn("claim-state-floor", review["failed_gate_ids"])
        self.assertIn("required-approvals", review["failed_gate_ids"])
        self.assertIn("provenance-review", review["missing_approvals"])

    def test_review_blocks_when_replication_evidence_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir)
            package = _package_template(package_root, claim_state="replicated")
            package["artifact_map"]["manifests"] = ["r1"]
            package["claim_summary"]["manifest_claim_counts"] = {"replicated": 1}
            review = build_release_candidate_review(
                package,
                package_manifest_path=package_root / "mission_artifact_package.json",
            )

        self.assertFalse(review["eligible_for_promotion"])
        self.assertIn("replication-evidence", review["failed_gate_ids"])
        self.assertIn("evidence-policy-linkage", review["failed_gate_ids"])

    def test_review_accepts_replicated_package_with_equivalent_rigor_and_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir)
            package = _package_template(package_root, claim_state="replicated")
            package["claim_summary"]["paper_candidate_blockers"] = ["human approval"]
            package["claim_summary"]["release_candidate_blockers"] = [
                "paper-candidate evidence or equivalent rigor",
                "provenance and licensing review",
                "human approval",
            ]
            review = build_release_candidate_review(
                package,
                package_manifest_path=package_root / "mission_artifact_package.json",
                approvals={
                    "approvals": [
                        {"approval_id": "provenance-review", "approved_by": "operator", "approved": True},
                        {"approval_id": "licensing-review", "approved_by": "operator", "approved": True},
                        {"approval_id": "release-operator", "approved_by": "operator", "approved": True},
                    ]
                },
            )

        self.assertTrue(review["eligible_for_promotion"])
        self.assertEqual(review["decision"], "promotable")
        self.assertNotIn("claim-state-floor", review["failed_gate_ids"])

    def test_review_and_promotion_materialize_when_all_gates_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir)
            package = _package_template(package_root, claim_state="paper-candidate")
            policy = load_release_candidate_policy()
            review = build_release_candidate_review(
                package,
                package_manifest_path=package_root / "mission_artifact_package.json",
                policy=policy,
                approvals={
                    "approvals": [
                        {"approval_id": "provenance-review", "approved_by": "operator", "approved": True},
                        {"approval_id": "licensing-review", "approved_by": "operator", "approved": True},
                        {"approval_id": "release-operator", "approved_by": "operator", "approved": True},
                    ]
                },
            )
            materialized = materialize_release_candidate_review(
                review,
                package_root=package_root,
                policy=policy,
            )
            promotion_path = materialize_release_candidate_promotion(
                materialized["review"],
                package_root=package_root,
                policy=policy,
            )
            release_automation = build_package_release_automation(
                materialized["review"],
                promotion_path=promotion_path,
            )

            rendered = json.loads(materialized["review_json"].read_text(encoding="utf-8"))
            promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
            self.assertTrue(materialized["review_json"].exists())
            self.assertTrue(materialized["review_markdown"].exists())
            self.assertEqual(rendered["decision"], "promotable")
            self.assertEqual(promotion["decision"], "promoted-release-candidate")
            self.assertTrue(release_automation["eligible_for_promotion"])
            self.assertEqual(release_automation["review_artifacts"]["promotion"], str(promotion_path))


if __name__ == "__main__":
    unittest.main()
