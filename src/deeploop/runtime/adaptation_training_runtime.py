from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from deeploop.autonomy.gate_taxonomy import build_gate_event, load_gate_policy
from deeploop.core.ledger import now_utc
from deeploop.core.paths import REPO_ROOT
from deeploop.core.shared import build_command as _build_command
from deeploop.core.structured_io import load_json_object, write_json_object
from deeploop.runtime.metric_ratchets import (
    MetricRatchetConfig,
    build_metric_ratchet_decision,
    metric_map,
)

DEFAULT_GATES_PATH = REPO_ROOT / "configs" / "autonomy" / "gates.yaml"
_SUPPORTED_TRAINING_KINDS = {"lora", "sft-lora", "qlora"}
_PRODUCED_OUTPUTS = [
    "adapted artifact",
    "post-adaptation evaluation",
    "keep/discard adaptation comparison",
]

def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded

def _write_markdown(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def _resolve_path(base_dir: Path, value: str | Path | None, *, default: Path | None = None) -> Path | None:
    if value is None:
        return default
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()

def _normalize_command(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        return tuple(shlex.split(raw))
    if isinstance(raw, (list, tuple)):
        command = tuple(str(item) for item in raw if str(item).strip())
        if command:
            return command
    raise ValueError("Expected a non-empty command.")

@dataclass(frozen=True)
class AdaptationCommand:
    command: tuple[str, ...]
    work_dir: Path
    env_name: str | None
    timeout_seconds: int | None

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        *,
        repo_root: Path,
        default_timeout_seconds: int,
    ) -> "AdaptationCommand":
        work_dir = _resolve_path(repo_root, raw.get("work_dir"), default=repo_root)
        if work_dir is None:
            raise ValueError("adaptation training command requires a non-null work_dir")
        timeout_seconds = raw.get("timeout_seconds")
        if timeout_seconds is None:
            resolved_timeout = default_timeout_seconds
        else:
            resolved_timeout = int(timeout_seconds)
        return cls(
            command=_normalize_command(raw.get("command")),
            work_dir=work_dir,
            env_name=(str(raw.get("env_name")).strip() if raw.get("env_name") is not None else None) or None,
            timeout_seconds=max(resolved_timeout, 1),
        )

@dataclass(frozen=True)
class AdaptationTrainingConfig:
    config_path: Path
    mission_state_path: Path | None
    branch_id: str
    objective: str
    training_kind: str
    repo_root: Path
    output_root: Path
    max_runtime_hours: float
    gpu_count: int
    baseline_metrics_path: Path
    intervention_metrics_path: Path | None
    adapter_artifact_path: Path
    evaluation_metrics_path: Path
    train: AdaptationCommand
    evaluate: AdaptationCommand
    comparison: MetricRatchetConfig

    @classmethod
    def load(
        cls,
        config_path: Path,
        *,
        mission_state_path: Path | None = None,
    ) -> "AdaptationTrainingConfig":
        resolved_config_path = config_path.expanduser().resolve()
        raw = _load_yaml(resolved_config_path)
        runtime_cfg = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
        base_dir = resolved_config_path.parent
        resolved_mission_state_path = mission_state_path.expanduser().resolve() if mission_state_path is not None else None
        repo_root = _resolve_path(base_dir, runtime_cfg.get("repo_root"), default=REPO_ROOT.resolve())
        if repo_root is None:
            raise ValueError("adaptation training config requires a non-null repo_root")
        output_default = (
            resolved_mission_state_path.parent / "adaptation_training" / resolved_config_path.stem
            if resolved_mission_state_path is not None
            else base_dir / f"{resolved_config_path.stem}_runtime"
        )
        output_root = _resolve_path(base_dir, runtime_cfg.get("output_root"), default=output_default)
        if output_root is None:
            raise ValueError("adaptation training config requires a non-null output_root")
        branch_id = str(raw.get("branch_id") or resolved_config_path.stem).strip()
        objective = str(raw.get("objective") or "Run a bounded local adaptation branch.").strip()
        training_kind = str(raw.get("training_kind") or "").strip().lower()
        if not training_kind:
            raise ValueError("training_kind is required.")
        max_runtime_hours = float(runtime_cfg.get("max_runtime_hours", 1.0) or 1.0)
        gpu_count = int(runtime_cfg.get("gpu_count", 1) or 1)
        if max_runtime_hours <= 0:
            raise ValueError("runtime.max_runtime_hours must be positive.")
        artifacts_cfg = raw.get("artifacts")
        if not isinstance(artifacts_cfg, dict):
            raise ValueError("artifacts mapping is required.")
        comparison_cfg = raw.get("metric_ratchet")
        if not isinstance(comparison_cfg, dict):
            comparison_cfg = raw.get("comparison")
        if not isinstance(comparison_cfg, dict):
            raise ValueError("comparison or metric_ratchet mapping is required.")
        budget_seconds = max(int(max_runtime_hours * 3600), 1)
        train_cfg = raw.get("train")
        eval_cfg = raw.get("evaluate")
        if not isinstance(train_cfg, dict) or not isinstance(eval_cfg, dict):
            raise ValueError("train and evaluate mappings are required.")
        baseline_metrics_path = _resolve_path(base_dir, artifacts_cfg.get("baseline_metrics_path"))
        adapter_artifact_path = _resolve_path(output_root, artifacts_cfg.get("adapter_artifact_path"))
        evaluation_metrics_path = _resolve_path(output_root, artifacts_cfg.get("evaluation_metrics_path"))
        if baseline_metrics_path is None:
            raise ValueError("artifacts.baseline_metrics_path is required.")
        if adapter_artifact_path is None:
            raise ValueError("artifacts.adapter_artifact_path is required.")
        if evaluation_metrics_path is None:
            raise ValueError("artifacts.evaluation_metrics_path is required.")
        return cls(
            config_path=resolved_config_path,
            mission_state_path=resolved_mission_state_path,
            branch_id=branch_id,
            objective=objective,
            training_kind=training_kind,
            repo_root=repo_root,
            output_root=output_root,
            max_runtime_hours=max_runtime_hours,
            gpu_count=gpu_count,
            baseline_metrics_path=baseline_metrics_path,
            intervention_metrics_path=_resolve_path(base_dir, artifacts_cfg.get("intervention_metrics_path")),
            adapter_artifact_path=adapter_artifact_path,
            evaluation_metrics_path=evaluation_metrics_path,
            train=AdaptationCommand.from_mapping(train_cfg, repo_root=repo_root, default_timeout_seconds=budget_seconds),
            evaluate=AdaptationCommand.from_mapping(eval_cfg, repo_root=repo_root, default_timeout_seconds=budget_seconds),
            comparison=MetricRatchetConfig.from_mapping(comparison_cfg),
        )

def _job_path(output_root: Path, step: str) -> Path:
    return output_root / f"{step}_job.json"

def _report_paths(output_root: Path) -> tuple[Path, Path, Path]:
    return (
        output_root / "adaptation_training_report.json",
        output_root / "adaptation_training_report.md",
        output_root / "adaptation_training_comparison.json",
    )

def _log_path(output_root: Path, step: str) -> Path:
    return output_root / f"{step}.log"

def _environment(config: AdaptationTrainingConfig, *, step: str) -> dict[str, str]:
    env = dict(os.environ)
    env["DEEPLOOP_ADAPTATION_BRANCH_ID"] = config.branch_id
    env["DEEPLOOP_ADAPTATION_STEP"] = step
    env["DEEPLOOP_ADAPTATION_CONFIG_PATH"] = str(config.config_path)
    env["DEEPLOOP_ADAPTATION_RUNTIME_ROOT"] = str(config.output_root)
    env["DEEPLOOP_ADAPTATION_ADAPTER_PATH"] = str(config.adapter_artifact_path)
    env["DEEPLOOP_ADAPTATION_EVAL_METRICS_PATH"] = str(config.evaluation_metrics_path)
    env["DEEPLOOP_ADAPTATION_BASELINE_METRICS_PATH"] = str(config.baseline_metrics_path)
    if config.intervention_metrics_path is not None:
        env["DEEPLOOP_ADAPTATION_INTERVENTION_METRICS_PATH"] = str(config.intervention_metrics_path)
    if config.mission_state_path is not None:
        env["DEEPLOOP_ADAPTATION_MISSION_STATE_PATH"] = str(config.mission_state_path)
    return env

def _job_payload(
    config: AdaptationTrainingConfig,
    *,
    step: str,
    command: AdaptationCommand,
    job_path: Path,
    status: str,
    timeout_seconds: int,
    log_path: Path,
    started_at: str | None = None,
    completed_at: str | None = None,
    returncode: int | None = None,
    expected_outputs: dict[str, str] | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "step": step,
        "branch_id": config.branch_id,
        "training_kind": config.training_kind,
        "status": status,
        "repo_root": str(config.repo_root),
        "work_dir": str(command.work_dir),
        "job_path": str(job_path),
        "log_path": str(log_path),
        "command": list(command.command),
        "full_command": _build_command(command.command, command.env_name),
        "env_name": command.env_name,
        "mission_state_path": str(config.mission_state_path) if config.mission_state_path is not None else None,
        "bounded_runtime": {
            "max_runtime_hours": config.max_runtime_hours,
            "timeout_seconds": timeout_seconds,
            "gpu_count": config.gpu_count,
        },
        "expected_outputs": expected_outputs or {},
        "started_at": started_at,
        "completed_at": completed_at,
        "returncode": returncode,
        "failure_reason": failure_reason,
    }

def _execute_command(
    config: AdaptationTrainingConfig,
    *,
    step: str,
    command: AdaptationCommand,
    timeout_seconds: int,
    expected_outputs: dict[str, str],
) -> dict[str, Any]:
    job_path = _job_path(config.output_root, step)
    log_path = _log_path(config.output_root, step)
    started_at = now_utc()
    pending_payload = _job_payload(
        config,
        step=step,
        command=command,
        job_path=job_path,
        status="running",
        timeout_seconds=timeout_seconds,
        log_path=log_path,
        started_at=started_at,
        expected_outputs=expected_outputs,
    )
    write_json_object(job_path, pending_payload)
    full_command = _build_command(command.command, command.env_name)
    try:
        completed = subprocess.run(
            full_command,
            cwd=command.work_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(timeout_seconds, 1),
            env=_environment(config, step=step),
        )
        stdout = completed.stdout
        stderr = completed.stderr
        returncode = int(completed.returncode)
        status = "completed" if returncode == 0 else "failed"
        failure_reason = None if returncode == 0 else f"{step} command exited with status {returncode}."
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nTimeoutExpired: {exc}\n"
        returncode = 124
        status = "failed"
        failure_reason = f"{step} command exceeded the bounded runtime budget of {timeout_seconds} seconds."
    except (FileNotFoundError, OSError) as exc:
        stdout = ""
        stderr = f"{type(exc).__name__}: {exc}\n"
        returncode = 127
        status = "failed"
        failure_reason = f"{step} command could not start: {exc}"
    completed_at = now_utc()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(stdout + stderr, encoding="utf-8")
    payload = _job_payload(
        config,
        step=step,
        command=command,
        job_path=job_path,
        status=status,
        timeout_seconds=timeout_seconds,
        log_path=log_path,
        started_at=started_at,
        completed_at=completed_at,
        returncode=returncode,
        expected_outputs=expected_outputs,
        failure_reason=failure_reason,
    )
    write_json_object(job_path, payload)
    return payload

def _gate_event(config: AdaptationTrainingConfig, gates: dict[str, Any]) -> dict[str, Any] | None:
    if config.training_kind == "dpo":
        return build_gate_event(
            "executor-mismatch",
            "DPO/preference-optimization runs stay outside this bounded adaptation runtime and should reroute to a reviewed executor.",
            gates_policy=gates,
        )
    if config.training_kind not in _SUPPORTED_TRAINING_KINDS:
        return build_gate_event(
            "executor-mismatch",
            (
                f"Training kind `{config.training_kind}` is outside the bounded local adaptation surface; "
                f"supported kinds are {', '.join(sorted(_SUPPORTED_TRAINING_KINDS))}."
            ),
            gates_policy=gates,
        )
    if config.gpu_count != 1:
        return build_gate_event(
            "budget-overrun",
            "Adaptation runtime currently supports exactly one local GPU job at a time.",
            gates_policy=gates,
        )
    budget_controls = gates.get("budget_controls", {}) if isinstance(gates.get("budget_controls"), dict) else {}
    max_hours = float(budget_controls.get("max_single_gpu_hours_without_approval", 2) or 2)
    if config.max_runtime_hours > max_hours:
        return build_gate_event(
            "budget-overrun",
            (
                f"Configured runtime budget of {config.max_runtime_hours:g} hours exceeds the "
                f"autonomous limit of {max_hours:g} hours."
            ),
            gates_policy=gates,
        )
    if not config.baseline_metrics_path.exists():
        return build_gate_event(
            "quality-shortfall",
            f"Baseline metrics file does not exist: {config.baseline_metrics_path}",
            gates_policy=gates,
        )
    if config.intervention_metrics_path is not None and not config.intervention_metrics_path.exists():
        return build_gate_event(
            "quality-shortfall",
            f"Intervention metrics file does not exist: {config.intervention_metrics_path}",
            gates_policy=gates,
        )
    return None

def _write_report(report_json_path: Path, report_markdown_path: Path, comparison_path: Path, report: dict[str, Any]) -> None:
    write_json_object(report_json_path, report)
    if isinstance(report.get("comparison"), dict):
        write_json_object(comparison_path, report["comparison"])
    lines = [
        "# Adaptation training runtime",
        "",
        f"- status: `{report.get('status')}`",
        f"- branch_id: `{report.get('branch_id')}`",
        f"- training_kind: `{report.get('training_kind')}`",
        f"- runtime_root: `{report.get('runtime_root')}`",
    ]
    if isinstance(report.get("comparison"), dict):
        comparison = report["comparison"]
        lines.extend(
            [
                f"- decision: `{comparison.get('decision')}`",
                f"- route_to: `{comparison.get('route_to')}`",
                f"- primary_metric: `{comparison.get('primary_metric')}`",
                f"- summary: {comparison.get('summary')}",
            ]
        )
    if isinstance(report.get("gate_event"), dict):
        gate_event = report["gate_event"]
        lines.extend(
            [
                f"- gate: `{gate_event.get('gate')}`",
                f"- risk_class: `{gate_event.get('risk_class')}`",
                f"- gate_reason: {gate_event.get('reason')}",
            ]
        )
    if report.get("summary"):
        lines.append(f"- summary: {report['summary']}")
    _write_markdown(report_markdown_path, lines)

def _result_payload(
    config: AdaptationTrainingConfig,
    *,
    status: str,
    summary: str,
    train_job: dict[str, Any] | None = None,
    eval_job: dict[str, Any] | None = None,
    comparison: dict[str, Any] | None = None,
    failure_reason: str | None = None,
    blocked_reason: str | None = None,
    gate_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report_json_path, report_markdown_path, comparison_path = _report_paths(config.output_root)
    report = {
        "schema_version": 1,
        "status": status,
        "summary": summary,
        "branch_id": config.branch_id,
        "objective": config.objective,
        "training_kind": config.training_kind,
        "runtime_root": str(config.output_root),
        "mission_state_path": str(config.mission_state_path) if config.mission_state_path is not None else None,
        "artifacts": {
            "adapter_artifact_path": str(config.adapter_artifact_path),
            "evaluation_metrics_path": str(config.evaluation_metrics_path),
            "baseline_metrics_path": str(config.baseline_metrics_path),
            "intervention_metrics_path": (
                str(config.intervention_metrics_path) if config.intervention_metrics_path is not None else None
            ),
        },
        "jobs": {
            "train": train_job,
            "evaluate": eval_job,
        },
        "comparison": comparison,
        "metric_ratchet": comparison,
        "failure_reason": failure_reason,
        "blocked_reason": blocked_reason,
        "gate_event": gate_event,
        "produced_outputs": list(_PRODUCED_OUTPUTS if status == "completed" else ()),
    }
    _write_report(report_json_path, report_markdown_path, comparison_path, report)
    mission_state_updates = {
        "adaptation_training": {
            "status": status,
            "summary": summary,
            "report_json_path": str(report_json_path),
            "comparison_path": str(comparison_path),
            "adapter_artifact_path": str(config.adapter_artifact_path),
            "evaluation_metrics_path": str(config.evaluation_metrics_path),
            "decision": comparison.get("decision") if isinstance(comparison, dict) else None,
            "route_to": comparison.get("route_to") if isinstance(comparison, dict) else None,
            "metric_ratchet": comparison,
            "gate_event": gate_event,
        }
    }
    if blocked_reason:
        mission_state_updates["blocked_reasons"] = [blocked_reason]
    if gate_event is not None and gate_event.get("gate") == "soft":
        mission_state_updates["soft_gate_events"] = [gate_event]
    if failure_reason:
        mission_state_updates["recent_failures"] = [failure_reason]
    return {
        "status": status,
        "summary": summary,
        "runtime_root": config.output_root,
        "train_job_path": _job_path(config.output_root, "train"),
        "eval_job_path": _job_path(config.output_root, "evaluate"),
        "report_json_path": report_json_path,
        "report_markdown_path": report_markdown_path,
        "comparison_path": comparison_path,
        "training_log_path": _log_path(config.output_root, "train"),
        "evaluation_log_path": _log_path(config.output_root, "evaluate"),
        "adapter_artifact_path": config.adapter_artifact_path,
        "evaluation_metrics_path": config.evaluation_metrics_path,
        "comparison": comparison,
        "gate_event": gate_event,
        "produced_outputs": report["produced_outputs"],
        "mission_state_updates": mission_state_updates,
    }

def run_adaptation_training(
    training_config_path: Path | str,
    *,
    mission_state_path: Path | str | None = None,
    gates_path: Path = DEFAULT_GATES_PATH,
) -> dict[str, Any]:
    resolved_mission_state_path = (
        Path(mission_state_path).expanduser().resolve() if mission_state_path is not None else None
    )
    config = AdaptationTrainingConfig.load(
        Path(training_config_path),
        mission_state_path=resolved_mission_state_path,
    )
    config.output_root.mkdir(parents=True, exist_ok=True)
    gates = load_gate_policy(gates_path)
    gate_event = _gate_event(config, gates)
    if gate_event is not None:
        status = str(gate_event["status"])
        reason = str(gate_event["reason"])
        return _result_payload(
            config,
            status=status,
            summary=(
                f"Adaptation training blocked: {reason}"
                if status == "blocked"
                else f"Adaptation training soft-gated: {reason}"
            ),
            blocked_reason=reason if status == "blocked" else None,
            gate_event=gate_event,
        )

    started = time.monotonic()
    total_budget_seconds = max(int(config.max_runtime_hours * 3600), 1)
    train_job = _execute_command(
        config,
        step="train",
        command=config.train,
        timeout_seconds=min(config.train.timeout_seconds or total_budget_seconds, total_budget_seconds),
        expected_outputs={"adapter_artifact_path": str(config.adapter_artifact_path)},
    )
    if str(train_job.get("status")) != "completed":
        failure_reason = str(train_job.get("failure_reason") or "Training step failed.")
        return _result_payload(
            config,
            status="failed",
            summary=f"Adaptation training failed: {failure_reason}",
            train_job=train_job,
            failure_reason=failure_reason,
        )
    if not config.adapter_artifact_path.exists():
        failure_reason = f"Training completed without producing adapter artifact `{config.adapter_artifact_path}`."
        return _result_payload(
            config,
            status="failed",
            summary=f"Adaptation training failed: {failure_reason}",
            train_job=train_job,
            failure_reason=failure_reason,
        )

    remaining_budget = total_budget_seconds - int(time.monotonic() - started)
    if remaining_budget <= 0:
        failure_reason = "Training consumed the entire bounded runtime budget before re-evaluation could start."
        return _result_payload(
            config,
            status="failed",
            summary=f"Adaptation training failed: {failure_reason}",
            train_job=train_job,
            failure_reason=failure_reason,
        )

    eval_job = _execute_command(
        config,
        step="evaluate",
        command=config.evaluate,
        timeout_seconds=min(config.evaluate.timeout_seconds or remaining_budget, remaining_budget),
        expected_outputs={"evaluation_metrics_path": str(config.evaluation_metrics_path)},
    )
    if str(eval_job.get("status")) != "completed":
        failure_reason = str(eval_job.get("failure_reason") or "Re-evaluation step failed.")
        return _result_payload(
            config,
            status="failed",
            summary=f"Adaptation training failed: {failure_reason}",
            train_job=train_job,
            eval_job=eval_job,
            failure_reason=failure_reason,
        )
    if not config.evaluation_metrics_path.exists():
        failure_reason = f"Re-evaluation completed without producing metrics `{config.evaluation_metrics_path}`."
        return _result_payload(
            config,
            status="failed",
            summary=f"Adaptation training failed: {failure_reason}",
            train_job=train_job,
            eval_job=eval_job,
            failure_reason=failure_reason,
        )

    baseline_metrics = metric_map(load_json_object(config.baseline_metrics_path))
    intervention_metrics = (
        metric_map(load_json_object(config.intervention_metrics_path))
        if config.intervention_metrics_path is not None
        else None
    )
    adapted_metrics = metric_map(load_json_object(config.evaluation_metrics_path))
    try:
        comparison = build_metric_ratchet_decision(
            config.comparison,
            candidate_metrics=adapted_metrics,
            anchors={
                "baseline": baseline_metrics,
                **({"intervention": intervention_metrics} if intervention_metrics is not None else {}),
            },
        )
    except ValueError as exc:
        failure_reason = str(exc)
        return _result_payload(
            config,
            status="failed",
            summary=f"Adaptation training failed: {failure_reason}",
            train_job=train_job,
            eval_job=eval_job,
            failure_reason=failure_reason,
        )
    summary = str(comparison["summary"])
    return _result_payload(
        config,
        status="completed",
        summary=summary,
        train_job=train_job,
        eval_job=eval_job,
        comparison=comparison,
    )
