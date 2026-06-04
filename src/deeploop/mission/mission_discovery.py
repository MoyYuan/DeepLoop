from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml

from deeploop.core.paths import SCRATCH_DIR
from deeploop.core.shared import dedupe_strings as _dedupe_strings, slugify as _slugify
from deeploop.core.structured_io import write_markdown, write_yaml_mapping
from deeploop.mission.project_bootstrap import (
    build_mission_config_from_project_root,
    compile_mission_contract,
    render_mission_contract_summary_lines,
)
from deeploop.mission.starter_projects import DEFAULT_STARTER_ID, bundled_starter_catalog, materialize_starter_project
from deeploop.project_contract import discover_project_contract

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
DISCOVERY_CANCEL_TOKENS = {"cancel", "exit", "quit"}
# Keep the interactive loop bounded so blank stdin does not trap the operator forever.
MAX_INITIAL_IDEA_ATTEMPTS = 3
_DISCOVERY_TO_CONTRACT_FIELDS = {
    "success_criteria": "success_criteria",
    "risks_and_leakage": "leakage_constraints",
    "compute_budget": "compute_budget",
    "deliverables": "deliverables",
    "novelty_and_tradeoffs": "novelty_target",
}


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def build_discovery_checklist(answers: dict[str, str]) -> list[dict[str, str]]:
    checklist = [
        {
            "id": "mission_idea",
            "label": "mission idea",
            "status": "provided" if _normalize_text(answers.get("mission_idea")) else "missing",
        }
    ]
    checklist.extend(
        {
            "id": field_id,
            "label": label,
            "status": "provided" if _normalize_text(answers.get(field_id)) else "missing",
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
        value = _normalize_text(answers.get(key))
        if value:
            constraints.append(value)
    return constraints


def _render_compact_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_render_compact_value(item) for item in value if _normalize_text(item))
    if isinstance(value, dict):
        return "; ".join(f"{key}={_render_compact_value(item)}" for key, item in value.items() if _normalize_text(item))
    return _normalize_text(value)


def _discovery_contract_human_inputs(answers: dict[str, str]) -> dict[str, Any]:
    human_inputs = {
        contract_field: _normalize_text(answers.get(answer_field))
        for answer_field, contract_field in _DISCOVERY_TO_CONTRACT_FIELDS.items()
    }
    available_assets = _normalize_text(answers.get("available_assets"))
    if available_assets:
        human_inputs["available_assets"] = available_assets
    missing_information = _normalize_text(answers.get("missing_information"))
    if missing_information:
        human_inputs["missing_information"] = missing_information
    return {key: value for key, value in human_inputs.items() if _normalize_text(value)}


def _project_context_answers(project_root: Path) -> dict[str, str]:
    base_config = build_mission_config_from_project_root(project_root)
    mission = base_config.get("mission") if isinstance(base_config.get("mission"), dict) else {}
    mission_contract = (
        base_config.get("mission_contract") if isinstance(base_config.get("mission_contract"), dict) else {}
    )
    artifacts = base_config.get("artifacts") if isinstance(base_config.get("artifacts"), dict) else {}
    data_contract = mission_contract.get("data") if isinstance(mission_contract.get("data"), dict) else {}
    evaluation = mission_contract.get("evaluation") if isinstance(mission_contract.get("evaluation"), dict) else {}
    budget = mission_contract.get("budget") if isinstance(mission_contract.get("budget"), dict) else {}
    boundaries = mission_contract.get("boundaries") if isinstance(mission_contract.get("boundaries"), dict) else {}
    follow_up_questions = [
        _normalize_text(item)
        for item in mission_contract.get("follow_up_questions", [])
        if _normalize_text(item)
    ]

    asset_parts = [
        _render_compact_value(data_contract.get("dataset")),
        _render_compact_value(artifacts.get("docs")),
        _render_compact_value(artifacts.get("configs")),
    ]
    available_assets = "; ".join(part for part in asset_parts if part)
    if not available_assets:
        available_assets = _normalize_text(mission.get("summary"))

    return {
        "mission_idea": _normalize_text(mission.get("objective")),
        "available_assets": available_assets,
        "success_criteria": _render_compact_value(evaluation.get("success_criteria")),
        "risks_and_leakage": _render_compact_value(boundaries.get("leakage_policy")),
        "compute_budget": _render_compact_value(budget.get("compute_budget")),
        "deliverables": _render_compact_value(
            mission_contract.get("artifacts", {}).get("deliverables")
            if isinstance(mission_contract.get("artifacts"), dict)
            else None
        ),
        "novelty_and_tradeoffs": _render_compact_value(evaluation.get("novelty_target")),
        "missing_information": "; ".join(follow_up_questions),
    }


def _discovery_prompt(prompt: str, *, default: str | None = None, label: str = "detected") -> str:
    if default:
        return f"{prompt} [press Enter to keep {label}: {default}] "
    return f"{prompt} "


def _read_discovery_response(reader: Callable[[str], str], prompt: str) -> str | None:
    """Return None for explicit cancel tokens; keep blank responses as empty strings."""
    response = reader(prompt)
    cleaned = _normalize_text(response)
    if cleaned.lower() in DISCOVERY_CANCEL_TOKENS:
        return None
    return cleaned


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
    mission_contract = config.get("mission_contract")
    if isinstance(mission_contract, dict):
        lines.extend(["- readiness summary:"])
        lines.extend(f"  {line}" if line else "" for line in render_mission_contract_summary_lines(mission_contract, format="plain"))
    return lines


def _discovery_payload(answers: dict[str, str]) -> dict[str, Any]:
    return {
        "mode": "interactive",
        "checklist": build_discovery_checklist(answers),
        "answers": {key: value for key, value in answers.items() if _normalize_text(value)},
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
        value = _normalize_text(answers.get(key))
        if value:
            lines.append(f"- **{label}**: {value}")
    return lines


def _choose_starter_project(
    *,
    reader: Callable[[str], str],
    printer: Callable[[str], None],
) -> str | None:
    starters = bundled_starter_catalog()
    if not starters:
        return DEFAULT_STARTER_ID
    default_index = next(
        (index for index, starter in enumerate(starters, start=1) if starter["id"] == DEFAULT_STARTER_ID),
        1,
    )
    printer("mission-discovery: choose a bundled starter project")
    for index, starter in enumerate(starters, start=1):
        default_marker = " (default)" if index == default_index else ""
        printer(f"{index}. {starter['title']}{default_marker} — {starter['description']}")
    while True:
        response = _read_discovery_response(
            reader,
            f"mission-discovery: Select a starter project [default {default_index}] ",
        )
        if response is None:
            return None
        if not response:
            return starters[default_index - 1]["id"]
        if response.isdigit():
            index = int(response)
            if 1 <= index <= len(starters):
                return starters[index - 1]["id"]
        for starter in starters:
            if response == starter["id"]:
                return starter["id"]
        printer("mission-discovery: invalid starter selection; choose a listed number or starter id")


def compile_discovery_config(
    *,
    mission_idea: str,
    discovery_answers: dict[str, str],
    mission_id: str | None = None,
    project_root: Path | None = None,
    starter_project_id: str | None = None,
) -> dict[str, Any]:
    answers = {"mission_idea": mission_idea, **discovery_answers}
    objective = _normalize_text(answers["mission_idea"])
    if not objective:
        raise ValueError("mission_idea is required for discovery compilation")
    title_seed = objective.split(".")[0] or objective
    title = title_seed[:120].rstrip(" ,;:") or "Interactive mission discovery"
    summary_parts = [
        f"Compile an executable DeepLoop mission from interactive discovery for: {objective}",
    ]
    available_assets = _normalize_text(answers.get("available_assets"))
    if available_assets:
        summary_parts.append(f"Starting context: {available_assets}")
    summary = " ".join(summary_parts)
    discovery_payload = _discovery_payload(answers)

    if project_root is None:
        resolved_mission_id = _normalize_text(mission_id) or f"{_slugify(title)}-mission"
        selected_starter_id = starter_project_id or DEFAULT_STARTER_ID
        discovery_root = materialize_starter_project(
            starter_id=selected_starter_id,
            title=title,
            summary=summary,
            objective=objective,
            mission_id=resolved_mission_id,
        )
        project_facts_path = discovery_root / "project-facts.yaml"
        project_facts = yaml.safe_load(project_facts_path.read_text(encoding="utf-8")) or {}
        if not isinstance(project_facts, dict):
            project_facts = {}
        project_section = project_facts.get("project") if isinstance(project_facts.get("project"), dict) else {}
        existing_constraints = [
            str(item).strip()
            for item in project_section.get("constraints", [])
            if str(item).strip()
        ]
        discovery_human_inputs = _discovery_contract_human_inputs(answers)
        project_section.update(
            {
                "name": _slugify(title),
                "title": title,
                "summary": summary,
                "objective": objective,
                "constraints": _dedupe_strings([*existing_constraints, *_discovery_constraints(answers)]),
                "human_inputs": {
                    **(
                        dict(project_section.get("human_inputs"))
                        if isinstance(project_section.get("human_inputs"), dict)
                        else {}
                    ),
                    **discovery_human_inputs,
                    "starter_project": selected_starter_id,
                },
            }
        )
        project_facts["project"] = project_section
        write_yaml_mapping(project_facts_path, project_facts)
        base_config = build_mission_config_from_project_root(discovery_root, mission_id=resolved_mission_id)
        base_config["mission"]["human_inputs"] = {
            **(base_config["mission"].get("human_inputs") if isinstance(base_config["mission"].get("human_inputs"), dict) else {}),
            "mission_discovery": discovery_payload,
        }
        docs_root = discovery_root / "docs"
        docs_root.mkdir(parents=True, exist_ok=True)
        write_markdown(docs_root / "project-brief.md", _discovery_brief_lines(base_config, answers))
    else:
        resolved_project_root = project_root.expanduser().resolve()
        base_config = build_mission_config_from_project_root(resolved_project_root, mission_id=mission_id)
        discovery_human_inputs = _discovery_contract_human_inputs(answers)
        existing_constraints = [
            str(item).strip()
            for item in base_config["mission"].get("constraints", [])
            if str(item).strip()
        ]
        merged_constraints = _dedupe_strings([*existing_constraints, *_discovery_constraints(answers)])
        existing_human_inputs = (
            dict(base_config["mission"].get("human_inputs"))
            if isinstance(base_config["mission"].get("human_inputs"), dict)
            else {}
        )
        contract_human_inputs = {
            key: value
            for key, value in {
                **existing_human_inputs,
                **discovery_human_inputs,
            }.items()
            if key != "mission_discovery"
        }
        base_config["mission"]["title"] = title
        base_config["mission"]["summary"] = summary
        base_config["mission"]["objective"] = objective
        base_config["mission"]["constraints"] = merged_constraints
        base_config["mission"]["human_inputs"] = {
            **contract_human_inputs,
            "mission_discovery": discovery_payload,
        }
        contract = discover_project_contract(resolved_project_root)
        project_metadata = contract.get("project_metadata") if isinstance(contract.get("project_metadata"), dict) else {}
        base_config["mission_contract"] = compile_mission_contract(
            objective=objective,
            summary=summary,
            project_metadata={
                **project_metadata,
                "title": title,
                "summary": summary,
                "objective": objective,
                "constraints": merged_constraints,
                "human_inputs": contract_human_inputs,
            },
            human_inputs=contract_human_inputs,
            artifacts={
                "docs": [str(path) for path in base_config.get("artifacts", {}).get("docs", [])],
                "configs": [str(path) for path in base_config.get("artifacts", {}).get("configs", [])],
            },
            autopilot=base_config.get("autopilot") if isinstance(base_config.get("autopilot"), dict) else {},
        )
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
    contextual_answers: dict[str, str] = {}
    starter_project_id: str | None = None
    if project_root is not None:
        printer(f"mission-discovery: using project context from {project_root}")
        contextual_answers = _project_context_answers(project_root)
    detected_idea = _normalize_text(contextual_answers.get("mission_idea"))
    if detected_idea:
        printer(f"mission-discovery: detected project objective: {detected_idea}")
    idea = _normalize_text(mission_idea)
    if not idea and detected_idea:
        response = _read_discovery_response(
            reader,
            _discovery_prompt(
                "mission-discovery: What is your rough mission idea or goal?",
                default=detected_idea,
                label="detected objective",
            ),
        )
        if response is None:
            return {"cancelled": True, "confirmed": False, "config": None, "config_path": None}
        idea = response or detected_idea
    else:
        attempts = 0
        while not idea:
            response = _read_discovery_response(reader, "mission-discovery: What is your rough mission idea or goal? ")
            if response is None:
                return {"cancelled": True, "confirmed": False, "config": None, "config_path": None}
            idea = response
            attempts += 1
            if idea:
                break
            if attempts >= MAX_INITIAL_IDEA_ATTEMPTS:
                printer("mission-discovery: no mission idea provided; canceling discovery")
                return {"cancelled": True, "confirmed": False, "config": None, "config_path": None}
    if project_root is None:
        starter_project_id = _choose_starter_project(reader=reader, printer=printer)
        if starter_project_id is None:
            return {"cancelled": True, "confirmed": False, "config": None, "config_path": None}
    answers: dict[str, str] = {"mission_idea": idea}
    for field_id, _label, prompt in DISCOVERY_QUESTIONS:
        _question_prompts(printer=printer, answers=answers)
        contextual_default = _normalize_text(contextual_answers.get(field_id))
        response = _read_discovery_response(
            reader,
            _discovery_prompt(f"mission-discovery: {prompt}", default=contextual_default),
        )
        if response is None:
            return {"cancelled": True, "confirmed": False, "config": None, "config_path": None}
        answers[field_id] = response or contextual_default

    config = compile_discovery_config(
        mission_idea=idea,
        discovery_answers={key: value for key, value in answers.items() if key != "mission_idea"},
        mission_id=mission_id,
        project_root=project_root,
        starter_project_id=starter_project_id,
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
    confirmation = _read_discovery_response(reader, "mission-discovery: Proceed with mission kickoff? [y/N] ")
    if confirmation is None:
        confirmation = "n"
    return {
        "cancelled": False,
        "confirmed": confirmation in {"y", "yes"},
        "config": config,
        "config_path": compiled_config_path,
        "starter_project_id": starter_project_id,
    }


__all__ = [
    "DISCOVERY_QUESTIONS",
    "build_discovery_checklist",
    "compile_discovery_config",
    "run_interactive_discovery",
]
