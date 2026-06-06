from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from deeploop.autonomy.operator_inbox import ensure_operator_inbox_contract, load_current_operator_request
from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.structured_io import load_json_object, load_jsonl_objects, write_json_object, write_markdown
from deeploop.mission._autonomy_gap_telemetry import build_autonomy_gap_telemetry
from deeploop.mission._constants import (
    RUNTIME_HISTORY_FILE as _RUNTIME_HISTORY_FILE,
    RUNTIME_STATE_FILE as _RUNTIME_STATE_FILE,
    RUNTIME_SUMMARY_JSON_FILE as _RUNTIME_SUMMARY_JSON_FILE,
    RUNTIME_SUMMARY_MD_FILE as _RUNTIME_SUMMARY_MD_FILE,
)
from deeploop.mission.mission_memory import sync_mission_memory
from deeploop.mission.mission_state import write_mission_state
from deeploop.platform.contracts import sync_platform_expansion_bundle

DEFAULT_RUNTIME_DIR_NAME = "mission_outer_runtime"

def _write_markdown(path: Path, lines: list[str]) -> None:
    write_markdown(path, lines)

def _runtime_root(mission_state_path: Path, runtime_root: Path | None) -> Path:
    if runtime_root is not None:
        return runtime_root.expanduser().resolve()
    return mission_state_path.parent / "runtime" / DEFAULT_RUNTIME_DIR_NAME

def _runtime_state_path(runtime_root: Path) -> Path:
    return runtime_root / _RUNTIME_STATE_FILE

def _runtime_history_path(runtime_root: Path) -> Path:
    return runtime_root / _RUNTIME_HISTORY_FILE

def _runtime_summary_json_path(runtime_root: Path) -> Path:
    return runtime_root / _RUNTIME_SUMMARY_JSON_FILE

def _runtime_summary_md_path(runtime_root: Path) -> Path:
    return runtime_root / _RUNTIME_SUMMARY_MD_FILE

def _default_runtime_state(
    mission_id: str,
    *,
    mission_state_path: Path,
    runtime_root: Path,
    max_iterations: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mission_id": mission_id,
        "mission_state_path": str(mission_state_path),
        "runtime_root": str(runtime_root),
        "status": "initialized",
        "iterations_completed": 0,
        "max_iterations": int(max_iterations),
        "started_at": now_utc(),
        "updated_at": now_utc(),
        "last_decision_id": None,
        "last_action_id": None,
        "last_branch_id": None,
        "last_executor_id": None,
        "terminal_reason": None,
        "history_path": str(_runtime_history_path(runtime_root)),
        "summary_json_path": str(_runtime_summary_json_path(runtime_root)),
        "summary_markdown_path": str(_runtime_summary_md_path(runtime_root)),
    }

def _load_runtime_state(
    mission_id: str,
    *,
    mission_state_path: Path,
    runtime_root: Path,
    max_iterations: int,
) -> dict[str, Any]:
    state_path = _runtime_state_path(runtime_root)
    if state_path.exists():
        state = load_json_object(state_path)
        state["max_iterations"] = int(max_iterations)
        state["updated_at"] = now_utc()
        return state
    return _default_runtime_state(
        mission_id,
        mission_state_path=mission_state_path,
        runtime_root=runtime_root,
        max_iterations=max_iterations,
    )

def _record_history(runtime_root: Path, payload: dict[str, Any]) -> None:
    append_jsonl(_runtime_history_path(runtime_root), payload)

def _runtime_summary(runtime_state: dict[str, Any], *, mission_state: dict[str, Any]) -> dict[str, Any]:
    history = load_jsonl_objects(_runtime_history_path(Path(runtime_state["runtime_root"], missing_ok=True)))
    outer_loop = mission_state.get("outer_loop") if isinstance(mission_state.get("outer_loop"), dict) else {}
    memory_path = (
        Path(outer_loop["mission_memory_path"]).expanduser().resolve()
        if isinstance(outer_loop.get("mission_memory_path"), str)
        else None
    )
    memory_snapshot = load_json_object(memory_path) if memory_path is not None and memory_path.exists() else {}
    current_operator_request_path = (
        Path(outer_loop["current_operator_request_path"]).expanduser().resolve()
        if isinstance(outer_loop.get("current_operator_request_path"), str)
        else None
    )
    operator_request = (
        load_current_operator_request(current_operator_request_path)
        if current_operator_request_path is not None and current_operator_request_path.exists()
        else None
    )
    operator_request_log_path = (
        Path(outer_loop["operator_request_log_path"]).expanduser().resolve()
        if isinstance(outer_loop.get("operator_request_log_path"), str)
        else None
    )
    recursive_agent = mission_state.get("agent_driver") if isinstance(mission_state.get("agent_driver"), Mapping) else None
    runtime_recovery = mission_state.get("runtime_recovery") if isinstance(mission_state.get("runtime_recovery"), Mapping) else None
    autonomy_gap_telemetry = build_autonomy_gap_telemetry(
        mission_state,
        operator_request_log_path=operator_request_log_path,
        current_operator_request=operator_request,
        runtime_recovery=runtime_recovery,
    )
    return {
        **runtime_state,
        "mission": {
            "mission_id": mission_state.get("mission_id"),
            "current_phase": mission_state.get("current_phase"),
            "next_phase": mission_state.get("next_phase"),
            "status": mission_state.get("status"),
            "autonomy_status": mission_state.get("autonomy_status", {}),
        },
        "mission_memory": {
            "path": str(memory_path) if memory_path is not None else None,
            "counts": memory_snapshot.get("counts", {}),
        },
        "operator_inbox": {
            "current_request_path": str(current_operator_request_path) if current_operator_request_path is not None else None,
            "current_request": operator_request,
        },
        "autonomy_gap_telemetry": autonomy_gap_telemetry,
        "recursive_agent": dict(recursive_agent) if isinstance(recursive_agent, Mapping) else None,
        "latest_history": history[-1:] if history else [],
    }

def _write_runtime_summary(runtime_state: dict[str, Any], *, mission_state: dict[str, Any]) -> None:
    runtime_root = Path(runtime_state["runtime_root"])
    summary = _runtime_summary(runtime_state, mission_state=mission_state)
    write_json_object(_runtime_summary_json_path(runtime_root), summary)
    autonomy = mission_state.get("autonomy_status", {}) if isinstance(mission_state.get("autonomy_status"), dict) else {}
    autonomy_gap_telemetry = summary.get("autonomy_gap_telemetry", {})
    telemetry_counts = autonomy_gap_telemetry.get("counts", {}) if isinstance(autonomy_gap_telemetry, Mapping) else {}
    recovery_preferences = (
        autonomy_gap_telemetry.get("recovery_preferences", {})
        if isinstance(autonomy_gap_telemetry, Mapping)
        else {}
    )
    temporary_gap_categories = (
        autonomy_gap_telemetry.get("temporary_gap_categories", {})
        if isinstance(autonomy_gap_telemetry, Mapping)
        else {}
    )
    recursive_agent = summary.get("recursive_agent") if isinstance(summary.get("recursive_agent"), Mapping) else None
    recursive_current_action = (
        recursive_agent.get("pending_action") or recursive_agent.get("current_action")
        if isinstance(recursive_agent, Mapping)
        else None
    )
    lines = [
        "# Mission outer runtime",
        "",
        f"- mission_id: `{mission_state.get('mission_id')}`",
        f"- runtime_status: `{runtime_state.get('status')}`",
        f"- iterations_completed: `{runtime_state.get('iterations_completed')}`",
        f"- current_phase: `{mission_state.get('current_phase')}`",
        f"- next_phase: `{mission_state.get('next_phase')}`",
        f"- mission_status: `{mission_state.get('status')}`",
        f"- autonomy_state: `{autonomy.get('state', 'unknown')}`",
        f"- autonomy_reason: {autonomy.get('reason', 'n/a')}",
        f"- summary_source: `mission_state`",
        f"- autonomy_gap_summary: {autonomy_gap_telemetry.get('summary', 'n/a')}",
        f"- operator_requests_total: `{telemetry_counts.get('operator_requests_total', 0)}`",
        f"- temporary_gap_requests: `{telemetry_counts.get('temporary_gap_requests', 0)}`",
        f"- permanent_boundary_requests: `{telemetry_counts.get('permanent_boundary_requests', 0)}`",
        f"- soft_gates_total: `{telemetry_counts.get('soft_gates_total', 0)}`",
        f"- bounded_recovery_outcomes: `{telemetry_counts.get('bounded_recovery_outcomes', 0)}`",
        f"- unresolved_temporary_gaps: `{telemetry_counts.get('unresolved_temporary_gaps', 0)}`",
        f"- temporary_gap_auto_recovered: `{telemetry_counts.get('temporary_gap_auto_recovered', 0)}`",
        f"- temporary_gap_escalated: `{telemetry_counts.get('temporary_gap_escalated', 0)}`",
        (
            "- temporary_gap_categories: "
            + (
                ", ".join(f"{key}={value}" for key, value in temporary_gap_categories.items())
                if isinstance(temporary_gap_categories, Mapping) and temporary_gap_categories
                else "n/a"
            )
        ),
        (
            "- recovery_preferences: "
            f"retry=`{recovery_preferences.get('retry', 0)}` "
            f"reroute=`{recovery_preferences.get('reroute', 0)}` "
            f"downscope=`{recovery_preferences.get('downscope', 0)}`"
        ),
    ]
    if isinstance(recursive_agent, Mapping):
        iteration_text = (
            f"{recursive_agent.get('iterations_completed')} / {recursive_agent.get('max_iterations')}"
            if recursive_agent.get("max_iterations") is not None
            else str(recursive_agent.get("iterations_completed") or "unknown")
        )
        role = recursive_current_action.get("role") if isinstance(recursive_current_action, Mapping) else "unknown"
        phase = (
            recursive_current_action.get("phase")
            if isinstance(recursive_current_action, Mapping) and recursive_current_action.get("phase") is not None
            else mission_state.get("current_phase")
        )
        lines.append(f"- current_recursive_iteration: {iteration_text}, role={role}, phase={phase}")
    latest_temporary_gap = (
        autonomy_gap_telemetry.get("latest_temporary_gap")
        if isinstance(autonomy_gap_telemetry, Mapping)
        else None
    )
    if isinstance(latest_temporary_gap, Mapping):
        lines.append(
            "- latest_temporary_gap: "
            f"`{latest_temporary_gap.get('kind')}` {latest_temporary_gap.get('summary')}"
        )
    latest_temporary_gap_hint = (
        autonomy_gap_telemetry.get("latest_temporary_gap_hint")
        if isinstance(autonomy_gap_telemetry, Mapping)
        else None
    )
    if isinstance(latest_temporary_gap_hint, Mapping):
        lines.append(
            "- latest_temporary_gap_hint: "
            f"`{latest_temporary_gap_hint.get('category')}` "
            f"-> `{latest_temporary_gap_hint.get('recommended_action') or 'n/a'}` "
            f"[{latest_temporary_gap_hint.get('telemetry_class')}]"
        )
    if runtime_state.get("terminal_reason"):
        lines.append(f"- terminal_reason: {runtime_state['terminal_reason']}")
    _write_markdown(_runtime_summary_md_path(runtime_root), lines)

def _write_state(
    mission_state_path: Path,
    mission_state: dict[str, Any],
    runtime_state: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
    evidence_snapshot: dict[str, Any] | None = None,
    decision_payload: dict[str, Any] | None = None,
    branch_payload: dict[str, Any] | None = None,
    action_payload: dict[str, Any] | None = None,
    executor_payload: Mapping[str, Any] | None = None,
    contract_resolver: Callable[[Path, dict[str, Any]], dict[str, Any]],
    sync_operator_inbox: Callable[..., dict[str, Any] | None],
) -> None:
    runtime_state["updated_at"] = now_utc()
    resolved_contract = contract or contract_resolver(mission_state_path, mission_state)
    memory_snapshot = sync_mission_memory(
        mission_state_path,
        mission_state,
        contract=resolved_contract,
        runtime_state=runtime_state,
        evidence_snapshot=evidence_snapshot,
        decision_payload=decision_payload,
        branch_payload=branch_payload,
    )
    operator_paths = ensure_operator_inbox_contract(mission_state_path.parent, contract=resolved_contract)
    operator_request_log_path = operator_paths["operator_request_log_path"]
    current_operator_request_path = operator_paths["current_operator_request_path"]
    operator_request = sync_operator_inbox(
        mission_state_path,
        mission_state,
        runtime_state,
        contract=resolved_contract,
        decision_payload=decision_payload,
        action_payload=action_payload,
        executor_payload=executor_payload,
    )
    mission_state["mission_runtime"] = {
        "runtime_root": runtime_state["runtime_root"],
        "state_path": str(_runtime_state_path(Path(runtime_state["runtime_root"]))),
        "history_path": runtime_state["history_path"],
        "status": runtime_state["status"],
        "iterations_completed": runtime_state["iterations_completed"],
        "updated_at": runtime_state["updated_at"],
        "terminal_reason": runtime_state.get("terminal_reason"),
        "mission_memory_path": resolved_contract["mission_memory_path"],
        "experiment_ledger_path": resolved_contract["experiment_ledger_path"],
        "research_memory_events_path": resolved_contract["research_memory_events_path"],
        "research_memory_index_path": resolved_contract["research_memory_index_path"],
        "operator_request_log_path": operator_request_log_path,
        "current_operator_request_path": current_operator_request_path,
        "current_operator_request_id": operator_request.get("request_id") if isinstance(operator_request, dict) else None,
        "memory_updated_at": memory_snapshot["updated_at"],
        "autonomy_gap_telemetry": build_autonomy_gap_telemetry(
            mission_state,
            operator_request_log_path=Path(operator_request_log_path),
            current_operator_request=operator_request,
            runtime_recovery=mission_state.get("runtime_recovery")
            if isinstance(mission_state.get("runtime_recovery"), Mapping)
            else None,
        ),
    }
    mission_state["operator_inbox"] = {
        "status": "open" if isinstance(operator_request, dict) else "clear",
        "current_request_id": operator_request.get("request_id") if isinstance(operator_request, dict) else None,
        "operator_request_log_path": operator_request_log_path,
        "current_operator_request_path": current_operator_request_path,
        "updated_at": runtime_state["updated_at"],
    }
    write_mission_state(mission_state_path, mission_state)
    write_json_object(_runtime_state_path(Path(runtime_state["runtime_root"])), runtime_state)
    _write_runtime_summary(runtime_state, mission_state=mission_state)
    sync_platform_expansion_bundle(mission_state_path, mission_state=mission_state)

def _transition_ledger_paths(mission_state_path: Path, runtime_root: Path, contract: dict[str, Any]) -> list[str]:
    return [
        str(mission_state_path),
        str(_runtime_state_path(runtime_root)),
        str(_runtime_history_path(runtime_root)),
        str(contract["decision_log_path"]),
        str(contract["branch_log_path"]),
        str(contract["mission_memory_path"]),
        str(contract["experiment_ledger_path"]),
        str(contract["research_memory_events_path"]),
        str(contract["research_memory_index_path"]),
        str(contract["operator_request_log_path"]),
        str(contract["current_operator_request_path"]),
    ]

def _record_ledger(
    mission_state_path: Path,
    *,
    mission_state: dict[str, Any],
    runtime_root: Path,
    contract: dict[str, Any],
    kind: str,
    status: str,
    summary: str,
    metadata: dict[str, Any] | None = None,
    jsonify: Callable[[Any], Any],
) -> None:
    ledger_path = mission_state_path.parent / "ledger.jsonl"
    append_jsonl(
        ledger_path,
        make_ledger_entry(
            kind=kind,
            mission_id=str(mission_state.get("mission_id") or ""),
            summary=summary,
            status=status,
            related_paths=_transition_ledger_paths(mission_state_path, runtime_root, contract),
            metadata=jsonify(metadata or {}),
        ),
    )
