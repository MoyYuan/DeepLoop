from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from deeploop.core.ledger import append_jsonl, now_utc
from deeploop.core.structured_io import json_safe_value, load_json_object, load_jsonl_objects, write_json_object
from deeploop.core.shared import normalize_strings as _normalize_strings, resolved_contract_path, slugify
from deeploop.mission._constants import TERMINAL_BRANCH_STATUSES as _TERMINAL_BRANCH_STATUSES
from deeploop.research.indexed_memory import (
    ensure_research_memory_contract,
    record_research_memory_entry,
    retrieve_research_memory,
)

DEFAULT_MISSION_MEMORY_FILE = "mission_memory.json"
DEFAULT_MISSION_EXPERIMENT_LEDGER_FILE = "mission_experiments.jsonl"
_SNAPSHOT_HISTORY_LIMIT = 16

def _jsonify(value: Any) -> Any:
    return json_safe_value(value)

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback

    if isinstance(raw, str) and raw.strip():
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = mission_root / path
    else:
        path = mission_root / default_name
    return path.resolve()

def build_mission_memory_contract(
    mission_root: Path,
    *,
    record_files: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    record_files = record_files if isinstance(record_files, Mapping) else {}
    mission_memory_path = resolved_contract_path(
        mission_root,
        record_files.get("mission_memory"),
        default_name=DEFAULT_MISSION_MEMORY_FILE,
    )
    experiment_ledger_path = resolved_contract_path(
        mission_root,
        record_files.get("mission_experiments"),
        default_name=DEFAULT_MISSION_EXPERIMENT_LEDGER_FILE,
    )
    return {
        "mission_memory_path": str(mission_memory_path),
        "experiment_ledger_path": str(experiment_ledger_path),
    }

def ensure_mission_memory_contract(
    mission_root: Path,
    *,
    contract: dict[str, Any] | None = None,
    record_files: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    built = build_mission_memory_contract(mission_root, record_files=record_files)
    resolved = {
        "mission_memory_path": str(
            resolved_contract_path(
                mission_root,
                (contract or {}).get("mission_memory_path"),
                default_name=Path(built["mission_memory_path"]).name,
            )
        ),
        "experiment_ledger_path": str(
            resolved_contract_path(
                mission_root,
                (contract or {}).get("experiment_ledger_path"),
                default_name=Path(built["experiment_ledger_path"]).name,
            )
        ),
    }
    if contract is not None:
        contract.update(resolved)
    memory_path = Path(resolved["mission_memory_path"])
    ledger_path = Path(resolved["experiment_ledger_path"])
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if not memory_path.exists():
        memory_path.write_text("{}\n", encoding="utf-8")
    ledger_path.touch(exist_ok=True)
    return resolved

def append_unique_jsonl(path: Path, payload: dict[str, Any], *, identity_field: str | None = None) -> None:
    if identity_field is not None:
        identity = str(payload.get(identity_field) or "").strip()
        if identity:
            for record in load_jsonl_objects(path, missing_ok=True):
                if str(record.get(identity_field) or "").strip() == identity:
                    return
    append_jsonl(path, payload)

def append_mission_experiment_entry(
    mission_state_path: Path,
    mission_id: str,
    *,
    contract: dict[str, Any],
    entry_id: str,
    kind: str,
    status: str,
    summary: str,
    phase: str | None = None,
    action_id: str | None = None,
    branch_id: str | None = None,
    executor_id: str | None = None,
    output_paths: list[str] | None = None,
    artifact_paths: list[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    mission_root = mission_state_path.parent
    paths = ensure_mission_memory_contract(mission_root, contract=contract)
    payload = {
        "schema_version": 1,
        "entry_id": entry_id,
        "recorded_at": now_utc(),
        "mission_id": mission_id,
        "kind": kind,
        "status": status,
        "summary": summary,
        "phase": phase,
        "action_id": action_id,
        "branch_id": branch_id,
        "executor_id": executor_id,
        "output_paths": _normalize_strings(output_paths),
        "artifact_paths": _normalize_strings(artifact_paths),
        "metadata": _jsonify(dict(metadata or {})),
    }
    append_unique_jsonl(Path(paths["experiment_ledger_path"]), payload, identity_field="entry_id")
    _record_experiment_research_memory(mission_state_path, contract=contract, experiment_entry=payload)
    return payload

def _branch_registry(
    mission_state: Mapping[str, Any],
    *,
    branch_log_path: Path | None,
    existing: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    existing_registry = existing.get("branch_registry")
    if isinstance(existing_registry, Mapping):
        for branch_id, payload in existing_registry.items():
            if isinstance(payload, Mapping):
                registry[str(branch_id)] = dict(payload)
    if branch_log_path is not None:
        for record in load_jsonl_objects(branch_log_path, missing_ok=True):
            branch_id = str(record.get("branch_id") or "").strip()
            if branch_id:
                registry[branch_id] = record
    else:
        for record in mission_state.get("branch_records") or []:
            if not isinstance(record, Mapping):
                continue
            branch_id = str(record.get("branch_id") or "").strip()
            if branch_id:
                registry[branch_id] = dict(record)
    return {branch_id: registry[branch_id] for branch_id in sorted(registry)}

def _active_branch_ids(branch_registry: Mapping[str, Mapping[str, Any]]) -> list[str]:
    active: list[str] = []
    for branch_id, payload in branch_registry.items():
        status = str(payload.get("status") or "").strip()
        if branch_id and status not in _TERMINAL_BRANCH_STATUSES:
            active.append(branch_id)
    return active

def _evidence_snapshot_entry(
    mission_state: Mapping[str, Any],
    *,
    evidence_snapshot: Mapping[str, Any] | None,
    decision_payload: Mapping[str, Any] | None,
    branch_registry: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(decision_payload, Mapping):
        return None
    decision_id = str(decision_payload.get("decision_id") or "").strip()
    snapshot_id = decision_id or f"snapshot-{now_utc()}"
    produced_outputs = _normalize_strings(
        (evidence_snapshot or {}).get("produced_outputs")
        or mission_state.get("produced_outputs")
        or mission_state.get("phase_outputs")
    )
    blockers = _normalize_strings((evidence_snapshot or {}).get("blockers") or mission_state.get("blocked_reasons"))
    recent_failures = _normalize_strings((evidence_snapshot or {}).get("recent_failures") or mission_state.get("recent_failures"))
    failure_count = int(
        (evidence_snapshot or {}).get("failure_count", mission_state.get("failure_count", 0)) or 0
    )
    result = decision_payload.get("result") if isinstance(decision_payload.get("result"), Mapping) else {}
    return {
        "snapshot_id": snapshot_id,
        "recorded_at": now_utc(),
        "decision_id": decision_id or None,
        "decision_type": str(decision_payload.get("decision_type") or ""),
        "decision_status": str(result.get("status") or ""),
        "phase": str(decision_payload.get("phase") or mission_state.get("current_phase") or ""),
        "summary": str(decision_payload.get("summary") or "Captured mission evidence snapshot."),
        "selected_action_ids": _normalize_strings(decision_payload.get("selected_action_ids")),
        "selected_branch_ids": _normalize_strings(decision_payload.get("selected_branch_ids")),
        "produced_outputs": produced_outputs,
        "blockers": blockers,
        "recent_failures": recent_failures,
        "failure_count": failure_count,
        "active_branch_ids": _active_branch_ids(branch_registry),
    }

def _merge_evidence_snapshots(existing: Any, candidate: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    snapshots = [dict(item) for item in existing or [] if isinstance(item, Mapping)]
    if candidate is None:
        return snapshots[-_SNAPSHOT_HISTORY_LIMIT:]
    candidate_id = str(candidate.get("snapshot_id") or "").strip()
    replaced = False
    for index, snapshot in enumerate(snapshots):
        if str(snapshot.get("snapshot_id") or "").strip() == candidate_id:
            snapshots[index] = dict(candidate)
            replaced = True
            break
    if not replaced:
        snapshots.append(dict(candidate))
    return snapshots[-_SNAPSHOT_HISTORY_LIMIT:]

def _open_questions(
    mission_state: Mapping[str, Any],
    *,
    existing: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_questions = mission_state.get("open_questions")
    if raw_questions is None:
        raw_questions = existing.get("open_questions", [])
    if not isinstance(raw_questions, list | tuple):
        raw_questions = [raw_questions]
    phase = str(mission_state.get("current_phase") or "")
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(raw_questions, start=1):
        if isinstance(item, Mapping):
            question = str(item.get("question") or item.get("summary") or "").strip()
            if not question:
                continue
            entries.append(
                {
                    "question_id": str(item.get("question_id") or slugify(question, fallback=f"question-{index}")),
                    "question": question,
                    "status": str(item.get("status") or "open"),
                    "phase": str(item.get("phase") or phase),
                    "source": str(item.get("source") or "mission-state"),
                    "updated_at": str(item.get("updated_at") or now_utc()),
                }
            )
            continue
        question = str(item).strip()
        if not question:
            continue
        entries.append(
            {
                "question_id": slugify(question, fallback=f"question-{index}"),
                "question": question,
                "status": "open",
                "phase": phase,
                "source": "mission-state",
                "updated_at": now_utc(),
            }
        )
    return entries

def _blocked_items(mission_state: Mapping[str, Any]) -> list[dict[str, Any]]:
    phase = str(mission_state.get("current_phase") or "")
    blocked_items: list[dict[str, Any]] = []
    for index, reason in enumerate(_normalize_strings(mission_state.get("blocked_reasons")), start=1):
        blocked_items.append(
            {
                "item_id": f"mission-blocked-{index}",
                "kind": "mission",
                "phase": phase,
                "status": str(mission_state.get("status") or "blocked"),
                "summary": reason,
            }
        )
    next_actions = mission_state.get("next_actions")
    actions = next_actions.get("actions") if isinstance(next_actions, Mapping) else []
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, Mapping):
                continue
            status = str(action.get("status") or "").strip()
            if status not in {"blocked", "failed"}:
                continue
            action_id = str(action.get("action_id") or action.get("task") or "blocked-action")
            notes = _normalize_strings(action.get("notes"))
            blocked_items.append(
                {
                    "item_id": f"action-{action_id}",
                    "kind": "action",
                    "action_id": str(action.get("action_id") or ""),
                    "branch_id": str(action.get("branch_id") or ""),
                    "phase": str(action.get("phase") or phase),
                    "status": status,
                    "summary": notes[0] if notes else str(action.get("task") or action_id),
                }
            )
    return blocked_items

def _finding_summary(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        summary = line.strip()
        if summary:
            return summary
    return path.stem.replace("-", " ")

def _research_query_text(mission_state: Mapping[str, Any]) -> str:
    query_parts = [
        str(mission_state.get("title") or ""),
        str(mission_state.get("summary") or ""),
        str(mission_state.get("objective") or ""),
        str(mission_state.get("current_phase") or ""),
    ]
    for item in mission_state.get("open_questions") or []:
        if isinstance(item, Mapping):
            query_parts.append(str(item.get("question") or item.get("summary") or ""))
        else:
            query_parts.append(str(item))
    return " ".join(part.strip() for part in query_parts if str(part).strip())

def _record_experiment_research_memory(
    mission_state_path: Path,
    *,
    contract: Mapping[str, Any],
    experiment_entry: Mapping[str, Any],
) -> None:
    ensure_research_memory_contract(contract=dict(contract))
    mission_id = str(experiment_entry.get("mission_id") or "").strip()
    kind = str(experiment_entry.get("kind") or "").strip()
    metadata = experiment_entry.get("metadata") if isinstance(experiment_entry.get("metadata"), Mapping) else {}
    provenance = {
        "source_kind": kind or "mission-experiment",
        "mission_id": mission_id or None,
        "recorded_at": str(experiment_entry.get("recorded_at") or now_utc()),
        "source_paths": [
            str(mission_state_path),
            str(contract["experiment_ledger_path"]),
            *[
                *(_normalize_strings(experiment_entry.get("output_paths"))),
                *(_normalize_strings(experiment_entry.get("artifact_paths"))),
            ],
        ],
        "source_entry_id": str(experiment_entry.get("entry_id") or "") or None,
        "decision_id": str(metadata.get("decision_id") or "") or None,
        "action_id": str(experiment_entry.get("action_id") or "") or None,
        "branch_id": str(experiment_entry.get("branch_id") or "") or None,
    }
    if kind == "promoted-finding":
        artifact_paths = _normalize_strings(experiment_entry.get("artifact_paths"))
        finding_id = str(metadata.get("finding_id") or (Path(artifact_paths[0]).stem if artifact_paths else "")).strip()
        record_research_memory_entry(
            {
                "entity_type": "critique",
                "entity_id": finding_id or str(experiment_entry.get("entry_id") or ""),
                "mission_id": mission_id or None,
                "status": str(experiment_entry.get("status") or "recorded"),
                "summary": str(experiment_entry.get("summary") or ""),
                "related_ids": [str(experiment_entry.get("action_id") or ""), str(experiment_entry.get("branch_id") or "")],
                "tags": ["promoted-finding", str(experiment_entry.get("phase") or "")],
                "payload": {
                    "critique_id": finding_id or str(experiment_entry.get("entry_id") or ""),
                    "manifest_id": str(metadata.get("manifest_id") or experiment_entry.get("entry_id") or ""),
                    "finding": str(experiment_entry.get("summary") or ""),
                    "recommendation": str(
                        metadata.get("recommendation")
                        or "Reuse this grounded finding when the mission scope or failure mode matches."
                    ),
                    "claim_state": str(metadata.get("claim_state") or "promoted"),
                    "artifact_paths": artifact_paths,
                },
                "provenance": provenance,
                "promotion": {
                    "status": "promoted",
                    "promoted_at": str(experiment_entry.get("recorded_at") or now_utc()),
                    "source_entry_ids": [str(experiment_entry.get("entry_id") or "")],
                },
            },
            contract=dict(contract),
        )
        return
    record_research_memory_entry(
        {
            "entity_type": "experiment",
            "entity_id": str(experiment_entry.get("entry_id") or ""),
            "mission_id": mission_id or None,
            "status": str(experiment_entry.get("status") or "recorded"),
            "summary": str(experiment_entry.get("summary") or ""),
            "related_ids": [
                str(experiment_entry.get("action_id") or ""),
                str(experiment_entry.get("branch_id") or ""),
                str(metadata.get("decision_id") or ""),
            ],
            "tags": [kind, str(experiment_entry.get("phase") or ""), str(experiment_entry.get("executor_id") or "")],
            "payload": {
                "manifest_id": str(metadata.get("manifest_id") or experiment_entry.get("entry_id") or ""),
                "hypothesis_id": str(
                    metadata.get("hypothesis_id")
                    or experiment_entry.get("branch_id")
                    or experiment_entry.get("action_id")
                    or mission_id
                    or ""
                ),
                "resource_tier": str(metadata.get("resource_tier") or "bounded"),
                "execution_profile": str(
                    metadata.get("execution_profile")
                    or experiment_entry.get("executor_id")
                    or metadata.get("executor_status")
                    or "unspecified"
                ),
                "result_state": str(experiment_entry.get("status") or "recorded"),
                "kind": kind,
                "phase": str(experiment_entry.get("phase") or ""),
                "metadata": _jsonify(dict(metadata)),
                "output_paths": _normalize_strings(experiment_entry.get("output_paths")),
                "artifact_paths": _normalize_strings(experiment_entry.get("artifact_paths")),
            },
            "provenance": provenance,
            "promotion": {
                "status": "candidate",
                "promoted_at": None,
                "source_entry_ids": [str(experiment_entry.get("entry_id") or "")],
            },
        },
        contract=dict(contract),
    )

def _record_mission_research_memory(
    mission_state_path: Path,
    *,
    mission_state: Mapping[str, Any],
    contract: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> None:
    mission_id = str(mission_state.get("mission_id") or "").strip()
    promoted_findings = snapshot.get("promoted_findings") if isinstance(snapshot.get("promoted_findings"), list) else []
    record_research_memory_entry(
        {
            "entity_type": "mission",
            "entity_id": mission_id,
            "mission_id": mission_id,
            "status": str(snapshot.get("mission_status") or mission_state.get("status") or "running"),
            "summary": str(mission_state.get("summary") or mission_state.get("title") or mission_id),
            "related_ids": [item.get("question_id") for item in snapshot.get("open_questions", []) if isinstance(item, Mapping)],
            "tags": [
                str(mission_state.get("mode") or ""),
                str(snapshot.get("current_phase") or ""),
                str(snapshot.get("next_phase") or ""),
            ],
            "payload": {
                "mission_id": mission_id,
                "summary": str(mission_state.get("summary") or ""),
                "constraints": _normalize_strings(
                    mission_state.get("constraints")
                    or mission_state.get("guardrails")
                    or mission_state.get("blocked_reasons")
                ),
                "owner_mode": str((contract or {}).get("mode") or mission_state.get("mode") or ""),
                "current_phase": str(snapshot.get("current_phase") or ""),
                "next_phase": str(snapshot.get("next_phase") or ""),
                "objective": str(mission_state.get("objective") or ""),
                "open_questions": [item.get("question") for item in snapshot.get("open_questions", []) if isinstance(item, Mapping)],
                "blocked_items": [item.get("summary") for item in snapshot.get("blocked_items", []) if isinstance(item, Mapping)],
                "promoted_findings": [item.get("summary") for item in promoted_findings if isinstance(item, Mapping)],
            },
            "provenance": {
                "source_kind": "mission-memory",
                "mission_id": mission_id,
                "recorded_at": str(snapshot.get("updated_at") or now_utc()),
                "source_paths": [
                    str(mission_state_path),
                    str(snapshot.get("mission_state_path") or mission_state_path),
                    str((snapshot.get("paths") or {}).get("mission_memory_path") or ""),
                ],
                "source_entry_id": mission_id,
            },
            "promotion": {
                "status": "promoted" if promoted_findings else "candidate",
                "promoted_at": str(snapshot.get("updated_at") or now_utc()) if promoted_findings else None,
                "source_entry_ids": [item.get("finding_id") for item in promoted_findings if isinstance(item, Mapping)],
            },
        },
        contract=dict(contract),
    )

def _promoted_findings(
    mission_root: Path,
    *,
    experiment_entries: list[dict[str, Any]],
    existing: Mapping[str, Any],
) -> list[dict[str, Any]]:
    findings: dict[str, dict[str, Any]] = {}
    existing_findings = existing.get("promoted_findings")
    if isinstance(existing_findings, list):
        for item in existing_findings:
            if isinstance(item, Mapping):
                finding_id = str(item.get("finding_id") or "").strip()
                if finding_id:
                    findings[finding_id] = dict(item)
    for entry in experiment_entries:
        if str(entry.get("kind") or "") != "promoted-finding":
            continue
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), Mapping) else {}
        artifact_paths = _normalize_strings(entry.get("artifact_paths"))
        finding_path = artifact_paths[0] if artifact_paths else str(metadata.get("finding_path") or "")
        finding_id = str(metadata.get("finding_id") or Path(finding_path).stem or entry.get("entry_id") or "").strip()
        if not finding_id:
            continue
        findings[finding_id] = {
            "finding_id": finding_id,
            "summary": str(entry.get("summary") or ""),
            "claim_state": str(metadata.get("claim_state") or "promoted"),
            "path": finding_path,
            "recorded_at": str(entry.get("recorded_at") or now_utc()),
        }
    findings_root = mission_root / "findings"
    if findings_root.exists():
        for path in sorted(findings_root.glob("*.md")):
            finding_id = path.stem
            findings.setdefault(
                finding_id,
                {
                    "finding_id": finding_id,
                    "summary": _finding_summary(path),
                    "claim_state": "promoted",
                    "path": str(path),
                    "recorded_at": now_utc(),
                },
            )
    return [findings[key] for key in sorted(findings)]

def _completed_phase_outputs(mission_state: Mapping[str, Any]) -> dict[str, list[str]]:
    completed = _normalize_strings(mission_state.get("completed_phases"))
    if str(mission_state.get("status") or "") == "completed":
        current_phase = str(mission_state.get("current_phase") or "").strip()
        if current_phase and current_phase not in completed:
            completed.append(current_phase)
    phase_outputs = mission_state.get("phase_outputs_by_phase")
    outputs: dict[str, list[str]] = {}
    for phase in completed:
        values = _normalize_strings(phase_outputs.get(phase)) if isinstance(phase_outputs, Mapping) else []
        if not values and phase == str(mission_state.get("current_phase") or ""):
            values = _normalize_strings(mission_state.get("produced_outputs") or mission_state.get("phase_outputs"))
        outputs[phase] = values
    return outputs

def sync_mission_memory(
    mission_state_path: Path,
    mission_state: Mapping[str, Any],
    *,
    contract: dict[str, Any],
    runtime_state: Mapping[str, Any] | None = None,
    evidence_snapshot: Mapping[str, Any] | None = None,
    decision_payload: Mapping[str, Any] | None = None,
    branch_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    mission_root = mission_state_path.parent
    resolved_paths = ensure_mission_memory_contract(mission_root, contract=contract)
    ensure_research_memory_contract(contract=contract)
    memory_path = Path(resolved_paths["mission_memory_path"])
    experiment_path = Path(resolved_paths["experiment_ledger_path"])
    existing = load_json_object(memory_path)
    branch_log_path = (
        resolved_contract_path(mission_root, contract.get("branch_log_path"), default_name="mission_branches.jsonl")
        if contract.get("branch_log_path") is not None
        else None
    )
    branch_registry = _branch_registry(mission_state, branch_log_path=branch_log_path, existing=existing)
    if isinstance(branch_payload, Mapping):
        branch_id = str(branch_payload.get("branch_id") or "").strip()
        if branch_id:
            branch_registry = dict(branch_registry)
            branch_registry[branch_id] = dict(branch_payload)
            branch_registry = {key: branch_registry[key] for key in sorted(branch_registry)}
    experiment_entries = load_jsonl_objects(experiment_path, missing_ok=True)
    latest_decision = dict(existing.get("latest_decision") or {}) if isinstance(existing.get("latest_decision"), Mapping) else {}
    if isinstance(decision_payload, Mapping):
        latest_decision = {
            "decision_id": decision_payload.get("decision_id"),
            "decision_type": decision_payload.get("decision_type"),
            "phase": decision_payload.get("phase"),
            "summary": decision_payload.get("summary"),
            "selected_action_ids": _normalize_strings(decision_payload.get("selected_action_ids")),
            "selected_branch_ids": _normalize_strings(decision_payload.get("selected_branch_ids")),
            "result": _jsonify(decision_payload.get("result", {})),
        }
    latest_experiment = {}
    for entry in reversed(experiment_entries):
        if str(entry.get("kind") or "") != "evidence-snapshot":
            latest_experiment = dict(entry)
            break
    if not latest_experiment and isinstance(existing.get("latest_experiment"), Mapping):
        latest_experiment = dict(existing.get("latest_experiment") or {})
    snapshot = {
        "schema_version": 1,
        "mission_id": str(mission_state.get("mission_id") or ""),
        "updated_at": now_utc(),
        "mission_state_path": str(mission_state_path),
        "mission_status": str(mission_state.get("status") or ""),
        "current_phase": str(mission_state.get("current_phase") or ""),
        "next_phase": str(mission_state.get("next_phase") or ""),
        "paths": {
            "mission_memory_path": str(memory_path),
            "experiment_ledger_path": str(experiment_path),
            "research_memory_events_path": str(contract.get("research_memory_events_path") or ""),
            "research_memory_index_path": str(contract.get("research_memory_index_path") or ""),
            "decision_log_path": str(contract.get("decision_log_path") or ""),
            "branch_log_path": str(contract.get("branch_log_path") or ""),
            "ledger_path": str(mission_root / "ledger.jsonl"),
        },
        "runtime": _jsonify(dict(runtime_state or {})) if runtime_state else {},
        "branch_registry": branch_registry,
        "evidence_snapshots": _merge_evidence_snapshots(
            existing.get("evidence_snapshots"),
            _evidence_snapshot_entry(
                mission_state,
                evidence_snapshot=evidence_snapshot,
                decision_payload=decision_payload,
                branch_registry=branch_registry,
            ),
        ),
        "open_questions": _open_questions(mission_state, existing=existing),
        "blocked_items": _blocked_items(mission_state),
        "promoted_findings": _promoted_findings(mission_root, experiment_entries=experiment_entries, existing=existing),
        "completed_phase_outputs": _completed_phase_outputs(mission_state),
        "latest_decision": latest_decision,
        "latest_experiment": latest_experiment,
    }
    _record_mission_research_memory(
        mission_state_path,
        mission_state=mission_state,
        contract=contract,
        snapshot=snapshot,
    )
    related_research = retrieve_research_memory(
        query=_research_query_text(mission_state),
        contract=contract,
        exclude_mission_id=str(mission_state.get("mission_id") or ""),
        promotion_statuses=["promoted", "candidate"],
        limit=5,
    )
    snapshot["retrieved_research_context"] = {
        "query": _research_query_text(mission_state),
        "matches": [
            {
                "entity_type": entry["entity_type"],
                "entity_id": entry["entity_id"],
                "mission_id": entry.get("mission_id"),
                "status": entry["status"],
                "summary": entry["summary"],
                "score": entry["score"],
                "promotion_status": (entry.get("promotion") or {}).get("status"),
                "source_paths": (entry.get("provenance") or {}).get("source_paths", []),
                "updated_at": entry.get("updated_at"),
            }
            for entry in related_research
        ],
    }
    snapshot["counts"] = {
        "branches": len(snapshot["branch_registry"]),
        "evidence_snapshots": len(snapshot["evidence_snapshots"]),
        "open_questions": len(snapshot["open_questions"]),
        "blocked_items": len(snapshot["blocked_items"]),
        "promoted_findings": len(snapshot["promoted_findings"]),
        "completed_phases": len(snapshot["completed_phase_outputs"]),
        "experiment_entries": len(experiment_entries),
        "retrieved_research_matches": len(snapshot["retrieved_research_context"]["matches"]),
    }
    write_json_object(memory_path, snapshot)
    return snapshot
