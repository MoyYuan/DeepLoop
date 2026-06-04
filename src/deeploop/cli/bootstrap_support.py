from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from deeploop.core.paths import (
    EXPECTED_EXTERNAL_DIRS,
    REPO_ROOT,
    WORKSPACE_ROOT,
    WORKSPACE_ROOT_ENV_VAR,
    ensure_expected_external_dirs,
)

_PROVIDER_SETUP_REGISTRY_PATH = REPO_ROOT / "configs" / "runtime" / "provider-setup-registry.yaml"
_PROVIDER_SELECTION_REGISTRY_PATH = REPO_ROOT / "configs" / "runtime" / "provider-selection-registry.yaml"
_DEFAULT_FIRST_RUN_SELECTION_PROFILE = "deepseek-chat-control-plane"
_COMMAND_CHECK_TIMEOUT_SECONDS = 20


def _check_python_version() -> tuple[bool, str]:
    major, minor = sys.version_info[:2]
    supported = (major, minor) >= (3, 11)
    return supported, f"detected {major}.{minor}; required >= 3.11"


def _check_operating_system() -> tuple[bool, str]:
    system = platform.system()
    supported = system == "Linux"
    return supported, f"detected {system}; supported public bootstrap contract is Linux"


def _check_workspace_root() -> tuple[bool, str]:
    if not WORKSPACE_ROOT.exists():
        return False, f"workspace root is missing: {WORKSPACE_ROOT}"
    writable = os.access(WORKSPACE_ROOT, os.W_OK)
    return writable, f"workspace root `{WORKSPACE_ROOT}` is {'writable' if writable else 'not writable'}"


def _check_external_dirs() -> tuple[bool, str]:
    missing = [str(path) for path in EXPECTED_EXTERNAL_DIRS if not path.exists()]
    if missing:
        return False, f"missing expected workspace dirs: {', '.join(missing[:4])}"
    unwritable = [str(path) for path in EXPECTED_EXTERNAL_DIRS if not os.access(path, os.W_OK)]
    if unwritable:
        return False, f"workspace dirs are not writable: {', '.join(unwritable[:4])}"
    return True, f"validated {len(EXPECTED_EXTERNAL_DIRS)} writable workspace dirs under `{WORKSPACE_ROOT}`"


def validate_public_bootstrap_environment() -> dict[str, tuple[bool, str]]:
    return {
        "python_version": _check_python_version(),
        "operating_system": _check_operating_system(),
        "workspace_root": _check_workspace_root(),
        "external_dirs": _check_external_dirs(),
    }


def _preflight_payload() -> dict[str, object]:
    checks = validate_public_bootstrap_environment()
    return {
        "workspace_root": str(WORKSPACE_ROOT),
        "checks": {
            name: {"passed": passed, "message": message}
            for name, (passed, message) in checks.items()
        },
    }


def _render_preflight_report(payload: dict[str, object]) -> str:
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    lines = ["# DeepLoop public bootstrap preflight"]
    for name, report in checks.items():
        if not isinstance(report, dict):
            continue
        passed = bool(report.get("passed"))
        symbol = "PASS" if passed else "FAIL"
        lines.append(f"- {name}: {symbol} — {report.get('message')}")
    return "\n".join(lines)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected YAML mapping at {path}")
    return loaded


def _selection_profile_record(selection_profile: str) -> dict[str, Any]:
    registry = _load_yaml_mapping(_PROVIDER_SELECTION_REGISTRY_PATH)
    profiles = registry.get("selection_profiles") if isinstance(registry.get("selection_profiles"), dict) else {}
    record = profiles.get(selection_profile)
    if not isinstance(record, dict):
        raise ValueError(
            f"Unknown provider selection profile `{selection_profile}` in {_PROVIDER_SELECTION_REGISTRY_PATH}."
        )
    return record


def _provider_setup_record(provider_family: str) -> dict[str, Any]:
    registry = _load_yaml_mapping(_PROVIDER_SETUP_REGISTRY_PATH)
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
    if provider_family is None and resolved_profile is None:
        resolved_profile = _DEFAULT_FIRST_RUN_SELECTION_PROFILE
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
        raise ValueError("Provide --provider-family or --selection-profile.")
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
    if completed.returncode == 0:
        message = "exited 0"
        if detail:
            message += f" ({detail})"
    else:
        message = f"exited {completed.returncode}"
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
        (
            "import importlib; "
            + "; ".join(f"importlib.import_module({module!r})" for module in module_list)
        ),
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
                    "message": (
                        "set in the current environment"
                        if present
                        else "not set in the current environment"
                    ),
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
                "message": (
                    f"found on PATH at {resolved}"
                    if resolved is not None
                    else "not found on PATH"
                ),
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
    deduped: list[str] = []
    for note in notes:
        if note and note not in deduped:
            deduped.append(note)
    return deduped


def build_provider_ready_command(
    *,
    provider_family: str | None = None,
    selection_profile: str | None = None,
) -> str:
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
    recheck_command = build_provider_ready_command(
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


def render_provider_ready_report(report: dict[str, Any]) -> str:
    lines = [
        "# DeepLoop provider readiness",
        "",
        f"- provider_family: `{report.get('provider_family')}`",
        f"- display_name: {report.get('display_name')}",
        f"- setup_status: `{report.get('status')}`",
        f"- runtime_integration: `{report.get('runtime_integration')}`",
        f"- scope_boundary: {report.get('scope_boundary')}",
        f"- setup_doc: `{report.get('setup_doc')}`",
        f"- selection_doc: `{report.get('selection_doc')}`",
    ]
    if report.get("selection_profile"):
        lines.append(f"- selection_profile_hint: `{report.get('selection_profile')}`")
    lines.append(f"- summary: {report.get('summary')}")
    if report.get("next_step"):
        lines.append(f"- next_step: {report.get('next_step')}")
    if report.get("resume_command"):
        lines.append(f"- resume_command: `{report.get('resume_command')}`")
    if report.get("recheck_command"):
        lines.append(f"- recheck_command: `{report.get('recheck_command')}`")
    failed_checks = report.get("failed_checks") if isinstance(report.get("failed_checks"), list) else []
    if failed_checks:
        lines.extend(["", "## Missing machine setup checks", ""])
        for check in failed_checks:
            label = check.get("name")
            if check.get("kind") == "python-import":
                label = ", ".join(check.get("modules", []))
            lines.append(f"- `{check.get('kind')}` `{label}`: {check.get('message')}")
    manual_notes = report.get("manual_notes") if isinstance(report.get("manual_notes"), list) else []
    if manual_notes:
        lines.extend(["", "## Manual notes", ""])
        lines.extend(f"- {note}" for note in manual_notes)
    return "\n".join(lines) + "\n"


def _add_setup_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit the scaffold result as JSON.")


def _setup_workspace(args: argparse.Namespace) -> int:
    created_dirs, existing_dirs = ensure_expected_external_dirs()
    payload = {
        "workspace_root": str(WORKSPACE_ROOT),
        "workspace_root_env_var": WORKSPACE_ROOT_ENV_VAR,
        "created_dirs": [str(path) for path in created_dirs],
        "existing_dirs": [str(path) for path in existing_dirs],
        "next_steps": [
            "deeploop preflight",
            "deeploop run --until-complete",
        ],
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return 0

    lines = [
        "# DeepLoop workspace scaffold ready",
        "",
        f"- workspace_root: `{WORKSPACE_ROOT}`",
        f"- override_env_var: `{WORKSPACE_ROOT_ENV_VAR}`",
        f"- created_dirs: `{len(created_dirs)}`",
        f"- already_present_dirs: `{len(existing_dirs)}`",
        "- next: `deeploop preflight`",
        "- first_run: `deeploop run --until-complete`",
        "- repo_checkout_shortcut: `make public-bootstrap-check`",
    ]
    print("\n".join(lines))
    return 0


def _add_preflight_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit the preflight report as JSON.")


def _preflight(args: argparse.Namespace) -> int:
    payload = _preflight_payload()
    checks = payload["checks"] if isinstance(payload["checks"], dict) else {}
    all_passed = all(
        isinstance(report, dict) and bool(report.get("passed"))
        for report in checks.values()
    )
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(_render_preflight_report(payload))
    return 0 if all_passed else 1


def _add_provider_ready_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider-family",
        help="Explicit provider family to validate at the machine-setup layer.",
    )
    parser.add_argument(
        "--selection-profile",
        help=(
            "Optional mission/runtime provider-selection profile. "
            "DeepLoop resolves the underlying provider family from the selection registry, "
            "but still checks setup only."
        ),
    )
    parser.add_argument(
        "--resume-command",
        help="Optional exact command the operator should run after fixing provider setup.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the readiness report as JSON.")


def _provider_ready(args: argparse.Namespace) -> int:
    report = check_provider_readiness(
        provider_family=getattr(args, "provider_family", None),
        selection_profile=getattr(args, "selection_profile", None),
        resume_command=getattr(args, "resume_command", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        print(render_provider_ready_report(report), end="")
    return 0 if report["status"] == "ready" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the installed DeepLoop public bootstrap environment.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_preflight_args(parser)
    args = parser.parse_args(argv)
    return _preflight(args)


__all__ = [
    "main",
    "_add_preflight_args",
    "_add_provider_ready_args",
    "_add_setup_args",
    "_preflight",
    "_provider_ready",
    "_setup_workspace",
    "build_provider_ready_command",
    "check_provider_readiness",
    "render_provider_ready_report",
    "validate_public_bootstrap_environment",
]
