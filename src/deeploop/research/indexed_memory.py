from __future__ import annotations

import json
import re
from hashlib import sha1
from json import JSONDecodeError, JSONDecoder
from pathlib import Path
from typing import Any, Mapping

import yaml

from deeploop.core.structured_io import json_safe_value, load_jsonl_objects, write_json_object
from deeploop.core.ledger import append_jsonl, now_utc
from deeploop.core.paths import REPO_ROOT, RESEARCH_MEMORY_DIR

RESEARCH_MEMORY_REGISTRY_PATH = REPO_ROOT / "configs" / "memory" / "registry.yaml"
RESEARCH_MEMORY_ENTRY_SCHEMA_PATH = REPO_ROOT / "schemas" / "research-memory-entry.schema.json"
DEFAULT_RESEARCH_MEMORY_EVENTS_FILE = "research_memory_entries.jsonl"
DEFAULT_RESEARCH_MEMORY_INDEX_FILE = "research_memory_index.json"


def _recover_last_json_object(raw: str) -> dict[str, Any] | None:
    decoder = JSONDecoder()
    position = 0
    recovered: dict[str, Any] | None = None
    while position < len(raw):
        while position < len(raw) and raw[position].isspace():
            position += 1
        if position >= len(raw):
            break
        try:
            loaded, position = decoder.raw_decode(raw, position)
        except JSONDecodeError:
            break
        if isinstance(loaded, dict):
            recovered = loaded
    return recovered


def _load_json(path: Path, *, repair: bool = False) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except JSONDecodeError:
        recovered = _recover_last_json_object(raw)
        if recovered is None:
            raise
        if repair:
            _write_json(path, recovered)
        loaded = recovered
    return loaded if isinstance(loaded, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json_object(path, payload)


def _rebuild_index_from_entries(contract: Mapping[str, Any]) -> dict[str, Any]:
    registry = load_research_memory_registry(Path(contract["research_memory_registry_path"]))
    index = _empty_index(contract)
    active: dict[str, dict[str, Any]] = {}
    for recorded in load_jsonl_objects(Path(contract["research_memory_events_path"]), missing_ok=True):
        normalized = _normalize_entry(recorded, registry=registry)
        created_at = str(recorded.get("created_at") or "").strip()
        updated_at = str(recorded.get("updated_at") or "").strip()
        normalized["created_at"] = created_at or str(normalized["provenance"].get("recorded_at") or now_utc())
        normalized["updated_at"] = updated_at or normalized["created_at"]
        key = _entry_key(normalized["entity_type"], normalized["entity_id"])
        existing = active.get(key)
        if existing and str(existing.get("fingerprint") or "") == normalized["fingerprint"]:
            continue
        active[key] = normalized
        index["active_entries"] = list(active.values())
        index = _rebuild_indexes(index, registry=registry)
    return index


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _jsonify(value: Any) -> Any:
    return json_safe_value(value, stringify_keys=True)


def _normalize_strings(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (str, Path)):
        value = str(raw).strip()
        return [value] if value else []
    if isinstance(raw, list | tuple | set):
        values: list[str] = []
        for item in raw:
            values.extend(_normalize_strings(item))
        return values
    return [str(raw)]


def _tokenize(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        tokens: list[str] = []
        for key, value in raw.items():
            tokens.extend(_tokenize(key))
            tokens.extend(_tokenize(value))
        return tokens
    if isinstance(raw, list | tuple | set):
        tokens: list[str] = []
        for item in raw:
            tokens.extend(_tokenize(item))
        return tokens
    text = str(raw).lower()
    return [token for token in re.findall(r"[a-z0-9][a-z0-9_\-]{1,63}", text) if len(token) >= 3]


def _entry_key(entity_type: str, entity_id: str) -> str:
    return f"{entity_type}:{entity_id}"


def _compact_summary(entry: Mapping[str, Any]) -> str:
    summary = str(entry.get("summary") or "").strip()
    if summary:
        return summary
    payload = entry.get("payload") if isinstance(entry.get("payload"), Mapping) else {}
    for field in ("summary", "statement", "finding", "rationale", "recommendation"):
        value = str(payload.get(field) or "").strip()
        if value:
            return value
    return str(entry.get("entity_id") or "").strip()


def _active_entry_limit(registry: Mapping[str, Any]) -> int:
    retention = registry.get("retention_policy") if isinstance(registry.get("retention_policy"), Mapping) else {}
    return max(1, int(retention.get("default_active_entries_per_mission_entity_type", 8) or 8))


def load_research_memory_registry(path: Path = RESEARCH_MEMORY_REGISTRY_PATH) -> dict[str, Any]:
    return _load_yaml(path)


def build_research_memory_contract(*, memory_root: Path | None = None) -> dict[str, str]:
    root = (memory_root or RESEARCH_MEMORY_DIR).expanduser().resolve()
    return {
        "research_memory_root": str(root),
        "research_memory_registry_path": str(RESEARCH_MEMORY_REGISTRY_PATH),
        "research_memory_schema_path": str(RESEARCH_MEMORY_ENTRY_SCHEMA_PATH),
        "research_memory_events_path": str(root / DEFAULT_RESEARCH_MEMORY_EVENTS_FILE),
        "research_memory_index_path": str(root / DEFAULT_RESEARCH_MEMORY_INDEX_FILE),
    }


def _empty_index(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "updated_at": now_utc(),
        "research_memory_root": str(contract["research_memory_root"]),
        "registry_contract_path": str(contract["research_memory_registry_path"]),
        "entry_schema_path": str(contract["research_memory_schema_path"]),
        "active_entries": [],
        "archived_entries": [],
        "term_index": {},
        "mission_index": {},
        "entity_type_index": {},
        "status_index": {},
        "promotion_index": {},
        "counts": {
            "active_entries": 0,
            "archived_entries": 0,
            "terms": 0,
        },
    }


def ensure_research_memory_contract(
    *,
    contract: dict[str, Any] | None = None,
    memory_root: Path | None = None,
) -> dict[str, str]:
    requested_root = memory_root
    if requested_root is None and isinstance(contract, Mapping):
        raw_root = contract.get("research_memory_root")
        if isinstance(raw_root, str) and raw_root.strip():
            requested_root = Path(raw_root)
    built = build_research_memory_contract(memory_root=requested_root)
    resolved = {
        "research_memory_root": str(
            Path(str((contract or {}).get("research_memory_root") or built["research_memory_root"])).expanduser().resolve()
        ),
        "research_memory_registry_path": str(
            Path(
                str((contract or {}).get("research_memory_registry_path") or built["research_memory_registry_path"])
            ).expanduser().resolve()
        ),
        "research_memory_schema_path": str(
            Path(str((contract or {}).get("research_memory_schema_path") or built["research_memory_schema_path"])).expanduser().resolve()
        ),
        "research_memory_events_path": str(
            Path(str((contract or {}).get("research_memory_events_path") or built["research_memory_events_path"])).expanduser().resolve()
        ),
        "research_memory_index_path": str(
            Path(str((contract or {}).get("research_memory_index_path") or built["research_memory_index_path"])).expanduser().resolve()
        ),
    }
    if isinstance(contract, dict):
        contract.update(resolved)
    events_path = Path(resolved["research_memory_events_path"])
    index_path = Path(resolved["research_memory_index_path"])
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.touch(exist_ok=True)
    if not index_path.exists():
        _write_json(index_path, _empty_index(resolved))
    return resolved


def load_research_memory_index(*, contract: Mapping[str, Any] | None = None, memory_root: Path | None = None) -> dict[str, Any]:
    resolved = ensure_research_memory_contract(contract=dict(contract or {}), memory_root=memory_root)
    index_path = Path(resolved["research_memory_index_path"])
    try:
        index = _load_json(index_path, repair=True)
    except JSONDecodeError:
        index = _rebuild_index_from_entries(resolved)
        _write_json(index_path, index)
    if not index:
        index = _empty_index(resolved)
    if not isinstance(index.get("active_entries"), list):
        index["active_entries"] = []
    if not isinstance(index.get("archived_entries"), list):
        index["archived_entries"] = []
    return index


def _schema_errors(payload: Mapping[str, Any], schema_path: Path) -> list[str]:
    schema = _load_json(schema_path)
    try:
        import jsonschema
    except ImportError:
        errors: list[str] = []
        for key in schema.get("required", []):
            if key not in payload:
                errors.append(f"missing field `{key}`")
        return errors

    validator = jsonschema.Draft202012Validator(schema)
    return [
        error.message
        for error in sorted(validator.iter_errors(dict(payload)), key=lambda item: list(item.path))[:8]
    ]


def _registry_errors(entry: Mapping[str, Any], registry: Mapping[str, Any]) -> list[str]:
    entity_type = str(entry.get("entity_type") or "").strip()
    entities = registry.get("entities") if isinstance(registry.get("entities"), list) else []
    selected = None
    for item in entities:
        if isinstance(item, Mapping) and str(item.get("id") or "").strip() == entity_type:
            selected = item
            break
    if selected is None:
        return [f"Unsupported entity_type `{entity_type}`"]
    payload = entry.get("payload") if isinstance(entry.get("payload"), Mapping) else {}
    errors: list[str] = []
    for field in selected.get("required_fields", []):
        value = payload.get(field, entry.get(field))
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"missing required field `{field}` for `{entity_type}`")
    return errors


def validate_research_memory_entry(entry: Mapping[str, Any], *, registry: Mapping[str, Any] | None = None) -> list[str]:
    registry = registry or load_research_memory_registry()
    errors = _schema_errors(entry, RESEARCH_MEMORY_ENTRY_SCHEMA_PATH)
    errors.extend(_registry_errors(entry, registry))
    return errors


def _retention_metadata(entry: Mapping[str, Any], *, registry: Mapping[str, Any]) -> dict[str, Any]:
    retention = registry.get("retention_policy") if isinstance(registry.get("retention_policy"), Mapping) else {}
    payload = entry.get("payload") if isinstance(entry.get("payload"), Mapping) else {}
    promotion = entry.get("promotion") if isinstance(entry.get("promotion"), Mapping) else {}
    entity_type = str(entry.get("entity_type") or "")
    status = str(entry.get("status") or "")
    decision_type = str(payload.get("decision_type") or "")
    reason = "rolling-window"
    protected = False
    if str(promotion.get("status") or "") == "promoted":
        reason = "promoted-evidence"
        protected = True
    elif entity_type == "experiment" and status in set(_normalize_strings(retention.get("preserve_experiment_statuses"))):
        reason = "failed-or-negative-result"
        protected = True
    elif entity_type == "decision" and decision_type in set(_normalize_strings(retention.get("preserve_decision_types"))):
        reason = "branching-decision"
        protected = True
    elif entity_type == "mission":
        reason = "mission-summary"
        protected = True
    return {
        "mode": "protected" if protected else "rolling-window",
        "reason": reason,
        "protected": protected,
        "active": True,
        "max_active_entries_per_mission_entity_type": _active_entry_limit(registry),
        "archived_at": None,
        "archive_reason": None,
    }


def _entry_fingerprint(entry: Mapping[str, Any]) -> str:
    comparable = {
        key: value
        for key, value in _jsonify(dict(entry)).items()
        if key not in {"updated_at", "created_at", "fingerprint"}
    }
    return sha1(json.dumps(comparable, sort_keys=True).encode("utf-8")).hexdigest()


def _normalize_entry(entry: Mapping[str, Any], *, registry: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _jsonify(dict(entry))
    mission_id = str(
        normalized.get("mission_id")
        or ((normalized.get("provenance") or {}).get("mission_id") if isinstance(normalized.get("provenance"), Mapping) else "")
        or ((normalized.get("payload") or {}).get("mission_id") if isinstance(normalized.get("payload"), Mapping) else "")
        or ""
    ).strip()
    normalized["schema_version"] = 1
    normalized["entity_type"] = str(normalized.get("entity_type") or "").strip()
    normalized["entity_id"] = str(normalized.get("entity_id") or "").strip()
    normalized["mission_id"] = mission_id or None
    normalized["status"] = str(normalized.get("status") or "recorded").strip()
    normalized["summary"] = _compact_summary(normalized)
    normalized["related_ids"] = sorted({value for value in _normalize_strings(normalized.get("related_ids")) if value})
    normalized["tags"] = sorted({value for value in _normalize_strings(normalized.get("tags")) if value})
    payload = normalized.get("payload") if isinstance(normalized.get("payload"), Mapping) else {}
    normalized["payload"] = dict(payload)
    provenance = normalized.get("provenance") if isinstance(normalized.get("provenance"), Mapping) else {}
    normalized["provenance"] = {
        "source_kind": str(provenance.get("source_kind") or "mission-runtime"),
        "mission_id": mission_id or None,
        "recorded_at": str(provenance.get("recorded_at") or now_utc()),
        "source_paths": _normalize_strings(provenance.get("source_paths")),
        "source_entry_id": str(provenance.get("source_entry_id") or "") or None,
        "decision_id": str(provenance.get("decision_id") or "") or None,
        "action_id": str(provenance.get("action_id") or "") or None,
        "branch_id": str(provenance.get("branch_id") or "") or None,
    }
    terms = sorted(
        {
            token
            for token in _tokenize(
                [
                    normalized["entity_type"],
                    normalized["entity_id"],
                    normalized["status"],
                    normalized["summary"],
                    normalized["tags"],
                    normalized["payload"],
                    normalized["related_ids"],
                ]
            )
        }
    )
    retrieval = normalized.get("retrieval") if isinstance(normalized.get("retrieval"), Mapping) else {}
    normalized["retrieval"] = {
        "terms": terms,
        "query_text": str(retrieval.get("query_text") or normalized["summary"]),
        "match_text": str(retrieval.get("match_text") or normalized["summary"]),
        "evidence_strength": str(retrieval.get("evidence_strength") or "grounded"),
    }
    promotion = normalized.get("promotion") if isinstance(normalized.get("promotion"), Mapping) else {}
    normalized["promotion"] = {
        "status": str(promotion.get("status") or "candidate"),
        "promoted_at": str(promotion.get("promoted_at") or "") or None,
        "source_entry_ids": sorted({value for value in _normalize_strings(promotion.get("source_entry_ids")) if value}),
    }
    normalized["retention"] = _retention_metadata(normalized, registry=registry)
    normalized["fingerprint"] = _entry_fingerprint(normalized)
    return normalized


def _rebuild_indexes(index: dict[str, Any], *, registry: Mapping[str, Any]) -> dict[str, Any]:
    active_entries = [
        dict(entry)
        for entry in index.get("active_entries", [])
        if isinstance(entry, Mapping) and isinstance(entry.get("retention"), Mapping) and entry["retention"].get("active", True)
    ]
    archived_entries = [dict(entry) for entry in index.get("archived_entries", []) if isinstance(entry, Mapping)]
    limit = _active_entry_limit(registry)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in active_entries:
        grouped.setdefault((str(entry.get("mission_id") or ""), str(entry.get("entity_type") or "")), []).append(entry)
    retained: list[dict[str, Any]] = []
    for _, entries in grouped.items():
        protected = [entry for entry in entries if bool((entry.get("retention") or {}).get("protected"))]
        rolling = [entry for entry in entries if not bool((entry.get("retention") or {}).get("protected"))]
        rolling.sort(key=lambda item: (str(item.get("updated_at") or ""), str(item.get("entity_id") or "")), reverse=True)
        retained.extend(protected)
        retained.extend(rolling[:limit])
        for overflow in rolling[limit:]:
            archived = dict(overflow)
            archived_retention = dict(archived.get("retention") or {})
            archived_retention.update(
                {
                    "active": False,
                    "archived_at": now_utc(),
                    "archive_reason": "rolling-window",
                }
            )
            archived["retention"] = archived_retention
            archived_entries.append(archived)
    active_entries = sorted(
        retained,
        key=lambda item: (
            str(item.get("entity_type") or ""),
            str(item.get("mission_id") or ""),
            str(item.get("updated_at") or ""),
            str(item.get("entity_id") or ""),
        ),
    )
    term_index: dict[str, list[str]] = {}
    mission_index: dict[str, list[str]] = {}
    entity_type_index: dict[str, list[str]] = {}
    status_index: dict[str, list[str]] = {}
    promotion_index: dict[str, list[str]] = {}
    for entry in active_entries:
        key = _entry_key(str(entry.get("entity_type") or ""), str(entry.get("entity_id") or ""))
        for term in _normalize_strings((entry.get("retrieval") or {}).get("terms")):
            term_index.setdefault(term, []).append(key)
        mission_id = str(entry.get("mission_id") or "")
        if mission_id:
            mission_index.setdefault(mission_id, []).append(key)
        entity_type_index.setdefault(str(entry.get("entity_type") or ""), []).append(key)
        status_index.setdefault(str(entry.get("status") or ""), []).append(key)
        promotion_index.setdefault(str((entry.get("promotion") or {}).get("status") or "candidate"), []).append(key)
    for mapping in (term_index, mission_index, entity_type_index, status_index, promotion_index):
        for key, values in mapping.items():
            mapping[key] = sorted(set(values))
    index.update(
        {
            "schema_version": 1,
            "updated_at": now_utc(),
            "active_entries": active_entries,
            "archived_entries": archived_entries,
            "term_index": term_index,
            "mission_index": mission_index,
            "entity_type_index": entity_type_index,
            "status_index": status_index,
            "promotion_index": promotion_index,
            "counts": {
                "active_entries": len(active_entries),
                "archived_entries": len(archived_entries),
                "terms": len(term_index),
            },
        }
    )
    return index


def record_research_memory_entry(
    entry: Mapping[str, Any],
    *,
    contract: dict[str, Any] | None = None,
    memory_root: Path | None = None,
) -> dict[str, Any]:
    resolved = ensure_research_memory_contract(contract=contract, memory_root=memory_root)
    registry = load_research_memory_registry(Path(resolved["research_memory_registry_path"]))
    normalized = _normalize_entry(entry, registry=registry)
    index_path = Path(resolved["research_memory_index_path"])
    index = load_research_memory_index(contract=resolved)
    active = {
        _entry_key(str(item.get("entity_type") or ""), str(item.get("entity_id") or "")): dict(item)
        for item in index.get("active_entries", [])
        if isinstance(item, Mapping)
    }
    key = _entry_key(normalized["entity_type"], normalized["entity_id"])
    existing = active.get(key)
    now = now_utc()
    normalized["created_at"] = str((existing or {}).get("created_at") or now)
    normalized["updated_at"] = now
    errors = validate_research_memory_entry(normalized, registry=registry)
    if errors:
        raise ValueError(f"Invalid research memory entry: {'; '.join(errors)}")
    if existing and str(existing.get("fingerprint") or "") == normalized["fingerprint"]:
        return existing
    active[key] = normalized
    index["active_entries"] = list(active.values())
    rebuilt = _rebuild_indexes(index, registry=registry)
    _write_json(index_path, rebuilt)
    append_jsonl(Path(resolved["research_memory_events_path"]), normalized)
    return normalized


def retrieve_research_memory(
    *,
    query: str,
    contract: Mapping[str, Any] | None = None,
    memory_root: Path | None = None,
    limit: int | None = None,
    exclude_mission_id: str | None = None,
    entity_types: list[str] | None = None,
    statuses: list[str] | None = None,
    promotion_statuses: list[str] | None = None,
) -> list[dict[str, Any]]:
    index = load_research_memory_index(contract=contract, memory_root=memory_root)
    active_entries = [
        dict(entry)
        for entry in index.get("active_entries", [])
        if isinstance(entry, Mapping) and bool((entry.get("retention") or {}).get("active", True))
    ]
    by_key = {
        _entry_key(str(entry.get("entity_type") or ""), str(entry.get("entity_id") or "")): entry for entry in active_entries
    }
    query_terms = sorted(set(_tokenize(query)))
    candidate_keys: set[str] = set()
    if query_terms:
        for term in query_terms:
            candidate_keys.update(index.get("term_index", {}).get(term, []))
    else:
        candidate_keys = set(by_key)
    allowed_entity_types = {value for value in _normalize_strings(entity_types)}
    allowed_statuses = {value for value in _normalize_strings(statuses)}
    allowed_promotions = {value for value in _normalize_strings(promotion_statuses)}
    matches: list[dict[str, Any]] = []
    for key in candidate_keys:
        entry = by_key.get(key)
        if entry is None:
            continue
        if exclude_mission_id and str(entry.get("mission_id") or "") == exclude_mission_id:
            continue
        if allowed_entity_types and str(entry.get("entity_type") or "") not in allowed_entity_types:
            continue
        if allowed_statuses and str(entry.get("status") or "") not in allowed_statuses:
            continue
        promotion_status = str((entry.get("promotion") or {}).get("status") or "candidate")
        if allowed_promotions and promotion_status not in allowed_promotions:
            continue
        terms = set(_normalize_strings((entry.get("retrieval") or {}).get("terms")))
        overlap = len(set(query_terms) & terms) if query_terms else 1
        if query_terms and overlap == 0:
            continue
        score = float(overlap * 5)
        if promotion_status == "promoted":
            score += 3.0
        if bool((entry.get("retention") or {}).get("protected")):
            score += 1.5
        result = dict(entry)
        result["score"] = score
        matches.append(result)
    matches.sort(key=lambda item: (float(item.get("score") or 0.0), str(item.get("updated_at") or "")), reverse=True)
    resolved_limit = max(1, int(limit or 5))
    return matches[:resolved_limit]


__all__ = [
    "DEFAULT_RESEARCH_MEMORY_EVENTS_FILE",
    "DEFAULT_RESEARCH_MEMORY_INDEX_FILE",
    "RESEARCH_MEMORY_ENTRY_SCHEMA_PATH",
    "RESEARCH_MEMORY_REGISTRY_PATH",
    "build_research_memory_contract",
    "ensure_research_memory_contract",
    "load_research_memory_index",
    "load_research_memory_registry",
    "record_research_memory_entry",
    "retrieve_research_memory",
    "validate_research_memory_entry",
]
