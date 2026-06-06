from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from deeploop.autonomy.mission_autonomy import build_outer_loop_contract, enrich_outer_loop_contract
from deeploop.autonomy.mission_contract_snapshot import load_mission_contract_snapshot_for_state
from deeploop.autonomy.gate_taxonomy import DEFAULT_OPERATING_MODE
from deeploop.autonomy.operator_inbox import ensure_operator_inbox_contract
from deeploop.core.ledger import append_jsonl
from deeploop.core.structured_io import load_jsonl_objects
from deeploop.mission.mission_memory import ensure_mission_memory_contract
from deeploop.research.indexed_memory import ensure_research_memory_contract

def _latest_matching_record(path: Path | None, field: str, value: str | None) -> dict[str, Any] | None:
    if path is None or value is None or not path.exists():
        return None
    for record in reversed(load_jsonl_objects(path, missing_ok=True)):
        if str(record.get(field) or "") == value:
            return record
    return None

def _append_contract_record(path: Path, payload: dict[str, Any], *, identity_field: str | None = None) -> None:
    if identity_field is not None:
        identity = payload.get(identity_field)
        if isinstance(identity, str):
            latest = _latest_matching_record(path, identity_field, identity)
            if latest == payload:
                return
    append_jsonl(path, payload)

def _outer_loop_contract(mission_state_path: Path, mission_state: dict[str, Any]) -> dict[str, Any]:
    mission_root = mission_state_path.parent
    snapshot = load_mission_contract_snapshot_for_state(mission_state, mission_root=mission_root)
    existing = mission_state.get("outer_loop")
    if isinstance(existing, dict) and existing.get("decision_log_path") and existing.get("branch_log_path"):
        gate_contract = snapshot.get("gate_contract") if isinstance(snapshot, Mapping) else None
        contract = dict(snapshot.get("outer_loop_contract", {})) if isinstance(snapshot, Mapping) else {}
        contract.update(existing)
        contract = enrich_outer_loop_contract(
            contract,
            mode=str(existing.get("mode") or mission_state.get("mode") or DEFAULT_OPERATING_MODE),
            gate_contract=dict(gate_contract) if isinstance(gate_contract, Mapping) else None,
        )
    else:
        outer_loop_policy = snapshot.get("outer_loop_policy") if isinstance(snapshot, Mapping) else None
        gate_contract = snapshot.get("gate_contract") if isinstance(snapshot, Mapping) else None
        contract = build_outer_loop_contract(
            mission_root,
            mode=str(mission_state.get("mode") or DEFAULT_OPERATING_MODE),
            policy=dict(outer_loop_policy) if isinstance(outer_loop_policy, Mapping) else None,
            gate_contract=dict(gate_contract) if isinstance(gate_contract, Mapping) else None,
        )
        mission_state["outer_loop"] = contract
    if isinstance(snapshot, Mapping) and isinstance(snapshot.get("snapshot_path"), str):
        contract["contract_snapshot_path"] = str(snapshot["snapshot_path"])
    decision_log_path = Path(contract["decision_log_path"]).expanduser().resolve()
    branch_log_path = Path(contract["branch_log_path"]).expanduser().resolve()
    ensure_mission_memory_contract(mission_root, contract=contract)
    ensure_research_memory_contract(contract=contract)
    ensure_operator_inbox_contract(mission_root, contract=contract)
    decision_log_path.parent.mkdir(parents=True, exist_ok=True)
    branch_log_path.parent.mkdir(parents=True, exist_ok=True)
    decision_log_path.touch(exist_ok=True)
    branch_log_path.touch(exist_ok=True)
    contract["decision_log_path"] = str(decision_log_path)
    contract["branch_log_path"] = str(branch_log_path)
    mission_state["outer_loop"] = contract
    return contract
