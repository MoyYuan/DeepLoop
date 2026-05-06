from __future__ import annotations

import json
import os
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

from deeploop.core.ledger import append_jsonl, make_ledger_entry
from deeploop.mission.mission_monitor import build_mission_snapshot, render_mission_snapshot
from runtime_artifact_helpers import fresh_test_root, write_json, write_jsonl

TEST_WORK_ROOT = REPO_ROOT / "tests" / "_runtime_artifacts" / "mission_monitor"


def _fresh_test_root(name: str) -> Path:
    return fresh_test_root(TEST_WORK_ROOT, name)


def _write_json(path: Path, payload: dict) -> None:
    write_json(path, payload)


def _write_jsonl(path: Path, payloads: list[dict]) -> None:
    write_jsonl(path, payloads)


class MissionMonitorTests(unittest.TestCase):
    def test_snapshot_collects_progress_runtime_and_logs(self) -> None:
        test_root = _fresh_test_root("collects_progress_runtime_and_logs")
        mission_root = test_root / "mission"
        progress_root = mission_root / "runtime" / "end_to_end_smoke"
        progress_root.mkdir(parents=True, exist_ok=True)

        mission_state_path = mission_root / "mission_state.json"
        runtime_summary_path = mission_root / "runtime" / "self_healing_runtime" / "demo-queue" / "queue_summary.json"
        _write_json(
            runtime_summary_path,
            {
                "queue_name": "demo-queue",
                "counts": {
                    "completed_jobs": 1,
                    "blocked_jobs": 0,
                    "warned_jobs": 0,
                    "failed_jobs": 0,
                    "recovered_jobs": 1,
                    "rerouted_jobs": 1,
                    "resumed_jobs": 0,
                },
                "entries": {
                    "baseline-job": {
                        "final_status": "rerouted",
                        "summary_json_path": str(runtime_summary_path),
                        "history_path": str(runtime_summary_path.with_name("baseline-job-history.jsonl")),
                        "next_route_to": "mechanistic-localization",
                    }
                },
            },
        )
        _write_json(
            progress_root / "progress.json",
            {
                "step": "baseline-queue",
                "status": "completed",
                "updated_at": "2026-04-12T17:00:00Z",
                "details": {"completed_jobs": 1},
            },
        )
        _write_json(
            progress_root / "summary.json",
            {
                "artifacts": {
                    "package_manifest": str(progress_root / "package-manifest.json"),
                    "package_summary": str(progress_root / "package-summary.md"),
                }
            },
        )
        log_path = progress_root / "launch.log"
        log_path.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")
        _write_json(
            progress_root / "launch.json",
            {"pid": os.getpid(), "started_at": "2026-04-12T17:00:00Z", "log_path": str(log_path)},
        )
        _write_json(
            mission_state_path,
            {
                "mission_id": "demo-mission",
                "title": "Demo mission",
                "current_phase": "execution",
                "next_phase": "critique",
                "status": "running",
                "autonomy_status": {"state": "runtime-self-healed", "reason": "Recovered a job."},
                "runtime_recovery": {"report_json_path": str(runtime_summary_path)},
                "end_to_end_smoke": {"summary_json_path": str(progress_root / "summary.json")},
            },
        )
        append_jsonl(
            mission_root / "ledger.jsonl",
            make_ledger_entry(
                kind="autoexec-queue",
                mission_id="demo-mission",
                summary="Processed demo queue",
                status="completed",
                related_paths=[str(runtime_summary_path)],
            ),
        )

        snapshot = build_mission_snapshot(mission_state_path, log_tail_lines=2, ledger_tail=1)
        self.assertEqual(snapshot["mission"]["mission_id"], "demo-mission")
        self.assertEqual(snapshot["progress"]["step"], "baseline-queue")
        self.assertEqual(snapshot["runtime_recovery"]["counts"]["recovered_jobs"], 1)
        self.assertEqual(snapshot["launch"]["process_status"], "running")
        self.assertEqual(snapshot["log_tail"], ["line-2", "line-3"])
        self.assertEqual(snapshot["failures"]["last_reroute"]["entry_id"], "baseline-job")

        rendered = render_mission_snapshot(snapshot)
        self.assertIn("# DeepLoop operator console", rendered)
        self.assertIn("## Top summary", rendered)
        self.assertIn("## Current progress", rendered)
        self.assertIn("## Runtime queue", rendered)
        self.assertIn("Processed demo queue", rendered)

    def test_snapshot_surfaces_outer_loop_action_branch_budget_and_promotion(self) -> None:
        test_root = _fresh_test_root("surfaces_outer_loop_action_branch_budget_and_promotion")
        mission_root = test_root / "mission"
        runtime_root = mission_root / "runtime" / "mission_outer_runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)

        mission_state_path = mission_root / "mission_state.json"
        decision_log_path = mission_root / "mission_decisions.jsonl"
        branch_log_path = mission_root / "mission_branches.jsonl"
        operator_request_log_path = mission_root / "mission_operator_requests.jsonl"
        current_operator_request_path = mission_root / "current_operator_request.json"
        runtime_report_path = mission_root / "runtime" / "self_healing_runtime" / "demo-queue" / "queue_summary.json"
        stage_summary_path = test_root / "stage-run" / "summary.json"
        stage_manifest_path = test_root / "stage-run" / "run_manifest.json"
        stage_runtime_report_path = test_root / "stage-run" / "runtime_report.json"
        stage_summary_path.parent.mkdir(parents=True, exist_ok=True)

        _write_json(
            stage_summary_path,
            {
                "stage_id": "baseline-evaluation",
                "status": "completed",
                "dataset_record_count": 64,
                "executed_examples": 16,
                "promotion_guidance": {
                    "recommended_state": "exploratory",
                    "max_allowed_state": "exploratory",
                    "reasons": ["Need more critique evidence before paper-candidate promotion."],
                },
            },
        )
        _write_json(
            stage_runtime_report_path,
            {
                "schema_version": 1,
                "stage_id": "baseline-evaluation",
                "telemetry": {
                    "elapsed_s": 24.0,
                    "executed_examples": 16,
                    "prompt_tokens_total": 4096,
                    "prompt_tokens_max": 192,
                    "generated_tokens_total": 512,
                    "peak_vram_mb": 6144,
                    "samples_per_s": 0.666667,
                    "toks_per_s": 21.333333,
                    "oom_retries": 0,
                },
                "budget": {
                    "prompt_token_budget": 512,
                    "prompt_token_utilization": 0.375,
                    "max_new_tokens": 64,
                    "selected_batch_size": 8,
                    "batch_probe_order": [32, 16, 8],
                    "gpu_memory_headroom_gb": 6,
                },
            },
        )
        _write_json(
            stage_manifest_path,
            {
                "schema_version": 1,
                "mission_id": "demo-mission",
                "runtime": {
                    "telemetry": {"executed_examples": 16},
                    "budget": {"prompt_token_budget": 512, "prompt_token_utilization": 0.375},
                    "runtime_report_path": str(stage_runtime_report_path),
                },
                "stage_context": {
                    "dataset_record_count": 64,
                    "runtime_telemetry": {"samples_per_s": 0.666667},
                    "runtime_budget": {"selected_batch_size": 8, "batch_probe_order": [32, 16, 8]},
                    "artifacts": {"runtime_report_path": str(stage_runtime_report_path)},
                },
            },
        )
        _write_json(
            runtime_report_path,
            {
                "queue_name": "demo-queue",
                "counts": {
                    "completed_jobs": 1,
                    "blocked_jobs": 0,
                    "warned_jobs": 0,
                    "failed_jobs": 0,
                    "recovered_jobs": 0,
                    "rerouted_jobs": 1,
                    "resumed_jobs": 0,
                },
                "entries": {
                    "baseline-job": {
                        "final_status": "rerouted",
                        "summary_json_path": str(runtime_report_path),
                        "history_path": str(runtime_report_path.with_name("baseline-job-history.jsonl")),
                        "next_route_to": "mechanistic-localization",
                    }
                },
            },
        )

        _write_jsonl(
            decision_log_path,
            [
                {
                    "decision_id": "demo-execution-local-eval",
                    "mission_id": "demo-mission",
                    "decision_type": "local-eval",
                    "summary": "Dispatch `run-baseline` through executor `stage-kernel`.",
                    "phase": "execution",
                    "scope": "internal",
                    "authority": {"mode": "autonomous", "requires_operator_approval": False, "approval_state": "not-required"},
                    "result": {"status": "selected", "recorded_at": "2026-04-12T19:08:09Z"},
                    "selected_action_ids": ["run-baseline"],
                    "selected_branch_ids": [],
                    "artifacts": [],
                    "notes": ["missing output: run logs", "missing output: metrics"],
                },
                {
                    "decision_id": "demo-critique-missing-outputs",
                    "mission_id": "demo-mission",
                    "decision_type": "critique",
                    "summary": "Continue `critique` because required outputs are still missing.",
                    "phase": "critique",
                    "scope": "internal",
                    "authority": {"mode": "autonomous", "requires_operator_approval": False, "approval_state": "not-required"},
                    "result": {"status": "selected", "recorded_at": "2026-04-12T19:10:09Z"},
                    "selected_action_ids": ["critique-missing-outputs"],
                    "selected_branch_ids": [],
                    "artifacts": [],
                    "notes": ["missing output: evidence assessment"],
                },
            ],
        )
        _write_jsonl(
            branch_log_path,
            [
                {
                    "schema_version": 1,
                    "branch_id": "analysis-critique",
                    "mission_id": "demo-mission",
                    "branch_type": "analysis",
                    "objective": "Feed baseline metrics into critique before promotion.",
                    "status": "critique-ready",
                    "recovery_status": "not-needed",
                    "runtime_owner": "deeploop",
                    "source_phase": "execution",
                    "target_phase": "critique",
                    "created_by_decision_id": "demo-execution-critique-branch",
                    "git_branch": None,
                    "artifacts": [],
                    "updated_at": "2026-04-12T19:09:09Z",
                    "notes": ["Feed baseline metrics into critique before promotion."],
                }
            ],
        )
        prior_operator_request = {
            "schema_version": 1,
            "request_id": "demo-temp-gap-request",
            "mission_id": "demo-mission",
            "created_at": "2026-04-12T19:08:59Z",
            "status": "resolved",
            "summary": "Autopilot paused for operator review: Queue `demo-queue` blocked on `blocked-followup`.",
            "explanation": "DeepLoop stopped honestly after a blocked bounded queue entry.",
            "blocker": {
                "kind": "operator-review",
                "gate": "operator-needed",
                "risk_class": "operator-review",
                "label": "operator review",
                "reason": "Queue `demo-queue` blocked on `blocked-followup`.",
                "default_response": None,
                "preferred_actions": ["retry", "reroute", "downscope"],
                "hard_gate_profile": None,
            },
            "context": {
                "mission_state_path": str(mission_state_path),
                "runtime_root": str(runtime_root),
                "mode": "sandboxed-yolo",
                "phase": "execution",
                "next_phase": "critique",
                "decision_id": "demo-execution-followup",
                "decision_type": "reroute",
                "action_id": "run-followups",
                "action_kind": "local-eval",
                "action_task": "Run the bounded follow-up queue.",
                "branch_id": "analysis-critique",
                "executor_id": "self-healing-queue",
            },
            "recommendation": {
                "summary": "Inspect the latest request and continue once the blocker is understood.",
                "pros": ["Simple default path."],
                "cons": ["May still need follow-up edits."],
            },
            "alternatives": [],
            "next_steps": [
                f"python scripts/mission/manage_mission.py inbox --mission-state {mission_state_path}",
                f"python scripts/mission/manage_mission.py resume --mission-state {mission_state_path}",
            ],
            "continue_command": f"python scripts/mission/manage_mission.py resume --mission-state {mission_state_path}",
        }
        operator_request = {
            "schema_version": 1,
            "request_id": "demo-operator-request",
            "mission_id": "demo-mission",
            "created_at": "2026-04-12T19:10:10Z",
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
                "runtime_root": str(runtime_root),
                "mode": "sandboxed-yolo",
                "phase": "critique",
                "next_phase": "experiment-design",
                "decision_id": "demo-critique-missing-outputs",
                "decision_type": "critique",
                "action_id": "critique-missing-outputs",
                "action_kind": "critique",
                "action_task": "Close the remaining critique outputs.",
                "branch_id": "analysis-critique",
                "executor_id": "stage-kernel",
            },
            "recommendation": {
                "summary": "Review the hard gate, keep the mission inside the sandbox, then resume autopilot.",
                "pros": ["Preserves sandboxed-yolo."],
                "cons": ["Requires operator review."],
            },
            "alternatives": [
                {
                    "option_id": "adjust-and-resume",
                    "summary": "Adjust the write target and continue.",
                    "pros": ["Keeps the current mode."],
                    "cons": ["May require a smaller task."],
                    "next_steps": [f"python scripts/mission/manage_mission.py resume --mission-state {mission_state_path}"],
                }
            ],
            "next_steps": [
                f"python scripts/mission/manage_mission.py inbox --mission-state {mission_state_path}",
                f"python scripts/mission/manage_mission.py resume --mission-state {mission_state_path}",
            ],
            "continue_command": f"python scripts/mission/manage_mission.py resume --mission-state {mission_state_path}",
        }
        _write_jsonl(operator_request_log_path, [prior_operator_request, operator_request])
        _write_json(current_operator_request_path, operator_request)

        history_entry = {
            "iteration": 3,
            "recorded_at": "2026-04-12T19:10:09Z",
            "phase": "critique",
            "directive": "continue-current-phase",
            "decision_id": "demo-critique-missing-outputs",
            "decision_type": "critique",
            "summary": "Continue `critique` because required outputs are still missing.",
            "action_id": "critique-missing-outputs",
            "branch_id": "analysis-critique",
            "outcome_status": "blocked",
            "mission_status": "blocked",
        }
        _write_json(
            runtime_root / "mission_runtime_state.json",
            {
                "schema_version": 1,
                "mission_id": "demo-mission",
                "mission_state_path": str(mission_state_path),
                "runtime_root": str(runtime_root),
                "status": "blocked",
                "iterations_completed": 3,
                "max_iterations": 5,
                "started_at": "2026-04-12T19:06:21Z",
                "updated_at": "2026-04-12T19:10:09Z",
                "last_decision_id": "demo-critique-missing-outputs",
                "last_action_id": "critique-missing-outputs",
                "last_branch_id": "analysis-critique",
                "last_executor_id": "stage-kernel",
                "terminal_reason": "Awaiting critique outputs.",
                "history_path": str(runtime_root / "mission_runtime_history.jsonl"),
                "summary_json_path": str(runtime_root / "mission_runtime_summary.json"),
                "summary_markdown_path": str(runtime_root / "mission_runtime_summary.md"),
            },
        )
        _write_jsonl(runtime_root / "mission_runtime_history.jsonl", [history_entry])
        _write_json(
            runtime_root / "mission_runtime_summary.json",
            {
                "schema_version": 1,
                "mission_id": "demo-mission",
                "runtime_root": str(runtime_root),
                "status": "blocked",
                "iterations_completed": 3,
                "max_iterations": 5,
                "last_decision_id": "demo-critique-missing-outputs",
                "last_action_id": "critique-missing-outputs",
                "last_branch_id": "analysis-critique",
                "last_executor_id": "stage-kernel",
                "terminal_reason": "Awaiting critique outputs.",
                "mission": {
                    "mission_id": "demo-mission",
                    "current_phase": "critique",
                    "next_phase": "experiment-design",
                    "status": "blocked",
                    "autonomy_status": {
                        "state": "mission-runtime-blocked",
                        "reason": "Awaiting critique outputs.",
                    },
                },
                "latest_history": [history_entry],
            },
        )
        (runtime_root / "mission_runtime_summary.md").write_text("# Mission outer runtime\n", encoding="utf-8")

        _write_json(
            mission_state_path,
            {
                "mission_id": "demo-mission",
                "title": "Demo mission",
                "current_phase": "critique",
                "next_phase": "experiment-design",
                "status": "blocked",
                "target_repo": str(REPO_ROOT),
                "completed_phases": ["execution"],
                "phase_history": ["execution", "critique"],
                "autonomy_status": {
                    "state": "mission-runtime-blocked",
                    "reason": "Awaiting critique outputs.",
                },
                "outer_loop": {
                    "policy_name": "deeploop-mission-outer-loop",
                    "execution_mode": "full-autonomous-internal",
                    "hard_gate_profile": "minimal",
                    "hard_gate_risk_classes": ["system-global-safety", "sandbox-boundary"],
                    "soft_gate_preferred_actions": ["retry", "reroute", "downscope"],
                    "decision_log_path": str(decision_log_path),
                    "branch_log_path": str(branch_log_path),
                    "operator_request_log_path": str(operator_request_log_path),
                    "current_operator_request_path": str(current_operator_request_path),
                },
                "mission_runtime": {"runtime_root": str(runtime_root)},
                "soft_gate_events": [
                    {
                        "gate": "soft",
                        "status": "deferred",
                        "risk_class": "quality-shortfall",
                        "reason": "Missing critique evidence bundle.",
                    }
                ],
                "next_actions": {
                    "summary": "Continue critique before promotion.",
                    "actions": [
                        {
                            "action_id": "run-baseline",
                            "role": "execution-operator",
                            "task": "Run the bounded baseline evaluation.",
                            "kind": "local-eval",
                            "status": "completed",
                            "phase": "execution",
                            "runtime_owner": "deeploop",
                            "requires_operator_approval": False,
                            "executor": {"id": "stage-kernel", "params": {"stage_id": "baseline-evaluation"}},
                            "notes": ["dispatching via stage-kernel"],
                        },
                        {
                            "action_id": "critique-missing-outputs",
                            "role": "critic-verifier",
                            "task": "Close the remaining critique outputs.",
                            "kind": "critique",
                            "status": "blocked",
                            "phase": "critique",
                            "branch_id": "analysis-critique",
                            "runtime_owner": "deeploop",
                            "requires_operator_approval": False,
                            "notes": ["missing output: evidence assessment", "Awaiting critique outputs."],
                        },
                    ],
                },
                "branch_records": [
                    {
                        "branch_id": "analysis-critique",
                        "branch_type": "analysis",
                        "objective": "Feed baseline metrics into critique before promotion.",
                        "status": "critique-ready",
                        "recovery_status": "not-needed",
                        "runtime_owner": "deeploop",
                        "source_phase": "execution",
                        "target_phase": "critique",
                        "updated_at": "2026-04-12T19:09:09Z",
                    }
                ],
                "runtime_recovery": {"report_json_path": str(runtime_report_path)},
                "phase_outputs_by_phase": {"execution": ["run logs", "metrics"]},
                "produced_outputs": [],
                "recent_failures": ["Executor `stage-kernel` previously timed out."],
                "failure_count": 1,
                "blocked_reasons": ["Awaiting critique outputs."],
                "stage_runs": {
                    "baseline-evaluation": {
                        "status": "completed",
                        "output_dir": str(stage_summary_path.parent),
                        "manifest_path": str(stage_summary_path.parent / "run_manifest.json"),
                        "summary_path": str(stage_summary_path),
                    }
                },
            },
        )

        snapshot = build_mission_snapshot(mission_state_path, ledger_tail=0)

        self.assertEqual(snapshot["outer_loop"]["runtime"]["status"], "blocked")
        self.assertEqual(snapshot["operator_console"]["operator_state"], "operator-action-required")
        self.assertEqual(snapshot["operator_console"]["attention_level"], "action-required")
        self.assertEqual(snapshot["operator_console"]["next_step_owner"], "operator")
        self.assertEqual(snapshot["operator_console"]["resume_policy"], "resume-after-fix")
        self.assertEqual(snapshot["operator_console"]["focus_action_id"], "critique-missing-outputs")
        self.assertEqual(snapshot["operator_console"]["focus_executor_id"], "stage-kernel")
        self.assertEqual(snapshot["outer_loop"]["runtime"]["remaining_iterations"], 2)
        self.assertEqual(snapshot["outer_loop"]["current_action"]["action_id"], "critique-missing-outputs")
        self.assertEqual(snapshot["outer_loop"]["current_branch"]["branch_id"], "analysis-critique")
        self.assertEqual(snapshot["outer_loop"]["branch_counts"]["critique-ready"], 1)
        self.assertEqual(snapshot["budgets"]["iterations_completed"], 3)
        self.assertEqual(snapshot["budgets"]["compute"]["status"], "tracked")
        self.assertEqual(snapshot["budgets"]["token"]["status"], "tracked")
        self.assertEqual(snapshot["budgets"]["cost"]["status"], "unavailable")
        self.assertEqual(snapshot["budgets"]["eta"]["quality"], "measured")
        self.assertEqual(snapshot["budgets"]["inner_loop"]["stage_id"], "baseline-evaluation")
        self.assertEqual(snapshot["budgets"]["inner_loop"]["remaining_examples"], 48)
        self.assertEqual(snapshot["evidence"]["promotion"]["state"], "exploratory")
        self.assertEqual(snapshot["failures"]["last_failure"], "Executor `stage-kernel` previously timed out.")
        self.assertEqual(snapshot["failures"]["last_reroute"]["route_to"], "mechanistic-localization")
        self.assertEqual(snapshot["autonomy_gap_telemetry"]["counts"]["operator_requests_total"], 2)
        self.assertEqual(snapshot["autonomy_gap_telemetry"]["counts"]["temporary_gap_requests"], 1)
        self.assertEqual(snapshot["autonomy_gap_telemetry"]["counts"]["permanent_boundary_requests"], 1)
        self.assertEqual(snapshot["autonomy_gap_telemetry"]["counts"]["soft_gates_total"], 1)
        self.assertEqual(snapshot["autonomy_gap_telemetry"]["counts"]["temporary_gap_auto_recovered"], 1)
        self.assertEqual(snapshot["autonomy_gap_telemetry"]["counts"]["temporary_gap_escalated"], 1)
        self.assertEqual(snapshot["autonomy_gap_telemetry"]["soft_gate_risk_classes"]["quality-shortfall"], 1)
        self.assertEqual(snapshot["autonomy_gap_telemetry"]["temporary_gap_categories"]["quality-shortfall"], 1)
        self.assertEqual(snapshot["autonomy_gap_telemetry"]["temporary_gap_categories"]["operator-review"], 1)
        self.assertEqual(snapshot["jobs"]["stage_runs"][0]["stage_id"], "baseline-evaluation")
        self.assertEqual(snapshot["jobs"]["stage_runs"][0]["telemetry"]["executed_examples"], 16)
        self.assertEqual(snapshot["operator_inbox"]["current_request"]["request_id"], "demo-operator-request")

        rendered = render_mission_snapshot(snapshot)
        self.assertIn("# DeepLoop operator console", rendered)
        self.assertIn("## Top summary", rendered)
        self.assertIn("operator_summary: BLOCKED — operator action is required before DeepLoop can continue.", rendered)
        self.assertIn("operator_state: `operator-action-required`", rendered)
        self.assertIn("attention_level: `action-required`", rendered)
        self.assertIn("next_step_owner: `operator`", rendered)
        self.assertIn("resume_policy: `resume-after-fix`", rendered)
        self.assertIn("gate_class: `hard-gate`", rendered)
        self.assertIn("focus_action: `critique-missing-outputs`", rendered)
        self.assertIn("focus_executor: `stage-kernel`", rendered)
        self.assertIn("## Exact next commands", rendered)
        self.assertIn("manage_mission.py retry", rendered)
        self.assertIn("manage_mission.py reroute", rendered)
        self.assertIn("## Mission outer loop", rendered)
        self.assertIn("current_action: `critique-missing-outputs`", rendered)
        self.assertIn("current_branch: `analysis-critique`", rendered)
        self.assertIn("hard_gate_profile: `minimal`", rendered)
        self.assertIn("soft_gate_strategy: `retry, reroute, downscope`", rendered)
        self.assertIn("latest_soft_gate: `quality-shortfall` Missing critique evidence bundle.", rendered)
        self.assertIn("## Operator inbox", rendered)
        self.assertIn("demo-operator-request", rendered)
        self.assertIn("promotion_state: `exploratory`", rendered)
        self.assertIn("last_reroute: `baseline-job` -> `mechanistic-localization`", rendered)
        self.assertIn("## Autonomy gap telemetry", rendered)
        self.assertIn("temporary_gap_requests: `1`", rendered)
        self.assertIn("permanent_boundary_requests: `1`", rendered)
        self.assertIn("soft_gates_total: `1`", rendered)
        self.assertIn("temporary_gap_auto_recovered: `1`", rendered)
        self.assertIn("temporary_gap_escalated: `1`", rendered)
        self.assertIn("temporary_gap_categories: operator-review=1, quality-shortfall=1", rendered)
        self.assertIn("latest_temporary_gap: `operator-review` Autopilot paused for operator review", rendered)
        self.assertIn("latest_temporary_gap_hint: `operator-review` -> `retry` [escalated]", rendered)
        self.assertIn("compute_budget_status: `tracked`", rendered)
        self.assertIn("token_budget_status: `tracked`", rendered)
        self.assertIn("cost_budget_status: `unavailable`", rendered)
        self.assertIn("eta_quality: `measured`", rendered)
        self.assertIn("## Inner-loop progress", rendered)
        self.assertIn("active_stage: `baseline-evaluation`", rendered)
        self.assertIn("processed `16` / `64` examples", rendered)
        self.assertIn("selected batch `8` stayed below the probe ceiling `32`", rendered)
        self.assertIn("Cost telemetry is not available yet", rendered)

    def test_snapshot_treats_deferred_soft_gate_as_current_autopilot_work(self) -> None:
        test_root = _fresh_test_root("deferred_soft_gate")
        mission_root = test_root / "mission"
        mission_state_path = mission_root / "mission_state.json"
        _write_json(
            mission_state_path,
            {
                "mission_id": "demo-soft-gate",
                "title": "Soft gate demo",
                "current_phase": "execution",
                "next_phase": "critique",
                "status": "running",
                "mode": "sandboxed-yolo",
                "autonomy_status": {"state": "mission-runtime-running", "reason": "Downscoping adaptation training."},
                "soft_gate_events": [
                    {
                        "gate": "soft",
                        "status": "deferred",
                        "risk_class": "budget-overrun",
                        "reason": "Need to downscope the bounded adaptation budget before retrying.",
                    }
                ],
                "next_actions": {
                    "summary": "Retry adaptation with a smaller budget.",
                    "actions": [
                        {
                            "action_id": "train-adapter",
                            "role": "execution-operator",
                            "task": "Retry adaptation with a smaller bounded budget.",
                            "kind": "local-training",
                            "status": "deferred",
                            "phase": "execution",
                            "runtime_owner": "deeploop",
                            "requires_operator_approval": False,
                            "executor": {"id": "adaptation-training", "params": {"training_config_path": "configs/runtime/train.yaml"}},
                            "notes": ["soft gate: budget-overrun"],
                        }
                    ],
                },
                "outer_loop": {
                    "mode": "sandboxed-yolo",
                    "hard_gate_profile": "minimal",
                    "soft_gate_preferred_actions": ["retry", "reroute", "downscope"],
                },
            },
        )

        snapshot = build_mission_snapshot(mission_state_path, ledger_tail=0)

        self.assertEqual(snapshot["outer_loop"]["current_action"]["action_id"], "train-adapter")
        self.assertEqual(snapshot["outer_loop"]["current_action"]["status"], "deferred")
        self.assertIsNone(snapshot["operator_inbox"]["current_request"])
        self.assertEqual(snapshot["operator_console"]["operator_state"], "autopilot-recovering")
        self.assertEqual(snapshot["operator_console"]["attention_level"], "passive")
        self.assertEqual(snapshot["operator_console"]["next_step_owner"], "autopilot")
        self.assertEqual(snapshot["operator_console"]["resume_policy"], "not-needed")

        rendered = render_mission_snapshot(snapshot)
        self.assertIn("## Top summary", rendered)
        self.assertIn("gate_class: `soft-gate`", rendered)
        self.assertIn("operator_state: `autopilot-recovering`", rendered)
        self.assertIn("next_step_owner: `autopilot`", rendered)
        self.assertIn("continue: No operator action is required right now.", rendered)
        self.assertIn("action_status: `deferred`", rendered)
        self.assertIn("soft_gate_status: autopilot kept control", rendered)
        self.assertIn("operator_inbox: clear", rendered)

    def test_snapshot_surfaces_adaptation_metric_ratchet_signal(self) -> None:
        test_root = _fresh_test_root("adaptation_metric_ratchet")
        mission_root = test_root / "mission"
        mission_state_path = mission_root / "mission_state.json"
        _write_json(
            mission_state_path,
            {
                "mission_id": "demo-ratchet",
                "title": "Adaptation ratchet mission",
                "current_phase": "execution",
                "next_phase": "critique",
                "status": "paused",
                "autonomy_status": {"state": "mission-runtime-paused", "reason": "Adaptation finished and ratchet routed to replication."},
                "adaptation_training": {
                    "status": "completed",
                    "summary": "Adapted artifact `keep` against the best prior anchor `intervention` on `accuracy` with route `replication`.",
                    "report_json_path": str(mission_root / "adaptation_training" / "adapt-branch" / "adaptation_training_report.json"),
                    "comparison_path": str(mission_root / "adaptation_training" / "adapt-branch" / "adaptation_training_comparison.json"),
                    "metric_ratchet": {
                        "decision": "keep",
                        "route_to": "replication",
                        "primary_metric": "accuracy",
                        "anchor_label": "intervention",
                        "summary": "Adapted artifact `keep` against the best prior anchor `intervention` on `accuracy` with route `replication`.",
                    },
                },
            },
        )

        snapshot = build_mission_snapshot(mission_state_path, ledger_tail=0)

        self.assertEqual(snapshot["evidence"]["adaptation_metric_ratchet"]["decision"], "keep")
        self.assertEqual(snapshot["evidence"]["adaptation_metric_ratchet"]["route_to"], "replication")
        self.assertEqual(snapshot["failures"]["last_reroute"]["entry_id"], "adaptation_training")
        self.assertEqual(snapshot["failures"]["last_reroute"]["route_to"], "replication")

        rendered = render_mission_snapshot(snapshot)
        self.assertIn("adaptation_metric_ratchet: `keep` -> `replication` on `accuracy`", rendered)
        self.assertIn("last_reroute: `adaptation_training` -> `replication`", rendered)

    def test_snapshot_surfaces_multi_mission_scheduler_state(self) -> None:
        test_root = _fresh_test_root("surfaces_multi_mission_scheduler_state")
        mission_root = test_root / "mission"
        mission_state_path = mission_root / "mission_state.json"
        scheduler_root = test_root / "scheduler"
        _write_json(
            mission_state_path,
            {
                "mission_id": "demo-scheduled-mission",
                "title": "Scheduled mission",
                "current_phase": "execution",
                "next_phase": "critique",
                "status": "running",
                "autonomy_status": {"state": "mission-runtime-max-iterations", "reason": "Slice yielded."},
                "mission_scheduler": {
                    "scheduler_id": "demo-multi-mission",
                    "scheduler_state_path": str(scheduler_root / "scheduler_state.json"),
                    "scheduler_summary_json_path": str(scheduler_root / "summary.json"),
                    "scheduler_summary_markdown_path": str(scheduler_root / "summary.md"),
                    "scheduler_status": "running",
                    "priority": 120,
                    "fair_share_weight": 1.5,
                    "mission_budget_iterations": 4,
                    "iterations_consumed": 2,
                    "remaining_budget": 2,
                    "last_scheduled_at": "2026-04-12T20:20:00Z",
                    "last_scheduled_cycle": 1,
                    "last_effective_priority": 12050.0,
                    "suppression_reason": None,
                    "active_operator_request_id": None,
                    "composition": {
                        "open_request_policy": "pause-lower-priority",
                        "safety_block_policy": "pause-lower-priority",
                    },
                },
            },
        )

        snapshot = build_mission_snapshot(mission_state_path, log_tail_lines=0, ledger_tail=0)

        self.assertEqual(snapshot["mission_scheduler"]["scheduler_id"], "demo-multi-mission")
        self.assertEqual(snapshot["mission_scheduler"]["remaining_budget"], 2)
        self.assertEqual(snapshot["artifacts"]["scheduler_state_path"], str(scheduler_root / "scheduler_state.json"))

        rendered = render_mission_snapshot(snapshot)
        self.assertIn("## Mission scheduler", rendered)
        self.assertIn("demo-multi-mission", rendered)
        self.assertIn("scheduler_remaining_budget", rendered)

    def test_completed_snapshot_hides_stale_current_work(self) -> None:
        test_root = _fresh_test_root("completed_hides_stale_current_work")
        mission_root = test_root / "mission"
        runtime_root = mission_root / "runtime" / "mission_outer_runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        _write_json(
            mission_state_path,
            {
                "mission_id": "demo-completed",
                "title": "Completed mission",
                "current_phase": "final-report",
                "next_phase": "replication",
                "status": "completed",
                "mode": "sandboxed-yolo",
                "autonomy_status": {
                    "state": "mission-runtime-completed",
                    "reason": "All required final-report outputs are present; the mission can complete honestly.",
                },
                "next_actions": {
                    "summary": "Dispatch stale action that should not appear after completion.",
                    "actions": [
                        {
                            "action_id": "stale-deferred-action",
                            "role": "experiment-designer",
                            "task": "Old deferred work that should not show up after completion.",
                            "kind": "artifact-edit",
                            "status": "deferred",
                            "phase": "experiment-design",
                            "runtime_owner": "deeploop",
                            "requires_operator_approval": False,
                        }
                    ],
                },
                "outer_loop": {
                    "mode": "sandboxed-yolo",
                    "hard_gate_profile": "minimal",
                    "decision_log_path": str(mission_root / "mission_decisions.jsonl"),
                    "branch_log_path": str(mission_root / "mission_branches.jsonl"),
                },
            },
        )
        _write_json(
            runtime_root / "mission_runtime_summary.json",
            {
                "status": "completed",
                "iterations_completed": 36,
                "max_iterations": 90,
                "terminal_reason": "All required final-report outputs are present; the mission can complete honestly.",
            },
        )

        snapshot = build_mission_snapshot(mission_state_path, ledger_tail=0)

        self.assertIsNone(snapshot["outer_loop"]["current_action"])
        self.assertIsNone(snapshot["outer_loop"]["current_branch"])
        self.assertIsNone(snapshot["mission"]["next_actions_summary"])
        self.assertEqual(snapshot["operator_console"]["operator_state"], "mission-complete")
        self.assertEqual(snapshot["operator_console"]["next_step_owner"], "none")
        self.assertEqual(snapshot["operator_console"]["resume_policy"], "not-needed")

        rendered = render_mission_snapshot(snapshot)
        self.assertIn("operator_summary: COMPLETED — DeepLoop finished this mission.", rendered)
        self.assertIn("operator_state: `mission-complete`", rendered)
        self.assertIn("next_step_owner: `none`", rendered)
        self.assertIn("current_action: none surfaced", rendered)
        self.assertIn("current_branch: none surfaced", rendered)
        self.assertNotIn("stale-deferred-action", rendered)
        self.assertNotIn("Dispatch stale action", rendered)

    def test_exited_process_does_not_render_running_headline_from_stale_runtime(self) -> None:
        test_root = _fresh_test_root("exited_process_not_running")
        mission_root = test_root / "mission"
        runtime_root = mission_root / "runtime" / "mission_outer_runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        launch_path = test_root / "launch.json"
        log_path = test_root / "launch.log"
        log_path.write_text("[demo] process exited\n", encoding="utf-8")

        _write_json(
            mission_state_path,
            {
                "mission_id": "demo-exited",
                "title": "Exited mission",
                "current_phase": "idea-intake",
                "next_phase": "literature-review",
                "status": "initialized",
                "mode": "sandboxed-yolo",
                "autonomy_status": {
                    "state": "initialized",
                    "reason": "Mission created but not yet advanced.",
                },
                "next_actions": {
                    "summary": "Dispatch `demo-idea-intake` through executor `recursive-agent` to close missing `idea-intake` outputs.",
                    "actions": [
                        {
                            "action_id": "demo-idea-intake",
                            "role": "planner",
                            "task": "Close the remaining idea-intake outputs.",
                            "kind": "artifact-edit",
                            "status": "in_progress",
                            "phase": "idea-intake",
                            "runtime_owner": "deeploop",
                            "requires_operator_approval": False,
                        }
                    ],
                },
                "outer_loop": {
                    "mode": "sandboxed-yolo",
                    "hard_gate_profile": "minimal",
                },
            },
        )
        _write_json(
            runtime_root / "mission_runtime_summary.json",
            {
                "status": "running",
                "iterations_completed": 1,
                "max_iterations": 4,
                "terminal_reason": None,
            },
        )
        _write_json(
            launch_path,
            {
                "pid": 999999999,
                "started_at": "2026-04-15T14:35:55Z",
                "log_path": str(log_path),
            },
        )

        snapshot = build_mission_snapshot(mission_state_path, launch_metadata_path=launch_path, ledger_tail=0)

        self.assertEqual(snapshot["launch"]["process_status"], "exited")
        self.assertEqual(snapshot["outer_loop"]["runtime"]["status"], "running")
        self.assertFalse(snapshot["operator_console"]["is_running"])
        self.assertEqual(snapshot["operator_console"]["headline"], "STOPPED — DeepLoop is not currently running.")
        self.assertEqual(snapshot["operator_console"]["process_status"], "exited")

    def test_recursive_agent_progress_replaces_completed_outer_action_as_active_work(self) -> None:
        test_root = _fresh_test_root("recursive_agent_progress_replaces_completed_outer_action")
        mission_root = test_root / "mission"
        runtime_root = mission_root / "runtime" / "mission_outer_runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"

        _write_json(
            runtime_root / "mission_runtime_state.json",
            {
                "schema_version": 1,
                "mission_id": "demo-recursive-progress",
                "runtime_root": str(runtime_root),
                "status": "running",
                "iterations_completed": 0,
                "max_iterations": 16,
                "last_action_id": "demo-idea-intake",
                "last_executor_id": "recursive-agent",
                "terminal_reason": None,
                "history_path": str(runtime_root / "mission_runtime_history.jsonl"),
                "summary_json_path": str(runtime_root / "mission_runtime_summary.json"),
                "summary_markdown_path": str(runtime_root / "mission_runtime_summary.md"),
            },
        )
        _write_json(
            mission_state_path,
            {
                "mission_id": "demo-recursive-progress",
                "title": "Recursive progress mission",
                "current_phase": "experiment-design",
                "next_phase": "execution",
                "status": "running",
                "mode": "sandboxed-yolo",
                "autonomy_status": {
                    "state": "recursive-agent-running",
                    "reason": "The recursive agent loop is advancing the mission.",
                },
                "next_actions": {
                    "summary": "Dispatch demo-idea-intake through executor recursive-agent to close missing idea-intake outputs.",
                    "actions": [
                        {
                            "action_id": "demo-idea-intake",
                            "role": "planner",
                            "task": "Close the remaining idea-intake outputs.",
                            "kind": "artifact-edit",
                            "status": "completed",
                            "phase": "idea-intake",
                            "executor": {"id": "recursive-agent", "params": {"config_path": "recursive-loop.yaml"}},
                        }
                    ],
                },
                "agent_driver": {
                    "status": "running",
                    "iterations_completed": 4,
                    "max_iterations": 5,
                    "pending_action": {
                        "role": "experiment-designer",
                        "task": "Design the next experiment.",
                        "phase": "experiment-design",
                        "loop_action_id": "recursive-agent-loop-iter-04-experiment-designer",
                    },
                    "current_action": {
                        "role": "question-designer",
                        "task": "Finalize question design.",
                        "phase": "question-design",
                        "loop_action_id": "recursive-agent-loop-iter-03-question-designer",
                    },
                },
            },
        )

        snapshot = build_mission_snapshot(mission_state_path, ledger_tail=0)
        rendered = render_mission_snapshot(snapshot)

        self.assertIsNone(snapshot["outer_loop"]["current_action"])
        self.assertEqual(snapshot["outer_loop"]["historical_action"]["action_id"], "demo-idea-intake")
        self.assertIn("Recursive-agent iteration: 4 / 5, role=experiment-designer, phase=experiment-design.", snapshot["operator_console"]["summary"])
        self.assertIn("Outer-loop iterations: `0` / `16` used. Recursive-agent iterations: `4` / `5` used.", snapshot["budgets"]["summary"])
        self.assertIn("outer_action_status: `completed` (historical)", rendered)
        self.assertIn("current_recursive_action: `recursive-agent-loop-iter-04-experiment-designer`", rendered)
        self.assertIn("current_recursive_iteration: Recursive-agent iteration: 4 / 5, role=experiment-designer, phase=experiment-design.", rendered)


if __name__ == "__main__":
    unittest.main()
