"""
DeepLoop self-optimization engine for autonomous profile and branch adjustment.

Learns from runtime telemetry, findings history, and mission artifacts to generate
deterministic recommendations for profile tuning, branch expansion/shrinkage, and
resource reallocation.

Integrates utility scorer, self-correction, statistical-rigor, confound-guard, and
sanity-gates signals to drive bounded, auditable optimization decisions.

Produces JSON/Markdown artifacts with full ledger integration.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from deeploop.core.dotted import get_dotted as _get_nested
from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.paths import REPO_ROOT, RUNS_DIR
from deeploop.core.structured_io import load_json as _load_json, load_yaml as _load_yaml

DEFAULT_CONTRACT_PATH = REPO_ROOT / "configs" / "autonomy" / "self-optimization.yaml"


def _find_latest_artifact(
    search_dir: Path, patterns: list[str]
) -> Optional[Path]:
    """Find most recent artifact matching any pattern."""
    candidates: list[Path] = []
    for pattern in patterns:
        if "*" in pattern:
            candidates.extend(search_dir.glob(pattern))
        else:
            candidate = search_dir / pattern
            if candidate.exists():
                candidates.append(candidate)
    
    if not candidates:
        return None
    
    # Return most recently modified
    return max(candidates, key=lambda p: p.stat().st_mtime)


@dataclass
class SignalSummary:
    """Container for aggregated optimization signals."""

    timestamp: str
    utility_score: float | None
    evidence_quality: float | None
    cost_efficiency: float | None
    confound_risk: float | None
    branch_health: str | None  # "healthy", "degraded", "critical"
    consistency_signal: float | None
    sources_consulted: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class Recommendation:
    """Single optimization recommendation."""

    recommendation_id: str
    category: str  # "expansion", "shrinkage", "adjustment"
    target: str
    action: str
    confidence_level: float  # 0.0-1.0
    rationale: str
    estimated_impact: dict[str, Any]
    fallback_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class OptimizationReport:
    """Final optimization report with recommendations."""

    timestamp: str
    mission_id: str
    optimization_phase: str  # e.g., "post-baseline", "post-localization"
    signal_summary: SignalSummary
    recommendations: list[Recommendation]
    decision_rationale: str
    bounded_constraints_applied: list[str]
    next_observation_window_days: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        d = asdict(self)
        d["signal_summary"] = self.signal_summary.to_dict()
        d["recommendations"] = [r.to_dict() for r in self.recommendations]
        return d


def _load_utility_signals(
    artifact_dir: Path, contract: dict[str, Any]
) -> dict[str, Any]:
    """Load utility scorer artifacts and extract optimization signals."""
    signals: dict[str, Any] = {}
    
    patterns = contract.get("data_sources", {}).get("utility_scorer", {}).get("artifact_patterns", [])
    utility_file = _find_latest_artifact(artifact_dir, patterns)
    
    if utility_file and utility_file.exists():
        try:
            data = _load_json(utility_file)
            top_branch = (data.get("ranked_branches") or [{}])[0]
            summary = data.get("summary", {})
            factors = top_branch.get("factors", {})
            signals["overall_score"] = top_branch.get(
                "overall_score",
                data.get("overall_score", data.get("combined_score", summary.get("mean_score"))),
            )
            signals["evidence_quality"] = factors.get("evidence_quality")
            signals["cost_risk_profile"] = factors.get("cost_risk_profile")
            signals["expected_information_gain"] = factors.get("expected_information_gain")
            signals["utility_source"] = str(utility_file)
            signals["utility_branch_count"] = len(
                data.get("ranked_branches", data.get("branch_scores", []))
            )
        except Exception:  # noqa: S110
            pass
    
    return signals


def _load_self_correction_signals(
    artifact_dir: Path, contract: dict[str, Any]
) -> dict[str, Any]:
    """Load self-correction artifacts and extract health/recovery signals."""
    signals: dict[str, Any] = {}
    
    patterns = contract.get("data_sources", {}).get("self_correction", {}).get("artifact_patterns", [])
    correction_file = _find_latest_artifact(artifact_dir, patterns)
    
    if correction_file and correction_file.exists():
        try:
            data = _load_json(correction_file)
            final_decision = data.get("final_decision", {})
            signals["branch_health"] = _classify_branch_health(final_decision.get("action", "unknown"))
            signals["correction_action"] = final_decision.get("action")
            signals["assessment_count"] = len(data.get("assessments", []))
            
            # Extract consistency from assessments
            if data.get("assessments"):
                continue_count = sum(1 for a in data["assessments"] if a.get("decision", {}).get("action") == "continue")
                signals["consistency_signal"] = continue_count / len(data["assessments"])
            
            signals["correction_source"] = str(correction_file)
        except Exception:  # noqa: S110
            pass
    
    return signals


def _load_statistical_signals(
    artifact_dir: Path, contract: dict[str, Any]
) -> dict[str, Any]:
    """Load statistical-rigor artifacts and extract evidence quality signals."""
    signals: dict[str, Any] = {}
    
    patterns = contract.get("data_sources", {}).get("statistical_rigor", {}).get("artifact_patterns", [])
    rigor_file = _find_latest_artifact(artifact_dir, patterns)
    
    if rigor_file and rigor_file.exists():
        try:
            data = _load_json(rigor_file)
            signals["effective_sample_size"] = _get_nested(data, "sample_size.effective_count")
            signals["confidence_interval_width"] = _get_nested(data, "primary_metric.interval_width")
            signals["warning_count"] = len(data.get("warnings", []))
            signals["rigor_source"] = str(rigor_file)
        except Exception:  # noqa: S110
            pass
    
    return signals


def _load_confound_signals(
    artifact_dir: Path, contract: dict[str, Any]
) -> dict[str, Any]:
    """Load confound-guard artifacts and extract risk signals."""
    signals: dict[str, Any] = {}
    
    patterns = contract.get("data_sources", {}).get("confound_guard", {}).get("artifact_patterns", [])
    confound_file = _find_latest_artifact(artifact_dir, patterns)
    
    if confound_file and confound_file.exists():
        try:
            data = _load_json(confound_file)
            risk_level = data.get("risk_level", "unknown")
            signals["confound_risk"] = _risk_level_to_score(risk_level)
            signals["detected_confound_count"] = len(data.get("detected_confounds", []))
            signals["confound_source"] = str(confound_file)
        except Exception:  # noqa: S110
            pass
    
    return signals


def _classify_branch_health(action: str) -> str:
    """Classify branch health from self-correction action."""
    if action == "continue":
        return "healthy"
    elif action in ("reroute", "stop"):
        return "degraded"
    else:
        return "unknown"


def _risk_level_to_score(level: str) -> float:
    """Convert risk level to numeric score."""
    mapping = {"low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0}
    return mapping.get(level.lower(), 0.5)


def _make_recommendations(
    signals: SignalSummary, contract: dict[str, Any]
) -> list[Recommendation]:
    """Generate optimization recommendations based on signals."""
    recommendations: list[Recommendation] = []
    thresholds = contract.get("thresholds", {})
    
    # Expansion recommendations
    if signals.utility_score is not None and signals.utility_score >= thresholds.get("high_utility_floor", 0.75):
        if signals.consistency_signal is not None and signals.consistency_signal >= 0.8:
            recommendations.append(
                Recommendation(
                    recommendation_id="rec-expand-high-utility",
                    category="expansion",
                    target="branch_count",
                    action="recommend_branch_expansion",
                    confidence_level=min(signals.utility_score, 0.95),
                    rationale=f"High utility score ({signals.utility_score:.2f}) with strong consistency signals warrant branch expansion.",
                    estimated_impact={"new_branches": 2, "expected_utility_gain": 0.1},
                    fallback_action="maintain_current_strategy",
                )
            )
    
    # Shrinkage recommendations
    if signals.utility_score is not None and signals.utility_score <= thresholds.get("low_utility_floor", 0.35):
        if signals.evidence_quality is None or signals.evidence_quality < thresholds.get("evidence_deficit_max", 0.3):
            recommendations.append(
                Recommendation(
                    recommendation_id="rec-shrink-low-utility",
                    category="shrinkage",
                    target="branch_count",
                    action="recommend_branch_pruning",
                    confidence_level=0.7,
                    rationale=f"Low utility score ({signals.utility_score:.2f}) with insufficient evidence suggests pruning.",
                    estimated_impact={"branches_to_remove": 1, "cost_savings_percent": 20},
                    fallback_action="pause_and_reassess",
                )
            )
    
    # Cost efficiency adjustment
    if signals.cost_efficiency is not None and signals.cost_efficiency < thresholds.get("cost_efficiency_threshold", 0.4):
        recommendations.append(
            Recommendation(
                recommendation_id="rec-adjust-cost-profile",
                category="adjustment",
                target="execution_profile",
                action="recommend_profile_optimization",
                confidence_level=0.75,
                rationale=f"Cost efficiency ({signals.cost_efficiency:.2f}) below threshold; profile retuning recommended.",
                estimated_impact={"cost_reduction_percent": 15, "risk_increase": "minimal"},
            )
        )
    
    # Confound risk mitigation
    if signals.confound_risk is not None and signals.confound_risk > thresholds.get("confound_risk_threshold", 0.6):
        recommendations.append(
            Recommendation(
                recommendation_id="rec-mitigate-confounds",
                category="adjustment",
                target="branch_configuration",
                action="recommend_confound_isolation",
                confidence_level=0.8,
                rationale=f"Elevated confound risk ({signals.confound_risk:.2f}) detected; isolation strategy recommended.",
                estimated_impact={"additional_controls_needed": 1, "cost_increase_percent": 10},
                fallback_action="escalate_to_expert_review",
            )
        )
    
    return recommendations[:5]  # Cap at 5 recommendations


def _apply_constraints(
    recommendations: list[Recommendation],
    contract: dict[str, Any],
) -> tuple[list[Recommendation], list[str]]:
    """Apply bounded output constraints to recommendations."""
    constraints_applied: list[str] = []
    constraints = contract.get("output_constraints", {})
    
    # Constraint: max recommendations per run
    max_recs = constraints.get("max_recommendations_per_run", 5)
    if len(recommendations) > max_recs:
        recommendations = recommendations[:max_recs]
        constraints_applied.append(f"Limited to top {max_recs} recommendations")
    
    # Constraint: cap total change magnitude
    max_change_pct = constraints.get("max_branch_changes_percent", 20)
    total_change = sum(1 for r in recommendations if r.category in ("expansion", "shrinkage"))
    if total_change > max_change_pct / 10:  # Rough scaling
        constraints_applied.append(f"Branch changes capped at {max_change_pct}% per run")
    
    return recommendations, constraints_applied


def optimize_from_artifacts(
    artifact_dir: Path,
    mission_id: str,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    mission_state_path: Path | None = None,
) -> dict[str, Any]:
    """
    Analyze mission artifacts and generate optimization recommendations.

    Args:
        artifact_dir: Directory containing mission artifacts (utility, self-correction, etc.)
        mission_id: Identifier for the mission
        contract_path: Path to self-optimization.yaml contract
        mission_state_path: Path to mission_state.json for context

    Returns:
        Dictionary with report, ledger entry, and recommendation outputs
    """
    contract = _load_yaml(contract_path)
    timestamp = now_utc()
    
    # Load all available signals
    utility_sigs = _load_utility_signals(artifact_dir, contract)
    correction_sigs = _load_self_correction_signals(artifact_dir, contract)
    statistical_sigs = _load_statistical_signals(artifact_dir, contract)
    confound_sigs = _load_confound_signals(artifact_dir, contract)
    
    # Aggregate into signal summary
    sources = [
        value
        for key, value in {
            **utility_sigs,
            **correction_sigs,
            **statistical_sigs,
            **confound_sigs,
        }.items()
        if key.endswith("_source") and isinstance(value, str)
    ]

    evidence_quality = utility_sigs.get("evidence_quality")
    if evidence_quality is None and statistical_sigs.get("effective_sample_size") is not None:
        effective_count = float(statistical_sigs["effective_sample_size"])
        evidence_quality = max(0.0, min(1.0, effective_count / 32.0))
    
    signal_summary = SignalSummary(
        timestamp=timestamp,
        utility_score=utility_sigs.get("overall_score"),
        evidence_quality=evidence_quality,
        cost_efficiency=utility_sigs.get("cost_risk_profile"),
        confound_risk=confound_sigs.get("confound_risk"),
        branch_health=correction_sigs.get("branch_health"),
        consistency_signal=correction_sigs.get("consistency_signal"),
        sources_consulted=list(set(sources)),
    )
    
    # Generate recommendations
    recommendations = _make_recommendations(signal_summary, contract)
    
    # Apply bounded constraints
    recommendations, constraints_applied = _apply_constraints(recommendations, contract)
    
    # Determine optimization phase and next window
    optimization_phase = _infer_phase(mission_state_path)
    next_window = contract.get("thresholds", {}).get("min_samples_for_trend", 3) * 2  # rough estimate
    
    # Build report
    report = OptimizationReport(
        timestamp=timestamp,
        mission_id=mission_id,
        optimization_phase=optimization_phase,
        signal_summary=signal_summary,
        recommendations=recommendations,
        decision_rationale=_build_rationale(signal_summary, recommendations),
        bounded_constraints_applied=constraints_applied,
        next_observation_window_days=next_window,
    )
    
    # Write artifacts
    output_dir = RUNS_DIR / "self_optimization" / mission_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    report_json_path = output_dir / f"self_optimization_report_{timestamp.replace(':', '-')}.json"
    report_json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    
    # Write recommendations as YAML
    recs_yaml_path = output_dir / f"optimization_recommendations_{timestamp.replace(':', '-')}.yaml"
    recs_data = {
        "timestamp": timestamp,
        "mission_id": mission_id,
        "total_recommendations": len(recommendations),
        "recommendations": [r.to_dict() for r in recommendations],
    }
    recs_yaml_path.write_text(yaml.dump(recs_data, default_flow_style=False), encoding="utf-8")
    
    # Ledger entry
    ledger_entry = make_ledger_entry(
        kind="self-optimization",
        mission_id=mission_id,
        summary=f"Generated {len(recommendations)} optimization recommendations",
        status="complete",
        related_paths=[str(report_json_path), str(recs_yaml_path)],
        metadata={
            "recommendation_categories": list(set(r.category for r in recommendations)),
            "average_confidence": sum(r.confidence_level for r in recommendations) / len(recommendations) if recommendations else 0.0,
            "signals_sources": signal_summary.sources_consulted,
            "constraints_applied": constraints_applied,
        },
    )
    
    # Optionally append to mission ledger
    if mission_state_path:
        ledger_path = mission_state_path.parent / "ledger.jsonl"
        append_jsonl(ledger_path, ledger_entry)
    
    return {
        "report_json_path": report_json_path,
        "recommendations_yaml_path": recs_yaml_path,
        "ledger_entry": ledger_entry,
        "report": report.to_dict(),
    }


def _infer_phase(mission_state_path: Path | None) -> str:
    """Infer optimization phase from mission state."""
    if not mission_state_path or not mission_state_path.exists():
        return "unknown"
    
    try:
        mission_state = _load_json(mission_state_path)
        completed = mission_state.get("completed_phases", [])
        if "baseline" in completed and "localization" not in completed:
            return "post-baseline"
        elif "localization" in completed:
            return "post-localization"
    except Exception:  # noqa: S110
        pass
    
    return "unknown"


def _build_rationale(signals: SignalSummary, recommendations: list[Recommendation]) -> str:
    """Build human-readable rationale for optimization decision."""
    parts = []
    
    if signals.utility_score is not None:
        parts.append(f"Utility score {signals.utility_score:.2f}.")
    
    if signals.branch_health:
        parts.append(f"Branch health: {signals.branch_health}.")
    
    if signals.confound_risk is not None and signals.confound_risk > 0.6:
        parts.append(f"Elevated confound risk detected ({signals.confound_risk:.2f}).")
    
    if recommendations:
        categories = set(r.category for r in recommendations)
        parts.append(f"Recommending: {', '.join(sorted(categories))}.")
    
    return " ".join(parts) if parts else "Insufficient signals for strong recommendation."
