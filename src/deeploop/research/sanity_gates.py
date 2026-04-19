from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from deeploop.core.config_paths import infer_repo_root_from_configs as _infer_repo_root, resolve_config_path as _resolve_path
from deeploop.core.dotted import get_dotted as _get_field
from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.paths import REPO_ROOT, RUNS_DIR
from deeploop.core.structured_io import (
    load_json_object as _load_json,
    load_structured_mapping as _load_structured,
    load_yaml_mapping as _load_yaml,
)
from deeploop.research.confound_guard import DEFAULT_CONTRACT_PATH as DEFAULT_CONFOUND_CONTRACT_PATH, evaluate_confound_guard

DEFAULT_CONTRACT_PATH = REPO_ROOT / "configs" / "autonomy" / "research-sanity-gates.yaml"
REPORT_SCHEMA_PATH = REPO_ROOT / "schemas" / "research-sanity-report.schema.json"


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


def _select_promotion_entries(manifest: dict, *, tiers: list[str] | None, split_kinds: list[str] | None, split_families: list[str] | None) -> list[dict]:
    selected: list[dict] = []
    for entry in manifest.get("files", []):
        if tiers and entry.get("tier") not in tiers:
            continue
        if split_kinds and entry.get("split_kind") not in split_kinds:
            continue
        if split_families and entry.get("split_family") not in split_families:
            continue
        selected.append(entry)
    return selected


def _probe_matching_examples(entries: list[dict], *, lexicalizations: list[str] | None, probe_limit: int) -> tuple[int, list[str]]:
    matched_examples = 0
    missing_paths: list[str] = []
    for entry in entries:
        local_path = Path(entry["local_path"]).expanduser()
        if not local_path.exists():
            missing_paths.append(str(local_path))
            continue
        with local_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                if lexicalizations and record.get("lex") not in lexicalizations:
                    continue
                matched_examples += 1
                if matched_examples >= probe_limit:
                    return matched_examples, missing_paths
    return matched_examples, missing_paths


def _resolve_dataset_probe(
    config: dict[str, Any],
    config_kind: str,
    *,
    proposal_type: dict[str, Any],
    resolved_refs: dict[str, dict[str, Any]],
) -> tuple[dict | None, dict | None]:
    dataset_source = proposal_type.get("dataset_source", {})
    if not dataset_source:
        return None, None

    selection: dict[str, Any] = {}
    lexicalizations: list[str] | None = None
    promotion_manifest_path: Path | None = None

    if config_kind == "baseline-eval":
        manifest_field = str(dataset_source["promotion_manifest_field"])
        manifest_ref = resolved_refs.get(manifest_field)
        if manifest_ref is None or manifest_ref.get("status") != "pass":
            return None, None
        promotion_manifest_path = manifest_ref["path"]
        selection = dict(_get_field(config, str(dataset_source["selection_field"])) or {})
        lexicalizations = list(_get_field(config, str(dataset_source["lexicalizations_field"])) or [])
    elif config_kind == "mechanistic-localization":
        source_manifest_ref = resolved_refs.get(str(dataset_source["manifest_field"]))
        if source_manifest_ref is None or source_manifest_ref.get("status") != "pass":
            return None, None
        source_manifest = source_manifest_ref["content"]
        provenance = source_manifest.get("dataset", {}).get("provenance")
        if not isinstance(provenance, str):
            return None, _new_check(
                "dataset-provenance",
                severity="block",
                status="block",
                message="Behavioral source manifest does not expose a dataset provenance path for sanity probing.",
            )
        promotion_manifest_path = Path(provenance).expanduser()
        selection_map = dataset_source.get("selection_map", {})
        selection = {
            "tiers": _get_field(config, str(selection_map.get("tiers", ""))) or None,
            "split_kinds": None,
            "split_families": _get_field(config, str(selection_map.get("split_families", ""))) or None,
        }
        lexicalizations = list(_get_field(config, str(selection_map.get("lexicalizations", ""))) or [])
    elif config_kind == "causal-intervention":
        baseline_ref = resolved_refs.get(str(dataset_source["manifest_field"]))
        if baseline_ref is None or baseline_ref.get("status") != "pass":
            return None, None
        baseline_manifest = baseline_ref["content"]
        provenance = baseline_manifest.get("dataset", {}).get("provenance")
        if not isinstance(provenance, str):
            return None, _new_check(
                "dataset-provenance",
                severity="block",
                status="block",
                message="Baseline manifest does not expose a dataset provenance path for sanity probing.",
            )
        promotion_manifest_path = Path(provenance).expanduser()
        selection = {"tiers": None, "split_kinds": None, "split_families": None}
        lexicalizations = None
    else:
        return None, None

    if promotion_manifest_path is None or not promotion_manifest_path.exists():
        return None, _new_check(
            "dataset-provenance",
            severity="block",
            status="block",
            message="Resolved dataset provenance manifest is missing.",
            details={"path": str(promotion_manifest_path) if promotion_manifest_path else None},
        )

    return {
        "promotion_manifest_path": promotion_manifest_path,
        "selection": selection,
        "lexicalizations": lexicalizations,
    }, None


def _report_root(mission_state_path: Path | None, contract: dict[str, Any]) -> Path:
    artifact_dir_name = str(contract.get("artifact_dir_name", "research_sanity"))
    if mission_state_path is not None:
        return mission_state_path.parent / artifact_dir_name
    return RUNS_DIR / artifact_dir_name


def _write_markdown_report(report: dict, markdown_path: Path) -> None:
    lines = [
        "# Research sanity gate",
        "",
        f"- verdict: `{report['verdict']}`",
        f"- config_kind: `{report['config_kind']}`",
        f"- config_path: `{report['config_path']}`",
        f"- mission_id: `{report['mission_id']}`",
        "",
        "## Reasons",
        "",
    ]
    if report["reasons"]:
        lines.extend(
            f"- `{reason['severity']}` `{reason['check_id']}`: {reason['message']}" for reason in report["reasons"]
        )
    else:
        lines.append("- all configured checks passed")
    lines.extend(["", "## Checks", ""])
    lines.extend(
        f"- `{check['status']}` `{check['id']}`: {check['message']}" for check in report["checks"]
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_report(report: dict) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    schema = _load_json(REPORT_SCHEMA_PATH)
    jsonschema.validate(report, schema)


def extract_proposal_config_path(command: list[str] | str, *, repo_root: Path) -> Path | None:
    tokens = shlex.split(command) if isinstance(command, str) else [str(token) for token in command]
    for index, token in enumerate(tokens):
        if token == "--config" and index + 1 < len(tokens):
            return _resolve_path(tokens[index + 1], repo_root=repo_root, config_path=repo_root / "configs")
        if token.startswith("--config="):
            return _resolve_path(token.split("=", 1)[1], repo_root=repo_root, config_path=repo_root / "configs")
    return None


def evaluate_research_sanity(
    config_path: Path,
    *,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    mission_state_path: Path | None = None,
    repo_root: Path | None = None,
    artifact_name: str | None = None,
    queue_entry_id: str | None = None,
    confound_contract_path: Path = DEFAULT_CONFOUND_CONTRACT_PATH,
) -> dict:
    checks: list[dict] = []
    config = None
    config_kind = "unknown"
    repo_root = repo_root or _infer_repo_root(config_path)
    contract = _load_yaml(contract_path)

    if not config_path.exists():
        checks.append(
            _new_check(
                "config-parse",
                severity="block",
                status="block",
                message="Referenced proposal config does not exist.",
                details={"path": str(config_path)},
            )
        )
    else:
        try:
            config = _load_structured(config_path)
            config_kind = _infer_config_kind(config)
            checks.append(
                _new_check(
                    "config-parse",
                    severity="block",
                    status="pass",
                    message="Proposal config exists and parsed successfully.",
                    details={"path": str(config_path), "config_kind": config_kind},
                )
            )
        except Exception as exc:
            checks.append(
                _new_check(
                    "config-parse",
                    severity="block",
                    status="block",
                    message=f"Proposal config failed to parse: {exc}",
                    details={"path": str(config_path)},
                )
            )

    resolved_refs: dict[str, dict[str, Any]] = {}
    proposal_type = contract.get("proposal_types", {}).get(config_kind, {})

    if config is not None and proposal_type:
        for reference in proposal_type.get("required_paths", []):
            field = str(reference["field"])
            raw_value = _get_field(config, field)
            if not isinstance(raw_value, str) or not raw_value:
                status = "block" if reference.get("required", True) else "warn"
                check = _new_check(
                    f"reference:{field}",
                    severity=str(reference.get("severity", status)),
                    status=status,
                    message=f"Required reference field `{field}` is missing.",
                )
                checks.append(check)
                resolved_refs[field] = {"status": status}
                continue

            resolved_path = _resolve_path(raw_value, repo_root=repo_root, config_path=config_path)
            details = {"field": field, "path": str(resolved_path)}
            if not resolved_path.exists():
                status = "block" if reference.get("required", True) else "warn"
                check = _new_check(
                    f"reference:{field}",
                    severity=str(reference.get("severity", status)),
                    status=status,
                    message=f"Referenced artifact for `{field}` does not exist.",
                    details=details,
                )
                checks.append(check)
                resolved_refs[field] = {"status": status, "path": resolved_path}
                continue

            parsed_content = None
            parse_as = reference.get("parse_as")
            try:
                if parse_as == "json":
                    parsed_content = _load_json(resolved_path)
                elif parse_as == "yaml":
                    parsed_content = _load_yaml(resolved_path)
                checks.append(
                    _new_check(
                        f"reference:{field}",
                        severity=str(reference.get("severity", "block")),
                        status="pass",
                        message=f"Referenced artifact for `{field}` exists and is readable.",
                        details=details,
                    )
                )
                resolved_refs[field] = {"status": "pass", "path": resolved_path, "content": parsed_content}
            except Exception as exc:
                checks.append(
                    _new_check(
                        f"reference:{field}",
                        severity=str(reference.get("severity", "block")),
                        status="block",
                        message=f"Referenced artifact for `{field}` failed to parse: {exc}",
                        details=details,
                    )
                )
                resolved_refs[field] = {"status": "block", "path": resolved_path}

    if config is not None and proposal_type:
        dataset_probe, dataset_probe_error = _resolve_dataset_probe(
            config,
            config_kind,
            proposal_type=proposal_type,
            resolved_refs=resolved_refs,
        )
        if dataset_probe_error is not None:
            checks.append(dataset_probe_error)
        elif dataset_probe is not None:
            promotion_manifest = _load_json(dataset_probe["promotion_manifest_path"])
            selection = dataset_probe["selection"]
            selected_entries = _select_promotion_entries(
                promotion_manifest,
                tiers=selection.get("tiers"),
                split_kinds=selection.get("split_kinds"),
                split_families=selection.get("split_families"),
            )
            if not selected_entries:
                checks.append(
                    _new_check(
                        "dataset-non-empty",
                        severity="block",
                        status="block",
                        message="Dataset selection matched zero promoted files.",
                        details={"promotion_manifest": str(dataset_probe["promotion_manifest_path"])},
                    )
                )
            else:
                probe_limit = max(int(contract.get("default_power_warning_threshold", 16)), 1)
                matched_examples, missing_paths = _probe_matching_examples(
                    selected_entries,
                    lexicalizations=dataset_probe["lexicalizations"],
                    probe_limit=probe_limit,
                )
                if missing_paths:
                    checks.append(
                        _new_check(
                            "dataset-files",
                            severity="block",
                            status="block",
                            message="Selected dataset files are missing locally.",
                            details={"missing_paths": missing_paths},
                        )
                    )
                if matched_examples == 0:
                    checks.append(
                        _new_check(
                            "dataset-non-empty",
                            severity="block",
                            status="block",
                            message="Dataset selection is empty after cheap local probing.",
                            details={
                                "selected_files": len(selected_entries),
                                "promotion_manifest": str(dataset_probe["promotion_manifest_path"]),
                            },
                        )
                    )
                else:
                    checks.append(
                        _new_check(
                            "dataset-non-empty",
                            severity="block",
                            status="pass",
                            message="Dataset selection is non-empty under cheap local probing.",
                            details={
                                "selected_files": len(selected_entries),
                                "matched_examples_probed": matched_examples,
                                "promotion_manifest": str(dataset_probe["promotion_manifest_path"]),
                            },
                        )
                    )

                power_threshold = int(proposal_type.get("cheap_power_check", {}).get("warn_if_examples_below", contract.get("default_power_warning_threshold", 16)))
                limit_field = proposal_type.get("cheap_power_check", {}).get("limit_examples_field")
                configured_limit = _get_field(config, str(limit_field)) if isinstance(limit_field, str) else None
                if isinstance(configured_limit, int) and configured_limit < power_threshold:
                    checks.append(
                        _new_check(
                            "cheap-power-worthiness",
                            severity="warn",
                            status="warn",
                            message=f"Configured example cap {configured_limit} is below the cheap power-worthiness threshold of {power_threshold}.",
                            details={"limit_examples": configured_limit, "threshold": power_threshold},
                        )
                    )
                elif matched_examples < power_threshold:
                    checks.append(
                        _new_check(
                            "cheap-power-worthiness",
                            severity="warn",
                            status="warn",
                            message=f"Only {matched_examples} matching example(s) were found before exhausting the cheap probe; this may be too small for a worthwhile run.",
                            details={"matched_examples": matched_examples, "threshold": power_threshold},
                        )
                    )
                else:
                    checks.append(
                        _new_check(
                            "cheap-power-worthiness",
                            severity="warn",
                            status="pass",
                            message="Cheap power-worthiness probe cleared the configured threshold.",
                            details={"matched_examples_probed": matched_examples, "threshold": power_threshold},
                        )
                    )

    if config is not None and proposal_type:
        prompt_contract = proposal_type.get("prompt_contract", {})
        if prompt_contract.get("applicable", True):
            required_any = [str(field) for field in prompt_contract.get("required_any", [])]
            prompt_values = {field: _get_field(config, field) for field in required_any}
            present_fields = [field for field, value in prompt_values.items() if value not in (None, "", [], {})]
            if not present_fields:
                checks.append(
                    _new_check(
                        "prompt-output-contract",
                        severity="block",
                        status="block",
                        message="No prompt/parser/output-contract field is present for a run that requires one.",
                    )
                )
            else:
                details = {"present_fields": present_fields}
                template_field = str(prompt_contract.get("template_field", "prompt.template_id"))
                template_id = _get_field(config, template_field)
                parser_registry = contract.get(str(prompt_contract.get("template_registry", "")), {})
                if isinstance(template_id, str) and template_id in parser_registry:
                    details["resolved_parser_id"] = parser_registry[template_id].get("parser_id")
                checks.append(
                    _new_check(
                        "prompt-output-contract",
                        severity="block",
                        status="pass",
                        message="Prompt/parser/output-contract fields are present for the proposed run.",
                        details=details,
                    )
                )
        else:
            checks.append(
                _new_check(
                    "prompt-output-contract",
                    severity="warn",
                    status="skip",
                    message="Prompt/output-contract check is not applicable for this proposal kind.",
                )
            )

    if config is not None and proposal_type:
        evaluation_intent = proposal_type.get("evaluation_intent", {})
        evaluation_missing: list[str] = []
        for field in evaluation_intent.get("required_all", []):
            value = _get_field(config, str(field))
            if value in (None, "", [], {}):
                evaluation_missing.append(str(field))
        for field in evaluation_intent.get("required_true", []):
            if _get_field(config, str(field)) is not True:
                evaluation_missing.append(str(field))
        any_true_fields = [str(field) for field in evaluation_intent.get("require_any_true", [])]
        if any_true_fields and not any(_get_field(config, field) is True for field in any_true_fields):
            evaluation_missing.append("one-of:" + ",".join(any_true_fields))

        details: dict[str, Any] = {}
        contract_relative_path = evaluation_intent.get("contract_relative_path")
        if isinstance(contract_relative_path, str):
            contract_file = _resolve_path(contract_relative_path, repo_root=repo_root, config_path=config_path)
            details["contract_path"] = str(contract_file)
            if not contract_file.exists():
                evaluation_missing.append(contract_relative_path)
            else:
                details["contract_exists"] = True
                if contract_file.suffix.lower() in {".yaml", ".yml"}:
                    details["contract"] = _load_yaml(contract_file)
                elif contract_file.suffix.lower() == ".json":
                    details["contract"] = _load_json(contract_file)

        if evaluation_missing:
            checks.append(
                _new_check(
                    "evaluation-intent",
                    severity="block",
                    status="block",
                    message="Metrics or evaluation intent is incomplete for this proposal.",
                    details={"missing_fields": evaluation_missing, **details},
                )
            )
        else:
            checks.append(
                _new_check(
                    "evaluation-intent",
                    severity="block",
                    status="pass",
                    message="Metrics or evaluation intent is explicitly defined for this proposal.",
                    details=details,
                )
            )

    if config is not None and proposal_type:
        comparability = proposal_type.get("comparability", {})
        manifest_fields = [str(field) for field in comparability.get("manifest_fields", [])]
        if "manifest_field" in comparability:
            manifest_fields.append(str(comparability["manifest_field"]))
        if manifest_fields:
            manifests: list[tuple[str, dict[str, Any]]] = []
            missing_fields: list[str] = []
            for field in manifest_fields:
                resolved = resolved_refs.get(field)
                if resolved is None or resolved.get("status") != "pass" or not isinstance(resolved.get("content"), dict):
                    missing_fields.append(field)
                    continue
                manifests.append((field, resolved["content"]))
            if missing_fields:
                checks.append(
                    _new_check(
                        "comparability",
                        severity="block",
                        status="block",
                        message="Follow-up proposal is missing a comparable baseline/reference manifest.",
                        details={"missing_references": missing_fields},
                    )
                )
            else:
                model_field_map = comparability.get("model_fields", {})
                dataset_names = set()
                source_model_values = {"family": set(), "identifier": set()}
                mismatch_messages: list[str] = []
                for field, manifest in manifests:
                    dataset_name = manifest.get("dataset", {}).get("name")
                    if isinstance(dataset_name, str):
                        dataset_names.add(dataset_name)
                    source_model_values["family"].add(str(manifest.get("model", {}).get("family")))
                    source_model_values["identifier"].add(str(manifest.get("model", {}).get("identifier")))
                    expected_family = _get_field(config, str(model_field_map.get("family", "")))
                    expected_identifier = _get_field(config, str(model_field_map.get("identifier", "")))
                    if expected_family is not None and manifest.get("model", {}).get("family") != expected_family:
                        mismatch_messages.append(f"{field} family mismatch")
                    if expected_identifier is not None and manifest.get("model", {}).get("identifier") != expected_identifier:
                        mismatch_messages.append(f"{field} identifier mismatch")
                if len(dataset_names) > 1:
                    mismatch_messages.append("referenced manifests disagree on dataset name")

                notes_field = comparability.get("notes_field")
                comparability_note = _get_field(config, str(notes_field)) if isinstance(notes_field, str) else None
                if mismatch_messages:
                    checks.append(
                        _new_check(
                            "comparability",
                            severity="block",
                            status="block",
                            message="Follow-up proposal is not comparable to its reference manifests.",
                            details={"mismatches": mismatch_messages},
                        )
                    )
                elif comparability_note in (None, "", [], {}):
                    checks.append(
                        _new_check(
                            "comparability",
                            severity="warn",
                            status="warn",
                            message="Comparable reference manifests exist, but the follow-up config has no explicit comparability notes.",
                            details={"manifest_fields": manifest_fields},
                        )
                    )
                else:
                    checks.append(
                        _new_check(
                            "comparability",
                            severity="block",
                            status="pass",
                            message="Follow-up proposal has comparable reference manifests and explicit notes.",
                            details={"manifest_fields": manifest_fields},
                        )
                    )
        else:
            checks.append(
                _new_check(
                    "comparability",
                    severity="warn",
                    status="skip",
                    message="Comparability check is not required for this proposal kind.",
                )
            )

    confound_result = evaluate_confound_guard(
        config_path,
        contract_path=confound_contract_path,
        mission_state_path=mission_state_path,
        repo_root=repo_root,
        artifact_name=artifact_name,
        queue_entry_id=queue_entry_id,
    )
    checks.extend(confound_result["report"]["checks"])

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
        "artifacts": {
            "report_json": str(report_json_path),
            "report_markdown": str(report_md_path),
            "confound_guard_json": str(confound_result["report_json_path"]),
            "confound_guard_markdown": str(confound_result["report_markdown_path"]),
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
                kind="research-sanity-gate",
                mission_id=str(report["mission_id"]),
                summary=f"Research sanity gate for {artifact_stem} returned {verdict}",
                status=verdict,
                related_paths=[
                    str(config_path),
                    str(report_json_path),
                    str(report_md_path),
                    str(confound_result["report_json_path"]),
                    str(confound_result["report_markdown_path"]),
                ],
                metadata={
                    "config_kind": config_kind,
                    "queue_entry_id": queue_entry_id,
                    "confound_verdict": confound_result["verdict"],
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
