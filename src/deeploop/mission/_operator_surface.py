from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def management_commands(mission_state_path: Path) -> dict[str, str]:
    mission_state_arg = str(mission_state_path)
    return {
        name: f"python scripts/mission/manage_mission.py {name} --mission-state {mission_state_arg}"
        for name in ("status", "logs", "decisions", "inbox", "resume", "retry", "reroute", "triage", "stop")
    }


def operator_response(request: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(request, Mapping):
        return None
    response = request.get("operator_response")
    return dict(response) if isinstance(response, Mapping) else None


def operator_surface_fields(
    *,
    mission_status: str,
    process_status: str,
    gate_class: str,
    summary: str,
    stop_reason: str | None,
    is_running: bool,
    requires_action: bool,
    current_request: Mapping[str, Any] | None,
    current_response: Mapping[str, Any] | None,
) -> dict[str, Any]:
    lifecycle_state = mission_status or ("running" if is_running else "stopped")
    operator_state = "stopped"
    attention_level = "investigate"
    next_step_owner = "operator"
    resume_policy = "inspect-first"
    state_reason = stop_reason or summary
    blocked_on = None
    focus_action_id = None
    focus_executor_id = None

    context = current_request.get("context") if isinstance(current_request, Mapping) else None
    if isinstance(context, Mapping):
        focus_action_id = context.get("action_id")
        focus_executor_id = context.get("executor_id")

    if requires_action and isinstance(current_request, Mapping):
        operator_state = "operator-action-required"
        attention_level = "action-required"
        next_step_owner = "operator"
        resume_policy = "resume-when-ready" if isinstance(current_response, Mapping) else "resume-after-fix"
        blocker = current_request.get("blocker") if isinstance(current_request.get("blocker"), Mapping) else {}
        blocked_on = str(blocker.get("reason") or summary)
        state_reason = blocked_on
    elif gate_class == "soft-gate" and is_running:
        operator_state = "autopilot-recovering"
        attention_level = "passive"
        next_step_owner = "autopilot"
        resume_policy = "not-needed"
    elif gate_class == "soft-gate":
        operator_state = "autopilot-ready-to-resume"
        attention_level = "resume-optional"
        next_step_owner = "operator"
        resume_policy = "resume-optional"
    elif mission_status == "completed":
        operator_state = "mission-complete"
        attention_level = "complete"
        next_step_owner = "none"
        resume_policy = "not-needed"
    elif is_running:
        operator_state = "autopilot-running"
        attention_level = "passive"
        next_step_owner = "autopilot"
        resume_policy = "not-needed"
    elif lifecycle_state in {"blocked", "failed", "paused"} or process_status == "exited":
        operator_state = "needs-investigation"
        attention_level = "investigate"
        next_step_owner = "operator"
        resume_policy = "inspect-first"
    else:
        operator_state = "stopped"
        attention_level = "investigate"
        next_step_owner = "operator"
        resume_policy = "start-or-resume"

    return {
        "lifecycle_state": lifecycle_state,
        "operator_state": operator_state,
        "attention_level": attention_level,
        "next_step_owner": next_step_owner,
        "resume_policy": resume_policy,
        "state_reason": state_reason,
        "blocked_on": blocked_on,
        "focus_action_id": focus_action_id,
        "focus_executor_id": focus_executor_id,
    }


def operator_console_snapshot(
    mission_state_path: Path,
    *,
    mission: Mapping[str, Any],
    outer_loop: Mapping[str, Any],
    operator_inbox: Mapping[str, Any],
    failures: Mapping[str, Any],
    launch: Mapping[str, Any] | None,
    observability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    commands = management_commands(mission_state_path)
    mission_status = str(mission.get("status") or "unknown")
    runtime = outer_loop.get("runtime") if isinstance(outer_loop.get("runtime"), Mapping) else None
    runtime_status = str(runtime.get("status") or "") if isinstance(runtime, Mapping) else ""
    recursive_agent = (
        runtime.get("recursive_agent")
        if isinstance(runtime, Mapping) and isinstance(runtime.get("recursive_agent"), Mapping)
        else None
    )
    process_status = str(launch.get("process_status") or "unknown") if isinstance(launch, Mapping) else "unknown"
    process_is_running = process_status == "running"
    runtime_is_running = runtime_status == "running" and process_status != "exited"
    mission_is_running = mission_status == "running" and process_status != "exited"
    current_request = (
        operator_inbox.get("current_request") if isinstance(operator_inbox.get("current_request"), Mapping) else None
    )
    latest_request = operator_inbox.get("latest_request") if isinstance(operator_inbox.get("latest_request"), Mapping) else None
    latest_soft_gate = outer_loop.get("latest_soft_gate") if isinstance(outer_loop.get("latest_soft_gate"), Mapping) else None
    current_response = operator_response(current_request)

    headline = "STOPPED — DeepLoop is not currently running."
    summary = "No operator-facing mission summary is available yet."
    recommendation = "Run status and logs to inspect the current mission state."
    continue_summary = "Start or resume the mission once the desired next step is clear."
    gate_class = "none"
    gate_detail = None
    stop_reason = None
    requires_action = False
    is_running = False
    alternatives: list[dict[str, Any]] = [
        {
            "option_id": "inspect-status",
            "summary": "Inspect the mission monitor for the latest state and current work.",
            "pros": ["Fastest way to confirm whether DeepLoop is still running."],
            "cons": ["Does not include the full detached-process log tail."],
            "next_steps": [commands["status"]],
        },
        {
            "option_id": "inspect-logs",
            "summary": "Read the detached process log if you need raw runtime detail.",
            "pros": ["Shows recent executor output and tracebacks."],
            "cons": ["Less concise than the operator console."],
            "next_steps": [commands["logs"]],
        },
    ]
    next_commands: list[dict[str, str]] = [
        {
            "label": "status",
            "command": commands["status"],
            "description": "Refresh the operator console summary.",
        },
        {
            "label": "logs",
            "command": commands["logs"],
            "description": "Inspect the detached mission log tail.",
        },
    ]

    if isinstance(current_request, Mapping):
        blocker = current_request.get("blocker") if isinstance(current_request.get("blocker"), Mapping) else {}
        blocker_details = blocker.get("details") if isinstance(blocker.get("details"), Mapping) else {}
        recommendation_payload = (
            current_request.get("recommendation") if isinstance(current_request.get("recommendation"), Mapping) else {}
        )
        blocked_entries = []
        raw_blocked_entries = blocker_details.get("blocked_entries")
        if isinstance(raw_blocked_entries, list):
            blocked_entries = [item for item in raw_blocked_entries if isinstance(item, Mapping)]
        context = current_request.get("context") if isinstance(current_request.get("context"), Mapping) else {}
        alternatives = [
            dict(item)
            for item in current_request.get("alternatives", [])
            if isinstance(item, Mapping)
        ] or alternatives
        gate_class = str(blocker.get("kind") or blocker.get("gate") or "operator-review")
        gate_detail = str(blocker.get("risk_class") or blocker.get("label") or gate_class)
        headline = "BLOCKED — operator action is required before DeepLoop can continue."
        summary = str(current_request.get("summary") or blocker.get("reason") or "DeepLoop opened the operator inbox.")
        recommendation = str(
            recommendation_payload.get("summary")
            or "Review the request, make the smallest safe change, then resume autopilot."
        )
        stop_reason = str(blocker.get("reason") or failures.get("completion_reason") or summary)
        requires_action = True
        continue_summary = "Review the inbox, make the requested change, optionally record retry/reroute feedback, then resume."
        next_commands = [
            *(
                [
                    {
                        "label": "triage",
                        "command": commands["triage"],
                        "description": "Run the bounded triage hook before choosing retry or reroute.",
                    }
                ]
                if blocked_entries and str(context.get("mode") or "") == "managed"
                else []
            ),
            {
                "label": "inbox",
                "command": commands["inbox"],
                "description": "Review the active operator request and recommendation.",
            },
            {
                "label": "status",
                "command": commands["status"],
                "description": "Confirm the current mission state and latest blocked work.",
            },
            {
                "label": "retry",
                "command": f'{commands["retry"]} --note "<what changed>"',
                "description": "Record that the blocked path was fixed in-scope and should be retried on resume.",
            },
            {
                "label": "reroute",
                "command": f'{commands["reroute"]} --note "<new plan>"',
                "description": "Record that the mission should resume on a smaller or alternate in-scope path.",
            },
            {
                "label": "resume",
                "command": str(current_request.get("continue_command") or commands["resume"]),
                "description": "Resume autopilot once the blocker has been addressed.",
            },
        ]
        if isinstance(current_response, Mapping):
            action = str(current_response.get("action") or "operator-action")
            continue_summary = (
                f"Operator feedback `{action}` is already recorded. Finish the requested change, then resume autopilot."
            )
            next_commands = [
                {
                    "label": "resume",
                    "command": str(current_request.get("continue_command") or commands["resume"]),
                    "description": "Resume autopilot with the recorded operator decision in place.",
                },
                {
                    "label": "inbox",
                    "command": commands["inbox"],
                    "description": "Review the active request and recorded operator feedback.",
                },
                {
                    "label": "status",
                    "command": commands["status"],
                    "description": "Re-check the mission state before resuming.",
                },
            ]
    elif isinstance(latest_soft_gate, Mapping):
        risk_class = str(latest_soft_gate.get("risk_class") or "soft-gate")
        preferred_actions = [
            str(item)
            for item in outer_loop.get("soft_gate_preferred_actions", [])
            if isinstance(item, str) and item
        ]
        gate_class = "soft-gate"
        gate_detail = risk_class
        is_running = process_is_running or runtime_is_running or mission_is_running
        headline = (
            "RUNNING — DeepLoop is still working through a soft gate."
            if is_running
            else "STOPPED — the last run ended after a soft-gate recovery path."
        )
        summary = str(
            latest_soft_gate.get("reason")
            or f"DeepLoop surfaced `{risk_class}` as a soft gate and kept control."
        )
        recommendation = (
            "Let DeepLoop keep control. Soft gates prefer retry, reroute, or downscope before the inbox opens."
        )
        continue_summary = (
            "No operator action is required right now."
            if is_running
            else "Inspect the last soft-gate recovery, then resume if you want DeepLoop to continue."
        )
        requires_action = not is_running
        alternatives = [
            {
                "option_id": "watch-autopilot",
                "summary": "Let DeepLoop continue its soft recovery path without operator intervention.",
                "pros": ["Keeps default sandboxed autopilot in control."],
                "cons": ["May take another bounded retry, reroute, or downscope step before the mission advances."],
                "next_steps": [commands["status"]],
            },
            {
                "option_id": "inspect-soft-gate",
                "summary": "Inspect the latest decision and logs if you want more detail about the soft-gate recovery.",
                "pros": ["Shows the exact recovery path."],
                "cons": ["Adds more detail than most operators need."],
                "next_steps": [commands["decisions"], commands["logs"]],
            },
        ]
        next_commands = [
            {
                "label": "status",
                "command": commands["status"],
                "description": "Refresh the autopilot summary.",
            },
            {
                "label": "decisions",
                "command": commands["decisions"],
                "description": "Inspect the latest mission decision if you want more detail.",
            },
            {
                "label": "logs",
                "command": commands["logs"],
                "description": "Inspect the detached process logs if the soft recovery looks stuck.",
            },
        ]
        if not is_running:
            next_commands.append(
                {
                    "label": "resume",
                    "command": commands["resume"],
                    "description": "Resume autopilot if you want another bounded pass after the soft-gate stop.",
                }
            )
        if preferred_actions:
            recommendation += f" Preferred soft recovery actions: `{', '.join(preferred_actions)}`."
    elif mission_status == "completed":
        headline = "COMPLETED — DeepLoop finished this mission."
        summary = str(failures.get("completion_reason") or "DeepLoop reached a completed mission state.")
        recommendation = "Inspect the current mission status, decisions, and packaged outputs."
        continue_summary = "No operator action is required unless you want to launch another bounded run."
        next_commands = [
            {
                "label": "status",
                "command": commands["status"],
                "description": "Review the final mission snapshot.",
            },
            {
                "label": "decisions",
                "command": commands["decisions"],
                "description": "Inspect the recent mission decisions.",
            },
            {
                "label": "logs",
                "command": commands["logs"],
                "description": "Inspect the final detached log tail if needed.",
            },
        ]
    elif process_is_running or runtime_is_running or mission_is_running:
        is_running = True
        headline = "RUNNING — DeepLoop is still working."
        summary = str(
            (recursive_agent.get("summary") if isinstance(recursive_agent, Mapping) else None)
            or mission.get("next_actions_summary")
            or failures.get("completion_reason")
            or "Autopilot still owns the current mission step."
        )
        recommendation = "Let DeepLoop keep running. Use the management surface only when you want more detail or need to stop."
        continue_summary = "No operator action is required right now."
        next_commands = [
            {
                "label": "status",
                "command": commands["status"],
                "description": "Refresh the operator console summary.",
            },
            {
                "label": "logs",
                "command": commands["logs"],
                "description": "Inspect the detached mission log tail.",
            },
            {
                "label": "decisions",
                "command": commands["decisions"],
                "description": "Inspect the latest mission decisions and routing choices.",
            },
            {
                "label": "stop",
                "command": commands["stop"],
                "description": "Stop the detached mission process if you need to intervene.",
            },
        ]
    else:
        request = latest_request if isinstance(latest_request, Mapping) else None
        blocker = request.get("blocker") if isinstance(request, Mapping) and isinstance(request.get("blocker"), Mapping) else {}
        gate_class = str(blocker.get("kind") or "none")
        gate_detail = str(blocker.get("risk_class") or "") or None
        summary = str(
            (request or {}).get("summary")
            or failures.get("completion_reason")
            or failures.get("last_blocker")
            or "The detached mission process exited or has not started yet."
        )
        recommendation = "Inspect status, logs, and decisions, address the blocker honestly, then resume if more work is needed."
        continue_summary = "Resume only after the blocker is understood and the next step is safe."
        requires_action = mission_status in {"blocked", "failed"}
        next_commands = [
            {
                "label": "status",
                "command": commands["status"],
                "description": "Refresh the operator console summary.",
            },
            {
                "label": "logs",
                "command": commands["logs"],
                "description": "Inspect the detached mission log tail.",
            },
            {
                "label": "decisions",
                "command": commands["decisions"],
                "description": "Inspect the latest mission decisions and blocked work.",
            },
            {
                "label": "resume",
                "command": commands["resume"],
                "description": "Resume autopilot once the blocker is addressed.",
            },
        ]

    surface = operator_surface_fields(
        mission_status=mission_status,
        process_status=process_status,
        gate_class=gate_class,
        summary=summary,
        stop_reason=stop_reason if stop_reason is not None else (None if is_running else summary),
        is_running=is_running,
        requires_action=requires_action,
        current_request=current_request if isinstance(current_request, Mapping) else None,
        current_response=current_response if isinstance(current_response, Mapping) else None,
    )
    inner_loop = observability.get("inner_loop") if isinstance(observability, Mapping) else None
    eta = observability.get("eta") if isinstance(observability, Mapping) else None
    recursive_budget = observability.get("recursive_agent") if isinstance(observability, Mapping) else None

    return {
        "state": "running" if is_running else ("blocked" if requires_action else mission_status or "stopped"),
        "lifecycle_state": surface["lifecycle_state"],
        "operator_state": surface["operator_state"],
        "attention_level": surface["attention_level"],
        "next_step_owner": surface["next_step_owner"],
        "resume_policy": surface["resume_policy"],
        "state_reason": surface["state_reason"],
        "blocked_on": surface["blocked_on"],
        "focus_action_id": surface["focus_action_id"],
        "focus_executor_id": surface["focus_executor_id"],
        "headline": headline,
        "summary": summary,
        "is_running": is_running,
        "requires_action": requires_action,
        "process_status": process_status,
        "gate_class": gate_class,
        "gate_detail": gate_detail,
        "stop_reason": stop_reason if stop_reason is not None else (None if is_running else summary),
        "recommendation": recommendation,
        "continue_summary": continue_summary,
        "budget_summary": observability.get("summary") if isinstance(observability, Mapping) else None,
        "inner_loop_summary": inner_loop.get("summary") if isinstance(inner_loop, Mapping) else None,
        "eta_summary": eta.get("summary") if isinstance(eta, Mapping) else None,
        "current_recursive_iteration": (
            recursive_budget.get("summary")
            if isinstance(recursive_budget, Mapping)
            else (recursive_agent.get("summary") if isinstance(recursive_agent, Mapping) else None)
        ),
        "alternatives": alternatives,
        "next_commands": next_commands,
        "request_id": current_request.get("request_id") if isinstance(current_request, Mapping) else None,
        "operator_response": current_response,
    }


def mode_summary(mode: str) -> str:
    normalized = str(mode or "").strip()
    if normalized == "sandboxed-yolo":
        return "default autopilot; DeepLoop keeps working until a true safety or authority boundary opens the operator inbox."
    if normalized == "managed":
        return "managed autonomy; DeepLoop still runs end-to-end but exposes broader permissions and intervention hooks."
    if normalized == "human-directed":
        return "human-directed; the operator stays in the loop for step-by-step control."
    return "autonomy posture unavailable"


__all__ = [
    "management_commands",
    "mode_summary",
    "operator_console_snapshot",
    "operator_response",
    "operator_surface_fields",
]
