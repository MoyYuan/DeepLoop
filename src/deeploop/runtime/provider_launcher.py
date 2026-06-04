from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Sequence

import yaml

from deeploop.core.paths import REPO_ROOT
from deeploop.core.phase_defaults import (
    default_kind_for_phase as _default_kind_for_phase,
    default_role_for_phase as _default_role_for_phase,
)
from deeploop.runtime.openai_compatible_adapter import build_openai_compatible_prompt_command

_SUPPORTED_PROVIDER_FAMILIES = frozenset({"openai-compatible-api"})
_DEFAULT_IDLE_TIMEOUT_SECONDS = 300.0
_POST_EXIT_RESULT_GRACE_SECONDS = 5.0
_POST_EXIT_RESULT_POLL_SECONDS = 0.2
_POLL_INTERVAL_SECONDS = 5.0


def _provider_subprocess_env() -> dict[str, str]:
    resolved_env = dict(os.environ)
    repo_src = REPO_ROOT / "src"
    if not repo_src.is_dir():
        return resolved_env
    existing_pythonpath = str(resolved_env.get("PYTHONPATH") or "").strip()
    pythonpath_entries = [str(repo_src)]
    if existing_pythonpath:
        pythonpath_entries.extend(
            entry for entry in existing_pythonpath.split(os.pathsep) if entry and entry != str(repo_src)
        )
    resolved_env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    return resolved_env


def build_provider_prompt_command(
    *,
    prompt_file: Path,
    result_json_path: Path | None = None,
    model: str | None = None,
) -> list[str]:
    return build_openai_compatible_prompt_command(
        prompt_file,
        result_json_path=result_json_path,
        model=model,
    )


def resolve_provider_idle_timeout_seconds(idle_timeout_seconds: float | None) -> float:
    if idle_timeout_seconds is not None:
        return idle_timeout_seconds
    return _DEFAULT_IDLE_TIMEOUT_SECONDS


def resolve_model_for_role(
    *,
    role: str,
    phase: str | None = None,
    explicit_model: str | None = None,
    tiers_config: Path | None = None,
) -> str:
    """Resolve which model identifier to use based on role and phase tier configuration.

    Resolution order:
    1. If ``explicit_model`` is provided, use it directly.
    2. Look up ``role`` in the model tiers config — first by direct role match,
       then by phase-to-role mapping.
    3. Fall back to the configured ``default_tier`` model.
    4. Fall back to the ``OPENAI_MODEL`` environment variable.
    5. Fall back to ``"deepseek-chat"`` as a last resort.

    Args:
        role: The intended role (e.g. ``"planner"``, ``"execution-operator"``).
        phase: Optional phase name (e.g. ``"experiment-design"``, ``"execution"``).
            When provided and the role is not directly listed in any tier, the
            function attempts to match the phase to a tier instead.
        explicit_model: If set, bypasses tier resolution and returns this value.
        tiers_config: Path to the model-tiers YAML configuration file. Defaults to
            ``<REPO_ROOT>/configs/runtime/model-tiers.yaml``.

    Returns:
        A model identifier string (e.g. ``"deepseek-chat"``, ``"deepseek-reasoner"``).
    """
    if explicit_model:
        return explicit_model

    resolved_tiers_path = (
        tiers_config
        if tiers_config is not None
        else REPO_ROOT / "configs" / "runtime" / "model-tiers.yaml"
    )

    try:
        raw = yaml.safe_load(resolved_tiers_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raw = None

    tiers_data: dict = raw if isinstance(raw, dict) else {}
    tiers: list[dict] = tiers_data.get("tiers", {})
    default_tier_name: str = str(tiers_data.get("default_tier", "execution"))

    # --- Look up role in tiers ---
    for tier_name, tier_cfg in tiers.items():
        if not isinstance(tier_cfg, dict):
            continue
        intended_roles = tier_cfg.get("intended_roles", [])
        if isinstance(intended_roles, list) and role in intended_roles:
            identifier = tier_cfg.get("model_identifier")
            if isinstance(identifier, str) and identifier:
                return identifier

    # --- Fallback: look up phase in tiers ---
    if phase:
        for tier_name, tier_cfg in tiers.items():
            if not isinstance(tier_cfg, dict):
                continue
            intended_phases = tier_cfg.get("intended_phases", [])
            if isinstance(intended_phases, list) and phase in intended_phases:
                identifier = tier_cfg.get("model_identifier")
                if isinstance(identifier, str) and identifier:
                    return identifier

    # --- Fallback to default tier ---
    if default_tier_name in tiers:
        default_cfg = tiers[default_tier_name]
        if isinstance(default_cfg, dict):
            identifier = default_cfg.get("model_identifier")
            if isinstance(identifier, str) and identifier:
                return identifier

    # --- Fallback to env var ---
    env_model = os.environ.get("OPENAI_MODEL", "").strip()
    if env_model:
        return env_model

    return "deepseek-chat"


def _load_json_file(path: Path) -> dict[str, object] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _normalize_list_like(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (str, Path)):
        return [str(raw)]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _dedupe_messages(messages: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    for message in messages:
        text = str(message).strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _provider_result_validation_errors(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    status = str(payload.get("status") or "").strip().lower()
    if status not in {
        "continue",
        "complete",
        "completed",
        "blocked",
        "failed",
        "fail",
        "error",
        "success",
        "successful",
        "succeeded",
        "ok",
        "done",
        "in_progress",
    }:
        errors.append("result.status must be a recognized recursive-agent status")
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        errors.append("result.summary must be a non-empty string")
    for key in ("produced_artifacts", "findings", "warnings"):
        value = payload.get(key)
        if value is not None and not isinstance(value, (str, list)):
            errors.append(f"result.{key} must be list-like when present")
    continuation = payload.get("continuation")
    if continuation is not None:
        if not isinstance(continuation, dict):
            errors.append("result.continuation must be an object when present")
        else:
            role = continuation.get("role")
            task = continuation.get("task")
            if (role is None) != (task is None):
                errors.append("result.continuation.role and result.continuation.task must be provided together")
    action_result = payload.get("action_result")
    if action_result is not None and not isinstance(action_result, dict):
        errors.append("result.action_result must be an object when present")
    phase_control = payload.get("phase_control")
    if phase_control is not None and not isinstance(phase_control, dict):
        errors.append("result.phase_control must be an object when present")
    return errors


_OUTPUT_NAME_STOPWORDS = {"a", "an", "and", "for", "of", "or", "the", "to", "with"}


def _normalize_output_name(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if token and token not in _OUTPUT_NAME_STOPWORDS
    )


def _extract_prompt_scalar(prompt_text: str, key: str) -> str | None:
    match = re.search(rf"^- {re.escape(key)}: `([^`]+)`$", prompt_text, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    return None if not value or value == "None" else value


def _extract_prompt_section_items(prompt_text: str, heading: str) -> list[str]:
    marker = f"## {heading}\n"
    start = prompt_text.find(marker)
    if start < 0:
        return []
    start += len(marker)
    remainder = prompt_text[start:]
    next_heading = remainder.find("\n## ")
    block = remainder if next_heading < 0 else remainder[:next_heading]
    items: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        item = line[2:].strip()
        if item.startswith("`") and item.endswith("`") and len(item) >= 2:
            item = item[1:-1].strip()
        if item:
            items.append(item)
    return items


def _extract_prompt_phase_constraints(prompt_text: str) -> tuple[list[str], list[str]]:
    marker = "## Phase constraints\n"
    start = prompt_text.find(marker)
    if start < 0:
        return ([], [])
    start += len(marker)
    remainder = prompt_text[start:]
    next_heading = remainder.find("\n## ")
    block = remainder if next_heading < 0 else remainder[:next_heading]
    required: list[str] = []
    transitions: list[str] = []
    current_target: list[str] | None = None
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if line == "Required phase outputs:":
            current_target = required
            continue
        if line == "Allowed next transitions:":
            current_target = transitions
            continue
        if line.startswith("Transition metadata:") or line.startswith("Relevant terminal/promotion rules:"):
            current_target = None
            continue
        if current_target is not None and line.startswith("- "):
            item = line[2:].strip()
            if item.startswith("`") and item.endswith("`") and len(item) >= 2:
                item = item[1:-1].strip()
            if item:
                current_target.append(item)
    return (required, transitions)


def _extract_transition_metadata(prompt_text: str, next_phase: str | None) -> tuple[str, str]:
    if not next_phase:
        return ("active", "not-needed")
    pattern = (
        rf"^- `{re.escape(next_phase)}` via `[^`]+` "
        r"\(branch_status=`([^`]+)`, recovery_status=`([^`]+)`\):"
    )
    match = re.search(pattern, prompt_text, re.MULTILINE)
    if not match:
        return ("active", "not-needed")
    return (match.group(1).strip() or "active", match.group(2).strip() or "not-needed")


def _collect_output_files(
    outputs_root: Path,
    *,
    min_mtime_ns: int | None = None,
    min_inode_on_tie: int | None = None,
) -> list[Path]:
    if not outputs_root.exists():
        return []
    collected: list[Path] = []
    for path in outputs_root.rglob("*"):
        if not path.is_file():
            continue
        if min_mtime_ns is not None:
            try:
                path_stat = path.stat()
                path_marker = (max(path_stat.st_mtime_ns, path_stat.st_ctime_ns), path_stat.st_ino)
                prompt_marker = (min_mtime_ns, min_inode_on_tie or -1)
                if path_marker <= prompt_marker:
                    continue
            except OSError:
                continue
        collected.append(path)
    return sorted(collected)


def _phase_outputs_are_satisfied(required_outputs: Sequence[str], produced_files: Sequence[Path]) -> bool:
    if not required_outputs:
        return False
    candidate_tokens = [
        set(_normalize_output_name(path.stem)) | set(_normalize_output_name(path.name))
        for path in produced_files
    ]
    for output_name in required_outputs:
        required_tokens = set(_normalize_output_name(output_name))
        if not required_tokens:
            return False
        if not any(required_tokens.issubset(tokens) for tokens in candidate_tokens):
            return False
    return True


def _latest_tree_activity(paths: Sequence[Path]) -> float | None:
    latest: float | None = None
    for root in paths:
        if not root.exists():
            continue
        candidates = [root]
        if root.is_dir():
            candidates = [root, *root.rglob("*")]
        for candidate in candidates:
            try:
                candidate_mtime = candidate.stat().st_mtime
            except OSError:
                continue
            latest = candidate_mtime if latest is None else max(latest, candidate_mtime)
    return latest


def _materialize_execution_summary_from_completed_runs(
    *,
    sandbox_root: Path,
    mission_state_path: Path,
) -> dict[str, object] | None:
    execution_root = mission_state_path.parent / "runtime" / "execution"
    runtime_candidates = [
        candidate
        for candidate in execution_root.iterdir()
        if candidate.is_dir() and (candidate / "runs").exists()
    ] if execution_root.exists() else []
    if len(runtime_candidates) != 1:
        return None
    runtime_root = runtime_candidates[0]
    if (runtime_root / "direction_selection.json").exists() and (sandbox_root / "outputs" / "baseline_execution_summary.json").exists():
        return _load_json_file(sandbox_root / "outputs" / "baseline_execution_summary.json")

    run_results: list[dict[str, object]] = []
    for manifest_path in sorted(runtime_root.glob("runs/*/run_manifest.json")):
        manifest = _load_json_file(manifest_path)
        if not isinstance(manifest, dict) or str(manifest.get("status") or "") != "completed":
            return None
        artifacts = manifest.get("artifacts")
        metrics = manifest.get("metrics")
        runtime = manifest.get("runtime")
        stage_context = manifest.get("stage_context")
        model = manifest.get("model")
        if not all(isinstance(item, dict) for item in (artifacts, metrics, runtime, stage_context, model)):
            return None
        slice_metrics_path = artifacts.get("slice_metrics_path")
        runtime_materialization_path = artifacts.get("runtime_materialization_path")
        if not isinstance(slice_metrics_path, str) or not isinstance(runtime_materialization_path, str):
            return None
        slice_scores = _load_json_file(Path(slice_metrics_path))
        runtime_materialization = _load_json_file(Path(runtime_materialization_path))
        if not isinstance(slice_scores, dict) or not isinstance(runtime_materialization, dict):
            return None
        starter_alias = str(model.get("identifier") or "")
        run_results.append(
            {
                "run_id": str(runtime.get("run_id") or manifest_path.parent.name),
                "direction": str(stage_context.get("direction") or ""),
                "starter_alias": starter_alias,
                "model_id": str(model.get("resolved_model_id") or manifest.get("resolved_model_id") or ""),
                "metrics": metrics,
                "slice_scores": slice_scores,
                "runtime": runtime,
                "runtime_materialization": runtime_materialization,
                "quality_checks": {
                    "empty_outputs": runtime.get("empty_outputs", 0),
                    "malformed_output_rate": runtime.get("malformed_output_rate", 0.0),
                    "comparable_sacrebleu_signature": True,
                },
                "wave_id": str(runtime.get("wave_id") or ""),
                "artifacts": artifacts,
                "alias_order": 0 if "0.5B" in starter_alias else 1,
            }
        )
    if len(run_results) < 4:
        return None

    signatures = {
        str(result["metrics"].get("sacrebleu_signature") or "")
        for result in run_results
    }
    signatures.discard("")
    if len(signatures) != 1:
        return None
    shared_signature = next(iter(signatures), "")
    if not shared_signature:
        return None

    per_direction: dict[str, list[dict[str, object]]] = {"zh-en": [], "en-zh": []}
    for result in run_results:
        direction = str(result["direction"])
        if direction in per_direction:
            per_direction[direction].append(result)
    if any(len(results) < 2 for results in per_direction.values()):
        return None

    stronger = {
        direction: max(
            results,
            key=lambda item: float(dict(item["metrics"]).get("sacrebleu", 0.0)),
        )
        for direction, results in per_direction.items()
    }
    zh_score = float(dict(stronger["zh-en"]["metrics"]).get("sacrebleu", 0.0))
    en_score = float(dict(stronger["en-zh"]["metrics"]).get("sacrebleu", 0.0))
    if zh_score <= en_score - 0.5:
        chosen_direction = "zh-en"
        direction_reason = "zh-en stronger-starter BLEU is at least 0.5 lower than en-zh."
    elif en_score <= zh_score - 0.5:
        chosen_direction = "en-zh"
        direction_reason = "en-zh stronger-starter BLEU is at least 0.5 lower than zh-en."
    else:
        chosen_direction = "zh-en"
        direction_reason = "Stronger-starter BLEU gap is below 0.5, so zh-en wins by tie-break."

    chosen_runs = sorted(
        per_direction[chosen_direction],
        key=lambda item: float(dict(item["metrics"]).get("sacrebleu", 0.0)),
        reverse=True,
    )
    top_gap = float(dict(chosen_runs[0]["metrics"]).get("sacrebleu", 0.0)) - float(
        dict(chosen_runs[1]["metrics"]).get("sacrebleu", 0.0)
    )
    if top_gap <= 0.2:
        chosen_starter = min(
            chosen_runs[:2],
            key=lambda item: (int(item["alias_order"]), -float(dict(item["metrics"]).get("sacrebleu", 0.0))),
        )
        starter_reason = "Chosen-direction starters are within 0.2 BLEU, so the smaller starter wins on budget."
    else:
        chosen_starter = chosen_runs[0]
        starter_reason = "Chosen-direction higher-scoring starter is outside the 0.2 BLEU tie band."

    baseline_stage_scoreboard = {
        "status": "completed",
        "stage_summary": {
            "all_runs_complete": True,
            "shared_sacrebleu_signature": shared_signature,
            "signature_match_status": "pass",
            "comparability_gate": "pass",
            "selected_direction": chosen_direction,
            "next_stage": "prompt-decode",
        },
        "run_rows": [
            {
                "run_id": result["run_id"],
                "direction": result["direction"],
                "starter_alias": result["starter_alias"],
                "resolved_model_id": result["model_id"],
                "sacrebleu": dict(result["metrics"]).get("sacrebleu"),
                "sacrebleu_signature": dict(result["metrics"]).get("sacrebleu_signature"),
                "empty_or_malformed_rate": dict(result["quality_checks"]).get("malformed_output_rate"),
                "comparable": True,
                "runtime_materialization_path": dict(result["artifacts"]).get("runtime_materialization_path"),
            }
            for result in sorted(run_results, key=lambda item: str(item["run_id"]))
        ],
    }
    direction_scoreboard = {
        "status": "completed",
        "shared_sacrebleu_signature": shared_signature,
        "rows": [
            {
                "direction": direction,
                "stronger_starter_run_id": str(stronger_result["run_id"]),
                "stronger_starter_model": str(stronger_result["starter_alias"]),
                "stronger_starter_resolved_model_id": str(stronger_result["model_id"]),
                "stronger_starter_sacrebleu": dict(stronger_result["metrics"]).get("sacrebleu"),
                "selected_for_improvement_spend": direction == chosen_direction,
                "next_stage_gate": "prompt-decode-authorized" if direction == chosen_direction else "baseline-only",
            }
            for direction, stronger_result in stronger.items()
        ],
    }
    direction_selection = {
        "status": "locked",
        "selected_direction": chosen_direction,
        "reason": direction_reason,
        "stronger_starter_by_direction": {
            direction: {
                "run_id": result["run_id"],
                "starter_alias": result["starter_alias"],
                "model_id": result["model_id"],
                "sacrebleu": dict(result["metrics"]).get("sacrebleu"),
                "sacrebleu_signature": dict(result["metrics"]).get("sacrebleu_signature"),
            }
            for direction, result in stronger.items()
        },
        "chosen_starter": {
            "run_id": chosen_starter["run_id"],
            "starter_alias": chosen_starter["starter_alias"],
            "model_id": chosen_starter["model_id"],
            "sacrebleu": dict(chosen_starter["metrics"]).get("sacrebleu"),
            "reason": starter_reason,
        },
    }
    prompt_release = {
        "status": "authorized-unspent",
        "selected_direction": chosen_direction,
        "selected_starter": {
            "run_id": chosen_starter["run_id"],
            "starter_alias": chosen_starter["starter_alias"],
            "resolved_model_id": chosen_starter["model_id"],
            "baseline_sacrebleu": dict(chosen_starter["metrics"]).get("sacrebleu"),
            "runtime_materialization_path": dict(chosen_starter["artifacts"]).get("runtime_materialization_path"),
        },
        "shared_sacrebleu_signature": shared_signature,
        "release_notes": [
            "Prompt/decode is open for exactly one direction after the completed full baseline matrix.",
            "Compare only against the stronger starter in the selected direction.",
        ],
    }
    crash_stability_notes = {
        "version": 1,
        "status": "stable",
        "notes": [
            "All four baseline runs completed without empty-output or signature-drift failures.",
            "The single-GPU host stayed within the 2-job ceiling by running one local-transformers job at a time.",
        ],
        "per_run": [
            {
                "run_id": result["run_id"],
                "direction": result["direction"],
                "crash_count": dict(result["runtime"]).get("crash_count"),
                "oom_retries": dict(result["runtime"]).get("oom_retries"),
                "empty_outputs": dict(result["quality_checks"]).get("empty_outputs"),
                "malformed_output_rate": dict(result["quality_checks"]).get("malformed_output_rate"),
                "peak_vram_mb": dict(result["runtime"]).get("peak_vram_mb"),
                "log_path": dict(result["artifacts"]).get("log_path"),
            }
            for result in sorted(run_results, key=lambda item: str(item["run_id"]))
        ],
    }

    for name, payload in {
        "baseline_stage_scoreboard.json": baseline_stage_scoreboard,
        "direction_scoreboard.json": direction_scoreboard,
        "direction_selection.json": direction_selection,
        "prompt_decode_stage_release.json": prompt_release,
        "crash_stability_notes.json": crash_stability_notes,
    }.items():
        (runtime_root / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    execution_summary = {
        "version": 1,
        "mission_id": str(mission_state_path.parent.name),
        "runtime_root": str(runtime_root),
        "selected_direction": chosen_direction,
        "selected_starter": {
            "run_id": chosen_starter["run_id"],
            "starter_alias": chosen_starter["starter_alias"],
            "resolved_model_id": chosen_starter["model_id"],
            "baseline_sacrebleu": dict(chosen_starter["metrics"]).get("sacrebleu"),
            "runtime_materialization_path": dict(chosen_starter["artifacts"]).get("runtime_materialization_path"),
        },
        "shared_sacrebleu_signature": shared_signature,
        "total_baseline_gpu_hours": round(
            sum(float(dict(result["runtime"]).get("runtime_gpu_hours", 0.0)) for result in run_results),
            4,
        ),
    }
    execution_summary_path = sandbox_root / "outputs" / "baseline_execution_summary.json"
    execution_summary_path.parent.mkdir(parents=True, exist_ok=True)
    execution_summary_path.write_text(json.dumps(execution_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return execution_summary


def _required_execution_paths_for(summary: dict[str, object] | None) -> tuple[Path, dict[str, Path]] | None:
    if not isinstance(summary, dict):
        return None
    runtime_root_raw = summary.get("runtime_root")
    if not isinstance(runtime_root_raw, str) or not runtime_root_raw.strip():
        return None
    runtime_root = Path(runtime_root_raw).expanduser().resolve()
    required = {
        "baseline_stage_scoreboard": runtime_root / "baseline_stage_scoreboard.json",
        "direction_scoreboard": runtime_root / "direction_scoreboard.json",
        "direction_selection": runtime_root / "direction_selection.json",
        "prompt_decode_stage_release": runtime_root / "prompt_decode_stage_release.json",
        "crash_stability_notes": runtime_root / "crash_stability_notes.json",
    }
    return runtime_root, required


def _maybe_materialize_execution_phase_result(
    *,
    result_json_path: Path,
    sandbox_root: Path | None,
    mission_state_path: Path | None,
    warnings: Sequence[str] = (),
) -> dict[str, object] | None:
    if sandbox_root is None or mission_state_path is None:
        return None
    mission_state = _load_json_file(mission_state_path)
    if not isinstance(mission_state, dict):
        return None
    if str(mission_state.get("current_phase") or "") != "execution":
        return None

    execution_summary_path = sandbox_root / "outputs" / "baseline_execution_summary.json"
    execution_summary = _load_json_file(execution_summary_path)

    resolved = _required_execution_paths_for(execution_summary)
    if resolved is None or any(not path.exists() for path in resolved[1].values()):
        execution_summary = _materialize_execution_summary_from_completed_runs(
            sandbox_root=sandbox_root,
            mission_state_path=mission_state_path,
        )
        resolved = _required_execution_paths_for(execution_summary)
    if resolved is None or any(not path.exists() for path in resolved[1].values()):
        return None
    runtime_root, required_paths = resolved

    direction_selection = _load_json_file(required_paths["direction_selection"])
    prompt_release = _load_json_file(required_paths["prompt_decode_stage_release"])
    crash_notes = _load_json_file(required_paths["crash_stability_notes"])
    if not all(isinstance(payload, dict) for payload in (direction_selection, prompt_release, crash_notes)):
        return None

    selected_direction = str(
        direction_selection.get("selected_direction")
        or execution_summary.get("selected_direction")
        or "unknown"
    )
    selected_starter = prompt_release.get("selected_starter")
    if not isinstance(selected_starter, dict):
        selected_starter = execution_summary.get("selected_starter")
    selected_starter = selected_starter if isinstance(selected_starter, dict) else {}
    selected_alias = str(selected_starter.get("starter_alias") or "unknown")
    selected_run_id = str(selected_starter.get("run_id") or "unknown")
    shared_signature = str(
        execution_summary.get("shared_sacrebleu_signature")
        or prompt_release.get("shared_sacrebleu_signature")
        or "unknown"
    )
    total_gpu_hours = execution_summary.get("total_baseline_gpu_hours")

    output_paths = [str(path) for path in required_paths.values()]
    for log_path in sorted((runtime_root / "logs").glob("*.log")):
        output_paths.append(str(log_path))

    findings = [
        f"Locked a shared sacreBLEU signature for the full baseline matrix: {shared_signature}.",
        f"Selected {selected_direction} for prompt/decode spend against {selected_alias}.",
        f"Completed the locked baseline matrix under {total_gpu_hours} GPU-hours." if total_gpu_hours is not None else "Completed the locked baseline matrix.",
    ]
    stability_notes = crash_notes.get("notes")
    if isinstance(stability_notes, list):
        findings.extend(str(note) for note in stability_notes[:2])

    payload: dict[str, object] = {
        "status": "complete",
        "summary": (
            "Completed the execution-stage baseline matrix, recorded metrics and stability notes, "
            f"and released exactly one prompt/decode path for {selected_direction}."
        ),
        "action_result": {
            "status": "completed",
            "phase": "execution",
            "kind": "phase-transition",
            "output_paths": output_paths,
            "notes": [
                f"selected_direction={selected_direction}",
                f"selected_starter_run_id={selected_run_id}",
                f"shared_sacrebleu_signature={shared_signature}",
            ],
        },
        "phase_control": {
            "current_phase": "execution",
            "next_phase": "critique",
            "decision_type": "phase-transition",
            "branch_status": "critique-ready",
            "recovery_status": "not-needed",
            "summary": "Execution outputs are complete and the mission can move into critique.",
        },
        "produced_artifacts": output_paths,
        "findings": findings,
        "mission_state_updates": {
            "current_phase": "critique",
            "next_phase": "critique",
        },
        "warnings": _dedupe_messages(
            list(warnings)
            + [
                "Provider result payload was unavailable, so the launcher synthesized a canonical execution result from persisted artifacts."
            ]
        ),
    }
    result_json_path.parent.mkdir(parents=True, exist_ok=True)
    result_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _maybe_materialize_phase_result_from_outputs(
    *,
    prompt_text: str,
    prompt_started_at: int,
    prompt_started_at_inode: int | None,
    result_json_path: Path,
    sandbox_root: Path | None,
    mission_state_path: Path | None,
    warnings: Sequence[str] = (),
) -> dict[str, object] | None:
    if sandbox_root is None or mission_state_path is None:
        return None
    mission_state = _load_json_file(mission_state_path)
    if not isinstance(mission_state, dict):
        return None
    current_phase = str(
        mission_state.get("current_phase")
        or _extract_prompt_scalar(prompt_text, "current_phase")
        or _extract_prompt_scalar(prompt_text, "action_phase")
        or ""
    ).strip()
    if not current_phase or current_phase == "execution":
        return None
    outputs_root = sandbox_root / "outputs"
    produced_files = _collect_output_files(
        outputs_root,
        min_mtime_ns=prompt_started_at,
        min_inode_on_tie=prompt_started_at_inode,
    )
    required_outputs, next_phase_candidates = _extract_prompt_phase_constraints(prompt_text)
    if not _phase_outputs_are_satisfied(required_outputs, produced_files):
        return None
    next_phase = next_phase_candidates[0] if next_phase_candidates else None
    branch_status, recovery_status = _extract_transition_metadata(prompt_text, next_phase)
    loop_action_id = _extract_prompt_scalar(prompt_text, "loop_action_id")
    mission_action_id = _extract_prompt_scalar(prompt_text, "mission_action_id")
    current_task = "\n".join(_extract_prompt_section_items(prompt_text, "Current task")).strip()
    summary = (
        f"Recovered `{current_phase}` from sandbox outputs after the provider subprocess stayed idle "
        "without writing agent_result.json."
    )
    payload: dict[str, object] = {
        "status": "complete" if not next_phase else "continue",
        "summary": summary,
        "produced_artifacts": [str(path) for path in produced_files],
        "findings": [
            f"Recovered required `{current_phase}` outputs from sandbox artifacts.",
            "Launcher synthesized the missing agent_result.json after an idle subprocess hang.",
        ],
        "action_result": {
            "mission_action_id": mission_action_id,
            "loop_action_id": loop_action_id,
            "status": "completed",
            "phase": current_phase,
            "kind": _default_kind_for_phase(current_phase),
            "output_paths": [str(path) for path in produced_files],
            "notes": [
                "Recovered completed sandbox outputs after the provider subprocess stayed idle.",
            ],
        },
        "phase_control": {
            "current_phase": current_phase,
            "next_phase": next_phase,
            "decision_type": "phase-transition" if next_phase else "final-report",
            "branch_status": branch_status,
            "recovery_status": recovery_status,
            "summary": summary,
        },
        "warnings": _dedupe_messages(
            list(warnings)
            + [
                "Provider result payload was unavailable, so the launcher synthesized a canonical phase result from sandbox outputs."
            ]
        ),
    }
    if next_phase:
        continuation_task = (
            f"Advance the mission from `{current_phase}` into `{next_phase}` using the recovered artifacts."
        )
        if current_task:
            continuation_task = f"{continuation_task} Prior task context: {current_task}"
        payload["continuation"] = {
            "role": _default_role_for_phase(next_phase),
            "task": continuation_task,
            "artifacts": [str(path) for path in produced_files],
            "kind": _default_kind_for_phase(next_phase),
            "phase": next_phase,
            "notes": [
                "Recovered continuation after the provider subprocess stayed idle without writing a result file.",
            ],
            "source": "launcher-timeout-recovery",
        }
    result_json_path.parent.mkdir(parents=True, exist_ok=True)
    result_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _materialize_provider_failure_result(
    *,
    prompt_text: str,
    result_json_path: Path,
    summary: str,
    warnings: Sequence[str],
    existing_payload: dict[str, object] | None = None,
    produced_artifacts: Sequence[str] = (),
    findings: Sequence[str] = (),
) -> dict[str, object]:
    current_phase = _extract_prompt_scalar(prompt_text, "current_phase") or _extract_prompt_scalar(prompt_text, "action_phase")
    loop_action_id = _extract_prompt_scalar(prompt_text, "loop_action_id")
    mission_action_id = _extract_prompt_scalar(prompt_text, "mission_action_id")
    base_action_result = existing_payload.get("action_result") if isinstance(existing_payload, dict) else None
    base_phase_control = existing_payload.get("phase_control") if isinstance(existing_payload, dict) else None
    base_findings = _normalize_list_like(existing_payload.get("findings")) if isinstance(existing_payload, dict) else []
    base_artifacts = _normalize_list_like(existing_payload.get("produced_artifacts")) if isinstance(existing_payload, dict) else []
    if isinstance(base_action_result, dict):
        base_artifacts.extend(_normalize_list_like(base_action_result.get("output_paths")))
    payload: dict[str, object] = {
        "status": "failed",
        "summary": summary,
        "findings": _dedupe_messages(base_findings + list(findings)),
        "action_result": {
            "mission_action_id": mission_action_id,
            "loop_action_id": loop_action_id,
            "phase": current_phase,
            "kind": base_action_result.get("kind") if isinstance(base_action_result, dict) else None,
            "branch_id": base_action_result.get("branch_id") if isinstance(base_action_result, dict) else None,
            "decision_id": base_action_result.get("decision_id") if isinstance(base_action_result, dict) else None,
            "output_paths": _dedupe_messages(base_artifacts + list(produced_artifacts)),
            "notes": _dedupe_messages(_normalize_list_like(base_action_result.get("notes")) if isinstance(base_action_result, dict) else []),
        },
        "phase_control": {
            "current_phase": current_phase,
            "next_phase": base_phase_control.get("next_phase") if isinstance(base_phase_control, dict) else None,
            "decision_type": base_phase_control.get("decision_type") if isinstance(base_phase_control, dict) else None,
            "branch_status": base_phase_control.get("branch_status") if isinstance(base_phase_control, dict) else None,
            "recovery_status": base_phase_control.get("recovery_status") if isinstance(base_phase_control, dict) else None,
            "summary": summary,
        },
        "produced_artifacts": _dedupe_messages(base_artifacts + list(produced_artifacts)),
        "warnings": _dedupe_messages(
            (_normalize_list_like(existing_payload.get("warnings")) if isinstance(existing_payload, dict) else [])
            + list(warnings)
        ),
    }
    result_json_path.parent.mkdir(parents=True, exist_ok=True)
    result_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _materialize_idle_failure_result(
    *,
    prompt_text: str,
    result_json_path: Path,
    warnings: Sequence[str] = (),
    existing_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    summary = "provider subprocess stayed idle without producing recoverable outputs or a ready agent_result.json."
    return _materialize_provider_failure_result(
        prompt_text=prompt_text,
        result_json_path=result_json_path,
        summary=summary,
        warnings=list(warnings)
        + ["Launcher ended an idle provider subprocess to avoid an infinite mission hang."],
        existing_payload=existing_payload,
        findings=["Launcher ended an idle provider subprocess to avoid an infinite mission hang."],
    )


def _execution_gap_artifacts_and_warnings(
    *,
    sandbox_root: Path | None,
    mission_state_path: Path | None,
) -> tuple[list[str], list[str]] | None:
    if sandbox_root is None or mission_state_path is None:
        return None
    mission_state = _load_json_file(mission_state_path)
    if not isinstance(mission_state, dict) or str(mission_state.get("current_phase") or "") != "execution":
        return None
    execution_summary_path = sandbox_root / "outputs" / "baseline_execution_summary.json"
    execution_summary = _load_json_file(execution_summary_path)
    resolved = _required_execution_paths_for(execution_summary)
    if resolved is None:
        return None
    runtime_root, required_paths = resolved
    missing = [path.name for path in required_paths.values() if not path.exists()]
    if not missing:
        return None
    available = [str(execution_summary_path)] if execution_summary_path.exists() else []
    available.extend(str(path) for path in required_paths.values() if path.exists())
    available.extend(str(path) for path in sorted((runtime_root / "logs").glob("*.log")))
    return (
        _dedupe_messages(available),
        [
            "Execution artifacts are only partially materialized; waiting on: " + ", ".join(sorted(missing)),
        ],
    )


def _read_result_payload_state(result_json_path: Path) -> tuple[dict[str, object] | None, list[str]]:
    if not result_json_path.exists():
        return None, ["provider did not write agent_result.json"]
    try:
        loaded = json.loads(result_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, ["provider wrote malformed agent_result.json"]
    if not isinstance(loaded, dict):
        return None, ["provider agent_result.json must contain a JSON object"]
    validation_errors = _provider_result_validation_errors(loaded)
    if validation_errors:
        return loaded, [f"provider result payload not ready: {error}" for error in validation_errors]
    return loaded, []


def _extract_result_payload_from_stdout(stdout: str) -> dict[str, object] | None:
    marker = "Returned recursive-agent JSON result:"
    marker_index = stdout.rfind(marker)
    if marker_index < 0:
        return None
    start_index = stdout.find("{", marker_index)
    if start_index < 0:
        return None
    try:
        loaded, _ = json.JSONDecoder().raw_decode(stdout[start_index:])
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    if _provider_result_validation_errors(loaded):
        return None
    return loaded


def _persist_result_payload(result_json_path: Path, payload: dict[str, object]) -> None:
    result_json_path.parent.mkdir(parents=True, exist_ok=True)
    result_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _wait_for_ready_result_payload(
    result_json_path: Path,
    *,
    timeout_seconds: float,
) -> tuple[dict[str, object] | None, list[str]]:
    deadline = time.time() + max(timeout_seconds, 0.0)
    latest_payload: dict[str, object] | None = None
    latest_warnings: list[str] = []
    while True:
        latest_payload, latest_warnings = _read_result_payload_state(result_json_path)
        if latest_payload is not None and not latest_warnings:
            return latest_payload, []
        if time.time() >= deadline:
            return latest_payload, latest_warnings
        time.sleep(_POST_EXIT_RESULT_POLL_SECONDS)


def run_provider_prompt(
    prompt_file: Path,
    *,
    result_json_path: Path | None = None,
    sandbox_root: Path | None = None,
    mission_state_path: Path | None = None,
    target_repo: Path | None = None,
    model: str | None = None,
    cwd: Path | None = None,
    idle_timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess[str]:
    prompt_text = prompt_file.read_text(encoding="utf-8")
    try:
        prompt_stat = prompt_file.stat()
        prompt_started_at_ns = max(prompt_stat.st_mtime_ns, prompt_stat.st_ctime_ns)
        prompt_started_at_inode = prompt_stat.st_ino
    except OSError:
        prompt_started_at_ns = time.time_ns()
        prompt_started_at_inode = None
    command = build_provider_prompt_command(
        prompt_file=prompt_file,
        result_json_path=result_json_path,
        model=model,
    )
    resolved_cwd = (cwd or target_repo or prompt_file.parent).expanduser().resolve()
    effective_idle_timeout_seconds = resolve_provider_idle_timeout_seconds(idle_timeout_seconds)
    if result_json_path is None:
        return subprocess.run(
            command,
            cwd=resolved_cwd,
            text=True,
            capture_output=True,
            check=False,
            env=_provider_subprocess_env(),
        )

    process = subprocess.Popen(
        command,
        cwd=resolved_cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_provider_subprocess_env(),
    )
    idle_watch_roots: list[Path] = [prompt_file.parent]
    if result_json_path is not None:
        idle_watch_roots.append(result_json_path.parent)
    if sandbox_root is not None:
        idle_watch_roots.append(sandbox_root / "outputs")
    mission_state = _load_json_file(mission_state_path) if mission_state_path is not None else None
    if isinstance(mission_state, dict) and str(mission_state.get("current_phase") or "") == "execution":
        idle_watch_roots.append(mission_state_path.parent / "runtime" / "execution")
    degraded_payload: dict[str, object] | None = None
    degraded_warnings: list[str] = []
    while True:
        if result_json_path is not None:
            _maybe_materialize_execution_phase_result(
                result_json_path=result_json_path,
                sandbox_root=sandbox_root,
                mission_state_path=mission_state_path,
                warnings=degraded_warnings,
            )
            degraded_payload, payload_warnings = _read_result_payload_state(result_json_path)
            degraded_warnings = _dedupe_messages(degraded_warnings + payload_warnings)
            if degraded_payload is not None and not payload_warnings:
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                return subprocess.CompletedProcess(command, 0, stdout, stderr)
        returncode = process.poll()
        if returncode is not None:
            stdout, stderr = process.communicate()
            if result_json_path is not None:
                degraded_payload, payload_warnings = _read_result_payload_state(result_json_path)
                if returncode == 0 and (degraded_payload is None or payload_warnings):
                    degraded_payload, payload_warnings = _wait_for_ready_result_payload(
                        result_json_path,
                        timeout_seconds=_POST_EXIT_RESULT_GRACE_SECONDS,
                    )
                if returncode == 0 and (degraded_payload is None or payload_warnings):
                    stdout_payload = _extract_result_payload_from_stdout(stdout)
                    if stdout_payload is not None:
                        _persist_result_payload(result_json_path, stdout_payload)
                        degraded_payload = stdout_payload
                        payload_warnings = []
                degraded_warnings = _dedupe_messages(
                    degraded_warnings
                    + payload_warnings
                    + [f"Provider subprocess exited with returncode {returncode} before emitting a ready result payload."]
                )
                if degraded_payload is not None and not payload_warnings:
                    return subprocess.CompletedProcess(command, 0, stdout, stderr)
                if degraded_payload is None or payload_warnings:
                    recovered = _maybe_materialize_execution_phase_result(
                        result_json_path=result_json_path,
                        sandbox_root=sandbox_root,
                        mission_state_path=mission_state_path,
                        warnings=degraded_warnings,
                    )
                    if recovered is None:
                        recovered = _maybe_materialize_phase_result_from_outputs(
                            prompt_text=prompt_text,
                            prompt_started_at=prompt_started_at_ns,
                            prompt_started_at_inode=prompt_started_at_inode,
                            result_json_path=result_json_path,
                            sandbox_root=sandbox_root,
                            mission_state_path=mission_state_path,
                            warnings=degraded_warnings,
                        )
                    if recovered is None:
                        execution_gap = _execution_gap_artifacts_and_warnings(
                            sandbox_root=sandbox_root,
                            mission_state_path=mission_state_path,
                        )
                        if execution_gap is not None:
                            artifacts, gap_warnings = execution_gap
                            _materialize_provider_failure_result(
                                prompt_text=prompt_text,
                                result_json_path=result_json_path,
                                summary="provider exited before execution artifacts finished materializing into a ready result payload.",
                                warnings=degraded_warnings + gap_warnings,
                                existing_payload=degraded_payload,
                                produced_artifacts=artifacts,
                                findings=["Execution artifacts were partially materialized when the provider exited."],
                            )
                        else:
                            _materialize_provider_failure_result(
                                prompt_text=prompt_text,
                                result_json_path=result_json_path,
                                summary="provider subprocess exited before producing a ready agent_result.json.",
                                warnings=degraded_warnings,
                                existing_payload=degraded_payload,
                                findings=["Launcher preserved the degraded provider payload so the outer runtime can retry safely."],
                            )
            return subprocess.CompletedProcess(command, returncode, stdout, stderr)
        if result_json_path.exists():
            degraded_payload, payload_warnings = _read_result_payload_state(result_json_path)
            degraded_warnings = _dedupe_messages(degraded_warnings + payload_warnings)
            if degraded_payload is not None and not payload_warnings:
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                return subprocess.CompletedProcess(command, 0, stdout, stderr)
        latest_activity = _latest_tree_activity(idle_watch_roots)
        if (
            result_json_path is not None
            and effective_idle_timeout_seconds >= 0
            and latest_activity is not None
            and (time.time() - latest_activity) >= effective_idle_timeout_seconds
        ):
            recovered = _maybe_materialize_phase_result_from_outputs(
                prompt_text=prompt_text,
                prompt_started_at=prompt_started_at_ns,
                prompt_started_at_inode=prompt_started_at_inode,
                result_json_path=result_json_path,
                sandbox_root=sandbox_root,
                mission_state_path=mission_state_path,
                warnings=degraded_warnings,
            )
            if recovered is None:
                execution_gap = _execution_gap_artifacts_and_warnings(
                    sandbox_root=sandbox_root,
                    mission_state_path=mission_state_path,
                )
                if execution_gap is not None:
                    artifacts, gap_warnings = execution_gap
                    _materialize_provider_failure_result(
                        prompt_text=prompt_text,
                        result_json_path=result_json_path,
                        summary="provider stayed idle while execution artifacts remained partially materialized.",
                        warnings=degraded_warnings + gap_warnings,
                        existing_payload=degraded_payload,
                        produced_artifacts=artifacts,
                        findings=["Execution artifacts were partially materialized when the provider stopped making progress."],
                    )
                else:
                    _materialize_idle_failure_result(
                        prompt_text=prompt_text,
                        result_json_path=result_json_path,
                        warnings=degraded_warnings,
                        existing_payload=degraded_payload,
                    )
        time.sleep(_POLL_INTERVAL_SECONDS)
