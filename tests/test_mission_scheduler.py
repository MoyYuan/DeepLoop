from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from deeploop.mission.mission_scheduler import load_mission_scheduler_config, run_mission_scheduler
from runtime_artifact_helpers import fresh_test_root, write_json, write_yaml

TEST_WORK_ROOT = REPO_ROOT / "tests" / "_runtime_artifacts" / "mission_scheduler"


def _fresh_test_root(name: str) -> Path:
    return fresh_test_root(TEST_WORK_ROOT, name)


def _write_json(path: Path, payload: dict) -> None:
    write_json(path, payload)


def _write_yaml(path: Path, payload: dict) -> None:
    write_yaml(path, payload)


def _mission_state(mission_id: str, *, status: str = "running") -> dict:
    return {
        "mission_id": mission_id,
        "title": f"{mission_id} title",
        "current_phase": "execution",
        "next_phase": "critique",
        "status": status,
        "autonomy_status": {"state": "initialized", "reason": "scheduler test"},
        "mission_runtime": {"iterations_completed": 0},
        "next_actions": {"summary": f"Advance {mission_id}", "actions": []},
    }


class MissionSchedulerTests(unittest.TestCase):
    def tearDown(self) -> None:
        shutil.rmtree(TEST_WORK_ROOT, ignore_errors=True)

    def test_scheduler_balances_priority_fairness_and_budgets(self) -> None:
        test_root = _fresh_test_root("balances_priority_fairness_and_budgets")
        high_state_path = test_root / "missions" / "high" / "mission_state.json"
        low_state_path = test_root / "missions" / "low" / "mission_state.json"
        _write_json(high_state_path, _mission_state("mission-high"))
        _write_json(low_state_path, _mission_state("mission-low"))
        config_path = test_root / "scheduler.yaml"
        _write_yaml(
            config_path,
            {
                "scheduler_id": "demo-scheduler",
                "scheduler_root": str(test_root / "scheduler"),
                "policy": {
                    "budget": {
                        "max_total_iterations": 3,
                        "slice_iterations": 1,
                        "max_consecutive_slices": 1,
                        "default_mission_budget_iterations": 4,
                    },
                    "fairness": {"starvation_window": 1, "aging_weight": 5.0},
                },
                "missions": [
                    {"mission_state": str(high_state_path), "priority": 100, "mission_budget_iterations": 3},
                    {"mission_state": str(low_state_path), "priority": 10, "mission_budget_iterations": 1},
                ],
            },
        )
        dispatch_order: list[str] = []

        def runner(mission_state_path: Path, *, max_iterations: int) -> dict[str, object]:
            mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
            dispatch_order.append(mission_state["mission_id"])
            mission_state["mission_runtime"]["iterations_completed"] = max_iterations
            mission_state["status"] = "running"
            _write_json(mission_state_path, mission_state)
            return {"status": "max-iterations", "iterations_completed": max_iterations, "terminal_reason": None}

        result = run_mission_scheduler(load_mission_scheduler_config(config_path), runner=runner)

        self.assertEqual(result["status"], "budget-exhausted")
        self.assertEqual(dispatch_order, ["mission-high", "mission-low", "mission-high"])
        summary = json.loads(Path(result["summary_json_path"]).read_text(encoding="utf-8"))
        self.assertEqual(summary["missions"]["mission-high"]["iterations_consumed"], 2)
        self.assertEqual(summary["missions"]["mission-low"]["iterations_consumed"], 1)
        low_state = json.loads(low_state_path.read_text(encoding="utf-8"))
        self.assertEqual(low_state["mission_scheduler"]["remaining_budget"], 0)

    def test_scheduler_records_higher_priority_preemption(self) -> None:
        test_root = _fresh_test_root("records_higher_priority_preemption")
        low_state_path = test_root / "missions" / "low" / "mission_state.json"
        high_state_path = test_root / "missions" / "high" / "mission_state.json"
        _write_json(low_state_path, _mission_state("mission-low"))
        _write_json(high_state_path, _mission_state("mission-high", status="blocked"))
        config_path = test_root / "scheduler.yaml"
        _write_yaml(
            config_path,
            {
                "scheduler_id": "demo-preemption",
                "scheduler_root": str(test_root / "scheduler"),
                "policy": {
                    "budget": {
                        "max_total_iterations": 2,
                        "slice_iterations": 1,
                        "max_consecutive_slices": 2,
                        "default_mission_budget_iterations": 2,
                    }
                },
                "missions": [
                    {"mission_state": str(low_state_path), "priority": 10},
                    {"mission_state": str(high_state_path), "priority": 100},
                ],
            },
        )
        dispatch_order: list[str] = []

        def runner(mission_state_path: Path, *, max_iterations: int) -> dict[str, object]:
            mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
            dispatch_order.append(mission_state["mission_id"])
            if mission_state["mission_id"] == "mission-low":
                high_state = json.loads(high_state_path.read_text(encoding="utf-8"))
                high_state["status"] = "running"
                _write_json(high_state_path, high_state)
            mission_state["mission_runtime"]["iterations_completed"] = max_iterations
            _write_json(mission_state_path, mission_state)
            return {"status": "max-iterations", "iterations_completed": max_iterations, "terminal_reason": None}

        result = run_mission_scheduler(load_mission_scheduler_config(config_path), runner=runner)

        self.assertEqual(result["status"], "budget-exhausted")
        self.assertEqual(dispatch_order, ["mission-low", "mission-high"])
        self.assertEqual(result["preemptions"][0]["reason"], "higher-priority-ready")

    def test_scheduler_composes_operator_attention_across_missions(self) -> None:
        test_root = _fresh_test_root("composes_operator_attention_across_missions")
        high_state_path = test_root / "missions" / "high" / "mission_state.json"
        low_state_path = test_root / "missions" / "low" / "mission_state.json"
        _write_json(high_state_path, _mission_state("mission-high", status="blocked"))
        _write_json(low_state_path, _mission_state("mission-low"))
        _write_json(
            high_state_path.parent / "current_operator_request.json",
            {
                "request_id": "operator-1",
                "status": "open",
                "blocker": {"kind": "hard-gate", "risk_class": "sandbox-boundary", "reason": "needs review"},
            },
        )
        config_path = test_root / "scheduler.yaml"
        _write_yaml(
            config_path,
            {
                "scheduler_id": "demo-composition",
                "scheduler_root": str(test_root / "scheduler"),
                "policy": {
                    "budget": {"max_total_iterations": 2, "slice_iterations": 1},
                    "composition": {"open_request_policy": "pause-lower-priority"},
                },
                "missions": [
                    {"mission_state": str(high_state_path), "priority": 100},
                    {"mission_state": str(low_state_path), "priority": 10},
                ],
            },
        )

        result = run_mission_scheduler(load_mission_scheduler_config(config_path), runner=lambda *_args, **_kwargs: {})

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["terminal_reason"], "operator-review-required")
        low_state = json.loads(low_state_path.read_text(encoding="utf-8"))
        self.assertEqual(low_state["mission_scheduler"]["suppression_reason"], "operator-focus")
        high_state = json.loads(high_state_path.read_text(encoding="utf-8"))
        self.assertEqual(high_state["mission_scheduler"]["active_operator_request_id"], "operator-1")


if __name__ == "__main__":
    unittest.main()
