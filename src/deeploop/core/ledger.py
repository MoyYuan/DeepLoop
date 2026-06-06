from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.lockf(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(json.dumps(record) + "\n")
            handle.flush()
        finally:
            fcntl.lockf(handle.fileno(), fcntl.LOCK_UN)


def make_ledger_entry(
    *,
    kind: str,
    mission_id: str,
    summary: str,
    status: str,
    related_paths: list[str] | None = None,
    metadata: dict | None = None,
) -> dict:
    return {
        "created_at": now_utc(),
        "kind": kind,
        "mission_id": mission_id,
        "summary": summary,
        "status": status,
        "related_paths": related_paths or [],
        "metadata": metadata or {},
    }


__all__ = ["append_jsonl", "make_ledger_entry", "now_utc"]

