from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from deeploop.core.structured_io import load_json_object, write_json_object

MISSION_STATE_SCHEMA_VERSION = 2


def migrate_mission_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    state = dict(payload)
    schema_version = state.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 1:
        state["schema_version"] = MISSION_STATE_SCHEMA_VERSION
    else:
        state["schema_version"] = max(schema_version, MISSION_STATE_SCHEMA_VERSION)

    current_phase = state.get("current_phase")
    if "completed_phases" not in state or not isinstance(state.get("completed_phases"), list):
        state["completed_phases"] = []
    if "phase_history" not in state or not isinstance(state.get("phase_history"), list):
        state["phase_history"] = [str(current_phase)] if isinstance(current_phase, str) and current_phase else []

    outer_loop = state.get("outer_loop")
    if isinstance(outer_loop, Mapping):
        normalized_outer_loop = dict(outer_loop)
        if "mode" not in normalized_outer_loop and isinstance(state.get("mode"), str):
            normalized_outer_loop["mode"] = str(state["mode"])
        state["outer_loop"] = normalized_outer_loop
    return state


def load_mission_state(path: Path) -> dict[str, Any]:
    return migrate_mission_state(load_json_object(path))


def write_mission_state(path: Path, payload: Mapping[str, Any]) -> None:
    write_json_object(path, migrate_mission_state(payload))


__all__ = [
    "MISSION_STATE_SCHEMA_VERSION",
    "load_mission_state",
    "migrate_mission_state",
    "write_mission_state",
]
