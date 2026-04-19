from __future__ import annotations

import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from deeploop.core.paths import REPO_ROOT as DEEPLOOP_REPO_ROOT

RUN_MANIFEST_TEMPLATE_PATH = DEEPLOOP_REPO_ROOT / "configs" / "manifests" / "run-manifest-template.json"
RUN_MANIFEST_SCHEMA_PATH = DEEPLOOP_REPO_ROOT / "schemas" / "run-manifest.schema.json"


def git_commit(repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return completed.stdout.strip()
    except FileNotFoundError:
        pass
    return "nogit"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_manifest(manifest: dict[str, Any], *, load_json: Callable[[Path], dict[str, Any]]) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    schema = load_json(RUN_MANIFEST_SCHEMA_PATH)
    jsonschema.validate(manifest, schema)


def build_runtime_report(
    *,
    stage_id: str,
    execution_plan: Any,
    predictor: Any,
    model: dict[str, Any],
    output_dir: Path,
    runtime_capability_probe: Callable[..., dict[str, Any]],
    empty_runtime_stats: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    runtime_stats = dict(getattr(predictor, "runtime_stats", empty_runtime_stats()))
    budget = dict(runtime_stats.get("budget", {}))
    budget["gpu_memory_headroom_gb"] = execution_plan.gpu_memory_headroom_gb
    budget["fallback_ladder"] = list(execution_plan.fallback_ladder)
    capability_probe = runtime_capability_probe(predictor, execution_plan=execution_plan, model=model)
    return {
        "schema_version": 1,
        "generated_at": now_utc(),
        "stage_id": stage_id,
        "output_dir": str(output_dir),
        "execution_profile": execution_plan.requested_profile,
        "execution_plan": execution_plan.to_dict(),
        "model": {
            "family": model.get("family"),
            "identifier": model.get("identifier"),
            "requested_backend": execution_plan.requested_backend,
            "resolved_backend": execution_plan.resolved_backend,
            "dtype": model.get("dtype"),
        },
        "telemetry": {
            "started_at": runtime_stats.get("started_at"),
            "completed_at": runtime_stats.get("completed_at"),
            "elapsed_s": runtime_stats.get("elapsed_s"),
            "executed_examples": runtime_stats.get("executed_examples", 0),
            "prompt_tokens_total": runtime_stats.get("prompt_tokens_total", 0),
            "prompt_tokens_max": runtime_stats.get("prompt_tokens_max", 0),
            "generated_tokens_total": runtime_stats.get("generated_tokens_total", 0),
            "generated_tokens_max": runtime_stats.get("generated_tokens_max", 0),
            "peak_vram_mb": runtime_stats.get("peak_vram_mb"),
            "toks_per_s": runtime_stats.get("toks_per_s"),
            "samples_per_s": runtime_stats.get("samples_per_s"),
            "ttft_s": runtime_stats.get("ttft_s"),
            "oom_retries": runtime_stats.get("oom_retries", 0),
            "batch_adjustments": runtime_stats.get("batch_adjustments", []),
            "batch_requests": runtime_stats.get("batch_requests", []),
        },
        "budget": budget,
        "capabilities": capability_probe,
        "autotune": runtime_stats.get("autotune", {}),
        "execution_search": runtime_stats.get("execution_search", {}),
        "summary": (
            f"{stage_id} executed with backend `{execution_plan.resolved_backend}` "
            f"on bucket `{execution_plan.context_bucket or 'unbounded'}`."
        ),
    }


def runtime_telemetry_metrics(runtime_report: dict[str, Any]) -> dict[str, Any]:
    telemetry = runtime_report.get("telemetry", {})
    budget = runtime_report.get("budget", {})
    autotune = runtime_report.get("autotune", {})
    return {
        "peak_vram_mb": telemetry.get("peak_vram_mb"),
        "toks_per_s": telemetry.get("toks_per_s"),
        "ttft_s": telemetry.get("ttft_s"),
        "oom_retries": telemetry.get("oom_retries"),
        "prompt_tokens_total": telemetry.get("prompt_tokens_total"),
        "prompt_tokens_max": telemetry.get("prompt_tokens_max"),
        "generated_tokens_total": telemetry.get("generated_tokens_total"),
        "batch_size": budget.get("selected_batch_size"),
        "prompt_token_utilization": budget.get("prompt_token_utilization"),
        "autotune_batch_size": autotune.get("selected_batch_size"),
        "autotune_cache_status": autotune.get("cache", {}).get("status"),
        "autotune_warning_count": len(autotune.get("warnings", [])),
        "autotune_peak_vram_utilization": autotune.get("selected_peak_vram_utilization"),
        "execution_search_status": runtime_report.get("execution_search", {}).get("status"),
    }


def runtime_manifest_payload(runtime_report: dict[str, Any]) -> dict[str, Any]:
    telemetry = runtime_report.get("telemetry", {})
    budget = runtime_report.get("budget", {})
    return {
        "execution_plan": runtime_report.get("execution_plan", {}),
        "telemetry": {
            "elapsed_s": telemetry.get("elapsed_s"),
            "executed_examples": telemetry.get("executed_examples"),
            "peak_vram_mb": telemetry.get("peak_vram_mb"),
            "toks_per_s": telemetry.get("toks_per_s"),
            "ttft_s": telemetry.get("ttft_s"),
            "oom_retries": telemetry.get("oom_retries"),
        },
        "budget": {
            "prompt_token_budget": budget.get("prompt_token_budget"),
            "prompt_token_utilization": budget.get("prompt_token_utilization"),
            "max_new_tokens": budget.get("max_new_tokens"),
            "selected_batch_size": budget.get("selected_batch_size"),
            "batch_probe_order": budget.get("batch_probe_order"),
            "gpu_memory_headroom_gb": budget.get("gpu_memory_headroom_gb"),
        },
        "capabilities": runtime_report.get("capabilities", {}),
        "autotune": runtime_report.get("autotune", {}),
        "execution_search": runtime_report.get("execution_search", {}),
    }


def build_manifest(
    *,
    adapter: Any,
    stage_id: str,
    loop_id: str,
    mode: str,
    claim_state: str,
    mission_id: str | None,
    resource_tier: str,
    execution_profile: str,
    model: dict[str, Any],
    dataset: dict[str, Any],
    prompt: dict[str, Any],
    output_dir: Path,
    command: str,
    seed: int,
    notes: list[str],
    metrics: dict[str, Any],
    stage_context: dict[str, Any],
    report_paths: list[str],
    stage_registry_contract_path: Path,
    load_json: Callable[[Path], dict[str, Any]],
    runtime_context: dict[str, Any] | None = None,
    runtime_payload: dict[str, Any] | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    manifest = deepcopy(load_json(RUN_MANIFEST_TEMPLATE_PATH))
    manifest["project"] = adapter.substrate_name
    manifest["mode"] = mode
    manifest["loop_id"] = loop_id
    manifest["claim_state"] = claim_state
    manifest["mission_id"] = mission_id
    manifest["resource_tier"] = resource_tier
    manifest["execution_profile"] = execution_profile
    manifest["code"] = {
        "repo": str(DEEPLOOP_REPO_ROOT),
        "git_commit": git_commit(DEEPLOOP_REPO_ROOT),
    }
    manifest["substrate_code"] = {
        "repo": str(adapter.substrate_repo_root),
        "git_commit": git_commit(adapter.substrate_repo_root),
    }
    manifest["model"] = model
    manifest["dataset"] = dataset
    manifest["prompt"] = prompt
    now = now_utc()
    manifest["run"] = {
        "seed": seed,
        "command": command,
        "started_at": now,
        "completed_at": now,
        "status": status,
    }
    manifest["metrics"] = metrics
    manifest["artifacts"] = {
        "log_path": None,
        "output_dir": str(output_dir),
        "report_paths": report_paths,
    }
    resolved_runtime_context = dict(runtime_context or {})
    if runtime_payload:
        resolved_runtime_context = {**resolved_runtime_context, **runtime_payload}
    if resolved_runtime_context:
        manifest["runtime"] = resolved_runtime_context
        if resolved_runtime_context.get("history_path"):
            manifest["artifacts"]["runtime_history_path"] = resolved_runtime_context.get("history_path")
    manifest["notes"] = notes
    manifest["stage"] = {
        "id": stage_id,
        "kernel_owner": "deeploop",
        "registry_contract": str(stage_registry_contract_path),
        "adapter": adapter.name,
    }
    manifest["stage_context"] = stage_context
    return manifest
