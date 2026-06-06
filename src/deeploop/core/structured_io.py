from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

_MAX_JSON_NESTING_DEPTH = 256


def _check_json_container_shape(value: Any, *, max_depth: int = _MAX_JSON_NESTING_DEPTH) -> None:
    active: set[int] = set()

    def visit(item: Any, depth: int) -> None:
        if depth > max_depth:
            raise ValueError(f"JSON payload exceeds maximum nesting depth of {max_depth}")
        if isinstance(item, Mapping):
            item_id = id(item)
            if item_id in active:
                raise ValueError("JSON payload contains a circular reference")
            active.add(item_id)
            try:
                for child in item.values():
                    visit(child, depth + 1)
            finally:
                active.remove(item_id)
            return
        if isinstance(item, list | tuple):
            item_id = id(item)
            if item_id in active:
                raise ValueError("JSON payload contains a circular reference")
            active.add(item_id)
            try:
                for child in item:
                    visit(child, depth + 1)
            finally:
                active.remove(item_id)

    visit(value, 0)


def json_safe_value(
    value: Any,
    *,
    stringify_keys: bool = False,
    max_depth: int = _MAX_JSON_NESTING_DEPTH,
) -> Any:
    active: set[int] = set()

    def convert(item: Any, depth: int) -> Any:
        if depth > max_depth:
            raise ValueError(f"JSON payload exceeds maximum nesting depth of {max_depth}")
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, Mapping):
            item_id = id(item)
            if item_id in active:
                raise ValueError("JSON payload contains a circular reference")
            active.add(item_id)
            try:
                return {
                    str(key) if stringify_keys else key: convert(child, depth + 1)
                    for key, child in item.items()
                }
            finally:
                active.remove(item_id)
        if isinstance(item, list | tuple):
            item_id = id(item)
            if item_id in active:
                raise ValueError("JSON payload contains a circular reference")
            active.add(item_id)
            try:
                return [convert(child, depth + 1) for child in item]
            finally:
                active.remove(item_id)
        return item

    return convert(value, 0)


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
    _check_json_container_shape(payload)
    write_text(path, json.dumps(payload, indent=indent) + "\n")


def write_markdown(path: Path, lines: list[str]) -> None:
    write_text(path, "\n".join(lines) + "\n")


def write_yaml_mapping(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, yaml.safe_dump(payload, sort_keys=False))


def schema_errors(payload: dict[str, Any], schema_path: Path) -> list[str]:
    """Validate *payload* against the JSON Schema at *schema_path*.

    Returns a list of error messages (empty when valid).  Falls back to
    checking only required keys when ``jsonschema`` is not installed.
    """
    schema = load_json_object(schema_path)
    try:
        import jsonschema
    except ImportError:
        import warnings
        warnings.warn("jsonschema not installed; schema validation is incomplete")
        return [f"missing field `{key}`" for key in schema.get("required", []) if key not in payload]
    validator = jsonschema.Draft202012Validator(schema)
    return [
        error.message
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))[:8]
    ]


__all__ = [
    "load_json",
    "load_json_object",
    "load_jsonl",
    "load_jsonl_objects",
    "load_structured_mapping",
    "load_yaml",
    "load_yaml_mapping",
    "json_safe_value",
    "schema_errors",
    "write_json_object",
    "write_markdown",
    "write_text",
    "write_yaml_mapping",
]
