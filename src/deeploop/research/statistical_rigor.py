from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.dotted import get_dotted as _get_nested
from deeploop.core.paths import MISSIONS_DIR, RUNS_DIR
from deeploop.core.structured_io import (
    load_json_object as _load_json,
    load_jsonl as _load_jsonl,
    load_structured_mapping as _load_structured_file,
    load_yaml_mapping as _load_yaml,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = REPO_ROOT / "configs" / "autonomy" / "statistical-rigor.yaml"


def _round_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _sanitize_stem(value: str) -> str:
    return value.replace("/", "-").replace(" ", "-")


def _resolve_target_bundle(target_path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    target = target_path.expanduser().resolve()
    support = contract.get("manifest_support", {})
    manifest_names = list(support.get("manifest_filenames", []))
    metrics_names = list(support.get("metrics_filenames", []))
    prediction_names = list(support.get("predictions_filenames", []))

    if target.is_dir():
        base_dir = target
        manifest_path = next((base_dir / name for name in manifest_names if (base_dir / name).exists()), None)
        metrics_path = next((base_dir / name for name in metrics_names if (base_dir / name).exists()), None)
        predictions_path = next((base_dir / name for name in prediction_names if (base_dir / name).exists()), None)
    elif target.is_file():
        base_dir = target.parent
        manifest_path = target if target.name in manifest_names else next((base_dir / name for name in manifest_names if (base_dir / name).exists()), None)
        metrics_path = target if target.name in metrics_names else next((base_dir / name for name in metrics_names if (base_dir / name).exists()), None)
        predictions_path = target if target.name in prediction_names else next((base_dir / name for name in prediction_names if (base_dir / name).exists()), None)
    else:
        raise FileNotFoundError(f"statistical-rigor target does not exist: {target}")

    if manifest_path is None and metrics_path is None and predictions_path is None:
        raise FileNotFoundError(f"no supported manifest or output files found under {target}")

    manifest = _load_structured_file(manifest_path) if manifest_path else {}
    metrics_payload = manifest.get("metrics")
    if not isinstance(metrics_payload, dict):
        metrics_payload = {}
    if metrics_path is not None:
        metrics_candidate = _load_structured_file(metrics_path)
        if isinstance(metrics_candidate, dict) and metrics_candidate:
            metrics_payload = metrics_payload or metrics_candidate

    output_dir = None
    for field in support.get("output_dir_paths", []):
        candidate = _get_nested(manifest, field)
        if isinstance(candidate, str) and candidate:
            output_dir = Path(candidate).expanduser()
            break
    if output_dir is None:
        output_dir = base_dir

    manifest_kind = "metrics-only"
    if manifest_path is not None:
        if manifest_path.name == "run_manifest.json":
            manifest_kind = "run-manifest"
        elif manifest_path.name == "study_manifest.json":
            manifest_kind = "study-manifest"
        elif "loop_id" in manifest:
            manifest_kind = "run-manifest"
        elif "study_id" in manifest:
            manifest_kind = "study-manifest"
        else:
            manifest_kind = "manifest"

    return {
        "target_path": target,
        "base_dir": base_dir,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "manifest_kind": manifest_kind,
        "metrics_path": metrics_path,
        "metrics": metrics_payload,
        "predictions_path": predictions_path,
        "output_dir": output_dir,
    }


def _wilson_interval(successes: int, count: int, z_value: float) -> tuple[float, float]:
    if count <= 0:
        return (0.0, 1.0)
    p_hat = successes / count
    z_sq = z_value**2
    denominator = 1 + z_sq / count
    center = (p_hat + z_sq / (2 * count)) / denominator
    half_width = z_value * math.sqrt((p_hat * (1 - p_hat) / count) + (z_sq / (4 * count**2))) / denominator
    return (max(0.0, center - half_width), min(1.0, center + half_width))


def _build_proportion_summary(
    *,
    count: int,
    estimate: float | None,
    successes: int | None,
    source: str,
    direct_measurement: bool,
    uncertainty_cfg: dict[str, Any],
) -> dict[str, Any] | None:
    if count <= 0:
        return None
    if successes is None:
        if estimate is None:
            return None
        successes = int(round(float(estimate) * count))
    successes = max(0, min(count, int(successes)))
    estimate_from_counts = successes / count
    point_estimate = estimate_from_counts if estimate is None else float(estimate)
    if abs(point_estimate - estimate_from_counts) < 1e-6:
        point_estimate = estimate_from_counts
    standard_error = math.sqrt(max(estimate_from_counts * (1 - estimate_from_counts), 0.0) / count)
    z_value = float(uncertainty_cfg.get("z_value", 1.959963984540054))
    lower, upper = _wilson_interval(successes, count, z_value)
    interval_width = upper - lower
    return {
        "count": int(count),
        "successes": int(successes),
        "estimate": _round_float(point_estimate),
        "estimate_from_counts": _round_float(estimate_from_counts),
        "standard_error": _round_float(standard_error),
        "error_bar_95": _round_float(interval_width / 2),
        "interval_95": [_round_float(lower), _round_float(upper)],
        "interval_width": _round_float(interval_width),
        "interval_method": str(uncertainty_cfg.get("interval_method", "wilson")),
        "source": source,
        "direct_measurement": direct_measurement,
    }


def _summary_from_metrics(
    metrics: dict[str, Any],
    *,
    source: str,
    direct_measurement: bool,
    uncertainty_cfg: dict[str, Any],
) -> dict[str, Any] | None:
    count = metrics.get("count")
    accuracy = metrics.get("accuracy")
    if isinstance(count, bool) or isinstance(accuracy, bool):
        return None
    if not isinstance(count, (int, float)) or not isinstance(accuracy, (int, float)):
        return None
    return _build_proportion_summary(
        count=int(count),
        estimate=float(accuracy),
        successes=None,
        source=source,
        direct_measurement=direct_measurement,
        uncertainty_cfg=uncertainty_cfg,
    )


def _summary_from_predictions(
    predictions: list[dict[str, Any]],
    *,
    source: str,
    uncertainty_cfg: dict[str, Any],
) -> dict[str, Any] | None:
    if not predictions:
        return None
    if not all("gold_label" in row and "predicted_label" in row for row in predictions):
        return None
    count = len(predictions)
    successes = sum(1 for row in predictions if row["gold_label"] == row["predicted_label"])
    return _build_proportion_summary(
        count=count,
        estimate=successes / count if count else None,
        successes=successes,
        source=source,
        direct_measurement=True,
        uncertainty_cfg=uncertainty_cfg,
    )


def _group_summaries_from_metrics(metrics: dict[str, Any], uncertainty_cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    families: dict[str, dict[str, Any]] = {}
    for family_name, family_payload in metrics.items():
        if not isinstance(family_payload, dict) or not family_payload:
            continue
        family_summary: dict[str, Any] = {}
        valid_family = True
        for label, label_payload in family_payload.items():
            if not isinstance(label_payload, dict):
                valid_family = False
                break
            summary = _summary_from_metrics(
                label_payload,
                source=f"metrics.{family_name}.{label}",
                direct_measurement=True,
                uncertainty_cfg=uncertainty_cfg,
            )
            if summary is None:
                valid_family = False
                break
            family_summary[str(label)] = summary
        if valid_family and family_summary:
            families[str(family_name)] = family_summary
    return families


def _group_summaries_from_predictions(
    predictions: list[dict[str, Any]],
    contract: dict[str, Any],
    uncertainty_cfg: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if not predictions:
        return {}
    if not all("gold_label" in row and "predicted_label" in row for row in predictions):
        return {}
    grouped: dict[str, dict[str, dict[str, int]]] = {}
    for family_name, field_name in contract.get("prediction_group_fields", {}).items():
        for row in predictions:
            if field_name not in row:
                continue
            label = str(row[field_name])
            family_bucket = grouped.setdefault(str(family_name), {})
            counts = family_bucket.setdefault(label, {"count": 0, "successes": 0})
            counts["count"] += 1
            if row["gold_label"] == row["predicted_label"]:
                counts["successes"] += 1

    family_summaries: dict[str, dict[str, Any]] = {}
    for family_name, labels in grouped.items():
        label_summaries: dict[str, Any] = {}
        for label, counts in labels.items():
            label_summaries[label] = _build_proportion_summary(
                count=counts["count"],
                estimate=counts["successes"] / counts["count"] if counts["count"] else None,
                successes=counts["successes"],
                source=f"predictions.jsonl:{family_name}.{label}",
                direct_measurement=True,
                uncertainty_cfg=uncertainty_cfg,
            )
        if label_summaries:
            family_summaries[family_name] = label_summaries
    return family_summaries


def _collect_references(
    manifest: dict[str, Any],
    contract: dict[str, Any],
    uncertainty_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for field in contract.get("reference_manifest_fields", []):
        value = _get_nested(manifest, str(field))
        if not isinstance(value, str) or not value:
            continue
        path = Path(value).expanduser()
        reference: dict[str, Any] = {
            "field": str(field),
            "path": str(path),
            "exists": path.exists(),
        }
        if path.exists():
            try:
                payload = _load_structured_file(path)
            except Exception as exc:
                reference["parse_error"] = str(exc)
            else:
                reference["manifest_kind"] = "reference"
                if isinstance(payload, dict):
                    reference["mission_id"] = payload.get("mission_id")
                    primary = _summary_from_metrics(
                        payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {},
                        source=f"reference:{field}",
                        direct_measurement=False,
                        uncertainty_cfg=uncertainty_cfg,
                    )
                    if primary is not None:
                        reference["primary_metric"] = primary
        references.append(reference)
    return references


def _difference_summaries(metrics: dict[str, Any], families: dict[str, dict[str, Any]]) -> dict[str, Any]:
    differences: dict[str, Any] = {}
    lexicalization = families.get("lexicalization", {})
    if isinstance(metrics.get("lexicalization_gap"), (int, float)) and "lex" in lexicalization and "delex" in lexicalization:
        lex_summary = lexicalization["lex"]
        delex_summary = lexicalization["delex"]
        lower = float(lex_summary["interval_95"][0]) - float(delex_summary["interval_95"][1])
        upper = float(lex_summary["interval_95"][1]) - float(delex_summary["interval_95"][0])
        differences["lexicalization_gap"] = {
            "definition": "lex - delex",
            "estimate": _round_float(metrics["lexicalization_gap"]),
            "interval_95": [_round_float(lower), _round_float(upper)],
            "interval_method": "conservative-wilson-difference",
        }
    return differences


def _warning(code: str, message: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    warning = {"code": code, "severity": "warn", "message": message}
    if context:
        warning["context"] = context
    return warning


def _build_warnings(
    *,
    primary_metric: dict[str, Any] | None,
    sample_size: dict[str, Any],
    group_summaries: dict[str, dict[str, Any]],
    references: list[dict[str, Any]],
    run_status: str | None,
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    power_cfg = contract.get("power", {})
    uncertainty_cfg = contract.get("uncertainty", {})
    promotion_cfg = contract.get("promotion", {})
    effective_count = sample_size.get("effective_count")

    if not primary_metric:
        warnings.append(_warning("missing-primary-metric", "No direct proportion metric was available for bounded uncertainty estimation."))
    elif not bool(primary_metric.get("direct_measurement", False)):
        warnings.append(
            _warning(
                "reference-only-estimate",
                "The best available uncertainty summary comes from a referenced manifest, not from a direct result in this artifact.",
                context={"source": primary_metric.get("source")},
            )
        )

    if effective_count is None:
        warnings.append(_warning("missing-sample-size", "No defensible sample size could be recovered from this artifact or its references."))
    else:
        warn_below_total = int(power_cfg.get("warn_below_total_examples", 0))
        not_ready_below = int(power_cfg.get("not_ready_below_total_examples", 0))
        if effective_count < not_ready_below:
            warnings.append(
                _warning(
                    "underpowered-total",
                    f"Effective sample size {effective_count} is below the not-ready threshold of {not_ready_below}.",
                    context={"effective_count": effective_count},
                )
            )
        elif effective_count < warn_below_total:
            warnings.append(
                _warning(
                    "small-total-sample",
                    f"Effective sample size {effective_count} is below the caution threshold of {warn_below_total}.",
                    context={"effective_count": effective_count},
                )
            )

    if primary_metric and isinstance(primary_metric.get("interval_width"), (int, float)):
        wide_threshold = float(uncertainty_cfg.get("wide_interval_threshold", 0.5))
        if float(primary_metric["interval_width"]) > wide_threshold:
            warnings.append(
                _warning(
                    "wide-primary-interval",
                    f"Primary 95% interval width {primary_metric['interval_width']} exceeds the caution threshold of {wide_threshold}.",
                    context={"interval_width": primary_metric["interval_width"]},
                )
            )

    warn_below_slice = int(power_cfg.get("warn_below_slice_examples", 0))
    degenerate_slice = int(power_cfg.get("degenerate_slice_examples", 0))
    for family_name, family_payload in group_summaries.items():
        for label, summary in family_payload.items():
            count = int(summary["count"])
            if count <= degenerate_slice:
                warnings.append(
                    _warning(
                        "degenerate-slice",
                        f"Slice {family_name}.{label} has only {count} examples; treat the estimate as extremely unstable.",
                        context={"family": family_name, "label": label, "count": count},
                    )
                )
            elif count < warn_below_slice:
                warnings.append(
                    _warning(
                        "small-slice",
                        f"Slice {family_name}.{label} has only {count} examples.",
                        context={"family": family_name, "label": label, "count": count},
                    )
                )

    blocked_statuses = {str(item) for item in promotion_cfg.get("blocked_run_statuses", [])}
    if run_status in blocked_statuses:
        warnings.append(
            _warning(
                "non-completed-status",
                f"Run status is {run_status}; this artifact is not a completed empirical result.",
                context={"run_status": run_status},
            )
        )

    for reference in references:
        if not reference.get("exists"):
            warnings.append(
                _warning(
                    "missing-reference",
                    f"Referenced artifact {reference['field']} does not exist: {reference['path']}.",
                    context={"field": reference["field"], "path": reference["path"]},
                )
            )
        elif reference.get("parse_error"):
            warnings.append(
                _warning(
                    "unreadable-reference",
                    f"Referenced artifact {reference['field']} could not be parsed: {reference['parse_error']}.",
                    context={"field": reference["field"], "path": reference["path"]},
                )
            )

    return warnings


def _promotion_guidance(
    *,
    primary_metric: dict[str, Any] | None,
    sample_size: dict[str, Any],
    run_status: str | None,
    contract: dict[str, Any],
) -> dict[str, Any]:
    promotion_cfg = contract.get("promotion", {})
    minimum_examples = int(promotion_cfg.get("minimum_total_examples_for_exploratory", 0))
    max_allowed_state = str(promotion_cfg.get("max_allowed_state", "exploratory"))
    blocked_statuses = {str(item) for item in promotion_cfg.get("blocked_run_statuses", [])}
    reasons: list[str] = []
    recommended_state = str(promotion_cfg.get("default_state", "exploratory"))

    effective_count = sample_size.get("effective_count")
    if primary_metric is None:
        reasons.append("no direct bounded proportion metric was available")
    elif not bool(primary_metric.get("direct_measurement", False)):
        reasons.append("the best available estimate is inherited from a reference artifact")
    if effective_count is None:
        reasons.append("sample size could not be defended from available artifacts")
    elif effective_count < minimum_examples:
        reasons.append(f"effective sample size {effective_count} is below the exploratory floor of {minimum_examples}")
    if run_status in blocked_statuses:
        reasons.append(f"run status {run_status} is not a completed empirical result")

    if reasons:
        recommended_state = "not-ready"

    return {
        "allowed_states": list(promotion_cfg.get("allowed_states", ["exploratory", "not-ready"])),
        "recommended_state": recommended_state,
        "max_allowed_state": max_allowed_state,
        "reasons": reasons or ["bounded evidence is sufficient only for exploratory use"],
        "allowed_uses": [
            "descriptive debugging",
            "triaging which slices deserve more data",
            "choosing bounded follow-up experiments",
        ],
        "disallowed_uses": [
            "significance claims",
            "paper-candidate promotion",
            "treating slice rankings as stable facts",
            "claiming robust gains from tiny bounded runs",
        ],
    }


def _artifact_root(
    *,
    mission_state_path: Path | None,
    output_root: Path | None,
    contract: dict[str, Any],
) -> Path:
    if output_root is not None:
        return output_root
    artifact_dir_name = str(contract.get("artifact_dir_name", "statistical_rigor"))
    if mission_state_path is not None:
        return mission_state_path.parent / artifact_dir_name
    return RUNS_DIR / artifact_dir_name


def _co_located_paths(output_dir: Path | None, contract: dict[str, Any]) -> tuple[Path | None, Path | None]:
    if output_dir is None or not bool(contract.get("write_run_local_copy", False)):
        return (None, None)
    names = contract.get("co_located_report_names", {})
    json_name = str(names.get("json", "deeploop_statistical_rigor.json"))
    markdown_name = str(names.get("markdown", "deeploop_statistical_rigor.md"))
    return (output_dir / json_name, output_dir / markdown_name)


def _write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    sample_size = report["sample_size"]
    primary_metric = report.get("primary_metric")
    promotion = report["promotion_guidance"]
    lines = [
        "# Statistical rigor report",
        "",
        f"- evaluated_at: `{report['evaluated_at']}`",
        f"- artifact_name: `{report['artifact_name']}`",
        f"- manifest_kind: `{report['manifest_kind']}`",
        f"- manifest_path: `{report['manifest_path']}`",
        f"- run_status: `{report['run_status']}`",
        f"- effective_sample_size: `{sample_size.get('effective_count')}`",
        f"- sample_size_source: `{sample_size.get('source')}`",
        f"- power_verdict: `{sample_size.get('power_verdict')}`",
        f"- promotion_guidance: `{promotion['recommended_state']}`",
        "",
        "## Primary uncertainty summary",
        "",
    ]
    if primary_metric:
        lines.extend(
            [
                f"- estimate: `{primary_metric['estimate']}`",
                f"- 95% interval: `{primary_metric['interval_95'][0]} .. {primary_metric['interval_95'][1]}`",
                f"- error_bar_95: `{primary_metric['error_bar_95']}`",
                f"- direct_measurement: `{primary_metric['direct_measurement']}`",
                f"- source: `{primary_metric['source']}`",
            ]
        )
    else:
        lines.append("- No defensible direct proportion estimate was available.")

    lines.extend(["", "## Warnings", ""])
    if report["warnings"]:
        lines.extend(f"- {warning['message']}" for warning in report["warnings"])
    else:
        lines.append("- None")

    if report["difference_summaries"]:
        lines.extend(["", "## Difference summaries", ""])
        for name, summary in report["difference_summaries"].items():
            lines.append(
                f"- {name}: estimate `{summary['estimate']}`, 95% interval `{summary['interval_95'][0]} .. {summary['interval_95'][1]}` ({summary['definition']})"
            )

    if report["group_summaries"]:
        lines.extend(["", "## Slice summaries", ""])
        for family_name, family_payload in report["group_summaries"].items():
            lines.append(f"### {family_name}")
            lines.append("")
            for label, summary in family_payload.items():
                lines.append(
                    f"- `{label}`: n=`{summary['count']}`, estimate=`{summary['estimate']}`, 95% interval=`{summary['interval_95'][0]} .. {summary['interval_95'][1]}`"
                )
            lines.append("")

    lines.extend(
        [
            "## Promotion guidance",
            "",
            *(f"- {reason}" for reason in promotion["reasons"]),
            "",
            "### Allowed uses",
            "",
            *(f"- {item}" for item in promotion["allowed_uses"]),
            "",
            "### Disallowed uses",
            "",
            *(f"- {item}" for item in promotion["disallowed_uses"]),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def evaluate_statistical_rigor(
    target_path: Path,
    *,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    mission_state_path: Path | None = None,
    output_root: Path | None = None,
    artifact_name: str | None = None,
) -> dict[str, Any]:
    contract = _load_yaml(contract_path)
    uncertainty_cfg = contract.get("uncertainty", {})
    bundle = _resolve_target_bundle(target_path, contract)
    manifest = bundle["manifest"]
    if mission_state_path is None and isinstance(manifest, dict):
        mission_id = manifest.get("mission_id")
        if isinstance(mission_id, str) and mission_id:
            inferred = MISSIONS_DIR / mission_id / "mission_state.json"
            if inferred.exists():
                mission_state_path = inferred

    predictions = _load_jsonl(bundle["predictions_path"]) if bundle["predictions_path"] else []
    predictions_primary = _summary_from_predictions(predictions, source="predictions.jsonl", uncertainty_cfg=uncertainty_cfg)
    direct_primary = predictions_primary or _summary_from_metrics(
        bundle["metrics"],
        source="manifest.metrics" if bundle["manifest_path"] else "metrics",
        direct_measurement=True,
        uncertainty_cfg=uncertainty_cfg,
    )
    group_summaries = _group_summaries_from_metrics(bundle["metrics"], uncertainty_cfg)
    if predictions:
        prediction_groups = _group_summaries_from_predictions(predictions, contract, uncertainty_cfg)
        for family_name, family_payload in prediction_groups.items():
            group_summaries.setdefault(family_name, family_payload)

    references = _collect_references(manifest, contract, uncertainty_cfg) if isinstance(manifest, dict) else []
    inherited_primary = next((reference["primary_metric"] for reference in references if "primary_metric" in reference), None)
    primary_metric = direct_primary or inherited_primary

    effective_count = primary_metric.get("count") if primary_metric else None
    count_source = primary_metric.get("source") if primary_metric else None
    power_cfg = contract.get("power", {})
    if effective_count is None:
        power_verdict = "unknown"
    elif effective_count < int(power_cfg.get("not_ready_below_total_examples", 0)):
        power_verdict = "underpowered"
    elif effective_count < int(power_cfg.get("warn_below_total_examples", 0)):
        power_verdict = "small-sample"
    else:
        power_verdict = "bounded"

    run_status = None
    if isinstance(manifest.get("run"), dict):
        run_status = manifest["run"].get("status")
    if run_status is None:
        run_status = manifest.get("status")

    artifact_stem_source = artifact_name or manifest.get("loop_id") or manifest.get("study_id") or bundle["target_path"].stem
    artifact_stem = _sanitize_stem(str(artifact_stem_source))
    report_root = _artifact_root(
        mission_state_path=mission_state_path.expanduser().resolve() if mission_state_path else None,
        output_root=output_root.expanduser().resolve() if output_root else None,
        contract=contract,
    )
    report_root.mkdir(parents=True, exist_ok=True)
    report_json_path = report_root / f"{artifact_stem}.json"
    report_markdown_path = report_root / f"{artifact_stem}.md"
    co_located_json_path, co_located_md_path = _co_located_paths(bundle["output_dir"], contract)

    sample_size = {
        "effective_count": effective_count,
        "source": count_source,
        "power_verdict": power_verdict,
        "warn_below_total_examples": int(power_cfg.get("warn_below_total_examples", 0)),
        "not_ready_below_total_examples": int(power_cfg.get("not_ready_below_total_examples", 0)),
    }
    warnings = _build_warnings(
        primary_metric=primary_metric,
        sample_size=sample_size,
        group_summaries=group_summaries,
        references=references,
        run_status=str(run_status) if run_status is not None else None,
        contract=contract,
    )
    promotion_guidance = _promotion_guidance(
        primary_metric=primary_metric,
        sample_size=sample_size,
        run_status=str(run_status) if run_status is not None else None,
        contract=contract,
    )
    report = {
        "evaluated_at": now_utc(),
        "contract_path": str(contract_path),
        "contract_version": contract.get("version", 1),
        "artifact_name": artifact_stem,
        "target_path": str(bundle["target_path"]),
        "manifest_path": str(bundle["manifest_path"]) if bundle["manifest_path"] else None,
        "manifest_kind": bundle["manifest_kind"],
        "mission_id": manifest.get("mission_id"),
        "run_status": run_status,
        "output_dir": str(bundle["output_dir"]) if bundle["output_dir"] else None,
        "sample_size": sample_size,
        "primary_metric": primary_metric,
        "group_summaries": group_summaries,
        "difference_summaries": _difference_summaries(bundle["metrics"], group_summaries),
        "references": references,
        "warnings": warnings,
        "promotion_guidance": promotion_guidance,
        "artifacts": {
            "report_json": str(report_json_path),
            "report_markdown": str(report_markdown_path),
            "co_located_json": str(co_located_json_path) if co_located_json_path else None,
            "co_located_markdown": str(co_located_md_path) if co_located_md_path else None,
        },
    }

    report_json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _write_markdown_report(report_markdown_path, report)

    if co_located_json_path and co_located_md_path:
        co_located_json_path.parent.mkdir(parents=True, exist_ok=True)
        co_located_json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        _write_markdown_report(co_located_md_path, report)

    if mission_state_path is not None and mission_state_path.exists():
        mission_state = _load_json(mission_state_path)
        related_paths = [path for path in [report_json_path, report_markdown_path, co_located_json_path, co_located_md_path, bundle["manifest_path"]] if path is not None]
        append_jsonl(
            mission_state_path.parent / "ledger.jsonl",
            make_ledger_entry(
                kind="statistical-rigor",
                mission_id=mission_state["mission_id"],
                summary=f"Statistical rigor for {artifact_stem} recommends {promotion_guidance['recommended_state']}.",
                status=promotion_guidance["recommended_state"],
                related_paths=[str(path) for path in related_paths],
                metadata={
                    "effective_count": effective_count,
                    "warning_count": len(warnings),
                    "primary_metric_estimate": primary_metric["estimate"] if primary_metric else None,
                    "promotion_guidance": promotion_guidance["recommended_state"],
                },
            ),
        )

    return {
        "report_json_path": report_json_path,
        "report_markdown_path": report_markdown_path,
        "co_located_json_path": co_located_json_path,
        "co_located_markdown_path": co_located_md_path,
        "recommended_state": promotion_guidance["recommended_state"],
        "warning_count": len(warnings),
        "effective_count": effective_count,
    }
