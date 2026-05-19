from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from deeploop.core.structured_io import write_json_object, write_markdown, write_text
from deeploop.runtime.copilot_adapter import build_copilot_prompt_command

DEFAULT_OUTER_USER_MODEL = "gpt-5-mini"
_PHASE_NAMES = ("opening", "midpoint", "closing")


@dataclass(frozen=True)
class DisposableUserSimulationInputs:
    campaign_id: str
    scenario_id: str
    container_name: str
    scenario_root: Path
    prompt_path: Path
    contract_path: Path
    runtime_pins_path: Path
    workspace_root: str
    artifacts_root: str
    minimum_session_seconds: int


def _require_env(env: Mapping[str, str], key: str) -> str:
    value = str(env.get(key, "")).strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


def load_disposable_user_simulation_inputs(env: Mapping[str, str] | None = None) -> DisposableUserSimulationInputs:
    resolved_env = os.environ if env is None else env
    contract_path = Path(_require_env(resolved_env, "DEEPLOOP_SIM_CONTRACT_PATH")).expanduser().resolve()
    prompt_path = Path(_require_env(resolved_env, "DEEPLOOP_SIM_PROMPT_PATH")).expanduser().resolve()
    runtime_pins_path = Path(_require_env(resolved_env, "DEEPLOOP_SIM_RUNTIME_PINS_PATH")).expanduser().resolve()
    minimum_session_seconds = int(_require_env(resolved_env, "DEEPLOOP_SIM_MIN_SESSION_SECONDS"))
    scenario_root = contract_path.parent
    return DisposableUserSimulationInputs(
        campaign_id=_require_env(resolved_env, "DEEPLOOP_SIM_CAMPAIGN_ID"),
        scenario_id=_require_env(resolved_env, "DEEPLOOP_SIM_SCENARIO_ID"),
        container_name=_require_env(resolved_env, "DEEPLOOP_SIM_CONTAINER_NAME"),
        scenario_root=scenario_root,
        prompt_path=prompt_path,
        contract_path=contract_path,
        runtime_pins_path=runtime_pins_path,
        workspace_root=_require_env(resolved_env, "DEEPLOOP_SIM_WORKSPACE_ROOT"),
        artifacts_root=_require_env(resolved_env, "DEEPLOOP_SIM_ARTIFACTS_ROOT"),
        minimum_session_seconds=minimum_session_seconds,
    )


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML mapping at {path}")
    return payload


def _runtime_pins_runtime_constraints(runtime_pins: dict[str, Any]) -> dict[str, Any]:
    constraints = runtime_pins.get("runtime_constraints")
    if not isinstance(constraints, dict):
        raise ValueError("Runtime pins file must contain a runtime_constraints mapping.")
    return constraints


def _validate_runtime_pins(contract: dict[str, Any], runtime_pins: dict[str, Any], *, model: str) -> None:
    runtime_constraints = _runtime_pins_runtime_constraints(runtime_pins)
    contract_constraints = contract.get("runtime_constraints")
    if not isinstance(contract_constraints, dict):
        raise ValueError("Scenario contract must contain runtime_constraints.")
    outer_user = runtime_constraints.get("outer_user_simulator")
    if not isinstance(outer_user, dict) or outer_user.get("model_alias") != model:
        raise ValueError("Runtime pins do not preserve the outer user simulator model alias.")
    contract_control = contract_constraints.get("deeploop_control_plane")
    runtime_control = runtime_constraints.get("deeploop_control_plane")
    if not isinstance(contract_control, dict) or not isinstance(runtime_control, dict):
        raise ValueError("Runtime pins are missing deeploop_control_plane constraints.")
    contract_control_model = contract_control.get("model") if isinstance(contract_control.get("model"), dict) else {}
    runtime_control_model = runtime_control.get("model") if isinstance(runtime_control.get("model"), dict) else {}
    if contract_control_model.get("alias") != runtime_control_model.get("alias"):
        raise ValueError("Runtime pins do not preserve the DeepLoop control-plane model alias.")
    contract_experiment = contract_constraints.get("deeploop_experiment_execution")
    runtime_experiment = runtime_constraints.get("deeploop_experiment_execution")
    if not isinstance(contract_experiment, dict) or not isinstance(runtime_experiment, dict):
        raise ValueError("Runtime pins are missing deeploop_experiment_execution constraints.")
    contract_experiment_model = (
        contract_experiment.get("model") if isinstance(contract_experiment.get("model"), dict) else {}
    )
    runtime_experiment_model = (
        runtime_experiment.get("model") if isinstance(runtime_experiment.get("model"), dict) else {}
    )
    if contract_experiment_model.get("identifier") != runtime_experiment_model.get("identifier"):
        raise ValueError("Runtime pins do not preserve the DeepLoop experiment model identifier.")


def _phase_target_seconds(minimum_session_seconds: int, phase_index: int, phase_count: int) -> int:
    if phase_count < 2:
        raise ValueError("phase_count must be at least 2")
    if phase_index < 0 or phase_index >= phase_count:
        raise ValueError("phase_index is out of range")
    if phase_index == 0:
        return 0
    if phase_index == phase_count - 1:
        return minimum_session_seconds
    return int(round(minimum_session_seconds * phase_index / (phase_count - 1)))


def build_phase_prompt(
    inputs: DisposableUserSimulationInputs,
    *,
    phase_index: int,
    phase_count: int,
    phase_name: str,
    previous_transcript: str,
    prompt_text: str,
    contract_text: str,
    runtime_pins_text: str,
) -> str:
    target_offset = _phase_target_seconds(inputs.minimum_session_seconds, phase_index, phase_count)
    phase_artifacts_root = inputs.scenario_root / "artifacts" / "outer-user-simulation" / "phase-notes"
    phase_note_path = phase_artifacts_root / f"{phase_index + 1:02d}-{phase_name}.md"
    lines = [
        f"# Disposable user simulation phase: {phase_name}",
        "",
        f"You are the outer user for `{inputs.scenario_id}` on phase `{phase_index + 1}/{phase_count}`.",
        "Stay on the user side, use host-side shell commands when needed, and keep the response grounded in the provided artifacts.",
        "",
        "## Session metadata",
        "",
        f"- campaign_id: `{inputs.campaign_id}`",
        f"- container_name: `{inputs.container_name}`",
        f"- minimum_session_seconds: `{inputs.minimum_session_seconds}`",
        f"- scheduled_offset_seconds: `{target_offset}`",
        f"- workspace_root: `{inputs.workspace_root}`",
        f"- artifacts_root: `{inputs.artifacts_root}`",
        "",
        "## Required behavior",
        "",
        f"- outer user simulator model: `{DEFAULT_OUTER_USER_MODEL}`",
        "- keep the simulated user on the host side",
        "- use shell commands on the host to interact with the disposable Docker container when progressing the scenario",
        f"- target container: `{inputs.container_name}`",
        "- prefer `docker exec <container> bash -lc '<command>'` for work inside the container",
        (
            "- if the contract includes a concrete `project_root` and a matching "
            "`deeploop run --project-root ... --until-complete` command, use that "
            "exact command before trying `deeploop run --until-complete` or other "
            "discovery-style fallbacks"
        ),
        "- do not change the pinned DeepLoop lanes",
        "- actually exercise the documented DeepLoop flow instead of writing a purely fictional transcript",
        f"- write a durable phase note to `{phase_note_path}` summarizing what you tried, what happened, and what the user would do next",
        "- keep any host-side artifacts under the scenario root rather than writing outside the prepared campaign bundle",
        "",
        "## Scenario prompt",
        "",
        prompt_text.strip(),
        "",
        "## Scenario contract",
        "",
        contract_text.strip(),
        "",
        "## Runtime pins",
        "",
        runtime_pins_text.strip(),
        "",
        "## Prior phase transcript",
        "",
        previous_transcript.strip() or "(none)",
        "",
        "## Phase task",
        "",
        "Act as the outer user for this phase.",
        "Run the host-side commands you need, including Docker-based interaction with the scenario container and the recommended DeepLoop commands when appropriate.",
        "Then provide a concise in-character turn plus any blockers or next steps you observed.",
    ]
    return "\n".join(lines)


def _build_copilot_command(prompt_text: str, *, add_dir: Path, model: str) -> list[str]:
    return build_copilot_prompt_command(
        prompt_text,
        add_dirs=(add_dir,),
        model=model,
        allow_all=True,
        no_ask_user=True,
        output_format="text",
    )


def _wait_until(
    started_at: float,
    target_offset: int,
    *,
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
) -> None:
    remaining = target_offset - (clock() - started_at)
    if remaining > 0:
        sleeper(remaining)


def run_disposable_user_simulation(
    inputs: DisposableUserSimulationInputs,
    *,
    model: str = DEFAULT_OUTER_USER_MODEL,
    phase_count: int = 3,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    contract = _load_json(inputs.contract_path)
    runtime_pins = _load_yaml(inputs.runtime_pins_path)
    _validate_runtime_pins(contract, runtime_pins, model=model)
    prompt_text = inputs.prompt_path.read_text(encoding="utf-8")
    contract_text = json.dumps(contract, indent=2, sort_keys=False)
    runtime_pins_text = yaml.safe_dump(runtime_pins, sort_keys=False)

    expected_outer_model = (
        contract.get("runtime_constraints", {})
        if isinstance(contract.get("runtime_constraints"), dict)
        else {}
    ).get("outer_user_simulator", {})
    expected_outer_model_alias = (
        expected_outer_model.get("model_alias") if isinstance(expected_outer_model, dict) else None
    )
    if expected_outer_model_alias and expected_outer_model_alias != model:
        raise ValueError(
            f"Outer user simulator model mismatch: contract expects `{expected_outer_model_alias}` but wrapper is pinned to `{model}`."
        )

    run_root = inputs.scenario_root / "artifacts" / "outer-user-simulation"
    run_root.mkdir(parents=True, exist_ok=True)
    phase_root = run_root / "phases"
    phase_root.mkdir(parents=True, exist_ok=True)

    write_json_object(
        run_root / "inputs.json",
        {
            "campaign_id": inputs.campaign_id,
            "scenario_id": inputs.scenario_id,
            "container_name": inputs.container_name,
            "scenario_root": str(inputs.scenario_root),
            "prompt_path": str(inputs.prompt_path),
            "contract_path": str(inputs.contract_path),
            "runtime_pins_path": str(inputs.runtime_pins_path),
            "workspace_root": inputs.workspace_root,
            "artifacts_root": inputs.artifacts_root,
            "minimum_session_seconds": inputs.minimum_session_seconds,
            "model": model,
            "phase_count": phase_count,
        },
    )

    phase_names = list(_PHASE_NAMES[:phase_count]) if phase_count <= len(_PHASE_NAMES) else [
        f"phase-{index + 1}" for index in range(phase_count)
    ]
    phase_targets = [_phase_target_seconds(inputs.minimum_session_seconds, index, phase_count) for index in range(phase_count)]
    started_at = clock()
    phase_summaries: list[dict[str, Any]] = []
    transcript_sections: list[str] = [
        f"# Disposable user simulation transcript: {inputs.scenario_id}",
        "",
        f"- campaign_id: `{inputs.campaign_id}`",
        f"- container_name: `{inputs.container_name}`",
        f"- model: `{model}`",
        f"- minimum_session_seconds: `{inputs.minimum_session_seconds}`",
        "",
    ]

    previous_transcript = ""
    failure: dict[str, Any] | None = None
    for phase_index, phase_name in enumerate(phase_names):
        _wait_until(started_at, phase_targets[phase_index], clock=clock, sleeper=sleeper)
        prompt = build_phase_prompt(
            inputs,
            phase_index=phase_index,
            phase_count=phase_count,
            phase_name=phase_name,
            previous_transcript=previous_transcript,
            prompt_text=prompt_text,
            contract_text=contract_text,
            runtime_pins_text=runtime_pins_text,
        )
        command = _build_copilot_command(prompt, add_dir=inputs.scenario_root, model=model)
        phase_dir = phase_root / f"{phase_index + 1:02d}-{phase_name}"
        phase_dir.mkdir(parents=True, exist_ok=True)
        write_text(phase_dir / "prompt.md", prompt)
        write_text(phase_dir / "command.txt", shlex.join(command))
        phase_started = clock()
        completed = runner(
            command,
            cwd=inputs.scenario_root,
            check=False,
            capture_output=True,
            text=True,
        )
        phase_elapsed = clock() - phase_started
        write_text(phase_dir / "stdout.txt", completed.stdout)
        write_text(phase_dir / "stderr.txt", completed.stderr)
        phase_record = {
            "phase_index": phase_index + 1,
            "phase_name": phase_name,
            "target_offset_seconds": phase_targets[phase_index],
            "elapsed_seconds": round(phase_elapsed, 3),
            "returncode": completed.returncode,
            "stdout_path": str(phase_dir / "stdout.txt"),
            "stderr_path": str(phase_dir / "stderr.txt"),
        }
        write_json_object(phase_dir / "phase.json", phase_record)
        phase_summaries.append(phase_record)

        transcript_sections.extend(
            [
                f"## Phase {phase_index + 1}: {phase_name}",
                "",
                "### Prompt",
                "",
                "```text",
                prompt,
                "```",
                "",
                "### Output",
                "",
                "```text",
                completed.stdout.strip() or "(no stdout)",
                "```",
                "",
                f"### Return code: `{completed.returncode}`",
                "",
            ]
        )
        previous_transcript = completed.stdout.strip() or previous_transcript
        if completed.returncode != 0:
            failure = {
                "phase_index": phase_index + 1,
                "phase_name": phase_name,
                "returncode": completed.returncode,
                "message": f"Copilot exited {completed.returncode} during phase `{phase_name}`.",
            }
            break

    _wait_until(started_at, inputs.minimum_session_seconds, clock=clock, sleeper=sleeper)
    elapsed_seconds = clock() - started_at
    summary = {
        "status": "failed" if failure is not None else "passed",
        "campaign_id": inputs.campaign_id,
        "scenario_id": inputs.scenario_id,
        "container_name": inputs.container_name,
        "model": model,
        "minimum_session_seconds": inputs.minimum_session_seconds,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "phase_count": phase_count,
        "phase_targets": phase_targets,
        "phases": phase_summaries,
    }
    if failure is not None:
        summary["failure"] = failure
    write_json_object(run_root / "summary.json", summary)
    write_markdown(run_root / "transcript.md", transcript_sections)
    if failure is not None:
        raise RuntimeError(str(failure["message"]))
    return summary


def main(argv: list[str] | None = None) -> int:
    del argv
    inputs = load_disposable_user_simulation_inputs()
    summary = run_disposable_user_simulation(inputs)
    print(json.dumps(summary, indent=2))
    return 0


__all__ = [
    "DEFAULT_OUTER_USER_MODEL",
    "DisposableUserSimulationInputs",
    "build_phase_prompt",
    "load_disposable_user_simulation_inputs",
    "run_disposable_user_simulation",
]
