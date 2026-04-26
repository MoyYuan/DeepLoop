from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.paths import LAUNCHES_DIR
from deeploop.core.paths import REPO_ROOT
from deeploop.core.structured_io import load_json_object, load_jsonl_objects, write_json_object
from deeploop.mission.mission_monitor import build_mission_snapshot, render_mission_snapshot
from deeploop.mission.mission_state import load_mission_state
from deeploop.cli.run_project import _add_run_args, _run_project
from deeploop.cli.init_mission import _add_init_args, _init_mission
from deeploop.cli.package_mission import _add_package_args, _package_mission
from deeploop.cli.analyze import _add_analyze_args, _analyze
from deeploop.runtime.recursive_agent_runtime import analyze_budget

_RUN_MISSION_SCRIPT = REPO_ROOT / "scripts" / "mission" / "run_mission.py"
_MANAGE_MISSION_SCRIPT = REPO_ROOT / "scripts" / "mission" / "manage_mission.py"
_INVOKE_PROVIDER_PROMPT_SCRIPT = REPO_ROOT / "scripts" / "runtime" / "invoke_provider_prompt.py"


def _load_json(path: Path) -> dict[str, Any]:
    return load_json_object(path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return load_jsonl_objects(path, missing_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json_object(path, payload)


def _resolve_existing_path(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    return path


def _resolve_optional_path(raw: str | None) -> Path | None:
    if raw is None:
        return None
    return Path(raw).expanduser().resolve()


def _pid_is_running(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _load_launch_metadata(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _load_json(path)


def _default_launch_paths(
    mission_state_path: Path,
    mission_state: dict[str, Any],
    *,
    launch_metadata_path: Path | None,
    log_path: Path | None,
) -> tuple[Path, Path, Path]:
    mission_id = str(mission_state.get("mission_id") or mission_state_path.parent.name)
    if launch_metadata_path is not None:
        launch_root = launch_metadata_path.parent
    elif log_path is not None:
        launch_root = log_path.parent
    else:
        launch_root = LAUNCHES_DIR / mission_id
    resolved_metadata_path = launch_metadata_path or (launch_root / "launch.json")
    resolved_log_path = log_path or (launch_root / "launch.log")
    return launch_root, resolved_metadata_path, resolved_log_path


def _management_command(subcommand: str, mission_state_path: Path, *extra: str) -> list[str]:
    return [
        sys.executable,
        str(_MANAGE_MISSION_SCRIPT),
        subcommand,
        "--mission-state",
        str(mission_state_path),
        *extra,
    ]


def _management_command_text(subcommand: str, mission_state_path: Path, *extra: str) -> str:
    return shlex.join(
        [
            "python",
            "scripts/mission/manage_mission.py",
            subcommand,
            "--mission-state",
            str(mission_state_path),
            *extra,
        ]
    )


def _start_launch(
    *,
    mission_state_path: Path,
    max_iterations: int | None,
    runtime_root: Path | None,
    launch_metadata_path: Path | None,
    log_path: Path | None,
    replace_running: bool,
    launch_reason: str,
) -> dict[str, Any]:
    mission_state = load_mission_state(mission_state_path)
    launch_root, metadata_path, resolved_log_path = _default_launch_paths(
        mission_state_path,
        mission_state,
        launch_metadata_path=launch_metadata_path,
        log_path=log_path,
    )
    existing = _load_launch_metadata(metadata_path)
    if existing and not replace_running and _pid_is_running(existing.get("pid")):
        raise RuntimeError(
            f"DeepLoop is already running with pid {existing['pid']}. Use `stop` first or pass --replace-running."
        )

    runtime_launcher = mission_state.get("runtime_launcher") if isinstance(mission_state.get("runtime_launcher"), dict) else {}
    launch_env_name = str(runtime_launcher.get("env_name") or "").strip()
    resolved_max_iterations = int(runtime_launcher.get("max_iterations", 12) or 12) if max_iterations is None else int(max_iterations)
    if resolved_max_iterations <= 0:
        raise ValueError("max_iterations must be positive.")
    command = []
    if launch_env_name:
        command.extend(["conda", "run", "-n", launch_env_name, "python"])
    else:
        command.append(sys.executable)
    command.extend(
        [
            str(_RUN_MISSION_SCRIPT),
            "--mission-state",
            str(mission_state_path),
            "--max-iterations",
            str(resolved_max_iterations),
        ]
    )
    if runtime_root is not None:
        command.extend(["--runtime-root", str(runtime_root)])

    resolved_log_path.parent.mkdir(parents=True, exist_ok=True)
    launch_root.mkdir(parents=True, exist_ok=True)
    launched_at = now_utc()
    with resolved_log_path.open("a", encoding="utf-8") as log_handle:
        log_handle.write(f"[{launched_at}] deeploop {launch_reason} {shlex.join(command)}\n")
        log_handle.flush()
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    payload = {
        "schema_version": 1,
        "launch_reason": launch_reason,
        "launched_at": launched_at,
        "started_at": launched_at,
        "pid": process.pid,
        "process_group_id": process.pid,
        "mission_id": mission_state.get("mission_id"),
        "mission_state_path": str(mission_state_path),
        "max_iterations": resolved_max_iterations,
        "mode": mission_state.get("mode") or (mission_state.get("outer_loop") or {}).get("mode") or "sandboxed-yolo",
        "runtime_root": str(runtime_root) if runtime_root is not None else None,
        "log_path": str(resolved_log_path),
        "launch_root": str(launch_root),
        "cwd": str(REPO_ROOT),
        "command": command,
        "status_command": _management_command("status", mission_state_path),
        "logs_command": _management_command("logs", mission_state_path),
        "decisions_command": _management_command("decisions", mission_state_path),
        "inbox_command": _management_command("inbox", mission_state_path),
        "stop_command": _management_command("stop", mission_state_path),
        "resume_command": _management_command("resume", mission_state_path),
    }
    _write_json(metadata_path, payload)
    payload["launch_metadata_path"] = str(metadata_path)
    return payload


def _render_launch_summary(payload: dict[str, Any], *, launch_reason: str) -> str:
    mission_state_path = payload["mission_state_path"]
    verb = "started" if launch_reason == "start" else "resumed"
    mode = str(payload.get("mode") or "sandboxed-yolo")
    title = "# DeepLoop autopilot " + verb if mode == "sandboxed-yolo" else f"# DeepLoop {mode} {verb}"
    lines = [
        title,
        "",
        f"- mission_id: `{payload.get('mission_id')}`",
        f"- operating_mode: `{mode}`",
        f"- max_iterations: `{payload.get('max_iterations')}`",
        f"- operator_posture: {_mode_summary(mode)}",
        f"- pid: `{payload.get('pid')}`",
        f"- log_path: `{payload.get('log_path')}`",
        f"- launch_metadata_path: `{payload.get('launch_metadata_path')}`",
    ]
    resume_context = payload.get("resume_context")
    if launch_reason == "resume" and isinstance(resume_context, dict):
        lines.extend(["", "## Resume handoff", ""])
        if resume_context.get("request_id"):
            lines.append(f"- operator_request: `{resume_context.get('request_id')}`")
        if resume_context.get("blocker"):
            lines.append(f"- blocker: {resume_context.get('blocker')}")
        if resume_context.get("recommendation"):
            lines.append(f"- recommendation: {resume_context.get('recommendation')}")
        operator_response = (
            resume_context.get("operator_response")
            if isinstance(resume_context.get("operator_response"), dict)
            else None
        )
        if operator_response is not None:
            lines.append(
                f"- operator_feedback: `{operator_response.get('action')}` at `{operator_response.get('recorded_at')}`"
            )
            if operator_response.get("note"):
                lines.append(f"- operator_note: {operator_response.get('note')}")
        else:
            lines.append("- operator_feedback: none recorded; resume only after the blocker is addressed.")
    lines.extend(
        [
            "",
            "## Next commands",
            "",
            f"- status: `python scripts/mission/manage_mission.py status --mission-state {mission_state_path}`",
            f"- logs: `python scripts/mission/manage_mission.py logs --mission-state {mission_state_path}`",
            f"- decisions: `python scripts/mission/manage_mission.py decisions --mission-state {mission_state_path}`",
            f"- inbox: `python scripts/mission/manage_mission.py inbox --mission-state {mission_state_path}`",
            f"- stop: `python scripts/mission/manage_mission.py stop --mission-state {mission_state_path}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_exact_next_commands(console: dict[str, Any]) -> list[str]:
    lines = ["## Exact next commands", ""]
    commands = console.get("next_commands")
    if isinstance(commands, list) and commands:
        for index, entry in enumerate(commands, start=1):
            if not isinstance(entry, dict):
                continue
            lines.append(f"{index}. `{entry.get('command')}`")
            if entry.get("description"):
                lines.append(f"   - {entry.get('description')}")
        return lines
    lines.append("No management commands are surfaced right now.")
    return lines


def _render_console_overview(console: dict[str, Any], *, heading: str) -> list[str]:
    lines = [
        heading,
        "",
        f"- operator_summary: {console.get('headline')}",
        f"- is_running: `{'yes' if console.get('is_running') else 'no'}`",
        f"- lifecycle_state: `{console.get('lifecycle_state')}`",
        f"- operator_state: `{console.get('operator_state')}`",
        f"- attention_level: `{console.get('attention_level')}`",
        f"- next_step_owner: `{console.get('next_step_owner')}`",
        f"- resume_policy: `{console.get('resume_policy')}`",
        f"- gate_class: `{console.get('gate_class')}`",
        f"- active_summary: {console.get('summary')}",
        f"- state_reason: {console.get('state_reason')}",
        f"- recommendation: {console.get('recommendation')}",
        f"- continue: {console.get('continue_summary')}",
    ]
    if console.get("gate_detail"):
        lines.append(f"- gate_detail: `{console.get('gate_detail')}`")
    if console.get("blocked_on"):
        lines.append(f"- blocked_on: {console.get('blocked_on')}")
    if console.get("focus_action_id"):
        lines.append(f"- focus_action: `{console.get('focus_action_id')}`")
    if console.get("focus_executor_id"):
        lines.append(f"- focus_executor: `{console.get('focus_executor_id')}`")
    if console.get("request_id"):
        lines.append(f"- active_request: `{console.get('request_id')}`")
    operator_response = console.get("operator_response") if isinstance(console.get("operator_response"), dict) else None
    if operator_response is not None:
        lines.append(
            f"- operator_feedback: `{operator_response.get('action')}` recorded at `{operator_response.get('recorded_at')}`"
        )
        if operator_response.get("note"):
            lines.append(f"- operator_feedback_note: {operator_response.get('note')}")
    return lines


def _resume_context(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    inbox = snapshot.get("operator_inbox", {}) if isinstance(snapshot.get("operator_inbox"), dict) else {}
    current_request = inbox.get("current_request") if isinstance(inbox.get("current_request"), dict) else None
    if current_request is None:
        return None
    blocker = current_request.get("blocker", {}) if isinstance(current_request.get("blocker"), dict) else {}
    recommendation = (
        current_request.get("recommendation") if isinstance(current_request.get("recommendation"), dict) else {}
    )
    operator_response = (
        current_request.get("operator_response")
        if isinstance(current_request.get("operator_response"), dict)
        else None
    )
    return {
        "request_id": current_request.get("request_id"),
        "blocker": f"`{blocker.get('kind')}` `{blocker.get('risk_class')}`",
        "recommendation": recommendation.get("summary"),
        "operator_response": operator_response,
    }


def _record_operator_feedback(snapshot: dict[str, Any], *, action: str, note: str | None) -> dict[str, Any]:
    inbox = snapshot.get("operator_inbox", {}) if isinstance(snapshot.get("operator_inbox"), dict) else {}
    current_request = inbox.get("current_request") if isinstance(inbox.get("current_request"), dict) else None
    if current_request is None:
        raise RuntimeError("No open operator request is active right now. Use `status` or `inbox` first.")

    mission_state_path = Path(snapshot["artifacts"]["mission_state_path"]).expanduser().resolve()
    current_request_path = Path(inbox["current_operator_request_path"]).expanduser().resolve()
    ledger_path = Path(snapshot["artifacts"]["ledger_path"]).expanduser().resolve()
    recorded_at = now_utc()
    command = _management_command_text(action, mission_state_path, "--note", note or "<note>")
    updated_request = dict(current_request)
    updated_request["operator_response"] = {
        "action": action,
        "recorded_at": recorded_at,
        "note": note,
        "command": command,
    }
    _write_json(current_request_path, updated_request)
    append_jsonl(
        ledger_path,
        make_ledger_entry(
            kind="operator-feedback",
            mission_id=str(snapshot["mission"].get("mission_id") or ""),
            summary=f"Operator recorded `{action}` for `{current_request.get('request_id')}`.",
            status="recorded",
            related_paths=[str(mission_state_path), str(current_request_path), str(ledger_path)],
            metadata={
                "request_id": current_request.get("request_id"),
                "action": action,
                "note": note,
                "command": command,
            },
        ),
    )
    return updated_request


def _render_operator_feedback_summary(
    snapshot: dict[str, Any],
    *,
    action: str,
    note: str | None,
    updated_request: dict[str, Any],
) -> str:
    mission_state_path = Path(snapshot["artifacts"]["mission_state_path"]).expanduser().resolve()
    console = snapshot.get("operator_console", {}) if isinstance(snapshot.get("operator_console"), dict) else {}
    blocker = updated_request.get("blocker", {}) if isinstance(updated_request.get("blocker"), dict) else {}
    recommendation = (
        updated_request.get("recommendation") if isinstance(updated_request.get("recommendation"), dict) else {}
    )
    action_summary = (
        "retry the current in-scope path once the fix is in place"
        if action == "retry"
        else "resume on a smaller or alternate in-scope path after the reroute change"
    )
    lines = [
        "# DeepLoop operator decision recorded",
        "",
        f"- request_id: `{updated_request.get('request_id')}`",
        f"- chosen_action: `{action}`",
        f"- blocker: `{blocker.get('kind')}` `{blocker.get('risk_class')}`",
        f"- action_summary: {action_summary}",
        f"- recommendation: {recommendation.get('summary')}",
    ]
    if note:
        lines.append(f"- operator_note: {note}")
    lines.append("")
    lines.extend(_render_console_overview(console, heading="## Mission handoff"))
    lines.append("")
    lines.extend(_render_exact_next_commands(console))
    lines.extend(
        [
            "",
            "## Suggested continue command",
            "",
            f"- `python scripts/mission/manage_mission.py resume --mission-state {mission_state_path}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_log_view(snapshot: dict[str, Any]) -> str:
    artifacts = snapshot.get("artifacts", {})
    launch = snapshot.get("launch")
    log_tail = snapshot.get("log_tail", [])
    lines = ["# DeepLoop mission logs", ""]
    if isinstance(launch, dict):
        lines.extend(
            [
                f"- pid: `{launch.get('pid')}`",
                f"- process_status: `{launch.get('process_status')}`",
                f"- log_path: `{launch.get('log_path')}`",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "- detached_process: unavailable",
                f"- launch_metadata_path: `{artifacts.get('launch_metadata_path')}`",
                "",
            ]
        )

    if log_tail:
        lines.extend(["```text", *log_tail, "```"])
    else:
        lines.append("No detached mission log lines are available yet.")
    return "\n".join(lines) + "\n"


def _render_decisions(entries: list[dict[str, Any]], *, decision_log_path: Path) -> str:
    lines = ["# DeepLoop mission decisions", "", f"- decision_log_path: `{decision_log_path}`", ""]
    if not entries:
        lines.append("No decisions recorded yet.")
        return "\n".join(lines) + "\n"

    for entry in entries:
        authority = entry.get("authority") if isinstance(entry.get("authority"), dict) else {}
        result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
        selected_actions = ", ".join(f"`{item}`" for item in entry.get("selected_action_ids") or []) or "none"
        selected_branches = ", ".join(f"`{item}`" for item in entry.get("selected_branch_ids") or []) or "none"
        lines.extend(
            [
                f"## `{entry.get('decision_id')}`",
                "",
                f"- recorded_at: `{result.get('recorded_at') or 'unknown'}`",
                f"- phase: `{entry.get('phase') or 'unknown'}`",
                f"- decision_type: `{entry.get('decision_type') or 'unknown'}`",
                f"- status: `{result.get('status') or 'unknown'}`",
                f"- summary: {entry.get('summary') or 'n/a'}",
                f"- selected_actions: {selected_actions}",
                f"- selected_branches: {selected_branches}",
                f"- approval: `{authority.get('approval_state') or 'unknown'}`",
            ]
        )
        notes = entry.get("notes")
        if isinstance(notes, list) and notes:
            lines.append(f"- notes: {'; '.join(str(note) for note in notes[:3])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _mode_summary(mode: str) -> str:
    normalized = str(mode or "").strip()
    if normalized == "sandboxed-yolo":
        return "default autopilot; soft gates recover first and only true safety or authority boundaries open the inbox."
    if normalized == "managed":
        return "managed autonomy with broader permissions and intervention hooks."
    if normalized == "human-directed":
        return "human-directed control; the operator stays in the loop step by step."
    return "autonomy posture unavailable."


def _triage_command_text(mission_state_path: Path, *extra: str) -> str:
    return _management_command_text("triage", mission_state_path, *extra)


def _triage_request_details(request: dict[str, Any], snapshot: dict[str, Any]) -> tuple[Path, list[dict[str, Any]]] | None:
    context = request.get("context") if isinstance(request.get("context"), dict) else {}
    blocker = request.get("blocker") if isinstance(request.get("blocker"), dict) else {}
    blocker_details = blocker.get("details") if isinstance(blocker.get("details"), dict) else {}
    raw_blocked_entries = blocker_details.get("blocked_entries")
    blocked_entries = [dict(item) for item in raw_blocked_entries if isinstance(item, dict)] if isinstance(raw_blocked_entries, list) else []
    if not blocked_entries:
        return None
    mission_state_text = str(
        context.get("mission_state_path")
        or snapshot.get("artifacts", {}).get("mission_state_path")
        or ""
    ).strip()
    if not mission_state_text:
        return None
    mission_state_path = Path(mission_state_text).expanduser()
    outer_loop = snapshot.get("outer_loop") if isinstance(snapshot.get("outer_loop"), dict) else {}
    intervention_profile = str(outer_loop.get("intervention_profile") or "")
    mode = str(context.get("mode") or snapshot.get("mission", {}).get("mode") or "")
    if intervention_profile != "hook-enabled" and mode != "managed":
        return None
    return mission_state_path.resolve(), blocked_entries


def _build_triage_prompt(
    *,
    snapshot: dict[str, Any],
    mission_state: dict[str, Any],
    request: dict[str, Any],
    blocked_entries: list[dict[str, Any]],
    result_json_path: Path,
) -> str:
    mission = snapshot.get("mission") if isinstance(snapshot.get("mission"), dict) else {}
    console = snapshot.get("operator_console") if isinstance(snapshot.get("operator_console"), dict) else {}
    context = request.get("context") if isinstance(request.get("context"), dict) else {}
    blocker = request.get("blocker") if isinstance(request.get("blocker"), dict) else {}
    recommendation = request.get("recommendation") if isinstance(request.get("recommendation"), dict) else {}
    ledger_path = Path(snapshot["artifacts"]["ledger_path"]).expanduser().resolve()
    recent_ledger = _load_jsonl(ledger_path)[-6:]

    lines = [
        "# DeepLoop bounded operator triage",
        "",
        "You are running a bounded review hook for a currently blocked DeepLoop mission.",
        "Do not mutate mission state, queue files, or operator requests. Diagnose only and recommend the smallest safe next step.",
        "",
        "## Mission",
        "",
        f"- mission_id: `{mission.get('mission_id') or mission_state.get('mission_id')}`",
        f"- title: {mission.get('title') or mission_state.get('title') or 'n/a'}",
        f"- mode: `{context.get('mode') or mission_state.get('mode') or 'unknown'}`",
        f"- current_phase: `{mission.get('current_phase') or mission_state.get('current_phase') or 'unknown'}`",
        f"- next_phase: `{mission.get('next_phase') or mission_state.get('next_phase') or 'unknown'}`",
        f"- operator_state: `{console.get('operator_state') or 'unknown'}`",
        "",
        "## Current operator request",
        "",
        f"- request_id: `{request.get('request_id')}`",
        f"- summary: {request.get('summary')}",
        f"- blocker_kind: `{blocker.get('kind')}`",
        f"- blocker_reason: {blocker.get('reason')}",
        f"- recommendation: {recommendation.get('summary') or 'n/a'}",
        "",
        "## Blocked queue entries",
        "",
    ]
    for entry in blocked_entries[:3]:
        lines.extend(
            [
                f"- queue: `{entry.get('queue_name')}` entry: `{entry.get('entry_id')}`",
                f"  - sanity_verdict: `{entry.get('sanity_verdict') or 'n/a'}`",
                f"  - summary_json_path: `{entry.get('summary_json_path') or 'n/a'}`",
                f"  - summary_markdown_path: `{entry.get('summary_markdown_path') or 'n/a'}`",
            ]
        )
        reasons = entry.get("top_blocking_reasons")
        if isinstance(reasons, list) and reasons:
            for reason in reasons[:3]:
                lines.append(f"  - reason: {reason}")
    lines.extend(
        [
            "",
            "## Recent ledger",
            "",
        ]
    )
    if recent_ledger:
        for item in recent_ledger:
            lines.append(
                f"- `{item.get('recorded_at') or item.get('timestamp') or 'unknown'}` `{item.get('kind') or 'unknown'}` `{item.get('status') or 'unknown'}`: {item.get('summary') or 'n/a'}"
            )
    else:
        lines.append("- No recent ledger entries were available.")
    lines.extend(
        [
            "",
            "## Required output",
            "",
            f"Write JSON to `{result_json_path}` with this exact top-level shape:",
            "```json",
            "{",
            '  "status": "completed" | "blocked" | "failed",',
            '  "summary": "short operator-facing diagnosis",',
            '  "recommended_operator_action": "retry" | "reroute" | "inspect" | "escalate",',
            '  "recommended_resume_action": "one sentence on what to do before resume",',
            '  "findings": ["specific finding 1", "specific finding 2"],',
            '  "evidence_paths": ["relevant/path/one", "relevant/path/two"],',
            '  "notes": ["bounded caution or scope note"]',
            "}",
            "```",
            "",
            "Only recommend actions that stay within the current mission scope and safety posture unless the evidence truly requires escalation.",
        ]
    )
    return "\n".join(lines) + "\n"


def _normalized_triage_result(payload: dict[str, Any]) -> dict[str, Any]:
    status_aliases = {"complete": "completed", "completed": "completed", "blocked": "blocked", "failed": "failed"}
    status = status_aliases.get(str(payload.get("status") or "").strip().lower(), "")
    summary = str(payload.get("summary") or "").strip()
    if not status:
        raise ValueError("triage result must include status `completed`, `blocked`, or `failed`.")
    if not summary:
        raise ValueError("triage result must include a non-empty summary.")
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
    evidence_paths = payload.get("evidence_paths") if isinstance(payload.get("evidence_paths"), list) else []
    notes = payload.get("notes") if isinstance(payload.get("notes"), list) else []
    return {
        "status": status,
        "summary": summary,
        "recommended_operator_action": str(payload.get("recommended_operator_action") or "").strip() or None,
        "recommended_resume_action": str(payload.get("recommended_resume_action") or "").strip() or None,
        "findings": [str(item) for item in findings if str(item).strip()],
        "evidence_paths": [str(item) for item in evidence_paths if str(item).strip()],
        "notes": [str(item) for item in notes if str(item).strip()],
    }


def _render_triage_summary(summary: dict[str, Any]) -> str:
    result = summary.get("result") if isinstance(summary.get("result"), dict) else {}
    lines = [
        "# DeepLoop bounded triage",
        "",
        f"- request_id: `{summary.get('request_id')}`",
        f"- status: `{result.get('status') or 'failed'}`",
        f"- summary: {result.get('summary') or 'n/a'}",
        f"- prompt_path: `{summary.get('prompt_path')}`",
        f"- result_json_path: `{summary.get('result_json_path')}`",
        f"- log_path: `{summary.get('log_path')}`",
        f"- report_json_path: `{summary.get('report_json_path')}`",
    ]
    if result.get("recommended_operator_action"):
        lines.append(f"- recommended_operator_action: `{result.get('recommended_operator_action')}`")
    if result.get("recommended_resume_action"):
        lines.append(f"- recommended_resume_action: {result.get('recommended_resume_action')}")
    findings = result.get("findings")
    if isinstance(findings, list) and findings:
        lines.append(f"- findings: {'; '.join(str(item) for item in findings[:4])}")
    evidence_paths = result.get("evidence_paths")
    if isinstance(evidence_paths, list) and evidence_paths:
        lines.append(f"- evidence_paths: {'; '.join(str(item) for item in evidence_paths[:4])}")
    notes = result.get("notes")
    if isinstance(notes, list) and notes:
        lines.append(f"- notes: {'; '.join(str(item) for item in notes[:4])}")
    return "\n".join(lines) + "\n"


def _watch_signature(snapshot: dict[str, Any]) -> tuple[str, ...]:
    mission = snapshot.get("mission") if isinstance(snapshot.get("mission"), dict) else {}
    console = snapshot.get("operator_console") if isinstance(snapshot.get("operator_console"), dict) else {}
    return (
        str(mission.get("status") or ""),
        str(console.get("operator_state") or ""),
        str(console.get("attention_level") or ""),
        str(console.get("process_status") or ""),
        str(console.get("request_id") or ""),
        str(console.get("summary") or ""),
        str(console.get("focus_action_id") or ""),
        str(console.get("focus_executor_id") or ""),
    )


def _watch_event(
    snapshot: dict[str, Any],
    *,
    poll: int,
    previous_signature: tuple[str, ...] | None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    mission = snapshot.get("mission") if isinstance(snapshot.get("mission"), dict) else {}
    console = snapshot.get("operator_console") if isinstance(snapshot.get("operator_console"), dict) else {}
    signature = _watch_signature(snapshot)
    mission_status = str(mission.get("status") or "unknown")
    process_status = str(console.get("process_status") or "unknown")
    attention_level = str(console.get("attention_level") or "unknown")
    operator_state = str(console.get("operator_state") or "unknown")
    alert_level = (
        "alarm"
        if attention_level == "action-required"
        or mission_status in {"blocked", "failed"}
        or (process_status == "exited" and mission_status not in {"completed", "paused"})
        else "info"
    )
    event = {
        "timestamp": now_utc(),
        "poll": poll,
        "alert_level": alert_level,
        "mission_state": mission_status,
        "operator_state": operator_state,
        "attention_level": attention_level,
        "process_status": process_status,
        "request_id": console.get("request_id"),
        "focus_action_id": console.get("focus_action_id"),
        "focus_executor_id": console.get("focus_executor_id"),
        "summary": console.get("summary"),
        "state_changed": previous_signature is None or signature != previous_signature,
    }
    return event, signature


def _render_watch_event(event: dict[str, Any]) -> str:
    level = "ALARM" if event.get("alert_level") == "alarm" else "INFO"
    lines = [
        f"[{event.get('timestamp')}] {level} poll={event.get('poll')} mission_state=`{event.get('mission_state')}` operator_state=`{event.get('operator_state')}` process_status=`{event.get('process_status')}`",
        f"- attention_level: `{event.get('attention_level')}`",
        f"- state_changed: `{'yes' if event.get('state_changed') else 'no'}`",
        f"- summary: {event.get('summary') or 'n/a'}",
    ]
    if event.get("request_id"):
        lines.append(f"- request_id: `{event.get('request_id')}`")
    if event.get("focus_action_id"):
        lines.append(f"- focus_action: `{event.get('focus_action_id')}`")
    if event.get("focus_executor_id"):
        lines.append(f"- focus_executor: `{event.get('focus_executor_id')}`")
    return "\n".join(lines) + "\n"


def _render_request_details(request: dict[str, Any], *, heading: str, snapshot: dict[str, Any] | None = None) -> list[str]:
    blocker = request.get("blocker", {}) if isinstance(request.get("blocker"), dict) else {}
    blocker_details = blocker.get("details", {}) if isinstance(blocker.get("details"), dict) else {}
    recommendation = request.get("recommendation", {}) if isinstance(request.get("recommendation"), dict) else {}
    alternatives = request.get("alternatives", []) if isinstance(request.get("alternatives"), list) else []
    next_steps = request.get("next_steps", []) if isinstance(request.get("next_steps"), list) else []
    operator_response = request.get("operator_response") if isinstance(request.get("operator_response"), dict) else None
    blocked_entries = blocker_details.get("blocked_entries") if isinstance(blocker_details.get("blocked_entries"), list) else []
    if snapshot is not None:
        triage_details = _triage_request_details(request, snapshot)
        if triage_details is not None:
            mission_state_path, _ = triage_details
            triage_command = _triage_command_text(mission_state_path)
            if triage_command not in next_steps:
                next_steps = [triage_command, *next_steps]
    lines = [
        heading,
        "",
        f"- request_id: `{request.get('request_id')}`",
        f"- status: `{request.get('status')}`",
        f"- blocker: `{blocker.get('kind')}` `{blocker.get('risk_class')}`",
        f"- blocker_reason: {blocker.get('reason')}",
        f"- summary: {request.get('summary')}",
        f"- explanation: {request.get('explanation')}",
        f"- recommendation: {recommendation.get('summary')}",
        f"- continue_command: `{request.get('continue_command')}`",
    ]
    pros = recommendation.get("pros")
    if isinstance(pros, list) and pros:
        lines.append(f"- recommendation_pros: {'; '.join(str(item) for item in pros[:3])}")
    cons = recommendation.get("cons")
    if isinstance(cons, list) and cons:
        lines.append(f"- recommendation_cons: {'; '.join(str(item) for item in cons[:3])}")
    if blocked_entries:
        first_entry = blocked_entries[0] if isinstance(blocked_entries[0], dict) else {}
        lines.append(f"- blocked_queue: `{first_entry.get('queue_name')}`")
        lines.append(f"- blocked_entry: `{first_entry.get('entry_id')}`")
        if first_entry.get("sanity_verdict"):
            lines.append(f"- blocked_entry_verdict: `{first_entry.get('sanity_verdict')}`")
        reasons = first_entry.get("top_blocking_reasons")
        if isinstance(reasons, list) and reasons:
            lines.append(f"- blocked_entry_reasons: {'; '.join(str(item) for item in reasons[:3])}")
    if operator_response is not None:
        lines.append(
            f"- operator_feedback: `{operator_response.get('action')}` recorded at `{operator_response.get('recorded_at')}`"
        )
        if operator_response.get("note"):
            lines.append(f"- operator_feedback_note: {operator_response.get('note')}")
    if next_steps:
        lines.extend(["", "## Next steps", ""])
        lines.extend(f"- `{step}`" for step in next_steps)
    if alternatives:
        lines.extend(["", "## Alternatives", ""])
        for alternative in alternatives[:3]:
            if not isinstance(alternative, dict):
                continue
            pros_text = "; ".join(str(item) for item in alternative.get("pros") or []) or "none"
            cons_text = "; ".join(str(item) for item in alternative.get("cons") or []) or "none"
            lines.extend(
                [
                    f"- `{alternative.get('option_id')}`: {alternative.get('summary')}",
                    f"  - pros: {pros_text}",
                    f"  - cons: {cons_text}",
                ]
            )
    return lines


def _render_inbox(snapshot: dict[str, Any]) -> str:
    inbox = snapshot.get("operator_inbox", {}) if isinstance(snapshot.get("operator_inbox"), dict) else {}
    console = snapshot.get("operator_console", {}) if isinstance(snapshot.get("operator_console"), dict) else {}
    current_request = inbox.get("current_request") if isinstance(inbox.get("current_request"), dict) else None
    latest_request = inbox.get("latest_request") if isinstance(inbox.get("latest_request"), dict) else None
    lines = [
        "# DeepLoop operator inbox",
        "",
        f"- operator_request_log_path: `{inbox.get('operator_request_log_path')}`",
        f"- current_operator_request_path: `{inbox.get('current_operator_request_path')}`",
        "",
    ]
    if console:
        lines.extend(_render_console_overview(console, heading="## Operator summary"))
        lines.append("")
    if current_request is not None:
        lines.extend(_render_request_details(current_request, heading="## Current request", snapshot=snapshot))
        lines.append("")
        lines.extend(_render_exact_next_commands(console))
        return "\n".join(lines).rstrip() + "\n"
    if latest_request is not None:
        lines.append("No open operator request is active right now.")
        lines.append("")
        lines.extend(_render_request_details(latest_request, heading="## Latest historical request", snapshot=snapshot))
        lines.append("")
        lines.extend(_render_exact_next_commands(console))
        return "\n".join(lines).rstrip() + "\n"
    lines.append("Operator inbox is clear. DeepLoop can keep working until a true safety or authority boundary needs review.")
    lines.append("")
    lines.extend(_render_exact_next_commands(console))
    return "\n".join(lines) + "\n"


def _resolve_snapshot(args: argparse.Namespace, *, log_tail_lines: int, ledger_tail: int = 0) -> dict[str, Any]:
    launch_metadata_path = _resolve_optional_path(getattr(args, "launch_metadata", None))
    mission_state_path = _resolve_existing_path(args.mission_state)
    return build_mission_snapshot(
        mission_state_path,
        launch_metadata_path=launch_metadata_path,
        log_tail_lines=log_tail_lines,
        ledger_tail=ledger_tail,
    )


def _check_editable_install_and_warn() -> None:
    """Warn to stderr if deeploop is editable-installed and the working tree is dirty.

    An editable install ties every spawned subprocess to the live source tree,
    so an uncommitted change or branch switch during a long-running mission will
    crash the next stage kernel.  This function is best-effort: it silently
    returns on any detection error so it never blocks a legitimate launch.
    """
    import importlib.metadata as _meta

    try:
        dist = _meta.Distribution.from_name("deeploop")
        raw = dist.read_text("direct_url.json")
    except Exception:
        return

    if raw is None:
        return

    try:
        direct_url = json.loads(raw)
    except Exception:
        return

    dir_info = direct_url.get("dir_info") or {}
    if not dir_info.get("editable"):
        return

    # Editable install confirmed — check for a dirty git working tree.
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return

    if result.returncode != 0 or not result.stdout.strip():
        return

    print(
        "\nWARNING: deeploop is installed in editable mode and the working tree\n"
        "is dirty. Every stage kernel subprocess loads modules directly from\n"
        "the live source directory, so uncommitted edits or a branch switch\n"
        "will crash the running mission the next time a kernel spins up.\n"
        "To protect a long-running mission, either:\n"
        "  • commit or stash all pending changes before launching, or\n"
        "  • install a stable snapshot with:\n"
        "      pip install git+https://github.com/tnetal/DeepLoop.git\n",
        file=sys.stderr,
    )


def _handle_start(args: argparse.Namespace) -> int:
    _check_editable_install_and_warn()
    mission_state_path = _resolve_existing_path(args.mission_state)
    resume_context = None
    if args.command == "resume":
        snapshot = _resolve_snapshot(args, log_tail_lines=0)
        resume_context = _resume_context(snapshot)
    payload = _start_launch(
        mission_state_path=mission_state_path,
        max_iterations=args.max_iterations,
        runtime_root=_resolve_optional_path(args.runtime_root),
        launch_metadata_path=_resolve_optional_path(args.launch_metadata),
        log_path=_resolve_optional_path(args.log_path),
        replace_running=args.replace_running,
        launch_reason=args.command,
    )
    if resume_context is not None:
        payload["resume_context"] = resume_context
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(_render_launch_summary(payload, launch_reason=args.command), end="")
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    snapshot = _resolve_snapshot(args, log_tail_lines=args.log_tail, ledger_tail=args.ledger_tail)
    if args.json:
        print(json.dumps(snapshot, indent=2))
    else:
        print(render_mission_snapshot(snapshot), end="")
    return 0


def _handle_logs(args: argparse.Namespace) -> int:
    snapshot = _resolve_snapshot(args, log_tail_lines=args.lines)
    if args.json:
        payload = {
            "launch": snapshot.get("launch"),
            "launch_metadata_path": snapshot.get("artifacts", {}).get("launch_metadata_path"),
            "log_tail": snapshot.get("log_tail", []),
        }
        print(json.dumps(payload, indent=2))
    else:
        print(_render_log_view(snapshot), end="")
    return 0


def _handle_decisions(args: argparse.Namespace) -> int:
    snapshot = _resolve_snapshot(args, log_tail_lines=0)
    decision_log_path = Path(snapshot["artifacts"]["decision_log_path"]).expanduser().resolve()
    entries = _load_jsonl(decision_log_path)[-max(args.limit, 0) :]
    if args.json:
        print(json.dumps(entries, indent=2))
    else:
        print(_render_decisions(entries, decision_log_path=decision_log_path), end="")
    return 0


def _handle_inbox(args: argparse.Namespace) -> int:
    snapshot = _resolve_snapshot(args, log_tail_lines=0)
    inbox = snapshot.get("operator_inbox", {})
    if args.json:
        print(json.dumps(inbox, indent=2))
    else:
        print(_render_inbox(snapshot), end="")
    return 0


def _handle_triage(args: argparse.Namespace) -> int:
    snapshot = _resolve_snapshot(args, log_tail_lines=0, ledger_tail=6)
    inbox = snapshot.get("operator_inbox", {}) if isinstance(snapshot.get("operator_inbox"), dict) else {}
    current_request = inbox.get("current_request") if isinstance(inbox.get("current_request"), dict) else None
    if current_request is None:
        raise RuntimeError("No open operator request is active right now. Use `status` or `inbox` first.")
    triage_details = _triage_request_details(current_request, snapshot)
    if triage_details is None:
        raise RuntimeError("Bounded triage is only available for blocked queue entries when intervention hooks are enabled.")

    mission_state_path, blocked_entries = triage_details
    mission_state = load_mission_state(mission_state_path)
    mission_root = mission_state_path.parent
    request_id = str(current_request.get("request_id") or "operator-triage")
    triage_root = mission_root / "runtime" / "operator_triage" / request_id
    triage_root.mkdir(parents=True, exist_ok=True)
    sandbox_root = triage_root / "sandbox"
    prompt_path = triage_root / "prompt.md"
    result_json_path = triage_root / "triage_result.json"
    log_path = triage_root / "triage.log"
    report_json_path = triage_root / "triage_report.json"
    prompt_text = _build_triage_prompt(
        snapshot=snapshot,
        mission_state=mission_state,
        request=current_request,
        blocked_entries=blocked_entries,
        result_json_path=result_json_path,
    )
    prompt_path.write_text(prompt_text, encoding="utf-8")

    command = [
        sys.executable,
        str(_INVOKE_PROVIDER_PROMPT_SCRIPT),
        "--prompt-file",
        str(prompt_path),
        "--result-json-path",
        str(result_json_path),
        "--sandbox-root",
        str(sandbox_root),
        "--mission-state-path",
        str(mission_state_path),
    ]
    target_repo = str(mission_state.get("target_repo") or "").strip()
    if target_repo:
        command.extend(["--target-repo", target_repo])
    if getattr(args, "model", None):
        command.extend(["--model", str(args.model)])
    if bool(getattr(args, "allow_all", False)):
        command.append("--allow-all")
    command.append("--no-ask-user")

    started_at = now_utc()
    completed = subprocess.run(
        command,
        cwd=Path(target_repo).expanduser().resolve() if target_repo else REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    completed_at = now_utc()
    log_path.write_text((completed.stdout or "") + (completed.stderr or ""), encoding="utf-8")
    if not result_json_path.exists():
        raise RuntimeError(f"Bounded triage did not produce `{result_json_path}`. Inspect `{log_path}`.")
    triage_result = _normalized_triage_result(_load_json(result_json_path))
    summary = {
        "schema_version": 1,
        "request_id": request_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "command": command,
        "prompt_path": str(prompt_path),
        "result_json_path": str(result_json_path),
        "log_path": str(log_path),
        "report_json_path": str(report_json_path),
        "blocked_entries": blocked_entries,
        "result": triage_result,
        "returncode": completed.returncode,
    }
    _write_json(report_json_path, summary)
    ledger_path = Path(snapshot["artifacts"]["ledger_path"]).expanduser().resolve()
    append_jsonl(
        ledger_path,
        make_ledger_entry(
            kind="operator-triage",
            mission_id=str(snapshot.get("mission", {}).get("mission_id") or mission_state.get("mission_id") or ""),
            summary=f"Recorded bounded triage for `{request_id}` with status `{triage_result['status']}`.",
            status=triage_result["status"],
            related_paths=[str(mission_state_path), str(prompt_path), str(result_json_path), str(report_json_path), str(log_path)],
            metadata={
                "request_id": request_id,
                "recommended_operator_action": triage_result.get("recommended_operator_action"),
                "recommended_resume_action": triage_result.get("recommended_resume_action"),
            },
        ),
    )
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(_render_triage_summary(summary), end="")
    return 0 if completed.returncode == 0 else 1


def _handle_watch(args: argparse.Namespace) -> int:
    poll_limit = int(args.polls) if args.polls is not None else None
    if poll_limit is not None and poll_limit <= 0:
        raise ValueError("polls must be positive when provided.")
    interval_seconds = float(args.interval_seconds)
    if interval_seconds < 0:
        raise ValueError("interval-seconds must be non-negative.")

    previous_signature: tuple[str, ...] | None = None
    poll = 0
    try:
        while poll_limit is None or poll < poll_limit:
            poll += 1
            snapshot = _resolve_snapshot(args, log_tail_lines=0, ledger_tail=1)
            event, previous_signature = _watch_event(snapshot, poll=poll, previous_signature=previous_signature)
            if args.json:
                print(json.dumps(event))
            else:
                print(_render_watch_event(event), end="")
            if poll_limit is not None and poll >= poll_limit:
                break
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("DeepLoop watch interrupted.", file=sys.stderr)
        return 130
    return 0


def _handle_stop(args: argparse.Namespace) -> int:
    snapshot = _resolve_snapshot(args, log_tail_lines=0)
    metadata_path = Path(snapshot["artifacts"]["launch_metadata_path"]).expanduser().resolve()
    metadata = _load_launch_metadata(metadata_path)
    if metadata is None:
        print(
            f"No launch metadata found at {metadata_path}. Start the mission with `manage_mission.py start` first.",
            file=sys.stderr,
        )
        return 1

    pid = metadata.get("pid")
    process_group_id = metadata.get("process_group_id") if isinstance(metadata.get("process_group_id"), int) else pid
    if not _pid_is_running(pid):
        print(f"DeepLoop is not running. Last known launch metadata is at `{metadata_path}`.")
        return 0

    selected_signal = signal.SIGKILL if args.force else signal.SIGTERM
    try:
        os.killpg(int(process_group_id), selected_signal)
    except ProcessLookupError:
        print("DeepLoop already exited before the stop request completed.")
        return 0

    metadata["stop_requested_at"] = now_utc()
    metadata["stop_signal"] = signal.Signals(selected_signal).name
    _write_json(metadata_path, metadata)
    print(
        "\n".join(
            [
                "# DeepLoop stop requested",
                "",
                f"- pid: `{pid}`",
                f"- signal: `{metadata['stop_signal']}`",
                f"- launch_metadata_path: `{metadata_path}`",
            ]
        )
    )
    return 0


def _handle_operator_feedback(args: argparse.Namespace) -> int:
    snapshot = _resolve_snapshot(args, log_tail_lines=0, ledger_tail=3)
    updated_request = _record_operator_feedback(snapshot, action=args.command, note=args.note)
    refreshed_snapshot = _resolve_snapshot(args, log_tail_lines=0, ledger_tail=3)
    if args.json:
        print(json.dumps(updated_request, indent=2))
    else:
        print(
            _render_operator_feedback_summary(
                refreshed_snapshot,
                action=args.command,
                note=args.note,
                updated_request=updated_request,
            ),
            end="",
        )
    return 0


def _handle_run(args: argparse.Namespace) -> int:
    return _run_project(args)


def _handle_init(args: argparse.Namespace) -> int:
    return _init_mission(args)


def _handle_package(args: argparse.Namespace) -> int:
    return _package_mission(args)


def _handle_analyze(args: argparse.Namespace) -> int:
    return _analyze(args)


def _handle_analyze_budget(args: argparse.Namespace) -> int:
    mission_state_path = Path(args.mission_state).expanduser().resolve() if args.mission_state else None
    config_path = Path(args.config).expanduser().resolve() if getattr(args, "config", None) else None
    report = analyze_budget(
        config_path=config_path,
        mission_state_path=mission_state_path,
    )
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
        return 0

    lines = [
        f"- max_iterations: `{report['max_iterations']}`",
        f"- pending_actions: `{report['pending_actions']}`",
        f"- iterations_completed: `{report['iterations_completed']}`",
        f"- iterations_remaining: `{report['iterations_remaining']}`",
        f"- projected_total: `{report['projected_total']}`",
        f"- utilization_ratio: `{report['utilization_ratio']:.0%}`",
        f"- status: `{report['status']}`",
    ]
    for warning in report["warnings"]:
        lines.append(f"- WARNING: {warning}")
    print("\n".join(lines))
    return 1 if report["status"] == "over-budget" else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate DeepLoop autopilot for a mission from one management CLI.",
        epilog=(
            "Default flow: start the mission, watch status, inspect inbox on hard/operator-needed "
            "stops, optionally record retry/reroute, then resume. run_mission.py and "
            "monitor_mission.py stay underneath as backend surfaces."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def _add_launch_parser(name: str, *, help_text: str) -> argparse.ArgumentParser:
        command = subparsers.add_parser(
            name,
            help=help_text,
            description=help_text,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        command.add_argument("--mission-state", required=True, help="Path to mission_state.json.")
        command.add_argument(
            "--max-iterations",
            type=int,
            default=None,
            help="Outer-loop iteration budget for this run. If omitted, use the mission launcher setting or 12.",
        )
        command.add_argument("--runtime-root", help="Optional override for runtime/mission_outer_runtime.")
        command.add_argument("--launch-metadata", help="Optional override for the detached launch metadata JSON.")
        command.add_argument("--log-path", help="Optional override for the detached mission log file.")
        command.add_argument(
            "--replace-running",
            action="store_true",
            help="Replace existing launch metadata even if it still points to a live process.",
        )
        command.add_argument("--json", action="store_true", help="Emit machine-readable launch metadata.")
        command.set_defaults(handler=_handle_start)
        return command

    _add_launch_parser("start", help_text="Start DeepLoop autopilot for a mission in the background.")
    _add_launch_parser(
        "resume",
        help_text="Resume DeepLoop autopilot after a stop, block, or operator fix.",
    )

    status = subparsers.add_parser(
        "status",
        help="Show the operator console and exact next commands.",
        description="Show whether autopilot is running, blocked, or exited and exactly what to do next.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    status.add_argument("--mission-state", required=True, help="Path to mission_state.json.")
    status.add_argument("--launch-metadata", help="Optional override for the detached launch metadata JSON.")
    status.add_argument("--log-tail", type=int, default=20, help="Number of detached-process log lines to include.")
    status.add_argument("--ledger-tail", type=int, default=8, help="Number of recent ledger entries to include.")
    status.add_argument("--json", action="store_true", help="Emit the structured status snapshot as JSON.")
    status.set_defaults(handler=_handle_status)

    logs = subparsers.add_parser(
        "logs",
        help="Show detached autopilot logs.",
        description="Show the current detached DeepLoop autopilot log tail.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    logs.add_argument("--mission-state", required=True, help="Path to mission_state.json.")
    logs.add_argument("--launch-metadata", help="Optional override for the detached launch metadata JSON.")
    logs.add_argument("--lines", type=int, default=40, help="Number of log lines to show.")
    logs.add_argument("--json", action="store_true", help="Emit log metadata and tail as JSON.")
    logs.set_defaults(handler=_handle_logs)

    decisions = subparsers.add_parser(
        "decisions",
        help="Show recent mission decisions.",
        description="Show recent mission decisions without inspecting raw JSONL manually.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    decisions.add_argument("--mission-state", required=True, help="Path to mission_state.json.")
    decisions.add_argument("--limit", type=int, default=5, help="Maximum number of recent decisions to show.")
    decisions.add_argument("--json", action="store_true", help="Emit recent decision entries as JSON.")
    decisions.set_defaults(handler=_handle_decisions)

    inbox = subparsers.add_parser(
        "inbox",
        help="Show the current operator request inbox.",
        description="Show the latest hard-gate or operator-needed request, recommendation, and exact continue commands.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    inbox.add_argument("--mission-state", required=True, help="Path to mission_state.json.")
    inbox.add_argument("--launch-metadata", help="Optional override for the detached launch metadata JSON.")
    inbox.add_argument("--json", action="store_true", help="Emit the structured operator inbox payload as JSON.")
    inbox.set_defaults(handler=_handle_inbox)

    triage = subparsers.add_parser(
        "triage",
        help="Run the bounded managed-mode triage hook for the current blocked request.",
        description="Run a bounded provider-backed triage pass against the active blocked queue entry when intervention hooks are enabled.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    triage.add_argument("--mission-state", required=True, help="Path to mission_state.json.")
    triage.add_argument("--launch-metadata", help="Optional override for the detached launch metadata JSON.")
    triage.add_argument("--model", help="Optional provider model override for the bounded triage pass.")
    triage.add_argument("--allow-all", action="store_true", help="Pass --allow-all through to the provider launcher.")
    triage.add_argument("--json", action="store_true", help="Emit the triage summary payload as JSON.")
    triage.set_defaults(handler=_handle_triage)

    watch = subparsers.add_parser(
        "watch",
        help="Poll the mission and emit fresh watch/alarm lines.",
        description="Watch the mission with fresh status snapshots so blocked or exited transitions are visible without stale shell buffers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    watch.add_argument("--mission-state", required=True, help="Path to mission_state.json.")
    watch.add_argument("--launch-metadata", help="Optional override for the detached launch metadata JSON.")
    watch.add_argument("--interval-seconds", type=float, default=300.0, help="Seconds between status polls.")
    watch.add_argument("--polls", type=int, help="Optional maximum number of polls before exiting.")
    watch.add_argument("--json", action="store_true", help="Emit one JSON watch event per line.")
    watch.set_defaults(handler=_handle_watch)

    stop = subparsers.add_parser(
        "stop",
        help="Stop a running DeepLoop autopilot mission.",
        description="Stop the detached DeepLoop autopilot process tracked for this mission.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    stop.add_argument("--mission-state", required=True, help="Path to mission_state.json.")
    stop.add_argument("--launch-metadata", help="Optional override for the detached launch metadata JSON.")
    stop.add_argument("--force", action="store_true", help="Send SIGKILL instead of SIGTERM.")
    stop.set_defaults(handler=_handle_stop)

    for command_name, help_text in (
        ("retry", "Record that the operator fixed an in-scope issue before resume."),
        ("reroute", "Record that the operator chose a rerouted or downscoped path before resume."),
    ):
        feedback = subparsers.add_parser(
            command_name,
            help=help_text,
            description=help_text,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        feedback.add_argument("--mission-state", required=True, help="Path to mission_state.json.")
        feedback.add_argument(
            "--note",
            help="Optional operator note describing the fix, reroute, or scope change before resume.",
        )
        feedback.add_argument("--launch-metadata", help="Optional override for the detached launch metadata JSON.")
        feedback.add_argument("--json", action="store_true", help="Emit the updated current operator request as JSON.")
        feedback.set_defaults(handler=_handle_operator_feedback)

    run_p = subparsers.add_parser(
        "run",
        help="Run a plain project folder through DeepLoop until completion or an operator boundary.",
        description="Run a plain researcher project folder through DeepLoop until completion or a true operator boundary.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_run_args(run_p)
    run_p.set_defaults(handler=_handle_run)

    init_p = subparsers.add_parser(
        "init",
        help="Initialise a DeepLoop mission from a project folder or explicit config.",
        description="Bootstrap a mission state from a plain-folder project or an explicit mission config.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_init_args(init_p)
    init_p.set_defaults(handler=_handle_init)

    package_p = subparsers.add_parser(
        "package",
        help="Package mission artifacts according to the artifact-package contract.",
        description="Package mission artifacts for the given mission state.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_package_args(package_p)
    package_p.set_defaults(handler=_handle_package)

    analyze_p = subparsers.add_parser(
        "analyze",
        help="Analyze the current mission state by routing a prompt to the configured provider.",
        description=(
            "Route a mission analysis prompt to the configured provider.  "
            "The prompt is always written to a file first — never passed as an inline CLI string — "
            "so this command is safe for large mission states that would otherwise trigger "
            "[Errno 7] Argument list too long."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_analyze_args(analyze_p)
    analyze_p.set_defaults(handler=_handle_analyze)

    analyze_budget_p = subparsers.add_parser(
        "analyze-budget",
        help="Predict whether the pending queue will exceed the recursive-agent iteration budget.",
        description=(
            "Analyse the configured max_iterations ceiling against the current pending action queue size "
            "and emit an early warning if the queue is dangerously close to or exceeds the budget."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    analyze_budget_p.add_argument("--mission-state", required=True, help="Path to mission_state.json.")
    analyze_budget_p.add_argument(
        "--config",
        help="Path to a recursive-agent loop config YAML. "
        "If omitted, the default recursive-agent-runtime policy values are used.",
    )
    analyze_budget_p.add_argument("--json", action="store_true", help="Emit the budget report as JSON.")
    analyze_budget_p.set_defaults(handler=_handle_analyze_budget)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


__all__ = ["build_parser", "main"]
