from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import MISSIONS_DIR
from deeploop.mission.project_runner import _find_explicit_mission_configs, initialize_mission_from_project_root, run_project_until_complete


class ProjectRunnerTests(unittest.TestCase):
    def test_initialize_mission_from_project_root_reuses_existing_state_without_force(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "resume-existing"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        project_root = test_root / "translation-pilot"
        project_root.mkdir(parents=True, exist_ok=True)
        mission_root = MISSIONS_DIR / "resume-existing-mission"
        shutil.rmtree(mission_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(mission_root, ignore_errors=True))
        mission_root.mkdir(parents=True, exist_ok=True)
        state_path = mission_root / "mission_state.json"
        state_path.write_text("{}\n", encoding="utf-8")

        with patch("deeploop.mission.project_bootstrap.build_mission_config_from_project_root") as mock_build_config:
            mock_build_config.return_value = {"mission": {"id": "resume-existing-mission"}}
            result = initialize_mission_from_project_root(project_root, force=False)

        self.assertEqual(result["mission_root"], mission_root)
        self.assertEqual(result["state_path"], state_path)
        self.assertTrue(result["generated_config_path"].exists())
        self.assertEqual(mock_build_config.call_count, 1)

    def test_run_project_until_complete_extends_runtime_limit_until_completion(self) -> None:
        project_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "completion"
        shutil.rmtree(project_root, ignore_errors=True)
        project_root.mkdir(parents=True, exist_ok=True)
        mission_root = project_root / "mission-root"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state_path.write_text("{}\n", encoding="utf-8")

        run_results = [
            {"status": "max-iterations", "iterations_completed": 4},
            {"status": "completed", "iterations_completed": 7},
        ]
        snapshots = [
            {"operator_console": {"requires_action": False}},
            {"operator_console": {"requires_action": False}},
        ]

        with (
            patch("deeploop.mission.project_runner.initialize_mission_from_project_root") as mock_init,
            patch("deeploop.mission.project_runner.run_mission") as mock_run_mission,
            patch("deeploop.mission.project_runner.build_mission_snapshot") as mock_snapshot,
        ):
            mock_init.return_value = {
                "mission_root": mission_root,
                "state_path": mission_state_path,
            }
            mock_run_mission.side_effect = run_results
            mock_snapshot.side_effect = snapshots

            result = run_project_until_complete(
                project_root,
                force=True,
                chunk_iterations=4,
                max_total_iterations=12,
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["runtime_passes"], 2)
        self.assertEqual(mock_run_mission.call_args_list[0].kwargs["max_iterations"], 4)
        self.assertEqual(mock_run_mission.call_args_list[1].kwargs["max_iterations"], 8)

    def test_run_project_until_complete_stops_for_operator_review(self) -> None:
        project_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "blocked"
        shutil.rmtree(project_root, ignore_errors=True)
        project_root.mkdir(parents=True, exist_ok=True)
        mission_root = project_root / "mission-root"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state_path.write_text("{}\n", encoding="utf-8")

        with (
            patch("deeploop.mission.project_runner.initialize_mission_from_project_root") as mock_init,
            patch("deeploop.mission.project_runner.run_mission") as mock_run_mission,
            patch("deeploop.mission.project_runner.build_mission_snapshot") as mock_snapshot,
        ):
            mock_init.return_value = {
                "mission_root": mission_root,
                "state_path": mission_state_path,
            }
            mock_run_mission.return_value = {"status": "blocked", "iterations_completed": 3}
            mock_snapshot.return_value = {
                "operator_console": {"requires_action": True, "headline": "BLOCKED"},
                "operator_inbox": {"current_request": {"summary": "demo hard boundary"}},
            }

            result = run_project_until_complete(project_root, chunk_iterations=3, max_total_iterations=12)

        self.assertEqual(result["status"], "operator-review-required")
        self.assertEqual(result["runtime_passes"], 1)

    def test_run_project_until_complete_auto_resumes_soft_gate_recovery(self) -> None:
        project_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "soft-gate"
        shutil.rmtree(project_root, ignore_errors=True)
        project_root.mkdir(parents=True, exist_ok=True)
        mission_root = project_root / "mission-root"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state_path.write_text("{}\n", encoding="utf-8")

        with (
            patch("deeploop.mission.project_runner.initialize_mission_from_project_root") as mock_init,
            patch("deeploop.mission.project_runner.run_mission") as mock_run_mission,
            patch("deeploop.mission.project_runner.build_mission_snapshot") as mock_snapshot,
        ):
            mock_init.return_value = {
                "mission_root": mission_root,
                "state_path": mission_state_path,
            }
            mock_run_mission.side_effect = [
                {"status": "blocked", "iterations_completed": 3},
                {"status": "completed", "iterations_completed": 5},
            ]
            mock_snapshot.side_effect = [
                {
                    "operator_console": {
                        "requires_action": True,
                        "gate_class": "soft-gate",
                        "resume_policy": "resume-optional",
                    }
                },
                {"operator_console": {"requires_action": False}},
            ]

            result = run_project_until_complete(project_root, chunk_iterations=3, max_total_iterations=12)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["runtime_passes"], 2)
        self.assertEqual(mock_run_mission.call_args_list[0].kwargs["max_iterations"], 3)
        self.assertEqual(mock_run_mission.call_args_list[1].kwargs["max_iterations"], 6)

    def test_run_project_until_complete_stops_at_total_iteration_budget(self) -> None:
        project_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "budget"
        shutil.rmtree(project_root, ignore_errors=True)
        project_root.mkdir(parents=True, exist_ok=True)
        mission_root = project_root / "mission-root"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state_path.write_text("{}\n", encoding="utf-8")

        with (
            patch("deeploop.mission.project_runner.initialize_mission_from_project_root") as mock_init,
            patch("deeploop.mission.project_runner.run_mission") as mock_run_mission,
            patch("deeploop.mission.project_runner.build_mission_snapshot") as mock_snapshot,
        ):
            mock_init.return_value = {
                "mission_root": mission_root,
                "state_path": mission_state_path,
            }
            mock_run_mission.side_effect = [
                {"status": "max-iterations", "iterations_completed": 4},
                {"status": "max-iterations", "iterations_completed": 8},
            ]
            mock_snapshot.side_effect = [
                {"operator_console": {"requires_action": False}},
                {"operator_console": {"requires_action": False}},
            ]

            result = run_project_until_complete(project_root, chunk_iterations=4, max_total_iterations=8)

        self.assertEqual(result["status"], "max-total-iterations")
        self.assertEqual(result["runtime_passes"], 2)

    @patch("deeploop.runtime.mission_executor_registry.package_mission_artifacts")
    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_run_project_until_complete_accepts_plain_folder_without_local_deeploop_state(
        self,
        mock_run_recursive_agent_loop,
        mock_package_mission_artifacts,
    ) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "plain-folder-acceptance"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        project_root = test_root / "translation-pilot"
        (project_root / "docs").mkdir(parents=True, exist_ok=True)
        (project_root / "docs" / "project-brief.md").write_text("# Project brief\n", encoding="utf-8")
        (project_root / "docs" / "benchmark-and-metrics.md").write_text("# Benchmark and metrics\n", encoding="utf-8")
        (project_root / "project-facts.yaml").write_text(
            yaml.safe_dump(
                {
                    "project": {
                        "name": "translation-plain-folder-acceptance",
                        "title": "Plain folder acceptance mission",
                        "summary": "Start from a minimal researcher folder only.",
                        "objective": "Reach a completed mission without putting DeepLoop runtime state in the substrate repo.",
                        "constraints": ["Keep the substrate folder researcher-owned and no-code."],
                    },
                    "artifacts": {"docs": ["docs/project-brief.md", "docs/benchmark-and-metrics.md"]},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        outputs_by_phase = {
            "idea-intake": ["mission brief", "rough constraints"],
            "literature-review": ["prior-art memo", "benchmark and method watchlist"],
            "question-design": ["hypotheses", "evaluation targets"],
            "benchmark-selection": ["dataset shortlist", "slice plan"],
            "experiment-design": ["run manifest draft", "execution profile selection", "resource tier selection"],
            "execution": ["run logs", "metrics", "crash / stability notes"],
            "critique": ["evidence assessment", "confound notes", "next-step recommendation"],
            "replication": ["repeated-run manifests", "replication summary"],
        }

        def _fake_recursive_runtime(config_path: Path) -> dict:
            config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
            mission_state_path = Path(config["mission_state"])
            state = json.loads(mission_state_path.read_text(encoding="utf-8"))
            phase = state["current_phase"]
            next_phase = {
                "question-design": "benchmark-selection",
                "execution": "critique",
                "critique": "replication",
                "replication": "final-report",
            }.get(phase, state.get("next_phase"))
            runtime_root = test_root / "recursive-runtime" / phase
            runtime_root.mkdir(parents=True, exist_ok=True)
            return {
                "status": "completed",
                "runtime_root": runtime_root,
                "state_path": runtime_root / "agent_loop_state.json",
                "memory_path": runtime_root / "loop_memory.jsonl",
                "latest_iteration_path": runtime_root / "iteration-01",
                "latest_result_path": runtime_root / "iteration-01" / "result.json",
                "report_json_path": runtime_root / "report.json",
                "report_markdown_path": runtime_root / "report.md",
                "produced_outputs": outputs_by_phase[phase],
                "latest_outcome": {
                    "phase_control": {"current_phase": phase, "next_phase": next_phase},
                    "action_result": {
                        "mission_action_id": f"plain-folder-acceptance-{phase}-missing-outputs",
                        "output_paths": [],
                    },
                },
            }

        mock_run_recursive_agent_loop.side_effect = _fake_recursive_runtime
        package_root = test_root / "package"
        package_root.mkdir(parents=True, exist_ok=True)
        mock_package_mission_artifacts.return_value = {
            "package_root": package_root,
            "manifest_path": package_root / "mission_artifact_package.json",
            "summary_path": package_root / "mission_artifact_package.md",
            "produced_outputs": ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        }

        result = run_project_until_complete(
            project_root,
            mission_id="plain-folder-acceptance-mission",
            force=True,
            chunk_iterations=4,
            max_total_iterations=32,
        )
        self.addCleanup(lambda: shutil.rmtree(Path(result["mission_root"]), ignore_errors=True))

        self.assertEqual(result["status"], "completed")
        mission_state = json.loads(Path(result["mission_state_path"]).read_text(encoding="utf-8"))
        self.assertEqual(mission_state["status"], "completed")
        self.assertEqual(mission_state["current_phase"], "final-report")
        self.assertEqual(mission_state["project_contract"]["status"], "plain-artifacts")
        self.assertEqual(mission_state["target_repo"], str(project_root.resolve()))
        self.assertEqual(mission_state["operator_inbox"]["status"], "clear")
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["final-report"],
            ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        )
        self.assertFalse((project_root / ".deeploop").exists())
        self.assertEqual(
            sorted(str(path.relative_to(project_root)) for path in project_root.rglob("*") if path.is_file()),
            [
                "docs/benchmark-and-metrics.md",
                "docs/project-brief.md",
                "project-facts.yaml",
            ],
        )

    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_run_project_until_complete_plain_folder_package_includes_manifests(
        self,
        mock_run_recursive_agent_loop,
    ) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "plain-folder-evidence"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        project_root = test_root / "translation-pilot"
        (project_root / "docs").mkdir(parents=True, exist_ok=True)
        (project_root / "docs" / "project-brief.md").write_text(
            "# Project brief\n- Evaluate translation quality from a plain folder substrate.\n",
            encoding="utf-8",
        )
        (project_root / "docs" / "benchmark-and-metrics.md").write_text(
            "# Benchmark and metrics\n- Track lexical accuracy and slice stability.\n",
            encoding="utf-8",
        )
        (project_root / "project-facts.yaml").write_text(
            yaml.safe_dump(
                {
                    "project": {
                        "name": "translation-plain-folder-evidence",
                        "title": "Plain folder evidence mission",
                        "summary": "Generate runnable evidence outside the researcher folder.",
                        "objective": "Reach final report with manifest-backed evidence.",
                        "constraints": ["Leave the researcher folder unchanged."],
                    },
                    "artifacts": {"docs": ["docs/project-brief.md", "docs/benchmark-and-metrics.md"]},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        outputs_by_phase = {
            "idea-intake": ["mission brief", "rough constraints"],
            "literature-review": ["prior-art memo", "benchmark and method watchlist"],
            "question-design": ["hypotheses", "evaluation targets"],
            "benchmark-selection": ["dataset shortlist", "slice plan"],
            "experiment-design": ["run manifest draft", "execution profile selection", "resource tier selection"],
        }

        def _fake_recursive_runtime(config_path: Path) -> dict:
            config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
            mission_state_path = Path(config["mission_state"])
            state = json.loads(mission_state_path.read_text(encoding="utf-8"))
            phase = state["current_phase"]
            next_phase = {
                "question-design": "benchmark-selection",
                "benchmark-selection": "experiment-design",
                "experiment-design": "execution",
            }.get(phase, state.get("next_phase"))
            runtime_root = test_root / "recursive-runtime" / phase
            runtime_root.mkdir(parents=True, exist_ok=True)
            return {
                "status": "completed",
                "runtime_root": runtime_root,
                "state_path": runtime_root / "agent_loop_state.json",
                "memory_path": runtime_root / "loop_memory.jsonl",
                "latest_iteration_path": runtime_root / "iteration-01",
                "latest_result_path": runtime_root / "iteration-01" / "result.json",
                "report_json_path": runtime_root / "report.json",
                "report_markdown_path": runtime_root / "report.md",
                "produced_outputs": outputs_by_phase[phase],
                "latest_outcome": {
                    "phase_control": {"current_phase": phase, "next_phase": next_phase},
                    "action_result": {
                        "mission_action_id": f"plain-folder-evidence-{phase}",
                        "output_paths": [],
                    },
                },
            }

        mock_run_recursive_agent_loop.side_effect = _fake_recursive_runtime

        result = run_project_until_complete(
            project_root,
            mission_id="plain-folder-evidence-mission",
            force=True,
            chunk_iterations=4,
            max_total_iterations=32,
        )
        self.addCleanup(lambda: shutil.rmtree(Path(result["mission_root"]), ignore_errors=True))

        self.assertEqual(result["status"], "completed")
        mission_state = json.loads(Path(result["mission_state_path"]).read_text(encoding="utf-8"))
        package_manifest_path = Path(mission_state["mission_package"]["manifest_path"])
        package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(package_manifest["checks"]["artifact_count_by_category"]["manifests"], 2)
        self.assertGreaterEqual(package_manifest["checks"]["artifact_count_by_category"]["critique_reports"], 1)
        self.assertNotIn("category:manifests", package_manifest["checks"]["missing_required_artifacts"])
        self.assertFalse((project_root / ".deeploop").exists())


    def test_find_explicit_mission_configs_returns_empty_when_no_deeploop_dir(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "no-deeploop"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        test_root.mkdir(parents=True, exist_ok=True)

        result = _find_explicit_mission_configs(test_root)

        self.assertEqual(result, [])

    def test_find_explicit_mission_configs_returns_yaml_files_from_missions_dir(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "explicit-configs"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        missions_dir = test_root / ".deeploop" / "missions"
        missions_dir.mkdir(parents=True, exist_ok=True)
        (missions_dir / "alpha-run.yaml").write_text("mission:\n  id: alpha\n", encoding="utf-8")
        (missions_dir / "beta-run.yml").write_text("mission:\n  id: beta\n", encoding="utf-8")

        result = _find_explicit_mission_configs(test_root)

        names = [p.name for p in result]
        self.assertIn("alpha-run.yaml", names)
        self.assertIn("beta-run.yml", names)

    def test_initialize_mission_from_project_root_uses_explicit_config_when_present(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "explicit-config-init"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        missions_dir = test_root / ".deeploop" / "missions"
        missions_dir.mkdir(parents=True, exist_ok=True)
        explicit_config_path = missions_dir / "custom-mission.yaml"
        explicit_config_path.write_text("mission:\n  id: custom-explicit-mission\n", encoding="utf-8")
        mission_root = MISSIONS_DIR / "custom-explicit-mission"
        shutil.rmtree(mission_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(mission_root, ignore_errors=True))

        sentinel_result = {
            "mission_root": mission_root,
            "state_path": mission_root / "mission_state.json",
            "summary_path": mission_root / "mission_summary.md",
            "ledger_path": mission_root / "ledger.jsonl",
        }
        with (
            patch("deeploop.mission.project_runner.initialize_mission") as mock_init_mission,
            patch("deeploop.mission.project_bootstrap.build_mission_config_from_project_root") as mock_build_config,
        ):
            mock_init_mission.return_value = sentinel_result

            result = initialize_mission_from_project_root(test_root, force=False)

        mock_init_mission.assert_called_once_with(explicit_config_path, force=False)
        mock_build_config.assert_not_called()
        self.assertEqual(result, sentinel_result)

    def test_initialize_mission_from_project_root_bootstraps_when_no_explicit_config(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "no-explicit-config-init"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        test_root.mkdir(parents=True, exist_ok=True)
        mission_root = MISSIONS_DIR / "bootstrap-only-mission"
        shutil.rmtree(mission_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(mission_root, ignore_errors=True))
        mission_root.mkdir(parents=True, exist_ok=True)

        sentinel_result = {
            "mission_root": mission_root,
            "state_path": mission_root / "mission_state.json",
            "summary_path": mission_root / "mission_summary.md",
            "ledger_path": mission_root / "ledger.jsonl",
        }
        with (
            patch("deeploop.mission.project_runner.initialize_mission") as mock_init_mission,
            patch("deeploop.mission.project_bootstrap.build_mission_config_from_project_root") as mock_build_config,
        ):
            mock_build_config.return_value = {"mission": {"id": "bootstrap-only-mission"}}
            mock_init_mission.return_value = sentinel_result
            result = initialize_mission_from_project_root(test_root, force=False)

        mock_build_config.assert_called_once()
        self.assertIn("generated_config_path", result)

    def test_initialize_mission_from_project_root_prints_notice_for_explicit_config(self) -> None:
        import io
        import contextlib

        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "explicit-config-notice"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        missions_dir = test_root / ".deeploop" / "missions"
        missions_dir.mkdir(parents=True, exist_ok=True)
        (missions_dir / "my-mission.yaml").write_text("mission:\n  id: notice-mission\n", encoding="utf-8")
        mission_root = MISSIONS_DIR / "notice-mission"
        shutil.rmtree(mission_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(mission_root, ignore_errors=True))

        sentinel_result = {
            "mission_root": mission_root,
            "state_path": mission_root / "mission_state.json",
            "summary_path": mission_root / "mission_summary.md",
            "ledger_path": mission_root / "ledger.jsonl",
        }
        buf = io.StringIO()
        with (
            patch("deeploop.mission.project_runner.initialize_mission") as mock_init_mission,
            contextlib.redirect_stdout(buf),
        ):
            mock_init_mission.return_value = sentinel_result
            initialize_mission_from_project_root(test_root, force=False)

        output = buf.getvalue()
        self.assertIn("detected explicit mission config", output)
        self.assertIn("my-mission.yaml", output)

    def test_initialize_mission_from_project_root_warns_when_mission_id_overridden_by_explicit_config(self) -> None:
        import io
        import contextlib

        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "explicit-config-mission-id-warn"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        missions_dir = test_root / ".deeploop" / "missions"
        missions_dir.mkdir(parents=True, exist_ok=True)
        (missions_dir / "explicit.yaml").write_text("mission:\n  id: explicit-id\n", encoding="utf-8")
        mission_root = MISSIONS_DIR / "explicit-id"
        shutil.rmtree(mission_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(mission_root, ignore_errors=True))

        sentinel_result = {
            "mission_root": mission_root,
            "state_path": mission_root / "mission_state.json",
            "summary_path": mission_root / "mission_summary.md",
            "ledger_path": mission_root / "ledger.jsonl",
        }
        buf = io.StringIO()
        with (
            patch("deeploop.mission.project_runner.initialize_mission") as mock_init_mission,
            contextlib.redirect_stdout(buf),
        ):
            mock_init_mission.return_value = sentinel_result
            initialize_mission_from_project_root(test_root, mission_id="my-override-id", force=False)

        output = buf.getvalue()
        self.assertIn("--mission-id", output)
        self.assertIn("takes precedence", output)
