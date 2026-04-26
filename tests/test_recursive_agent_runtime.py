from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from deeploop.autonomy.mission_autonomy import resolve_phase_contract
from deeploop.core.paths import SANDBOXES_DIR
from deeploop.runtime.recursive_agent_runtime import (
    _normalized_result_outcome,
    _resolve_transitioned_current_phase,
    _select_next_action,
    _should_yield_to_outer_runtime,
    _timeout_seconds_for_action,
    _validate_result,
    analyze_budget,
    run_recursive_agent_loop,
)
from runtime_artifact_helpers import fresh_test_root

TEST_WORK_ROOT = TESTS_ROOT / "_runtime_artifacts"


def _fresh_test_root(name: str) -> Path:
    return fresh_test_root(TEST_WORK_ROOT, name)


class RecursiveAgentRuntimeTests(unittest.TestCase):
    def test_runtime_drives_fresh_context_iterations_to_completion(self) -> None:
        mission_id = "recursive-agent-runtime-test"
        sandbox_root = SANDBOXES_DIR / mission_id
        test_root = _fresh_test_root("recursive-agent-runtime-test")
        shutil.rmtree(sandbox_root, ignore_errors=True)
        mission_root = test_root / "mission"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        decision_log_path = mission_root / "mission_decisions.jsonl"
        branch_log_path = mission_root / "mission_branches.jsonl"
        branch_id = "mission-branch-a"
        decision_id = "decision-a"
        decision_log_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "decision_id": decision_id,
                    "mission_id": mission_id,
                    "decision_type": "phase-transition",
                    "summary": "Transition into execution and stay on the current branch until critique.",
                    "phase": "idea-intake",
                    "scope": "internal",
                    "authority": {
                        "mode": "autonomous",
                        "requires_operator_approval": False,
                        "approval_state": "not-required",
                    },
                    "result": {"status": "selected", "recorded_at": "2025-01-01T00:00:00Z"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        branch_log_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "branch_id": branch_id,
                    "mission_id": mission_id,
                    "branch_type": "execution",
                    "objective": "Carry the recursive runtime through planning and execution.",
                    "status": "active",
                    "recovery_status": "not-needed",
                    "runtime_owner": "deeploop",
                    "source_phase": "idea-intake",
                    "target_phase": "critique",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        mission_state_path.write_text(
            json.dumps(
                {
                    "mission_id": mission_id,
                    "mode": "sandboxed-yolo",
                    "title": "Recursive runtime test mission",
                    "summary": "Exercise recursive Copilot-style looping.",
                    "objective": "Plan work, execute one step, and stop only on explicit completion.",
                    "current_phase": "idea-intake",
                    "next_phase": "execution",
                    "status": "initialized",
                    "target_repo": str(REPO_ROOT),
                    "roles": ["planner", "execution-operator"],
                    "next_actions": {
                        "summary": "Plan, then execute, then hand off to critique.",
                        "source_decision_id": decision_id,
                        "actions": [
                            {
                                "action_id": "plan-first-step",
                                "decision_id": decision_id,
                                "branch_id": branch_id,
                                "kind": "critique",
                                "role": "planner",
                                "task": "Draft the first bounded experiment plan.",
                                "status": "pending",
                                "phase": "idea-intake",
                                "runtime_owner": "deeploop",
                                "requires_operator_approval": False,
                                "artifacts": [],
                                "output_paths": [],
                                "notes": ["Start with a bounded plan."],
                            },
                            {
                                "action_id": "execute-first-step",
                                "decision_id": decision_id,
                                "branch_id": branch_id,
                                "kind": "local-eval",
                                "role": "execution-operator",
                                "task": "Run the first experiment from the drafted plan.",
                                "status": "pending",
                                "phase": "execution",
                                "runtime_owner": "deeploop",
                                "requires_operator_approval": False,
                                "artifacts": [],
                                "output_paths": [],
                                "notes": [],
                            },
                        ],
                    },
                    "outer_loop": {
                        "execution_mode": "full-autonomous-internal",
                        "internal_execution": "autonomous-by-default",
                        "external_publish": "operator-approval-required",
                        "autonomous_action_kinds": ["critique", "local-eval"],
                        "decision_log_path": str(decision_log_path),
                        "branch_log_path": str(branch_log_path),
                    },
                    "autonomy_status": {"state": "initialized", "reason": "test"},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        config_path = test_root / "recursive-runtime.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "mission_state": str(mission_state_path),
                    "loop_name": "demo-loop",
                    "max_iterations": 4,
                    "max_consecutive_failures": 2,
                    "agent": {
                        "command": [
                            sys.executable,
                            str(TESTS_ROOT / "fake_recursive_agent.py"),
                            "--prompt",
                            "{prompt_path}",
                            "--result-json",
                            "{result_json_path}",
                        ],
                        "cwd": str(REPO_ROOT),
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = run_recursive_agent_loop(config_path)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["iterations_completed"], 2)
        self.assertTrue(result["report_json_path"].exists())
        self.assertTrue(result["memory_path"].exists())
        self.assertTrue(result["state_path"].exists())
        self.assertEqual(result["latest_outcome"]["phase_control"]["next_phase"], "critique")
        self.assertEqual(result["latest_outcome"]["action_result"]["mission_action_id"], "execute-first-step")

        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["agent_driver"]["status"], "completed")
        self.assertEqual(mission_state["agent_driver"]["latest_mission_action_id"], "execute-first-step")
        self.assertEqual(mission_state["agent_driver"]["active_branch_id"], branch_id)
        self.assertEqual(mission_state["autonomy_status"]["state"], "recursive-agent-complete")
        self.assertEqual(mission_state["current_phase"], "execution")
        self.assertEqual(mission_state["next_phase"], "critique")
        self.assertEqual(mission_state["completed_phases"], ["idea-intake"])
        self.assertEqual(mission_state["phase_history"], ["idea-intake", "execution"])
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["idea-intake"],
            resolve_phase_contract("idea-intake")["outputs"],
        )
        self.assertEqual(
            mission_state["phase_outputs_by_phase"]["execution"],
            resolve_phase_contract("execution")["outputs"],
        )
        self.assertEqual(mission_state["produced_outputs"], resolve_phase_contract("execution")["outputs"])
        self.assertEqual(mission_state["phase_outputs"], resolve_phase_contract("execution")["outputs"])
        self.assertEqual(mission_state["next_actions"]["actions"][0]["status"], "completed")
        self.assertEqual(mission_state["next_actions"]["actions"][1]["status"], "completed")
        self.assertTrue(any(path.endswith("planner-note.txt") for path in mission_state["next_actions"]["actions"][0]["output_paths"]))
        self.assertTrue(any(path.endswith("execution-note.txt") for path in mission_state["next_actions"]["actions"][1]["output_paths"]))

        memory_entries = [json.loads(line) for line in result["memory_path"].read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(memory_entries), 2)
        self.assertEqual(memory_entries[0]["role"], "planner")
        self.assertEqual(memory_entries[0]["mission_action_id"], "plan-first-step")
        self.assertEqual(memory_entries[0]["continuation"]["action_id"], "execute-first-step")
        self.assertEqual(memory_entries[1]["role"], "execution-operator")
        self.assertEqual(memory_entries[1]["action_result"]["branch_id"], branch_id)

        first_prompt = (result["runtime_root"] / "iteration-01-planner" / "prompt.md").read_text(encoding="utf-8")
        self.assertIn("mission_action_id: `plan-first-step`", first_prompt)
        self.assertIn("## Branch context", first_prompt)
        self.assertIn("## Decision context", first_prompt)
        self.assertIn("## Policy placement rule", first_prompt)
        self.assertIn("## Foundational substrate rule", first_prompt)
        self.assertIn("Put reusable project-agnostic methods in skills.", first_prompt)
        self.assertIn("minimal fact/contract substrate", first_prompt)
        self.assertIn("DeepLoop owns build repo code", first_prompt)
        self.assertIn("additional trusted datasets", first_prompt)

        loop_report = json.loads(result["report_json_path"].read_text(encoding="utf-8"))
        self.assertEqual(loop_report["status"], "completed")
        self.assertEqual(loop_report["iterations"][0]["status"], "continue")
        self.assertEqual(loop_report["iterations"][1]["status"], "complete")
        self.assertEqual(loop_report["latest_outcome"]["phase_control"]["branch_status"], "critique-ready")
        shutil.rmtree(sandbox_root, ignore_errors=True)
        shutil.rmtree(test_root, ignore_errors=True)

    def test_runtime_blocks_when_no_followup_action_exists(self) -> None:
        mission_id = "recursive-agent-runtime-blocks"
        sandbox_root = SANDBOXES_DIR / mission_id
        test_root = _fresh_test_root("recursive-agent-runtime-blocks")
        shutil.rmtree(sandbox_root, ignore_errors=True)
        mission_root = test_root / "mission"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state_path.write_text(
            json.dumps(
                {
                    "mission_id": mission_id,
                    "mode": "sandboxed-yolo",
                    "title": "Recursive runtime block test",
                    "summary": "Exercise loop termination when actions run out.",
                    "objective": "Run one bounded task and stop when no next handoff exists.",
                    "current_phase": "idea-intake",
                    "next_phase": "execution",
                    "status": "initialized",
                    "target_repo": str(REPO_ROOT),
                    "roles": ["planner"],
                    "next_actions": {"actions": []},
                    "autonomy_status": {"state": "initialized", "reason": "test"},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        config_path = test_root / "recursive-runtime.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "mission_state": str(mission_state_path),
                    "loop_name": "block-loop",
                    "max_iterations": 4,
                    "max_consecutive_failures": 2,
                    "initial_task": "Do one planning step only.",
                    "agent": {
                        "command": [
                            sys.executable,
                            str(TESTS_ROOT / "fake_recursive_agent_no_followup.py"),
                            "--prompt",
                            "{prompt_path}",
                            "--result-json",
                            "{result_json_path}",
                        ],
                        "cwd": str(REPO_ROOT),
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = run_recursive_agent_loop(config_path)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["iterations_completed"], 1)
        self.assertEqual(result["latest_outcome"]["status"], "blocked")

        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["agent_driver"]["status"], "blocked")
        self.assertEqual(mission_state["autonomy_status"]["state"], "recursive-agent-blocked")
        self.assertIn("No further mission next action", mission_state["agent_driver"]["latest_outcome"]["summary"])
        shutil.rmtree(sandbox_root, ignore_errors=True)
        shutil.rmtree(test_root, ignore_errors=True)

    def test_runtime_discards_stale_pending_action_after_phase_transition(self) -> None:
        mission_id = "recursive-agent-runtime-stale-phase"
        sandbox_root = SANDBOXES_DIR / mission_id
        test_root = _fresh_test_root("recursive-agent-runtime-stale-phase")
        shutil.rmtree(sandbox_root, ignore_errors=True)
        mission_root = test_root / "mission"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state_path.write_text(
            json.dumps(
                {
                    "mission_id": mission_id,
                    "mode": "sandboxed-yolo",
                    "title": "Recursive runtime stale phase test",
                    "summary": "Ensure stale loop handoffs are dropped after phase changes.",
                    "objective": "Use the current-phase next action instead of an old pending handoff.",
                    "current_phase": "question-design",
                    "next_phase": "experiment-design",
                    "status": "running",
                    "target_repo": str(REPO_ROOT),
                    "roles": ["planner", "literature-scout"],
                    "next_actions": {
                        "actions": [
                            {
                                "action_id": "question-design-missing-outputs",
                                "role": "planner",
                                "task": "Close the question-design outputs.",
                                "kind": "artifact-edit",
                                "status": "pending",
                                "phase": "question-design",
                                "runtime_owner": "deeploop",
                                "requires_operator_approval": False,
                            }
                        ]
                    },
                    "autonomy_status": {"state": "running", "reason": "test"},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        loop_name = "stale-phase-loop"
        runtime_root = mission_root / "runtime" / "recursive_agent_runtime" / loop_name
        runtime_root.mkdir(parents=True, exist_ok=True)
        (runtime_root / "agent_loop_state.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "loop_name": loop_name,
                    "status": "running",
                    "iterations_completed": 0,
                    "consecutive_failures": 1,
                    "action_cursor": 0,
                    "initial_task_consumed": False,
                    "pending_action": {
                        "role": "literature-scout",
                        "task": "Finish the literature review.",
                        "phase": "literature-review",
                        "kind": "phase-transition",
                        "source": "agent-continuation",
                    },
                    "latest_iteration_path": None,
                    "latest_result_path": None,
                    "updated_at": "2025-01-01T00:00:00Z",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        fake_agent = test_root / "phase_agent.py"
        fake_agent.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "import argparse",
                    "import json",
                    "from pathlib import Path",
                    "parser = argparse.ArgumentParser()",
                    "parser.add_argument('--prompt', required=True)",
                    "parser.add_argument('--result-json', required=True)",
                    "args = parser.parse_args()",
                    "prompt_text = Path(args.prompt).read_text(encoding='utf-8')",
                    "payload = {",
                    "    'status': 'complete',",
                    "    'summary': prompt_text,",
                    "    'phase_control': {'current_phase': 'question-design', 'next_phase': 'experiment-design'},",
                    "}",
                    "Path(args.result_json).write_text(json.dumps(payload), encoding='utf-8')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        config_path = test_root / "recursive-runtime.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "mission_state": str(mission_state_path),
                    "loop_name": loop_name,
                    "max_iterations": 1,
                    "agent": {
                        "command": [
                            sys.executable,
                            str(fake_agent),
                            "--prompt",
                            "{prompt_path}",
                            "--result-json",
                            "{result_json_path}",
                        ],
                        "cwd": str(REPO_ROOT),
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = run_recursive_agent_loop(config_path)

        prompt_text = (result["runtime_root"] / "iteration-01-planner" / "prompt.md").read_text(encoding="utf-8")
        self.assertEqual(result["status"], "completed")
        self.assertIn("role: `planner`", prompt_text)
        self.assertNotIn("role: `literature-scout`", prompt_text)
        shutil.rmtree(sandbox_root, ignore_errors=True)
        shutil.rmtree(test_root, ignore_errors=True)

    def test_runtime_prefers_new_outer_action_over_same_phase_stale_handoff(self) -> None:
        mission_id = "recursive-agent-runtime-stale-same-phase"
        sandbox_root = SANDBOXES_DIR / mission_id
        test_root = _fresh_test_root("recursive-agent-runtime-stale-same-phase")
        shutil.rmtree(sandbox_root, ignore_errors=True)
        mission_root = test_root / "mission"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state_path.write_text(
            json.dumps(
                {
                    "mission_id": mission_id,
                    "mode": "sandboxed-yolo",
                    "title": "Recursive runtime stale same-phase test",
                    "summary": "Ensure new outer decisions override stale same-phase handoffs.",
                    "objective": "Use the rerouted planner action instead of the old literature-scout handoff.",
                    "current_phase": "literature-review",
                    "next_phase": "question-design",
                    "status": "running",
                    "target_repo": str(REPO_ROOT),
                    "roles": ["planner", "literature-scout"],
                    "next_actions": {
                        "actions": [
                            {
                                "action_id": "literature-review-missing-outputs",
                                "role": "planner",
                                "task": "Downscope literature review and close the missing outputs.",
                                "kind": "artifact-edit",
                                "status": "pending",
                                "phase": "literature-review",
                                "runtime_owner": "deeploop",
                                "requires_operator_approval": False,
                            }
                        ]
                    },
                    "autonomy_status": {"state": "running", "reason": "test"},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        loop_name = "stale-same-phase-loop"
        runtime_root = mission_root / "runtime" / "recursive_agent_runtime" / loop_name
        runtime_root.mkdir(parents=True, exist_ok=True)
        (runtime_root / "agent_loop_state.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "mission_id": mission_id,
                    "loop_name": loop_name,
                    "status": "running",
                    "iterations_completed": 3,
                    "consecutive_failures": 2,
                    "action_cursor": 0,
                    "initial_task_consumed": False,
                    "pending_action": {
                        "role": "literature-scout",
                        "task": "Finish the literature review.",
                        "phase": "literature-review",
                        "kind": "phase-transition",
                        "source": "agent-continuation",
                    },
                    "latest_iteration_path": None,
                    "latest_result_path": None,
                    "updated_at": "2025-01-01T00:00:00Z",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        fake_agent = test_root / "same_phase_agent.py"
        fake_agent.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "import argparse",
                    "import json",
                    "from pathlib import Path",
                    "parser = argparse.ArgumentParser()",
                    "parser.add_argument('--prompt', required=True)",
                    "parser.add_argument('--result-json', required=True)",
                    "args = parser.parse_args()",
                    "prompt_text = Path(args.prompt).read_text(encoding='utf-8')",
                    "payload = {",
                    "    'status': 'complete',",
                    "    'summary': prompt_text,",
                    "    'phase_control': {'current_phase': 'literature-review', 'next_phase': 'question-design'},",
                    "}",
                    "Path(args.result_json).write_text(json.dumps(payload), encoding='utf-8')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        config_path = test_root / "recursive-runtime.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "mission_state": str(mission_state_path),
                    "loop_name": loop_name,
                    "max_iterations": 1,
                    "agent": {
                        "command": [
                            sys.executable,
                            str(fake_agent),
                            "--prompt",
                            "{prompt_path}",
                            "--result-json",
                            "{result_json_path}",
                        ],
                        "cwd": str(REPO_ROOT),
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = run_recursive_agent_loop(config_path)

        prompt_text = (result["runtime_root"] / "iteration-04-planner" / "prompt.md").read_text(encoding="utf-8")
        self.assertEqual(result["status"], "completed")
        self.assertIn("role: `planner`", prompt_text)
        self.assertNotIn("role: `literature-scout`", prompt_text)
        shutil.rmtree(sandbox_root, ignore_errors=True)
        shutil.rmtree(test_root, ignore_errors=True)

    def test_runtime_keeps_legacy_handoff_fields_compatible(self) -> None:
        payload = {
            "status": "continue",
            "summary": "Legacy handoff emitted.",
            "next_role": "critic-verifier",
            "next_task": "Review the bounded result.",
            "produced_artifacts": ["runs/demo/output.json"],
        }
        self.assertEqual(_validate_result(payload), [])
        normalized = _normalized_result_outcome(
            payload,
            {
                "role": "planner",
                "task": "Plan the next step.",
                "artifacts": [],
                "action_id": "legacy-action",
                "loop_action_id": "demo-loop-iter-01-planner",
                "kind": "critique",
                "phase": "execution",
                "branch_id": "branch-a",
                "decision_id": "decision-a",
                "notes": [],
                "source": "test",
                "mission_action_index": 0,
            },
        )
        self.assertEqual(normalized["continuation"]["role"], "critic-verifier")
        self.assertEqual(normalized["continuation"]["task"], "Review the bounded result.")
        self.assertEqual(normalized["action_result"]["mission_action_id"], "legacy-action")

    def test_validate_result_accepts_string_list_like_handoff_fields(self) -> None:
        payload = {
            "status": "continue",
            "summary": "Handoff stays valid when a single note comes back as a string.",
            "continuation": {
                "role": "question-design",
                "task": "Turn the review into bounded hypotheses.",
                "artifacts": "runs/demo/prior-art-memo.md",
                "notes": "Use the prior-art memo as the bounded contract.",
            },
        }
        self.assertEqual(_validate_result(payload), [])
        normalized = _normalized_result_outcome(
            payload,
            {
                "role": "literature-scout",
                "task": "Ground the mission in prior art.",
                "artifacts": [],
                "action_id": None,
                "loop_action_id": "demo-loop-iter-02-literature-scout",
                "kind": "phase-transition",
                "phase": "literature-review",
                "branch_id": None,
                "decision_id": None,
                "notes": [],
                "source": "test",
                "mission_action_index": None,
            },
        )
        self.assertEqual(normalized["continuation"]["artifacts"], ["runs/demo/prior-art-memo.md"])
        self.assertEqual(normalized["continuation"]["notes"], ["Use the prior-art memo as the bounded contract."])

    def test_timeout_seconds_expand_for_execution_phase(self) -> None:
        timeout = _timeout_seconds_for_action(
            config={},
            policy={
                "timeout_seconds": 1800,
                "phase_timeout_seconds": {
                    "execution": 21600,
                },
            },
            action={"phase": "execution"},
        )
        self.assertEqual(timeout, 21600)

        execution_role_timeout = _timeout_seconds_for_action(
            config={},
            policy={
                "timeout_seconds": 1800,
                "phase_timeout_seconds": {
                    "execution": 21600,
                },
            },
            action={"phase": "experiment-design", "role": "execution-operator", "kind": "branch-create"},
        )
        self.assertEqual(execution_role_timeout, 21600)

        default_timeout = _timeout_seconds_for_action(
            config={},
            policy={"timeout_seconds": 1800},
            action={"phase": "question-design"},
        )
        self.assertEqual(default_timeout, 1800)

    def test_select_next_action_skips_completed_entries(self) -> None:
        index, action = _select_next_action(
            [
                {"action_id": "done-a", "task": "done", "status": "completed"},
                {"action_id": "done-b", "task": "done", "status": "cancelled"},
                {"action_id": "done-c", "task": "done", "status": "blocked"},
                {"action_id": "done-d", "task": "done", "status": "failed"},
                {"action_id": "ready-c", "task": "run critique", "status": "in_progress"},
            ],
            0,
        )
        self.assertEqual(index, 4)
        self.assertEqual(action["action_id"], "ready-c")

    def test_runtime_normalizes_complete_action_result_status_alias(self) -> None:
        payload = {
            "status": "complete",
            "summary": "Finished the bounded task.",
            "action_result": {
                "status": "complete",
                "output_paths": ["runs/demo/output.json"],
            },
        }
        self.assertEqual(_validate_result(payload), [])
        normalized = _normalized_result_outcome(
            payload,
            {
                "role": "planner",
                "task": "Plan the next step.",
                "artifacts": [],
                "action_id": "alias-action",
                "loop_action_id": "demo-loop-iter-01-planner",
                "kind": "artifact-edit",
                "phase": "question-design",
                "branch_id": None,
                "decision_id": None,
                "notes": [],
                "source": "test",
                "mission_action_index": 0,
            },
        )
        self.assertEqual(normalized["action_result"]["status"], "completed")

    def test_validate_result_accepts_contract_failure_action_result_aliases(self) -> None:
        payload = {
            "status": "continue",
            "summary": "Execution recorded a critique-ready contract failure.",
            "continuation": {
                "role": "critic-verifier",
                "task": "Review the contract failure before any retry.",
                "phase": "critique",
            },
            "action_result": {
                "status": "contract-failure-recorded",
                "phase": "execution",
                "kind": "phase-transition",
            },
            "phase_control": {
                "current_phase": "execution",
                "next_phase": "critique",
                "decision_type": "phase-transition",
            },
        }
        self.assertEqual(_validate_result(payload), [])
        normalized = _normalized_result_outcome(
            payload,
            {
                "role": "executor",
                "task": "Run the bounded contract gate.",
                "artifacts": [],
                "action_id": None,
                "loop_action_id": "demo-loop-iter-01-executor",
                "kind": "phase-transition",
                "phase": "execution",
                "branch_id": None,
                "decision_id": None,
                "notes": [],
                "source": "test",
                "mission_action_index": None,
            },
        )
        self.assertEqual(normalized["action_result"]["status"], "completed")

    def test_validate_result_accepts_continue_action_result_alias(self) -> None:
        payload = {
            "status": "continue",
            "summary": "Critique reroutes to experiment-design.",
            "continuation": {
                "role": "experiment-designer",
                "task": "Revise the post-baseline prompt-stage contract.",
                "phase": "experiment-design",
            },
            "action_result": {
                "status": "continue",
                "phase": "critique",
                "kind": "phase-transition",
            },
            "phase_control": {
                "current_phase": "critique",
                "next_phase": "experiment-design",
                "decision_type": "reroute",
            },
        }
        self.assertEqual(_validate_result(payload), [])
        normalized = _normalized_result_outcome(
            payload,
            {
                "role": "critic-verifier",
                "task": "Review the baseline-stage evidence.",
                "artifacts": [],
                "action_id": "critique-reroute",
                "loop_action_id": "demo-loop-iter-02-critic-verifier",
                "kind": "phase-transition",
                "phase": "critique",
                "branch_id": None,
                "decision_id": None,
                "notes": [],
                "source": "test",
                "mission_action_index": 1,
            },
        )
        self.assertEqual(normalized["action_result"]["status"], "completed")

    def test_runtime_advances_contract_failure_handoff_to_critique(self) -> None:
        mission_id = "recursive-agent-contract-failure"
        sandbox_root = SANDBOXES_DIR / mission_id
        test_root = _fresh_test_root("recursive-agent-contract-failure")
        shutil.rmtree(sandbox_root, ignore_errors=True)
        mission_root = test_root / "mission"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state_path.write_text(
            json.dumps(
                {
                    "mission_id": mission_id,
                    "mode": "sandboxed-yolo",
                    "title": "Recursive runtime contract-failure handoff",
                    "summary": "Ensure contract-failure execution results advance to critique.",
                    "objective": "Record a bounded contract failure, hand off to critique, and finish cleanly.",
                    "current_phase": "execution",
                    "next_phase": "critique",
                    "status": "initialized",
                    "target_repo": str(REPO_ROOT),
                    "roles": ["executor", "critic-verifier"],
                    "next_actions": {"actions": []},
                    "autonomy_status": {"state": "initialized", "reason": "test"},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        config_path = test_root / "recursive-runtime.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "mission_state": str(mission_state_path),
                    "loop_name": "contract-failure-loop",
                    "max_iterations": 4,
                    "max_consecutive_failures": 2,
                    "initial_task": "Run the bounded contract check before critique.",
                    "default_role": "executor",
                    "agent": {
                        "command": [
                            sys.executable,
                            str(TESTS_ROOT / "fake_recursive_agent_contract_failure.py"),
                            "--prompt",
                            "{prompt_path}",
                            "--result-json",
                            "{result_json_path}",
                        ],
                        "cwd": str(REPO_ROOT),
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = run_recursive_agent_loop(config_path)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["iterations_completed"], 2)

        runtime_root = result["runtime_root"]
        first_summary = json.loads((runtime_root / "iteration-01-executor" / "summary.json").read_text(encoding="utf-8"))
        second_summary = json.loads((runtime_root / "iteration-02-critic-verifier" / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(first_summary["status"], "continue")
        self.assertEqual(first_summary["normalized_result"]["action_result"]["status"], "completed")
        self.assertEqual(first_summary["normalized_result"]["continuation"]["role"], "critic-verifier")
        self.assertEqual(second_summary["status"], "complete")

        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["agent_driver"]["status"], "completed")
        self.assertEqual(mission_state["current_phase"], "replication")
        self.assertEqual(mission_state["completed_phases"], ["execution", "critique"])

        shutil.rmtree(sandbox_root, ignore_errors=True)
        shutil.rmtree(test_root, ignore_errors=True)

    def test_validate_result_accepts_critique_parked_action_result_alias(self) -> None:
        payload = {
            "status": "continue",
            "summary": "Critique remains parked on bounded evidence.",
            "continuation": {
                "role": "critic-verifier",
                "task": "Stay in critique until a new mission decision opens a later stage.",
                "phase": "critique",
            },
            "action_result": {
                "status": "critique-parked",
                "phase": "critique",
                "kind": "phase-transition",
            },
            "phase_control": {
                "current_phase": "critique",
                "next_phase": "critique",
                "decision_type": "stay-in-critique",
                "branch_status": "critique-parked",
            },
        }
        self.assertEqual(_validate_result(payload), [])
        normalized = _normalized_result_outcome(
            payload,
            {
                "role": "critic-verifier",
                "task": "Review the bounded prompt evidence.",
                "artifacts": [],
                "action_id": "critique-hold",
                "loop_action_id": "demo-loop-iter-05-critic-verifier",
                "kind": "phase-transition",
                "phase": "critique",
                "branch_id": None,
                "decision_id": None,
                "notes": [],
                "source": "test",
                "mission_action_index": 4,
            },
        )
        self.assertEqual(normalized["action_result"]["status"], "completed")

    def test_same_phase_hold_yields_to_outer_runtime(self) -> None:
        action = {
            "role": "critic-verifier",
            "task": "Stay in critique until a new mission decision opens a later stage.",
            "artifacts": [],
            "action_id": "critique-hold",
            "loop_action_id": "demo-loop-iter-05-critic-verifier",
            "kind": "phase-transition",
            "phase": "critique",
            "branch_id": None,
            "decision_id": None,
            "notes": [],
            "source": "test",
            "mission_action_index": 4,
        }
        outcome = _normalized_result_outcome(
            {
                "status": "continue",
                "summary": "Stay in critique until the outer mission runtime decides the next stage.",
                "continuation": {
                    "role": "critic-verifier",
                    "task": "Stay in critique until a new mission decision opens a later stage.",
                    "phase": "critique",
                },
                "action_result": {
                    "status": "continue",
                    "phase": "critique",
                    "kind": "phase-transition",
                },
                "phase_control": {
                    "current_phase": "critique",
                    "next_phase": "critique",
                    "decision_type": "stay-in-critique",
                    "branch_status": "critique-ready",
                },
            },
            action,
        )

        self.assertTrue(_should_yield_to_outer_runtime(outcome, action=action))

    def test_runtime_clears_stale_continuation_identity_when_handoff_does_not_match_known_action(self) -> None:
        payload = {
            "status": "complete",
            "summary": "Closed the current phase and handed off the next one.",
            "continuation": {
                "role": "literature-scout",
                "task": "Ground the mission in prior art and close the literature-review outputs.",
                "action_id": "idea-intake-missing-outputs",
                "kind": "phase-transition",
                "phase": "literature-review",
                "decision_id": "idea-intake-missing-outputs",
                "notes": ["Move into literature review."],
            },
            "action_result": {
                "status": "completed",
            },
            "phase_control": {
                "current_phase": "idea-intake",
                "next_phase": "literature-review",
            },
        }
        action = {
            "role": "planner",
            "task": "Close the remaining idea-intake outputs.",
            "artifacts": [],
            "action_id": "idea-intake-missing-outputs",
            "loop_action_id": "demo-loop-iter-01-planner",
            "kind": "artifact-edit",
            "phase": "idea-intake",
            "branch_id": None,
            "decision_id": "idea-intake-missing-outputs",
            "notes": [],
            "source": "test",
            "mission_action_index": 0,
        }
        mission_state = {
            "next_actions": {
                "actions": [
                    {
                        "action_id": "idea-intake-missing-outputs",
                        "role": "planner",
                        "task": "Close the remaining idea-intake outputs.",
                        "kind": "artifact-edit",
                        "phase": "idea-intake",
                        "decision_id": "idea-intake-missing-outputs",
                    },
                    {
                        "action_id": "literature-review-phase-transition",
                        "role": "literature-scout",
                        "task": "Advance the mission from idea-intake to literature-review.",
                        "kind": "phase-transition",
                        "phase": "literature-review",
                        "decision_id": "literature-review-phase-transition",
                    },
                    {
                        "action_id": "literature-review-missing-outputs",
                        "role": "literature-scout",
                        "task": "Close the remaining literature-review outputs.",
                        "kind": "artifact-edit",
                        "phase": "literature-review",
                        "decision_id": "literature-review-missing-outputs",
                    },
                ]
            }
        }

        normalized = _normalized_result_outcome(payload, action, mission_state=mission_state)

        self.assertEqual(normalized["continuation"]["role"], "literature-scout")
        self.assertEqual(normalized["continuation"]["phase"], "literature-review")
        self.assertIsNone(normalized["continuation"]["action_id"])
        self.assertIsNone(normalized["continuation"]["decision_id"])

    def test_runtime_advances_current_phase_for_continuation_handoff(self) -> None:
        resolved = _resolve_transitioned_current_phase(
            mission_state={"current_phase": "idea-intake"},
            action={"phase": "idea-intake", "kind": "artifact-edit"},
            continuation={"phase": "literature-review"},
            phase_control={"current_phase": "idea-intake", "next_phase": "literature-review"},
        )

        self.assertEqual(resolved, "literature-review")


class AnalyzeBudgetTests(unittest.TestCase):
    def test_analyze_budget_returns_ok_for_small_queue(self) -> None:
        test_root = _fresh_test_root("analyze-budget-ok")
        mission_root = test_root / "mission"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state = {
            "mission_id": "budget-test-ok",
            "status": "running",
            "current_phase": "execution",
            "next_actions": {
                "summary": "Two pending jobs.",
                "actions": [
                    {"action_id": "job-1", "role": "execution-operator", "status": "pending"},
                    {"action_id": "job-2", "role": "execution-operator", "status": "pending"},
                ],
            },
        }
        mission_state_path.write_text(
            __import__("json").dumps(mission_state), encoding="utf-8"
        )

        report = analyze_budget(mission_state_path=mission_state_path)

        self.assertEqual(report["pending_actions"], 2)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["warnings"], [])
        self.assertGreater(report["max_iterations"], 0)

    def test_analyze_budget_returns_over_budget_for_large_queue(self) -> None:
        test_root = _fresh_test_root("analyze-budget-over")
        mission_root = test_root / "mission"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        many_actions = [
            {"action_id": f"job-{i:03d}", "role": "execution-operator", "status": "pending"}
            for i in range(72)
        ]
        mission_state = {
            "mission_id": "budget-test-over",
            "status": "running",
            "current_phase": "execution",
            "next_actions": {"summary": "Massive baseline queue.", "actions": many_actions},
        }
        mission_state_path.write_text(
            __import__("json").dumps(mission_state), encoding="utf-8"
        )

        report = analyze_budget(mission_state_path=mission_state_path)

        self.assertEqual(report["pending_actions"], 72)
        self.assertEqual(report["status"], "over-budget")
        self.assertTrue(len(report["warnings"]) > 0)
        self.assertGreater(report["projected_total"], report["max_iterations"])

    def test_analyze_budget_excludes_done_actions_from_pending_count(self) -> None:
        test_root = _fresh_test_root("analyze-budget-done")
        mission_root = test_root / "mission"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        mission_state = {
            "mission_id": "budget-test-done",
            "status": "running",
            "current_phase": "execution",
            "next_actions": {
                "summary": "Mix of done and pending.",
                "actions": [
                    {"action_id": "job-1", "role": "execution-operator", "status": "done"},
                    {"action_id": "job-2", "role": "execution-operator", "status": "completed"},
                    {"action_id": "job-3", "role": "execution-operator", "status": "pending"},
                ],
            },
        }
        mission_state_path.write_text(
            __import__("json").dumps(mission_state), encoding="utf-8"
        )

        report = analyze_budget(mission_state_path=mission_state_path)

        self.assertEqual(report["pending_actions"], 1)

    def test_analyze_budget_returns_warning_for_near_ceiling_queue(self) -> None:
        test_root = _fresh_test_root("analyze-budget-warn")
        mission_root = test_root / "mission"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        config_path = test_root / "loop_config.yaml"
        config_path.write_text(
            "max_iterations: 10\nmission_state: placeholder\n", encoding="utf-8"
        )
        # 9 out of 10 => 90% utilization => warning
        actions = [
            {"action_id": f"job-{i}", "role": "execution-operator", "status": "pending"}
            for i in range(9)
        ]
        mission_state = {
            "mission_id": "budget-test-warn",
            "status": "running",
            "current_phase": "execution",
            "next_actions": {"summary": "Near-ceiling queue.", "actions": actions},
        }
        mission_state_path.write_text(
            __import__("json").dumps(mission_state), encoding="utf-8"
        )

        report = analyze_budget(config_path=config_path, mission_state_path=mission_state_path)

        self.assertEqual(report["max_iterations"], 10)
        self.assertEqual(report["pending_actions"], 9)
        self.assertIn(report["status"], {"warning", "over-budget"})
        self.assertTrue(len(report["warnings"]) > 0)


if __name__ == "__main__":
    unittest.main()
