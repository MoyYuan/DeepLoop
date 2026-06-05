"""Prompt/decode sweep kernel.

Extracted from stage_kernels.py. All shared helpers live in stage_kernels.py.
"""

from __future__ import annotations

import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from deeploop.autonomy.operating_modes import DEFAULT_OPERATING_MODE
from deeploop.runtime.stage_kernels import (
    KernelRunResult,
    StageAdapter,
    _adapter_runtime_contract,
    _autotune_execution_plan,
    _build_manifest,
    _build_runtime_report,
    _configure_adapter_prompt,
    _dataset_name,
    _load_dataset_bundle,
    _load_json,
    _load_yaml,
    _normalize_generation_config,
    _normalize_notes,
    _run_predictions,
    _validate_manifest,
    _write_json,
)


def _string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    return [str(raw)]


def _metric_path(raw: Any, *, default: tuple[str, ...]) -> tuple[str, ...]:
    path = tuple(_string_list(raw))
    return path or tuple(default)


def _metric_at_path(payload: Any, metric_path: tuple[str, ...]) -> float | None:
    current = payload
    for key in metric_path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    if current is None:
        return None
    return float(current)


def _prompt_sweep_reference_value(payload: Any, metric_path: tuple[str, ...]) -> float | None:
    if not isinstance(payload, dict):
        return None
    direct = _metric_at_path(payload, metric_path)
    if direct is not None:
        return direct
    if len(metric_path) >= 2 and metric_path[-1] == "score":
        current = payload.get(metric_path[0])
        if isinstance(current, (int, float)):
            return float(current)
    return None


def _prompt_sweep_selected_starter_reference(
    selected_starter: dict[str, Any],
    metric_path: tuple[str, ...],
) -> float | None:
    if not metric_path:
        return None
    metric_name = metric_path[0]
    candidate_keys = (
        f"locked_baseline_{metric_name}",
        f"baseline_{metric_name}",
        metric_name,
    )
    for key in candidate_keys:
        value = selected_starter.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _prompt_sweep_output_paths(config: dict[str, Any], *, direction: str, runtime_root: Path) -> dict[str, Path]:
    run_cfg = config.get("run", {})
    output_dir = Path(
        run_cfg.get("output_dir", runtime_root / "runs" / f"prompt-{direction}")
    ).expanduser()
    reports_dir = Path(config.get("reports_dir", runtime_root / "reports")).expanduser()
    return {
        "output_dir": output_dir,
        "reports_dir": reports_dir,
        "scoreboard_path": reports_dir / "prompt_decode_scoreboard.json",
        "promotion_decision_path": reports_dir / "prompt_decode_promotion_decision.json",
        "diagnostic_slice_audit_path": reports_dir / "diagnostic_slice_audit.json",
        "summary_path": output_dir / "summary.json",
        "crash_notes_path": Path(config.get("crash_notes_path", runtime_root / "crash_stability_notes.json")).expanduser(),
    }


def _prompt_sweep_selection_config(
    dataset_materialization: dict[str, Any],
    key: str,
    direction: str,
) -> dict[str, Any]:
    defaults = {
        "primary_dev_selection": {"tiers": ["primary-dev"], "split_kinds": ["primary-dev"]},
        "secondary_holdout_selection": {"tiers": ["secondary-holdout"], "split_kinds": ["secondary-holdout"]},
        "final_test_selection": {"tiers": ["final-test"], "split_kinds": ["final-test"]},
    }
    selection = deepcopy(defaults.get(key, {}))
    selection.update(deepcopy(dataset_materialization.get(key, {})))
    selection["split_families"] = _string_list(selection.get("split_families")) or [direction]
    if "limit_examples" not in selection and dataset_materialization.get("limit_examples") is not None:
        selection["limit_examples"] = int(dataset_materialization["limit_examples"])
    return selection


def _prompt_sweep_selection(
    adapter: StageAdapter,
    *,
    promotion_manifest_path: Path,
    selection: dict[str, Any],
) -> dict[str, Any]:
    return _load_dataset_bundle(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        tiers=_string_list(selection.get("tiers")),
        split_kinds=_string_list(selection.get("split_kinds")),
        split_families=_string_list(selection.get("split_families")),
        lexicalizations=_string_list(selection.get("lexicalizations")) or None,
        rule_families=_string_list(selection.get("rule_families")) or None,
        limit=int(selection["limit_examples"]) if selection.get("limit_examples") is not None else None,
    )


def _prompt_sweep_model_config(config: dict[str, Any]) -> dict[str, Any]:
    runtime_lock = dict(config.get("runtime_lock", {}))
    selected_starter = dict(config.get("selected_starter", {}))
    identifier = (
        runtime_lock.get("resolved_model_path")
        or runtime_lock.get("resolved_model_id")
        or selected_starter.get("resolved_model_id")
        or config.get("model", {}).get("identifier")
    )
    if not identifier:
        raise ValueError("prompt-decode-sweep requires a resolved model path or identifier in runtime_lock.")
    family = str(
        runtime_lock.get("family")
        or config.get("model", {}).get("family")
        or ("qwen3.5" if "qwen" in str(identifier).lower() else "unknown")
    )
    return {
        "family": family,
        "identifier": str(identifier),
        "backend": str(runtime_lock.get("backend", config.get("model", {}).get("backend", "local-transformers"))),
        "dtype": str(runtime_lock.get("dtype", config.get("model", {}).get("dtype", "float16"))),
        "max_new_tokens": int(
            runtime_lock.get("max_new_tokens", config.get("model", {}).get("max_new_tokens", 256)) or 256
        ),
    }


def _decode_policy_config(raw_decode: Any, *, decode_policy: Any, max_new_tokens: int) -> dict[str, Any]:
    if isinstance(raw_decode, dict):
        return _normalize_generation_config(raw_decode, max_new_tokens=max_new_tokens)
    policy = str(decode_policy or "greedy")
    if policy == "greedy":
        return _normalize_generation_config(
            {
                "do_sample": False,
                "temperature": 0.0,
                "top_p": 1.0,
                "repetition_penalty": 1.0,
                "max_new_tokens": max_new_tokens,
            },
            max_new_tokens=max_new_tokens,
        )
    if policy == "temperature-0.2":
        return _normalize_generation_config(
            {
                "do_sample": True,
                "temperature": 0.2,
                "top_p": 0.95,
                "repetition_penalty": 1.02,
                "max_new_tokens": max_new_tokens,
            },
            max_new_tokens=max_new_tokens,
        )
    raise ValueError(f"Unsupported prompt/decode policy: {policy}")


def _prompt_sweep_split_execution(
    adapter: StageAdapter,
    predictor: Any,
    *,
    examples: list[tuple[dict, dict]],
    split_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / f"{split_id}_predictions.jsonl"
    metrics_path = output_dir / f"{split_id}_metrics.json"
    started = time.monotonic()
    records = _run_predictions(adapter, predictor, examples, predictions_path=predictions_path)
    elapsed_s = max(time.monotonic() - started, 1e-9)
    metrics = adapter.compute_metrics(records)
    _write_json(metrics_path, metrics)
    return {
        "records": records,
        "metrics": metrics,
        "runtime_gpu_hours": round(elapsed_s / 3600.0, 6),
        "artifacts": {
            "predictions_path": str(predictions_path),
            "metrics_path": str(metrics_path),
        },
    }


def _prompt_sweep_prompt_samples(
    adapter: StageAdapter,
    examples: list[tuple[dict, dict]],
) -> list[str]:
    sample_examples = examples[: min(len(examples), 4)]
    return [adapter.format_prompt(example) for example, _ in sample_examples]


def _run_prompt_sweep_variant(
    *,
    adapter: StageAdapter,
    stage_id: str,
    execution_profile: str,
    model_cfg: dict[str, Any],
    variant: dict[str, Any],
    decode_config: dict[str, Any],
    primary_examples: list[tuple[dict, dict]],
    holdout_examples: list[tuple[dict, dict]],
    output_dir: Path,
    seed: int,
) -> dict[str, Any]:
    _configure_adapter_prompt(adapter, {"template_id": variant["template_id"]})
    prompt_samples = _prompt_sweep_prompt_samples(adapter, primary_examples or holdout_examples)
    execution_plan, predictor = _autotune_execution_plan(
        stage_id,
        execution_profile=execution_profile,
        model_cfg=model_cfg,
        prompts=prompt_samples,
        runtime_contract=_adapter_runtime_contract(adapter),
        decode_config=decode_config,
    )
    primary_run = _prompt_sweep_split_execution(
        adapter,
        predictor,
        examples=primary_examples,
        split_id="primary_dev",
        output_dir=output_dir,
    )
    holdout_run = _prompt_sweep_split_execution(
        adapter,
        predictor,
        examples=holdout_examples,
        split_id="secondary_holdout",
        output_dir=output_dir,
    )
    runtime_report = _build_runtime_report(
        stage_id=stage_id,
        execution_plan=execution_plan,
        predictor=predictor,
        model=model_cfg,
        output_dir=output_dir,
    )
    runtime_report_path = output_dir / "runtime_report.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(runtime_report_path, runtime_report)
    return {
        "prompt_family": str(variant.get("prompt_family", variant.get("template_id", "unknown"))),
        "primary_metrics": primary_run["metrics"],
        "holdout_metrics": holdout_run["metrics"],
        "primary_runtime_gpu_hours": primary_run["runtime_gpu_hours"],
        "holdout_runtime_gpu_hours": holdout_run["runtime_gpu_hours"],
        "runtime_gpu_hours": round(primary_run["runtime_gpu_hours"] + holdout_run["runtime_gpu_hours"], 6),
        "execution_plan": execution_plan.to_dict(),
        "seed": seed,
        "artifacts": {
            "primary_dev": primary_run["artifacts"],
            "secondary_holdout": holdout_run["artifacts"],
            "runtime_report_path": str(runtime_report_path),
        },
    }


def _run_prompt_sweep_baseline_anchor(
    *,
    adapter: StageAdapter,
    stage_id: str,
    execution_profile: str,
    model_cfg: dict[str, Any],
    template_id: str,
    final_examples: list[tuple[dict, dict]],
    output_dir: Path,
    seed: int,
) -> dict[str, Any]:
    _configure_adapter_prompt(adapter, {"template_id": template_id})
    prompt_samples = _prompt_sweep_prompt_samples(adapter, final_examples)
    execution_plan, predictor = _autotune_execution_plan(
        stage_id,
        execution_profile=execution_profile,
        model_cfg=model_cfg,
        prompts=prompt_samples,
        runtime_contract=_adapter_runtime_contract(adapter),
    )
    final_run = _prompt_sweep_split_execution(
        adapter,
        predictor,
        examples=final_examples,
        split_id="final_test",
        output_dir=output_dir,
    )
    runtime_report = _build_runtime_report(
        stage_id=stage_id,
        execution_plan=execution_plan,
        predictor=predictor,
        model=model_cfg,
        output_dir=output_dir,
    )
    runtime_report_path = output_dir / "runtime_report.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(runtime_report_path, runtime_report)
    return {
        "metrics": final_run["metrics"],
        "runtime_gpu_hours": final_run["runtime_gpu_hours"],
        "summary": {
            "template_id": template_id,
            "score": _metric_at_path(final_run["metrics"], ("sacrebleu", "score"))
            if _metric_at_path(final_run["metrics"], ("sacrebleu", "score")) is not None
            else final_run["metrics"],
            "artifacts": {
                **final_run["artifacts"],
                "runtime_report_path": str(runtime_report_path),
            },
            "seed": seed,
        },
    }


def _run_prompt_sweep_final_candidate(
    *,
    adapter: StageAdapter,
    stage_id: str,
    execution_profile: str,
    model_cfg: dict[str, Any],
    variant: dict[str, Any],
    decode_config: dict[str, Any],
    final_examples: list[tuple[dict, dict]],
    output_dir: Path,
    seed: int,
) -> dict[str, Any]:
    final_output_dir = output_dir / "final-test"
    _configure_adapter_prompt(adapter, {"template_id": variant["template_id"]})
    prompt_samples = _prompt_sweep_prompt_samples(adapter, final_examples)
    execution_plan, predictor = _autotune_execution_plan(
        stage_id,
        execution_profile=execution_profile,
        model_cfg=model_cfg,
        prompts=prompt_samples,
        runtime_contract=_adapter_runtime_contract(adapter),
        decode_config=decode_config,
    )
    final_run = _prompt_sweep_split_execution(
        adapter,
        predictor,
        examples=final_examples,
        split_id="final_test",
        output_dir=final_output_dir,
    )
    runtime_report = _build_runtime_report(
        stage_id=stage_id,
        execution_plan=execution_plan,
        predictor=predictor,
        model=model_cfg,
        output_dir=final_output_dir,
    )
    runtime_report_path = final_output_dir / "runtime_report.json"
    final_output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(runtime_report_path, runtime_report)
    return {
        "metrics": final_run["metrics"],
        "runtime_gpu_hours": final_run["runtime_gpu_hours"],
        "artifacts": {
            **final_run["artifacts"],
            "runtime_report_path": str(runtime_report_path),
        },
        "seed": seed,
    }


def _select_best_prompt_variant(
    executed_results: list[dict[str, Any]],
    *,
    metric_path: tuple[str, ...],
) -> dict[str, Any]:
    def _sort_key(item: dict[str, Any]) -> tuple[float, float]:
        primary_score = _metric_at_path(item["result"]["primary_metrics"], metric_path)
        holdout_score = _metric_at_path(item["result"]["holdout_metrics"], metric_path)
        return (
            float(primary_score if primary_score is not None else float("-inf")),
            float(holdout_score if holdout_score is not None else float("-inf")),
        )

    return max(executed_results, key=_sort_key)


def _prompt_sweep_promotion_rules(config: dict[str, Any]) -> dict[str, Any]:
    default_rules = {
        "full_set_gain_threshold": 0.3,
        "slice_signal_override": {
            "required_slice_gain": 0.8,
            "required_slice_count": 2,
            "max_full_set_regression": -0.2,
            "eligible_slice_ids": [],
        },
    }
    rules = deepcopy(default_rules)
    rules.update(deepcopy(config.get("promotion_rules", {})))
    override = dict(default_rules["slice_signal_override"])
    override.update(deepcopy(rules.get("slice_signal_override", {})))
    override["eligible_slice_ids"] = _string_list(override.get("eligible_slice_ids"))
    rules["slice_signal_override"] = override
    return rules


def _prompt_sweep_slice_override(
    *,
    baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
    metric_path: tuple[str, ...],
    full_set_gain: float,
    override_rules: dict[str, Any],
) -> dict[str, Any]:
    slice_gains: dict[str, Any] = {}
    winning_slice_ids: list[str] = []
    required_gain = float(override_rules.get("required_slice_gain", 0.8))
    eligible_slice_ids = _string_list(override_rules.get("eligible_slice_ids"))
    baseline_slices = dict(baseline_metrics.get("diagnostic_slices", {}))
    candidate_slices = dict(candidate_metrics.get("diagnostic_slices", {}))
    for slice_id in eligible_slice_ids:
        baseline_score = _metric_at_path(baseline_slices.get(slice_id), metric_path)
        candidate_score = _metric_at_path(candidate_slices.get(slice_id), metric_path)
        if baseline_score is None or candidate_score is None:
            continue
        gain = round(candidate_score - baseline_score, 4)
        slice_gains[slice_id] = {
            "baseline": baseline_score,
            "candidate": candidate_score,
            "gain_vs_baseline": gain,
            "count": candidate_slices.get(slice_id, {}).get("count"),
        }
        if gain >= required_gain:
            winning_slice_ids.append(slice_id)
    max_full_set_regression = float(override_rules.get("max_full_set_regression", -0.2))
    required_count = int(override_rules.get("required_slice_count", 2))
    return {
        "passes": full_set_gain >= max_full_set_regression and len(winning_slice_ids) >= required_count,
        "winning_slice_ids": winning_slice_ids,
        "slice_gains": slice_gains,
    }


def _prompt_sweep_reference_payload(
    config: dict[str, Any],
    *,
    metric_path: tuple[str, ...],
    baseline_anchor: dict[str, Any],
) -> dict[str, Any]:
    promotion_reference = dict(config.get("promotion_reference", {}))
    selected_starter = dict(config.get("selected_starter", {}))
    reference_metrics_path = promotion_reference.get("baseline_metrics_path") or promotion_reference.get("metrics_path")
    reference_metrics = None
    if reference_metrics_path:
        reference_metrics = _load_json(Path(reference_metrics_path).expanduser())
    reference_score = None
    for candidate in (
        _prompt_sweep_reference_value(reference_metrics, metric_path),
        _prompt_sweep_reference_value(promotion_reference.get("reference_numbers"), metric_path),
        _prompt_sweep_selected_starter_reference(selected_starter, metric_path),
    ):
        if candidate is not None:
            reference_score = round(float(candidate), 4)
            break
    if reference_score is not None:
        return {
            "kind": str(promotion_reference.get("kind", "locked-baseline")),
            "label": str(
                promotion_reference.get("label")
                or promotion_reference.get("kind")
                or "locked-baseline"
            ),
            "run_id": promotion_reference.get("baseline_run_id") or selected_starter.get("locked_baseline_run_id"),
            "metrics_path": str(reference_metrics_path) if reference_metrics_path else None,
            "metrics": reference_metrics,
            "score": reference_score,
            "scoring_signatures": dict(promotion_reference.get("scoring_signatures", {})),
        }
    anchor_score = _metric_at_path(baseline_anchor["metrics"], metric_path)
    return {
        "kind": "baseline-anchor",
        "label": "baseline-anchor-replay",
        "run_id": None,
        "metrics_path": baseline_anchor["summary"]["artifacts"]["metrics_path"],
        "metrics": baseline_anchor["metrics"],
        "score": round(float(anchor_score), 4) if anchor_score is not None else None,
        "scoring_signatures": {},
    }


def _prompt_sweep_baseline_anchor_preflight(
    *,
    reference: dict[str, Any],
    baseline_anchor: dict[str, Any],
) -> dict[str, Any]:
    expected_signatures = dict(reference.get("scoring_signatures", {}))
    reference_metrics = reference.get("metrics")
    if not expected_signatures and isinstance(reference_metrics, dict):
        for metric_name in ("sacrebleu", "chrf"):
            metric_payload = reference_metrics.get(metric_name)
            if isinstance(metric_payload, dict) and metric_payload.get("signature"):
                expected_signatures[metric_name] = str(metric_payload["signature"])
    checks: list[dict[str, Any]] = []
    if not expected_signatures:
        return {
            "status": "not-applicable",
            "reference_kind": reference["kind"],
            "checks": checks,
        }
    for metric_name, expected in sorted(expected_signatures.items()):
        actual = None
        metric_payload = baseline_anchor["metrics"].get(metric_name)
        if isinstance(metric_payload, dict):
            actual = metric_payload.get("signature")
        checks.append(
            {
                "metric": metric_name,
                "expected": expected,
                "actual": actual,
                "status": "passed" if expected == actual else "failed",
            }
        )
    failures = [item for item in checks if item["status"] != "passed"]
    if failures:
        raise ValueError(
            "Prompt/decode baseline-anchor preflight failed: "
            + "; ".join(
                f"{item['metric']} expected {item['expected']} got {item['actual']}"
                for item in failures
            )
        )
    return {
        "status": "passed",
        "reference_kind": reference["kind"],
        "checks": checks,
    }


def _prompt_sweep_slice_metric(metric_payload: Any, metric_name: str) -> dict[str, Any]:
    nested = metric_payload.get(metric_name) if isinstance(metric_payload, dict) else None
    if isinstance(nested, dict):
        return {
            "score": nested.get("score"),
            "signature": nested.get("signature"),
        }
    return {
        "score": None,
        "signature": None,
    }


def _prompt_sweep_delta(candidate_value: Any, reference_value: Any) -> float | None:
    if candidate_value is None or reference_value is None:
        return None
    return round(float(candidate_value) - float(reference_value), 4)


def _prompt_sweep_diagnostic_slice_audit(
    *,
    direction: str,
    best_variant: dict[str, Any],
    reference: dict[str, Any],
    reference_metrics: dict[str, Any] | None,
    candidate_metrics: dict[str, Any],
    eligible_slice_ids: list[str],
) -> dict[str, Any]:
    reference_slices = dict(reference_metrics.get("diagnostic_slices", {})) if isinstance(reference_metrics, dict) else {}
    candidate_slices = dict(candidate_metrics.get("diagnostic_slices", {}))
    slices: dict[str, Any] = {}
    issues: list[str] = []
    for slice_id in eligible_slice_ids:
        reference_slice = reference_slices.get(slice_id, {})
        candidate_slice = candidate_slices.get(slice_id, {})
        candidate_count = candidate_slice.get("count") if isinstance(candidate_slice, dict) else None
        reference_count = reference_slice.get("count") if isinstance(reference_slice, dict) else None
        count = candidate_count if candidate_count is not None else reference_count
        if not isinstance(candidate_slice, dict):
            issues.append(f"missing-candidate-slice:{slice_id}")
        if count is None:
            issues.append(f"missing-count:{slice_id}")
        slices[slice_id] = {
            "count": count,
            "sacrebleu": _prompt_sweep_slice_metric(candidate_slice, "sacrebleu"),
            "chrf": _prompt_sweep_slice_metric(candidate_slice, "chrf"),
            "output_length_ratio": (
                candidate_slice.get("output_length_ratio") if isinstance(candidate_slice, dict) else None
            ),
            "reference_count": reference_count,
            "reference_sacrebleu": _prompt_sweep_slice_metric(reference_slice, "sacrebleu"),
            "reference_chrf": _prompt_sweep_slice_metric(reference_slice, "chrf"),
            "reference_output_length_ratio": (
                reference_slice.get("output_length_ratio") if isinstance(reference_slice, dict) else None
            ),
            "delta": {
                "sacrebleu": _prompt_sweep_delta(
                    _metric_at_path(candidate_slice, ("sacrebleu", "score")),
                    _metric_at_path(reference_slice, ("sacrebleu", "score")),
                ),
                "chrf": _prompt_sweep_delta(
                    _metric_at_path(candidate_slice, ("chrf", "score")),
                    _metric_at_path(reference_slice, ("chrf", "score")),
                ),
                "output_length_ratio": _prompt_sweep_delta(
                    candidate_slice.get("output_length_ratio") if isinstance(candidate_slice, dict) else None,
                    reference_slice.get("output_length_ratio") if isinstance(reference_slice, dict) else None,
                ),
            },
            "status": "ok" if count is not None and isinstance(candidate_slice, dict) else "incomplete",
        }
    return {
        "version": 1,
        "stage_id": "prompt-decode",
        "direction": direction,
        "reference": {
            "kind": reference["kind"],
            "label": reference["label"],
            "run_id": reference.get("run_id"),
            "metrics_path": reference.get("metrics_path"),
        },
        "candidate": {
            "variant_id": str(best_variant["variant_id"]),
        },
        "required_slice_ids": eligible_slice_ids,
        "clean": not issues,
        "issues": issues,
        "slices": slices,
    }


def _prompt_sweep_promotion_decision(
    *,
    best_variant: dict[str, Any],
    best_row: dict[str, Any],
    best_result: dict[str, Any],
    final_result: dict[str, Any],
    reference: dict[str, Any],
    baseline_anchor: dict[str, Any],
    baseline_anchor_preflight: dict[str, Any],
    slice_override: dict[str, Any],
    promotion_rules: dict[str, Any],
    metric_path: tuple[str, ...],
) -> dict[str, Any]:
    gain_vs_reference = best_row.get("wmt19_final", {}).get("gain_vs_reference", 0.0)
    full_set_gain_threshold = float(promotion_rules.get("full_set_gain_threshold", 0.3))
    promoted = gain_vs_reference >= full_set_gain_threshold
    if not promoted and slice_override.get("passes"):
        promoted = True
    return {
        "decision": "promoted" if promoted else "not-promoted",
        "best_candidate": {
            "variant_id": best_variant["variant_id"],
            "gain_vs_reference": gain_vs_reference,
            "reference_kind": reference.get("kind", "unknown"),
            "prompt_family": best_result.get("prompt_family", ""),
            "primary_score": _metric_at_path(best_result.get("primary_metrics", {}), metric_path),
            "holdout_score": _metric_at_path(best_result.get("holdout_metrics", {}), metric_path),
            "final_score": _metric_at_path(final_result.get("metrics", {}), metric_path),
            "reference_score": reference.get("score"),
        },
        "reference": {
            "kind": reference.get("kind", "unknown"),
            "score": reference.get("score"),
            "label": reference.get("label", ""),
        },
        "baseline_anchor": {
            "score": _metric_at_path(baseline_anchor.get("metrics", {}), metric_path),
            "status": baseline_anchor_preflight.get("status", "passed"),
        },
        "slice_override": slice_override,
        "promotion_rules": {
            "full_set_gain_threshold": full_set_gain_threshold,
        },
    }


def _prompt_sweep_replication_gate(
    config: dict[str, Any],
    *,
    output_paths: dict[str, Path],
    manifest_path: Path,
    slice_audit: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    gate_cfg = dict(config.get("replication_gate", {}))
    required_artifacts = _string_list(gate_cfg.get("required_artifacts"))
    if not required_artifacts:
        required_artifacts = [
            str(manifest_path),
            str(output_paths["scoreboard_path"]),
            str(output_paths["promotion_decision_path"]),
            str(output_paths["summary_path"]),
            str(output_paths["diagnostic_slice_audit_path"]),
        ]
    artifact_statuses = [
        {
            "path": path,
            "exists": Path(path).expanduser().exists(),
        }
        for path in required_artifacts
    ]
    follow_up_manifest_complete = all(item["exists"] for item in artifact_statuses)
    follow_up_manifest_clean = (
        follow_up_manifest_complete
        and bool(slice_audit.get("clean"))
        and reference["kind"] != "baseline-anchor"
    )
    return {
        "status": "closed",
        "policy_status": str(gate_cfg.get("status", "closed-until-clean-follow-up")),
        "follow_up_manifest_complete": follow_up_manifest_complete,
        "follow_up_manifest_clean": follow_up_manifest_clean,
        "required_artifacts": required_artifacts,
        "artifact_statuses": artifact_statuses,
        "reason": (
            "Execution produced a follow-up package, but replication remains closed until critique reviews the clean manifest bundle."
        ),
    }


def _update_prompt_sweep_crash_notes(
    path: Path,
    *,
    summary: dict[str, Any],
    scoreboard_path: Path,
    promotion_decision_path: Path,
    summary_path: Path,
    diagnostic_slice_audit_path: Path,
) -> None:
    payload = {}
    if path.exists():
        loaded = _load_json(path)
        if isinstance(loaded, dict):
            payload = loaded
    payload["prompt_decode_stage"] = {
        "status": summary["status"],
        "executed_variant_ids": summary["executed_variant_ids"],
        "skipped_variant_ids": summary["skipped_variant_ids"],
        "issues": [],
        "artifacts": {
            "scoreboard_path": str(scoreboard_path),
            "promotion_decision_path": str(promotion_decision_path),
            "diagnostic_slice_audit_path": str(diagnostic_slice_audit_path),
            "summary_path": str(summary_path),
        },
    }
    _write_json(path, payload)


def run_prompt_decode_sweep(config_path: Path, *, adapter: StageAdapter) -> KernelRunResult:
    config = _load_yaml(config_path)
    direction = str(config["selected_direction"])
    runtime_root = Path(config.get("runtime_root", adapter.runs_root)).expanduser()
    output_paths = _prompt_sweep_output_paths(config, direction=direction, runtime_root=runtime_root)
    output_dir = output_paths["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths["reports_dir"].mkdir(parents=True, exist_ok=True)
    dataset_materialization = dict(config.get("dataset_materialization", {}))
    promotion_manifest_path = Path(
        dataset_materialization.get("promotion_manifest_path", adapter.default_promotion_manifest())
    ).expanduser()
    primary_bundle = _prompt_sweep_selection(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        selection=_prompt_sweep_selection_config(dataset_materialization, "primary_dev_selection", direction),
    )
    holdout_bundle = _prompt_sweep_selection(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        selection=_prompt_sweep_selection_config(dataset_materialization, "secondary_holdout_selection", direction),
    )
    final_bundle = _prompt_sweep_selection(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        selection=_prompt_sweep_selection_config(dataset_materialization, "final_test_selection", direction),
    )
    model_cfg = _prompt_sweep_model_config(config)
    runtime_lock = dict(config.get("runtime_lock", {}))
    locked_context_bucket = str(runtime_lock.get("context_bucket", "short"))
    metric_path = _metric_path(config.get("metric_path"), default=("sacrebleu", "score"))
    diagnostic_metric_path = _metric_path(
        config.get("diagnostic_metric_path"),
        default=tuple(metric_path),
    )
    promotion_rules = _prompt_sweep_promotion_rules(config)
    loop_id = str(config.get("run", {}).get("loop_id", f"prompt-decode-{direction}"))
    seed = int(config.get("run", {}).get("seed", 0))
    variant_matrix = list(config.get("variant_matrix", []))[: int(config.get("max_variants", len(config.get("variant_matrix", []))))]
    rows: list[dict[str, Any]] = []
    executed_results: list[dict[str, Any]] = []
    total_stage_gpu_hours = 0.0

    for raw_variant in variant_matrix:
        variant = deepcopy(raw_variant)
        variant_id = str(variant["variant_id"])
        context_bucket = str(variant.get("context_bucket", locked_context_bucket))
        if context_bucket != locked_context_bucket:
            rows.append(
                {
                    "variant_id": variant_id,
                    "status": "skipped",
                    "prompt_family": variant.get("prompt_family", variant.get("template_id")),
                    "context_bucket": context_bucket,
                    "trusted_source_ids": list(variant.get("trusted_source_ids", [])),
                    "skip_reason": (
                        f"context_bucket={context_bucket} drifts from locked runtime "
                        f"context_bucket={locked_context_bucket}"
                    ),
                }
            )
            continue
        decode_config = _decode_policy_config(
            variant.get("decode"),
            decode_policy=variant.get("decode_policy"),
            max_new_tokens=int(model_cfg.get("max_new_tokens", 32) or 32),
        )
        variant_result = _run_prompt_sweep_variant(
            adapter=adapter,
            stage_id="prompt-decode-sweep",
            execution_profile=str(config["execution_profile"]),
            model_cfg=model_cfg,
            variant=variant,
            decode_config=decode_config,
            primary_examples=primary_bundle["examples"],
            holdout_examples=holdout_bundle["examples"],
            output_dir=output_dir / variant_id,
            seed=seed,
        )
        total_stage_gpu_hours += float(variant_result["runtime_gpu_hours"])
        row = {
            "variant_id": variant_id,
            "status": "completed",
            "prompt_family": variant_result["prompt_family"],
            "context_bucket": context_bucket,
            "trusted_source_ids": list(variant.get("trusted_source_ids", [])),
            "wmt18_primary": {
                "score": _metric_at_path(variant_result["primary_metrics"], metric_path),
                "runtime_gpu_hours": round(float(variant_result["primary_runtime_gpu_hours"]), 6),
            },
            "wmt17_holdout": {
                "score": _metric_at_path(variant_result["holdout_metrics"], metric_path),
                "runtime_gpu_hours": round(float(variant_result["holdout_runtime_gpu_hours"]), 6),
            },
            "artifacts": variant_result["artifacts"],
        }
        executed_results.append(
            {
                "variant": variant,
                "decode_config": decode_config,
                "result": variant_result,
                "row": row,
            }
        )
        rows.append(row)

    if not executed_results:
        raise ValueError("Prompt/decode sweep had no executable variants under the current runtime contract.")

    best_executed = _select_best_prompt_variant(executed_results, metric_path=metric_path)
    baseline_anchor_cfg = dict(config.get("baseline_anchor_replay", {}))
    baseline_anchor_template_id = str(baseline_anchor_cfg.get("template_id", "baseline-plain-v1"))
    baseline_anchor = _run_prompt_sweep_baseline_anchor(
        adapter=adapter,
        stage_id="prompt-decode-sweep",
        execution_profile=str(config["execution_profile"]),
        model_cfg=model_cfg,
        template_id=baseline_anchor_template_id,
        final_examples=final_bundle["examples"],
        output_dir=output_dir / "baseline-anchor",
        seed=seed,
    )
    total_stage_gpu_hours += float(baseline_anchor["runtime_gpu_hours"])
    final_result = _run_prompt_sweep_final_candidate(
        adapter=adapter,
        stage_id="prompt-decode-sweep",
        execution_profile=str(config["execution_profile"]),
        model_cfg=model_cfg,
        variant=best_executed["variant"],
        decode_config=best_executed["decode_config"],
        final_examples=final_bundle["examples"],
        output_dir=output_dir / best_executed["variant"]["variant_id"],
        seed=seed,
    )
    total_stage_gpu_hours += float(final_result["runtime_gpu_hours"])
    best_row = best_executed["row"]
    final_score = _metric_at_path(final_result["metrics"], metric_path)
    if final_score is None:
        raise ValueError("Prompt/decode sweep final candidate metrics are missing the requested metric.")
    promotion_reference = _prompt_sweep_reference_payload(
        config,
        metric_path=metric_path,
        baseline_anchor=baseline_anchor,
    )
    baseline_anchor_preflight = _prompt_sweep_baseline_anchor_preflight(
        reference=promotion_reference,
        baseline_anchor=baseline_anchor,
    )
    best_row["wmt19_final"] = {
        "score": final_score,
        "runtime_gpu_hours": round(float(final_result["runtime_gpu_hours"]), 6),
    }
    if promotion_reference["score"] is None:
        raise ValueError("Prompt/decode sweep promotion reference is missing the requested metric.")
    full_set_gain = round(
        float(final_score) - float(promotion_reference["score"]),
        4,
    )
    reference_metrics = promotion_reference.get("metrics")
    slice_override = _prompt_sweep_slice_override(
        baseline_metrics=reference_metrics if isinstance(reference_metrics, dict) else {},
        candidate_metrics=final_result["metrics"],
        metric_path=diagnostic_metric_path,
        full_set_gain=full_set_gain,
        override_rules=promotion_rules["slice_signal_override"],
    )
    best_row["wmt19_final"]["gain_vs_reference"] = full_set_gain
    best_row["wmt19_final"]["reference_label"] = promotion_reference["label"]
    if promotion_reference["kind"] == "baseline-anchor":
        best_row["wmt19_final"]["gain_vs_baseline_anchor"] = full_set_gain
    else:
        best_row["wmt19_final"]["gain_vs_locked_baseline"] = full_set_gain
    required_slice_ids = _string_list(
        dict(config.get("slice_audit", {})).get("required_slice_ids")
    ) or _string_list(promotion_rules["slice_signal_override"].get("eligible_slice_ids"))
    slice_audit = _prompt_sweep_diagnostic_slice_audit(
        direction=direction,
        best_variant=best_executed["variant"],
        reference=promotion_reference,
        reference_metrics=reference_metrics if isinstance(reference_metrics, dict) else None,
        candidate_metrics=final_result["metrics"],
        eligible_slice_ids=required_slice_ids,
    )
    _write_json(output_paths["diagnostic_slice_audit_path"], slice_audit)
    if config.get("slice_audit") and not slice_audit["clean"]:
        raise ValueError(
            "Prompt/decode diagnostic slice audit is incomplete: "
            + ", ".join(slice_audit["issues"])
        )
    decision = _prompt_sweep_promotion_decision(
        best_variant=best_executed["variant"],
        best_row=best_row,
        best_result=best_executed["result"],
        final_result=final_result,
        reference=promotion_reference,
        baseline_anchor=baseline_anchor,
        baseline_anchor_preflight=baseline_anchor_preflight,
        slice_override=slice_override,
        promotion_rules=promotion_rules,
        metric_path=metric_path,
    )
    scoreboard = {
        "version": 2,
        "mission_id": config.get("mission_id"),
        "loop_action_id": config.get("loop_action_id"),
        "stage_id": "prompt-decode",
        "selected_direction": direction,
        "selected_starter": config.get("selected_starter"),
        "promotion_reference": promotion_reference,
        "baseline_anchor": baseline_anchor["summary"],
        "baseline_anchor_preflight": baseline_anchor_preflight,
        "smoke_limit_from_baseline": None,
        "rows": rows,
    }
    _write_json(output_paths["scoreboard_path"], scoreboard)
    summary = {
        "version": 2,
        "mission_id": config.get("mission_id"),
        "loop_action_id": config.get("loop_action_id"),
        "stage_id": "prompt-decode",
        "status": "completed",
        "selected_direction": direction,
        "selected_starter": config.get("selected_starter"),
        "executed_variant_ids": [item["variant"]["variant_id"] for item in executed_results],
        "skipped_variant_ids": [
            item["variant_id"] for item in rows if item.get("status") == "skipped"
        ],
        "stage_spent_gpu_hours": round(total_stage_gpu_hours, 6),
        "decision": decision["decision"],
        "best_candidate": decision["best_candidate"],
        "promotion_reference": promotion_reference,
        "baseline_anchor": baseline_anchor["summary"],
        "baseline_anchor_preflight": baseline_anchor_preflight,
        "notes": _normalize_notes(
            [
                config.get("notes", []),
                baseline_anchor_cfg.get("notes", []),
                "DeepLoop executed the prompt/decode sweep through the shared stage-kernel surface.",
            ]
        ),
    }
    _update_prompt_sweep_crash_notes(
        output_paths["crash_notes_path"],
        summary=summary,
        scoreboard_path=output_paths["scoreboard_path"],
        promotion_decision_path=output_paths["promotion_decision_path"],
        summary_path=output_paths["summary_path"],
        diagnostic_slice_audit_path=output_paths["diagnostic_slice_audit_path"],
    )
    manifest = _build_manifest(
        adapter=adapter,
        stage_id="prompt-decode-sweep",
        loop_id=loop_id,
        mode=str(config.get("mode", DEFAULT_OPERATING_MODE)),
        claim_state=str(config.get("claim_state", "exploratory")),
        mission_id=config.get("mission_id"),
        resource_tier=str(config["resource_tier"]),
        execution_profile=str(config["execution_profile"]),
        model=model_cfg,
        dataset={
            "name": _dataset_name(adapter, primary_bundle["promotion_manifest"]),
            "slice": f"primary-dev:{direction},secondary-holdout:{direction},final-test:{direction}",
            "provenance": str(promotion_manifest_path),
        },
        prompt={
            "template_id": str(best_executed["variant"].get("template_id")),
            "parser_id": getattr(adapter, "parser_id", "unknown-parser"),
        },
        output_dir=output_dir,
        command=f"prompt-decode-sweep --config {config_path}",
        seed=seed,
        notes=_normalize_notes(config.get("notes", [])),
        metrics={
            "best_primary_score": _metric_at_path(best_executed["result"]["primary_metrics"], metric_path),
            "best_holdout_score": _metric_at_path(best_executed["result"]["holdout_metrics"], metric_path),
            "best_final_score": final_score,
            "reference_kind": promotion_reference["kind"],
            "reference_score": promotion_reference["score"],
            "baseline_anchor_score": _metric_at_path(baseline_anchor["metrics"], metric_path),
            "gain_vs_reference": full_set_gain,
            "decision": decision["decision"],
            "executed_variants": len(executed_results),
            "skipped_variants": len(rows) - len(executed_results),
        },
        stage_context={
            "direction": direction,
            "runtime_root": str(runtime_root),
            "locked_context_bucket": locked_context_bucket,
            "dataset_materialization": {
                "promotion_manifest_path": str(promotion_manifest_path),
                "primary_dev_selection": _prompt_sweep_selection_config(
                    dataset_materialization,
                    "primary_dev_selection",
                    direction,
                ),
                "secondary_holdout_selection": _prompt_sweep_selection_config(
                    dataset_materialization,
                    "secondary_holdout_selection",
                    direction,
                ),
                "final_test_selection": _prompt_sweep_selection_config(
                    dataset_materialization,
                    "final_test_selection",
                    direction,
                ),
            },
            "variant_matrix": variant_matrix,
            "promotion_rules": promotion_rules,
            "promotion_reference": promotion_reference,
            "baseline_anchor": baseline_anchor["summary"],
            "baseline_anchor_preflight": baseline_anchor_preflight,
            "artifacts": {
                "scoreboard_path": str(output_paths["scoreboard_path"]),
                "promotion_decision_path": str(output_paths["promotion_decision_path"]),
                "diagnostic_slice_audit_path": str(output_paths["diagnostic_slice_audit_path"]),
                "summary_path": str(output_paths["summary_path"]),
                "crash_notes_path": str(output_paths["crash_notes_path"]),
            },
        },
        report_paths=[
            str(output_paths["scoreboard_path"]),
            str(output_paths["promotion_decision_path"]),
            str(output_paths["diagnostic_slice_audit_path"]),
            str(output_paths["summary_path"]),
            str(output_paths["crash_notes_path"]),
        ],
    )
    manifest_path = output_dir / "run_manifest.json"
    _validate_manifest(manifest)
    _write_json(manifest_path, manifest)
    _write_json(output_paths["promotion_decision_path"], decision)
    _write_json(output_paths["summary_path"], summary)
    decision["replication_gate"] = _prompt_sweep_replication_gate(
        config,
        output_paths=output_paths,
        manifest_path=manifest_path,
        slice_audit=slice_audit,
        reference=promotion_reference,
    )
    summary["replication_gate"] = decision["replication_gate"]
    _write_json(output_paths["promotion_decision_path"], decision)
    _write_json(output_paths["summary_path"], summary)
    return KernelRunResult(
        stage_id="prompt-decode-sweep",
        status="completed",
        output_dir=output_dir,
        manifest_path=manifest_path,
        summary_path=output_paths["summary_path"],
        artifacts={
            "scoreboard": output_paths["scoreboard_path"],
            "promotion_decision": output_paths["promotion_decision_path"],
            "diagnostic_slice_audit": output_paths["diagnostic_slice_audit_path"],
            "summary": output_paths["summary_path"],
            "crash_notes": output_paths["crash_notes_path"],
            "manifest": manifest_path,
        },
    )
