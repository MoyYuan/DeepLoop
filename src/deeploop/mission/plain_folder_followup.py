from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deeploop.core.structured_io import write_json_object, write_text, write_yaml_mapping

PLAIN_FOLDER_ADAPTER_SPEC = "deeploop.runtime.plain_folder_adapter:build_plain_folder_adapter"


def _clean_statement(text: str) -> str:
    statement = " ".join(str(text).split()).strip()
    return statement.rstrip(".")


def _doc_statements(path: Path, *, limit: int = 3) -> list[tuple[str, str]]:
    statements: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:]
        statement = _clean_statement(stripped)
        if statement:
            statements.append((path.name, statement))
        if len(statements) >= limit:
            break
    return statements


def _statement_candidates(project_contract: dict[str, Any]) -> list[tuple[str, str]]:
    metadata = (
        project_contract.get("project_metadata")
        if isinstance(project_contract.get("project_metadata"), dict)
        else {}
    )
    candidates: list[tuple[str, str]] = []
    for field in ("title", "summary", "objective"):
        value = metadata.get(field)
        if isinstance(value, str) and value.strip():
            candidates.append((f"project-{field}", _clean_statement(value)))
    for item in metadata.get("constraints", []):
        statement = _clean_statement(str(item))
        if statement:
            candidates.append(("project-constraint", statement))
    artifacts = project_contract.get("artifacts") if isinstance(project_contract.get("artifacts"), dict) else {}
    for raw_path in artifacts.get("docs", []):
        path = Path(raw_path)
        if not path.exists():
            continue
        candidates.extend(_doc_statements(path))
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for source_doc, statement in candidates:
        key = statement.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((source_doc, statement))
    if deduped:
        return deduped
    project_name = str(metadata.get("name") or Path(str(project_contract.get("repo_root") or "")).name or "plain-folder-project")
    return [("project-fallback", f"DeepLoop should evaluate claims for {project_name}")]


def _example_record(*, source_doc: str, statement: str, index: int) -> dict[str, Any]:
    return {
        "hypothesis": statement,
        "label": "entailment",
        "tier": "C" if index % 2 == 0 else "S",
        "lex": "lex" if index % 2 == 0 else "delex",
        "rule": "project_fact" if "constraint" not in source_doc else "project_constraint",
        "chain_len": 1,
        "source_doc": source_doc,
        "slice_ids": [source_doc.replace(" ", "-").lower()],
    }


def materialize_plain_folder_followups(
    *,
    mission_id: str,
    mission_mode: str,
    mission_root: Path,
    mission_state_path: Path,
    project_contract: dict[str, Any],
) -> dict[str, Any]:
    runtime_root = mission_root / "runtime" / "plain_folder_followups"
    dataset_root = runtime_root / "dataset"
    config_root = runtime_root / "configs"
    runs_root = runtime_root / "runs"
    dataset_root.mkdir(parents=True, exist_ok=True)
    config_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    candidates = _statement_candidates(project_contract)
    examples = [_example_record(source_doc=source_doc, statement=statement, index=index) for index, (source_doc, statement) in enumerate(candidates)]
    if len(examples) < 4:
        examples.extend(
            _example_record(source_doc="project-repeat", statement=examples[index % len(examples)]["hypothesis"], index=len(examples) + index)
            for index in range(4 - len(examples))
        )
    dataset_path = dataset_root / "plain_folder_examples.jsonl"
    write_text(dataset_path, "".join(json.dumps(record) + "\n" for record in examples))
    promotion_manifest_path = dataset_root / "promotion_manifest.json"
    write_json_object(
        promotion_manifest_path,
        {
            "dataset_id": f"{mission_id}-plain-folder-followup",
            "files": [
                {
                    "source": "plain_folder_examples.jsonl",
                    "local_path": str(dataset_path),
                    "tier": "C",
                    "split_kind": "dev",
                    "split_family": "iid",
                },
                {
                    "source": "plain_folder_examples.jsonl",
                    "local_path": str(dataset_path),
                    "tier": "S",
                    "split_kind": "dev",
                    "split_family": "length_ood",
                },
            ],
        },
    )

    baseline_common = {
        "mission_id": mission_id,
        "mode": mission_mode,
        "claim_state": "exploratory",
        "resource_tier": "cpu-smoke",
        "execution_profile": "cpu-smoke",
        "dataset": {
            "promotion_manifest": str(promotion_manifest_path),
            "selection": {
                "tiers": ["C", "S"],
                "split_kinds": ["dev"],
                "split_families": ["iid", "length_ood"],
                "lexicalizations": ["lex", "delex"],
                "rule_families": ["project_fact", "project_constraint"],
            },
            "limit_examples": min(len(examples), 6),
        },
        "model": {
            "family": "plain-folder",
            "identifier": "mock://plain-folder",
            "backend": "mock-entailment",
            "dtype": "none",
        },
        "prompt": {"template_id": "plain_folder_prompt_v1"},
    }
    execution_output_dir = runs_root / "execution-baseline"
    replication_output_dir = runs_root / "replication-baseline"
    execution_config_path = config_root / "execution-baseline.yaml"
    replication_config_path = config_root / "replication-baseline.yaml"
    write_yaml_mapping(
        execution_config_path,
        {
            **baseline_common,
            "run": {
                "loop_id": f"{mission_id}-execution-baseline",
                "output_dir": str(execution_output_dir),
                "notes": ["Generated plain-folder execution evidence run."],
            },
        },
    )
    write_yaml_mapping(
        replication_config_path,
        {
            **baseline_common,
            "run": {
                "loop_id": f"{mission_id}-replication-baseline",
                "output_dir": str(replication_output_dir),
                "notes": ["Generated plain-folder replication evidence run."],
            },
        },
    )

    execution_manifest_path = execution_output_dir / "run_manifest.json"
    return {
        "generated_paths": {
            "dataset_path": str(dataset_path),
            "promotion_manifest_path": str(promotion_manifest_path),
            "execution_config_path": str(execution_config_path),
            "replication_config_path": str(replication_config_path),
            "runs_root": str(runs_root),
        },
        "phase_execution_hints": {
            "execution": {
                "executor": {
                    "id": "stage-kernel",
                    "params": {
                        "stage_id": "baseline-evaluation",
                        "config_path": str(execution_config_path),
                        "adapter_spec": PLAIN_FOLDER_ADAPTER_SPEC,
                    },
                },
                "next_phase_on_success": "critique",
            },
            "critique": {
                "executor": {
                    "id": "evaluation-comparison",
                    "params": {
                        "mission_state_path": str(mission_state_path),
                        "manifest_paths": [str(execution_manifest_path)],
                        "run_roots": [str(runs_root)],
                        "artifact_name": f"{mission_id}-plain-folder-evidence",
                    },
                },
                "next_phase_on_success": "replication",
            },
            "replication": {
                "executor": {
                    "id": "stage-kernel",
                    "params": {
                        "stage_id": "baseline-evaluation",
                        "config_path": str(replication_config_path),
                        "adapter_spec": PLAIN_FOLDER_ADAPTER_SPEC,
                    },
                },
                "next_phase_on_success": "final-report",
            },
        },
    }
