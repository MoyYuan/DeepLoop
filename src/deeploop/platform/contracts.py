from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from deeploop.core.ledger import now_utc
from deeploop.core.paths import REPO_ROOT
from deeploop.core.structured_io import (
    load_json_object as _load_json,
    load_yaml_mapping as _load_yaml,
)

DEFAULT_PLATFORM_EXPANSION_CONTRACT_PATH = REPO_ROOT / "configs" / "platform" / "expansion.yaml"

class _TemplateMap(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"

def _resolve_templates(value: object, context: dict[str, str]) -> object:
    if isinstance(value, str):
        return value.format_map(_TemplateMap(context))
    if isinstance(value, list):
        return [_resolve_templates(item, context) for item in value]
    if isinstance(value, dict):
        return {str(key): _resolve_templates(item, context) for key, item in value.items()}
    return value

def load_platform_expansion_contract(path: Path = DEFAULT_PLATFORM_EXPANSION_CONTRACT_PATH) -> dict[str, object]:
    return _load_yaml(path)

def _seed_surface_output(path: Path, *, surface_id: str, mission_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    if path.suffix == ".json":
        payload = {
            "surface_id": surface_id,
            "mission_id": mission_id,
            "status": "pending",
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return
    if path.suffix == ".jsonl":
        path.write_text("", encoding="utf-8")
        return
    if path.suffix == ".md":
        title = path.stem.replace("-", " ")
        path.write_text(f"# {title}\n\nPending `{surface_id}` output for `{mission_id}`.\n", encoding="utf-8")
        return
    path.write_text("", encoding="utf-8")

def _write_jsonl(path: Path, payloads: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(dict(payload), indent=None) + "\n" for payload in payloads),
        encoding="utf-8",
    )

def _resolve_path(raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser().resolve()

def _surface_paths(surface: Mapping[str, Any], *, suffix: str) -> list[Path]:
    paths: list[Path] = []
    for raw in surface.get("produces", []):
        resolved = _resolve_path(raw)
        if resolved is not None and resolved.name.endswith(suffix):
            paths.append(resolved)
    return paths

def _load_optional_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    loaded = _load_json(path)
    return loaded if isinstance(loaded, dict) else {}

def _relative_to_mission(path: Path, mission_root: Path) -> str:
    try:
        return path.resolve().relative_to(mission_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()

def _summarize_release_notes(package: Mapping[str, Any], review: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    summary = package.get("summary") if isinstance(package.get("summary"), Mapping) else {}
    release_review = summary.get("release_review") if isinstance(summary.get("release_review"), Mapping) else {}
    for bullet in release_review.get("bullets", []):
        text = str(bullet).strip()
        if text:
            lines.append(text)
        if len(lines) >= 6:
            break
    if not lines and review:
        for item in review.get("next_actions", []):
            text = str(item).strip()
            if text:
                lines.append(text)
            if len(lines) >= 6:
                break
    return lines

def materialize_platform_expansion_bundle(
    *,
    mission_id: str,
    mission_root: Path,
    mission_state_path: Path,
    target_repo: Path,
    contract_path: Path = DEFAULT_PLATFORM_EXPANSION_CONTRACT_PATH,
) -> dict[str, object]:
    contract = load_platform_expansion_contract(contract_path)
    context = {
        "mission_id": mission_id,
        "mission_root": str(mission_root.resolve()),
        "mission_state_path": str(mission_state_path.resolve()),
        "repo_root": str(REPO_ROOT.resolve()),
        "target_repo": str(target_repo.expanduser().resolve()),
    }
    resolved = _resolve_templates(contract, context)
    materialization = resolved.get("materialization") if isinstance(resolved.get("materialization"), dict) else {}
    platform_root = Path(str(materialization.get("platform_root") or mission_root / "runtime" / "platform")).expanduser().resolve()
    platform_root.mkdir(parents=True, exist_ok=True)

    raw_shared_contracts = resolved.get("shared_contracts") if isinstance(resolved.get("shared_contracts"), dict) else {}
    shared_contracts = {str(key): str(value) for key, value in raw_shared_contracts.items()}
    surfaces_cfg = resolved.get("surfaces") if isinstance(resolved.get("surfaces"), dict) else {}
    surfaces: dict[str, dict[str, object]] = {}
    for surface_id, raw_surface in surfaces_cfg.items():
        if not isinstance(raw_surface, dict):
            continue
        handoff_name = str(raw_surface.get("handoff_name") or f"{surface_id}.json")
        handoff_path = platform_root / handoff_name
        surface_dir = handoff_path.parent / handoff_path.stem
        surface_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "surface_id": str(surface_id),
            "status": str(raw_surface.get("status") or "planned"),
            "description": str(raw_surface.get("description") or ""),
            "mission_id": mission_id,
            "mission_state_path": str(mission_state_path.resolve()),
            "target_repo": str(target_repo.expanduser().resolve()),
            "platform_root": str(platform_root),
            "surface_root": str(surface_dir.resolve()),
            "consumes": [str(item) for item in raw_surface.get("consumes", []) if str(item).strip()],
            "produces": [str(item) for item in raw_surface.get("produces", []) if str(item).strip()],
            "integration_hooks": [str(item) for item in raw_surface.get("integration_hooks", []) if str(item).strip()],
            "shared_contracts": shared_contracts,
        }
        for output_path in payload["produces"]:
            _seed_surface_output(Path(output_path).expanduser().resolve(), surface_id=str(surface_id), mission_id=mission_id)
        handoff_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        surfaces[str(surface_id)] = {
            "status": payload["status"],
            "description": payload["description"],
            "handoff_path": str(handoff_path),
            "surface_root": payload["surface_root"],
            "consumes": payload["consumes"],
            "produces": payload["produces"],
        }

    manifest_path = platform_root / str(materialization.get("manifest_name") or "platform-expansion.json")
    manifest_payload = {
        "version": int(resolved.get("version", 1)),
        "policy_name": str(resolved.get("policy_name") or "deeploop-platform-expansion"),
        "summary": str(resolved.get("summary") or "").strip(),
        "mission_id": mission_id,
        "mission_state_path": str(mission_state_path.resolve()),
        "target_repo": str(target_repo.expanduser().resolve()),
        "platform_root": str(platform_root),
        "shared_contracts": shared_contracts,
        "surfaces": surfaces,
    }
    manifest_path.write_text(json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8")
    return {
        "policy_name": manifest_payload["policy_name"],
        "platform_root": str(platform_root),
        "manifest_path": str(manifest_path),
        "surfaces": surfaces,
        "shared_contracts": shared_contracts,
    }

def sync_platform_expansion_bundle(
    mission_state_path: Path,
    *,
    mission_state: Mapping[str, Any] | None = None,
    package_payload: Mapping[str, Any] | None = None,
    package_manifest_path: Path | None = None,
    release_review_path: Path | None = None,
) -> dict[str, object] | None:
    resolved_state_path = mission_state_path.expanduser().resolve()
    resolved_state = dict(mission_state) if isinstance(mission_state, Mapping) else _load_optional_json(resolved_state_path)
    platform_expansion = resolved_state.get("platform_expansion")
    if not isinstance(platform_expansion, Mapping):
        return None

    platform_root = _resolve_path(platform_expansion.get("platform_root"))
    manifest_path = _resolve_path(platform_expansion.get("manifest_path"))
    if platform_root is None or manifest_path is None:
        return None
    platform_root.mkdir(parents=True, exist_ok=True)
    mission_root = resolved_state_path.parent
    manifest_payload = _load_optional_json(manifest_path)
    manifest_payload.update(
        {
            "version": int(manifest_payload.get("version", platform_expansion.get("version", 1)) or 1),
            "policy_name": str(manifest_payload.get("policy_name") or platform_expansion.get("policy_name") or "deeploop-platform-expansion"),
            "mission_id": str(resolved_state.get("mission_id") or manifest_payload.get("mission_id") or ""),
            "mission_state_path": str(resolved_state_path),
            "target_repo": str(resolved_state.get("target_repo") or manifest_payload.get("target_repo") or ""),
            "platform_root": str(platform_root),
            "shared_contracts": dict(platform_expansion.get("shared_contracts") or manifest_payload.get("shared_contracts") or {}),
        }
    )

    outer_loop = resolved_state.get("outer_loop") if isinstance(resolved_state.get("outer_loop"), Mapping) else {}
    runtime = resolved_state.get("mission_runtime") if isinstance(resolved_state.get("mission_runtime"), Mapping) else {}
    scheduler = resolved_state.get("mission_scheduler") if isinstance(resolved_state.get("mission_scheduler"), Mapping) else {}
    mission_package = package_payload if isinstance(package_payload, Mapping) else {}
    if not mission_package and isinstance(resolved_state.get("mission_package"), Mapping):
        mission_package = dict(resolved_state["mission_package"])

    mission_memory_path = _resolve_path(outer_loop.get("mission_memory_path")) or _resolve_path(runtime.get("mission_memory_path"))
    experiment_ledger_path = _resolve_path(outer_loop.get("experiment_ledger_path")) or _resolve_path(runtime.get("experiment_ledger_path"))
    research_memory_events_path = _resolve_path(outer_loop.get("research_memory_events_path")) or _resolve_path(runtime.get("research_memory_events_path"))
    research_memory_index_path = _resolve_path(outer_loop.get("research_memory_index_path")) or _resolve_path(runtime.get("research_memory_index_path"))
    ledger_path = mission_root / "ledger.jsonl"
    mission_memory = _load_optional_json(mission_memory_path)

    resolved_package_manifest_path = (
        package_manifest_path.expanduser().resolve()
        if package_manifest_path is not None
        else _resolve_path(mission_package.get("manifest_path") or mission_package.get("package_manifest_path"))
    )
    package_manifest = _load_optional_json(resolved_package_manifest_path)

    resolved_release_review_path = (
        release_review_path.expanduser().resolve()
        if release_review_path is not None
        else _resolve_path(
            mission_package.get("release_review_path")
            or mission_package.get("release_review_json")
            or (
                (package_manifest.get("release_automation") or {}).get("review_artifacts", {})
                if isinstance(package_manifest.get("release_automation"), Mapping)
                else {}
            ).get("json")
        )
    )
    release_review = _load_optional_json(resolved_release_review_path)

    surfaces = platform_expansion.get("surfaces") if isinstance(platform_expansion.get("surfaces"), Mapping) else {}
    manifest_surfaces = manifest_payload.get("surfaces") if isinstance(manifest_payload.get("surfaces"), Mapping) else {}
    updated_surfaces: dict[str, dict[str, Any]] = {}
    synced_at = now_utc()

    for surface_id in sorted(set(surfaces) | set(manifest_surfaces)):
        base_surface = surfaces.get(surface_id) if isinstance(surfaces.get(surface_id), Mapping) else {}
        manifest_surface = manifest_surfaces.get(surface_id) if isinstance(manifest_surfaces.get(surface_id), Mapping) else {}
        handoff_path = _resolve_path(base_surface.get("handoff_path") or manifest_surface.get("handoff_path"))
        if handoff_path is None:
            handoff_path = platform_root / f"{surface_id}-handoff.json"
        surface_root = _resolve_path(base_surface.get("surface_root") or manifest_surface.get("surface_root")) or (
            handoff_path.parent / handoff_path.stem
        )
        surface_root.mkdir(parents=True, exist_ok=True)
        consumes = [str(item) for item in (base_surface.get("consumes") or manifest_surface.get("consumes") or [])]
        produces = [str(item) for item in (base_surface.get("produces") or manifest_surface.get("produces") or [])]
        integration_hooks = [
            str(item)
            for item in (base_surface.get("integration_hooks") or manifest_surface.get("integration_hooks") or [])
        ]
        description = str(base_surface.get("description") or manifest_surface.get("description") or "")
        integration_state: dict[str, Any]
        status = str(base_surface.get("status") or manifest_surface.get("status") or "planned")

        if surface_id == "scheduler":
            queue_path = next(iter(_surface_paths({"produces": produces}, suffix=".json")), surface_root / "mission-queue.json")
            dispatch_path = next(
                iter(_surface_paths({"produces": produces}, suffix=".jsonl")),
                surface_root / "dispatch-records.jsonl",
            )
            scheduler_summary = _load_optional_json(_resolve_path(scheduler.get("scheduler_summary_json_path")))
            dispatch_events = [
                event
                for event in scheduler_summary.get("recent_history", [])
                if isinstance(event, Mapping) and str(event.get("event") or "").strip()
            ]
            queue_payload = {
                "schema_version": 1,
                "synced_at": synced_at,
                "mission_id": manifest_payload["mission_id"],
                "mission_state_path": str(resolved_state_path),
                "mission_memory_path": str(mission_memory_path) if mission_memory_path else None,
                "experiment_ledger_path": str(experiment_ledger_path) if experiment_ledger_path else None,
                "scheduler_id": scheduler.get("scheduler_id"),
                "scheduler_status": scheduler.get("scheduler_status"),
                "priority": scheduler.get("priority"),
                "fair_share_weight": scheduler.get("fair_share_weight"),
                "iterations_consumed": scheduler.get("iterations_consumed"),
                "remaining_budget": scheduler.get("remaining_budget"),
                "last_effective_priority": scheduler.get("last_effective_priority"),
                "active_operator_request_id": scheduler.get("active_operator_request_id"),
            }
            write_json_object(queue_path, queue_payload)
            _write_jsonl(dispatch_path, [dict(event) for event in dispatch_events])
            if scheduler.get("scheduler_status"):
                status = str(scheduler.get("scheduler_status"))
            integration_state = {
                "mission_queue_path": str(queue_path),
                "dispatch_records_path": str(dispatch_path),
                "scheduler_state_path": scheduler.get("scheduler_state_path"),
                "scheduler_summary_json_path": scheduler.get("scheduler_summary_json_path"),
                "scheduler_summary_markdown_path": scheduler.get("scheduler_summary_markdown_path"),
                "active_operator_request_id": scheduler.get("active_operator_request_id"),
                "dispatch_event_count": len(dispatch_events),
            }
        elif surface_id == "indexed_memory":
            catalog_path = next(iter(_surface_paths({"produces": produces}, suffix=".json")), surface_root / "source-catalog.json")
            ingest_jobs_path = next(
                iter(_surface_paths({"produces": produces}, suffix=".jsonl")),
                surface_root / "ingest-jobs.jsonl",
            )
            retrieved_context = (
                mission_memory.get("retrieved_research_context")
                if isinstance(mission_memory.get("retrieved_research_context"), Mapping)
                else {}
            )
            source_catalog = {
                "schema_version": 1,
                "synced_at": synced_at,
                "mission_id": manifest_payload["mission_id"],
                "mission_state_path": str(resolved_state_path),
                "mission_memory_path": str(mission_memory_path) if mission_memory_path else None,
                "experiment_ledger_path": str(experiment_ledger_path) if experiment_ledger_path else None,
                "ledger_path": str(ledger_path.resolve()) if ledger_path.exists() else None,
                "research_memory_events_path": str(research_memory_events_path) if research_memory_events_path else None,
                "research_memory_index_path": str(research_memory_index_path) if research_memory_index_path else None,
                "retrieved_research_context": {
                    "query": retrieved_context.get("query"),
                    "match_count": len(retrieved_context.get("matches", [])) if isinstance(retrieved_context.get("matches"), list) else 0,
                    "matches": list(retrieved_context.get("matches", []))[:5] if isinstance(retrieved_context.get("matches"), list) else [],
                },
                "sources": [
                    {
                        "source_id": "mission-memory",
                        "path": str(mission_memory_path) if mission_memory_path else None,
                        "exists": bool(mission_memory_path and mission_memory_path.exists()),
                    },
                    {
                        "source_id": "mission-experiments",
                        "path": str(experiment_ledger_path) if experiment_ledger_path else None,
                        "exists": bool(experiment_ledger_path and experiment_ledger_path.exists()),
                    },
                    {
                        "source_id": "mission-ledger",
                        "path": str(ledger_path.resolve()) if ledger_path.exists() else None,
                        "exists": ledger_path.exists(),
                    },
                ],
            }
            write_json_object(catalog_path, source_catalog)
            ingest_jobs = [
                {
                    "job_id": f"{manifest_payload['mission_id']}-{job['source_id']}",
                    "mission_id": manifest_payload["mission_id"],
                    "source_id": job["source_id"],
                    "source_path": job["path"],
                    "status": "ready" if job["exists"] else "waiting-for-source",
                    "queued_at": synced_at,
                }
                for job in source_catalog["sources"]
                if job["path"]
            ]
            _write_jsonl(ingest_jobs_path, ingest_jobs)
            if research_memory_events_path and research_memory_index_path:
                status = "active"
            integration_state = {
                "source_catalog_path": str(catalog_path),
                "ingest_jobs_path": str(ingest_jobs_path),
                "mission_memory_path": str(mission_memory_path) if mission_memory_path else None,
                "research_memory_events_path": str(research_memory_events_path) if research_memory_events_path else None,
                "research_memory_index_path": str(research_memory_index_path) if research_memory_index_path else None,
                "retrieved_research_match_count": source_catalog["retrieved_research_context"]["match_count"],
            }
        elif surface_id == "release_automation":
            request_path = next(
                iter(_surface_paths({"produces": [path for path in produces if path.endswith(".json")]}, suffix=".json")),
                surface_root / "release-candidate-request.json",
            )
            notes_path = next(
                iter(_surface_paths({"produces": [path for path in produces if path.endswith(".md")]}, suffix=".md")),
                surface_root / "release-notes-draft.md",
            )
            release_automation = (
                package_manifest.get("release_automation")
                if isinstance(package_manifest.get("release_automation"), Mapping)
                else {}
            )
            request_payload = {
                "schema_version": 1,
                "synced_at": synced_at,
                "mission_id": manifest_payload["mission_id"],
                "mission_state_path": str(resolved_state_path),
                "package_manifest_path": str(resolved_package_manifest_path) if resolved_package_manifest_path else None,
                "package_summary_path": mission_package.get("summary_path") or mission_package.get("package_summary_path"),
                "package_digest": package_manifest.get("package_digest"),
                "package_claim_state": package_manifest.get("claim_summary", {}).get("package_claim_state")
                if isinstance(package_manifest.get("claim_summary"), Mapping)
                else None,
                "review_json_path": str(resolved_release_review_path) if resolved_release_review_path else None,
                "review_markdown_path": (release_automation.get("review_artifacts") or {}).get("markdown")
                if isinstance(release_automation, Mapping)
                else None,
                "promotion_path": (release_automation.get("review_artifacts") or {}).get("promotion")
                if isinstance(release_automation, Mapping)
                else None,
                "decision": release_automation.get("decision") or release_review.get("decision"),
                "eligible_for_promotion": (
                    release_automation.get("eligible_for_promotion")
                    if release_automation
                    else release_review.get("eligible_for_promotion")
                ),
                "missing_reviews": list(release_automation.get("missing_reviews", [])) if release_automation else [],
                "failed_gate_ids": list(release_automation.get("failed_gate_ids", [])) if release_automation else [],
                "scheduler_status": scheduler.get("scheduler_status"),
                "indexed_memory_status": updated_surfaces.get("indexed_memory", {}).get("status"),
            }
            write_json_object(request_path, request_payload)
            note_lines = [
                "# Release notes draft",
                "",
                f"- mission_id: `{manifest_payload['mission_id']}`",
                f"- package_claim_state: `{request_payload['package_claim_state'] or 'unknown'}`",
                f"- release_decision: `{request_payload['decision'] or 'planned'}`",
                f"- eligible_for_promotion: `{request_payload['eligible_for_promotion']}`",
                f"- scheduler_status: `{scheduler.get('scheduler_status') or 'unscheduled'}`",
                f"- indexed_memory_status: `{updated_surfaces.get('indexed_memory', {}).get('status', 'planned')}`",
                "",
                "## Highlights",
                "",
            ]
            highlights = _summarize_release_notes(package_manifest, release_review)
            note_lines.extend(f"- {line}" for line in highlights or ["Awaiting packaged release summary."])
            notes_path.parent.mkdir(parents=True, exist_ok=True)
            notes_path.write_text("\n".join(note_lines) + "\n", encoding="utf-8")
            if request_payload["decision"]:
                status = str(request_payload["decision"])
            elif resolved_package_manifest_path is not None:
                status = "packaged"
            integration_state = {
                "release_candidate_request_path": str(request_path),
                "release_notes_draft_path": str(notes_path),
                "package_manifest_path": str(resolved_package_manifest_path) if resolved_package_manifest_path else None,
                "release_review_path": str(resolved_release_review_path) if resolved_release_review_path else None,
                "promotion_path": request_payload["promotion_path"],
            }
        else:
            integration_state = {}

        handoff_payload = {
            "surface_id": surface_id,
            "status": status,
            "description": description,
            "mission_id": manifest_payload["mission_id"],
            "mission_state_path": str(resolved_state_path),
            "target_repo": manifest_payload["target_repo"],
            "platform_root": str(platform_root),
            "surface_root": str(surface_root),
            "consumes": consumes,
            "produces": produces,
            "integration_hooks": integration_hooks,
            "shared_contracts": dict(manifest_payload["shared_contracts"]),
            "synced_at": synced_at,
            "integration_state": integration_state,
        }
        write_json_object(handoff_path, handoff_payload)
        updated_surfaces[surface_id] = {
            "status": status,
            "description": description,
            "handoff_path": str(handoff_path),
            "surface_root": str(surface_root),
            "consumes": consumes,
            "produces": produces,
            "integration_hooks": integration_hooks,
            "integration_state": integration_state,
            "synced_at": synced_at,
        }

    manifest_payload["surfaces"] = updated_surfaces
    manifest_payload["integrated_runtime"] = {
        "mission_runtime_path": runtime.get("state_path"),
        "mission_memory_path": str(mission_memory_path) if mission_memory_path else None,
        "research_memory_index_path": str(research_memory_index_path) if research_memory_index_path else None,
        "package_manifest_path": str(resolved_package_manifest_path) if resolved_package_manifest_path else None,
        "release_review_path": str(resolved_release_review_path) if resolved_release_review_path else None,
        "updated_at": synced_at,
    }
    write_json_object(manifest_path, manifest_payload)

    if isinstance(mission_state, dict):
        mission_state["platform_expansion"] = {
            "policy_name": manifest_payload["policy_name"],
            "platform_root": str(platform_root),
            "manifest_path": str(manifest_path),
            "shared_contracts": dict(manifest_payload["shared_contracts"]),
            "surfaces": updated_surfaces,
        }
    persisted_state = dict(resolved_state)
    persisted_state["platform_expansion"] = {
        "policy_name": manifest_payload["policy_name"],
        "platform_root": str(platform_root),
        "manifest_path": str(manifest_path),
        "shared_contracts": dict(manifest_payload["shared_contracts"]),
        "surfaces": updated_surfaces,
    }
    write_json_object(resolved_state_path, persisted_state)
    return persisted_state["platform_expansion"]
