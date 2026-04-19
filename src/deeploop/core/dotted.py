from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def get_dotted(payload: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for piece in dotted_path.split("."):
        if not isinstance(current, Mapping) or piece not in current:
            return None
        current = current[piece]
    return current


__all__ = ["get_dotted"]
