from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.mission_executor_registry import (
    AdaptationTrainingExecutorAction,
    EvaluationComparisonExecutorAction,
    MissionExecutorId,
    RecursiveAgentExecutorAction,
    ReportSynthesisExecutorAction,
    SelfHealingQueueExecutorAction,
    StageKernelExecutorAction,
    get_mission_executor_registry,
    run_mission_action,
    run_mission_executor,
)
from deeploop.runtime.stage_kernels import KernelRunResult


class MissionExecutorRegistryTests(unittest.TestCase):
    def test_registry_advertises_runnable_executors(self) -> None:
        registry = get_mission_executor_registry()

        self.assertEqual(
            set(registry),
            {
                MissionExecutorId.RECURSIVE_AGENT,
                MissionExecutorId.SELF_HEALING_QUEUE,
                MissionExecutorId.STAGE_KERNEL,
                MissionExecutorId.ADAPTATION_TRAINING,
                MissionExecutorId.EVALUATION_COMPARISON,
                MissionExecutorId.REPORT_SYNTHESIS,
            },
        )
        self.assertTrue(all(executor.runner is not None for executor in registry.values()))

    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_recursive_agent_executor_dispatches_runtime(self, mock_run_recursive_agent_loop) -> None:
        runtime_root = REPO_ROOT / "runs" / "mission-a" / "recursive"
        mock_run_recursive_agent_loop.return_value = {
            "status": "completed",
            "iterations_completed": 2,
            "consecutive_failures": 0,
            "runtime_root": runtime_root,
            "state_path": runtime_root / "agent_loop_state.json",
            "memory_path": runtime_root / "loop_memory.jsonl",
            "latest_iteration_path": runtime_root / "iteration-02-execution-operator",
            "latest_result_path": runtime_root / "iteration-02-execution-operator" / "summary.json",
            "report_json_path": runtime_root / "loop_report.json",
            "report_markdown_path": runtime_root / "loop_report.md",
            "latest_outcome": {
                "status": "complete",
                "action_result": {
                    "mission_action_id": "execute-first-step",
                    "loop_action_id": "demo-loop-iter-02-execution-operator",
                },
            },
        }

        action = RecursiveAgentExecutorAction(config_path="configs/runtime/demo-loop.yaml")
        result = run_mission_action(action)

        mock_run_recursive_agent_loop.assert_called_once_with(Path("configs/runtime/demo-loop.yaml"))
        self.assertEqual(result.executor_id, MissionExecutorId.RECURSIVE_AGENT)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.payload["latest_outcome"]["action_result"]["mission_action_id"], "execute-first-step")
        self.assertEqual(result.artifacts["state_path"], runtime_root / "agent_loop_state.json")
        self.assertEqual(result.artifacts["report_json_path"], runtime_root / "loop_report.json")

    @patch("deeploop.runtime.mission_executor_registry.run_recursive_agent_loop")
    def test_recursive_agent_executor_promotes_completed_latest_action_past_loop_cap(
        self,
        mock_run_recursive_agent_loop,
    ) -> None:
        runtime_root = REPO_ROOT / "runs" / "mission-a" / "recursive"
        mock_run_recursive_agent_loop.return_value = {
            "status": "max-iterations",
            "iterations_completed": 7,
            "consecutive_failures": 0,
            "runtime_root": runtime_root,
            "state_path": runtime_root / "agent_loop_state.json",
            "memory_path": runtime_root / "loop_memory.jsonl",
            "latest_iteration_path": runtime_root / "iteration-07-execution-operator",
            "latest_result_path": runtime_root / "iteration-07-execution-operator" / "summary.json",
            "report_json_path": runtime_root / "loop_report.json",
            "report_markdown_path": runtime_root / "loop_report.md",
            "latest_outcome": {
                "status": "continue",
                "phase_control": {"current_phase": "execution", "next_phase": "critique"},
                "action_result": {
                    "mission_action_id": "execute-first-step",
                    "loop_action_id": "demo-loop-iter-07-execution-operator",
                    "status": "completed",
                },
            },
        }

        action = RecursiveAgentExecutorAction(config_path="configs/runtime/demo-loop.yaml")
        result = run_mission_action(action)

        self.assertEqual(result.executor_id, MissionExecutorId.RECURSIVE_AGENT)
        self.assertEqual(result.status, "completed")
        self.assertIn("iteration cap", result.summary)
        self.assertEqual(result.payload["status"], "max-iterations")

    @patch("deeploop.runtime.mission_executor_registry.run_self_healing_queue")
    def test_self_healing_queue_executor_normalizes_queue_status(self, mock_run_self_healing_queue) -> None:
        mock_run_self_healing_queue.return_value = {
            "completed_jobs": 1,
            "blocked_jobs": 1,
            "failed_jobs": 0,
            "queue_name": "demo-queue",
            "blocked_entries": [
                {
                    "entry_id": "blocked-followup",
                    "queue_name": "demo-queue",
                    "sanity_verdict": "block",
                    "top_blocking_reasons": ["comparison anchor is missing"],
                }
            ],
            "ledger_path": REPO_ROOT / "runs" / "mission-a" / "ledger.jsonl",
            "runtime_report_path": REPO_ROOT / "runs" / "mission-a" / "queue_summary.json",
            "runtime_report_markdown_path": REPO_ROOT / "runs" / "mission-a" / "queue_summary.md",
        }

        action = SelfHealingQueueExecutorAction(
            config_path="configs/runtime/demo-queue.yaml",
            policy_path="configs/runtime/self-healing-runtime.yaml",
        )
        result = run_mission_executor(MissionExecutorId.SELF_HEALING_QUEUE, action)

        mock_run_self_healing_queue.assert_called_once_with(
            Path("configs/runtime/demo-queue.yaml"),
            policy_path=Path("configs/runtime/self-healing-runtime.yaml"),
        )
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.executor_id, MissionExecutorId.SELF_HEALING_QUEUE)
        self.assertEqual(result.payload["blocked_entries"][0]["entry_id"], "blocked-followup")

    @patch("deeploop.runtime.mission_executor_registry.run_stage_from_config")
    def test_stage_kernel_executor_wraps_kernel_result(self, mock_run_stage_from_config) -> None:
        output_dir = REPO_ROOT / "runs" / "stage"
        mock_run_stage_from_config.return_value = KernelRunResult(
            stage_id="baseline-evaluation",
            status="completed",
            output_dir=output_dir,
            manifest_path=output_dir / "run_manifest.json",
            summary_path=None,
            artifacts={"predictions": output_dir / "predictions.jsonl"},
        )

        action = StageKernelExecutorAction(
            stage_id="baseline-evaluation",
            config_path="configs/runtime/stage.yaml",
            adapter_spec="demo.runtime:build_adapter",
        )
        result = run_mission_action(action)

        mock_run_stage_from_config.assert_called_once_with(
            "baseline-evaluation",
            Path("configs/runtime/stage.yaml"),
            adapter=None,
            adapter_spec="demo.runtime:build_adapter",
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.artifacts["predictions"], output_dir / "predictions.jsonl")

    @patch("deeploop.runtime.mission_executor_registry.run_adaptation_training")
    @patch("deeploop.runtime.mission_executor_registry.evaluate_self_correction")
    @patch("deeploop.runtime.mission_executor_registry.package_mission_artifacts")
    def test_evaluation_and_report_executors_wrap_existing_surfaces(
        self,
        mock_package_mission_artifacts,
        mock_evaluate_self_correction,
        mock_run_adaptation_training,
    ) -> None:
        mock_run_adaptation_training.return_value = {
            "status": "completed",
            "summary": "Adapted artifact `keep` against the best prior anchor `intervention` on `accuracy` with route `replication`.",
            "runtime_root": REPO_ROOT / "runs" / "mission-a" / "adaptation",
            "train_job_path": REPO_ROOT / "runs" / "mission-a" / "adaptation" / "train_job.json",
            "eval_job_path": REPO_ROOT / "runs" / "mission-a" / "adaptation" / "evaluate_job.json",
            "report_json_path": REPO_ROOT / "runs" / "mission-a" / "adaptation" / "report.json",
            "report_markdown_path": REPO_ROOT / "runs" / "mission-a" / "adaptation" / "report.md",
            "comparison_path": REPO_ROOT / "runs" / "mission-a" / "adaptation" / "comparison.json",
            "training_log_path": REPO_ROOT / "runs" / "mission-a" / "adaptation" / "train.log",
            "evaluation_log_path": REPO_ROOT / "runs" / "mission-a" / "adaptation" / "evaluate.log",
            "adapter_artifact_path": REPO_ROOT / "runs" / "mission-a" / "adaptation" / "adapter.bin",
            "evaluation_metrics_path": REPO_ROOT / "runs" / "mission-a" / "adaptation" / "metrics.json",
            "comparison": {"decision": "keep", "route_to": "replication"},
            "produced_outputs": ["adapted artifact"],
            "mission_state_updates": {"adaptation_training": {"decision": "keep", "route_to": "replication"}},
        }
        mock_evaluate_self_correction.return_value = {
            "report_json_path": REPO_ROOT / "runs" / "mission-a" / "self_correction.json",
            "report_markdown_path": REPO_ROOT / "runs" / "mission-a" / "self_correction.md",
            "final_decision": {"action": "reroute", "route_to": "mechanistic-localization"},
            "recommendations": [],
        }
        mock_package_mission_artifacts.return_value = {
            "package_root": REPO_ROOT / "runs" / "packages" / "mission-a",
            "manifest_path": REPO_ROOT / "runs" / "packages" / "mission-a" / "mission_artifact_package.json",
            "summary_path": REPO_ROOT / "runs" / "packages" / "mission-a" / "mission_artifact_package.md",
            "package": {},
        }

        adaptation = run_mission_action(
            AdaptationTrainingExecutorAction(
                training_config_path="configs/runtime/train.yaml",
                mission_state_path="runs/mission-a/mission_state.json",
            )
        )
        comparison = run_mission_action(
            EvaluationComparisonExecutorAction(
                mission_state_path="runs/mission-a/mission_state.json",
                manifest_paths=["runs/mission-a/a.json"],
                run_roots=["runs/mission-a"],
                artifact_name="mission-a-compare",
            )
        )

        import deeploop.runtime.mission_executor_registry as _mer
        mock_mission_state = {
            "mission_id": "mission-a",
            "title": "Test",
            "summary": "Test mission",
            "current_phase": "literature-review",
            "status": "running",
        }
        with patch.object(_mer, "_load_json", return_value=mock_mission_state):
            synthesis = run_mission_action(
                ReportSynthesisExecutorAction(mission_state_path="runs/mission-a/mission_state.json")
            )

        mock_run_adaptation_training.assert_called_once_with(
            Path("configs/runtime/train.yaml"),
            mission_state_path=Path("runs/mission-a/mission_state.json"),
        )
        mock_evaluate_self_correction.assert_called_once()
        mock_package_mission_artifacts.assert_called_once()
        package_args, package_kwargs = mock_package_mission_artifacts.call_args
        self.assertEqual(package_args[0], Path("runs/mission-a/mission_state.json"))
        self.assertTrue(str(package_kwargs["contract_path"]).endswith("configs/runtime/artifact-package-contract.yaml"))
        self.assertIsNone(package_kwargs["output_root"])
        self.assertEqual(adaptation.status, "completed")
        self.assertEqual(adaptation.executor_id, MissionExecutorId.ADAPTATION_TRAINING)
        self.assertEqual(adaptation.artifacts["comparison_path"], REPO_ROOT / "runs" / "mission-a" / "adaptation" / "comparison.json")
        self.assertEqual(comparison.status, "reroute")
        self.assertEqual(synthesis.status, "completed")

    def test_executor_rejects_wrong_action_type(self) -> None:
        with self.assertRaises(TypeError):
            run_mission_executor(
                MissionExecutorId.RECURSIVE_AGENT,
                ReportSynthesisExecutorAction(mission_state_path="runs/mission-a/mission_state.json"),
            )


if __name__ == "__main__":
    unittest.main()
