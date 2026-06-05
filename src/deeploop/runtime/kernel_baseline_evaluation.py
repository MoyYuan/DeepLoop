"""Baseline evaluation kernel.

Extracted from stage_kernels.py. All shared helpers live in stage_kernels.py.
"""

from __future__ import annotations

from pathlib import Path

from deeploop.runtime.stage_kernels import (
    UNKNOWN_MISSION_ID,
    KernelRunResult,
    StageAdapter,
    _adapter_runtime_contract,
    _autotune_execution_plan,
    _build_manifest,
    _build_runtime_report,
    _configure_adapter_model_family,
    _configure_adapter_prompt,
    _dataset_name,
    _load_dataset_bundle,
    _load_yaml,
    _normalize_notes,
    _run_predictions,
    _runtime_manifest_payload,
    _runtime_telemetry_metrics,
    _selection_slice,
    _validate_manifest,
    _write_json,
)


def run_baseline_evaluation(config_path: Path, *, adapter: StageAdapter) -> KernelRunResult:
    config = _load_yaml(config_path)
    dataset_cfg = config["dataset"]
    selection = dataset_cfg["selection"]
    prompt_cfg = config.get("prompt", {})
    promotion_manifest_path = Path(
        dataset_cfg.get("promotion_manifest", str(adapter.default_promotion_manifest()))
    ).expanduser()
    dataset_bundle = _load_dataset_bundle(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        tiers=selection.get("tiers"),
        split_kinds=selection.get("split_kinds"),
        split_families=selection.get("split_families"),
        lexicalizations=selection.get("lexicalizations"),
        rule_families=selection.get("rule_families"),
        limit=dataset_cfg.get("limit_examples"),
    )

    model_cfg = config["model"]
    _configure_adapter_model_family(adapter, model_cfg)
    _configure_adapter_prompt(adapter, prompt_cfg)
    model_identifier = model_cfg.get("identifier", model_cfg.get("checkpoint", model_cfg.get("label", "")))
    prompt_samples = [adapter.format_prompt(example) for example, _ in dataset_bundle["examples"]]
    runtime_model_cfg = {
        "family": model_cfg.get("family"),
        "identifier": model_identifier,
        "backend": model_cfg.get("backend"),
        "dtype": str(model_cfg.get("dtype", "float16")),
        "max_new_tokens": int(model_cfg.get("max_new_tokens", 32) or 32),
    }
    execution_plan, predictor = _autotune_execution_plan(
        "baseline-evaluation",
        execution_profile=str(config["execution_profile"]),
        model_cfg=runtime_model_cfg,
        prompts=prompt_samples,
        runtime_contract=_adapter_runtime_contract(adapter),
    )
    manifest_model = {
        "family": model_cfg["family"],
        "identifier": model_identifier,
        "backend": execution_plan.resolved_backend,
        "dtype": str(model_cfg.get("dtype", "float16")),
        "max_new_tokens": int(execution_plan.max_new_tokens),
    }

    output_dir = Path(config["run"]["output_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "predictions.jsonl"
    metrics_path = output_dir / "metrics.json"
    manifest_path = output_dir / "run_manifest.json"
    runtime_report_path = output_dir / "runtime_report.json"

    records = _run_predictions(
        adapter,
        predictor,
        dataset_bundle["examples"],
        predictions_path=predictions_path,
    )
    runtime_report = _build_runtime_report(
        stage_id="baseline-evaluation",
        execution_plan=execution_plan,
        predictor=predictor,
        model=manifest_model,
        output_dir=output_dir,
    )
    _write_json(runtime_report_path, runtime_report)
    runtime_manifest_payload = _runtime_manifest_payload(runtime_report)
    metrics = {**adapter.compute_metrics(records), **_runtime_telemetry_metrics(runtime_report)}
    _write_json(metrics_path, metrics)

    manifest = _build_manifest(
        adapter=adapter,
        stage_id="baseline-evaluation",
        loop_id=config["run"]["loop_id"],
        mode=config["mode"],
        claim_state=config["claim_state"],
        mission_id=config.get("mission_id", UNKNOWN_MISSION_ID),
        resource_tier=config["resource_tier"],
        execution_profile=config["execution_profile"],
        model=manifest_model,
        dataset={
            "name": _dataset_name(adapter, dataset_bundle["promotion_manifest"]),
            "slice": _selection_slice(dataset_bundle["selected_files"]),
            "provenance": str(promotion_manifest_path),
        },
        prompt={
            "template_id": prompt_cfg.get("template_id", adapter.prompt_template_id),
            "parser_id": prompt_cfg.get("parser_id", getattr(adapter, "parser_id", "unknown-parser")),
        },
        output_dir=output_dir,
        command=f"baseline-evaluation --config {config_path}",
        seed=int(config["run"].get("seed", 0)),
        notes=_normalize_notes(config["run"].get("notes", [])),
        metrics=metrics,
        stage_context={
            "selection": selection,
            "dataset_record_count": len(dataset_bundle["examples"]),
            "config_path": str(config_path),
            "execution_contract": runtime_manifest_payload["execution_plan"],
            "runtime_telemetry": runtime_manifest_payload["telemetry"],
            "runtime_budget": runtime_manifest_payload["budget"],
            "capabilities": runtime_manifest_payload["capabilities"],
            "runtime_autotune": runtime_manifest_payload["autotune"],
            "execution_search": runtime_manifest_payload["execution_search"],
            "artifacts": {
                "predictions_path": str(predictions_path),
                "metrics_path": str(metrics_path),
                "runtime_report_path": str(runtime_report_path),
            },
        },
        report_paths=[str(runtime_report_path)],
        runtime_payload={
            "execution_profile": runtime_manifest_payload["execution_plan"],
            "telemetry": runtime_manifest_payload["telemetry"],
            "budget": runtime_manifest_payload["budget"],
            "capabilities": runtime_manifest_payload["capabilities"],
            "autotune": runtime_manifest_payload["autotune"],
            "execution_search": runtime_manifest_payload["execution_search"],
            "runtime_report_path": str(runtime_report_path),
        },
    )
    _validate_manifest(manifest)
    _write_json(manifest_path, manifest)

    return KernelRunResult(
        stage_id="baseline-evaluation",
        status="completed",
        output_dir=output_dir,
        manifest_path=manifest_path,
        artifacts={
            "predictions": predictions_path,
            "metrics": metrics_path,
            "runtime_report": runtime_report_path,
            "manifest": manifest_path,
        },
    )
