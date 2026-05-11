from __future__ import annotations

import importlib.util
import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
MODULE_PATH = REPO_ROOT / "scripts" / "release" / "docker_validation.py"
SPEC = importlib.util.spec_from_file_location("docker_validation", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load docker validation module from {MODULE_PATH}")
docker_validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(docker_validation)

SMOKE_MODULE_PATH = REPO_ROOT / "scripts" / "release" / "in_container_smoke.py"
SMOKE_SPEC = importlib.util.spec_from_file_location("in_container_smoke", SMOKE_MODULE_PATH)
if SMOKE_SPEC is None or SMOKE_SPEC.loader is None:
    raise RuntimeError(f"Unable to load in-container smoke module from {SMOKE_MODULE_PATH}")
in_container_smoke = importlib.util.module_from_spec(SMOKE_SPEC)
SMOKE_SPEC.loader.exec_module(in_container_smoke)


class ReleaseDockerValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "release_docker_validation"
        shutil.rmtree(self.runtime_root, ignore_errors=True)
        self.runtime_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def test_validate_dist_build_uses_artifact_stage(self) -> None:
        command = docker_validation.build_docker_build_command(
            mode="dist",
            docker_bin="docker",
            dockerfile=Path("/repo/docker/release-validation.Dockerfile"),
            image_tag="deeploop-release-validation:dist-test",
            python_image="python:3.11-slim",
            pull=False,
        )

        self.assertEqual(command[:7], [
            "docker",
            "build",
            "--file",
            "/repo/docker/release-validation.Dockerfile",
            "--target",
            "artifact-validation",
            "--tag",
        ])
        self.assertIn("deeploop-release-validation:dist-test", command)
        self.assertIn("PYTHON_IMAGE=python:3.11-slim", command)
        self.assertNotIn("--pull", command)
        self.assertEqual(command[-1], str(REPO_ROOT))

    def test_validate_pypi_build_passes_install_spec(self) -> None:
        command = docker_validation.build_docker_build_command(
            mode="pypi",
            docker_bin="docker",
            dockerfile=Path("/repo/docker/release-validation.Dockerfile"),
            image_tag="deeploop-release-validation:pypi-test",
            python_image="python:3.11-slim",
            pull=True,
            install_spec="deeploop==9.9.9",
        )

        self.assertIn("pypi-validation", command)
        self.assertIn("--pull", command)
        self.assertIn("DEEPLOOP_INSTALL_SPEC=deeploop==9.9.9", command)

    def test_default_install_spec_tracks_project_version(self) -> None:
        version = docker_validation.load_project_version()
        self.assertEqual(docker_validation.default_install_spec(), f"deeploop=={version}")
        self.assertEqual(
            docker_validation.default_image_tag("dist"),
            f"deeploop-release-validation:dist-{version}",
        )
        self.assertEqual(
            docker_validation.default_image_tag("pypi", install_spec=f"deeploop=={version}"),
            f"deeploop-release-validation:pypi-{version}",
        )

    def test_zero_start_smoke_materializes_selected_starter_and_stops_for_provider_setup(self) -> None:
        mission_id = "release-docker-validation-zero-start"
        self.addCleanup(
            lambda: in_container_smoke._cleanup_mission_artifacts(mission_id, remove_discovery_config=True)
        )

        result = in_container_smoke._run_zero_start_bundled_starter_provider_gate_smoke(
            mission_id=mission_id,
        )
        self.addCleanup(lambda: shutil.rmtree(Path(result["project_root"]), ignore_errors=True))

        self.assertEqual(result["workflow"], "zero-start-bundled-starter")
        self.assertEqual(result["starter_project"], "translation-budget-ladder")
        self.assertEqual(result["provider_family"], "copilot-cli")
        self.assertIn("Copilot CLI", result["next_step"])
        self.assertIn("deeploop run --project-root", result["resume_command"])
        self.assertEqual(
            result["recheck_command"],
            "deeploop provider-ready --selection-profile control-plane-copilot-cli",
        )
        self.assertTrue(Path(result["project_root"]).joinpath("docs", "budget-and-baselines.md").exists())
        self.assertTrue(Path(result["discovery_config_path"]).exists())

    def test_discovery_first_smoke_tracks_defaults_without_mutation(self) -> None:
        mission_id = "release-docker-validation-discovery"
        self.addCleanup(
            lambda: in_container_smoke._cleanup_mission_artifacts(mission_id, remove_discovery_config=True)
        )

        result = in_container_smoke._run_discovery_first_plain_folder_smoke(
            REPO_ROOT,
            self.runtime_root,
            mission_id=mission_id,
        )

        self.assertEqual(result["workflow"], "forecast-rough-notes-discovery")
        self.assertEqual(result["mission_status"], "initialized")
        self.assertEqual(result["readiness_status"], "ready-with-defaults")
        self.assertEqual(result["launch_recommendation"], "launch-with-disclosed-defaults")
        self.assertEqual(result["discovery_mode"], "interactive")
        self.assertTrue(Path(result["mission_state_path"]).exists())
        self.assertTrue(Path(result["discovery_config_path"]).exists())

    def test_partial_project_folder_repair_smoke_reports_contract_gaps(self) -> None:
        mission_id = "release-docker-validation-repair"
        self.addCleanup(lambda: in_container_smoke._cleanup_mission_artifacts(mission_id))

        result = in_container_smoke._run_partial_project_folder_repair_smoke(
            REPO_ROOT,
            self.runtime_root,
            mission_id=mission_id,
        )

        self.assertEqual(result["workflow"], "partial-project-folder-repair")
        self.assertEqual(result["repair_exit_code"], 1)
        self.assertEqual(result["repair_signal"], "missing-bootstrap-contract")
        self.assertTrue(Path(result["starter_scaffold_path"]).exists())
        self.assertTrue(str(result["expected_target_path"]).endswith("partial-project-folder/project-facts.yaml"))

    def test_operator_handoff_surface_smoke_renders_status_inbox_resume_loop(self) -> None:
        mission_id = "release-docker-validation-operator-handoff"
        self.addCleanup(lambda: in_container_smoke._cleanup_mission_artifacts(mission_id))

        result = in_container_smoke._run_operator_handoff_surface_smoke(
            mission_id=mission_id,
        )

        self.assertEqual(result["workflow"], "operator-handoff-surface")
        self.assertTrue(Path(result["mission_state_path"]).exists())
        self.assertEqual(
            result["continue_command"],
            f"deeploop resume --mission-state {result['mission_state_path']}",
        )


if __name__ == "__main__":
    unittest.main()
