from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import shutil
import yaml

from deeploop.core.paths import REPO_ROOT
from deeploop.mission.starter_projects import resolve_starter_source

DEFAULT_MATRIX_PATH = REPO_ROOT / "configs" / "testing" / "disposable-user-simulation-matrix.yaml"


@dataclass(frozen=True)
class DisposableDockerSpec:
    dockerfile: Path
    build_target: str
    image_prefix: str
    workspace_root: PurePosixPath
    artifacts_root: PurePosixPath


@dataclass(frozen=True)
class ExternalSimulatorSpec:
    boundary: str
    required_model_alias: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class DeepLoopControlPlaneSpec:
    selection_profile: str
    provider_family: str
    backend: str
    model_alias: str


@dataclass(frozen=True)
class DeepLoopExperimentExecutionSpec:
    selection_profile: str
    deployment_profile: str
    host_execution_profile: str
    provider_family: str
    backend: str
    model_identifier: str
    endpoint_alias: str
    model_artifact_path: str
    model_artifact_host_path: str
    model_artifact_url: str
    policy_note: str


@dataclass(frozen=True)
class DisposableUserSimulationScenario:
    scenario_id: str
    title: str
    summary: str
    project_shape: str
    user_goal: str
    starter_id: str | None = None
    discovery_starter_id: str | None = None
    fixture_path: Path | None = None


@dataclass(frozen=True)
class DisposableUserSimulationMatrix:
    contract_id: str
    sequential_execution: bool
    disposable_container_per_scenario: bool
    minimum_session_seconds: int
    docker: DisposableDockerSpec
    simulator: ExternalSimulatorSpec
    control_plane: DeepLoopControlPlaneSpec
    experiment_execution: DeepLoopExperimentExecutionSpec
    scenarios: tuple[DisposableUserSimulationScenario, ...]
    source_path: Path


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML mapping at {path}")
    return payload


def _normalize_strings(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        value = raw.strip()
        return (value,) if value else ()
    if isinstance(raw, list | tuple):
        values: list[str] = []
        for item in raw:
            values.extend(_normalize_strings(item))
        return tuple(values)
    value = str(raw).strip()
    return (value,) if value else ()


def _resolved_relative_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def load_disposable_user_simulation_matrix(
    path: Path = DEFAULT_MATRIX_PATH,
) -> DisposableUserSimulationMatrix:
    resolved_path = path.expanduser().resolve()
    payload = _load_yaml_mapping(resolved_path)
    defaults = payload.get("campaign_defaults") if isinstance(payload.get("campaign_defaults"), dict) else {}
    docker = defaults.get("docker") if isinstance(defaults.get("docker"), dict) else {}
    simulator = defaults.get("simulator") if isinstance(defaults.get("simulator"), dict) else {}
    deeploop = defaults.get("deeploop") if isinstance(defaults.get("deeploop"), dict) else {}
    control_plane = deeploop.get("control_plane") if isinstance(deeploop.get("control_plane"), dict) else {}
    experiment_execution = (
        deeploop.get("experiment_execution") if isinstance(deeploop.get("experiment_execution"), dict) else {}
    )

    minimum_session_seconds = int(defaults.get("minimum_session_seconds", 0) or 0)
    if minimum_session_seconds < 3600:
        raise ValueError("Disposable user simulation campaigns must require at least 3600 seconds per scenario.")

    scenarios: list[DisposableUserSimulationScenario] = []
    for raw_scenario in payload.get("scenarios", []):
        if not isinstance(raw_scenario, dict):
            raise ValueError("Scenario entries must be mappings.")
        fixture_path = raw_scenario.get("fixture_path")
        resolved_fixture = _resolved_relative_path(str(fixture_path)) if fixture_path else None
        scenarios.append(
            DisposableUserSimulationScenario(
                scenario_id=str(raw_scenario.get("scenario_id") or "").strip(),
                title=str(raw_scenario.get("title") or "").strip(),
                summary=str(raw_scenario.get("summary") or "").strip(),
                project_shape=str(raw_scenario.get("project_shape") or "").strip(),
                user_goal=str(raw_scenario.get("user_goal") or "").strip(),
                starter_id=str(raw_scenario.get("starter_id") or "").strip() or None,
                discovery_starter_id=str(raw_scenario.get("discovery_starter_id") or "").strip() or None,
                fixture_path=resolved_fixture,
            )
        )

    scenario_ids = [scenario.scenario_id for scenario in scenarios]
    if not scenarios or any(not scenario_id for scenario_id in scenario_ids):
        raise ValueError("Disposable user simulation matrix must declare non-empty scenario_id values.")
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("Disposable user simulation matrix contains duplicate scenario_id values.")

    return DisposableUserSimulationMatrix(
        contract_id=str(payload.get("contract_id") or "disposable-user-simulation-matrix"),
        sequential_execution=bool(defaults.get("sequential_execution", True)),
        disposable_container_per_scenario=bool(defaults.get("disposable_container_per_scenario", True)),
        minimum_session_seconds=minimum_session_seconds,
        docker=DisposableDockerSpec(
            dockerfile=_resolved_relative_path(str(docker.get("dockerfile") or "docker/release-validation.Dockerfile")),
            build_target=str(docker.get("build_target") or "user-simulation-base"),
            image_prefix=str(docker.get("image_prefix") or "deeploop-user-simulation"),
            workspace_root=PurePosixPath(str(docker.get("workspace_root") or "/home/deeploop/Workspaces")),
            artifacts_root=PurePosixPath(str(docker.get("artifacts_root") or "/artifacts")),
        ),
        simulator=ExternalSimulatorSpec(
            boundary=str(simulator.get("boundary") or "external-user-simulator"),
            required_model_alias=str(simulator.get("required_model_alias") or "").strip(),
            notes=_normalize_strings(simulator.get("notes")),
        ),
        control_plane=DeepLoopControlPlaneSpec(
            selection_profile=str(control_plane.get("selection_profile") or "").strip(),
            provider_family=str(control_plane.get("provider_family") or "").strip(),
            backend=str(control_plane.get("backend") or "").strip(),
            model_alias=str(control_plane.get("model_alias") or "").strip(),
        ),
        experiment_execution=DeepLoopExperimentExecutionSpec(
            selection_profile=str(experiment_execution.get("selection_profile") or "").strip(),
            deployment_profile=str(experiment_execution.get("deployment_profile") or "").strip(),
            host_execution_profile=str(experiment_execution.get("host_execution_profile") or "").strip(),
            provider_family=str(experiment_execution.get("provider_family") or "").strip(),
            backend=str(experiment_execution.get("backend") or "").strip(),
            model_identifier=str(experiment_execution.get("model_identifier") or "").strip(),
            endpoint_alias=str(experiment_execution.get("endpoint_alias") or "").strip(),
            model_artifact_path=str(experiment_execution.get("model_artifact_path") or "").strip(),
            model_artifact_host_path=str(
                experiment_execution.get("model_artifact_host_path")
                or experiment_execution.get("model_artifact_path")
                or ""
            ).strip(),
            model_artifact_url=str(experiment_execution.get("model_artifact_url") or "").strip(),
            policy_note=str(experiment_execution.get("policy_note") or "").strip(),
        ),
        scenarios=tuple(scenarios),
        source_path=resolved_path,
    )


def select_scenarios(
    matrix: DisposableUserSimulationMatrix,
    requested_ids: list[str],
) -> list[DisposableUserSimulationScenario]:
    if not requested_ids:
        return list(matrix.scenarios)
    requested = set(requested_ids)
    selected = [scenario for scenario in matrix.scenarios if scenario.scenario_id in requested]
    missing = sorted(requested - {scenario.scenario_id for scenario in selected})
    if missing:
        raise ValueError(f"Unknown disposable user simulation scenarios: {', '.join(missing)}")
    return selected


def scenario_project_root_in_container(
    matrix: DisposableUserSimulationMatrix,
    scenario: DisposableUserSimulationScenario,
) -> PurePosixPath | None:
    if scenario.project_shape == "discovery-first":
        return None
    return matrix.docker.workspace_root / "projects" / scenario.scenario_id


def recommended_deeploop_commands(
    matrix: DisposableUserSimulationMatrix,
    scenario: DisposableUserSimulationScenario,
) -> list[str]:
    project_root = scenario_project_root_in_container(matrix, scenario)
    commands: list[str] = []
    if project_root is None:
        commands.append("deeploop run --until-complete")
    else:
        commands.append(f"deeploop run --project-root {project_root} --until-complete")
    commands.extend(
        [
            "deeploop status --mission-state <mission-state.json>",
            "deeploop inbox --mission-state <mission-state.json>",
            "deeploop resume --mission-state <mission-state.json>",
        ]
    )
    return commands


def runtime_constraints_payload(matrix: DisposableUserSimulationMatrix) -> dict[str, Any]:
    experiment_model = {
        "identifier": matrix.experiment_execution.model_identifier,
        "endpoint_alias": matrix.experiment_execution.endpoint_alias,
        "artifact_path": matrix.experiment_execution.model_artifact_path,
        "artifact_url": matrix.experiment_execution.model_artifact_url,
    }
    if matrix.experiment_execution.model_artifact_host_path:
        experiment_model["host_artifact_path"] = matrix.experiment_execution.model_artifact_host_path
    return {
        "outer_user_simulator": {
            "boundary": matrix.simulator.boundary,
            "model_alias": matrix.simulator.required_model_alias,
            "notes": list(matrix.simulator.notes),
        },
        "deeploop_control_plane": {
            "selection_profile": matrix.control_plane.selection_profile,
            "provider_family": matrix.control_plane.provider_family,
            "backend": matrix.control_plane.backend,
            "model": {"alias": matrix.control_plane.model_alias},
        },
        "deeploop_experiment_execution": {
            "selection_profile": matrix.experiment_execution.selection_profile,
            "deployment_profile": matrix.experiment_execution.deployment_profile,
            "host_execution_profile": matrix.experiment_execution.host_execution_profile,
            "provider_family": matrix.experiment_execution.provider_family,
            "backend": matrix.experiment_execution.backend,
            "model": experiment_model,
            "policy_note": matrix.experiment_execution.policy_note,
        },
        "recursive_agent_provider_selection": {
            "contract": "configs/runtime/provider-selection-registry.yaml",
            "profile": matrix.control_plane.selection_profile,
            "mission_default": {
                "provider_family": matrix.control_plane.provider_family,
                "backend": matrix.control_plane.backend,
                "model": {"alias": matrix.control_plane.model_alias},
            },
            "fallbacks": {"profile": "no-cross-provider-fallback"},
        },
    }


def _runtime_constraint_lines(matrix: DisposableUserSimulationMatrix) -> list[str]:
    lines = [
        f"Use Copilot CLI `{matrix.control_plane.model_alias}` as the DeepLoop control-plane provider.",
        (
            "All DeepLoop-carried experiments must stay on "
            f"`{matrix.experiment_execution.model_identifier}` via selection profile "
            f"`{matrix.experiment_execution.selection_profile}`."
        ),
        (
            "Treat host execution profile "
            f"`{matrix.experiment_execution.host_execution_profile}` as the default local execution envelope."
        ),
        (
            "Use only the downloaded GGUF artifact "
            f"`{matrix.experiment_execution.model_artifact_path}` for local simulation-backed execution."
        ),
    ]
    if (
        matrix.experiment_execution.model_artifact_host_path
        and matrix.experiment_execution.model_artifact_host_path != matrix.experiment_execution.model_artifact_path
    ):
        lines.append(
            "Preserve host provenance from "
            f"`{matrix.experiment_execution.model_artifact_host_path}` while treating "
            f"`{matrix.experiment_execution.model_artifact_path}` as the container-visible runtime path."
        )
    return lines


def apply_runtime_constraints_to_project_facts(
    project_root: Path,
    matrix: DisposableUserSimulationMatrix,
    scenario: DisposableUserSimulationScenario,
) -> None:
    project_facts_path = project_root / "project-facts.yaml"
    if not project_facts_path.exists():
        return
    payload = _load_yaml_mapping(project_facts_path)
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    existing_constraints = [str(item).strip() for item in project.get("constraints", []) if str(item).strip()]
    for line in _runtime_constraint_lines(matrix):
        if line not in existing_constraints:
            existing_constraints.append(line)
    human_inputs = project.get("human_inputs") if isinstance(project.get("human_inputs"), dict) else {}
    human_inputs.update(
        {
            "outer_user_simulator_model": matrix.simulator.required_model_alias,
            "deeploop_control_plane_selection_profile": matrix.control_plane.selection_profile,
            "deeploop_control_plane_model_alias": matrix.control_plane.model_alias,
            "deeploop_experiment_execution_selection_profile": matrix.experiment_execution.selection_profile,
            "deeploop_experiment_execution_model_identifier": matrix.experiment_execution.model_identifier,
            "deeploop_experiment_execution_model_artifact_path": matrix.experiment_execution.model_artifact_path,
            "deeploop_host_execution_profile": matrix.experiment_execution.host_execution_profile,
            "user_simulation_scenario": scenario.scenario_id,
        }
    )
    if matrix.experiment_execution.model_artifact_host_path:
        human_inputs["deeploop_experiment_execution_model_artifact_host_path"] = (
            matrix.experiment_execution.model_artifact_host_path
        )
    project["constraints"] = existing_constraints
    project["human_inputs"] = human_inputs
    payload["project"] = project
    project_facts_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def materialize_scenario_workspace(
    matrix: DisposableUserSimulationMatrix,
    scenario: DisposableUserSimulationScenario,
    *,
    workspace_root: Path,
) -> Path | None:
    workspace_root.mkdir(parents=True, exist_ok=True)
    projects_root = workspace_root / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    if scenario.project_shape == "discovery-first":
        return None
    project_root = projects_root / scenario.scenario_id
    if project_root.exists():
        shutil.rmtree(project_root)
    if scenario.project_shape == "bundled-starter":
        if scenario.starter_id is None:
            raise ValueError(f"Scenario `{scenario.scenario_id}` is missing starter_id.")
        shutil.copytree(resolve_starter_source(scenario.starter_id), project_root)
    elif scenario.project_shape == "plain-folder-fixture":
        if scenario.fixture_path is None:
            raise ValueError(f"Scenario `{scenario.scenario_id}` is missing fixture_path.")
        shutil.copytree(scenario.fixture_path, project_root)
    else:
        raise ValueError(f"Unsupported project_shape `{scenario.project_shape}`.")
    apply_runtime_constraints_to_project_facts(project_root, matrix, scenario)
    return project_root


def build_scenario_contract(
    matrix: DisposableUserSimulationMatrix,
    scenario: DisposableUserSimulationScenario,
    *,
    campaign_id: str,
    container_name: str,
) -> dict[str, Any]:
    project_root = scenario_project_root_in_container(matrix, scenario)
    return {
        "contract_id": matrix.contract_id,
        "campaign_id": campaign_id,
        "scenario_id": scenario.scenario_id,
        "title": scenario.title,
        "summary": scenario.summary,
        "project_shape": scenario.project_shape,
        "user_goal": scenario.user_goal,
        "minimum_session_seconds": matrix.minimum_session_seconds,
        "sequential_execution": matrix.sequential_execution,
        "disposable_container_per_scenario": matrix.disposable_container_per_scenario,
        "container": {
            "name": container_name,
            "workspace_root": str(matrix.docker.workspace_root),
            "artifacts_root": str(matrix.docker.artifacts_root),
            "project_root": str(project_root) if project_root is not None else None,
        },
        "runtime_constraints": runtime_constraints_payload(matrix),
        "recommended_commands": recommended_deeploop_commands(matrix, scenario),
        "scenario_inputs": {
            "starter_id": scenario.starter_id,
            "discovery_starter_id": scenario.discovery_starter_id,
            "fixture_path": str(scenario.fixture_path) if scenario.fixture_path is not None else None,
        },
    }


def render_scenario_contract_markdown(contract: dict[str, Any]) -> list[str]:
    container = contract.get("container") if isinstance(contract.get("container"), dict) else {}
    runtime_constraints = (
        contract.get("runtime_constraints") if isinstance(contract.get("runtime_constraints"), dict) else {}
    )
    control_plane = (
        runtime_constraints.get("deeploop_control_plane")
        if isinstance(runtime_constraints.get("deeploop_control_plane"), dict)
        else {}
    )
    experiment_execution = (
        runtime_constraints.get("deeploop_experiment_execution")
        if isinstance(runtime_constraints.get("deeploop_experiment_execution"), dict)
        else {}
    )
    experiment_model = experiment_execution.get("model") if isinstance(experiment_execution.get("model"), dict) else {}
    recommended_commands = contract.get("recommended_commands") if isinstance(contract.get("recommended_commands"), list) else []
    lines = [
        f"# Disposable user simulation scenario: {contract.get('scenario_id')}",
        "",
        f"- campaign_id: `{contract.get('campaign_id')}`",
        f"- title: `{contract.get('title')}`",
        f"- project_shape: `{contract.get('project_shape')}`",
        f"- container_name: `{container.get('name')}`",
        f"- workspace_root: `{container.get('workspace_root')}`",
        f"- project_root: `{container.get('project_root')}`",
        f"- minimum_session_seconds: `{contract.get('minimum_session_seconds')}`",
        "",
        "## Pinned DeepLoop runtime lanes",
        "",
        (
            f"- control plane: `{control_plane.get('selection_profile')}` / "
            f"`{control_plane.get('model', {}).get('alias')}`"
        ),
        (
            f"- experiment execution: `{experiment_execution.get('selection_profile')}` / "
            f"`{experiment_model.get('identifier')}`"
        ),
        (
            f"- experiment endpoint alias: "
            f"`{experiment_model.get('endpoint_alias')}`"
        ),
        (
            f"- required GGUF artifact: "
            f"`{experiment_model.get('artifact_path')}`"
        ),
    ]
    if experiment_model.get("host_artifact_path"):
        lines.append(f"- host GGUF provenance: `{experiment_model.get('host_artifact_path')}`")
    lines.extend(
        [
        (
            f"- host execution profile: "
            f"`{experiment_execution.get('host_execution_profile')}`"
        ),
        "",
        "## Recommended DeepLoop commands",
        "",
        ]
    )
    lines.extend(f"- `{command}`" for command in recommended_commands)
    return lines


def render_outer_user_prompt(
    matrix: DisposableUserSimulationMatrix,
    scenario: DisposableUserSimulationScenario,
    contract: dict[str, Any],
) -> list[str]:
    container = contract.get("container") if isinstance(contract.get("container"), dict) else {}
    recommended_commands = contract.get("recommended_commands") if isinstance(contract.get("recommended_commands"), list) else []
    lines = [
        f"# Outer user simulation prompt: {scenario.scenario_id}",
        "",
        f"You are simulating a fresh user for `{scenario.title}`.",
        "",
        "## Non-negotiable boundaries",
        "",
        f"- outer user simulator model: `{matrix.simulator.required_model_alias}`",
        f"- container name: `{container.get('name')}`",
        f"- minimum session wall time: `{matrix.minimum_session_seconds}` seconds",
        "- treat this container as disposable; do not assume any prior user state",
        (
            f"- when using DeepLoop, keep its control plane pinned to "
            f"`{matrix.control_plane.model_alias}` via `{matrix.control_plane.selection_profile}`"
        ),
        (
            f"- all DeepLoop-carried experiments must stay on "
            f"`{matrix.experiment_execution.model_identifier}` via "
            f"`{matrix.experiment_execution.selection_profile}`"
        ),
        (
            f"- use only the downloaded GGUF artifact "
            f"`{matrix.experiment_execution.model_artifact_path}` when serving the local execution lane"
        ),
        (
            "- if the contract provides a concrete `project_root` and a matching "
            "`deeploop run --project-root ... --until-complete` command, start with "
            "that exact command before trying discovery-style fallbacks"
        ),
        "",
        "## Scenario goal",
        "",
        scenario.user_goal,
        "",
        "## Recommended commands inside the container",
        "",
    ]
    lines.extend(f"- `{command}`" for command in recommended_commands)
    lines.extend(
        [
            "",
            "## Required artifacts",
            "",
            "- keep durable notes, transcripts, and any simulator wrapper outputs under the mounted scenario artifact directory",
            "- use the generated runtime pin files and project facts as the source of truth for the DeepLoop lane policy",
        ]
    )
    return lines


__all__ = [
    "DEFAULT_MATRIX_PATH",
    "DisposableUserSimulationMatrix",
    "DisposableUserSimulationScenario",
    "apply_runtime_constraints_to_project_facts",
    "build_scenario_contract",
    "load_disposable_user_simulation_matrix",
    "materialize_scenario_workspace",
    "recommended_deeploop_commands",
    "render_outer_user_prompt",
    "render_scenario_contract_markdown",
    "runtime_constraints_payload",
    "scenario_project_root_in_container",
    "select_scenarios",
]
