"""Causal intervention kernel.

Extracted from stage_kernels.py. All shared helpers live in stage_kernels.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deeploop.autonomy.gate_taxonomy import DEFAULT_OPERATING_MODE
from deeploop.runtime.stage_kernels import (
    UNKNOWN_MISSION_ID,
    KernelRunResult,
    StageAdapter,
    ZONE_ORDER,
    _adapter_runtime_contract,
    _assign_proxy_unit,
    _autotune_execution_plan,
    _build_manifest,
    _build_runtime_report,
    _configure_adapter_model_family,
    _configure_adapter_prompt,
    _dataset_name,
    _load_dataset_bundle,
    _load_json,
    _load_yaml,
    _merge_model_config,
    _normalize_notes,
    _run_predictions,
    _runtime_manifest_payload,
    _runtime_telemetry_metrics,
    _selection_slice,
    _units_from_layer_spec,
    _validate_manifest,
    _write_json,
    _write_jsonl,
)


def _strength_factor(strength: str) -> float:
    lowered = strength.lower()
    if "large" in lowered or "strong" in lowered:
        return 0.85
    if "medium" in lowered or "sweep" in lowered:
        return 0.65
    return 0.45


def _flip_label(label: str) -> str:
    lowered = label.lower()
    if lowered == "entailment":
        return "contradiction"
    if lowered == "contradiction":
        return "entailment"
    return "unparsed"


def _select_target_units(target_layers: Any, candidates: list[dict]) -> list[str]:
    requested_units = _units_from_layer_spec(target_layers)
    available_units = [candidate["unit_id"] for candidate in candidates if candidate["normalized_score"] >= 0]
    if not available_units:
        available_units = [candidate["unit_id"] for candidate in candidates]
    intersection = [unit for unit in requested_units if unit in available_units]
    if intersection:
        return intersection
    return available_units[:2] if len(available_units) > 1 else available_units


def _apply_intervention_proxy(
    baseline_records: list[dict],
    *,
    candidates: list[dict],
    targeted_units: list[str],
    strength: str,
    side_effect_response: str,
    metric_fn: Any,
) -> tuple[list[dict], dict]:
    candidate_map = {candidate["unit_id"]: candidate for candidate in candidates}
    allowed_units = targeted_units or [candidate["unit_id"] for candidate in candidates] or list(ZONE_ORDER)
    strength_factor = _strength_factor(strength)

    max_score = max((max(candidate["normalized_score"], 0.0) for candidate in candidates), default=1.0) or 1.0
    post_records: list[dict] = []
    recoveries = 0
    side_effect_count = 0
    originally_correct = 0

    for record in baseline_records:
        post_record = dict(record)
        candidate_unit = _assign_proxy_unit(record, allowed_units)
        candidate = candidate_map.get(candidate_unit, {"normalized_score": 0.0, "dominant_split_families": []})
        score_factor = max(candidate.get("normalized_score", 0.0), 0.0) / max_score
        targeted = candidate_unit in targeted_units
        was_correct = record.get("predicted_label") == record.get("gold_label")
        if was_correct:
            originally_correct += 1

        effect = "unchanged"
        if targeted and not was_correct and (strength_factor + score_factor) >= 0.75:
            post_record["predicted_label"] = post_record["gold_label"]
            effect = "recovered"
            recoveries += 1
        else:
            dominant_splits = set(candidate.get("dominant_split_families", []))
            collateral_slice = targeted and was_correct and record.get("split_family") not in dominant_splits
            if collateral_slice and strength_factor >= 0.8 and "reduce" not in side_effect_response:
                post_record["predicted_label"] = _flip_label(str(post_record.get("predicted_label", "unparsed")))
                effect = "collateral"
                side_effect_count += 1
            elif collateral_slice:
                effect = "attenuated"

        post_record["candidate_unit"] = candidate_unit
        post_record["intervention_applied"] = targeted
        post_record["intervention_effect"] = effect
        post_records.append(post_record)

    pre_metrics = metric_fn(baseline_records)
    post_metrics = metric_fn(post_records)
    post_correct = sum(1 for record in post_records if record.get("predicted_label") == record.get("gold_label"))
    pre_correct = sum(1 for record in baseline_records if record.get("predicted_label") == record.get("gold_label"))
    accuracy_delta = (
        round(post_metrics["accuracy"] - pre_metrics["accuracy"], 6)
        if pre_metrics.get("accuracy") is not None and post_metrics.get("accuracy") is not None
        else None
    )
    side_effect_rate = round(side_effect_count / originally_correct, 6) if originally_correct else None

    metrics = {
        "pre_metrics": pre_metrics,
        "post_metrics": post_metrics,
        "recoveries": recoveries,
        "side_effect_count": side_effect_count,
        "side_effect_rate": side_effect_rate,
        "accuracy_delta": accuracy_delta,
        "pre_correct": pre_correct,
        "post_correct": post_correct,
        "targeted_units": targeted_units,
    }
    return post_records, metrics


def run_causal_intervention(config_path: Path, *, adapter: StageAdapter) -> KernelRunResult:
    config = _load_yaml(config_path)
    localization_source = Path(config["localization_source"]).expanduser()
    study_id = config["study_id"]
    output_dir = Path(config.get("run", {}).get("output_dir", adapter.runs_root / study_id)).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "study_summary.json"
    predictions_path = output_dir / "intervention_predictions.jsonl"
    metrics_path = output_dir / "intervention_metrics.json"
    manifest_path = output_dir / "study_manifest.json"

    compare_manifest_path = Path(config["evaluation"]["compare_against"]).expanduser()
    compare_manifest = _load_json(compare_manifest_path)

    if not localization_source.exists():
        summary = {
            "study_id": study_id,
            "phase": config["phase"],
            "status": "blocked",
            "localization_source": str(localization_source),
            "compare_against": str(compare_manifest_path),
            "notes": _normalize_notes(config.get("reporting", {}).get("notes", [])),
        }
        _write_json(summary_path, summary)
        manifest = _build_manifest(
            adapter=adapter,
            stage_id="causal-intervention",
            loop_id=study_id,
            mode=DEFAULT_OPERATING_MODE,
            claim_state="exploratory",
            mission_id=compare_manifest.get("mission_id", UNKNOWN_MISSION_ID),
            resource_tier=compare_manifest.get("resource_tier", "cpu-smoke"),
            execution_profile=compare_manifest.get("execution_profile", "intervention-proxy"),
            model=_merge_model_config(config.get("model", {}), compare_manifest.get("model", {})),
            dataset=compare_manifest.get("dataset", {}),
            prompt=compare_manifest.get("prompt", {}),
            output_dir=output_dir,
            command=f"causal-intervention --config {config_path}",
            seed=int(config.get("run", {}).get("seed", 0)),
            notes=_normalize_notes(
                [
                    "Blocked because localization evidence is missing.",
                    config.get("reporting", {}).get("notes", []),
                ]
            ),
            metrics={"localization_source_exists": False},
            stage_context={
                "localization_source": str(localization_source),
                "compare_against": str(compare_manifest_path),
                "proxy_kernel": True,
            },
            report_paths=[str(summary_path)],
            status="blocked",
        )
        _validate_manifest(manifest)
        _write_json(manifest_path, manifest)
        return KernelRunResult(
            stage_id="causal-intervention",
            status="blocked",
            output_dir=output_dir,
            manifest_path=manifest_path,
            summary_path=summary_path,
            artifacts={"summary": summary_path, "manifest": manifest_path},
        )

    localization_manifest = _load_json(localization_source)
    candidates_path = Path(
        localization_manifest.get("stage_context", {})
        .get("artifacts", {})
        .get("candidates_path", localization_source.parent / "localization_candidates.json")
    ).expanduser()
    candidates_payload = _load_json(candidates_path)
    candidates = candidates_payload.get("candidate_units", [])
    dataset_filters = dict(localization_manifest.get("stage_context", {}).get("dataset_filters", {}))
    promotion_manifest_path = Path(
        localization_manifest.get("dataset", {}).get("provenance")
        or compare_manifest.get("dataset", {}).get("provenance")
        or adapter.default_promotion_manifest()
    ).expanduser()
    dataset_bundle = _load_dataset_bundle(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        tiers=dataset_filters.get("tiers"),
        split_kinds=dataset_filters.get("split_kinds"),
        split_families=dataset_filters.get("split_families"),
        lexicalizations=dataset_filters.get("lexicalizations"),
        rule_families=dataset_filters.get("rule_families"),
        limit=dataset_filters.get("limit_examples"),
    )

    model_cfg = _merge_model_config(config.get("model", {}), compare_manifest.get("model", {}))
    prompt_cfg = compare_manifest.get("prompt", config.get("prompt", {}))
    _configure_adapter_model_family(adapter, model_cfg)
    _configure_adapter_prompt(adapter, prompt_cfg)
    prompt_samples = [adapter.format_prompt(example) for example, _ in dataset_bundle["examples"]]
    execution_plan, predictor = _autotune_execution_plan(
        "causal-intervention",
        execution_profile=str(compare_manifest.get("execution_profile", "intervention-proxy")),
        model_cfg=model_cfg,
        prompts=prompt_samples,
        runtime_contract=_adapter_runtime_contract(adapter),
    )
    model_cfg["backend"] = execution_plan.resolved_backend
    model_cfg["max_new_tokens"] = int(execution_plan.max_new_tokens)
    baseline_records = _run_predictions(
        adapter,
        predictor,
        dataset_bundle["examples"],
        predictions_path=None,
    )
    runtime_report_path = output_dir / "runtime_report.json"
    runtime_report = _build_runtime_report(
        stage_id="causal-intervention",
        execution_plan=execution_plan,
        predictor=predictor,
        model=model_cfg,
        output_dir=output_dir,
    )
    _write_json(runtime_report_path, runtime_report)
    runtime_manifest_payload = _runtime_manifest_payload(runtime_report)
    targeted_units = _select_target_units(config["model"].get("target_layers"), candidates)
    post_records, intervention_metrics = _apply_intervention_proxy(
        baseline_records,
        candidates=candidates,
        targeted_units=targeted_units,
        strength=str(config["intervention"].get("strength", "small")),
        side_effect_response=str(config["intervention"].get("side_effect_response", "preserve")).lower(),
        metric_fn=adapter.compute_metrics,
    )
    _write_jsonl(predictions_path, post_records)
    _write_json(metrics_path, intervention_metrics)

    summary = {
        "study_id": study_id,
        "phase": config["phase"],
        "status": "completed",
        "localization_source": str(localization_source),
        "compare_against": str(compare_manifest_path),
        "targeted_units": targeted_units,
        "accuracy_delta": intervention_metrics["accuracy_delta"],
        "notes": _normalize_notes(
            [
                "DeepLoop runnable kernel executed a deterministic intervention proxy rather than a prep-only gate.",
                config.get("reporting", {}).get("notes", []),
            ]
        ),
    }
    _write_json(summary_path, summary)

    manifest = _build_manifest(
        adapter=adapter,
        stage_id="causal-intervention",
        loop_id=study_id,
        mode=DEFAULT_OPERATING_MODE,
        claim_state="exploratory",
        mission_id=compare_manifest.get("mission_id", UNKNOWN_MISSION_ID),
        resource_tier=compare_manifest.get("resource_tier", "cpu-smoke"),
        execution_profile=compare_manifest.get("execution_profile", "intervention-proxy"),
        model=model_cfg,
        dataset={
            "name": _dataset_name(adapter, dataset_bundle["promotion_manifest"]),
            "slice": _selection_slice(dataset_bundle["selected_files"]),
            "provenance": str(promotion_manifest_path),
        },
        prompt=prompt_cfg
        if isinstance(prompt_cfg, dict)
        else {"template_id": adapter.prompt_template_id, "parser_id": getattr(adapter, "parser_id", "unknown-parser")},
        output_dir=output_dir,
        command=f"causal-intervention --config {config_path}",
        seed=int(config.get("run", {}).get("seed", 0)),
        notes=_normalize_notes(
            [
                "Deterministic proxy intervention; model-internals execution remains future work.",
                config.get("reporting", {}).get("notes", []),
            ]
        ),
        metrics={
            "accuracy_pre": intervention_metrics["pre_metrics"].get("accuracy"),
            "accuracy_post": intervention_metrics["post_metrics"].get("accuracy"),
            "accuracy_delta": intervention_metrics["accuracy_delta"],
            "recoveries": intervention_metrics["recoveries"],
            "side_effect_count": intervention_metrics["side_effect_count"],
            "side_effect_rate": intervention_metrics["side_effect_rate"],
            **_runtime_telemetry_metrics(runtime_report),
        },
        stage_context={
            "localization_source": str(localization_source),
            "compare_against": str(compare_manifest_path),
            "targeted_units": targeted_units,
            "dataset_filters": dataset_filters,
            "execution_contract": runtime_manifest_payload["execution_plan"],
            "runtime_telemetry": runtime_manifest_payload["telemetry"],
            "runtime_budget": runtime_manifest_payload["budget"],
            "capabilities": runtime_manifest_payload["capabilities"],
            "runtime_autotune": runtime_manifest_payload["autotune"],
            "execution_search": runtime_manifest_payload["execution_search"],
            "artifacts": {
                "summary_path": str(summary_path),
                "predictions_path": str(predictions_path),
                "metrics_path": str(metrics_path),
                "candidates_path": str(candidates_path),
                "runtime_report_path": str(runtime_report_path),
            },
            "proxy_kernel": True,
            "intervention": config.get("intervention", {}),
        },
        report_paths=[str(summary_path), str(metrics_path), str(runtime_report_path)],
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
        stage_id="causal-intervention",
        status="completed",
        output_dir=output_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
        artifacts={
            "summary": summary_path,
            "predictions": predictions_path,
            "metrics": metrics_path,
            "runtime_report": runtime_report_path,
            "manifest": manifest_path,
        },
    )
