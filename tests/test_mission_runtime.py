from __future__ import annotations

from copy import deepcopy
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from deeploop.autonomy.mission_autonomy import build_outer_loop_contract
from deeploop.mission.mission_runtime import (
    _apply_phase_change,
    _mission_state_updates_from_executor,
    run_mission,
)
from deeploop.project_contract import discover_project_contract
from deeploop.research.indexed_memory import build_research_memory_contract
from deeploop.runtime.mission_executor_registry import MissionExecutionResult, MissionExecutorId
from deeploop.runtime.stage_kernels import KernelRunResult
from runtime_artifact_helpers import fresh_test_root, write_json

TEST_WORK_ROOT = REPO_ROOT / "tests" / "_runtime_artifacts" / "mission_runtime"


def _fresh_test_root(name: str) -> Path:
    return fresh_test_root(TEST_WORK_ROOT, name)


def _write_json(path: Path, payload: dict) -> None:
    normalized_payload = payload
    if path.name == "mission_state.json" and isinstance(payload.get("mission_id"), str):
        normalized_payload = deepcopy(payload)
        mission_root = path.parent
        outer_loop = build_outer_loop_contract(
            mission_root,
            mode=str(normalized_payload.get("mode") or "sandboxed-yolo"),
        )
        existing_outer_loop = (
            dict(normalized_payload.get("outer_loop"))
            if isinstance(normalized_payload.get("outer_loop"), dict)
            else {}
        )
        outer_loop.update(existing_outer_loop)
        outer_loop.update(build_research_memory_contract(memory_root=mission_root / "research_memory"))
        normalized_payload["outer_loop"] = outer_loop
    write_json(path, normalized_payload)


def _base_state(*, mission_id: str, current_phase: str, next_phase: str, actions: list[dict]) -> dict:
    return {
        "mission_id": mission_id,
        "mode": "sandboxed-yolo",
        "title": "Mission runtime test",
        "summary": "Exercise the mission outer runtime.",
        "objective": "Drive the mission honestly across bounded steps.",
        "current_phase": current_phase,
        "next_phase": next_phase,
        "status": "running",
        "target_repo": str(REPO_ROOT),
        "completed_phases": [],
        "phase_history": [current_phase],
        "roles": ["execution-operator", "critic-verifier", "report-synthesizer"],
        "next_actions": {"actions": actions},
        "autonomy_status": {"state": "initialized", "reason": "test"},
    }


class MissionRuntimeTests(unittest.TestCase):
    def test_invoke_followup_planner_imports_provider_from_contract_pythonpath(self) -> None:
        from deeploop.mission.mission_runtime import _invoke_followup_planner

        test_root = _fresh_test_root("invoke_followup_planner_imports_provider")
        repo_root = test_root / "demo-project"
        contract_root = repo_root / ".deeploop"
        src_root = repo_root / "src"
        module_name = "demo_followup_provider"
        module_path = src_root / f"{module_name}.py"
        (contract_root / "queues").mkdir(parents=True, exist_ok=True)
        src_root.mkdir(parents=True, exist_ok=True)
        baseline_queue_path = contract_root / "queues" / "baseline.yaml"
        baseline_queue_path.write_text("queue: demo\n", encoding="utf-8")
        module_path.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "import json",
                    "from pathlib import Path",
                    "",
                    "def stage_followups(mission_state_path: Path, baseline_queue_config: str) -> dict:",
                    "    state_path = Path(mission_state_path)",
                    "    state = json.loads(state_path.read_text(encoding='utf-8'))",
                    "    state['followup_queue_config'] = str(baseline_queue_config)",
                    "    state_path.write_text(json.dumps(state, indent=2) + '\\n', encoding='utf-8')",
                    "    return {'baseline_queue_config': str(baseline_queue_config)}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        runtime_providers_path = contract_root / "runtime-providers.yaml"
        runtime_providers_path.write_text(
            "\n".join(
                [
                    "version: 1",
                    "providers:",
                    "  followup_planner:",
                    f"    entrypoint: {module_name}:stage_followups",
                    "    pythonpath:",
                    "      - ../src",
                    "    params:",
                    "      baseline_queue_config: queues/baseline.yaml",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        mission_state_path = test_root / "mission" / "mission_state.json"
        mission_state = {
            **_base_state(
                mission_id="mission-runtime-provider-pythonpath",
                current_phase="execution",
                next_phase="critique",
                actions=[],
            ),
            "target_repo": str(repo_root),
            "project_contract": discover_project_contract(repo_root),
            "bootstrap": {
                "followup_planner": {
                    "provider": "followup_planner",
                }
            },
        }
        _write_json(mission_state_path, mission_state)

        result = _invoke_followup_planner(mission_state_path, mission_state, mission_state["bootstrap"])

        self.assertEqual(result["baseline_queue_config"], str(baseline_queue_path.resolve()))
        updated_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(updated_state["followup_queue_config"], str(baseline_queue_path.resolve()))

    def test_revisiting_phase_clears_current_outputs_but_keeps_history(self) -> None:
        mission_state = _base_state(
            mission_id="mission-runtime-revisit",
            current_phase="critique",
            next_phase="experiment-design",
            actions=[],
        )
        mission_state["completed_phases"] = [
            "idea-intake",
            "literature-review",
            "question-design",
            "experiment-design",
            "execution",
        ]
        mission_state["phase_history"] = [
            "idea-intake",
            "literature-review",
            "question-design",
            "experiment-design",
            "execution",
            "critique",
        ]
        mission_state["phase_outputs_by_phase"] = {
            "experiment-design": ["run manifest draft", "execution profile selection"],
            "execution": ["run logs", "metrics", "crash / stability notes"],
            "critique": ["evidence assessment", "confound notes", "next-step recommendation"],
        }
        mission_state["produced_outputs"] = ["evidence assessment", "confound notes", "next-step recommendation"]
        mission_state["phase_outputs"] = list(mission_state["produced_outputs"])

        _apply_phase_change(
            mission_state,
            from_phase="critique",
            to_phase="experiment-design",
            next_phase="execution",
        )

        self.assertEqual(mission_state["current_phase"], "experiment-design")
        self.assertEqual(mission_state["next_phase"], "execution")
        self.assertEqual(mission_state["produced_outputs"], [])
        self.assertEqual(mission_state["phase_outputs"], [])
        self.assertEqual(mission_state["phase_outputs_by_phase"]["experiment-design"], [])

    def test_executor_updates_preserve_recursive_phase_handoff(self) -> None:
        mission_state = _base_state(
            mission_id="mission-runtime-recursive-handoff",
            current_phase="experiment-design",
            next_phase="execution",
            actions=[],
        )
        mission_state["completed_phases"] = ["idea-intake", "literature-review", "question-design", "experiment-design"]
        mission_state["phase_history"] = [
            "idea-intake",
            "literature-review",
            "question-design",
            "experiment-design",
            "execution",
        ]
        mission_state["current_phase"] = "execution"
        mission_state["next_phase"] = "execution"
        result = MissionExecutionResult(
            executor_id=MissionExecutorId.RECURSIVE_AGENT,
            status="max-iterations",
            summary="Recursive loop reached its iteration cap after promoting into execution.",
            payload={
                "latest_outcome": {
                    "phase_control": {
                        "current_phase": "experiment-design",
                        "next_phase": "execution",
                    },
                    "continuation": {
                        "phase": "execution",
                    },
                }
            },
            artifacts={},
        )

        updated_state, action_status, output_paths = _mission_state_updates_from_executor(
            mission_state,
            action_payload={
                "action_id": "close-experiment-design",
                "phase": "experiment-design",
                "produces_outputs": [
                    "run manifest draft",
                    "execution profile selection",
                    "resource tier selection",
                ],
            },
            result=result,
        )

        self.assertEqual(updated_state["current_phase"], "execution")
        self.assertEqual(updated_state["next_phase"], "critique")
        self.assertEqual(action_status, "deferred")
        self.assertEqual(output_paths, [])

    @patch("deeploop.mission.mission_runtime.run_mission_action")
    def test_runtime_retries_recursive_idle_failure_with_planner_downscope(self, mock_run_mission_action) -> None:
        test_root = _fresh_test_root("recursive_idle_failure_recovery")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            {
                **_base_state(
                    mission_id="mission-runtime-recursive-recovery",
                    current_phase="literature-review",
                    next_phase="question-design",
                    actions=[
                        {
                            "action_id": "literature-pass",
                            "role": "literature-scout",
                            "task": "Produce the literature review artifacts.",
                            "kind": "artifact-edit",
                            "status": "pending",
                            "phase": "literature-review",
                            "runtime_owner": "deeploop",
                            "requires_operator_approval": False,
                            "executor": {
                                "id": "recursive-agent",
                                "params": {"config_path": "configs/runtime/demo-recursive.yaml"},
                            },
                            "produces_outputs": ["prior-art memo", "benchmark and method watchlist"],
                        }
                    ],
                ),
                "phase_execution_hints": {
                    "literature-review": {
                        "executor": {
                            "id": "recursive-agent",
                            "params": {"config_path": "configs/runtime/demo-recursive.yaml"},
                        }
                    }
                },
            },
        )

        def _fake_run_action(action):
            if mock_run_mission_action.call_count == 1:
                return MissionExecutionResult(
                    executor_id=MissionExecutorId.RECURSIVE_AGENT,
                    status="blocked",
                    summary="provider subprocess stayed idle without producing recoverable outputs or agent_result.json.",
                    payload={},
                    artifacts={},
                )
            return MissionExecutionResult(
                executor_id=MissionExecutorId.RECURSIVE_AGENT,
                status="completed",
                summary="Recovered literature outputs under planner downscope.",
                payload={
                    "produced_outputs": ["prior-art memo", "benchmark and method watchlist"],
                    "phase_control": {
                        "current_phase": "literature-review",
                        "next_phase": "question-design",
                    },
                },
                artifacts={},
            )

        mock_run_mission_action.side_effect = _fake_run_action

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "max-iterations")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual([action["role"] for action in mission_state["next_actions"]["actions"][:2]], ["literature-scout", "planner"])
        self.assertEqual(mission_state["current_phase"], "question-design")
        self.assertEqual(mission_state["failure_count"], 1)
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["literature-review"],
            ["prior-art memo", "benchmark and method watchlist"],
        )

    @patch("deeploop.mission.mission_runtime.run_mission_action")
    def test_runtime_retries_recursive_idle_failure_for_execution_local_eval(self, mock_run_mission_action) -> None:
        test_root = _fresh_test_root("recursive_execution_idle_recovery")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            {
                **_base_state(
                    mission_id="mission-runtime-recursive-execution-recovery",
                    current_phase="execution",
                    next_phase="critique",
                    actions=[
                        {
                            "action_id": "run-baseline",
                            "role": "execution-operator",
                            "task": "Run the bounded baseline evaluation.",
                            "kind": "local-eval",
                            "status": "pending",
                            "phase": "execution",
                            "runtime_owner": "deeploop",
                            "requires_operator_approval": False,
                            "executor": {
                                "id": "recursive-agent",
                                "params": {"config_path": "configs/runtime/demo-recursive.yaml"},
                            },
                            "produces_outputs": ["run logs", "metrics", "crash / stability notes"],
                        }
                    ],
                ),
                "phase_execution_hints": {
                    "execution": {
                        "executor": {
                            "id": "recursive-agent",
                            "params": {"config_path": "configs/runtime/demo-recursive.yaml"},
                        }
                    }
                },
            },
        )

        def _fake_run_action(action):
            if mock_run_mission_action.call_count == 1:
                return MissionExecutionResult(
                    executor_id=MissionExecutorId.RECURSIVE_AGENT,
                    status="blocked",
                    summary="provider subprocess stayed idle without producing recoverable outputs or agent_result.json.",
                    payload={},
                    artifacts={},
                )
            return MissionExecutionResult(
                executor_id=MissionExecutorId.RECURSIVE_AGENT,
                status="completed",
                summary="Recovered execution outputs after bounded retry.",
                payload={
                    "produced_outputs": ["run logs", "metrics", "crash / stability notes"],
                    "phase_control": {
                        "current_phase": "execution",
                        "next_phase": "critique",
                    },
                },
                artifacts={},
            )

        mock_run_mission_action.side_effect = _fake_run_action

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "max-iterations")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["current_phase"], "critique")
        self.assertEqual(mission_state["failure_count"], 1)
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["execution"],
            ["run logs", "metrics", "crash / stability notes"],
        )

    @patch("deeploop.mission.mission_runtime.run_mission_action")
    def test_runtime_retries_recursive_idle_failure_for_critique(self, mock_run_mission_action) -> None:
        test_root = _fresh_test_root("recursive_critique_idle_recovery")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            {
                **_base_state(
                    mission_id="mission-runtime-recursive-critique-recovery",
                    current_phase="critique",
                    next_phase="replication",
                    actions=[
                        {
                            "action_id": "write-critique",
                            "role": "critic-verifier",
                            "task": "Write the critique artifacts.",
                            "kind": "critique",
                            "status": "pending",
                            "phase": "critique",
                            "runtime_owner": "deeploop",
                            "requires_operator_approval": False,
                            "executor": {
                                "id": "recursive-agent",
                                "params": {"config_path": "configs/runtime/demo-recursive.yaml"},
                            },
                            "produces_outputs": ["evidence assessment", "confound notes", "next-step recommendation"],
                        }
                    ],
                ),
                "phase_execution_hints": {
                    "critique": {
                        "executor": {
                            "id": "recursive-agent",
                            "params": {"config_path": "configs/runtime/demo-recursive.yaml"},
                        }
                    }
                },
            },
        )

        def _fake_run_action(action):
            if mock_run_mission_action.call_count == 1:
                return MissionExecutionResult(
                    executor_id=MissionExecutorId.RECURSIVE_AGENT,
                    status="blocked",
                    summary="provider subprocess stayed idle without producing recoverable outputs or agent_result.json.",
                    payload={},
                    artifacts={},
                )
            return MissionExecutionResult(
                executor_id=MissionExecutorId.RECURSIVE_AGENT,
                status="completed",
                summary="Recovered critique outputs after bounded retry.",
                payload={
                    "produced_outputs": ["evidence assessment", "confound notes", "next-step recommendation"],
                    "phase_control": {
                        "current_phase": "critique",
                        "next_phase": "replication",
                    },
                },
                artifacts={},
            )

        mock_run_mission_action.side_effect = _fake_run_action

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "max-iterations")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["current_phase"], "replication")
        self.assertEqual(mission_state["failure_count"], 1)
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["critique"],
            ["evidence assessment", "confound notes", "next-step recommendation"],
        )

    @patch("deeploop.runtime.mission_executor_registry.run_stage_from_config")
    def test_runtime_dispatches_executor_then_transitions_phase(self, mock_run_stage_from_config) -> None:
        test_root = _fresh_test_root("dispatches_executor_then_transitions_phase")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-dispatch",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "run-baseline",
                        "role": "execution-operator",
                        "task": "Run the bounded baseline evaluation.",
                        "kind": "local-eval",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "stage-kernel",
                            "params": {
                                "stage_id": "baseline-evaluation",
                                "config_path": "configs/runtime/demo-stage.yaml",
                            },
                        },
                        "produces_outputs": ["run logs", "metrics", "crash / stability notes"],
                    }
                ],
            ),
        )
        output_dir = test_root / "stage-run"
        mock_run_stage_from_config.return_value = KernelRunResult(
            stage_id="baseline-evaluation",
            status="completed",
            output_dir=output_dir,
            manifest_path=output_dir / "study_manifest.json",
            summary_path=output_dir / "summary.json",
            artifacts={"metrics": output_dir / "metrics.json"},
        )

        result = run_mission(mission_state_path, max_iterations=3)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["iterations_completed"], 3)
        mock_run_stage_from_config.assert_called_once()

        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["current_phase"], "critique")
        self.assertEqual(mission_state["status"], "blocked")
        self.assertEqual(mission_state["next_actions"]["actions"][0]["status"], "completed")
        self.assertEqual(mission_state["next_actions"]["actions"][1]["status"], "completed")
        self.assertEqual(mission_state["next_actions"]["actions"][2]["status"], "blocked")
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["execution"],
            ["run logs", "metrics", "crash / stability notes"],
        )
        decision_log = (mission_state_path.parent / "mission_decisions.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len([line for line in decision_log if line.strip()]), 3)
        branch_log = (mission_state_path.parent / "mission_branches.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len([line for line in branch_log if line.strip()]), 1)
        mission_memory = json.loads((mission_state_path.parent / "mission_memory.json").read_text(encoding="utf-8"))
        self.assertEqual(len(mission_memory["branch_registry"]), 1)
        self.assertEqual(next(iter(mission_memory["branch_registry"].values()))["status"], "critique-ready")
        self.assertEqual(mission_memory["completed_phase_outputs"]["execution"], ["run logs", "metrics", "crash / stability notes"])
        self.assertEqual(mission_memory["counts"]["evidence_snapshots"], 3)
        experiment_entries = [
            json.loads(line)
            for line in (mission_state_path.parent / "mission_experiments.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(
            [entry["kind"] for entry in experiment_entries],
            ["evidence-snapshot", "experiment-run", "evidence-snapshot", "evidence-snapshot"],
        )
        self.assertEqual(experiment_entries[1]["status"], "completed")
        self.assertTrue(result["mission_memory_path"].exists())
        self.assertTrue(result["experiment_ledger_path"].exists())
        self.assertTrue(result["research_memory_events_path"].exists())
        self.assertTrue(result["research_memory_index_path"].exists())

    @patch("deeploop.runtime.mission_executor_registry.run_stage_from_config")
    def test_runtime_resumes_after_max_iterations_without_rerunning_executor(self, mock_run_stage_from_config) -> None:
        test_root = _fresh_test_root("resumes_after_max_iterations")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-resume",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "run-baseline",
                        "role": "execution-operator",
                        "task": "Run the bounded baseline evaluation.",
                        "kind": "local-eval",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "stage-kernel",
                            "params": {
                                "stage_id": "baseline-evaluation",
                                "config_path": "configs/runtime/demo-stage.yaml",
                            },
                        },
                        "produces_outputs": ["run logs", "metrics", "crash / stability notes"],
                    }
                ],
            ),
        )
        output_dir = test_root / "stage-run"
        mock_run_stage_from_config.return_value = KernelRunResult(
            stage_id="baseline-evaluation",
            status="completed",
            output_dir=output_dir,
            manifest_path=output_dir / "study_manifest.json",
            summary_path=None,
            artifacts={},
        )

        first = run_mission(mission_state_path, max_iterations=1)
        second = run_mission(mission_state_path, max_iterations=3)

        self.assertEqual(first["status"], "max-iterations")
        self.assertEqual(second["status"], "blocked")
        self.assertEqual(second["iterations_completed"], 3)
        mock_run_stage_from_config.assert_called_once()

        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["current_phase"], "critique")
        self.assertEqual(mission_state["mission_runtime"]["iterations_completed"], 3)
        experiment_entries = [
            json.loads(line)
            for line in (mission_state_path.parent / "mission_experiments.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len([entry for entry in experiment_entries if entry["kind"] == "experiment-run"]), 1)
        self.assertEqual(experiment_entries[1]["action_id"], "run-baseline")

    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_runtime_integrates_recursive_agent_executor(self, mock_run_recursive_agent_loop) -> None:
        test_root = _fresh_test_root("integrates_recursive_agent_executor")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-recursive",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "delegate-execution",
                        "role": "execution-operator",
                        "task": "Run the recursive mission worker.",
                        "kind": "local-eval",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "recursive-agent",
                            "params": {"config_path": str(test_root / "recursive-loop.yaml")},
                        },
                    }
                ],
            ),
        )

        def _fake_recursive_runtime(config_path: Path) -> dict:
            state = json.loads(mission_state_path.read_text(encoding="utf-8"))
            state["completed_phases"] = ["idea-intake", "literature-review", "question-design", "experiment-design", "execution", "critique", "replication"]
            state["current_phase"] = "final-report"
            state["next_phase"] = "final-report"
            state["produced_outputs"] = [
                "findings summary",
                "paper-candidate recommendation",
                "artifact readiness notes",
            ]
            state["phase_outputs"] = list(state["produced_outputs"])
            state["phase_outputs_by_phase"] = {
                "execution": ["run logs", "metrics", "crash / stability notes"],
                "critique": ["evidence assessment", "confound notes", "next-step recommendation"],
                "replication": ["repeated-run manifests", "replication summary"],
                "final-report": list(state["produced_outputs"]),
            }
            _write_json(mission_state_path, state)
            runtime_root = test_root / "recursive-runtime"
            return {
                "status": "completed",
                "runtime_root": runtime_root,
                "state_path": runtime_root / "agent_loop_state.json",
                "memory_path": runtime_root / "loop_memory.jsonl",
                "latest_iteration_path": runtime_root / "iteration-01",
                "latest_result_path": runtime_root / "iteration-01" / "result.json",
                "report_json_path": runtime_root / "report.json",
                "report_markdown_path": runtime_root / "report.md",
                "latest_outcome": {
                    "phase_control": {"current_phase": "final-report", "next_phase": "final-report"},
                    "action_result": {"mission_action_id": "delegate-execution"},
                },
            }

        mock_run_recursive_agent_loop.side_effect = _fake_recursive_runtime

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "completed")
        mock_run_recursive_agent_loop.assert_called_once()
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["current_phase"], "final-report")
        self.assertEqual(mission_state["status"], "completed")
        self.assertEqual(mission_state["next_actions"]["actions"][0]["status"], "completed")
        mission_memory = json.loads((mission_state_path.parent / "mission_memory.json").read_text(encoding="utf-8"))
        self.assertEqual(mission_memory["latest_experiment"]["executor_id"], "recursive-agent")

    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_runtime_blocks_when_final_report_contract_is_unsatisfied(self, mock_run_recursive_agent_loop) -> None:
        test_root = _fresh_test_root("blocks_unsatisfied_final_report_contract")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-recursive-incomplete",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "delegate-execution",
                        "role": "execution-operator",
                        "task": "Run the recursive mission worker.",
                        "kind": "local-eval",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "recursive-agent",
                            "params": {"config_path": str(test_root / "recursive-loop.yaml")},
                        },
                    }
                ],
            ),
        )

        def _fake_recursive_runtime(config_path: Path) -> dict:
            state = json.loads(mission_state_path.read_text(encoding="utf-8"))
            state["current_phase"] = "final-report"
            state["next_phase"] = "final-report"
            state["produced_outputs"] = [
                "findings summary",
                "paper-candidate recommendation",
                "artifact readiness notes",
            ]
            state["phase_outputs"] = list(state["produced_outputs"])
            state["phase_outputs_by_phase"] = {"final-report": list(state["produced_outputs"])}
            _write_json(mission_state_path, state)
            runtime_root = test_root / "recursive-runtime"
            return {
                "status": "completed",
                "runtime_root": runtime_root,
                "state_path": runtime_root / "agent_loop_state.json",
                "memory_path": runtime_root / "loop_memory.jsonl",
                "latest_iteration_path": runtime_root / "iteration-01",
                "latest_result_path": runtime_root / "iteration-01" / "result.json",
                "report_json_path": runtime_root / "report.json",
                "report_markdown_path": runtime_root / "report.md",
                "latest_outcome": {
                    "phase_control": {"current_phase": "final-report", "next_phase": "final-report"},
                    "action_result": {"mission_action_id": "delegate-execution"},
                },
            }

        mock_run_recursive_agent_loop.side_effect = _fake_recursive_runtime

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "blocked")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["status"], "blocked")
        self.assertEqual(mission_state["current_phase"], "final-report")
        self.assertIn(
            "Final-report outputs exist, but the completion contract is still unsatisfied.",
            mission_state["blocked_reasons"],
        )
        self.assertEqual(
            mission_state["mission_runtime"]["terminal_reason"],
            "Final-report outputs exist, but the completion contract is still unsatisfied.",
        )
        self.assertEqual(mission_state["operator_inbox"]["status"], "open")

    @patch("deeploop.mission.mission_runtime.record_research_memory_entry")
    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_runtime_completes_when_no_win_budget_closure_waives_replication(
        self,
        mock_run_recursive_agent_loop,
        mock_record_research_memory_entry,
    ) -> None:
        test_root = _fresh_test_root("completes_no_win_budget_without_replication")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-no-win-budget",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "delegate-execution",
                        "role": "execution-operator",
                        "task": "Run the recursive mission worker.",
                        "kind": "local-eval",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "recursive-agent",
                            "params": {"config_path": str(test_root / "recursive-loop.yaml")},
                        },
                    }
                ],
            ),
        )

        def _fake_recursive_runtime(config_path: Path) -> dict:
            state = json.loads(mission_state_path.read_text(encoding="utf-8"))
            state["completed_phases"] = [
                "idea-intake",
                "literature-review",
                "question-design",
                "experiment-design",
                "execution",
                "critique",
            ]
            state["current_phase"] = "final-report"
            state["next_phase"] = "final-report"
            state["produced_outputs"] = [
                "findings summary",
                "paper-candidate recommendation",
                "artifact readiness notes",
            ]
            state["phase_outputs"] = list(state["produced_outputs"])
            state["phase_outputs_by_phase"] = {
                "execution": ["run logs", "metrics", "crash / stability notes"],
                "critique": ["evidence assessment", "confound notes", "next-step recommendation"],
                "final-report": list(state["produced_outputs"]),
            }
            state["branch_closure_mode"] = "no-win-under-budget"
            state["downstream_execution_authorized"] = False
            _write_json(mission_state_path, state)
            runtime_root = test_root / "recursive-runtime"
            return {
                "status": "completed",
                "runtime_root": runtime_root,
                "state_path": runtime_root / "agent_loop_state.json",
                "memory_path": runtime_root / "loop_memory.jsonl",
                "latest_iteration_path": runtime_root / "iteration-01",
                "latest_result_path": runtime_root / "iteration-01" / "result.json",
                "report_json_path": runtime_root / "report.json",
                "report_markdown_path": runtime_root / "report.md",
                "latest_outcome": {
                    "phase_control": {"current_phase": "final-report", "next_phase": "final-report"},
                    "action_result": {"mission_action_id": "delegate-execution"},
                },
            }

        mock_run_recursive_agent_loop.side_effect = _fake_recursive_runtime

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "completed")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["status"], "completed")
        self.assertEqual(mission_state["current_phase"], "final-report")
        self.assertEqual(mission_state["operator_inbox"]["status"], "clear")

    @patch("deeploop.mission.mission_runtime.record_research_memory_entry")
    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_runtime_completes_when_final_report_no_promotion_closes_replication(
        self,
        mock_run_recursive_agent_loop,
        mock_record_research_memory_entry,
    ) -> None:
        test_root = _fresh_test_root("completes_final_report_no_promotion_without_replication")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-final-report-no-promotion",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "delegate-execution",
                        "role": "execution-operator",
                        "task": "Run the recursive mission worker.",
                        "kind": "local-eval",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "recursive-agent",
                            "params": {"config_path": str(test_root / "recursive-loop.yaml")},
                        },
                    }
                ],
            ),
        )

        def _fake_recursive_runtime(config_path: Path) -> dict:
            state = json.loads(mission_state_path.read_text(encoding="utf-8"))
            state["completed_phases"] = [
                "idea-intake",
                "literature-review",
                "question-design",
                "experiment-design",
                "execution",
                "critique",
            ]
            state["current_phase"] = "final-report"
            state["next_phase"] = "final-report"
            state["final_report"] = {
                "decision": "no-promotion",
                "close_mission": True,
                "no_further_execution_reroute": True,
            }
            state["produced_outputs"] = [
                "findings summary",
                "paper-candidate recommendation",
                "artifact readiness notes",
            ]
            state["phase_outputs"] = list(state["produced_outputs"])
            state["phase_outputs_by_phase"] = {
                "execution": ["run logs", "metrics", "crash / stability notes"],
                "critique": ["evidence assessment", "confound notes", "next-step recommendation"],
                "final-report": list(state["produced_outputs"]),
            }
            _write_json(mission_state_path, state)
            runtime_root = test_root / "recursive-runtime"
            return {
                "status": "completed",
                "runtime_root": runtime_root,
                "state_path": runtime_root / "agent_loop_state.json",
                "memory_path": runtime_root / "loop_memory.jsonl",
                "latest_iteration_path": runtime_root / "iteration-01",
                "latest_result_path": runtime_root / "iteration-01" / "result.json",
                "report_json_path": runtime_root / "report.json",
                "report_markdown_path": runtime_root / "report.md",
                "latest_outcome": {
                    "phase_control": {"current_phase": "final-report", "next_phase": "final-report"},
                    "action_result": {"mission_action_id": "delegate-execution"},
                },
            }

        mock_run_recursive_agent_loop.side_effect = _fake_recursive_runtime

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "completed")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["status"], "completed")
        self.assertEqual(mission_state["current_phase"], "final-report")
        self.assertEqual(mission_state["operator_inbox"]["status"], "clear")

    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_runtime_preserves_prior_phase_outputs_when_final_report_updates_nested_state(
        self,
        mock_run_recursive_agent_loop,
    ) -> None:
        test_root = _fresh_test_root("preserves_nested_phase_outputs_on_final_report")
        mission_state_path = test_root / "mission" / "mission_state.json"
        mission_state = _base_state(
            mission_id="mission-runtime-final-report-deep-merge",
            current_phase="final-report",
            next_phase="final-report",
            actions=[
                {
                    "action_id": "assemble-final-report",
                    "role": "report-synthesizer",
                    "task": "Close the mission with the final report.",
                    "kind": "final-report",
                    "status": "pending",
                    "phase": "final-report",
                    "runtime_owner": "deeploop",
                    "requires_operator_approval": False,
                    "executor": {
                        "id": "recursive-agent",
                        "params": {"config_path": str(test_root / "recursive-loop.yaml")},
                    },
                    "produces_outputs": [
                        "findings summary",
                        "paper-candidate recommendation",
                        "artifact readiness notes",
                    ],
                }
            ],
        )
        mission_state["completed_phases"] = [
            "idea-intake",
            "literature-review",
            "question-design",
            "experiment-design",
            "execution",
            "critique",
            "replication",
        ]
        mission_state["phase_history"] = list(mission_state["completed_phases"]) + ["final-report"]
        mission_state["phase_outputs_by_phase"] = {
            "execution": ["run logs", "metrics", "crash / stability notes"],
            "critique": ["evidence assessment", "confound notes", "next-step recommendation"],
            "replication": ["repeated-run manifests", "replication summary"],
        }
        _write_json(mission_state_path, mission_state)

        def _fake_recursive_runtime(config_path: Path) -> dict:
            runtime_root = test_root / "recursive-runtime"
            return {
                "status": "completed",
                "runtime_root": runtime_root,
                "state_path": runtime_root / "agent_loop_state.json",
                "memory_path": runtime_root / "loop_memory.jsonl",
                "latest_iteration_path": runtime_root / "iteration-01",
                "latest_result_path": runtime_root / "iteration-01" / "result.json",
                "report_json_path": runtime_root / "report.json",
                "report_markdown_path": runtime_root / "report.md",
                "latest_outcome": {
                    "status": "complete",
                    "phase_control": {"current_phase": "final-report", "next_phase": "final-report"},
                    "action_result": {"mission_action_id": "assemble-final-report"},
                    "mission_state_updates": {
                        "current_phase": "final-report",
                        "next_phase": "final-report",
                        "status": "completed",
                        "produced_outputs": [
                            "findings summary",
                            "paper-candidate recommendation",
                            "artifact readiness notes",
                        ],
                        "phase_outputs": [
                            "findings summary",
                            "paper-candidate recommendation",
                            "artifact readiness notes",
                        ],
                        "phase_outputs_by_phase": {
                            "final-report": [
                                "findings summary",
                                "paper-candidate recommendation",
                                "artifact readiness notes",
                            ]
                        },
                    },
                },
            }

        mock_run_recursive_agent_loop.side_effect = _fake_recursive_runtime

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "completed")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["status"], "completed")
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["execution"],
            ["run logs", "metrics", "crash / stability notes"],
        )
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["critique"],
            ["evidence assessment", "confound notes", "next-step recommendation"],
        )
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["replication"],
            ["repeated-run manifests", "replication summary"],
        )
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["final-report"],
            ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        )
        self.assertEqual(mission_state["operator_inbox"]["status"], "clear")

    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_runtime_dispatches_missing_critique_outputs_via_phase_hint(
        self,
        mock_run_recursive_agent_loop,
    ) -> None:
        test_root = _fresh_test_root("dispatches_missing_critique_outputs_via_phase_hint")
        mission_state_path = test_root / "mission" / "mission_state.json"
        recursive_config_path = test_root / "runtime" / "phase-loop.yaml"
        recursive_config_path.parent.mkdir(parents=True, exist_ok=True)
        recursive_config_path.write_text("mission_state: placeholder\n", encoding="utf-8")
        _write_json(
            mission_state_path,
            {
                **_base_state(
                    mission_id="mission-runtime-critique-hint",
                    current_phase="critique",
                    next_phase="replication",
                    actions=[],
                ),
                "phase_execution_hints": {
                    "critique": {
                        "executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}},
                        "next_phase_on_success": "replication",
                    }
                },
            },
        )

        runtime_root = test_root / "recursive-runtime"
        mock_run_recursive_agent_loop.return_value = {
            "status": "completed",
            "runtime_root": runtime_root,
            "state_path": runtime_root / "agent_loop_state.json",
            "memory_path": runtime_root / "loop_memory.jsonl",
            "latest_iteration_path": runtime_root / "iteration-01",
            "latest_result_path": runtime_root / "iteration-01" / "result.json",
            "report_json_path": runtime_root / "report.json",
            "report_markdown_path": runtime_root / "report.md",
            "produced_outputs": [
                "evidence assessment",
                "confound notes",
                "next-step recommendation",
            ],
            "latest_outcome": {
                "phase_control": {"current_phase": "replication", "next_phase": "final-report"},
                "action_result": {
                    "mission_action_id": "mission-runtime-critique-hint-critique-missing-outputs",
                },
            },
        }

        result = run_mission(mission_state_path, max_iterations=1)

        self.assertEqual(result["status"], "max-iterations")
        mock_run_recursive_agent_loop.assert_called_once_with(recursive_config_path)
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["current_phase"], "replication")
        self.assertEqual(mission_state["next_phase"], "final-report")
        self.assertEqual(mission_state["next_actions"]["actions"][0]["status"], "completed")
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["critique"],
            ["evidence assessment", "confound notes", "next-step recommendation"],
        )
        mission_memory = json.loads((mission_state_path.parent / "mission_memory.json").read_text(encoding="utf-8"))
        self.assertEqual(mission_memory["latest_experiment"]["executor_id"], "recursive-agent")

    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_runtime_advances_when_recursive_loop_caps_after_completed_action(
        self,
        mock_run_recursive_agent_loop,
    ) -> None:
        test_root = _fresh_test_root("recursive_agent_cap_after_completion")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-recursive-cap",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "delegate-execution",
                        "role": "execution-operator",
                        "task": "Run the recursive mission worker.",
                        "kind": "local-eval",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "recursive-agent",
                            "params": {"config_path": str(test_root / "recursive-loop.yaml")},
                        },
                    }
                ],
            ),
        )

        def _fake_recursive_runtime(config_path: Path) -> dict:
            state = json.loads(mission_state_path.read_text(encoding="utf-8"))
            state["completed_phases"] = ["idea-intake", "literature-review", "question-design", "experiment-design", "execution", "critique", "replication"]
            state["current_phase"] = "final-report"
            state["next_phase"] = "final-report"
            state["produced_outputs"] = [
                "findings summary",
                "paper-candidate recommendation",
                "artifact readiness notes",
            ]
            state["phase_outputs"] = list(state["produced_outputs"])
            state["phase_outputs_by_phase"] = {
                "execution": ["run logs", "metrics", "crash / stability notes"],
                "critique": ["evidence assessment", "confound notes", "next-step recommendation"],
                "replication": ["repeated-run manifests", "replication summary"],
                "final-report": list(state["produced_outputs"]),
            }
            _write_json(mission_state_path, state)
            runtime_root = test_root / "recursive-runtime"
            return {
                "status": "max-iterations",
                "runtime_root": runtime_root,
                "state_path": runtime_root / "agent_loop_state.json",
                "memory_path": runtime_root / "loop_memory.jsonl",
                "latest_iteration_path": runtime_root / "iteration-07",
                "latest_result_path": runtime_root / "iteration-07" / "result.json",
                "report_json_path": runtime_root / "report.json",
                "report_markdown_path": runtime_root / "report.md",
                "latest_outcome": {
                    "phase_control": {"current_phase": "final-report", "next_phase": "final-report"},
                    "action_result": {"mission_action_id": "delegate-execution", "status": "completed"},
                },
            }

        mock_run_recursive_agent_loop.side_effect = _fake_recursive_runtime

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "completed")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["current_phase"], "final-report")
        self.assertEqual(mission_state["status"], "completed")
        self.assertEqual(mission_state["next_actions"]["actions"][0]["status"], "completed")

    @patch("deeploop.mission.mission_runtime._invoke_followup_planner")
    @patch("deeploop.runtime.mission_executor_registry.run_self_healing_queue")
    def test_runtime_auto_stages_followups_after_bootstrap_queue(
        self,
        mock_run_self_healing_queue,
        mock_invoke_followup_planner,
    ) -> None:
        test_root = _fresh_test_root("auto_stages_followups_after_bootstrap_queue")
        mission_state_path = test_root / "mission" / "mission_state.json"
        queue_config_path = test_root / "baseline_queue.yaml"
        queue_config_path.write_text("queue: test\n", encoding="utf-8")
        _write_json(
            mission_state_path,
            {
                **_base_state(
                    mission_id="mission-runtime-bootstrap",
                    current_phase="execution",
                    next_phase="critique",
                    actions=[],
                ),
                "status": "initialized",
                "bootstrap": {
                    "status": "pending-baseline-execution",
                    "followup_planner": {
                        "entrypoint": "demo_followup:stage_followups",
                        "params": {
                            "baseline_queue_config": str(queue_config_path),
                        },
                    },
                },
                "phase_execution_hints": {
                    "execution": {
                        "executor": {
                            "id": "self-healing-queue",
                            "params": {"config_path": str(queue_config_path)},
                        },
                        "produces_outputs": ["run logs", "metrics", "crash / stability notes"],
                    }
                },
            },
        )
        mock_run_self_healing_queue.return_value = {
            "completed_jobs": 2,
            "blocked_jobs": 0,
            "warned_jobs": 0,
            "failed_jobs": 0,
            "recovered_jobs": 0,
            "rerouted_jobs": 0,
            "resumed_jobs": 0,
            "ledger_path": test_root / "queue_ledger.jsonl",
            "runtime_report_path": test_root / "queue_report.json",
        }

        def _fake_advance(state_path: Path, _mission_state: dict, _bootstrap: dict) -> dict:
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            state["status"] = "running"
            state["autonomy_status"] = {
                "state": "mission-runtime-ready",
                "reason": "Behavioral baselines and findings exist; canonical follow-up staging is ready.",
            }
            state["next_actions"] = {
                "summary": "Follow-up staging is ready.",
                "actions": [
                    {
                        "action_id": "critique-anchor-run",
                        "role": "critic-verifier",
                        "task": "Critique the repaired anchor run.",
                        "kind": "critique",
                        "status": "pending",
                        "phase": "critique",
                    }
                ],
            }
            state["canonical_followup_runtime"] = {"followup_queue_path": str(queue_config_path)}
            Path(state_path).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            return {"followup_queue_path": queue_config_path, "generated_configs": []}

        mock_invoke_followup_planner.side_effect = _fake_advance

        result = run_mission(mission_state_path, max_iterations=1)

        self.assertEqual(result["status"], "max-iterations")
        mock_run_self_healing_queue.assert_called_once()
        mock_invoke_followup_planner.assert_called_once()
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["bootstrap"]["status"], "followup-staged")
        self.assertIn("canonical_followup_runtime", mission_state)
        self.assertEqual(mission_state["runtime_recovery"]["completed_jobs"], 2)
        self.assertEqual(mission_state["next_actions"]["actions"][0]["action_id"], "critique-anchor-run")

    @patch("deeploop.runtime.mission_executor_registry.package_mission_artifacts")
    @patch("deeploop.runtime.mission_executor_registry.run_stage_from_config")
    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_runtime_completes_init_state_via_phase_execution_hints(
        self,
        mock_run_recursive_agent_loop,
        mock_run_stage_from_config,
        mock_package_mission_artifacts,
    ) -> None:
        test_root = _fresh_test_root("completes_init_state_via_phase_hints")
        mission_state_path = test_root / "mission" / "mission_state.json"
        recursive_config_path = test_root / "runtime" / "phase-loop.yaml"
        recursive_config_path.parent.mkdir(parents=True, exist_ok=True)
        recursive_config_path.write_text("mission_state: placeholder\n", encoding="utf-8")
        _write_json(
            mission_state_path,
            {
                "mission_id": "mission-runtime-init-hints",
                "mode": "sandboxed-yolo",
                "title": "Tiny Asym init proof",
                "summary": "Exercise the init-driven lifecycle through phase execution hints.",
                "objective": "Run a tiny mission from init through final-report.",
                "current_phase": "idea-intake",
                "next_phase": "literature-review",
                "status": "initialized",
                "target_repo": str(REPO_ROOT),
                "completed_phases": [],
                "phase_history": ["idea-intake"],
                "roles": [
                    "planner",
                    "literature-scout",
                    "dataset-strategist",
                    "experiment-designer",
                    "execution-operator",
                    "critic-verifier",
                    "report-synthesizer",
                ],
                "next_actions": {},
                "phase_execution_hints": {
                    "idea-intake": {"executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}}},
                    "literature-review": {"executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}}},
                    "question-design": {
                        "executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}},
                        "next_phase_on_success": "benchmark-selection",
                    },
                    "benchmark-selection": {"executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}}},
                    "experiment-design": {"executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}}},
                    "execution": {
                        "executor": {
                            "id": "stage-kernel",
                            "params": {"stage_id": "baseline-evaluation", "config_path": str(test_root / "baseline.yaml")},
                        }
                    },
                    "critique": {
                        "executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}},
                        "next_phase_on_success": "replication",
                    },
                    "replication": {
                        "executor": {
                            "id": "stage-kernel",
                            "params": {"stage_id": "baseline-evaluation", "config_path": str(test_root / "replication.yaml")},
                        },
                        "next_phase_on_success": "final-report",
                    },
                    "final-report": {
                        "executor": {
                            "id": "report-synthesis",
                            "params": {"mission_state_path": str(mission_state_path)},
                        }
                    },
                },
                "autonomy_status": {"state": "initialized", "reason": "test"},
            },
        )

        def _fake_recursive_runtime(config_path: Path) -> dict:
            state = json.loads(mission_state_path.read_text(encoding="utf-8"))
            phase = state["current_phase"]
            outputs_by_phase = {
                "idea-intake": ["mission brief", "rough constraints"],
                "literature-review": ["prior-art memo", "benchmark and method watchlist"],
                "question-design": ["hypotheses", "evaluation targets"],
                "benchmark-selection": ["dataset shortlist", "slice plan"],
                "experiment-design": ["run manifest draft", "execution profile selection", "resource tier selection"],
                "critique": ["evidence assessment", "confound notes", "next-step recommendation"],
            }
            next_phase = {
                "question-design": "benchmark-selection",
                "critique": "replication",
            }.get(phase, state.get("next_phase"))
            runtime_root = test_root / "recursive-runtime" / phase
            runtime_root.mkdir(parents=True, exist_ok=True)
            return {
                "status": "completed",
                "runtime_root": runtime_root,
                "state_path": runtime_root / "agent_loop_state.json",
                "memory_path": runtime_root / "loop_memory.jsonl",
                "latest_iteration_path": runtime_root / "iteration-01",
                "latest_result_path": runtime_root / "iteration-01" / "result.json",
                "report_json_path": runtime_root / "report.json",
                "report_markdown_path": runtime_root / "report.md",
                "produced_outputs": outputs_by_phase[phase],
                "latest_outcome": {
                    "phase_control": {"current_phase": phase, "next_phase": next_phase},
                    "action_result": {
                        "mission_action_id": f"mission-runtime-init-hints-{phase}-missing-outputs",
                        "output_paths": [],
                    },
                },
            }

        mock_run_recursive_agent_loop.side_effect = _fake_recursive_runtime

        def _fake_stage_run(stage_id: str, config_path: Path, **_: object) -> KernelRunResult:
            output_dir = test_root / "stage-runs" / Path(config_path).stem
            output_dir.mkdir(parents=True, exist_ok=True)
            return KernelRunResult(
                stage_id=stage_id,
                status="completed",
                output_dir=output_dir,
                manifest_path=output_dir / "study_manifest.json",
                summary_path=output_dir / "summary.json",
                artifacts={"metrics": output_dir / "metrics.json"},
            )

        mock_run_stage_from_config.side_effect = _fake_stage_run
        package_root = test_root / "package"
        package_root.mkdir(parents=True, exist_ok=True)
        mock_package_mission_artifacts.return_value = {
            "package_root": package_root,
            "manifest_path": package_root / "mission_artifact_package.json",
            "summary_path": package_root / "mission_artifact_package.md",
            "produced_outputs": ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        }

        result = run_mission(mission_state_path, max_iterations=20)

        self.assertEqual(result["status"], "completed")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["status"], "completed")
        self.assertEqual(mission_state["current_phase"], "final-report")
        self.assertIn("replication", mission_state["completed_phases"])
        self.assertEqual(mission_state["operator_inbox"]["status"], "clear")
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["final-report"],
            ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        )
        mission_memory = json.loads((mission_state_path.parent / "mission_memory.json").read_text(encoding="utf-8"))
        self.assertTrue(mock_run_recursive_agent_loop.called)
        self.assertEqual(mock_run_stage_from_config.call_count, 2)
        self.assertEqual(mock_package_mission_artifacts.call_count, 2)
        self.assertEqual(mission_memory["latest_experiment"]["status"], "completed")

    @patch("deeploop.runtime.mission_executor_registry.package_mission_artifacts")
    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_runtime_completes_generic_plain_folder_lifecycle_via_recursive_agent_hints(
        self,
        mock_run_recursive_agent_loop,
        mock_package_mission_artifacts,
    ) -> None:
        test_root = _fresh_test_root("completes_plain_folder_recursive_lifecycle")
        mission_state_path = test_root / "mission" / "mission_state.json"
        recursive_config_path = test_root / "runtime" / "phase-loop.yaml"
        recursive_config_path.parent.mkdir(parents=True, exist_ok=True)
        recursive_config_path.write_text("mission_state: placeholder\n", encoding="utf-8")
        _write_json(
            mission_state_path,
            {
                "mission_id": "mission-runtime-plain-folder-defaults",
                "mode": "sandboxed-yolo",
                "title": "Plain folder lifecycle proof",
                "summary": "Exercise the generic recursive-agent lifecycle through all default plain-folder phases.",
                "objective": "Run a generic mission from init through final-report using recursive-agent phase hints.",
                "current_phase": "idea-intake",
                "next_phase": "literature-review",
                "status": "initialized",
                "target_repo": str(REPO_ROOT),
                "completed_phases": [],
                "phase_history": ["idea-intake"],
                "roles": [
                    "planner",
                    "literature-scout",
                    "dataset-strategist",
                    "experiment-designer",
                    "execution-operator",
                    "critic-verifier",
                    "report-synthesizer",
                ],
                "next_actions": {},
                "phase_execution_hints": {
                    "idea-intake": {"executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}}},
                    "literature-review": {"executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}}},
                    "question-design": {
                        "executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}},
                        "next_phase_on_success": "benchmark-selection",
                    },
                    "benchmark-selection": {"executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}}},
                    "experiment-design": {"executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}}},
                    "execution": {
                        "executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}},
                        "next_phase_on_success": "critique",
                    },
                    "critique": {
                        "executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}},
                        "next_phase_on_success": "replication",
                    },
                    "replication": {
                        "executor": {"id": "recursive-agent", "params": {"config_path": str(recursive_config_path)}},
                        "next_phase_on_success": "final-report",
                    },
                    "final-report": {
                        "executor": {
                            "id": "report-synthesis",
                            "params": {"mission_state_path": str(mission_state_path)},
                        }
                    },
                },
                "autonomy_status": {"state": "initialized", "reason": "test"},
            },
        )

        def _fake_recursive_runtime(config_path: Path) -> dict:
            state = json.loads(mission_state_path.read_text(encoding="utf-8"))
            phase = state["current_phase"]
            outputs_by_phase = {
                "idea-intake": ["mission brief", "rough constraints"],
                "literature-review": ["prior-art memo", "benchmark and method watchlist"],
                "question-design": ["hypotheses", "evaluation targets"],
                "benchmark-selection": ["dataset shortlist", "slice plan"],
                "experiment-design": ["run manifest draft", "execution profile selection", "resource tier selection"],
                "execution": ["run logs", "metrics", "crash / stability notes"],
                "critique": ["evidence assessment", "confound notes", "next-step recommendation"],
                "replication": ["repeated-run manifests", "replication summary"],
            }
            next_phase = {
                "question-design": "benchmark-selection",
                "execution": "critique",
                "critique": "replication",
                "replication": "final-report",
            }.get(phase, state.get("next_phase"))
            runtime_root = test_root / "recursive-runtime" / phase
            runtime_root.mkdir(parents=True, exist_ok=True)
            return {
                "status": "completed",
                "runtime_root": runtime_root,
                "state_path": runtime_root / "agent_loop_state.json",
                "memory_path": runtime_root / "loop_memory.jsonl",
                "latest_iteration_path": runtime_root / "iteration-01",
                "latest_result_path": runtime_root / "iteration-01" / "result.json",
                "report_json_path": runtime_root / "report.json",
                "report_markdown_path": runtime_root / "report.md",
                "produced_outputs": outputs_by_phase[phase],
                "latest_outcome": {
                    "phase_control": {"current_phase": phase, "next_phase": next_phase},
                    "action_result": {
                        "mission_action_id": f"mission-runtime-plain-folder-defaults-{phase}-missing-outputs",
                        "output_paths": [],
                    },
                },
            }

        mock_run_recursive_agent_loop.side_effect = _fake_recursive_runtime
        package_root = test_root / "package"
        package_root.mkdir(parents=True, exist_ok=True)
        mock_package_mission_artifacts.return_value = {
            "package_root": package_root,
            "manifest_path": package_root / "mission_artifact_package.json",
            "summary_path": package_root / "mission_artifact_package.md",
            "produced_outputs": ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        }

        result = run_mission(mission_state_path, max_iterations=20)

        self.assertEqual(result["status"], "completed")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["status"], "completed")
        self.assertEqual(mission_state["current_phase"], "final-report")
        self.assertIn("replication", mission_state["completed_phases"])
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["execution"],
            ["run logs", "metrics", "crash / stability notes"],
        )
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["replication"],
            ["repeated-run manifests", "replication summary"],
        )
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["final-report"],
            ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        )
        self.assertGreaterEqual(mock_run_recursive_agent_loop.call_count, 7)
        self.assertEqual(mock_package_mission_artifacts.call_count, 2)

    @patch("deeploop.runtime.mission_executor_registry.run_adaptation_training")
    def test_runtime_integrates_adaptation_training_executor(self, mock_run_adaptation_training) -> None:
        test_root = _fresh_test_root("integrates_adaptation_training_executor")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-placeholder",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "train-adapter",
                        "role": "execution-operator",
                        "task": "Run the bounded adaptation step.",
                        "kind": "local-training",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "adaptation-training",
                            "params": {"training_config_path": "configs/runtime/train.yaml"},
                        },
                    }
                ],
            ),
        )
        runtime_root = test_root / "adaptation"
        mock_run_adaptation_training.return_value = {
            "status": "completed",
            "summary": "Adapted artifact `keep` against the best prior anchor `intervention` on `accuracy` with route `replication`.",
            "runtime_root": runtime_root,
            "train_job_path": runtime_root / "train_job.json",
            "eval_job_path": runtime_root / "evaluate_job.json",
            "report_json_path": runtime_root / "report.json",
            "report_markdown_path": runtime_root / "report.md",
            "comparison_path": runtime_root / "comparison.json",
            "training_log_path": runtime_root / "train.log",
            "evaluation_log_path": runtime_root / "evaluate.log",
            "adapter_artifact_path": runtime_root / "adapter.bin",
            "evaluation_metrics_path": runtime_root / "eval_metrics.json",
            "comparison": {"decision": "keep", "route_to": "replication"},
            "produced_outputs": [
                "adapted artifact",
                "post-adaptation evaluation",
                "keep/discard adaptation comparison",
            ],
            "mission_state_updates": {
                "adaptation_training": {"decision": "keep", "route_to": "replication"},
            },
        }

        result = run_mission(mission_state_path, max_iterations=1)

        self.assertEqual(result["status"], "max-iterations")
        self.assertEqual(result["iterations_completed"], 1)
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["status"], "paused")
        self.assertEqual(mission_state["next_actions"]["actions"][0]["status"], "completed")
        self.assertEqual(mission_state["adaptation_training"]["comparison"]["decision"], "keep")
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["execution"],
            [
                "adapted artifact",
                "post-adaptation evaluation",
                "keep/discard adaptation comparison",
            ],
        )

    @patch("deeploop.runtime.mission_executor_registry.run_adaptation_training")
    def test_runtime_blocks_when_adaptation_runtime_reports_blocked(self, mock_run_adaptation_training) -> None:
        test_root = _fresh_test_root("blocks_adaptation_executor")
        mission_state_path = test_root / "mission" / "mission_state.json"
        gate_event = {
            "gate": "hard",
            "status": "blocked",
            "risk_class": "sandbox-boundary",
            "label": "sandbox escape / writes outside allowed mutable roots",
            "reason": "adaptation output root escapes the allowed mutable roots",
            "default_response": "stop-and-escalate",
            "preferred_actions": [],
            "hard_gate_profile": "minimal",
        }
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-adaptation-blocked",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "train-adapter",
                        "role": "execution-operator",
                        "task": "Run the bounded adaptation step.",
                        "kind": "local-training",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "adaptation-training",
                            "params": {"training_config_path": "configs/runtime/train.yaml"},
                        },
                    }
                ],
            ),
        )
        mock_run_adaptation_training.return_value = {
            "status": "blocked",
            "summary": "Adaptation training blocked: adaptation output root escapes the allowed mutable roots.",
            "runtime_root": test_root / "adaptation",
            "train_job_path": test_root / "adaptation" / "train_job.json",
            "eval_job_path": test_root / "adaptation" / "evaluate_job.json",
            "report_json_path": test_root / "adaptation" / "report.json",
            "report_markdown_path": test_root / "adaptation" / "report.md",
            "comparison_path": test_root / "adaptation" / "comparison.json",
            "training_log_path": test_root / "adaptation" / "train.log",
            "evaluation_log_path": test_root / "adaptation" / "evaluate.log",
            "adapter_artifact_path": test_root / "adaptation" / "adapter.bin",
            "evaluation_metrics_path": test_root / "adaptation" / "eval_metrics.json",
            "comparison": None,
            "produced_outputs": [],
            "gate_event": gate_event,
            "mission_state_updates": {
                "blocked_reasons": ["adaptation output root escapes the allowed mutable roots"],
                "adaptation_training": {"status": "blocked", "gate_event": gate_event},
            },
        }

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "blocked")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["status"], "blocked")
        self.assertEqual(mission_state["next_actions"]["actions"][0]["status"], "blocked")
        self.assertIn("Adaptation training blocked", mission_state["autonomy_status"]["reason"])
        operator_request = json.loads(
            (mission_state_path.parent / "current_operator_request.json").read_text(encoding="utf-8")
        )
        self.assertEqual(operator_request["blocker"]["kind"], "hard-gate")
        self.assertEqual(operator_request["blocker"]["risk_class"], "sandbox-boundary")
        self.assertEqual(
            operator_request["continue_command"],
            f"deeploop resume --mission-state {mission_state_path}",
        )
        operator_history = [
            json.loads(line)
            for line in (mission_state_path.parent / "mission_operator_requests.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(operator_history), 1)
        self.assertEqual(operator_history[0]["request_id"], operator_request["request_id"])

    @patch("deeploop.runtime.mission_executor_registry.run_adaptation_training")
    def test_runtime_keeps_soft_gate_deferrals_out_of_operator_inbox(self, mock_run_adaptation_training) -> None:
        test_root = _fresh_test_root("soft_gate_deferral")
        mission_state_path = test_root / "mission" / "mission_state.json"
        gate_event = {
            "gate": "soft",
            "status": "deferred",
            "risk_class": "budget-overrun",
            "label": "budget / resource pressure",
            "reason": "bounded runtime budget should be downscoped before retrying adaptation training",
            "default_response": "downscope-reroute-retry",
            "preferred_actions": ["downscope", "reroute", "retry"],
            "hard_gate_profile": "minimal",
        }
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-soft-gate",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "train-adapter",
                        "role": "execution-operator",
                        "task": "Run the bounded adaptation step.",
                        "kind": "local-training",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "adaptation-training",
                            "params": {"training_config_path": "configs/runtime/train.yaml"},
                        },
                    }
                ],
            ),
        )
        mock_run_adaptation_training.return_value = {
            "status": "deferred",
            "summary": "Adaptation training soft-gated: bounded runtime budget should be downscoped before retrying adaptation training.",
            "runtime_root": test_root / "adaptation",
            "train_job_path": test_root / "adaptation" / "train_job.json",
            "eval_job_path": test_root / "adaptation" / "evaluate_job.json",
            "report_json_path": test_root / "adaptation" / "report.json",
            "report_markdown_path": test_root / "adaptation" / "report.md",
            "comparison_path": test_root / "adaptation" / "comparison.json",
            "training_log_path": test_root / "adaptation" / "train.log",
            "evaluation_log_path": test_root / "adaptation" / "evaluate.log",
            "adapter_artifact_path": test_root / "adaptation" / "adapter.bin",
            "evaluation_metrics_path": test_root / "adaptation" / "eval_metrics.json",
            "comparison": None,
            "gate_event": gate_event,
            "produced_outputs": [],
            "mission_state_updates": {
                "soft_gate_events": [gate_event],
                "adaptation_training": {"status": "deferred", "gate_event": gate_event},
            },
        }

        result = run_mission(mission_state_path, max_iterations=1)

        self.assertEqual(result["status"], "max-iterations")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["status"], "paused")
        self.assertEqual(mission_state["next_actions"]["actions"][0]["status"], "deferred")
        self.assertEqual(mission_state["soft_gate_events"][0]["risk_class"], "budget-overrun")
        self.assertEqual(
            json.loads((mission_state_path.parent / "current_operator_request.json").read_text(encoding="utf-8")),
            {},
        )
        self.assertEqual(
            (mission_state_path.parent / "mission_operator_requests.jsonl").read_text(encoding="utf-8").strip(),
            "",
        )
        runtime_summary = json.loads(result["summary_json_path"].read_text(encoding="utf-8"))
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["counts"]["soft_gates_total"], 1)
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["counts"]["operator_requests_total"], 0)
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["recovery_preferences"]["downscope"], 1)
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["counts"]["temporary_gap_auto_recovered"], 1)
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["counts"]["temporary_gap_escalated"], 0)
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["temporary_gap_categories"]["budget-overrun"], 1)
        rendered_summary = result["summary_markdown_path"].read_text(encoding="utf-8")
        self.assertIn("soft_gates_total: `1`", rendered_summary)
        self.assertIn("operator_requests_total: `0`", rendered_summary)
        self.assertIn("temporary_gap_auto_recovered: `1`", rendered_summary)
        self.assertIn("temporary_gap_categories: budget-overrun=1", rendered_summary)

    @patch("deeploop.runtime.mission_executor_registry.run_adaptation_training")
    def test_runtime_stages_managed_recovery_after_soft_gate_deferral(self, mock_run_adaptation_training) -> None:
        test_root = _fresh_test_root("managed_soft_gate_recovery")
        mission_state_path = test_root / "mission" / "mission_state.json"
        gate_event = {
            "gate": "soft",
            "status": "deferred",
            "risk_class": "budget-overrun",
            "label": "budget / resource pressure",
            "reason": "bounded runtime budget should be downscoped before retrying adaptation training",
            "default_response": "downscope-reroute-retry",
            "preferred_actions": ["downscope", "reroute", "retry"],
            "hard_gate_profile": "minimal",
        }
        mission_state = _base_state(
            mission_id="mission-runtime-managed-soft-gate",
            current_phase="execution",
            next_phase="critique",
            actions=[
                {
                    "action_id": "adapt-model",
                    "role": "execution-operator",
                    "task": "Run the bounded adaptation step.",
                    "kind": "local-training",
                    "status": "pending",
                    "phase": "execution",
                    "runtime_owner": "deeploop",
                    "requires_operator_approval": False,
                    "executor": {
                        "id": "adaptation-training",
                        "params": {"training_config_path": "configs/runtime/train.yaml"},
                    },
                }
            ],
        )
        mission_state["mode"] = "managed"
        _write_json(mission_state_path, mission_state)
        mock_run_adaptation_training.return_value = {
            "status": "deferred",
            "summary": "Adaptation training soft-gated: bounded runtime budget should be downscoped before retrying adaptation training.",
            "runtime_root": test_root / "adaptation",
            "train_job_path": test_root / "adaptation" / "train_job.json",
            "eval_job_path": test_root / "adaptation" / "evaluate_job.json",
            "report_json_path": test_root / "adaptation" / "report.json",
            "report_markdown_path": test_root / "adaptation" / "report.md",
            "comparison_path": test_root / "adaptation" / "comparison.json",
            "training_log_path": test_root / "adaptation" / "train.log",
            "evaluation_log_path": test_root / "adaptation" / "evaluate.log",
            "adapter_artifact_path": test_root / "adaptation" / "adapter.bin",
            "evaluation_metrics_path": test_root / "adaptation" / "eval_metrics.json",
            "comparison": None,
            "gate_event": gate_event,
            "produced_outputs": [],
            "mission_state_updates": {
                "soft_gate_events": [gate_event],
                "adaptation_training": {"status": "deferred", "gate_event": gate_event},
            },
        }

        result = run_mission(mission_state_path, max_iterations=1)

        self.assertEqual(result["status"], "max-iterations")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["automatic_recovery"]["action"], "downscope")
        self.assertEqual(mission_state["automatic_recovery"]["source"], "soft-gate")
        staged_actions = {action["action_id"]: action for action in mission_state["next_actions"]["actions"]}
        self.assertIn("adapt-model-downscope-managed-recovery", staged_actions)
        self.assertEqual(staged_actions["adapt-model-downscope-managed-recovery"]["status"], "pending")
        self.assertEqual(staged_actions["adapt-model-downscope-managed-recovery"]["role"], "planner")
        self.assertEqual(
            json.loads((mission_state_path.parent / "current_operator_request.json").read_text(encoding="utf-8")),
            {},
        )

    @patch("deeploop.runtime.mission_executor_registry.run_self_healing_queue")
    def test_runtime_surfaces_blocked_queue_entry_details_in_operator_request(self, mock_run_self_healing_queue) -> None:
        test_root = _fresh_test_root("blocked_queue_entry_details")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-queue-block",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "run-followup-queue",
                        "role": "execution-operator",
                        "task": "Run the follow-up queue.",
                        "kind": "local-eval",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "self-healing-queue",
                            "params": {"config_path": "configs/runtime/demo-queue.yaml"},
                        },
                    }
                ],
            ),
        )
        mock_run_self_healing_queue.return_value = {
            "completed_jobs": 1,
            "blocked_jobs": 1,
            "failed_jobs": 0,
            "queue_name": "demo-queue",
            "blocked_entries": [
                {
                    "entry_id": "blocked-followup",
                    "queue_name": "demo-queue",
                    "summary_json_path": str(test_root / "runtime" / "summary.json"),
                    "summary_markdown_path": str(test_root / "runtime" / "summary.md"),
                    "sanity_verdict": "block",
                    "top_blocking_reasons": [
                        "Reference manifest is too weak for a trustworthy comparison.",
                        "Evaluation anchors are insufficient.",
                    ],
                }
            ],
            "ledger_path": test_root / "mission" / "ledger.jsonl",
            "runtime_report_path": test_root / "runtime" / "queue_summary.json",
            "runtime_report_markdown_path": test_root / "runtime" / "queue_summary.md",
        }

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "blocked")
        operator_request = json.loads((mission_state_path.parent / "current_operator_request.json").read_text(encoding="utf-8"))
        self.assertIn("blocked-followup", operator_request["summary"])
        self.assertIn("Reference manifest is too weak", operator_request["blocker"]["reason"])
        self.assertEqual(operator_request["context"]["blocked_entries"][0]["queue_name"], "demo-queue")
        runtime_summary = json.loads(result["summary_json_path"].read_text(encoding="utf-8"))
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["counts"]["operator_requests_total"], 1)
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["counts"]["temporary_gap_requests"], 1)
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["counts"]["unresolved_temporary_gaps"], 1)
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["counts"]["temporary_gap_auto_recovered"], 0)
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["counts"]["temporary_gap_escalated"], 1)
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["latest_temporary_gap"]["kind"], "operator-review")
        self.assertEqual(runtime_summary["autonomy_gap_telemetry"]["temporary_gap_categories"]["blocked-queue-entry-review"], 1)
        rendered_summary = result["summary_markdown_path"].read_text(encoding="utf-8")
        self.assertIn("temporary_gap_requests: `1`", rendered_summary)
        self.assertIn("latest_temporary_gap: `operator-review`", rendered_summary)
        self.assertIn("temporary_gap_escalated: `1`", rendered_summary)
        self.assertIn("temporary_gap_categories: blocked-queue-entry-review=1", rendered_summary)

    @patch("deeploop.mission.mission_runtime.subprocess.run")
    @patch("deeploop.runtime.mission_executor_registry.run_self_healing_queue")
    def test_runtime_surfaces_bounded_triage_command_for_managed_blocked_queue(
        self,
        mock_run_self_healing_queue,
        mock_bounded_triage_run,
    ) -> None:
        test_root = _fresh_test_root("managed_blocked_queue_triage")
        mission_state_path = test_root / "mission" / "mission_state.json"
        mission_state = _base_state(
            mission_id="mission-runtime-managed-queue-block",
            current_phase="execution",
            next_phase="critique",
            actions=[
                {
                    "action_id": "run-followup-queue",
                    "role": "execution-operator",
                    "task": "Run the follow-up queue.",
                    "kind": "local-eval",
                    "status": "pending",
                    "phase": "execution",
                    "runtime_owner": "deeploop",
                    "requires_operator_approval": False,
                    "executor": {
                        "id": "self-healing-queue",
                        "params": {"config_path": "configs/runtime/demo-queue.yaml"},
                    },
                }
            ],
        )
        mission_state["mode"] = "managed"
        _write_json(mission_state_path, mission_state)
        def _fake_triage_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            result_path = Path(command[command.index("--result-json-path") + 1])
            _write_json(
                result_path,
                {
                    "status": "completed",
                    "summary": "The blocked queue entry should be rerouted inside the managed boundary.",
                    "recommended_operator_action": "reroute",
                    "recommended_resume_action": "Record a reroute before resume.",
                    "findings": ["The intervention follow-up is the only blocked branch."],
                    "evidence_paths": [str(test_root / "runtime" / "summary.json")],
                    "notes": ["Stay inside the current managed-mode boundary."],
                },
            )
            return subprocess.CompletedProcess(command, 0, "triage complete\n", "")

        mock_bounded_triage_run.side_effect = _fake_triage_run
        mock_run_self_healing_queue.return_value = {
            "completed_jobs": 0,
            "blocked_jobs": 1,
            "failed_jobs": 0,
            "queue_name": "demo-queue",
            "blocked_entries": [
                {
                    "entry_id": "blocked-followup",
                    "queue_name": "demo-queue",
                    "summary_json_path": str(test_root / "runtime" / "summary.json"),
                    "summary_markdown_path": str(test_root / "runtime" / "summary.md"),
                    "sanity_verdict": "block",
                    "top_blocking_reasons": ["Need richer evidence before intervention."],
                }
            ],
            "ledger_path": test_root / "mission" / "ledger.jsonl",
            "runtime_report_path": test_root / "runtime" / "queue_summary.json",
            "runtime_report_markdown_path": test_root / "runtime" / "queue_summary.md",
        }

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "blocked")
        operator_request = json.loads((mission_state_path.parent / "current_operator_request.json").read_text(encoding="utf-8"))
        self.assertEqual(operator_request["auto_triage"]["recommended_operator_action"], "reroute")
        self.assertIn("automatic bounded triage recommends `reroute`", operator_request["recommendation"]["summary"])
        self.assertIn("Managed mode staged `reroute`", operator_request["recommendation"]["summary"])
        self.assertIn("run-followup-queue-reroute-managed-recovery", operator_request["explanation"])
        self.assertIn("deeploop triage", operator_request["next_steps"][0])
        self.assertEqual(operator_request["alternatives"][0]["option_id"], "bounded-triage")
        updated_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            updated_state["automatic_bounded_triage"]["result"]["recommended_operator_action"],
            "reroute",
        )
        self.assertEqual(updated_state["automatic_recovery"]["action"], "reroute")
        staged_actions = {action["action_id"]: action for action in updated_state["next_actions"]["actions"]}
        self.assertIn("run-followup-queue-reroute-managed-recovery", staged_actions)
        self.assertEqual(staged_actions["run-followup-queue-reroute-managed-recovery"]["status"], "pending")

    @patch("deeploop.runtime.mission_executor_registry.run_stage_from_config")
    def test_runtime_records_executor_exceptions_as_failed(self, mock_run_stage_from_config) -> None:
        test_root = _fresh_test_root("records_executor_exceptions")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            _base_state(
                mission_id="mission-runtime-failure",
                current_phase="execution",
                next_phase="critique",
                actions=[
                    {
                        "action_id": "run-broken-stage",
                        "role": "execution-operator",
                        "task": "Run the broken bounded stage.",
                        "kind": "local-eval",
                        "status": "pending",
                        "phase": "execution",
                        "runtime_owner": "deeploop",
                        "requires_operator_approval": False,
                        "executor": {
                            "id": "stage-kernel",
                            "params": {
                                "stage_id": "baseline-evaluation",
                                "config_path": "configs/runtime/demo-stage.yaml",
                            },
                        },
                    }
                ],
            ),
        )
        mock_run_stage_from_config.side_effect = RuntimeError("boom")

        result = run_mission(mission_state_path, max_iterations=2)

        self.assertEqual(result["status"], "failed")
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["status"], "failed")
        self.assertEqual(mission_state["next_actions"]["actions"][0]["status"], "blocked")
        self.assertEqual(mission_state["failure_count"], 1)
        self.assertIn("RuntimeError", mission_state["autonomy_status"]["reason"])

    @patch("deeploop.runtime.mission_executor_registry.package_mission_artifacts")
    @patch("deeploop.runtime.mission_executor_registry.evaluate_self_correction")
    @patch("deeploop.runtime.mission_executor_registry.run_stage_from_config")
    def test_runtime_completes_multi_phase_mission_via_canonical_outer_loop(
        self,
        mock_run_stage_from_config,
        mock_evaluate_self_correction,
        mock_package_mission_artifacts,
    ) -> None:
        test_root = _fresh_test_root("completes_multi_phase_mission_via_canonical_outer_loop")
        mission_state_path = test_root / "mission" / "mission_state.json"
        _write_json(
            mission_state_path,
            {
                **_base_state(
                    mission_id="mission-runtime-end-to-end",
                    current_phase="execution",
                    next_phase="critique",
                    actions=[
                        {
                            "action_id": "run-followups",
                            "role": "execution-operator",
                            "task": "Run the bounded follow-up queue.",
                            "kind": "local-eval",
                            "status": "pending",
                            "phase": "execution",
                            "runtime_owner": "deeploop",
                            "requires_operator_approval": False,
                            "executor": {
                                "id": "stage-kernel",
                                "params": {
                                    "stage_id": "mechanistic-localization",
                                    "config_path": "configs/runtime/demo-stage.yaml",
                                },
                            },
                            "produces_outputs": ["run logs", "metrics", "crash / stability notes"],
                        },
                        {
                            "action_id": "decide-replication-readiness",
                            "role": "critic-verifier",
                            "task": "Compare the bounded follow-up evidence and decide the next mission promotion.",
                            "kind": "replication",
                            "status": "pending",
                            "phase": "critique",
                            "runtime_owner": "deeploop",
                            "requires_operator_approval": False,
                            "executor": {
                                "id": "evaluation-comparison",
                                "params": {
                                    "mission_state_path": str(mission_state_path),
                                    "manifest_paths": [str(test_root / "runs" / "followup_manifest.json")],
                                    "run_roots": [str(test_root / "runs")],
                                    "artifact_name": "mission-runtime-proof",
                                },
                            },
                            "produces_outputs": [
                                "evidence assessment",
                                "confound notes",
                                "next-step recommendation",
                            ],
                        },
                        {
                            "action_id": "assemble-final-report",
                            "role": "report-synthesizer",
                            "task": "Assemble the mission-level final report package.",
                            "kind": "final-report",
                            "status": "pending",
                            "phase": "final-report",
                            "runtime_owner": "deeploop",
                            "requires_operator_approval": False,
                            "executor": {
                                "id": "report-synthesis",
                                "params": {"mission_state_path": str(mission_state_path)},
                            },
                            "produces_outputs": [
                                "findings summary",
                                "paper-candidate recommendation",
                                "artifact readiness notes",
                            ],
                        },
                    ],
                ),
                "completion_contract": {
                    "replication_requirement": "waived",
                    "replication_waiver_reason": (
                        "Canonical outer-loop test routes directly from critique to final-report and records the "
                        "remaining replication gap in the final package."
                    ),
                },
            },
        )
        mission_summary_path = mission_state_path.parent / "mission_summary.md"
        mission_summary_path.write_text(
            "\n".join(
                [
                    "# Mission summary",
                    "",
                    "- current_phase: `idea-intake`",
                    "- status: `initialized`",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        output_dir = test_root / "stage-run"
        mock_run_stage_from_config.return_value = KernelRunResult(
            stage_id="mechanistic-localization",
            status="completed",
            output_dir=output_dir,
            manifest_path=output_dir / "study_manifest.json",
            summary_path=output_dir / "summary.json",
            artifacts={"metrics": output_dir / "metrics.json"},
        )
        mock_evaluate_self_correction.return_value = {
            "report_json_path": test_root / "self_correction" / "report.json",
            "report_markdown_path": test_root / "self_correction" / "report.md",
            "final_decision": {"action": "continue", "route_to": "final-report"},
            "phase_control": {"current_phase": "final-report", "next_phase": "final-report"},
            "recommendations": [],
        }
        package_state_snapshots: list[tuple[str | None, str | None]] = []

        def _fake_package_refresh(state_path: Path, **_: object) -> dict[str, object]:
            state_snapshot = json.loads(state_path.read_text(encoding="utf-8"))
            autonomy = state_snapshot.get("autonomy_status") if isinstance(state_snapshot.get("autonomy_status"), dict) else {}
            package_state_snapshots.append(
                (
                    state_snapshot.get("status"),
                    autonomy.get("state"),
                )
            )
            return {
                "package_root": test_root / "package",
                "manifest_path": test_root / "package" / "mission_artifact_package.json",
                "summary_path": test_root / "package" / "mission_artifact_package.md",
                "package": {},
            }

        mock_package_mission_artifacts.side_effect = _fake_package_refresh

        result = run_mission(mission_state_path, max_iterations=5)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["iterations_completed"], 5)
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["current_phase"], "final-report")
        self.assertEqual(mission_state["status"], "completed")
        action_statuses = {
            action["action_id"]: action["status"] for action in mission_state["next_actions"]["actions"]
        }
        self.assertEqual(action_statuses["run-followups"], "completed")
        self.assertEqual(action_statuses["decide-replication-readiness"], "completed")
        self.assertEqual(action_statuses["assemble-final-report"], "completed")
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["final-report"],
            ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        )
        self.assertEqual(mission_state["mission_runtime"]["status"], "completed")
        history_entries = [
            json.loads(line)
            for line in result["history_path"].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(
            [entry["directive"] for entry in history_entries],
            [
                "dispatch-executor",
                "branch",
                "dispatch-executor",
                "dispatch-executor",
                "complete",
            ],
        )
        experiment_entries = [
            json.loads(line)
            for line in result["experiment_ledger_path"].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(
            [entry.get("executor_id") for entry in experiment_entries if entry["kind"] == "experiment-run"],
            ["stage-kernel", "evaluation-comparison", "report-synthesis"],
        )
        runtime_summary = json.loads(result["summary_json_path"].read_text(encoding="utf-8"))
        self.assertEqual(runtime_summary["mission"]["status"], "completed")
        self.assertEqual(runtime_summary["mission"]["current_phase"], "final-report")
        rendered_mission_summary = mission_summary_path.read_text(encoding="utf-8")
        self.assertIn("- current_phase: `final-report`", rendered_mission_summary)
        self.assertIn("- status: `completed`", rendered_mission_summary)
        self.assertNotIn("- current_phase: `idea-intake`", rendered_mission_summary)
        self.assertEqual(
            package_state_snapshots,
            [
                ("running", "mission-runtime-running"),
                ("completed", "mission-runtime-completed"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
