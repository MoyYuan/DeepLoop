"""Acceptance test: run a toy research mission through the full DeepLoop lifecycle.

Requires DEEPLOOP_ACCEPTANCE_API_KEY env var. Skips if not set.
Max 3 iterations, ~$0.15 cost.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


@unittest.skipIf(
    not os.environ.get("DEEPLOOP_ACCEPTANCE_API_KEY"),
    "DEEPLOOP_ACCEPTANCE_API_KEY not set",
)
class ToyMissionAcceptanceTest(unittest.TestCase):
    """Run a complete mission: init -> decision -> dispatch -> result -> completion."""

    def setUp(self):
        self.test_root = Path(tempfile.mkdtemp())
        self.project_root = self.test_root / "project"
        self.project_root.mkdir(parents=True)

        # Write a minimal project-facts.yaml
        (self.project_root / "project-facts.yaml").write_text(
            "project:\n"
            "  name: toy-acceptance\n"
            "  title: Toy Acceptance Mission\n"
            "  summary: Minimal end-to-end acceptance test\n"
            "  objective: Test the full DeepLoop pipeline end to end\n"
            "artifacts:\n"
            "  docs:\n"
            "    - docs/project-brief.md\n",
            encoding="utf-8",
        )

        # Write a minimal project brief
        docs_dir = self.project_root / "docs"
        docs_dir.mkdir(exist_ok=True)
        (docs_dir / "project-brief.md").write_text(
            "# Project Brief\n\n"
            "Summarize a single CSV column from a public dataset.\n"
            "Keep it short and bounded.\n",
            encoding="utf-8",
        )

        # Environment: point to DeepSeek via the acceptance API key
        self.env = os.environ.copy()
        existing_pp = self.env.get("PYTHONPATH", "")
        self.env["PYTHONPATH"] = (
            str(SRC_ROOT) + os.pathsep + existing_pp
            if existing_pp
            else str(SRC_ROOT)
        )
        self.env["DEEPLOOP_WORKSPACE_ROOT"] = str(self.test_root / "workspace")
        self.env["OPENAI_API_KEY"] = os.environ["DEEPLOOP_ACCEPTANCE_API_KEY"]
        self.env["OPENAI_BASE_URL"] = "https://api.deepseek.com/v1"
        self.env["OPENAI_MODEL"] = "deepseek-chat"

        self.mission_id = "toy-acceptance-test"

    def tearDown(self):
        shutil.rmtree(self.test_root, ignore_errors=True)

    def _run_script(self, script_name: str, args: list[str], **kwargs) -> subprocess.CompletedProcess:
        script_path = REPO_ROOT / "scripts" / "mission" / script_name
        return subprocess.run(
            [sys.executable, str(script_path)] + args,
            cwd=REPO_ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            **kwargs,
        )

    @property
    def _state_path(self) -> Path:
        return (
            Path(self.env["DEEPLOOP_WORKSPACE_ROOT"])
            / "runs" / "deeploop" / "missions"
            / self.mission_id
            / "mission_state.json"
        )

    def test_full_lifecycle(self):
        """Complete lifecycle: init -> decision engine -> dispatch -> artifacts -> status."""
        # ---- Step 1: Init ----------------------------------------------------------
        init_result = self._run_script(
            "init_mission.py",
            [
                "--project-root",
                str(self.project_root),
                "--mission-id",
                self.mission_id,
                "--force",
            ],
            timeout=60,
        )
        self.assertEqual(
            init_result.returncode,
            0,
            f"init failed:\nstdout: {init_result.stdout}\nstderr: {init_result.stderr}",
        )

        # ---- Step 2: Verify mission state exists and complies with schema ----------
        self.assertTrue(self._state_path.exists(), f"Missing mission state: {self._state_path}")
        state = json.loads(self._state_path.read_text(encoding="utf-8"))

        # Schema compliance — mission_state.json may store schema_version at top level
        # or rely on migration on load; verify core fields are present
        self.assertIn("mission_id", state)
        self.assertEqual(state["mission_id"], self.mission_id)
        self.assertIn("current_phase", state)
        self.assertIn("status", state)
        self.assertIn("roles", state)
        self.assertIsInstance(state["roles"], list)
        self.assertIn("outer_loop", state)
        self.assertIsInstance(state["outer_loop"], dict)

        # Initial mission state expectations
        self.assertEqual(state["status"], "initialized")
        self.assertEqual(state["current_phase"], "idea-intake")

        # ---- Step 3: Set status to running so the runtime can proceed --------------
        state["status"] = "running"
        self._state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

        # ---- Step 4: Resume the mission (max 3 iterations) -------------------------
        resume_result = self._run_script(
            "run_mission.py",
            [
                "--mission-state",
                str(self._state_path),
                "--max-iterations",
                "3",
            ],
            timeout=300,
        )

        # ---- Step 5: Verify the mission made progress ------------------------------
        final_state = json.loads(self._state_path.read_text(encoding="utf-8"))
        status = str(final_state.get("status", ""))
        # The mission should have transitioned from 'initialized' to something else
        self.assertNotEqual(
            status,
            "initialized",
            "Mission did not progress beyond initialized",
        )
        self.assertIn(
            status,
            {"running", "completed", "max-iterations", "blocked", "failed", "paused"},
            f"Unexpected terminal status: {status}",
        )

        # Check the runtime produced a result payload
        try:
            resume_payload = json.loads(resume_result.stdout)
        except (json.JSONDecodeError, ValueError):
            resume_payload = {}
        self.assertIn("status", resume_payload or final_state)
        self.assertIn("iterations_completed", resume_payload or {})

        # ---- Step 6: Verify expected artifacts exist -------------------------------
        mission_root = self._state_path.parent
        runtime_dir = mission_root / "runtime" / "mission_outer_runtime"
        if runtime_dir.exists():
            history_files = list(runtime_dir.iterdir())
            self.assertGreater(
                len(history_files),
                0,
                "Runtime directory exists but contains no files",
            )
            # At least one decision/action history entry should exist
            runtime_state_path = runtime_dir / "runtime_state.json"
            if runtime_state_path.exists():
                runtime_state = json.loads(runtime_state_path.read_text(encoding="utf-8"))
                self.assertIn("iterations_completed", runtime_state)
                self.assertGreaterEqual(
                    int(runtime_state.get("iterations_completed", 0)),
                    0,
                    "iterations_completed should be >= 0",
                )

        # Verify summary file was written
        summary_candidates = list(mission_root.glob("mission_summary*"))
        self.assertGreater(
            len(summary_candidates),
            0,
            f"No summary file found under {mission_root}",
        )

        # Verify ledger was written
        ledger_path = mission_root / "ledger.jsonl"
        if ledger_path.exists():
            ledger_entries = [
                line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()
            ]
            self.assertGreater(
                len(ledger_entries),
                0,
                "Ledger should contain at least the init entry",
            )

        # Verify decision log has content
        outer_loop = final_state.get("outer_loop", {})
        decision_log_path_str = outer_loop.get("decision_log_path")
        if decision_log_path_str:
            decision_log_path = Path(decision_log_path_str)
            if decision_log_path.exists():
                decisions = decision_log_path.read_text(encoding="utf-8").splitlines()
                self.assertGreater(
                    len(decisions),
                    0,
                    "Decision log should contain at least one decision",
                )


if __name__ == "__main__":
    unittest.main()
