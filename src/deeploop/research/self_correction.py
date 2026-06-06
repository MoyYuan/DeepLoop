from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deeploop.autonomy.gate_taxonomy import resolve_operating_mode
from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.paths import LEDGER_DIR, REPO_ROOT, RUNS_DIR, WORKSPACE_ROOT, resolve_workspace_path
from deeploop.core.structured_io import load_json_object as _load_json, load_yaml_mapping as _load_yaml

DEFAULT_CONTRACT_PATH = REPO_ROOT / "configs" / "autonomy" / "self-correction.yaml"
REPORT_SCHEMA_PATH = REPO_ROOT / "schemas" / "self-correction-report.schema.json"


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _report_root(mission_state_path: Path | None, contract: dict[str, Any]) -> Path:
    artifact_dir_name = str(contract.get("artifact_dir_name", "self_correction"))
    if mission_state_path is not None:
        return mission_state_path.parent / artifact_dir_name
    return RUNS_DIR / artifact_dir_name


def _mission_ledger_path(mission_state_path: Path | None) -> Path:
    if mission_state_path is not None:
        return mission_state_path.parent / "ledger.jsonl"
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    return LEDGER_DIR / "self_correction.jsonl"


def _validate_report(report: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    jsonschema.validate(report, _load_json(REPORT_SCHEMA_PATH))


def _normalize_notes(notes: list[Any] | None) -> list[str]:
    return [str(note).strip() for note in (notes or []) if str(note).strip()]


def _infer_study_kind(manifest_path: Path, manifest: dict[str, Any]) -> str:
    loop_id = str(manifest.get("loop_id", "")).lower()
    metrics = manifest.get("metrics", {}) if isinstance(manifest.get("metrics"), dict) else {}
    command = str(manifest.get("run", {}).get("command", "")).lower()
    if "localization_source_exists" in metrics or "intervention" in loop_id or "run_causal_intervention" in command:
        return "causal-intervention"
    if "prepared_rule_families" in metrics or "mech" in loop_id or "mechanistic" in command:
        return "mechanistic-localization"
    if manifest_path.name == "run_manifest.json" or "accuracy" in metrics:
        return "baseline-eval"
    return "unknown"


def _infer_substrate(contract: dict[str, Any], mission_state: dict[str, Any] | None, manifests: list[dict[str, Any]]) -> str | None:
    project = None
    if mission_state is not None:
        target_repo = mission_state.get("target_repo")
        if isinstance(target_repo, str) and target_repo:
            project = resolve_workspace_path(target_repo).name
    if project is None and manifests:
        candidate = manifests[0].get("project")
        if isinstance(candidate, str) and candidate:
            project = candidate
    if project is None:
        return None
    for substrate_name, substrate_cfg in contract.get("substrates", {}).items():
        if substrate_cfg.get("project") == project:
            return str(substrate_name)
    return project


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in sorted(path.resolve() for path in paths):
        if path in seen:
            continue
        ordered.append(path)
        seen.add(path)
    return ordered


def _default_run_roots(contract: dict[str, Any], mission_state: dict[str, Any] | None) -> list[Path]:
    if mission_state is None:
        return []
    substrate_name = _infer_substrate(contract, mission_state, [])
    if substrate_name is not None:
        substrate_cfg = contract.get("substrates", {}).get(substrate_name, {})
        roots = [resolve_workspace_path(raw_root) for raw_root in substrate_cfg.get("run_roots", [])]
        if roots:
            return roots
    target_repo = mission_state.get("target_repo")
    if isinstance(target_repo, str) and target_repo:
        return [WORKSPACE_ROOT / "runs" / resolve_workspace_path(target_repo).name]
    return []


def _discover_manifest_paths(
    *,
    manifest_paths: list[Path] | None,
    run_roots: list[Path] | None,
    contract: dict[str, Any],
    mission_state: dict[str, Any] | None,
) -> list[Path]:
    explicit_paths = [path.expanduser().resolve() for path in (manifest_paths or [])]
    for path in explicit_paths:
        if not path.exists():
            raise FileNotFoundError(f"Manifest does not exist: {path}")
    if explicit_paths:
        return _unique_paths(explicit_paths)

    roots = [path.expanduser().resolve() for path in (run_roots or [])]
    if not roots:
        roots = [path.resolve() for path in _default_run_roots(contract, mission_state)]
    patterns = [str(pattern) for pattern in contract.get("default_manifest_globs", ["**/run_manifest.json", "**/study_manifest.json"])]
    discovered: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
            discovered.extend(path for path in root.glob(pattern) if path.is_file())
    return _unique_paths(discovered)


def _taxonomy_entry(contract: dict[str, Any], classification_id: str) -> dict[str, Any]:
    taxonomy = contract.get("taxonomy", {})
    if classification_id not in taxonomy:
        raise KeyError(f"Unknown self-correction classification: {classification_id}")
    return taxonomy[classification_id]


def _classification(contract: dict[str, Any], classification_id: str, *, details: dict[str, Any]) -> dict[str, Any]:
    entry = _taxonomy_entry(contract, classification_id)
    return {
        "id": classification_id,
        "severity": str(entry["severity"]),
        "default_action": str(entry["default_action"]),
        "summary": str(entry["summary"]),
        "details": details,
    }


def _collect_rule_family_failures(metrics: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    thresholds = contract.get("thresholds", {})
    family_accuracy_max = float(thresholds.get("family_collapse_accuracy_max", 0.05))
    min_family_examples = int(thresholds.get("min_family_examples", 1))
    failures: list[dict[str, Any]] = []
    for family, payload in sorted((metrics.get("rule_family") or {}).items()):
        if not isinstance(payload, dict):
            continue
        accuracy = _as_float(payload.get("accuracy"))
        count = _as_int(payload.get("count"))
        if accuracy is None or count is None:
            continue
        if accuracy <= family_accuracy_max and count >= min_family_examples:
            failures.append({"family": family, "accuracy": accuracy, "count": count})
    return failures


def _metrics_excerpt(metrics: dict[str, Any], rule_failures: list[dict[str, Any]]) -> dict[str, Any]:
    excerpt: dict[str, Any] = {}
    for field in ("count", "accuracy", "lexicalization_gap", "source_accuracy", "baseline_accuracy", "localization_source_exists"):
        if field in metrics:
            excerpt[field] = metrics[field]
    if rule_failures:
        excerpt["collapsed_rule_families"] = [item["family"] for item in rule_failures]
    return excerpt


def assess_manifest_for_self_correction(
    manifest_path: Path,
    *,
    manifest: dict[str, Any] | None = None,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> dict[str, Any]:
    contract = _load_yaml(contract_path)
    return _classify_manifest(manifest_path, manifest or _load_json(manifest_path), contract)


def _classify_manifest(manifest_path: Path, manifest: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    thresholds = contract.get("thresholds", {})
    signal_detection = contract.get("signal_detection", {})
    notes = _normalize_notes(manifest.get("notes"))
    notes_lower = [note.lower() for note in notes]
    metrics = manifest.get("metrics", {}) if isinstance(manifest.get("metrics"), dict) else {}
    study_kind = _infer_study_kind(manifest_path, manifest)
    run_status = str(manifest.get("run", {}).get("status", "unknown")).lower()
    execution_profile = str(manifest.get("execution_profile", ""))
    count = _as_int(metrics.get("count"))
    accuracy = _as_float(metrics.get("accuracy"))
    lexicalization_gap = _as_float(metrics.get("lexicalization_gap"))
    rule_failures = _collect_rule_family_failures(metrics, contract)
    blocked_phrases = [str(item).lower() for item in signal_detection.get("blocked_prerequisite_phrases", [])]
    prep_only_phrases = [str(item).lower() for item in signal_detection.get("prep_only_phrases", [])]
    blocked_by_prerequisite = metrics.get("localization_source_exists") is False or any(
        phrase in note for phrase in blocked_phrases for note in notes_lower
    )

    classifications: list[dict[str, Any]] = []
    if run_status == "failed":
        classifications.append(_classification(contract, "execution-failed", details={"run_status": run_status}))
    if run_status == "blocked" or (run_status == "prepared" and blocked_by_prerequisite):
        classification_id = "blocked-prerequisite" if blocked_by_prerequisite else "execution-blocked"
        details = {"run_status": run_status}
        if metrics.get("localization_source_exists") is False:
            details["missing_dependency"] = "localization_source"
        classifications.append(_classification(contract, classification_id, details=details))

    prep_only = execution_profile == "analysis-prep" or any(
        phrase in note for phrase in prep_only_phrases for note in notes_lower
    )
    if prep_only:
        classifications.append(
            _classification(
                contract,
                "prep-only-artifact",
                details={"execution_profile": execution_profile, "notes": notes},
            )
        )

    min_examples_for_claim = int(thresholds.get("min_examples_for_confident_claim", 16))
    if count is not None and count < min_examples_for_claim:
        classifications.append(
            _classification(
                contract,
                "insufficient-evidence",
                details={"count": count, "claim_threshold": min_examples_for_claim},
            )
        )

    min_examples_for_signal = int(thresholds.get("min_examples_for_signal", 8))
    accuracy_collapse_max = float(thresholds.get("accuracy_collapse_max", 0.05))
    weak_accuracy_max = float(thresholds.get("weak_accuracy_max", 0.30))
    if accuracy is not None and count is not None and count >= min_examples_for_signal:
        if accuracy <= accuracy_collapse_max:
            classifications.append(
                _classification(
                    contract,
                    "accuracy-collapse",
                    details={"accuracy": accuracy, "count": count, "threshold": accuracy_collapse_max},
                )
            )
        elif accuracy < weak_accuracy_max:
            classifications.append(
                _classification(
                    contract,
                    "weak-accuracy-signal",
                    details={"accuracy": accuracy, "count": count, "threshold": weak_accuracy_max},
                )
            )

    lexicalization_gap_abs_min = float(thresholds.get("lexicalization_gap_abs_min", 0.25))
    if lexicalization_gap is not None and abs(lexicalization_gap) >= lexicalization_gap_abs_min:
        direction = "delex-better" if lexicalization_gap < 0 else "lex-better"
        classifications.append(
            _classification(
                contract,
                "lexicalization-instability",
                details={
                    "lexicalization_gap": lexicalization_gap,
                    "direction": direction,
                    "threshold": lexicalization_gap_abs_min,
                },
            )
        )

    if rule_failures:
        classifications.append(
            _classification(
                contract,
                "rule-family-collapse",
                details={"collapsed_rule_families": rule_failures},
            )
        )

    classification_ids = [item["id"] for item in classifications]
    route_to = study_kind if study_kind != "unknown" else "mission-review"
    if "blocked-prerequisite" in classification_ids:
        action = "reroute"
        route_to = "mechanistic-localization"
        rationale = "Blocked prerequisites mean the branch should reroute through the missing dependency before retrying."
    elif "execution-failed" in classification_ids or "accuracy-collapse" in classification_ids:
        action = "stop"
        route_to = "halt-branch"
        rationale = "The branch collapsed or failed and should not remain an active experimental anchor."
    elif accuracy is not None and accuracy > accuracy_collapse_max and "weak-accuracy-signal" in classification_ids:
        action = "continue"
        route_to = "mechanistic-localization" if study_kind == "baseline-eval" else route_to
        rationale = "The branch has non-zero signal and remains useful as a failure-analysis anchor."
    elif "prep-only-artifact" in classification_ids:
        action = "continue"
        route_to = "mechanistic-localization-execution" if study_kind == "mechanistic-localization" else route_to
        rationale = "Preparation artifacts are durable planning outputs, but the branch still needs real evidence-producing execution."
    elif "rule-family-collapse" in classification_ids or "lexicalization-instability" in classification_ids:
        action = "reroute"
        route_to = "lexicalization-slice-audit" if "lexicalization-instability" in classification_ids else "rule-family-followup"
        rationale = "The branch should continue only after rerouting into the failing slices it exposed."
    else:
        action = "continue"
        rationale = "No blocking failure was detected, so the branch can continue."

    decision = {
        "action": action,
        "route_to": route_to,
        "rationale": rationale,
        "triggered_by": classification_ids,
    }
    return {
        "manifest_path": str(manifest_path),
        "loop_id": str(manifest.get("loop_id", manifest_path.parent.name)),
        "project": manifest.get("project"),
        "mode": resolve_operating_mode(manifest.get("mode")),
        "study_kind": study_kind,
        "run_status": run_status,
        "execution_profile": execution_profile,
        "metrics": _metrics_excerpt(metrics, rule_failures),
        "classifications": classifications,
        "decision": decision,
    }


def _select_anchor(assessments: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any] | None:
    collapse_max = float(contract.get("thresholds", {}).get("accuracy_collapse_max", 0.05))
    contenders = []
    for assessment in assessments:
        if assessment.get("study_kind") != "baseline-eval":
            continue
        accuracy = _as_float((assessment.get("metrics") or {}).get("accuracy"))
        if accuracy is None or accuracy <= collapse_max:
            continue
        lexicalization_gap = _as_float((assessment.get("metrics") or {}).get("lexicalization_gap")) or 0.0
        contenders.append((accuracy, -abs(lexicalization_gap), assessment["loop_id"], assessment))
    if not contenders:
        return None
    contenders.sort(reverse=True)
    return contenders[0][3]


def _recommendations_for_assessment(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    classifications = {item["id"]: item for item in assessment.get("classifications", [])}
    metrics = assessment.get("metrics", {})
    loop_id = assessment["loop_id"]
    manifest_path = assessment["manifest_path"]
    recommendations: list[dict[str, Any]] = []

    if "accuracy-collapse" in classifications:
        recommendations.append(
            {
                "recommendation_id": f"stop-{loop_id}",
                "action": "stop",
                "route_to": "alternate-checkpoint-or-prompt",
                "priority": 1,
                "summary": f"Stop `{loop_id}` as a primary anchor because accuracy collapsed to {metrics.get('accuracy')}.",
                "source_manifests": [manifest_path],
                "triggered_by": ["accuracy-collapse"],
            }
        )
    if "weak-accuracy-signal" in classifications:
        collapsed_families = (metrics.get("collapsed_rule_families") or [])[:3]
        family_text = ", ".join(collapsed_families) if collapsed_families else "its failing slices"
        recommendations.append(
            {
                "recommendation_id": f"anchor-{loop_id}",
                "action": "continue",
                "route_to": "mechanistic-localization",
                "priority": 2,
                "summary": f"Keep `{loop_id}` as the mixed-signal anchor and route follow-up work toward {family_text}.",
                "source_manifests": [manifest_path],
                "triggered_by": ["weak-accuracy-signal"] + (["rule-family-collapse"] if "rule-family-collapse" in classifications else []),
            }
        )
    if "lexicalization-instability" in classifications:
        recommendations.append(
            {
                "recommendation_id": f"lex-audit-{loop_id}",
                "action": "reroute",
                "route_to": "lexicalization-slice-audit",
                "priority": 3,
                "summary": f"Reroute `{loop_id}` into an explicit lexicalization audit because the lexicalization gap is {metrics.get('lexicalization_gap')}.",
                "source_manifests": [manifest_path],
                "triggered_by": ["lexicalization-instability"],
            }
        )
    if "blocked-prerequisite" in classifications:
        recommendations.append(
            {
                "recommendation_id": f"unblock-{loop_id}",
                "action": "reroute",
                "route_to": "mechanistic-localization",
                "priority": 1,
                "summary": f"Reroute `{loop_id}` through mechanistic localization before retrying intervention.",
                "source_manifests": [manifest_path],
                "triggered_by": ["blocked-prerequisite"],
            }
        )
    if "prep-only-artifact" in classifications and assessment.get("study_kind") == "mechanistic-localization":
        recommendations.append(
            {
                "recommendation_id": f"execute-{loop_id}",
                "action": "continue",
                "route_to": "mechanistic-localization-execution",
                "priority": 3,
                "summary": f"Treat `{loop_id}` as prep only and schedule the actual mechanistic localization execution step next.",
                "source_manifests": [manifest_path],
                "triggered_by": ["prep-only-artifact"],
            }
        )
    return recommendations


def _dedupe_recommendations(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for recommendation in recommendations:
        key = recommendation["recommendation_id"]
        existing = merged.get(key)
        if existing is None:
            merged[key] = recommendation
            continue
        existing["source_manifests"] = sorted(set(existing["source_manifests"]) | set(recommendation["source_manifests"]))
        existing["triggered_by"] = sorted(set(existing["triggered_by"]) | set(recommendation["triggered_by"]))
        existing["priority"] = min(int(existing.get("priority", 9)), int(recommendation.get("priority", 9)))
    return sorted(merged.values(), key=lambda item: (int(item.get("priority", 9)), item["recommendation_id"]))


def _synthesize_final_decision(assessments: list[dict[str, Any]], anchor: dict[str, Any] | None) -> dict[str, Any]:
    branch_actions = {assessment["loop_id"]: assessment["decision"]["action"] for assessment in assessments}
    actions = set(branch_actions.values())
    if actions == {"stop"}:
        action = "stop"
        route_to = "mission-review"
        rationale = "Every analyzed branch collapsed or failed, so the mission should stop and be re-scoped."
    elif "continue" in actions and ("reroute" in actions or "stop" in actions):
        action = "reroute"
        route_to = anchor["decision"]["route_to"] if anchor is not None else "mission-review"
        rationale = "Keep viable branches, but reroute the mission around blocked or collapsed branches before launching the next experiment."
    elif "continue" in actions:
        action = "continue"
        route_to = anchor["decision"]["route_to"] if anchor is not None else "mission-review"
        rationale = "At least one branch remains healthy enough to continue without a broader reroute."
    elif "reroute" in actions:
        action = "reroute"
        route_to = "mission-review"
        rationale = "No branch is ready to continue as-is, but the evidence supports a reroute instead of a full stop."
    else:
        action = "stop"
        route_to = "mission-review"
        rationale = "No actionable evidence remained after self-correction."
    return {
        "action": action,
        "route_to": route_to,
        "rationale": rationale,
        "branch_actions": branch_actions,
    }


def _write_markdown_report(report: dict[str, Any], markdown_path: Path) -> None:
    lines = [
        "# Self-correction report",
        "",
        f"- final_action: `{report['final_decision']['action']}`",
        f"- route_to: `{report['final_decision']['route_to']}`",
        f"- mission_id: `{report['mission_id']}`",
        f"- substrate: `{report['substrate']}`",
        "",
        "## Assessed manifests",
        "",
    ]
    for assessment in report["assessments"]:
        lines.append(
            f"- `{assessment['loop_id']}` ({assessment['study_kind']}) -> `{assessment['decision']['action']}` / `{assessment['decision']['route_to']}`"
        )
        for classification in assessment["classifications"]:
            lines.append(
                f"  - `{classification['severity']}` `{classification['id']}`: {classification['summary']}"
            )
    lines.extend(["", "## Recommendations", ""])
    if report["recommendations"]:
        for recommendation in report["recommendations"]:
            lines.append(
                f"- `{recommendation['action']}` `{recommendation['route_to']}`: {recommendation['summary']}"
            )
    else:
        lines.append("- No additional recommendations")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate_self_correction(
    *,
    mission_state_path: Path | None = None,
    manifest_paths: list[Path] | None = None,
    run_roots: list[Path] | None = None,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    artifact_name: str | None = None,
) -> dict[str, Any]:
    contract = _load_yaml(contract_path)
    mission_state = _load_json(mission_state_path) if mission_state_path is not None else None
    candidate_paths = _discover_manifest_paths(
        manifest_paths=manifest_paths,
        run_roots=run_roots,
        contract=contract,
        mission_state=mission_state,
    )
    if not candidate_paths:
        raise RuntimeError("No manifests were available for self-correction.")

    loaded_manifests = [(path, _load_json(path)) for path in candidate_paths]
    if manifest_paths is None and mission_state is not None:
        mission_id = mission_state.get("mission_id")
        mission_mode = resolve_operating_mode(mission_state.get("mode"))
        loaded_manifests = [
            (path, manifest)
            for path, manifest in loaded_manifests
            if manifest.get("mission_id") == mission_id and resolve_operating_mode(manifest.get("mode")) == mission_mode
        ]
    if not loaded_manifests:
        raise RuntimeError("No mission-linked manifests remained after filtering.")

    assessments = [_classify_manifest(path, manifest, contract) for path, manifest in loaded_manifests]
    substrate = _infer_substrate(contract, mission_state, [manifest for _, manifest in loaded_manifests])
    anchor = _select_anchor(assessments, contract)
    recommendations = []
    for assessment in assessments:
        recommendations.extend(_recommendations_for_assessment(assessment))
    if anchor is not None:
        recommendations.append(
            {
                "recommendation_id": f"mission-anchor-{anchor['loop_id']}",
                "action": "reroute",
                "route_to": "mechanistic-localization",
                "priority": 2,
                "summary": f"Route the next mission iteration through mechanistic localization anchored on `{anchor['loop_id']}`.",
                "source_manifests": [anchor["manifest_path"]],
                "triggered_by": ["mission-anchor"],
            }
        )
    recommendations = _dedupe_recommendations(recommendations)
    final_decision = _synthesize_final_decision(assessments, anchor)

    mission_context = None
    mission_id = None
    if mission_state is not None:
        mission_id = mission_state.get("mission_id")
        mission_context = {
            "current_phase": mission_state.get("current_phase"),
            "next_phase": mission_state.get("next_phase"),
            "autonomy_status": mission_state.get("autonomy_status"),
            "existing_next_actions": mission_state.get("next_actions", {}).get("summary"),
        }

    artifact_name = artifact_name or (f"{mission_id}-self-correction" if mission_id else "self-correction")
    report_root = _report_root(mission_state_path, contract)
    report_root.mkdir(parents=True, exist_ok=True)
    report_json_path = report_root / f"{artifact_name}.json"
    report_markdown_path = report_root / f"{artifact_name}.md"

    report = {
        "schema_version": 1,
        "artifact_name": artifact_name,
        "generated_at": now_utc(),
        "mission_id": mission_id,
        "substrate": substrate,
        "contract_path": str(contract_path),
        "manifest_paths": [str(path) for path, _ in loaded_manifests],
        "mission_context": mission_context or {},
        "assessments": assessments,
        "recommendations": recommendations,
        "final_decision": final_decision,
    }
    _validate_report(report)
    report_json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _write_markdown_report(report, report_markdown_path)

    if mission_state_path is not None and mission_state is not None:
        mission_state["self_correction"] = {
            "generated_at": report["generated_at"],
            "action": final_decision["action"],
            "route_to": final_decision["route_to"],
            "report_json_path": str(report_json_path),
            "report_markdown_path": str(report_markdown_path),
            "manifests_analyzed": len(assessments),
            "recommendation_ids": [item["recommendation_id"] for item in recommendations],
        }
        mission_state_path.write_text(json.dumps(mission_state, indent=2) + "\n", encoding="utf-8")

    ledger_path = _mission_ledger_path(mission_state_path)
    append_jsonl(
        ledger_path,
        make_ledger_entry(
            kind="self-correction",
            mission_id=str(mission_id or "standalone"),
            summary=f"Self-correction for {artifact_name} returned {final_decision['action']}",
            status=final_decision["action"],
            related_paths=[str(report_json_path), str(report_markdown_path)] + [str(path) for path, _ in loaded_manifests],
            metadata={
                "substrate": substrate,
                "route_to": final_decision["route_to"],
                "branch_actions": final_decision["branch_actions"],
            },
        ),
    )

    return {
        "report_json_path": report_json_path,
        "report_markdown_path": report_markdown_path,
        "final_decision": final_decision,
        "recommendations": recommendations,
    }
