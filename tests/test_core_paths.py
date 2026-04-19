from __future__ import annotations

import importlib
import os
import sys
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
        module = importlib.reload(core_paths)

        self.assertEqual(module.DEFAULT_WORKSPACE_ROOT, Path.home() / "workspaces")
        self.assertEqual(module.WORKSPACE_ROOT, module.DEFAULT_WORKSPACE_ROOT)

    def test_workspace_root_can_be_overridden_via_environment(self) -> None:
        override_root = REPO_ROOT / "reports" / "test-fixtures" / "workspace-root"

        with patch.dict(
            os.environ,
            {core_paths.WORKSPACE_ROOT_ENV_VAR: str(override_root)},
            clear=False,
        ):
            module = importlib.reload(core_paths)

        self.assertEqual(module.WORKSPACE_ROOT, override_root.resolve())
        self.assertEqual(module.RUNS_DIR, override_root.resolve() / "runs" / "deeploop")
