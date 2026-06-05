from __future__ import annotations

"""Canonical mission runtime dispatch for DeepLoop-owned executors."""

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import sys
from typing import Any, Callable, TypeAlias

from deeploop.artifacts.artifact_packager import PACKAGE_CONTRACT_PATH, package_mission_artifacts
from deeploop.core.structured_io import load_json_object as _load_json
from deeploop.research.self_correction import DEFAULT_CONTRACT_PATH as SELF_CORRECTION_CONTRACT_PATH
from deeploop.research.self_correction import evaluate_self_correction
from deeploop.runtime.adaptation_training_runtime import run_adaptation_training
from deeploop.runtime.recursive_agent_runtime import run_recursive_agent_loop
from deeploop.runtime.report_synthesis import synthesize_report
from deeploop.runtime.self_healing_runtime import run_self_healing_queue
from deeploop.runtime.stage_kernels import StageAdapter, run_stage_from_config


class MissionExecutorId(str, Enum):
    RECURSIVE_AGENT = "recursive-agent"
    SELF_HEALING_QUEUE = "self-healing-queue"
    STAGE_KERNEL = "stage-kernel"
    ADAPTATION_TRAINING = "adaptation-training"
    EVALUATION_COMPARISON = "evaluation-comparison"
    REPORT_SYNTHESIS = "report-synthesis"


class MissionExecutorError(RuntimeError):
    """Base error raised by the mission executor registry."""


class UnknownMissionExecutorError(MissionExecutorError):
    """Raised when a caller requests an unregistered mission executor."""


class MissionExecutorNotImplementedError(MissionExecutorError):
    """Raised when a placeholder executor is dispatched."""


def _normalized_path(value: str | Path) -> Path:
    return Path(value).expanduser()


def _normalized_optional_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    return _normalized_path(value)


def _normalized_paths(values: list[str | Path] | tuple[str | Path, ...] | None) -> tuple[Path, ...]:
    if not values:
        return ()
    return tuple(_normalized_path(value) for value in values)


def _recursive_agent_executor_status(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "failed")
    if status != "max-iterations":
        return status
    latest_outcome = payload.get("latest_outcome")
    if not isinstance(latest_outcome, dict):
        return status
    action_result = latest_outcome.get("action_result")
    if not isinstance(action_result, dict):
        return status
    action_status = str(action_result.get("status") or "").strip().lower()
    if action_status == "complete":
        action_status = "completed"
    if action_status == "completed":
        return "completed"
    return status


@dataclass(frozen=True)
class RecursiveAgentExecutorAction:
    config_path: Path | str

    def __post_init__(self) -> None:
        object.__setattr__(self, "config_path", _normalized_path(self.config_path))


@dataclass(frozen=True)
class SelfHealingQueueExecutorAction:
    config_path: Path | str
    policy_path: Path | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "config_path", _normalized_path(self.config_path))
        object.__setattr__(self, "policy_path", _normalized_optional_path(self.policy_path))


@dataclass(frozen=True)
class StageKernelExecutorAction:
    stage_id: str
    config_path: Path | str
    adapter: StageAdapter | None = None
    adapter_spec: str | None = None
    pythonpath: tuple[Path, ...] | list[Path | str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "config_path", _normalized_path(self.config_path))
        object.__setattr__(self, "pythonpath", _normalized_paths(self.pythonpath))


@dataclass(frozen=True)
class AdaptationTrainingExecutorAction:
    training_config_path: Path | str
    mission_state_path: Path | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "training_config_path", _normalized_path(self.training_config_path))
        object.__setattr__(self, "mission_state_path", _normalized_optional_path(self.mission_state_path))


@dataclass(frozen=True)
class EvaluationComparisonExecutorAction:
    mission_state_path: Path | str | None = None
    manifest_paths: tuple[Path, ...] | list[Path | str] = ()
    run_roots: tuple[Path, ...] | list[Path | str] = ()
    contract_path: Path | str = SELF_CORRECTION_CONTRACT_PATH
    artifact_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_state_path", _normalized_optional_path(self.mission_state_path))
        object.__setattr__(self, "manifest_paths", _normalized_paths(self.manifest_paths))
        object.__setattr__(self, "run_roots", _normalized_paths(self.run_roots))
        object.__setattr__(self, "contract_path", _normalized_path(self.contract_path))


@dataclass(frozen=True)
class ReportSynthesisExecutorAction:
    mission_state_path: Path | str
    contract_path: Path | str = PACKAGE_CONTRACT_PATH
    output_root: Path | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_state_path", _normalized_path(self.mission_state_path))
        object.__setattr__(self, "contract_path", _normalized_path(self.contract_path))
        object.__setattr__(self, "output_root", _normalized_optional_path(self.output_root))


MissionExecutorAction: TypeAlias = (
    RecursiveAgentExecutorAction
    | SelfHealingQueueExecutorAction
    | StageKernelExecutorAction
    | AdaptationTrainingExecutorAction
    | EvaluationComparisonExecutorAction
    | ReportSynthesisExecutorAction
)


@dataclass(frozen=True)
class MissionExecutionResult:
    executor_id: MissionExecutorId
    status: str
    summary: str
    payload: dict[str, Any]
    artifacts: dict[str, Path]


@dataclass(frozen=True)
class MissionExecutor:
    executor_id: MissionExecutorId
    action_type: type[MissionExecutorAction]
    summary: str
    runner: Callable[[MissionExecutorAction], MissionExecutionResult] | None = None

    def run(self, action: MissionExecutorAction) -> MissionExecutionResult:
        if not isinstance(action, self.action_type):
            raise TypeError(
                f"Executor `{self.executor_id.value}` requires action type "
                f"{self.action_type.__name__}, got {type(action).__name__}."
            )
        if self.runner is None:
            raise MissionExecutorNotImplementedError(
                f"Executor `{self.executor_id.value}` is registered as a placeholder: {self.summary}"
            )
        return self.runner(action)


def _artifact_paths(**values: Path | str | None) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    for key, value in values.items():
        if value is None:
            continue
        artifacts[key] = value if isinstance(value, Path) else _normalized_path(value)
    return artifacts


@contextmanager
def _temporary_sys_path(paths: tuple[Path, ...]) -> Any:
    inserted: list[str] = []
    try:
        for path in reversed(paths):
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)
                inserted.append(text)
        yield
    finally:
        for text in inserted:
            if text in sys.path:
                sys.path.remove(text)


def _queue_status(payload: dict[str, Any]) -> str:
    if int(payload.get("failed_jobs", 0) or 0) > 0:
        return "failed"
    if int(payload.get("blocked_jobs", 0) or 0) > 0:
        return "blocked"
    return "completed"


def _run_recursive_agent_executor(action: RecursiveAgentExecutorAction) -> MissionExecutionResult:
    payload = run_recursive_agent_loop(action.config_path)
    status = _recursive_agent_executor_status(payload)
    summary = f"Recursive agent loop finished with status `{payload['status']}`."
    if str(payload.get("status")) == "max-iterations" and status == "completed":
        summary = "Recursive agent loop reached its iteration cap after completing the latest action."
    return MissionExecutionResult(
        executor_id=MissionExecutorId.RECURSIVE_AGENT,
        status=status,
        summary=summary,
        payload=payload,
        artifacts=_artifact_paths(
            runtime_root=payload.get("runtime_root"),
            state_path=payload.get("state_path"),
            memory_path=payload.get("memory_path"),
            latest_iteration_path=payload.get("latest_iteration_path"),
            latest_result_path=payload.get("latest_result_path"),
            report_json_path=payload.get("report_json_path"),
            report_markdown_path=payload.get("report_markdown_path"),
        ),
    )


def _run_self_healing_queue_executor(action: SelfHealingQueueExecutorAction) -> MissionExecutionResult:
    payload = run_self_healing_queue(action.config_path, policy_path=action.policy_path)
    status = _queue_status(payload)
    return MissionExecutionResult(
        executor_id=MissionExecutorId.SELF_HEALING_QUEUE,
        status=status,
        summary=f"Self-healing queue finished with status `{status}`.",
        payload=payload,
        artifacts=_artifact_paths(
            ledger_path=payload.get("ledger_path"),
            runtime_report_path=payload.get("runtime_report_path"),
            runtime_report_markdown_path=payload.get("runtime_report_markdown_path"),
        ),
    )


def _run_stage_kernel_executor(action: StageKernelExecutorAction) -> MissionExecutionResult:
    with _temporary_sys_path(action.pythonpath):
        result = run_stage_from_config(
            action.stage_id,
            action.config_path,
            adapter=action.adapter,
            adapter_spec=action.adapter_spec,
        )
    payload = {
        "stage_id": result.stage_id,
        "status": result.status,
        "output_dir": result.output_dir,
        "manifest_path": result.manifest_path,
        "summary_path": result.summary_path,
        "artifacts": result.artifacts,
    }
    return MissionExecutionResult(
        executor_id=MissionExecutorId.STAGE_KERNEL,
        status=result.status,
        summary=f"Stage kernel `{result.stage_id}` finished with status `{result.status}`.",
        payload=payload,
        artifacts=_artifact_paths(
            output_dir=result.output_dir,
            manifest_path=result.manifest_path,
            summary_path=result.summary_path,
            **result.artifacts,
        ),
    )


def _run_adaptation_training_executor(action: AdaptationTrainingExecutorAction) -> MissionExecutionResult:
    payload = run_adaptation_training(
        action.training_config_path,
        mission_state_path=action.mission_state_path,
    )
    status = str(payload["status"])
    comparison = payload.get("comparison")
    decision = str(comparison.get("decision")) if isinstance(comparison, dict) else None
    summary = str(payload.get("summary") or "Bounded adaptation training finished.")
    if decision is not None:
        summary = f"{summary.rstrip('.')}. decision={decision}"
    return MissionExecutionResult(
        executor_id=MissionExecutorId.ADAPTATION_TRAINING,
        status=status,
        summary=summary,
        payload=payload,
        artifacts=_artifact_paths(
            runtime_root=payload.get("runtime_root"),
            train_job_path=payload.get("train_job_path"),
            eval_job_path=payload.get("eval_job_path"),
            report_json_path=payload.get("report_json_path"),
            report_markdown_path=payload.get("report_markdown_path"),
            comparison_path=payload.get("comparison_path"),
            training_log_path=payload.get("training_log_path"),
            evaluation_log_path=payload.get("evaluation_log_path"),
            adapter_artifact_path=payload.get("adapter_artifact_path"),
            evaluation_metrics_path=payload.get("evaluation_metrics_path"),
        ),
    )


def _run_evaluation_comparison_executor(action: EvaluationComparisonExecutorAction) -> MissionExecutionResult:
    payload = evaluate_self_correction(
        mission_state_path=action.mission_state_path,
        manifest_paths=list(action.manifest_paths) or None,
        run_roots=list(action.run_roots) or None,
        contract_path=action.contract_path,
        artifact_name=action.artifact_name,
    )
    final_decision = payload["final_decision"]
    status = str(final_decision["action"])
    return MissionExecutionResult(
        executor_id=MissionExecutorId.EVALUATION_COMPARISON,
        status=status,
        summary=f"Evaluation comparison returned `{status}`.",
        payload=payload,
        artifacts=_artifact_paths(
            report_json_path=payload.get("report_json_path"),
            report_markdown_path=payload.get("report_markdown_path"),
        ),
    )


def _run_report_synthesis_executor(action: ReportSynthesisExecutorAction) -> MissionExecutionResult:
    # Load mission state
    mission_state = _load_json(action.mission_state_path)  # type: ignore[arg-type]

    # Generate the research report (LaTeX + optional PDF)
    report_result = synthesize_report(
        mission_state=mission_state,
        experiment_dag=None,
        bounded_memory=None,
        output_dir=action.output_root,
    )

    # Also refresh the artifact package for backward compatibility
    package_payload = package_mission_artifacts(
        action.mission_state_path,
        contract_path=action.contract_path,
        output_root=action.output_root,
    )

    # Merge report paths into the package payload
    merged_payload = dict(package_payload)
    merged_payload["report_tex_path"] = report_result.get("report_tex_path", "")
    merged_payload["report_pdf_path"] = report_result.get("report_pdf_path", "")

    return MissionExecutionResult(
        executor_id=MissionExecutorId.REPORT_SYNTHESIS,
        status="completed",
        summary=report_result.get("summary", "Mission artifact package refreshed."),
        payload=merged_payload,
        artifacts=_artifact_paths(
            package_root=merged_payload.get("package_root"),
            manifest_path=merged_payload.get("manifest_path"),
            summary_path=merged_payload.get("summary_path"),
            report_tex_path=merged_payload.get("report_tex_path") or None,
            report_pdf_path=merged_payload.get("report_pdf_path") or None,
        ),
    )


_EXECUTORS = {
    MissionExecutorId.RECURSIVE_AGENT: MissionExecutor(
        executor_id=MissionExecutorId.RECURSIVE_AGENT,
        action_type=RecursiveAgentExecutorAction,
        summary="Runs the bounded recursive-agent runtime from a loop config.",
        runner=_run_recursive_agent_executor,
    ),
    MissionExecutorId.SELF_HEALING_QUEUE: MissionExecutor(
        executor_id=MissionExecutorId.SELF_HEALING_QUEUE,
        action_type=SelfHealingQueueExecutorAction,
        summary="Runs the bounded self-healing queue runtime from a queue config.",
        runner=_run_self_healing_queue_executor,
    ),
    MissionExecutorId.STAGE_KERNEL: MissionExecutor(
        executor_id=MissionExecutorId.STAGE_KERNEL,
        action_type=StageKernelExecutorAction,
        summary="Runs a registered DeepLoop stage kernel from its config and adapter.",
        runner=_run_stage_kernel_executor,
    ),
    MissionExecutorId.ADAPTATION_TRAINING: MissionExecutor(
        executor_id=MissionExecutorId.ADAPTATION_TRAINING,
        action_type=AdaptationTrainingExecutorAction,
        summary="Runs DeepLoop-owned bounded local adaptation plus post-training evaluation/comparison.",
        runner=_run_adaptation_training_executor,
    ),
    MissionExecutorId.EVALUATION_COMPARISON: MissionExecutor(
        executor_id=MissionExecutorId.EVALUATION_COMPARISON,
        action_type=EvaluationComparisonExecutorAction,
        summary="Runs self-correction comparison over mission or manifest evidence.",
        runner=_run_evaluation_comparison_executor,
    ),
    MissionExecutorId.REPORT_SYNTHESIS: MissionExecutor(
        executor_id=MissionExecutorId.REPORT_SYNTHESIS,
        action_type=ReportSynthesisExecutorAction,
        summary="Synthesizes the mission artifact package for operator/report handoff.",
        runner=_run_report_synthesis_executor,
    ),
}


def _resolve_executor_id(executor_id: MissionExecutorId | str) -> MissionExecutorId:
    try:
        return executor_id if isinstance(executor_id, MissionExecutorId) else MissionExecutorId(str(executor_id))
    except ValueError as exc:
        raise UnknownMissionExecutorError(f"Unknown mission executor `{executor_id}`.") from exc


def _executor_id_for_action(action: MissionExecutorAction) -> MissionExecutorId:
    for executor_id, executor in _EXECUTORS.items():
        if isinstance(action, executor.action_type):
            return executor_id
    raise TypeError(f"Unsupported mission executor action type: {type(action).__name__}")


def get_mission_executor_registry() -> dict[MissionExecutorId, MissionExecutor]:
    return dict(_EXECUTORS)


def run_mission_executor(
    executor_id: MissionExecutorId | str,
    action: MissionExecutorAction,
) -> MissionExecutionResult:
    resolved_executor_id = _resolve_executor_id(executor_id)
    return _EXECUTORS[resolved_executor_id].run(action)


def run_mission_action(action: MissionExecutorAction) -> MissionExecutionResult:
    return run_mission_executor(_executor_id_for_action(action), action)
