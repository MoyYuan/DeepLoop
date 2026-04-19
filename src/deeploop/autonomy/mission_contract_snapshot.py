from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from deeploop.autonomy.gate_taxonomy import load_gate_policy, resolve_gate_contract
from deeploop.autonomy.mission_autonomy import (
    STATE_MACHINE_PATH,
    build_outer_loop_contract,
    load_mission_outer_loop_policy,
    resolve_phase_contract,
)
from deeploop.core.structured_io import load_json_object, load_yaml_mapping, write_json_object

MISSION_CONTRACT_SNAPSHOT_SCHEMA_VERSION = 1
MISSION_CONTRACT_SNAPSHOT_FILE = "mission_contract_snapshot.json"


def mission_contract_snapshot_path(mission_root: Path) -> Path:
    return mission_root / "contracts" / MISSION_CONTRACT_SNAPSHOT_FILE


def build_mission_contract_snapshot(
    mission_root: Path,
    *,
    mode: str,
    outer_loop_contract: Mapping[str, Any] | None = None,
    outer_loop_policy: Mapping[str, Any] | None = None,
    gates_policy: Mapping[str, Any] | None = None,
    state_machine: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_outer_loop_policy = dict(outer_loop_policy or load_mission_outer_loop_policy())
    resolved_gates_policy = dict(gates_policy or load_gate_policy())
    resolved_state_machine = dict(state_machine or load_yaml_mapping(STATE_MACHINE_PATH))
    snapshot_path = mission_contract_snapshot_path(mission_root)

    contract = dict(outer_loop_contract or {})
    resolved_mode = str(contract.get("mode") or mode or "").strip()
    if not contract:
        gate_contract = resolve_gate_contract(mode=resolved_mode or mode, gates_policy=resolved_gates_policy)
        contract = build_outer_loop_contract(
            mission_root,
            mode=mode,
            policy=resolved_outer_loop_policy,
            gate_contract=gate_contract,
        )
        resolved_mode = str(contract.get("mode") or mode or "").strip()
    gate_contract = resolve_gate_contract(mode=resolved_mode or mode, gates_policy=resolved_gates_policy)
    contract["contract_snapshot_path"] = str(snapshot_path)

    return {
        "schema_version": MISSION_CONTRACT_SNAPSHOT_SCHEMA_VERSION,
        "mission_root": str(mission_root),
        "mode": resolved_mode or str(mode),
        "snapshot_path": str(snapshot_path),
        "outer_loop_contract": contract,
        "outer_loop_policy": resolved_outer_loop_policy,
        "gates_policy": resolved_gates_policy,
        "gate_contract": gate_contract,
        "state_machine": resolved_state_machine,
    }


def materialize_mission_contract_snapshot(
    mission_root: Path,
    *,
    mode: str,
    outer_loop_contract: Mapping[str, Any] | None = None,
    outer_loop_policy: Mapping[str, Any] | None = None,
    gates_policy: Mapping[str, Any] | None = None,
    state_machine: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = build_mission_contract_snapshot(
        mission_root,
        mode=mode,
        outer_loop_contract=outer_loop_contract,
        outer_loop_policy=outer_loop_policy,
        gates_policy=gates_policy,
        state_machine=state_machine,
    )
    write_json_object(mission_contract_snapshot_path(mission_root), snapshot)
    return snapshot


def load_mission_contract_snapshot(path: Path) -> dict[str, Any]:
    return load_json_object(path)


def resolve_contract_snapshot_path(
    *,
    mission_root: Path | None = None,
    mission_state: Mapping[str, Any] | None = None,
) -> Path | None:
    if isinstance(mission_state, Mapping):
        contract_snapshot = mission_state.get("contract_snapshot")
        if isinstance(contract_snapshot, Mapping):
            raw_path = contract_snapshot.get("path") or contract_snapshot.get("snapshot_path")
            if isinstance(raw_path, str) and raw_path.strip():
                return Path(raw_path).expanduser().resolve()
        outer_loop = mission_state.get("outer_loop")
        if isinstance(outer_loop, Mapping):
            raw_path = outer_loop.get("contract_snapshot_path")
            if isinstance(raw_path, str) and raw_path.strip():
                return Path(raw_path).expanduser().resolve()
    if mission_root is None:
        return None
    candidate = mission_contract_snapshot_path(mission_root)
    return candidate if candidate.exists() else None


def load_mission_contract_snapshot_for_state(
    mission_state: Mapping[str, Any] | None,
    *,
    mission_root: Path | None = None,
) -> dict[str, Any] | None:
    snapshot_path = resolve_contract_snapshot_path(mission_root=mission_root, mission_state=mission_state)
    if snapshot_path is None or not snapshot_path.exists():
        return None
    return load_mission_contract_snapshot(snapshot_path)


def resolve_phase_contract_for_state(
    current_phase: str,
    *,
    mission_state: Mapping[str, Any] | None,
    mission_root: Path | None = None,
) -> dict[str, Any]:
    snapshot = load_mission_contract_snapshot_for_state(mission_state, mission_root=mission_root)
    if isinstance(snapshot, Mapping):
        state_machine = snapshot.get("state_machine")
        if isinstance(state_machine, Mapping):
            return resolve_phase_contract(current_phase, state_machine=state_machine)
    return resolve_phase_contract(current_phase)


__all__ = [
    "MISSION_CONTRACT_SNAPSHOT_FILE",
    "MISSION_CONTRACT_SNAPSHOT_SCHEMA_VERSION",
    "build_mission_contract_snapshot",
    "load_mission_contract_snapshot",
    "load_mission_contract_snapshot_for_state",
    "materialize_mission_contract_snapshot",
    "mission_contract_snapshot_path",
    "resolve_contract_snapshot_path",
    "resolve_phase_contract_for_state",
]
