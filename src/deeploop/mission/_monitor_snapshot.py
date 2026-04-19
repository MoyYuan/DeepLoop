from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from deeploop.autonomy.operating_modes import DEFAULT_OPERATING_MODE
from deeploop.autonomy.operator_inbox import latest_operator_request, load_current_operator_request
from deeploop.mission._autonomy_gap_telemetry import build_autonomy_gap_telemetry
from deeploop.mission._operator_surface import mode_summary as _mode_summary, operator_console_snapshot as _operator_console_snapshot
from deeploop.mission._monitor_classification import (
    _branch_records,
    _budgets_snapshot,
    _current_action_record,
    _default_launch_metadata_path,
    _default_operator_inbox_paths,
    _default_outer_loop_paths,
    _failure_snapshot,
    _jobs_snapshot,
    _latest_soft_gate_event,
    _maybe_load_json,
    _maybe_load_jsonl,
    _maybe_path,
    _normalize_strings,
    _progress_root,
    _promotion_snapshot,
    _runtime_snapshot,
    _scheduler_snapshot,
    _select_current_action,
    _select_current_branch,
    _stage_runs_snapshot,
    _summarize_branch,
    _tail_lines,
    _pid_status,
)
from deeploop.mission.mission_state import load_mission_state


def build_mission_snapshot(
    mission_state_path: Path,
    *,
    launch_metadata_path: Path | None = None,
    log_tail_lines: int = 20,
    ledger_tail: int = 8,
) -> dict[str, Any]:
    mission_state_path = mission_state_path.expanduser().resolve()
    mission_state = load_mission_state(mission_state_path)
    mission_root = mission_state_path.parent
    progress_root = _progress_root(mission_state_path)
    progress = _maybe_load_json(progress_root / "progress.json")

    runtime_recovery_state = mission_state.get("runtime_recovery", {})
    runtime_report_path = (
        _maybe_path(runtime_recovery_state.get("report_json_path"))
        if isinstance(runtime_recovery_state, Mapping)
        else None
    )
    runtime_report = _maybe_load_json(runtime_report_path) or (
        dict(runtime_recovery_state) if isinstance(runtime_recovery_state, Mapping) else None
    )

    end_to_end = mission_state.get("end_to_end_smoke", {})
    end_to_end_summary_path = (
        _maybe_path(end_to_end.get("summary_json_path"))
        if isinstance(end_to_end, Mapping)
        else None
    ) or (progress_root / "summary.json")
    end_to_end_summary = _maybe_load_json(end_to_end_summary_path)

    resolved_launch_path = (
        launch_metadata_path.expanduser().resolve()
        if launch_metadata_path is not None
        else _default_launch_metadata_path(mission_state_path, mission_state)
    )
    launch_metadata = _maybe_load_json(resolved_launch_path)
    if launch_metadata is None and launch_metadata_path is None:
        launch_metadata = _maybe_load_json(progress_root / "launch.json")
        if launch_metadata is not None:
            resolved_launch_path = progress_root / "launch.json"

    launch_snapshot: dict[str, Any] | None = None
    log_tail: list[str] = []
    if launch_metadata is not None:
        pid = launch_metadata.get("pid")
        log_path = _maybe_path(launch_metadata.get("log_path"))
        if log_path is not None:
            log_tail = _tail_lines(log_path, log_tail_lines)
        launch_snapshot = {
            **launch_metadata,
            "process_status": _pid_status(int(pid)) if isinstance(pid, int) else "unknown",
        }

    ledger_path = mission_root / "ledger.jsonl"
    recent_ledger = _maybe_load_jsonl(ledger_path)[-max(ledger_tail, 0) :] if ledger_path.exists() else []

    outer_loop = mission_state.get("outer_loop") if isinstance(mission_state.get("outer_loop"), Mapping) else {}
    default_decision_log_path, default_branch_log_path = _default_outer_loop_paths(mission_state_path)
    default_operator_request_log_path, default_current_operator_request_path = _default_operator_inbox_paths(
        mission_state_path
    )
    decision_log_path = _maybe_path(outer_loop.get("decision_log_path")) or default_decision_log_path
    branch_log_path = _maybe_path(outer_loop.get("branch_log_path")) or default_branch_log_path
    operator_request_log_path = (
        _maybe_path(outer_loop.get("operator_request_log_path")) or default_operator_request_log_path
    )
    current_operator_request_path = (
        _maybe_path(outer_loop.get("current_operator_request_path")) or default_current_operator_request_path
    )
    decision_log = _maybe_load_jsonl(decision_log_path)
    branch_log = _maybe_load_jsonl(branch_log_path)
    current_operator_request = (
        load_current_operator_request(current_operator_request_path)
        if current_operator_request_path.exists()
        else None
    )
    latest_operator = latest_operator_request(operator_request_log_path, current_operator_request_path)

    runtime = _runtime_snapshot(mission_state_path, mission_state)
    mission_status = str(mission_state.get("status") or "")
    next_actions = mission_state.get("next_actions") if isinstance(mission_state.get("next_actions"), Mapping) else {}
    actions = [dict(action) for action in next_actions.get("actions", []) if isinstance(action, Mapping)]
    current_action = _select_current_action(
        actions,
        current_phase=str(mission_state.get("current_phase") or ""),
        runtime=runtime,
    )
    current_action_record = _current_action_record(actions, current_action)
    branches = _branch_records(mission_state, branch_log)
    current_branch = _select_current_branch(branches, runtime=runtime, current_action=current_action)
    if mission_status == "completed":
        current_action = None
        current_action_record = None
        current_branch = None
    branch_counts = Counter(str(branch.get("status") or "unknown") for branch in branches)
    job_actions = [] if mission_status == "completed" else actions
    stage_runs = _stage_runs_snapshot(mission_state)
    jobs = _jobs_snapshot(job_actions, runtime_report, stage_runs=stage_runs)
    evidence = {
        "current_phase_outputs": _normalize_strings(mission_state.get("produced_outputs") or mission_state.get("phase_outputs")),
        "phase_outputs_by_phase": {
            str(phase): _normalize_strings(outputs)
            for phase, outputs in (mission_state.get("phase_outputs_by_phase") or {}).items()
        }
        if isinstance(mission_state.get("phase_outputs_by_phase"), Mapping)
        else {},
        "promotion": _promotion_snapshot(mission_state, end_to_end_summary),
    }
    failures = _failure_snapshot(mission_state, runtime, runtime_report)
    autonomy_gap_telemetry = build_autonomy_gap_telemetry(
        mission_state,
        operator_request_log_path=operator_request_log_path,
        current_operator_request=current_operator_request,
        runtime_recovery=runtime_report,
    )
    budgets = _budgets_snapshot(runtime, stage_runs=stage_runs, action_record=current_action_record)
    scheduler = _scheduler_snapshot(mission_state)

    artifacts = {
        "mission_state_path": str(mission_state_path),
        "launch_metadata_path": str(resolved_launch_path),
        "progress_json_path": str(progress_root / "progress.json"),
        "progress_markdown_path": str(progress_root / "progress.md"),
        "summary_json_path": str(end_to_end_summary_path),
        "summary_markdown_path": str(progress_root / "summary.md"),
        "ledger_path": str(ledger_path),
        "decision_log_path": str(decision_log_path),
        "branch_log_path": str(branch_log_path),
        "operator_request_log_path": str(operator_request_log_path),
        "current_operator_request_path": str(current_operator_request_path),
    }
    if isinstance(runtime, Mapping):
        for key in ("state_path", "history_path", "summary_json_path", "summary_markdown_path"):
            value = runtime.get(key)
            if isinstance(value, str):
                artifacts[f"mission_runtime_{key}"] = value
    if isinstance(scheduler, Mapping):
        for key in ("scheduler_state_path", "scheduler_summary_json_path", "scheduler_summary_markdown_path"):
            value = scheduler.get(key)
            if isinstance(value, str):
                artifacts[key] = value
    if isinstance(end_to_end, Mapping):
        for key in (
            "baseline_runtime_report",
            "followup_runtime_report",
            "mechanistic_manifest",
            "intervention_manifest",
            "package_manifest",
        ):
            value = end_to_end.get(key)
            if isinstance(value, str):
                artifacts[key] = value

    mission_snapshot = {
        "mission_id": mission_state.get("mission_id"),
        "title": mission_state.get("title"),
        "current_phase": mission_state.get("current_phase"),
        "next_phase": mission_state.get("next_phase"),
        "status": mission_state.get("status"),
        "autonomy_status": mission_state.get("autonomy_status", {}),
        "target_repo": mission_state.get("target_repo"),
        "completed_phases": _normalize_strings(mission_state.get("completed_phases")),
        "phase_history": _normalize_strings(mission_state.get("phase_history")),
        "next_actions_summary": None if mission_status == "completed" else next_actions.get("summary"),
    }

    outer_loop_snapshot = {
        "mode": outer_loop.get("mode") or mission_state.get("mode") or DEFAULT_OPERATING_MODE,
        "mode_summary": _mode_summary(
            str(outer_loop.get("mode") or mission_state.get("mode") or DEFAULT_OPERATING_MODE)
        ),
        "policy_name": outer_loop.get("policy_name"),
        "execution_mode": outer_loop.get("execution_mode"),
        "permissions_profile": outer_loop.get("permissions_profile", outer_loop.get("internal_execution")),
        "intervention_profile": outer_loop.get("intervention_profile"),
        "hard_gate_profile": outer_loop.get("hard_gate_profile"),
        "hard_gate_risk_classes": _normalize_strings(outer_loop.get("hard_gate_risk_classes")),
        "soft_gate_risk_classes": _normalize_strings(outer_loop.get("soft_gate_risk_classes")),
        "soft_gate_preferred_actions": _normalize_strings(outer_loop.get("soft_gate_preferred_actions")),
        "latest_soft_gate": _latest_soft_gate_event(mission_state),
        "decision_log_path": str(decision_log_path),
        "branch_log_path": str(branch_log_path),
        "latest_decision": decision_log[-1] if decision_log else None,
        "decision_tail": decision_log[-3:],
        "runtime": runtime,
        "current_action": current_action,
        "current_branch": current_branch,
        "branch_counts": dict(sorted(branch_counts.items())),
        "branches": [_summarize_branch(branch) for branch in branches[-5:]],
    }
    operator_inbox_snapshot = {
        "operator_request_log_path": str(operator_request_log_path),
        "current_operator_request_path": str(current_operator_request_path),
        "current_request": current_operator_request,
        "latest_request": latest_operator,
    }
    operator_console = _operator_console_snapshot(
        mission_state_path,
        mission=mission_snapshot,
        outer_loop=outer_loop_snapshot,
        operator_inbox=operator_inbox_snapshot,
        failures=failures,
        launch=launch_snapshot,
        observability=budgets,
    )

    return {
        "mission": mission_snapshot,
        "outer_loop": outer_loop_snapshot,
        "operator_inbox": operator_inbox_snapshot,
        "operator_console": operator_console,
        "jobs": jobs,
        "budgets": budgets,
        "mission_scheduler": scheduler,
        "evidence": evidence,
        "failures": failures,
        "autonomy_gap_telemetry": autonomy_gap_telemetry,
        "progress": progress,
        "launch": launch_snapshot,
        "runtime_recovery": runtime_report,
        "end_to_end_summary": end_to_end_summary,
        "artifacts": artifacts,
        "recent_ledger": recent_ledger,
        "log_tail": log_tail,
    }
