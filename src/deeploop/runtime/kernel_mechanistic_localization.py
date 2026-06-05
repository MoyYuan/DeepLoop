"""Mechanistic localization kernel.

Extracted from stage_kernels.py. All shared helpers live in stage_kernels.py.
"""

from __future__ import annotations

from pathlib import Path

from deeploop.autonomy.operating_modes import DEFAULT_OPERATING_MODE
from deeploop.runtime.stage_kernels import (
    UNKNOWN_MISSION_ID,
    KernelRunResult,
    StageAdapter,
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


def _mechanistic_proxy_outputs(records: list[dict], *, allowed_units: list[str], methods: dict) -> tuple[list[dict], list[dict]]:
    grouped: dict[str, dict] = {
        unit: {
            "examples": 0,
            "failing_examples": 0,
            "proxy_recovery_score": 0.0,
            "proxy_collateral_risk": 0.0,
            "rule_counts": {},
            "split_counts": {},
        }
        for unit in allowed_units
    }
    observations: list[dict] = []

    for record in records:
        candidate_unit = _assign_proxy_unit(record, allowed_units)
        is_correct = record.get("predicted_label") == record.get("gold_label")
        chain_len = int(record.get("chain_len", 0) or 0)
        recovery_weight = 1.0 + (0.2 * min(chain_len, 5)) + (0.3 if record.get("split_family") != "iid" else 0.0)
        collateral_risk = 0.15 + (0.1 if record.get("lex") == "delex" else 0.0)
        observation = {
            **record,
            "candidate_unit": candidate_unit,
            "was_correct": is_correct,
            "recovery_score_proxy": round(recovery_weight if not is_correct else 0.0, 6),
            "collateral_risk_proxy": round(collateral_risk if is_correct else collateral_risk / 2, 6),
        }
        observations.append(observation)

        bucket = grouped[candidate_unit]
        bucket["examples"] += 1
        bucket["proxy_collateral_risk"] += observation["collateral_risk_proxy"]
        rule = str(record.get("rule", "unknown"))
        split_family = str(record.get("split_family", "unknown"))
        bucket["rule_counts"][rule] = bucket["rule_counts"].get(rule, 0) + 1
        bucket["split_counts"][split_family] = bucket["split_counts"].get(split_family, 0) + 1
        if not is_correct:
            bucket["failing_examples"] += 1
            bucket["proxy_recovery_score"] += observation["recovery_score_proxy"]

    enabled_methods = [name for name, enabled in methods.items() if enabled]
    candidates: list[dict] = []
    for unit, payload in grouped.items():
        examples = payload["examples"]
        normalized_score = payload["proxy_recovery_score"] - (0.5 * payload["proxy_collateral_risk"])
        dominant_rules = sorted(payload["rule_counts"], key=payload["rule_counts"].get, reverse=True)[:3]
        dominant_splits = sorted(payload["split_counts"], key=payload["split_counts"].get, reverse=True)[:3]
        candidates.append(
            {
                "unit_id": unit,
                "examples": examples,
                "failing_examples": payload["failing_examples"],
                "error_rate": round(payload["failing_examples"] / examples, 6) if examples else None,
                "proxy_recovery_score": round(payload["proxy_recovery_score"], 6),
                "proxy_collateral_risk": round(payload["proxy_collateral_risk"], 6),
                "normalized_score": round(normalized_score, 6),
                "dominant_rule_families": dominant_rules,
                "dominant_split_families": dominant_splits,
                "methods": enabled_methods,
            }
        )
    candidates.sort(key=lambda item: item["normalized_score"], reverse=True)
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    return observations, candidates


def run_mechanistic_localization(config_path: Path, *, adapter: StageAdapter) -> KernelRunResult:
    config = _load_yaml(config_path)
    source_manifest_path = Path(config["behavioral_source_manifest"]).expanduser()
    source_manifest = _load_json(source_manifest_path)
    study_id = config["study_id"]
    output_dir = Path(config.get("run", {}).get("output_dir", adapter.runs_root / study_id)).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "study_summary.json"
    observations_path = output_dir / "localization_observations.jsonl"
    candidates_path = output_dir / "localization_candidates.json"
    manifest_path = output_dir / "study_manifest.json"

    dataset_cfg = config["dataset"]
    promotion_manifest_path = Path(
        source_manifest.get("dataset", {}).get("provenance", adapter.default_promotion_manifest())
    ).expanduser()
    dataset_bundle = _load_dataset_bundle(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        tiers=dataset_cfg.get("tiers"),
        split_kinds=dataset_cfg.get("split_kinds"),
        split_families=dataset_cfg.get("split_families"),
        lexicalizations=dataset_cfg.get("lexicalizations"),
        rule_families=dataset_cfg.get("rule_families"),
        limit=dataset_cfg.get("limit_examples"),
    )

    model_cfg = _merge_model_config(config.get("model", {}), source_manifest.get("model", {}))
    prompt_cfg = source_manifest.get("prompt", config.get("prompt", {}))
    _configure_adapter_model_family(adapter, model_cfg)
    _configure_adapter_prompt(adapter, prompt_cfg)
    prompt_samples = [adapter.format_prompt(example) for example, _ in dataset_bundle["examples"]]
    execution_plan, predictor = _autotune_execution_plan(
        "mechanistic-localization",
        execution_profile=str(source_manifest.get("execution_profile", "mechanistic-proxy")),
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
        stage_id="mechanistic-localization",
        execution_plan=execution_plan,
        predictor=predictor,
        model=model_cfg,
        output_dir=output_dir,
    )
    _write_json(runtime_report_path, runtime_report)
    runtime_manifest_payload = _runtime_manifest_payload(runtime_report)
    metrics = {**adapter.compute_metrics(baseline_records), **_runtime_telemetry_metrics(runtime_report)}
    allowed_units = _units_from_layer_spec(config["model"].get("layer_selection"))
    observations, candidates = _mechanistic_proxy_outputs(
        baseline_records,
        allowed_units=allowed_units,
        methods=config.get("methods", {}),
    )
    _write_jsonl(observations_path, observations)
    _write_json(candidates_path, {"study_id": study_id, "candidate_units": candidates})

    top_candidate = candidates[0] if candidates else None
    summary = {
        "study_id": study_id,
        "phase": config["phase"],
        "status": "completed",
        "behavioral_source_manifest": str(source_manifest_path),
        "source_accuracy": source_manifest.get("metrics", {}).get("accuracy"),
        "executed_examples": len(observations),
        "candidate_units": [candidate["unit_id"] for candidate in candidates],
        "top_candidate": top_candidate["unit_id"] if top_candidate else None,
        "methods": config.get("methods", {}),
        "notes": _normalize_notes(
            [
                "DeepLoop runnable kernel executed a deterministic localization proxy rather than a prep-only bundle.",
                config.get("reporting", {}).get("notes", []),
            ]
        ),
    }
    _write_json(summary_path, summary)

    manifest = _build_manifest(
        adapter=adapter,
        stage_id="mechanistic-localization",
        loop_id=study_id,
        mode=DEFAULT_OPERATING_MODE,
        claim_state="exploratory",
        mission_id=source_manifest.get("mission_id", UNKNOWN_MISSION_ID),
        resource_tier=source_manifest.get("resource_tier", "cpu-smoke"),
        execution_profile=source_manifest.get("execution_profile", "mechanistic-proxy"),
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
        command=f"mechanistic-localization --config {config_path}",
        seed=int(config.get("run", {}).get("seed", 0)),
        notes=_normalize_notes(
            [
                "Deterministic proxy localization; model-internals execution remains future work.",
                config.get("reporting", {}).get("notes", []),
            ]
        ),
        metrics={
            "executed_examples": len(observations),
            "baseline_accuracy": metrics.get("accuracy"),
            "top_candidate_score": top_candidate["normalized_score"] if top_candidate else None,
            "candidate_count": len(candidates),
            **_runtime_telemetry_metrics(runtime_report),
        },
        stage_context={
            "behavioral_source_manifest": str(source_manifest_path),
            "dataset_filters": dataset_cfg,
            "methods": config.get("methods", {}),
            "candidate_units": candidates,
            "execution_contract": runtime_manifest_payload["execution_plan"],
            "runtime_telemetry": runtime_manifest_payload["telemetry"],
            "runtime_budget": runtime_manifest_payload["budget"],
            "capabilities": runtime_manifest_payload["capabilities"],
            "runtime_autotune": runtime_manifest_payload["autotune"],
            "execution_search": runtime_manifest_payload["execution_search"],
            "artifacts": {
                "summary_path": str(summary_path),
                "observations_path": str(observations_path),
                "candidates_path": str(candidates_path),
                "runtime_report_path": str(runtime_report_path),
            },
            "proxy_kernel": True,
        },
        report_paths=[str(summary_path), str(candidates_path), str(runtime_report_path)],
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
        stage_id="mechanistic-localization",
        status="completed",
        output_dir=output_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
        artifacts={
            "summary": summary_path,
            "observations": observations_path,
            "candidates": candidates_path,
            "runtime_report": runtime_report_path,
            "manifest": manifest_path,
        },
    )
