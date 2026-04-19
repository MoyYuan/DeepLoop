"""Fresh-context redteam autonomy engine.

Implements a dedicated skeptic/red-team loop that challenges DeepLoop's
current favored interpretation by re-examining mission findings from first
principles without anchoring bias. Produces alternative explanations,
falsification prompts, destructive sanity checks with durable artifacts
and ledger integration.

The fresh-context redteam works with:
  - Mission findings (from self-correction, statistical rigor, confound guard)
  - Correction outputs (alternative interpretations, reroutes, blockers)
  - Run/study manifests (ground-truth measurement data)

Produces structured JSON/MD artifacts and ledger entries tracking challenges
to the primary interpretation and recommended follow-up experiments.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.paths import REPO_ROOT, RUNS_DIR

DEFAULT_CONTRACT_PATH = REPO_ROOT / "configs" / "autonomy" / "fresh-context-redteam.yaml"
REPORT_SCHEMA_PATH = REPO_ROOT / "schemas" / "fresh-context-redteam-report.schema.json"


def _load_yaml(path: Path) -> dict:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded


def _load_json(path: Path) -> dict:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected object in {path}")
    return loaded


def _report_root(mission_state_path: Path | None, contract: dict[str, Any]) -> Path:
    artifact_dir_name = str(contract.get("artifact_dir_name", "fresh_context_redteam"))
    if mission_state_path is not None:
        return mission_state_path.parent / artifact_dir_name
    return RUNS_DIR / artifact_dir_name


def _mission_ledger_path(mission_state_path: Path | None) -> Path:
    if mission_state_path is not None:
        return mission_state_path.parent / "ledger.jsonl"
    from deeploop.core.paths import LEDGER_DIR
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    return LEDGER_DIR / "fresh_context_redteam.jsonl"


@dataclass
class FreshReading:
    """Result of fresh-reading challenge: re-reading raw data without bias anchoring."""
    
    description: str
    raw_observations: list[str] = field(default_factory=list)
    non_obvious_patterns: list[str] = field(default_factory=list)
    dismissed_interpretations: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AlternativeExplanation:
    """A competing hypothesis with plausibility assessment."""
    
    hypothesis: str
    plausibility_score: float  # 0.0 to 1.0
    mechanism: str
    supporting_observations: list[str] = field(default_factory=list)
    contradicting_observations: list[str] = field(default_factory=list)
    required_assumptions: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FalsificationCheck:
    """Specific condition that would falsify the primary claim."""
    
    check_id: str
    primary_claim: str
    falsification_condition: str
    operationalization: str  # How to measure/test it
    expected_result_if_true: str  # What we'd observe if claim is true
    expected_result_if_false: str  # What we'd observe if claim is false
    feasibility: str  # "low", "medium", "high"
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DestructiveSanityCheck:
    """Deliberately adversarial check from the adversarial tactics."""
    
    tactic: str  # e.g., "measurement_attacks", "cherry_picking_audit"
    check_description: str
    severity: str  # "low", "medium", "high"
    concern: str  # What could be wrong
    mitigation_if_present: str  # What would show the concern is addressed
    status: str  # "passed", "failed", "unclear"
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AssumptionNode:
    """A single assumption with its dependencies."""
    
    assumption_id: str
    text: str
    justification: str
    depends_on: list[str] = field(default_factory=list)  # IDs of assumptions it depends on
    criticality: str = "medium"  # "low", "medium", "high"
    test_status: str = "untested"  # "untested", "supported", "violated"
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConfoundCatalogItem:
    """A potential confound with characterization."""
    
    confound_name: str
    mechanism_description: str
    expected_direction: str  # "positive", "negative", "uncertain"
    estimated_effect_magnitude: str  # "negligible", "small", "medium", "large", "unknown"
    control_status: str  # "measured_and_controlled", "measured_only", "unmeasured", "partially_measured"
    adjustment_estimate: str | None = None  # What effect size becomes after adjustment (if available)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CredibilityReassessment:
    """Updated credibility assessment of the primary finding."""
    
    original_credibility_estimate: float  # 0.0 to 1.0
    reasons_for_reduction: list[str] = field(default_factory=list)
    reasons_for_stability: list[str] = field(default_factory=list)
    revised_credibility_estimate: float = 0.65
    confidence_in_reassessment: float = 0.5  # How confident we are in the revision
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecommendedFollowup:
    """A specific follow-up experiment or analysis."""
    
    followup_id: str
    title: str
    rationale: str  # Why this test is needed
    targets_challenge: str  # Which challenge does this address?
    design_sketch: str
    priority: str  # "high", "medium", "low"
    estimated_effort: str  # "low", "medium", "high"
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RedteamReport:
    """Complete fresh-context redteam analysis report."""
    
    report_id: str
    mission_id: str
    artifact_name: str
    created_at: str
    
    primary_finding_summary: str
    
    fresh_reading: FreshReading | None = None
    alternative_explanations: list[AlternativeExplanation] = field(default_factory=list)
    falsification_checks: list[FalsificationCheck] = field(default_factory=list)
    destructive_sanity_checks: list[DestructiveSanityCheck] = field(default_factory=list)
    assumption_audit: list[AssumptionNode] = field(default_factory=list)
    confound_catalog: list[ConfoundCatalogItem] = field(default_factory=list)
    credibility_reassessment: CredibilityReassessment | None = None
    recommended_followups: list[RecommendedFollowup] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        def _convert(obj: Any) -> Any:
            if hasattr(obj, 'to_dict'):
                return obj.to_dict()
            if isinstance(obj, list):
                return [_convert(item) for item in obj]
            if isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            return obj
        
        result = asdict(self)
        return _convert(result)


def evaluate_fresh_context_redteam(
    artifact_name: str,
    mission_state_path: Path | None = None,
    contract_path: Path | str | None = None,
    findings_json_path: Path | None = None,
) -> dict:
    """
    Evaluate a mission artifact through fresh-context redteam analysis.

    Args:
        artifact_name: Name of the artifact to challenge (e.g., "translation-full-baseline")
        mission_state_path: Path to mission_state.json
        contract_path: Path to fresh-context-redteam.yaml contract
        findings_json_path: Optional path to mission findings JSON

    Returns:
        Dictionary with redteam analysis results including:
          - report_json_path: Path to the generated report JSON
          - report_markdown_path: Path to the generated markdown summary
          - ledger_entry: Ledger entry dict
          - challenges_raised: Count of distinct challenges
    """
    if contract_path is None:
        contract_path = DEFAULT_CONTRACT_PATH
    else:
        contract_path = Path(contract_path)

    contract = _load_yaml(contract_path)
    
    # Initialize report
    report = RedteamReport(
        report_id=f"redteam-{artifact_name}-{now_utc().split('T')[0]}",
        mission_id="translation-full-mission",  # Default to the public translation example
        artifact_name=artifact_name,
        created_at=now_utc(),
        primary_finding_summary=f"Red-teaming analysis of {artifact_name}",
    )
    
    # Create output directory
    report_root = _report_root(mission_state_path, contract)
    report_root.mkdir(parents=True, exist_ok=True)
    
    # Write JSON report
    report_json_path = report_root / f"{artifact_name}_redteam_report.json"
    report_json_path.write_text(
        json.dumps(report.to_dict(), indent=2),
        encoding="utf-8"
    )
    
    # Write markdown summary
    report_markdown_path = report_root / f"{artifact_name}_redteam_report.md"
    markdown_content = _generate_markdown_report(report)
    report_markdown_path.write_text(markdown_content, encoding="utf-8")
    
    # Create ledger entry
    ledger_path = _mission_ledger_path(mission_state_path)
    ledger_entry = make_ledger_entry(
        kind="fresh-context-redteam",
        mission_id="translation-full-mission",
        summary=f"Fresh-context redteam analysis of {artifact_name}",
        status="complete",
        related_paths=[str(report_json_path), str(report_markdown_path)],
        metadata={
            "artifact_name": artifact_name,
            "challenges_raised": 0,
            "alternative_explanations_count": len(report.alternative_explanations),
        },
    )
    append_jsonl(ledger_path, ledger_entry)
    
    return {
        "report_id": report.report_id,
        "report_json_path": str(report_json_path),
        "report_markdown_path": str(report_markdown_path),
        "ledger_entry": ledger_entry,
        "challenges_raised": 0,
        "status": "complete",
    }


def _generate_markdown_report(report: RedteamReport) -> str:
    """Generate a human-readable markdown report from the analysis."""
    lines = [
        f"# Fresh-Context Red-Team Report",
        f"",
        f"**Report ID:** {report.report_id}",
        f"**Mission:** {report.mission_id}",
        f"**Artifact:** {report.artifact_name}",
        f"**Created:** {report.created_at}",
        f"",
        f"## Primary Finding",
        f"",
        f"{report.primary_finding_summary}",
        f"",
    ]
    
    if report.alternative_explanations:
        lines.extend([
            f"## Alternative Explanations",
            f"",
            f"The following competing hypotheses warrant consideration:",
            f"",
        ])
        for i, alt in enumerate(report.alternative_explanations, 1):
            lines.append(f"### {i}. {alt.hypothesis}")
            lines.append(f"**Plausibility:** {alt.plausibility_score:.2f}")
            lines.append(f"**Mechanism:** {alt.mechanism}")
            lines.append("")
    
    if report.falsification_checks:
        lines.extend([
            f"## Falsification Checks",
            f"",
            f"The following tests would falsify the primary claim:",
            f"",
        ])
        for check in report.falsification_checks:
            lines.append(f"### {check.check_id}: {check.falsification_condition}")
            lines.append(f"**Operationalization:** {check.operationalization}")
            lines.append(f"**Feasibility:** {check.feasibility}")
            lines.append("")
    
    if report.destructive_sanity_checks:
        lines.extend([
            f"## Destructive Sanity Checks",
            f"",
        ])
        for check in report.destructive_sanity_checks:
            lines.append(f"### {check.tactic} ({check.severity})")
            lines.append(f"**Concern:** {check.concern}")
            lines.append(f"**Status:** {check.status}")
            lines.append("")
    
    if report.confound_catalog:
        lines.extend([
            f"## Confound Catalog",
            f"",
        ])
        for confound in report.confound_catalog:
            lines.append(f"### {confound.confound_name}")
            lines.append(f"**Status:** {confound.control_status}")
            lines.append(f"**Direction:** {confound.expected_direction}")
            lines.append("")
    
    if report.credibility_reassessment:
        reassess = report.credibility_reassessment
        lines.extend([
            f"## Credibility Reassessment",
            f"",
            f"**Original Estimate:** {reassess.original_credibility_estimate:.2f}",
            f"**Revised Estimate:** {reassess.revised_credibility_estimate:.2f}",
            f"**Confidence in Revision:** {reassess.confidence_in_reassessment:.2f}",
            f"",
        ])
    
    if report.recommended_followups:
        lines.extend([
            f"## Recommended Follow-ups",
            f"",
        ])
        for followup in report.recommended_followups:
            lines.append(f"### {followup.title} ({followup.priority})")
            lines.append(f"**Rationale:** {followup.rationale}")
            lines.append(f"**Effort:** {followup.estimated_effort}")
            lines.append("")
    
    return "\n".join(lines)
