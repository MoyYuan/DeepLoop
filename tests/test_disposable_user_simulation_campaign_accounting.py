from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.testing.disposable_user_simulation import DEFAULT_MATRIX_PATH, load_disposable_user_simulation_matrix

SCRIPT_PATH = REPO_ROOT / "scripts" / "testing" / "run_disposable_user_simulation_matrix.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("run_disposable_user_simulation_matrix_script", SCRIPT_PATH)
assert _SCRIPT_SPEC is not None and _SCRIPT_SPEC.loader is not None
run_disposable_user_simulation_matrix = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(run_disposable_user_simulation_matrix)


class DisposableUserSimulationCampaignAccountingTests(unittest.TestCase):
    def test_run_scenario_failed_summary_preserves_elapsed_seconds(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        scenario = matrix.scenarios[0]
        scenario_root = REPO_ROOT / "build" / "test-disposable-user-simulation-accounting" / "failed-scenario"
        shutil.rmtree(scenario_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, scenario_root, True)

        with patch.object(run_disposable_user_simulation_matrix, "_resolve_model_artifact_mounts", return_value=[]):
            with patch.object(run_disposable_user_simulation_matrix, "_resolve_container_openai_env", return_value={}):
                with patch.object(run_disposable_user_simulation_matrix, "_start_container"):
                    with patch.object(run_disposable_user_simulation_matrix, "_stop_container"):
                        with patch.object(
                            run_disposable_user_simulation_matrix,
                            "_run_simulator_command",
                            side_effect=run_disposable_user_simulation_matrix.SimulatorCommandError(
                                "Simulator command exited 1.",
                                elapsed_seconds=12.345,
                            ),
                        ):
                            summary = run_disposable_user_simulation_matrix._run_scenario(
                                docker_bin="docker",
                                image_tag="demo:latest",
                                campaign_id="campaign-accounting",
                                scenario_root=scenario_root,
                                scenario=scenario,
                                matrix=matrix,
                                simulator_command=["python", "-c", "raise SystemExit(1)"],
                                prepare_only=False,
                            )

        payload = json.loads((scenario_root / "scenario_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["elapsed_seconds"], 12.345)
        self.assertEqual(payload["elapsed_seconds"], 12.345)
        self.assertEqual(payload["failures"], ["Simulator command exited 1."])

    def test_write_campaign_status_final_status_retains_latest_completed_phase(self) -> None:
        campaign_root = REPO_ROOT / "build" / "test-disposable-user-simulation-accounting" / "campaign-status-final"
        shutil.rmtree(campaign_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, campaign_root, True)
        phase_root = campaign_root / "scenario-a" / "artifacts" / "outer-user-simulation" / "phases" / "02-midpoint"
        phase_root.mkdir(parents=True, exist_ok=True)
        (phase_root / "phase.json").write_text(
            json.dumps({"phase_index": 2, "phase_name": "midpoint", "elapsed_seconds": 120.0}),
            encoding="utf-8",
        )

        run_disposable_user_simulation_matrix._write_campaign_status(
            campaign_root,
            campaign_id="campaign-accounting",
            scenario_ids=["scenario-a", "scenario-b"],
            scenario_summaries=[
                {"scenario_id": "scenario-a", "status": "passed"},
                {"scenario_id": "scenario-b", "status": "failed"},
            ],
            current_scenario_id=None,
            current_scenario_root=None,
            started_at="2026-05-18T20:00:00Z",
            status="failed",
        )

        payload = json.loads((campaign_root / "campaign_status.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "failed")
        self.assertIsNone(payload["current_scenario_id"])
        self.assertEqual(payload["last_completed_phase"]["phase_name"], "midpoint")
        self.assertEqual(payload["last_completed_phase"]["elapsed_seconds"], 120.0)


if __name__ == "__main__":
    unittest.main()
