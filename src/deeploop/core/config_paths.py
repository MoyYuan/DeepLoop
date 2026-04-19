from __future__ import annotations

from pathlib import Path


def resolve_config_path(raw_path: str, *, repo_root: Path | None, config_path: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate
    if repo_root is not None:
        return (repo_root / raw_path).resolve()
    return (config_path.parent / raw_path).resolve()


def infer_repo_root_from_configs(config_path: Path) -> Path | None:
    for parent in config_path.parents:
        if parent.name == "configs":
            return parent.parent
    return None


__all__ = ["infer_repo_root_from_configs", "resolve_config_path"]
