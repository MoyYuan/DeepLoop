from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from deeploop.core.config_paths import infer_repo_root_from_configs as _infer_repo_root, resolve_config_path as _resolve_path
from deeploop.core.shared import get_dotted as _get_field
from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.paths import REPO_ROOT, RUNS_DIR
from deeploop.core.structured_io import load_json_object as _load_json, load_yaml_mapping as _load_yaml

DEFAULT_CONTRACT_PATH = REPO_ROOT / "configs" / "autonomy" / "confound-guard.yaml"
REPORT_SCHEMA_PATH = REPO_ROOT / "schemas" / "confound-guard-report.schema.json"


def _infer_config_kind(config: dict[str, Any]) -> str:
    phase = config.get("phase")
    if phase == "mechanistic-localization":
        return "mechanistic-localization"
    if phase == "causal-intervention":
        return "causal-intervention"
    if "dataset" in config and "model" in config and "run" in config:
        return "baseline-eval"
    return "generic"


def _new_check(check_id: str, *, severity: str, status: str, message: str, details: dict | None = None) -> dict:
    return {
        "id": check_id,
        "severity": severity,
        "status": status,
        "message": message,
        "details": details or {},
    }


def _report_root(mission_state_path: Path | None, contract: dict[str, Any]) -> Path:
    artifact_dir_name = str(contract.get("artifact_dir_name", "confound_guard"))
    if mission_state_path is not None:
        return mission_state_path.parent / artifact_dir_name
    return RUNS_DIR / artifact_dir_name


def _normalize_value(value: Any) -> str:
    if isinstance(value, str):
        if value.startswith("~") or value.startswith("/"):
            return str(Path(value).expanduser())
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _notes_text(notes: Any) -> str:
    if isinstance(notes, list):
        return "\n".join(str(item) for item in notes)
    if isinstance(notes, str):
        return notes
    return ""


def _is_missing(value: Any) -> bool:
    return value in (None, "", [], {})


def _is_analysis_prep_manifest(manifest: dict[str, Any], contract: dict[str, Any]) -> bool:
    markers = contract.get("analysis_prep_markers", {})
    if manifest.get("resource_tier") in set(markers.get("resource_tiers", [])):
        return True
    if manifest.get("execution_profile") in set(markers.get("execution_profiles", [])):
        return True
    if _get_field(manifest, "model.backend") in set(markers.get("model_backends", [])):
        return True
    if _get_field(manifest, "prompt.template_id") in set(markers.get("prompt_template_ids", [])):
        return True
    if _get_field(manifest, "prompt.parser_id") in set(markers.get("prompt_parser_ids", [])):
        return True
    notes_text = _notes_text(manifest.get("notes")).lower()
    return any(marker.lower() in notes_text for marker in markers.get("notes_contain", []))


def _resolve_references(
    config: dict[str, Any],
    *,
    config_path: Path,
    repo_root: Path | None,
    proposal_type: dict[str, Any],
) -> tuple[list[dict], dict[str, dict[str, Any]], list[dict]]:
    checks: list[dict] = []
    resolved_refs: dict[str, dict[str, Any]] = {}
    references: list[dict] = []
    for reference in proposal_type.get("reference_manifests", []):
        field = str(reference["field"])
        role = reference.get("role")
        severity = str(reference.get("severity", "block"))
        raw_value = _get_field(config, field)
        if not isinstance(raw_value, str) or not raw_value:
            status = "block" if reference.get("required", True) else "warn"
            checks.append(
                _new_check(
                    f"confound:reference:{field}",
                    severity=severity,
                    status=status,
                    message=f"Reference manifest field `{field}` is missing.",
                )
            )
            resolved_refs[field] = {"status": status, "role": role, "spec": reference}
            references.append({"field": field, "role": role, "path": None, "status": status})
            continue

        resolved_path = _resolve_path(raw_value, repo_root=repo_root, config_path=config_path)
        details = {"field": field, "path": str(resolved_path), "role": role}
        if not resolved_path.exists():
            status = "block" if reference.get("required", True) else "warn"
            checks.append(
                _new_check(
                    f"confound:reference:{field}",
                    severity=severity,
                    status=status,
                    message=f"Reference manifest for `{field}` does not exist.",
                    details=details,
                )
            )
            resolved_refs[field] = {"status": status, "role": role, "spec": reference, "path": resolved_path}
            references.append({"field": field, "role": role, "path": str(resolved_path), "status": status})
            continue

        try:
            manifest = _load_json(resolved_path)
        except Exception as exc:
            checks.append(
                _new_check(
                    f"confound:reference:{field}",
                    severity=severity,
                    status="block",
                    message=f"Reference manifest for `{field}` failed to parse: {exc}",
                    details=details,
                )
            )
            resolved_refs[field] = {"status": "block", "role": role, "spec": reference, "path": resolved_path}
            references.append({"field": field, "role": role, "path": str(resolved_path), "status": "block"})
            continue

        checks.append(
            _new_check(
                f"confound:reference:{field}",
                severity=severity,
                status="pass",
                message=f"Reference manifest for `{field}` exists and parsed successfully.",
                details=details,
            )
        )
        resolved_refs[field] = {
            "status": "pass",
            "role": role,
            "spec": reference,
            "path": resolved_path,
            "manifest": manifest,
        }
        references.append({"field": field, "role": role, "path": str(resolved_path), "status": "pass"})
    return checks, resolved_refs, references


def _prompt_alignment_check(
    config: dict[str, Any],
    *,
    contract: dict[str, Any],
    proposal_type: dict[str, Any],
    resolved_refs: dict[str, dict[str, Any]],
) -> dict:
    prompt_cfg = proposal_type.get("prompt_alignment")
    if not prompt_cfg:
        return _new_check(
            "confound:prompt-parser",
            severity="warn",
            status="skip",
            message="Prompt/parser confound check is not configured for this proposal kind.",
        )

    severity = str(prompt_cfg.get("severity", "block"))
    issues: list[str] = []
    details: dict[str, Any] = {}

    registry_name = str(prompt_cfg.get("registry_name", "prompt_templates"))
    registry_template_field = prompt_cfg.get("registry_template_field")
    registry_parser_field = prompt_cfg.get("registry_parser_field")
    if isinstance(registry_template_field, str):
        template_id = _get_field(config, registry_template_field)
        details["template_id"] = template_id
        if isinstance(template_id, str):
            registry = contract.get(registry_name, {})
            expected = registry.get(template_id, {}) if isinstance(registry, dict) else {}
            expected_parser = expected.get("parser_id") if isinstance(expected, dict) else None
            actual_parser = _get_field(config, str(registry_parser_field)) if isinstance(registry_parser_field, str) else None
            if expected_parser is not None:
                details["expected_parser_id"] = expected_parser
                if actual_parser not in (None, "") and actual_parser != expected_parser:
                    issues.append(
                        f"Config parser `{actual_parser}` does not match template `{template_id}` expectation `{expected_parser}`."
                    )

    compare_reference_fields = [str(field) for field in prompt_cfg.get("compare_reference_fields", [])]
    reference_fields = [str(field) for field in prompt_cfg.get("reference_fields", list(resolved_refs.keys()))]
    for axis in compare_reference_fields:
        values: dict[str, Any] = {}
        for field in reference_fields:
            resolved = resolved_refs.get(field)
            manifest = resolved.get("manifest") if resolved else None
            if not isinstance(manifest, dict):
                continue
            value = _get_field(manifest, axis)
            if not _is_missing(value):
                values[field] = value
        if len({_normalize_value(value) for value in values.values()}) > 1:
            issues.append(f"Reference manifests disagree on `{axis}`.")
            details.setdefault("reference_mismatches", {})[axis] = {field: values[field] for field in sorted(values)}

    if issues:
        return _new_check(
            "confound:prompt-parser",
            severity=severity,
            status=severity,
            message="Prompt/parser comparability issues were detected.",
            details={"issues": issues, **details},
        )
    return _new_check(
        "confound:prompt-parser",
        severity=severity,
        status="pass",
        message="Prompt/parser contract is consistent for the candidate comparison set.",
        details=details,
    )


def _evaluation_guard_check(
    config: dict[str, Any],
    *,
    proposal_type: dict[str, Any],
    resolved_refs: dict[str, dict[str, Any]],
) -> dict:
    evaluation_cfg = proposal_type.get("evaluation_guard")
    if not evaluation_cfg:
        return _new_check(
            "confound:evaluation-anchor",
            severity="warn",
            status="skip",
            message="Evaluation-intent confound check is not configured for this proposal kind.",
        )

    severity = str(evaluation_cfg.get("severity", "block"))
    issues: list[str] = []
    details: dict[str, Any] = {}
    missing_config_fields = [
        str(field)
        for field in evaluation_cfg.get("required_config_fields", [])
        if _is_missing(_get_field(config, str(field)))
    ]
    if missing_config_fields:
        issues.append("Missing required evaluation config fields.")
        details["missing_config_fields"] = missing_config_fields

    missing_true_fields = [
        str(field)
        for field in evaluation_cfg.get("required_true_fields", [])
        if _get_field(config, str(field)) is not True
    ]
    if missing_true_fields:
        issues.append("Required boolean evaluation guards are not enabled.")
        details["missing_true_fields"] = missing_true_fields

    reference_details: dict[str, dict[str, list[str]]] = {}
    for requirement in evaluation_cfg.get("reference_requirements", []):
        field = str(requirement["field"])
        resolved = resolved_refs.get(field)
        manifest = resolved.get("manifest") if resolved else None
        if not isinstance(manifest, dict):
            issues.append(f"Reference manifest `{field}` is unavailable for evaluation checks.")
            continue
        missing_required = [
            str(path)
            for path in requirement.get("required_metric_paths", [])
            if _is_missing(_get_field(manifest, str(path)))
        ]
        missing_any = [str(path) for path in requirement.get("required_any_metric_paths", [])]
        any_present = any(not _is_missing(_get_field(manifest, path)) for path in missing_any)
        if missing_required:
            issues.append(f"Reference manifest `{field}` is missing required metric anchors.")
            reference_details.setdefault(field, {})["missing_required_metric_paths"] = missing_required
        if missing_any and not any_present:
            issues.append(f"Reference manifest `{field}` does not expose any acceptable follow-up metric anchor.")
            reference_details.setdefault(field, {})["missing_any_metric_paths"] = missing_any
    if reference_details:
        details["reference_metric_issues"] = reference_details

    if issues:
        return _new_check(
            "confound:evaluation-anchor",
            severity=severity,
            status=severity,
            message="Evaluation intent or metric anchors are insufficient for a trustworthy comparison.",
            details={"issues": issues, **details},
        )
    return _new_check(
        "confound:evaluation-anchor",
        severity=severity,
        status="pass",
        message="Evaluation intent and reference metric anchors are explicit enough for comparison.",
        details=details,
    )


def _reference_strength_checks(
    *,
    contract: dict[str, Any],
    resolved_refs: dict[str, dict[str, Any]],
) -> list[dict]:
    checks: list[dict] = []
    for field, resolved in resolved_refs.items():
        spec = resolved.get("spec", {})
        strength = spec.get("strength", {})
        if not strength:
            continue
        severity = str(spec.get("severity", "block"))
        manifest = resolved.get("manifest")
        details = {"path": str(resolved.get("path")) if resolved.get("path") else None, "role": resolved.get("role")}
        if not isinstance(manifest, dict):
            checks.append(
                _new_check(
                    f"confound:reference-strength:{field}",
                    severity=severity,
                    status="block",
                    message="Reference strength could not be evaluated because the manifest is unavailable.",
                    details=details,
                )
            )
            continue

        issues: list[str] = []
        required_status = strength.get("require_run_status")
        actual_status = _get_field(manifest, "run.status")
        if required_status is not None and actual_status != required_status:
            issues.append(f"run.status is `{actual_status}` instead of `{required_status}`")
        if bool(strength.get("forbid_analysis_prep", False)) and _is_analysis_prep_manifest(manifest, contract):
            issues.append("manifest still looks like an analysis-prep or placeholder artifact")
        missing_metric_paths = [
            str(path)
            for path in strength.get("require_metric_paths", [])
            if _is_missing(_get_field(manifest, str(path)))
        ]
        if missing_metric_paths:
            details["missing_metric_paths"] = missing_metric_paths
            issues.append("required metric anchors are missing")
        any_metric_paths = [str(path) for path in strength.get("require_any_metric_paths", [])]
        if any_metric_paths and not any(not _is_missing(_get_field(manifest, path)) for path in any_metric_paths):
            details["missing_any_metric_paths"] = any_metric_paths
            issues.append("none of the acceptable follow-up evidence fields are present")
        note_markers = [str(marker) for marker in strength.get("forbid_notes_containing", [])]
        notes_text = _notes_text(manifest.get("notes"))
        if note_markers and any(marker.lower() in notes_text.lower() for marker in note_markers):
            issues.append("notes explicitly mark the reference as prep-only or weak")
            details["forbidden_note_markers"] = note_markers

        if issues:
            checks.append(
                _new_check(
                    f"confound:reference-strength:{field}",
                    severity=severity,
                    status=severity,
                    message=f"Reference manifest `{field}` is too weak for a trustworthy follow-up comparison.",
                    details={"issues": issues, **details},
                )
            )
        else:
            checks.append(
                _new_check(
                    f"confound:reference-strength:{field}",
                    severity=severity,
                    status="pass",
                    message=f"Reference manifest `{field}` clears the configured evidence-strength guard.",
                    details=details,
                )
            )
    return checks


def _runtime_checks(
    config: dict[str, Any],
    *,
    proposal_type: dict[str, Any],
    resolved_refs: dict[str, dict[str, Any]],
) -> list[dict]:
    runtime_cfg = proposal_type.get("runtime_guard")
    if not runtime_cfg:
        return [
            _new_check(
                "confound:runtime-fallback",
                severity="warn",
                status="skip",
                message="Runtime fallback check is not configured for this proposal kind.",
            ),
            _new_check(
                "confound:runtime-comparability",
                severity="warn",
                status="skip",
                message="Runtime comparability check is not configured for this proposal kind.",
            ),
        ]

    checks: list[dict] = []
    fallback_fields = [str(field) for field in runtime_cfg.get("suspect_config_fields", [])]
    fallback_details = {field: _get_field(config, field) for field in fallback_fields if not _is_missing(_get_field(config, field))}
    fallback_severity = str(runtime_cfg.get("fallback_severity", "warn"))
    if fallback_details:
        checks.append(
            _new_check(
                "confound:runtime-fallback",
                severity=fallback_severity,
                status=fallback_severity,
                message="Config declares a runtime fallback that can change fairness or comparability.",
                details={"suspect_config_fields": fallback_details},
            )
        )
    else:
        checks.append(
            _new_check(
                "confound:runtime-fallback",
                severity=fallback_severity,
                status="pass",
                message="No suspicious runtime fallback field was declared in the config.",
            )
        )

    compare_fields = [str(field) for field in runtime_cfg.get("compare_reference_fields", [])]
    mismatch_details: dict[str, dict[str, Any]] = {}
    for axis in compare_fields:
        values: dict[str, Any] = {}
        for field, resolved in resolved_refs.items():
            manifest = resolved.get("manifest")
            if not isinstance(manifest, dict):
                continue
            value = _get_field(manifest, axis)
            if not _is_missing(value):
                values[field] = value
        if len({_normalize_value(value) for value in values.values()}) > 1:
            mismatch_details[axis] = values
    mismatch_severity = str(runtime_cfg.get("reference_mismatch_severity", "block"))
    if mismatch_details:
        checks.append(
            _new_check(
                "confound:runtime-comparability",
                severity=mismatch_severity,
                status=mismatch_severity,
                message="Reference manifests imply different runtime surfaces for the candidate comparison.",
                details={"reference_runtime_mismatches": mismatch_details},
            )
        )
    else:
        checks.append(
            _new_check(
                "confound:runtime-comparability",
                severity=mismatch_severity,
                status="pass",
                message="Reference manifests do not expose a runtime-surface mismatch on configured axes.",
            )
        )
    return checks


def _comparability_check(
    config: dict[str, Any],
    *,
    proposal_type: dict[str, Any],
    resolved_refs: dict[str, dict[str, Any]],
) -> dict:
    comparability_cfg = proposal_type.get("comparability")
    if not comparability_cfg:
        return _new_check(
            "confound:manifest-comparability",
            severity="warn",
            status="skip",
            message="Manifest comparability guard is not configured for this proposal kind.",
        )

    severity = str(comparability_cfg.get("severity", "block"))
    mismatch_details: dict[str, Any] = {}
    issues: list[str] = []

    for axis in comparability_cfg.get("compare_reference_fields", []):
        axis = str(axis)
        values: dict[str, Any] = {}
        for field, resolved in resolved_refs.items():
            manifest = resolved.get("manifest")
            if not isinstance(manifest, dict):
                continue
            value = _get_field(manifest, axis)
            if not _is_missing(value):
                values[field] = value
        if len({_normalize_value(value) for value in values.values()}) > 1:
            mismatch_details.setdefault("reference_field_mismatches", {})[axis] = values
            issues.append(f"Reference manifests disagree on `{axis}`.")

    for pair in comparability_cfg.get("config_reference_pairs", []):
        config_field = str(pair["config_field"])
        reference_field = str(pair["reference_field"])
        config_value = _get_field(config, config_field)
        if _is_missing(config_value):
            continue
        for reference_name in [str(name) for name in pair.get("reference_manifests", list(resolved_refs.keys()))]:
            resolved = resolved_refs.get(reference_name)
            manifest = resolved.get("manifest") if resolved else None
            if not isinstance(manifest, dict):
                continue
            reference_value = _get_field(manifest, reference_field)
            if _is_missing(reference_value):
                continue
            if _normalize_value(config_value) != _normalize_value(reference_value):
                mismatch_details.setdefault("config_reference_mismatches", []).append(
                    {
                        "config_field": config_field,
                        "config_value": config_value,
                        "reference_manifest": reference_name,
                        "reference_field": reference_field,
                        "reference_value": reference_value,
                    }
                )
                issues.append(f"Config `{config_field}` does not match `{reference_name}` on `{reference_field}`.")

    if issues:
        return _new_check(
            "confound:manifest-comparability",
            severity=severity,
            status=severity,
            message="Manifest or config comparability mismatches were detected.",
            details={"issues": issues, **mismatch_details},
        )
    notes_field = comparability_cfg.get("notes_field")
    require_notes = bool(comparability_cfg.get("require_notes", False))
    if require_notes and isinstance(notes_field, str) and _is_missing(_get_field(config, notes_field)):
        notes_severity = str(comparability_cfg.get("notes_severity", "warn"))
        return _new_check(
            "confound:manifest-comparability",
            severity=notes_severity,
            status=notes_severity,
            message="Comparable references exist, but the config does not record explicit comparability notes.",
            details={"notes_field": notes_field, **mismatch_details},
        )
    return _new_check(
        "confound:manifest-comparability",
        severity=severity,
        status="pass",
        message="Manifest set and config stay on the configured comparability axes.",
        details=mismatch_details,
    )


def _write_markdown_report(report: dict, markdown_path: Path) -> None:
    lines = [
        "# Confound guard",
        "",
        f"- verdict: `{report['verdict']}`",
        f"- config_kind: `{report['config_kind']}`",
        f"- config_path: `{report['config_path']}`",
        f"- mission_id: `{report['mission_id']}`",
        "",
        "## References",
        "",
    ]
    if report["references"]:
        lines.extend(
            f"- `{reference['status']}` `{reference['field']}` ({reference['role']}): `{reference.get('path')}`"
            for reference in report["references"]
        )
    else:
        lines.append("- no reference manifests configured")
    lines.extend(["", "## Reasons", ""])
    if report["reasons"]:
        lines.extend(f"- `{reason['severity']}` `{reason['check_id']}`: {reason['message']}" for reason in report["reasons"])
    else:
        lines.append("- all configured confound checks passed")
    lines.extend(["", "## Checks", ""])
    lines.extend(f"- `{check['status']}` `{check['id']}`: {check['message']}" for check in report["checks"])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_report(report: dict) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    schema = _load_json(REPORT_SCHEMA_PATH)
    jsonschema.validate(report, schema)


def evaluate_confound_guard(
    config_path: Path,
    *,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    mission_state_path: Path | None = None,
    repo_root: Path | None = None,
    artifact_name: str | None = None,
    queue_entry_id: str | None = None,
) -> dict:
    checks: list[dict] = []
    references: list[dict] = []
    config = None
    config_kind = "unknown"
    repo_root = repo_root or _infer_repo_root(config_path)
    contract = _load_yaml(contract_path)

    if not config_path.exists():
        checks.append(
            _new_check(
                "confound:config-parse",
                severity="block",
                status="block",
                message="Proposal config does not exist.",
                details={"path": str(config_path)},
            )
        )
    else:
        try:
            config = _load_yaml(config_path) if config_path.suffix.lower() in {".yaml", ".yml"} else _load_json(config_path)
            config_kind = _infer_config_kind(config)
            checks.append(
                _new_check(
                    "confound:config-parse",
                    severity="block",
                    status="pass",
                    message="Proposal config parsed successfully for confound checks.",
                    details={"path": str(config_path), "config_kind": config_kind},
                )
            )
        except Exception as exc:
            checks.append(
                _new_check(
                    "confound:config-parse",
                    severity="block",
                    status="block",
                    message=f"Proposal config failed to parse for confound checks: {exc}",
                    details={"path": str(config_path)},
                )
            )

    proposal_type = contract.get("proposal_types", {}).get(config_kind, {})
    resolved_refs: dict[str, dict[str, Any]] = {}
    if config is not None and proposal_type:
        reference_checks, resolved_refs, references = _resolve_references(
            config,
            config_path=config_path,
            repo_root=repo_root,
            proposal_type=proposal_type,
        )
        checks.extend(reference_checks)
        checks.extend(_reference_strength_checks(contract=contract, resolved_refs=resolved_refs))
        checks.append(
            _prompt_alignment_check(
                config,
                contract=contract,
                proposal_type=proposal_type,
                resolved_refs=resolved_refs,
            )
        )
        checks.append(
            _evaluation_guard_check(
                config,
                proposal_type=proposal_type,
                resolved_refs=resolved_refs,
            )
        )
        checks.extend(
            _runtime_checks(
                config,
                proposal_type=proposal_type,
                resolved_refs=resolved_refs,
            )
        )
        checks.append(
            _comparability_check(
                config,
                proposal_type=proposal_type,
                resolved_refs=resolved_refs,
            )
        )
    elif config is not None:
        checks.append(
            _new_check(
                "confound:proposal-kind",
                severity="warn",
                status="skip",
                message=f"No confound policy is configured for proposal kind `{config_kind}`.",
            )
        )

    reasons = [
        {"check_id": check["id"], "severity": check["status"], "message": check["message"]}
        for check in checks
        if check["status"] in {"warn", "block"}
    ]
    if any(check["status"] == "block" for check in checks):
        verdict = "block"
    elif any(check["status"] == "warn" for check in checks):
        verdict = "warn"
    else:
        verdict = "pass"

    report_root = _report_root(mission_state_path, contract)
    report_root.mkdir(parents=True, exist_ok=True)
    artifact_stem = artifact_name or config_path.stem
    report_json_path = report_root / f"{artifact_stem}.json"
    report_md_path = report_root / f"{artifact_stem}.md"
    report = {
        "schema_version": 1,
        "created_at": now_utc(),
        "mission_id": None,
        "queue_entry_id": queue_entry_id,
        "config_path": str(config_path),
        "config_kind": config_kind,
        "contract_path": str(contract_path),
        "repo_root": str(repo_root) if repo_root is not None else None,
        "verdict": verdict,
        "summary": {
            "passed": sum(1 for check in checks if check["status"] == "pass"),
            "warned": sum(1 for check in checks if check["status"] == "warn"),
            "blocked": sum(1 for check in checks if check["status"] == "block"),
            "skipped": sum(1 for check in checks if check["status"] == "skip"),
        },
        "reasons": reasons,
        "checks": checks,
        "references": references,
        "artifacts": {
            "report_json": str(report_json_path),
            "report_markdown": str(report_md_path),
        },
    }
    if mission_state_path is not None and mission_state_path.exists():
        mission_state = _load_json(mission_state_path)
        report["mission_id"] = mission_state.get("mission_id")

    _validate_report(report)
    report_json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _write_markdown_report(report, report_md_path)

    if mission_state_path is not None and mission_state_path.exists() and report["mission_id"] is not None:
        ledger_path = mission_state_path.parent / "ledger.jsonl"
        append_jsonl(
            ledger_path,
            make_ledger_entry(
                kind="confound-guard",
                mission_id=str(report["mission_id"]),
                summary=f"Confound guard for {artifact_stem} returned {verdict}",
                status=verdict,
                related_paths=[str(config_path), str(report_json_path), str(report_md_path)],
                metadata={
                    "config_kind": config_kind,
                    "queue_entry_id": queue_entry_id,
                    "reasons": reasons,
                },
            ),
        )

    return {
        "verdict": verdict,
        "report": report,
        "report_json_path": report_json_path,
        "report_markdown_path": report_md_path,
    }


@dataclass
class CheckResult:
    check_id: str
    result: str
    message: str
    affected_fields: list[str]
    details: dict[str, Any]


def _infer_config_type(config: dict[str, Any]) -> str:
    if "intervention_type" in config or "localization_manifest_path" in config:
        return "causal-intervention"
    if "baseline_manifest_path" in config or "localization_targets" in config:
        return "mechanistic-localization"
    return "baseline-eval"


def _compat_check_result(
    check_id: str,
    result: str,
    message: str,
    *,
    affected_fields: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        result=result,
        message=message,
        affected_fields=affected_fields or [],
        details=details or {},
    )


def _check_prompt_parser_mismatch(config: dict[str, Any], baseline_config: dict[str, Any] | None, config_type: str) -> CheckResult:
    if config_type == "baseline-eval":
        return _compat_check_result("prompt-parser-mismatch", "pass", "Baseline prompt/parser contract is self-contained.")
    if baseline_config is None:
        return _compat_check_result(
            "prompt-parser-mismatch",
            "block",
            "Follow-up config is missing `baseline_config_source`, so prompt/parser comparability cannot be checked.",
            affected_fields=["baseline_config_source"],
        )
    mismatches: list[str] = []
    affected_fields: list[str] = []
    for field in ("prompt_template", "parser"):
        config_value = config.get(field)
        baseline_value = baseline_config.get(field)
        if config_value != baseline_value:
            mismatches.append(f"{field}: {config_value!r} != {baseline_value!r}")
            affected_fields.append(field)
    if mismatches:
        return _compat_check_result(
            "prompt-parser-mismatch",
            "block",
            "Follow-up prompt/parser contract diverges from the baseline config.",
            affected_fields=affected_fields,
            details={"mismatches": mismatches},
        )
    return _compat_check_result("prompt-parser-mismatch", "pass", "Follow-up prompt/parser contract matches the baseline config.")


def _check_model_mismatch(config: dict[str, Any], baseline_config: dict[str, Any] | None, config_type: str) -> CheckResult:
    if config_type == "baseline-eval" or baseline_config is None:
        return _compat_check_result("model-mismatch", "pass", "No cross-config model comparison is required.")
    config_value = config.get("model_name", config.get("model"))
    baseline_value = baseline_config.get("model_name", baseline_config.get("model"))
    if config_value != baseline_value:
        return _compat_check_result(
            "model-mismatch",
            "block",
            "Follow-up config points at a different model than the baseline reference.",
            affected_fields=["model_name"],
            details={"config_model": config_value, "baseline_model": baseline_value},
        )
    return _compat_check_result("model-mismatch", "pass", "Model lineage matches the baseline reference.")


def _check_missing_baseline_reference(config: dict[str, Any], config_type: str) -> CheckResult:
    if config_type == "baseline-eval":
        return _compat_check_result("missing-baseline-reference", "pass", "Baseline config does not need a prior baseline reference.")
    reference_fields = [
        "baseline_manifest_path",
        "behavioral_source_manifest",
        "evaluation.compare_against",
    ]
    for field in reference_fields:
        if "." in field:
            if not _is_missing(_get_field(config, field)):
                return _compat_check_result("missing-baseline-reference", "pass", "Baseline reference field is present.")
        elif not _is_missing(config.get(field)):
            return _compat_check_result("missing-baseline-reference", "pass", "Baseline reference field is present.")
    return _compat_check_result(
        "missing-baseline-reference",
        "block",
        "Follow-up config is missing a usable baseline manifest reference.",
        affected_fields=["baseline_manifest_path"],
    )


def _check_evaluation_contract_drift(config: dict[str, Any], baseline_config: dict[str, Any] | None, config_type: str) -> CheckResult:
    if baseline_config is None or config_type == "baseline-eval":
        return _compat_check_result("evaluation-contract-drift", "pass", "No baseline evaluation contract comparison is required.")
    current_metrics = [str(item) for item in config.get("metrics", []) if str(item)]
    baseline_metrics = [str(item) for item in baseline_config.get("metrics", []) if str(item)]
    if not baseline_metrics:
        return _compat_check_result("evaluation-contract-drift", "pass", "Baseline config does not declare a metrics contract.")
    if not current_metrics:
        return _compat_check_result(
            "evaluation-contract-drift",
            "warn",
            "Follow-up config omits explicit metrics even though the baseline declared them.",
            affected_fields=["metrics"],
            details={"baseline_metrics": baseline_metrics},
        )
    missing_metrics = [metric for metric in baseline_metrics if metric not in current_metrics]
    if missing_metrics:
        return _compat_check_result(
            "evaluation-contract-drift",
            "warn",
            f"Follow-up config dropped baseline metrics: {', '.join(missing_metrics)}.",
            affected_fields=["metrics"],
            details={"baseline_metrics": baseline_metrics, "config_metrics": current_metrics},
        )
    return _compat_check_result("evaluation-contract-drift", "pass", "Evaluation contract stayed aligned with the baseline metrics.")


def _check_followup_lineage(
    config: dict[str, Any],
    baseline_config: dict[str, Any] | None,
    config_type: str,
    config_path: Path,
) -> CheckResult:
    del baseline_config
    if config_type == "baseline-eval":
        return _compat_check_result("followup-lineage", "pass", "Baseline config does not depend on prior lineage artifacts.")
    baseline_manifest = config.get("baseline_manifest_path") or config.get("behavioral_source_manifest") or _get_field(config, "evaluation.compare_against")
    if _is_missing(baseline_manifest):
        return _compat_check_result(
            "followup-lineage",
            "warn",
            "Follow-up lineage is incomplete because `baseline_manifest_path` is missing.",
            affected_fields=["baseline_manifest_path"],
        )
    baseline_path = _resolve_path(str(baseline_manifest), repo_root=_infer_repo_root(config_path), config_path=config_path)
    if not baseline_path.exists():
        return _compat_check_result(
            "followup-lineage",
            "warn",
            "Follow-up lineage references a baseline manifest path that does not exist yet.",
            affected_fields=["baseline_manifest_path"],
            details={"path": str(baseline_path)},
        )
    return _compat_check_result("followup-lineage", "pass", "Follow-up lineage points at an existing baseline manifest.")


def evaluate_confound_contamination(
    config_path: Path,
    *,
    mission_state_path: Path | None = None,
    artifact_name: str | None = None,
) -> dict:
    config = _load_yaml(config_path)
    config_type = _infer_config_type(config)
    baseline_config: dict[str, Any] | None = None
    baseline_source = config.get("baseline_config_source")
    if isinstance(baseline_source, str) and baseline_source:
        baseline_path = _resolve_path(baseline_source, repo_root=_infer_repo_root(config_path), config_path=config_path)
        if baseline_path.exists():
            baseline_config = _load_yaml(baseline_path)

    checks = [
        _check_prompt_parser_mismatch(config, baseline_config, config_type),
        _check_model_mismatch(config, baseline_config, config_type),
        _check_missing_baseline_reference(config, config_type),
        _check_evaluation_contract_drift(config, baseline_config, config_type),
        _check_followup_lineage(config, baseline_config, config_type, config_path),
    ]
    if any(check.result == "block" for check in checks):
        verdict = "block"
    elif any(check.result == "warn" for check in checks):
        verdict = "warn"
    else:
        verdict = "pass"

    if mission_state_path is not None:
        artifact_root = mission_state_path.parent / "confound_analysis"
    else:
        artifact_root = RUNS_DIR / "confound_analysis"
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_stem = artifact_name or config_path.stem
    report_json_path = artifact_root / f"{artifact_stem}.json"
    report_markdown_path = artifact_root / f"{artifact_stem}.md"
    warnings_jsonl_path = artifact_root / f"{artifact_stem}.warnings.jsonl"

    report = {
        "config_path": str(config_path),
        "config_type": config_type,
        "verdict": verdict,
        "checks_run": [asdict(check) for check in checks],
    }
    report_json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report_markdown_path.write_text(
        "# Confound contamination analysis\n\n"
        + "\n".join(f"- `{check.result}` `{check.check_id}`: {check.message}" for check in checks)
        + "\n",
        encoding="utf-8",
    )
    warnings_jsonl_path.write_text(
        "".join(json.dumps(asdict(check)) + "\n" for check in checks if check.result in {"warn", "block"}),
        encoding="utf-8",
    )

    ledger_entry = None
    if mission_state_path is not None and mission_state_path.exists():
        mission_state = _load_json(mission_state_path)
        ledger_entry = make_ledger_entry(
            kind="confound-contamination-guard",
            mission_id=str(mission_state.get("mission_id")),
            summary=f"Compatibility confound analysis for {artifact_stem} returned {verdict}",
            status=verdict,
            related_paths=[str(report_json_path), str(report_markdown_path), str(warnings_jsonl_path)],
            metadata={"config_type": config_type},
        )
        append_jsonl(artifact_root / "ledger.jsonl", ledger_entry)

    return {
        "verdict": verdict,
        "config_type": config_type,
        "report_json_path": report_json_path,
        "report_markdown_path": report_markdown_path,
        "warnings_jsonl_path": warnings_jsonl_path,
        "ledger_entry": ledger_entry,
    }
