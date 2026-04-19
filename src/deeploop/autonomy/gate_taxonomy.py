from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from deeploop.autonomy.operating_modes import DEFAULT_OPERATING_MODE, resolve_operating_mode
from deeploop.core.paths import REPO_ROOT

DEFAULT_GATES_PATH = REPO_ROOT / "configs" / "autonomy" / "gates.yaml"
_DEFAULT_SOFT_ACTIONS = ("retry", "reroute", "downscope")
_DEFAULT_HARD_RESPONSE = "stop-and-escalate"


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded


def _normalize_strings(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (str, Path)):
        text = str(raw).strip()
        return [text] if text else []
    if isinstance(raw, list | tuple):
        values: list[str] = []
        for item in raw:
            values.extend(_normalize_strings(item))
        return values
    return [str(raw)]


def _normalized_mapping(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, Mapping) else {}


def _legacy_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": int(policy.get("version", 1) or 1),
        "policy_name": str(policy.get("policy_name", "deeploop-autonomy-gates")),
        "summary": "Normalized autonomy gates for the canonical DeepLoop runtime.",
        "default_hard_gate_profile": "minimal",
        "mode_defaults": {
            "default": {"hard_gate_profile": "minimal"},
            "sandboxed-yolo": {"hard_gate_profile": "minimal"},
            "managed": {"hard_gate_profile": "minimal"},
            "human-directed": {"hard_gate_profile": "minimal"},
        },
        "soft_gate_defaults": {
            "preferred_actions": list(_DEFAULT_SOFT_ACTIONS),
            "terminal_actions": ["operator-review"],
        },
        "risk_classes": {
            "system-global-safety": {
                "label": "system/global safety",
                "default_gate": "hard",
                "default_response": _DEFAULT_HARD_RESPONSE,
            },
            "sandbox-boundary": {
                "label": "sandbox escape / writes outside allowed mutable roots",
                "default_gate": "hard",
                "default_response": _DEFAULT_HARD_RESPONSE,
            },
            "secrets-provenance-licensing": {
                "label": "secrets/provenance/licensing risk",
                "default_gate": "hard",
                "default_response": _DEFAULT_HARD_RESPONSE,
            },
            "external-release": {
                "label": "external publish/release",
                "default_gate": "hard",
                "default_response": _DEFAULT_HARD_RESPONSE,
            },
            "unsandboxed-escalation": {
                "label": "explicit unsandboxed escalation",
                "default_gate": "hard",
                "default_response": _DEFAULT_HARD_RESPONSE,
            },
            "scientific-validity": {
                "label": "scientific validity / evidence quality",
                "default_gate": "soft",
                "default_response": "retry-reroute-downscope",
                "preferred_actions": list(_DEFAULT_SOFT_ACTIONS),
            },
            "budget-overrun": {
                "label": "budget / resource pressure",
                "default_gate": "soft",
                "default_response": "downscope-reroute-retry",
                "preferred_actions": ["downscope", "reroute", "retry"],
            },
            "executor-mismatch": {
                "label": "executor availability / capability mismatch",
                "default_gate": "soft",
                "default_response": "reroute-downscope-retry",
                "preferred_actions": ["reroute", "downscope", "retry"],
            },
            "quality-shortfall": {
                "label": "quality / completeness shortfall",
                "default_gate": "soft",
                "default_response": "retry-downscope-reroute",
                "preferred_actions": ["retry", "downscope", "reroute"],
            },
        },
        "hard_gate_profiles": {
            "minimal": {
                "summary": "Default profile synthesized from an older gate config.",
                "hard_stop_risk_classes": [
                    "system-global-safety",
                    "sandbox-boundary",
                    "secrets-provenance-licensing",
                    "external-release",
                    "unsandboxed-escalation",
                    "scientific-validity",
                    "budget-overrun",
                    "executor-mismatch",
                    "quality-shortfall",
                ],
            }
        },
        "approval_required": list(policy.get("approval_required", [])),
        "budget_controls": _normalized_mapping(policy.get("budget_controls")),
        "failure_policy": _normalized_mapping(policy.get("failure_policy")),
    }


def normalize_gate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(policy.get("risk_classes"), Mapping):
        return normalize_gate_policy(_legacy_policy(policy))

    soft_gate_defaults = _normalized_mapping(policy.get("soft_gate_defaults"))
    default_soft_actions = _normalize_strings(soft_gate_defaults.get("preferred_actions")) or list(_DEFAULT_SOFT_ACTIONS)
    risk_classes: dict[str, dict[str, Any]] = {}
    for raw_risk_class, raw_config in dict(policy.get("risk_classes", {})).items():
        if not isinstance(raw_config, Mapping):
            continue
        risk_class = str(raw_risk_class).strip()
        if not risk_class:
            continue
        default_gate = str(raw_config.get("default_gate") or raw_config.get("gate") or "soft").strip().lower()
        if default_gate not in {"hard", "soft"}:
            default_gate = "soft"
        default_response = str(
            raw_config.get("default_response")
            or (_DEFAULT_HARD_RESPONSE if default_gate == "hard" else "retry-reroute-downscope")
        ).strip()
        preferred_actions = _normalize_strings(raw_config.get("preferred_actions"))
        if not preferred_actions and default_gate == "soft":
            preferred_actions = list(default_soft_actions)
        risk_classes[risk_class] = {
            "id": risk_class,
            "label": str(raw_config.get("label") or risk_class),
            "description": str(raw_config.get("description") or "").strip(),
            "default_gate": default_gate,
            "default_response": default_response,
            "preferred_actions": preferred_actions,
            "legacy_aliases": _normalize_strings(raw_config.get("legacy_aliases")),
        }

    default_hard_risk_classes = [
        risk_class for risk_class, config in risk_classes.items() if config["default_gate"] == "hard"
    ]
    raw_profiles = policy.get("hard_gate_profiles")
    hard_gate_profiles: dict[str, dict[str, Any]] = {}
    if isinstance(raw_profiles, Mapping):
        for raw_profile, raw_config in raw_profiles.items():
            if not isinstance(raw_config, Mapping):
                continue
            profile = str(raw_profile).strip()
            if not profile:
                continue
            hard_stop_risk_classes = [
                risk_class
                for risk_class in _normalize_strings(raw_config.get("hard_stop_risk_classes"))
                if risk_class in risk_classes
            ]
            if not hard_stop_risk_classes:
                hard_stop_risk_classes = list(default_hard_risk_classes)
            hard_gate_profiles[profile] = {
                "id": profile,
                "summary": str(raw_config.get("summary") or "").strip(),
                "hard_stop_risk_classes": hard_stop_risk_classes,
            }
    if not hard_gate_profiles:
        hard_gate_profiles["minimal"] = {
            "id": "minimal",
            "summary": "Default profile synthesized from hard risk classes.",
            "hard_stop_risk_classes": list(default_hard_risk_classes),
        }

    default_profile = str(policy.get("default_hard_gate_profile") or "minimal").strip() or "minimal"
    if default_profile not in hard_gate_profiles:
        default_profile = next(iter(hard_gate_profiles))

    mode_defaults: dict[str, dict[str, str]] = {}
    raw_mode_defaults = policy.get("mode_defaults")
    if isinstance(raw_mode_defaults, Mapping):
        for raw_mode, raw_config in raw_mode_defaults.items():
            resolved_config = _normalized_mapping(raw_config)
            profile = str(resolved_config.get("hard_gate_profile") or default_profile).strip() or default_profile
            if profile not in hard_gate_profiles:
                profile = default_profile
            mode_defaults[str(raw_mode)] = {"hard_gate_profile": profile}
    if "default" not in mode_defaults:
        mode_defaults["default"] = {"hard_gate_profile": default_profile}

    return {
        "version": int(policy.get("version", 2) or 2),
        "policy_name": str(policy.get("policy_name", "deeploop-autonomy-gates")),
        "summary": str(policy.get("summary") or "").strip(),
        "default_hard_gate_profile": default_profile,
        "mode_defaults": mode_defaults,
        "soft_gate_defaults": {
            "preferred_actions": default_soft_actions,
            "terminal_actions": _normalize_strings(soft_gate_defaults.get("terminal_actions")) or ["operator-review"],
            "note": str(soft_gate_defaults.get("note") or "").strip(),
        },
        "risk_classes": risk_classes,
        "hard_gate_profiles": hard_gate_profiles,
        "approval_required": _normalize_strings(policy.get("approval_required")),
        "budget_controls": _normalized_mapping(policy.get("budget_controls")),
        "failure_policy": _normalized_mapping(policy.get("failure_policy")),
    }


def load_gate_policy(path: Path = DEFAULT_GATES_PATH) -> dict[str, Any]:
    return normalize_gate_policy(_load_yaml(path))


def resolve_gate_contract(
    *,
    mode: str | None = None,
    gates_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = normalize_gate_policy(gates_policy or load_gate_policy())
    resolved_mode = resolve_operating_mode(mode, default=DEFAULT_OPERATING_MODE)
    mode_defaults = _normalized_mapping(policy.get("mode_defaults"))
    mode_gate_defaults = _normalized_mapping(mode_defaults.get(resolved_mode))
    profile_name = str(mode_gate_defaults.get("hard_gate_profile") or policy["default_hard_gate_profile"]).strip()
    if profile_name not in policy["hard_gate_profiles"]:
        profile_name = str(policy["default_hard_gate_profile"])
    profile = policy["hard_gate_profiles"][profile_name]
    hard_gate_risk_classes = list(profile["hard_stop_risk_classes"])
    soft_gate_risk_classes = [
        risk_class for risk_class in policy["risk_classes"] if risk_class not in set(hard_gate_risk_classes)
    ]
    gate_risk_classes: list[dict[str, Any]] = []
    for risk_class, raw_config in policy["risk_classes"].items():
        active_gate = "hard" if risk_class in set(hard_gate_risk_classes) else "soft"
        gate_risk_classes.append(
            {
                "id": risk_class,
                "label": raw_config["label"],
                "description": raw_config["description"],
                "default_gate": raw_config["default_gate"],
                "active_gate": active_gate,
                "default_response": raw_config["default_response"],
                "preferred_actions": list(raw_config["preferred_actions"]),
                "legacy_aliases": list(raw_config["legacy_aliases"]),
            }
        )
    return {
        "mode": resolved_mode,
        "policy_name": policy["policy_name"],
        "policy_version": int(policy["version"]),
        "summary": policy["summary"],
        "hard_gate_profile": profile_name,
        "hard_gate_profile_summary": profile["summary"],
        "hard_gate_risk_classes": hard_gate_risk_classes,
        "soft_gate_risk_classes": soft_gate_risk_classes,
        "soft_gate_preferred_actions": list(policy["soft_gate_defaults"]["preferred_actions"]),
        "soft_gate_terminal_actions": list(policy["soft_gate_defaults"]["terminal_actions"]),
        "gate_risk_classes": gate_risk_classes,
        "budget_controls": dict(policy["budget_controls"]),
        "failure_policy": dict(policy["failure_policy"]),
    }


def build_gate_event(
    risk_class: str,
    reason: str,
    *,
    mode: str | None = None,
    gates_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = resolve_gate_contract(mode=mode, gates_policy=gates_policy)
    risk_entry = next((item for item in contract["gate_risk_classes"] if item["id"] == risk_class), None)
    if risk_entry is None:
        raise KeyError(f"Unknown gate risk class `{risk_class}`.")
    gate = str(risk_entry["active_gate"])
    return {
        "gate": gate,
        "status": "blocked" if gate == "hard" else "deferred",
        "risk_class": str(risk_entry["id"]),
        "label": str(risk_entry["label"]),
        "reason": str(reason),
        "default_response": str(risk_entry["default_response"]),
        "preferred_actions": list(risk_entry["preferred_actions"]),
        "hard_gate_profile": str(contract["hard_gate_profile"]),
    }


__all__ = [
    "DEFAULT_GATES_PATH",
    "build_gate_event",
    "load_gate_policy",
    "normalize_gate_policy",
    "resolve_gate_contract",
]
