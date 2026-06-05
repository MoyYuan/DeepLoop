from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from deeploop.core.ledger import append_jsonl, make_ledger_entry
from deeploop.core.paths import REPO_ROOT
from deeploop.runtime.stage_kernels import StageAdapter, load_stage_adapter, run_stage_from_config

logger = logging.getLogger(__name__)

DEFAULT_POLICY_PATH = REPO_ROOT / "configs" / "runtime" / "recovery-policy.yaml"


@dataclass
class RecoveryAttempt:
    attempt: int
    config_path: str
    status: str
    classification: str | None = None
    action: str | None = None
    detail: str | None = None


@dataclass
class RecoveryRunResult:
    stage_id: str
    status: str
    attempt_count: int
    output_dir: Path
    manifest_path: Path
    summary_path: Path | None
    recovery_report_path: Path
    recovery_history_path: Path
    artifacts: dict[str, Path]
    resumed: bool = False


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _expected_manifest_path(stage_id: str, output_dir: Path) -> Path:
    run_manifest_stages = {"baseline-evaluation", "prompt-decode-sweep"}
    return output_dir / ("run_manifest.json" if stage_id in run_manifest_stages else "study_manifest.json")


def _expected_summary_path(stage_id: str, output_dir: Path) -> Path | None:
    if stage_id == "baseline-evaluation":
        return None
    if stage_id == "prompt-decode-sweep":
        summary_path = output_dir / "summary.json"
        return summary_path if summary_path.exists() else None
    summary_path = output_dir / "study_summary.json"
    return summary_path if summary_path.exists() else None


def _infer_output_dir(stage_id: str, config: dict[str, Any], adapter: StageAdapter) -> Path:
    configured = config.get("run", {}).get("output_dir")
    if configured:
        return Path(str(configured)).expanduser()
    if stage_id == "baseline-evaluation":
        return adapter.runs_root / str(config.get("run", {}).get("loop_id", "baseline-recovery"))
    if stage_id == "prompt-decode-sweep":
        selected_direction = str(config.get("selected_direction", "unknown"))
        loop_id = str(config.get("run", {}).get("loop_id", f"prompt-decode-{selected_direction}"))
        return adapter.runs_root / loop_id
    return adapter.runs_root / str(config.get("study_id", f"{stage_id}-recovery"))


def _classify_exception(exc: Exception) -> str:
    message = str(exc).lower()
    if isinstance(exc, FileNotFoundError):
        return "missing-artifact"
    if "unsupported backend" in message or "unable to initialize backend" in message:
        return "unsupported-backend"
    if "requires torch and transformers" in message:
        return "dependency-missing"
    if isinstance(exc, (KeyError, TypeError)):
        return "config-error"
    return "unexpected-error"


def _classify_blocked(stage_id: str, config: dict[str, Any]) -> str:
    if stage_id == "causal-intervention":
        localization_source = config.get("localization_source")
        if localization_source and not Path(str(localization_source)).expanduser().exists():
            return "missing-artifact"
    return "stage-blocked"


def _patch_backend_fallback(config: dict[str, Any], policy: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
    fallback_cfg = policy.get("fallback_backends", {}).get("default")
    if not isinstance(fallback_cfg, dict):
        return None
    patched = json.loads(json.dumps(config))
    patched.setdefault("model", {})
    patched["model"]["backend"] = fallback_cfg["backend"]
    patched["model"]["identifier"] = fallback_cfg["identifier"]
    patched["model"]["dtype"] = fallback_cfg.get("dtype", "none")
    notes = patched.setdefault("run", {}).setdefault("notes", [])
    if isinstance(notes, list):
        notes.append("DeepLoop runtime recovery applied backend fallback.")
    return patched, "fallback-backend"


def _write_recovery_outputs(
    *,
    stage_id: str,
    policy: dict[str, Any],
    output_dir: Path,
    attempts: list[RecoveryAttempt],
    final_status: str,
    manifest_path: Path,
    summary_path: Path | None,
    resumed: bool,
) -> tuple[Path, Path]:
    names = policy.get("artifact_names", {})
    recovery_root = output_dir / "runtime_recovery"
    history_path = recovery_root / str(names.get("history_jsonl", "recovery-history.jsonl"))
    report_path = recovery_root / str(names.get("report_json", "recovery-report.json"))
    for attempt in attempts:
        append_jsonl(history_path, asdict(attempt))
    _write_json(
        report_path,
        {
            "stage_id": stage_id,
            "final_status": final_status,
            "attempt_count": len(attempts),
            "resumed": resumed,
            "manifest_path": str(manifest_path),
            "summary_path": str(summary_path) if summary_path is not None else None,
            "attempts": [asdict(attempt) for attempt in attempts],
        },
    )
    return report_path, history_path


def run_stage_with_recovery(
    stage_id: str,
    config_path: Path,
    *,
    adapter: StageAdapter | None = None,
    adapter_spec: str | None = None,
    policy_path: Path = DEFAULT_POLICY_PATH,
    mission_state_path: Path | None = None,
) -> RecoveryRunResult:
    policy = _load_yaml(policy_path)
    resolved_adapter = adapter or load_stage_adapter(adapter_spec)
    current_config_path = Path(config_path).resolve()
    current_config = _load_yaml(current_config_path)
    output_dir = _infer_output_dir(stage_id, current_config, resolved_adapter)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = _expected_manifest_path(stage_id, output_dir)
    summary_path = _expected_summary_path(stage_id, output_dir)
    attempts: list[RecoveryAttempt] = []

    if policy.get("resume_if_manifest_exists", True) and manifest_path.exists():
        attempts.append(
            RecoveryAttempt(
                attempt=0,
                config_path=str(current_config_path),
                status="resumed",
                action="resume-existing-manifest",
            )
        )
        report_path, history_path = _write_recovery_outputs(
            stage_id=stage_id,
            policy=policy,
            output_dir=output_dir,
            attempts=attempts,
            final_status="resumed",
            manifest_path=manifest_path,
            summary_path=summary_path,
            resumed=True,
        )
        return RecoveryRunResult(
            stage_id=stage_id,
            status="resumed",
            attempt_count=0,
            output_dir=output_dir,
            manifest_path=manifest_path,
            summary_path=summary_path,
            recovery_report_path=report_path,
            recovery_history_path=history_path,
            artifacts={
                "manifest": manifest_path,
                "recovery_report": report_path,
                "recovery_history": history_path,
            },
            resumed=True,
        )

    max_attempts = int(policy.get("max_attempts", 2))
    final_status = "failed"
    last_result = None
    for attempt_number in range(1, max_attempts + 2):
        try:
            last_result = run_stage_from_config(stage_id, current_config_path, adapter=resolved_adapter)
            output_dir = last_result.output_dir
            manifest_path = last_result.manifest_path
            summary_path = last_result.summary_path
            attempts.append(RecoveryAttempt(attempt=attempt_number, config_path=str(current_config_path), status=last_result.status))
            if last_result.status == "completed":
                final_status = "completed"
            else:
                classification = _classify_blocked(stage_id, current_config)
                attempts[-1].classification = classification
                attempts[-1].action = str(policy.get("classifications", {}).get(classification, {}).get("action", "stop"))
                final_status = last_result.status
            break
        except (subprocess.CalledProcessError, OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
            logger.warning("Recovery attempt failed with expected error: %s", exc)
            classification = _classify_exception(exc)
            action = str(policy.get("classifications", {}).get(classification, {}).get("action", "stop"))
            attempts.append(
                RecoveryAttempt(
                    attempt=attempt_number,
                    config_path=str(current_config_path),
                    status="failed",
                    classification=classification,
                    action=action,
                    detail=str(exc),
                )
            )
            if attempt_number > max_attempts or action != "fallback-backend":
                break
            patched = _patch_backend_fallback(current_config, policy)
            if patched is None:
                break
            current_config, _ = patched
            current_config_path = output_dir / "runtime_recovery" / f"attempt-{attempt_number + 1}-config.yaml"
            current_config_path.parent.mkdir(parents=True, exist_ok=True)
            current_config_path.write_text(yaml.safe_dump(current_config, sort_keys=False), encoding="utf-8")

    report_path, history_path = _write_recovery_outputs(
        stage_id=stage_id,
        policy=policy,
        output_dir=output_dir,
        attempts=attempts,
        final_status=final_status,
        manifest_path=manifest_path,
        summary_path=summary_path,
        resumed=False,
    )
    artifacts = {
        "manifest": manifest_path,
        "recovery_report": report_path,
        "recovery_history": history_path,
    }
    if summary_path is not None:
        artifacts["summary"] = summary_path
    if last_result is not None:
        artifacts.update(last_result.artifacts)

    if mission_state_path is not None:
        append_jsonl(
            Path(mission_state_path).parent / "ledger.jsonl",
            make_ledger_entry(
                kind=str(policy.get("ledger", {}).get("kind", "stage-recovery")),
                mission_id=Path(mission_state_path).parent.name,
                summary=f"{stage_id} {final_status} after {len(attempts)} attempt(s)",
                status=final_status,
                related_paths=[str(report_path), str(history_path), str(manifest_path)],
                metadata={"stage_id": stage_id, "attempt_count": len(attempts)},
            ),
        )

    return RecoveryRunResult(
        stage_id=stage_id,
        status=final_status,
        attempt_count=len(attempts),
        output_dir=output_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
        recovery_report_path=report_path,
        recovery_history_path=history_path,
        artifacts=artifacts,
        resumed=False,
    )
