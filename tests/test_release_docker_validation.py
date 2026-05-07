from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "release" / "docker_validation.py"
SPEC = importlib.util.spec_from_file_location("docker_validation", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load docker validation module from {MODULE_PATH}")
docker_validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(docker_validation)


class ReleaseDockerValidationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
