from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def metric_map(payload: Mapping[str, Any]) -> dict[str, float]:
    metrics_payload = payload.get("metrics") if isinstance(payload.get("metrics"), Mapping) else payload
    metrics: dict[str, float] = {}
    for key, value in metrics_payload.items():
        resolved = _as_float(value)
        if resolved is not None:
            metrics[str(key)] = resolved
    return metrics


def metric_higher_is_better(metric_name: str, *, default: bool) -> bool:
    lowered = metric_name.lower()
    if any(token in lowered for token in ("loss", "error", "latency", "perplexity")):
        return False
    return default


@dataclass(frozen=True)
class MetricRatchetConfig:
    primary_metric: str
    higher_is_better: bool = True
    min_improvement: float = 0.0
    max_allowed_regression: float = 0.0
    guardrail_metrics: tuple[str, ...] = ()
    route_on_keep: str = "replication"
    route_on_discard: str = "experiment-design"
    slice_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "MetricRatchetConfig":
        primary_metric = str(raw.get("primary_metric") or "").strip()
        if not primary_metric:
            raise ValueError("metric ratchet primary_metric is required.")
        raw_slice_overrides = raw.get("slice_overrides")
        slice_overrides = (
            {
                str(key): dict(value)
                for key, value in raw_slice_overrides.items()
                if isinstance(key, str) and isinstance(value, Mapping)
            }
            if isinstance(raw_slice_overrides, Mapping)
            else {}
        )
        return cls(
            primary_metric=primary_metric,
            higher_is_better=bool(raw.get("higher_is_better", True)),
            min_improvement=float(raw.get("min_improvement", 0.0) or 0.0),
            max_allowed_regression=float(raw.get("max_allowed_regression", 0.0) or 0.0),
            guardrail_metrics=tuple(str(item) for item in raw.get("guardrail_metrics", ()) if str(item).strip()),
            route_on_keep=str(raw.get("route_on_keep", "replication")).strip() or "replication",
            route_on_discard=str(raw.get("route_on_discard", "experiment-design")).strip() or "experiment-design",
            slice_overrides=slice_overrides,
        )


def build_metric_ratchet_decision(
    config: MetricRatchetConfig,
    *,
    candidate_metrics: Mapping[str, float],
    anchors: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    primary = config.primary_metric
    candidate_score = candidate_metrics.get(primary)
    if candidate_score is None:
        raise ValueError(f"Evaluation metrics are missing primary metric `{primary}`.")

    anchor_candidates = [
        (str(label), float(metrics[primary]))
        for label, metrics in anchors.items()
        if primary in metrics
    ]
    if not anchor_candidates:
        raise ValueError(f"Anchor metrics are missing primary metric `{primary}`.")
    if "baseline" not in {label for label, _ in anchor_candidates}:
        raise ValueError(f"Baseline metrics are missing primary metric `{primary}`.")

    if config.higher_is_better:
        anchor_label, anchor_score = max(anchor_candidates, key=lambda item: item[1])
        improvement = candidate_score - anchor_score
    else:
        anchor_label, anchor_score = min(anchor_candidates, key=lambda item: item[1])
        improvement = anchor_score - candidate_score
    keep = improvement >= config.min_improvement

    baseline_score = anchors["baseline"].get(primary)
    intervention_score = anchors.get("intervention", {}).get(primary)
    selected_anchor_metrics = anchors.get(anchor_label, anchors["baseline"])

    guardrails: dict[str, dict[str, float]] = {}
    for metric in config.guardrail_metrics:
        candidate_value = candidate_metrics.get(metric)
        anchor_value = selected_anchor_metrics.get(metric)
        if candidate_value is None or anchor_value is None:
            continue
        higher_is_better = metric_higher_is_better(metric, default=config.higher_is_better)
        regression = anchor_value - candidate_value if higher_is_better else candidate_value - anchor_value
        guardrails[metric] = {
            "anchor": anchor_value,
            "candidate": candidate_value,
            "higher_is_better": higher_is_better,
            "regression": regression,
        }
        if regression > config.max_allowed_regression:
            keep = False

    decision = "keep" if keep else "discard"
    route_to = config.route_on_keep if keep else config.route_on_discard
    deltas = {
        "vs_baseline": candidate_score - baseline_score if baseline_score is not None else None,
        "vs_intervention": candidate_score - intervention_score if intervention_score is not None else None,
        "vs_anchor": improvement if config.higher_is_better else -improvement,
    }
    return {
        "ratchet_kind": "metric-ratchet",
        "primary_metric": primary,
        "higher_is_better": config.higher_is_better,
        "anchor_label": anchor_label,
        "decision": decision,
        "route_to": route_to,
        "scores": {
            "baseline": baseline_score,
            "intervention": intervention_score,
            "candidate": candidate_score,
            "adapted": candidate_score,
            "anchor": anchor_score,
        },
        "deltas": deltas,
        "guardrails": guardrails,
        "thresholds": {
            "min_improvement": config.min_improvement,
            "max_allowed_regression": config.max_allowed_regression,
        },
        "metric_paths": {
            "primary_metric": [primary],
            "guardrail_metrics": {metric: [metric] for metric in config.guardrail_metrics},
        },
        "slice_overrides": config.slice_overrides,
        "promotion_guidance": (
            f"Promote the candidate along `{route_to}` for bounded follow-up review."
            if keep
            else f"Do not promote the candidate; reroute toward `{route_to}`."
        ),
        "summary": (
            f"Adapted artifact `{decision}` against the best prior anchor `{anchor_label}` "
            f"on `{primary}` with route `{route_to}`."
        ),
    }


__all__ = [
    "MetricRatchetConfig",
    "build_metric_ratchet_decision",
    "metric_higher_is_better",
    "metric_map",
]
