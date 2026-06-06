from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from deeploop.autonomy.operator_inbox import load_current_operator_request, load_operator_request_log
from deeploop.core.shared import normalize_strings as _normalize_strings

_PERMANENT_BOUNDARY_REQUEST_KINDS = {"hard-gate", "authority-boundary"}
_TEMPORARY_GAP_REQUEST_KINDS = {"operator-review", "unrecoverable-failure"}
_RECOVERY_ACTIONS = ("retry", "reroute", "downscope")
_RUNTIME_RECOVERY_COUNT_KEYS = (
    "completed_jobs",
    "blocked_jobs",
    "warned_jobs",
    "failed_jobs",
    "recovered_jobs",
    "rerouted_jobs",
    "resumed_jobs",
)






def _request_payload(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    request_id = str(raw.get("request_id") or "").strip()
    if not request_id:
        return None
    return dict(raw)


def _path_from_payload(raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser().resolve()


def _soft_gate_actions(event: Mapping[str, Any]) -> list[str]:
    preferred_actions = [item for item in _normalize_strings(event.get("preferred_actions")) if item in _RECOVERY_ACTIONS]
    if preferred_actions:
        return preferred_actions
    default_response = str(event.get("default_response") or "").strip()
    if not default_response:
        return []
    return [item for item in default_response.split("-") if item in _RECOVERY_ACTIONS]


def _runtime_recovery_counts(runtime_recovery: Mapping[str, Any] | None) -> dict[str, int]:
    if not isinstance(runtime_recovery, Mapping):
        return {key: 0 for key in _RUNTIME_RECOVERY_COUNT_KEYS}
    nested_counts = runtime_recovery.get("counts")
    source = nested_counts if isinstance(nested_counts, Mapping) else runtime_recovery
    return {
        key: int(source.get(key, 0) or 0)
        for key in _RUNTIME_RECOVERY_COUNT_KEYS
    }


def _request_kind(request: Mapping[str, Any] | None) -> str | None:
    if not isinstance(request, Mapping):
        return None
    blocker = request.get("blocker")
    if not isinstance(blocker, Mapping):
        return None
    kind = str(blocker.get("kind") or "").strip()
    return kind or None


def _request_summary(request: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(request, Mapping):
        return None
    blocker = request.get("blocker") if isinstance(request.get("blocker"), Mapping) else {}
    return {
        "request_id": request.get("request_id"),
        "summary": request.get("summary"),
        "kind": blocker.get("kind"),
        "risk_class": blocker.get("risk_class"),
        "reason": blocker.get("reason"),
        "created_at": request.get("created_at"),
    }


def _temporary_gap_hint_from_request(request: Mapping[str, Any]) -> dict[str, Any] | None:
    blocker = request.get("blocker") if isinstance(request.get("blocker"), Mapping) else {}
    kind = str(blocker.get("kind") or "").strip()
    if kind not in _TEMPORARY_GAP_REQUEST_KINDS:
        return None
    details = blocker.get("details") if isinstance(blocker.get("details"), Mapping) else {}
    blocked_entries = details.get("blocked_entries") if isinstance(details.get("blocked_entries"), list) else []
    category = "blocked-queue-entry-review" if blocked_entries else str(blocker.get("risk_class") or kind or "operator-review")
    preferred_actions = [item for item in _normalize_strings(blocker.get("preferred_actions")) if item in _RECOVERY_ACTIONS]
    auto_triage = request.get("auto_triage") if isinstance(request.get("auto_triage"), Mapping) else {}
    recommended_action = str(auto_triage.get("recommended_operator_action") or "").strip()
    if not recommended_action and preferred_actions:
        recommended_action = preferred_actions[0]
    context = request.get("context") if isinstance(request.get("context"), Mapping) else {}
    reroute_target = str(details.get("reroute_target") or context.get("next_phase") or "").strip() or None
    return {
        "source": "operator_request",
        "request_id": request.get("request_id"),
        "category": category,
        "recommended_action": recommended_action or None,
        "preferred_actions": preferred_actions,
        "recoverability": "operator-required",
        "reroute_target": reroute_target,
        "telemetry_class": "escalated",
        "summary": str(request.get("summary") or blocker.get("reason") or "").strip(),
        "created_at": request.get("created_at"),
    }


def _temporary_gap_hint_from_soft_gate(event: Mapping[str, Any]) -> dict[str, Any]:
    preferred_actions = _soft_gate_actions(event)
    status = str(event.get("status") or "observed").strip() or "observed"
    telemetry_class = "escalated" if status in {"blocked", "failed", "operator-review"} else "auto-recovered"
    reroute_target = str(event.get("route_to") or event.get("reroute_target") or "").strip() or None
    return {
        "source": "soft_gate",
        "request_id": None,
        "category": str(event.get("risk_class") or "soft-gate"),
        "recommended_action": preferred_actions[0] if preferred_actions else None,
        "preferred_actions": preferred_actions,
        "recoverability": "operator-required" if telemetry_class == "escalated" else "bounded",
        "reroute_target": reroute_target,
        "telemetry_class": telemetry_class,
        "summary": str(event.get("reason") or "").strip(),
        "created_at": event.get("created_at"),
    }


def build_autonomy_gap_telemetry(
    mission_state: Mapping[str, Any],
    *,
    operator_request_log_path: Path | None = None,
    current_operator_request: Mapping[str, Any] | None = None,
    runtime_recovery: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    outer_loop = mission_state.get("outer_loop") if isinstance(mission_state.get("outer_loop"), Mapping) else {}
    resolved_log_path = operator_request_log_path or _path_from_payload(outer_loop.get("operator_request_log_path"))
    current_request_path = _path_from_payload(outer_loop.get("current_operator_request_path"))

    request_log = load_operator_request_log(resolved_log_path) if resolved_log_path is not None and resolved_log_path.exists() else []
    current_request = _request_payload(current_operator_request)
    if current_request is None and current_request_path is not None and current_request_path.exists():
        current_request = load_current_operator_request(current_request_path)

    deduped_requests: list[dict[str, Any]] = []
    seen_request_ids: set[str] = set()
    for request in request_log:
        payload = _request_payload(request)
        if payload is None:
            continue
        request_id = str(payload["request_id"])
        if request_id in seen_request_ids:
            continue
        deduped_requests.append(payload)
        seen_request_ids.add(request_id)
    if current_request is not None:
        current_request_id = str(current_request["request_id"])
        if current_request_id not in seen_request_ids:
            deduped_requests.append(dict(current_request))
            seen_request_ids.add(current_request_id)

    request_class_counts: Counter[str] = Counter()
    latest_temporary_gap: dict[str, Any] | None = None
    for request in deduped_requests:
        kind = _request_kind(request) or "operator-review"
        request_class_counts[kind] += 1
        if kind in _TEMPORARY_GAP_REQUEST_KINDS:
            latest_temporary_gap = request

    soft_gate_events = [
        dict(event)
        for event in (mission_state.get("soft_gate_events") or [])
        if isinstance(event, Mapping)
    ]
    soft_gate_risk_classes: Counter[str] = Counter()
    soft_gate_statuses: Counter[str] = Counter()
    recovery_preferences: Counter[str] = Counter()
    temporary_gap_hints: list[dict[str, Any]] = []
    for event in soft_gate_events:
        soft_gate_risk_classes[str(event.get("risk_class") or "soft-gate")] += 1
        soft_gate_statuses[str(event.get("status") or "observed")] += 1
        for action in _soft_gate_actions(event):
            recovery_preferences[action] += 1
        temporary_gap_hints.append(_temporary_gap_hint_from_soft_gate(event))

    for request in deduped_requests:
        hint = _temporary_gap_hint_from_request(request)
        if hint is not None:
            temporary_gap_hints.append(hint)

    recovery_outcomes = _runtime_recovery_counts(runtime_recovery)
    bounded_recovery_outcomes = (
        recovery_outcomes["recovered_jobs"]
        + recovery_outcomes["rerouted_jobs"]
        + recovery_outcomes["resumed_jobs"]
    )
    temporary_gap_category_counts: Counter[str] = Counter(
        str(hint.get("category") or "temporary-gap") for hint in temporary_gap_hints
    )
    temporary_gap_auto_recovered = sum(
        1 for hint in temporary_gap_hints if str(hint.get("telemetry_class") or "") == "auto-recovered"
    )
    temporary_gap_escalated = sum(
        1 for hint in temporary_gap_hints if str(hint.get("telemetry_class") or "") == "escalated"
    )
    current_request_kind = _request_kind(current_request)
    unresolved_temporary_gaps = 1 if current_request_kind in _TEMPORARY_GAP_REQUEST_KINDS else 0
    if unresolved_temporary_gaps and current_request is not None:
        latest_temporary_gap = dict(current_request)

    counts = {
        "operator_requests_total": len(deduped_requests),
        "permanent_boundary_requests": sum(
            request_class_counts.get(kind, 0) for kind in _PERMANENT_BOUNDARY_REQUEST_KINDS
        ),
        "temporary_gap_requests": sum(
            request_class_counts.get(kind, 0) for kind in _TEMPORARY_GAP_REQUEST_KINDS
        ),
        "hard_gate_requests": request_class_counts.get("hard-gate", 0),
        "authority_boundary_requests": request_class_counts.get("authority-boundary", 0),
        "soft_gates_total": len(soft_gate_events),
        "bounded_recovery_outcomes": bounded_recovery_outcomes,
        "unresolved_temporary_gaps": unresolved_temporary_gaps,
        "temporary_gap_auto_recovered": temporary_gap_auto_recovered,
        "temporary_gap_escalated": temporary_gap_escalated,
    }
    latest_soft_gate = soft_gate_events[-1] if soft_gate_events else None
    latest_temporary_gap_hint = temporary_gap_hints[-1] if temporary_gap_hints else None
    if not any(counts.values()):
        summary = "No operator requests, soft gates, or bounded recovery outcomes are recorded yet."
    else:
        summary = (
            "Tracked "
            f"{counts['operator_requests_total']} operator requests "
            f"({counts['temporary_gap_requests']} temporary-gap, {counts['permanent_boundary_requests']} permanent-boundary), "
            f"{counts['soft_gates_total']} soft gates, {counts['bounded_recovery_outcomes']} bounded recovery outcomes, "
            f"{counts['temporary_gap_auto_recovered']} auto-recovered temporary gaps, and "
            f"{counts['temporary_gap_escalated']} escalated temporary gaps."
        )
        if unresolved_temporary_gaps:
            summary += f" {unresolved_temporary_gaps} temporary gap currently remains unresolved."

    return {
        "status": "tracked",
        "summary": summary,
        "counts": counts,
        "operator_request_classes": dict(sorted(request_class_counts.items())),
        "soft_gate_risk_classes": dict(sorted(soft_gate_risk_classes.items())),
        "soft_gate_statuses": dict(sorted(soft_gate_statuses.items())),
        "temporary_gap_categories": dict(sorted(temporary_gap_category_counts.items())),
        "temporary_gap_hints": temporary_gap_hints,
        "recovery_preferences": {key: recovery_preferences.get(key, 0) for key in _RECOVERY_ACTIONS},
        "recovery_outcomes": recovery_outcomes,
        "latest_soft_gate": {
            "risk_class": latest_soft_gate.get("risk_class"),
            "status": latest_soft_gate.get("status"),
            "reason": latest_soft_gate.get("reason"),
        }
        if isinstance(latest_soft_gate, Mapping)
        else None,
        "current_request": _request_summary(current_request),
        "latest_temporary_gap": _request_summary(latest_temporary_gap),
        "latest_temporary_gap_hint": latest_temporary_gap_hint,
        "tracked_paths": {
            "operator_request_log_path": str(resolved_log_path) if resolved_log_path is not None else None,
            "current_operator_request_path": str(current_request_path) if current_request_path is not None else None,
        },
    }


__all__ = ["build_autonomy_gap_telemetry"]
