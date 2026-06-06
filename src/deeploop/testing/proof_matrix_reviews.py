from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from deeploop.core.shared import normalize_strings as _normalize_strings
from deeploop.core.structured_io import write_json_object, write_markdown



def _case_failure_categories(case_summary: Mapping[str, Any]) -> list[str]:
    categories: list[str] = []
    operator_request = (
        case_summary.get("operator_request")
        if isinstance(case_summary.get("operator_request"), Mapping)
        else None
    )
    blocker = operator_request.get("blocker") if isinstance(operator_request, Mapping) and isinstance(operator_request.get("blocker"), Mapping) else {}
    blocker_kind = str(blocker.get("kind") or "").strip()
    if blocker_kind:
        categories.append(blocker_kind)
    boundary_check = (
        case_summary.get("boundary_check")
        if isinstance(case_summary.get("boundary_check"), Mapping)
        else {}
    )
    if not boundary_check.get("project_tree_unchanged", True):
        categories.append("substrate-gap")
    mission_state = _case_mission_state(case_summary)
    if not _normalize_strings(mission_state.get("final_report_outputs")):
        categories.append("product-gap")
    failures = _normalize_strings(case_summary.get("failures"))
    if failures and not categories:
        categories.append("product-gap")
    deduped: list[str] = []
    for category in categories:
        if category not in deduped:
            deduped.append(category)
    return deduped


def _nested_mapping(parent: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    current: Any = parent
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return current if isinstance(current, Mapping) else {}


def _case_mission_state_from_snapshot(case_summary: Mapping[str, Any]) -> dict[str, Any]:
    run_project_result = (
        case_summary.get("run_project_result")
        if isinstance(case_summary.get("run_project_result"), Mapping)
        else {}
    )
    snapshot = run_project_result.get("snapshot") if isinstance(run_project_result.get("snapshot"), Mapping) else {}
    mission_snapshot = _nested_mapping(snapshot, "mission")
    outer_loop_snapshot = _nested_mapping(snapshot, "outer_loop")
    runtime_snapshot = _nested_mapping(outer_loop_snapshot, "runtime")
    evidence = _nested_mapping(snapshot, "evidence")
    phase_outputs = evidence.get("phase_outputs_by_phase")
    final_report_outputs = (
        _normalize_strings(phase_outputs.get("final-report"))
        if isinstance(phase_outputs, Mapping)
        else []
    )
    operator_inbox = snapshot.get("operator_inbox")
    mission_state_payload = (
        dict(case_summary.get("mission_state"))
        if isinstance(case_summary.get("mission_state"), Mapping)
        else {}
    )
    if final_report_outputs:
        mission_state_payload["final_report_outputs"] = final_report_outputs
    if isinstance(operator_inbox, Mapping) and operator_inbox.get("status") is not None:
        mission_state_payload.setdefault("operator_inbox_status", operator_inbox.get("status"))
    if mission_snapshot.get("status") is not None:
        mission_state_payload.setdefault("status", mission_snapshot.get("status"))
    elif runtime_snapshot.get("status") is not None:
        mission_state_payload.setdefault("status", runtime_snapshot.get("status"))
    if mission_snapshot.get("current_phase") is not None:
        mission_state_payload.setdefault("current_phase", mission_snapshot.get("current_phase"))
    return mission_state_payload


def _case_mission_state(case_summary: Mapping[str, Any]) -> dict[str, Any]:
    mission_state = case_summary.get("mission_state")
    if isinstance(mission_state, Mapping):
        payload = dict(mission_state)
        if payload.get("final_report_outputs"):
            return payload
    snapshot_payload = _case_mission_state_from_snapshot(case_summary)
    if snapshot_payload.get("final_report_outputs"):
        return snapshot_payload
    run_project_result = (
        case_summary.get("run_project_result")
        if isinstance(case_summary.get("run_project_result"), Mapping)
        else {}
    )
    mission_state_path = run_project_result.get("mission_state_path")
    if not isinstance(mission_state_path, str) or not mission_state_path.strip():
        return dict(mission_state) if isinstance(mission_state, Mapping) else {}
    path = Path(mission_state_path).expanduser().resolve()
    if not path.exists():
        return dict(mission_state) if isinstance(mission_state, Mapping) else {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return dict(mission_state) if isinstance(mission_state, Mapping) else {}
    phase_outputs = payload.get("phase_outputs_by_phase")
    final_report_outputs = (
        _normalize_strings(phase_outputs.get("final-report"))
        if isinstance(phase_outputs, Mapping)
        else []
    )
    operator_inbox = payload.get("operator_inbox")
    mission_state_payload = dict(mission_state) if isinstance(mission_state, Mapping) else {}
    mission_state_payload.setdefault(
        "operator_inbox_status",
        operator_inbox.get("status") if isinstance(operator_inbox, Mapping) else None,
    )
    mission_state_payload.setdefault("final_report_outputs", final_report_outputs)
    mission_state_payload.setdefault("status", payload.get("status"))
    mission_state_payload.setdefault("current_phase", payload.get("current_phase"))
    return mission_state_payload


def build_multi_substrate_proof_review(campaign_summary: Mapping[str, Any]) -> dict[str, Any]:
    case_summaries = [
        dict(summary)
        for summary in (campaign_summary.get("case_summaries") or [])
        if isinstance(summary, Mapping)
    ]
    workflow_shapes = sorted(
        {
            str(summary.get("workflow_shape") or "unspecified")
            for summary in case_summaries
            if str(summary.get("workflow_shape") or "").strip()
        }
    )
    case_reviews: list[dict[str, Any]] = []
    passed_cases = 0
    boundary_clean_cases = 0
    clear_operator_cases = 0
    final_report_cases = 0
    all_claims_supported = True
    for summary in case_summaries:
        mission_state = _case_mission_state(summary)
        operator_request = summary.get("operator_request") if isinstance(summary.get("operator_request"), Mapping) else {}
        boundary_check = summary.get("boundary_check") if isinstance(summary.get("boundary_check"), Mapping) else {}
        final_report_outputs = _normalize_strings(mission_state.get("final_report_outputs"))
        operator_inbox_status = mission_state.get("operator_inbox_status")
        supports_claims = bool(summary.get("status") == "passed")
        case_review = {
            "case_id": summary.get("case_id"),
            "title": summary.get("title"),
            "workflow_shape": summary.get("workflow_shape"),
            "status": summary.get("status"),
            "autonomy_claims": _normalize_strings(summary.get("autonomy_claims")),
            "claim_support_status": "supported" if supports_claims else "not-yet-supported",
            "operator_boundary_class": (
                operator_request.get("blocker", {}).get("kind")
                if isinstance(operator_request.get("blocker"), Mapping)
                else None
            ),
            "failure_categories": _case_failure_categories(summary),
            "gate_results": {
                "boundary_integrity": bool(boundary_check.get("project_tree_unchanged")),
                "operator_inbox_clear": operator_inbox_status in {None, "clear"},
                "final_report_outputs_present": bool(final_report_outputs),
            },
            "final_report_outputs": final_report_outputs,
            "failures": _normalize_strings(summary.get("failures")),
        }
        case_reviews.append(case_review)
        if summary.get("status") == "passed":
            passed_cases += 1
        if case_review["gate_results"]["boundary_integrity"]:
            boundary_clean_cases += 1
        if case_review["gate_results"]["operator_inbox_clear"]:
            clear_operator_cases += 1
        if case_review["gate_results"]["final_report_outputs_present"]:
            final_report_cases += 1
        if case_review["autonomy_claims"] and not supports_claims:
            all_claims_supported = False

    gates = [
        {
            "gate_id": "all_cases_passed",
            "passed": passed_cases == len(case_summaries) and bool(case_summaries),
            "summary": f"{passed_cases}/{len(case_summaries)} cases passed.",
        },
        {
            "gate_id": "materially_different_workflow_shapes",
            "passed": len(workflow_shapes) >= 3,
            "summary": f"{len(workflow_shapes)} workflow shapes covered: {', '.join(workflow_shapes) or 'none'}.",
        },
        {
            "gate_id": "boundary_integrity",
            "passed": boundary_clean_cases == len(case_summaries) and bool(case_summaries),
            "summary": f"{boundary_clean_cases}/{len(case_summaries)} cases kept the substrate tree unchanged.",
        },
        {
            "gate_id": "operator_inbox_clear",
            "passed": clear_operator_cases == len(case_summaries) and bool(case_summaries),
            "summary": f"{clear_operator_cases}/{len(case_summaries)} cases kept the operator inbox clear.",
        },
        {
            "gate_id": "final_report_outputs_present",
            "passed": final_report_cases == len(case_summaries) and bool(case_summaries),
            "summary": f"{final_report_cases}/{len(case_summaries)} cases produced final-report outputs.",
        },
        {
            "gate_id": "autonomy_claims_supported",
            "passed": all_claims_supported,
            "summary": "All explicit fixture autonomy claims are supported by the current campaign results."
            if all_claims_supported
            else "At least one fixture claim is not yet supported by the current campaign results.",
        },
    ]
    passed_gate_ids = [gate["gate_id"] for gate in gates if gate["passed"]]
    failed_gate_ids = [gate["gate_id"] for gate in gates if not gate["passed"]]
    decision = "eligible-for-promotion" if not failed_gate_ids else "remediation-needed"
    return {
        "schema_version": 1,
        "campaign_id": campaign_summary.get("campaign_id"),
        "campaign_status": campaign_summary.get("status"),
        "decision": decision,
        "summary": (
            "Plain-folder proof matrix meets the promotion gates for a multi-substrate proof surface."
            if decision == "eligible-for-promotion"
            else "Plain-folder proof matrix still has gaps before it can serve as a milestone-grade multi-substrate proof surface."
        ),
        "counts": {
            "cases_run": len(case_summaries),
            "passed_cases": passed_cases,
            "failed_cases": len(case_summaries) - passed_cases,
            "workflow_shapes": len(workflow_shapes),
            "boundary_clean_cases": boundary_clean_cases,
            "clear_operator_cases": clear_operator_cases,
            "final_report_cases": final_report_cases,
        },
        "workflow_shapes": workflow_shapes,
        "passed_gate_ids": passed_gate_ids,
        "failed_gate_ids": failed_gate_ids,
        "gates": gates,
        "case_reviews": case_reviews,
    }


def materialize_proof_matrix_review(review: Mapping[str, Any], output_root: Path) -> dict[str, str]:
    output_root = output_root.expanduser().resolve()
    json_path = output_root / "proof_matrix_review.json"
    markdown_path = output_root / "proof_matrix_review.md"
    write_json_object(json_path, dict(review))
    lines = [
        f"# Plain-folder proof matrix review: {review.get('campaign_id')}",
        "",
        f"- decision: `{review.get('decision')}`",
        f"- summary: {review.get('summary')}",
        "",
        "## Gates",
        "",
    ]
    for gate in review.get("gates", []):
        if not isinstance(gate, Mapping):
            continue
        lines.append(
            f"- `{gate.get('gate_id')}`: `{'passed' if gate.get('passed') else 'failed'}` — {gate.get('summary')}"
        )
    lines.extend(["", "## Case reviews", ""])
    for case_review in review.get("case_reviews", []):
        if not isinstance(case_review, Mapping):
            continue
        lines.append(
            f"- `{case_review.get('case_id')}`: `{case_review.get('status')}` "
            f"({case_review.get('workflow_shape')})"
        )
        claims = _normalize_strings(case_review.get("autonomy_claims"))
        if claims:
            lines.extend([f"  - claim: {claim}" for claim in claims])
        categories = _normalize_strings(case_review.get("failure_categories"))
        if categories:
            lines.append(f"  - failure_categories: {', '.join(categories)}")
    write_markdown(markdown_path, lines)
    return {
        "review_json_path": str(json_path),
        "review_markdown_path": str(markdown_path),
    }


__all__ = ["build_multi_substrate_proof_review", "materialize_proof_matrix_review"]
