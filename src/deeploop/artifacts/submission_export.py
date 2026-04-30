from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from deeploop.artifacts.artifact_packager import PACKAGE_CONTRACT_PATH, package_mission_artifacts
from deeploop.core.paths import REPO_ROOT
from deeploop.core.structured_io import write_json_object, write_markdown, write_text

SUPPORTED_EXPORT_FORMATS = ("github-repo",)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _prepare_output_root(output_root: Path, *, force: bool) -> None:
    if _is_relative_to(output_root, REPO_ROOT):
        raise ValueError(f"Submission export output must stay outside the DeepLoop source tree: {output_root}")
    if output_root.exists() and not output_root.is_dir():
        raise ValueError(f"Submission export output is not a directory: {output_root}")
    if output_root.exists():
        existing = [path for path in output_root.iterdir() if path.name != ".git"]
        if existing and not force:
            raise FileExistsError(f"Submission export output is not empty; pass --force to replace it: {output_root}")
        for path in existing:
            _remove_path(path)
    output_root.mkdir(parents=True, exist_ok=True)


def _artifact_section(artifact: dict[str, Any], *, target_repo: Path) -> Path:
    category = str(artifact.get("metadata", {}).get("export_category") or "")
    source_path = Path(str(artifact.get("source_path", ""))).expanduser()
    name = source_path.name.lower()
    kind = str(artifact.get("kind", "artifact"))
    source_resolved = source_path.resolve()

    if _is_relative_to(source_resolved, target_repo):
        return Path("project-input") / source_resolved.relative_to(target_repo).parent
    if category == "manifests":
        return Path("manifests")
    if category == "kernel_outputs":
        if "metric" in kind or "metric" in name:
            return Path("results") / "metrics"
        if "prediction" in name or "forecast" in name:
            return Path("results") / "predictions"
        if "log" in name:
            return Path("results") / "logs"
        if "stability" in name or "note" in name:
            return Path("results") / "stability-notes"
        return Path("results") / "generated"
    if category == "findings":
        return Path("docs") / "findings"
    if category == "critique_reports":
        return Path("docs") / "reviews"
    if category == "mission_specs" and name.endswith((".md", ".txt")):
        return Path("methods")
    return Path("bookkeeping") / "deeploop"


def _copy_export_artifact(
    artifact: dict[str, Any],
    *,
    package_root: Path,
    output_root: Path,
    target_repo: Path,
    used_paths: set[Path],
) -> dict[str, Any]:
    package_path = package_root / str(artifact["package_path"])
    if not package_path.exists() or not package_path.is_file():
        raise FileNotFoundError(package_path)
    section = _artifact_section(artifact, target_repo=target_repo)
    source_name = Path(str(artifact.get("source_path", package_path.name))).name or package_path.name
    destination = output_root / section / source_name
    if destination in used_paths:
        digest = hashlib.sha256(str(artifact.get("artifact_id", source_name)).encode("utf-8")).hexdigest()[:8]
        destination = output_root / section / f"{Path(source_name).stem}-{digest}{Path(source_name).suffix}"
    used_paths.add(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(package_path, destination)
    return {
        "artifact_id": artifact["artifact_id"],
        "kind": artifact.get("kind"),
        "source_category": artifact.get("metadata", {}).get("export_category"),
        "export_path": destination.relative_to(output_root).as_posix(),
        "source_path": artifact.get("source_path"),
    }


def _artifact_with_category(artifact: dict[str, Any], artifact_map: dict[str, list[str]]) -> dict[str, Any]:
    metadata = dict(artifact.get("metadata", {}))
    artifact_id = str(artifact["artifact_id"])
    for category, artifact_ids in artifact_map.items():
        if artifact_id in artifact_ids:
            metadata["export_category"] = category
            copied = dict(artifact)
            copied["metadata"] = metadata
            return copied
    copied = dict(artifact)
    metadata["export_category"] = "uncategorized"
    copied["metadata"] = metadata
    return copied


def _copy_package_bookkeeping(package_result: dict[str, Any], *, output_root: Path) -> list[dict[str, str]]:
    copied: list[dict[str, str]] = []
    for key in ("manifest_path", "summary_path", "release_review_path", "release_review_markdown_path"):
        path = Path(package_result[key]).expanduser().resolve()
        destination = output_root / "bookkeeping" / "deeploop" / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied.append({"label": key, "export_path": destination.relative_to(output_root).as_posix()})
    return copied


def _render_readme(
    *,
    mission: dict[str, Any],
    package: dict[str, Any],
    copied_artifacts: list[dict[str, Any]],
    output_root: Path,
    mission_state_path: Path,
    force: bool,
) -> list[str]:
    run_bundles = package.get("run_bundles", [])
    claim_summary = package.get("claim_summary", {})
    caveats = [
        *claim_summary.get("paper_candidate_blockers", []),
        *claim_summary.get("release_candidate_blockers", []),
    ]
    artifact_lines = [f"- `{item['export_path']}` — {item.get('kind', 'artifact')}" for item in copied_artifacts]
    reproduce_command = f"deeploop export --mission-state {mission_state_path} --output {output_root} --format github-repo"
    if force:
        reproduce_command = f"{reproduce_command} --force"
    return [
        "# DeepLoop submission export",
        "",
        "## Mission objective",
        "",
        str(mission.get("objective") or mission.get("title") or "No objective recorded."),
        "",
        "## Methods",
        "",
        "Method and mission summary artifacts are in `methods/`; original project inputs copied from the target project are in `project-input/`.",
        "",
        "## Results",
        "",
        f"- package_claim_state: `{claim_summary.get('package_claim_state', 'unknown')}`",
        f"- run_bundle_count: `{len(run_bundles)}`",
        "- generated metrics, predictions, logs, and other science outputs are under `results/`.",
        "",
        "## Caveats",
        "",
        *(f"- {item}" for item in dict.fromkeys(str(item) for item in caveats if str(item).strip())),
        "",
        "## Artifact index",
        "",
        *artifact_lines,
        "",
        "## Reproduce this export",
        "",
        "```bash",
        reproduce_command,
        "```",
        "",
    ]


def export_submission_repository(
    mission_state_path: Path,
    output_root: Path,
    *,
    export_format: str = "github-repo",
    contract_path: Path = PACKAGE_CONTRACT_PATH,
    force: bool = False,
) -> dict[str, Any]:
    if export_format not in SUPPORTED_EXPORT_FORMATS:
        raise ValueError(f"Unsupported submission export format: {export_format}")
    mission_state_path = mission_state_path.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    contract_path = contract_path.expanduser().resolve()

    package_result = package_mission_artifacts(mission_state_path, contract_path=contract_path)
    package = package_result["package"]
    package_root = Path(package_result["package_root"]).expanduser().resolve()
    mission = package["mission"]
    target_repo = Path(str(mission["target_repo"])).expanduser().resolve()

    _prepare_output_root(output_root, force=force)

    artifact_map = package.get("artifact_map", {})
    artifacts = [
        _artifact_with_category(artifact, artifact_map)
        for artifact in package.get("artifacts", [])
        if artifact.get("package_path")
    ]
    used_paths: set[Path] = set()
    copied_artifacts = [
        _copy_export_artifact(
            artifact,
            package_root=package_root,
            output_root=output_root,
            target_repo=target_repo,
            used_paths=used_paths,
        )
        for artifact in artifacts
    ]
    bookkeeping = _copy_package_bookkeeping(package_result, output_root=output_root)

    reproduce_command = [
        "deeploop",
        "export",
        "--mission-state",
        str(mission_state_path),
        "--output",
        str(output_root),
        "--format",
        export_format,
    ]
    if force:
        reproduce_command.append("--force")
    provenance = {
        "schema_version": 1,
        "mission_id": package["mission_id"],
        "source_mission_state": str(mission_state_path),
        "source_package_manifest": str(package_result["manifest_path"]),
        "package_digest": package["package_digest"],
        "export_format": export_format,
        "target_repo": str(target_repo),
        "reproduce_command": reproduce_command,
    }
    manifest = {
        "schema_version": 1,
        "mission_id": package["mission_id"],
        "export_format": export_format,
        "output_root": str(output_root),
        "artifact_count": len(copied_artifacts),
        "artifacts": copied_artifacts,
        "bookkeeping": bookkeeping,
        "checks": {
            "all_package_artifacts_copied": len(copied_artifacts) == len(artifacts),
            "deeploop_source_tree_excluded": True,
            "runtime_cache_copied_only_as_selected_bookkeeping": True,
        },
    }

    readme_path = output_root / "README.md"
    manifest_path = output_root / "submission_manifest.json"
    provenance_path = output_root / "provenance.json"
    caveats_path = output_root / "caveats-and-limitations.md"
    gitignore_path = output_root / ".gitignore"
    write_markdown(
        readme_path,
        _render_readme(
            mission=mission,
            package=package,
            copied_artifacts=copied_artifacts,
            output_root=output_root,
            mission_state_path=mission_state_path,
            force=force,
        ),
    )
    write_json_object(manifest_path, manifest)
    write_json_object(provenance_path, provenance)
    write_markdown(
        caveats_path,
        [
            "# Caveats and limitations",
            "",
            *[
                f"- {item}"
                for item in dict.fromkeys(
                    str(item)
                    for item in (
                        package.get("claim_summary", {}).get("paper_candidate_blockers", [])
                        + package.get("claim_summary", {}).get("release_candidate_blockers", [])
                    )
                    if str(item).strip()
                )
            ],
            "",
        ],
    )
    write_text(
        gitignore_path,
        "\n".join(
            [
                "__pycache__/",
                ".pytest_cache/",
                ".mypy_cache/",
                ".ruff_cache/",
                "runs/",
                "scratch/",
                ".deeploop/runtime/",
                "",
            ]
        ),
    )

    return {
        "output_root": output_root,
        "readme_path": readme_path,
        "manifest_path": manifest_path,
        "provenance_path": provenance_path,
        "artifact_count": len(copied_artifacts),
        "package_manifest_path": package_result["manifest_path"],
    }
