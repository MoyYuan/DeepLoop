from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import MISSIONS_DIR
from deeploop.cli.run_project import _add_run_args, _noncompleted_summary_lines, _run_project
from deeploop.mission.project_runner import (
    _find_explicit_mission_configs,
    initialize_mission_from_project_root,
    run_config_until_complete,
    run_project_until_complete,
)


class ProjectRunnerTests(unittest.TestCase):
    def test_run_project_surfaces_handoff_summary_on_stderr(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = argparse.Namespace(
            project_root="/repo/demo",
            mission_id=None,
            force=False,
            until_complete=True,
            chunk_iterations=4,
            max_total_iterations=24,
        )
        result = {
            "status": "operator-review-required",
            "mission_state_path": Path("/repo/demo/.deeploop/mission_state.json"),
            "snapshot": {
                "operator_console": {
                    "headline": "PAUSED — DeepLoop needs an operator decision before it can continue.",
                    "summary": "Autopilot paused at `sandbox-boundary`: attempted write outside mutable roots.",
                    "recommendation": "Start with `status`, open `inbox`, make the smallest safe change or choice, then `resume`.",
                    "next_commands": [
                        {
                            "command": "deeploop inbox --mission-state /repo/demo/.deeploop/mission_state.json",
                        }
                    ],
                }
            },
        }

        with patch("deeploop.cli.run_project.run_project_until_complete", return_value=result):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = _run_project(args)

        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "operator-review-required")
        self.assertIn("DeepLoop paused before completion.", stderr.getvalue())
        self.assertIn("PAUSED — DeepLoop needs an operator decision", stderr.getvalue())
        self.assertIn("deeploop status --mission-state /repo/demo/.deeploop/mission_state.json", stderr.getvalue())
        self.assertIn("deeploop inbox --mission-state /repo/demo/.deeploop/mission_state.json", stderr.getvalue())
        self.assertIn("deeploop resume --mission-state /repo/demo/.deeploop/mission_state.json", stderr.getvalue())

    def test_run_project_with_plain_folder_prefers_bootstrap_over_provider_gate(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        project_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "plain-folder-bootstrap-first"
        shutil.rmtree(project_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(project_root, ignore_errors=True))
        project_root.mkdir(parents=True, exist_ok=True)
        args = argparse.Namespace(
            project_root=str(project_root),
            mission_id="bootstrap-first",
            force=False,
            until_complete=True,
            chunk_iterations=4,
            max_total_iterations=24,
        )
        result = {
            "status": "bootstrap-repair-required",
            "project_root": project_root,
            "bootstrap_repair": {
                "status": "required",
                "reason": "missing-bootstrap-contract",
                "summary": "Project root needs project-facts.yaml.",
                "recommendation": "Create project-facts.yaml.",
            },
        }

        with (
            patch("deeploop.cli.run_project._provider_readiness_result") as mock_provider_gate,
            patch("deeploop.cli.run_project.run_project_until_complete", return_value=result) as mock_run_project,
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = _run_project(args)

        self.assertEqual(exit_code, 1)
        mock_provider_gate.assert_not_called()
        mock_run_project.assert_called_once()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "bootstrap-repair-required")
        self.assertIn("could not bootstrap this project root yet", stderr.getvalue())
        self.assertIn("missing-bootstrap-contract", stderr.getvalue())

    def test_run_project_with_plain_folder_surfaces_mission_readiness_guidance(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = argparse.Namespace(
            project_root="/repo/demo",
            mission_id="demo-mission",
            force=False,
            until_complete=True,
            chunk_iterations=4,
            max_total_iterations=24,
        )
        result = {
            "status": "mission-readiness-required",
            "mission_state_path": Path("/repo/runtime/demo-mission/mission_state.json"),
            "mission_summary_path": Path("/repo/runtime/demo-mission/mission_summary.md"),
            "readiness": {
                "status": "blocked",
                "launch_recommendation": "stop-for-operator-input",
            },
            "follow_up_questions": [
                "Where is the dataset located, or how should DeepLoop obtain access to it?",
                "What leakage boundary should DeepLoop enforce for train, validation, and test data?",
            ],
        }

        with patch("deeploop.cli.run_project.run_project_until_complete", return_value=result):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = _run_project(args)

        self.assertEqual(exit_code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "mission-readiness-required")
        self.assertIn("mission contract still needs operator input", stderr.getvalue())
        self.assertIn("stop-for-operator-input", stderr.getvalue())
        self.assertIn("Where is the dataset located", stderr.getvalue())
        self.assertIn("mission_summary.md", stderr.getvalue())

    def test_run_project_without_project_root_uses_idea_flow(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = argparse.Namespace(
            project_root=None,
            idea="Find a good starter path.",
            mission_idea="Find a good starter path.",
            mission_id="interactive-run",
            force=False,
            until_complete=True,
            chunk_iterations=4,
            max_total_iterations=24,
        )
        result = {
            "status": "completed",
            "project_root": Path("/tmp/workspaces/projects/interactive-run"),
            "mission_state_path": Path("/tmp/workspaces/runs/deeploop/missions/interactive-run/mission_state.json"),
        }

        with (
            patch("deeploop.cli.run_project.run_project_until_complete", return_value=result) as mock_run,
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = _run_project(args)

        self.assertEqual(exit_code, 0)
        mock_run.assert_called_once()
        self.assertEqual(json.loads(stdout.getvalue())["status"], "completed")
        self.assertEqual(stderr.getvalue(), "")

    def test_run_project_without_project_root_surfaces_provider_readiness_guidance(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = argparse.Namespace(
            project_root=None,
            idea="Find a good starter path.",
            mission_id="interactive-run",
            force=False,
            until_complete=True,
            chunk_iterations=4,
            max_total_iterations=24,
        )
        provider_result = {
            "status": "provider-readiness-required",
            "project_root": Path("/workspaces/projects/interactive-run"),
            "config_path": Path("/workspaces/scratch/interactive-run.yaml"),
            "provider_readiness": {
                "status": "action-required",
                "provider_family": "copilot-cli",
                "selection_profile": "control-plane-copilot-cli",
                "summary": "Machine-level provider setup is incomplete for `copilot-cli`.",
                "failed_checks": [
                    {
                        "kind": "required-tool",
                        "name": "copilot",
                        "message": "not found on PATH",
                    }
                ],
                "next_step": "Install the Copilot CLI and complete its machine authentication on this machine.",
                "resume_command": "deeploop run --project-root /workspaces/projects/interactive-run --mission-id interactive-run --chunk-iterations 4 --max-total-iterations 12 --until-complete",
                "recheck_command": "deeploop provider-ready --selection-profile control-plane-copilot-cli",
            },
        }

        with patch("deeploop.cli.run_project.run_project_until_complete", return_value=provider_result):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = _run_project(args)

        self.assertEqual(exit_code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "provider-readiness-required")
        self.assertIn("required provider setup is not ready yet", stderr.getvalue())
        self.assertIn("copilot-cli", stderr.getvalue())
        self.assertIn("Install the Copilot CLI", stderr.getvalue())

    def test_run_project_without_project_root_reports_usage_when_no_idea(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = argparse.Namespace(
            project_root=None,
            idea=None,
            mission_id=None,
            force=False,
            until_complete=True,
            chunk_iterations=4,
            max_total_iterations=24,
        )

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = _run_project(args)

        self.assertEqual(exit_code, 2)
        self.assertIn("Usage: deeploop run --idea", stdout.getvalue())
        self.assertIn("--project-root", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_run_project_help_explains_until_complete_and_manual_flow(self) -> None:
        parser = argparse.ArgumentParser()
        _add_run_args(parser)

        help_text = parser.format_help()
        normalized_help = " ".join(help_text.split())

        self.assertIn("--idea", normalized_help)
        self.assertIn("deeploop init", normalized_help)
        self.assertIn("deeploop start", normalized_help)
        self.assertIn("deeploop status", normalized_help)
        self.assertIn("deeploop inbox", normalized_help)
        self.assertIn("deeploop resume", normalized_help)
        self.assertIn("--mission-state <mission-state.json>", normalized_help)

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
                max_total_iterations=24,
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

    def test_run_project_until_complete_stops_for_blocked_mission_readiness(self) -> None:
        project_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "blocked-readiness"
        shutil.rmtree(project_root, ignore_errors=True)
        project_root.mkdir(parents=True, exist_ok=True)
        mission_root = project_root / "mission-root"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state_path.write_text(
            json.dumps(
                {
                    "mission_contract": {
                        "readiness": {
                            "status": "blocked",
                            "launch_recommendation": "stop-for-operator-input",
                        },
                        "follow_up_questions": [
                            "Where is the dataset located, or how should DeepLoop obtain access to it?",
                        ],
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        summary_path = mission_root / "mission_summary.md"
        summary_path.write_text("# Mission summary\n", encoding="utf-8")

        with (
            patch("deeploop.mission.project_runner.initialize_mission_from_project_root") as mock_init,
            patch("deeploop.mission.project_runner.run_mission") as mock_run_mission,
        ):
            mock_init.return_value = {
                "mission_root": mission_root,
                "state_path": mission_state_path,
                "summary_path": summary_path,
            }

            result = run_project_until_complete(project_root, chunk_iterations=3, max_total_iterations=12)

        self.assertEqual(result["status"], "mission-readiness-required")
        self.assertEqual(result["mission_state_path"], mission_state_path)
        self.assertEqual(result["mission_summary_path"], summary_path)
        self.assertEqual(
            result["follow_up_questions"],
            ["Where is the dataset located, or how should DeepLoop obtain access to it?"],
        )
        mock_run_mission.assert_not_called()

    def test_run_config_until_complete_stops_for_blocked_mission_readiness(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "blocked-config-readiness"
        shutil.rmtree(test_root, ignore_errors=True)
        test_root.mkdir(parents=True, exist_ok=True)
        config_path = test_root / "mission.yaml"
        config_path.write_text("mission:\n  target_repo: /repo/demo\n", encoding="utf-8")
        mission_root = test_root / "mission-root"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state_path.write_text(
            json.dumps(
                {
                    "target_repo": "/repo/demo",
                    "mission_contract": {
                        "readiness": {
                            "status": "blocked",
                            "launch_recommendation": "stop-for-operator-input",
                        },
                        "follow_up_questions": [
                            "Where is the dataset located, or how should DeepLoop obtain access to it?",
                        ],
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        summary_path = mission_root / "mission_summary.md"
        summary_path.write_text("# Mission summary\n", encoding="utf-8")

        with (
            patch("deeploop.mission.project_runner.initialize_mission") as mock_init,
            patch("deeploop.mission.project_runner.run_mission") as mock_run_mission,
        ):
            mock_init.return_value = {
                "mission_root": mission_root,
                "state_path": mission_state_path,
                "summary_path": summary_path,
            }

            result = run_config_until_complete(config_path, chunk_iterations=3, max_total_iterations=12)

        self.assertEqual(result["status"], "mission-readiness-required")
        self.assertEqual(result["mission_state_path"], mission_state_path)
        self.assertEqual(result["mission_summary_path"], summary_path)
        mock_run_mission.assert_not_called()

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

    def test_run_project_until_complete_tracks_existing_state_and_repeated_resumes(self) -> None:
        project_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "resume-stress"
        shutil.rmtree(project_root, ignore_errors=True)
        project_root.mkdir(parents=True, exist_ok=True)
        mission_root = project_root / "mission-root"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state_path.write_text(
            json.dumps(
                {
                    "mission_id": "resume-stress-mission",
                    "current_phase": "execution",
                    "status": "paused",
                    "mission_runtime": {
                        "status": "paused",
                        "iterations_completed": 5,
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

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
                {"status": "max-iterations", "iterations_completed": 6},
                {"status": "blocked", "iterations_completed": 8},
                {"status": "completed", "iterations_completed": 10},
            ]
            mock_snapshot.side_effect = [
                {"operator_console": {"requires_action": False}},
                {
                    "operator_console": {
                        "requires_action": True,
                        "gate_class": "soft-gate",
                        "resume_policy": "resume-optional",
                    }
                },
                {"operator_console": {"requires_action": False}},
            ]

            result = run_project_until_complete(project_root, chunk_iterations=2, max_total_iterations=12)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["runtime_passes"], 3)
        self.assertEqual(
            result["resume_summary"],
            {
                "resumed_existing_mission": True,
                "initial_runtime_status": "paused",
                "initial_iterations_completed": 5,
                "bounded_resume_passes": 2,
                "soft_recovery_resume_passes": 1,
            },
        )
        self.assertEqual(mock_run_mission.call_args_list[0].kwargs["max_iterations"], 2)
        self.assertEqual(mock_run_mission.call_args_list[1].kwargs["max_iterations"], 8)
        self.assertEqual(mock_run_mission.call_args_list[2].kwargs["max_iterations"], 10)

    def test_noncompleted_summary_lines_include_resume_context(self) -> None:
        lines = _noncompleted_summary_lines(
            {
                "status": "max-total-iterations",
                "mission_state_path": Path("/repo/demo/.deeploop/mission_state.json"),
                "snapshot": {"operator_console": {"requires_action": False}},
                "resume_summary": {
                    "resumed_existing_mission": True,
                    "initial_runtime_status": "paused",
                    "initial_iterations_completed": 5,
                    "bounded_resume_passes": 2,
                    "soft_recovery_resume_passes": 1,
                },
            }
        )

        rendered = "\n".join(lines)
        self.assertIn("reused prior mission state (5 recorded iteration(s), status `paused`)", rendered)
        self.assertIn("auto-resumed 2 bounded pass(es)", rendered)
        self.assertIn("1 via soft-gate recovery", rendered)

    def test_noncompleted_summary_lines_include_bootstrap_repair_guidance(self) -> None:
        lines = _noncompleted_summary_lines(
            {
                "status": "bootstrap-repair-required",
                "bootstrap_repair": {
                    "status": "required",
                    "reason": "missing-bootstrap-contract",
                    "summary": "Project root is missing project-facts.yaml.",
                    "recommendation": "Create project-facts.yaml and rerun deeploop run.",
                    "starter_scaffold_path": "/repo/demo/starter/project-facts.yaml",
                    "starter_target_path": "/repo/demo/project-facts.yaml",
                    "actions": ["Copy the starter scaffold into place."],
                },
            }
        )

        rendered = "\n".join(lines)
        self.assertIn("DeepLoop could not bootstrap this project root yet.", rendered)
        self.assertIn("missing-bootstrap-contract", rendered)
        self.assertIn("/repo/demo/project-facts.yaml", rendered)

    def test_noncompleted_summary_lines_include_mission_readiness_guidance(self) -> None:
        lines = _noncompleted_summary_lines(
            {
                "status": "mission-readiness-required",
                "mission_state_path": Path("/repo/demo/.deeploop/mission_state.json"),
                "mission_summary_path": Path("/repo/demo/.deeploop/mission_summary.md"),
                "readiness": {
                    "status": "blocked",
                    "launch_recommendation": "stop-for-operator-input",
                },
                "follow_up_questions": [
                    "Where is the dataset located, or how should DeepLoop obtain access to it?",
                ],
            }
        )

        rendered = "\n".join(lines)
        self.assertIn("mission contract still needs operator input", rendered)
        self.assertIn("stop-for-operator-input", rendered)
        self.assertIn("Where is the dataset located", rendered)
        self.assertIn("mission_summary.md", rendered)

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
                        "human_inputs": {
                            "dataset_access": "Use a documented benchmark slice with a holdout split.",
                            "prediction_target": "quality_delta_vs_baseline",
                        },
                        "enable_tree_search": False,
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
            "experiment-design": ["manifest.json", "execution_profile.json", "resource_tier.json"],
            "execution": ["run_manifest.json", "predictions.jsonl", "metrics.json", "runtime_report.json"],
            "critique": ["critique_evidence.json", "confound_notes", "next-step recommendation"],
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
        after_paths = sorted(
            str(path.relative_to(project_root))
            for path in project_root.rglob("*")
            if path.is_file()
        )
        # Filter runtime-only artifacts that are generated during the run
        non_runtime_paths = sorted(
            p for p in after_paths
            if not p.startswith("research_report/")
        )
        self.assertEqual(
            non_runtime_paths,
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
                        "human_inputs": {
                            "dataset_access": "Use a documented benchmark slice with a holdout split.",
                            "prediction_target": "quality_delta_vs_baseline",
                        },
                        "enable_tree_search": False,
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
            "experiment-design": ["manifest.json", "execution_profile.json", "resource_tier.json"],
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

    def test_initialize_mission_from_project_root_returns_repair_result_without_initializing(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_runner" / "repair-required-init"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        test_root.mkdir(parents=True, exist_ok=True)

        with (
            patch("deeploop.mission.project_runner.initialize_mission") as mock_init_mission,
            patch("deeploop.mission.project_bootstrap.build_mission_config_from_project_root") as mock_build_config,
        ):
            mock_build_config.return_value = {
                "mission": {"id": "repair-required-mission"},
                "bootstrap_repair": {
                    "status": "required",
                    "reason": "missing-bootstrap-contract",
                    "summary": "Project root needs project-facts.yaml.",
                    "recommendation": "Create project-facts.yaml.",
                },
            }
            result = initialize_mission_from_project_root(test_root, force=False)

        mock_init_mission.assert_not_called()
        self.assertEqual(result["status"], "bootstrap-repair-required")

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
