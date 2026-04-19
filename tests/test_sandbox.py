from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.sandbox import build_sandbox_spec


class SandboxTests(unittest.TestCase):
    def test_build_sandbox_spec_reset_clears_role_inputs_and_outputs(self) -> None:
        mission_id = "sandbox-reset-test"
        target_repo = REPO_ROOT
        sandbox = build_sandbox_spec(mission_id, "planner", target_repo)
        sandbox_root = Path(sandbox["sandbox_root"])
        self.addCleanup(lambda: shutil.rmtree(sandbox_root.parent, ignore_errors=True))
        stale_input = Path(sandbox["inputs_dir"]) / "stale.txt"
        stale_output = Path(sandbox["outputs_dir"]) / "stale.txt"
        stale_input.write_text("old\n", encoding="utf-8")
        stale_output.write_text("old\n", encoding="utf-8")

        reset_sandbox = build_sandbox_spec(mission_id, "planner", target_repo, reset=True)

        self.assertEqual(Path(reset_sandbox["sandbox_root"]), sandbox_root)
        self.assertFalse(stale_input.exists())
        self.assertFalse(stale_output.exists())
        self.assertTrue(Path(reset_sandbox["inputs_dir"]).exists())
        self.assertTrue(Path(reset_sandbox["outputs_dir"]).exists())


if __name__ == "__main__":
    unittest.main()
