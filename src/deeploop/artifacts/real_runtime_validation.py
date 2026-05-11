from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from deeploop.artifacts.release_automation import GATE_2_RUNTIME_CONTRACT_PATH, load_gate_2_runtime_contract
from deeploop.cli.analyze import _build_analyze_prompt, _render_analyze_result
from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.paths import REPO_ROOT, resolve_workspace_path
from deeploop.core.structured_io import (
    json_safe_value,
    load_json_object,
    load_yaml_mapping,
    write_json_object,
    write_markdown,
    write_text,
    write_yaml_mapping,
)
from deeploop.mission.mission_state import load_mission_state, write_mission_state
from deeploop.mission.orchestrator import initialize_mission
from deeploop.mission.project_bootstrap import build_mission_config_from_project_root
from deeploop.runtime.provider_launcher import run_provider_prompt
from deeploop.runtime.recursive_agent_runtime import run_recursive_agent_loop

GATE_2_REAL_RUNTIME_VALIDATION_CONTRACT_PATH = (
    REPO_ROOT / "configs" / "runtime" / "gate-2-real-runtime-validation.yaml"
)
_PROVIDER_SETUP_REGISTRY_PATH = REPO_ROOT / "configs" / "runtime" / "provider-setup-registry.yaml"
_PROVIDER_SELECTION_REGISTRY_PATH = REPO_ROOT / "configs" / "runtime" / "provider-selection-registry.yaml"
_COMMAND_CHECK_TIMEOUT_SECONDS = 20


def load_gate_2_real_runtime_validation_contract(
    path: Path = GATE_2_REAL_RUNTIME_VALIDATION_CONTRACT_PATH,
) -> dict[str, Any]:
    contract = load_yaml_mapping(path)
    if contract.get("contract_id") != "gate-2-real-runtime-validation":
        raise ValueError(f"Unexpected Gate 2 runtime validation contract id in {path}")
    return contract


def _selection_profile_record(selection_profile: str) -> dict[str, Any]:
    registry = load_yaml_mapping(_PROVIDER_SELECTION_REGISTRY_PATH)
    profiles = registry.get("selection_profiles") if isinstance(registry.get("selection_profiles"), dict) else {}
    record = profiles.get(selection_profile)
    if not isinstance(record, dict):
        raise ValueError(f"Unknown provider selection profile `{selection_profile}` in {_PROVIDER_SELECTION_REGISTRY_PATH}.")
    return record


def _provider_setup_record(provider_family: str) -> dict[str, Any]:
    registry = load_yaml_mapping(_PROVIDER_SETUP_REGISTRY_PATH)
    families = registry.get("provider_families") if isinstance(registry.get("provider_families"), dict) else {}
    record = families.get(provider_family)
    if not isinstance(record, dict):
        raise ValueError(f"Unknown provider family `{provider_family}` in {_PROVIDER_SETUP_REGISTRY_PATH}.")
    return record


def _resolve_provider_target(
    *,
    provider_family: str | None = None,
    selection_profile: str | None = None,
) -> tuple[str, str | None, dict[str, Any]]:
    resolved_profile = str(selection_profile or "").strip() or None
    resolved_provider_family = str(provider_family or "").strip() or None
    if resolved_profile is not None:
        selection_record = _selection_profile_record(resolved_profile)
        derived_provider_family = str(selection_record.get("provider_family") or "").strip()
        if not derived_provider_family:
            mission_default = (
                selection_record.get("mission_default")
                if isinstance(selection_record.get("mission_default"), dict)
                else {}
            )
            derived_provider_family = str(mission_default.get("provider_family") or "").strip()
        if not derived_provider_family:
            raise ValueError(f"Selection profile `{resolved_profile}` does not resolve a provider family.")
        if resolved_provider_family is not None and resolved_provider_family != derived_provider_family:
            raise ValueError(
                f"Selection profile `{resolved_profile}` resolves provider family `{derived_provider_family}`, "
                f"not `{resolved_provider_family}`."
            )
        resolved_provider_family = derived_provider_family
    if resolved_provider_family is None:
        raise ValueError("Provide provider_family or selection_profile.")
    return resolved_provider_family, resolved_profile, _provider_setup_record(resolved_provider_family)


def _trim_process_output(stdout: str, stderr: str, *, limit: int = 200) -> str:
    combined = " ".join(part.strip() for part in (stdout, stderr) if part.strip())
    collapsed = " ".join(combined.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _resolve_registry_command(command: str) -> list[str]:
    tokens = shlex.split(command)
    if not tokens:
        raise ValueError("Provider readiness command must not be empty.")
    if tokens[0] == "python":
        tokens[0] = sys.executable
        if len(tokens) > 1 and tokens[1].startswith("scripts/"):
            tokens[1] = str((REPO_ROOT / tokens[1]).resolve())
    return tokens


def _command_check(command: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            _resolve_registry_command(command),
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_CHECK_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        return {
            "kind": "command",
            "name": command,
            "passed": False,
            "message": f"required command is unavailable: {exc}",
        }
    except subprocess.TimeoutExpired:
        return {
            "kind": "command",
            "name": command,
            "passed": False,
            "message": f"timed out after {_COMMAND_CHECK_TIMEOUT_SECONDS} seconds",
        }
    detail = _trim_process_output(completed.stdout, completed.stderr)
    message = "exited 0" if completed.returncode == 0 else f"exited {completed.returncode}"
    if detail:
        message += f" ({detail})"
    return {
        "kind": "command",
        "name": command,
        "passed": completed.returncode == 0,
        "message": message,
    }


def _python_import_check(modules: list[str]) -> dict[str, Any]:
    module_list = [str(module).strip() for module in modules if str(module).strip()]
    command = [
        sys.executable,
        "-c",
        "import importlib; " + "; ".join(f"importlib.import_module({module!r})" for module in module_list),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_CHECK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "kind": "python-import",
            "modules": module_list,
            "passed": False,
            "message": f"timed out after {_COMMAND_CHECK_TIMEOUT_SECONDS} seconds",
        }
    detail = _trim_process_output(completed.stdout, completed.stderr)
    message = "imports succeeded" if completed.returncode == 0 else f"imports failed with exit code {completed.returncode}"
    if detail:
        message += f" ({detail})"
    return {
        "kind": "python-import",
        "modules": module_list,
        "passed": completed.returncode == 0,
        "message": message,
    }


def _automated_readiness_checks(provider_record: dict[str, Any]) -> list[dict[str, Any]]:
    readiness = (
        provider_record.get("readiness_expectations")
        if isinstance(provider_record.get("readiness_expectations"), dict)
        else {}
    )
    automated = readiness.get("automated") if isinstance(readiness.get("automated"), list) else []
    checks: list[dict[str, Any]] = []
    for raw_check in automated:
        if not isinstance(raw_check, dict):
            continue
        kind = str(raw_check.get("kind") or "").strip()
        if kind == "command":
            command = str(raw_check.get("command") or "").strip()
            if not command:
                continue
            check = _command_check(command)
            check["expectation"] = raw_check.get("expectation")
            checks.append(check)
            continue
        if kind == "env":
            env_name = str(raw_check.get("name") or "").strip()
            if not env_name:
                continue
            present = bool(os.environ.get(env_name, "").strip())
            checks.append(
                {
                    "kind": "env",
                    "name": env_name,
                    "passed": present,
                    "message": "set in the current environment" if present else "not set in the current environment",
                    "expectation": raw_check.get("expectation"),
                }
            )
            continue
        if kind == "python-import":
            raw_modules = raw_check.get("modules") if isinstance(raw_check.get("modules"), list) else []
            modules = [str(module).strip() for module in raw_modules if str(module).strip()]
            if not modules:
                continue
            check = _python_import_check(modules)
            check["expectation"] = raw_check.get("expectation")
            checks.append(check)
    return checks


def _required_tool_checks(provider_record: dict[str, Any]) -> list[dict[str, Any]]:
    raw_tools = provider_record.get("required_tools") if isinstance(provider_record.get("required_tools"), list) else []
    checks: list[dict[str, Any]] = []
    for raw_tool in raw_tools:
        if not isinstance(raw_tool, dict):
            continue
        command_name = str(raw_tool.get("command") or "").strip()
        if not command_name:
            continue
        resolved = shutil.which(command_name)
        checks.append(
            {
                "kind": "required-tool",
                "name": command_name,
                "passed": resolved is not None,
                "message": f"found on PATH at {resolved}" if resolved is not None else "not found on PATH",
                "purpose": raw_tool.get("purpose"),
            }
        )
    return checks


def _manual_readiness_notes(provider_record: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for key in ("auth_prerequisites",):
        raw_notes = provider_record.get(key) if isinstance(provider_record.get(key), list) else []
        notes.extend(str(note).strip() for note in raw_notes if str(note).strip())
    readiness = (
        provider_record.get("readiness_expectations")
        if isinstance(provider_record.get("readiness_expectations"), dict)
        else {}
    )
    raw_manual = readiness.get("manual") if isinstance(readiness.get("manual"), list) else []
    notes.extend(str(note).strip() for note in raw_manual if str(note).strip())
    return _dedupe_strings(notes)


def _build_provider_ready_command(*, provider_family: str | None = None, selection_profile: str | None = None) -> str:
    command = ["deeploop", "provider-ready"]
    if selection_profile:
        command.extend(["--selection-profile", selection_profile])
    elif provider_family:
        command.extend(["--provider-family", provider_family])
    return shlex.join(command)


def _next_provider_setup_step(provider_family: str, failed_checks: list[dict[str, Any]]) -> str:
    failed_env = next((check for check in failed_checks if check.get("kind") == "env"), None)
    if failed_env is not None:
        return f"Set `{failed_env['name']}` in the shell where you will run DeepLoop."
    failed_import = next((check for check in failed_checks if check.get("kind") == "python-import"), None)
    if failed_import is not None:
        modules = ", ".join(failed_import.get("modules", []))
        return f"Install the required Python modules for this provider family: {modules}."
    failed_tool_names = [
        str(check.get("name") or "").split()[0]
        for check in failed_checks
        if check.get("kind") in {"required-tool", "command"}
    ]
    if provider_family == "copilot-cli" and "copilot" in failed_tool_names:
        return "Install the Copilot CLI and complete its machine authentication on this machine."
    if failed_tool_names:
        tools = ", ".join(dict.fromkeys(name for name in failed_tool_names if name))
        return f"Install the required tool(s) for this provider family: {tools}."
    return "Complete the documented machine-level provider setup for this provider family."


def check_provider_readiness(
    *,
    provider_family: str | None = None,
    selection_profile: str | None = None,
    resume_command: str | None = None,
) -> dict[str, Any]:
    resolved_provider_family, resolved_profile, provider_record = _resolve_provider_target(
        provider_family=provider_family,
        selection_profile=selection_profile,
    )
    tool_checks = _required_tool_checks(provider_record)
    automated_checks = _automated_readiness_checks(provider_record)
    failed_checks = [check for check in [*tool_checks, *automated_checks] if not bool(check.get("passed"))]
    manual_notes = _manual_readiness_notes(provider_record)
    recheck_command = _build_provider_ready_command(
        provider_family=resolved_provider_family,
        selection_profile=resolved_profile,
    )
    if failed_checks:
        next_step = _next_provider_setup_step(resolved_provider_family, failed_checks)
        summary = (
            f"Machine-level provider setup is incomplete for `{resolved_provider_family}`. "
            "DeepLoop is stopping before kickoff so you can fix the missing setup explicitly."
        )
        status = "action-required"
    else:
        next_step = "Machine-level provider setup checks passed."
        summary = (
            f"Machine-level provider setup checks passed for `{resolved_provider_family}`. "
            "Provider/model selection remains a separate mission/runtime contract."
        )
        status = "ready"
    return {
        "status": status,
        "provider_family": resolved_provider_family,
        "display_name": str(provider_record.get("display_name") or resolved_provider_family),
        "selection_profile": resolved_profile,
        "runtime_integration": str(provider_record.get("runtime_integration") or "unknown"),
        "setup_doc": "docs/reference/provider-setup.md",
        "selection_doc": "docs/reference/provider-selection.md",
        "scope_boundary": (
            "This surface checks machine-level provider setup only. "
            "Provider/model selection stays separate."
        ),
        "summary": summary,
        "next_step": next_step,
        "resume_command": resume_command,
        "recheck_command": recheck_command,
        "required_tool_checks": tool_checks,
        "automated_checks": automated_checks,
        "failed_checks": failed_checks,
        "manual_notes": manual_notes,
    }


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _slugify(value: str) -> str:
    parts: list[str] = []
    previous_dash = False
    for char in value.lower():
        if char.isalnum():
            parts.append(char)
            previous_dash = False
        elif parts and not previous_dash:
            parts.append("-")
            previous_dash = True
    return "".join(parts).strip("-") or "gate-2-validation"


def _resolved_output_root(raw_root: str | Path | None, contract: dict[str, Any]) -> Path:
    configured_root = raw_root or contract.get("default_evidence_root")
    if configured_root is None:
        raise ValueError("Gate 2 runtime validation contract is missing default_evidence_root")
    return resolve_workspace_path(configured_root)


def _resolved_lane_specs(
    *,
    harness_contract: dict[str, Any] | None = None,
    gate_contract: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    resolved_harness = harness_contract or load_gate_2_real_runtime_validation_contract()
    resolved_gate = gate_contract or load_gate_2_runtime_contract()
    required_lanes = resolved_gate.get("required_lanes") if isinstance(resolved_gate.get("required_lanes"), list) else []
    gate_lane_map = {
        str(lane.get("lane_id")): dict(lane)
        for lane in required_lanes
        if isinstance(lane, dict) and str(lane.get("lane_id") or "").strip()
    }
    harness_lanes = resolved_harness.get("lanes") if isinstance(resolved_harness.get("lanes"), dict) else {}
    harness_lane_ids = {str(key) for key in harness_lanes}
    gate_lane_ids = set(gate_lane_map)
    if harness_lane_ids != gate_lane_ids:
        raise ValueError(
            "Gate 2 runtime validation harness lanes must match the approved Gate 2 lane contract. "
            f"harness={sorted(harness_lane_ids)} gate={sorted(gate_lane_ids)}"
        )
    merged: dict[str, dict[str, Any]] = {}
    for lane_id in sorted(gate_lane_ids):
        lane_harness = dict(harness_lanes.get(lane_id) or {})
        lane_gate = dict(gate_lane_map[lane_id])
        merged[lane_id] = {
            **lane_harness,
            **lane_gate,
            "lane_id": lane_id,
            "source_lane_contract": str(resolved_harness.get("source_lane_contract") or ""),
        }
    return merged


def _file_fingerprints(root: Path) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    if not root.exists():
        return fingerprints
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        fingerprints[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return fingerprints


def _diff_fingerprints(before: dict[str, str], after: dict[str, str]) -> dict[str, Any]:
    before_keys = set(before)
    after_keys = set(after)
    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    changed = sorted(key for key in before_keys & after_keys if before[key] != after[key])
    return {
        "unchanged": not added and not removed and not changed,
        "added_paths": added,
        "removed_paths": removed,
        "changed_paths": changed,
    }


def _lane_notes_for(
    lane_id: str,
    *,
    general_notes: list[str] | None = None,
    lane_notes: dict[str, list[str]] | None = None,
) -> list[str]:
    return _dedupe_strings(list(general_notes or []) + list((lane_notes or {}).get(lane_id, [])))


def _manual_boundary_checks(lane: dict[str, Any], notes: list[str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for env_name in lane.get("required_env_vars") or []:
        name = str(env_name).strip()
        if not name:
            continue
        checks.append(
            {
                "kind": "env",
                "name": name,
                "passed": bool(os.environ.get(name, "").strip()),
                "message": "set in the validation shell" if os.environ.get(name, "").strip() else "missing from the validation shell",
            }
        )
    checks.append(
        {
            "kind": "manual-note",
            "name": "operator-attestation",
            "passed": bool(notes),
            "message": "manual boundary notes recorded" if notes else "record at least one manual boundary note for this lane",
        }
    )
    return checks


def _bootstrap_lane_mission(
    lane: dict[str, Any],
    *,
    lane_root: Path,
    validation_id: str,
) -> dict[str, Any]:
    bootstrap_project = REPO_ROOT / str(lane.get("bootstrap_project") or "")
    if not bootstrap_project.is_dir():
        raise FileNotFoundError(f"Bootstrap project path does not exist: {bootstrap_project}")
    copied_project_root = lane_root / "project"
    if copied_project_root.exists():
        shutil.rmtree(copied_project_root)
    shutil.copytree(bootstrap_project, copied_project_root)
    mission_id = f"{_slugify(validation_id)}-{_slugify(str(lane['lane_id']))}"
    generated_config = build_mission_config_from_project_root(copied_project_root, mission_id=mission_id)
    config_path = lane_root / "generated_mission_config.yaml"
    write_yaml_mapping(config_path, generated_config)
    initialized = initialize_mission(config_path, force=True)
    return {
        "mission_id": mission_id,
        "project_root": copied_project_root,
        "generated_config_path": config_path,
        "generated_config": generated_config,
        "mission_root": Path(initialized["mission_root"]),
        "mission_state_path": Path(initialized["state_path"]),
        "mission_summary_path": Path(initialized["summary_path"]),
        "ledger_path": Path(initialized["ledger_path"]),
    }


def _run_local_qwen_lane(
    lane: dict[str, Any],
    *,
    mission_state_path: Path,
    mission_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    mission_state = load_json_object(mission_state_path)
    runtime_root = mission_root / str(lane.get("runtime_artifact_root") or f"runtime/gate_2_validation/{lane['lane_id']}")
    runtime_root.mkdir(parents=True, exist_ok=True)
    result_json_path = runtime_root / "analyze_result.json"
    prompt_path = runtime_root / "analyze_prompt.md"
    rendered_markdown_path = runtime_root / "analyze_result.md"
    stdout_path = runtime_root / "provider_stdout.txt"
    stderr_path = runtime_root / "provider_stderr.txt"

    prompt_text = _build_analyze_prompt(
        mission_state=mission_state,
        mission_state_path=mission_state_path,
        result_json_path=result_json_path,
        task=str(lane.get("analyze_task") or "").strip() or None,
    )
    write_text(prompt_path, prompt_text)
    completed = run_provider_prompt(
        prompt_path,
        provider_family=str(lane.get("provider_family") or "openai-compatible-api"),
        result_json_path=result_json_path,
        mission_state_path=mission_state_path,
        target_repo=project_root,
        model=str(((lane.get("model_expectation") or {}).get("identifier") or "")).strip() or None,
        allow_all=True,
        no_ask_user=True,
    )
    write_text(stdout_path, completed.stdout or "")
    write_text(stderr_path, completed.stderr or "")

    result_payload = load_json_object(result_json_path) if result_json_path.exists() else None
    if result_payload is not None:
        write_text(rendered_markdown_path, _render_analyze_result(result_payload, result_json_path=result_json_path))
    accepted_statuses = {
        str(status).strip().lower() for status in lane.get("accepted_result_statuses") or [] if str(status).strip()
    }
    result_status = str((result_payload or {}).get("status") or "").strip().lower()
    passed = bool(
        completed.returncode == 0
        and result_payload
        and str((result_payload or {}).get("summary") or "").strip()
        and (not accepted_statuses or result_status in accepted_statuses)
    )
    return {
        "surface": str(lane.get("validation_surface") or "deeploop-analyze"),
        "passed": passed,
        "returncode": completed.returncode,
        "prompt_path": prompt_path,
        "result_json_path": result_json_path,
        "result_markdown_path": rendered_markdown_path if rendered_markdown_path.exists() else None,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "result": result_payload,
    }


def _inject_recursive_validation_action(
    lane: dict[str, Any],
    *,
    mission_state_path: Path,
    mission_root: Path,
    validation_id: str,
) -> dict[str, Any]:
    mission_state = load_mission_state(mission_state_path)
    action_spec = lane.get("validation_action") if isinstance(lane.get("validation_action"), dict) else {}
    role = str(action_spec.get("role") or "planner")
    current_phase = str(mission_state.get("current_phase") or "idea-intake")
    action = {
        "action_id": f"{_slugify(validation_id)}-{_slugify(str(lane['lane_id']))}-validation-action",
        "role": role,
        "task": str(action_spec.get("task") or "Complete one bounded runtime validation step.").strip(),
        "kind": str(action_spec.get("kind") or "runtime-validation").strip() or "runtime-validation",
        "status": "pending",
        "phase": current_phase,
        "runtime_owner": "deeploop",
        "requires_operator_approval": False,
        "artifacts": [],
        "output_paths": [],
        "notes": [str(item).strip() for item in action_spec.get("notes") or [] if str(item).strip()],
    }
    mission_state["next_actions"] = {
        "summary": f"Gate 2 runtime validation action for {lane['lane_id']}",
        "actions": [action],
    }
    roles = mission_state.get("roles") if isinstance(mission_state.get("roles"), list) else []
    if role not in roles:
        mission_state["roles"] = [*roles, role]
    write_mission_state(mission_state_path, mission_state)
    ledger_path = mission_root / "ledger.jsonl"
    append_jsonl(
        ledger_path,
        make_ledger_entry(
            kind="gate-2-runtime-validation-setup",
            mission_id=str(mission_state.get("mission_id") or validation_id),
            summary=f"Injected bounded validation action for {lane['lane_id']}",
            status="ready",
            related_paths=[str(mission_state_path)],
            metadata={"lane_id": lane["lane_id"], "action_id": action["action_id"]},
        ),
    )
    return action


def _run_copilot_lane(
    lane: dict[str, Any],
    *,
    mission_state_path: Path,
    mission_root: Path,
    project_root: Path,
    lane_root: Path,
    validation_id: str,
) -> dict[str, Any]:
    injected_action = _inject_recursive_validation_action(
        lane,
        mission_state_path=mission_state_path,
        mission_root=mission_root,
        validation_id=validation_id,
    )
    loop_name = f"{_slugify(str(lane.get('loop_name_prefix') or 'gate-2-copilot-cli-validation'))}-{_slugify(validation_id)}"
    config_path = lane_root / "recursive_agent_validation.yaml"
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "runtime" / "invoke_provider_prompt.py"),
        "--provider-family",
        str(lane.get("provider_family") or "copilot-cli"),
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
    model_alias = str(((lane.get("model_expectation") or {}).get("alias") or "")).strip()
    if model_alias:
        command.extend(["--model", model_alias])
    config_payload = {
        "mission_state": str(mission_state_path),
        "loop_name": loop_name,
        "max_iterations": int(lane.get("max_iterations", 1) or 1),
        "max_consecutive_failures": 1,
        "provider_selection": {
            "contract": str(lane.get("source_lane_contract") or GATE_2_RUNTIME_CONTRACT_PATH),
            "profile": lane.get("selection_profile"),
            "mission_default": {
                "provider_family": lane.get("provider_family"),
                "backend": lane.get("backend"),
                "model": {"alias": model_alias or None},
            },
        },
        "agent": {
            "command": command,
            "cwd": str(project_root),
        },
    }
    write_yaml_mapping(config_path, config_payload)
    loop_result = run_recursive_agent_loop(config_path)
    accepted_loop_statuses = {
        str(status).strip().lower() for status in lane.get("accepted_loop_statuses") or [] if str(status).strip()
    }
    accepted_iteration_statuses = {
        str(status).strip().lower() for status in lane.get("accepted_iteration_statuses") or [] if str(status).strip()
    }
    latest_outcome = loop_result.get("latest_outcome") if isinstance(loop_result.get("latest_outcome"), dict) else {}
    latest_status = str(latest_outcome.get("status") or "").strip().lower()
    loop_status = str(loop_result.get("status") or "").strip().lower()
    passed = bool(
        str(latest_outcome.get("summary") or "").strip()
        and int(loop_result.get("iterations_completed", 0) or 0) >= 1
        and (not accepted_loop_statuses or loop_status in accepted_loop_statuses)
        and (not accepted_iteration_statuses or latest_status in accepted_iteration_statuses)
    )
    return {
        "surface": str(lane.get("validation_surface") or "recursive-agent-runtime"),
        "passed": passed,
        "config_path": config_path,
        "injected_action": injected_action,
        "loop_result": loop_result,
    }


def _write_lane_record(
    record_path: Path,
    *,
    record: dict[str, Any],
) -> tuple[Path, Path]:
    json_path = record_path / "validation_record.json"
    markdown_path = record_path / "validation_record.md"
    write_json_object(json_path, json_safe_value(record, stringify_keys=True))

    runtime = record.get("runtime_execution") if isinstance(record.get("runtime_execution"), dict) else {}
    provider_readiness = record.get("provider_readiness") if isinstance(record.get("provider_readiness"), dict) else {}
    manual_checks = record.get("manual_boundary_checks") if isinstance(record.get("manual_boundary_checks"), list) else []
    mutation = record.get("project_boundary") if isinstance(record.get("project_boundary"), dict) else {}
    lines = [
        "# Gate 2 real runtime lane validation",
        "",
        f"- validation_id: `{record.get('validation_id')}`",
        f"- lane_id: `{record.get('lane_id')}`",
        f"- status: `{record.get('status')}`",
        f"- provider_family: `{record.get('provider_family')}`",
        f"- backend: `{record.get('backend')}`",
        f"- selection_profile: `{record.get('selection_profile')}`",
        f"- validation_surface: `{runtime.get('surface') or record.get('validation_surface')}`",
        f"- mission_state_path: `{record.get('mission_state_path')}`",
        f"- project_root: `{record.get('project_root')}`",
        f"- operator: `{record.get('operator')}`",
        f"- machine_label: `{record.get('machine_label')}`",
    ]
    model_expectation = record.get("model_expectation") if isinstance(record.get("model_expectation"), dict) else {}
    if model_expectation:
        model_bits = ", ".join(f"{key}={value}" for key, value in model_expectation.items() if value not in {None, ""})
        if model_bits:
            lines.append(f"- model_expectation: {model_bits}")
    lines.append(f"- provider_readiness: `{provider_readiness.get('status', 'unknown')}`")
    lines.append(f"- project_mutation_detected: `{'no' if mutation.get('unchanged') else 'yes'}`")
    lines.extend(["", "## Manual boundary notes", ""])
    notes = record.get("manual_notes") if isinstance(record.get("manual_notes"), list) else []
    if notes:
        lines.extend(f"- {item}" for item in notes)
    else:
        lines.append("- none recorded")
    if manual_checks:
        lines.extend(["", "## Manual boundary checks", ""])
        for check in manual_checks:
            lines.append(
                f"- `{check.get('kind')}` `{check.get('name')}` — {'PASS' if check.get('passed') else 'FAIL'}: {check.get('message')}"
            )
    lines.extend(["", "## Runtime evidence", ""])
    for key in (
        "prompt_path",
        "result_json_path",
        "result_markdown_path",
        "stdout_path",
        "stderr_path",
        "config_path",
    ):
        value = runtime.get(key)
        if value:
            lines.append(f"- {key}: `{value}`")
    loop_result = runtime.get("loop_result") if isinstance(runtime.get("loop_result"), dict) else {}
    if loop_result:
        for key in ("status", "report_json_path", "report_markdown_path", "memory_path", "latest_result_path"):
            value = loop_result.get(key)
            if value:
                lines.append(f"- recursive_{key}: `{value}`")
        latest_outcome = loop_result.get("latest_outcome") if isinstance(loop_result.get("latest_outcome"), dict) else {}
        if latest_outcome.get("summary"):
            lines.append(f"- recursive_summary: {latest_outcome.get('summary')}")
    elif isinstance(runtime.get("result"), dict):
        lines.append(f"- analyze_status: `{runtime['result'].get('status')}`")
        lines.append(f"- analyze_summary: {runtime['result'].get('summary')}")
    if not mutation.get("unchanged", True):
        lines.extend(["", "## Project boundary differences", ""])
        for key in ("added_paths", "removed_paths", "changed_paths"):
            values = mutation.get(key) if isinstance(mutation.get(key), list) else []
            if values:
                lines.append(f"- {key}: {', '.join(values)}")
    blockers = record.get("failure_reasons") if isinstance(record.get("failure_reasons"), list) else []
    if blockers:
        lines.extend(["", "## Failure reasons", ""])
        lines.extend(f"- {item}" for item in blockers)
    write_markdown(markdown_path, lines)
    return json_path, markdown_path


def validate_real_runtime(
    *,
    lane_ids: list[str] | None = None,
    output_root: str | Path | None = None,
    validation_id: str | None = None,
    operator: str | None = None,
    machine_label: str | None = None,
    general_notes: list[str] | None = None,
    lane_notes: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    harness_contract = load_gate_2_real_runtime_validation_contract()
    gate_contract = load_gate_2_runtime_contract()
    lane_specs = _resolved_lane_specs(harness_contract=harness_contract, gate_contract=gate_contract)
    selected_lane_ids = lane_ids or sorted(lane_specs)
    unknown = [lane_id for lane_id in selected_lane_ids if lane_id not in lane_specs]
    if unknown:
        raise ValueError(f"Unknown Gate 2 runtime validation lane(s): {', '.join(sorted(unknown))}")

    resolved_validation_id = validation_id or f"gate-2-{now_utc().replace(':', '').replace('+00:00', 'z')}"
    resolved_operator = (operator or os.environ.get("USER") or "unknown-operator").strip() or "unknown-operator"
    resolved_machine_label = (machine_label or socket.gethostname() or "unknown-machine").strip() or "unknown-machine"
    base_output_root = _resolved_output_root(output_root, harness_contract)
    validation_root = base_output_root / _slugify(resolved_validation_id)
    validation_root.mkdir(parents=True, exist_ok=True)

    lane_results: list[dict[str, Any]] = []
    overall_status = "passed"
    for lane_id in selected_lane_ids:
        lane = lane_specs[lane_id]
        lane_root = validation_root / lane_id
        shutil.rmtree(lane_root, ignore_errors=True)
        lane_root.mkdir(parents=True, exist_ok=True)
        notes = _lane_notes_for(lane_id, general_notes=general_notes, lane_notes=lane_notes)
        failure_reasons: list[str] = []
        runtime_execution: dict[str, Any] = {}
        project_boundary: dict[str, Any] = {"unchanged": True, "added_paths": [], "removed_paths": [], "changed_paths": []}
        manual_checks = _manual_boundary_checks(lane, notes)
        bootstrap: dict[str, Any] | None = None
        provider_readiness: dict[str, Any] = {}

        try:
            bootstrap = _bootstrap_lane_mission(lane, lane_root=lane_root, validation_id=resolved_validation_id)
            before_project = _file_fingerprints(bootstrap["project_root"])
            provider_readiness = check_provider_readiness(
                selection_profile=str(lane.get("selection_profile") or "") or None,
                provider_family=str(lane.get("provider_family") or "") or None,
                resume_command=f"python scripts/release/real_runtime_validation.py --lane {lane_id}",
            )
            failed_manual_checks = [check for check in manual_checks if not bool(check.get("passed"))]
            if provider_readiness.get("status") != "ready":
                failure_reasons.append(str(provider_readiness.get("summary") or "Provider readiness did not pass."))
            if failed_manual_checks:
                failure_reasons.extend(str(check.get("message") or "manual boundary check failed") for check in failed_manual_checks)

            if not failure_reasons:
                if str(lane.get("validation_surface")) == "deeploop-analyze":
                    runtime_execution = _run_local_qwen_lane(
                        lane,
                        mission_state_path=bootstrap["mission_state_path"],
                        mission_root=bootstrap["mission_root"],
                        project_root=bootstrap["project_root"],
                    )
                elif str(lane.get("validation_surface")) == "recursive-agent-runtime":
                    runtime_execution = _run_copilot_lane(
                        lane,
                        mission_state_path=bootstrap["mission_state_path"],
                        mission_root=bootstrap["mission_root"],
                        project_root=bootstrap["project_root"],
                        lane_root=lane_root,
                        validation_id=resolved_validation_id,
                    )
                else:
                    raise ValueError(f"Unsupported validation surface for lane {lane_id}: {lane.get('validation_surface')}")
                if not runtime_execution.get("passed"):
                    failure_reasons.append("Runtime validation surface executed but did not meet the lane success criteria.")

            after_project = _file_fingerprints(bootstrap["project_root"])
            project_boundary = _diff_fingerprints(before_project, after_project)
            if not project_boundary.get("unchanged"):
                failure_reasons.append("The copied project boundary changed during runtime validation.")

            lane_status = "passed" if not failure_reasons else "failed"
            record = {
                "schema_version": 1,
                "generated_at": now_utc(),
                "validation_id": resolved_validation_id,
                "lane_id": lane_id,
                "status": lane_status,
                "operator": resolved_operator,
                "machine_label": resolved_machine_label,
                "provider_family": lane.get("provider_family"),
                "backend": lane.get("backend"),
                "selection_profile": lane.get("selection_profile"),
                "model_expectation": dict(lane.get("model_expectation") or {}),
                "validation_surface": lane.get("validation_surface"),
                "gate_2_lane_contract": dict(lane),
                "proof_boundary": {
                    **dict(gate_contract.get("gate_2_proof_boundary") or {}),
                    **dict(harness_contract.get("proof_boundary") or {}),
                },
                "canonical_public_docs": list(harness_contract.get("canonical_public_docs") or []),
                "manual_boundary_prompts": list(lane.get("manual_boundary_notes") or []),
                "manual_notes": notes,
                "manual_boundary_checks": manual_checks,
                "provider_readiness": provider_readiness,
                "project_root": bootstrap["project_root"],
                "mission_root": bootstrap["mission_root"],
                "mission_state_path": bootstrap["mission_state_path"],
                "mission_summary_path": bootstrap["mission_summary_path"],
                "ledger_path": bootstrap["ledger_path"],
                "generated_config_path": bootstrap["generated_config_path"],
                "project_boundary": project_boundary,
                "runtime_execution": runtime_execution,
                "failure_reasons": failure_reasons,
            }
        except Exception as exc:
            overall_status = "failed"
            record = {
                "schema_version": 1,
                "generated_at": now_utc(),
                "validation_id": resolved_validation_id,
                "lane_id": lane_id,
                "status": "failed",
                "operator": resolved_operator,
                "machine_label": resolved_machine_label,
                "provider_family": lane.get("provider_family"),
                "backend": lane.get("backend"),
                "selection_profile": lane.get("selection_profile"),
                "model_expectation": dict(lane.get("model_expectation") or {}),
                "validation_surface": lane.get("validation_surface"),
                "gate_2_lane_contract": dict(lane),
                "proof_boundary": {
                    **dict(gate_contract.get("gate_2_proof_boundary") or {}),
                    **dict(harness_contract.get("proof_boundary") or {}),
                },
                "canonical_public_docs": list(harness_contract.get("canonical_public_docs") or []),
                "manual_boundary_prompts": list(lane.get("manual_boundary_notes") or []),
                "manual_notes": notes,
                "manual_boundary_checks": manual_checks,
                "provider_readiness": provider_readiness,
                "project_root": (bootstrap or {}).get("project_root"),
                "mission_root": (bootstrap or {}).get("mission_root"),
                "mission_state_path": (bootstrap or {}).get("mission_state_path"),
                "mission_summary_path": (bootstrap or {}).get("mission_summary_path"),
                "ledger_path": (bootstrap or {}).get("ledger_path"),
                "generated_config_path": (bootstrap or {}).get("generated_config_path"),
                "project_boundary": project_boundary,
                "runtime_execution": runtime_execution,
                "failure_reasons": [f"Unhandled validation error: {type(exc).__name__}: {exc}"],
            }
        if record["status"] != "passed":
            overall_status = "failed"
        record_json, record_markdown = _write_lane_record(lane_root, record=record)
        lane_results.append(
            {
                "lane_id": lane_id,
                "status": record["status"],
                "record_json_path": record_json,
                "record_markdown_path": record_markdown,
            }
        )

    summary = {
        "schema_version": 1,
        "generated_at": now_utc(),
        "validation_id": resolved_validation_id,
        "status": overall_status,
        "output_root": validation_root,
        "operator": resolved_operator,
        "machine_label": resolved_machine_label,
        "lane_results": lane_results,
        "contract_paths": {
            "gate_2_runtime_lanes": GATE_2_RUNTIME_CONTRACT_PATH,
            "gate_2_runtime_validation": GATE_2_REAL_RUNTIME_VALIDATION_CONTRACT_PATH,
        },
    }
    summary_json_path = validation_root / "gate_2_real_runtime_validation.json"
    summary_markdown_path = validation_root / "gate_2_real_runtime_validation.md"
    write_json_object(summary_json_path, json_safe_value(summary, stringify_keys=True))
    write_markdown(
        summary_markdown_path,
        [
            "# Gate 2 real runtime validation summary",
            "",
            f"- validation_id: `{resolved_validation_id}`",
            f"- status: `{overall_status}`",
            f"- operator: `{resolved_operator}`",
            f"- machine_label: `{resolved_machine_label}`",
            f"- output_root: `{validation_root}`",
            "",
            "## Lane records",
            "",
            *[
                f"- `{item['lane_id']}` — {item['status']} (`{item['record_json_path']}`)"
                for item in lane_results
            ],
        ],
    )
    return {
        **summary,
        "summary_json_path": summary_json_path,
        "summary_markdown_path": summary_markdown_path,
    }


__all__ = [
    "GATE_2_REAL_RUNTIME_VALIDATION_CONTRACT_PATH",
    "load_gate_2_real_runtime_validation_contract",
    "validate_real_runtime",
]
