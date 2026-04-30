from __future__ import annotations

"""Mission bootstrap surface.

This module now owns mission initialization only. Canonical mission execution
and monitoring live in :mod:`deeploop.mission.mission_runtime` and
:mod:`deeploop.mission.mission_monitor`.
"""

import json
import sys
from pathlib import Path

import yaml

from deeploop.autonomy.mission_contract_snapshot import materialize_mission_contract_snapshot
from deeploop.autonomy.mission_autonomy import build_outer_loop_contract
from deeploop.autonomy.operating_modes import DEFAULT_OPERATING_MODE
from deeploop.autonomy.operator_inbox import ensure_operator_inbox_contract
from deeploop.core.ledger import append_jsonl, make_ledger_entry
from deeploop.core.paths import MISSIONS_DIR, REPO_ROOT
from deeploop.core.structured_io import write_json_object, write_markdown, write_text, write_yaml_mapping
from deeploop.mission.mission_memory import sync_mission_memory
from deeploop.mission.plain_folder_followup import materialize_plain_folder_followups
from deeploop.mission.mission_state import write_mission_state
from deeploop.platform.contracts import materialize_platform_expansion_bundle, sync_platform_expansion_bundle
from deeploop.project_contract import discover_project_contract, normalize_data_artifacts, project_contract_input_artifacts
from deeploop.runtime.sandbox import build_sandbox_spec, rule_sources_for_repo


ROLE_OUTPUTS = {
    "planner": ["mission plan updates", "phase transitions"],
    "literature-scout": ["prior-art notes", "benchmark watchlists"],
    "dataset-strategist": ["dataset promotion plans", "slice notes"],
    "experiment-designer": ["manifest drafts", "baseline configs"],
    "execution-operator": ["run manifests", "metrics", "logs"],
    "critic-verifier": ["critique summaries", "evidence-state recommendations"],
    "report-synthesizer": ["findings summaries", "paper-ready notes"],
}
DATASET_ARTIFACT_ROLES = {"dataset-strategist", "execution-operator"}


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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


def _default_recursive_agent_command(*, model: str | None = None) -> list[str]:
    command = [
        str(Path(sys.executable).resolve()),
        str(REPO_ROOT / "scripts" / "runtime" / "invoke_provider_prompt.py"),
        "--prompt-file",
        "{prompt_path}",
        "--result-json-path",
        "{result_json_path}",
        "--sandbox-root",
        "{sandbox_root}",
        "--mission-state-path",
        "{mission_state_path}",
        "--target-repo",
        "{target_repo}",
        "--allow-all",
        "--no-ask-user",
    ]
    if model:
        command.extend(["--model", model])
    return command


def _materialize_recursive_agent_profile(
    recursive_cfg: dict,
    *,
    mission_root: Path,
    mission_state_path: Path,
    target_repo: Path,
    mission_id: str,
) -> dict[str, str]:
    loop_name = str(recursive_cfg.get("loop_name") or f"{mission_id}-phase-loop")
    profile_root = mission_root / "runtime" / "recursive_agent_profiles"
    profile_root.mkdir(parents=True, exist_ok=True)
    profile_path = profile_root / f"{loop_name}.yaml"
    context = {
        "mission_id": mission_id,
        "mission_root": str(mission_root),
        "mission_state_path": str(mission_state_path),
        "target_repo": str(target_repo),
        "recursive_agent_config_path": str(profile_path),
    }
    agent_cfg = recursive_cfg.get("agent") if isinstance(recursive_cfg.get("agent"), dict) else {}
    command = agent_cfg.get("command")
    if not isinstance(command, list) or not command:
        command = _default_recursive_agent_command(model=str(recursive_cfg.get("model") or "").strip() or None)
    payload = {
        "mission_state": str(mission_state_path),
        "loop_name": loop_name,
        "max_iterations": int(recursive_cfg.get("max_iterations", 2) or 2),
        "max_consecutive_failures": int(recursive_cfg.get("max_consecutive_failures", 2) or 2),
        "policy_path": str(
            Path(
                recursive_cfg.get("policy_path")
                or (REPO_ROOT / "configs" / "runtime" / "recursive-agent-runtime.yaml")
            )
            .expanduser()
            .resolve()
        ),
        "agent": {
            "command": _resolve_templates(command, context),
            "cwd": str(Path(str(agent_cfg.get("cwd") or target_repo)).expanduser().resolve()),
        },
    }
    if agent_cfg.get("env_name") is not None:
        payload["agent"]["env_name"] = str(agent_cfg["env_name"])
    write_yaml_mapping(profile_path, payload)
    return {"loop_name": loop_name, "config_path": str(profile_path)}


def _phase_execution_hints(config: dict, *, context: dict[str, str]) -> dict[str, dict]:
    autopilot_cfg = config.get("autopilot") if isinstance(config.get("autopilot"), dict) else {}
    raw_hints = autopilot_cfg.get("phase_execution_hints")
    if not isinstance(raw_hints, dict):
        return {}
    hints: dict[str, dict] = {}
    for phase, raw_hint in raw_hints.items():
        if not isinstance(raw_hint, dict):
            continue
        executor_name = str(raw_hint.get("executor") or raw_hint.get("executor_id") or "").strip()
        params = raw_hint.get("params") if isinstance(raw_hint.get("params"), dict) else {}
        resolved_params = _resolve_templates(params, context)
        if executor_name == "recursive-agent" and "config_path" not in resolved_params:
            recursive_config_path = context.get("recursive_agent_config_path")
            if recursive_config_path:
                resolved_params = {**resolved_params, "config_path": recursive_config_path}
        if executor_name == "report-synthesis" and "mission_state_path" not in resolved_params:
            resolved_params = {**resolved_params, "mission_state_path": context["mission_state_path"]}
        hint: dict[str, object] = {
            "executor": {
                "id": executor_name,
                "params": resolved_params,
            }
        }
        for key in ("artifacts", "notes", "produces_outputs"):
            if key in raw_hint:
                resolved_value = _resolve_templates(raw_hint.get(key), context)
                if isinstance(resolved_value, list):
                    hint[key] = [str(item) for item in resolved_value]
        next_phase_on_success = _resolve_templates(raw_hint.get("next_phase_on_success"), context)
        if isinstance(next_phase_on_success, str) and next_phase_on_success.strip():
            hint["next_phase_on_success"] = next_phase_on_success.strip()
        deterministic_routes = _resolve_templates(raw_hint.get("deterministic_routes"), context)
        if isinstance(deterministic_routes, list):
            hint["deterministic_routes"] = [dict(item) for item in deterministic_routes if isinstance(item, dict)]
        hints[str(phase)] = hint
    return hints


def _initial_phase_state(config: dict) -> tuple[str, list[str], list[str], str]:
    phases = [str(phase) for phase in config.get("phases", [])]
    if not phases:
        raise ValueError("Mission config must declare at least one phase.")
    mission_cfg = config.get("mission") if isinstance(config.get("mission"), dict) else {}
    initial_phase = str(mission_cfg.get("initial_phase") or phases[0]).strip()
    if initial_phase not in phases:
        raise ValueError(f"Configured initial_phase `{initial_phase}` is not in mission phases.")
    initial_index = phases.index(initial_phase)
    raw_seed = mission_cfg.get("seed_completed_phases")
    if isinstance(raw_seed, list):
        completed_phases = [str(item).strip() for item in raw_seed if str(item).strip()]
    else:
        completed_phases = phases[:initial_index]
    invalid = [phase for phase in completed_phases if phase not in phases]
    if invalid:
        raise ValueError(f"Configured seed_completed_phases contains unknown phases: {', '.join(invalid)}")
    phase_history = list(completed_phases)
    if not phase_history or phase_history[-1] != initial_phase:
        phase_history.append(initial_phase)
    next_phase = phases[initial_index + 1] if initial_index + 1 < len(phases) else initial_phase
    return initial_phase, completed_phases, phase_history, next_phase


def _bootstrap_state(config: dict, *, context: dict[str, str]) -> dict[str, object]:
    mission_cfg = config.get("mission") if isinstance(config.get("mission"), dict) else {}
    raw_bootstrap = mission_cfg.get("bootstrap")
    if not isinstance(raw_bootstrap, dict):
        return {}
    resolved = _resolve_templates(raw_bootstrap, context)
    if not isinstance(resolved, dict):
        return {}
    bootstrap = {str(key): value for key, value in resolved.items()}
    queue_path = bootstrap.get("baseline_queue_config")
    if isinstance(queue_path, str) and queue_path.strip():
        resolved_queue_path = Path(queue_path).expanduser().resolve()
        if not resolved_queue_path.exists():
            raise FileNotFoundError(f"Bootstrap baseline queue config not found: {resolved_queue_path}")
        bootstrap["baseline_queue_config"] = str(resolved_queue_path)
    if bootstrap and "status" not in bootstrap:
        bootstrap["status"] = "pending"
    return bootstrap


def _remove_tree(path: Path) -> None:
    import shutil

    for _ in range(3):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
    if path.exists():
        raise OSError(f"Unable to remove existing mission root: {path}")


def _merge_artifacts(config_artifacts: dict | None, project_contract: dict[str, object], *, target_repo: Path) -> dict[str, list]:
    merged: dict[str, list] = {"docs": [], "configs": [], "data": []}
    if isinstance(config_artifacts, dict):
        for key in ("docs", "configs"):
            values = config_artifacts.get(key)
            if isinstance(values, list):
                merged[key].extend(str(item) for item in values if str(item).strip())
        merged["data"].extend(normalize_data_artifacts(config_artifacts.get("data"), base_dir=target_repo))
    contract_artifacts = project_contract.get("artifacts") if isinstance(project_contract.get("artifacts"), dict) else {}
    for key in ("docs", "configs"):
        values = contract_artifacts.get(key)
        if isinstance(values, list):
            merged[key].extend(str(item) for item in values if str(item).strip())
    data_values = contract_artifacts.get("data")
    if isinstance(data_values, list):
        merged["data"].extend(dict(item) for item in data_values if isinstance(item, dict))
    for key in ("docs", "configs"):
        deduped: list[str] = []
        seen: set[str] = set()
        for value in merged[key]:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        merged[key] = deduped
    deduped_data: list[dict] = []
    seen_data: set[str] = set()
    for value in merged["data"]:
        if not isinstance(value, dict):
            continue
        path = str(value.get("path") or "").strip()
        if not path or path in seen_data:
            continue
        seen_data.add(path)
        deduped_data.append(value)
    merged["data"] = deduped_data
    return merged


def _data_artifact_paths(data_artifacts: list) -> list[str]:
    paths: list[str] = []
    for artifact in data_artifacts:
        if isinstance(artifact, dict) and str(artifact.get("path") or "").strip():
            paths.append(str(artifact["path"]))
    return paths


def initialize_mission(config_path: Path, *, force: bool = False) -> dict:
    config = _load_yaml(config_path)
    mission_cfg = config["mission"]
    requested_mode = str(mission_cfg.get("mode") or DEFAULT_OPERATING_MODE)
    mission_id = mission_cfg["id"]
    target_repo = Path(mission_cfg["target_repo"]).expanduser()
    project_contract = discover_project_contract(target_repo)
    mission_artifacts = _merge_artifacts(config.get("artifacts"), project_contract, target_repo=target_repo)
    data_artifact_paths = _data_artifact_paths(mission_artifacts["data"])
    handoff_artifacts = project_contract_input_artifacts(project_contract) + mission_artifacts["docs"] + mission_artifacts["configs"] + data_artifact_paths
    handoff_artifacts = list(dict.fromkeys(handoff_artifacts))
    mission_root = MISSIONS_DIR / mission_id

    if mission_root.exists() and force:
        _remove_tree(mission_root)
    mission_root.mkdir(parents=True, exist_ok=True)
    handoff_root = mission_root / "agent_handoffs"
    findings_root = mission_root / "findings"
    handoff_root.mkdir(parents=True, exist_ok=True)
    findings_root.mkdir(parents=True, exist_ok=True)
    outer_loop = build_outer_loop_contract(mission_root, mode=requested_mode)
    ensure_operator_inbox_contract(mission_root, contract=outer_loop)
    mission_mode = str(outer_loop.get("mode") or requested_mode)
    current_phase, completed_phases, phase_history, next_phase = _initial_phase_state(config)
    contract_snapshot = materialize_mission_contract_snapshot(
        mission_root,
        mode=requested_mode,
        outer_loop_contract=outer_loop,
    )
    outer_loop["contract_snapshot_path"] = contract_snapshot["snapshot_path"]
    write_text(Path(outer_loop["decision_log_path"]), "")
    write_text(Path(outer_loop["branch_log_path"]), "")
    write_text(Path(outer_loop["experiment_ledger_path"]), "")
    write_text(Path(outer_loop["operator_request_log_path"]), "")
    write_text(Path(outer_loop["current_operator_request_path"]), "{}\n")

    roles = list(config.get("roles", []))
    sandboxes: dict[str, dict] = {}
    handoffs: dict[str, str] = {}
    for role in roles:
        sandbox = build_sandbox_spec(mission_id, role, target_repo)
        sandboxes[role] = sandbox
        handoff = {
            "mission_id": mission_id,
            "role": role,
            "target_repo": str(target_repo),
            "env_name": sandbox["env_name"],
            "sandbox_root": sandbox["sandbox_root"],
            "rule_sources": sandbox["rule_sources"],
            "input_artifacts": handoff_artifacts,
            "expected_outputs": ROLE_OUTPUTS.get(role, []),
            "instructions": [
                "Ingest rule sources in the listed order before acting.",
                "Write durable outputs inside the assigned sandbox or mission artifacts.",
                "Record non-trivial findings in the mission ledger or findings directory.",
            ],
        }
        if role in DATASET_ARTIFACT_ROLES and mission_artifacts["data"]:
            handoff["dataset_artifacts"] = mission_artifacts["data"]
        handoff_path = handoff_root / f"{role}.json"
        write_json_object(handoff_path, handoff)
        handoffs[role] = str(handoff_path)

    state = {
        "mission_id": mission_id,
        "mode": mission_mode,
        "title": mission_cfg["title"],
        "summary": mission_cfg["summary"],
        "objective": mission_cfg["objective"],
        "current_phase": current_phase,
        "completed_phases": completed_phases,
        "phase_history": phase_history,
        "next_phase": next_phase,
        "autonomy_status": {"state": "initialized", "reason": "Mission created but not yet advanced."},
        "status": "initialized",
        "target_repo": str(target_repo),
        "roles": roles,
        "rule_sources": rule_sources_for_repo(target_repo),
        "artifacts": mission_artifacts,
        "project_contract": project_contract,
        "contract_snapshot": {
            "schema_version": contract_snapshot["schema_version"],
            "path": contract_snapshot["snapshot_path"],
        },
        "next_actions": {},
        "handoffs": handoffs,
        "sandboxes": {role: sandbox["sandbox_root"] for role, sandbox in sandboxes.items()},
        "outer_loop": outer_loop,
    }
    mission_profile = str(mission_cfg.get("profile") or "").strip()
    if mission_profile:
        state["mission_profile"] = mission_profile
    state_path = mission_root / "mission_state.json"
    autopilot_cfg = config.get("autopilot") if isinstance(config.get("autopilot"), dict) else {}
    runtime_profiles: dict[str, dict[str, str]] = {}
    template_context = {
        "mission_id": mission_id,
        "mission_root": str(mission_root),
        "mission_state_path": str(state_path),
        "target_repo": str(target_repo),
    }
    recursive_cfg = autopilot_cfg.get("recursive_agent") if isinstance(autopilot_cfg.get("recursive_agent"), dict) else None
    if isinstance(recursive_cfg, dict):
        recursive_profile = _materialize_recursive_agent_profile(
            recursive_cfg,
            mission_root=mission_root,
            mission_state_path=state_path,
            target_repo=target_repo,
            mission_id=mission_id,
        )
        runtime_profiles["recursive_agent"] = recursive_profile
        template_context["recursive_agent_config_path"] = recursive_profile["config_path"]
    phase_execution_hints = _phase_execution_hints(config, context=template_context)
    bootstrap = _bootstrap_state(config, context=template_context)
    launch_env_name = str(autopilot_cfg.get("launch_env_name") or "").strip()
    launch_profile = str(autopilot_cfg.get("launch_profile") or mission_profile or "").strip()
    raw_launch_max_iterations = autopilot_cfg.get("max_iterations")
    if str(project_contract.get("status") or "") == "plain-artifacts":
        plain_folder_followups = materialize_plain_folder_followups(
            mission_id=mission_id,
            mission_mode=mission_mode,
            mission_root=mission_root,
            mission_state_path=state_path,
            project_contract=project_contract,
        )
        phase_execution_hints = {
            **phase_execution_hints,
            **plain_folder_followups["phase_execution_hints"],
        }
        mission_artifacts["configs"] = list(
            dict.fromkeys(
                [
                    *mission_artifacts["configs"],
                    plain_folder_followups["generated_paths"]["execution_config_path"],
                    plain_folder_followups["generated_paths"]["replication_config_path"],
                ]
            )
        )
        state["artifacts"] = mission_artifacts
        state["plain_folder_followups"] = plain_folder_followups["generated_paths"]
    if runtime_profiles:
        state["runtime_profiles"] = runtime_profiles
    if phase_execution_hints:
        state["phase_execution_hints"] = phase_execution_hints
    deterministic_routing = autopilot_cfg.get("deterministic_routing")
    if isinstance(deterministic_routing, dict):
        state["deterministic_routing"] = _resolve_templates(deterministic_routing, template_context)
    if bootstrap:
        state["bootstrap"] = bootstrap
    runtime_launcher: dict[str, object] = {}
    if launch_env_name:
        runtime_launcher["env_name"] = launch_env_name
    if raw_launch_max_iterations is not None:
        runtime_launcher["max_iterations"] = int(raw_launch_max_iterations)
    if launch_profile:
        runtime_launcher["profile"] = launch_profile
    if runtime_launcher:
        state["runtime_launcher"] = runtime_launcher
    platform_expansion = materialize_platform_expansion_bundle(
        mission_id=mission_id,
        mission_root=mission_root,
        mission_state_path=state_path,
        target_repo=target_repo,
    )
    state["platform_expansion"] = platform_expansion
    write_mission_state(state_path, state)
    sync_mission_memory(state_path, state, contract=outer_loop)
    sync_platform_expansion_bundle(state_path, mission_state=state)

    summary_path = mission_root / "mission_summary.md"
    summary_lines = [
        "# Mission summary",
        "",
        f"- mission_id: `{mission_id}`",
        f"- mode: `{mission_mode}`",
        *( [f"- mission_profile: `{mission_profile}`"] if mission_profile else [] ),
        f"- target_repo: `{target_repo}`",
        f"- objective: {mission_cfg['objective']}",
        f"- current_phase: `{current_phase}`",
        f"- contract_snapshot_path: `{contract_snapshot['snapshot_path']}`",
        f"- platform_root: `{platform_expansion['platform_root']}`",
        "- platform_surfaces: "
        + ", ".join(
            f"`{surface_id}` ({surface.get('status', 'planned')})"
            for surface_id, surface in sorted(platform_expansion["surfaces"].items())
        ),
        f"- project_contract_status: `{project_contract['status']}`",
        f"- project_contract_root: `{project_contract['contract_root']}`",
    ]
    write_markdown(
        summary_path,
        summary_lines,
    )

    ledger_path = mission_root / "ledger.jsonl"
    append_jsonl(
        ledger_path,
        make_ledger_entry(
            kind="mission-init",
            mission_id=mission_id,
            summary=f"Initialized mission {mission_id}",
            status="initialized",
            related_paths=[
                str(state_path),
                str(summary_path),
                outer_loop["decision_log_path"],
                outer_loop["branch_log_path"],
                outer_loop["mission_memory_path"],
                outer_loop["experiment_ledger_path"],
                outer_loop["operator_request_log_path"],
                outer_loop["current_operator_request_path"],
                platform_expansion["manifest_path"],
                *[
                    str(surface["handoff_path"])
                    for surface in platform_expansion["surfaces"].values()
                    if isinstance(surface, dict) and surface.get("handoff_path")
                ],
            ],
            metadata={"config_path": str(config_path)},
        ),
    )

    return {
        "mission_root": mission_root,
        "state_path": state_path,
        "summary_path": summary_path,
        "ledger_path": ledger_path,
    }
