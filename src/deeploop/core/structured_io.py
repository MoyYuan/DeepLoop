from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    loaded = load_yaml(path)
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_object(path: Path) -> dict[str, Any]:
    loaded = load_json(path)
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected object in {path}")
    return loaded


def load_jsonl(path: Path, *, missing_ok: bool = False) -> list[Any]:
    if missing_ok and not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_jsonl_objects(path: Path, *, missing_ok: bool = False) -> list[dict[str, Any]]:
    return [item for item in load_jsonl(path, missing_ok=missing_ok) if isinstance(item, dict)]


def load_structured_mapping(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return load_yaml_mapping(path)
    if suffix == ".json":
        return load_json_object(path)
    raise ValueError(f"Unsupported structured file type: {path}")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def write_json_object(path: Path, payload: dict[str, Any], *, indent: int = 2) -> None:
    write_text(path, json.dumps(payload, indent=indent) + "\n")


def write_markdown(path: Path, lines: list[str]) -> None:
    write_text(path, "\n".join(lines) + "\n")


def write_yaml_mapping(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, yaml.safe_dump(payload, sort_keys=False))


__all__ = [
    "load_json",
    "load_json_object",
    "load_jsonl",
    "load_jsonl_objects",
    "load_structured_mapping",
    "load_yaml",
    "load_yaml_mapping",
    "write_json_object",
    "write_markdown",
    "write_text",
    "write_yaml_mapping",
]
