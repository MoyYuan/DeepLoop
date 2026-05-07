from __future__ import annotations

from pathlib import Path
from typing import Any

from deeploop.mission.orchestrator import DEFAULT_OPERATING_MODE
from deeploop.project_contract import discover_project_contract

DEFAULT_BOOTSTRAP_ROLES = [
    "planner",
    "literature-scout",
    "dataset-strategist",
    "experiment-designer",
    "execution-operator",
    "critic-verifier",
    "report-synthesizer",
]

DEFAULT_BOOTSTRAP_PHASES = [
    "idea-intake",
    "literature-review",
    "question-design",
    "benchmark-selection",
    "experiment-design",
    "execution",
    "critique",
    "replication",
    "final-report",
]

DEFAULT_BOOTSTRAP_AUTOPILOT = {"max_iterations": 64}
DEFAULT_RECURSIVE_AGENT_AUTOPILOT = {
    "max_iterations": 4,
}
DEFAULT_PHASE_EXECUTION_HINTS = {
    "idea-intake": {"executor": "recursive-agent"},
    "literature-review": {"executor": "recursive-agent"},
    "question-design": {"executor": "recursive-agent", "next_phase_on_success": "benchmark-selection"},
    "benchmark-selection": {"executor": "recursive-agent"},
    "experiment-design": {"executor": "recursive-agent"},
    "execution": {"executor": "recursive-agent", "next_phase_on_success": "critique"},
    "critique": {"executor": "recursive-agent", "next_phase_on_success": "replication"},
    "replication": {"executor": "recursive-agent", "next_phase_on_success": "final-report"},
    "final-report": {"executor": "report-synthesis"},
}

DEFAULT_BOOTSTRAP_CONSTRAINT = (
    "Treat the project folder as a minimal fact/contract substrate; DeepLoop owns "
    "build repo code, runtime scripts, generated configs, and experiment logic."
)


def _clean_text(value: Any, *, fallback: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return fallback


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _merge_mapping(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_mapping(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


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


def build_mission_config_from_project_root(project_root: Path, *, mission_id: str | None = None) -> dict[str, Any]:
    repo_root = project_root.expanduser().resolve()
    contract = discover_project_contract(repo_root)
    project_metadata = contract.get("project_metadata") if isinstance(contract.get("project_metadata"), dict) else {}
    project_name = _clean_text(project_metadata.get("name"), fallback=repo_root.name)
    mission_slug = _slugify(project_name)
    resolved_mission_id = _clean_text(
        mission_id or project_metadata.get("mission_id"),
        fallback=f"{mission_slug}-mission",
    )
    title = _clean_text(project_metadata.get("title"), fallback=f"{project_name} mission")
    summary = _clean_text(
        project_metadata.get("summary"),
        fallback=(
            f"Bootstrap DeepLoop from the minimal facts in `{repo_root.name}` and keep "
            "all implementation/build surfaces DeepLoop-owned."
        ),
    )
    objective = _clean_text(
        project_metadata.get("objective"),
        fallback=(
            f"Use DeepLoop to make measurable progress on `{project_name}` starting only "
            "from the project folder's minimal facts and contracts."
        ),
    )
    constraints = _clean_string_list(project_metadata.get("constraints"))
    if DEFAULT_BOOTSTRAP_CONSTRAINT not in constraints:
        constraints.append(DEFAULT_BOOTSTRAP_CONSTRAINT)
    roles = _clean_string_list(project_metadata.get("roles")) or DEFAULT_BOOTSTRAP_ROLES
    phases = _clean_string_list(project_metadata.get("phases")) or DEFAULT_BOOTSTRAP_PHASES
    human_inputs = project_metadata.get("human_inputs") if isinstance(project_metadata.get("human_inputs"), dict) else {}
    autopilot = project_metadata.get("autopilot") if isinstance(project_metadata.get("autopilot"), dict) else {}
    merged_autopilot = dict(DEFAULT_BOOTSTRAP_AUTOPILOT)
    merged_autopilot.update({key: value for key, value in autopilot.items() if key not in {"recursive_agent", "phase_execution_hints"}})
    recursive_agent_cfg = (
        autopilot.get("recursive_agent")
        if isinstance(autopilot.get("recursive_agent"), dict)
        else {}
    )
    merged_autopilot["recursive_agent"] = _merge_mapping(
        {
            "loop_name": f"{mission_slug}-phase-loop",
            **DEFAULT_RECURSIVE_AGENT_AUTOPILOT,
        },
        recursive_agent_cfg,
    )
    raw_phase_hints = autopilot.get("phase_execution_hints") if isinstance(autopilot.get("phase_execution_hints"), dict) else {}
    phase_hints = {
        phase: dict(hint)
        for phase, hint in DEFAULT_PHASE_EXECUTION_HINTS.items()
    }
    for phase, raw_hint in raw_phase_hints.items():
        if not isinstance(raw_hint, dict):
            continue
        phase_hints[str(phase)] = _merge_mapping(dict(phase_hints.get(str(phase), {})), raw_hint)
    merged_autopilot["phase_execution_hints"] = phase_hints
    artifacts = contract.get("artifacts") if isinstance(contract.get("artifacts"), dict) else {}
    return {
        "mission": {
            "id": resolved_mission_id,
            "mode": _clean_text(project_metadata.get("mode"), fallback=DEFAULT_OPERATING_MODE),
            "title": title,
            "summary": summary,
            "objective": objective,
            "target_repo": str(repo_root),
            "target_project": project_name,
            "constraints": constraints,
            "human_inputs": human_inputs,
        },
        "roles": roles,
        "phases": phases,
        "artifacts": {
            "docs": [str(path) for path in artifacts.get("docs", [])],
            "configs": [str(path) for path in artifacts.get("configs", [])],
            "data": [dict(item) for item in artifacts.get("data", []) if isinstance(item, dict)],
        },
        "autopilot": merged_autopilot,
    }
