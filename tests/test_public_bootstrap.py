from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import MISSIONS_DIR
from deeploop.mission.project_bootstrap import build_mission_config_from_project_root
from deeploop.mission.project_runner import run_project_until_complete

EXAMPLE_ROOT = REPO_ROOT / "examples" / "translation-budget-ladder"


class PublicBootstrapTests(unittest.TestCase):
    def _copy_example(self, test_root: Path) -> Path:
        project_root = test_root / "translation-budget-ladder"
        shutil.copytree(EXAMPLE_ROOT, project_root)
        return project_root

    def test_public_plain_folder_fixture_bootstraps_with_project_root_cli(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "public_bootstrap" / "cli"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        project_root = self._copy_example(test_root)

        expected_config = build_mission_config_from_project_root(project_root)
        mission_root = MISSIONS_DIR / expected_config["mission"]["id"]
        shutil.rmtree(mission_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(mission_root, ignore_errors=True))

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/mission/init_mission.py",
                "--project-root",
                str(project_root),
                "--force",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("bootstrapped mission config from project folder", completed.stdout)
        state_path = mission_root / "mission_state.json"
        self.assertTrue(state_path.exists(), f"missing mission state: {state_path}")
        mission_state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["project_contract"]["status"], "plain-artifacts")
        self.assertEqual(mission_state["target_repo"], str(project_root.resolve()))
        self.assertIn(mission_state.get("operator_inbox", {}).get("status"), {None, "clear"})
        self.assertFalse((project_root / ".deeploop").exists())

    def test_public_bootstrap_preflight_reports_supported_environment(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/public_bootstrap_preflight.py",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("python_version: PASS", completed.stdout)
        self.assertIn("operating_system: PASS", completed.stdout)
        self.assertIn("workspace_root: PASS", completed.stdout)
        self.assertIn("external_dirs: PASS", completed.stdout)

    def test_make_setup_creates_all_dirs_needed_for_fresh_home_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fresh_home = Path(tmpdir) / "home"
            fresh_home.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env["HOME"] = str(fresh_home)

            setup = subprocess.run(
                [
                    "make",
                    f"PYTHON={sys.executable}",
                    "setup",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/public_bootstrap_preflight.py",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("workspace_root: PASS", completed.stdout)
        self.assertIn("external_dirs: PASS", completed.stdout)

    @patch("deeploop.runtime.mission_executor_registry.package_mission_artifacts")
    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_public_plain_folder_fixture_runs_until_complete_without_mutating_project(
        self,
        mock_run_recursive_agent_loop,
        mock_package_mission_artifacts,
    ) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "public_bootstrap" / "run_project"
        shutil.rmtree(test_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        project_root = self._copy_example(test_root)

        before_paths = sorted(
            str(path.relative_to(project_root))
            for path in project_root.rglob("*")
            if path.is_file()
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
                        "mission_action_id": f"public-bootstrap-{phase}",
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
            mission_id="public-bootstrap-example-mission",
            force=True,
            chunk_iterations=4,
            max_total_iterations=32,
        )
        self.addCleanup(lambda: shutil.rmtree(Path(result["mission_root"]), ignore_errors=True))

        mission_state = json.loads(Path(result["mission_state_path"]).read_text(encoding="utf-8"))
        after_paths = sorted(
            str(path.relative_to(project_root))
            for path in project_root.rglob("*")
            if path.is_file()
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(mission_state["status"], "completed")
        self.assertEqual(mission_state["current_phase"], "final-report")
        self.assertEqual(mission_state["project_contract"]["status"], "plain-artifacts")
        self.assertEqual(mission_state["operator_inbox"]["status"], "clear")
        self.assertFalse((project_root / ".deeploop").exists())
        self.assertEqual(before_paths, after_paths)


if __name__ == "__main__":
    unittest.main()
