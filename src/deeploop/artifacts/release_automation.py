from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deeploop.core.ledger import now_utc
from deeploop.core.paths import REPO_ROOT
from deeploop.core.structured_io import (
    load_json_object as _load_json,
    load_yaml_mapping as _load_yaml,
)

RELEASE_POLICY_PATH = REPO_ROOT / "configs" / "runtime" / "release-candidate-policy.yaml"
EVIDENCE_POLICY_PATH = REPO_ROOT / "configs" / "autonomy" / "evidence-policy.yaml"
GATE_2_RUNTIME_CONTRACT_PATH = REPO_ROOT / "configs" / "runtime" / "gate-2-runtime-lanes.yaml"
RELEASE_REVIEW_SCHEMA_PATH = REPO_ROOT / "schemas" / "release-candidate-review.schema.json"

CLAIM_ORDER = {
    "not-ready": -1,
    "exploratory": 0,
    "replicated": 1,
    "paper-candidate": 2,
    "release-candidate": 3,
}


def load_release_candidate_policy(path: Path = RELEASE_POLICY_PATH) -> dict[str, Any]:
    return _load_yaml(path)


def load_evidence_policy(path: Path = EVIDENCE_POLICY_PATH) -> dict[str, Any]:
    return _load_yaml(path)


def load_gate_2_runtime_contract(path: Path = GATE_2_RUNTIME_CONTRACT_PATH) -> dict[str, Any]:
    return _load_yaml(path)


def load_release_candidate_reviews(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"reviews": []}
    resolved = path.expanduser().resolve()
    if resolved.suffix.lower() in {".yaml", ".yml"}:
        payload = _load_yaml(resolved)
    else:
        payload = _load_json(resolved)
    if not isinstance(payload, dict):
        raise ValueError(f"Release reviews must be a mapping: {resolved}")
    if "reviews" not in payload and isinstance(payload.get("approvals"), list):
        payload = dict(payload)
        payload["reviews"] = payload.get("approvals", [])
    return payload


def load_release_candidate_approvals(path: Path | None) -> dict[str, Any]:
    return load_release_candidate_reviews(path)


def validate_release_candidate_review(
    review: dict[str, Any],
    schema_path: Path = RELEASE_REVIEW_SCHEMA_PATH,
) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return []

    try:
        jsonschema.validate(review, _load_json(schema_path))
    except Exception as exc:  # pragma: no cover
        return [str(exc)]
    return []


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _review_output_paths(policy: dict[str, Any], package_root: Path) -> dict[str, Path]:
    outputs = policy.get("outputs", {})
    return {
        "json": package_root / str(outputs.get("review_json", "release_candidate_review.json")),
        "markdown": package_root / str(outputs.get("review_markdown", "release_candidate_review.md")),
        "promotion": package_root / str(outputs.get("promotion_json", "release_candidate_promotion.json")),
    }


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None or value == "":
        return []
    return [str(value)]


def _normalize_review_reviewer(item: dict[str, Any]) -> dict[str, Any] | None:
    reviewer_payload = item.get("reviewer") if isinstance(item.get("reviewer"), dict) else {}
    reviewer_type = str(
        reviewer_payload.get("type") or item.get("reviewer_type") or ("human" if item.get("approved_by") else "")
    ).strip().lower()
    reviewer_id = str(
        reviewer_payload.get("reviewer_id")
        or item.get("reviewer_id")
        or item.get("approved_by")
        or item.get("reviewer")
        or ""
    ).strip()
    reviewer_role = str(reviewer_payload.get("role") or item.get("reviewer_role") or item.get("role") or "").strip()
    display_name = str(
        reviewer_payload.get("display_name")
        or item.get("reviewer_name")
        or item.get("reviewer_display_name")
        or ""
    ).strip()
    reviewer: dict[str, Any] = {}
    if reviewer_type:
        reviewer["type"] = reviewer_type
    if reviewer_id:
        reviewer["reviewer_id"] = reviewer_id
    if reviewer_role:
        reviewer["role"] = reviewer_role
    if display_name:
        reviewer["display_name"] = display_name
    return reviewer or None


def _normalize_review_status(item: dict[str, Any]) -> tuple[str, bool]:
    explicit = item.get("satisfied")
    if isinstance(explicit, bool):
        return ("satisfied" if explicit else "pending", explicit)
    explicit = item.get("approved")
    if isinstance(explicit, bool):
        return ("satisfied" if explicit else "pending", explicit)
    status = str(item.get("status", "")).strip().lower()
    if status in {"approved", "complete", "completed", "passed", "satisfied", "accepted", "true", "yes"}:
        return ("satisfied", True)
    if status in {"rejected", "failed", "blocked"}:
        return ("rejected", False)
    if status in {"needs-follow-up", "needs_follow_up"}:
        return ("needs-follow-up", False)
    if status in {"pending", "missing"}:
        return (status, False)
    return ("pending", False)


def _required_review_definitions(policy: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(policy.get("required_reviews"), list):
        return [item for item in policy.get("required_reviews", []) if isinstance(item, dict)]
    legacy_requirements = []
    for item in policy.get("required_approvals", []):
        if not isinstance(item, dict):
            continue
        legacy_requirements.append(
            {
                "id": item.get("id"),
                "description": item.get("description"),
                "allowed_reviewer_types": ["human"],
                "allowed_reviewer_roles": [],
                "human_override_allowed": True,
                "satisfies_blockers": item.get("satisfies_blockers", []),
            }
        )
    return legacy_requirements


def _normalize_review_records(
    policy: dict[str, Any],
    reviews: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    raw_records = []
    if isinstance(reviews, dict):
        if isinstance(reviews.get("reviews"), list):
            raw_records = reviews.get("reviews", [])
        elif isinstance(reviews.get("approvals"), list):
            raw_records = reviews.get("approvals", [])
    provided: dict[str, dict[str, Any]] = {}
    for item in raw_records:
        if not isinstance(item, dict):
            continue
        review_id = str(item.get("review_id") or item.get("approval_id") or item.get("id") or "").strip()
        if not review_id:
            continue
        status, satisfied = _normalize_review_status(item)
        provided[review_id] = {
            "review_id": review_id,
            "status": status,
            "satisfied": satisfied,
            "reviewer": _normalize_review_reviewer(item),
            "reviewed_at": item.get("reviewed_at") or item.get("approved_at") or item.get("timestamp"),
            "note": item.get("note") or item.get("rationale"),
            "evidence_refs": _normalize_string_list(item.get("evidence_refs") or item.get("evidence")),
            "runtime_metadata": dict(item.get("runtime_metadata", {}))
            if isinstance(item.get("runtime_metadata"), dict)
            else {},
        }

    results: list[dict[str, Any]] = []
    missing: list[str] = []
    for requirement in _required_review_definitions(policy):
        review_id = str(requirement.get("id", "")).strip()
        if not review_id:
            continue
        record = provided.get(review_id, {})
        reviewer = record.get("reviewer") if isinstance(record.get("reviewer"), dict) else None
        reviewer_type = str((reviewer or {}).get("type") or "").strip().lower()
        reviewer_role = str((reviewer or {}).get("role") or "").strip()
        validation_errors: list[str] = []
        satisfied = bool(record.get("satisfied"))
        if satisfied:
            if reviewer_type not in {"agent", "human"}:
                validation_errors.append("reviewer.type must be `agent` or `human`.")
            if not (reviewer or {}).get("reviewer_id"):
                validation_errors.append("reviewer.reviewer_id is required for satisfied reviews.")
            if not record.get("reviewed_at"):
                validation_errors.append("reviewed_at is required for satisfied reviews.")
            if not str(record.get("note") or "").strip():
                validation_errors.append("note is required for satisfied reviews.")
            allowed_types = {str(item).strip().lower() for item in requirement.get("allowed_reviewer_types", []) if str(item).strip()}
            allowed_roles = {str(item).strip() for item in requirement.get("allowed_reviewer_roles", []) if str(item).strip()}
            human_override_allowed = bool(requirement.get("human_override_allowed"))
            if reviewer_type == "human":
                if not human_override_allowed and allowed_types and "human" not in allowed_types:
                    validation_errors.append("human override is not allowed for this review.")
            else:
                if allowed_types and reviewer_type not in allowed_types:
                    validation_errors.append(
                        f"reviewer.type `{reviewer_type or 'missing'}` is not allowed for `{review_id}`."
                    )
                if allowed_roles and reviewer_role not in allowed_roles:
                    validation_errors.append(
                        f"reviewer.role `{reviewer_role or 'missing'}` is not allowed for `{review_id}`."
                    )
        effective_satisfied = satisfied and not validation_errors
        if not effective_satisfied:
            missing.append(review_id)
        result_status = "satisfied" if effective_satisfied else (
            "invalid" if validation_errors else str(record.get("status") or "missing")
        )
        results.append(
            {
                "review_id": review_id,
                "description": str(requirement.get("description", "")),
                "status": result_status,
                "satisfied": effective_satisfied,
                "reviewer": reviewer,
                "reviewed_at": record.get("reviewed_at"),
                "note": record.get("note"),
                "evidence_refs": list(record.get("evidence_refs", [])),
                "runtime_metadata": dict(record.get("runtime_metadata", {})),
                "human_override": bool(effective_satisfied and reviewer_type == "human"),
                "validation_errors": validation_errors,
                "satisfies_blockers": [str(item).lower() for item in requirement.get("satisfies_blockers", [])],
            }
        )
    return (results, missing)


def build_release_candidate_review(
    package: dict[str, Any],
    *,
    package_manifest_path: Path,
    policy: dict[str, Any] | None = None,
    reviews: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_policy = policy or load_release_candidate_policy()
    package_root = Path(str(package["package_root"])).expanduser().resolve()
    review_paths = _review_output_paths(resolved_policy, package_root)
    claim_summary = package.get("claim_summary", {})
    checks = package.get("checks", {})
    artifact_map = package.get("artifact_map", {})
    summary = package.get("summary", {})
    claim_state = str(claim_summary.get("package_claim_state", "exploratory"))
    evidence_policy = load_evidence_policy()
    gate_2_contract = load_gate_2_runtime_contract()
    failed_gate_ids: list[str] = []
    gates: list[dict[str, Any]] = []

    def add_gate(gate_id: str, description: str, passed: bool, details: list[str]) -> None:
        gates.append(
            {
                "gate_id": gate_id,
                "description": description,
                "status": "passed" if passed else "failed",
                "details": details,
            }
        )
        if not passed:
            failed_gate_ids.append(gate_id)

    required_check_names = [str(item) for item in resolved_policy.get("required_package_checks", [])]
    failed_checks = [name for name in required_check_names if not bool(checks.get(name))]
    validation_errors = [str(item) for item in checks.get("validation_errors", [])]
    package_checks_passed = not failed_checks and not validation_errors
    add_gate(
        "package-checks",
        "Package integrity checks passed.",
        package_checks_passed,
        [f"{name}: passed" for name in required_check_names if name not in failed_checks]
        + [f"{name}: missing or false" for name in failed_checks]
        + [f"validation error: {error}" for error in validation_errors],
    )

    floor = str(resolved_policy.get("claim_state_floor", "paper-candidate"))
    paper_candidate_blockers = [str(item) for item in claim_summary.get("paper_candidate_blockers", []) if str(item).strip()]
    equivalent_rigor = claim_state == "replicated" and not [
        blocker
        for blocker in paper_candidate_blockers
        if blocker.lower() not in {"human approval"}
    ]
    floor_passed = CLAIM_ORDER.get(claim_state, CLAIM_ORDER["exploratory"]) >= CLAIM_ORDER.get(
        floor,
        CLAIM_ORDER["paper-candidate"],
    ) or (floor == "paper-candidate" and equivalent_rigor)
    add_gate(
        "claim-state-floor",
        f"Package claim state reaches {floor}.",
        floor_passed,
        [
            f"package_claim_state={claim_state}",
            f"required_floor={floor}",
            f"equivalent_rigor={'yes' if equivalent_rigor else 'no'}",
        ],
    )

    manifest_claim_counts = {
        str(state): int(count or 0)
        for state, count in (claim_summary.get("manifest_claim_counts") or {}).items()
    }
    manifest_count = max(
        len([item for item in artifact_map.get("manifests", []) if item]),
        sum(manifest_claim_counts.values()),
    )
    replication_required = CLAIM_ORDER.get(claim_state, CLAIM_ORDER["exploratory"]) >= CLAIM_ORDER["replicated"]
    replication_passed = (not replication_required) or manifest_count >= 2
    add_gate(
        "replication-evidence",
        "Claim states at `replicated` or above have at least 2 related manifests.",
        replication_passed,
        [
            f"manifest_count={manifest_count}",
            f"claim_state={claim_state}",
        ],
    )

    evidence_requirements: list[str] = []
    for entry in evidence_policy.get("claim_states", []):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id") or "") == claim_state:
            evidence_requirements = [str(item) for item in entry.get("promotion_requirements", []) if str(item).strip()]
            break
    missing_evidence_requirements: list[str] = []
    if claim_state in {"replicated", "paper-candidate", "release-candidate"} and manifest_count < 2:
        missing_evidence_requirements.append("at least 2 related manifests")
    add_gate(
        "evidence-policy-linkage",
        "Mechanically verifiable evidence-policy requirements are satisfied for the package claim state.",
        not missing_evidence_requirements,
        [f"requirement: {item}" for item in evidence_requirements]
        + (
            [f"missing: {item}" for item in missing_evidence_requirements]
            if missing_evidence_requirements
            else ["mechanically verifiable requirements satisfied"]
        ),
    )

    required_categories = [str(item) for item in resolved_policy.get("required_artifact_categories", [])]
    missing_categories = [category for category in required_categories if not artifact_map.get(category)]
    add_gate(
        "artifact-coverage",
        "Required artifact categories are populated.",
        not missing_categories,
        [f"{category}: present" for category in required_categories if category not in missing_categories]
        + [f"{category}: missing" for category in missing_categories],
    )

    required_sections = [str(item) for item in resolved_policy.get("required_summary_sections", [])]
    missing_sections = [section for section in required_sections if section not in summary]
    add_gate(
        "summary-surfaces",
        "Package summary exposes operator, paper, and release surfaces.",
        not missing_sections,
        [f"{section}: present" for section in required_sections if section not in missing_sections]
        + [f"{section}: missing" for section in missing_sections],
    )

    review_results, missing_reviews = _normalize_review_records(resolved_policy, reviews)
    invalid_reviews = [item["review_id"] for item in review_results if item.get("status") == "invalid"]

    release_blockers = [str(item) for item in claim_summary.get("release_candidate_blockers", []) if str(item).strip()]
    satisfied_terms = set()
    if floor_passed:
        satisfied_terms.update({"paper-candidate evidence", "equivalent rigor"})
    for review in review_results:
        if review["satisfied"]:
            satisfied_terms.update(review.get("satisfies_blockers", []))
    effective_release_blockers = [
        blocker
        for blocker in release_blockers
        if not any(term in blocker.lower() for term in satisfied_terms)
    ]
    fail_on_release_blockers = bool(
        resolved_policy.get("blocker_policies", {}).get("fail_on_release_candidate_blockers", True)
    )
    add_gate(
        "release-blockers",
        "Release-candidate blockers are cleared.",
        not fail_on_release_blockers or not effective_release_blockers,
        effective_release_blockers or ["No release blockers reported."],
    )

    add_gate(
        "required-reviews",
        "Required durable release reviews are recorded.",
        not missing_reviews,
        [f"{item['review_id']}: satisfied" for item in review_results if item["satisfied"]]
        + [f"{item['review_id']}: invalid" for item in review_results if item.get("status") == "invalid"]
        + [f"{review_id}: missing" for review_id in missing_reviews],
    )

    recommended_actions: list[str] = []
    if not floor_passed:
        recommended_actions.append(
            f"Promote evidence from {claim_state} to at least {floor} before attempting release promotion."
        )
    if effective_release_blockers:
        recommended_actions.extend(effective_release_blockers[:3])
    if missing_reviews:
        recommended_actions.append(
            "Record required reviews: " + ", ".join(sorted(missing_reviews)) + "."
        )
    if invalid_reviews:
        recommended_actions.append(
            "Repair invalid review records: " + ", ".join(sorted(invalid_reviews)) + "."
        )
    if failed_checks:
        recommended_actions.append(
            "Repair failed package checks before promotion: " + ", ".join(sorted(failed_checks)) + "."
        )
    if validation_errors:
        recommended_actions.append("Resolve package validation errors before promotion.")

    eligible_for_promotion = not failed_gate_ids
    gate_2_runtime_contract = {
        "policy_path": str(GATE_2_RUNTIME_CONTRACT_PATH),
        "phase_id": str((gate_2_contract.get("approved_phase") or {}).get("id", "")),
        "baseline_boundary": dict(gate_2_contract.get("baseline_install_boundary", {})),
        "proof_boundary": dict(gate_2_contract.get("gate_2_proof_boundary", {})),
        "required_lanes": list(gate_2_contract.get("required_lanes", [])),
    }
    return {
        "schema_version": 2,
        "policy_name": str(resolved_policy.get("policy_name", "deeploop-release-candidate-policy")),
        "policy_version": int(resolved_policy.get("version", 1)),
        "generated_at": now_utc(),
        "package_id": str(package.get("package_id", "")),
        "mission_id": str(package.get("mission_id", "")),
        "package_root": str(package_root),
        "package_manifest_path": str(package_manifest_path.resolve()),
        "package_digest": str(package.get("package_digest", "")),
        "package_claim_state": claim_state,
        "evidence_policy_path": str(EVIDENCE_POLICY_PATH),
        "gate_2_runtime_contract": gate_2_runtime_contract,
        "decision": "promotable" if eligible_for_promotion else "blocked",
        "eligible_for_promotion": eligible_for_promotion,
        "gates": gates,
        "failed_gate_ids": failed_gate_ids,
        "blocking_reasons": _dedupe_preserve(effective_release_blockers + recommended_actions),
        "required_reviews": review_results,
        "missing_reviews": missing_reviews,
        "review_artifacts": {
            "json": str(review_paths["json"]),
            "markdown": str(review_paths["markdown"]),
            "promotion": None,
        },
        "next_actions": _dedupe_preserve(recommended_actions) or ["No additional release actions required."],
    }


def materialize_release_candidate_review(
    review: dict[str, Any],
    *,
    package_root: Path,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_policy = policy or load_release_candidate_policy()
    package_root = package_root.expanduser().resolve()
    review_paths = _review_output_paths(resolved_policy, package_root)
    rendered_review = dict(review)
    rendered_review["review_artifacts"] = {
        "json": str(review_paths["json"]),
        "markdown": str(review_paths["markdown"]),
        "promotion": review.get("review_artifacts", {}).get("promotion"),
    }

    validation_errors = validate_release_candidate_review(rendered_review)
    if validation_errors:
        raise RuntimeError(
            "Release candidate review failed schema validation: " + "; ".join(validation_errors)
        )

    review_paths["json"].write_text(json.dumps(rendered_review, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Release candidate review",
        "",
        f"- decision: `{rendered_review['decision']}`",
        f"- package_id: `{rendered_review['package_id']}`",
        f"- mission_id: `{rendered_review['mission_id']}`",
        f"- package_claim_state: `{rendered_review['package_claim_state']}`",
        f"- policy_name: `{rendered_review['policy_name']}`",
        "",
        "## Promotion gates",
        "",
    ]
    for gate in rendered_review["gates"]:
        lines.append(f"- `{gate['gate_id']}` — {gate['status']}")
        for detail in gate["details"][:4]:
            lines.append(f"  - {detail}")
    lines.extend(["", "## Required reviews", ""])
    for review in rendered_review["required_reviews"]:
        reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
        reviewer_id = reviewer.get("reviewer_id") or "unrecorded"
        reviewer_type = reviewer.get("type") or "unknown"
        role = reviewer.get("role")
        status = review.get("status") or ("satisfied" if review.get("satisfied") else "missing")
        reviewer_bits = f"{reviewer_id}, {reviewer_type}"
        if role:
            reviewer_bits += f", role={role}"
        lines.append(f"- `{review['review_id']}` — {status} ({reviewer_bits})")
        if review.get("reviewed_at"):
            lines.append(f"  - reviewed_at: {review['reviewed_at']}")
        if review.get("note"):
            lines.append(f"  - note: {review['note']}")
        if review.get("evidence_refs"):
            lines.append("  - evidence_refs: " + ", ".join(review["evidence_refs"][:3]))
        for error in review.get("validation_errors", [])[:3]:
            lines.append(f"  - validation: {error}")
    gate_2_runtime_contract = rendered_review.get("gate_2_runtime_contract", {})
    if gate_2_runtime_contract:
        proof_boundary = gate_2_runtime_contract.get("proof_boundary", {})
        lines.extend(["", "## Gate 2 runtime contract", ""])
        lines.append(f"- phase_id: `{gate_2_runtime_contract.get('phase_id', '')}`")
        lines.append(
            "- durable mission/runtime evidence required: "
            + ("yes" if proof_boundary.get("durable_mission_runtime_evidence_required") else "no")
        )
        lines.append(
            "- manual machine auth remains explicit: "
            + ("yes" if proof_boundary.get("manual_machine_auth_remains_explicit") else "no")
        )
        for lane in gate_2_runtime_contract.get("required_lanes", []):
            if not isinstance(lane, dict):
                continue
            model_expectation = lane.get("model_expectation") if isinstance(lane.get("model_expectation"), dict) else {}
            model_bits = [
                f"{key}={value}"
                for key, value in model_expectation.items()
                if isinstance(key, str) and value not in {None, ""}
            ]
            lane_summary = (
                f"- `{lane.get('lane_id', '')}` — {lane.get('provider_family', '')}/{lane.get('backend', '')}"
            )
            if lane.get("selection_profile"):
                lane_summary += f", profile={lane['selection_profile']}"
            if model_bits:
                lane_summary += ", " + ", ".join(model_bits)
            lines.append(lane_summary)
    lines.extend(["", "## Next actions", ""])
    lines.extend(f"- {item}" for item in rendered_review["next_actions"])
    review_paths["markdown"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "review_json": review_paths["json"],
        "review_markdown": review_paths["markdown"],
        "review": rendered_review,
    }


def materialize_release_candidate_promotion(
    review: dict[str, Any],
    *,
    package_root: Path,
    policy: dict[str, Any] | None = None,
) -> Path:
    if not review.get("eligible_for_promotion"):
        raise ValueError("Release candidate promotion requires all gates to pass.")
    resolved_policy = policy or load_release_candidate_policy()
    promotion_path = _review_output_paths(resolved_policy, package_root.expanduser().resolve())["promotion"]
    promotion_payload = {
        "schema_version": 2,
        "generated_at": now_utc(),
        "policy_name": review["policy_name"],
        "package_id": review["package_id"],
        "mission_id": review["mission_id"],
        "package_digest": review["package_digest"],
        "package_manifest_path": review["package_manifest_path"],
        "release_candidate_review_path": review["review_artifacts"]["json"],
        "approved_gate_ids": [gate["gate_id"] for gate in review["gates"] if gate["status"] == "passed"],
        "review_ids": [
            required_review["review_id"]
            for required_review in review["required_reviews"]
            if required_review["satisfied"]
        ],
        "decision": "promoted-release-candidate",
    }
    promotion_path.write_text(json.dumps(promotion_payload, indent=2) + "\n", encoding="utf-8")
    return promotion_path


def build_package_release_automation(
    review: dict[str, Any],
    *,
    promotion_path: Path | None = None,
) -> dict[str, Any]:
    review_artifacts = dict(review.get("review_artifacts", {}))
    review_artifacts["promotion"] = str(promotion_path) if promotion_path else None
    return {
        "policy_name": review["policy_name"],
        "decision": review["decision"],
        "eligible_for_promotion": bool(review["eligible_for_promotion"]),
        "failed_gate_ids": list(review.get("failed_gate_ids", [])),
        "missing_reviews": list(review.get("missing_reviews", [])),
        "gate_2_runtime_contract": dict(review.get("gate_2_runtime_contract", {})),
        "review_artifacts": review_artifacts,
    }
