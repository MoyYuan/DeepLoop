from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import deeploop.core.paths as core_paths


class CorePathsTests(unittest.TestCase):
    def tearDown(self) -> None:
        importlib.reload(core_paths)

    def test_workspace_root_defaults_to_documented_home_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("pathlib.Path.home", return_value=Path(tmpdir)):
                with patch.dict(os.environ, {}, clear=True):
                    module = importlib.reload(core_paths)

        self.assertEqual(module.DEFAULT_WORKSPACE_ROOT, Path(tmpdir) / "workspaces")
        self.assertEqual(module.WORKSPACE_ROOT, module.DEFAULT_WORKSPACE_ROOT)

    def test_workspace_root_prefers_existing_cased_workspace_when_unambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            (home / "Workspaces").mkdir()
            with patch("pathlib.Path.home", return_value=home):
                with patch.dict(os.environ, {}, clear=True):
                    module = importlib.reload(core_paths)

        self.assertEqual(module.DEFAULT_WORKSPACE_ROOT, home / "Workspaces")
        self.assertEqual(module.WORKSPACE_ROOT, home / "Workspaces")

    def test_workspace_root_can_be_overridden_via_environment(self) -> None:
        override_root = REPO_ROOT / "reports" / "test-fixtures" / "workspace-root"

        with patch.dict(
            os.environ,
            {core_paths.WORKSPACE_ROOT_ENV_VAR: str(override_root)},
            clear=True,
        ):
            module = importlib.reload(core_paths)

        self.assertEqual(module.WORKSPACE_ROOT, override_root.resolve())
        self.assertEqual(module.RUNS_DIR, override_root.resolve() / "runs" / "deeploop")

    def test_workspace_path_resolves_workspace_uri_against_configured_root(self) -> None:
        override_root = REPO_ROOT / "reports" / "test-fixtures" / "workspace-root"

        with patch.dict(
            os.environ,
            {core_paths.WORKSPACE_ROOT_ENV_VAR: str(override_root)},
            clear=True,
        ):
            module = importlib.reload(core_paths)

        self.assertEqual(
            module.resolve_workspace_path("workspace://runs/deeploop/packages"),
            override_root.resolve() / "runs" / "deeploop" / "packages",
        )

    def test_runs_root_can_be_overridden_independently_of_workspace_root(self) -> None:
        workspace_root = REPO_ROOT / "reports" / "test-fixtures" / "workspace-root"
        runs_root = REPO_ROOT / "reports" / "test-fixtures" / "isolated-runs-root"

        with patch.dict(
            os.environ,
            {
                core_paths.WORKSPACE_ROOT_ENV_VAR: str(workspace_root),
                core_paths.RUNS_ROOT_ENV_VAR: str(runs_root),
            },
            clear=False,
        ):
            module = importlib.reload(core_paths)

        self.assertEqual(module.WORKSPACE_ROOT, workspace_root.resolve())
        self.assertEqual(module.RUNS_DIR, runs_root.resolve())
        self.assertEqual(module.PACKAGES_DIR, runs_root.resolve() / "packages")
        self.assertEqual(module.RESEARCH_MEMORY_DIR, runs_root.resolve() / "ledger" / "research_memory")

    def test_workspace_root_diagnostics_warns_for_case_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            (home / "Workspaces").mkdir()
            (home / "workspaces").mkdir()
            project_root = home / "Workspaces" / "example-project"
            with patch("pathlib.Path.home", return_value=home):
                with patch.dict(os.environ, {}, clear=True):
                    module = importlib.reload(core_paths)
                    diagnostics = module.workspace_root_diagnostics(project_root)

        joined = "\n".join(diagnostics)
        self.assertIn("Both", joined)
        self.assertNotIn("outside DeepLoop workspace root", joined)
