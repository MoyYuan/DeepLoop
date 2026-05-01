from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.paths import resolve_workspace_path
from deeploop.core.paths import REPO_ROOT as DEEPLOOP_REPO_ROOT
from deeploop.research.sanity_gates import evaluate_research_sanity, extract_proposal_config_path
from deeploop.research.self_correction import assess_manifest_for_self_correction

DEFAULT_POLICY_PATH = DEEPLOOP_REPO_ROOT / "configs" / "runtime" / "self-healing-runtime.yaml"
RUN_MANIFEST_SCHEMA_PATH = DEEPLOOP_REPO_ROOT / "schemas" / "run-manifest.schema.json"


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded


def _load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected object in {path}")
    return loaded


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True


def _resolved_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _resolved_env_name(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _normalize_tokens(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (str, Path)):
        return [str(raw)]
    return [str(item) for item in raw]


def _resolve_workspace_tokens(raw: Any) -> list[str]:
    return [
        str(resolve_workspace_path(token)) if token.startswith("workspace://") else token
        for token in _normalize_tokens(raw)
    ]


def _policy_entry(policy: dict[str, Any], kind: str) -> dict[str, Any]:
    entry = policy.get("taxonomy", {}).get(kind)
    if not isinstance(entry, dict):
        raise KeyError(f"Unknown runtime failure kind: {kind}")
    return entry


def _failure_record(
    policy: dict[str, Any],
    kind: str,
    *,
    details: dict[str, Any],
    repair_order: list[str] | None = None,
) -> dict[str, Any]:
    entry = _policy_entry(policy, kind)
    return {
        "kind": kind,
        "severity": str(entry.get("severity", "high")),
        "summary": str(entry.get("summary", kind)),
        "default_action": str(entry.get("default_action", "stop")),
        "repair_order": repair_order or [str(item) for item in entry.get("repair_order", [entry.get("default_action", "stop")])],
        "details": details,
    }


def _manifest_validation_errors(manifest: dict[str, Any]) -> list[str]:
    schema = _load_json(RUN_MANIFEST_SCHEMA_PATH)
    try:
        import jsonschema
    except ImportError:
        errors: list[str] = []
        for key in schema.get("required", []):
            if key not in manifest:
                errors.append(f"missing top-level field `{key}`")
        for key in ("code", "model", "dataset", "run", "artifacts"):
            value = manifest.get(key)
            if not isinstance(value, dict):
                errors.append(f"field `{key}` must be an object")
                continue
            for required_key in schema.get("properties", {}).get(key, {}).get("required", []):
                if required_key not in value:
                    errors.append(f"field `{key}.{required_key}` is required")
        return errors

    validator = jsonschema.Draft202012Validator(schema)
    return [error.message for error in sorted(validator.iter_errors(manifest), key=lambda item: list(item.path))[:8]]


def _history_path(entry_root: Path) -> Path:
    return entry_root / "history.jsonl"


def _append_history(entry_root: Path, payload: dict[str, Any]) -> None:
    append_jsonl(_history_path(entry_root), payload)


def _build_command(command: list[str], env_name: str | None) -> list[str]:
    if env_name is None:
        return list(command)
    return ["conda", "run", "-n", env_name, *command]


def _attempt_environment(
    *,
    entry_id: str,
    queue_name: str,
    attempt_number: int,
    mode: str,
    history_path: Path,
) -> dict[str, str]:
    environment = dict(os.environ)
    environment["DEEPLOOP_RUNTIME_ENTRY_ID"] = entry_id
    environment["DEEPLOOP_RUNTIME_QUEUE_NAME"] = queue_name
    environment["DEEPLOOP_RUNTIME_ATTEMPT"] = str(attempt_number)
    environment["DEEPLOOP_RUNTIME_RECOVERY_MODE"] = mode
    environment["DEEPLOOP_RUNTIME_HISTORY_PATH"] = str(history_path)
    return environment


def _execute_attempt(
    *,
    entry_id: str,
    queue_name: str,
    repo_root: Path,
    entry_root: Path,
    attempt_number: int,
    mode: str,
    env_name: str | None,
    command: list[str],
) -> dict[str, Any]:
    full_command = _build_command(command, env_name)
    log_path = entry_root / f"attempt-{attempt_number:02d}-{mode}.log"
    started_at = now_utc()
    try:
        completed = subprocess.run(
            full_command,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            env=_attempt_environment(
                entry_id=entry_id,
                queue_name=queue_name,
                attempt_number=attempt_number,
                mode=mode,
                history_path=_history_path(entry_root),
            ),
        )
        stdout = completed.stdout
        stderr = completed.stderr
        returncode = completed.returncode
        exception_text = None
    except (FileNotFoundError, OSError) as exc:
        stdout = ""
        stderr = f"{type(exc).__name__}: {exc}\n"
        returncode = 127
        exception_text = str(exc)
    completed_at = now_utc()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(stdout + stderr, encoding="utf-8")
    return {
        "attempt": attempt_number,
        "mode": mode,
        "env_name": env_name,
        "command": command,
        "full_command": full_command,
        "started_at": started_at,
        "completed_at": completed_at,
        "returncode": returncode,
        "log_path": str(log_path),
        "stdout": stdout,
        "stderr": stderr,
        "exception": exception_text,
    }


def _classify_process_failure(policy: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]:
    signal_cfg = policy.get("signal_detection", {})
    combined_output = f"{attempt.get('stdout', '')}\n{attempt.get('stderr', '')}".lower()
    import_env_patterns = [str(item).lower() for item in signal_cfg.get("import_env_patterns", [])]
    if any(pattern in combined_output for pattern in import_env_patterns):
        return _failure_record(
            policy,
            "import-env-failure",
            details={
                "returncode": attempt["returncode"],
                "log_path": attempt["log_path"],
                "output_excerpt": combined_output[-500:],
            },
        )
    return _failure_record(
        policy,
        "command-failure",
        details={
            "returncode": attempt["returncode"],
            "log_path": attempt["log_path"],
            "output_excerpt": combined_output[-500:],
        },
    )


def _classify_manifest_payload(
    *,
    policy: dict[str, Any],
    manifest_path: Path,
    manifest: dict[str, Any],
    log_path: str,
) -> dict[str, Any]:
    validation_errors = _manifest_validation_errors(manifest)
    if validation_errors:
        return {
            "status": "failure",
            "failure": _failure_record(
                policy,
                "schema-mismatch",
                details={
                    "expected_manifest": str(manifest_path),
                    "validation_errors": validation_errors,
                    "log_path": log_path,
                },
            ),
        }
    assessment = assess_manifest_for_self_correction(manifest_path, manifest=manifest)
    scientific_action = assessment["decision"]["action"]
    if scientific_action != "continue":
        repair_order = ["reroute", "stop"] if scientific_action == "reroute" else ["stop"]
        return {
            "status": "failure",
            "manifest": manifest,
            "assessment": assessment,
            "failure": _failure_record(
                policy,
                "scientific-failure",
                details={
                    "expected_manifest": str(manifest_path),
                    "scientific_action": scientific_action,
                    "route_to": assessment["decision"]["route_to"],
                    "triggered_by": assessment["decision"]["triggered_by"],
                    "assessment": assessment,
                },
                repair_order=repair_order,
            ),
        }
    return {
        "status": "completed",
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "assessment": assessment,
    }


def _classify_attempt_outcome(
    *,
    policy: dict[str, Any],
    expected_manifest: Path,
    attempt: dict[str, Any],
) -> dict[str, Any]:
    if int(attempt["returncode"]) != 0:
        return {"status": "failure", "failure": _classify_process_failure(policy, attempt)}
    if not expected_manifest.exists():
        return {
            "status": "failure",
            "failure": _failure_record(
                policy,
                "missing-artifact",
                details={"expected_manifest": str(expected_manifest), "log_path": attempt["log_path"]},
            ),
        }
    try:
        manifest = _load_json(expected_manifest)
    except (json.JSONDecodeError, ValueError) as exc:
        return {
            "status": "failure",
            "failure": _failure_record(
                policy,
                "schema-mismatch",
                details={
                    "expected_manifest": str(expected_manifest),
                    "reason": f"{type(exc).__name__}: {exc}",
                    "log_path": attempt["log_path"],
                },
            ),
        }
    return _classify_manifest_payload(
        policy=policy,
        manifest_path=expected_manifest,
        manifest=manifest,
        log_path=str(attempt["log_path"]),
    )


def _repair_hints(proposal_config_path: Path | None) -> dict[str, Any]:
    hints: dict[str, Any] = {
        "configured_output_dir": None,
        "mission_id": None,
        "loop_id": None,
    }
    if proposal_config_path is None or not proposal_config_path.exists():
        return hints
    try:
        proposal = _load_yaml(proposal_config_path)
    except (OSError, ValueError, yaml.YAMLError):
        return hints
    run_cfg = proposal.get("run", {}) if isinstance(proposal.get("run"), Mapping) else {}
    configured_output_dir = run_cfg.get("output_dir")
    if configured_output_dir:
        hints["configured_output_dir"] = _resolved_path(Path(str(configured_output_dir)))
    mission_id = proposal.get("mission_id")
    if mission_id:
        hints["mission_id"] = str(mission_id)
    loop_id = run_cfg.get("loop_id")
    if loop_id:
        hints["loop_id"] = str(loop_id)
    return hints


def _artifact_search_roots(
    *,
    expected_manifest: Path,
    mission_root: Path,
    repo_root: Path,
    proposal_config_path: Path | None,
) -> list[Path]:
    hints = _repair_hints(proposal_config_path)
    configured_output_dir = hints.get("configured_output_dir")
    raw_roots = [
        configured_output_dir,
        configured_output_dir.parent if isinstance(configured_output_dir, Path) else None,
        expected_manifest.parent,
        mission_root / "runtime",
        mission_root,
        repo_root / "runtime",
    ]
    ordered: list[Path] = []
    seen: set[Path] = set()
    for raw_root in raw_roots:
        if not isinstance(raw_root, Path):
            continue
        resolved = _resolved_path(raw_root)
        if not resolved.exists() or resolved in seen:
            continue
        ordered.append(resolved)
        seen.add(resolved)
    return ordered


def _manifest_candidate_score(
    *,
    candidate_path: Path,
    manifest: dict[str, Any],
    expected_manifest: Path,
    root_index: int,
    hints: dict[str, Any],
) -> tuple[int, int, int, int, str]:
    configured_output_dir = hints.get("configured_output_dir")
    exact_output_dir = int(isinstance(configured_output_dir, Path) and candidate_path == configured_output_dir / expected_manifest.name)
    under_output_dir = int(isinstance(configured_output_dir, Path) and _is_relative_to(candidate_path, configured_output_dir))
    loop_match = int(bool(hints.get("loop_id")) and str(manifest.get("loop_id") or "") == str(hints["loop_id"]))
    mission_match = int(bool(hints.get("mission_id")) and str(manifest.get("mission_id") or "") == str(hints["mission_id"]))
    return (-exact_output_dir, -under_output_dir, -loop_match, -mission_match, f"{root_index}:{candidate_path}")


def _maybe_self_heal_manifest_path(
    *,
    policy: dict[str, Any],
    failure: dict[str, Any],
    expected_manifest: Path,
    attempt: dict[str, Any],
    mission_root: Path,
    repo_root: Path,
    proposal_config_path: Path | None,
) -> dict[str, Any] | None:
    if failure["kind"] not in {"missing-artifact", "schema-mismatch"}:
        return None
    hints = _repair_hints(proposal_config_path)
    roots = _artifact_search_roots(
        expected_manifest=expected_manifest,
        mission_root=mission_root,
        repo_root=repo_root,
        proposal_config_path=proposal_config_path,
    )
    search_cfg = policy.get("artifact_search", {}) if isinstance(policy.get("artifact_search"), Mapping) else {}
    patterns = [str(item) for item in search_cfg.get("manifest_globs", [f"**/{expected_manifest.name}"])]
    max_candidates = max(1, int(search_cfg.get("max_candidates", 24)))
    candidates: list[tuple[tuple[int, int, int, int, str], Path, dict[str, Any]]] = []
    seen: set[Path] = {_resolved_path(expected_manifest)}
    quarantined: list[str] = []
    for root_index, root in enumerate(roots):
        for pattern in patterns:
            for candidate in sorted(root.glob(pattern)):
                if not candidate.is_file():
                    continue
                resolved_candidate = _resolved_path(candidate)
                if resolved_candidate in seen:
                    continue
                seen.add(resolved_candidate)
                if not _is_relative_to(resolved_candidate, root):
                    quarantined.append(str(resolved_candidate))
                    continue
                try:
                    manifest = _load_json(resolved_candidate)
                except (OSError, json.JSONDecodeError, ValueError):
                    continue
                if _manifest_validation_errors(manifest):
                    continue
                score = _manifest_candidate_score(
                    candidate_path=resolved_candidate,
                    manifest=manifest,
                    expected_manifest=expected_manifest,
                    root_index=root_index,
                    hints=hints,
                )
                candidates.append((score, resolved_candidate, manifest))
                if len(candidates) >= max_candidates:
                    break
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break
    if not candidates:
        failure["details"]["searched_roots"] = [str(root) for root in roots]
        if quarantined:
            failure["details"]["quarantined_candidates"] = quarantined
        return None
    _, source_manifest_path, manifest = sorted(candidates, key=lambda item: item[0])[0]
    expected_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_manifest_path, expected_manifest)
    outcome = _classify_manifest_payload(
        policy=policy,
        manifest_path=expected_manifest,
        manifest=manifest,
        log_path=str(attempt["log_path"]),
    )
    if outcome["status"] != "completed":
        return None
    outcome["repair"] = {
        "mode": "normalize-path",
        "source_manifest": str(source_manifest_path),
        "target_manifest": str(expected_manifest),
    }
    return outcome


def _recovery_limits(policy: dict[str, Any], entry: dict[str, Any]) -> dict[str, int]:
    repair_cfg = entry.get("repair", {}) if isinstance(entry.get("repair"), dict) else {}
    return {
        "max_attempts": int(repair_cfg.get("max_attempts", policy.get("max_attempts", 1))),
        "max_retries": int(repair_cfg.get("max_retries", policy.get("max_retries", 0))),
        "max_resumes": int(repair_cfg.get("max_resumes", policy.get("max_resumes", 0))),
        "max_reroutes": int(repair_cfg.get("max_reroutes", policy.get("max_reroutes", 0))),
    }


def _reroute_command(entry: dict[str, Any], *, proposal_config_path: Path | None) -> tuple[list[str], str | None] | None:
    repair_cfg = entry.get("repair", {}) if isinstance(entry.get("repair"), dict) else {}
    explicit_command = repair_cfg.get("reroute_command")
    if explicit_command:
        env_name = _resolved_env_name(repair_cfg.get("reroute_env_name", entry.get("env_name")))
        return _resolve_workspace_tokens(explicit_command), env_name
    stage_id = entry.get("stage_id")
    adapter = entry.get("adapter")
    if not stage_id or not adapter or proposal_config_path is None:
        return None
    reroute_env_name = _resolved_env_name(repair_cfg.get("reroute_env_name", entry.get("env_name")))
    python_binary = "python" if reroute_env_name else sys.executable
    command = [
        python_binary,
        str(DEEPLOOP_REPO_ROOT / "scripts" / "runtime" / "run_stage_kernel.py"),
        "--stage",
        str(stage_id),
        "--config",
        str(proposal_config_path),
        "--adapter",
        str(adapter),
    ]
    for raw_path in _normalize_tokens(entry.get("pythonpath")):
        command.extend(["--pythonpath", str(resolve_workspace_path(raw_path))])
    return command, reroute_env_name


def _resume_command(entry: dict[str, Any], mode: str) -> tuple[list[str], str | None]:
    repair_cfg = entry.get("repair", {}) if isinstance(entry.get("repair"), dict) else {}
    if mode == "resume" and repair_cfg.get("resume_command"):
        command = _resolve_workspace_tokens(repair_cfg.get("resume_command"))
        env_name = _resolved_env_name(repair_cfg.get("resume_env_name", entry.get("env_name")))
        return command, env_name
    if mode == "retry" and repair_cfg.get("retry_command"):
        command = _resolve_workspace_tokens(repair_cfg.get("retry_command"))
        env_name = _resolved_env_name(repair_cfg.get("retry_env_name", entry.get("env_name")))
        return command, env_name
    return _resolve_workspace_tokens(entry.get("command")), _resolved_env_name(entry.get("env_name"))


def _select_recovery(
    *,
    failure: dict[str, Any],
    entry: dict[str, Any],
    limits: dict[str, int],
    attempts: list[dict[str, Any]],
    proposal_config_path: Path | None,
) -> dict[str, Any] | None:
    if len(attempts) >= limits["max_attempts"]:
        return None
    retries_used = sum(1 for attempt in attempts if attempt["mode"] == "retry")
    resumes_used = sum(1 for attempt in attempts if attempt["mode"] == "resume")
    reroutes_used = sum(1 for attempt in attempts if attempt["mode"] == "reroute")
    for action in failure.get("repair_order", []):
        if action == "retry" and retries_used < limits["max_retries"]:
            command, env_name = _resume_command(entry, "retry")
            return {"mode": "retry", "command": command, "env_name": env_name}
        if action == "resume" and resumes_used < limits["max_resumes"]:
            command, env_name = _resume_command(entry, "resume")
            return {"mode": "resume", "command": command, "env_name": env_name}
        if action == "reroute" and reroutes_used < limits["max_reroutes"]:
            reroute = _reroute_command(entry, proposal_config_path=proposal_config_path)
            if reroute is not None:
                command, env_name = reroute
                return {"mode": "reroute", "command": command, "env_name": env_name}
        if action == "stop":
            break
    return None


def _entry_summary_markdown(summary: dict[str, Any]) -> list[str]:
    lines = [
        f"# Runtime entry `{summary['entry_id']}`",
        "",
        f"- final_status: `{summary['final_status']}`",
        f"- recovered: `{summary['recovered']}`",
        f"- expected_manifest: `{summary['expected_manifest']}`",
        f"- attempts: `{len(summary['attempts'])}`",
    ]
    if summary.get("next_route_to"):
        lines.append(f"- next_route_to: `{summary['next_route_to']}`")
    lines.extend(["", "## Attempts", ""])
    for attempt in summary["attempts"]:
        lines.append(f"- attempt {attempt['attempt']}: `{attempt['mode']}` -> returncode `{attempt['returncode']}`")
        if attempt.get("failure"):
            lines.append(f"  - failure: `{attempt['failure']['kind']}`")
        if attempt.get("recovery_applied"):
            lines.append(f"  - recovery: `{attempt['recovery_applied']['mode']}`")
    return lines


def _queue_summary_markdown(report: dict[str, Any]) -> list[str]:
    lines = [
        "# Self-healing runtime queue",
        "",
        f"- queue_name: `{report['queue_name']}`",
        f"- mission_id: `{report['mission_id']}`",
        f"- completed_jobs: `{report['counts']['completed_jobs']}`",
        f"- blocked_jobs: `{report['counts']['blocked_jobs']}`",
        f"- warned_jobs: `{report['counts']['warned_jobs']}`",
        f"- failed_jobs: `{report['counts']['failed_jobs']}`",
        f"- recovered_jobs: `{report['counts']['recovered_jobs']}`",
        f"- rerouted_jobs: `{report['counts']['rerouted_jobs']}`",
        f"- resumed_jobs: `{report['counts']['resumed_jobs']}`",
        f"- truncated_jobs: `{report['counts']['truncated_jobs']}`",
        "",
    ]
    if report.get("truncation_warning"):
        lines += [
            f"**WARNING:** {report['truncation_warning']}",
            "",
        ]
    lines += [
        "## Entries",
        "",
    ]
    for entry in report["entries"]:
        lines.append(f"- `{entry['entry_id']}` -> `{entry['final_status']}`")
        if entry.get("sanity_verdict"):
            lines.append(f"  - sanity_verdict: `{entry['sanity_verdict']}`")
        reasons = entry.get("top_blocking_reasons")
        if isinstance(reasons, list) and reasons:
            lines.append(f"  - top_blocking_reasons: {'; '.join(str(item) for item in reasons[:3])}")
    return lines


def _update_mission_state(
    mission_state_path: Path,
    mission_state: dict[str, Any],
    *,
    report_json_path: Path,
    report_markdown_path: Path,
    counts: dict[str, int],
    entry_summaries: list[dict[str, Any]],
    policy_path: Path,
    truncated_jobs: int = 0,
) -> None:
    runtime_entries = {
        entry["entry_id"]: {
            "final_status": entry["final_status"],
            "summary_json_path": entry["summary_json_path"],
            "summary_markdown_path": entry.get("summary_markdown_path"),
            "history_path": entry["history_path"],
            "next_route_to": entry.get("next_route_to"),
            "sanity_verdict": entry.get("sanity_verdict"),
            "top_blocking_reasons": list(entry.get("top_blocking_reasons") or []),
        }
        for entry in entry_summaries
    }
    mission_state["runtime_recovery"] = {
        "generated_at": now_utc(),
        "policy_path": str(policy_path),
        "report_json_path": str(report_json_path),
        "report_markdown_path": str(report_markdown_path),
        "counts": counts,
        "entries": runtime_entries,
    }
    if counts["failed_jobs"] > 0:
        state = "runtime-failed"
        reason = f"{counts['failed_jobs']} queue job(s) exceeded bounded recovery."
    elif counts["blocked_jobs"] > 0:
        state = "runtime-blocked"
        blocked_entry = next((entry for entry in entry_summaries if entry.get("final_status") == "blocked"), None)
        if isinstance(blocked_entry, Mapping):
            reason = str(
                blocked_entry.get("top_blocking_reasons", [None])[0]
                or blocked_entry.get("final_failure", {}).get("message")
                or f"Queue blocked on {blocked_entry.get('entry_id')}"
            )
        else:
            reason = f"{counts['blocked_jobs']} queue job(s) blocked before completion."
    elif counts["rerouted_jobs"] > 0 and counts["completed_jobs"] < len(entry_summaries):
        state = "runtime-rerouted"
        reason = f"{counts['rerouted_jobs']} queue job(s) were rerouted or paused on deterministic recovery paths."
    elif counts["recovered_jobs"] > 0:
        state = "runtime-self-healed"
        reason = f"{counts['recovered_jobs']} queue job(s) recovered after retry/reroute/resume."
    elif truncated_jobs > 0:
        state = "completed-truncated"
        reason = f"Queue capped by max_jobs; {truncated_jobs} job(s) were not executed."
    else:
        state = "runtime-completed"
        reason = "Queue completed without needing recovery."
    mission_state["autonomy_status"] = {"state": state, "reason": reason}
    mission_state_path.write_text(json.dumps(mission_state, indent=2) + "\n", encoding="utf-8")


def _entry_terminal_status(failure: dict[str, Any]) -> tuple[str, str | None]:
    if failure["kind"] == "scientific-failure":
        route_to = failure["details"].get("route_to")
        if failure["details"].get("scientific_action") == "reroute":
            return "rerouted", str(route_to) if route_to else None
    return "failed", None


def _run_entry(
    *,
    config: dict[str, Any],
    policy: dict[str, Any],
    mission_state_path: Path,
    mission_state: dict[str, Any],
    queue_root: Path,
    ledger_path: Path,
    queue_name: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    entry_id = str(entry["id"])
    entry_root = queue_root / entry_id
    entry_root.mkdir(parents=True, exist_ok=True)
    expected_manifest = resolve_workspace_path(entry["expected_manifest"])
    repo_root = resolve_workspace_path(entry["repo"])
    proposal_config_path = (
        resolve_workspace_path(entry["proposal_config"])
        if isinstance(entry.get("proposal_config"), str)
        else extract_proposal_config_path(entry.get("command", []), repo_root=repo_root)
    )
    summary: dict[str, Any] = {
        "schema_version": 1,
        "entry_id": entry_id,
        "mission_id": mission_state.get("mission_id"),
        "queue_name": queue_name,
        "expected_manifest": str(expected_manifest),
        "history_path": str(_history_path(entry_root)),
        "attempts": [],
        "recovered": False,
        "final_status": "unknown",
        "next_route_to": None,
    }
    mission_root = mission_state_path.parent
    if expected_manifest.exists() and not bool(config.get("rerun_existing", False)):
        summary["final_status"] = "skipped"
        _append_history(
            entry_root,
            {"created_at": now_utc(), "event": "skip-existing", "expected_manifest": str(expected_manifest)},
        )
        append_jsonl(
            ledger_path,
            make_ledger_entry(
                kind="autoexec-skip",
                mission_id=str(mission_state["mission_id"]),
                summary=f"Skipped {entry_id} because manifest already exists",
                status="skipped",
                related_paths=[str(expected_manifest)],
            ),
        )
    elif proposal_config_path is None:
        summary["final_status"] = "blocked"
        failure = _failure_record(
            policy,
            "command-failure",
            details={"reason": "proposal-config-unresolved", "command": _normalize_tokens(entry.get("command"))},
            repair_order=["stop"],
        )
        _append_history(entry_root, {"created_at": now_utc(), "event": "blocked", "failure": failure})
        append_jsonl(
            ledger_path,
            make_ledger_entry(
                kind="autoexec-block",
                mission_id=str(mission_state["mission_id"]),
                summary=f"Blocked {entry_id} because no proposal config could be inferred from the command",
                status="blocked",
                related_paths=[str(_history_path(entry_root))],
                metadata={"command": _normalize_tokens(entry.get("command"))},
            ),
        )
    else:
        sanity_result = evaluate_research_sanity(
            proposal_config_path,
            mission_state_path=mission_state_path,
            repo_root=repo_root,
            artifact_name=entry_id,
            queue_entry_id=entry_id,
        )
        summary["sanity_verdict"] = sanity_result["verdict"]
        summary["sanity_report_json_path"] = str(sanity_result["report_json_path"])
        summary["sanity_report_markdown_path"] = str(sanity_result["report_markdown_path"])
        if sanity_result["verdict"] == "block":
            summary["final_status"] = "blocked"
            _append_history(
                entry_root,
                {
                    "created_at": now_utc(),
                    "event": "sanity-block",
                    "report_json_path": str(sanity_result["report_json_path"]),
                    "report_markdown_path": str(sanity_result["report_markdown_path"]),
                },
            )
            append_jsonl(
                ledger_path,
                make_ledger_entry(
                    kind="autoexec-block",
                    mission_id=str(mission_state["mission_id"]),
                    summary=f"Blocked {entry_id} because the research sanity gate returned block",
                    status="blocked",
                    related_paths=[str(sanity_result["report_json_path"]), str(sanity_result["report_markdown_path"])],
                    metadata={"config_path": str(proposal_config_path)},
                ),
            )
        else:
            limits = _recovery_limits(policy, entry)
            current_mode = "primary"
            current_command = _resolve_workspace_tokens(entry.get("command"))
            current_env_name = _resolved_env_name(entry.get("env_name"))
            final_failure: dict[str, Any] | None = None
            final_assessment: dict[str, Any] | None = None
            while True:
                attempt = _execute_attempt(
                    entry_id=entry_id,
                    queue_name=queue_name,
                    repo_root=repo_root,
                    entry_root=entry_root,
                    attempt_number=len(summary["attempts"]) + 1,
                    mode=current_mode,
                    env_name=current_env_name,
                    command=current_command,
                )
                append_jsonl(
                    ledger_path,
                    make_ledger_entry(
                        kind="autoexec-attempt",
                        mission_id=str(mission_state["mission_id"]),
                        summary=f"{entry_id} attempt {attempt['attempt']} ({current_mode}) exited {attempt['returncode']}",
                        status="running" if attempt["returncode"] == 0 else "recovering",
                        related_paths=[attempt["log_path"]],
                        metadata={"command": attempt["full_command"], "repo": str(repo_root)},
                    ),
                )
                outcome = _classify_attempt_outcome(policy=policy, expected_manifest=expected_manifest, attempt=attempt)
                attempt_record = {key: attempt[key] for key in ("attempt", "mode", "env_name", "command", "full_command", "started_at", "completed_at", "returncode", "log_path")}
                if outcome["status"] != "completed":
                    repaired_outcome = _maybe_self_heal_manifest_path(
                        policy=policy,
                        failure=outcome["failure"],
                        expected_manifest=expected_manifest,
                        attempt=attempt,
                        mission_root=mission_root,
                        repo_root=repo_root,
                        proposal_config_path=proposal_config_path,
                    )
                    if repaired_outcome is not None:
                        outcome = repaired_outcome
                if outcome["status"] == "completed":
                    attempt_record["assessment"] = outcome["assessment"]
                    if "repair" in outcome:
                        attempt_record["recovery_applied"] = outcome["repair"]
                        summary["recovered"] = True
                    summary["attempts"].append(attempt_record)
                    if "repair" in outcome:
                        _append_history(
                            entry_root,
                            {
                                "created_at": now_utc(),
                                "event": "attempt-repaired",
                                "attempt": attempt_record["attempt"],
                                "mode": attempt_record["mode"],
                                "recovery_applied": outcome["repair"],
                            },
                        )
                    summary["final_status"] = "completed"
                    summary["manifest_path"] = str(outcome.get("manifest_path", expected_manifest))
                    summary["assessment"] = outcome["assessment"]
                    final_assessment = outcome["assessment"]
                    break
                failure = outcome["failure"]
                attempt_record["failure"] = failure
                recovery = _select_recovery(
                    failure=failure,
                    entry=entry,
                    limits=limits,
                    attempts=summary["attempts"] + [attempt_record],
                    proposal_config_path=proposal_config_path,
                )
                if recovery is not None:
                    attempt_record["recovery_applied"] = recovery
                    summary["recovered"] = True
                summary["attempts"].append(attempt_record)
                _append_history(
                    entry_root,
                    {
                        "created_at": now_utc(),
                        "event": "attempt-failure",
                        "attempt": attempt_record["attempt"],
                        "mode": attempt_record["mode"],
                        "failure": failure,
                        "recovery_applied": attempt_record.get("recovery_applied"),
                    },
                )
                if recovery is None:
                    final_failure = failure
                    summary["final_status"], summary["next_route_to"] = _entry_terminal_status(failure)
                    if "assessment" in outcome:
                        summary["assessment"] = outcome["assessment"]
                        final_assessment = outcome["assessment"]
                    break
                current_mode = str(recovery["mode"])
                current_command = _normalize_tokens(recovery["command"])
                current_env_name = _resolved_env_name(recovery["env_name"])
            final_status = summary["final_status"]
            related_paths = [str(_history_path(entry_root))]
            if "manifest_path" in summary:
                related_paths.append(summary["manifest_path"])
            if final_assessment is not None:
                summary["final_decision"] = final_assessment["decision"]
            if final_failure is not None:
                summary["final_failure"] = final_failure
            append_jsonl(
                ledger_path,
                make_ledger_entry(
                    kind="autoexec-finish",
                    mission_id=str(mission_state["mission_id"]),
                    summary=f"Finished {entry_id} with status {final_status}",
                    status=final_status,
                    related_paths=related_paths,
                    metadata={
                        "attempts": len(summary["attempts"]),
                        "recovered": summary["recovered"],
                        "next_route_to": summary.get("next_route_to"),
                    },
                ),
            )
    summary_json_path = entry_root / "summary.json"
    summary_markdown_path = entry_root / "summary.md"
    _write_json(summary_json_path, summary)
    _write_markdown(summary_markdown_path, _entry_summary_markdown(summary))
    summary["summary_json_path"] = str(summary_json_path)
    summary["summary_markdown_path"] = str(summary_markdown_path)
    return summary


def run_self_healing_queue(config_path: Path, *, policy_path: Path | None = None) -> dict[str, Any]:
    config = _load_yaml(Path(config_path).resolve())
    resolved_policy_path = resolve_workspace_path(config.get("runtime_policy") or policy_path or DEFAULT_POLICY_PATH)
    policy = _load_yaml(resolved_policy_path)
    mission_state_path = resolve_workspace_path(config["mission_state"])
    mission_state = _load_json(mission_state_path)
    mission_root = mission_state_path.parent
    ledger_path = mission_root / "ledger.jsonl"
    queue_name = str(config.get("queue_name", Path(config_path).stem))
    queue_root = mission_root / "runtime" / str(policy.get("artifact_dir_name", "self_healing_runtime")) / queue_name
    queue_root.mkdir(parents=True, exist_ok=True)

    counts = {
        "completed_jobs": 0,
        "blocked_jobs": 0,
        "warned_jobs": 0,
        "failed_jobs": 0,
        "recovered_jobs": 0,
        "rerouted_jobs": 0,
        "resumed_jobs": 0,
        "truncated_jobs": 0,
    }
    entry_summaries: list[dict[str, Any]] = []
    entries = config.get("entries", [])
    max_jobs = int(config.get("max_jobs", 0) or len(entries))
    truncated_jobs = max(0, len(entries) - max_jobs)
    counts["truncated_jobs"] = truncated_jobs
    truncation_warning: str | None = None
    if truncated_jobs > 0:
        truncation_warning = (
            f"WARNING: queue-runtime: max_jobs={max_jobs} cap truncated {truncated_jobs} job(s) "
            f"({len(entries)} total entries). Only the first {max_jobs} job(s) were executed."
        )
        print(truncation_warning, file=sys.stderr)
        append_jsonl(
            ledger_path,
            make_ledger_entry(
                kind="autonomy-gate-warning",
                mission_id=str(mission_state.get("mission_id", "")),
                summary=truncation_warning,
                status="truncated",
                related_paths=[],
                metadata={"max_jobs": max_jobs, "total_entries": len(entries), "truncated_jobs": truncated_jobs},
            ),
        )
    for entry in entries[:max_jobs]:
        summary = _run_entry(
            config=config,
            policy=policy,
            mission_state_path=mission_state_path,
            mission_state=mission_state,
            queue_root=queue_root,
            ledger_path=ledger_path,
            queue_name=queue_name,
            entry=entry,
        )
        entry_summaries.append(summary)
        final_status = summary["final_status"]
        if final_status == "completed":
            counts["completed_jobs"] += 1
        elif final_status == "blocked":
            counts["blocked_jobs"] += 1
        elif final_status == "failed":
            counts["failed_jobs"] += 1
        if summary.get("sanity_verdict") == "warn":
            counts["warned_jobs"] += 1
        if summary["recovered"] and final_status == "completed":
            counts["recovered_jobs"] += 1
        if final_status == "rerouted" or any(attempt["mode"] == "reroute" for attempt in summary["attempts"]):
            counts["rerouted_jobs"] += 1
        counts["resumed_jobs"] += sum(1 for attempt in summary["attempts"] if attempt["mode"] == "resume")

    blocked_entries: list[dict[str, Any]] = []
    for summary in entry_summaries:
        if str(summary.get("final_status")) != "blocked":
            continue
        blocking_reasons: list[str] = []
        sanity_report_path = summary.get("sanity_report_json_path")
        if isinstance(sanity_report_path, str) and sanity_report_path:
            report_path = Path(sanity_report_path)
            if report_path.exists():
                report = _load_json(report_path)
                reasons = report.get("reasons")
                if isinstance(reasons, list):
                    for reason in reasons:
                        if not isinstance(reason, Mapping):
                            continue
                        if str(reason.get("severity") or "") != "block":
                            continue
                        message = str(reason.get("message") or "").strip()
                        if message:
                            blocking_reasons.append(message)
        final_failure = summary.get("final_failure") if isinstance(summary.get("final_failure"), Mapping) else {}
        if not blocking_reasons and final_failure:
            message = str(final_failure.get("message") or final_failure.get("kind") or "").strip()
            if message:
                blocking_reasons.append(message)
        summary["top_blocking_reasons"] = blocking_reasons[:3]
        blocked_entries.append(
            {
                "entry_id": summary["entry_id"],
                "queue_name": queue_name,
                "summary_json_path": summary.get("summary_json_path"),
                "summary_markdown_path": summary.get("summary_markdown_path"),
                "sanity_verdict": summary.get("sanity_verdict"),
                "top_blocking_reasons": blocking_reasons[:3],
            }
        )

    report = {
        "schema_version": 1,
        "generated_at": now_utc(),
        "queue_name": queue_name,
        "mission_id": mission_state.get("mission_id"),
        "policy_path": str(resolved_policy_path),
        "queue_config_path": str(Path(config_path).resolve()),
        "counts": counts,
        "truncation_warning": truncation_warning,
        "entries": [
            {
                "entry_id": entry["entry_id"],
                "final_status": entry["final_status"],
                "summary_json_path": entry["summary_json_path"],
                "summary_markdown_path": entry["summary_markdown_path"],
                "sanity_verdict": entry.get("sanity_verdict"),
                "top_blocking_reasons": list(entry.get("top_blocking_reasons") or []),
            }
            for entry in entry_summaries
        ],
        "blocked_entries": blocked_entries,
    }
    report_json_path = queue_root / "queue_summary.json"
    report_markdown_path = queue_root / "queue_summary.md"
    _write_json(report_json_path, report)
    _write_markdown(report_markdown_path, _queue_summary_markdown(report))
    _update_mission_state(
        mission_state_path,
        mission_state,
        report_json_path=report_json_path,
        report_markdown_path=report_markdown_path,
        counts=counts,
        entry_summaries=entry_summaries,
        policy_path=resolved_policy_path,
        truncated_jobs=truncated_jobs,
    )
    append_jsonl(
        ledger_path,
        make_ledger_entry(
            kind="autoexec-queue",
            mission_id=str(mission_state["mission_id"]),
            summary=f"Processed queue {queue_name} with {counts['completed_jobs']} completed job(s)",
            status="completed" if counts["failed_jobs"] == 0 else "failed",
            related_paths=[str(report_json_path), str(report_markdown_path)],
            metadata=counts,
        ),
    )
    return {
        **counts,
        "queue_name": queue_name,
        "truncation_warning": truncation_warning,
        "blocked_entries": blocked_entries,
        "ledger_path": ledger_path,
        "runtime_report_path": report_json_path,
        "runtime_report_markdown_path": report_markdown_path,
    }
