from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Mapping

from deeploop.autonomy.gate_taxonomy import DEFAULT_GATES_PATH, resolve_gate_contract
from deeploop.autonomy.operating_modes import DEFAULT_OPERATING_MODE, resolve_operating_mode
from deeploop.autonomy.operator_inbox import MISSION_OPERATOR_REQUEST_SCHEMA_PATH, build_operator_inbox_contract
from deeploop.core.paths import REPO_ROOT
from deeploop.core.structured_io import load_json_object, load_yaml_mapping
from deeploop.mission.mission_memory import build_mission_memory_contract
from deeploop.research.indexed_memory import build_research_memory_contract

MISSION_OUTER_LOOP_POLICY_PATH = REPO_ROOT / "configs" / "autonomy" / "mission-outer-loop.yaml"
STATE_MACHINE_PATH = REPO_ROOT / "configs" / "autonomy" / "state-machine.yaml"
MISSION_ACTION_SCHEMA_PATH = REPO_ROOT / "schemas" / "mission-action.schema.json"
MISSION_DECISION_SCHEMA_PATH = REPO_ROOT / "schemas" / "mission-decision.schema.json"
MISSION_BRANCH_RECORD_SCHEMA_PATH = REPO_ROOT / "schemas" / "mission-branch-record.schema.json"


def _load_yaml(path: Path) -> dict[str, Any]:
    return load_yaml_mapping(path)


def _load_json(path: Path) -> dict[str, Any]:
    return load_json_object(path)


def load_mission_outer_loop_policy(path: Path = MISSION_OUTER_LOOP_POLICY_PATH) -> dict[str, Any]:
    return _load_yaml(path)


def _schema_errors(payload: dict[str, Any], schema_path: Path) -> list[str]:
    schema = _load_json(schema_path)
    try:
        import jsonschema
    except ImportError:
        warnings.warn("jsonschema not installed; schema validation is incomplete")
        errors: list[str] = []
        for key in schema.get("required", []):
            if key not in payload:
                errors.append(f"missing field `{key}`")
        return errors

    validator = jsonschema.Draft202012Validator(schema)
    return [
        error.message
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))[:8]
    ]


def validate_mission_action(payload: dict[str, Any]) -> list[str]:
    return _schema_errors(payload, MISSION_ACTION_SCHEMA_PATH)


def validate_mission_decision(payload: dict[str, Any]) -> list[str]:
    return _schema_errors(payload, MISSION_DECISION_SCHEMA_PATH)


def validate_mission_branch_record(payload: dict[str, Any]) -> list[str]:
    return _schema_errors(payload, MISSION_BRANCH_RECORD_SCHEMA_PATH)


def ensure_valid_contract_payload(payload: dict[str, Any], *, kind: str) -> None:
    validators = {
        "mission_action": validate_mission_action,
        "mission_decision": validate_mission_decision,
        "mission_branch_record": validate_mission_branch_record,
    }
    validator = validators[kind]
    errors = validator(payload)
    if errors:
        raise ValueError(f"Invalid {kind}: {'; '.join(errors)}")


def enrich_outer_loop_contract(
    contract: dict[str, Any],
    *,
    mode: str | None = None,
    gate_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    requested_mode = mode or str(contract.get("mode") or DEFAULT_OPERATING_MODE)
    resolved_mode = resolve_operating_mode(requested_mode, default=DEFAULT_OPERATING_MODE)
    resolved_gate_contract = dict(gate_contract or resolve_gate_contract(mode=resolved_mode))
    enriched = dict(contract)
    enriched.setdefault("mode", resolved_mode)
    enriched.setdefault("gate_policy_name", resolved_gate_contract["policy_name"])
    enriched.setdefault("gate_policy_path", str(DEFAULT_GATES_PATH))
    enriched.setdefault("hard_gate_profile", resolved_gate_contract["hard_gate_profile"])
    enriched.setdefault("hard_gate_profile_summary", resolved_gate_contract["hard_gate_profile_summary"])
    enriched.setdefault("hard_gate_risk_classes", list(resolved_gate_contract["hard_gate_risk_classes"]))
    enriched.setdefault("soft_gate_risk_classes", list(resolved_gate_contract["soft_gate_risk_classes"]))
    enriched.setdefault("soft_gate_preferred_actions", list(resolved_gate_contract["soft_gate_preferred_actions"]))
    enriched.setdefault("gate_risk_classes", list(resolved_gate_contract["gate_risk_classes"]))
    return enriched


def build_outer_loop_contract(
    mission_root: Path,
    *,
    mode: str,
    policy: dict[str, Any] | None = None,
    gate_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or load_mission_outer_loop_policy()
    default_mode = str(policy.get("default_mode") or DEFAULT_OPERATING_MODE)
    resolved_mode = resolve_operating_mode(mode, default=default_mode)
    mode_defaults = policy.get("mode_defaults", {})
    selected = mode_defaults.get(resolved_mode, mode_defaults.get("default", {}))
    if not isinstance(selected, dict):
        raise ValueError(f"Invalid mission outer-loop defaults for mode {resolved_mode}")
    record_files = policy.get("record_files", {})
    schema_paths = policy.get("schema_paths", {})
    action_classes = policy.get("action_classes", {})
    memory_contract = build_mission_memory_contract(mission_root, record_files=record_files)
    research_memory_contract = build_research_memory_contract()
    operator_inbox_contract = build_operator_inbox_contract(mission_root, record_files=record_files)
    resolved_gate_contract = dict(gate_contract or resolve_gate_contract(mode=resolved_mode))
    autonomous_action_kinds = [
        action_id
        for action_id, config in action_classes.items()
        if isinstance(config, dict) and not bool(config.get("requires_operator_approval", False))
    ]
    contract = {
        "mode": resolved_mode,
        "policy_name": str(policy.get("policy_name", "deeploop-mission-outer-loop")),
        "policy_path": str(MISSION_OUTER_LOOP_POLICY_PATH),
        "execution_mode": str(selected.get("execution_mode", resolved_mode)),
        "internal_execution": str(selected.get("internal_execution", selected.get("permissions_profile", "human-approved"))),
        "permissions_profile": str(selected.get("permissions_profile", "human-approved")),
        "intervention_profile": str(selected.get("intervention_profile", "step-by-step")),
        "external_publish": str(selected.get("external_publish", "human-review-required")),
        "default_operator_approval": str(selected.get("default_operator_approval", "required")),
        "gate_policy_name": resolved_gate_contract["policy_name"],
        "gate_policy_path": str(DEFAULT_GATES_PATH),
        "hard_gate_profile": resolved_gate_contract["hard_gate_profile"],
        "hard_gate_profile_summary": resolved_gate_contract["hard_gate_profile_summary"],
        "hard_gate_risk_classes": list(resolved_gate_contract["hard_gate_risk_classes"]),
        "soft_gate_risk_classes": list(resolved_gate_contract["soft_gate_risk_classes"]),
        "soft_gate_preferred_actions": list(resolved_gate_contract["soft_gate_preferred_actions"]),
        "gate_risk_classes": list(resolved_gate_contract["gate_risk_classes"]),
        "action_schema": str(REPO_ROOT / str(schema_paths.get("mission_action", MISSION_ACTION_SCHEMA_PATH.relative_to(REPO_ROOT)))),
        "decision_schema": str(REPO_ROOT / str(schema_paths.get("mission_decision", MISSION_DECISION_SCHEMA_PATH.relative_to(REPO_ROOT)))),
        "branch_schema": str(
            REPO_ROOT / str(schema_paths.get("mission_branch_record", MISSION_BRANCH_RECORD_SCHEMA_PATH.relative_to(REPO_ROOT)))
        ),
        "operator_request_schema": str(
            REPO_ROOT / str(schema_paths.get("mission_operator_request", MISSION_OPERATOR_REQUEST_SCHEMA_PATH.relative_to(REPO_ROOT)))
        ),
        "decision_log_path": str(mission_root / str(record_files.get("mission_decisions", "mission_decisions.jsonl"))),
        "branch_log_path": str(mission_root / str(record_files.get("mission_branches", "mission_branches.jsonl"))),
        "mission_memory_path": memory_contract["mission_memory_path"],
        "experiment_ledger_path": memory_contract["experiment_ledger_path"],
        "research_memory_root": research_memory_contract["research_memory_root"],
        "research_memory_registry_path": research_memory_contract["research_memory_registry_path"],
        "research_memory_schema_path": research_memory_contract["research_memory_schema_path"],
        "research_memory_events_path": research_memory_contract["research_memory_events_path"],
        "research_memory_index_path": research_memory_contract["research_memory_index_path"],
        "operator_request_log_path": operator_inbox_contract["operator_request_log_path"],
        "current_operator_request_path": operator_inbox_contract["current_operator_request_path"],
        "branch_statuses": [str(item) for item in policy.get("branch_statuses", [])],
        "recovery_statuses": [str(item) for item in policy.get("recovery_statuses", [])],
        "autonomous_action_kinds": autonomous_action_kinds,
        "mutable_roots": [str(item) for item in policy.get("runtime_ownership", {}).get("mutable_roots", [])],
    }
    return enrich_outer_loop_contract(contract, mode=resolved_mode, gate_contract=resolved_gate_contract)


def resolve_phase_contract(
    current_phase: str,
    path: Path = STATE_MACHINE_PATH,
    *,
    state_machine: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not current_phase:
        return {}
    loaded = dict(state_machine) if isinstance(state_machine, Mapping) else _load_yaml(path)
    states = loaded.get("states")
    if not isinstance(states, list):
        return {}
    transition_defaults = loaded.get("transition_defaults", {})
    transition_metadata = loaded.get("transition_metadata", {})
    per_phase_metadata = transition_metadata.get(current_phase, {}) if isinstance(transition_metadata, dict) else {}
    for state in states:
        if not isinstance(state, dict) or str(state.get("id")) != current_phase:
            continue
        transitions: list[str] = []
        enriched: list[dict[str, str]] = []
        for raw in state.get("transitions", []):
            if isinstance(raw, dict):
                target = str(raw.get("target", "")).strip()
                raw_meta = raw
            else:
                target = str(raw).strip()
                raw_meta = {}
            if not target:
                continue
            transitions.append(target)
            merged: dict[str, Any] = {}
            if isinstance(transition_defaults, dict):
                merged.update(transition_defaults)
            if isinstance(per_phase_metadata, dict):
                maybe_target = per_phase_metadata.get(target)
                if isinstance(maybe_target, dict):
                    merged.update(maybe_target)
            merged.update({key: value for key, value in raw_meta.items() if key != "target"})
            enriched.append(
                {
                    "target": target,
                    "decision_type": str(merged.get("decision_type", "phase-transition")),
                    "branch_status": str(merged.get("branch_status", "active")),
                    "recovery_status": str(merged.get("recovery_status", "not-needed")),
                    "summary": str(merged.get("summary", "")),
                }
            )
        return {
            "outputs": [str(item) for item in state.get("outputs", [])],
            "transitions": transitions,
            "transition_metadata": enriched,
            "terminal_rules": [str(item) for item in loaded.get("terminal_rules", [])],
        }
    return {}


__all__ = [
    "MISSION_ACTION_SCHEMA_PATH",
    "MISSION_BRANCH_RECORD_SCHEMA_PATH",
    "MISSION_DECISION_SCHEMA_PATH",
    "MISSION_OUTER_LOOP_POLICY_PATH",
    "STATE_MACHINE_PATH",
    "build_outer_loop_contract",
    "enrich_outer_loop_contract",
    "ensure_valid_contract_payload",
    "load_mission_outer_loop_policy",
    "resolve_phase_contract",
    "validate_mission_action",
    "validate_mission_branch_record",
    "validate_mission_decision",
]
