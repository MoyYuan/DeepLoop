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

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

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
    parser.add_argument("--output-root", help="Optional output root override.")
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
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else REPO_ROOT / "reports" / "disposable-user-simulation" / campaign_id
    )
    output_root.mkdir(parents=True, exist_ok=True)

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
    _write_campaign_summary(output_root, campaign_summary)
    return 1 if status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
