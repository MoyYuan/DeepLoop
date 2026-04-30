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
from deeploop.artifacts.submission_export import export_submission_repository
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
            adaptation_dir = mission_root / "adaptation_training" / "adapt-branch"
            adaptation_dir.mkdir(parents=True, exist_ok=True)
            (adaptation_dir / "adaptation_training_report.json").write_text('{"status":"completed"}\n', encoding="utf-8")
            (adaptation_dir / "adaptation_training_report.md").write_text("# Adaptation\n", encoding="utf-8")
            (adaptation_dir / "adaptation_training_comparison.json").write_text(
                '{"decision":"keep","route_to":"replication"}\n',
                encoding="utf-8",
            )

            output_root = test_root / "packages"
            result = package_mission_artifacts(mission_state_path, output_root=output_root)

            self.assertTrue(result["manifest_path"].exists())
            self.assertTrue(result["summary_path"].exists())
            checks = result["package"]["checks"]
            self.assertFalse(checks["all_required_artifacts_present"])
            self.assertEqual(checks["missing_required_artifacts"], ["category:manifests"])
            self.assertEqual(result["package"]["artifact_map"]["manifests"], [])
            self.assertGreaterEqual(len(result["package"]["artifact_map"]["critique_reports"]), 3)
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

    def test_packager_marks_pending_downstream_references_without_crashing(self) -> None:
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
            baseline_dir = runs_dir / "baseline-run"
            baseline_dir.mkdir(parents=True, exist_ok=True)

            mission_state_path = mission_root / "mission_state.json"
            mission_state = {
                "mission_id": "pending-downstream-mission",
                "title": "Pending downstream test",
                "objective": "Ensure evaluation-comparison references to future phases are marked pending.",
                "current_phase": "causal-intervention",
                "status": "in-progress",
                "target_repo": str(target_repo),
                "roles": ["execution-operator"],
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
            (findings_dir / "finding.md").write_text("- Causal intervention queued.\n", encoding="utf-8")
            (runtime_dir / "runtime_state.json").write_text('{"status":"in-progress"}\n', encoding="utf-8")

            # Phase 1 (baseline) manifest references a Phase 3 (intervention) manifest that doesn't
            # exist yet.  The downstream path simulates a queued evaluation-comparison handoff.
            future_intervention_dir = runs_dir / "intervention-run"
            future_manifest_path = future_intervention_dir / "study_manifest.json"

            baseline_manifest = {
                "mission_id": "pending-downstream-mission",
                "loop_id": "baseline-run",
                "claim_state": "exploratory",
                "run": {"status": "completed"},
                "metrics": {"accuracy": 0.75},
                "artifacts": {
                    "output_dir": str(baseline_dir),
                    "report_paths": [],
                },
                "evaluation": {
                    "compare_against": str(future_manifest_path),
                },
                "notes": ["Baseline completed; causal intervention pending."],
            }
            (baseline_dir / "run_manifest.json").write_text(
                json.dumps(baseline_manifest, indent=2) + "\n", encoding="utf-8"
            )

            output_root = test_root / "packages"
            # Must not raise FileNotFoundError despite the future path not existing.
            result = package_mission_artifacts(mission_state_path, output_root=output_root)

            self.assertTrue(result["manifest_path"].exists())
            checks = result["package"]["checks"]
            # The future manifest path should be tracked as a pending downstream artifact.
            self.assertIn("pending_downstream_artifacts", checks)
            self.assertTrue(
                any(str(future_manifest_path) in path for path in checks["pending_downstream_artifacts"])
            )
            # The pending artifact must not appear in the main artifacts list.
            present_paths = {a["source_path"] for a in result["package"]["artifacts"]}
            self.assertNotIn(str(future_manifest_path.resolve()), present_paths)
            # Package digest and copy must succeed (baseline manifest present).
            self.assertGreater(len(result["package"]["artifacts"]), 0)
            self.assertEqual(validate_package_manifest(result["package"]), [])

    def test_packager_includes_recorded_recursive_agent_outputs(self) -> None:
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
            smoke_dir = mission_root / "runtime" / "plain_folder_followups" / "runs" / "replication-baseline"
            smoke_dir.mkdir(parents=True, exist_ok=True)
            agent_runtime = mission_root / "runtime" / "recursive-agent"
            agent_runtime.mkdir(parents=True, exist_ok=True)
            scratch_outputs = test_root / "sandboxes" / "recursive-output-package-mission" / "execution-operator" / "outputs"
            scout_outputs = test_root / "sandboxes" / "recursive-output-package-mission" / "literature-scout" / "outputs"
            scratch_outputs.mkdir(parents=True, exist_ok=True)
            scout_outputs.mkdir(parents=True, exist_ok=True)

            task_metrics = scratch_outputs / "metrics.json"
            task_metrics.write_text('{"test_mae":81.045,"raw_pred_improvement_pct":10.7}\n', encoding="utf-8")
            run_log = scratch_outputs / "run-log.txt"
            run_log.write_text("trained direct history_48 model\n", encoding="utf-8")
            stability_notes = scratch_outputs / "stability-notes.txt"
            stability_notes.write_text("residual correction was less stable\n", encoding="utf-8")
            predictions = scratch_outputs / "test-predictions.jsonl"
            predictions.write_text('{"y":1,"prediction":1.2}\n', encoding="utf-8")
            prior_art = scout_outputs / "prior-art-memo.md"
            prior_art.write_text("# Prior art\n", encoding="utf-8")
            hypotheses = scout_outputs / "hypotheses-and-evaluation-targets.json"
            hypotheses.write_text('{"primary_metric":"test_mae"}\n', encoding="utf-8")
            missing_output = scratch_outputs / "missing-task-output.json"

            mission_state_path = mission_root / "mission_state.json"
            memory_path = agent_runtime / "memory.jsonl"
            mission_state = {
                "mission_id": "recursive-output-package-mission",
                "title": "Recursive output package test",
                "objective": "Package recursive-agent task outputs before smoke metadata.",
                "current_phase": "final-report",
                "status": "completed",
                "target_repo": str(target_repo),
                "roles": ["literature-scout", "execution-operator", "report-synthesizer"],
                "artifacts": {"docs": [], "configs": []},
                "next_actions": {
                    "actions": [
                        {
                            "action_id": "execute-forecast",
                            "phase": "execution",
                            "status": "completed",
                            "output_paths": [str(task_metrics), str(run_log), str(missing_output)],
                        }
                    ],
                    "generated_configs": [],
                },
                "agent_driver": {
                    "memory_path": str(memory_path),
                    "latest_outcome": {
                        "produced_artifacts": [str(stability_notes), str(predictions)],
                        "action_result": {
                            "phase": "execution",
                            "output_paths": [str(task_metrics), str(run_log), str(stability_notes), str(predictions)],
                        },
                    },
                },
            }
            mission_state_path.write_text(json.dumps(mission_state, indent=2) + "\n", encoding="utf-8")
            memory_path.write_text(
                json.dumps(
                    {
                        "phase": "literature-review",
                        "produced_artifacts": [str(prior_art)],
                        "action_result": {"output_paths": [str(hypotheses)]},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (mission_root / "mission_summary.md").write_text("# Summary\n", encoding="utf-8")
            (mission_root / "mission_decisions.jsonl").write_text("", encoding="utf-8")
            (mission_root / "mission_branches.jsonl").write_text("", encoding="utf-8")
            (mission_root / "mission_memory.json").write_text("{}\n", encoding="utf-8")
            (mission_root / "mission_experiments.jsonl").write_text("", encoding="utf-8")
            (mission_root / "ledger.jsonl").write_text("", encoding="utf-8")
            (findings_dir / "finding.md").write_text("- Forecasting execution found chronology-safe evidence.\n", encoding="utf-8")
            (runtime_dir / "runtime_state.json").write_text('{"status":"completed"}\n', encoding="utf-8")
            (smoke_dir / "metrics.json").write_text('{"accuracy":1.0}\n', encoding="utf-8")
            smoke_manifest = {
                "mission_id": "recursive-output-package-mission",
                "loop_id": "plain-folder-replication-baseline",
                "claim_state": "exploratory",
                "run": {"status": "completed"},
                "metrics": {"accuracy": 1.0},
                "artifacts": {
                    "output_dir": str(smoke_dir),
                    "report_paths": [],
                },
                "notes": ["Generated plain-folder replication smoke evidence."],
            }
            (smoke_dir / "run_manifest.json").write_text(json.dumps(smoke_manifest, indent=2) + "\n", encoding="utf-8")

            result = package_mission_artifacts(mission_state_path, output_root=test_root / "packages")
            package = result["package"]
            artifact_paths = {Path(artifact["source_path"]).name: artifact for artifact in package["artifacts"]}

            self.assertIn("metrics.json", artifact_paths)
            self.assertIn("run-log.txt", artifact_paths)
            self.assertIn("stability-notes.txt", artifact_paths)
            self.assertIn("test-predictions.jsonl", artifact_paths)
            self.assertIn("prior-art-memo.md", artifact_paths)
            self.assertIn("hypotheses-and-evaluation-targets.json", artifact_paths)
            self.assertEqual(len(package["artifact_map"]["task_metrics"]), 1)
            self.assertEqual(len(package["artifact_map"]["task_predictions"]), 1)
            self.assertEqual(len(package["artifact_map"]["task_run_logs"]), 2)
            self.assertGreaterEqual(len(package["artifact_map"]["task_method_artifacts"]), 2)
            self.assertEqual(len(package["artifact_map"]["plain_folder_smoke_metadata"]), 1)
            self.assertFalse(package["checks"]["all_required_artifacts_present"])
            self.assertTrue(
                any(str(missing_output) in item for item in package["checks"]["missing_required_artifacts"])
            )
            self.assertEqual(package["checks"]["missing_recorded_output_artifacts"][0]["source_path"], str(missing_output))
            summary_text = result["summary_path"].read_text(encoding="utf-8")
            self.assertLess(
                summary_text.index("Task metric: metrics.json"),
                summary_text.index("Plain-folder smoke metadata (not task evidence): metrics.json"),
            )
            self.assertEqual(validate_package_manifest(package), [])

    def test_packager_overwrites_existing_package_directory_without_crashing(self) -> None:
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
                "mission_id": "rerun-package-mission",
                "title": "Re-run package test",
                "objective": "Packaging must succeed even when output directory already exists.",
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
            (findings_dir / "finding.md").write_text("- Finding.\n", encoding="utf-8")
            (runtime_dir / "runtime_state.json").write_text('{"status":"completed"}\n', encoding="utf-8")
            adaptation_dir = mission_root / "adaptation_training" / "adapt-branch"
            adaptation_dir.mkdir(parents=True, exist_ok=True)
            (adaptation_dir / "adaptation_training_report.json").write_text('{"status":"completed"}\n', encoding="utf-8")
            (adaptation_dir / "adaptation_training_report.md").write_text("# Adaptation\n", encoding="utf-8")
            (adaptation_dir / "adaptation_training_comparison.json").write_text(
                '{"decision":"keep","route_to":"replication"}\n',
                encoding="utf-8",
            )

            output_root = test_root / "packages"

            # First run: create the package directory.
            package_mission_artifacts(mission_state_path, output_root=output_root)

            # Simulate a locked/non-empty sub-tree left over from the first run (e.g.
            # research_memory JSON ledger) by writing a nested file after packaging.
            stale_dir = output_root / "rerun-package-mission" / "research_memory"
            stale_dir.mkdir(parents=True, exist_ok=True)
            (stale_dir / "ledger.json").write_text('{"stale": true}\n', encoding="utf-8")

            # Second run must not crash with [Errno 39] Directory not empty.
            result = package_mission_artifacts(mission_state_path, output_root=output_root)

            self.assertTrue(result["manifest_path"].exists())
            self.assertTrue(result["summary_path"].exists())

    def test_submission_export_materializes_clean_repo_layout(self) -> None:
        runs_root = WORKSPACE_ROOT / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runs_root) as tmpdir:
            test_root = Path(tmpdir)
            mission_root = test_root / "mission"
            mission_root.mkdir(parents=True, exist_ok=True)
            target_repo = test_root / "plain-project"
            target_repo.mkdir(parents=True, exist_ok=True)
            (target_repo / "docs").mkdir(parents=True, exist_ok=True)
            project_facts = target_repo / "project-facts.yaml"
            method_doc = target_repo / "docs" / "method.md"
            project_facts.write_text("dataset: demo\n", encoding="utf-8")
            method_doc.write_text("# Method\nBounded forecasting baseline.\n", encoding="utf-8")
            findings_dir = mission_root / "findings"
            findings_dir.mkdir(parents=True, exist_ok=True)
            runtime_dir = mission_root / "runtime" / "mission_outer_runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            run_dir = mission_root / "runtime" / "plain_folder_followups" / "runs" / "forecast-baseline"
            run_dir.mkdir(parents=True, exist_ok=True)

            mission_state_path = mission_root / "mission_state.json"
            mission_state = {
                "mission_id": "submission-export-mission",
                "title": "Submission export test",
                "objective": "Export a completed forecasting mission into a GitHub-ready folder.",
                "current_phase": "final-report",
                "status": "completed",
                "target_repo": str(target_repo),
                "roles": ["execution-operator", "report-synthesizer"],
                "artifacts": {"docs": [str(method_doc)], "configs": [str(project_facts)]},
                "next_actions": {"actions": [], "generated_configs": []},
            }
            mission_state_path.write_text(json.dumps(mission_state, indent=2) + "\n", encoding="utf-8")
            (mission_root / "mission_summary.md").write_text("# Summary\nForecasting completed.\n", encoding="utf-8")
            (mission_root / "mission_decisions.jsonl").write_text("", encoding="utf-8")
            (mission_root / "mission_branches.jsonl").write_text("", encoding="utf-8")
            (mission_root / "mission_memory.json").write_text("{}\n", encoding="utf-8")
            (mission_root / "mission_experiments.jsonl").write_text("", encoding="utf-8")
            (mission_root / "ledger.jsonl").write_text("", encoding="utf-8")
            (findings_dir / "caveat.md").write_text("- Limited to the demo split.\n", encoding="utf-8")
            (runtime_dir / "runtime_state.json").write_text('{"status":"completed"}\n', encoding="utf-8")
            (run_dir / "metrics.json").write_text('{"mape": 0.12}\n', encoding="utf-8")
            (run_dir / "predictions.csv").write_text("timestamp,yhat\n2026-01-01,1.0\n", encoding="utf-8")
            (run_dir / "run-log.txt").write_text("completed\n", encoding="utf-8")
            (run_dir / "stability-notes.txt").write_text("No observed instability.\n", encoding="utf-8")
            manifest = {
                "mission_id": "submission-export-mission",
                "loop_id": "forecast-baseline",
                "claim_state": "replicated",
                "run": {"status": "completed"},
                "metrics": {"accuracy": 0.88},
                "artifacts": {
                    "output_dir": str(run_dir),
                    "log_path": str(run_dir / "run-log.txt"),
                    "report_paths": [],
                },
                "stage_context": {
                    "artifacts": {
                        "metrics_json": str(run_dir / "metrics.json"),
                        "predictions_csv": str(run_dir / "predictions.csv"),
                        "stability_notes": str(run_dir / "stability-notes.txt"),
                    }
                },
                "notes": ["Final report claim references metrics and predictions."],
            }
            (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            output_root = test_root / "submission-repo"
            result = export_submission_repository(mission_state_path, output_root, force=True)

            self.assertTrue(result["readme_path"].exists())
            self.assertTrue((output_root / "submission_manifest.json").exists())
            self.assertTrue((output_root / "provenance.json").exists())
            self.assertTrue((output_root / "caveats-and-limitations.md").exists())
            self.assertTrue((output_root / "project-input" / "project-facts.yaml").exists())
            self.assertTrue((output_root / "project-input" / "docs" / "method.md").exists())
            self.assertTrue((output_root / "results" / "metrics" / "metrics.json").exists())
            self.assertTrue((output_root / "results" / "predictions" / "predictions.csv").exists())
            self.assertTrue((output_root / "results" / "logs" / "run-log.txt").exists())
            self.assertTrue((output_root / "results" / "stability-notes" / "stability-notes.txt").exists())
            self.assertTrue((output_root / "manifests" / "run_manifest.json").exists())
            self.assertTrue((output_root / "bookkeeping" / "deeploop" / "mission_artifact_package.json").exists())
            submission_manifest = json.loads((output_root / "submission_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(submission_manifest["checks"]["all_package_artifacts_copied"])
            self.assertFalse((output_root / "runs").exists())
            self.assertFalse((output_root / "scratch").exists())
if __name__ == "__main__":
    unittest.main()
