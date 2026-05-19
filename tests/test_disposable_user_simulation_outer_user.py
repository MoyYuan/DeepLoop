from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.testing.disposable_user_simulation import (
    DEFAULT_MATRIX_PATH,
    build_scenario_contract,
    load_disposable_user_simulation_matrix,
)
from deeploop.testing.disposable_user_simulation_outer_user import (
    DisposableUserSimulationInputs,
    run_disposable_user_simulation,
)


class DisposableUserSimulationOuterUserRegressionTests(unittest.TestCase):
    def _build_inputs(self, test_name: str, *, minimum_session_seconds: int = 12) -> tuple[DisposableUserSimulationInputs, Path]:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        scenario = matrix.scenarios[0]
        scenario_root = REPO_ROOT / "build" / "test-disposable-user-simulation-outer-user" / test_name
        shutil.rmtree(scenario_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, scenario_root, True)
        scenario_root.mkdir(parents=True, exist_ok=True)
        (scenario_root / "artifacts").mkdir(parents=True, exist_ok=True)
        (scenario_root / "prompt.md").write_text("Outer prompt body", encoding="utf-8")

        contract = build_scenario_contract(matrix, scenario, campaign_id="campaign-outer", container_name="demo-container")
        (scenario_root / "scenario_contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
        (scenario_root / "runtime_pins.yaml").write_text(
            yaml.safe_dump(
                {
                    "runtime_constraints": contract["runtime_constraints"],
                    "recommended_commands": contract.get("recommended_commands") or [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        return (
            DisposableUserSimulationInputs(
                campaign_id="campaign-outer",
                scenario_id=scenario.scenario_id,
                container_name="demo-container",
                scenario_root=scenario_root,
                prompt_path=scenario_root / "prompt.md",
                contract_path=scenario_root / "scenario_contract.json",
                runtime_pins_path=scenario_root / "runtime_pins.yaml",
                workspace_root="/home/deeploop/Workspaces",
                artifacts_root="/artifacts",
                minimum_session_seconds=minimum_session_seconds,
            ),
            scenario_root,
        )

    def test_midpoint_failure_still_waits_until_minimum_session_seconds(self) -> None:
        inputs, _ = self._build_inputs("midpoint-failure-waits")
        current = [0.0]
        phase_calls: list[str] = []

        def fake_clock() -> float:
            return current[0]

        def fake_sleep(seconds: float) -> None:
            current[0] += seconds

        def fake_run(command, **kwargs):
            del command, kwargs
            phase_calls.append(f"phase-{len(phase_calls) + 1}")
            duration = 1.0 if len(phase_calls) == 1 else 0.5
            current[0] += duration
            return subprocess.CompletedProcess(
                args=["copilot"],
                returncode=0 if len(phase_calls) == 1 else 17,
                stdout=f"{phase_calls[-1]} output\n",
                stderr="",
            )

        with self.assertRaisesRegex(RuntimeError, "phase `midpoint`"):
            run_disposable_user_simulation(
                inputs,
                runner=fake_run,
                clock=fake_clock,
                sleeper=fake_sleep,
            )

        self.assertEqual(phase_calls, ["phase-1", "phase-2"])
        self.assertEqual(current[0], inputs.minimum_session_seconds)

    def test_failure_path_artifacts_are_written_before_failure_surfaces(self) -> None:
        inputs, scenario_root = self._build_inputs("failure-artifacts")
        current = [0.0]
        phase_names = ["opening", "midpoint"]

        def fake_clock() -> float:
            return current[0]

        def fake_sleep(seconds: float) -> None:
            current[0] += seconds

        def fake_run(command, **kwargs):
            del command, kwargs
            phase_number = len(phase_names) - 1
            current[0] += 0.25
            return subprocess.CompletedProcess(
                args=["copilot"],
                returncode=0 if phase_number == 1 else 23,
                stdout=f"{phase_names.pop(0)} output\n",
                stderr="simulated failure\n" if phase_number == 0 else "",
            )

        with self.assertRaisesRegex(RuntimeError, "phase `midpoint`"):
            run_disposable_user_simulation(
                inputs,
                runner=fake_run,
                clock=fake_clock,
                sleeper=fake_sleep,
            )

        run_root = scenario_root / "artifacts" / "outer-user-simulation"
        summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
        transcript = (run_root / "transcript.md").read_text(encoding="utf-8")

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["failure"]["phase_name"], "midpoint")
        self.assertEqual(summary["failure"]["returncode"], 23)
        self.assertEqual(len(summary["phases"]), 2)
        self.assertTrue((run_root / "phases" / "01-opening" / "phase.json").exists())
        self.assertTrue((run_root / "phases" / "02-midpoint" / "phase.json").exists())
        self.assertFalse((run_root / "phases" / "03-closing" / "phase.json").exists())
        self.assertIn("opening output", transcript)
        self.assertIn("midpoint output", transcript)

    def test_successful_run_still_waits_until_minimum_session_seconds(self) -> None:
        inputs, _ = self._build_inputs("successful-run-waits")
        current = [0.0]
        call_count = [0]

        def fake_clock() -> float:
            return current[0]

        def fake_sleep(seconds: float) -> None:
            current[0] += seconds

        def fake_run(command, **kwargs):
            del command, kwargs
            call_count[0] += 1
            current[0] += 0.1
            return subprocess.CompletedProcess(
                args=["copilot"],
                returncode=0,
                stdout=f"phase-{call_count[0]} output\n",
                stderr="",
            )

        summary = run_disposable_user_simulation(
            inputs,
            runner=fake_run,
            clock=fake_clock,
            sleeper=fake_sleep,
        )

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(call_count[0], 3)
        self.assertGreaterEqual(current[0], inputs.minimum_session_seconds)
        self.assertGreaterEqual(summary["elapsed_seconds"], inputs.minimum_session_seconds)


if __name__ == "__main__":
    unittest.main()
