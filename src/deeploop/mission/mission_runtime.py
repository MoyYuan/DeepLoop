from __future__ import annotations

from contextlib import contextmanager
import importlib
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

from deeploop.autonomy.mission_contract_snapshot import load_mission_contract_snapshot_for_state, resolve_phase_contract_for_state
from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.paths import REPO_ROOT
from deeploop.core.structured_io import load_json_object, load_jsonl_objects, write_json_object, write_markdown
from deeploop.mission._constants import (
    RUNTIME_HISTORY_FILE as _RUNTIME_HISTORY_FILE,
    RUNTIME_STATE_FILE as _RUNTIME_STATE_FILE,
    RUNTIME_SUMMARY_JSON_FILE as _RUNTIME_SUMMARY_JSON_FILE,
    RUNTIME_SUMMARY_MD_FILE as _RUNTIME_SUMMARY_MD_FILE,
)
from deeploop.autonomy.mission_autonomy import build_outer_loop_contract, enrich_outer_loop_contract, resolve_phase_contract
from deeploop.autonomy.operator_inbox import (
    append_operator_request,
    clear_current_operator_request,
    ensure_operator_inbox_contract,
    load_current_operator_request,
)
from deeploop.autonomy.operating_modes import DEFAULT_OPERATING_MODE
from deeploop.mission.mission_decision_engine import (
    MissionDecisionDirective,
    MissionEvidence,
    MissionPlannedAction,
    decide_next_mission_action,
)
from deeploop.mission._runtime_contract import _append_contract_record, _outer_loop_contract
from deeploop.mission._runtime_persistence import (
    _load_runtime_state,
    _record_history as _record_history_impl,
    _record_ledger as _record_ledger_impl,
    _runtime_history_path,
    _runtime_root,
    _runtime_state_path,
    _runtime_summary_json_path,
    _runtime_summary_md_path,
    _write_state as _write_state_impl,
)
from deeploop.mission.mission_memory import (
    append_mission_experiment_entry,
    ensure_mission_memory_contract,
    sync_mission_memory,
)
from deeploop.mission.mission_state import load_mission_state, write_mission_state
from deeploop.mission.mission_monitor import build_mission_snapshot
from deeploop.platform.contracts import sync_platform_expansion_bundle
from deeploop.project_contract import resolve_runtime_provider
from deeploop.research.indexed_memory import (
    ensure_research_memory_contract,
    record_research_memory_entry,
)
from deeploop.runtime.mission_executor_registry import (
    AdaptationTrainingExecutorAction,
    EvaluationComparisonExecutorAction,
    MissionExecutionResult,
    MissionExecutorAction,
    MissionExecutorId,
    RecursiveAgentExecutorAction,
    ReportSynthesisExecutorAction,
    SelfHealingQueueExecutorAction,
    StageKernelExecutorAction,
    run_mission_action,
)
from deeploop.runtime import mission_executor_registry as _mission_executor_registry

DEFAULT_RUNTIME_DIR_NAME = "mission_outer_runtime"
_TERMINAL_RUNTIME_STATUSES = {"completed", "blocked", "failed", "max-iterations"}
_INVOKE_PROVIDER_PROMPT_SCRIPT = REPO_ROOT / "scripts" / "runtime" / "invoke_provider_prompt.py"


def _load_json(path: Path) -> dict[str, Any]:
    return load_json_object(path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return load_jsonl_objects(path, missing_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json_object(path, payload)


def _write_markdown(path: Path, lines: list[str]) -> None:
    write_markdown(path, lines)


def _jsonify(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonify(item) for item in value]
    return value


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _normalize_strings(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        value = raw.strip()
        return [value] if value else []
    if isinstance(raw, list | tuple):
        values: list[str] = []
        for item in raw:
            values.extend(_normalize_strings(item))
        return values
    return [str(raw)]


def _branch_records_from_log(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    latest_by_branch: dict[str, dict[str, Any]] = {}
    for record in _load_jsonl(path):
        branch_id = record.get("branch_id")
        if isinstance(branch_id, str) and branch_id:
            latest_by_branch[branch_id] = record
    return list(latest_by_branch.values())


def gather_mission_evidence(
    mission_state_path: Path,
    mission_state: Mapping[str, Any] | None = None,
) -> MissionEvidence:
    resolved_state_path = mission_state_path.expanduser().resolve()
    state = dict(mission_state or load_mission_state(resolved_state_path))
    outer_loop = state.get("outer_loop") if isinstance(state.get("outer_loop"), dict) else {}
    branch_log_path = (
        Path(outer_loop["branch_log_path"]).expanduser().resolve()
        if isinstance(outer_loop.get("branch_log_path"), str)
        else None
    )
    produced_outputs = _normalize_strings(state.get("produced_outputs") or state.get("phase_outputs"))
    phase_outputs = state.get("phase_outputs_by_phase")
    current_phase = str(state.get("current_phase") or "")
    if not produced_outputs and isinstance(phase_outputs, dict):
        produced_outputs = _normalize_strings(phase_outputs.get(current_phase))
    return MissionEvidence.from_mapping(
        {
            "produced_outputs": produced_outputs,
            "blockers": _normalize_strings(state.get("blocked_reasons")),
            "recent_failures": _normalize_strings(state.get("recent_failures")),
            "failure_count": int(state.get("failure_count", 0) or 0),
            "branch_records": _branch_records_from_log(branch_log_path) or state.get("branch_records") or (),
        }
    )


def _phase_transitions(phase: str, *, mission_state: Mapping[str, Any] | None = None) -> list[str]:
    return _normalize_strings(resolve_phase_contract_for_state(phase, mission_state=mission_state).get("transitions"))


def _next_phase_for(
    current_phase: str,
    *,
    mission_state: Mapping[str, Any] | None = None,
    fallback: str | None = None,
) -> str:
    transitions = _phase_transitions(current_phase, mission_state=mission_state)
    if isinstance(fallback, str) and fallback in transitions:
        return fallback
    if transitions:
        return transitions[0]
    return current_phase


def _append_unique(values: list[str], item: str) -> None:
    if item and item not in values:
        values.append(item)


def _merge_outputs(mission_state: dict[str, Any], *, phase: str, outputs: list[str]) -> None:
    if not outputs:
        return
    phase_outputs = mission_state.setdefault("phase_outputs_by_phase", {})
    existing_phase_outputs = _normalize_strings(phase_outputs.get(phase)) if isinstance(phase_outputs, dict) else []
    for output in outputs:
        if output not in existing_phase_outputs:
            existing_phase_outputs.append(output)
    mission_state.setdefault("phase_outputs_by_phase", {})[phase] = existing_phase_outputs
    if phase == str(mission_state.get("current_phase") or ""):
        current_outputs = _normalize_strings(mission_state.get("produced_outputs") or mission_state.get("phase_outputs"))
        for output in outputs:
            if output not in current_outputs:
                current_outputs.append(output)
        mission_state["produced_outputs"] = current_outputs
        mission_state["phase_outputs"] = current_outputs


def _snapshot_phase_outputs(mission_state: dict[str, Any], phase: str) -> None:
    outputs = _normalize_strings(mission_state.get("produced_outputs") or mission_state.get("phase_outputs"))
    if outputs:
        _merge_outputs(mission_state, phase=phase, outputs=outputs)


def _apply_phase_change(
    mission_state: dict[str, Any],
    *,
    from_phase: str,
    to_phase: str,
    next_phase: str | None,
) -> None:
    resolved_to_phase = to_phase or from_phase
    prior_history = list(mission_state.get("phase_history") or [])
    if from_phase and from_phase != resolved_to_phase:
        _snapshot_phase_outputs(mission_state, from_phase)
        completed = list(mission_state.get("completed_phases") or [])
        _append_unique(completed, from_phase)
        mission_state["completed_phases"] = completed
    history = list(mission_state.get("phase_history") or [])
    if not history:
        history.append(resolved_to_phase)
    elif history[-1] != resolved_to_phase:
        history.append(resolved_to_phase)
    mission_state["phase_history"] = history
    preserved_outputs = _normalize_strings(mission_state.get("produced_outputs") or mission_state.get("phase_outputs"))
    mission_state["current_phase"] = resolved_to_phase
    mission_state["next_phase"] = _next_phase_for(resolved_to_phase, mission_state=mission_state, fallback=next_phase)
    phase_outputs = mission_state.get("phase_outputs_by_phase") if isinstance(mission_state.get("phase_outputs_by_phase"), dict) else {}
    revisiting_phase = from_phase != resolved_to_phase and resolved_to_phase in prior_history
    if from_phase == resolved_to_phase:
        current_outputs = preserved_outputs
    elif revisiting_phase:
        phase_outputs = dict(phase_outputs)
        phase_outputs[resolved_to_phase] = []
        mission_state["phase_outputs_by_phase"] = phase_outputs
        current_outputs = []
    else:
        current_outputs = _normalize_strings(phase_outputs.get(resolved_to_phase))
    mission_state["produced_outputs"] = current_outputs
    mission_state["phase_outputs"] = current_outputs


def _serialized_executor(executor_action: MissionExecutorAction) -> dict[str, Any]:
    if isinstance(executor_action, RecursiveAgentExecutorAction):
        return {"id": MissionExecutorId.RECURSIVE_AGENT.value, "params": {"config_path": str(executor_action.config_path)}}
    if isinstance(executor_action, SelfHealingQueueExecutorAction):
        return {
            "id": MissionExecutorId.SELF_HEALING_QUEUE.value,
            "params": {
                "config_path": str(executor_action.config_path),
                "policy_path": str(executor_action.policy_path) if executor_action.policy_path is not None else None,
            },
        }
    if isinstance(executor_action, StageKernelExecutorAction):
        return {
            "id": MissionExecutorId.STAGE_KERNEL.value,
            "params": {
                "stage_id": executor_action.stage_id,
                "config_path": str(executor_action.config_path),
                "adapter_spec": executor_action.adapter_spec,
                "pythonpath": [str(path) for path in executor_action.pythonpath],
            },
        }
    if isinstance(executor_action, AdaptationTrainingExecutorAction):
        return {
            "id": MissionExecutorId.ADAPTATION_TRAINING.value,
            "params": {
                "training_config_path": str(executor_action.training_config_path),
                "mission_state_path": (
                    str(executor_action.mission_state_path) if executor_action.mission_state_path is not None else None
                ),
            },
        }
    if isinstance(executor_action, EvaluationComparisonExecutorAction):
        return {
            "id": MissionExecutorId.EVALUATION_COMPARISON.value,
            "params": {
                "mission_state_path": (
                    str(executor_action.mission_state_path) if executor_action.mission_state_path is not None else None
                ),
                "manifest_paths": [str(path) for path in executor_action.manifest_paths],
                "run_roots": [str(path) for path in executor_action.run_roots],
                "contract_path": str(executor_action.contract_path),
                "artifact_name": executor_action.artifact_name,
            },
        }
    if isinstance(executor_action, ReportSynthesisExecutorAction):
        return {
            "id": MissionExecutorId.REPORT_SYNTHESIS.value,
            "params": {
                "mission_state_path": str(executor_action.mission_state_path),
                "contract_path": str(executor_action.contract_path),
                "output_root": str(executor_action.output_root) if executor_action.output_root is not None else None,
            },
        }
    raise TypeError(f"Unsupported mission executor action type: {type(executor_action).__name__}")


def _action_payload(action: MissionPlannedAction) -> dict[str, Any]:
    payload = action.to_payload()
    if action.executor_dispatch is not None:
        payload["executor"] = _serialized_executor(action.executor_dispatch.action)
    return payload


def _find_action(actions: list[dict[str, Any]], action_id: str) -> tuple[int, dict[str, Any] | None]:
    for index, action in enumerate(actions):
        if str(action.get("action_id") or "") == action_id:
            return index, action
    return -1, None


def _upsert_selected_action(
    mission_state: dict[str, Any],
    action: MissionPlannedAction,
    *,
    summary: str,
    force_status: str | None = None,
) -> dict[str, Any]:
    next_actions = mission_state.setdefault("next_actions", {})
    actions = next_actions.setdefault("actions", [])
    if not isinstance(actions, list):
        actions = []
        next_actions["actions"] = actions
    payload = _action_payload(action)
    if force_status is not None:
        payload["status"] = force_status
    index, existing = _find_action(actions, action.action_id)
    if existing is not None:
        merged = dict(existing)
        merged.update(payload)
        actions[index] = merged
        payload = merged
    else:
        actions.append(payload)
    next_actions["source_decision_id"] = action.decision_id
    next_actions["summary"] = summary
    return payload


def _update_action_result(
    mission_state: dict[str, Any],
    *,
    action_id: str,
    status: str,
    output_paths: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any] | None:
    next_actions = mission_state.get("next_actions")
    if not isinstance(next_actions, dict):
        return None
    actions = next_actions.get("actions")
    if not isinstance(actions, list):
        return None
    index, existing = _find_action(actions, action_id)
    if existing is None:
        return None
    updated = dict(existing)
    updated["status"] = status
    if output_paths:
        merged_output_paths = _normalize_strings(updated.get("output_paths"))
        for path in output_paths:
            if path not in merged_output_paths:
                merged_output_paths.append(path)
        updated["output_paths"] = merged_output_paths
    if notes:
        merged_notes = _normalize_strings(updated.get("notes"))
        for note in notes:
            if note not in merged_notes:
                merged_notes.append(note)
        updated["notes"] = merged_notes
    actions[index] = updated
    return updated


def _stage_managed_recovery_action(
    mission_state: dict[str, Any],
    *,
    source_action_payload: Mapping[str, Any] | None,
    recommended_action: str | None,
    reason: str,
    source: str,
    request_id: str | None = None,
    recommended_resume_action: str | None = None,
) -> dict[str, Any] | None:
    if str(mission_state.get("mode") or DEFAULT_OPERATING_MODE) != "managed":
        return None
    action = str(recommended_action or "").strip()
    if action not in {"retry", "reroute", "downscope"}:
        return None
    phase = str((source_action_payload or {}).get("phase") or mission_state.get("current_phase") or "").strip()
    source_action_id = str((source_action_payload or {}).get("action_id") or "").strip()
    if not phase:
        return None
    summary = (
        f"Managed mode staged `{action}` as the next bounded recovery step for `{phase}`"
        + (f" after {source} `{request_id}`." if request_id else f" after {source}.")
    )
    notes = [
        f"managed-auto-recovery={action}",
        f"recovery-source={source}",
    ]
    if reason.strip():
        notes.append(reason.strip())
    if recommended_resume_action and recommended_resume_action.strip():
        notes.append(f"resume-action={recommended_resume_action.strip()}")
    staged_action_id: str
    if action == "retry" and source_action_id:
        updated = _update_action_result(
            mission_state,
            action_id=source_action_id,
            status="pending",
            notes=notes,
        )
        if updated is None:
            return None
        staged_action_id = str(updated.get("action_id") or source_action_id)
    else:
        recovery_action = MissionPlannedAction(
            action_id=f"{source_action_id or phase}-{action}-managed-recovery",
            mission_id=str(mission_state.get("mission_id") or ""),
            kind="artifact-edit",
            role="planner",
            task=(
                f"{'Reroute' if action == 'reroute' else 'Downscope'} `{phase}` inside the current managed boundary. "
                f"{reason.strip()}"
            ).strip(),
            phase=phase,
            notes=tuple(notes),
            requires_operator_approval=False,
        )
        staged_action_payload = _upsert_selected_action(mission_state, recovery_action, summary=summary)
        staged_action_id = str(staged_action_payload.get("action_id") or recovery_action.action_id)
    record = {
        "status": "staged",
        "source": source,
        "request_id": request_id,
        "action": action,
        "phase": phase,
        "source_action_id": source_action_id or None,
        "staged_action_id": staged_action_id,
        "summary": summary,
        "reason": reason.strip() or None,
        "recommended_resume_action": recommended_resume_action.strip() if recommended_resume_action else None,
        "recorded_at": now_utc(),
    }
    mission_state["automatic_recovery"] = record
    return record


def _attach_managed_recovery_to_request(request: dict[str, Any], recovery_record: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(request)
    recommendation = dict(updated.get("recommendation")) if isinstance(updated.get("recommendation"), Mapping) else {}
    existing_summary = str(recommendation.get("summary") or "").strip()
    staged_summary = str(recovery_record.get("summary") or "").strip()
    if staged_summary:
        recommendation["summary"] = (
            f"{staged_summary} Resume to apply the staged step."
            + (f" {existing_summary}" if existing_summary else "")
        ).strip()
    updated["recommendation"] = recommendation
    explanation = str(updated.get("explanation") or "").strip()
    updated["explanation"] = (
        f"{explanation} Managed mode already staged `{recovery_record.get('action')}` as the next bounded recovery step "
        f"(`{recovery_record.get('staged_action_id')}`)."
    ).strip()
    return updated


def _payload_phase_control(payload: Mapping[str, Any]) -> dict[str, Any]:
    phase_control = payload.get("phase_control")
    if isinstance(phase_control, Mapping):
        return dict(phase_control)
    latest_outcome = payload.get("latest_outcome")
    if isinstance(latest_outcome, Mapping) and isinstance(latest_outcome.get("phase_control"), Mapping):
        return dict(latest_outcome["phase_control"])
    return {}


def _payload_state_updates(payload: Mapping[str, Any]) -> dict[str, Any]:
    updates = payload.get("mission_state_updates")
    if isinstance(updates, Mapping):
        return dict(updates)
    latest_outcome = payload.get("latest_outcome")
    if isinstance(latest_outcome, Mapping) and isinstance(latest_outcome.get("mission_state_updates"), Mapping):
        return dict(latest_outcome["mission_state_updates"])
    return {}


def _resolved_executor_current_phase(
    updated_state: Mapping[str, Any],
    *,
    phase_control: Mapping[str, Any],
    latest_outcome: Mapping[str, Any] | None,
) -> str:
    current_phase = str(updated_state.get("current_phase") or "").strip()
    raw_phase = str(phase_control.get("current_phase") or "").strip()
    next_phase = str(phase_control.get("next_phase") or "").strip()
    continuation_phase = ""
    if isinstance(latest_outcome, Mapping):
        continuation = latest_outcome.get("continuation")
        if isinstance(continuation, Mapping):
            continuation_phase = str(continuation.get("phase") or "").strip()
    if current_phase and raw_phase and current_phase != raw_phase:
        if next_phase and current_phase == next_phase:
            return current_phase
        if continuation_phase and current_phase == continuation_phase:
            return current_phase
    if raw_phase and next_phase and continuation_phase == next_phase and next_phase != raw_phase:
        return next_phase
    return raw_phase or current_phase


def _bootstrap_mapping(mission_state: Mapping[str, Any]) -> dict[str, Any]:
    bootstrap = mission_state.get("bootstrap")
    return dict(bootstrap) if isinstance(bootstrap, Mapping) else {}


def _bootstrap_followup_planner(bootstrap: Mapping[str, Any]) -> dict[str, Any]:
    planner = bootstrap.get("followup_planner")
    return dict(planner) if isinstance(planner, Mapping) else {}


def _provider_pythonpath(values: Any, *, base_dir: Path) -> tuple[Path, ...]:
    if values is None:
        return ()
    if not isinstance(values, list):
        raise ValueError("Follow-up planner pythonpath must be declared as a list.")
    resolved: list[Path] = []
    for item in values:
        text = str(item).strip()
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        else:
            path = path.resolve()
        resolved.append(path)
    return tuple(resolved)


@contextmanager
def _temporary_sys_path(paths: tuple[Path, ...]) -> Any:
    import sys

    inserted: list[str] = []
    try:
        for path in reversed(paths):
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)
                inserted.append(text)
        yield
    finally:
        for text in inserted:
            if text in sys.path:
                sys.path.remove(text)


def _resolve_followup_planner(
    mission_state: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
) -> tuple[str, dict[str, Any], tuple[Path, ...]]:
    planner_cfg = _bootstrap_followup_planner(bootstrap)
    project_contract = mission_state.get("project_contract")
    project_contract_payload = dict(project_contract) if isinstance(project_contract, Mapping) else {}
    repo_root = Path(str(project_contract_payload.get("repo_root") or mission_state.get("target_repo") or ".")).expanduser().resolve()
    provider_id = str(planner_cfg.get("provider") or "").strip()
    provider_cfg = resolve_runtime_provider(project_contract_payload, provider_id) if provider_id else None
    entrypoint = str(planner_cfg.get("entrypoint") or (provider_cfg or {}).get("entrypoint") or "").strip()
    params: dict[str, Any] = {}
    if isinstance((provider_cfg or {}).get("params"), dict):
        params.update((provider_cfg or {}).get("params", {}))
    if isinstance(planner_cfg.get("params"), dict):
        params.update(planner_cfg.get("params", {}))
    pythonpath = _provider_pythonpath((provider_cfg or {}).get("pythonpath"), base_dir=repo_root)
    planner_pythonpath = planner_cfg.get("pythonpath")
    if planner_pythonpath is not None:
        pythonpath = _provider_pythonpath(planner_pythonpath, base_dir=repo_root)
    return entrypoint, params, pythonpath


def _invoke_followup_planner(
    mission_state_path: Path,
    mission_state: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
) -> dict[str, Any]:
    entrypoint, params, pythonpath = _resolve_followup_planner(mission_state, bootstrap)
    if not entrypoint:
        raise ValueError("Mission bootstrap requested follow-up staging but no planner entrypoint was configured.")
    module_name, _, attribute_name = entrypoint.partition(":")
    if not module_name or not attribute_name:
        raise ValueError(f"Invalid follow-up planner entrypoint `{entrypoint}`.")
    with _temporary_sys_path(pythonpath):
        planner = getattr(importlib.import_module(module_name), attribute_name)
        result = planner(mission_state_path=mission_state_path, **params)
    if not isinstance(result, dict):
        raise ValueError(f"Follow-up planner `{entrypoint}` must return a dict payload.")
    return result


def _maybe_stage_bootstrap_followups(
    mission_state_path: Path,
    mission_state: dict[str, Any],
    *,
    result: MissionExecutionResult,
) -> tuple[dict[str, Any], str | None]:
    bootstrap = _bootstrap_mapping(mission_state)
    if not bootstrap:
        return mission_state, None
    planner_cfg = _bootstrap_followup_planner(bootstrap)
    if not planner_cfg:
        return mission_state, None
    if result.executor_id != MissionExecutorId.SELF_HEALING_QUEUE or str(result.status) != "completed":
        return mission_state, None
    if str(bootstrap.get("status") or "").strip() == "followup-staged":
        return mission_state, None
    write_mission_state(mission_state_path, mission_state)
    _invoke_followup_planner(mission_state_path, mission_state, bootstrap)
    reloaded_state = load_mission_state(mission_state_path)
    reloaded_bootstrap = _bootstrap_mapping(reloaded_state) or bootstrap
    reloaded_bootstrap["status"] = "followup-staged"
    reloaded_bootstrap["advanced_at"] = now_utc()
    reloaded_state["bootstrap"] = reloaded_bootstrap
    return reloaded_state, "Baseline queue completed; staged canonical follow-up runtime automatically."


def _mission_state_updates_from_executor(
    mission_state: dict[str, Any],
    *,
    action_payload: dict[str, Any],
    result: MissionExecutionResult,
) -> tuple[dict[str, Any], str, list[str]]:
    updated_state = mission_state
    output_paths = [str(path) for path in result.artifacts.values()]
    payload_updates = _payload_state_updates(result.payload)
    if payload_updates:
        updated_state = _deep_merge(updated_state, _jsonify(payload_updates))
    phase_control = _payload_phase_control(result.payload)
    latest_outcome = result.payload.get("latest_outcome")
    from_phase = str(updated_state.get("current_phase") or action_payload.get("phase") or "")
    to_phase = _resolved_executor_current_phase(
        updated_state,
        phase_control=phase_control,
        latest_outcome=latest_outcome if isinstance(latest_outcome, Mapping) else None,
    ) or from_phase
    if phase_control or to_phase != from_phase:
        _apply_phase_change(
            updated_state,
            from_phase=from_phase,
            to_phase=to_phase,
            next_phase=(
                str(phase_control.get("next_phase"))
                if phase_control.get("next_phase") is not None
                else str(updated_state.get("next_phase") or "")
            ),
        )
    next_phase_on_success = str(action_payload.get("next_phase_on_success") or "").strip()
    if next_phase_on_success and not str(phase_control.get("next_phase") or "").strip():
        updated_state["next_phase"] = next_phase_on_success
    produced_outputs = _normalize_strings(result.payload.get("produced_outputs"))
    if not produced_outputs:
        produced_outputs = _normalize_strings(action_payload.get("produces_outputs"))
    _merge_outputs(updated_state, phase=str(action_payload.get("phase") or updated_state.get("current_phase") or ""), outputs=produced_outputs)
    raw_status = str(result.status)
    action_status = "completed"
    if raw_status in {"blocked", "failed", "error"}:
        action_status = "blocked"
    elif raw_status in {"deferred", "cancelled"}:
        action_status = raw_status
    elif raw_status == "max-iterations":
        action_status = "deferred"
    output_paths.extend(_normalize_strings(result.payload.get("output_paths")))
    if isinstance(latest_outcome, Mapping):
        action_result = latest_outcome.get("action_result")
        if isinstance(action_result, Mapping):
            output_paths.extend(_normalize_strings(action_result.get("output_paths")))
    return updated_state, action_status, output_paths


def _should_continue_after_recursive_executor_failure(
    *,
    result: MissionExecutionResult,
    action_payload: Mapping[str, Any],
) -> bool:
    if result.executor_id != MissionExecutorId.RECURSIVE_AGENT:
        return False
    if str(result.status) not in {"blocked", "failed", "error"}:
        return False
    if bool(action_payload.get("requires_operator_approval")):
        return False
    action_kind = str(action_payload.get("kind") or "").strip()
    if not action_kind or action_kind == "operator-review":
        return False
    return True


def _record_history(runtime_root: Path, payload: dict[str, Any]) -> None:
    _record_history_impl(runtime_root, payload)


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
) -> None:
    _write_state_impl(
        mission_state_path,
        mission_state,
        runtime_state,
        contract=contract,
        evidence_snapshot=evidence_snapshot,
        decision_payload=decision_payload,
        branch_payload=branch_payload,
        action_payload=action_payload,
        executor_payload=executor_payload,
        contract_resolver=_outer_loop_contract,
        sync_operator_inbox=_sync_operator_inbox,
    )


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
) -> None:
    _record_ledger_impl(
        mission_state_path,
        mission_state=mission_state,
        runtime_root=runtime_root,
        contract=contract,
        kind=kind,
        status=status,
        summary=summary,
        metadata=metadata,
        jsonify=_jsonify,
    )


def _record_selected_outcome(
    mission_state_path: Path,
    *,
    mission_state: dict[str, Any],
    runtime_root: Path,
    contract: dict[str, Any],
    outcome_payloads: dict[str, dict[str, Any] | None],
) -> None:
    decision_payload = outcome_payloads["decision"]
    assert decision_payload is not None
    _append_contract_record(Path(contract["decision_log_path"]), decision_payload, identity_field="decision_id")
    branch_payload = outcome_payloads.get("branch_record")
    if isinstance(branch_payload, dict):
        _append_contract_record(Path(contract["branch_log_path"]), branch_payload)
    record_research_memory_entry(
        {
            "entity_type": "decision",
            "entity_id": str(decision_payload.get("decision_id") or ""),
            "mission_id": str(mission_state.get("mission_id") or ""),
            "status": str(decision_payload.get("result", {}).get("status") or "selected"),
            "summary": str(decision_payload.get("summary") or "Mission runtime selected a bounded step."),
            "related_ids": [
                *_normalize_strings(decision_payload.get("selected_action_ids")),
                *_normalize_strings(decision_payload.get("selected_branch_ids")),
            ],
            "tags": [
                str(decision_payload.get("decision_type") or ""),
                str(decision_payload.get("phase") or mission_state.get("current_phase") or ""),
            ],
            "payload": {
                "decision_id": str(decision_payload.get("decision_id") or ""),
                "related_entity_id": str(
                    next(
                        iter(
                            decision_payload.get("selected_branch_ids")
                            or decision_payload.get("selected_action_ids")
                            or [mission_state.get("mission_id")]
                        )
                    )
                ),
                "rationale": str(decision_payload.get("summary") or ""),
                "actor": "mission-runtime",
                "decision_type": str(decision_payload.get("decision_type") or ""),
                "phase": str(decision_payload.get("phase") or mission_state.get("current_phase") or ""),
                "result": _jsonify(decision_payload.get("result", {})),
                "selected_action_ids": _jsonify(decision_payload.get("selected_action_ids", [])),
                "selected_branch_ids": _jsonify(decision_payload.get("selected_branch_ids", [])),
            },
            "provenance": {
                "source_kind": "mission-decision",
                "mission_id": str(mission_state.get("mission_id") or ""),
                "recorded_at": now_utc(),
                "source_paths": [
                    str(mission_state_path),
                    str(contract["decision_log_path"]),
                    str(contract["mission_memory_path"]),
                ],
                "source_entry_id": str(decision_payload.get("decision_id") or "") or None,
                "decision_id": str(decision_payload.get("decision_id") or "") or None,
                "branch_id": str((branch_payload or {}).get("branch_id") or "") or None,
            },
            "promotion": {
                "status": (
                    "promoted"
                    if str(decision_payload.get("decision_type") or "") in {"branch", "reroute", "phase-transition"}
                    else "candidate"
                ),
                "promoted_at": now_utc()
                if str(decision_payload.get("decision_type") or "") in {"branch", "reroute", "phase-transition"}
                else None,
                "source_entry_ids": [str(decision_payload.get("decision_id") or "")],
            },
        },
        contract=contract,
    )
    _record_ledger(
        mission_state_path,
        mission_state=mission_state,
        runtime_root=runtime_root,
        contract=contract,
        kind="mission-runtime-decision",
        status=str(decision_payload.get("result", {}).get("status") or "selected"),
        summary=str(decision_payload.get("summary") or "Mission runtime selected a bounded step."),
        metadata={
            "decision_id": decision_payload.get("decision_id"),
            "decision_type": decision_payload.get("decision_type"),
            "selected_action_ids": decision_payload.get("selected_action_ids", []),
            "selected_branch_ids": decision_payload.get("selected_branch_ids", []),
        },
    )


def _management_commands(mission_state_path: Path) -> dict[str, str]:
    mission_state_arg = str(mission_state_path)
    return {
        name: f"python scripts/mission/manage_mission.py {name} --mission-state {mission_state_arg}"
        for name in ("status", "logs", "decisions", "inbox", "resume", "triage")
    }


def _build_runtime_triage_prompt(
    *,
    snapshot: Mapping[str, Any],
    mission_state: Mapping[str, Any],
    request: Mapping[str, Any],
    blocked_entries: list[dict[str, Any]],
    result_json_path: Path,
) -> str:
    mission = snapshot.get("mission") if isinstance(snapshot.get("mission"), Mapping) else {}
    console = snapshot.get("operator_console") if isinstance(snapshot.get("operator_console"), Mapping) else {}
    context = request.get("context") if isinstance(request.get("context"), Mapping) else {}
    blocker = request.get("blocker") if isinstance(request.get("blocker"), Mapping) else {}
    recommendation = request.get("recommendation") if isinstance(request.get("recommendation"), Mapping) else {}
    ledger_path = Path(str(snapshot.get("artifacts", {}).get("ledger_path") or "")).expanduser().resolve()
    recent_ledger = _load_jsonl(ledger_path)[-6:] if ledger_path.exists() else []

    lines = [
        "# DeepLoop automatic bounded triage",
        "",
        "You are running a bounded recovery hook before the operator inbox is surfaced.",
        "Do not mutate mission state, queue files, or operator requests. Diagnose only and recommend the smallest safe next step.",
        "",
        "## Mission",
        "",
        f"- mission_id: `{mission.get('mission_id') or mission_state.get('mission_id')}`",
        f"- title: {mission.get('title') or mission_state.get('title') or 'n/a'}",
        f"- mode: `{context.get('mode') or mission_state.get('mode') or 'unknown'}`",
        f"- current_phase: `{mission.get('current_phase') or mission_state.get('current_phase') or 'unknown'}`",
        f"- operator_state: `{console.get('operator_state') or 'unknown'}`",
        "",
        "## Blocked request",
        "",
        f"- request_id: `{request.get('request_id')}`",
        f"- summary: {request.get('summary')}",
        f"- blocker_kind: `{blocker.get('kind')}`",
        f"- blocker_reason: {blocker.get('reason')}",
        f"- recommendation: {recommendation.get('summary') or 'n/a'}",
        "",
        "## Blocked queue entries",
        "",
    ]
    for entry in blocked_entries[:3]:
        lines.extend(
            [
                f"- queue: `{entry.get('queue_name')}` entry: `{entry.get('entry_id')}`",
                f"  - sanity_verdict: `{entry.get('sanity_verdict') or 'n/a'}`",
                f"  - summary_json_path: `{entry.get('summary_json_path') or 'n/a'}`",
                f"  - summary_markdown_path: `{entry.get('summary_markdown_path') or 'n/a'}`",
            ]
        )
        for reason in _normalize_strings(entry.get("top_blocking_reasons"))[:3]:
            lines.append(f"  - reason: {reason}")
    lines.extend(["", "## Recent ledger", ""])
    if recent_ledger:
        for item in recent_ledger:
            lines.append(
                f"- `{item.get('recorded_at') or item.get('timestamp') or 'unknown'}` `{item.get('kind') or 'unknown'}` `{item.get('status') or 'unknown'}`: {item.get('summary') or 'n/a'}"
            )
    else:
        lines.append("- No recent ledger entries were available.")
    lines.extend(
        [
            "",
            "## Required output",
            "",
            f"Write JSON to `{result_json_path}` with this exact top-level shape:",
            "```json",
            "{",
            '  "status": "completed" | "blocked" | "failed",',
            '  "summary": "short operator-facing diagnosis",',
            '  "recommended_operator_action": "retry" | "reroute" | "inspect" | "escalate",',
            '  "recommended_resume_action": "one sentence on what to do before resume",',
            '  "findings": ["specific finding 1", "specific finding 2"],',
            '  "evidence_paths": ["relevant/path/one", "relevant/path/two"],',
            '  "notes": ["bounded caution or scope note"]',
            "}",
            "```",
            "",
            "Prefer retry, reroute, or downscope inside the current mission scope unless the evidence truly requires escalation.",
        ]
    )
    return "\n".join(lines) + "\n"


def _normalized_runtime_triage_result(payload: dict[str, Any]) -> dict[str, Any]:
    status_aliases = {"complete": "completed", "completed": "completed", "blocked": "blocked", "failed": "failed"}
    status = status_aliases.get(str(payload.get("status") or "").strip().lower(), "")
    summary = str(payload.get("summary") or "").strip()
    if not status:
        raise ValueError("runtime bounded triage result must include status `completed`, `blocked`, or `failed`.")
    if not summary:
        raise ValueError("runtime bounded triage result must include a non-empty summary.")
    return {
        "status": status,
        "summary": summary,
        "recommended_operator_action": str(payload.get("recommended_operator_action") or "").strip() or None,
        "recommended_resume_action": str(payload.get("recommended_resume_action") or "").strip() or None,
        "findings": [str(item) for item in payload.get("findings", []) if str(item).strip()]
        if isinstance(payload.get("findings"), list)
        else [],
        "evidence_paths": [str(item) for item in payload.get("evidence_paths", []) if str(item).strip()]
        if isinstance(payload.get("evidence_paths"), list)
        else [],
        "notes": [str(item) for item in payload.get("notes", []) if str(item).strip()]
        if isinstance(payload.get("notes"), list)
        else [],
    }


def _should_auto_run_bounded_triage(
    request: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
) -> bool:
    blocker = request.get("blocker") if isinstance(request.get("blocker"), Mapping) else {}
    if str(blocker.get("kind") or "") != "operator-review":
        return False
    blocker_details = blocker.get("details") if isinstance(blocker.get("details"), Mapping) else {}
    blocked_entries = blocker_details.get("blocked_entries")
    if not isinstance(blocked_entries, list) or not blocked_entries:
        return False
    return str(contract.get("intervention_profile") or "") == "hook-enabled"


def _run_bounded_triage_before_escalation(
    mission_state_path: Path,
    mission_state: Mapping[str, Any],
    runtime_state: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = build_mission_snapshot(mission_state_path, log_tail_lines=0, ledger_tail=6)
    blocker = request.get("blocker") if isinstance(request.get("blocker"), Mapping) else {}
    blocker_details = blocker.get("details") if isinstance(blocker.get("details"), Mapping) else {}
    blocked_entries = [dict(item) for item in blocker_details.get("blocked_entries", []) if isinstance(item, Mapping)]
    request_id = str(request.get("request_id") or "runtime-bounded-triage")
    mission_root = mission_state_path.parent
    triage_root = mission_root / "runtime" / "operator_triage" / request_id
    triage_root.mkdir(parents=True, exist_ok=True)
    sandbox_root = triage_root / "sandbox"
    prompt_path = triage_root / "prompt.md"
    result_json_path = triage_root / "triage_result.json"
    log_path = triage_root / "triage.log"
    report_json_path = triage_root / "triage_report.json"
    prompt_text = _build_runtime_triage_prompt(
        snapshot=snapshot,
        mission_state=mission_state,
        request=request,
        blocked_entries=blocked_entries,
        result_json_path=result_json_path,
    )
    prompt_path.write_text(prompt_text, encoding="utf-8")
    target_repo = str(mission_state.get("target_repo") or "").strip()
    command = [
        sys.executable,
        str(_INVOKE_PROVIDER_PROMPT_SCRIPT),
        "--prompt-file",
        str(prompt_path),
        "--result-json-path",
        str(result_json_path),
        "--sandbox-root",
        str(sandbox_root),
        "--mission-state-path",
        str(mission_state_path),
        "--no-ask-user",
    ]
    if target_repo:
        command.extend(["--target-repo", target_repo])
    started_at = now_utc()
    completed = subprocess.run(
        command,
        cwd=Path(target_repo).expanduser().resolve() if target_repo else REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    completed_at = now_utc()
    log_path.write_text((completed.stdout or "") + (completed.stderr or ""), encoding="utf-8")
    if result_json_path.exists():
        try:
            triage_result = _normalized_runtime_triage_result(_load_json(result_json_path))
        except Exception as exc:
            triage_result = {
                "status": "failed",
                "summary": f"Automatic bounded triage produced invalid output: {exc}",
                "recommended_operator_action": None,
                "recommended_resume_action": None,
                "findings": [],
                "evidence_paths": [],
                "notes": [],
            }
    else:
        triage_result = {
            "status": "failed",
            "summary": f"Automatic bounded triage did not produce `{result_json_path}`.",
            "recommended_operator_action": None,
            "recommended_resume_action": None,
            "findings": [],
            "evidence_paths": [],
            "notes": [],
        }
    summary = {
        "schema_version": 1,
        "request_id": request_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "command": command,
        "prompt_path": str(prompt_path),
        "result_json_path": str(result_json_path),
        "log_path": str(log_path),
        "report_json_path": str(report_json_path),
        "blocked_entries": blocked_entries,
        "result": triage_result,
        "returncode": completed.returncode,
        "auto_invoked": True,
    }
    _write_json(report_json_path, summary)
    _record_ledger(
        mission_state_path,
        mission_state=dict(mission_state),
        runtime_root=Path(str(runtime_state.get("runtime_root") or mission_root / "runtime" / DEFAULT_RUNTIME_DIR_NAME)),
        contract=dict(contract),
        kind="runtime-bounded-triage",
        status=triage_result["status"],
        summary=f"Recorded automatic bounded triage for `{request_id}` with status `{triage_result['status']}`.",
        metadata={
            "request_id": request_id,
            "recommended_operator_action": triage_result.get("recommended_operator_action"),
            "recommended_resume_action": triage_result.get("recommended_resume_action"),
            "report_json_path": str(report_json_path),
        },
    )
    return summary


def _attach_auto_triage_to_request(request: dict[str, Any], triage_summary: Mapping[str, Any]) -> dict[str, Any]:
    result = triage_summary.get("result") if isinstance(triage_summary.get("result"), Mapping) else {}
    updated = dict(request)
    updated["auto_triage"] = {
        "status": result.get("status"),
        "summary": result.get("summary"),
        "recommended_operator_action": result.get("recommended_operator_action"),
        "recommended_resume_action": result.get("recommended_resume_action"),
        "report_json_path": triage_summary.get("report_json_path"),
        "completed_at": triage_summary.get("completed_at"),
    }
    updated_recommendation = (
        dict(updated.get("recommendation"))
        if isinstance(updated.get("recommendation"), Mapping)
        else {}
    )
    recommended_action = str(result.get("recommended_operator_action") or "").strip()
    recommended_resume_action = str(result.get("recommended_resume_action") or "").strip()
    triage_summary_text = str(result.get("summary") or "").strip()
    if recommended_action or recommended_resume_action or triage_summary_text:
        pieces = []
        if recommended_action:
            pieces.append(f"automatic bounded triage recommends `{recommended_action}`")
        if recommended_resume_action:
            pieces.append(recommended_resume_action)
        elif triage_summary_text:
            pieces.append(triage_summary_text)
        updated_recommendation["summary"] = ". ".join(pieces) + "."
    updated["recommendation"] = updated_recommendation
    explanation = str(updated.get("explanation") or "").strip()
    triage_note = f"Automatic bounded triage already ran with status `{result.get('status')}`."
    report_json_path = str(triage_summary.get("report_json_path") or "").strip()
    if report_json_path:
        triage_note += f" Report: `{report_json_path}`."
    updated["explanation"] = f"{explanation} {triage_note}".strip()
    return updated


def _hard_gate_event(
    mission_state: Mapping[str, Any],
    executor_payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    candidates: list[Mapping[str, Any]] = []
    if isinstance(executor_payload, Mapping) and isinstance(executor_payload.get("gate_event"), Mapping):
        candidates.append(executor_payload["gate_event"])
    adaptation = mission_state.get("adaptation_training")
    if isinstance(adaptation, Mapping) and isinstance(adaptation.get("gate_event"), Mapping):
        candidates.append(adaptation["gate_event"])
    for candidate in candidates:
        if str(candidate.get("gate") or "") == "hard":
            return dict(candidate)
    return None


def _operator_guidance(
    *,
    blocker_kind: str,
    mode: str,
    reason: str,
    commands: Mapping[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if blocker_kind == "hard-gate":
        recommendation = {
            "summary": (
                "Review the hard gate, keep the mission inside the current safety boundary if possible, "
                "then resume autopilot."
            ),
            "pros": [
                "Preserves the default sandboxed autopilot posture.",
                "Keeps the mission honest about true safety and authority boundaries.",
            ],
            "cons": [
                "Requires an operator review before work can continue.",
            ],
        }
        alternatives = [
            {
                "option_id": "adjust-and-resume",
                "summary": "Adjust scope, paths, or inputs so the next step stays inside the current boundary.",
                "pros": ["Usually keeps the default mode intact.", "Minimizes authority expansion."],
                "cons": ["May reduce ambition or require a smaller next step."],
                "next_steps": [commands["status"], commands["resume"]],
            },
            {
                "option_id": "escalate-authority",
                "summary": f"Escalate beyond `{mode}` only if the mission truly requires it.",
                "pros": ["Allows the blocked action to proceed if broader authority is justified."],
                "cons": ["Increases risk and review burden."],
                "next_steps": [commands["inbox"], commands["resume"]],
            },
        ]
    elif blocker_kind == "authority-boundary":
        recommendation = {
            "summary": "Approve the requested action or change the plan, then resume the mission.",
            "pros": ["Makes the human decision explicit.", "Keeps the runtime honest about authority."],
            "cons": ["Adds an operator checkpoint before the next action."],
        }
        alternatives = [
            {
                "option_id": "approve-and-resume",
                "summary": "Approve the requested authority expansion and continue.",
                "pros": ["Fastest path if the action is acceptable."],
                "cons": ["Requires the operator to own the approval decision."],
                "next_steps": [commands["inbox"], commands["resume"]],
            },
            {
                "option_id": "reroute-in-scope",
                "summary": "Edit the mission inputs so the next action stays in scope.",
                "pros": ["Keeps work inside the existing operating mode."],
                "cons": ["May require downscoping the plan."],
                "next_steps": [commands["status"], commands["resume"]],
            },
        ]
    elif blocker_kind == "unrecoverable-failure":
        recommendation = {
            "summary": "Inspect the failure, fix the blocking condition, then resume the mission.",
            "pros": ["Restarts autopilot with an explicit fix in place.", "Avoids pretending recovery exists when it does not."],
            "cons": ["Needs manual debugging before the mission can continue."],
        }
        alternatives = [
            {
                "option_id": "debug-and-resume",
                "summary": "Use the logs and recent decisions to repair the failing executor or config.",
                "pros": ["Preserves the original mission intent."],
                "cons": ["May take longer than rerouting."],
                "next_steps": [commands["logs"], commands["resume"]],
            },
            {
                "option_id": "downscope-and-resume",
                "summary": "Reduce scope or reroute around the failing step before resuming.",
                "pros": ["Can restore progress faster."],
                "cons": ["May skip the original blocked path."],
                "next_steps": [commands["decisions"], commands["resume"]],
            },
        ]
    else:
        recommendation = {
            "summary": "Review the operator request, make the smallest safe change, then resume.",
            "pros": ["Keeps the handoff explicit.", "Preserves auditability."],
            "cons": ["Requires an operator decision before continuing."],
        }
        alternatives = [
            {
                "option_id": "inspect-and-resume",
                "summary": "Inspect the latest request and continue once the blocker is understood.",
                "pros": ["Simple default path."],
                "cons": ["May still need follow-up edits."],
                "next_steps": [commands["inbox"], commands["resume"]],
            },
            {
                "option_id": "downscope-first",
                "summary": "Change the next step to a smaller bounded task before resuming.",
                "pros": ["Reduces the chance of another hard stop."],
                "cons": ["May defer the original task."],
                "next_steps": [commands["status"], commands["resume"]],
            },
        ]
    _ = reason
    return recommendation, alternatives


def _build_operator_request(
    mission_state_path: Path,
    mission_state: Mapping[str, Any],
    runtime_state: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    decision_payload: Mapping[str, Any] | None,
    action_payload: Mapping[str, Any] | None,
    executor_payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    runtime_status = str(runtime_state.get("status") or "")
    if runtime_status not in {"blocked", "failed"}:
        return None

    mission_id = str(mission_state.get("mission_id") or mission_state_path.parent.name)
    mode = str(contract.get("mode") or mission_state.get("mode") or DEFAULT_OPERATING_MODE)
    reason = str(runtime_state.get("terminal_reason") or mission_state.get("autonomy_status", {}).get("reason") or "").strip()
    decision_id = str(
        (decision_payload or {}).get("decision_id")
        or runtime_state.get("last_decision_id")
        or f"{mission_id}-operator-request"
    )
    action_id = str((action_payload or {}).get("action_id") or runtime_state.get("last_action_id") or "operator-review")
    action_kind = str((action_payload or {}).get("kind") or (decision_payload or {}).get("decision_type") or "operator-review")
    executor = (action_payload or {}).get("executor") if isinstance((action_payload or {}).get("executor"), Mapping) else {}
    executor_id = str(executor.get("id") or runtime_state.get("last_executor_id") or "n/a")
    blocked_entries = []
    if isinstance(executor_payload, Mapping):
        raw_blocked_entries = executor_payload.get("blocked_entries")
        if isinstance(raw_blocked_entries, list):
            blocked_entries = [dict(item) for item in raw_blocked_entries if isinstance(item, Mapping)]
    first_blocked_entry = blocked_entries[0] if blocked_entries else {}
    gate_event = _hard_gate_event(mission_state, executor_payload)
    authority = (decision_payload or {}).get("authority") if isinstance((decision_payload or {}).get("authority"), Mapping) else {}
    requires_operator_approval = bool(authority.get("requires_operator_approval") or (action_payload or {}).get("requires_operator_approval"))

    blocker_kind = "operator-review"
    gate = "operator-needed"
    risk_class = "operator-review"
    label = "operator review"
    default_response = None
    preferred_actions: list[str] = []
    hard_gate_profile = None
    if blocked_entries:
        preferred_actions = _normalize_strings(contract.get("soft_gate_preferred_actions"))
    if isinstance(gate_event, Mapping):
        blocker_kind = "hard-gate"
        gate = str(gate_event.get("gate") or "hard")
        risk_class = str(gate_event.get("risk_class") or "hard-gate")
        label = str(gate_event.get("label") or risk_class)
        default_response = gate_event.get("default_response")
        preferred_actions = _normalize_strings(gate_event.get("preferred_actions"))
        hard_gate_profile = gate_event.get("hard_gate_profile")
    elif requires_operator_approval:
        blocker_kind = "authority-boundary"
        gate = "approval-required"
        risk_class = "authority-boundary"
        label = "explicit operator approval"
    elif runtime_status == "failed":
        blocker_kind = "unrecoverable-failure"
        gate = "failure"
        risk_class = "unrecoverable-failure"
        label = "unrecoverable runtime failure"

    commands = _management_commands(mission_state_path)
    recommendation, alternatives = _operator_guidance(
        blocker_kind=blocker_kind,
        mode=mode,
        reason=reason,
        commands=commands,
    )

    blocked_reason = reason
    if blocked_entries:
        queue_name = str(first_blocked_entry.get("queue_name") or executor_id)
        entry_id = str(first_blocked_entry.get("entry_id") or "blocked-entry")
        verdict = str(first_blocked_entry.get("sanity_verdict") or "").strip()
        top_reasons = [str(item) for item in first_blocked_entry.get("top_blocking_reasons") or [] if str(item).strip()]
        blocked_reason = f"Queue `{queue_name}` blocked on `{entry_id}`."
        if verdict:
            blocked_reason += f" sanity_verdict=`{verdict}`."
        if top_reasons:
            blocked_reason += f" Top reasons: {'; '.join(top_reasons[:3])}."

    if blocker_kind == "hard-gate":
        summary = f"Autopilot paused at `{risk_class}`: {reason}"
        explanation = (
            f"DeepLoop stopped because `{reason}` crossed the `{risk_class}` hard-gate class under the "
            f"`{contract.get('hard_gate_profile')}` profile."
        )
    elif blocker_kind == "authority-boundary":
        summary = f"Autopilot paused for operator approval: {reason or action_kind}"
        explanation = "DeepLoop selected a step that explicitly requires operator approval before execution."
    elif blocker_kind == "unrecoverable-failure":
        summary = f"Autopilot stopped on an unrecoverable failure: {reason}"
        explanation = "DeepLoop exhausted its bounded recovery path and stopped honestly instead of faking progress."
    else:
        summary = f"Autopilot paused for operator review: {blocked_reason or action_kind}"
        explanation = (
            "DeepLoop needs an operator decision before it can continue honestly."
            if not blocked_entries
            else "DeepLoop stopped honestly after a blocked bounded queue entry. The operator surface now includes the specific blocked entry and top blocking reasons."
        )

    triage_enabled = bool(blocked_entries) and str(contract.get("intervention_profile") or "") == "hook-enabled"
    if triage_enabled:
        recommendation = dict(recommendation)
        recommendation["pros"] = [
            *[str(item) for item in recommendation.get("pros") or []],
            "Managed-mode bounded triage can inspect the blocked entry before you choose retry versus reroute.",
        ]
        triage_alternative = {
            "option_id": "bounded-triage",
            "summary": "Run a bounded recursive-agent triage pass against the blocked queue entry before resuming.",
            "pros": [
                "Keeps the review in scope and attached to the current blocked artifacts.",
                "Produces a durable triage report instead of relying on ad hoc shell notes.",
            ],
            "cons": [
                "Only available when intervention hooks are explicitly enabled.",
                "Still requires the operator to choose the final retry or reroute action.",
            ],
            "next_steps": [commands["triage"], commands["inbox"], commands["resume"]],
        }
        alternatives = [triage_alternative, *alternatives]

    next_steps = [
        commands["inbox"],
        commands["status"],
        commands["decisions"],
        commands["logs"],
        commands["resume"],
    ]
    if triage_enabled:
        next_steps.insert(0, commands["triage"])

    return {
        "schema_version": 1,
        "request_id": f"{decision_id}-operator-request",
        "mission_id": mission_id,
        "created_at": now_utc(),
        "status": "open",
        "summary": summary,
        "explanation": explanation,
        "blocker": {
            "kind": blocker_kind,
            "gate": gate,
            "risk_class": risk_class,
            "label": label,
            "reason": blocked_reason or summary,
            "default_response": default_response,
            "preferred_actions": preferred_actions,
            "hard_gate_profile": hard_gate_profile,
            "details": {
                "queue_name": first_blocked_entry.get("queue_name"),
                "blocked_entries": blocked_entries,
            }
            if blocked_entries
            else {},
        },
        "context": {
            "mission_state_path": str(mission_state_path),
            "runtime_root": str(runtime_state.get("runtime_root") or ""),
            "mode": mode,
            "phase": str(mission_state.get("current_phase") or ""),
            "next_phase": str(mission_state.get("next_phase") or ""),
            "decision_id": decision_id,
            "decision_type": str((decision_payload or {}).get("decision_type") or "operator-review"),
            "action_id": action_id,
            "action_kind": action_kind,
            "action_task": (action_payload or {}).get("task"),
            "branch_id": (action_payload or {}).get("branch_id") or runtime_state.get("last_branch_id"),
            "executor_id": executor_id,
            "blocked_entries": blocked_entries,
        },
        "recommendation": recommendation,
        "alternatives": alternatives,
        "next_steps": next_steps,
        "continue_command": commands["resume"],
    }


def _sync_operator_inbox(
    mission_state_path: Path,
    mission_state: dict[str, Any],
    runtime_state: dict[str, Any],
    *,
    contract: dict[str, Any],
    decision_payload: Mapping[str, Any] | None,
    action_payload: Mapping[str, Any] | None,
    executor_payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    paths = ensure_operator_inbox_contract(mission_state_path.parent, contract=contract)
    current_request_path = Path(paths["current_operator_request_path"])
    if str(runtime_state.get("status") or "") not in {"blocked", "failed"}:
        clear_current_operator_request(current_request_path)
        runtime_state["current_operator_request_id"] = None
        return None
    request = _build_operator_request(
        mission_state_path,
        mission_state,
        runtime_state,
        contract=contract,
        decision_payload=decision_payload,
        action_payload=action_payload,
        executor_payload=executor_payload,
    )
    if request is None:
        clear_current_operator_request(current_request_path)
        runtime_state["current_operator_request_id"] = None
        return None
    if _should_auto_run_bounded_triage(request, contract=contract):
        try:
            triage_summary = _run_bounded_triage_before_escalation(
                mission_state_path,
                mission_state,
                runtime_state,
                request,
                contract=contract,
            )
        except Exception as exc:
            triage_summary = {
                "schema_version": 1,
                "request_id": request.get("request_id"),
                "completed_at": now_utc(),
                "report_json_path": None,
                "result": {
                    "status": "failed",
                    "summary": f"Automatic bounded triage failed before the inbox opened: {exc}",
                    "recommended_operator_action": None,
                    "recommended_resume_action": None,
                    "findings": [],
                    "evidence_paths": [],
                    "notes": [],
                },
            }
        request = _attach_auto_triage_to_request(request, triage_summary)
        mission_state["automatic_bounded_triage"] = _jsonify(triage_summary)
        runtime_state["automatic_bounded_triage"] = _jsonify(triage_summary)
        triage_result = triage_summary.get("result") if isinstance(triage_summary.get("result"), Mapping) else {}
        managed_recovery = _stage_managed_recovery_action(
            mission_state,
            source_action_payload=action_payload,
            recommended_action=str(triage_result.get("recommended_operator_action") or "").strip() or None,
            reason=str(triage_result.get("summary") or "").strip(),
            source="bounded-triage",
            request_id=str(request.get("request_id") or "").strip() or None,
            recommended_resume_action=str(triage_result.get("recommended_resume_action") or "").strip() or None,
        )
        if managed_recovery is not None:
            request = _attach_managed_recovery_to_request(request, managed_recovery)
            runtime_state["automatic_recovery"] = _jsonify(managed_recovery)
    append_operator_request(
        Path(paths["operator_request_log_path"]),
        current_request_path,
        request,
    )
    runtime_state["current_operator_request_id"] = request["request_id"]
    return request


def _sync_branch_state(mission_state: dict[str, Any], branch_payload: dict[str, Any] | None) -> None:
    if not isinstance(branch_payload, dict):
        return
    branch_records = list(mission_state.get("branch_records") or [])
    branch_id = str(branch_payload.get("branch_id") or "")
    replaced = False
    for index, existing in enumerate(branch_records):
        if isinstance(existing, dict) and str(existing.get("branch_id") or "") == branch_id:
            branch_records[index] = branch_payload
            replaced = True
            break
    if not replaced:
        branch_records.append(branch_payload)
    mission_state["branch_records"] = branch_records


def _stop_status(
    mission_state: dict[str, Any],
    *,
    runtime_state: dict[str, Any],
    status: str,
    reason: str,
) -> None:
    runtime_state["status"] = status
    runtime_state["terminal_reason"] = reason
    mission_state["autonomy_status"] = {
        "state": f"mission-runtime-{status}",
        "reason": reason,
    }
    if status == "completed":
        mission_state["status"] = "completed"
    elif status == "failed":
        mission_state["status"] = "failed"
    elif status == "blocked":
        mission_state["status"] = "blocked"
        blocked_reasons = _normalize_strings(mission_state.get("blocked_reasons"))
        if reason not in blocked_reasons:
            blocked_reasons.append(reason)
        mission_state["blocked_reasons"] = blocked_reasons
    elif status == "max-iterations":
        mission_state["status"] = "paused"


def _refresh_completed_mission_package(
    mission_state_path: Path,
    mission_state: dict[str, Any],
) -> dict[str, Any] | None:
    package_payload = mission_state.get("mission_package")
    if not isinstance(package_payload, Mapping):
        return None
    package_root_raw = str(package_payload.get("package_root") or "").strip()
    if not package_root_raw:
        return None
    package_root = Path(package_root_raw).expanduser().resolve()
    return _mission_executor_registry.package_mission_artifacts(
        mission_state_path,
        output_root=package_root.parent,
    )


def run_mission(
    mission_state_path: Path,
    *,
    max_iterations: int = 12,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    resolved_state_path = mission_state_path.expanduser().resolve()
    mission_state = load_mission_state(resolved_state_path)
    runtime_root_path = _runtime_root(resolved_state_path, runtime_root)
    runtime_root_path.mkdir(parents=True, exist_ok=True)
    runtime_state = _load_runtime_state(
        str(mission_state.get("mission_id") or "mission"),
        mission_state_path=resolved_state_path,
        runtime_root=runtime_root_path,
        max_iterations=max_iterations,
    )
    if str(mission_state.get("status") or "") == "completed":
        contract = _outer_loop_contract(resolved_state_path, mission_state)
        runtime_state["status"] = "completed"
        runtime_state["terminal_reason"] = "Mission state already marked complete."
        _write_state(resolved_state_path, mission_state, runtime_state, contract=contract)
        return {
            "status": runtime_state["status"],
            "iterations_completed": runtime_state["iterations_completed"],
            "runtime_root": runtime_root_path,
            "state_path": _runtime_state_path(runtime_root_path),
            "history_path": _runtime_history_path(runtime_root_path),
            "summary_json_path": _runtime_summary_json_path(runtime_root_path),
            "summary_markdown_path": _runtime_summary_md_path(runtime_root_path),
            "mission_state_path": resolved_state_path,
            "terminal_reason": runtime_state.get("terminal_reason"),
            "mission_memory_path": Path(contract["mission_memory_path"]),
            "experiment_ledger_path": Path(contract["experiment_ledger_path"]),
        }

    while runtime_state["iterations_completed"] < int(max_iterations):
        mission_state = load_mission_state(resolved_state_path)
        contract = _outer_loop_contract(resolved_state_path, mission_state)
        evidence = gather_mission_evidence(resolved_state_path, mission_state)
        outcome = decide_next_mission_action(mission_state, evidence=evidence)
        payloads = outcome.payload_bundle()
        _record_selected_outcome(
            resolved_state_path,
            mission_state=mission_state,
            runtime_root=runtime_root_path,
            contract=contract,
            outcome_payloads=payloads,
        )
        _sync_branch_state(mission_state, payloads.get("branch_record"))
        evidence_payload = {
            "produced_outputs": list(evidence.produced_outputs),
            "blockers": list(evidence.blockers),
            "recent_failures": list(evidence.recent_failures),
            "failure_count": evidence.failure_count,
        }
        append_mission_experiment_entry(
            resolved_state_path,
            str(mission_state.get("mission_id") or ""),
            contract=contract,
            entry_id=f"evidence-{outcome.decision.decision_id}",
            kind="evidence-snapshot",
            status="recorded",
            summary=f"Captured mission evidence before decision `{outcome.decision.decision_id}`.",
            phase=str(outcome.decision.phase or mission_state.get("current_phase") or ""),
            branch_id=outcome.branch_record.branch_id if outcome.branch_record is not None else None,
            metadata={
                "decision_id": outcome.decision.decision_id,
                "decision_type": outcome.decision.decision_type,
                **evidence_payload,
            },
        )
        if outcome.action is not None:
            action_payload = _upsert_selected_action(mission_state, outcome.action, summary=outcome.decision.summary)
        else:
            action_payload = None

        raw_outcome_status = "selected"
        terminal_reason = outcome.decision.summary
        executor_payload: Mapping[str, Any] | None = None

        if outcome.directive == MissionDecisionDirective.COMPLETE:
            _stop_status(mission_state, runtime_state=runtime_state, status="completed", reason=terminal_reason)
        elif outcome.directive == MissionDecisionDirective.FAIL:
            _stop_status(mission_state, runtime_state=runtime_state, status="failed", reason=terminal_reason)
        elif outcome.directive == MissionDecisionDirective.BLOCK:
            if outcome.action is not None:
                _update_action_result(
                    mission_state,
                    action_id=outcome.action.action_id,
                    status="blocked",
                    notes=[terminal_reason],
                )
            _stop_status(mission_state, runtime_state=runtime_state, status="blocked", reason=terminal_reason)
            raw_outcome_status = "blocked"
        elif outcome.directive in {
            MissionDecisionDirective.BRANCH,
            MissionDecisionDirective.REROUTE,
        } or (
            outcome.directive == MissionDecisionDirective.CONTINUE
            and outcome.decision.transition is not None
        ):
            transition = outcome.decision.transition.to_payload() if outcome.decision.transition is not None else {}
            from_phase = str(transition.get("from_phase") or mission_state.get("current_phase") or "")
            to_phase = str(transition.get("to_phase") or (outcome.action.phase if outcome.action is not None else from_phase))
            _apply_phase_change(
                mission_state,
                from_phase=from_phase,
                to_phase=to_phase,
                next_phase=str(transition.get("to_phase") or mission_state.get("next_phase") or ""),
            )
            mission_state["status"] = "running"
            mission_state["autonomy_status"] = {
                "state": "mission-runtime-transitioned",
                "reason": terminal_reason,
            }
            if outcome.action is not None:
                _update_action_result(
                    mission_state,
                    action_id=outcome.action.action_id,
                    status="completed",
                    notes=[terminal_reason],
                )
            raw_outcome_status = outcome.directive.value
            runtime_state["status"] = "running"
            runtime_state["terminal_reason"] = None
        elif outcome.directive == MissionDecisionDirective.DISPATCH and outcome.action is not None:
            dispatch = outcome.action.executor_dispatch
            assert dispatch is not None
            _update_action_result(
                mission_state,
                action_id=outcome.action.action_id,
                status="in_progress",
                notes=[f"dispatching via {dispatch.executor_id.value}"],
            )
            bootstrap = _bootstrap_mapping(mission_state)
            if (
                dispatch.executor_id == MissionExecutorId.SELF_HEALING_QUEUE
                and _bootstrap_followup_planner(bootstrap)
                and str(bootstrap.get("status") or "").strip() in {"pending", "pending-baseline-execution"}
            ):
                bootstrap["status"] = "baseline-running"
                bootstrap["started_at"] = now_utc()
                mission_state["bootstrap"] = bootstrap
            runtime_state["status"] = "running"
            runtime_state["last_executor_id"] = dispatch.executor_id.value
            _write_state(resolved_state_path, mission_state, runtime_state, contract=contract)
            try:
                result = run_mission_action(dispatch.action)
            except Exception as exc:
                action_phase = str(
                    (action_payload.get("phase") if isinstance(action_payload, dict) else None)
                    or mission_state.get("current_phase")
                    or ""
                )
                action_branch_id = str(
                    (action_payload.get("branch_id") if isinstance(action_payload, dict) else None) or ""
                )
                terminal_reason = (
                    f"Executor `{dispatch.executor_id.value}` raised `{type(exc).__name__}`: {exc}"
                )
                failures = _normalize_strings(mission_state.get("recent_failures"))
                failures.append(terminal_reason)
                mission_state["recent_failures"] = failures[-8:]
                mission_state["failure_count"] = int(mission_state.get("failure_count", 0) or 0) + 1
                _update_action_result(
                    mission_state,
                    action_id=outcome.action.action_id,
                    status="blocked",
                    notes=[terminal_reason],
                )
                _stop_status(mission_state, runtime_state=runtime_state, status="failed", reason=terminal_reason)
                raw_outcome_status = "failed"
                _record_ledger(
                    resolved_state_path,
                    mission_state=mission_state,
                    runtime_root=runtime_root_path,
                    contract=contract,
                    kind="mission-runtime-execution",
                    status="failed",
                    summary=terminal_reason,
                    metadata={
                        "action_id": outcome.action.action_id,
                        "executor_id": dispatch.executor_id.value,
                    },
                )
                append_mission_experiment_entry(
                    resolved_state_path,
                    str(mission_state.get("mission_id") or ""),
                    contract=contract,
                    entry_id=f"execution-{outcome.action.action_id}",
                    kind="experiment-run",
                    status="failed",
                    summary=terminal_reason,
                    phase=action_phase,
                    action_id=outcome.action.action_id,
                    branch_id=action_branch_id,
                    executor_id=dispatch.executor_id.value,
                    metadata={"reason": terminal_reason},
                )
            else:
                post_execution_state = load_mission_state(resolved_state_path)
                updated_state, action_status, output_paths = _mission_state_updates_from_executor(
                    post_execution_state,
                    action_payload=action_payload,
                    result=result,
                )
                _update_action_result(
                    updated_state,
                    action_id=outcome.action.action_id,
                    status=action_status,
                    output_paths=output_paths,
                    notes=[result.summary, f"executor-status={result.status}"],
                )
                if result.executor_id == MissionExecutorId.SELF_HEALING_QUEUE:
                    updated_state["runtime_recovery"] = _jsonify(result.payload)
                elif result.executor_id == MissionExecutorId.ADAPTATION_TRAINING:
                    updated_state["adaptation_training"] = _jsonify(result.payload)
                elif result.executor_id == MissionExecutorId.EVALUATION_COMPARISON:
                    updated_state["evaluation_comparison"] = _jsonify(result.payload)
                elif result.executor_id == MissionExecutorId.REPORT_SYNTHESIS:
                    updated_state["mission_package"] = _jsonify(result.payload)
                elif result.executor_id == MissionExecutorId.STAGE_KERNEL:
                    stage_runs = updated_state.setdefault("stage_runs", {})
                    stage_id = str(result.payload.get("stage_id") or outcome.action.action_id)
                    stage_runs[stage_id] = _jsonify(result.payload)
                gate_event = result.payload.get("gate_event") if isinstance(result.payload.get("gate_event"), Mapping) else None
                if (
                    str(result.status) == "deferred"
                    and isinstance(gate_event, Mapping)
                    and str(gate_event.get("gate") or "") == "soft"
                ):
                    managed_recovery = _stage_managed_recovery_action(
                        updated_state,
                        source_action_payload=action_payload,
                        recommended_action=(
                            _normalize_strings(gate_event.get("preferred_actions"))[:1] or [None]
                        )[0],
                        reason=str(gate_event.get("reason") or result.summary or "").strip(),
                        source="soft-gate",
                        recommended_resume_action=str(gate_event.get("default_response") or "").strip() or None,
                    )
                    if managed_recovery is not None:
                        runtime_state["automatic_recovery"] = _jsonify(managed_recovery)
                bootstrap_note = None
                try:
                    updated_state, bootstrap_note = _maybe_stage_bootstrap_followups(
                        resolved_state_path,
                        updated_state,
                        result=result,
                    )
                except Exception as exc:
                    action_phase = str(
                        (action_payload.get("phase") if isinstance(action_payload, dict) else None)
                        or mission_state.get("current_phase")
                        or ""
                    )
                    action_branch_id = str(
                        (action_payload.get("branch_id") if isinstance(action_payload, dict) else None) or ""
                    )
                    terminal_reason = f"Bootstrap follow-up staging failed: {exc}"
                    failures = _normalize_strings(updated_state.get("recent_failures"))
                    failures.append(terminal_reason)
                    updated_state["recent_failures"] = failures[-8:]
                    updated_state["failure_count"] = int(updated_state.get("failure_count", 0) or 0) + 1
                    _update_action_result(
                        updated_state,
                        action_id=outcome.action.action_id,
                        status="blocked",
                        notes=[terminal_reason],
                    )
                    mission_state = updated_state
                    _stop_status(mission_state, runtime_state=runtime_state, status="failed", reason=terminal_reason)
                    raw_outcome_status = "failed"
                    append_mission_experiment_entry(
                        resolved_state_path,
                        str(mission_state.get("mission_id") or ""),
                        contract=contract,
                        entry_id=f"execution-{outcome.action.action_id}",
                        kind="experiment-run",
                        status="failed",
                        summary=terminal_reason,
                        phase=action_phase,
                        action_id=outcome.action.action_id,
                        branch_id=action_branch_id,
                        executor_id=result.executor_id.value,
                        metadata={"reason": terminal_reason, "payload": _jsonify(result.payload)},
                    )
                    _record_ledger(
                        resolved_state_path,
                        mission_state=mission_state,
                        runtime_root=runtime_root_path,
                        contract=contract,
                        kind="mission-runtime-execution",
                        status="failed",
                        summary=terminal_reason,
                        metadata={
                            "action_id": outcome.action.action_id,
                            "executor_id": result.executor_id.value,
                            "executor_status": result.status,
                            "artifacts": [str(path) for path in result.artifacts.values()],
                        },
                    )
                    continue
                raw_outcome_status = str(result.status)
                terminal_reason = result.summary
                if bootstrap_note:
                    terminal_reason = bootstrap_note
                executor_payload = result.payload
                mission_state = updated_state
                if _should_continue_after_recursive_executor_failure(result=result, action_payload=action_payload):
                    failures = _normalize_strings(mission_state.get("recent_failures"))
                    failures.append(terminal_reason)
                    mission_state["recent_failures"] = failures[-8:]
                    mission_state["failure_count"] = int(mission_state.get("failure_count", 0) or 0) + 1
                    mission_state["status"] = "running"
                    mission_state["autonomy_status"] = {
                        "state": "mission-runtime-recovery",
                        "reason": terminal_reason,
                    }
                    runtime_state["status"] = "running"
                    runtime_state["terminal_reason"] = None
                elif raw_outcome_status in {"blocked"}:
                    _stop_status(mission_state, runtime_state=runtime_state, status="blocked", reason=terminal_reason)
                elif raw_outcome_status in {"failed", "error"}:
                    failures = _normalize_strings(mission_state.get("recent_failures"))
                    failures.append(terminal_reason)
                    mission_state["recent_failures"] = failures[-8:]
                    mission_state["failure_count"] = int(mission_state.get("failure_count", 0) or 0) + 1
                    _stop_status(mission_state, runtime_state=runtime_state, status="failed", reason=terminal_reason)
                elif raw_outcome_status == "max-iterations":
                    _stop_status(mission_state, runtime_state=runtime_state, status="max-iterations", reason=terminal_reason)
                else:
                    mission_state["status"] = "running"
                    autonomy_state = mission_state.get("autonomy_status")
                    if (
                        not isinstance(autonomy_state, Mapping)
                        or str(autonomy_state.get("state") or "") != "mission-runtime-ready"
                    ):
                        mission_state["autonomy_status"] = {
                            "state": "mission-runtime-running",
                            "reason": terminal_reason,
                        }
                    runtime_state["status"] = "running"
                    runtime_state["terminal_reason"] = None
                append_mission_experiment_entry(
                    resolved_state_path,
                    str(mission_state.get("mission_id") or ""),
                    contract=contract,
                    entry_id=f"execution-{outcome.action.action_id}",
                    kind="experiment-run",
                    status=str(result.status),
                    summary=result.summary,
                    phase=str(action_payload.get("phase") or mission_state.get("current_phase") or ""),
                    action_id=outcome.action.action_id,
                    branch_id=str(action_payload.get("branch_id") or ""),
                    executor_id=result.executor_id.value,
                    output_paths=output_paths,
                    artifact_paths=[str(path) for path in result.artifacts.values()],
                    metadata={
                        "executor_status": result.status,
                        "payload": _jsonify(result.payload),
                        "bootstrap_note": bootstrap_note,
                    },
                )
                _record_ledger(
                    resolved_state_path,
                    mission_state=mission_state,
                    runtime_root=runtime_root_path,
                    contract=contract,
                    kind="mission-runtime-execution",
                    status=str(result.status),
                    summary=terminal_reason,
                    metadata={
                        "action_id": outcome.action.action_id,
                        "executor_id": result.executor_id.value,
                        "executor_status": result.status,
                        "bootstrap_note": bootstrap_note,
                        "artifacts": [str(path) for path in result.artifacts.values()],
                    },
                )
        else:
            reason = (
                f"Selected action `{outcome.action.action_id}` has no executor-backed runtime; stopping honestly."
                if outcome.action is not None
                else "No executable mission action was selected; stopping honestly."
            )
            if outcome.action is not None:
                _update_action_result(
                    mission_state,
                    action_id=outcome.action.action_id,
                    status="blocked",
                    notes=[reason],
                )
            _stop_status(mission_state, runtime_state=runtime_state, status="blocked", reason=reason)
            raw_outcome_status = "blocked"
            terminal_reason = reason

        runtime_state["iterations_completed"] = int(runtime_state.get("iterations_completed", 0) or 0) + 1
        runtime_state["last_decision_id"] = outcome.decision.decision_id
        runtime_state["last_action_id"] = outcome.action.action_id if outcome.action is not None else None
        runtime_state["last_branch_id"] = outcome.branch_record.branch_id if outcome.branch_record is not None else None
        history_entry = {
            "iteration": runtime_state["iterations_completed"],
            "recorded_at": now_utc(),
            "phase": mission_state.get("current_phase"),
            "directive": outcome.directive.value,
            "decision_id": outcome.decision.decision_id,
            "decision_type": outcome.decision.decision_type,
            "summary": outcome.decision.summary,
            "action_id": outcome.action.action_id if outcome.action is not None else None,
            "branch_id": outcome.branch_record.branch_id if outcome.branch_record is not None else None,
            "outcome_status": raw_outcome_status,
            "mission_status": mission_state.get("status"),
        }
        _record_history(runtime_root_path, history_entry)
        _write_state(
            resolved_state_path,
            mission_state,
            runtime_state,
            contract=contract,
            evidence_snapshot=evidence_payload,
            decision_payload=payloads["decision"],
            branch_payload=payloads.get("branch_record"),
            action_payload=action_payload,
            executor_payload=executor_payload,
        )
        if outcome.directive == MissionDecisionDirective.COMPLETE:
            refreshed_package = _refresh_completed_mission_package(resolved_state_path, mission_state)
            if isinstance(refreshed_package, dict):
                mission_state["mission_package"] = _jsonify(refreshed_package)
                _write_state(
                    resolved_state_path,
                    mission_state,
                    runtime_state,
                    contract=contract,
                )
        if runtime_state["status"] in _TERMINAL_RUNTIME_STATUSES:
            break

    if runtime_state["status"] == "running" and runtime_state["iterations_completed"] >= int(max_iterations):
        mission_state = load_mission_state(resolved_state_path)
        _stop_status(
            mission_state,
            runtime_state=runtime_state,
            status="max-iterations",
            reason=f"Stopped after reaching the bounded mission-runtime limit of {max_iterations} iterations.",
        )
        contract = _outer_loop_contract(resolved_state_path, mission_state)
        _record_ledger(
            resolved_state_path,
            mission_state=mission_state,
            runtime_root=runtime_root_path,
            contract=contract,
            kind="mission-runtime-stop",
            status="max-iterations",
            summary=runtime_state["terminal_reason"],
            metadata={"max_iterations": max_iterations},
        )
        _write_state(resolved_state_path, mission_state, runtime_state, contract=contract)

    contract = _outer_loop_contract(resolved_state_path, load_mission_state(resolved_state_path))
    return {
        "status": runtime_state["status"],
        "iterations_completed": runtime_state["iterations_completed"],
        "runtime_root": runtime_root_path,
        "state_path": _runtime_state_path(runtime_root_path),
        "history_path": _runtime_history_path(runtime_root_path),
        "summary_json_path": _runtime_summary_json_path(runtime_root_path),
        "summary_markdown_path": _runtime_summary_md_path(runtime_root_path),
        "mission_state_path": resolved_state_path,
        "terminal_reason": runtime_state.get("terminal_reason"),
        "mission_memory_path": Path(contract["mission_memory_path"]),
        "experiment_ledger_path": Path(contract["experiment_ledger_path"]),
        "research_memory_events_path": Path(contract["research_memory_events_path"]),
        "research_memory_index_path": Path(contract["research_memory_index_path"]),
    }
