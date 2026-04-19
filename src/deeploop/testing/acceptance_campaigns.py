from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

DEFAULT_ACCEPTANCE_CAMPAIGN = "translation-paper-scale"


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_strings(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        value = raw.strip()
        return [value] if value else []
    if isinstance(raw, list | tuple):
        values: list[str] = []
        for item in raw:
            values.extend(_normalize_strings(item))
        return values
    return [str(raw)]


def _path_exists(path_value: Any) -> bool:
    if not path_value:
        return False
    return Path(str(path_value)).expanduser().exists()


def build_acceptance_review(
    summary: Mapping[str, Any],
    *,
    campaign_id: str = DEFAULT_ACCEPTANCE_CAMPAIGN,
    implementation_stage: str = "plain-folder-proof-matrix",
) -> dict[str, Any]:
    case_summaries = [
        dict(case_summary)
        for case_summary in (summary.get("case_summaries") or [])
        if isinstance(case_summary, Mapping)
    ]
    failed_case_ids = _normalize_strings(summary.get("failed_case_ids"))
    proof_review = dict(summary.get("proof_review")) if isinstance(summary.get("proof_review"), Mapping) else {}
    boundary_clean_cases = 0
    final_report_cases = 0
    for case_summary in case_summaries:
        boundary_check = case_summary.get("boundary_check") if isinstance(case_summary.get("boundary_check"), Mapping) else {}
        if boundary_check.get("project_tree_unchanged", True):
            boundary_clean_cases += 1
        mission_state = case_summary.get("mission_state") if isinstance(case_summary.get("mission_state"), Mapping) else {}
        if _normalize_strings(mission_state.get("final_report_outputs")):
            final_report_cases += 1

    gate_results = [
        {
            "gate_id": "case-summaries-present",
            "passed": bool(case_summaries),
            "details": {"cases_run": len(case_summaries)},
        },
        {
            "gate_id": "all-cases-passed",
            "passed": summary.get("status") == "passed" and not failed_case_ids and bool(case_summaries),
            "details": {
                "campaign_status": str(summary.get("status") or "unknown"),
                "failed_case_ids": failed_case_ids,
            },
        },
        {
            "gate_id": "boundary-integrity",
            "passed": boundary_clean_cases == len(case_summaries) and bool(case_summaries),
            "details": {
                "boundary_clean_cases": boundary_clean_cases,
                "cases_run": len(case_summaries),
            },
        },
        {
            "gate_id": "final-report-evidence-present",
            "passed": final_report_cases == len(case_summaries) and bool(case_summaries),
            "details": {
                "final_report_cases": final_report_cases,
                "cases_run": len(case_summaries),
            },
        },
        {
            "gate_id": "proof-review-eligible",
            "passed": proof_review.get("decision") == "eligible-for-promotion",
            "details": {
                "decision": str(proof_review.get("decision") or "unknown"),
                "failed_gate_ids": _normalize_strings(proof_review.get("failed_gate_ids")),
            },
        },
        {
            "gate_id": "proof-review-artifacts-present",
            "passed": all(
                _path_exists(summary.get(key))
                for key in (
                    "review_json_path",
                    "review_markdown_path",
                    "summary_json_path",
                )
            ),
            "details": {
                key: str(summary.get(key) or "")
                for key in (
                    "review_json_path",
                    "review_markdown_path",
                    "summary_json_path",
                )
            },
        },
    ]
    failed_gate_ids = [gate["gate_id"] for gate in gate_results if not gate["passed"]]
    passed = not failed_gate_ids
    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "implementation_stage": implementation_stage,
        "updated_at": _now_utc(),
        "decision": "passed" if passed else "failed",
        "eligible_for_milestone_gate": passed,
        "summary": {
            "campaign_status": str(summary.get("status") or "unknown"),
            "campaign_root": str(summary.get("campaign_root") or ""),
            "summary_json_path": str(summary.get("summary_json_path") or ""),
            "cases_run": list(summary.get("cases_run") or []),
            "workflow_shapes": list(proof_review.get("workflow_shapes") or []),
            "caveats": list(summary.get("caveats") or []),
        },
        "failed_gate_ids": failed_gate_ids,
        "gates": gate_results,
        "artifacts": {
            key: str(summary.get(key) or "")
            for key in (
                "summary_json_path",
                "review_json_path",
                "review_markdown_path",
            )
        },
    }


def render_acceptance_review_markdown(review: dict[str, Any]) -> str:
    lines = [
        f"# Acceptance review: {review['campaign_id']}",
        "",
        f"- decision: **{review['decision']}**",
        f"- implementation_stage: `{review['implementation_stage']}`",
        f"- eligible_for_milestone_gate: `{review['eligible_for_milestone_gate']}`",
        f"- updated_at: `{review['updated_at']}`",
        "",
        "## Gates",
        "",
    ]
    for gate in review.get("gates") or []:
        status = "passed" if gate.get("passed") else "failed"
        lines.append(f"- `{gate['gate_id']}`: **{status}**")
    failed_gate_ids = review.get("failed_gate_ids") or []
    if failed_gate_ids:
        lines.extend(["", "## Failed gates", ""])
        for gate_id in failed_gate_ids:
            lines.append(f"- `{gate_id}`")
    artifacts = review.get("artifacts") or {}
    if artifacts:
        lines.extend(["", "## Artifacts", ""])
        for key in sorted(artifacts):
            lines.append(f"- {key}: `{artifacts[key]}`")
    summary = review.get("summary") or {}
    caveats = summary.get("caveats") or []
    if caveats:
        lines.extend(["", "## Caveats", ""])
        for caveat in caveats:
            lines.append(f"- {caveat}")
    return "\n".join(lines) + "\n"


def materialize_acceptance_review(
    review: dict[str, Any],
    *,
    output_root: Path,
) -> dict[str, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "acceptance_review.json"
    markdown_path = output_root / "acceptance_review.md"
    json_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_acceptance_review_markdown(review), encoding="utf-8")
    return {"json_path": json_path, "markdown_path": markdown_path}


__all__ = [
    "DEFAULT_ACCEPTANCE_CAMPAIGN",
    "build_acceptance_review",
    "materialize_acceptance_review",
    "render_acceptance_review_markdown",
]
