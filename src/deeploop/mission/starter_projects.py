from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from deeploop.core.paths import PROJECTS_DIR, REPO_ROOT

STARTER_CATALOG: tuple[dict[str, str], ...] = (
    {
        "id": "starter-general-research",
        "directory": "starter-general-research",
        "title": "General research starter",
        "description": "A neutral starter for end-to-end auto research from a minimal project folder.",
    },
    {
        "id": "translation-budget-ladder",
        "directory": "translation-budget-ladder",
        "title": "Translation budget ladder",
        "description": "A benchmark-heavy translation example with explicit budget and baseline constraints.",
    },
)
DEFAULT_STARTER_ID = "starter-general-research"


def bundled_starter_catalog() -> list[dict[str, str]]:
    starters: list[dict[str, str]] = []
    for starter in STARTER_CATALOG:
        source = REPO_ROOT / "examples" / starter["directory"]
        if source.is_dir():
            starters.append({**starter, "source_path": str(source)})
    return starters


def resolve_starter_source(starter_id: str) -> Path:
    for starter in bundled_starter_catalog():
        if starter["id"] == starter_id:
            return Path(starter["source_path"]).expanduser().resolve()
    raise FileNotFoundError(f"Unknown bundled starter project: {starter_id}")


def _slugify(value: str) -> str:
    slug_chars: list[str] = []
    pending_dash = False
    for char in value.lower():
        if char.isalnum():
            if pending_dash and slug_chars:
                slug_chars.append("-")
            slug_chars.append(char)
            pending_dash = False
        elif slug_chars:
            pending_dash = True
    slug = "".join(slug_chars).strip("-")
    return slug or "deeploop-project"


def _ensure_unique_destination(base_name: str) -> Path:
    destination = PROJECTS_DIR / base_name
    if not destination.exists():
        return destination
    index = 2
    while True:
        candidate = PROJECTS_DIR / f"{base_name}-{index}"
        if not candidate.exists():
            return candidate
        index += 1


def _write_starter_project_facts(
    project_root: Path,
    *,
    title: str,
    summary: str,
    objective: str,
    starter_id: str,
) -> None:
    project_facts_path = project_root / "project-facts.yaml"
    if not project_facts_path.exists():
        return
    payload = yaml.safe_load(project_facts_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    existing_constraints = [str(item).strip() for item in project.get("constraints", []) if str(item).strip()]
    project.update(
        {
            "name": _slugify(title),
            "title": title,
            "summary": summary,
            "objective": objective,
            "constraints": existing_constraints,
        }
    )
    human_inputs = project.get("human_inputs") if isinstance(project.get("human_inputs"), dict) else {}
    human_inputs["starter_project"] = starter_id
    project["human_inputs"] = human_inputs
    payload["project"] = project
    project_facts_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def materialize_starter_project(
    *,
    starter_id: str,
    title: str,
    summary: str,
    objective: str,
    mission_id: str,
) -> Path:
    source = resolve_starter_source(starter_id)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    destination = _ensure_unique_destination(_slugify(mission_id.removesuffix("-mission") or title))
    shutil.copytree(source, destination)
    _write_starter_project_facts(
        destination,
        title=title,
        summary=summary,
        objective=objective,
        starter_id=starter_id,
    )
    return destination


__all__ = [
    "DEFAULT_STARTER_ID",
    "bundled_starter_catalog",
    "materialize_starter_project",
    "resolve_starter_source",
]
