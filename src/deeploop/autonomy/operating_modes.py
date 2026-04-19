from __future__ import annotations

from typing import Any

DEFAULT_OPERATING_MODE = "sandboxed-yolo"
CANONICAL_OPERATING_MODES = frozenset({"human-directed", "sandboxed-yolo", "managed"})
AUTONOMOUS_OPERATING_MODES = frozenset({"sandboxed-yolo", "managed"})


def _normalized_mode_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text


def resolve_operating_mode(
    mode: str | None,
    *,
    default: str = DEFAULT_OPERATING_MODE,
 ) -> str:
    requested = _normalized_mode_name(mode)
    if not requested or requested == "default":
        requested = _normalized_mode_name(default) or DEFAULT_OPERATING_MODE
    if requested not in CANONICAL_OPERATING_MODES:
        supported = ", ".join(sorted(CANONICAL_OPERATING_MODES))
        raise ValueError(f"Unsupported operating mode `{requested}`. Supported modes: {supported}.")
    return requested


def canonical_operating_mode(
    mode: str | None,
    *,
    default: str = DEFAULT_OPERATING_MODE,
) -> str:
    return resolve_operating_mode(mode, default=default)


def is_autonomous_operating_mode(
    mode: str | None,
    *,
    default: str = DEFAULT_OPERATING_MODE,
) -> bool:
    canonical = canonical_operating_mode(mode, default=default)
    return canonical in AUTONOMOUS_OPERATING_MODES


__all__ = [
    "AUTONOMOUS_OPERATING_MODES",
    "CANONICAL_OPERATING_MODES",
    "DEFAULT_OPERATING_MODE",
    "canonical_operating_mode",
    "is_autonomous_operating_mode",
    "resolve_operating_mode",
]
