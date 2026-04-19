from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml


def fresh_test_root(work_root: Path, name: str) -> Path:
    root = work_root / name
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(payload) + "\n" for payload in payloads), encoding="utf-8")


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


__all__ = ["fresh_test_root", "write_json", "write_jsonl", "write_yaml"]
