from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from deeploop.core.paths import REPO_ROOT as DEEPLOOP_REPO_ROOT

BACKEND_POLICY_PATH = DEEPLOOP_REPO_ROOT / "configs" / "runtime" / "backend-policy.yaml"


def runtime_context_from_env(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    resolved_env = os.environ if env is None else env
    entry_id = resolved_env.get("DEEPLOOP_RUNTIME_ENTRY_ID")
    attempt = resolved_env.get("DEEPLOOP_RUNTIME_ATTEMPT")
    recovery_mode = resolved_env.get("DEEPLOOP_RUNTIME_RECOVERY_MODE")
    history_path = resolved_env.get("DEEPLOOP_RUNTIME_HISTORY_PATH")
    if not any((entry_id, attempt, recovery_mode, history_path)):
        return {}
    context: dict[str, Any] = {}
    if entry_id:
        context["entry_id"] = entry_id
    if attempt and attempt.isdigit():
        context["attempt"] = int(attempt)
    if recovery_mode:
        context["recovery_mode"] = recovery_mode
    if history_path:
        context["history_path"] = history_path
    return context


def normalize_backend_name(backend: str) -> str:
    lowered = str(backend or "").strip().lower()
    if lowered in {"transformers", "local-transformers"}:
        return "local-transformers"
    return lowered


def resolve_execution_backend(
    *,
    requested_backend: str,
    preferred_backend: str,
    backend_policy: dict[str, Any],
) -> str:
    resolved_backend = normalize_backend_name(requested_backend)
    if not resolved_backend:
        resolved_backend = normalize_backend_name(str(backend_policy.get("primary_local_inference_backend", "")))
    if not resolved_backend:
        resolved_backend = normalize_backend_name(preferred_backend)
    return resolved_backend


def load_backend_policy(*, load_yaml: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
    loaded = load_yaml(BACKEND_POLICY_PATH)
    return loaded if isinstance(loaded, dict) else {}


def known_runtime_backends() -> set[str]:
    return {"local-transformers", "vllm", "mock-entailment", "mock-contradiction"}


def module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def available_runtime_backends() -> dict[str, dict[str, Any]]:
    return {
        "local-transformers": {
            "available": module_available("torch") and module_available("transformers"),
            "reason": "requires torch and transformers",
        },
        "vllm": {
            "available": module_available("torch") and module_available("vllm"),
            "reason": "requires torch and vllm",
        },
        "mock-entailment": {"available": True, "reason": "builtin-mock-backend"},
        "mock-contradiction": {"available": True, "reason": "builtin-mock-backend"},
    }


def backend_search_order(
    *,
    requested_backend: str,
    preferred_backend: str,
    defaults: dict[str, Any],
    backend_policy: dict[str, Any],
) -> list[str]:
    ordered: list[str] = []
    for candidate in [
        requested_backend,
        preferred_backend,
        normalize_backend_name(str(backend_policy.get("primary_local_inference_backend", ""))),
        normalize_backend_name(str(backend_policy.get("secondary_local_inference_backend", ""))),
        *[normalize_backend_name(str(item)) for item in defaults.get("backend_priority", [])],
    ]:
        if candidate and candidate not in ordered and candidate in known_runtime_backends():
            ordered.append(candidate)
    return ordered or ["local-transformers"]
