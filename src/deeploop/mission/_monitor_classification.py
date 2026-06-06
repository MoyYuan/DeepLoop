from __future__ import annotations

import os
from datetime import datetime, timezone
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from deeploop.mission._constants import (
    ACTIVE_BRANCH_STATUSES as _ACTIVE_BRANCH_STATUSES,
    RUNTIME_HISTORY_FILE as _RUNTIME_HISTORY_FILE,
    RUNTIME_STATE_FILE as _RUNTIME_STATE_FILE,
    RUNTIME_SUMMARY_JSON_FILE as _RUNTIME_SUMMARY_JSON_FILE,
    RUNTIME_SUMMARY_MD_FILE as _RUNTIME_SUMMARY_MD_FILE,
)
from deeploop.autonomy.operator_inbox import build_operator_inbox_contract
from deeploop.core.paths import LAUNCHES_DIR
from deeploop.core.shared import normalize_strings as _normalize_strings
from deeploop.core.structured_io import load_json_object, load_jsonl_objects

_DEFAULT_RUNTIME_DIR_NAME = "mission_outer_runtime"
_PROMOTION_STATE_ORDER = {"not-ready": 0, "exploratory": 1, "paper-candidate": 2}

def _maybe_load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return load_json_object(path)

def _maybe_load_jsonl(path: Path | None, missing_ok=True) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    return load_jsonl_objects(path, missing_ok=True)

def _tail_lines(path: Path, line_count: int) -> list[str]:
    if line_count <= 0 or not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-line_count:]

def _pid_status(pid: int | None) -> str:
    if pid is None or pid <= 0:
        return "unknown"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "exited"
    except PermissionError:
        return "running"
    return "running"

def _progress_root(mission_state_path: Path) -> Path:
    return mission_state_path.parent / "runtime" / "end_to_end_smoke"

def _default_launch_metadata_path(mission_state_path: Path, mission_state: dict[str, Any]) -> Path:
    mission_id = mission_state.get("mission_id")
    if isinstance(mission_id, str) and mission_id:
        return LAUNCHES_DIR / mission_id / "launch.json"
    return _progress_root(mission_state_path) / "launch.json"

def _maybe_path(raw: Any) -> Path | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()

def _default_outer_loop_paths(mission_state_path: Path) -> tuple[Path, Path]:
    mission_root = mission_state_path.parent
    return mission_root / "mission_decisions.jsonl", mission_root / "mission_branches.jsonl"

def _default_operator_inbox_paths(mission_state_path: Path) -> tuple[Path, Path]:
    contract = build_operator_inbox_contract(mission_state_path.parent)
    return (
        Path(contract["operator_request_log_path"]),
        Path(contract["current_operator_request_path"]),
    )

def _runtime_root(mission_state_path: Path, mission_state: Mapping[str, Any]) -> Path:
    runtime = mission_state.get("mission_runtime")
    if isinstance(runtime, Mapping):
        resolved = _maybe_path(runtime.get("runtime_root"))
        if resolved is not None:
            return resolved
    return mission_state_path.parent / "runtime" / _DEFAULT_RUNTIME_DIR_NAME

def _dedupe_records(records: list[dict[str, Any]], *, identity_field: str) -> list[dict[str, Any]]:
    latest_by_identity: dict[str, dict[str, Any]] = {}
    for record in records:
        identity = str(record.get(identity_field) or "")
        if identity:
            latest_by_identity[identity] = record
    return list(latest_by_identity.values())

def _summarize_action(action: Mapping[str, Any]) -> dict[str, Any]:
    executor = action.get("executor") if isinstance(action.get("executor"), Mapping) else {}
    return {
        "action_id": action.get("action_id"),
        "status": action.get("status"),
        "kind": action.get("kind"),
        "phase": action.get("phase"),
        "role": action.get("role"),
        "branch_id": action.get("branch_id"),
        "executor_id": executor.get("id") if isinstance(executor, Mapping) else None,
        "task": action.get("task"),
        "notes": _normalize_strings(action.get("notes"))[-3:],
        "output_paths": _normalize_strings(action.get("output_paths")),
        "created_at": action.get("created_at"),
    }

def _recursive_agent_snapshot(mission_state: Mapping[str, Any]) -> dict[str, Any] | None:
    agent_driver = mission_state.get("agent_driver")
    if not isinstance(agent_driver, Mapping):
        return None
    current_action = agent_driver.get("current_action")
    pending_action = agent_driver.get("pending_action")
    active_action = pending_action if isinstance(pending_action, Mapping) else current_action
    iterations_completed = agent_driver.get("iterations_completed")
    max_iterations = agent_driver.get("max_iterations")
    remaining_iterations = (
        max(int(max_iterations) - int(iterations_completed), 0)
        if isinstance(iterations_completed, int) and isinstance(max_iterations, int)
        else None
    )
    role = active_action.get("role") if isinstance(active_action, Mapping) else None
    phase = (
        active_action.get("phase")
        if isinstance(active_action, Mapping) and active_action.get("phase") is not None
        else mission_state.get("current_phase")
    )
    iteration_text = (
        f"{iterations_completed} / {max_iterations}"
        if isinstance(iterations_completed, int) and isinstance(max_iterations, int)
        else str(iterations_completed or "unknown")
    )
    summary = f"Recursive-agent iteration: {iteration_text}, role={role or 'unknown'}, phase={phase or 'unknown'}."
    return {
        "status": agent_driver.get("status"),
        "iterations_completed": iterations_completed,
        "max_iterations": max_iterations,
        "remaining_iterations": remaining_iterations,
        "role": role,
        "phase": phase,
        "current_action": dict(current_action) if isinstance(current_action, Mapping) else None,
        "pending_action": dict(pending_action) if isinstance(pending_action, Mapping) else None,
        "active_action": dict(active_action) if isinstance(active_action, Mapping) else None,
        "summary": summary,
        "runtime_root": agent_driver.get("runtime_root"),
        "state_path": agent_driver.get("state_path"),
        "latest_iteration_path": agent_driver.get("latest_iteration_path"),
        "latest_result_path": agent_driver.get("latest_result_path"),
    }

def _summarize_branch(branch: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "branch_id": branch.get("branch_id"),
        "status": branch.get("status"),
        "branch_type": branch.get("branch_type"),
        "objective": branch.get("objective"),
        "source_phase": branch.get("source_phase"),
        "target_phase": branch.get("target_phase"),
        "recovery_status": branch.get("recovery_status"),
        "runtime_owner": branch.get("runtime_owner"),
        "updated_at": branch.get("updated_at"),
        "notes": _normalize_strings(branch.get("notes"))[-3:],
    }

def _latest_soft_gate_event(mission_state: Mapping[str, Any]) -> dict[str, Any] | None:
    events = mission_state.get("soft_gate_events")
    if isinstance(events, list):
        for event in reversed(events):
            if isinstance(event, Mapping):
                return dict(event)
    adaptation = mission_state.get("adaptation_training")
    if isinstance(adaptation, Mapping):
        event = adaptation.get("gate_event")
        if isinstance(event, Mapping) and str(event.get("gate") or "") == "soft":
            return dict(event)
    return None

def _runtime_snapshot(mission_state_path: Path, mission_state: dict[str, Any]) -> dict[str, Any] | None:
    runtime_root = _runtime_root(mission_state_path, mission_state)
    runtime_state_path = runtime_root / _RUNTIME_STATE_FILE
    runtime_history_path = runtime_root / _RUNTIME_HISTORY_FILE
    runtime_summary_json_path = runtime_root / _RUNTIME_SUMMARY_JSON_FILE
    runtime_summary_md_path = runtime_root / _RUNTIME_SUMMARY_MD_FILE
    runtime_state = _maybe_load_json(runtime_state_path)
    runtime_summary = _maybe_load_json(runtime_summary_json_path)
    runtime_history = _maybe_load_jsonl(runtime_history_path, missing_ok=True)
    mission_runtime = mission_state.get("mission_runtime") if isinstance(mission_state.get("mission_runtime"), Mapping) else {}

    if not any(
        (
            bool(mission_runtime),
            runtime_state is not None,
            runtime_summary is not None,
            bool(runtime_history),
            runtime_summary_md_path.exists(),
        )
    ):
        return None

    merged: dict[str, Any] = {}
    merged.update(dict(mission_runtime))
    if isinstance(runtime_state, dict):
        merged.update(runtime_state)
    if isinstance(runtime_summary, dict):
        merged.update({key: value for key, value in runtime_summary.items() if key != "mission"})
        mission_summary = runtime_summary.get("mission")
        if isinstance(mission_summary, Mapping):
            merged["mission"] = dict(mission_summary)
    if "latest_history" not in merged:
        merged["latest_history"] = runtime_history[-1:] if runtime_history else []
    merged["history_tail"] = runtime_history[-5:]
    last_executor_id = merged.get("last_executor_id")
    # Tier 1: Structured history records with executor_id (v0.2.1+).
    # Iterates all history entries and accumulates a full executor usage count.
    executor_usage_counts: Counter[str] = Counter()
    found_structured = False
    for record in runtime_history:
        if not isinstance(record, Mapping):
            continue
        eid = str(record.get("executor_id") or "")
        if eid:
            executor_usage_counts[eid] += 1
            found_structured = True
    if found_structured:
        merged["executor_usage_counts"] = dict(executor_usage_counts)
        merged["recursive_agent_invocations"] = int(executor_usage_counts.get("recursive-agent", 0))
    elif last_executor_id:
        # Tier 2: Fall back to runtime_state last_executor_id (single count for
        # the most recent executor; set from mission_runtime.py dispatch path).
        executor_usage_counts = Counter({last_executor_id: 1})
        merged["executor_usage_counts"] = dict(executor_usage_counts)
        merged["recursive_agent_invocations"] = int(last_executor_id == "recursive-agent")
    else:
        # Tier 3: Legacy fallback — parse executor usage from rendered summary
        # text (backward compatibility with history records from before v0.2.1).
        for record in runtime_history:
            if not isinstance(record, Mapping):
                continue
            summary = str(record.get("summary") or "")
            marker = "through executor `"
            if marker not in summary:
                continue
            executor_id = summary.split(marker, 1)[1].split("`", 1)[0].strip()
            if executor_id:
                executor_usage_counts[executor_id] += 1
        merged["executor_usage_counts"] = dict(executor_usage_counts)
        merged["recursive_agent_invocations"] = int(executor_usage_counts.get("recursive-agent", 0))
    recursive_agent = _recursive_agent_snapshot(mission_state)
    if recursive_agent is not None:
        merged["recursive_agent"] = recursive_agent
    merged["runtime_root"] = str(runtime_root)
    merged["state_path"] = str(runtime_state_path)
    merged["history_path"] = str(runtime_history_path)
    merged["summary_json_path"] = str(runtime_summary_json_path)
    merged["summary_markdown_path"] = str(runtime_summary_md_path)

    iterations_completed = merged.get("iterations_completed")
    max_iterations = merged.get("max_iterations")
    if isinstance(iterations_completed, int) and isinstance(max_iterations, int):
        merged["remaining_iterations"] = max(max_iterations - iterations_completed, 0)
    else:
        merged["remaining_iterations"] = None
    return merged

def _scheduler_snapshot(mission_state: Mapping[str, Any]) -> dict[str, Any] | None:
    scheduler = mission_state.get("mission_scheduler")
    if not isinstance(scheduler, Mapping) or not scheduler:
        return None
    return {
        "scheduler_id": scheduler.get("scheduler_id"),
        "scheduler_status": scheduler.get("scheduler_status"),
        "priority": scheduler.get("priority"),
        "fair_share_weight": scheduler.get("fair_share_weight"),
        "mission_budget_iterations": scheduler.get("mission_budget_iterations"),
        "iterations_consumed": scheduler.get("iterations_consumed"),
        "remaining_budget": scheduler.get("remaining_budget"),
        "last_scheduled_at": scheduler.get("last_scheduled_at"),
        "last_scheduled_cycle": scheduler.get("last_scheduled_cycle"),
        "last_effective_priority": scheduler.get("last_effective_priority"),
        "suppression_reason": scheduler.get("suppression_reason"),
        "active_operator_request_id": scheduler.get("active_operator_request_id"),
        "scheduler_state_path": scheduler.get("scheduler_state_path"),
        "scheduler_summary_json_path": scheduler.get("scheduler_summary_json_path"),
        "scheduler_summary_markdown_path": scheduler.get("scheduler_summary_markdown_path"),
        "composition": dict(scheduler.get("composition", {})) if isinstance(scheduler.get("composition"), Mapping) else {},
    }

def _branch_records(mission_state: dict[str, Any], branch_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    state_records = mission_state.get("branch_records")
    if isinstance(state_records, list):
        for record in state_records:
            if isinstance(record, Mapping):
                branch_id = str(record.get("branch_id") or "")
                if branch_id:
                    merged[branch_id] = dict(record)
    for record in _dedupe_records(branch_log, identity_field="branch_id"):
        branch_id = str(record.get("branch_id") or "")
        if branch_id:
            merged[branch_id] = record
    return list(merged.values())

def _select_current_action(
    actions: list[dict[str, Any]],
    *,
    current_phase: str,
    runtime: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not actions:
        return None
    runtime_action_id = str(runtime.get("last_action_id") or "") if isinstance(runtime, Mapping) else ""

    def _find(predicate: Any) -> dict[str, Any] | None:
        matches = [action for action in actions if predicate(action)]
        return matches[-1] if matches else None

    selected = _find(lambda action: str(action.get("status") or "") == "in_progress")
    if selected is None and runtime_action_id:
        selected = _find(lambda action: str(action.get("action_id") or "") == runtime_action_id)
    if selected is None and current_phase:
        selected = _find(
            lambda action: str(action.get("phase") or "") == current_phase
            and str(action.get("status") or "") in {"pending", "blocked", "deferred"}
        )
    if selected is None:
        selected = _find(lambda action: str(action.get("status") or "") in {"pending", "blocked", "deferred"})
    if selected is None:
        selected = actions[-1]
    return _summarize_action(selected)

def _select_current_branch(
    branches: list[dict[str, Any]],
    *,
    runtime: Mapping[str, Any] | None,
    current_action: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not branches:
        return None
    requested_branch_id = ""
    if isinstance(current_action, Mapping):
        requested_branch_id = str(current_action.get("branch_id") or "")
    if not requested_branch_id and isinstance(runtime, Mapping):
        requested_branch_id = str(runtime.get("last_branch_id") or "")
    if requested_branch_id:
        for branch in branches:
            if str(branch.get("branch_id") or "") == requested_branch_id:
                return _summarize_branch(branch)
    for branch in reversed(branches):
        if str(branch.get("status") or "") in _ACTIVE_BRANCH_STATUSES:
            return _summarize_branch(branch)
    return _summarize_branch(branches[-1])

def _action_category(action: Mapping[str, Any]) -> str:
    kind = str(action.get("kind") or "").lower()
    executor = action.get("executor") if isinstance(action.get("executor"), Mapping) else {}
    executor_id = str(executor.get("id") or "").lower()
    if "training" in kind or executor_id == "adaptation-training":
        return "training"
    if "eval" in kind or "evaluation" in kind or executor_id in {"stage-kernel", "evaluation-comparison"}:
        return "evaluation"
    return "other"

def _runtime_recovery_entries(runtime_recovery: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(runtime_recovery, Mapping):
        return []
    entries = runtime_recovery.get("entries")
    normalized: list[dict[str, Any]] = []
    if isinstance(entries, Mapping):
        for entry_id, payload in entries.items():
            if isinstance(payload, Mapping):
                record = dict(payload)
                record.setdefault("entry_id", entry_id)
                normalized.append(record)
    elif isinstance(entries, list):
        for payload in entries:
            if isinstance(payload, Mapping):
                normalized.append(dict(payload))
    return normalized

def _parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed

def _format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "unavailable"
    total_seconds = max(int(math.ceil(float(seconds))), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s" if minutes < 10 and secs else f"{minutes}m"
    return f"{secs}s"

def _format_percent(value: Any) -> str | None:
    if not isinstance(value, int | float):
        return None
    return f"{round(float(value) * 100, 1):g}%"

def _first_number(*values: Any) -> float | int | None:
    for value in values:
        if isinstance(value, int | float):
            return value
    return None

def _merge_mapping_values(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, Mapping):
            merged.update(dict(value))
    return merged

def _stage_run_details(stage_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    output_dir = payload.get("output_dir")
    manifest_path = _maybe_path(payload.get("manifest_path"))
    summary_path = _maybe_path(payload.get("summary_path"))
    manifest = _maybe_load_json(manifest_path)
    summary = _maybe_load_json(summary_path)
    runtime_payload = manifest.get("runtime") if isinstance(manifest, Mapping) else None
    stage_context = manifest.get("stage_context") if isinstance(manifest, Mapping) else None
    artifacts = stage_context.get("artifacts") if isinstance(stage_context, Mapping) else None
    runtime_report_path = (
        _maybe_path((artifacts or {}).get("runtime_report_path"))
        or _maybe_path((runtime_payload or {}).get("runtime_report_path"))
        or (Path(output_dir).expanduser().resolve() / "runtime_report.json" if isinstance(output_dir, str) else None)
    )
    runtime_report = _maybe_load_json(runtime_report_path)
    telemetry = _merge_mapping_values(
        (stage_context or {}).get("runtime_telemetry"),
        (runtime_payload or {}).get("telemetry"),
        (runtime_report or {}).get("telemetry"),
    )
    budget = _merge_mapping_values(
        (stage_context or {}).get("runtime_budget"),
        (runtime_payload or {}).get("budget"),
        (runtime_report or {}).get("budget"),
    )
    execution_plan = _merge_mapping_values(
        (stage_context or {}).get("execution_contract"),
        (runtime_payload or {}).get("execution_profile"),
        (runtime_report or {}).get("execution_plan"),
    )
    dataset_record_count = _first_number(
        (stage_context or {}).get("dataset_record_count"),
        (summary or {}).get("dataset_record_count"),
    )
    executed_examples = _first_number(
        telemetry.get("executed_examples"),
        (summary or {}).get("executed_examples"),
    )
    remaining_examples = None
    progress_ratio = None
    if isinstance(dataset_record_count, int | float) and isinstance(executed_examples, int | float):
        remaining_examples = max(int(dataset_record_count) - int(executed_examples), 0)
        if dataset_record_count:
            progress_ratio = max(min(float(executed_examples) / float(dataset_record_count), 1.0), 0.0)
    samples_per_s = telemetry.get("samples_per_s")
    eta_seconds = None
    eta_quality = "unknown"
    if remaining_examples == 0 and isinstance(dataset_record_count, int | float) and dataset_record_count:
        eta_quality = "complete"
        eta_seconds = 0
    elif isinstance(remaining_examples, int) and remaining_examples > 0 and isinstance(samples_per_s, int | float) and samples_per_s > 0:
        eta_quality = "measured"
        eta_seconds = remaining_examples / float(samples_per_s)

    prompt_budget = budget.get("prompt_token_budget")
    prompt_utilization = budget.get("prompt_token_utilization")
    selected_batch_size = budget.get("selected_batch_size")
    batch_probe_order = [int(item) for item in budget.get("batch_probe_order", []) if isinstance(item, int | float)]
    max_batch_probe = max(batch_probe_order) if batch_probe_order else None
    peak_vram_mb = telemetry.get("peak_vram_mb")
    gpu_memory_headroom_gb = budget.get("gpu_memory_headroom_gb")
    compute_signals: list[str] = []
    prompt_utilization_text = _format_percent(prompt_utilization)
    if prompt_utilization_text is not None:
        compute_signals.append(f"prompt window peaked at {prompt_utilization_text} of the token budget")
    if isinstance(selected_batch_size, int | float) and isinstance(max_batch_probe, int):
        if int(selected_batch_size) < max_batch_probe:
            compute_signals.append(
                f"selected batch `{int(selected_batch_size)}` stayed below the probe ceiling `{max_batch_probe}`"
            )
    if isinstance(gpu_memory_headroom_gb, int | float):
        compute_signals.append(f"reserved GPU headroom stays at `{float(gpu_memory_headroom_gb):g} GB`")
    if isinstance(peak_vram_mb, int | float):
        compute_signals.append(f"observed peak VRAM is `{float(peak_vram_mb):g} MB`")
    compute_summary = (
        "Compute use is legible: " + "; ".join(compute_signals[:3]) + "."
        if compute_signals
        else "Compute-budget telemetry is not available for this stage run yet."
    )

    token_summary = "Token-budget telemetry is not available for this stage run yet."
    if isinstance(prompt_budget, int | float):
        token_summary = (
            f"Prompt token budget is `{int(prompt_budget)}`"
            + (
                f"; peak utilization reached `{prompt_utilization_text}`."
                if prompt_utilization_text is not None
                else "."
            )
        )

    cost_payload = runtime_report.get("cost") if isinstance(runtime_report, Mapping) else None
    cost_budget_usd = _first_number(
        (cost_payload or {}).get("budget_usd"),
        budget.get("cost_budget_usd"),
        budget.get("budget_usd"),
    )
    estimated_cost_usd = _first_number(
        (cost_payload or {}).get("estimated_cost_usd"),
        (cost_payload or {}).get("cost_usd"),
        telemetry.get("cost_usd"),
        budget.get("estimated_cost_usd"),
    )
    if isinstance(cost_budget_usd, int | float) or isinstance(estimated_cost_usd, int | float):
        cost_summary = (
            f"Observed cost is `${float(estimated_cost_usd or 0):.4f}`"
            + (f" against `${float(cost_budget_usd):.4f}` budget." if isinstance(cost_budget_usd, int | float) else ".")
        )
    else:
        cost_summary = "Cost telemetry is not available yet; use token and elapsed-time budgets as the current proxy."

    progress_summary = f"Stage `{stage_id}` progress is not measurable yet."
    if isinstance(dataset_record_count, int | float) and isinstance(executed_examples, int | float):
        ratio_text = _format_percent(progress_ratio) or "0%"
        progress_summary = (
            f"Stage `{stage_id}` has processed `{int(executed_examples)}` / `{int(dataset_record_count)}` examples "
            f"(`{ratio_text}` complete)."
        )
    elif isinstance(executed_examples, int | float):
        progress_summary = f"Stage `{stage_id}` has processed `{int(executed_examples)}` examples so far."

    eta_summary = "ETA is still uncertain because no measured inner-loop throughput is available yet."
    if eta_quality == "complete":
        eta_summary = f"Stage `{stage_id}` has already finished its measured inner loop."
    elif eta_quality == "measured":
        eta_summary = f"Measured inner-loop ETA is `{_format_duration(eta_seconds)}` at `{float(samples_per_s):g}` samples/s."

    return {
        "stage_id": stage_id,
        "status": payload.get("status"),
        "output_dir": output_dir,
        "manifest_path": str(manifest_path) if manifest_path is not None else payload.get("manifest_path"),
        "summary_path": str(summary_path) if summary_path is not None else payload.get("summary_path"),
        "runtime_report_path": str(runtime_report_path) if runtime_report_path is not None else None,
        "telemetry": telemetry,
        "budget": budget,
        "execution_plan": execution_plan,
        "dataset_record_count": int(dataset_record_count) if isinstance(dataset_record_count, int | float) else None,
        "executed_examples": int(executed_examples) if isinstance(executed_examples, int | float) else None,
        "remaining_examples": remaining_examples,
        "progress_ratio": progress_ratio,
        "eta_seconds": eta_seconds,
        "eta_quality": eta_quality,
        "progress_summary": progress_summary,
        "eta_summary": eta_summary,
        "compute_summary": compute_summary,
        "compute_signals": compute_signals,
        "token_summary": token_summary,
        "cost_summary": cost_summary,
        "estimated_cost_usd": estimated_cost_usd,
        "cost_budget_usd": cost_budget_usd,
    }

def _stage_runs_snapshot(mission_state: dict[str, Any]) -> list[dict[str, Any]]:
    stage_runs: list[dict[str, Any]] = []
    raw_stage_runs = mission_state.get("stage_runs")
    if isinstance(raw_stage_runs, Mapping):
        for stage_id, payload in raw_stage_runs.items():
            if not isinstance(payload, Mapping):
                continue
            record = _stage_run_details(str(stage_id), payload)
            stage_runs.append(record)
    return stage_runs

def _current_action_record(
    actions: list[dict[str, Any]],
    current_action: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(current_action, Mapping):
        return None
    requested_action_id = str(current_action.get("action_id") or "")
    if not requested_action_id:
        return None
    for action in actions:
        if str(action.get("action_id") or "") == requested_action_id:
            return action
    return None

def _select_stage_run_for_observability(
    stage_runs: list[dict[str, Any]],
    *,
    action_record: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not stage_runs:
        return None
    requested_stage_id = ""
    executor = action_record.get("executor") if isinstance(action_record, Mapping) else None
    params = executor.get("params") if isinstance(executor, Mapping) else None
    if isinstance(params, Mapping):
        requested_stage_id = str(params.get("stage_id") or "")
    if requested_stage_id:
        for stage_run in stage_runs:
            if str(stage_run.get("stage_id") or "") == requested_stage_id:
                return stage_run
    for stage_run in reversed(stage_runs):
        if str(stage_run.get("status") or "") in {"running", "in_progress", "blocked", "pending"}:
            return stage_run
    return stage_runs[-1]

def _outer_loop_eta(runtime: Mapping[str, Any] | None) -> dict[str, Any]:
    remaining_iterations = runtime.get("remaining_iterations") if isinstance(runtime, Mapping) else None
    if not isinstance(runtime, Mapping):
        return {
            "quality": "unknown",
            "eta_seconds": None,
            "summary": "ETA is unavailable because the mission outer runtime has not written iteration telemetry yet.",
        }
    if remaining_iterations == 0:
        return {
            "quality": "complete",
            "eta_seconds": 0,
            "summary": "No outer-loop iterations remain in the current bounded mission runtime.",
        }
    started_at = _parse_timestamp(runtime.get("started_at"))
    updated_at = _parse_timestamp(runtime.get("updated_at"))
    iterations_completed = runtime.get("iterations_completed")
    if (
        isinstance(remaining_iterations, int)
        and remaining_iterations > 0
        and isinstance(iterations_completed, int)
        and iterations_completed > 0
        and started_at is not None
        and updated_at is not None
        and updated_at >= started_at
    ):
        elapsed_seconds = (updated_at - started_at).total_seconds()
        average_iteration_seconds = elapsed_seconds / iterations_completed if iterations_completed else None
        eta_seconds = average_iteration_seconds * remaining_iterations if average_iteration_seconds is not None else None
        return {
            "quality": "rough",
            "eta_seconds": eta_seconds,
            "summary": (
                f"Outer-loop ETA is rough: `{remaining_iterations}` iterations remain, which looks like about "
                f"`{_format_duration(eta_seconds)}` at the current average pace."
            ),
        }
    return {
        "quality": "unknown",
        "eta_seconds": None,
        "summary": "ETA is still uncertain because DeepLoop has not recorded enough outer-loop timing data yet.",
    }

def _inner_loop_snapshot(
    stage_runs: list[dict[str, Any]],
    *,
    action_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    stage_run = _select_stage_run_for_observability(stage_runs, action_record=action_record)
    if not isinstance(stage_run, Mapping):
        return {
            "status": "unavailable",
            "stage_id": None,
            "progress_summary": "No inner-loop telemetry is available for the current mission work yet.",
            "summary": "No inner-loop telemetry is available for the current mission work yet.",
            "eta_quality": "unknown",
            "eta_seconds": None,
            "eta_summary": "ETA is unavailable because no stage runtime telemetry has been surfaced yet.",
            "compute_summary": "Compute budget is unavailable because no stage runtime telemetry has been surfaced yet.",
            "compute_signals": [],
            "token_summary": "Token budget is unavailable because no stage runtime telemetry has been surfaced yet.",
            "cost_summary": "Cost budget is unavailable because no cost telemetry has been surfaced yet.",
            "executed_examples": None,
            "dataset_record_count": None,
            "remaining_examples": None,
            "progress_ratio": None,
            "telemetry_source": None,
        }
    return {
        "status": "tracked",
        "stage_id": stage_run.get("stage_id"),
        "progress_summary": stage_run.get("progress_summary"),
        "summary": stage_run.get("progress_summary"),
        "eta_quality": stage_run.get("eta_quality"),
        "eta_seconds": stage_run.get("eta_seconds"),
        "eta_summary": stage_run.get("eta_summary"),
        "compute_summary": stage_run.get("compute_summary"),
        "compute_signals": list(stage_run.get("compute_signals") or []),
        "token_summary": stage_run.get("token_summary"),
        "cost_summary": stage_run.get("cost_summary"),
        "executed_examples": stage_run.get("executed_examples"),
        "dataset_record_count": stage_run.get("dataset_record_count"),
        "remaining_examples": stage_run.get("remaining_examples"),
        "progress_ratio": stage_run.get("progress_ratio"),
        "telemetry_source": {
            "manifest_path": stage_run.get("manifest_path"),
            "summary_path": stage_run.get("summary_path"),
            "runtime_report_path": stage_run.get("runtime_report_path"),
        },
        "budget": dict(stage_run.get("budget") or {}),
        "telemetry": dict(stage_run.get("telemetry") or {}),
        "estimated_cost_usd": stage_run.get("estimated_cost_usd"),
        "cost_budget_usd": stage_run.get("cost_budget_usd"),
    }

def _jobs_snapshot(
    actions: list[dict[str, Any]],
    runtime_recovery: Mapping[str, Any] | None,
    *,
    stage_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    categorized = {
        "training": {"in_progress": [], "pending": [], "deferred": []},
        "evaluation": {"in_progress": [], "pending": [], "deferred": []},
        "other": {"in_progress": [], "pending": [], "deferred": []},
    }
    for action in actions:
        status = str(action.get("status") or "")
        if status not in {"in_progress", "pending", "deferred"}:
            continue
        category = _action_category(action)
        categorized[category][status].append(_summarize_action(action))

    return {
        **categorized,
        "queue": {
            "queue_name": runtime_recovery.get("queue_name") if isinstance(runtime_recovery, Mapping) else None,
            "counts": dict(runtime_recovery.get("counts") or {}) if isinstance(runtime_recovery, Mapping) else {},
            "entries": _runtime_recovery_entries(runtime_recovery),
        },
        "stage_runs": stage_runs,
    }

def _promotion_signal(payload: Mapping[str, Any], *, source: str, location: str) -> dict[str, Any] | None:
    recommended_state = payload.get("recommended_state")
    max_allowed_state = payload.get("max_allowed_state")
    if recommended_state is None and max_allowed_state is None:
        return None
    return {
        "source": source,
        "location": location,
        "recommended_state": str(recommended_state) if recommended_state is not None else None,
        "max_allowed_state": str(max_allowed_state) if max_allowed_state is not None else None,
        "reasons": _normalize_strings(payload.get("reasons") or payload.get("promotion_reasons")),
    }

def _find_promotion_signals(payload: Any, *, source: str, location: str = "root") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if isinstance(payload, Mapping):
        promotion_guidance = payload.get("promotion_guidance")
        if isinstance(promotion_guidance, Mapping):
            signal = _promotion_signal(promotion_guidance, source=source, location=f"{location}.promotion_guidance")
            if signal is not None:
                findings.append(signal)
        elif "recommended_state" in payload or "max_allowed_state" in payload:
            signal = _promotion_signal(payload, source=source, location=location)
            if signal is not None:
                findings.append(signal)
        for key, value in payload.items():
            if key == "promotion_guidance":
                continue
            findings.extend(_find_promotion_signals(value, source=source, location=f"{location}.{key}"))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            findings.extend(_find_promotion_signals(value, source=source, location=f"{location}[{index}]"))
    return findings

def _promotion_rank(value: str | None) -> int:
    if value is None:
        return len(_PROMOTION_STATE_ORDER) + 1
    return _PROMOTION_STATE_ORDER.get(value, len(_PROMOTION_STATE_ORDER) + 1)

def _promotion_candidate_paths(mission_state: dict[str, Any], end_to_end_summary: dict[str, Any] | None) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    def _add(label: str, raw_path: Any) -> None:
        path = _maybe_path(raw_path)
        if path is None or not path.exists() or path.suffix != ".json" or path in seen:
            return
        seen.add(path)
        candidates.append((label, path))

    runtime_recovery = mission_state.get("runtime_recovery")
    if isinstance(runtime_recovery, Mapping):
        _add("runtime_recovery", runtime_recovery.get("report_json_path"))
    evaluation_comparison = mission_state.get("evaluation_comparison")
    if isinstance(evaluation_comparison, Mapping):
        _add("evaluation_comparison", evaluation_comparison.get("report_json_path"))
    self_correction = mission_state.get("self_correction")
    if isinstance(self_correction, Mapping):
        _add("self_correction", self_correction.get("report_json_path"))
    mission_package = mission_state.get("mission_package")
    if isinstance(mission_package, Mapping):
        _add("mission_package", mission_package.get("package_manifest_path"))
        _add("mission_package", mission_package.get("artifact_index_path"))
    stage_runs = mission_state.get("stage_runs")
    if isinstance(stage_runs, Mapping):
        for stage_id, payload in stage_runs.items():
            if not isinstance(payload, Mapping):
                continue
            _add(f"stage_run:{stage_id}", payload.get("summary_path"))
            _add(f"stage_run:{stage_id}", payload.get("manifest_path"))
    if isinstance(end_to_end_summary, Mapping):
        artifacts = end_to_end_summary.get("artifacts")
        if isinstance(artifacts, Mapping):
            for key in ("baseline_runtime_report", "followup_runtime_report", "package_manifest"):
                _add(f"end_to_end:{key}", artifacts.get(key))
    return candidates

def _promotion_snapshot(mission_state: dict[str, Any], end_to_end_summary: dict[str, Any] | None) -> dict[str, Any]:
    findings = _find_promotion_signals(mission_state, source="mission_state")
    for source, path in _promotion_candidate_paths(mission_state, end_to_end_summary):
        payload = _maybe_load_json(path)
        if payload is not None:
            findings.extend(_find_promotion_signals(payload, source=source))

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str, str]] = set()
    for finding in findings:
        identity = (
            finding.get("recommended_state"),
            finding.get("max_allowed_state"),
            str(finding.get("source") or ""),
            str(finding.get("location") or ""),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(finding)

    if not deduped:
        return {
            "state": "unavailable",
            "max_allowed_state": None,
            "reasons": [],
            "sources": [],
            "summary": "No explicit evidence-promotion guidance surfaced yet from mission artifacts.",
        }

    selected = min(
        deduped,
        key=lambda finding: _promotion_rank(
            str(finding.get("recommended_state") or finding.get("max_allowed_state") or "")
        ),
    )
    max_allowed_state = None
    for finding in deduped:
        candidate = finding.get("max_allowed_state")
        if candidate is None:
            continue
        if max_allowed_state is None or _promotion_rank(candidate) < _promotion_rank(max_allowed_state):
            max_allowed_state = candidate
    reasons: list[str] = []
    for finding in deduped:
        for reason in finding.get("reasons", []):
            if reason not in reasons:
                reasons.append(reason)

    state = selected.get("recommended_state") or selected.get("max_allowed_state") or "available"
    summary = f"Evidence promotion currently resolves to `{state}`."
    if max_allowed_state is not None and max_allowed_state != state:
        summary = f"Evidence promotion currently resolves to `{state}` with ceiling `{max_allowed_state}`."
    if reasons:
        summary = f"{summary} {reasons[0]}"
    return {
        "state": state,
        "max_allowed_state": max_allowed_state,
        "reasons": reasons,
        "sources": deduped[:5],
        "summary": summary,
    }

def _adaptation_metric_ratchet_snapshot(mission_state: dict[str, Any]) -> dict[str, Any] | None:
    adaptation = mission_state.get("adaptation_training")
    if not isinstance(adaptation, Mapping):
        return None
    ratchet = adaptation.get("metric_ratchet")
    if not isinstance(ratchet, Mapping):
        ratchet = adaptation.get("comparison")
    if not isinstance(ratchet, Mapping):
        return None
    return {
        "status": str(adaptation.get("status") or ""),
        "decision": ratchet.get("decision"),
        "route_to": ratchet.get("route_to"),
        "primary_metric": ratchet.get("primary_metric"),
        "anchor_label": ratchet.get("anchor_label"),
        "summary": ratchet.get("summary") or adaptation.get("summary"),
        "promotion_guidance": ratchet.get("promotion_guidance"),
        "report_json_path": adaptation.get("report_json_path"),
        "comparison_path": adaptation.get("comparison_path"),
    }

def _failure_snapshot(
    mission_state: dict[str, Any],
    runtime: Mapping[str, Any] | None,
    runtime_recovery: Mapping[str, Any] | None,
) -> dict[str, Any]:
    recent_failures = _normalize_strings(mission_state.get("recent_failures"))
    blocked_reasons = _normalize_strings(mission_state.get("blocked_reasons"))
    last_reroute: dict[str, Any] | None = None
    for entry in reversed(_runtime_recovery_entries(runtime_recovery)):
        route_to = entry.get("next_route_to")
        final_status = str(entry.get("final_status") or "")
        if route_to or final_status == "rerouted":
            last_reroute = {
                "entry_id": entry.get("entry_id"),
                "status": final_status or None,
                "route_to": route_to,
            }
            break
    if last_reroute is None:
        evaluation_comparison = mission_state.get("evaluation_comparison")
        if isinstance(evaluation_comparison, Mapping):
            final_decision = evaluation_comparison.get("final_decision")
            if isinstance(final_decision, Mapping):
                route_to = final_decision.get("route_to")
                action = final_decision.get("action")
                if route_to or action:
                    last_reroute = {"entry_id": "evaluation_comparison", "status": action, "route_to": route_to}
    if last_reroute is None:
        ratchet = _adaptation_metric_ratchet_snapshot(mission_state)
        if isinstance(ratchet, Mapping):
            route_to = ratchet.get("route_to")
            decision = ratchet.get("decision")
            if route_to or decision:
                last_reroute = {"entry_id": "adaptation_training", "status": decision, "route_to": route_to}

    completion_reason = None
    if isinstance(runtime, Mapping):
        runtime_status = str(runtime.get("status") or "")
        if runtime_status not in {"running", ""}:
            completion_reason = runtime.get("terminal_reason")
    if completion_reason is None:
        autonomy = mission_state.get("autonomy_status")
        if isinstance(autonomy, Mapping):
            autonomy_state = str(autonomy.get("state") or "")
            if "ready" not in autonomy_state and "running" not in autonomy_state:
                completion_reason = autonomy.get("reason")

    return {
        "failure_count": int(mission_state.get("failure_count", 0) or 0),
        "recent_failures": recent_failures,
        "blocked_reasons": blocked_reasons,
        "last_failure": recent_failures[-1] if recent_failures else None,
        "last_blocker": blocked_reasons[-1] if blocked_reasons else None,
        "last_reroute": last_reroute,
        "completion_reason": completion_reason,
}

def _budgets_snapshot(
    runtime: Mapping[str, Any] | None,
    *,
    stage_runs: list[dict[str, Any]],
    action_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    inner_loop = _inner_loop_snapshot(stage_runs, action_record=action_record)
    outer_loop_eta = _outer_loop_eta(runtime)
    if not isinstance(runtime, Mapping):
        return {
            "iterations_completed": None,
            "max_iterations": None,
            "remaining_iterations": None,
            "tracked_budgets": ["inner-loop progress"] if inner_loop.get("status") == "tracked" else [],
            "unavailable_budgets": ["compute", "cost", "outer-loop iterations", "token"],
            "summary": inner_loop.get("summary") or "No mission-outer budget artifact is available yet.",
            "compute": {
                "status": "tracked" if inner_loop.get("status") == "tracked" else "unavailable",
                "summary": inner_loop.get("compute_summary"),
                "signals": inner_loop.get("compute_signals", []),
            },
            "token": {
                "status": "tracked" if inner_loop.get("status") == "tracked" else "unavailable",
                "summary": inner_loop.get("token_summary"),
            },
            "cost": {
                "status": "tracked"
                if isinstance(inner_loop.get("estimated_cost_usd"), int | float)
                or isinstance(inner_loop.get("cost_budget_usd"), int | float)
                else "unavailable",
                "summary": inner_loop.get("cost_summary"),
                "estimated_cost_usd": inner_loop.get("estimated_cost_usd"),
                "budget_usd": inner_loop.get("cost_budget_usd"),
            },
            "eta": {
                "quality": inner_loop.get("eta_quality"),
                "eta_seconds": inner_loop.get("eta_seconds"),
                "summary": inner_loop.get("eta_summary"),
                "outer_loop": outer_loop_eta,
            },
            "inner_loop": inner_loop,
            "recursive_agent": None,
        }
    iterations_completed = runtime.get("iterations_completed")
    max_iterations = runtime.get("max_iterations")
    remaining_iterations = runtime.get("remaining_iterations")
    tracked_budgets: list[str] = []
    unavailable_budgets: list[str] = []
    if max_iterations is not None:
        tracked_budgets.append("outer-loop iterations")
    else:
        unavailable_budgets.append("outer-loop iterations")
    if isinstance(iterations_completed, int) and isinstance(max_iterations, int):
        summary = f"Outer-loop iterations: `{iterations_completed}` / `{max_iterations}` used."
    else:
        summary = "Only partial mission-outer budget metadata is available."
    compute = {
        "status": "tracked" if inner_loop.get("status") == "tracked" else "unavailable",
        "summary": inner_loop.get("compute_summary"),
        "signals": inner_loop.get("compute_signals", []),
    }
    token = {
        "status": "tracked" if inner_loop.get("status") == "tracked" else "unavailable",
        "summary": inner_loop.get("token_summary"),
    }
    cost_tracked = isinstance(inner_loop.get("estimated_cost_usd"), int | float) or isinstance(
        inner_loop.get("cost_budget_usd"), int | float
    )
    cost = {
        "status": "tracked" if cost_tracked else "unavailable",
        "summary": inner_loop.get("cost_summary"),
        "estimated_cost_usd": inner_loop.get("estimated_cost_usd"),
        "budget_usd": inner_loop.get("cost_budget_usd"),
    }
    eta = {
        "quality": inner_loop.get("eta_quality")
        if inner_loop.get("eta_quality") not in {None, "unknown"}
        else outer_loop_eta.get("quality"),
        "eta_seconds": inner_loop.get("eta_seconds")
        if inner_loop.get("eta_quality") not in {None, "unknown"}
        else outer_loop_eta.get("eta_seconds"),
        "summary": inner_loop.get("eta_summary")
        if inner_loop.get("eta_quality") not in {None, "unknown"}
        else outer_loop_eta.get("summary"),
        "outer_loop": outer_loop_eta,
    }
    if compute["status"] == "tracked":
        tracked_budgets.append("compute")
        tracked_budgets.append("token")
    else:
        unavailable_budgets.extend(["compute", "token"])
    if cost_tracked:
        tracked_budgets.append("cost")
    else:
        unavailable_budgets.append("cost")
    if inner_loop.get("status") == "tracked":
        tracked_budgets.append("inner-loop progress")
        summary = f"{summary} {inner_loop.get('summary')}"
    recursive_agent = runtime.get("recursive_agent") if isinstance(runtime.get("recursive_agent"), Mapping) else None
    if isinstance(recursive_agent, Mapping):
        tracked_budgets.append("recursive-agent iterations")
        recursive_iterations = recursive_agent.get("iterations_completed")
        recursive_max = recursive_agent.get("max_iterations")
        if isinstance(recursive_iterations, int) and isinstance(recursive_max, int):
            summary = f"{summary} Recursive-agent iterations: `{recursive_iterations}` / `{recursive_max}` used."
        elif isinstance(recursive_iterations, int):
            summary = f"{summary} Recursive-agent iterations: `{recursive_iterations}` used."
    return {
        "iterations_completed": iterations_completed,
        "max_iterations": max_iterations,
        "remaining_iterations": remaining_iterations,
        "tracked_budgets": tracked_budgets,
        "unavailable_budgets": unavailable_budgets,
        "summary": summary,
        "compute": compute,
        "token": token,
        "cost": cost,
        "eta": eta,
        "inner_loop": inner_loop,
        "recursive_agent": dict(recursive_agent) if isinstance(recursive_agent, Mapping) else None,
    }
