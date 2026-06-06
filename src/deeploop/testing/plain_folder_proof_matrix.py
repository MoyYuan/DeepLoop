from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from deeploop.core.paths import REPO_ROOT, WORKSPACE_ROOT
from deeploop.core.shared import normalize_strings as _normalize_strings
from deeploop.core.structured_io import load_yaml_mapping

DEFAULT_FIXTURES_ROOT = REPO_ROOT / "tests" / "_proof_fixtures" / "plain_folder"
DEFAULT_CAMPAIGNS_ROOT = WORKSPACE_ROOT / "runs" / "deeploop" / "proof_matrix"
PROOF_CASE_METADATA = "proof-case.yaml"
PROJECT_FACTS_NAME = "project-facts.yaml"

@dataclass(frozen=True)
class PlainFolderProofCase:
    case_id: str
    fixture_root: Path
    title: str
    summary: str
    workflow_shape: str
    expected_focus: str
    autonomy_claims: tuple[str, ...] = ()
    acceptance_thresholds: dict[str, Any] | None = None

def discover_plain_folder_proof_cases(
    fixtures_root: Path = DEFAULT_FIXTURES_ROOT,
) -> list[PlainFolderProofCase]:
    resolved_root = fixtures_root.expanduser().resolve()
    if not resolved_root.exists():
        return []

    cases: list[PlainFolderProofCase] = []
    for fixture_root in sorted(path for path in resolved_root.iterdir() if path.is_dir()):
        facts_path = fixture_root / PROJECT_FACTS_NAME
        if not facts_path.exists():
            raise FileNotFoundError(f"Missing {PROJECT_FACTS_NAME} in proof fixture {fixture_root}")

        metadata_path = fixture_root / PROOF_CASE_METADATA
        metadata = load_yaml_mapping(metadata_path) if metadata_path.exists() else {}
        cases.append(
            PlainFolderProofCase(
                case_id=str(metadata.get("case_id") or fixture_root.name),
                fixture_root=fixture_root,
                title=str(metadata.get("title") or fixture_root.name.replace("-", " ").title()),
                summary=str(metadata.get("summary") or ""),
                workflow_shape=str(metadata.get("workflow_shape") or "unspecified"),
                expected_focus=str(metadata.get("expected_focus") or "unspecified"),
                autonomy_claims=tuple(_normalize_strings(metadata.get("autonomy_claims"))),
                acceptance_thresholds=(
                    dict(metadata.get("acceptance_thresholds"))
                    if isinstance(metadata.get("acceptance_thresholds"), dict)
                    else {}
                ),
            )
        )
    return cases

def snapshot_project_tree(project_root: Path) -> list[str]:
    resolved_root = project_root.expanduser().resolve()
    if not resolved_root.exists():
        return []
    paths: list[str] = []
    for path in sorted(resolved_root.rglob("*")):
        relative = path.relative_to(resolved_root).as_posix()
        if path.is_dir():
            paths.append(f"{relative}/")
        else:
            paths.append(relative)
    return paths

def parse_run_project_output(raw_output: str) -> dict[str, Any]:
    stripped = raw_output.lstrip()
    if not stripped:
        raise ValueError("run_project.py produced no output")
    decoder = json.JSONDecoder()
    payload, _ = decoder.raw_decode(stripped)
    if not isinstance(payload, dict):
        raise ValueError("run_project.py did not emit a JSON object")
    return payload

def summarize_boundary_check(before_paths: list[str], after_paths: list[str]) -> dict[str, Any]:
    before = set(before_paths)
    after = set(after_paths)
    return {
        "project_tree_unchanged": before_paths == after_paths,
        "added_paths": sorted(after - before),
        "removed_paths": sorted(before - after),
    }

__all__ = [
    "DEFAULT_CAMPAIGNS_ROOT",
    "DEFAULT_FIXTURES_ROOT",
    "PROJECT_FACTS_NAME",
    "PROOF_CASE_METADATA",
    "PlainFolderProofCase",
    "discover_plain_folder_proof_cases",
    "parse_run_project_output",
    "snapshot_project_tree",
    "summarize_boundary_check",
]
