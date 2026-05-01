from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from deeploop.core.paths import SCRATCH_DIR
from deeploop.core.structured_io import write_markdown, write_yaml_mapping
from deeploop.mission.project_bootstrap import build_mission_config_from_project_root

DISCOVERY_QUESTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "available_assets",
        "available assets / context",
        "What data, artifacts, baselines, or prior notes do you already have?",
    ),
    (
        "success_criteria",
        "success criteria / metrics",
        "What should count as success? Include metrics, benchmarks, or decision thresholds if you know them.",
    ),
    (
        "risks_and_leakage",
        "leakage / risks",
        "What leakage, confounds, or failure risks should DeepLoop watch for?",
    ),
    (
        "compute_budget",
        "compute budget",
        "What compute, time, or parallelism budget should the mission respect?",
    ),
    (
        "deliverables",
        "deliverables",
        "What outputs do you want at the end (report, artifact package, experiment plan, benchmark memo, etc.)?",
    ),
    (
        "novelty_and_tradeoffs",
        "novelty / tradeoffs",
        "How ambitious should the mission be, and what tradeoffs matter most?",
    ),
    (
        "missing_information",
        "missing information",
        "What key information is still missing that DeepLoop should surface before autonomous kickoff?",
    ),
)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


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
    return slug or "interactive-mission"


def build_discovery_checklist(answers: dict[str, str]) -> list[dict[str, str]]:
    checklist = [
        {
            "id": "mission_idea",
            "label": "mission idea",
            "status": "provided" if _clean_text(answers.get("mission_idea")) else "missing",
        }
    ]
    checklist.extend(
        {
            "id": field_id,
            "label": label,
            "status": "provided" if _clean_text(answers.get(field_id)) else "missing",
        }
        for field_id, label, _prompt in DISCOVERY_QUESTIONS
    )
    return checklist


def _question_prompts(*, printer: Callable[[str], None], answers: dict[str, str]) -> None:
    missing = [item["label"] for item in build_discovery_checklist(answers) if item["status"] == "missing"]
    printer("mission-discovery: current missing checklist")
    for label in missing:
        printer(f"- [ ] {label}")
    if not missing:
        printer("- [x] discovery checklist complete")


def _discovery_constraints(answers: dict[str, str]) -> list[str]:
    constraints: list[str] = []
    for key in ("risks_and_leakage", "compute_budget", "novelty_and_tradeoffs"):
        value = _clean_text(answers.get(key))
        if value:
            constraints.append(value)
    return constraints


def _discovery_summary_lines(
    *,
    config: dict[str, Any],
    answers: dict[str, str],
    project_root: Path | None,
    compiled_config_path: Path,
) -> list[str]:
    lines = [
        "mission-discovery: compiled mission summary",
        f"- title: {config['mission']['title']}",
        f"- objective: {config['mission']['objective']}",
        f"- target_repo: {config['mission']['target_repo']}",
        f"- compiled_config: {compiled_config_path}",
    ]
    if project_root is not None:
        lines.append(f"- discovery_context_project_root: {project_root}")
    lines.append("- discovery checklist:")
    for item in build_discovery_checklist(answers):
        marker = "x" if item["status"] == "provided" else " "
        lines.append(f"  - [{marker}] {item['label']}")
    return lines


def _discovery_payload(answers: dict[str, str]) -> dict[str, Any]:
    return {
        "mode": "interactive",
        "checklist": build_discovery_checklist(answers),
        "answers": {key: value for key, value in answers.items() if _clean_text(value)},
    }


def _discovery_brief_lines(config: dict[str, Any], answers: dict[str, str]) -> list[str]:
    lines = [
        "# Mission discovery brief",
        "",
        f"- title: {config['mission']['title']}",
        f"- objective: {config['mission']['objective']}",
        "",
        "## Discovery checklist",
    ]
    for item in build_discovery_checklist(answers):
        marker = "x" if item["status"] == "provided" else " "
        lines.append(f"- [{marker}] {item['label']}")
    lines.extend(["", "## Discovery answers"])
    for key, label, _prompt in (("mission_idea", "mission idea", ""), *DISCOVERY_QUESTIONS):
        value = _clean_text(answers.get(key))
        if value:
            lines.append(f"- **{label}**: {value}")
    return lines


def compile_discovery_config(
    *,
    mission_idea: str,
    discovery_answers: dict[str, str],
    mission_id: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    answers = {"mission_idea": mission_idea, **discovery_answers}
    objective = _clean_text(answers["mission_idea"]) or "Refine the mission interactively before execution."
    title_seed = objective.split(".")[0] or objective
    title = title_seed[:120].rstrip(" ,;:") or "Interactive mission discovery"
    summary_parts = [
        f"Compile an executable DeepLoop mission from interactive discovery for: {objective}",
    ]
    available_assets = _clean_text(answers.get("available_assets"))
    if available_assets:
        summary_parts.append(f"Starting context: {available_assets}")
    summary = " ".join(summary_parts)

    if project_root is None:
        resolved_mission_id = _clean_text(mission_id) or f"{_slugify(title)}-mission"
        discovery_root = SCRATCH_DIR / "mission_discovery_projects" / resolved_mission_id
        docs_root = discovery_root / "docs"
        docs_root.mkdir(parents=True, exist_ok=True)
        constraints = _discovery_constraints(answers)
        project_facts = {
            "project": {
                "name": _slugify(title),
                "title": title,
                "summary": summary,
                "objective": objective,
                "constraints": constraints,
                "human_inputs": {"mission_discovery": _discovery_payload(answers)},
            },
            "artifacts": {"docs": ["docs/project-brief.md"]},
        }
        write_yaml_mapping(discovery_root / "project-facts.yaml", project_facts)
        base_config = build_mission_config_from_project_root(discovery_root, mission_id=resolved_mission_id)
        write_markdown(docs_root / "project-brief.md", _discovery_brief_lines(base_config, answers))
    else:
        base_config = build_mission_config_from_project_root(project_root, mission_id=mission_id)
        discovery_payload = _discovery_payload(answers)
        existing_constraints = [
            str(item).strip()
            for item in base_config["mission"].get("constraints", [])
            if str(item).strip()
        ]
        merged_constraints = list(dict.fromkeys([*existing_constraints, *_discovery_constraints(answers)]))
        existing_human_inputs = (
            dict(base_config["mission"].get("human_inputs"))
            if isinstance(base_config["mission"].get("human_inputs"), dict)
            else {}
        )
        base_config["mission"]["title"] = title
        base_config["mission"]["summary"] = summary
        base_config["mission"]["objective"] = objective
        base_config["mission"]["constraints"] = merged_constraints
        base_config["mission"]["human_inputs"] = {
            **existing_human_inputs,
            "mission_discovery": discovery_payload,
        }
    return base_config


def run_interactive_discovery(
    *,
    mission_id: str | None = None,
    mission_idea: str | None = None,
    project_root: Path | None = None,
    reader: Callable[[str], str] = input,
    printer: Callable[[str], None] = print,
) -> dict[str, Any]:
    printer("mission-discovery: starting interactive mission formulation")
    if project_root is not None:
        printer(f"mission-discovery: using project context from {project_root}")
    idea = _clean_text(mission_idea)
    while not idea:
        idea = _clean_text(reader("mission-discovery: What is your rough mission idea or goal? "))
    answers: dict[str, str] = {"mission_idea": idea}
    for field_id, _label, prompt in DISCOVERY_QUESTIONS:
        _question_prompts(printer=printer, answers=answers)
        answers[field_id] = _clean_text(reader(f"mission-discovery: {prompt} "))

    config = compile_discovery_config(
        mission_idea=idea,
        discovery_answers={key: value for key, value in answers.items() if key != "mission_idea"},
        mission_id=mission_id,
        project_root=project_root,
    )
    compiled_config_dir = SCRATCH_DIR / "mission_discovery_configs"
    compiled_config_dir.mkdir(parents=True, exist_ok=True)
    compiled_config_path = compiled_config_dir / f"{config['mission']['id']}.yaml"
    write_yaml_mapping(compiled_config_path, config)
    printer(f"mission-discovery: wrote compiled config to {compiled_config_path}")
    for line in _discovery_summary_lines(
        config=config,
        answers=answers,
        project_root=project_root,
        compiled_config_path=compiled_config_path,
    ):
        printer(line)
    confirmation = _clean_text(reader("mission-discovery: Proceed with mission kickoff? [y/N] ")).lower()
    return {
        "confirmed": confirmation in {"y", "yes"},
        "config": config,
        "config_path": compiled_config_path,
    }


__all__ = [
    "DISCOVERY_QUESTIONS",
    "build_discovery_checklist",
    "compile_discovery_config",
    "run_interactive_discovery",
]
