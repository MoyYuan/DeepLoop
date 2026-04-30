from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_RECOMMENDED_CONTRACT_FILES = (
    ("project.yaml", "project metadata and default DeepLoop artifact wiring"),
    ("runtime-providers.yaml", "runtime/provider entrypoints and integration hooks"),
    ("evaluation-contract.yaml", "evaluation and metric contract metadata"),
)
_PLAIN_PROJECT_FACT_FILES = (
    ("project-facts.yaml", "plain researcher-provided project facts"),
    ("project-facts.yml", "plain researcher-provided project facts"),
)
_CONFIG_EXTENSIONS = {".yaml", ".yml", ".json", ".toml"}
_DATA_EXTENSIONS = {".csv", ".tsv", ".parquet", ".jsonl", ".feather", ".arrow", ".sqlite", ".db"}
CONTRACT_OPERATIONAL_FIELDS = (
    "acceptance_criteria",
    "artifact_contract",
    "budgets",
    "data",
    "evaluation_contract",
)
_PLAIN_OPERATIONAL_TOP_LEVEL_FIELDS = {"project", "artifacts", *CONTRACT_OPERATIONAL_FIELDS}


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in project contract file {path}")
    return loaded


def _normalize_paths(values: Any, *, base_dir: Path) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for item in values:
        text = str(item).strip()
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        else:
            path = path.resolve()
        normalized.append(str(path))
    return normalized


def _infer_format(path: Path) -> str | None:
    suffix = path.suffix.lower().lstrip(".")
    return suffix or None


def normalize_data_artifacts(values: Any, *, base_dir: Path) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in values:
        if isinstance(item, dict):
            raw_path = item.get("path")
            metadata = {str(key): value for key, value in item.items() if str(key) != "path"}
        else:
            raw_path = item
            metadata = {}
        text = str(raw_path or "").strip()
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        else:
            path = path.resolve()
        record: dict[str, Any] = {
            "path": str(path),
            **metadata,
        }
        if "kind" not in record:
            record["kind"] = "dataset"
        if "format" not in record:
            inferred_format = _infer_format(path)
            if inferred_format:
                record["format"] = inferred_format
        if path.exists() and path.is_file() and "size_bytes" not in record:
            record["size_bytes"] = path.stat().st_size
        normalized.append(record)
    return normalized


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _extract_contract_requirement_value(payload: dict[str, Any], project: dict[str, Any], field: str) -> Any:
    if field in payload:
        return payload[field]
    if field in project:
        return project[field]
    human_inputs = project.get("human_inputs") if isinstance(project.get("human_inputs"), dict) else {}
    if field == "budgets" and field in human_inputs:
        return human_inputs[field]
    return None


def _plain_contract_requirements(payload: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    requirements: dict[str, Any] = {}
    for field in CONTRACT_OPERATIONAL_FIELDS:
        value = _extract_contract_requirement_value(payload, project, field)
        if value is not None:
            requirements[field] = value
    return requirements


def _contract_coverage(requirements: dict[str, Any], unoperationalized_fields: list[str]) -> list[dict[str, Any]]:
    coverage = [
        {
            "field": field,
            "present": field in requirements,
            "promoted_to_config": field in requirements,
            "included_in_prompts": field in requirements,
            "enforced_by_runtime": False,
        }
        for field in CONTRACT_OPERATIONAL_FIELDS
    ]
    coverage.extend(
        {
            "field": field,
            "present": True,
            "promoted_to_config": False,
            "included_in_prompts": False,
            "enforced_by_runtime": False,
        }
        for field in unoperationalized_fields
    )
    return coverage


def _default_plain_artifacts(repo_root: Path) -> dict[str, list[str]]:
    docs: list[str] = []
    configs: list[str] = []
    doc_roots = [repo_root, repo_root / "docs"]
    for root in doc_roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name == "AGENTS.md":
                continue
            if path.suffix.lower() == ".md":
                docs.append(str(path.resolve()))
            elif path.suffix.lower() in {".yaml", ".yml", ".json"} and path.parent != repo_root / ".deeploop":
                configs.append(str(path.resolve()))
    return {
        "docs": _dedupe_strings(docs),
        "configs": _dedupe_strings(configs),
    }


def _config_extension_warnings(config_paths: list[str], *, source: str) -> list[str]:
    warnings: list[str] = []
    for raw_path in config_paths:
        suffix = Path(raw_path).suffix.lower()
        if suffix and suffix not in _CONFIG_EXTENSIONS:
            suggestion = "data" if suffix in _DATA_EXTENSIONS else "the appropriate artifact type"
            warnings.append(
                f"{source} declares non-config artifact `{raw_path}` under artifacts.configs; "
                f"declare it under artifacts.{suggestion} instead."
            )
    return warnings


def _resolve_provider_value(value: Any, *, base_dir: Path, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {str(child_key): _resolve_provider_value(child_value, base_dir=base_dir, key=str(child_key)) for child_key, child_value in value.items()}
    if isinstance(value, list):
        return [_resolve_provider_value(item, base_dir=base_dir, key=key) for item in value]
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return text
    looks_like_path = bool(key and key.endswith(("_path", "_paths", "_config", "_root", "_dir")))
    if text.startswith(("./", "../")):
        looks_like_path = True
    if not looks_like_path:
        return value
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    return str(path)


def _resolve_provider_pythonpath(values: Any, *, base_dir: Path, runtime_providers_path: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError(
            f"Runtime provider pythonpath in {runtime_providers_path} must be declared as a list."
        )
    resolved: list[str] = []
    for item in values:
        text = str(item).strip()
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        else:
            path = path.resolve()
        resolved.append(str(path))
    return resolved


def discover_project_contract(target_repo: Path) -> dict[str, Any]:
    repo_root = target_repo.expanduser().resolve()
    contract_root = repo_root / ".deeploop"
    project_path = contract_root / "project.yaml"
    runtime_providers_path = contract_root / "runtime-providers.yaml"
    evaluation_contract_path = contract_root / "evaluation-contract.yaml"
    missions_root = contract_root / "missions"
    repo_agents = repo_root / "AGENTS.md"
    repo_copilot = repo_root / ".github" / "copilot-instructions.md"

    project_payload = _load_yaml_mapping(project_path)
    artifacts_payload = project_payload.get("artifacts") if isinstance(project_payload.get("artifacts"), dict) else {}
    docs = _normalize_paths(artifacts_payload.get("docs"), base_dir=repo_root)
    configs = _normalize_paths(artifacts_payload.get("configs"), base_dir=repo_root)
    data = normalize_data_artifacts(artifacts_payload.get("data"), base_dir=repo_root)
    mission_files = (
        [str(path.resolve()) for path in sorted(missions_root.glob("*.yaml"))]
        if missions_root.exists()
        else []
    )
    recommended_files = [str((contract_root / name).resolve()) for name, _ in _RECOMMENDED_CONTRACT_FILES]
    missing_recommended = [path for path in recommended_files if not Path(path).exists()]
    scaffold_recommendations = [
        {"path": path, "reason": reason}
        for (name, reason), path in zip(_RECOMMENDED_CONTRACT_FILES, recommended_files)
        if str((contract_root / name).resolve()) in missing_recommended
    ]
    guidance_paths = [
        str(path.resolve())
        for path in (repo_agents, repo_copilot)
        if path.exists()
    ]
    contract_files = [
        str(path.resolve())
        for path in (project_path, runtime_providers_path, evaluation_contract_path)
        if path.exists()
    ]
    plain_facts_path = next((repo_root / name for name, _ in _PLAIN_PROJECT_FACT_FILES if (repo_root / name).exists()), None)
    if not contract_root.exists() and plain_facts_path is not None:
        plain_payload = _load_yaml_mapping(plain_facts_path)
        plain_project = plain_payload.get("project") if isinstance(plain_payload.get("project"), dict) else {}
        plain_artifacts_payload = plain_payload.get("artifacts") if isinstance(plain_payload.get("artifacts"), dict) else {}
        contract_requirements = _plain_contract_requirements(plain_payload, plain_project)
        unoperationalized_fields = sorted(
            str(key)
            for key in plain_payload
            if str(key) not in _PLAIN_OPERATIONAL_TOP_LEVEL_FIELDS
        )
        warnings = [
            "Plain project facts contain top-level fields that are preserved in the project contract "
            f"but not operationalized in mission config or prompts: {', '.join(unoperationalized_fields)}."
        ] if unoperationalized_fields else []
        fallback_artifacts = _default_plain_artifacts(repo_root)
        plain_docs = _normalize_paths(plain_artifacts_payload.get("docs"), base_dir=repo_root) or fallback_artifacts["docs"]
        plain_configs = _normalize_paths(plain_artifacts_payload.get("configs"), base_dir=repo_root) or fallback_artifacts["configs"]
        plain_data = normalize_data_artifacts(plain_artifacts_payload.get("data"), base_dir=repo_root)
        return {
            "status": "plain-artifacts",
            "repo_root": str(repo_root),
            "contract_root": str(repo_root),
            "project_metadata": plain_project,
            "contract_requirements": contract_requirements,
            "contract_coverage": _contract_coverage(contract_requirements, unoperationalized_fields),
            "unoperationalized_fields": unoperationalized_fields,
            "guidance_paths": guidance_paths,
            "contract_files": [str(plain_facts_path.resolve())],
            "artifacts": {
                "docs": plain_docs,
                "configs": plain_configs,
                "data": plain_data,
            },
            "runtime_providers_path": None,
            "evaluation_contract_path": None,
            "mission_files": [],
            "recommended_files": [str(plain_facts_path.resolve())],
            "missing_recommended_files": [],
            "scaffold_recommendations": [],
            "warnings": [
                *warnings,
                *_config_extension_warnings(plain_configs, source=str(plain_facts_path.resolve())),
            ],
        }
    warnings: list[str] = []
    if not contract_root.exists():
        warnings.append("Project does not define a `.deeploop/` contract directory yet.")
    elif missing_recommended:
        warnings.append("Project `.deeploop/` contract is partial; recommended contract files are missing.")
    warnings.extend(_config_extension_warnings(configs, source=str(project_path.resolve())))
    return {
        "status": "available" if contract_root.exists() else "missing",
        "repo_root": str(repo_root),
        "contract_root": str(contract_root),
        "project_metadata": project_payload.get("project") if isinstance(project_payload.get("project"), dict) else {},
        "guidance_paths": guidance_paths,
        "contract_files": contract_files,
        "artifacts": {
            "docs": docs,
            "configs": configs,
            "data": data,
        },
        "runtime_providers_path": str(runtime_providers_path.resolve()) if runtime_providers_path.exists() else None,
        "evaluation_contract_path": str(evaluation_contract_path.resolve()) if evaluation_contract_path.exists() else None,
        "mission_files": mission_files,
        "recommended_files": recommended_files,
        "missing_recommended_files": missing_recommended,
        "scaffold_recommendations": scaffold_recommendations,
        "warnings": warnings,
    }


def resolve_runtime_provider(contract: dict[str, Any], provider_id: str) -> dict[str, Any] | None:
    runtime_providers_path = contract.get("runtime_providers_path")
    contract_root = contract.get("contract_root")
    if not runtime_providers_path or not contract_root:
        return None
    providers_payload = _load_yaml_mapping(Path(str(runtime_providers_path)))
    providers = providers_payload.get("providers")
    if providers is None:
        return None
    if not isinstance(providers, dict):
        raise ValueError(f"Expected `providers` mapping in {runtime_providers_path}.")
    provider = providers.get(str(provider_id))
    if not isinstance(provider, dict):
        return None
    entrypoint = str(provider.get("entrypoint") or "").strip()
    if not entrypoint:
        raise ValueError(f"Runtime provider `{provider_id}` in {runtime_providers_path} is missing `entrypoint`.")
    params = provider.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError(f"Runtime provider `{provider_id}` in {runtime_providers_path} must declare params as a mapping.")
    resolved_params = _resolve_provider_value(params, base_dir=Path(str(contract_root)), key=None)
    pythonpath = _resolve_provider_pythonpath(
        provider.get("pythonpath"),
        base_dir=Path(str(contract_root)),
        runtime_providers_path=str(runtime_providers_path),
    )
    return {
        "provider_id": str(provider_id),
        "entrypoint": entrypoint,
        "pythonpath": pythonpath,
        "params": resolved_params if isinstance(resolved_params, dict) else {},
    }


def project_contract_input_artifacts(contract: dict[str, Any]) -> list[str]:
    artifact_payload = contract.get("artifacts") if isinstance(contract.get("artifacts"), dict) else {}
    docs = [str(path) for path in artifact_payload.get("docs", [])]
    configs = [str(path) for path in artifact_payload.get("configs", [])]
    data = [
        str(item.get("path"))
        for item in artifact_payload.get("data", [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    contract_files = [str(path) for path in contract.get("contract_files", [])]
    mission_files = [str(path) for path in contract.get("mission_files", [])]
    return _dedupe_strings(contract_files + mission_files + docs + configs + data)
