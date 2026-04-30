from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

from deeploop.artifacts.release_automation import (
    build_package_release_automation,
    build_release_candidate_review,
    load_release_candidate_policy,
    materialize_release_candidate_review,
)
from deeploop.core.structured_io import (
    load_json_object as _load_json,
    load_jsonl_objects as _load_jsonl,
    load_yaml_mapping as _load_yaml,
)
from deeploop.core.paths import REPO_ROOT, RUNS_DIR, WORKSPACE_ROOT

PACKAGE_CONTRACT_PATH = REPO_ROOT / "configs" / "runtime" / "artifact-package-contract.yaml"
PACKAGE_SCHEMA_PATH = REPO_ROOT / "schemas" / "mission-artifact-package.schema.json"
EVIDENCE_POLICY_PATH = REPO_ROOT / "configs" / "autonomy" / "evidence-policy.yaml"

CLAIM_ORDER = {
    "not-ready": -1,
    "exploratory": 0,
    "replicated": 1,
    "paper-candidate": 2,
    "release-candidate": 3,
}
DEFAULT_CATEGORIES = (
    "mission_specs",
    "mission_configs",
    "ledgers",
    "findings",
    "manifests",
    "task_metrics",
    "task_predictions",
    "task_run_logs",
    "task_method_artifacts",
    "kernel_outputs",
    "critique_reports",
    "runtime_metadata",
    "plain_folder_smoke_metadata",
)


def _remove_tree(path: Path) -> None:
    for attempt in range(3):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        if attempt < 2:
            time.sleep(0.1)
    if path.exists():
        raise OSError(f"Unable to remove existing package directory: {path}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _safe_resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _infer_repo_root_from_contract_path(contract_path: Path) -> Path | None:
    for parent in contract_path.parents:
        if parent.name == "configs":
            return parent.parent
    return None


def _resolve_contract_declared_path(raw_path: str | Path, *, contract_path: Path) -> Path:
    raw_text = str(raw_path)
    normalized_text = raw_text.replace("\\", "/")
    candidate = Path(normalized_text).expanduser()
    if candidate.is_absolute() or raw_text.startswith("~"):
        return candidate.resolve()
    if normalized_text.startswith(("./", "../")):
        return (contract_path.parent / candidate).resolve()
    repo_root = _infer_repo_root_from_contract_path(contract_path)
    if repo_root is not None:
        return (repo_root / candidate).resolve()
    return (contract_path.parent / candidate).resolve()


def _packaged_artifacts_root(source_path: Path) -> Path | None:
    for parent in source_path.resolve().parents:
        if parent.name == "artifacts":
            return parent
    return None


def _resolve_existing_or_packaged_path(raw_path: str | Path, *, source_path: Path) -> Path:
    resolved = _safe_resolve(raw_path)
    if resolved.exists():
        return resolved
    packaged_root = _packaged_artifacts_root(source_path)
    if packaged_root is None or not _is_relative_to(resolved, WORKSPACE_ROOT):
        return resolved
    candidate = packaged_root / resolved.relative_to(WORKSPACE_ROOT)
    return candidate.resolve() if candidate.exists() else resolved


def _artifact_id_for_path(path: Path) -> str:
    resolved = path.resolve()
    if _is_relative_to(resolved, WORKSPACE_ROOT):
        relative = resolved.relative_to(WORKSPACE_ROOT).as_posix()
    else:
        relative = resolved.as_posix().lstrip("/")
    return relative.replace("/", "::")


def _package_relative_path(path: Path, copied_root_name: str) -> Path:
    resolved = path.resolve()
    if _is_relative_to(resolved, WORKSPACE_ROOT):
        return Path(copied_root_name) / resolved.relative_to(WORKSPACE_ROOT)
    return Path(copied_root_name) / "external" / resolved.as_posix().lstrip("/")


def _infer_manifest_stage(manifest_path: Path, manifest: dict[str, Any]) -> str:
    stage = manifest.get("stage", {})
    if isinstance(stage, dict):
        stage_id = stage.get("id")
        if isinstance(stage_id, str) and stage_id:
            return stage_id
    loop_id = str(manifest.get("loop_id", "")).lower()
    metrics = manifest.get("metrics", {}) if isinstance(manifest.get("metrics"), dict) else {}
    if manifest_path.name == "run_manifest.json":
        return "baseline-evaluation"
    if "localization_source_exists" in metrics or "intervention" in loop_id:
        return "causal-intervention"
    if "source_accuracy" in metrics or "candidate_count" in metrics or "mech" in loop_id:
        return "mechanistic-localization"
    return "unknown"


def _primary_metric(manifest: dict[str, Any]) -> tuple[str | None, float | None]:
    metrics = manifest.get("metrics", {})
    if not isinstance(metrics, dict):
        return (None, None)
    for key in ("accuracy", "accuracy_post", "accuracy_delta", "source_accuracy", "baseline_accuracy"):
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            return (key, float(value))
    return (None, None)


def _manifest_summary_lines(manifest: dict[str, Any]) -> list[str]:
    notes = manifest.get("notes", [])
    lines = [str(note).strip() for note in notes if str(note).strip()]
    metric_name, metric_value = _primary_metric(manifest)
    if metric_name is not None and metric_value is not None:
        lines.insert(0, f"{metric_name}: {metric_value:.6g}")
    status = manifest.get("run", {}).get("status")
    if isinstance(status, str) and status:
        lines.insert(0, f"status: {status}")
    return lines[:4]


def _next_claim_state(current_state: str) -> str | None:
    ordered = sorted(
        ((rank, state) for state, rank in CLAIM_ORDER.items() if rank >= 0),
        key=lambda item: item[0],
    )
    current_rank = CLAIM_ORDER.get(current_state, 0)
    for rank, state in ordered:
        if rank > current_rank:
            return state
    return None


def _build_replication_evidence(run_bundles: list[dict[str, Any]]) -> dict[str, Any]:
    manifest_groups: dict[str, list[str]] = {}
    for bundle in run_bundles:
        loop_id = str(bundle.get("loop_id") or "unknown")
        manifest_id = str(bundle.get("manifest_artifact_id") or "").strip()
        if not manifest_id:
            continue
        manifest_groups.setdefault(loop_id, []).append(manifest_id)
    return {
        "total_manifests": len([bundle for bundle in run_bundles if bundle.get("manifest_artifact_id")]),
        "independent_runs": len(manifest_groups),
        "manifest_groups": manifest_groups,
    }


def _bundle_has_replication_signal(bundle: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            str(bundle.get("loop_id") or ""),
            str(bundle.get("stage_id") or ""),
            *[str(item) for item in bundle.get("notes") or []],
        ]
    ).lower()
    return any(token in haystack for token in ("replication", "follow-up", "followup", "repeated-run", "repeat"))


def _max_claim_state(states: list[str]) -> str:
    if not states:
        return "exploratory"
    return max(states, key=lambda state: CLAIM_ORDER.get(state, CLAIM_ORDER["exploratory"]))


def _package_evidence_state(max_manifest_state: str, run_bundles: list[dict[str, Any]]) -> str:
    derived_states = [max_manifest_state]
    if len([bundle for bundle in run_bundles if bundle.get("manifest_artifact_id")]) >= 2 and any(
        _bundle_has_replication_signal(bundle) for bundle in run_bundles
    ):
        derived_states.append("replicated")
    return _max_claim_state(derived_states)


def _state_requirements(policy: dict[str, Any], state_id: str) -> list[str]:
    for entry in policy.get("claim_states", []):
        if entry.get("id") == state_id:
            return [str(item) for item in entry.get("promotion_requirements", [])]
    return []


def _find_critique_ceiling(critique_reports: list[dict[str, Any]]) -> str:
    ceiling = "release-candidate"
    ceiling_rank = CLAIM_ORDER[ceiling]
    for report in critique_reports:
        metadata = report.get("metadata", {})
        critique_ceiling = metadata.get("critique_ceiling")
        if isinstance(critique_ceiling, str) and critique_ceiling in CLAIM_ORDER:
            rank = CLAIM_ORDER[critique_ceiling]
            if rank < ceiling_rank:
                ceiling = critique_ceiling
                ceiling_rank = rank
    return ceiling


def _extract_text_bullets(path: Path, *, limit: int = 4) -> list[str]:
    bullets: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:]
        bullets.append(stripped)
        if len(bullets) >= limit:
            break
    return bullets


def load_package_contract(path: Path = PACKAGE_CONTRACT_PATH) -> dict[str, Any]:
    return _load_yaml(path)


def validate_package_manifest(package: dict[str, Any], schema_path: Path = PACKAGE_SCHEMA_PATH) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return []

    try:
        jsonschema.validate(package, _load_json(schema_path))
    except Exception as exc:  # pragma: no cover - jsonschema type depends on install
        return [str(exc)]
    return []


def _validate_output_root(output_root: Path, mission_state: dict[str, Any]) -> None:
    if not _is_relative_to(output_root, WORKSPACE_ROOT / "runs"):
        raise ValueError(f"Package output root must stay under {WORKSPACE_ROOT / 'runs'}: {output_root}")
    repo_paths = [REPO_ROOT]
    target_repo = mission_state.get("target_repo")
    if isinstance(target_repo, str) and target_repo:
        repo_paths.append(_safe_resolve(target_repo))
    if any(_is_relative_to(output_root, repo_path) for repo_path in repo_paths):
        raise ValueError(f"Package output root must remain outside repo trees: {output_root}")


def _copy_artifact(source_path: Path, package_root: Path, copied_root_name: str) -> tuple[Path, int]:
    package_path = package_root / _package_relative_path(source_path, copied_root_name)
    package_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, package_path)
    return package_path, package_path.stat().st_size


def _resolve_manifest_paths(search_roots: list[Path], mission_id: str, patterns: list[str]) -> list[Path]:
    manifests: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        for pattern in patterns:
            for path in sorted(root.glob(pattern)):
                if not path.is_file():
                    continue
                try:
                    manifest = _load_json(path)
                except Exception:
                    continue
                if manifest.get("mission_id") == mission_id:
                    manifests.append(path.resolve())
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in manifests:
        if path not in seen:
            ordered.append(path)
            seen.add(path)
    return ordered


def _bundle_related_paths(manifest_path: Path, manifest: dict[str, Any], contract: dict[str, Any]) -> tuple[list[Path], list[Path]]:
    artifact_cfg = contract.get("artifact_map", {})
    kernel_paths: set[Path] = set()
    critique_paths: set[Path] = set()

    artifacts = manifest.get("artifacts", {})
    if isinstance(artifacts, dict):
        log_path = artifacts.get("log_path")
        if isinstance(log_path, str) and log_path:
            resolved = _resolve_existing_or_packaged_path(log_path, source_path=manifest_path)
            if resolved.exists() and resolved.is_file():
                kernel_paths.add(resolved)
        for report_path in artifacts.get("report_paths", []):
            if isinstance(report_path, str) and report_path:
                resolved = _resolve_existing_or_packaged_path(report_path, source_path=manifest_path)
                if resolved.exists() and resolved.is_file():
                    kernel_paths.add(resolved)

    stage_artifacts = manifest.get("stage_context", {}).get("artifacts", {})
    if isinstance(stage_artifacts, dict):
        for raw_path in stage_artifacts.values():
            if isinstance(raw_path, str) and raw_path:
                resolved = _resolve_existing_or_packaged_path(raw_path, source_path=manifest_path)
                if resolved.exists() and resolved.is_file():
                    kernel_paths.add(resolved)

    output_dir = artifacts.get("output_dir") if isinstance(artifacts, dict) else None
    if isinstance(output_dir, str) and output_dir:
        output_root = _resolve_existing_or_packaged_path(output_dir, source_path=manifest_path)
        for pattern in artifact_cfg.get("kernel_output_globs", []):
            for path in sorted(output_root.glob(pattern)):
                if path.is_file():
                    kernel_paths.add(path.resolve())
        for pattern in artifact_cfg.get("critique_report_globs", []):
            for path in sorted(output_root.glob(pattern)):
                if path.is_file():
                    critique_paths.add(path.resolve())

    critique_json_candidates = [
        path
        for path in critique_paths
        if path.suffix.lower() == ".json"
    ]
    for critique_json in critique_json_candidates:
        try:
            report = _load_json(critique_json)
        except Exception:
            continue
        artifacts_payload = report.get("artifacts", {})
        if isinstance(artifacts_payload, dict):
            for key in ("report_markdown", "co_located_markdown", "co_located_json"):
                raw_path = artifacts_payload.get(key)
                if isinstance(raw_path, str) and raw_path:
                    resolved = _resolve_existing_or_packaged_path(raw_path, source_path=critique_json)
                    if resolved.exists() and resolved.is_file():
                        critique_paths.add(resolved)

    return (sorted(kernel_paths), sorted(critique_paths))


def _collect_global_reports(
    contract: dict[str, Any],
    mission_aliases: set[str],
) -> list[tuple[Path, str, dict[str, Any]]]:
    collected: list[tuple[Path, str, dict[str, Any]]] = []
    for report_root_cfg in contract.get("artifact_map", {}).get("global_report_roots", {}).values():
        root = _safe_resolve(report_root_cfg["root"])
        if not root.exists():
            continue
        for pattern in report_root_cfg.get("patterns", []):
            for path in sorted(root.glob(pattern)):
                if not path.is_file():
                    continue
                metadata: dict[str, Any] = {}
                if path.suffix.lower() == ".json":
                    try:
                        payload = _load_json(path)
                    except Exception:
                        continue
                    mission_id = payload.get("mission_id")
                    if mission_id not in mission_aliases:
                        continue
                    if "promotion_guidance" in payload and isinstance(payload["promotion_guidance"], dict):
                        critique_ceiling = payload["promotion_guidance"].get("max_allowed_state")
                        if isinstance(critique_ceiling, str):
                            metadata["critique_ceiling"] = critique_ceiling
                        reasons = payload["promotion_guidance"].get("reasons", [])
                        metadata["promotion_reasons"] = [str(reason) for reason in reasons]
                    if isinstance(payload.get("warnings"), list):
                        metadata["warnings"] = [
                            str(item.get("message"))
                            for item in payload["warnings"]
                            if isinstance(item, dict) and item.get("message")
                        ]
                elif path.parent.name not in mission_aliases and not any(alias in path.parts for alias in mission_aliases):
                    continue
                collected.append((path.resolve(), "critique_reports", metadata))
    return collected


def _reference_paths_from_manifest(manifest_path: Path, manifest: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    field_paths = (
        ("behavioral_source_manifest",),
        ("localization_source",),
        ("dataset", "provenance"),
        ("evaluation", "compare_against"),
        ("stage_context", "behavioral_source_manifest"),
    )
    for dotted in field_paths:
        current: Any = manifest
        for part in dotted:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if isinstance(current, str) and current:
            candidates.append(_resolve_existing_or_packaged_path(current, source_path=manifest_path))
    return candidates


def _artifact_kind_for_path(path: Path, category: str) -> str:
    name = path.name
    if category == "ledgers":
        return "ledger"
    if category == "findings":
        return "finding"
    if category == "runtime_metadata":
        if "agent_handoffs" in path.parts:
            return "agent-handoff"
        if path.name.startswith("mission_meta_eval"):
            return "mission-meta-eval"
        return "runtime-metadata"
    if category == "mission_specs":
        if name == "mission_state.json":
            return "mission-state"
        if name == "mission_summary.md":
            return "mission-summary"
        if name.startswith("bounded_followup_plan"):
            return "bounded-followup-plan"
        if name.startswith("mission_next_actions"):
            return "mission-next-actions"
        return "mission-spec"
    if category == "mission_configs":
        return "mission-config"
    if category == "manifests":
        return "study-manifest" if name == "study_manifest.json" else "run-manifest"
    if category == "task_metrics":
        return "task-metrics"
    if category == "task_predictions":
        return "task-predictions"
    if category == "task_run_logs":
        lowered = name.lower()
        if "stability" in lowered:
            return "task-stability-notes"
        return "task-run-log"
    if category == "task_method_artifacts":
        return "task-method-artifact"
    if category == "plain_folder_smoke_metadata":
        return "plain-folder-smoke-metadata"
    if category == "kernel_outputs":
        if name.endswith(".jsonl"):
            return "kernel-records"
        if "metrics" in name:
            return "kernel-metrics"
        return "kernel-output"
    if category == "critique_reports":
        lowered = name.lower()
        if "statistical_rigor" in lowered:
            return "statistical-rigor-report"
        if "self_optimization" in lowered:
            return "self-optimization-report"
        if "redteam" in lowered:
            return "fresh-context-redteam-report"
        if "self_correction" in lowered:
            return "self-correction-report"
        if "confound_guard" in lowered:
            return "confound-guard-report"
        return "critique-report"
    return "artifact"


def _artifact_label(path: Path, category: str) -> str:
    if category == "manifests":
        return path.parent.name
    if category == "critique_reports":
        return path.stem
    if category == "mission_configs" and "repos" in path.parts:
        return path.relative_to(WORKSPACE_ROOT / "repos").as_posix()
    if category == "mission_specs" and "repos" in path.parts:
        return path.relative_to(WORKSPACE_ROOT / "repos").as_posix()
    return path.name


def _looks_like_artifact_path(raw: str) -> bool:
    text = raw.strip()
    if not text:
        return False
    if text.startswith(("~", "/", ".")) or "/" in text or "\\" in text:
        return True
    return bool(Path(text).suffix)


def _recorded_artifact_category(path: Path) -> str:
    lowered_name = path.name.lower()
    lowered_parts = {part.lower() for part in path.parts}
    lowered_path = path.as_posix().lower()
    if "plain_folder_followups" in lowered_parts or "plain-folder" in lowered_path:
        return "plain_folder_smoke_metadata"
    if "metrics" in lowered_name:
        return "task_metrics"
    if "prediction" in lowered_name or "predictions" in lowered_name or "model-output" in lowered_name:
        return "task_predictions"
    if lowered_name.endswith(".log") or lowered_name in {"run-log.txt", "run_log.txt"} or "stability" in lowered_name:
        return "task_run_logs"
    if any(
        token in lowered_name
        for token in (
            "prior-art",
            "hypotheses",
            "evaluation-targets",
            "watchlist",
            "run-manifest-draft",
            "execution-profile",
            "resource-tier",
            "method",
        )
    ):
        return "task_method_artifacts"
    return "task_method_artifacts"


def _resolve_recorded_artifact_path(raw_path: str, *, source_path: Path, mission_root: Path, target_repo: Path) -> Path:
    raw_text = raw_path.strip()
    candidate = Path(raw_text).expanduser()
    if candidate.is_absolute() or raw_text.startswith("~"):
        return _resolve_existing_or_packaged_path(raw_text, source_path=source_path)
    for root in (mission_root, target_repo, WORKSPACE_ROOT, REPO_ROOT):
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return (mission_root / candidate).resolve()


def _strings_from_value(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple, set)):
        values: list[str] = []
        for item in raw:
            values.extend(_strings_from_value(item))
        return values
    return []


def _metric_fragments(path: Path, *, limit: int = 3) -> list[str]:
    if path.suffix.lower() != ".json":
        return []
    try:
        payload = _load_json(path)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else payload
    fragments: list[str] = []
    for key, value in metrics.items():
        if isinstance(value, (int, float)):
            fragments.append(f"{key}={value:.6g}")
        if len(fragments) >= limit:
            break
    return fragments


def _artifact_bullets(artifacts: list[dict[str, Any]], artifact_ids: list[str], *, prefix: str, limit: int = 4) -> list[str]:
    selected_ids = set(artifact_ids[:limit])
    bullets: list[str] = []
    for artifact in artifacts:
        if artifact["artifact_id"] not in selected_ids:
            continue
        fragments = _metric_fragments(Path(artifact["source_path"]))
        detail = f" — {', '.join(fragments)}" if fragments else ""
        bullets.append(f"{prefix}: {artifact['label']} (`{artifact['artifact_id']}`){detail}.")
    return bullets


def package_mission_artifacts(
    mission_state_path: Path,
    *,
    contract_path: Path = PACKAGE_CONTRACT_PATH,
    output_root: Path | None = None,
) -> dict[str, Any]:
    mission_state_path = mission_state_path.expanduser().resolve()
    contract_path = contract_path.expanduser().resolve()
    mission_state = _load_json(mission_state_path)
    mission_root = mission_state_path.parent
    mission_id = str(mission_state["mission_id"])
    target_repo = _safe_resolve(mission_state["target_repo"])
    contract = load_package_contract(contract_path)
    evidence_policy = _load_yaml(EVIDENCE_POLICY_PATH)

    resolved_output_root = _safe_resolve(output_root or contract.get("output_root", RUNS_DIR / "packages"))
    _validate_output_root(resolved_output_root, mission_state)
    package_root = resolved_output_root / mission_id
    if package_root.exists():
        _remove_tree(package_root)
    package_root.mkdir(parents=True, exist_ok=True)

    copied_root_name = str(contract.get("outputs", {}).get("copied_artifact_root", "artifacts"))
    artifact_registry: dict[Path, dict[str, Any]] = {}
    category_membership: dict[str, set[str]] = {category: set() for category in DEFAULT_CATEGORIES}
    pending_links: set[tuple[Path, Path, str]] = set()
    pending_artifact_ids: set[str] = set()
    recorded_output_artifacts: dict[str, dict[str, Any]] = {}

    def register_artifact(
        path: Path,
        *,
        category: str,
        claim_state: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
        lazy: bool = False,
    ) -> str:
        resolved = path.expanduser().resolve()
        is_file_missing = not resolved.exists() or not resolved.is_file()
        if is_file_missing and not lazy:
            raise FileNotFoundError(resolved)
        artifact_id = _artifact_id_for_path(resolved)
        record = artifact_registry.get(resolved)
        if record is None:
            record = {
                "artifact_id": artifact_id,
                "kind": _artifact_kind_for_path(resolved, category),
                "label": _artifact_label(resolved, category),
                "source_path": str(resolved),
                "package_path": None,
                "status": "pending" if is_file_missing else status,
                "claim_state": claim_state,
                "size_bytes": 0,
                "metadata": dict(metadata or {}),
            }
            artifact_registry[resolved] = record
        else:
            if claim_state and not record.get("claim_state"):
                record["claim_state"] = claim_state
            if status and not record.get("status") and not is_file_missing:
                record["status"] = status
            if metadata:
                record["metadata"].update(metadata)
        if is_file_missing:
            pending_artifact_ids.add(artifact_id)
        else:
            category_membership.setdefault(category, set()).add(artifact_id)
        return artifact_id

    def maybe_register(path: str | Path, *, category: str, metadata: dict[str, Any] | None = None) -> str | None:
        resolved = _safe_resolve(path)
        if not resolved.exists() or not resolved.is_file():
            return None
        return register_artifact(resolved, category=category, metadata=metadata)

    artifact_cfg = contract.get("artifact_map", {})
    for category, patterns in artifact_cfg.get("mission_root_sections", {}).items():
        for pattern in patterns:
            for matched in sorted(mission_root.glob(pattern)):
                if matched.is_file():
                    register_artifact(matched, category=category)

    for raw_doc in mission_state.get("artifacts", {}).get("docs", []):
        maybe_register(raw_doc, category="mission_specs", metadata={"declared_by": "mission_state.artifacts.docs"})
    for raw_config in mission_state.get("artifacts", {}).get("configs", []):
        maybe_register(raw_config, category="mission_configs", metadata={"declared_by": "mission_state.artifacts.configs"})
    for raw_config in mission_state.get("next_actions", {}).get("generated_configs", []):
        maybe_register(raw_config, category="mission_configs", metadata={"declared_by": "mission_state.next_actions.generated_configs"})
    for support_path in contract.get("supporting_contracts", []):
        maybe_register(
            _resolve_contract_declared_path(support_path, contract_path=contract_path),
            category="mission_configs",
            metadata={"declared_by": "artifact_package_contract"},
        )

    def register_recorded_output(raw_path: str, *, declared_by: str, source_path: Path, phase: str | None = None) -> None:
        if not _looks_like_artifact_path(raw_path):
            return
        resolved = _resolve_recorded_artifact_path(
            raw_path,
            source_path=source_path,
            mission_root=mission_root,
            target_repo=target_repo,
        )
        category = _recorded_artifact_category(resolved)
        metadata: dict[str, Any] = {"declared_by": declared_by, "science_handoff": True}
        if phase:
            metadata["phase"] = phase
        artifact_id = register_artifact(resolved, category=category, metadata=metadata, lazy=True)
        if category != "plain_folder_smoke_metadata" and resolved.exists() and resolved.is_file():
            category_membership.setdefault("kernel_outputs", set()).add(artifact_id)
        record = recorded_output_artifacts.setdefault(
            artifact_id,
            {
                "artifact_id": artifact_id,
                "source_path": str(resolved),
                "declared_by": [],
                "category": category,
                "phase": phase,
            },
        )
        declared_sources = record.setdefault("declared_by", [])
        if declared_by not in declared_sources:
            declared_sources.append(declared_by)
        if phase and not record.get("phase"):
            record["phase"] = phase

    def register_outputs_from_mapping(mapping: Any, *, declared_by: str, source_path: Path, phase: str | None = None) -> None:
        if not isinstance(mapping, dict):
            return
        for key in ("produced_artifacts", "output_paths", "artifact_paths"):
            for raw_path in _strings_from_value(mapping.get(key)):
                register_recorded_output(raw_path, declared_by=f"{declared_by}.{key}", source_path=source_path, phase=phase)
        action_result = mapping.get("action_result")
        if isinstance(action_result, dict):
            action_phase = str(action_result.get("phase") or phase or "").strip() or phase
            for raw_path in _strings_from_value(action_result.get("output_paths")):
                register_recorded_output(
                    raw_path,
                    declared_by=f"{declared_by}.action_result.output_paths",
                    source_path=source_path,
                    phase=action_phase,
                )
        latest_outcome = mapping.get("latest_outcome")
        if isinstance(latest_outcome, dict):
            register_outputs_from_mapping(latest_outcome, declared_by=f"{declared_by}.latest_outcome", source_path=source_path, phase=phase)

    register_outputs_from_mapping(mission_state, declared_by="mission_state", source_path=mission_state_path)
    phase_outputs = mission_state.get("phase_outputs_by_phase")
    if isinstance(phase_outputs, dict):
        for phase, outputs in phase_outputs.items():
            for raw_path in _strings_from_value(outputs):
                register_recorded_output(
                    raw_path,
                    declared_by="mission_state.phase_outputs_by_phase",
                    source_path=mission_state_path,
                    phase=str(phase),
                )
    for index, action in enumerate(mission_state.get("next_actions", {}).get("actions", [])):
        if not isinstance(action, dict):
            continue
        action_phase = str(action.get("phase") or "").strip() or None
        for raw_path in _strings_from_value(action.get("output_paths")):
            register_recorded_output(
                raw_path,
                declared_by=f"mission_state.next_actions.actions[{index}].output_paths",
                source_path=mission_state_path,
                phase=action_phase,
            )
    agent_driver = mission_state.get("agent_driver")
    if isinstance(agent_driver, dict):
        register_outputs_from_mapping(agent_driver, declared_by="mission_state.agent_driver", source_path=mission_state_path)
        memory_path_raw = agent_driver.get("memory_path")
        if isinstance(memory_path_raw, str) and memory_path_raw:
            memory_path = _resolve_recorded_artifact_path(
                memory_path_raw,
                source_path=mission_state_path,
                mission_root=mission_root,
                target_repo=target_repo,
            )
            if memory_path.exists() and memory_path.is_file():
                for entry in _load_jsonl(memory_path):
                    if isinstance(entry, dict):
                        register_outputs_from_mapping(entry, declared_by="agent_driver.memory", source_path=memory_path, phase=str(entry.get("phase") or "") or None)
    experiments_path = mission_root / "mission_experiments.jsonl"
    if experiments_path.exists():
        for entry in _load_jsonl(experiments_path):
            if isinstance(entry, dict):
                register_outputs_from_mapping(entry, declared_by="mission_experiments", source_path=experiments_path, phase=str(entry.get("phase") or "") or None)

    mission_aliases = {mission_id, mission_id.removesuffix("-mission")}
    manifest_search_roots = [
        WORKSPACE_ROOT / "runs" / target_repo.name,
        mission_root,
    ]
    manifest_paths = _resolve_manifest_paths(
        manifest_search_roots,
        mission_id,
        [str(item) for item in artifact_cfg.get("manifest_patterns", [])],
    )

    run_bundles: list[dict[str, Any]] = []
    for manifest_path in manifest_paths:
        manifest = _load_json(manifest_path)
        manifest_artifact_id = register_artifact(
            manifest_path,
            category="manifests",
            claim_state=str(manifest.get("claim_state")) if manifest.get("claim_state") else None,
            status=str(manifest.get("run", {}).get("status")) if manifest.get("run", {}).get("status") else None,
            metadata={"loop_id": manifest.get("loop_id")},
        )

        for referenced_path in _reference_paths_from_manifest(manifest_path, manifest):
            reference_category = (
                "manifests"
                if referenced_path.name in {"run_manifest.json", "study_manifest.json"}
                else "mission_configs"
            )
            register_artifact(referenced_path, category=reference_category, lazy=True)
            pending_links.add((manifest_path, referenced_path, "depends-on"))

        kernel_paths, critique_paths = _bundle_related_paths(manifest_path, manifest, contract)
        bundle_artifact_ids = [manifest_artifact_id]
        critique_artifact_ids: list[str] = []
        for kernel_path in kernel_paths:
            kernel_category = _recorded_artifact_category(kernel_path)
            kernel_id = register_artifact(kernel_path, category=kernel_category)
            category_membership.setdefault("kernel_outputs", set()).add(kernel_id)
            bundle_artifact_ids.append(kernel_id)
            pending_links.add((manifest_path, kernel_path, "produces"))
        for critique_path in critique_paths:
            critique_metadata: dict[str, Any] = {}
            if critique_path.suffix.lower() == ".json":
                try:
                    report = _load_json(critique_path)
                except Exception:
                    report = {}
                if isinstance(report.get("promotion_guidance"), dict):
                    critique_ceiling = report["promotion_guidance"].get("max_allowed_state")
                    if isinstance(critique_ceiling, str):
                        critique_metadata["critique_ceiling"] = critique_ceiling
                    reasons = report["promotion_guidance"].get("reasons", [])
                    critique_metadata["promotion_reasons"] = [str(reason) for reason in reasons]
                warnings = report.get("warnings")
                if isinstance(warnings, list):
                    critique_metadata["warnings"] = [
                        str(item.get("message"))
                        for item in warnings
                        if isinstance(item, dict) and item.get("message")
                    ]
            critique_id = register_artifact(critique_path, category="critique_reports", metadata=critique_metadata)
            critique_artifact_ids.append(critique_id)
            pending_links.add((critique_path, manifest_path, "evaluates"))

        metric_name, metric_value = _primary_metric(manifest)
        run_bundles.append(
            {
                "bundle_id": manifest_path.parent.name,
                "loop_id": str(manifest.get("loop_id", manifest_path.parent.name)),
                "stage_id": _infer_manifest_stage(manifest_path, manifest),
                "manifest_artifact_id": manifest_artifact_id,
                "status": str(manifest.get("run", {}).get("status", "unknown")),
                "claim_state": str(manifest.get("claim_state", "exploratory")),
                "artifact_ids": sorted(set(bundle_artifact_ids)),
                "critique_artifact_ids": sorted(set(critique_artifact_ids)),
                "primary_metric": metric_value,
                "metric_name": metric_name,
                "summary_lines": _manifest_summary_lines(manifest),
                "notes": [str(item) for item in manifest.get("notes", []) if str(item).strip()],
            }
        )

    for report_path, category, metadata in _collect_global_reports(contract, mission_aliases):
        register_artifact(report_path, category=category, metadata=metadata)

    ledger_path = mission_root / "ledger.jsonl"
    if ledger_path.exists():
        ledger_artifact_id = register_artifact(ledger_path, category="ledgers")
        for entry in _load_jsonl(ledger_path):
            related_paths = entry.get("related_paths", [])
            for raw_path in related_paths:
                if not isinstance(raw_path, str):
                    continue
                related_path = _safe_resolve(raw_path)
                if not related_path.exists() or not related_path.is_file():
                    continue
                if related_path.name.endswith("manifest.json"):
                    category = "manifests"
                elif "findings" in related_path.parts:
                    category = "findings"
                elif "runtime" in related_path.parts or "agent_handoffs" in related_path.parts:
                    category = "runtime_metadata"
                elif "report" in related_path.name or "statistical_rigor" in related_path.name:
                    category = "critique_reports"
                elif related_path.suffix.lower() in {".yaml", ".yml", ".json"}:
                    category = "mission_configs"
                else:
                    category = "mission_specs"
                register_artifact(related_path, category=category)
                pending_links.add((ledger_path, related_path, "ledger-related"))
                if category == "critique_reports":
                    pending_links.add((related_path, ledger_path, "recorded-in"))
        category_membership["ledgers"].add(ledger_artifact_id)

    disappeared_paths = [
        path
        for path in artifact_registry
        if (not path.exists() or not path.is_file())
        and artifact_registry[path]["artifact_id"] not in pending_artifact_ids
    ]
    for path in disappeared_paths:
        artifact_id = artifact_registry[path]["artifact_id"]
        del artifact_registry[path]
        for artifact_ids in category_membership.values():
            artifact_ids.discard(artifact_id)

    missing_required_artifacts: list[str] = []
    required_filenames = {str(item) for item in contract.get("required_artifacts", {}).get("filenames", [])}
    existing_filenames = {path.name for path in artifact_registry}
    for filename in sorted(required_filenames):
        if filename not in existing_filenames:
            missing_required_artifacts.append(filename)
    required_categories = [str(item) for item in contract.get("required_artifacts", {}).get("categories", [])]
    for category in required_categories:
        if not category_membership.get(category):
            missing_required_artifacts.append(f"category:{category}")
    missing_recorded_output_artifacts = [
        {
            "artifact_id": record["artifact_id"],
            "source_path": record["source_path"],
            "declared_by": list(record.get("declared_by", [])),
            "category": record.get("category"),
            "phase": record.get("phase"),
            "reason": "declared by recursive-agent output metadata but the file was not found",
        }
        for record in sorted(recorded_output_artifacts.values(), key=lambda item: item["source_path"])
        if record["artifact_id"] in pending_artifact_ids
    ]
    for record in missing_recorded_output_artifacts:
        missing_required_artifacts.append(f"phase-output:{record['source_path']}")
    all_required_artifacts_present = not missing_required_artifacts
    missing_required_artifacts_summary = (
        f"Missing required mission artifacts: {', '.join(missing_required_artifacts)}"
        if missing_required_artifacts
        else None
    )

    digest = hashlib.sha256()
    for source_path in sorted(artifact_registry):
        if artifact_registry[source_path]["artifact_id"] in pending_artifact_ids:
            continue
        digest.update(str(source_path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(source_path.read_bytes())
        digest.update(b"\0")
    package_digest = digest.hexdigest()

    for source_path in sorted(artifact_registry):
        if artifact_registry[source_path]["artifact_id"] in pending_artifact_ids:
            continue
        package_path, size_bytes = _copy_artifact(source_path, package_root, copied_root_name)
        artifact_registry[source_path]["package_path"] = str(package_path.relative_to(package_root))
        artifact_registry[source_path]["size_bytes"] = size_bytes

    source_to_id = {source: record["artifact_id"] for source, record in artifact_registry.items()}
    cross_links: list[dict[str, str]] = []
    for source_path, target_path, relationship in sorted(pending_links, key=lambda item: (str(item[0]), str(item[1]), item[2])):
        source_id = source_to_id.get(source_path.resolve())
        target_id = source_to_id.get(target_path.resolve())
        if source_id and target_id:
            cross_links.append(
                {
                    "source_artifact_id": source_id,
                    "target_artifact_id": target_id,
                    "relationship": relationship,
                }
            )

    artifacts = sorted(
        (record for record in artifact_registry.values() if record["artifact_id"] not in pending_artifact_ids),
        key=lambda item: item["source_path"],
    )
    pending_artifacts = sorted(
        (record for record in artifact_registry.values() if record["artifact_id"] in pending_artifact_ids),
        key=lambda item: item["source_path"],
    )
    artifact_map = {
        category: sorted(category_membership.get(category, set()))
        for category in DEFAULT_CATEGORIES
    }

    critique_reports = [
        artifact
        for artifact in artifacts
        if artifact["artifact_id"] in set(artifact_map["critique_reports"])
    ]
    manifest_claim_counts: dict[str, int] = {}
    for bundle in run_bundles:
        manifest_claim_counts[bundle["claim_state"]] = manifest_claim_counts.get(bundle["claim_state"], 0) + 1
    max_manifest_state = _max_claim_state(list(manifest_claim_counts))
    critique_ceiling = _find_critique_ceiling(critique_reports)
    evidence_state = _package_evidence_state(max_manifest_state, run_bundles)
    package_claim_state = min(
        (evidence_state, critique_ceiling),
        key=lambda state: CLAIM_ORDER.get(state, CLAIM_ORDER["exploratory"]),
    )
    replication_evidence = _build_replication_evidence(run_bundles)
    next_state = _next_claim_state(package_claim_state)
    critique_reasons: list[str] = []
    critique_warnings: list[str] = []
    for artifact in critique_reports:
        metadata = artifact.get("metadata", {})
        for reason in metadata.get("promotion_reasons", []):
            if reason not in critique_reasons:
                critique_reasons.append(reason)
        for warning in metadata.get("warnings", []):
            if warning not in critique_warnings:
                critique_warnings.append(warning)

    top_bundles = sorted(
        run_bundles,
        key=lambda bundle: (
            bundle["primary_metric"] if bundle["primary_metric"] is not None else float("-inf"),
            bundle["loop_id"],
        ),
        reverse=True,
    )[:3]
    finding_ids = artifact_map["findings"]
    finding_artifacts = [artifact for artifact in artifacts if artifact["artifact_id"] in set(finding_ids)]
    finding_bullets: list[str] = []
    for finding in finding_artifacts:
        finding_bullets.extend(_extract_text_bullets(Path(finding["source_path"]), limit=2))
        if len(finding_bullets) >= 4:
            break
    task_evidence_bullets = _artifact_bullets(artifacts, artifact_map["task_metrics"], prefix="Task metric")
    task_evidence_bullets.extend(
        _artifact_bullets(artifacts, artifact_map["task_predictions"], prefix="Task prediction/model output", limit=3)
    )
    task_evidence_bullets.extend(_artifact_bullets(artifacts, artifact_map["task_run_logs"], prefix="Task run log", limit=3))
    task_evidence_bullets.extend(
        _artifact_bullets(artifacts, artifact_map["task_method_artifacts"], prefix="Task method artifact", limit=3)
    )
    if artifact_map["plain_folder_smoke_metadata"]:
        task_evidence_bullets.extend(
            _artifact_bullets(
                artifacts,
                artifact_map["plain_folder_smoke_metadata"],
                prefix="Plain-folder smoke metadata (not task evidence)",
                limit=3,
            )
        )
    if missing_recorded_output_artifacts:
        task_evidence_bullets.append(
            "Missing recorded task output artifacts: "
            + ", ".join(record["source_path"] for record in missing_recorded_output_artifacts[:4])
            + "."
        )
    if not task_evidence_bullets:
        task_evidence_bullets.append("No task-specific recursive-agent output artifacts were declared for packaging.")
    has_documented_caveats = bool(finding_artifacts or critique_reasons or critique_warnings)
    paper_blockers: list[str] = []
    if CLAIM_ORDER.get(package_claim_state, CLAIM_ORDER["exploratory"]) < CLAIM_ORDER["replicated"]:
        paper_blockers.append("replicated evidence")
    if not has_documented_caveats:
        paper_blockers.append("documented caveats")
    paper_blockers.append("human approval")
    if next_state == "paper-candidate" and CLAIM_ORDER.get(package_claim_state, CLAIM_ORDER["exploratory"]) >= CLAIM_ORDER["replicated"]:
        paper_blockers = [blocker for blocker in paper_blockers if blocker != "replicated evidence"]
    release_blockers: list[str] = []
    paper_candidate_equivalent = (
        CLAIM_ORDER.get(package_claim_state, CLAIM_ORDER["exploratory"]) >= CLAIM_ORDER["paper-candidate"]
        or (
            package_claim_state == "replicated"
            and all(blocker not in {"replicated evidence", "documented caveats"} for blocker in paper_blockers)
        )
    )
    if not paper_candidate_equivalent:
        release_blockers.append("paper-candidate evidence or equivalent rigor")
    release_blockers.extend(["provenance and licensing review", "human approval"])

    operator_key_ids = artifact_map["mission_specs"][:2] + artifact_map["findings"][:1] + artifact_map["manifests"][:2]
    operator_bullets = [
        f"Package root: {package_root}",
        f"Current phase: {mission_state.get('current_phase')} ({mission_state.get('status')})",
        f"Packaged {len(artifacts)} artifacts across {len(run_bundles)} manifest bundles.",
    ]
    if missing_required_artifacts_summary:
        operator_bullets.append(missing_required_artifacts_summary)
    next_actions = mission_state.get("next_actions", {})
    if isinstance(next_actions.get("summary"), str):
        operator_bullets.append(f"Next-actions summary: {next_actions['summary']}")
    for action in next_actions.get("actions", [])[:4]:
        if isinstance(action, dict):
            operator_bullets.append(f"{action.get('role')}: {action.get('task')}")

    paper_bullets = [f"Conservative claim posture: {package_claim_state}."]
    if top_bundles:
        for bundle in top_bundles:
            metric_display = (
                f"{bundle['metric_name']}={bundle['primary_metric']:.6g}"
                if bundle["metric_name"] and bundle["primary_metric"] is not None
                else "metric unavailable"
            )
            paper_bullets.append(
                f"{bundle['loop_id']} ({bundle['stage_id']}, {bundle['claim_state']}): {metric_display}."
            )
    paper_bullets.extend(finding_bullets[:3])
    paper_bullets.extend(critique_reasons[:3])

    release_bullets = [f"Package claim state: {package_claim_state}.", f"Critique ceiling: {critique_ceiling}."]
    release_bullets.append(
        "Replication evidence: "
        f"{replication_evidence['total_manifests']} manifests across "
        f"{replication_evidence['independent_runs']} run groups."
    )
    if evidence_state != max_manifest_state:
        release_bullets.append(
            f"Package-level evidence raises the manifest floor from {max_manifest_state} to {evidence_state}."
        )
    release_bullets.extend(release_blockers[:3])
    release_bullets.extend(critique_warnings[:3])
    if missing_required_artifacts_summary:
        release_bullets.append(missing_required_artifacts_summary)
    mission_scheduler = mission_state.get("mission_scheduler")
    if isinstance(mission_scheduler, dict) and mission_scheduler.get("scheduler_id"):
        release_bullets.append(
            "Scheduler posture: "
            f"{mission_scheduler.get('scheduler_id')}={mission_scheduler.get('scheduler_status', 'unknown')}, "
            f"remaining_budget={mission_scheduler.get('remaining_budget', 'n/a')}."
        )
    mission_memory_path = mission_root / "mission_memory.json"
    if mission_memory_path.exists():
        mission_memory = _load_json(mission_memory_path)
        retrieved_research = (
            mission_memory.get("retrieved_research_context")
            if isinstance(mission_memory.get("retrieved_research_context"), dict)
            else {}
        )
        if retrieved_research:
            release_bullets.append(
                "Indexed memory context: "
                f"{len(retrieved_research.get('matches', [])) if isinstance(retrieved_research.get('matches'), list) else 0} "
                f"match(es) for `{retrieved_research.get('query', '')}`."
            )
    platform_expansion = mission_state.get("platform_expansion")
    if isinstance(platform_expansion, dict):
        surfaces = platform_expansion.get("surfaces")
        if isinstance(surfaces, dict) and surfaces:
            release_bullets.append(
                "Platform surfaces: "
                + ", ".join(
                    f"{surface_id}={surface.get('status', 'unknown')}"
                    for surface_id, surface in sorted(surfaces.items())
                    if isinstance(surface, dict)
                )
                + "."
            )

    manifest_name = str(contract.get("outputs", {}).get("manifest_json", "mission_artifact_package.json"))
    summary_name = str(contract.get("outputs", {}).get("summary_markdown", "mission_artifact_package.md"))
    manifest_path = package_root / manifest_name
    summary_path = package_root / summary_name

    package = {
        "schema_version": 1,
        "package_id": f"{mission_id}-{package_claim_state}-package",
        "mission_id": mission_id,
        "package_root": str(package_root),
        "package_digest": package_digest,
        "mission": {
            "title": mission_state.get("title", ""),
            "objective": mission_state.get("objective", ""),
            "current_phase": mission_state.get("current_phase", ""),
            "status": mission_state.get("status", ""),
            "target_repo": str(target_repo),
            "roles": list(mission_state.get("roles", [])),
        },
        "claim_summary": {
            "package_claim_state": package_claim_state,
            "manifest_claim_counts": manifest_claim_counts,
            "critique_ceiling": critique_ceiling,
            "promotion_requirements": _state_requirements(evidence_policy, package_claim_state),
            "paper_candidate_blockers": (
                ([missing_required_artifacts_summary] if missing_required_artifacts_summary else [])
                + paper_blockers
                + critique_reasons
            ),
            "release_candidate_blockers": (
                ([missing_required_artifacts_summary] if missing_required_artifacts_summary else [])
                + release_blockers
                + critique_reasons
            ),
        },
        "artifacts": artifacts,
        "artifact_map": artifact_map,
        "replication_evidence": replication_evidence,
        "run_bundles": sorted(run_bundles, key=lambda item: item["loop_id"]),
        "cross_links": cross_links,
        "summary": {
            "operator_handoff": {
                "headline": "Operator handoff package",
                "bullets": operator_bullets,
                "key_artifact_ids": operator_key_ids,
            },
            "paper_drafting": {
                "headline": "Paper drafting posture",
                "bullets": paper_bullets,
                "key_artifact_ids": [bundle["manifest_artifact_id"] for bundle in top_bundles],
            },
            "task_evidence": {
                "headline": "Task-specific science evidence",
                "bullets": task_evidence_bullets,
                "key_artifact_ids": (
                    artifact_map["task_metrics"][:3]
                    + artifact_map["task_predictions"][:2]
                    + artifact_map["task_run_logs"][:2]
                    + artifact_map["task_method_artifacts"][:2]
                ),
            },
            "release_review": {
                "headline": "Release review posture",
                "bullets": release_bullets,
                "key_artifact_ids": artifact_map["critique_reports"][:3],
            },
        },
        "checks": {
            "copy_complete": True,
            "outside_repo_outputs": True,
            "all_required_artifacts_present": all_required_artifacts_present,
            "missing_required_artifacts": missing_required_artifacts,
            "validation_errors": [],
            "artifact_count_by_category": {
                category: len(ids)
                for category, ids in artifact_map.items()
            },
            "pending_downstream_artifacts": [record["source_path"] for record in pending_artifacts],
            "missing_recorded_output_artifacts": missing_recorded_output_artifacts,
        },
    }

    release_policy = load_release_candidate_policy()
    release_review = build_release_candidate_review(
        package,
        package_manifest_path=manifest_path,
        policy=release_policy,
    )
    release_bullets.insert(0, f"Release automation decision: {release_review['decision']}.")
    if release_review["missing_approvals"]:
        release_bullets.append(
            "Missing approvals: " + ", ".join(sorted(release_review["missing_approvals"])) + "."
        )
    if release_review["failed_gate_ids"]:
        release_bullets.append(
            "Failed gates: " + ", ".join(release_review["failed_gate_ids"][:3]) + "."
        )
    package["summary"]["release_review"]["bullets"] = release_bullets
    package["release_automation"] = build_package_release_automation(release_review)

    validation_errors = validate_package_manifest(package)
    package["checks"]["validation_errors"] = validation_errors
    if validation_errors:
        raise RuntimeError("Mission artifact package failed schema validation: " + "; ".join(validation_errors))

    manifest_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")

    markdown_lines = [
        "# Mission artifact package",
        "",
        f"- mission_id: `{mission_id}`",
        f"- package_id: `{package['package_id']}`",
        f"- package_claim_state: `{package_claim_state}`",
        f"- package_digest: `{package_digest}`",
        f"- package_root: `{package_root}`",
        f"- target_repo: `{target_repo}`",
        "",
        "## Operator handoff",
        "",
    ]
    markdown_lines.extend(f"- {line}" for line in operator_bullets)
    markdown_lines.extend(["", "## Task-specific science evidence", ""])
    markdown_lines.extend(f"- {line}" for line in task_evidence_bullets)
    markdown_lines.extend(["", "## Paper drafting", ""])
    markdown_lines.extend(f"- {line}" for line in paper_bullets)
    markdown_lines.extend(["", "## Release review", ""])
    markdown_lines.extend(f"- {line}" for line in release_bullets)
    if operator_key_ids:
        markdown_lines.extend(["", "## Key artifact ids", ""])
        markdown_lines.extend(f"- `{artifact_id}`" for artifact_id in operator_key_ids)
    summary_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")

    release_review_result = materialize_release_candidate_review(
        release_review,
        package_root=package_root,
        policy=release_policy,
    )

    return {
        "package_root": package_root,
        "manifest_path": manifest_path,
        "summary_path": summary_path,
        "package": package,
        "release_review_path": release_review_result["review_json"],
        "release_review_markdown_path": release_review_result["review_markdown"],
    }
