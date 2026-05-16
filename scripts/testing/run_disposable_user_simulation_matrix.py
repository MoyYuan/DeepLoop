from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "local" / "disposable-user-simulation"
DEFAULT_MANAGED_SANDBOX_TTL_HOURS = 24.0
DEFAULT_MANAGED_SANDBOX_CLEANUP_POLICY = "delete"
MANAGED_SANDBOX_ENV = "DEEPLOOP_DISPOSABLE_SIM_USE_MANAGED_SANDBOX"
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}

from deeploop.core.structured_io import write_json_object, write_markdown
from deeploop.testing.disposable_user_simulation import (
    DEFAULT_MATRIX_PATH,
    build_scenario_contract,
    load_disposable_user_simulation_matrix,
    materialize_scenario_workspace,
    render_outer_user_prompt,
    render_scenario_contract_markdown,
    runtime_constraints_payload,
    select_scenarios,
)


class ManagedSandboxContext:
    def __init__(self, *, manager_path: Path, registry_root: Path | None, manifest: dict[str, Any]) -> None:
        self.manager_path = manager_path
        self.registry_root = registry_root
        self.manifest = manifest


def _volume_arg(source: Path, target: str, *, read_only: bool = False) -> str:
    suffix = ":ro" if read_only else ""
    return f"{source.resolve()}:{target}{suffix}"


def _resolve_host_copilot_mounts(
    *,
    enabled: bool,
    home: Path | None = None,
) -> list[dict[str, object]]:
    if not enabled:
        return []
    host_home = (home or Path.home()).expanduser().resolve()
    copilot_binary = shutil.which("copilot")
    if not copilot_binary:
        raise FileNotFoundError("`--mount-host-copilot` requires a host `copilot` binary on PATH.")
    gh_config = host_home / ".config" / "gh"
    if not gh_config.is_dir():
        raise FileNotFoundError(
            "`--mount-host-copilot` requires host GitHub CLI auth/config at ~/.config/gh."
        )
    mounts: list[dict[str, object]] = [
        {
            "source": str(Path(copilot_binary).expanduser().resolve()),
            "target": "/usr/local/bin/copilot",
            "read_only": True,
            "kind": "binary",
        },
        {
            "source": str(gh_config),
            "target": "/home/deeploop/.config/gh",
            "read_only": True,
            "kind": "config",
        },
    ]
    copilot_home = host_home / ".copilot"
    if copilot_home.exists():
        mounts.append(
            {
                "source": str(copilot_home),
                "target": "/home/deeploop/.copilot",
                "read_only": False,
                "kind": "copilot-home",
            }
        )
    return mounts


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _campaign_id(explicit: str | None) -> str:
    return explicit or f"disposable-user-simulation-{_utc_stamp()}"


def _default_output_root(campaign_id: str) -> Path:
    return DEFAULT_OUTPUT_ROOT / campaign_id


def _env_flag_enabled(value: str | None) -> bool:
    return value is not None and value.strip().lower() in TRUTHY_ENV_VALUES


def _managed_sandbox_requested(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "managed_sandbox", False) or _env_flag_enabled(os.environ.get(MANAGED_SANDBOX_ENV)))


def _default_sandbox_manager_path() -> Path:
    return REPO_ROOT.parent / "system-scripts" / "sandbox_manager.py"


def _resolve_sandbox_manager_path(override: str | None) -> Path:
    candidate = Path(override).expanduser().resolve() if override else _default_sandbox_manager_path().resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f"Sandbox manager not found: {candidate}")
    return candidate


def _run_sandbox_manager_json(
    manager_path: Path,
    command: list[str],
    *,
    registry_root: Path | None = None,
) -> dict[str, Any]:
    env = dict(os.environ)
    if registry_root is not None:
        env["SANDBOX_REGISTRY_ROOT"] = str(registry_root)
    result = subprocess.run(
        [sys.executable, str(manager_path), *command, "--json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or f"sandbox manager exited with {result.returncode}"
        raise RuntimeError(f"Sandbox manager command failed: {details}")
    return json.loads(result.stdout)


def _managed_sandbox_summary(context: ManagedSandboxContext) -> dict[str, Any]:
    manifest = context.manifest
    integrity = manifest.get("integrity", {})
    return {
        "id": manifest["id"],
        "path": manifest["path"],
        "state": manifest["state"],
        "purpose": manifest["purpose"],
        "type": manifest["type"],
        "expires_at": manifest["expires_at"],
        "cleanup_policy": manifest["cleanup_policy"],
        "manifest_path": integrity.get("manifest_path"),
        "registry_root": integrity.get("registry_root"),
        "manager_path": str(context.manager_path),
    }


def _add_managed_sandbox_metadata(
    payload: dict[str, object],
    managed_sandbox: ManagedSandboxContext | None,
) -> dict[str, object]:
    if managed_sandbox is not None:
        payload["managed_sandbox"] = _managed_sandbox_summary(managed_sandbox)
    return payload


def _prepare_campaign_output_root(
    *,
    args: argparse.Namespace,
    campaign_id: str,
) -> tuple[Path, ManagedSandboxContext | None]:
    requested_output_root = Path(args.output_root).expanduser().resolve() if args.output_root else None
    if not _managed_sandbox_requested(args):
        output_root = requested_output_root or _default_output_root(campaign_id)
        output_root.mkdir(parents=True, exist_ok=True)
        return output_root, None

    manager_path = _resolve_sandbox_manager_path(getattr(args, "sandbox_manager", None))
    registry_root = (
        Path(args.sandbox_registry_root).expanduser().resolve()
        if getattr(args, "sandbox_registry_root", None)
        else None
    )
    create_command = [
        "create",
        "--repo",
        "deeploop",
        "--purpose",
        "disposable user simulation",
        "--type",
        "validation",
        "--cleanup-policy",
        args.sandbox_cleanup_policy,
        "--ttl-hours",
        str(args.sandbox_ttl_hours),
    ]
    if requested_output_root is not None:
        create_command.extend(["--path", str(requested_output_root)])
    manifest = _run_sandbox_manager_json(manager_path, create_command, registry_root=registry_root)
    output_root = Path(manifest["path"]).resolve()
    if not output_root.is_dir():
        raise RuntimeError(f"Managed sandbox path was not created: {output_root}")
    return output_root, ManagedSandboxContext(manager_path=manager_path, registry_root=registry_root, manifest=manifest)


def _sanitize_tag_suffix(raw: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", raw.lower()).strip("-") or "simulation"


def _sanitize_container_name(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw).strip("-")[:63] or "deeploop-simulation"


def _build_image_tag(image_prefix: str, campaign_id: str) -> str:
    return f"{image_prefix}:{_sanitize_tag_suffix(campaign_id)}"


def _build_docker_image(
    *,
    docker_bin: str,
    dockerfile: Path,
    build_target: str,
    image_tag: str,
    pull: bool,
) -> None:
    command = [
        docker_bin,
        "build",
        "--file",
        str(dockerfile),
        "--target",
        build_target,
        "--tag",
        image_tag,
    ]
    if pull:
        command.append("--pull")
    command.append(str(REPO_ROOT))
    print(f"+ {shlex.join(command)}", flush=True)
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def _start_container(
    *,
    docker_bin: str,
    image_tag: str,
    container_name: str,
    workspace_root: Path,
    artifacts_root: Path,
    container_workspace_root: str,
    container_artifacts_root: str,
    extra_mounts: list[dict[str, object]] | None = None,
) -> None:
    command = [
        docker_bin,
        "run",
        "--detach",
        "--rm",
        "--name",
        container_name,
        "--volume",
        f"{workspace_root}:{container_workspace_root}",
        "--volume",
        f"{artifacts_root}:{container_artifacts_root}",
    ]
    for mount in extra_mounts or []:
        source = Path(str(mount["source"])).expanduser().resolve()
        target = str(mount["target"])
        read_only = bool(mount.get("read_only", False))
        command.extend(["--volume", _volume_arg(source, target, read_only=read_only)])
    command.extend([image_tag, "sleep", "infinity"])
    print(f"+ {shlex.join(command)}", flush=True)
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def _stop_container(*, docker_bin: str, container_name: str) -> None:
    command = [docker_bin, "stop", container_name]
    subprocess.run(command, cwd=REPO_ROOT, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _write_yaml(path: Path, payload: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_campaign_summary(campaign_root: Path, summary: dict[str, object]) -> None:
    write_json_object(campaign_root / "campaign_summary.json", summary)
    scenario_summaries = summary.get("scenarios") if isinstance(summary.get("scenarios"), list) else []
    lines = [
        "# Disposable user simulation campaign",
        "",
        f"- campaign_id: `{summary.get('campaign_id')}`",
        f"- status: `{summary.get('status')}`",
        f"- minimum_session_seconds: `{summary.get('minimum_session_seconds')}`",
        f"- sequential_execution: `{summary.get('sequential_execution')}`",
        f"- image_tag: `{summary.get('image_tag')}`",
        "",
        "## Scenario results",
        "",
    ]
    for scenario in scenario_summaries:
        if not isinstance(scenario, dict):
            continue
        lines.append(
            f"- `{scenario.get('scenario_id')}` — `{scenario.get('status')}` "
            f"(elapsed={scenario.get('elapsed_seconds')}, container={scenario.get('container_name')})"
        )
    write_markdown(campaign_root / "campaign_summary.md", lines)


def _run_simulator_command(
    command: list[str],
    *,
    scenario_root: Path,
    env: dict[str, str],
    minimum_session_seconds: int,
) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed = time.monotonic() - started
    (scenario_root / "simulator.stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (scenario_root / "simulator.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if elapsed < minimum_session_seconds:
        raise RuntimeError(
            f"Simulator command ended after {elapsed:.1f}s; minimum required duration is {minimum_session_seconds}s."
        )
    if completed.returncode != 0:
        raise RuntimeError(f"Simulator command exited {completed.returncode}.")
    return completed, elapsed


def _scenario_runtime_pins_yaml(contract: dict[str, object]) -> dict[str, object]:
    runtime_constraints = (
        contract.get("runtime_constraints") if isinstance(contract.get("runtime_constraints"), dict) else {}
    )
    return {
        "runtime_constraints": runtime_constraints,
        "recommended_commands": contract.get("recommended_commands") or [],
    }


def _run_scenario(
    *,
    docker_bin: str,
    image_tag: str,
    campaign_id: str,
    scenario_root: Path,
    scenario: object,
    matrix: object,
    simulator_command: list[str] | None,
    prepare_only: bool,
    host_copilot_mount: bool,
) -> dict[str, object]:
    from deeploop.testing.disposable_user_simulation import DisposableUserSimulationScenario, DisposableUserSimulationMatrix

    if not isinstance(matrix, DisposableUserSimulationMatrix):
        raise TypeError("matrix must be a DisposableUserSimulationMatrix")
    if not isinstance(scenario, DisposableUserSimulationScenario):
        raise TypeError("scenario must be a DisposableUserSimulationScenario")

    workspace_root = scenario_root / "workspace"
    artifacts_root = scenario_root / "artifacts"
    prompts_root = scenario_root / "prompts"
    workspace_root.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    prompts_root.mkdir(parents=True, exist_ok=True)

    materialize_scenario_workspace(matrix, scenario, workspace_root=workspace_root)
    container_mounts = _resolve_host_copilot_mounts(enabled=host_copilot_mount)

    container_name = _sanitize_container_name(f"{campaign_id}-{scenario.scenario_id}")
    contract = build_scenario_contract(
        matrix,
        scenario,
        campaign_id=campaign_id,
        container_name=container_name,
    )
    contract_path = scenario_root / "scenario_contract.json"
    write_json_object(contract_path, contract)
    write_markdown(scenario_root / "scenario_contract.md", render_scenario_contract_markdown(contract))
    _write_yaml(scenario_root / "deeploop_runtime_pins.yaml", _scenario_runtime_pins_yaml(contract))
    write_json_object(scenario_root / "container_mounts.json", {"container_mounts": container_mounts})
    write_markdown(prompts_root / "outer_user_prompt.md", render_outer_user_prompt(matrix, scenario, contract))

    if prepare_only:
        summary = {
            "scenario_id": scenario.scenario_id,
            "status": "prepared",
            "container_name": container_name,
            "elapsed_seconds": 0.0,
            "contract_path": str(contract_path),
            "container_mounts": container_mounts,
        }
        write_json_object(scenario_root / "scenario_summary.json", summary)
        write_markdown(
            scenario_root / "scenario_summary.md",
            [
                f"# Scenario summary: {scenario.scenario_id}",
                "",
                "- status: `prepared`",
                f"- contract: `{contract_path}`",
            ],
        )
        return summary

    if not simulator_command:
        raise ValueError("A simulator command is required unless --prepare-only is set.")

    started_at = datetime.now(timezone.utc).isoformat()
    elapsed_seconds = 0.0
    container_started = False
    failures: list[str] = []
    try:
        _start_container(
            docker_bin=docker_bin,
            image_tag=image_tag,
            container_name=container_name,
            workspace_root=workspace_root.resolve(),
            artifacts_root=artifacts_root.resolve(),
            container_workspace_root=str(matrix.docker.workspace_root),
            container_artifacts_root=str(matrix.docker.artifacts_root),
            extra_mounts=container_mounts,
        )
        container_started = True

        env = dict(os.environ)
        env.update(
            {
                "DEEPLOOP_SIM_CAMPAIGN_ID": campaign_id,
                "DEEPLOOP_SIM_SCENARIO_ID": scenario.scenario_id,
                "DEEPLOOP_SIM_CONTAINER_NAME": container_name,
                "DEEPLOOP_SIM_CONTRACT_PATH": str(contract_path),
                "DEEPLOOP_SIM_PROMPT_PATH": str(prompts_root / "outer_user_prompt.md"),
                "DEEPLOOP_SIM_RUNTIME_PINS_PATH": str(scenario_root / "deeploop_runtime_pins.yaml"),
                "DEEPLOOP_SIM_WORKSPACE_ROOT": str(matrix.docker.workspace_root),
                "DEEPLOOP_SIM_ARTIFACTS_ROOT": str(matrix.docker.artifacts_root),
                "DEEPLOOP_SIM_MIN_SESSION_SECONDS": str(matrix.minimum_session_seconds),
            }
        )
        _, elapsed_seconds = _run_simulator_command(
            simulator_command,
            scenario_root=scenario_root,
            env=env,
            minimum_session_seconds=matrix.minimum_session_seconds,
        )
        status = "passed"
    except Exception as exc:
        failures.append(str(exc))
        status = "failed"
    finally:
        if container_started:
            _stop_container(docker_bin=docker_bin, container_name=container_name)

    ended_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "scenario_id": scenario.scenario_id,
        "status": status,
        "container_name": container_name,
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "failures": failures,
        "contract_path": str(contract_path),
        "container_mounts": container_mounts,
    }
    write_json_object(scenario_root / "scenario_summary.json", summary)
    lines = [
        f"# Scenario summary: {scenario.scenario_id}",
        "",
        f"- status: `{status}`",
        f"- container_name: `{container_name}`",
        f"- elapsed_seconds: `{round(elapsed_seconds, 3)}`",
        f"- contract: `{contract_path}`",
    ]
    if failures:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in failures)
    write_markdown(scenario_root / "scenario_summary.md", lines)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the disposable Docker user-simulation matrix sequentially with a pluggable external simulator command.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--matrix-config", default=str(DEFAULT_MATRIX_PATH), help="Path to the matrix config.")
    parser.add_argument("--campaign-id", help="Optional campaign id override.")
    parser.add_argument("--output-root", help="Optional output root override. With --managed-sandbox, this becomes the tracked sandbox path.")
    parser.add_argument("--docker-bin", default="docker", help="Docker-compatible CLI to invoke.")
    parser.add_argument("--no-pull", action="store_true", help="Skip docker build --pull.")
    parser.add_argument("--skip-build", action="store_true", help="Reuse an existing image tag instead of building a new image.")
    parser.add_argument("--image-tag", help="Optional image tag override.")
    parser.add_argument("--scenario", action="append", default=[], help="Scenario id to run. Repeat to select multiple scenarios.")
    parser.add_argument(
        "--mount-host-copilot",
        action="store_true",
        help=(
            "Explicitly mount the host Copilot binary plus ~/.config/gh and optional ~/.copilot "
            "into the disposable container so in-container Copilot-backed DeepLoop flows can run. "
            "~/.copilot is mounted read-write so Copilot can persist session-state."
        ),
    )
    parser.add_argument("--prepare-only", action="store_true", help="Only materialize scenario bundles; do not build images, start containers, or run a simulator command.")
    parser.add_argument(
        "--managed-sandbox",
        action="store_true",
        help="Track the campaign output root with the shared sandbox manager.",
    )
    parser.add_argument(
        "--sandbox-manager",
        help="Path to system-scripts/sandbox_manager.py. Defaults to ../system-scripts relative to the repo root.",
    )
    parser.add_argument(
        "--sandbox-registry-root",
        help="Override SANDBOX_REGISTRY_ROOT for managed sandbox metadata and storage.",
    )
    parser.add_argument(
        "--sandbox-ttl-hours",
        type=float,
        default=DEFAULT_MANAGED_SANDBOX_TTL_HOURS,
        help="TTL for managed disposable-user-simulation sandboxes before reap-stale can remove them.",
    )
    parser.add_argument(
        "--sandbox-cleanup-policy",
        choices=("delete", "archive", "manual"),
        default=DEFAULT_MANAGED_SANDBOX_CLEANUP_POLICY,
        help="Cleanup policy recorded for managed disposable-user-simulation sandboxes.",
    )
    parser.add_argument(
        "--simulator-command",
        nargs=argparse.REMAINDER,
        help=(
            "Host-side simulator command to run for each scenario. Put this option last. "
            "Example: python scripts/testing/run_disposable_user_simulation_outer_user.py"
        ),
    )
    args = parser.parse_args(argv)

    if shutil.which(args.docker_bin) is None and not args.prepare_only:
        print(f"disposable-user-simulation: required CLI `{args.docker_bin}` was not found on PATH", file=sys.stderr)
        return 2

    matrix = load_disposable_user_simulation_matrix(Path(args.matrix_config))
    scenarios = select_scenarios(matrix, list(args.scenario))
    campaign_id = _campaign_id(args.campaign_id)
    output_root, managed_sandbox = _prepare_campaign_output_root(args=args, campaign_id=campaign_id)
    if managed_sandbox is not None:
        write_json_object(output_root / "metadata" / "managed-sandbox.json", managed_sandbox.manifest)

    image_tag = args.image_tag or _build_image_tag(matrix.docker.image_prefix, campaign_id)
    if not args.prepare_only and not args.skip_build:
        _build_docker_image(
            docker_bin=args.docker_bin,
            dockerfile=matrix.docker.dockerfile,
            build_target=matrix.docker.build_target,
            image_tag=image_tag,
            pull=not args.no_pull,
        )

    scenario_summaries: list[dict[str, object]] = []
    for scenario in scenarios:
        scenario_root = output_root / scenario.scenario_id
        scenario_root.mkdir(parents=True, exist_ok=True)
        scenario_summaries.append(
            _run_scenario(
                docker_bin=args.docker_bin,
                image_tag=image_tag,
                campaign_id=campaign_id,
                scenario_root=scenario_root,
                scenario=scenario,
                matrix=matrix,
                simulator_command=list(args.simulator_command or []),
                prepare_only=bool(args.prepare_only),
                host_copilot_mount=bool(args.mount_host_copilot),
            )
        )

    status = "passed"
    if any(summary.get("status") == "failed" for summary in scenario_summaries):
        status = "failed"
    elif all(summary.get("status") == "prepared" for summary in scenario_summaries):
        status = "prepared"

    campaign_summary = {
        "campaign_id": campaign_id,
        "status": status,
        "contract_id": matrix.contract_id,
        "minimum_session_seconds": matrix.minimum_session_seconds,
        "sequential_execution": matrix.sequential_execution,
        "image_tag": image_tag,
        "runtime_constraints": runtime_constraints_payload(matrix),
        "scenarios": scenario_summaries,
    }
    _add_managed_sandbox_metadata(campaign_summary, managed_sandbox)
    _write_campaign_summary(output_root, campaign_summary)
    return 1 if status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
