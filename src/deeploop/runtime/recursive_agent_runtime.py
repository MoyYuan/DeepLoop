from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

from deeploop.autonomy.mission_contract_snapshot import resolve_phase_contract_for_state
from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.paths import REPO_ROOT as DEEPLOOP_REPO_ROOT
from deeploop.core.structured_io import load_json_object, load_jsonl_objects, write_json_object, write_markdown
from deeploop.mission.mission_state import load_mission_state, write_mission_state
from deeploop.runtime._prompt_renderer import (
    iteration_summary_markdown as _iteration_summary_markdown,
    loop_report_markdown as _loop_report_markdown,
    render_prompt as _render_prompt,
)
from deeploop.runtime.sandbox import build_sandbox_spec

DEFAULT_POLICY_PATH = DEEPLOOP_REPO_ROOT / "configs" / "runtime" / "recursive-agent-runtime.yaml"
ROLE_ALIASES = {"executor": "execution-operator"}


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded


def _load_json(path: Path) -> dict[str, Any]:
    return load_json_object(path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return load_jsonl_objects(path, missing_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json_object(path, payload)


def _write_markdown(path: Path, lines: list[str]) -> None:
    write_markdown(path, lines)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _normalize_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (str, Path)):
        return [str(raw)]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    raise ValueError(f"Expected list-like value, got {type(raw).__name__}")


def _is_list_like(raw: Any) -> bool:
    return raw is None or isinstance(raw, (str, Path, list))


def _resolved_env_name(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _optional_string(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _normalize_action(
    raw: dict[str, Any],
    *,
    default_role: str,
    default_phase: str,
    source: str,
    mission_action_index: int | None = None,
) -> dict[str, Any]:
    if not isinstance(raw.get("task"), str) or not str(raw["task"]).strip():
        raise ValueError("recursive runtime actions must include a non-empty task")
    return {
        "role": str(raw.get("role", default_role)),
        "task": str(raw["task"]).strip(),
        "artifacts": _normalize_list(raw.get("artifacts")),
        "action_id": _optional_string(raw.get("action_id")),
        "loop_action_id": _optional_string(raw.get("loop_action_id")),
        "kind": _optional_string(raw.get("kind")),
        "phase": str(raw.get("phase", default_phase) or default_phase),
        "branch_id": _optional_string(raw.get("branch_id")),
        "decision_id": _optional_string(raw.get("decision_id")),
        "notes": _normalize_list(raw.get("notes")),
        "produces_outputs": _normalize_list(raw.get("produces_outputs")),
        "source": source,
        "mission_action_index": mission_action_index,
    }


def _select_next_action(actions: list[Any], cursor: int) -> tuple[int, dict[str, Any] | None]:
    index = max(cursor, 0)
    while index < len(actions):
        candidate = actions[index]
        if not isinstance(candidate, dict):
            raise ValueError("mission next action entries must be mappings with a task")
        status = str(candidate.get("status") or "").strip().lower()
        if status in {"completed", "cancelled", "blocked", "failed", "error"}:
            index += 1
            continue
        return index, candidate
    return index, None


def _loop_action_id(loop_name: str, iteration_number: int, role: str) -> str:
    safe_role = role.replace(" ", "-")
    return f"{loop_name}-iter-{iteration_number:02d}-{safe_role}"


def _canonical_role(role: str, mission_state: dict[str, Any] | None) -> str:
    roles = mission_state.get("roles") if isinstance(mission_state, dict) else None
    declared_roles = {str(item) for item in roles} if isinstance(roles, list) else set()
    if role in declared_roles:
        return role
    alias = ROLE_ALIASES.get(role)
    if alias is not None and (not declared_roles or alias in declared_roles):
        return alias
    return role


def _canonicalize_action_role(action: dict[str, Any], mission_state: dict[str, Any] | None) -> dict[str, Any]:
    role = _optional_string(action.get("role"))
    if role is not None:
        action["role"] = _canonical_role(role, mission_state)
    return action


def _latest_matching_record(path: Path | None, field: str, value: str | None) -> dict[str, Any] | None:
    if path is None or value is None or not path.exists():
        return None
    for record in reversed(_load_jsonl(path)):
        if str(record.get(field) or "") == value:
            return record
    return None


def _normalize_continuation(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw = payload.get("continuation")
    if isinstance(raw, dict):
        role = _optional_string(raw.get("role"))
        task = _optional_string(raw.get("task"))
        if role and task:
            return {
                "role": role,
                "task": task,
                "artifacts": _normalize_list(raw.get("artifacts")),
                "action_id": _optional_string(raw.get("action_id")),
                "kind": _optional_string(raw.get("kind")),
                "phase": _optional_string(raw.get("phase")),
                "branch_id": _optional_string(raw.get("branch_id")),
                "decision_id": _optional_string(raw.get("decision_id")),
                "notes": _normalize_list(raw.get("notes")),
                "source": "agent-continuation",
                "mission_action_index": None,
            }
    next_role = _optional_string(payload.get("next_role"))
    next_task = _optional_string(payload.get("next_task"))
    if next_role and next_task:
        return {
            "role": next_role,
            "task": next_task,
            "artifacts": _normalize_list(payload.get("produced_artifacts")),
            "action_id": None,
            "kind": None,
            "phase": None,
            "branch_id": None,
            "decision_id": None,
            "notes": [],
            "source": "legacy-handoff",
            "mission_action_index": None,
        }
    return None


def _continuation_matches_action(continuation: dict[str, Any], candidate: dict[str, Any]) -> bool:
    for key in ("role", "task", "phase", "kind", "branch_id"):
        continuation_value = _optional_string(continuation.get(key))
        candidate_value = _optional_string(candidate.get(key))
        if continuation_value is not None and continuation_value != candidate_value:
            return False
    return True


def _sanitize_continuation(
    continuation: dict[str, Any] | None,
    *,
    mission_state: dict[str, Any] | None,
    action: dict[str, Any],
) -> dict[str, Any] | None:
    if continuation is None:
        return None
    sanitized = dict(continuation)
    role = _optional_string(sanitized.get("role"))
    if role is not None:
        sanitized["role"] = _canonical_role(role, mission_state)
    next_actions = mission_state.get("next_actions") if isinstance(mission_state, dict) else None
    actions = next_actions.get("actions") if isinstance(next_actions, dict) else None
    if isinstance(actions, list):
        for candidate in actions:
            if not isinstance(candidate, dict):
                continue
            candidate_action_id = _optional_string(candidate.get("action_id"))
            continuation_action_id = _optional_string(sanitized.get("action_id"))
            if continuation_action_id is not None and continuation_action_id != candidate_action_id:
                continue
            if not _continuation_matches_action(sanitized, candidate):
                continue
            sanitized["action_id"] = candidate_action_id
            for key in ("kind", "phase", "branch_id", "decision_id"):
                candidate_value = _optional_string(candidate.get(key))
                if candidate_value is not None:
                    sanitized[key] = candidate_value
            return sanitized
    if _continuation_matches_action(sanitized, action):
        if _optional_string(action.get("action_id")) is not None:
            sanitized["action_id"] = _optional_string(action.get("action_id"))
        if _optional_string(action.get("decision_id")) is not None:
            sanitized["decision_id"] = _optional_string(action.get("decision_id"))
        for key in ("kind", "phase", "branch_id"):
            if _optional_string(sanitized.get(key)) is None and _optional_string(action.get(key)) is not None:
                sanitized[key] = _optional_string(action.get(key))
        return sanitized
    sanitized["action_id"] = None
    sanitized["decision_id"] = None
    return sanitized


def _default_action_result_status(iteration_status: str) -> str:
    if iteration_status in {"continue", "complete"}:
        return "completed"
    if iteration_status == "blocked":
        return "blocked"
    return "in_progress"


def _canonical_action_result_status(raw: Any, *, iteration_status: str) -> str:
    value = _optional_string(raw)
    if value is None:
        return _default_action_result_status(iteration_status)
    aliases = {
        "continue": "completed",
        "complete": "completed",
        "completed": "completed",
        "critique-parked": "completed",
        "in-progress": "in_progress",
    }
    if value.startswith("contract-failure"):
        return "completed"
    return aliases.get(value, value)


def _normalize_phase_control(payload: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("phase_control") if isinstance(payload.get("phase_control"), dict) else {}
    normalized = {
        "current_phase": _optional_string(raw.get("current_phase")) or _optional_string(action.get("phase")),
        "next_phase": _optional_string(raw.get("next_phase")),
        "decision_type": _optional_string(raw.get("decision_type")),
        "branch_status": _optional_string(raw.get("branch_status")),
        "recovery_status": _optional_string(raw.get("recovery_status")),
        "summary": _optional_string(raw.get("summary")),
    }
    return {key: value for key, value in normalized.items() if value is not None}


def _normalize_action_result(payload: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("action_result") if isinstance(payload.get("action_result"), dict) else {}
    normalized = {
        "mission_action_id": _optional_string(raw.get("mission_action_id")) or _optional_string(action.get("action_id")),
        "loop_action_id": _optional_string(raw.get("loop_action_id")) or _optional_string(action.get("loop_action_id")),
        "status": _canonical_action_result_status(raw.get("status"), iteration_status=str(payload["status"])),
        "phase": _optional_string(raw.get("phase")) or _optional_string(action.get("phase")),
        "kind": _optional_string(raw.get("kind")) or _optional_string(action.get("kind")),
        "branch_id": _optional_string(raw.get("branch_id")) or _optional_string(action.get("branch_id")),
        "decision_id": _optional_string(raw.get("decision_id")) or _optional_string(action.get("decision_id")),
        "output_paths": _normalize_list(raw.get("output_paths")) or _normalize_list(payload.get("produced_artifacts")),
        "notes": _normalize_list(raw.get("notes")),
    }
    return normalized


def _normalized_result_outcome(
    payload: dict[str, Any],
    action: dict[str, Any],
    *,
    mission_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": str(payload["status"]),
        "summary": str(payload["summary"]),
        "continuation": _sanitize_continuation(
            _normalize_continuation(payload),
            mission_state=mission_state,
            action=action,
        ),
        "phase_control": _normalize_phase_control(payload, action),
        "action_result": _normalize_action_result(payload, action),
        "produced_artifacts": _normalize_list(payload.get("produced_artifacts")),
        "findings": _normalize_list(payload.get("findings")),
        "mission_state_updates": payload.get("mission_state_updates", {}),
    }


def _should_yield_to_outer_runtime(
    outcome: dict[str, Any] | None,
    *,
    action: dict[str, Any] | None,
) -> bool:
    if not isinstance(outcome, dict) or not isinstance(action, dict):
        return False
    continuation = outcome.get("continuation")
    if not isinstance(continuation, dict) or not _continuation_matches_action(continuation, action):
        return False
    phase_control = outcome.get("phase_control")
    if not isinstance(phase_control, dict):
        return False
    current_phase = _optional_string(phase_control.get("current_phase")) or _optional_string(action.get("phase"))
    next_phase = _optional_string(phase_control.get("next_phase")) or current_phase
    if not current_phase or next_phase != current_phase:
        return False
    decision_type = (_optional_string(phase_control.get("decision_type")) or "").lower()
    branch_status = (_optional_string(phase_control.get("branch_status")) or "").lower()
    return decision_type in {"hold", "stay-in-critique"} or branch_status == "critique-parked"


def _should_yield_before_execution(
    outcome: dict[str, Any] | None,
    *,
    action: dict[str, Any] | None,
    remaining_iterations: int,
) -> bool:
    if remaining_iterations > 1 or not isinstance(outcome, dict) or not isinstance(action, dict):
        return False
    continuation = outcome.get("continuation")
    if not isinstance(continuation, dict):
        return False
    phase_control = outcome.get("phase_control")
    next_phase = _optional_string(continuation.get("phase"))
    if next_phase is None and isinstance(phase_control, dict):
        next_phase = _optional_string(phase_control.get("next_phase"))
    action_phase = _optional_string(action.get("phase"))
    if next_phase != "execution" or action_phase == "execution":
        return False
    continuation_role = _optional_string(continuation.get("role"))
    return continuation_role in {None, "execution-operator"} or continuation_role in ROLE_ALIASES


def _effective_outcome(outcome: dict[str, Any] | None, loop_status: str) -> dict[str, Any] | None:
    if outcome is None:
        return None
    effective = dict(outcome)
    action_result = dict(effective.get("action_result", {}))
    if loop_status == "blocked" and action_result.get("status") == "in_progress":
        action_result["status"] = "blocked"
    effective["action_result"] = action_result
    return effective


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _build_command(command: list[str], env_name: str | None) -> list[str]:
    if env_name is None:
        return command
    return ["conda", "run", "-n", env_name, *command]


def _runtime_root(mission_state_path: Path, artifact_dir_name: str, loop_name: str) -> Path:
    return mission_state_path.parent / "runtime" / artifact_dir_name / loop_name


def _memory_path(runtime_root: Path) -> Path:
    return runtime_root / "loop_memory.jsonl"


def _state_path(runtime_root: Path) -> Path:
    return runtime_root / "agent_loop_state.json"


def _recent_entries(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    return records[-limit:]


def _loop_state(runtime_root: Path, mission_id: str, loop_name: str) -> dict[str, Any]:
    state_path = _state_path(runtime_root)
    if state_path.exists():
        return _load_json(state_path)
    return {
        "schema_version": 1,
        "mission_id": mission_id,
        "loop_name": loop_name,
        "status": "initialized",
        "iterations_completed": 0,
        "consecutive_failures": 0,
        "action_cursor": 0,
        "initial_task_consumed": False,
        "pending_action": None,
        "latest_iteration_path": None,
        "latest_result_path": None,
        "updated_at": now_utc(),
    }


def _save_loop_state(runtime_root: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_utc()
    _write_json(_state_path(runtime_root), state)


def _replace_markdown_field(lines: list[str], field: str, value: str) -> list[str]:
    prefix = f"- {field}:"
    updated = list(lines)
    for index, line in enumerate(updated):
        if line.startswith(prefix):
            updated[index] = f"{prefix} {value}"
            return updated
    updated.append(f"{prefix} {value}")
    return updated


def _sync_outer_runtime_summary_from_recursive_agent(mission_state: Mapping[str, Any]) -> None:
    mission_runtime = mission_state.get("mission_runtime")
    agent_driver = mission_state.get("agent_driver")
    if not isinstance(mission_runtime, Mapping) or not isinstance(agent_driver, Mapping):
        return
    synchronized_at = now_utc()
    raw_summary_json_path = mission_runtime.get("summary_json_path")
    if raw_summary_json_path:
        summary_json_path = Path(str(raw_summary_json_path)).expanduser()
        try:
            summary = _load_json(summary_json_path) if summary_json_path.exists() else {}
            summary["mission"] = {
                "mission_id": mission_state.get("mission_id"),
                "current_phase": mission_state.get("current_phase"),
                "next_phase": mission_state.get("next_phase"),
                "status": mission_state.get("status"),
                "autonomy_status": mission_state.get("autonomy_status", {}),
            }
            summary["recursive_agent"] = dict(agent_driver)
            summary["summary_source"] = "mission_state"
            summary["summary_synchronized_at"] = synchronized_at
            _write_json(summary_json_path, summary)
        except (OSError, ValueError):
            pass

    raw_summary_markdown_path = mission_runtime.get("summary_markdown_path")
    if not raw_summary_markdown_path:
        return
    summary_markdown_path = Path(str(raw_summary_markdown_path)).expanduser()
    try:
        lines = summary_markdown_path.read_text(encoding="utf-8").splitlines() if summary_markdown_path.exists() else []
        autonomy = mission_state.get("autonomy_status", {}) if isinstance(mission_state.get("autonomy_status"), Mapping) else {}
        active_action = agent_driver.get("pending_action") or agent_driver.get("current_action")
        iteration_text = (
            f"{agent_driver.get('iterations_completed')} / {agent_driver.get('max_iterations')}"
            if agent_driver.get("max_iterations") is not None
            else str(agent_driver.get("iterations_completed") or "unknown")
        )
        role = active_action.get("role") if isinstance(active_action, Mapping) else "unknown"
        phase = (
            active_action.get("phase")
            if isinstance(active_action, Mapping) and active_action.get("phase") is not None
            else mission_state.get("current_phase")
        )
        replacements = {
            "current_phase": f"`{mission_state.get('current_phase')}`",
            "next_phase": f"`{mission_state.get('next_phase')}`",
            "mission_status": f"`{mission_state.get('status')}`",
            "autonomy_state": f"`{autonomy.get('state', 'unknown')}`",
            "autonomy_reason": str(autonomy.get("reason", "n/a")),
            "summary_source": "`mission_state`",
            "summary_synchronized_at": f"`{synchronized_at}`",
            "current_recursive_iteration": f"{iteration_text}, role={role}, phase={phase}",
        }
        for field, value in replacements.items():
            lines = _replace_markdown_field(lines, field, value)
        _write_markdown(summary_markdown_path, lines)
    except OSError:
        pass




def _validate_result(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = payload.get("status")
    if status not in {"continue", "complete", "blocked", "failed"}:
        errors.append("result.status must be one of continue|complete|blocked|failed")
    if not isinstance(payload.get("summary"), str) or not str(payload.get("summary")).strip():
        errors.append("result.summary must be a non-empty string")
    for key in ("next_role", "next_task"):
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"result.{key} must be a string when present")
    for key in ("produced_artifacts", "findings"):
        value = payload.get(key)
        if not _is_list_like(value):
            errors.append(f"result.{key} must be a list-like value when present")
    updates = payload.get("mission_state_updates")
    if updates is not None and not isinstance(updates, dict):
        errors.append("result.mission_state_updates must be an object when present")
    continuation = payload.get("continuation")
    if continuation is not None:
        if not isinstance(continuation, dict):
            errors.append("result.continuation must be an object when present")
        else:
            role = continuation.get("role")
            task = continuation.get("task")
            if (role is None) != (task is None):
                errors.append("result.continuation.role and result.continuation.task must be provided together")
            for key in ("role", "task", "action_id", "kind", "phase", "branch_id", "decision_id"):
                value = continuation.get(key)
                if value is not None and not isinstance(value, str):
                    errors.append(f"result.continuation.{key} must be a string when present")
            for key in ("artifacts", "notes"):
                value = continuation.get(key)
                if not _is_list_like(value):
                    errors.append(f"result.continuation.{key} must be a list-like value when present")
    action_result = payload.get("action_result")
    if action_result is not None:
        if not isinstance(action_result, dict):
            errors.append("result.action_result must be an object when present")
        else:
            value = _canonical_action_result_status(action_result.get("status"), iteration_status=str(payload["status"]))
            if value is not None and value not in {"in_progress", "completed", "blocked", "deferred", "cancelled"}:
                errors.append(
                    "result.action_result.status must be one of in_progress|completed|blocked|deferred|cancelled"
                )
            for key in ("mission_action_id", "loop_action_id", "phase", "kind", "branch_id", "decision_id"):
                value = action_result.get(key)
                if value is not None and not isinstance(value, str):
                    errors.append(f"result.action_result.{key} must be a string when present")
            for key in ("output_paths", "notes"):
                value = action_result.get(key)
                if not _is_list_like(value):
                    errors.append(f"result.action_result.{key} must be a list-like value when present")
    phase_control = payload.get("phase_control")
    if phase_control is not None:
        if not isinstance(phase_control, dict):
            errors.append("result.phase_control must be an object when present")
        else:
            for key in ("current_phase", "next_phase", "decision_type", "branch_status", "recovery_status", "summary"):
                value = phase_control.get(key)
                if value is not None and not isinstance(value, str):
                    errors.append(f"result.phase_control.{key} must be a string when present")
    return errors


def _update_mission_action_state(
    mission_state: dict[str, Any],
    *,
    action: dict[str, Any] | None,
    action_result: dict[str, Any] | None,
) -> None:
    if action is None or action_result is None:
        return
    next_actions = mission_state.get("next_actions")
    if not isinstance(next_actions, dict):
        return
    actions = next_actions.get("actions")
    if not isinstance(actions, list):
        return

    target_action_id = _optional_string(action_result.get("mission_action_id")) or _optional_string(action.get("action_id"))
    target_index = action.get("mission_action_index")
    for index, item in enumerate(actions):
        if not isinstance(item, dict):
            continue
        if target_action_id is not None and _optional_string(item.get("action_id")) != target_action_id:
            continue
        if target_action_id is None and target_index != index:
            continue
        updated = dict(item)
        updated["status"] = str(action_result.get("status") or updated.get("status") or "in_progress")
        output_paths = _normalize_list(action_result.get("output_paths"))
        if output_paths:
            updated["output_paths"] = output_paths
        notes = _normalize_list(updated.get("notes")) + [
            item
            for item in _normalize_list(action_result.get("notes"))
            if item not in _normalize_list(updated.get("notes"))
        ]
        if notes:
            updated["notes"] = notes
        for key in ("phase", "kind", "branch_id", "decision_id"):
            value = action_result.get(key)
            if value is not None:
                updated[key] = value
        actions[index] = updated
        return


def _resolve_transitioned_current_phase(
    *,
    mission_state: dict[str, Any],
    action: dict[str, Any] | None,
    continuation: dict[str, Any] | None,
    phase_control: dict[str, Any],
) -> str | None:
    current_phase = _optional_string(phase_control.get("current_phase")) or _optional_string(mission_state.get("current_phase"))
    next_phase = _optional_string(phase_control.get("next_phase"))
    action_phase = _optional_string(action.get("phase")) if isinstance(action, dict) else None
    action_kind = _optional_string(action.get("kind")) if isinstance(action, dict) else None
    continuation_phase = _optional_string(continuation.get("phase")) if isinstance(continuation, dict) else None
    if next_phase and current_phase and next_phase != current_phase:
        if continuation_phase == next_phase:
            return next_phase
        if action_kind == "phase-transition" and action_phase == current_phase:
            return next_phase
    return current_phase


def _timeout_seconds_for_action(
    *,
    config: Mapping[str, Any],
    policy: Mapping[str, Any],
    action: Mapping[str, Any] | None,
) -> int:
    base_timeout = int(config.get("timeout_seconds", policy.get("timeout_seconds", 1800)))
    phase = _optional_string(action.get("phase")) if isinstance(action, Mapping) else None
    role = _optional_string(action.get("role")) if isinstance(action, Mapping) else None
    raw_phase_timeouts = config.get("phase_timeout_seconds", policy.get("phase_timeout_seconds", {}))
    if phase and isinstance(raw_phase_timeouts, Mapping):
        phase_timeout = raw_phase_timeouts.get(phase)
        if phase_timeout is not None:
            return max(base_timeout, int(phase_timeout))
    if role == "execution-operator" and isinstance(raw_phase_timeouts, Mapping):
        execution_timeout = raw_phase_timeouts.get("execution")
        if execution_timeout is not None:
            return max(base_timeout, int(execution_timeout))
    return base_timeout


def _append_unique(values: list[str], item: str | None) -> None:
    if item and item not in values:
        values.append(item)


def _merge_phase_outputs(mission_state: dict[str, Any], *, phase: str, outputs: list[str]) -> None:
    if not phase or not outputs:
        return
    phase_outputs = mission_state.get("phase_outputs_by_phase")
    if not isinstance(phase_outputs, dict):
        phase_outputs = {}
    existing = _normalize_list(phase_outputs.get(phase))
    for output in outputs:
        if output not in existing:
            existing.append(output)
    phase_outputs[phase] = existing
    mission_state["phase_outputs_by_phase"] = phase_outputs


def _outputs_for_transitioned_action(
    *,
    mission_state: Mapping[str, Any] | None,
    current_action: dict[str, Any] | None,
    phase_control: dict[str, Any],
    continuation: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(current_action, dict):
        return []
    outputs = _normalize_list(current_action.get("produces_outputs"))
    if outputs:
        return outputs
    action_phase = _optional_string(current_action.get("phase"))
    current_phase = _optional_string(phase_control.get("current_phase"))
    next_phase = _optional_string(phase_control.get("next_phase"))
    continuation_phase = _optional_string(continuation.get("phase")) if isinstance(continuation, dict) else None
    if not action_phase or not next_phase or next_phase == action_phase:
        return []
    if continuation_phase == next_phase or current_phase == action_phase:
        return _normalize_list(resolve_phase_contract_for_state(action_phase, mission_state=mission_state).get("outputs"))
    return []


def _apply_result_to_mission(
    mission_state_path: Path,
    mission_state: dict[str, Any],
    *,
    runtime_root: Path,
    loop_name: str,
    state: dict[str, Any],
    current_action: dict[str, Any] | None,
    latest_outcome: dict[str, Any] | None,
    status: str,
) -> dict[str, Any]:
    effective_outcome = _effective_outcome(latest_outcome, status)
    previous_phase = _optional_string(mission_state.get("current_phase"))
    if effective_outcome is not None and isinstance(effective_outcome.get("mission_state_updates"), dict):
        mission_state = _deep_merge(mission_state, effective_outcome["mission_state_updates"])
    phase_control = effective_outcome.get("phase_control", {}) if effective_outcome is not None else {}
    continuation = effective_outcome.get("continuation") if effective_outcome is not None else None
    completed_phases = _normalize_list(mission_state.get("completed_phases"))
    phase_history = _normalize_list(mission_state.get("phase_history"))
    transitioned_outputs = _outputs_for_transitioned_action(
        mission_state=mission_state,
        current_action=current_action,
        phase_control=phase_control if isinstance(phase_control, dict) else {},
        continuation=continuation if isinstance(continuation, dict) else None,
    )
    output_phase = _optional_string(current_action.get("phase")) if isinstance(current_action, dict) else previous_phase
    if output_phase and transitioned_outputs:
        _merge_phase_outputs(mission_state, phase=output_phase, outputs=transitioned_outputs)
    resolved_current_phase = _resolve_transitioned_current_phase(
        mission_state=mission_state,
        action=current_action,
        continuation=continuation if isinstance(continuation, dict) else None,
        phase_control=phase_control if isinstance(phase_control, dict) else {},
    )
    if resolved_current_phase is not None:
        mission_state["current_phase"] = resolved_current_phase
    if previous_phase and resolved_current_phase and previous_phase != resolved_current_phase:
        _append_unique(completed_phases, previous_phase)
    _append_unique(phase_history, previous_phase)
    _append_unique(phase_history, mission_state.get("current_phase"))
    if completed_phases:
        mission_state["completed_phases"] = completed_phases
    if phase_history:
        mission_state["phase_history"] = phase_history
    if resolved_current_phase is not None:
        current_phase_outputs = _normalize_list((mission_state.get("phase_outputs_by_phase") or {}).get(resolved_current_phase))
        mission_state["produced_outputs"] = current_phase_outputs
        mission_state["phase_outputs"] = current_phase_outputs
    if phase_control.get("next_phase") is not None:
        mission_state["next_phase"] = phase_control["next_phase"]
    _update_mission_action_state(
        mission_state,
        action=current_action,
        action_result=effective_outcome.get("action_result") if effective_outcome is not None else None,
    )
    mission_state["agent_driver"] = {
        "generated_at": now_utc(),
        "loop_name": loop_name,
        "runtime_root": str(runtime_root),
        "state_path": str(_state_path(runtime_root)),
        "memory_path": str(_memory_path(runtime_root)),
        "status": status,
        "max_iterations": state.get("max_iterations"),
        "iterations_completed": state["iterations_completed"],
        "iterations_remaining": state.get("iterations_remaining"),
        "consecutive_failures": state["consecutive_failures"],
        "latest_result_path": state.get("latest_result_path"),
        "latest_iteration_path": state.get("latest_iteration_path"),
        "pending_action": state.get("pending_action"),
        "current_action": current_action,
        "latest_mission_action_id": effective_outcome.get("action_result", {}).get("mission_action_id")
        if effective_outcome is not None
        else None,
        "latest_loop_action_id": effective_outcome.get("action_result", {}).get("loop_action_id")
        if effective_outcome is not None
        else None,
        "active_branch_id": (
            effective_outcome.get("action_result", {}).get("branch_id")
            if effective_outcome is not None
            else None
        )
        or (current_action.get("branch_id") if isinstance(current_action, dict) else None),
        "latest_outcome": effective_outcome,
    }
    if status == "completed":
        mission_state["autonomy_status"] = {
            "state": "recursive-agent-complete",
            "reason": "The recursive agent loop reported mission completion.",
        }
    elif status == "blocked":
        mission_state["autonomy_status"] = {
            "state": "recursive-agent-blocked",
            "reason": "The recursive agent loop exhausted bounded recovery or returned blocked.",
        }
    else:
        mission_state["autonomy_status"] = {
            "state": "recursive-agent-running",
            "reason": "The recursive agent loop is advancing the mission through fresh-context agent iterations.",
        }
    write_mission_state(mission_state_path, mission_state)
    _sync_outer_runtime_summary_from_recursive_agent(mission_state)
    return mission_state


def _write_findings(mission_root: Path, iteration_number: int, role: str, findings: list[str]) -> Path | None:
    if not findings:
        return None
    findings_root = mission_root / "findings"
    findings_root.mkdir(parents=True, exist_ok=True)
    path = findings_root / f"recursive-loop-{iteration_number:02d}-{role}.md"
    lines = [f"# Recursive loop findings ({role})", ""]
    lines.extend(f"- {item}" for item in findings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_recursive_agent_loop(config_path: Path) -> dict[str, Any]:
    config = _load_yaml(Path(config_path).resolve())
    policy_path = Path(config.get("policy_path") or DEFAULT_POLICY_PATH).expanduser().resolve()
    policy = _load_yaml(policy_path)
    mission_state_path = Path(config["mission_state"]).expanduser().resolve()
    mission_state = load_mission_state(mission_state_path)
    mission_root = mission_state_path.parent
    ledger_path = mission_root / "ledger.jsonl"

    loop_name = str(config.get("loop_name", "recursive-agent-loop"))
    runtime_root = _runtime_root(
        mission_state_path,
        str(policy.get("artifact_dir_name", "recursive_agent_runtime")),
        loop_name,
    )
    runtime_root.mkdir(parents=True, exist_ok=True)
    state = _loop_state(runtime_root, str(mission_state["mission_id"]), loop_name)
    _save_loop_state(runtime_root, state)

    max_iterations = int(config.get("max_iterations", policy.get("max_iterations", 8)))
    state["max_iterations"] = max_iterations
    state["iterations_remaining"] = max(0, max_iterations - int(state.get("iterations_completed", 0)))
    max_consecutive_failures = int(config.get("max_consecutive_failures", policy.get("max_consecutive_failures", 2)))
    recent_ledger_limit = int(config.get("recent_ledger_limit", policy.get("recent_ledger_limit", 8)))
    recent_memory_limit = int(config.get("recent_memory_limit", policy.get("recent_memory_limit", 6)))
    agent_cfg = config.get("agent", {})
    if not isinstance(agent_cfg, dict) or not isinstance(agent_cfg.get("command"), list) or not agent_cfg["command"]:
        raise ValueError("recursive agent runtime requires agent.command to be a non-empty list")
    _save_loop_state(runtime_root, state)

    iterations: list[dict[str, Any]] = []
    status = "running"
    latest_outcome: dict[str, Any] | None = None
    current_action: dict[str, Any] | None = None

    for _ in range(max_iterations):
        mission_state = load_mission_state(mission_state_path)
        current_phase = str(mission_state.get("current_phase") or "")
        next_actions = mission_state.get("next_actions", {})
        actions = next_actions.get("actions") if isinstance(next_actions, dict) else None
        cursor = int(state.get("action_cursor", 0))
        chosen: dict[str, Any] | None = None
        proposed_cursor = cursor
        if isinstance(actions, list):
            proposed_cursor, chosen_candidate = _select_next_action(actions, cursor)
            if isinstance(chosen_candidate, dict):
                chosen = chosen_candidate
        pending_action = state.get("pending_action")
        selected_action_index: int | None = None
        used_initial_task = False
        action: dict[str, Any] | None = None
        if isinstance(pending_action, dict):
            candidate_action = _normalize_action(
                pending_action,
                default_role=str(config.get("default_role", "planner")),
                default_phase=current_phase,
                source=str(pending_action.get("source") or "pending-action"),
            )
            candidate_action = _canonicalize_action_role(candidate_action, mission_state)
            pending_phase = _optional_string(candidate_action.get("phase"))
            chosen_phase = _optional_string((chosen or {}).get("phase")) or current_phase or None
            chosen_action_id = _optional_string((chosen or {}).get("action_id"))
            pending_action_id = _optional_string(candidate_action.get("action_id"))
            mission_selected_current_phase = bool(chosen) and chosen_phase == current_phase
            should_prefer_mission_action = mission_selected_current_phase and (
                str(candidate_action.get("source") or "") != "mission-next-action"
                or pending_action_id != chosen_action_id
            )
            if (pending_phase and current_phase and pending_phase != current_phase) or should_prefer_mission_action:
                state["pending_action"] = None
                state["consecutive_failures"] = 0
                pending_action = None
            else:
                action = candidate_action
        if action is None:
            if isinstance(actions, list):
                state["action_cursor"] = proposed_cursor
                if isinstance(chosen, dict):
                    selected_action_index = proposed_cursor
                    action = _normalize_action(
                        chosen,
                        default_role=str(config.get("default_role", "planner")),
                        default_phase=current_phase,
                        source="mission-next-action",
                        mission_action_index=selected_action_index,
                    )
                    action = _canonicalize_action_role(action, mission_state)
                else:
                    chosen = None
            else:
                chosen = None
            if chosen is None:
                initial_task = str(config.get("initial_task") or mission_state.get("objective") or "").strip()
                if initial_task and not bool(state.get("initial_task_consumed", False)):
                    used_initial_task = True
                    action = _normalize_action(
                        {
                            "role": str(config.get("default_role", "planner")),
                            "task": initial_task,
                            "artifacts": [],
                            "phase": current_phase,
                        },
                        default_role=str(config.get("default_role", "planner")),
                        default_phase=current_phase,
                        source="initial-task",
                    )
                    action = _canonicalize_action_role(action, mission_state)
                else:
                    status = "blocked"
                    current_action = None
                    latest_outcome = _normalized_result_outcome(
                        {
                            "status": "blocked",
                            "summary": "No further mission next action or pending agent handoff is available.",
                        },
                        {
                            "role": str(config.get("default_role", "planner")),
                            "task": "",
                            "artifacts": [],
                            "action_id": None,
                            "loop_action_id": None,
                            "kind": None,
                            "phase": str(mission_state.get("current_phase") or ""),
                            "branch_id": None,
                            "decision_id": None,
                            "notes": [],
                            "source": "runtime",
                            "mission_action_index": None,
                        },
                    )
                    state["status"] = status
                    state["pending_action"] = None
                    _save_loop_state(runtime_root, state)
                    mission_state = _apply_result_to_mission(
                        mission_state_path,
                        mission_state,
                        runtime_root=runtime_root,
                        loop_name=loop_name,
                        state=state,
                        current_action=current_action,
                        latest_outcome=latest_outcome,
                        status=status,
                    )
                    break

        iteration_number = int(state["iterations_completed"]) + 1
        remaining_after_this_iteration = max_iterations - iteration_number
        action["loop_action_id"] = action.get("loop_action_id") or _loop_action_id(loop_name, iteration_number, action["role"])
        current_action = dict(action)
        if used_initial_task:
            state["initial_task_consumed"] = True
        sandbox = build_sandbox_spec(
            str(mission_state["mission_id"]),
            action["role"],
            Path(mission_state["target_repo"]).expanduser(),
            reset=True,
        )
        iteration_root = runtime_root / f"iteration-{iteration_number:02d}-{action['role']}"
        iteration_root.mkdir(parents=True, exist_ok=True)
        prompt_path = iteration_root / "prompt.md"
        result_json_path = iteration_root / "agent_result.json"
        log_path = iteration_root / "agent.log"
        summary_json_path = iteration_root / "summary.json"
        summary_markdown_path = iteration_root / "summary.md"

        recent_ledger = _recent_entries(_load_jsonl(ledger_path), recent_ledger_limit)
        recent_memory = _recent_entries(_load_jsonl(_memory_path(runtime_root)), recent_memory_limit)
        outer_loop = mission_state.get("outer_loop", {}) if isinstance(mission_state.get("outer_loop"), dict) else {}
        decision_log_path = Path(outer_loop["decision_log_path"]) if isinstance(outer_loop.get("decision_log_path"), str) else None
        branch_log_path = Path(outer_loop["branch_log_path"]) if isinstance(outer_loop.get("branch_log_path"), str) else None
        branch_record = _latest_matching_record(branch_log_path, "branch_id", action.get("branch_id"))
        decision_record = _latest_matching_record(decision_log_path, "decision_id", action.get("decision_id"))
        prompt_text = _render_prompt(
            mission_state=mission_state,
            action=action,
            sandbox=sandbox,
            recent_ledger=recent_ledger,
            recent_memory=recent_memory,
            branch_record=branch_record,
            decision_record=decision_record,
            result_json_path=result_json_path,
            iteration_number=iteration_number,
            max_iterations=max_iterations,
        )
        prompt_path.write_text(prompt_text, encoding="utf-8")
        if remaining_after_this_iteration == 0 and (
            _optional_string(action.get("phase")) == "execution" or _optional_string(action.get("role")) == "execution-operator"
        ):
            print(
                f"[deeploop] WARNING: routing execution action '{action.get('action_id') or action.get('loop_action_id')}' "
                f"into final recursive iteration {iteration_number}/{max_iterations}. "
                "Consider yielding to the outer loop or increasing max_iterations.",
                file=sys.stderr,
            )

        context = {
            "prompt_path": str(prompt_path),
            "result_json_path": str(result_json_path),
            "sandbox_root": sandbox["sandbox_root"],
            "inputs_dir": sandbox["inputs_dir"],
            "outputs_dir": sandbox["outputs_dir"],
            "mission_state_path": str(mission_state_path),
            "target_repo": mission_state["target_repo"],
            "role": action["role"],
            "iteration": str(iteration_number),
            "loop_action_id": action["loop_action_id"],
            "mission_action_id": action.get("action_id") or "",
            "branch_id": action.get("branch_id") or "",
            "action_kind": action.get("kind") or "",
            "action_phase": action.get("phase") or "",
            "decision_id": action.get("decision_id") or "",
        }
        base_command = [str(token).format(**context) for token in agent_cfg["command"]]
        full_command = _build_command(base_command, _resolved_env_name(agent_cfg.get("env_name")))

        environment = dict(os.environ)
        environment.update(
            {
                "DEEPLOOP_AGENT_ITERATION": str(iteration_number),
                "DEEPLOOP_AGENT_ROLE": action["role"],
                "DEEPLOOP_MISSION_ID": str(mission_state["mission_id"]),
                "DEEPLOOP_MISSION_STATE_PATH": str(mission_state_path),
                "DEEPLOOP_SANDBOX_ROOT": sandbox["sandbox_root"],
                "DEEPLOOP_SANDBOX_INPUTS_DIR": sandbox["inputs_dir"],
                "DEEPLOOP_SANDBOX_OUTPUTS_DIR": sandbox["outputs_dir"],
                "DEEPLOOP_RESULT_JSON_PATH": str(result_json_path),
                "DEEPLOOP_RULE_SOURCES": os.pathsep.join(sandbox["rule_sources"]),
                "DEEPLOOP_LOOP_NAME": loop_name,
                "DEEPLOOP_LOOP_ACTION_ID": action["loop_action_id"],
                "DEEPLOOP_MISSION_ACTION_PHASE": action.get("phase") or "",
                "DEEPLOOP_MISSION_ACTION_KIND": action.get("kind") or "",
                "DEEPLOOP_MISSION_ACTION_ID": action.get("action_id") or "",
                "DEEPLOOP_MISSION_BRANCH_ID": action.get("branch_id") or "",
                "DEEPLOOP_MISSION_DECISION_ID": action.get("decision_id") or "",
            }
        )

        started_at = now_utc()
        timeout_seconds = _timeout_seconds_for_action(config=config, policy=policy, action=action)
        try:
            completed = subprocess.run(
                full_command,
                cwd=Path(str(agent_cfg.get("cwd", mission_state["target_repo"]))).expanduser(),
                input=prompt_text if bool(agent_cfg.get("stdin_prompt", False)) else None,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                env=environment,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + f"\nTimeoutExpired after {timeout_seconds} seconds\n"
            returncode = 124
        completed_at = now_utc()
        log_path.write_text(stdout + stderr, encoding="utf-8")

        result_payload: dict[str, Any] | None = None
        result_errors: list[str] = []
        if result_json_path.exists():
            try:
                result_payload = _load_json(result_json_path)
                result_errors = _validate_result(result_payload)
            except (json.JSONDecodeError, ValueError) as exc:
                result_errors = [f"invalid result json: {type(exc).__name__}: {exc}"]
        elif policy.get("completion_token") and str(policy["completion_token"]) in stdout:
            result_payload = {"status": "complete", "summary": "Completion token detected in agent output."}
        else:
            result_errors = ["agent did not produce result_json_path"]

        iteration_status = "failed"
        if returncode == 0 and result_payload is not None and not result_errors:
            iteration_status = str(result_payload["status"])
        else:
            if result_payload is None:
                result_payload = {
                    "status": "failed",
                    "summary": "Agent process failed before producing a valid result payload.",
                }
        if result_payload is not None and not result_errors:
            normalized_outcome = _normalized_result_outcome(result_payload, action, mission_state=mission_state)
        elif result_payload is not None:
            normalized_outcome = _normalized_result_outcome(
                {
                    "status": "failed",
                    "summary": str(result_payload.get("summary") or "Agent returned an invalid result payload."),
                },
                action,
                mission_state=mission_state,
            )
        else:
            normalized_outcome = None

        summary = {
            "schema_version": 1,
            "iteration": iteration_number,
            "role": action["role"],
            "loop_action_id": action["loop_action_id"],
            "mission_action_id": action.get("action_id"),
            "action_kind": action.get("kind"),
            "phase": action.get("phase"),
            "branch_id": action.get("branch_id"),
            "task": action["task"],
            "status": iteration_status,
            "started_at": started_at,
            "completed_at": completed_at,
            "returncode": returncode,
            "prompt_path": str(prompt_path),
            "result_json_path": str(result_json_path),
            "log_path": str(log_path),
            "command": full_command,
            "result": result_payload,
            "normalized_result": normalized_outcome,
            "result_errors": result_errors,
        }
        _write_json(summary_json_path, summary)
        _write_markdown(summary_markdown_path, _iteration_summary_markdown(summary))

        findings_path = _write_findings(
            mission_root,
            iteration_number,
            action["role"],
            normalized_outcome.get("findings", []) if normalized_outcome is not None else [],
        )
        memory_entry = {
            "created_at": now_utc(),
            "iteration": iteration_number,
            "role": action["role"],
            "task": action["task"],
            "status": iteration_status,
            "loop_action_id": action["loop_action_id"],
            "mission_action_id": action.get("action_id"),
            "action_kind": action.get("kind"),
            "phase": action.get("phase"),
            "branch_id": action.get("branch_id"),
            "summary": normalized_outcome.get("summary") if normalized_outcome is not None else "unknown",
            "continuation": normalized_outcome.get("continuation") if normalized_outcome is not None else None,
            "action_result": normalized_outcome.get("action_result") if normalized_outcome is not None else None,
            "phase_control": normalized_outcome.get("phase_control") if normalized_outcome is not None else None,
            "prompt_path": str(prompt_path),
            "result_json_path": str(result_json_path),
            "log_path": str(log_path),
            "produced_artifacts": normalized_outcome.get("produced_artifacts", []) if normalized_outcome is not None else [],
            "findings_path": str(findings_path) if findings_path is not None else None,
        }
        _append_jsonl(_memory_path(runtime_root), memory_entry)

        append_jsonl(
            ledger_path,
            make_ledger_entry(
                kind="recursive-agent-iteration",
                mission_id=str(mission_state["mission_id"]),
                summary=f"Recursive loop iteration {iteration_number} ({action['role']}) returned {iteration_status}",
                status=iteration_status,
                related_paths=[str(prompt_path), str(log_path), str(summary_json_path)]
                + ([str(findings_path)] if findings_path is not None else []),
                metadata={
                    "task": action["task"],
                    "loop_action_id": action["loop_action_id"],
                    "mission_action_id": action.get("action_id"),
                    "branch_id": action.get("branch_id"),
                    "continuation_role": (
                        (normalized_outcome.get("continuation") or {}).get("role")
                        if normalized_outcome is not None
                        else None
                    ),
                    "continuation_task": (
                        (normalized_outcome.get("continuation") or {}).get("task")
                        if normalized_outcome is not None
                        else None
                    ),
                    "next_phase": (
                        (normalized_outcome.get("phase_control") or {}).get("next_phase")
                        if normalized_outcome is not None
                        else None
                    ),
                },
            ),
        )

        remaining_iterations = max_iterations - iteration_number
        state["iterations_completed"] = iteration_number
        state["iterations_remaining"] = remaining_iterations
        state["latest_iteration_path"] = str(iteration_root)
        state["latest_result_path"] = str(summary_json_path)
        latest_outcome = normalized_outcome
        if remaining_iterations <= max(1, round(max_iterations * 0.20)) and remaining_iterations > 0:
            print(
                f"[deeploop] WARNING: iteration budget nearly exhausted for loop '{loop_name}': "
                f"{iteration_number}/{max_iterations} iterations consumed, {remaining_iterations} remaining. "
                "Consider increasing max_iterations in your recursive agent config.",
                file=sys.stderr,
            )
        iterations.append(
            {
                "iteration": iteration_number,
                "role": action["role"],
                "status": iteration_status,
                "loop_action_id": action["loop_action_id"],
                "mission_action_id": action.get("action_id"),
                "branch_id": action.get("branch_id"),
                "phase": action.get("phase"),
                "summary_json_path": str(summary_json_path),
            }
        )

        if iteration_status in {"failed", "blocked"}:
            state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
            state["pending_action"] = dict(action)
            if state["consecutive_failures"] >= max_consecutive_failures or iteration_status == "blocked":
                status = "blocked"
                state["status"] = status
                _save_loop_state(runtime_root, state)
                mission_state = _apply_result_to_mission(
                    mission_state_path,
                    mission_state,
                    runtime_root=runtime_root,
                    loop_name=loop_name,
                    state=state,
                    current_action=current_action,
                    latest_outcome=latest_outcome,
                    status=status,
                )
                break
        else:
            state["consecutive_failures"] = 0
            continuation = latest_outcome.get("continuation") if latest_outcome is not None else None
            if _should_yield_to_outer_runtime(latest_outcome, action=action):
                state["pending_action"] = None
                status = "max-iterations"
                state["status"] = status
                _save_loop_state(runtime_root, state)
                mission_state = _apply_result_to_mission(
                    mission_state_path,
                    mission_state,
                    runtime_root=runtime_root,
                    loop_name=loop_name,
                    state=state,
                    current_action=current_action,
                    latest_outcome=latest_outcome,
                    status="running",
                )
                break
            if _should_yield_before_execution(latest_outcome, action=action, remaining_iterations=remaining_iterations):
                state["pending_action"] = dict(continuation)
                status = "max-iterations"
                state["status"] = status
                _save_loop_state(runtime_root, state)
                print(
                    f"[deeploop] WARNING: execution handoff reached with only "
                    f"{remaining_iterations}/{max_iterations} recursive iterations remaining; "
                    "yielding to the outer loop before starting execution.",
                    file=sys.stderr,
                )
                mission_state = _apply_result_to_mission(
                    mission_state_path,
                    mission_state,
                    runtime_root=runtime_root,
                    loop_name=loop_name,
                    state=state,
                    current_action=current_action,
                    latest_outcome=latest_outcome,
                    status="running",
                )
                break
            if latest_outcome is not None and continuation is not None:
                state["pending_action"] = dict(continuation)
            else:
                state["pending_action"] = None
                if selected_action_index is not None:
                    state["action_cursor"] = selected_action_index + 1

            if iteration_status == "complete":
                status = "completed"
                state["status"] = status
                _save_loop_state(runtime_root, state)
                mission_state = _apply_result_to_mission(
                    mission_state_path,
                    mission_state,
                    runtime_root=runtime_root,
                    loop_name=loop_name,
                    state=state,
                    current_action=current_action,
                    latest_outcome=latest_outcome,
                    status=status,
                )
                break

        state["status"] = "running"
        _save_loop_state(runtime_root, state)
        mission_state = _apply_result_to_mission(
            mission_state_path,
            mission_state,
            runtime_root=runtime_root,
            loop_name=loop_name,
            state=state,
            current_action=current_action,
            latest_outcome=latest_outcome,
            status="running",
        )
    else:
        status = "max-iterations"
        state["status"] = status
        _save_loop_state(runtime_root, state)
        mission_state = _apply_result_to_mission(
            mission_state_path,
            mission_state,
            runtime_root=runtime_root,
            loop_name=loop_name,
            state=state,
            current_action=current_action,
            latest_outcome=latest_outcome,
            status="running",
        )

    report = {
        "schema_version": 1,
        "generated_at": now_utc(),
        "mission_id": mission_state["mission_id"],
        "loop_name": loop_name,
        "status": status,
        "max_iterations": max_iterations,
        "iterations_completed": state["iterations_completed"],
        "iterations_remaining": max(0, max_iterations - int(state["iterations_completed"])),
        "consecutive_failures": state["consecutive_failures"],
        "runtime_root": str(runtime_root),
        "memory_path": str(_memory_path(runtime_root)),
        "state_path": str(_state_path(runtime_root)),
        "latest_iteration_path": state.get("latest_iteration_path"),
        "latest_result_path": state.get("latest_result_path"),
        "latest_outcome": _effective_outcome(latest_outcome, status),
        "iterations": iterations,
    }
    report_json_path = runtime_root / "loop_report.json"
    report_markdown_path = runtime_root / "loop_report.md"
    _write_json(report_json_path, report)
    _write_markdown(report_markdown_path, _loop_report_markdown(report))
    append_jsonl(
        ledger_path,
        make_ledger_entry(
            kind="recursive-agent-loop",
            mission_id=str(mission_state["mission_id"]),
            summary=f"Recursive agent loop {loop_name} finished with status {status}",
            status=status,
            related_paths=[str(report_json_path), str(report_markdown_path)],
            metadata={"iterations_completed": state["iterations_completed"], "consecutive_failures": state["consecutive_failures"]},
        ),
    )
    return {
        "status": status,
        "max_iterations": max_iterations,
        "iterations_completed": state["iterations_completed"],
        "iterations_remaining": max(0, max_iterations - int(state["iterations_completed"])),
        "consecutive_failures": state["consecutive_failures"],
        "runtime_root": runtime_root,
        "memory_path": _memory_path(runtime_root),
        "state_path": _state_path(runtime_root),
        "report_json_path": report_json_path,
        "report_markdown_path": report_markdown_path,
        "latest_iteration_path": Path(state["latest_iteration_path"]) if state.get("latest_iteration_path") else None,
        "latest_result_path": Path(state["latest_result_path"]) if state.get("latest_result_path") else None,
        "latest_outcome": _effective_outcome(latest_outcome, status),
    }


_BUDGET_WARN_THRESHOLD = 0.80


def analyze_budget(
    *,
    config_path: Path | None = None,
    mission_state_path: Path | None = None,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """Predict whether the pending action queue will exceed the configured iteration budget.

    Returns a structured report with fields:
      - max_iterations: the effective cap
      - pending_actions: count of actions waiting in the mission state
      - iterations_completed: iterations already consumed in the current loop state (0 if loop not started)
      - iterations_remaining: max_iterations - iterations_completed
      - utilization_ratio: (pending_actions + iterations_completed) / max_iterations
      - status: "ok" | "warning" | "over-budget"
      - warnings: list of human-readable warning strings
    """
    resolved_policy_path = Path(policy_path or DEFAULT_POLICY_PATH).expanduser().resolve()
    policy: dict[str, Any] = {}
    if resolved_policy_path.exists():
        policy = _load_yaml(resolved_policy_path)

    config: dict[str, Any] = {}
    if config_path is not None:
        config = _load_yaml(Path(config_path).expanduser().resolve())
        if policy_path is None:
            raw_policy = config.get("policy_path")
            if raw_policy:
                alt_policy = Path(raw_policy).expanduser().resolve()
                if alt_policy.exists():
                    policy = _load_yaml(alt_policy)

    max_iterations = int(config.get("max_iterations", policy.get("max_iterations", 8)))

    pending_actions = 0
    iterations_completed = 0
    mission_state: dict[str, Any] = {}

    if mission_state_path is not None:
        resolved_ms = Path(mission_state_path).expanduser().resolve()
        if resolved_ms.exists():
            mission_state = load_mission_state(resolved_ms)
            next_actions = mission_state.get("next_actions")
            if isinstance(next_actions, dict):
                actions_list = next_actions.get("actions")
                if isinstance(actions_list, list):
                    pending_actions = sum(
                        1
                        for a in actions_list
                        if isinstance(a, dict) and str(a.get("status", "pending")) not in {"done", "completed", "skipped"}
                    )

        if config_path is not None:
            loop_name = str(config.get("loop_name", "recursive-agent-loop"))
            artifact_dir_name = str(policy.get("artifact_dir_name", "recursive_agent_runtime"))
            resolved_ms = Path(mission_state_path).expanduser().resolve()
            runtime_root = _runtime_root(resolved_ms, artifact_dir_name, loop_name)
            state_path = _state_path(runtime_root)
            if state_path.exists():
                loop_state = _load_json(state_path)
                iterations_completed = int(loop_state.get("iterations_completed", 0))

    iterations_remaining = max(0, max_iterations - iterations_completed)
    projected_total = iterations_completed + pending_actions
    utilization_ratio = round(projected_total / max_iterations, 4) if max_iterations > 0 else 1.0

    warnings: list[str] = []
    status = "ok"

    if projected_total > max_iterations:
        status = "over-budget"
        warnings.append(
            f"Projected total ({projected_total}) exceeds max_iterations ({max_iterations}). "
            "The loop will halt mid-queue. Increase max_iterations in your recursive agent config."
        )
    elif utilization_ratio >= _BUDGET_WARN_THRESHOLD:
        status = "warning"
        warnings.append(
            f"Projected utilization is {utilization_ratio:.0%} of max_iterations ({max_iterations}). "
            "Queue size is dangerously close to the iteration ceiling. "
            "Consider increasing max_iterations before submitting this queue."
        )

    return {
        "max_iterations": max_iterations,
        "pending_actions": pending_actions,
        "iterations_completed": iterations_completed,
        "iterations_remaining": iterations_remaining,
        "projected_total": projected_total,
        "utilization_ratio": utilization_ratio,
        "status": status,
        "warnings": warnings,
    }
