from __future__ import annotations

import importlib
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.autonomy.gate_taxonomy import DEFAULT_GATES_PATH, resolve_gate_contract
from deeploop.autonomy.mission_autonomy import build_outer_loop_contract
from deeploop.autonomy.gate_taxonomy import DEFAULT_OPERATING_MODE
from deeploop.autonomy.operator_inbox import build_operator_inbox_contract
from deeploop.artifacts.artifact_packager import package_mission_artifacts
from deeploop.artifacts.release_automation import build_release_candidate_review
from deeploop.core.ledger import now_utc
from deeploop.core.paths import REPO_ROOT as PACKAGE_REPO_ROOT
from deeploop.mission.mission_management import build_parser
from deeploop.mission.mission_monitor import build_mission_snapshot
from deeploop.mission.mission_runtime import run_mission
from deeploop.mission.mission_scheduler import load_mission_scheduler_config, run_mission_scheduler
from deeploop.platform.contracts import load_platform_expansion_contract
from deeploop.research.confound_guard import evaluate_confound_guard
from deeploop.research.indexed_memory import build_research_memory_contract, retrieve_research_memory
from deeploop.research.sanity_gates import evaluate_research_sanity
from deeploop.runtime.provider_launcher import run_provider_prompt
from deeploop.runtime.mission_executor_registry import run_mission_action
from deeploop.runtime.recursive_agent_runtime import run_recursive_agent_loop
from deeploop.runtime.stage_kernels import run_stage_from_config

REMOVED_SHIMS = [
    "adaptation_training_runtime.py",
    "artifact_packager.py",
    "confound_guard.py",
    "copilot_launcher.py",
    "gate_taxonomy.py",
    "ledger.py",
    "mission_autonomy.py",
    "mission_decision_engine.py",
    "mission_executor_registry.py",
    "mission_management.py",
    "mission_memory.py",
    "mission_monitor.py",
    "mission_package.py",
    "mission_runtime.py",
    "novelty_refresh.py",
    "operator_inbox.py",
    "orchestrator.py",
    "paths.py",
    "recursive_agent_runtime.py",
    "runtime_recovery.py",
    "sandbox.py",
    "sanity_gates.py",
    "self_correction.py",
    "self_healing_runtime.py",
    "self_optimization.py",
    "stage_kernels.py",
    "statistical_rigor.py",
    "utility_scorer.py",
]


class PackageStructureTests(unittest.TestCase):
    def test_pyproject_public_metadata_and_console_scripts_are_complete(self) -> None:
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = pyproject["project"]

        self.assertTrue(project.get("authors"))
        self.assertEqual(project["authors"][0]["name"], "DeepLoop maintainers")

        urls = project.get("urls", {})
        for key in ("Homepage", "Documentation", "Issues", "Source", "Changelog"):
            self.assertTrue(urls.get(key), key)

        scripts = project.get("scripts", {})
        expected_scripts = {
            "deeploop": "deeploop.mission.mission_management:main",
            "deeploop-init-mission": "deeploop.cli.init_mission:main",
            "deeploop-run-project": "deeploop.cli.run_project:main",
            "deeploop-package-mission": "deeploop.cli.package_mission:main",
            "deeploop-analyze": "deeploop.cli.analyze:main",
        }
        self.assertEqual(scripts, expected_scripts)

        for target in scripts.values():
            module_name, attr_name = target.split(":")
            exported = getattr(importlib.import_module(module_name), attr_name)
            self.assertTrue(callable(exported), target)

    def test_wheel_contains_required_runtime_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "wheel",
                        str(REPO_ROOT),
                        "--no-deps",
                        "--no-build-isolation",
                        "--wheel-dir",
                        tmpdir,
                    ],
                    cwd=REPO_ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                self.fail((exc.stdout or "") + (exc.stderr or ""))
            wheel_paths = list(Path(tmpdir).glob("deeploop-*.whl"))
            self.assertEqual(len(wheel_paths), 1, [path.name for path in wheel_paths])
            wheel_path = wheel_paths[0]
            with ZipFile(wheel_path) as wheel:
                wheel_files = set(wheel.namelist())

        expected_assets = {
            "deeploop/_assets/configs/autonomy/mission-outer-loop.yaml",
            "deeploop/_assets/configs/runtime/recursive-agent-runtime.yaml",
            "deeploop/_assets/examples/translation-budget-ladder/project-facts.yaml",
            "deeploop/_assets/examples/starter-general-research/project-facts.yaml",
            "deeploop/_assets/schemas/mission-action.schema.json",
            "deeploop/_assets/scripts/runtime/invoke_provider_prompt.py",
            "deeploop/_assets/scripts/mission/run_mission.py",
            "deeploop/_assets/scripts/mission/manage_mission.py",
        }
        self.assertTrue(expected_assets.issubset(wheel_files), expected_assets - wheel_files)

    def test_packaged_invoke_provider_prompt_bootstraps_package_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wheel_dir = Path(tmpdir) / "wheelhouse"
            site_packages = Path(tmpdir) / "site-packages"
            wheel_dir.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "wheel",
                        str(REPO_ROOT),
                        "--no-deps",
                        "--no-build-isolation",
                        "--wheel-dir",
                        str(wheel_dir),
                    ],
                    cwd=REPO_ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                self.fail((exc.stdout or "") + (exc.stderr or ""))

            wheel_paths = list(wheel_dir.glob("deeploop-*.whl"))
            self.assertEqual(len(wheel_paths), 1, [path.name for path in wheel_paths])
            with ZipFile(wheel_paths[0]) as wheel:
                wheel.extractall(site_packages)

            packaged_script = site_packages / "deeploop" / "_assets" / "scripts" / "runtime" / "invoke_provider_prompt.py"
            self.assertTrue(packaged_script.exists(), packaged_script)

            completed = subprocess.run(
                [sys.executable, str(packaged_script), "--help"],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("--prompt-file", completed.stdout)

    def test_release_hygiene_ignores_generated_build_artifacts(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("site/", "*.egg-info/", "docs/_build/", "build/", "dist/", ".vscode/"):
            self.assertIn(pattern, gitignore)

        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("scripts/mission/run_mission.py", makefile)
        self.assertIn("scripts/mission/package_mission.py", makefile)
        self.assertNotIn("advance_asym_mission.py", makefile)
        self.assertNotIn("scripts/mission/meta_eval.py", makefile)

    def test_canonical_packages_expose_expected_entrypoints(self) -> None:
        self.assertEqual(PACKAGE_REPO_ROOT, REPO_ROOT)
        self.assertEqual(DEFAULT_OPERATING_MODE, "sandboxed-yolo")
        self.assertRegex(now_utc(), r"\+00:00$")
        self.assertTrue(DEFAULT_GATES_PATH.exists())

        mission_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "package_structure" / "mission"
        self.assertEqual(resolve_gate_contract(mode="sandboxed-yolo")["mode"], "sandboxed-yolo")
        self.assertEqual(load_platform_expansion_contract()["version"], 1)
        inbox_contract = build_operator_inbox_contract(mission_root)
        self.assertEqual(inbox_contract["operator_request_log_path"], str((mission_root / "mission_operator_requests.jsonl").resolve()))
        self.assertEqual(inbox_contract["current_operator_request_path"], str((mission_root / "current_operator_request.json").resolve()))
        self.assertEqual(build_outer_loop_contract(mission_root, mode="sandboxed-yolo")["mode"], "sandboxed-yolo")

        self.assertTrue(callable(build_parser))
        self.assertTrue(callable(build_mission_snapshot))
        self.assertTrue(callable(run_mission))
        self.assertTrue(callable(build_research_memory_contract))
        self.assertTrue(callable(retrieve_research_memory))
        self.assertTrue(callable(load_mission_scheduler_config))
        self.assertTrue(callable(run_mission_scheduler))
        self.assertTrue(callable(run_mission_action))
        self.assertTrue(callable(run_recursive_agent_loop))
        self.assertTrue(callable(run_stage_from_config))
        self.assertTrue(callable(run_provider_prompt))
        self.assertTrue(callable(evaluate_research_sanity))
        self.assertTrue(callable(evaluate_confound_guard))
        self.assertTrue(callable(package_mission_artifacts))
        self.assertTrue(callable(build_release_candidate_review))

    def test_flat_compatibility_shims_are_removed(self) -> None:
        package_root = SRC_ROOT / "deeploop"
        for filename in REMOVED_SHIMS:
            self.assertFalse((package_root / filename).exists(), filename)


if __name__ == "__main__":
    unittest.main()
