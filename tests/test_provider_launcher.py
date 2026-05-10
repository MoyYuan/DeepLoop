from __future__ import annotations

import json
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
            "hello world",
            provider_family="copilot-cli",
            add_dirs=[Path("/tmp/demo"), Path("/tmp/demo"), Path("/tmp/other")],
            model="gpt-5.4",
        )
        self.assertEqual(command[:4], ["copilot", "-p", "hello world", "--output-format"])
        self.assertIn("--allow-all", command)
        self.assertIn("--no-ask-user", command)
        self.assertIn("gpt-5.4", command)
        self.assertEqual(command.count("--add-dir"), 2)

    def test_build_command_rejects_unknown_provider_family(self) -> None:
        with self.assertRaises(ValueError):
            build_provider_prompt_command("hello world", provider_family="unknown-provider")

    def test_build_command_for_openai_compatible_api_uses_prompt_file(self) -> None:
        command = build_provider_prompt_command(
            "hello world",
            provider_family="openai-compatible-api",
            prompt_file=Path("/tmp/prompt.md"),
            result_json_path=Path("/tmp/result.json"),
            model="Qwen3.6-27B-UD-Q4_K_XL.gguf",
        )
        self.assertEqual(command[:3], [sys.executable, "-m", "deeploop.runtime.openai_compatible_adapter"])
        self.assertIn("--prompt-file", command)
        self.assertIn("--result-json-path", command)
        self.assertIn("Qwen3.6-27B-UD-Q4_K_XL.gguf", command)

    def test_build_command_for_openai_compatible_api_requires_prompt_file(self) -> None:
        with self.assertRaises(ValueError):
            build_provider_prompt_command("hello world", provider_family="openai-compatible-api")

    def test_resolve_provider_idle_timeout_prefers_longer_copilot_window(self) -> None:
        self.assertEqual(resolve_provider_idle_timeout_seconds("copilot-cli", None), 900.0)
        self.assertEqual(resolve_provider_idle_timeout_seconds("copilot-cli", 30.0), 30.0)
        self.assertEqual(resolve_provider_idle_timeout_seconds("other-provider", None), 120.0)

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


if __name__ == "__main__":
    unittest.main()
