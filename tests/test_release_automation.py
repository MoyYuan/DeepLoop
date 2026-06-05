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
    @staticmethod
    def _review_record(review_id: str, *, reviewer_type: str, reviewer_id: str, role: str | None = None) -> dict:
        reviewer = {"type": reviewer_type, "reviewer_id": reviewer_id}
        if role:
            reviewer["role"] = role
        return {
            "review_id": review_id,
            "status": "satisfied",
            "reviewed_at": "2026-05-12T00:00:00Z",
            "reviewer": reviewer,
            "note": f"{review_id} completed",
        }

    def test_review_blocks_when_claim_floor_or_reviews_are_missing(self) -> None:
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
        self.assertIn("required-reviews", review["failed_gate_ids"])
        self.assertIn("provenance-review", review["missing_reviews"])
        self.assertEqual(review["gate_2_runtime_contract"]["phase_id"], "current-approved-phase")

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
        lane_ids = {lane["lane_id"] for lane in review["gate_2_runtime_contract"]["required_lanes"]}
        self.assertIn("local-qwen-openai-compatible", lane_ids)

    def test_review_accepts_replicated_package_with_equivalent_rigor_and_agent_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir)
            package = _package_template(package_root, claim_state="replicated")
            package["claim_summary"]["paper_candidate_blockers"] = ["human approval"]
            package["claim_summary"]["release_candidate_blockers"] = [
                "paper-candidate evidence or equivalent rigor",
                "provenance-review record",
                "licensing-review record",
                "release-operator review",
            ]
            review = build_release_candidate_review(
                package,
                package_manifest_path=package_root / "mission_artifact_package.json",
                reviews={
                    "reviews": [
                        self._review_record(
                            "provenance-review",
                            reviewer_type="agent",
                            reviewer_id="provenance-auditor-v1",
                            role="provenance-reviewer",
                        ),
                        self._review_record(
                            "licensing-review",
                            reviewer_type="agent",
                            reviewer_id="licensing-auditor-v1",
                            role="licensing-reviewer",
                        ),
                        {
                            **self._review_record(
                                "release-operator",
                                reviewer_type="agent",
                                reviewer_id="release-agent-v1",
                                role="release-operator",
                            ),
                            "runtime_metadata": {"executor": "copilot-cli", "model": "gpt-5-mini"},
                        },
                    ]
                },
            )

        self.assertTrue(review["eligible_for_promotion"])
        self.assertEqual(review["decision"], "promotable")
        self.assertNotIn("claim-state-floor", review["failed_gate_ids"])
        self.assertEqual(review["required_reviews"][0]["reviewer"]["type"], "agent")
        self.assertEqual(review["required_reviews"][2]["runtime_metadata"]["model"], "gpt-5-mini")
        self.assertTrue(review["gate_2_runtime_contract"]["proof_boundary"]["manual_machine_auth_remains_explicit"])

    def test_review_accepts_human_override_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir)
            package = _package_template(package_root, claim_state="paper-candidate")
            package["claim_summary"]["release_candidate_blockers"] = [
                "provenance-review record",
                "licensing-review record",
                "release-operator review",
            ]
            review = build_release_candidate_review(
                package,
                package_manifest_path=package_root / "mission_artifact_package.json",
                reviews={
                    "reviews": [
                        self._review_record("provenance-review", reviewer_type="human", reviewer_id="operator-name"),
                        self._review_record("licensing-review", reviewer_type="human", reviewer_id="operator-name"),
                        self._review_record("release-operator", reviewer_type="human", reviewer_id="operator-name"),
                    ]
                },
            )

        self.assertTrue(review["eligible_for_promotion"])
        self.assertTrue(all(item["human_override"] for item in review["required_reviews"]))

    def test_review_requires_auditable_metadata_for_satisfied_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir)
            package = _package_template(package_root, claim_state="paper-candidate")
            package["claim_summary"]["release_candidate_blockers"] = [
                "provenance-review record",
                "licensing-review record",
                "release-operator review",
            ]
            review = build_release_candidate_review(
                package,
                package_manifest_path=package_root / "mission_artifact_package.json",
                reviews={
                    "reviews": [
                        {"review_id": "provenance-review", "status": "satisfied"},
                        self._review_record(
                            "licensing-review",
                            reviewer_type="agent",
                            reviewer_id="licensing-auditor-v1",
                            role="licensing-reviewer",
                        ),
                        self._review_record(
                            "release-operator",
                            reviewer_type="agent",
                            reviewer_id="release-agent-v1",
                            role="release-operator",
                        ),
                    ]
                },
            )

        provenance_review = next(item for item in review["required_reviews"] if item["review_id"] == "provenance-review")
        self.assertFalse(review["eligible_for_promotion"])
        self.assertEqual(provenance_review["status"], "invalid")
        self.assertTrue(any("note is required" in error for error in provenance_review["validation_errors"]))

    def test_review_and_promotion_materialize_when_all_gates_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir)
            package = _package_template(package_root, claim_state="paper-candidate")
            policy = load_release_candidate_policy()
            review = build_release_candidate_review(
                package,
                package_manifest_path=package_root / "mission_artifact_package.json",
                policy=policy,
                reviews={
                    "reviews": [
                        self._review_record("provenance-review", reviewer_type="human", reviewer_id="operator-name"),
                        self._review_record("licensing-review", reviewer_type="human", reviewer_id="operator-name"),
                        self._review_record("release-operator", reviewer_type="human", reviewer_id="operator-name"),
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
            self.assertEqual(promotion["review_ids"], ["provenance-review", "licensing-review", "release-operator"])
            self.assertTrue(release_automation["eligible_for_promotion"])
            self.assertEqual(release_automation["review_artifacts"]["promotion"], str(promotion_path))
            self.assertEqual(release_automation["missing_reviews"], [])
            self.assertEqual(rendered["gate_2_runtime_contract"]["phase_id"], "current-approved-phase")
            self.assertIn("## Gate 2 runtime contract", materialized["review_markdown"].read_text(encoding="utf-8"))
            self.assertIn("## Required reviews", materialized["review_markdown"].read_text(encoding="utf-8"))
            self.assertEqual(release_automation["gate_2_runtime_contract"]["phase_id"], "current-approved-phase")


if __name__ == "__main__":
    unittest.main()
