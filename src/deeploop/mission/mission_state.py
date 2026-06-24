from __future__ import annotations

import fcntl
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from deeploop.core.structured_io import load_json_object, write_json_object
from deeploop.mission.mission_summary import sync_mission_summary_for_state_path

MISSION_STATE_SCHEMA_VERSION = 2
_MISSION_STATE_LOCK_TIMEOUT = 5  # seconds


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


def _acquire_state_lock(path: Path, timeout: int = _MISSION_STATE_LOCK_TIMEOUT) -> int | None:
    """Acquire an exclusive advisory lock on *path*, blocking up to *timeout* seconds.

    Returns the open file descriptor (so the caller can release it), or
    ``None`` if the lock could not be acquired within the timeout.
    """
    deadline = time.monotonic() + timeout
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a", encoding="utf-8")
    while True:
        try:
            fcntl.lockf(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle.fileno()
        except (BlockingIOError, OSError):
            if time.monotonic() >= deadline:
                try:
                    handle.close()
                except Exception:
                    pass
                return None
            time.sleep(0.1)


def _release_state_lock(handle_fd: int) -> None:
    """Release an advisory lock previously acquired by :func:`_acquire_state_lock`."""
    try:
        fcntl.lockf(handle_fd, fcntl.LOCK_UN)
    except Exception:
        pass


def load_mission_state(path: Path) -> dict[str, Any]:
    return migrate_mission_state(load_json_object(path))


def write_mission_state(path: Path, payload: Mapping[str, Any]) -> None:
    migrated_payload = migrate_mission_state(payload)
    lock_fd = _acquire_state_lock(path)
    if lock_fd is None:
        print(
            f"[deeploop] WARNING: Could not acquire lock on `{path}` "
            f"within {_MISSION_STATE_LOCK_TIMEOUT}s; skipping write to avoid "
            f"corrupting concurrent state.",
            file=sys.stderr,
        )
        return
    try:
        write_json_object(path, migrated_payload)
        sync_mission_summary_for_state_path(path, migrated_payload)
    finally:
        _release_state_lock(lock_fd)


__all__ = [
    "MISSION_STATE_SCHEMA_VERSION",
    "load_mission_state",
    "migrate_mission_state",
    "write_mission_state",
]
