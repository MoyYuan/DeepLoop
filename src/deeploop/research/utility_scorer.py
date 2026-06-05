"""
DeepLoop utility scorer for branch ranking and prioritization.

Produces deterministic multi-factor scores combining evidence quality,
replication gap, cost/risk profile, novelty proxy, and expected information
gain to rank experiment branches for autonomous decision-making.

Integrates autonomy artifacts (sanity, self-correction, statistical-rigor,
confound-guard) and produces JSON/Markdown reports with ledger integration.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.structured_io import load_json as _load_json, load_yaml as _load_yaml
from deeploop.core.paths import REPO_ROOT

DEFAULT_CONTRACT_PATH = REPO_ROOT / "configs" / "autonomy" / "utility-scorer.yaml"
DEFAULT_CROSS_BRANCH_VARIANCE = 0.3
_ARTIFACT_LOAD_ERROR_TYPES = (OSError, TypeError, ValueError)


def _round_float(value: float | None, places: int = 6) -> float | None:
    """Round float to specified decimal places."""
    if value is None:
        return None
    return round(float(value), places)


def _find_artifact_file(
    branch_dir: Path, patterns: list[str]
) -> Optional[Path]:
    """Find first matching artifact file in branch directory."""
    for pattern in patterns:
        if "*" in pattern:
            matches = list(branch_dir.glob(pattern))
            if matches:
                return matches[0]
        else:
            candidate = branch_dir / pattern
            if candidate.exists():
                return candidate
    return None


def _record_artifact_warning(
    bundle: dict[str, Any], artifact_name: str, path: Path, exc: Exception
) -> None:
    warnings = bundle.setdefault("artifact_warnings", [])
    warnings.append(f"{artifact_name} artifact {path.name} could not be loaded: {exc}")


def _load_optional_json_artifact(
    bundle: dict[str, Any], artifact_name: str, path: Path
) -> dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except _ARTIFACT_LOAD_ERROR_TYPES as exc:
        _record_artifact_warning(bundle, artifact_name, path, exc)
        return None
    if not isinstance(payload, dict):
        _record_artifact_warning(
            bundle,
            artifact_name,
            path,
            TypeError("expected a JSON object"),
        )
        return None
    return payload


@dataclass
class ScoreFactors:
    """Container for individual scoring factors."""

    evidence_quality: float
    replication_gap: float
    cost_risk_profile: float
    novelty_proxy: float
    expected_information_gain: float

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass
class BranchScore:
    """Utility score for a single branch."""

    branch_id: str
    overall_score: float
    factors: ScoreFactors
    recommendation: str
    justification: str
    critical_alerts: list[str]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "branch_id": self.branch_id,
            "overall_score": self.overall_score,
            "factors": self.factors.to_dict(),
            "recommendation": self.recommendation,
            "justification": self.justification,
            "critical_alerts": self.critical_alerts,
            "metadata": self.metadata,
        }


def _compute_evidence_quality(bundle: dict[str, Any]) -> tuple[float, str]:
    """
    Compute evidence quality factor from statistical-rigor artifacts.

    Range: [0, 1], higher is better.
    """
    metadata = bundle.get("metadata", {})
    metrics = bundle.get("metrics", {})

    # Extract components
    effective_count = float(metadata.get("effective_count", 10))
    warning_count = int(metadata.get("warning_count", 0))

    primary_metric = metrics.get("primary_estimate", {})
    if isinstance(primary_metric, dict):
        ci_width = float(primary_metric.get("confidence_interval_width", 0.5))
    else:
        ci_width = 0.5

    # Normalize effective sample size (10-1000 range)
    sample_size_factor = min(1.0, max(0, (effective_count - 10) / 500))

    # Invert CI width (narrower = higher quality)
    ci_quality_factor = max(0, 1 - min(1.0, ci_width / 0.5))

    # Penalize warnings
    warning_factor = max(0, 1 - (warning_count * 0.1))

    # Geometric mean for combined factor
    if sample_size_factor > 0 and ci_quality_factor > 0 and warning_factor > 0:
        evidence_quality = pow(
            sample_size_factor * ci_quality_factor * warning_factor, 1 / 3
        )
    else:
        evidence_quality = 0.0

    evidence_quality = _round_float(evidence_quality, 6)

    justification = (
        f"Sample size factor: {_round_float(sample_size_factor, 3)}, "
        f"CI quality factor: {_round_float(ci_quality_factor, 3)}, "
        f"Warning factor: {_round_float(warning_factor, 3)}"
    )

    return evidence_quality, justification


def _compute_replication_gap(bundle: dict[str, Any]) -> tuple[float, str]:
    """
    Compute replication gap factor from self-correction and sanity-gates.

    Range: [0, 1], higher means better replicated/stable.
    """
    metadata = bundle.get("metadata", {})

    consistency_score = float(metadata.get("self_correction_consistency", 0.5))
    sanity_pass_rate = float(metadata.get("sanity_pass_rate", 0.5))
    branch_variance = float(
        metadata.get("cross_branch_variance", DEFAULT_CROSS_BRANCH_VARIANCE)
    )

    # Stability: invert variance
    stability_component = max(0, 1 - branch_variance)

    # Combined: weighted average
    replication_gap = (
        0.4 * consistency_score
        + 0.3 * sanity_pass_rate
        + 0.3 * stability_component
    )
    replication_gap = _round_float(replication_gap, 6)

    justification = (
        f"Consistency: {_round_float(consistency_score, 3)}, "
        f"Sanity pass rate: {_round_float(sanity_pass_rate, 3)}, "
        f"Stability: {_round_float(stability_component, 3)}"
    )

    return replication_gap, justification


def _compute_cost_risk_profile(bundle: dict[str, Any]) -> tuple[float, str]:
    """
    Compute cost/risk factor from runtime metrics.

    Range: [0, 1], higher means more efficient/lower risk.
    """
    runtime = bundle.get("runtime_metrics", {})

    gpu_hours = float(runtime.get("gpu_hours", 1.0))
    memory_gb = float(runtime.get("peak_memory_gb", 20.0))
    retry_count = int(runtime.get("retry_count", 0))
    total_seconds = float(runtime.get("total_seconds", 3600.0))

    # Cost factors
    gpu_cost_factor = max(0, 1 - min(1.0, gpu_hours / 4))
    memory_factor = max(0, 1 - min(1.0, memory_gb / 40))
    reliability_factor = max(0, 1 - (retry_count * 0.15))

    # Efficiency: wall time per GPU hour
    if gpu_hours > 0:
        wall_hours = total_seconds / 3600
        efficiency_ratio = gpu_hours / max(0.1, wall_hours)
        efficiency_factor = min(1.0, max(0, efficiency_ratio))
    else:
        efficiency_factor = 0.5

    # Combined
    cost_risk = (
        0.35 * gpu_cost_factor
        + 0.25 * memory_factor
        + 0.25 * reliability_factor
        + 0.15 * efficiency_factor
    )
    cost_risk = _round_float(cost_risk, 6)

    justification = (
        f"GPU efficiency: {_round_float(gpu_cost_factor, 3)}, "
        f"Memory efficiency: {_round_float(memory_factor, 3)}, "
        f"Reliability: {_round_float(reliability_factor, 3)}, "
        f"Execution efficiency: {_round_float(efficiency_factor, 3)}"
    )

    return cost_risk, justification


def _compute_novelty_proxy(bundle: dict[str, Any]) -> tuple[float, str]:
    """
    Compute novelty proxy from findings deviation and unexpectedness.

    Range: [0, 1], higher means more novel/unexpected.
    """
    metrics = bundle.get("metrics", {})
    findings = bundle.get("findings", {})

    finding_deviation = float(metrics.get("finding_deviation_from_baseline", 0.0))
    unexpectedness = float(metrics.get("unexpectedness_factor", 0.5))
    findings_count = int(findings.get("total_count", 1))
    baseline_count = int(findings.get("baseline_count", 1))

    # Deviation component (cap at 0.3 for scaling)
    deviation_component = min(1.0, abs(finding_deviation) / 0.3)

    # Finding ratio
    finding_ratio = min(1.0, findings_count / max(1, baseline_count))

    # Combined
    novelty = (
        0.4 * deviation_component
        + 0.35 * unexpectedness
        + 0.25 * finding_ratio
    )
    novelty = _round_float(novelty, 6)

    justification = (
        f"Deviation: {_round_float(deviation_component, 3)}, "
        f"Unexpectedness: {_round_float(unexpectedness, 3)}, "
        f"Finding ratio: {_round_float(finding_ratio, 3)}"
    )

    return novelty, justification


def _compute_expected_information_gain(bundle: dict[str, Any]) -> tuple[float, str]:
    """
    Compute expected information gain from confound-guard and mechanistic clarity.

    Range: [0, 1], higher means more potential for learning.
    """
    metadata = bundle.get("metadata", {})

    confound_pass_rate = float(metadata.get("confound_pass_rate", 0.5))
    mechanistic_clarity = float(metadata.get("mechanistic_clarity", 0.5))
    gap_closure = float(metadata.get("gap_closure_potential", 0.5))

    # Combined
    eig = 0.5 * confound_pass_rate + 0.3 * mechanistic_clarity + 0.2 * gap_closure
    eig = _round_float(eig, 6)

    justification = (
        f"Confound safety: {_round_float(confound_pass_rate, 3)}, "
        f"Mechanistic clarity: {_round_float(mechanistic_clarity, 3)}, "
        f"Gap closure potential: {_round_float(gap_closure, 3)}"
    )

    return eig, justification


def _build_factor_justifications(
    evidence: tuple[float, str],
    replication: tuple[float, str],
    cost: tuple[float, str],
    novelty: tuple[float, str],
    eig: tuple[float, str],
) -> dict[str, str]:
    """Build justification dictionary from factor tuples."""
    return {
        "evidence_quality": evidence[1],
        "replication_gap": replication[1],
        "cost_risk_profile": cost[1],
        "novelty_proxy": novelty[1],
        "expected_information_gain": eig[1],
    }


def _compute_overall_score(
    factors: ScoreFactors, bundle: dict[str, Any]
) -> tuple[float, list[str]]:
    """
    Compute overall utility score with penalties.

    Returns: (score, critical_alerts)
    """
    weights = {
        "evidence_quality": 0.25,
        "replication_gap": 0.20,
        "cost_risk_profile": 0.20,
        "novelty_proxy": 0.20,
        "expected_information_gain": 0.15,
    }

    weighted_score = (
        weights["evidence_quality"] * factors.evidence_quality
        + weights["replication_gap"] * factors.replication_gap
        + weights["cost_risk_profile"] * factors.cost_risk_profile
        + weights["novelty_proxy"] * factors.novelty_proxy
        + weights["expected_information_gain"] * factors.expected_information_gain
    )

    alerts: list[str] = []
    penalties = 0.0

    # Penalty: low evidence quality
    if factors.evidence_quality < 0.30:
        penalties += 0.15
        alerts.append(
            f"Low evidence quality ({_round_float(factors.evidence_quality, 3)}): "
            "insufficient sample size or high uncertainty"
        )

    # Penalty: high confound risk
    confound_risk = 1 - factors.expected_information_gain
    if confound_risk > 0.70:
        penalties += 0.20
        alerts.append(
            f"High confound risk ({_round_float(confound_risk, 3)}): "
            "potential hidden variables may confound findings"
        )

    # Penalty: high cost (relative to median)
    runtime = bundle.get("runtime_metrics", {})
    gpu_hours = float(runtime.get("gpu_hours", 0))
    if gpu_hours > 4:  # 2x typical 2-hour limit
        penalties += 0.10
        alerts.append(
            f"High resource cost ({gpu_hours} GPU hours): "
            "expensive relative to typical experiments"
        )

    # Apply penalties
    adjusted_score = max(0.0, weighted_score - penalties)
    adjusted_score = _round_float(adjusted_score, 6)

    return adjusted_score, alerts


def _get_recommendation(
    score: float, factors: ScoreFactors, alerts: list[str]
) -> tuple[str, str]:
    """
    Determine recommendation based on score and factors.

    Returns: (recommendation_state, justification)
    """
    # PRIORITIZE: high score with strong evidence
    if score >= 0.80 and factors.evidence_quality >= 0.60:
        return (
            "PRIORITIZE",
            "High utility score with strong empirical support. "
            "Candidate for immediate follow-up or publication.",
        )

    # CONTINUE: moderate-to-high score or high novelty with moderate support
    if 0.60 <= score < 0.80:
        return (
            "CONTINUE",
            "Moderate utility score. Worth pursuing with replication or refinement.",
        )

    if score >= 0.50 and factors.novelty_proxy > 0.70:
        return (
            "CONTINUE",
            "Unexpected findings with reasonable support. Pursue mechanistic understanding.",
        )

    # DEFER: low-moderate score
    if 0.40 <= score < 0.60:
        return (
            "DEFER",
            "Low priority but not hopeless. Revisit after higher-priority branches complete.",
        )

    # PRUNE: very low score or critical issues
    if score < 0.40:
        return (
            "PRUNE",
            "Insufficient value for current resource constraints.",
        )

    if len(alerts) > 1 and factors.evidence_quality < 0.40:
        return (
            "PRUNE",
            "Multiple critical issues with weak evidence support.",
        )

    # Default to DEFER
    return (
        "DEFER",
        "Unable to classify decisively; recommend deferral pending additional context.",
    )


def _load_branch_artifacts(branch_dir: Path) -> dict[str, Any]:
    """Load all available autonomy artifacts for a branch."""
    bundle: dict[str, Any] = {
        "branch_dir": str(branch_dir),
        "metadata": {},
        "metrics": {},
        "runtime_metrics": {},
        "findings": {"total_count": 0, "baseline_count": 0},
        "artifact_warnings": [],
    }

    # Look for statistical-rigor report
    rigor_report = _find_artifact_file(
        branch_dir,
        [
            "utility-rigor-report.json",
            "*-statistical-rigor*.json",
            "statistical-rigor.json",
        ],
    )
    if rigor_report:
        rigor = _load_optional_json_artifact(
            bundle, "statistical-rigor", rigor_report
        )
        if rigor is not None:
            metadata = rigor.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            bundle["metadata"]["effective_count"] = metadata.get(
                "effective_count", 10
            )
            bundle["metadata"]["warning_count"] = metadata.get("warning_count", 0)
            metrics = rigor.get("metrics")
            if not isinstance(metrics, dict):
                metrics = {}
            primary = metrics.get("primary", {})
            if isinstance(primary, dict):
                confidence_interval = primary.get("confidence_interval")
                if not isinstance(confidence_interval, dict):
                    confidence_interval = {}
                bundle["metrics"]["primary_estimate"] = {
                    "confidence_interval_width": confidence_interval.get("width", 0.5)
                }

    # Look for self-correction report
    self_correct = _find_artifact_file(
        branch_dir,
        [
            "*-self-correction*.json",
            "self-correction.json",
            "corrections.json",
        ],
    )
    if self_correct:
        sc = _load_optional_json_artifact(bundle, "self-correction", self_correct)
        if sc is not None:
            metadata = sc.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            bundle["metadata"]["self_correction_consistency"] = metadata.get(
                "consistency_score", 0.5
            )

    # Look for sanity-gates report
    sanity = _find_artifact_file(
        branch_dir,
        [
            "*-sanity-gates*.json",
            "sanity-gates.json",
            "sanity.json",
        ],
    )
    if sanity:
        sg = _load_optional_json_artifact(bundle, "sanity-gates", sanity)
        if sg is not None:
            checks = sg.get("checks", [])
            if not isinstance(checks, list):
                checks = []
            passed = sum(
                1
                for c in checks
                if isinstance(c, dict) and c.get("status") == "passed"
            )
            total = len(checks)
            bundle["metadata"]["sanity_pass_rate"] = (
                passed / total if total > 0 else 0.5
            )
            findings = sg.get("findings", {})
            if not isinstance(findings, dict):
                findings = {}
            bundle["findings"]["total_count"] = findings.get("total_count", 0)
            bundle["findings"]["baseline_count"] = findings.get(
                "baseline_count", 1
            )
            bundle["metrics"]["finding_deviation_from_baseline"] = findings.get(
                "deviation_from_baseline", 0.0
            )
            bundle["metrics"]["unexpectedness_factor"] = findings.get(
                "unexpectedness", 0.5
            )

    # Look for confound-guard report
    confound = _find_artifact_file(
        branch_dir,
        [
            "*-confound-guard*.json",
            "confound-guard.json",
            "confounds.json",
        ],
    )
    if confound:
        cg = _load_optional_json_artifact(bundle, "confound-guard", confound)
        if cg is not None:
            threats = cg.get("threats", [])
            if not isinstance(threats, list):
                threats = []
            mitigated = sum(
                1
                for t in threats
                if isinstance(t, dict) and t.get("status") == "mitigated"
            )
            total = len(threats)
            bundle["metadata"]["confound_pass_rate"] = (
                mitigated / total if total > 0 else 0.5
            )
            metadata = cg.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            bundle["metadata"]["mechanistic_clarity"] = metadata.get(
                "mechanistic_clarity", 0.5
            )
            bundle["metadata"]["gap_closure_potential"] = metadata.get(
                "gap_closure_potential", 0.5
            )

    # Look for runtime metrics in manifest
    manifest = _find_artifact_file(
        branch_dir, ["manifest.json", "*-manifest.json"]
    )
    if manifest:
        mf = _load_optional_json_artifact(bundle, "manifest", manifest)
        if mf is not None:
            artifacts = mf.get("artifacts", {})
            if not isinstance(artifacts, dict):
                artifacts = {}
            runtime = artifacts.get("runtime", {})
            if not isinstance(runtime, dict):
                runtime = {}
            bundle["runtime_metrics"]["gpu_hours"] = runtime.get("gpu_hours", 1.0)
            bundle["runtime_metrics"]["peak_memory_gb"] = runtime.get(
                "peak_memory_gb", 20.0
            )
            bundle["runtime_metrics"]["retry_count"] = runtime.get("retry_count", 0)
            bundle["runtime_metrics"]["total_seconds"] = runtime.get(
                "total_seconds", 3600.0
            )

    # Set defaults for missing values
    bundle["metadata"].setdefault("sanity_pass_rate", 0.5)
    bundle["metadata"].setdefault("self_correction_consistency", 0.5)
    bundle["metadata"].setdefault("confound_pass_rate", 0.5)
    bundle["metadata"].setdefault("mechanistic_clarity", 0.5)
    bundle["metadata"].setdefault("gap_closure_potential", 0.5)
    bundle["metadata"].setdefault(
        "cross_branch_variance", DEFAULT_CROSS_BRANCH_VARIANCE
    )

    return bundle


def score_branch(branch_id: str, branch_dir: Path) -> BranchScore:
    """Score a single experiment branch."""
    bundle = _load_branch_artifacts(branch_dir)

    # Compute individual factors
    evidence, evidence_just = _compute_evidence_quality(bundle)
    replication, replication_just = _compute_replication_gap(bundle)
    cost, cost_just = _compute_cost_risk_profile(bundle)
    novelty, novelty_just = _compute_novelty_proxy(bundle)
    eig, eig_just = _compute_expected_information_gain(bundle)

    factors = ScoreFactors(
        evidence_quality=evidence,
        replication_gap=replication,
        cost_risk_profile=cost,
        novelty_proxy=novelty,
        expected_information_gain=eig,
    )

    # Compute overall score
    overall, alerts = _compute_overall_score(factors, bundle)

    # Get recommendation
    recommendation, rec_just = _get_recommendation(overall, factors, alerts)

    # Build full justification
    full_justification = (
        f"{recommendation}: {rec_just}\n\n"
        f"Factor breakdown:\n"
        f"  Evidence Quality: {evidence_just}\n"
        f"  Replication Gap: {replication_just}\n"
        f"  Cost/Risk Profile: {cost_just}\n"
        f"  Novelty Proxy: {novelty_just}\n"
        f"  Expected Information Gain: {eig_just}"
    )

    return BranchScore(
        branch_id=branch_id,
        overall_score=overall,
        factors=factors,
        recommendation=recommendation,
        justification=full_justification,
        critical_alerts=alerts,
        metadata={
            "artifact_paths": {
                "branch_dir": str(branch_dir),
            },
            "artifact_warnings": list(bundle.get("artifact_warnings", [])),
            "scoring_timestamp": now_utc(),
        },
    )


def _write_markdown_report(
    path: Path, ranked_branches: list[BranchScore], summary: dict[str, Any]
) -> None:
    """Write human-readable markdown utility report."""
    lines: list[str] = [
        "# Utility Score Report\n",
        f"Generated: {now_utc()}\n",
        f"Total branches scored: {summary['total_branches']}\n",
    ]

    # Summary statistics
    lines.extend(
        [
            "\n## Summary Statistics\n",
            f"- Mean utility score: {_round_float(summary['mean_score'], 3)}\n",
            f"- Median utility score: {_round_float(summary['median_score'], 3)}\n",
            f"- Std deviation: {_round_float(summary['std_dev'], 3)}\n",
            f"- Min score: {_round_float(summary['min_score'], 3)}\n",
            f"- Max score: {_round_float(summary['max_score'], 3)}\n",
        ]
    )

    # Recommendations summary
    rec_counts = summary.get("recommendations_count", {})
    lines.extend(
        [
            "\n## Recommendation Breakdown\n",
        ]
    )
    for rec, count in sorted(rec_counts.items()):
        lines.append(f"- **{rec}**: {count} branches\n")

    # Ranked branches
    lines.append("\n## Ranked Branches\n")
    for i, branch in enumerate(ranked_branches, 1):
        lines.extend(
            [
                f"\n### {i}. {branch.branch_id}\n",
                f"**Score**: {_round_float(branch.overall_score, 3)}\n",
                f"**Recommendation**: {branch.recommendation}\n",
                f"\n**Factors**:\n",
                f"- Evidence Quality: {_round_float(branch.factors.evidence_quality, 3)}\n",
                f"- Replication Gap: {_round_float(branch.factors.replication_gap, 3)}\n",
                f"- Cost/Risk: {_round_float(branch.factors.cost_risk_profile, 3)}\n",
                f"- Novelty Proxy: {_round_float(branch.factors.novelty_proxy, 3)}\n",
                f"- Information Gain: {_round_float(branch.factors.expected_information_gain, 3)}\n",
            ]
        )

        if branch.critical_alerts:
            lines.append(f"\n**Critical Alerts**:\n")
            for alert in branch.critical_alerts:
                lines.append(f"- ⚠️  {alert}\n")

        artifact_warnings = branch.metadata.get("artifact_warnings", [])
        if artifact_warnings:
            lines.append("\n**Artifact Warnings**:\n")
            for warning in artifact_warnings:
                lines.append(f"- {warning}\n")

        lines.append(f"\n{branch.justification}\n")

    path.write_text("".join(lines), encoding="utf-8")


def evaluate_utility_score(
    branches_dir: Path,
    *,
    mission_state_path: Optional[Path] = None,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    artifact_name: Optional[str] = None,
) -> dict[str, Any]:
    """
    Evaluate utility scores for all branches in a directory.

    Args:
        branches_dir: Directory containing branch subdirectories
        mission_state_path: Path to mission_state.json for ledger linking
        contract_path: Path to utility-scorer.yaml contract
        artifact_name: Optional name for output artifacts

    Returns:
        Dictionary with scoring results and artifact paths
    """
    if not branches_dir.is_dir():
        raise FileNotFoundError(f"Branches directory not found: {branches_dir}")

    # Discover branches
    branch_dirs = sorted([d for d in branches_dir.iterdir() if d.is_dir()])
    if not branch_dirs:
        raise FileNotFoundError(f"No branch directories found in {branches_dir}")

    # Score all branches
    all_scores: list[BranchScore] = []
    for branch_dir in branch_dirs:
        branch_id = branch_dir.name
        score = score_branch(branch_id, branch_dir)
        all_scores.append(score)

    # Sort by score descending
    ranked = sorted(all_scores, key=lambda s: s.overall_score, reverse=True)

    # Compute summary statistics
    scores = [s.overall_score for s in all_scores]
    summary = {
        "total_branches": len(all_scores),
        "mean_score": sum(scores) / len(scores) if scores else 0.0,
        "median_score": sorted(scores)[len(scores) // 2] if scores else 0.0,
        "std_dev": (
            math.sqrt(
                sum((s - (sum(scores) / len(scores))) ** 2 for s in scores)
                / len(scores)
            )
            if len(scores) > 1
            else 0.0
        ),
        "min_score": min(scores) if scores else 0.0,
        "max_score": max(scores) if scores else 0.0,
        "recommendations_count": {},
    }

    for branch in all_scores:
        rec = branch.recommendation
        summary["recommendations_count"][rec] = (
            summary["recommendations_count"].get(rec, 0) + 1
        )

    # Determine artifact stem
    if artifact_name is None:
        artifact_name = f"utility-score-{branches_dir.name}"
    artifact_stem = artifact_name.replace("/", "-").replace(" ", "-")

    # Create reports directory
    reports_dir = branches_dir.parent / "utility-score-reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Write JSON report
    report_json_path = reports_dir / f"{artifact_stem}-report.json"
    report_dict = {
        "created_at": now_utc(),
        "summary": summary,
        "ranked_branches": [branch.to_dict() for branch in ranked],
    }
    report_json_path.write_text(
        json.dumps(report_dict, indent=2) + "\n", encoding="utf-8"
    )

    # Write markdown report
    report_md_path = reports_dir / f"{artifact_stem}-summary.md"
    _write_markdown_report(report_md_path, ranked, summary)

    # Write ledger entry
    if mission_state_path is not None and mission_state_path.exists():
        mission_state = _load_json(mission_state_path)
        top_rec = ranked[0].recommendation if ranked else "UNKNOWN"
        top_score = _round_float(ranked[0].overall_score, 3) if ranked else 0.0

        append_jsonl(
            mission_state_path.parent / "ledger.jsonl",
            make_ledger_entry(
                kind="utility-score",
                mission_id=mission_state["mission_id"],
                summary=f"Utility scoring complete for {len(all_scores)} branches. "
                f"Top recommendation: {top_rec} (score: {top_score})",
                status="success",
                related_paths=[str(report_json_path), str(report_md_path)],
                metadata={
                    "total_branches": len(all_scores),
                    "top_recommendation": top_rec,
                    "top_score": top_score,
                    "mean_score": _round_float(summary["mean_score"], 3),
                    "recommendations_breakdown": summary["recommendations_count"],
                },
            ),
        )

    return {
        "report_json_path": report_json_path,
        "report_markdown_path": report_md_path,
        "ranked_branches": ranked,
        "summary": summary,
        "total_branches": len(all_scores),
    }
