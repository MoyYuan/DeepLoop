"""Shared canonical utility functions used across the DeepLoop codebase.

These replace duplicated private helpers that previously lived in individual
modules.  Import from here instead of re-defining locally.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence


def slugify(value: str) -> str:
    """Canonical slug: lowercase alphanumeric tokens joined by hyphens."""
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    return "-".join(token for token in tokens if token) if tokens else value.lower().replace(" ", "-")


def is_relative_to(path: Path, parent: Path) -> bool:
    """Return True when *path* is a descendant of *parent*."""
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def build_command(command: Sequence[str], env_name: str | None) -> list[str]:
    """Wrap *command* for execution, optionally via ``conda run``."""
    if env_name:
        return ["conda", "run", "-n", env_name, *command]
    return list(command)


def dedupe_strings(values: Sequence[str]) -> list[str]:
    """Return *values* with duplicates removed, preserving order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def normalize_strings(raw: Any) -> list[str]:
    """Flatten *raw* into a deduplicated, ordered list of non-empty strings.

    Handles ``str``, ``Path``, ``list``, ``tuple``, ``set``, and ``None``.
    """
    if raw is None:
        return []
    if isinstance(raw, (str, Path)):
        value = str(raw).strip()
        return [value] if value else []
    if isinstance(raw, list | tuple | set):
        result: list[str] = []
        for item in raw:
            result.extend(normalize_strings(item))
        return dedupe_strings(result)
    return [str(raw)]


def normalize_list_like(raw: object) -> list[str]:
    """Convert a scalar or iterable into a flat list of strings."""
    if raw is None:
        return []
    if isinstance(raw, (str, Path)):
        return [str(raw)]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []
