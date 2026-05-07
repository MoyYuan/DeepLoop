from __future__ import annotations

import io
import json
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from deeploop.mission.mission_management import main as manage_mission_main
from runtime_artifact_helpers import fresh_test_root, write_json, write_jsonl

TEST_WORK_ROOT = REPO_ROOT / "tests" / "_runtime_artifacts" / "mission_management"


def _fresh_test_root(name: str) -> Path:
    return fresh_test_root(TEST_WORK_ROOT, name)


def _write_json(path: Path, payload: dict) -> None:
    write_json(path, payload)


def _write_jsonl(path: Path, payloads: list[dict]) -> None:
    write_jsonl(path, payloads)


def _base_state(*, mission_id: str) -> dict:
    return {
        "mission_id": mission_id,
        "mode": "sandboxed-yolo",
        "title": "Mission management test",
        "current_phase": "execution",
        "next_phase": "critique",
        "status": "running",
        "autonomy_status": {"state": "autonomous", "reason": "test"},
        "next_actions": {
            "summary": "Run the baseline and inspect critique evidence.",
            "actions": [
                {
                    "action_id": "run-baseline",
                    "role": "execution-operator",
                    "task": "Run the bounded baseline evaluation.",
                    "kind": "local-eval",
                    "status": "pending",
                    "phase": "execution",
                    "runtime_owner": "deeploop",
                    "requires_operator_approval": False,
                    "executor": {"id": "stage-kernel", "params": {"stage_id": "baseline-evaluation"}},
                }
            ],
        },
    }


def _operator_request(mission_state_path: Path, *, mission_id: str, request_id: str = "demo-operator-request") -> dict:
    return {
        "schema_version": 1,
        "request_id": request_id,
        "mission_id": mission_id,
        "created_at": "2026-04-12T20:01:00Z",
        "status": "open",
        "summary": "Autopilot paused at `sandbox-boundary`: attempted write outside mutable roots.",
        "explanation": "DeepLoop stopped because the requested write crossed the sandbox boundary.",
        "blocker": {
            "kind": "hard-gate",
            "gate": "hard",
            "risk_class": "sandbox-boundary",
            "label": "sandbox escape / writes outside allowed mutable roots",
            "reason": "attempted write outside mutable roots",
            "default_response": "stop-and-escalate",
            "preferred_actions": [],
            "hard_gate_profile": "minimal",
        },
        "context": {
            "mission_state_path": str(mission_state_path),
            "runtime_root": str(mission_state_path.parent / "runtime" / "mission_outer_runtime"),
            "mode": "sandboxed-yolo",
            "phase": "execution",
            "next_phase": "critique",
            "decision_id": "demo-decision",
            "decision_type": "local-eval",
            "action_id": "run-baseline",
            "action_kind": "local-eval",
            "action_task": "Run the bounded baseline evaluation.",
            "branch_id": None,
            "executor_id": "stage-kernel",
        },
        "recommendation": {
            "summary": "Adjust the write target so the action stays inside the sandbox, then resume autopilot.",
            "pros": ["Keeps the default safety posture."],
            "cons": ["Requires a quick operator review."],
        },
        "alternatives": [
            {
                "option_id": "adjust-and-resume",
                "summary": "Keep the action inside the sandbox.",
                "pros": ["Preserves sandboxed-yolo."],
                "cons": ["May require a smaller change."],
                    "next_steps": [f"deeploop resume --mission-state {mission_state_path}"],
            }
        ],
        "next_steps": [
            f"deeploop inbox --mission-state {mission_state_path}",
            f"deeploop resume --mission-state {mission_state_path}",
        ],
        "continue_command": f"deeploop resume --mission-state {mission_state_path}",
    }


def _managed_blocked_request(mission_state_path: Path, *, mission_id: str) -> dict:
    request = _operator_request(
        mission_state_path,
        mission_id=mission_id,
        request_id="demo-managed-triage-request",
    )
    request["summary"] = "Autopilot paused for operator review: Queue `demo-queue` blocked on `blocked-followup`."
    request["blocker"] = {
        "kind": "operator-review",
        "gate": "operator-needed",
        "risk_class": "operator-review",
        "label": "operator review",
        "reason": "Queue `demo-queue` blocked on `blocked-followup`.",
        "details": {
            "queue_name": "demo-queue",
            "blocked_entries": [
                {
                    "entry_id": "blocked-followup",
                    "queue_name": "demo-queue",
                    "summary_json_path": str(mission_state_path.parent / "runtime" / "summary.json"),
                    "summary_markdown_path": str(mission_state_path.parent / "runtime" / "summary.md"),
                    "sanity_verdict": "block",
                    "top_blocking_reasons": [
                        "Need richer mechanistic evidence before intervention.",
                        "Evaluation anchors are still missing.",
                    ],
                }
            ],
        },
    }
    request["context"]["mode"] = "managed"
    request["context"]["blocked_entries"] = request["blocker"]["details"]["blocked_entries"]
    request["recommendation"]["summary"] = "Inspect the blocked entry, optionally run bounded triage, then choose retry or reroute."
    request["next_steps"] = [
        f"deeploop inbox --mission-state {mission_state_path}",
        f"deeploop resume --mission-state {mission_state_path}",
    ]
    return request


class _FakePopen:
    def __init__(self, command: list[str], **kwargs: object) -> None:
        self.command = command
        self.kwargs = kwargs
        self.pid = 4312


class MissionManagementTests(unittest.TestCase):
    def test_export_subcommand_routes_to_submission_export(self) -> None:
        with patch("deeploop.mission.mission_management._export_mission", return_value=0) as mock_export:
            result = manage_mission_main(
                [
                    "export",
                    "--mission-state",
                    "/tmp/mission_state.json",
                    "--output",
                    "/tmp/submission",
                    "--format",
                    "github-repo",
                    "--force",
                ]
            )

        self.assertEqual(result, 0)
        mock_export.assert_called_once()
        args = mock_export.call_args.args[0]
        self.assertEqual(args.mission_state, "/tmp/mission_state.json")
        self.assertEqual(args.output, "/tmp/submission")
        self.assertEqual(args.format, "github-repo")
        self.assertTrue(args.force)

    def test_start_launches_canonical_runtime_and_writes_metadata(self) -> None:
        test_root = _fresh_test_root("start_launches_runtime")
        mission_state_path = test_root / "mission" / "mission_state.json"
        launch_metadata_path = test_root / "launch" / "launch.json"
        log_path = test_root / "launch" / "launch.log"
        _write_json(mission_state_path, _base_state(mission_id="demo-start"))

        _clean_git = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        stdout = io.StringIO()
        with patch("deeploop.mission.mission_management.subprocess.run", return_value=_clean_git):
            with patch("deeploop.mission.mission_management.subprocess.Popen", side_effect=_FakePopen) as mock_popen:
                with redirect_stdout(stdout):
                    result = manage_mission_main(
                        [
                            "start",
                            "--mission-state",
                            str(mission_state_path),
                            "--launch-metadata",
                            str(launch_metadata_path),
                            "--log-path",
                            str(log_path),
                            "--max-iterations",
                            "7",
                        ]
                    )

        self.assertEqual(result, 0)
        self.assertEqual(mock_popen.call_count, 1)
        metadata = json.loads(launch_metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["mission_id"], "demo-start")
        self.assertEqual(metadata["pid"], 4312)
        self.assertEqual(metadata["launch_reason"], "start")
        self.assertIn("workspace_root", metadata)
        self.assertEqual(Path(metadata["command"][1]).resolve(), REPO_ROOT / "scripts" / "mission" / "run_mission.py")
        self.assertEqual(metadata["command"][-1], "7")
        self.assertIn("DeepLoop autopilot started", stdout.getvalue())
        self.assertIn("workspace_root", stdout.getvalue())
        self.assertIn("deeploop status", stdout.getvalue())
        self.assertIn("deeploop start", log_path.read_text(encoding="utf-8"))

    def test_start_uses_configured_launch_env_when_present(self) -> None:
        test_root = _fresh_test_root("start_uses_launch_env")
        mission_state_path = test_root / "mission" / "mission_state.json"
        launch_metadata_path = test_root / "launch" / "launch.json"
        log_path = test_root / "launch" / "launch.log"
        mission_state = _base_state(mission_id="demo-start-env")
        mission_state["runtime_launcher"] = {"env_name": "llm"}
        _write_json(mission_state_path, mission_state)

        _clean_git = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("deeploop.mission.mission_management.subprocess.run", return_value=_clean_git):
            with patch("deeploop.mission.mission_management.subprocess.Popen", side_effect=_FakePopen) as mock_popen:
                result = manage_mission_main(
                    [
                        "start",
                        "--mission-state",
                        str(mission_state_path),
                        "--launch-metadata",
                        str(launch_metadata_path),
                        "--log-path",
                        str(log_path),
                    ]
                )

        self.assertEqual(result, 0)
        self.assertEqual(mock_popen.call_count, 1)
        command = mock_popen.call_args.args[0]
        self.assertEqual(command[:5], ["conda", "run", "-n", "llm", "python"])
        self.assertEqual(Path(command[5]).resolve(), REPO_ROOT / "scripts" / "mission" / "run_mission.py")

    def test_start_uses_configured_max_iterations_when_cli_omitted(self) -> None:
        test_root = _fresh_test_root("start_uses_configured_iterations")
        mission_state_path = test_root / "mission" / "mission_state.json"
        launch_metadata_path = test_root / "launch" / "launch.json"
        log_path = test_root / "launch" / "launch.log"
        mission_state = _base_state(mission_id="demo-start-iterations")
        mission_state["runtime_launcher"] = {"env_name": "llm", "max_iterations": 33}
        _write_json(mission_state_path, mission_state)

        _clean_git = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("deeploop.mission.mission_management.subprocess.run", return_value=_clean_git):
            with patch("deeploop.mission.mission_management.subprocess.Popen", side_effect=_FakePopen) as mock_popen:
                result = manage_mission_main(
                    [
                        "start",
                        "--mission-state",
                        str(mission_state_path),
                        "--launch-metadata",
                        str(launch_metadata_path),
                        "--log-path",
                        str(log_path),
                    ]
                )

        self.assertEqual(result, 0)
        command = mock_popen.call_args.args[0]
        self.assertEqual(command[-1], "33")
        metadata = json.loads(launch_metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["max_iterations"], 33)

    def test_start_injects_runtime_cache_env_for_editable_install(self) -> None:
        """When the package is editable, start should snapshot src and set DEEPLOOP_RUNTIME_CACHE_SRC."""
        import importlib.metadata as _meta
        from deeploop.mission.mission_management import _snapshot_src_for_mission

        test_root = _fresh_test_root("start_runtime_cache")
        mission_state_path = test_root / "mission" / "mission_state.json"
        launch_metadata_path = test_root / "launch" / "launch.json"
        log_path = test_root / "launch" / "launch.log"
        _write_json(mission_state_path, _base_state(mission_id="demo-cache"))

        cache_src = test_root / "fake_cache" / "src"
        cache_pkg = cache_src / "deeploop"
        cache_pkg.mkdir(parents=True, exist_ok=True)
        (cache_pkg / "__init__.py").write_text("")

        _clean_git = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("deeploop.mission.mission_management.subprocess.run", return_value=_clean_git):
            with patch(
                "deeploop.mission.mission_management._snapshot_src_for_mission",
                return_value=cache_src,
            ):
                with patch("deeploop.mission.mission_management.subprocess.Popen", side_effect=_FakePopen) as mock_popen:
                    result = manage_mission_main(
                        [
                            "start",
                            "--mission-state",
                            str(mission_state_path),
                            "--launch-metadata",
                            str(launch_metadata_path),
                            "--log-path",
                            str(log_path),
                        ]
                    )

        self.assertEqual(result, 0)
        self.assertEqual(mock_popen.call_count, 1)
        popen_kwargs = mock_popen.call_args.kwargs
        self.assertIn("env", popen_kwargs)
        self.assertEqual(popen_kwargs["env"].get("DEEPLOOP_RUNTIME_CACHE_SRC"), str(cache_src))
        metadata = json.loads(launch_metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["runtime_cache_src"], str(cache_src))

    def test_snapshot_src_returns_none_for_non_editable_install(self) -> None:
        """_snapshot_src_for_mission should return None for a non-editable install."""
        from deeploop.mission.mission_management import _snapshot_src_for_mission

        with patch("deeploop.mission.mission_management._is_editable_install", return_value=False):
            result = _snapshot_src_for_mission("test-mission", "2026-04-26T18:00:00Z")

        self.assertIsNone(result)

    def test_snapshot_src_uses_unique_paths_within_same_second(self) -> None:
        from deeploop.mission.mission_management import _snapshot_src_for_mission

        test_root = _fresh_test_root("start_runtime_cache_unique_paths")
        fake_repo_root = test_root / "repo"
        fake_pkg_src = fake_repo_root / "src" / "deeploop"
        fake_pkg_src.mkdir(parents=True, exist_ok=True)
        (fake_pkg_src / "__init__.py").write_text("__version__ = '0.1.0'\n", encoding="utf-8")
        runtime_cache_root = test_root / "runtime_cache"

        with patch("deeploop.mission.mission_management._is_editable_install", return_value=True):
            with patch("deeploop.mission.mission_management.REPO_ROOT", fake_repo_root):
                with patch("deeploop.mission.mission_management._RUNTIME_CACHE_ROOT", runtime_cache_root):
                    first = _snapshot_src_for_mission("demo-cache", "2026-04-26T18:00:00.123456+00:00")
                    second = _snapshot_src_for_mission("demo-cache", "2026-04-26T18:00:00.654321+00:00")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)
        self.assertTrue((first / "deeploop" / "__init__.py").exists())
        self.assertTrue((second / "deeploop" / "__init__.py").exists())

    def test_snapshot_src_includes_repo_level_runtime_assets(self) -> None:
        from deeploop.mission.mission_management import _snapshot_src_for_mission

        test_root = _fresh_test_root("start_runtime_cache_repo_assets")
        fake_repo_root = test_root / "repo"
        fake_pkg_src = fake_repo_root / "src" / "deeploop"
        fake_pkg_src.mkdir(parents=True, exist_ok=True)
        (fake_pkg_src / "__init__.py").write_text("__version__ = '0.1.0'\n", encoding="utf-8")
        (fake_repo_root / "configs" / "autonomy").mkdir(parents=True, exist_ok=True)
        (fake_repo_root / "configs" / "autonomy" / "mission-outer-loop.yaml").write_text("mode: test\n", encoding="utf-8")
        (fake_repo_root / "schemas").mkdir(parents=True, exist_ok=True)
        (fake_repo_root / "schemas" / "mission-state.schema.json").write_text("{}", encoding="utf-8")
        (fake_repo_root / "scripts" / "runtime").mkdir(parents=True, exist_ok=True)
        (fake_repo_root / "scripts" / "runtime" / "invoke_provider_prompt.py").write_text("print('ok')\n", encoding="utf-8")
        (fake_repo_root / "AGENTS.md").write_text("runtime rules\n", encoding="utf-8")
        runtime_cache_root = test_root / "runtime_cache"

        with patch("deeploop.mission.mission_management._is_editable_install", return_value=True):
            with patch("deeploop.mission.mission_management.REPO_ROOT", fake_repo_root):
                with patch("deeploop.mission.mission_management._RUNTIME_CACHE_ROOT", runtime_cache_root):
                    cache_src = _snapshot_src_for_mission("demo-cache", "2026-04-26T18:00:00.123456+00:00")

        self.assertIsNotNone(cache_src)
        cache_root = cache_src.parent
        self.assertTrue((cache_src / "deeploop" / "__init__.py").exists())
        self.assertEqual(
            (cache_root / "configs" / "autonomy" / "mission-outer-loop.yaml").read_text(encoding="utf-8"),
            "mode: test\n",
        )
        self.assertEqual((cache_root / "schemas" / "mission-state.schema.json").read_text(encoding="utf-8"), "{}")
        self.assertEqual(
            (cache_root / "scripts" / "runtime" / "invoke_provider_prompt.py").read_text(encoding="utf-8"),
            "print('ok')\n",
        )
        self.assertEqual((cache_root / "AGENTS.md").read_text(encoding="utf-8"), "runtime rules\n")

    def test_status_logs_and_decisions_surface_operator_views(self) -> None:
        test_root = _fresh_test_root("status_logs_decisions")
        mission_root = test_root / "mission"
        mission_state_path = mission_root / "mission_state.json"
        decision_log_path = mission_root / "mission_decisions.jsonl"
        branch_log_path = mission_root / "mission_branches.jsonl"
        operator_request_log_path = mission_root / "mission_operator_requests.jsonl"
        current_operator_request_path = mission_root / "current_operator_request.json"
        launch_metadata_path = test_root / "launch" / "launch.json"
        log_path = test_root / "launch" / "launch.log"
        stage_root = test_root / "stage-run"
        stage_manifest_path = stage_root / "run_manifest.json"
        stage_runtime_report_path = stage_root / "runtime_report.json"
        stage_summary_path = stage_root / "study_summary.json"

        mission_state = _base_state(mission_id="demo-status")
        mission_state["outer_loop"] = {
            "policy_name": "deeploop-mission-outer-loop",
            "decision_log_path": str(decision_log_path),
            "branch_log_path": str(branch_log_path),
            "operator_request_log_path": str(operator_request_log_path),
            "current_operator_request_path": str(current_operator_request_path),
        }
        mission_state["stage_runs"] = {
            "baseline-evaluation": {
                "status": "completed",
                "output_dir": str(stage_root),
                "manifest_path": str(stage_manifest_path),
                "summary_path": str(stage_summary_path),
            }
        }
        _write_json(mission_state_path, mission_state)
        _write_json(
            stage_runtime_report_path,
            {
                "telemetry": {
                    "elapsed_s": 12.0,
                    "executed_examples": 8,
                    "samples_per_s": 1.0,
                    "peak_vram_mb": 4096,
                },
                "budget": {
                    "prompt_token_budget": 256,
                    "prompt_token_utilization": 0.5,
                    "selected_batch_size": 4,
                    "batch_probe_order": [16, 8, 4],
                    "gpu_memory_headroom_gb": 6,
                },
            },
        )
        _write_json(
            stage_manifest_path,
            {
                "runtime": {
                    "runtime_report_path": str(stage_runtime_report_path),
                },
                "stage_context": {
                    "dataset_record_count": 16,
                    "artifacts": {"runtime_report_path": str(stage_runtime_report_path)},
                },
            },
        )
        _write_json(stage_summary_path, {"stage_id": "baseline-evaluation", "status": "completed", "executed_examples": 8})
        _write_jsonl(
            decision_log_path,
            [
                {
                    "decision_id": "demo-decision",
                    "mission_id": "demo-status",
                    "decision_type": "local-eval",
                    "summary": "Dispatch the baseline stage.",
                    "phase": "execution",
                    "authority": {
                        "mode": "autonomous",
                        "requires_operator_approval": False,
                        "approval_state": "not-required",
                    },
                    "result": {"status": "selected", "recorded_at": "2026-04-12T20:00:00Z"},
                    "selected_action_ids": ["run-baseline"],
                    "selected_branch_ids": [],
                    "notes": ["metrics still pending"],
                }
            ],
        )
        _write_jsonl(branch_log_path, [])
        operator_request = _operator_request(mission_state_path, mission_id="demo-status")
        _write_jsonl(operator_request_log_path, [operator_request])
        _write_json(current_operator_request_path, operator_request)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")
        _write_json(
            launch_metadata_path,
            {
                "pid": 999999,
                "started_at": "2026-04-12T20:00:00Z",
                "log_path": str(log_path),
            },
        )

        status_stdout = io.StringIO()
        with redirect_stdout(status_stdout):
            status_result = manage_mission_main(
                ["status", "--mission-state", str(mission_state_path), "--launch-metadata", str(launch_metadata_path)]
            )
        self.assertEqual(status_result, 0)
        self.assertIn("# DeepLoop operator console", status_stdout.getvalue())
        self.assertIn("## Top summary", status_stdout.getvalue())
        self.assertIn("operator_state: `operator-action-required`", status_stdout.getvalue())
        self.assertIn("next_step_owner: `operator`", status_stdout.getvalue())
        self.assertIn("focus_action: `run-baseline`", status_stdout.getvalue())
        self.assertIn("## Exact next commands", status_stdout.getvalue())
        self.assertIn("latest_decision", status_stdout.getvalue())
        self.assertIn("## Operator inbox", status_stdout.getvalue())
        self.assertIn("demo-operator-request", status_stdout.getvalue())
        self.assertIn("## Inner-loop progress", status_stdout.getvalue())
        self.assertIn("active_stage: `baseline-evaluation`", status_stdout.getvalue())
        self.assertIn("token_budget_summary", status_stdout.getvalue())

        logs_stdout = io.StringIO()
        with redirect_stdout(logs_stdout):
            logs_result = manage_mission_main(
                [
                    "logs",
                    "--mission-state",
                    str(mission_state_path),
                    "--launch-metadata",
                    str(launch_metadata_path),
                    "--lines",
                    "2",
                ]
            )
        self.assertEqual(logs_result, 0)
        self.assertIn("line-2", logs_stdout.getvalue())
        self.assertIn("line-3", logs_stdout.getvalue())
        self.assertNotIn("line-1", logs_stdout.getvalue())

        decisions_stdout = io.StringIO()
        with redirect_stdout(decisions_stdout):
            decisions_result = manage_mission_main(
                ["decisions", "--mission-state", str(mission_state_path), "--limit", "1"]
            )
        self.assertEqual(decisions_result, 0)
        self.assertIn("demo-decision", decisions_stdout.getvalue())
        self.assertIn("Dispatch the baseline stage.", decisions_stdout.getvalue())
        self.assertIn("run-baseline", decisions_stdout.getvalue())

        inbox_stdout = io.StringIO()
        with redirect_stdout(inbox_stdout):
            inbox_result = manage_mission_main(["inbox", "--mission-state", str(mission_state_path)])
        self.assertEqual(inbox_result, 0)
        self.assertIn("demo-operator-request", inbox_stdout.getvalue())
        self.assertIn("## Operator summary", inbox_stdout.getvalue())
        self.assertIn("attention_level: `action-required`", inbox_stdout.getvalue())
        self.assertIn("resume_policy: `resume-after-fix`", inbox_stdout.getvalue())
        self.assertIn("## Exact next commands", inbox_stdout.getvalue())
        self.assertIn("continue_command", inbox_stdout.getvalue())

    def test_stop_requests_shutdown_for_tracked_launch(self) -> None:
        test_root = _fresh_test_root("stop_requests_shutdown")
        mission_state_path = test_root / "mission" / "mission_state.json"
        launch_metadata_path = test_root / "launch" / "launch.json"
        _write_json(mission_state_path, _base_state(mission_id="demo-stop"))
        _write_json(
            launch_metadata_path,
            {
                "pid": 4321,
                "process_group_id": 4321,
                "started_at": "2026-04-12T20:00:00Z",
                "log_path": str(test_root / "launch" / "launch.log"),
            },
        )

        stdout = io.StringIO()
        with patch("deeploop.mission.mission_management._pid_is_running", return_value=True):
            with patch("deeploop.mission.mission_management.os.killpg") as mock_killpg:
                with redirect_stdout(stdout):
                    result = manage_mission_main(
                        [
                            "stop",
                            "--mission-state",
                            str(mission_state_path),
                            "--launch-metadata",
                            str(launch_metadata_path),
                        ]
                    )

        self.assertEqual(result, 0)
        mock_killpg.assert_called_once_with(4321, signal.SIGTERM)
        metadata = json.loads(launch_metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["stop_signal"], "SIGTERM")
        self.assertIn("DeepLoop stop requested", stdout.getvalue())

    def test_help_lists_management_subcommands(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "mission" / "manage_mission.py"), "--help"],
            check=False,
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIn("start", completed.stdout)
        self.assertIn("status", completed.stdout)
        self.assertIn("logs", completed.stdout)
        self.assertIn("decisions", completed.stdout)
        self.assertIn("inbox", completed.stdout)
        self.assertIn("stop", completed.stdout)
        self.assertIn("resume", completed.stdout)
        self.assertIn("retry", completed.stdout)
        self.assertIn("reroute", completed.stdout)
        self.assertIn("triage", completed.stdout)
        self.assertIn("watch", completed.stdout)
        self.assertIn("analyze", completed.stdout)
        self.assertIn("analyze-budget", completed.stdout)

    def test_retry_records_operator_feedback_and_guides_resume(self) -> None:
        test_root = _fresh_test_root("retry_records_feedback")
        mission_root = test_root / "mission"
        mission_state_path = mission_root / "mission_state.json"
        decision_log_path = mission_root / "mission_decisions.jsonl"
        branch_log_path = mission_root / "mission_branches.jsonl"
        operator_request_log_path = mission_root / "mission_operator_requests.jsonl"
        current_operator_request_path = mission_root / "current_operator_request.json"
        mission_state = _base_state(mission_id="demo-retry")
        mission_state["status"] = "blocked"
        mission_state["autonomy_status"] = {"state": "mission-runtime-blocked", "reason": "Awaiting operator review."}
        mission_state["outer_loop"] = {
            "hard_gate_profile": "minimal",
            "decision_log_path": str(decision_log_path),
            "branch_log_path": str(branch_log_path),
            "operator_request_log_path": str(operator_request_log_path),
            "current_operator_request_path": str(current_operator_request_path),
        }
        _write_json(mission_state_path, mission_state)
        _write_jsonl(decision_log_path, [])
        _write_jsonl(branch_log_path, [])
        operator_request = _operator_request(mission_state_path, mission_id="demo-retry")
        _write_jsonl(operator_request_log_path, [operator_request])
        _write_json(current_operator_request_path, operator_request)

        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            result = manage_mission_main(
                ["retry", "--mission-state", str(mission_state_path), "--note", "write target fixed inside sandbox"]
            )

        self.assertEqual(result, 0)
        updated_request = json.loads(current_operator_request_path.read_text(encoding="utf-8"))
        self.assertEqual(updated_request["operator_response"]["action"], "retry")
        self.assertEqual(updated_request["operator_response"]["note"], "write target fixed inside sandbox")
        ledger_lines = (mission_root / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any('"kind": "operator-feedback"' in line for line in ledger_lines))
        self.assertIn("DeepLoop operator decision recorded", stdout.getvalue())
        self.assertIn("deeploop resume", stdout.getvalue())
        self.assertIn("operator_feedback: `retry`", stdout.getvalue())

    def test_resume_surfaces_recorded_operator_feedback(self) -> None:
        test_root = _fresh_test_root("resume_surfaces_feedback")
        mission_root = test_root / "mission"
        mission_state_path = mission_root / "mission_state.json"
        decision_log_path = mission_root / "mission_decisions.jsonl"
        branch_log_path = mission_root / "mission_branches.jsonl"
        operator_request_log_path = mission_root / "mission_operator_requests.jsonl"
        current_operator_request_path = mission_root / "current_operator_request.json"
        launch_metadata_path = test_root / "launch" / "launch.json"
        log_path = test_root / "launch" / "launch.log"
        mission_state = _base_state(mission_id="demo-resume")
        mission_state["status"] = "blocked"
        mission_state["autonomy_status"] = {"state": "mission-runtime-blocked", "reason": "Awaiting operator review."}
        mission_state["outer_loop"] = {
            "hard_gate_profile": "minimal",
            "decision_log_path": str(decision_log_path),
            "branch_log_path": str(branch_log_path),
            "operator_request_log_path": str(operator_request_log_path),
            "current_operator_request_path": str(current_operator_request_path),
        }
        _write_json(mission_state_path, mission_state)
        _write_jsonl(decision_log_path, [])
        _write_jsonl(branch_log_path, [])
        operator_request = _operator_request(mission_state_path, mission_id="demo-resume")
        operator_request["operator_response"] = {
            "action": "reroute",
            "recorded_at": "2026-04-12T20:05:00Z",
            "note": "downscope to the in-sandbox path",
            "command": f"deeploop reroute --mission-state {mission_state_path}",
        }
        _write_jsonl(operator_request_log_path, [operator_request])
        _write_json(current_operator_request_path, operator_request)

        stdout = io.StringIO()
        with patch("deeploop.mission.mission_management.subprocess.Popen", side_effect=_FakePopen):
            with redirect_stdout(stdout):
                result = manage_mission_main(
                    [
                        "resume",
                        "--mission-state",
                        str(mission_state_path),
                        "--launch-metadata",
                        str(launch_metadata_path),
                        "--log-path",
                        str(log_path),
                    ]
                )

        self.assertEqual(result, 0)
        self.assertIn("## Resume handoff", stdout.getvalue())
        self.assertIn("operator_feedback: `reroute`", stdout.getvalue())
        self.assertIn("operator_note: downscope to the in-sandbox path", stdout.getvalue())

    def test_triage_runs_bounded_hook_for_managed_blocked_request(self) -> None:
        test_root = _fresh_test_root("triage_runs_managed_hook")
        mission_root = test_root / "mission"
        mission_state_path = mission_root / "mission_state.json"
        decision_log_path = mission_root / "mission_decisions.jsonl"
        branch_log_path = mission_root / "mission_branches.jsonl"
        operator_request_log_path = mission_root / "mission_operator_requests.jsonl"
        current_operator_request_path = mission_root / "current_operator_request.json"
        mission_state = _base_state(mission_id="demo-managed-triage")
        mission_state["mode"] = "managed"
        mission_state["target_repo"] = str(REPO_ROOT)
        mission_state["status"] = "blocked"
        mission_state["autonomy_status"] = {"state": "mission-runtime-blocked", "reason": "Awaiting operator review."}
        mission_state["outer_loop"] = {
            "hard_gate_profile": "minimal",
            "decision_log_path": str(decision_log_path),
            "branch_log_path": str(branch_log_path),
            "operator_request_log_path": str(operator_request_log_path),
            "current_operator_request_path": str(current_operator_request_path),
            "intervention_profile": "hook-enabled",
        }
        _write_json(mission_state_path, mission_state)
        _write_jsonl(decision_log_path, [])
        _write_jsonl(branch_log_path, [])
        operator_request = _managed_blocked_request(mission_state_path, mission_id="demo-managed-triage")
        _write_jsonl(operator_request_log_path, [operator_request])
        _write_json(current_operator_request_path, operator_request)

        def _fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            result_path = Path(command[command.index("--result-json-path") + 1])
            _write_json(
                result_path,
                {
                    "status": "completed",
                    "summary": "The block is real but a reroute is sufficient until mechanistic evidence matures.",
                    "recommended_operator_action": "reroute",
                    "recommended_resume_action": "Record a reroute that keeps only the mechanistic path active before resume.",
                    "findings": [
                        "The queue blocked on the intervention follow-up, not the mechanistic branch.",
                        "The current evidence is not strong enough for intervention.",
                    ],
                    "evidence_paths": [str(mission_root / "runtime" / "summary.json")],
                    "notes": ["Stay inside the existing managed-mode boundary."],
                },
            )
            return subprocess.CompletedProcess(command, 0, "triage complete\n", "")

        stdout = io.StringIO()
        with patch("deeploop.mission.mission_management.subprocess.run", side_effect=_fake_run):
            with redirect_stdout(stdout):
                result = manage_mission_main(["triage", "--mission-state", str(mission_state_path)])

        self.assertEqual(result, 0)
        self.assertIn("DeepLoop bounded triage", stdout.getvalue())
        self.assertIn("recommended_operator_action: `reroute`", stdout.getvalue())
        report_path = mission_root / "runtime" / "operator_triage" / "demo-managed-triage-request" / "triage_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["result"]["recommended_operator_action"], "reroute")
        ledger_lines = (mission_root / "ledger.jsonl").read_text(encoding="utf-8")
        self.assertIn('"kind": "operator-triage"', ledger_lines)

        inbox_stdout = io.StringIO()
        with redirect_stdout(inbox_stdout):
            inbox_result = manage_mission_main(["inbox", "--mission-state", str(mission_state_path)])
        self.assertEqual(inbox_result, 0)
        self.assertIn("deeploop triage", inbox_stdout.getvalue())

    def test_triage_rejects_non_zero_subprocess_even_with_result_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mission_root = Path(tmpdir)
            mission_state_path = mission_root / "mission_state.json"
            decision_log_path = mission_root / "decisions.jsonl"
            branch_log_path = mission_root / "branches.jsonl"
            operator_request_log_path = mission_root / "operator_requests.jsonl"
            current_operator_request_path = mission_root / "current_operator_request.json"
            mission_state = _base_state(mission_id="demo-managed-triage-failure")
            mission_state["mode"] = "managed"
            mission_state["target_repo"] = str(REPO_ROOT)
            mission_state["status"] = "blocked"
            mission_state["autonomy_status"] = {"state": "mission-runtime-blocked", "reason": "Awaiting operator review."}
            mission_state["outer_loop"] = {
                "hard_gate_profile": "minimal",
                "decision_log_path": str(decision_log_path),
                "branch_log_path": str(branch_log_path),
                "operator_request_log_path": str(operator_request_log_path),
                "current_operator_request_path": str(current_operator_request_path),
                "intervention_profile": "hook-enabled",
            }
            _write_json(mission_state_path, mission_state)
            _write_jsonl(decision_log_path, [])
            _write_jsonl(branch_log_path, [])
            operator_request = _managed_blocked_request(
                mission_state_path,
                mission_id="demo-managed-triage-failure",
            )
            _write_jsonl(operator_request_log_path, [operator_request])
            _write_json(current_operator_request_path, operator_request)

            def _fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                result_path = Path(command[command.index("--result-json-path") + 1])
                _write_json(
                    result_path,
                    {
                        "status": "completed",
                        "summary": "This should not be accepted because the subprocess failed.",
                    },
                )
                return subprocess.CompletedProcess(command, 2, "", "triage failed\n")

            stderr = io.StringIO()
            with patch("deeploop.mission.mission_management.subprocess.run", side_effect=_fake_run):
                with redirect_stderr(stderr):
                    result = manage_mission_main(["triage", "--mission-state", str(mission_state_path)])

        self.assertEqual(result, 1)
        self.assertIn("Bounded triage subprocess exited 2", stderr.getvalue())

    def test_watch_surfaces_alarm_when_state_changes(self) -> None:
        mission_state_path = Path("/tmp/demo-watch-mission-state.json")
        snapshots = [
            {
                "mission": {"status": "running"},
                "operator_console": {
                    "operator_state": "autopilot-running",
                    "attention_level": "passive",
                    "process_status": "running",
                    "summary": "Dispatch `launch-mechanistic-probe` through executor `stage-kernel`.",
                    "focus_action_id": "launch-mechanistic-probe",
                    "focus_executor_id": "stage-kernel",
                },
            },
            {
                "mission": {"status": "blocked"},
                "operator_console": {
                    "operator_state": "operator-action-required",
                    "attention_level": "action-required",
                    "process_status": "running",
                    "summary": "Queue `demo-queue` blocked on `blocked-followup`.",
                    "request_id": "demo-managed-triage-request",
                    "focus_action_id": "run-followup-queue",
                    "focus_executor_id": "self-healing-queue",
                },
            },
        ]

        stdout = io.StringIO()
        with patch("deeploop.mission.mission_management._resolve_snapshot", side_effect=snapshots):
            with patch("deeploop.mission.mission_management.time.sleep", return_value=None):
                with redirect_stdout(stdout):
                    result = manage_mission_main(
                        [
                            "watch",
                            "--mission-state",
                            str(mission_state_path),
                            "--polls",
                            "2",
                            "--interval-seconds",
                            "0",
                        ]
                    )

        self.assertEqual(result, 0)
        output = stdout.getvalue()
        self.assertIn("INFO poll=1", output)
        self.assertIn("ALARM poll=2", output)
        self.assertIn("demo-managed-triage-request", output)

    def test_analyze_budget_reports_ok_for_small_queue(self) -> None:
        test_root = _fresh_test_root("analyze_budget_ok")
        mission_root = test_root / "mission"
        mission_state_path = mission_root / "mission_state.json"
        mission_state = _base_state(mission_id="demo-analyze-budget-ok")
        _write_json(mission_state_path, mission_state)

        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            result = manage_mission_main(
                ["analyze-budget", "--mission-state", str(mission_state_path)]
            )

        self.assertEqual(result, 0)
        output = stdout.getvalue()
        self.assertIn("max_iterations", output)
        self.assertIn("pending_actions", output)
        self.assertIn("status: `ok`", output)

    def test_analyze_budget_reports_over_budget_for_large_queue(self) -> None:
        test_root = _fresh_test_root("analyze_budget_over")
        mission_root = test_root / "mission"
        mission_state_path = mission_root / "mission_state.json"
        mission_state = _base_state(mission_id="demo-analyze-budget-over")
        many_actions = [
            {
                "action_id": f"job-{i:03d}",
                "role": "execution-operator",
                "task": f"Run baseline job {i}.",
                "status": "pending",
                "phase": "execution",
            }
            for i in range(72)
        ]
        mission_state["next_actions"] = {"summary": "Large baseline queue.", "actions": many_actions}
        _write_json(mission_state_path, mission_state)

        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            result = manage_mission_main(
                ["analyze-budget", "--mission-state", str(mission_state_path)]
            )

        self.assertEqual(result, 1)
        output = stdout.getvalue()
        self.assertIn("over-budget", output)
        self.assertIn("WARNING", output)

    def test_analyze_budget_json_flag_emits_structured_report(self) -> None:
        test_root = _fresh_test_root("analyze_budget_json")
        mission_root = test_root / "mission"
        mission_state_path = mission_root / "mission_state.json"
        mission_state = _base_state(mission_id="demo-analyze-budget-json")
        _write_json(mission_state_path, mission_state)

        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            manage_mission_main(
                ["analyze-budget", "--mission-state", str(mission_state_path), "--json"]
            )

        report = json.loads(stdout.getvalue())
        self.assertIn("max_iterations", report)
        self.assertIn("pending_actions", report)
        self.assertIn("status", report)
        self.assertIn("warnings", report)
        self.assertIsInstance(report["warnings"], list)


if __name__ == "__main__":
    unittest.main()
