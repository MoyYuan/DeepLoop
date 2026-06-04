from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.provider_launcher import (
    build_provider_prompt_command,
    resolve_provider_idle_timeout_seconds,
    run_provider_prompt,
)


class ProviderLauncherTests(unittest.TestCase):
    def test_build_command_adds_permissions_and_dirs(self) -> None:
        command = build_provider_prompt_command(
            prompt_file=Path("/tmp/prompt.md"),
            model="gpt-5.4",
        )
        self.assertEqual(command[:3], [sys.executable, "-m", "deeploop.runtime.openai_compatible_adapter"])
        self.assertIn("--prompt-file", command)
        self.assertIn("gpt-5.4", command)

    def test_build_command_for_openai_compatible_api_uses_prompt_file(self) -> None:
        command = build_provider_prompt_command(
            prompt_file=Path("/tmp/prompt.md"),
            result_json_path=Path("/tmp/result.json"),
            model="Qwen3.6-27B-UD-Q4_K_XL.gguf",
        )
        self.assertEqual(command[:3], [sys.executable, "-m", "deeploop.runtime.openai_compatible_adapter"])
        self.assertIn("--prompt-file", command)
        self.assertIn("--result-json-path", command)
        self.assertIn("Qwen3.6-27B-UD-Q4_K_XL.gguf", command)

    def test_build_command_requires_prompt_file(self) -> None:
        command = build_provider_prompt_command(
            prompt_file=Path("/nonexistent/prompt.md"),
            model="gpt-4",
        )
        self.assertIn("--prompt-file", command)
        self.assertEqual(command[:3], [sys.executable, "-m", "deeploop.runtime.openai_compatible_adapter"])

    @patch("deeploop.runtime.provider_launcher.time.sleep", return_value=None)
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_bootstraps_source_pythonpath_for_openai_compatible_process(
        self, mock_popen, _mock_sleep
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "result.json"
            prompt_file.write_text("hello world", encoding="utf-8")

            process = MagicMock()
            process.poll.side_effect = [None, None]
            process.communicate.return_value = ("provider stdout", "provider stderr")
            mock_popen.return_value = process

            result_json_path.write_text(json.dumps({"status": "complete", "summary": "done"}), encoding="utf-8")

            completed = run_provider_prompt(
                prompt_file,
                result_json_path=result_json_path,
                cwd=root,
            )

        self.assertEqual(completed.returncode, 0)
        _, kwargs = mock_popen.call_args
        env = kwargs["env"]
        self.assertEqual(env["PYTHONPATH"].split(os.pathsep)[0], str(SRC_ROOT))

    def test_resolve_provider_idle_timeout_defaults(self) -> None:
        self.assertEqual(resolve_provider_idle_timeout_seconds(None), 300.0)
        self.assertEqual(resolve_provider_idle_timeout_seconds(30.0), 30.0)

    @patch("deeploop.runtime.provider_launcher.time.sleep", return_value=None)
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_returns_once_result_file_is_valid(self, mock_popen, _mock_sleep) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "result.json"
            prompt_file.write_text("hello world", encoding="utf-8")

            process = MagicMock()
            process.poll.side_effect = [None, None]
            process.communicate.return_value = ("partial stdout", "partial stderr")
            mock_popen.return_value = process

            result_json_path.write_text(json.dumps({"status": "complete", "summary": "done"}), encoding="utf-8")

            completed = run_provider_prompt(prompt_file, result_json_path=result_json_path, cwd=root)

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "partial stdout")
        self.assertEqual(completed.stderr, "partial stderr")
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    @patch("deeploop.runtime.provider_launcher.time.sleep", return_value=None)
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_accepts_in_progress_analysis_payloads(self, mock_popen, _mock_sleep) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "result.json"
            prompt_file.write_text("hello world", encoding="utf-8")

            process = MagicMock()
            process.poll.side_effect = [None, None]
            process.communicate.return_value = ("analysis stdout", "analysis stderr")
            mock_popen.return_value = process

            result_json_path.write_text(
                json.dumps(
                    {
                        "status": "in_progress",
                        "summary": "Mission is still in intake.",
                        "recommended_next_step": "Advance to the next bounded phase.",
                        "findings": ["The provider returned an operator-facing analysis payload."],
                    }
                ),
                encoding="utf-8",
            )

            completed = run_provider_prompt(prompt_file, result_json_path=result_json_path, cwd=root)

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "analysis stdout")
        self.assertEqual(completed.stderr, "analysis stderr")
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    @patch("deeploop.runtime.provider_launcher.time.sleep", return_value=None)
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_materializes_execution_result_from_runtime_outputs(
        self, mock_popen, _mock_sleep
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "iteration-05" / "result.json"
            sandbox_root = root / "sandbox"
            mission_state_path = root / "mission" / "mission_state.json"
            runtime_root = root / "runtime" / "execution"
            prompt_file.write_text("hello world", encoding="utf-8")
            sandbox_root.mkdir(parents=True, exist_ok=True)
            mission_state_path.parent.mkdir(parents=True, exist_ok=True)
            mission_state_path.write_text(json.dumps({"current_phase": "execution"}), encoding="utf-8")
            (sandbox_root / "outputs").mkdir(parents=True, exist_ok=True)
            (runtime_root / "logs").mkdir(parents=True, exist_ok=True)
            (sandbox_root / "outputs" / "baseline_execution_summary.json").write_text(
                json.dumps(
                    {
                        "runtime_root": str(runtime_root),
                        "selected_direction": "en-zh",
                        "selected_starter": {
                            "run_id": "baseline-en-zh-qwen35-1p5b",
                            "starter_alias": "Qwen3.5-1.5B-Instruct",
                        },
                        "shared_sacrebleu_signature": "sig-demo",
                        "total_baseline_gpu_hours": 1.23,
                    }
                ),
                encoding="utf-8",
            )
            for name, payload in {
                "baseline_stage_scoreboard.json": {"status": "completed"},
                "direction_scoreboard.json": {"status": "completed"},
                "direction_selection.json": {"selected_direction": "en-zh"},
                "prompt_decode_stage_release.json": {
                    "selected_starter": {
                        "run_id": "baseline-en-zh-qwen35-1p5b",
                        "starter_alias": "Qwen3.5-1.5B-Instruct",
                    },
                    "shared_sacrebleu_signature": "sig-demo",
                },
                "crash_stability_notes.json": {"notes": ["all runs completed", "no malformed outputs"]},
            }.items():
                (runtime_root / name).write_text(json.dumps(payload), encoding="utf-8")
            (runtime_root / "logs" / "baseline-wave-1.log").write_text("done\n", encoding="utf-8")

            process = MagicMock()
            process.poll.side_effect = [None, None]
            process.communicate.return_value = ("partial stdout", "partial stderr")
            mock_popen.return_value = process

            completed = run_provider_prompt(
                prompt_file,
                result_json_path=result_json_path,
                sandbox_root=sandbox_root,
                mission_state_path=mission_state_path,
                cwd=root,
            )

            synthesized = json.loads(result_json_path.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(synthesized["status"], "complete")
        self.assertEqual(synthesized["phase_control"]["next_phase"], "critique")
        self.assertIn("baseline_stage_scoreboard.json", "\n".join(synthesized["produced_artifacts"]))
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    @patch("deeploop.runtime.provider_launcher.time.sleep", return_value=None)
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_recovers_execution_summary_from_completed_run_manifests(
        self, mock_popen, _mock_sleep
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "iteration-05" / "result.json"
            sandbox_root = root / "sandbox"
            mission_state_path = root / "mission" / "mission_state.json"
            runtime_root = root / "mission" / "runtime" / "execution" / "demo-runtime"
            prompt_file.write_text("hello world", encoding="utf-8")
            mission_state_path.parent.mkdir(parents=True, exist_ok=True)
            mission_state_path.write_text(json.dumps({"current_phase": "execution"}), encoding="utf-8")
            (sandbox_root / "outputs").mkdir(parents=True, exist_ok=True)
            (runtime_root / "logs").mkdir(parents=True, exist_ok=True)
            (sandbox_root / "outputs" / "materialize_wmt19_baseline_matrix.py").write_text(
                "from pathlib import Path\n"
                "import json\n"
                "def materialize_root_artifacts(output_root, run_results):\n"
                "    for name in ('baseline_stage_scoreboard.json','direction_scoreboard.json','direction_selection.json','prompt_decode_stage_release.json','crash_stability_notes.json'):\n"
                "        Path(output_root / name).write_text(json.dumps({'name': name, 'selected_direction': 'zh-en', 'selected_starter': {'run_id': 'baseline-zh-en-qwen35-1p5b', 'starter_alias': 'Qwen3.5-1.5B-Instruct'}, 'shared_sacrebleu_signature': 'sig-demo', 'notes': ['all runs completed']}))\n"
                "    return {'chosen_direction': 'zh-en', 'chosen_starter': {'run_id': 'baseline-zh-en-qwen35-1p5b', 'starter_alias': 'Qwen3.5-1.5B-Instruct'}, 'shared_sacrebleu_signature': 'sig-demo', 'total_baseline_gpu_hours': 1.23}\n",
                encoding="utf-8",
            )
            for run_id, direction, alias, resolved_model_id in (
                ("baseline-zh-en-qwen35-0p5b", "zh-en", "Qwen3.5-0.5B-Instruct", "Qwen/Qwen3.5-0.8B"),
                ("baseline-zh-en-qwen35-1p5b", "zh-en", "Qwen3.5-1.5B-Instruct", "Qwen/Qwen3.5-2B"),
                ("baseline-en-zh-qwen35-0p5b", "en-zh", "Qwen3.5-0.5B-Instruct", "Qwen/Qwen3.5-0.8B"),
                ("baseline-en-zh-qwen35-1p5b", "en-zh", "Qwen3.5-1.5B-Instruct", "Qwen/Qwen3.5-2B"),
            ):
                run_dir = runtime_root / "runs" / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                artifacts = {
                    "slice_metrics_path": str(run_dir / "slice_metrics.json"),
                    "runtime_materialization_path": str(run_dir / "runtime_materialization.json"),
                    "log_path": str(runtime_root / "logs" / f"{run_id}.log"),
                }
                (run_dir / "slice_metrics.json").write_text(json.dumps({"slice-a": {"sacrebleu": 1.0}}), encoding="utf-8")
                (run_dir / "runtime_materialization.json").write_text(json.dumps({"conda_env": "llm"}), encoding="utf-8")
                (runtime_root / "logs" / f"{run_id}.log").write_text("done\n", encoding="utf-8")
                (run_dir / "run_manifest.json").write_text(
                    json.dumps(
                        {
                            "status": "completed",
                            "artifacts": artifacts,
                            "metrics": {"sacrebleu": 20.0, "sacrebleu_signature": "sig-demo"},
                            "runtime": {
                                "run_id": run_id,
                                "wave_id": "wave-a" if direction == "zh-en" else "wave-b",
                                "empty_outputs": 0,
                                "malformed_output_rate": 0.0,
                            },
                            "stage_context": {"direction": direction},
                            "model": {"identifier": alias, "resolved_model_id": resolved_model_id},
                        }
                    ),
                    encoding="utf-8",
                )

            process = MagicMock()
            process.poll.side_effect = [None, None]
            process.communicate.return_value = ("partial stdout", "partial stderr")
            mock_popen.return_value = process

            completed = run_provider_prompt(
                prompt_file,
                result_json_path=result_json_path,
                sandbox_root=sandbox_root,
                mission_state_path=mission_state_path,
                cwd=root,
            )

            execution_summary = json.loads((sandbox_root / "outputs" / "baseline_execution_summary.json").read_text(encoding="utf-8"))
            synthesized = json.loads(result_json_path.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(execution_summary["selected_direction"], "zh-en")
        self.assertEqual(synthesized["status"], "complete")
        self.assertIn("prompt_decode_stage_release.json", "\n".join(synthesized["produced_artifacts"]))
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    @patch("deeploop.runtime.provider_launcher.time.sleep", return_value=None)
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_recovers_non_execution_phase_from_outputs(self, mock_popen, _mock_sleep) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "iteration-02" / "agent_result.json"
            sandbox_root = root / "sandbox"
            mission_state_path = root / "mission" / "mission_state.json"
            mission_state_path.parent.mkdir(parents=True, exist_ok=True)
            mission_state_path.write_text(json.dumps({"current_phase": "literature-review"}), encoding="utf-8")
            (sandbox_root / "outputs").mkdir(parents=True, exist_ok=True)
            prompt_file.write_text(
                "\n".join(
                    [
                        "# DeepLoop recursive agent iteration",
                        "",
                        "- loop_action_id: `demo-loop-02`",
                        "- mission_action_id: `demo-mission-action`",
                        "- action_phase: `literature-review`",
                        "- current_phase: `literature-review`",
                        "",
                        "## Current task",
                        "",
                        "Produce the prior-art memo and benchmark watchlist.",
                        "",
                        "## Phase constraints",
                        "",
                        "Required phase outputs:",
                        "- prior-art memo",
                        "- benchmark and method watchlist",
                        "",
                        "Allowed next transitions:",
                        "- `question-design`",
                        "",
                        "Transition metadata:",
                        "- `question-design` via `phase-transition` (branch_status=`active`, recovery_status=`not-needed`): Convert prior-art coverage into concrete hypotheses and targets.",
                        "",
                        "## Output contract",
                        "",
                        "Write a machine-readable result JSON to:",
                        f"- `{result_json_path}`",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (sandbox_root / "outputs" / "prior-art-memo.md").write_text("# Prior art\n", encoding="utf-8")
            (sandbox_root / "outputs" / "benchmark-method-watchlist.yaml").write_text("benchmark: wmt19\n", encoding="utf-8")

            process = MagicMock()
            process.poll.side_effect = [None, None]
            process.communicate.return_value = ("partial stdout", "partial stderr")
            mock_popen.return_value = process

            completed = run_provider_prompt(
                prompt_file,
                result_json_path=result_json_path,
                sandbox_root=sandbox_root,
                mission_state_path=mission_state_path,
                cwd=root,
                idle_timeout_seconds=0,
            )

            synthesized = json.loads(result_json_path.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(synthesized["status"], "continue")
        self.assertEqual(synthesized["phase_control"]["next_phase"], "question-design")
        self.assertEqual(synthesized["continuation"]["role"], "planner")
        self.assertIn("prior-art-memo.md", "\n".join(synthesized["produced_artifacts"]))
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    @patch("deeploop.runtime.provider_launcher.time.sleep", return_value=None)
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_fails_fast_when_only_stale_outputs_exist(self, mock_popen, _mock_sleep) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "iteration-03" / "agent_result.json"
            sandbox_root = root / "sandbox"
            mission_state_path = root / "mission" / "mission_state.json"
            mission_state_path.parent.mkdir(parents=True, exist_ok=True)
            mission_state_path.write_text(json.dumps({"current_phase": "question-design"}), encoding="utf-8")
            (sandbox_root / "outputs").mkdir(parents=True, exist_ok=True)
            stale_hypotheses = sandbox_root / "outputs" / "question-design-hypotheses.json"
            stale_targets = sandbox_root / "outputs" / "question-design-evaluation-targets.json"
            stale_hypotheses.write_text("{}", encoding="utf-8")
            stale_targets.write_text("{}", encoding="utf-8")
            prompt_file.write_text(
                "\n".join(
                    [
                        "# DeepLoop recursive agent iteration",
                        "",
                        "- loop_action_id: `demo-loop-03`",
                        "- mission_action_id: `demo-question-design`",
                        "- action_phase: `question-design`",
                        "- current_phase: `question-design`",
                        "",
                        "## Phase constraints",
                        "",
                        "Required phase outputs:",
                        "- hypotheses",
                        "- evaluation targets",
                        "",
                        "Allowed next transitions:",
                        "- `experiment-design`",
                        "",
                        "Transition metadata:",
                        "- `experiment-design` via `phase-transition` (branch_status=`active`, recovery_status=`not-needed`): Promote the current hypothesis into a concrete execution plan.",
                        "",
                        "## Output contract",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            process = MagicMock()
            process.poll.side_effect = [None, None]
            process.communicate.return_value = ("partial stdout", "partial stderr")
            mock_popen.return_value = process

            completed = run_provider_prompt(
                prompt_file,
                result_json_path=result_json_path,
                sandbox_root=sandbox_root,
                mission_state_path=mission_state_path,
                cwd=root,
                idle_timeout_seconds=0,
            )
            synthesized = json.loads(result_json_path.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(synthesized["status"], "failed")
        self.assertIn("idle", synthesized["summary"].lower())
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    @patch("deeploop.runtime.provider_launcher.time.sleep", return_value=None)
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_recovers_outputs_after_invalid_result_payload(self, mock_popen, _mock_sleep) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "iteration-04" / "agent_result.json"
            sandbox_root = root / "sandbox"
            mission_state_path = root / "mission" / "mission_state.json"
            mission_state_path.parent.mkdir(parents=True, exist_ok=True)
            mission_state_path.write_text(json.dumps({"current_phase": "literature-review"}), encoding="utf-8")
            (sandbox_root / "outputs").mkdir(parents=True, exist_ok=True)
            prompt_file.write_text(
                "\n".join(
                    [
                        "# DeepLoop recursive agent iteration",
                        "",
                        "- loop_action_id: `demo-loop-04`",
                        "- mission_action_id: `demo-lit-review`",
                        "- action_phase: `literature-review`",
                        "- current_phase: `literature-review`",
                        "",
                        "## Current task",
                        "",
                        "Produce the prior-art memo and benchmark watchlist.",
                        "",
                        "## Phase constraints",
                        "",
                        "Required phase outputs:",
                        "- prior-art memo",
                        "- benchmark and method watchlist",
                        "",
                        "Allowed next transitions:",
                        "- `question-design`",
                        "",
                        "Transition metadata:",
                        "- `question-design` via `phase-transition` (branch_status=`active`, recovery_status=`not-needed`): Convert prior-art coverage into concrete hypotheses and targets.",
                    ]
                ),
                encoding="utf-8",
            )
            result_json_path.parent.mkdir(parents=True, exist_ok=True)
            result_json_path.write_text(json.dumps({"status": "continue"}), encoding="utf-8")
            (sandbox_root / "outputs" / "prior-art-memo.md").write_text("# Prior art\n", encoding="utf-8")
            (sandbox_root / "outputs" / "benchmark-method-watchlist.yaml").write_text("benchmark: wmt19\n", encoding="utf-8")

            process = MagicMock()
            process.poll.side_effect = [None, None]
            process.communicate.return_value = ("partial stdout", "partial stderr")
            mock_popen.return_value = process

            completed = run_provider_prompt(
                prompt_file,
                result_json_path=result_json_path,
                sandbox_root=sandbox_root,
                mission_state_path=mission_state_path,
                cwd=root,
                idle_timeout_seconds=0,
            )
            synthesized = json.loads(result_json_path.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(synthesized["status"], "continue")
        self.assertEqual(len(synthesized["warnings"]), len(set(synthesized["warnings"])))
        self.assertTrue(any("result.summary must be a non-empty string" in warning for warning in synthesized["warnings"]))
        self.assertTrue(any("synthesized a canonical phase result" in warning for warning in synthesized["warnings"]))
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    @patch("deeploop.runtime.provider_launcher.time.sleep", return_value=None)
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_materializes_execution_gap_failure_with_artifacts(
        self, mock_popen, _mock_sleep
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "iteration-05" / "agent_result.json"
            sandbox_root = root / "sandbox"
            mission_state_path = root / "mission" / "mission_state.json"
            runtime_root = root / "runtime" / "execution"
            prompt_file.write_text("hello world", encoding="utf-8")
            mission_state_path.parent.mkdir(parents=True, exist_ok=True)
            mission_state_path.write_text(json.dumps({"current_phase": "execution"}), encoding="utf-8")
            (sandbox_root / "outputs").mkdir(parents=True, exist_ok=True)
            (runtime_root / "logs").mkdir(parents=True, exist_ok=True)
            (sandbox_root / "outputs" / "baseline_execution_summary.json").write_text(
                json.dumps({"runtime_root": str(runtime_root), "selected_direction": "en-zh"}),
                encoding="utf-8",
            )
            (runtime_root / "direction_selection.json").write_text(
                json.dumps({"selected_direction": "en-zh"}),
                encoding="utf-8",
            )
            (runtime_root / "logs" / "baseline-wave-1.log").write_text("still running\n", encoding="utf-8")

            process = MagicMock()
            process.poll.side_effect = [None, None]
            process.communicate.return_value = ("partial stdout", "partial stderr")
            mock_popen.return_value = process

            completed = run_provider_prompt(
                prompt_file,
                result_json_path=result_json_path,
                sandbox_root=sandbox_root,
                mission_state_path=mission_state_path,
                cwd=root,
                idle_timeout_seconds=0,
            )
            synthesized = json.loads(result_json_path.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(synthesized["status"], "failed")
        self.assertIn("baseline_execution_summary.json", "\n".join(synthesized["produced_artifacts"]))
        self.assertIn("baseline-wave-1.log", "\n".join(synthesized["produced_artifacts"]))
        self.assertTrue(any("baseline_stage_scoreboard.json" in warning for warning in synthesized["warnings"]))
        self.assertEqual(len(synthesized["warnings"]), len(set(synthesized["warnings"])))
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    @patch("deeploop.runtime.provider_launcher.time.sleep", return_value=None)
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_materializes_failure_when_provider_exits_before_ready_payload(
        self, mock_popen, _mock_sleep
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "iteration-06" / "agent_result.json"
            prompt_file.write_text("hello world", encoding="utf-8")

            process = MagicMock()
            process.poll.side_effect = [17]
            process.communicate.return_value = ("partial stdout", "partial stderr")
            mock_popen.return_value = process

            completed = run_provider_prompt(prompt_file, result_json_path=result_json_path, cwd=root)
            synthesized = json.loads(result_json_path.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 17)
        self.assertEqual(synthesized["status"], "failed")
        self.assertIn("ready agent_result.json", synthesized["summary"])
        self.assertTrue(any("returncode 17" in warning for warning in synthesized["warnings"]))
        self.assertEqual(synthesized["produced_artifacts"], [])

    @patch("deeploop.runtime.provider_launcher.time.sleep", return_value=None)
    @patch("deeploop.runtime.provider_launcher._read_result_payload_state")
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_accepts_ready_payload_that_arrives_just_after_zero_exit(
        self, mock_popen, mock_read_result, _mock_sleep
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "iteration-07" / "agent_result.json"
            prompt_file.write_text("hello world", encoding="utf-8")

            process = MagicMock()
            process.poll.side_effect = [0]
            process.communicate.return_value = ("provider stdout", "provider stderr")
            mock_popen.return_value = process

            mock_read_result.side_effect = [
                (None, ["provider did not write agent_result.json"]),
                (None, ["provider did not write agent_result.json"]),
                ({"status": "continue", "summary": "done"}, []),
            ]

            completed = run_provider_prompt(prompt_file, result_json_path=result_json_path, cwd=root)

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "provider stdout")
        self.assertEqual(completed.stderr, "provider stderr")
        self.assertGreaterEqual(mock_read_result.call_count, 3)

    @patch("deeploop.runtime.provider_launcher._wait_for_ready_result_payload")
    @patch("deeploop.runtime.provider_launcher.subprocess.Popen")
    def test_run_provider_prompt_recovers_valid_result_payload_from_stdout_when_file_is_missing(
        self, mock_popen, mock_wait_for_ready
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "iteration-08" / "agent_result.json"
            prompt_file.write_text("hello world", encoding="utf-8")

            process = MagicMock()
            process.poll.side_effect = [0]
            process.communicate.return_value = (
                "Returned recursive-agent JSON result:\n"
                "{\n"
                '  "status": "continue",\n'
                '  "summary": "advance",\n'
                '  "continuation": {"role": "researcher", "task": "review"},\n'
                '  "action_result": {"status": "done"},\n'
                '  "phase_control": {"current_phase": "idea-intake"}\n'
                "}\n",
                "provider stderr",
            )
            mock_popen.return_value = process
            mock_wait_for_ready.return_value = (None, ["provider did not write agent_result.json"])

            completed = run_provider_prompt(prompt_file, result_json_path=result_json_path, cwd=root)
            recovered = json.loads(result_json_path.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, "provider stderr")
        self.assertEqual(recovered["status"], "continue")
        self.assertEqual(recovered["summary"], "advance")


if __name__ == "__main__":
    unittest.main()
