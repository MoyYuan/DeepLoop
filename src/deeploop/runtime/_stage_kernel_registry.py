from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

from deeploop.core.paths import REPO_ROOT as DEEPLOOP_REPO_ROOT

STAGE_REGISTRY_CONTRACT_PATH = DEEPLOOP_REPO_ROOT / "configs" / "runtime" / "stage-kernel-registry.yaml"


def get_stage_registry(kernels: dict[str, Any]) -> dict[str, Any]:
    return dict(kernels)


def run_stage_from_config(
    stage_id: str,
    config_path: Path,
    *,
    adapter: Any | None = None,
    adapter_spec: str | None = None,
    kernels: dict[str, Any],
    adapter_loader: Callable[[str | None], Any],
) -> Any:
    resolved_adapter = adapter or adapter_loader(adapter_spec)
    kernel = kernels[stage_id]
    return kernel.runner(Path(config_path).resolve(), resolved_adapter)


def load_stage_adapter(adapter_spec: str | None) -> Any:
    if not adapter_spec:
        raise ValueError("adapter_spec is required when an adapter object is not provided")
    module_name, _, factory_name = adapter_spec.partition(":")
    if not module_name or not factory_name:
        raise ValueError("adapter_spec must be in the form module.path:factory")
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name)
    adapter = factory()
    return adapter


def load_stage_registry_contract(*, load_yaml: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
    return load_yaml(STAGE_REGISTRY_CONTRACT_PATH)
