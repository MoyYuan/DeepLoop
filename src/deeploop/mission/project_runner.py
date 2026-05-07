from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deeploop.mission.mission_monitor import build_mission_snapshot
from deeploop.mission.mission_runtime import run_mission
from deeploop.mission.orchestrator import initialize_mission


def _jsonify(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    return value


def _normalized_int(value: int, *, minimum: int) -> int:
    resolved = int(value)
    if resolved < minimum:
        raise ValueError(f"Expected integer >= {minimum}, got {value}.")
    return resolved


def _soft_recovery_resume_allowed(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    operator_console = snapshot.get("operator_console")
    if not isinstance(operator_console, dict):
        return False
    gate_class = str(operator_console.get("gate_class") or "").strip().lower()
    resume_policy = str(operator_console.get("resume_policy") or "").strip().lower()
    return gate_class == "soft-gate" and resume_policy in {"resume-optional", "not-needed"}


def _resume_summary_from_state(mission_state_path: Path) -> dict[str, Any]:
    if not mission_state_path.exists():
        return {
            "resumed_existing_mission": False,
            "initial_runtime_status": None,
            "initial_iterations_completed": 0,
        }
    try:
        mission_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "resumed_existing_mission": False,
            "initial_runtime_status": None,
            "initial_iterations_completed": 0,
        }
    mission_runtime = mission_state.get("mission_runtime") if isinstance(mission_state.get("mission_runtime"), dict) else {}
    runtime_status = str(mission_runtime.get("status") or "").strip() or None
    iterations_completed = int(mission_runtime.get("iterations_completed", 0) or 0)
    return {
        "resumed_existing_mission": iterations_completed > 0 or runtime_status is not None,
        "initial_runtime_status": runtime_status,
        "initial_iterations_completed": iterations_completed,
    }


def run_project_until_complete(
    project_root: Path,
    *,
    mission_id: str | None = None,
    force: bool = False,
    chunk_iterations: int = 8,
    max_total_iterations: int = 256,
) -> dict[str, Any]:
    resolved_project_root = project_root.expanduser().resolve()
    resolved_chunk_iterations = _normalized_int(chunk_iterations, minimum=1)
    resolved_max_total_iterations = _normalized_int(max_total_iterations, minimum=1)
    if resolved_chunk_iterations > resolved_max_total_iterations:
        raise ValueError("chunk_iterations cannot exceed max_total_iterations.")

    init_result = initialize_mission_from_project_root(
        resolved_project_root,
        mission_id=mission_id,
        force=force,
    )
    if init_result.get("status") == "bootstrap-repair-required":
        return {
            "status": "bootstrap-repair-required",
            "project_root": resolved_project_root,
            "bootstrap_repair": init_result.get("bootstrap_repair"),
        }
    mission_state_path = Path(init_result["state_path"]).expanduser().resolve()
    resume_summary = _resume_summary_from_state(mission_state_path)
    runtime_passes = 0
    soft_recovery_resume_passes = 0
    latest_result: dict[str, Any] | None = None
    latest_snapshot: dict[str, Any] | None = None
    runtime_limit = min(resolved_chunk_iterations, resolved_max_total_iterations)

    while True:
        latest_result = run_mission(mission_state_path, max_iterations=runtime_limit)
        runtime_passes += 1
        latest_snapshot = build_mission_snapshot(mission_state_path, log_tail_lines=20, ledger_tail=8)
        latest_status = str(latest_result.get("status") or "")
        operator_console = (
            latest_snapshot.get("operator_console")
            if isinstance(latest_snapshot.get("operator_console"), dict)
            else {}
        )
        requires_action = bool(operator_console.get("requires_action"))
        soft_recovery_resume = _soft_recovery_resume_allowed(latest_snapshot)

        if latest_status == "completed":
            break
        if requires_action and not soft_recovery_resume:
            resume_summary["bounded_resume_passes"] = max(runtime_passes - 1, 0)
            resume_summary["soft_recovery_resume_passes"] = soft_recovery_resume_passes
            return {
                "status": "operator-review-required",
                "project_root": resolved_project_root,
                "mission_root": Path(init_result["mission_root"]),
                "mission_state_path": mission_state_path,
                "runtime_passes": runtime_passes,
                "runtime_iteration_limit": runtime_limit,
                "runtime_result": latest_result,
                "snapshot": latest_snapshot,
                "resume_summary": resume_summary,
            }
        if latest_status not in {"max-iterations", "blocked", "failed"} or (
            latest_status in {"blocked", "failed"} and not soft_recovery_resume
        ):
            resume_summary["bounded_resume_passes"] = max(runtime_passes - 1, 0)
            resume_summary["soft_recovery_resume_passes"] = soft_recovery_resume_passes
            return {
                "status": latest_status or "stopped",
                "project_root": resolved_project_root,
                "mission_root": Path(init_result["mission_root"]),
                "mission_state_path": mission_state_path,
                "runtime_passes": runtime_passes,
                "runtime_iteration_limit": runtime_limit,
                "runtime_result": latest_result,
                "snapshot": latest_snapshot,
                "resume_summary": resume_summary,
            }
        if soft_recovery_resume:
            soft_recovery_resume_passes += 1

        iterations_completed = int(latest_result.get("iterations_completed", 0) or 0)
        if iterations_completed >= resolved_max_total_iterations:
            resume_summary["bounded_resume_passes"] = max(runtime_passes - 1, 0)
            resume_summary["soft_recovery_resume_passes"] = soft_recovery_resume_passes
            return {
                "status": "max-total-iterations",
                "project_root": resolved_project_root,
                "mission_root": Path(init_result["mission_root"]),
                "mission_state_path": mission_state_path,
                "runtime_passes": runtime_passes,
                "runtime_iteration_limit": runtime_limit,
                "runtime_result": latest_result,
                "snapshot": latest_snapshot,
                "resume_summary": resume_summary,
            }
        runtime_limit = min(max(iterations_completed, runtime_limit) + resolved_chunk_iterations, resolved_max_total_iterations)

    resume_summary["bounded_resume_passes"] = max(runtime_passes - 1, 0)
    resume_summary["soft_recovery_resume_passes"] = soft_recovery_resume_passes
    return {
        "status": "completed",
        "project_root": resolved_project_root,
        "mission_root": Path(init_result["mission_root"]),
        "mission_state_path": mission_state_path,
        "runtime_passes": runtime_passes,
        "runtime_iteration_limit": runtime_limit,
        "runtime_result": latest_result,
        "snapshot": latest_snapshot,
        "resume_summary": resume_summary,
    }


def _find_explicit_mission_configs(project_root: Path) -> list[Path]:
    """Return any YAML config files found in <project_root>/.deeploop/missions/."""
    missions_dir = project_root / ".deeploop" / "missions"
    if not missions_dir.is_dir():
        return []
    return sorted(missions_dir.glob("*.yaml")) + sorted(missions_dir.glob("*.yml"))


def initialize_mission_from_project_root(
    project_root: Path,
    *,
    mission_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from deeploop.core.paths import MISSIONS_DIR, SCRATCH_DIR
    from deeploop.mission.project_bootstrap import build_mission_config_from_project_root
    import yaml

    resolved_project_root = project_root.expanduser().resolve()

    explicit_configs = _find_explicit_mission_configs(resolved_project_root)
    if explicit_configs:
        selected_config = explicit_configs[0]
        print(
            f"run: detected explicit mission config in "
            f"{resolved_project_root / '.deeploop' / 'missions'} — "
            f"using {selected_config.name} instead of bootstrapping a blank mission.",
            flush=True,
        )
        if len(explicit_configs) > 1:
            others = [p.name for p in explicit_configs[1:]]
            print(
                f"run: ignoring additional config(s): {', '.join(others)}. "
                "Use `deeploop init --config <path>` to initialize a specific config.",
                flush=True,
            )
        if mission_id is not None:
            print(
                f"run: --mission-id={mission_id!r} was supplied but an explicit config "
                "was found; the explicit config's mission id takes precedence.",
                flush=True,
            )
        return initialize_mission(selected_config, force=force)

    generated_config = build_mission_config_from_project_root(resolved_project_root, mission_id=mission_id)
    bootstrap_repair = (
        generated_config.get("bootstrap_repair") if isinstance(generated_config.get("bootstrap_repair"), dict) else None
    )
    if isinstance(bootstrap_repair, dict) and str(bootstrap_repair.get("status") or "").strip().lower() == "required":
        return {
            "status": "bootstrap-repair-required",
            "project_root": resolved_project_root,
            "bootstrap_repair": bootstrap_repair,
        }
    resolved_mission_id = str(generated_config["mission"]["id"])
    mission_root = MISSIONS_DIR / resolved_mission_id
    state_path = mission_root / "mission_state.json"
    summary_path = mission_root / "mission_summary.md"
    ledger_path = mission_root / "ledger.jsonl"
    generated_config_dir = SCRATCH_DIR / "mission_bootstrap_configs"
    generated_config_dir.mkdir(parents=True, exist_ok=True)
    generated_config_path = generated_config_dir / f"{resolved_mission_id}.yaml"
    generated_config_path.write_text(yaml.safe_dump(generated_config, sort_keys=False), encoding="utf-8")
    persisted_config_path = mission_root / "generated_mission_config.yaml"
    if mission_root.exists() and state_path.exists() and not force:
        return {
            "mission_root": mission_root,
            "state_path": state_path,
            "summary_path": summary_path,
            "ledger_path": ledger_path,
            "generated_config_path": generated_config_path,
            "persisted_config_path": persisted_config_path,
        }
    result = initialize_mission(generated_config_path, force=force)
    persisted_config_path = Path(result["mission_root"]) / "generated_mission_config.yaml"
    persisted_config_path.write_text(generated_config_path.read_text(encoding="utf-8"), encoding="utf-8")
    return {
        **result,
        "generated_config_path": generated_config_path,
        "persisted_config_path": persisted_config_path,
    }


__all__ = [
    "initialize_mission_from_project_root",
    "run_project_until_complete",
    "_jsonify",
]
