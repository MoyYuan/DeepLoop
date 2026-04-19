from __future__ import annotations

from pathlib import Path
from typing import Any

from deeploop.artifacts.artifact_packager import package_mission_artifacts
from deeploop.core.structured_io import write_json_object, write_markdown
from deeploop.mission.mission_state import load_mission_state

DEFAULT_CONTRACT_PATH = Path(__file__).resolve().parents[3] / "configs" / "runtime" / "mission-package.yaml"


def _compatibility_root(mission_state_path: Path, mission_id: str, package_name: str | None) -> Path:
    return mission_state_path.parent / "mission_packages" / (package_name or f"{mission_id}-package")


def _artifact_entries(canonical_package_root: Path, package: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for artifact in package.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        package_path = artifact.get("package_path")
        linked_path = (
            str((canonical_package_root / str(package_path)).resolve())
            if isinstance(package_path, str) and package_path
            else None
        )
        entries.append(
            {
                "path": str(artifact.get("source_path") or ""),
                "kind": str(artifact.get("kind") or "other"),
                "linked_path": linked_path,
            }
        )
    return entries


def build_mission_package(
    mission_state_path: Path,
    *,
    package_name: str | None = None,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> dict[str, Any]:
    mission_state_path = mission_state_path.expanduser().resolve()
    mission_state = load_mission_state(mission_state_path)
    mission_id = str(mission_state["mission_id"])

    canonical = package_mission_artifacts(mission_state_path)
    canonical_package_root = Path(canonical["package_root"]).expanduser().resolve()
    package = canonical["package"]
    compatibility_root = _compatibility_root(mission_state_path, mission_id, package_name)
    compatibility_root.mkdir(parents=True, exist_ok=True)

    artifact_entries = _artifact_entries(canonical_package_root, package)
    kind_counts: dict[str, int] = {}
    for entry in artifact_entries:
        kind = str(entry["kind"])
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    artifact_index_path = compatibility_root / "artifact-index.json"
    package_manifest_path = compatibility_root / "package-manifest.json"
    summary_path = compatibility_root / "package-summary.md"

    write_json_object(
        artifact_index_path,
        {
            "mission_id": mission_id,
            "artifact_count": len(artifact_entries),
            "artifacts": artifact_entries,
            "compatibility_status": "delegated-to-artifact-packager",
            "canonical_package_root": str(canonical_package_root),
        },
    )
    write_json_object(
        package_manifest_path,
        {
            "mission_id": mission_id,
            "mission_root": str(mission_state_path.parent),
            "package_root": str(compatibility_root),
            "artifact_index_path": str(artifact_index_path),
            "summary_path": str(summary_path),
            "kind_counts": kind_counts,
            "compatibility_status": "delegated-to-artifact-packager",
            "canonical_package_root": str(canonical_package_root),
            "canonical_manifest_path": str(canonical["manifest_path"]),
            "canonical_summary_path": str(canonical["summary_path"]),
            "contract_path": str(contract_path.expanduser().resolve()),
        },
    )
    write_markdown(
        summary_path,
        [
            f"# Mission package: {mission_id}",
            "",
            "- compatibility surface: delegated to `deeploop.artifacts.artifact_packager.package_mission_artifacts`",
            f"- target_repo: `{mission_state.get('target_repo')}`",
            f"- artifact_count: `{len(artifact_entries)}`",
            f"- canonical_package_root: `{canonical_package_root}`",
            f"- canonical_manifest_path: `{canonical['manifest_path']}`",
            f"- canonical_summary_path: `{canonical['summary_path']}`",
            "",
            "## Artifact counts by kind",
            "",
            *[f"- {kind}: `{count}`" for kind, count in sorted(kind_counts.items())],
            "",
            "## Indexed artifacts",
            "",
            *[f"- `{entry['kind']}` -> `{entry['path']}`" for entry in artifact_entries[:25]],
        ],
    )

    return {
        "package_root": compatibility_root,
        "artifact_index_path": artifact_index_path,
        "package_manifest_path": package_manifest_path,
        "summary_path": summary_path,
        "artifact_count": len(artifact_entries),
        "canonical_package_root": canonical_package_root,
        "canonical_manifest_path": canonical["manifest_path"],
        "canonical_summary_path": canonical["summary_path"],
    }
