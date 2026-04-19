from __future__ import annotations

import json
from pathlib import Path
import tempfile
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.artifacts.artifact_packager import (
    _resolve_contract_declared_path,
    _resolve_manifest_paths,
    load_package_contract,
    package_mission_artifacts,
    validate_package_manifest,
)
from deeploop.core.paths import WORKSPACE_ROOT


class ArtifactPackagerTests(unittest.TestCase):
    def test_contract_loads(self) -> None:
        contract = load_package_contract()
        self.assertEqual(contract.get("version"), 1)
        self.assertIn("artifact_map", contract)
        self.assertIn("supporting_contracts", contract)
        self.assertTrue(contract["supporting_contracts"])
        self.assertTrue(
            all(not str(path).startswith("~/workspaces/repos/deeploop") for path in contract["supporting_contracts"])
        )
        self.assertTrue(all(str(path).startswith("configs/") for path in contract["supporting_contracts"]))

    def test_contract_declared_paths_resolve_from_contract_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            contract_path = Path(tmpdir) / "alt-repo" / "configs" / "runtime" / "artifact-package-contract.yaml"
            contract_path.parent.mkdir(parents=True, exist_ok=True)
            contract_path.write_text("version: 1\n", encoding="utf-8")

            resolved = _resolve_contract_declared_path(
                "configs/autonomy/evidence-policy.yaml",
                contract_path=contract_path,
            )

            self.assertEqual(
                resolved,
                (Path(tmpdir) / "alt-repo" / "configs" / "autonomy" / "evidence-policy.yaml").resolve(),
            )

    def test_contract_declared_paths_fall_back_to_contract_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            contract_path = Path(tmpdir) / "contracts" / "artifact-package-contract.yaml"
            contract_path.parent.mkdir(parents=True, exist_ok=True)
            contract_path.write_text("version: 1\n", encoding="utf-8")

            resolved = _resolve_contract_declared_path(
                "support/evidence-policy.yaml",
                contract_path=contract_path,
            )

            self.assertEqual(
                resolved,
                (Path(tmpdir) / "contracts" / "support" / "evidence-policy.yaml").resolve(),
            )

    def test_contract_declared_paths_accept_windows_style_relative_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            contract_path = Path(tmpdir) / "contracts" / "artifact-package-contract.yaml"
            contract_path.parent.mkdir(parents=True, exist_ok=True)
            contract_path.write_text("version: 1\n", encoding="utf-8")

            resolved = _resolve_contract_declared_path(
                r".\support\evidence-policy.yaml",
                contract_path=contract_path,
            )

            self.assertEqual(
                resolved,
                (Path(tmpdir) / "contracts" / "support" / "evidence-policy.yaml").resolve(),
            )

    def test_resolve_manifest_paths_searches_mission_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir)
            mission_id = "demo-mission"
            generic_run_root = workspace_root / "runs" / "demo-project"
            mission_root = workspace_root / "runs" / "deeploop" / "missions" / mission_id
            manifest_path = mission_root / "runtime" / "execution" / "demo-run" / "runs" / "baseline-a" / "run_manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "mission_id": mission_id,
                        "loop_id": "baseline-a",
                        "run": {"status": "completed"},
                    }
                ),
                encoding="utf-8",
            )

            resolved = _resolve_manifest_paths(
                [generic_run_root, mission_root],
                mission_id,
                ["**/run_manifest.json", "**/study_manifest.json"],
            )

            self.assertEqual(resolved, [manifest_path.resolve()])

    def test_packager_records_missing_required_artifacts_without_failing(self) -> None:
        runs_root = WORKSPACE_ROOT / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runs_root) as tmpdir:
            test_root = Path(tmpdir)
            mission_root = test_root / "mission"
            mission_root.mkdir(parents=True, exist_ok=True)
            target_repo = test_root / "plain-project"
            target_repo.mkdir(parents=True, exist_ok=True)
            findings_dir = mission_root / "findings"
            findings_dir.mkdir(parents=True, exist_ok=True)
            runtime_dir = mission_root / "runtime" / "mission_outer_runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)

            mission_state_path = mission_root / "mission_state.json"
            mission_state = {
                "mission_id": "missing-manifest-mission",
                "title": "Missing manifest package test",
                "objective": "Package what exists without pretending manifests were produced.",
                "current_phase": "final-report",
                "status": "completed",
                "target_repo": str(target_repo),
                "roles": ["report-synthesizer"],
                "artifacts": {"docs": [], "configs": []},
                "next_actions": {"actions": [], "generated_configs": []},
            }
            mission_state_path.write_text(json.dumps(mission_state, indent=2) + "\n", encoding="utf-8")
            (mission_root / "mission_summary.md").write_text("# Summary\n", encoding="utf-8")
            (mission_root / "mission_decisions.jsonl").write_text("", encoding="utf-8")
            (mission_root / "mission_branches.jsonl").write_text("", encoding="utf-8")
            (mission_root / "mission_memory.json").write_text("{}\n", encoding="utf-8")
            (mission_root / "mission_experiments.jsonl").write_text("", encoding="utf-8")
            (mission_root / "ledger.jsonl").write_text("", encoding="utf-8")
            (findings_dir / "finding.md").write_text("- Runtime recovered without manifests.\n", encoding="utf-8")
            (runtime_dir / "runtime_state.json").write_text('{"status":"completed"}\n', encoding="utf-8")

            output_root = test_root / "packages"
            result = package_mission_artifacts(mission_state_path, output_root=output_root)

            self.assertTrue(result["manifest_path"].exists())
            self.assertTrue(result["summary_path"].exists())
            checks = result["package"]["checks"]
            self.assertFalse(checks["all_required_artifacts_present"])
            self.assertEqual(checks["missing_required_artifacts"], ["category:manifests"])
            self.assertEqual(result["package"]["artifact_map"]["manifests"], [])
            self.assertEqual(result["package"]["replication_evidence"]["total_manifests"], 0)
            self.assertIn(
                "Missing required mission artifacts: category:manifests",
                result["package"]["claim_summary"]["release_candidate_blockers"],
            )
            self.assertEqual(validate_package_manifest(result["package"]), [])

    def test_packager_marks_package_replicated_when_followup_manifest_exists(self) -> None:
        runs_root = WORKSPACE_ROOT / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runs_root) as tmpdir:
            test_root = Path(tmpdir)
            mission_root = test_root / "mission"
            mission_root.mkdir(parents=True, exist_ok=True)
            target_repo = test_root / "plain-project"
            target_repo.mkdir(parents=True, exist_ok=True)
            findings_dir = mission_root / "findings"
            findings_dir.mkdir(parents=True, exist_ok=True)
            runtime_dir = mission_root / "runtime" / "mission_outer_runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            runs_dir = mission_root / "runtime" / "plain_folder_followups" / "runs"
            execution_dir = runs_dir / "execution-baseline"
            replication_dir = runs_dir / "replication-baseline"
            execution_dir.mkdir(parents=True, exist_ok=True)
            replication_dir.mkdir(parents=True, exist_ok=True)

            mission_state_path = mission_root / "mission_state.json"
            mission_state = {
                "mission_id": "replicated-package-mission",
                "title": "Replicated package test",
                "objective": "Package execution and follow-up replication evidence honestly.",
                "current_phase": "final-report",
                "status": "completed",
                "target_repo": str(target_repo),
                "roles": ["execution-operator", "critic-verifier", "report-synthesizer"],
                "artifacts": {"docs": [], "configs": []},
                "next_actions": {"actions": [], "generated_configs": []},
            }
            mission_state_path.write_text(json.dumps(mission_state, indent=2) + "\n", encoding="utf-8")
            (mission_root / "mission_summary.md").write_text("# Summary\n", encoding="utf-8")
            (mission_root / "mission_decisions.jsonl").write_text("", encoding="utf-8")
            (mission_root / "mission_branches.jsonl").write_text("", encoding="utf-8")
            (mission_root / "mission_memory.json").write_text("{}\n", encoding="utf-8")
            (mission_root / "mission_experiments.jsonl").write_text("", encoding="utf-8")
            (mission_root / "ledger.jsonl").write_text("", encoding="utf-8")
            (findings_dir / "finding.md").write_text("- Follow-up replication stayed within the bounded plain-folder contract.\n", encoding="utf-8")
            (runtime_dir / "runtime_state.json").write_text('{"status":"completed"}\n', encoding="utf-8")
            (execution_dir / "runtime_report.json").write_text('{"status":"completed"}\n', encoding="utf-8")
            (replication_dir / "runtime_report.json").write_text('{"status":"completed"}\n', encoding="utf-8")
            execution_manifest = {
                "mission_id": "replicated-package-mission",
                "loop_id": "demo-execution-baseline",
                "claim_state": "exploratory",
                "run": {"status": "completed"},
                "metrics": {"accuracy": 0.8},
                "artifacts": {
                    "output_dir": str(execution_dir),
                    "report_paths": [str(execution_dir / "runtime_report.json")],
                },
                "notes": ["Generated plain-folder execution evidence run."],
            }
            replication_manifest = {
                "mission_id": "replicated-package-mission",
                "loop_id": "demo-replication-baseline",
                "claim_state": "exploratory",
                "run": {"status": "completed"},
                "metrics": {"accuracy": 0.8},
                "artifacts": {
                    "output_dir": str(replication_dir),
                    "report_paths": [str(replication_dir / "runtime_report.json")],
                },
                "notes": ["Generated plain-folder replication evidence run."],
            }
            (execution_dir / "run_manifest.json").write_text(json.dumps(execution_manifest, indent=2) + "\n", encoding="utf-8")
            (replication_dir / "run_manifest.json").write_text(
                json.dumps(replication_manifest, indent=2) + "\n", encoding="utf-8"
            )

            output_root = test_root / "packages"
            result = package_mission_artifacts(mission_state_path, output_root=output_root)

            self.assertEqual(result["package"]["claim_summary"]["package_claim_state"], "replicated")
            self.assertEqual(result["package"]["replication_evidence"]["total_manifests"], 2)
            self.assertEqual(result["package"]["claim_summary"]["paper_candidate_blockers"], ["human approval"])
            self.assertTrue(any("raises the manifest floor" in bullet for bullet in result["package"]["summary"]["release_review"]["bullets"]))
            self.assertEqual(validate_package_manifest(result["package"]), [])

    def test_packager_reuses_co_packaged_artifacts_when_manifest_paths_are_stale(self) -> None:
        runs_root = WORKSPACE_ROOT / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runs_root) as tmpdir:
            test_root = Path(tmpdir)
            archived_root = test_root / "archived-package"
            packaged_artifacts_root = archived_root / "artifacts"
            mission_rel = Path("runs/deeploop/missions/archived-package-mission")
            mission_root = packaged_artifacts_root / mission_rel
            target_repo = test_root / "demo-project"
            target_repo.mkdir(parents=True, exist_ok=True)
            findings_dir = mission_root / "findings"
            findings_dir.mkdir(parents=True, exist_ok=True)
            runtime_dir = mission_root / "runtime" / "mission_outer_runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            runs_dir = mission_root / "runtime" / "plain_folder_followups" / "runs"
            execution_dir = runs_dir / "execution-baseline"
            replication_dir = runs_dir / "replication-baseline"
            execution_dir.mkdir(parents=True, exist_ok=True)
            replication_dir.mkdir(parents=True, exist_ok=True)

            mission_state_path = mission_root / "mission_state.json"
            mission_state_path.parent.mkdir(parents=True, exist_ok=True)
            mission_state = {
                "mission_id": "archived-package-mission",
                "title": "Archived package replay test",
                "objective": "Recover replicated evidence from co-packaged artifacts even when manifest paths are stale.",
                "current_phase": "final-report",
                "status": "completed",
                "target_repo": str(target_repo),
                "roles": ["execution-operator", "critic-verifier", "report-synthesizer"],
                "artifacts": {"docs": [], "configs": []},
                "next_actions": {"actions": [], "generated_configs": []},
            }
            mission_state_path.write_text(json.dumps(mission_state, indent=2) + "\n", encoding="utf-8")
            (mission_root / "mission_summary.md").write_text("# Summary\n", encoding="utf-8")
            (mission_root / "mission_decisions.jsonl").write_text("", encoding="utf-8")
            (mission_root / "mission_branches.jsonl").write_text("", encoding="utf-8")
            (mission_root / "mission_memory.json").write_text("{}\n", encoding="utf-8")
            (mission_root / "mission_experiments.jsonl").write_text("", encoding="utf-8")
            (mission_root / "ledger.jsonl").write_text("", encoding="utf-8")
            (findings_dir / "finding.md").write_text("- Archived replication evidence stayed intact.\n", encoding="utf-8")
            (runtime_dir / "runtime_state.json").write_text('{"status":"completed"}\n', encoding="utf-8")

            original_execution_dir = WORKSPACE_ROOT / mission_rel / "runtime" / "plain_folder_followups" / "runs" / "execution-baseline"
            original_replication_dir = WORKSPACE_ROOT / mission_rel / "runtime" / "plain_folder_followups" / "runs" / "replication-baseline"
            (execution_dir / "runtime_report.json").write_text('{"status":"completed"}\n', encoding="utf-8")
            (execution_dir / "metrics.json").write_text('{"accuracy":0.8}\n', encoding="utf-8")
            (replication_dir / "runtime_report.json").write_text('{"status":"completed"}\n', encoding="utf-8")
            (replication_dir / "metrics.json").write_text('{"accuracy":0.8}\n', encoding="utf-8")

            execution_manifest = {
                "mission_id": "archived-package-mission",
                "loop_id": "archived-execution-baseline",
                "claim_state": "exploratory",
                "run": {"status": "completed"},
                "metrics": {"accuracy": 0.8},
                "artifacts": {
                    "output_dir": str(original_execution_dir),
                    "report_paths": [str(original_execution_dir / "runtime_report.json")],
                },
                "stage_context": {
                    "artifacts": {
                        "metrics_json": str(original_execution_dir / "metrics.json"),
                    }
                },
                "notes": ["Generated plain-folder execution evidence run."],
            }
            replication_manifest = {
                "mission_id": "archived-package-mission",
                "loop_id": "archived-replication-baseline",
                "claim_state": "exploratory",
                "run": {"status": "completed"},
                "metrics": {"accuracy": 0.8},
                "artifacts": {
                    "output_dir": str(original_replication_dir),
                    "report_paths": [str(original_replication_dir / "runtime_report.json")],
                },
                "stage_context": {
                    "artifacts": {
                        "metrics_json": str(original_replication_dir / "metrics.json"),
                    }
                },
                "notes": ["Generated plain-folder replication evidence run."],
            }
            (execution_dir / "run_manifest.json").write_text(json.dumps(execution_manifest, indent=2) + "\n", encoding="utf-8")
            (replication_dir / "run_manifest.json").write_text(
                json.dumps(replication_manifest, indent=2) + "\n", encoding="utf-8"
            )

            result = package_mission_artifacts(mission_state_path, output_root=test_root / "repackaged")

            self.assertEqual(result["package"]["claim_summary"]["package_claim_state"], "replicated")
            self.assertEqual(result["package"]["replication_evidence"]["total_manifests"], 2)
            self.assertEqual(result["package"]["claim_summary"]["paper_candidate_blockers"], ["human approval"])
            self.assertEqual(validate_package_manifest(result["package"]), [])

if __name__ == "__main__":
    unittest.main()
