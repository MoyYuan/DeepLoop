from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Mapping

from deeploop.core.ledger import append_jsonl, now_utc
from deeploop.core.paths import REPO_ROOT

DEFAULT_OPERATOR_REQUEST_LOG_FILE = "mission_operator_requests.jsonl"
DEFAULT_CURRENT_OPERATOR_REQUEST_FILE = "current_operator_request.json"
MISSION_OPERATOR_REQUEST_SCHEMA_PATH = REPO_ROOT / "schemas" / "mission-operator-request.schema.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    loaded = json.loads(raw)
    return loaded if isinstance(loaded, dict) else {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        loaded = json.loads(line)
        if isinstance(loaded, dict):
            records.append(loaded)
    return records


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _resolved_contract_path(mission_root: Path, raw: Any, *, default_name: str) -> Path:
    if isinstance(raw, str) and raw.strip():
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = mission_root / path
    else:
        path = mission_root / default_name
    return path.resolve()


def build_operator_inbox_contract(
    mission_root: Path,
    *,
    record_files: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    record_files = record_files if isinstance(record_files, Mapping) else {}
    request_log_path = _resolved_contract_path(
        mission_root,
        record_files.get("mission_operator_requests"),
        default_name=DEFAULT_OPERATOR_REQUEST_LOG_FILE,
    )
    current_request_path = _resolved_contract_path(
        mission_root,
        record_files.get("current_operator_request"),
        default_name=DEFAULT_CURRENT_OPERATOR_REQUEST_FILE,
    )
    return {
        "operator_request_log_path": str(request_log_path),
        "current_operator_request_path": str(current_request_path),
    }


def ensure_operator_inbox_contract(
    mission_root: Path,
    *,
    contract: dict[str, Any] | None = None,
    record_files: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    built = build_operator_inbox_contract(mission_root, record_files=record_files)
    resolved = {
        "operator_request_log_path": str(
            _resolved_contract_path(
                mission_root,
                (contract or {}).get("operator_request_log_path"),
                default_name=Path(built["operator_request_log_path"]).name,
            )
        ),
        "current_operator_request_path": str(
            _resolved_contract_path(
                mission_root,
                (contract or {}).get("current_operator_request_path"),
                default_name=Path(built["current_operator_request_path"]).name,
            )
        ),
    }
    if contract is not None:
        contract.update(resolved)
    log_path = Path(resolved["operator_request_log_path"])
    current_path = Path(resolved["current_operator_request_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    current_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    if not current_path.exists():
        _write_json(current_path, {})
    return resolved


def _schema_errors(
    payload: dict[str, Any],
    schema_path: Path = MISSION_OPERATOR_REQUEST_SCHEMA_PATH,
) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        import jsonschema
    except ImportError:
        warnings.warn("jsonschema not installed; schema validation is incomplete")
        errors: list[str] = []
        for key in schema.get("required", []):
            if key not in payload:
                errors.append(f"missing field `{key}`")
        return errors

    validator = jsonschema.Draft202012Validator(schema)
    return [
        error.message
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))[:8]
    ]


def validate_operator_request(payload: dict[str, Any]) -> list[str]:
    return _schema_errors(payload)


def append_operator_request(
    log_path: Path,
    current_path: Path,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    record = dict(payload)
    record.setdefault("created_at", now_utc())
    request_id = str(record.get("request_id") or "").strip()
    latest = None
    if request_id:
        for existing in reversed(_load_jsonl(log_path)):
            if str(existing.get("request_id") or "").strip() == request_id:
                latest = existing
                break
        if isinstance(latest, dict):
            record["created_at"] = latest.get("created_at", record["created_at"])
    errors = validate_operator_request(record)
    if errors:
        raise ValueError(f"Invalid operator request: {'; '.join(errors)}")
    if request_id:
        if not isinstance(latest, dict):
            append_jsonl(log_path, record)
    else:
        append_jsonl(log_path, record)
    _write_json(current_path, record)
    return record


def clear_current_operator_request(current_path: Path) -> None:
    _write_json(current_path, {})


def load_current_operator_request(path: Path) -> dict[str, Any] | None:
    loaded = _load_json(path)
    return loaded if isinstance(loaded.get("request_id"), str) and loaded.get("request_id") else None


def load_operator_request_log(path: Path) -> list[dict[str, Any]]:
    return _load_jsonl(path)


def latest_operator_request(log_path: Path, current_path: Path) -> dict[str, Any] | None:
    current = load_current_operator_request(current_path)
    if current is not None:
        return current
    history = _load_jsonl(log_path)
    return history[-1] if history else None


__all__ = [
    "DEFAULT_CURRENT_OPERATOR_REQUEST_FILE",
    "DEFAULT_OPERATOR_REQUEST_LOG_FILE",
    "MISSION_OPERATOR_REQUEST_SCHEMA_PATH",
    "append_operator_request",
    "build_operator_inbox_contract",
    "clear_current_operator_request",
    "ensure_operator_inbox_contract",
    "latest_operator_request",
    "load_current_operator_request",
    "load_operator_request_log",
    "validate_operator_request",
]

