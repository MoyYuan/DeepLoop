from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

import yaml

from deeploop.core.paths import REPO_ROOT as DEEPLOOP_REPO_ROOT, RUNS_DIR
from deeploop.runtime import (
    _stage_kernel_registry as stage_kernel_registry,
    _stage_kernel_reporting as stage_kernel_reporting,
    _stage_kernel_resolution as stage_kernel_resolution,
)

logger = logging.getLogger(__name__)

STAGE_REGISTRY_CONTRACT_PATH = stage_kernel_registry.STAGE_REGISTRY_CONTRACT_PATH
INFERENCE_FAMILY_CONTRACT_PATH = DEEPLOOP_REPO_ROOT / "configs" / "execution-profiles" / "inference-families.yaml"
ZONE_ORDER = ("early", "mid", "late")
AUTOTUNE_CACHE_PATH = RUNS_DIR / "runtime-autotune-cache" / "batch_size_cache.json"
UNKNOWN_MISSION_ID = "unknown-mission"

@dataclass
class KernelRunResult:
    stage_id: str
    status: str
    output_dir: Path
    manifest_path: Path
    summary_path: Path | None = None
    artifacts: dict[str, Path] = field(default_factory=dict)

class StageAdapter(Protocol):
    name: str
    substrate_name: str
    substrate_repo_root: Path
    runs_root: Path
    prompt_template_id: str
    parser_id: str

    def default_promotion_manifest(self) -> Path: ...

    def load_promotion_manifest(self, path: Path) -> dict: ...

    def resolve_dataset_files(
        self,
        manifest: dict,
        *,
        tiers: list[str] | None = None,
        split_kinds: list[str] | None = None,
        split_families: list[str] | None = None,
    ) -> list[dict]: ...

    def iter_examples(self, paths: Iterable[Path], *, limit: int | None = None) -> Iterable[dict]: ...

    def include_example(
        self,
        example: dict,
        *,
        lexicalizations: list[str] | None = None,
        rule_families: list[str] | None = None,
    ) -> bool: ...

    def format_prompt(self, example: dict) -> str: ...

    def parse_prediction(self, text: str) -> str: ...

    def compute_metrics(self, records: list[dict]) -> dict: ...

    def build_prediction_record(
        self,
        example: dict,
        *,
        predicted_label: str,
        raw_output: str,
        source_metadata: dict,
    ) -> dict: ...

@dataclass(frozen=True)
class StageKernel:
    stage_id: str
    runner: Any
    summary: str

@dataclass(frozen=True)
class ExecutionProfilePlan:
    requested_profile: str
    resolved_profile: str
    source: str
    requested_backend: str
    resolved_backend: str
    contract_backend: str | None
    context_bucket: str | None
    prompt_token_budget: int | None
    max_new_tokens: int
    batch_probe_order: tuple[int, ...]
    fallback_ladder: tuple[str, ...]
    contract_metrics: tuple[str, ...]
    gpu_memory_headroom_gb: float | None
    applies_to_model: bool
    notes: tuple[str, ...] = ()
    contract_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_profile": self.requested_profile,
            "resolved_profile": self.resolved_profile,
            "source": self.source,
            "requested_backend": self.requested_backend,
            "resolved_backend": self.resolved_backend,
            "contract_backend": self.contract_backend,
            "context_bucket": self.context_bucket,
            "prompt_token_budget": self.prompt_token_budget,
            "max_new_tokens": self.max_new_tokens,
            "batch_probe_order": list(self.batch_probe_order),
            "fallback_ladder": list(self.fallback_ladder),
            "contract_metrics": list(self.contract_metrics),
            "gpu_memory_headroom_gb": self.gpu_memory_headroom_gb,
            "applies_to_model": self.applies_to_model,
            "notes": list(self.notes),
            "contract_path": self.contract_path,
        }

def _normalize_generation_config(
    decode_config: dict[str, Any] | None,
    *,
    max_new_tokens: int,
) -> dict[str, Any]:
    raw = decode_config if isinstance(decode_config, dict) else {}
    do_sample = bool(raw.get("do_sample", False))
    return {
        "do_sample": do_sample,
        "temperature": float(raw.get("temperature", 0.0 if not do_sample else 1.0)),
        "top_p": float(raw.get("top_p", 1.0)),
        "repetition_penalty": float(raw.get("repetition_penalty", 1.0)),
        "max_new_tokens": int(raw.get("max_new_tokens", max_new_tokens) or max_new_tokens),
    }

class MockPredictor:
    batch_size = 64

    def __init__(self, label: str) -> None:
        self.label = label
        self.batch_probe_order = [int(self.batch_size)]
        self.prompt_token_budget: int | None = None
        self.runtime_stats = _empty_runtime_stats()

    def predict(self, prompt: str) -> str:
        _ = prompt
        return json.dumps({"label": self.label})

    def predict_many(self, prompts: list[str]) -> list[str]:
        return [self.predict(prompt) for prompt in prompts]

class TransformersPredictor:
    def __init__(
        self,
        model_path: str,
        *,
        max_new_tokens: int = 32,
        dtype: str = "float16",
        runtime_contract: dict[str, Any] | None = None,
        prompt_token_budget: int | None = None,
        batch_probe_order: Iterable[int] | None = None,
        decode_config: dict[str, Any] | None = None,
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - optional runtime path
            raise RuntimeError(
                "local-transformers backend requires torch and transformers to be installed."
            ) from exc

        resolved_model_path = str(Path(model_path).expanduser())
        dtype_map = {
            "float16": getattr(torch, "float16"),
            "bfloat16": getattr(torch, "bfloat16"),
            "float32": getattr(torch, "float32"),
            "auto": "auto",
        }
        torch_dtype = dtype_map.get(dtype, getattr(torch, "float16"))
        self.tokenizer = _configure_generation_tokenizer(
            AutoTokenizer.from_pretrained(resolved_model_path, trust_remote_code=True)
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            resolved_model_path,
            trust_remote_code=True,
            torch_dtype=torch_dtype,
            device_map="auto",
        )
        self.torch = torch
        self.max_new_tokens = max_new_tokens
        default_batch_size = _default_transformers_batch_size(resolved_model_path)
        self.batch_probe_order = _normalize_batch_probe_order(batch_probe_order, default=default_batch_size)
        self._batch_probe_index = 0
        self.batch_size = self.batch_probe_order[0]
        self.prompt_token_budget = prompt_token_budget
        self.runtime_stats = _empty_runtime_stats()
        self.generation_config = _normalize_generation_config(decode_config, max_new_tokens=self.max_new_tokens)
        contract = runtime_contract if isinstance(runtime_contract, dict) else {}
        tokenizer_chat_template = getattr(self.tokenizer, "chat_template", None)
        self.use_chat_template = (
            bool(contract.get("use_chat_template"))
            and callable(getattr(self.tokenizer, "apply_chat_template", None))
            and bool(tokenizer_chat_template)
        )
        self.stop_markers = tuple(str(item) for item in contract.get("stop_markers", ()) if str(item).strip())
        self.bad_words_ids = [
            token_ids
            for token_ids in (
                self.tokenizer.encode("<think>", add_special_tokens=False),
                self.tokenizer.encode("</think>", add_special_tokens=False),
            )
            if token_ids
        ]
        if self.torch.cuda.is_available():  # pragma: no branch - environment dependent
            try:
                self.torch.cuda.reset_peak_memory_stats()
            except Exception:  # pragma: no cover - optional runtime path
                pass

    def predict(self, prompt: str) -> str:  # pragma: no cover - optional runtime path
        return self.predict_many([prompt])[0]

    def predict_many(self, prompts: list[str]) -> list[str]:  # pragma: no cover - optional runtime path
        outputs: list[str] = []
        index = 0
        current_batch_size = max(1, int(self.batch_probe_order[self._batch_probe_index]))
        while index < len(prompts):
            batch = prompts[index : index + current_batch_size]
            try:
                outputs.extend(self._predict_batch(batch))
                index += len(batch)
            except RuntimeError as exc:
                if "out of memory" not in str(exc).lower() or self._batch_probe_index >= len(self.batch_probe_order) - 1:
                    self._update_peak_vram()
                    raise
                if self.torch.cuda.is_available():
                    self._update_peak_vram()
                    self.torch.cuda.empty_cache()
                next_batch_size = max(1, int(self.batch_probe_order[self._batch_probe_index + 1]))
                self.runtime_stats["oom_retries"] = int(self.runtime_stats.get("oom_retries", 0)) + 1
                self.runtime_stats.setdefault("batch_adjustments", []).append(
                    {
                        "reason": "oom",
                        "from_batch_size": current_batch_size,
                        "to_batch_size": next_batch_size,
                    }
                )
                self._batch_probe_index += 1
                current_batch_size = next_batch_size
        self.batch_size = min(self.batch_size, current_batch_size)
        self.runtime_stats["selected_batch_size"] = int(self.batch_size)
        return outputs

    def _predict_batch(self, prompts: list[str]) -> list[str]:
        render_prompts = prompts
        if self.use_chat_template:
            render_prompts = [
                self.tokenizer.apply_chat_template(
                    [{"role": "user", "content": prompt}],
                    tokenize=False,
                    add_generation_prompt=True,
                )
                for prompt in prompts
            ]
        tokenization_kwargs: dict[str, Any] = {"return_tensors": "pt", "padding": True, "truncation": True}
        if self.prompt_token_budget:
            tokenization_kwargs["max_length"] = int(self.prompt_token_budget)
        inputs = self.tokenizer(render_prompts, **tokenization_kwargs).to(self.model.device)
        prompt_width = inputs["input_ids"].shape[1]
        generation_kwargs: dict[str, Any] = {
            "max_new_tokens": int(self.generation_config["max_new_tokens"]),
            "do_sample": bool(self.generation_config["do_sample"]),
            "pad_token_id": self.tokenizer.pad_token_id,
            "eos_token_id": self.tokenizer.eos_token_id,
            "bad_words_ids": self.bad_words_ids or None,
            "repetition_penalty": float(self.generation_config["repetition_penalty"]),
        }
        if generation_kwargs["do_sample"]:
            generation_kwargs["temperature"] = float(self.generation_config["temperature"])
            generation_kwargs["top_p"] = float(self.generation_config["top_p"])
        outputs = self.model.generate(
            **inputs,
            **generation_kwargs,
        )
        decoded: list[str] = []
        for row in range(len(prompts)):
            text = self.tokenizer.decode(outputs[row][prompt_width:], skip_special_tokens=True)
            decoded.append(_truncate_text_markers(text.strip(), self.stop_markers))
        self._update_peak_vram()
        return decoded

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def _update_peak_vram(self) -> None:
        if not self.torch.cuda.is_available():  # pragma: no cover - environment dependent
            return
        try:
            peak_vram_mb = round(float(self.torch.cuda.max_memory_allocated()) / (1024 * 1024), 3)
        except Exception:  # pragma: no cover - optional runtime path
            return
        current_peak = self.runtime_stats.get("peak_vram_mb")
        if current_peak is None or peak_vram_mb > float(current_peak):
            self.runtime_stats["peak_vram_mb"] = peak_vram_mb

class VllmPredictor:
    def __init__(
        self,
        model_path: str,
        *,
        max_new_tokens: int = 32,
        dtype: str = "float16",
        runtime_contract: dict[str, Any] | None = None,
        prompt_token_budget: int | None = None,
        batch_probe_order: Iterable[int] | None = None,
        decode_config: dict[str, Any] | None = None,
    ) -> None:
        try:
            import torch
            from vllm import LLM, SamplingParams
        except ImportError as exc:  # pragma: no cover - optional runtime path
            raise RuntimeError("vllm backend requires torch and vllm to be installed.") from exc

        resolved_model_path = str(Path(model_path).expanduser())
        self.llm = LLM(
            model=resolved_model_path,
            dtype=dtype or "auto",
            trust_remote_code=True,
        )
        self.SamplingParams = SamplingParams
        self.torch = torch
        self.tokenizer = _configure_generation_tokenizer(self.llm.get_tokenizer())
        self.max_new_tokens = max_new_tokens
        default_batch_size = _default_transformers_batch_size(resolved_model_path)
        self.batch_probe_order = _normalize_batch_probe_order(batch_probe_order, default=default_batch_size)
        self._batch_probe_index = 0
        self.batch_size = self.batch_probe_order[0]
        self.prompt_token_budget = prompt_token_budget
        self.runtime_stats = _empty_runtime_stats()
        self.generation_config = _normalize_generation_config(decode_config, max_new_tokens=self.max_new_tokens)
        contract = runtime_contract if isinstance(runtime_contract, dict) else {}
        tokenizer_chat_template = getattr(self.tokenizer, "chat_template", None)
        self.use_chat_template = (
            bool(contract.get("use_chat_template"))
            and callable(getattr(self.tokenizer, "apply_chat_template", None))
            and bool(tokenizer_chat_template)
        )
        self.stop_markers = tuple(str(item) for item in contract.get("stop_markers", ()) if str(item).strip())
        if self.torch.cuda.is_available():  # pragma: no branch - environment dependent
            try:
                self.torch.cuda.reset_peak_memory_stats()
            except Exception:  # pragma: no cover - optional runtime path
                pass

    def predict(self, prompt: str) -> str:  # pragma: no cover - optional runtime path
        return self.predict_many([prompt])[0]

    def predict_many(self, prompts: list[str]) -> list[str]:  # pragma: no cover - optional runtime path
        render_prompts = prompts
        if self.use_chat_template:
            render_prompts = [
                self.tokenizer.apply_chat_template(
                    [{"role": "user", "content": prompt}],
                    tokenize=False,
                    add_generation_prompt=True,
                )
                for prompt in prompts
            ]
        sampling_params = self.SamplingParams(
            temperature=float(self.generation_config["temperature"]),
            top_p=float(self.generation_config["top_p"]),
            max_tokens=int(self.generation_config["max_new_tokens"]),
            repetition_penalty=float(self.generation_config["repetition_penalty"]),
            stop=list(self.stop_markers) or None,
        )
        outputs = self.llm.generate(render_prompts, sampling_params, use_tqdm=False)
        decoded: list[str] = []
        for output in outputs:
            candidates = getattr(output, "outputs", None) or []
            text = candidates[0].text if candidates else ""
            decoded.append(_truncate_text_markers(str(text).strip(), self.stop_markers))
        self._update_peak_vram()
        return decoded

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def _update_peak_vram(self) -> None:
        if not self.torch.cuda.is_available():  # pragma: no cover - environment dependent
            return
        try:
            peak_vram_mb = round(float(self.torch.cuda.max_memory_allocated()) / (1024 * 1024), 3)
        except Exception:  # pragma: no cover - optional runtime path
            return
        current_peak = self.runtime_stats.get("peak_vram_mb")
        if current_peak is None or peak_vram_mb > float(current_peak):
            self.runtime_stats["peak_vram_mb"] = peak_vram_mb

def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))

def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

from deeploop.core.structured_io import load_json_object as _load_json  # noqa: E402
from deeploop.core.structured_io import write_json_object as _write_json  # noqa: E402

def _validate_manifest(manifest: dict) -> None:
    stage_kernel_reporting.validate_manifest(manifest, load_json=_load_json)

def _now_utc() -> str:
    return stage_kernel_reporting.now_utc()

def _normalize_notes(raw_notes: Any) -> list[str]:
    if raw_notes is None:
        return []
    if isinstance(raw_notes, str):
        return [raw_notes]
    if isinstance(raw_notes, list):
        notes: list[str] = []
        for item in raw_notes:
            notes.extend(_normalize_notes(item))
        return notes
    return [str(raw_notes)]

def _runtime_context() -> dict[str, Any]:
    return stage_kernel_resolution.runtime_context_from_env()

def _dataset_name(adapter: StageAdapter, promotion_manifest: dict) -> str:
    dataset_name = getattr(adapter, "dataset_name", None)
    if callable(dataset_name):
        return str(dataset_name(promotion_manifest))
    return str(promotion_manifest.get("dataset_id", adapter.substrate_name))

def _adapter_runtime_contract(adapter: StageAdapter) -> dict[str, Any]:
    runtime_contract = getattr(adapter, "runtime_contract", None)
    if callable(runtime_contract):
        resolved = runtime_contract()
        if isinstance(resolved, dict):
            return resolved
    return {}

def _configure_adapter_model_family(adapter: StageAdapter, model_cfg: dict[str, Any]) -> None:
    configure_model_family = getattr(adapter, "configure_model_family", None)
    if callable(configure_model_family):
        configure_model_family(model_cfg.get("family"))

def _configure_adapter_prompt(adapter: StageAdapter, prompt_cfg: dict[str, Any] | None) -> None:
    if not isinstance(prompt_cfg, dict):
        return
    template_id = prompt_cfg.get("template_id")
    if template_id is None:
        return
    configure_prompt_template = getattr(adapter, "configure_prompt_template", None)
    if callable(configure_prompt_template):
        configure_prompt_template(str(template_id))
        return
    try:
        setattr(adapter, "prompt_template_id", str(template_id))
    except (AttributeError, TypeError):
        return

def _empty_runtime_stats() -> dict[str, Any]:
    return {
        "oom_retries": 0,
        "peak_vram_mb": None,
        "batch_adjustments": [],
        "batch_requests": [],
    }

def _predictor_machine_fingerprint(predictor: Any) -> dict[str, Any]:
    torch_module = _predictor_torch_module(predictor)
    fingerprint: dict[str, Any] = {
        "gpu_available": False,
        "device_name": None,
        "cuda_capability": None,
        "total_vram_mb": None,
    }
    if torch_module is None or not torch_module.cuda.is_available():
        return fingerprint
    device_index = int(torch_module.cuda.current_device())
    props = torch_module.cuda.get_device_properties(device_index)
    capability = None
    get_capability = getattr(torch_module.cuda, "get_device_capability", None)
    if callable(get_capability):
        major, minor = get_capability(device_index)
        capability = f"{major}.{minor}"
    fingerprint.update(
        {
            "gpu_available": True,
            "device_name": str(getattr(props, "name", "")) or None,
            "cuda_capability": capability,
            "total_vram_mb": round(float(getattr(props, "total_memory", 0)) / (1024 * 1024), 3),
        }
    )
    return fingerprint

def _autotune_prompt_signature(predictor: Any, prompts: list[str]) -> dict[str, Any]:
    counts = [_count_tokens(prompt, predictor) for prompt in prompts]
    return {
        "prompt_count": len(prompts),
        "prompt_tokens_max": max(counts) if counts else 0,
        "prompt_tokens_avg": round(sum(counts) / len(counts), 3) if counts else 0.0,
    }

def _autotune_cache_key(
    predictor: Any,
    *,
    prompts: list[str],
    runtime_stats: dict[str, Any],
    batch_candidates: list[int],
) -> tuple[str, dict[str, Any]]:
    execution_plan = runtime_stats.get("execution_plan", {})
    model = runtime_stats.get("model", {})
    key_payload = {
        "schema_version": 1,
        "stage_id": runtime_stats.get("stage_id"),
        "backend": execution_plan.get("resolved_backend"),
        "model_family": model.get("family"),
        "model_identifier": model.get("identifier"),
        "dtype": model.get("dtype"),
        "context_bucket": execution_plan.get("context_bucket"),
        "prompt_token_budget": execution_plan.get("prompt_token_budget"),
        "max_new_tokens": execution_plan.get("max_new_tokens"),
        "gpu_memory_headroom_gb": execution_plan.get("gpu_memory_headroom_gb"),
        "batch_probe_order": sorted(batch_candidates),
        "machine": _predictor_machine_fingerprint(predictor),
        "prompt_signature": _autotune_prompt_signature(predictor, prompts),
    }
    return json.dumps(key_payload, sort_keys=True), key_payload

def _load_autotune_cache(cache_path: Path) -> dict[str, Any]:
    if not cache_path.exists():
        return {"schema_version": 1, "entries": {}}
    loaded = json.loads(cache_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return {"schema_version": 1, "entries": {}}
    entries = loaded.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    return {
        "schema_version": int(loaded.get("schema_version", 1) or 1),
        "entries": entries,
    }

def _write_autotune_cache_entry(cache_path: Path, *, cache_key: str, payload: dict[str, Any]) -> None:
    cache = _load_autotune_cache(cache_path)
    cache["entries"][cache_key] = payload
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(cache_path)

def _autotune_warnings(
    *,
    selected_result: dict[str, Any] | None,
    batch_candidates: list[int],
    total_vram_mb: float | None,
    headroom_target_mb: float | None,
) -> tuple[list[dict[str, Any]], float | None]:
    if selected_result is None:
        return [], None
    peak_vram_mb = selected_result.get("peak_vram_mb")
    if total_vram_mb in {None, 0} or peak_vram_mb is None:
        return [], None
    selected_peak_vram_utilization = round(float(peak_vram_mb) / float(total_vram_mb), 6)
    safe_ceiling_mb = max(float(total_vram_mb) - float(headroom_target_mb or 0.0), 0.0)
    warnings: list[dict[str, Any]] = []
    if batch_candidates and int(selected_result["batch_size"]) == max(batch_candidates) and safe_ceiling_mb > 0:
        safe_utilization = float(peak_vram_mb) / safe_ceiling_mb
        if safe_utilization < 0.6:
            warnings.append(
                {
                    "code": "underutilized-vram",
                    "message": "Selected batch remained well below the configured safe VRAM ceiling; the batch probe ladder may be too conservative.",
                    "peak_vram_mb": peak_vram_mb,
                    "safe_ceiling_mb": round(safe_ceiling_mb, 3),
                    "safe_utilization": round(safe_utilization, 6),
                }
            )
    return warnings, selected_peak_vram_utilization

def _module_available(module_name: str) -> bool:
    return stage_kernel_resolution.module_available(module_name)

def _runtime_capability_probe(
    predictor: Any,
    *,
    execution_plan: ExecutionProfilePlan,
    model: dict[str, Any],
) -> dict[str, Any]:
    backend_availability = _available_runtime_backends()
    selected_backend = str(execution_plan.resolved_backend or model.get("backend") or "").strip()
    probe = {
        "selected_backend": selected_backend,
        "contract_backend": execution_plan.contract_backend,
        "degraded_backend": bool(
            execution_plan.contract_backend and execution_plan.contract_backend != execution_plan.resolved_backend
        ),
        "backends": backend_availability,
        "machine": {
            "gpu_available": False,
            "gpu_count": 0,
            "device_name": None,
            "cuda_capability": None,
            "total_vram_mb": None,
            "free_vram_mb": None,
            "dtype_support": {
                "float16": str(model.get("dtype", "")).strip().lower() in {"", "float16", "auto"},
                "bfloat16": False,
            },
        },
    }
    torch_module = getattr(predictor, "torch", None)
    if torch_module is None or not bool(torch_module.cuda.is_available()):
        return probe
    device_index = int(torch_module.cuda.current_device())
    properties = torch_module.cuda.get_device_properties(device_index)
    free_bytes = None
    total_bytes = None
    if hasattr(torch_module.cuda, "mem_get_info"):
        free_bytes, total_bytes = torch_module.cuda.mem_get_info(device_index)
    capability = torch_module.cuda.get_device_capability(device_index)
    probe["machine"] = {
        "gpu_available": True,
        "gpu_count": int(torch_module.cuda.device_count()),
        "device_name": str(torch_module.cuda.get_device_name(device_index)),
        "cuda_capability": f"{capability[0]}.{capability[1]}",
        "total_vram_mb": round(float((total_bytes or properties.total_memory)) / (1024 * 1024), 3),
        "free_vram_mb": round(float(free_bytes) / (1024 * 1024), 3) if free_bytes is not None else None,
        "dtype_support": {
            "float16": True,
            "bfloat16": bool(
                getattr(torch_module.cuda, "is_bf16_supported", lambda *_args, **_kwargs: False)(device_index)
            ),
        },
    }
    return probe

def _predictor_torch_module(predictor: Any) -> Any | None:
    torch_module = getattr(predictor, "torch", None)
    if torch_module is None or not bool(torch_module.cuda.is_available()):
        return None
    return torch_module

def _predictor_total_vram_mb(predictor: Any) -> float | None:
    torch_module = _predictor_torch_module(predictor)
    if torch_module is None:
        return None
    device_index = int(torch_module.cuda.current_device())
    return round(float(torch_module.cuda.get_device_properties(device_index).total_memory) / (1024 * 1024), 3)

def _reset_predictor_peak_vram(predictor: Any) -> None:
    torch_module = _predictor_torch_module(predictor)
    if torch_module is None:
        return
    torch_module.cuda.reset_peak_memory_stats()

def _read_predictor_peak_vram_mb(predictor: Any) -> float | None:
    torch_module = _predictor_torch_module(predictor)
    if torch_module is None:
        return None
    return round(float(torch_module.cuda.max_memory_allocated()) / (1024 * 1024), 3)

def _clear_predictor_cuda_cache(predictor: Any) -> None:
    torch_module = _predictor_torch_module(predictor)
    if torch_module is None:
        return
    torch_module.cuda.empty_cache()

def _warmup_batch_prompts(prompts: list[str], batch_size: int) -> list[str]:
    if not prompts:
        return []
    seed_prompt = max(prompts, key=lambda item: len(str(item)))
    return [seed_prompt] * max(1, int(batch_size))

def _maybe_autotune_batch_size(predictor: Any, prompts: list[str]) -> Any:
    runtime_stats = dict(getattr(predictor, "runtime_stats", _empty_runtime_stats()))
    execution_plan = runtime_stats.get("execution_plan", {})
    batch_candidates = [int(value) for value in getattr(predictor, "batch_probe_order", []) if int(value) > 0]
    resolved_backend = str(execution_plan.get("resolved_backend") or "").strip()
    if resolved_backend.startswith("mock-"):
        runtime_stats["autotune"] = {
            "status": "skipped",
            "reason": "mock_backend",
        }
        predictor.runtime_stats = runtime_stats
        return predictor
    if not isinstance(execution_plan, dict) or len(batch_candidates) <= 1 or not prompts:
        runtime_stats["autotune"] = {
            "status": "skipped",
            "reason": "no_execution_plan_or_single_batch_candidate",
        }
        predictor.runtime_stats = runtime_stats
        return predictor
    candidate_results: list[dict[str, Any]] = []
    successful_results: list[dict[str, Any]] = []
    headroom_gb = execution_plan.get("gpu_memory_headroom_gb")
    total_vram_mb = _predictor_total_vram_mb(predictor)
    headroom_target_mb = float(headroom_gb) * 1024 if headroom_gb is not None else None
    cache_path = Path(runtime_stats.get("autotune_cache_path", AUTOTUNE_CACHE_PATH)).expanduser().resolve()
    cache_key, cache_key_payload = _autotune_cache_key(
        predictor,
        prompts=prompts,
        runtime_stats=runtime_stats,
        batch_candidates=batch_candidates,
    )
    cached_entry = _load_autotune_cache(cache_path).get("entries", {}).get(cache_key)
    cache_summary: dict[str, Any] = {
        "path": str(cache_path),
        "status": "miss",
        "key": cache_key_payload,
    }
    if isinstance(cached_entry, dict):
        cached_batch_size = int(cached_entry.get("selected_batch_size", 0) or 0)
        if cached_batch_size in batch_candidates:
            predictor.batch_size = cached_batch_size
            predictor.batch_probe_order = [
                cached_batch_size,
                *[candidate for candidate in batch_candidates if candidate < cached_batch_size],
            ]
            if hasattr(predictor, "_batch_probe_index"):
                predictor._batch_probe_index = 0
            selected_result = {
                "batch_size": cached_batch_size,
                "peak_vram_mb": cached_entry.get("peak_vram_mb"),
                "samples_per_s": cached_entry.get("samples_per_s"),
            }
            warnings, peak_vram_utilization = _autotune_warnings(
                selected_result=selected_result,
                batch_candidates=batch_candidates,
                total_vram_mb=total_vram_mb,
                headroom_target_mb=headroom_target_mb,
            )
            runtime_stats["selected_batch_size"] = cached_batch_size
            runtime_stats["autotune"] = {
                "status": "completed",
                "strategy": "cache-reuse",
                "selected_batch_size": cached_batch_size,
                "selected_peak_vram_mb": cached_entry.get("peak_vram_mb"),
                "selected_samples_per_s": cached_entry.get("samples_per_s"),
                "selected_peak_vram_utilization": peak_vram_utilization,
                "total_vram_mb": total_vram_mb,
                "headroom_target_mb": round(headroom_target_mb, 3) if headroom_target_mb is not None else None,
                "prompt_signature": cache_key_payload["prompt_signature"],
                "machine_fingerprint": cache_key_payload["machine"],
                "cache": {
                    **cache_summary,
                    "status": "hit",
                    "updated_at": cached_entry.get("updated_at"),
                },
                "warnings": warnings,
                "rejected_candidates": [],
            }
            predictor.runtime_stats = runtime_stats
            return predictor
        cache_summary["status"] = "stale"
        cache_summary["reason"] = "cached_batch_not_in_probe_order"
    batch_predict = getattr(predictor, "_predict_batch", None)
    for candidate_batch_size in batch_candidates:
        candidate_prompts = _warmup_batch_prompts(prompts, candidate_batch_size)
        start_time = time.monotonic()
        _reset_predictor_peak_vram(predictor)
        try:
            if callable(batch_predict):
                raw_outputs = list(batch_predict(candidate_prompts))
            else:
                previous_batch_size = int(getattr(predictor, "batch_size", candidate_batch_size) or candidate_batch_size)
                predictor.batch_size = int(candidate_batch_size)
                raw_outputs = list(predictor.predict_many(candidate_prompts))
                predictor.batch_size = previous_batch_size
        except RuntimeError as exc:
            if "out of memory" not in str(exc).lower():
                raise
            _clear_predictor_cuda_cache(predictor)
            candidate_results.append(
                {
                    "batch_size": int(candidate_batch_size),
                    "status": "oom",
                    "reason": "candidate_probe_oom",
                }
            )
            continue
        elapsed_s = max(time.monotonic() - start_time, 1e-9)
        generated_tokens_total = sum(_count_tokens(output, predictor) for output in raw_outputs)
        peak_vram_mb = _read_predictor_peak_vram_mb(predictor)
        within_headroom = (
            True
            if headroom_target_mb is None or total_vram_mb is None or peak_vram_mb is None
            else peak_vram_mb <= max(total_vram_mb - headroom_target_mb, 0.0)
        )
        result = {
            "batch_size": int(candidate_batch_size),
            "status": "ok" if within_headroom else "headroom_exceeded",
            "elapsed_s": round(elapsed_s, 6),
            "samples_per_s": round(len(candidate_prompts) / elapsed_s, 6),
            "toks_per_s": round(generated_tokens_total / elapsed_s, 6) if generated_tokens_total else 0.0,
            "peak_vram_mb": peak_vram_mb,
            "within_headroom": within_headroom,
        }
        candidate_results.append(result)
        if within_headroom:
            successful_results.append(result)
    selected_result = None
    if successful_results:
        selected_result = max(successful_results, key=lambda item: (item["batch_size"], item["samples_per_s"]))
    elif candidate_results:
        fallback_candidates = [item for item in candidate_results if item.get("status") == "ok"]
        if fallback_candidates:
            selected_result = max(fallback_candidates, key=lambda item: (item["batch_size"], item["samples_per_s"]))
    if selected_result is None:
        runtime_stats["autotune"] = {
            "status": "failed",
            "reason": "no_successful_batch_candidate",
            "candidates": candidate_results,
        }
        predictor.runtime_stats = runtime_stats
        return predictor
    selected_batch_size = int(selected_result["batch_size"])
    predictor.batch_size = selected_batch_size
    predictor.batch_probe_order = [
        selected_batch_size,
        *[candidate for candidate in batch_candidates if candidate < selected_batch_size],
    ]
    if hasattr(predictor, "_batch_probe_index"):
        predictor._batch_probe_index = 0
    rejected_candidates = [item for item in candidate_results if int(item.get("batch_size", 0) or 0) != selected_batch_size]
    warnings, peak_vram_utilization = _autotune_warnings(
        selected_result=selected_result,
        batch_candidates=batch_candidates,
        total_vram_mb=total_vram_mb,
        headroom_target_mb=headroom_target_mb,
    )
    _write_autotune_cache_entry(
        cache_path,
        cache_key=cache_key,
        payload={
            "updated_at": _now_utc(),
            "selected_batch_size": selected_batch_size,
            "peak_vram_mb": selected_result.get("peak_vram_mb"),
            "samples_per_s": selected_result.get("samples_per_s"),
            "toks_per_s": selected_result.get("toks_per_s"),
            "cache_key": cache_key_payload,
        },
    )
    runtime_stats["selected_batch_size"] = selected_batch_size
    runtime_stats["autotune"] = {
        "status": "completed",
        "strategy": "warmup-batch-search",
        "selected_batch_size": selected_batch_size,
        "selected_peak_vram_mb": selected_result.get("peak_vram_mb"),
        "selected_samples_per_s": selected_result.get("samples_per_s"),
        "selected_toks_per_s": selected_result.get("toks_per_s"),
        "selected_peak_vram_utilization": peak_vram_utilization,
        "total_vram_mb": total_vram_mb,
        "headroom_target_mb": round(headroom_target_mb, 3) if headroom_target_mb is not None else None,
        "prompt_signature": cache_key_payload["prompt_signature"],
        "machine_fingerprint": cache_key_payload["machine"],
        "cache": cache_summary,
        "warnings": warnings,
        "rejected_candidates": rejected_candidates,
        "candidates": candidate_results,
    }
    predictor.runtime_stats = runtime_stats
    return predictor

def _normalize_batch_probe_order(batch_probe_order: Iterable[int] | None, *, default: int) -> list[int]:
    resolved: list[int] = []
    for value in batch_probe_order or ():
        try:
            batch_size = max(1, int(value))
        except (TypeError, ValueError):
            continue
        if batch_size not in resolved:
            resolved.append(batch_size)
    if not resolved:
        resolved.append(max(1, int(default)))
    return resolved

def _estimate_token_count(text: str) -> int:
    stripped = str(text).strip()
    if not stripped:
        return 0
    whitespace_tokens = len([token for token in stripped.split() if token])
    char_tokens = math.ceil(len(stripped) / 4)
    return max(1, whitespace_tokens, char_tokens)

def _count_tokens(text: str, predictor: Any, *, clamp: int | None = None) -> int:
    token_counter = getattr(predictor, "count_tokens", None)
    if callable(token_counter):
        try:
            count = int(token_counter(text))
        except Exception:
            count = _estimate_token_count(text)
    else:
        count = _estimate_token_count(text)
    if clamp is not None:
        count = min(count, int(clamp))
    return max(0, count)

def _resolve_profile_backend(backend: str) -> str:
    return stage_kernel_resolution.normalize_backend_name(backend)

def _load_backend_policy() -> dict[str, Any]:
    return stage_kernel_resolution.load_backend_policy(load_yaml=_load_yaml)

def _known_runtime_backends() -> set[str]:
    return stage_kernel_resolution.known_runtime_backends()

def _available_runtime_backends() -> dict[str, dict[str, Any]]:
    return stage_kernel_resolution.available_runtime_backends()

def _backend_search_order(
    *,
    requested_backend: str,
    preferred_backend: str,
    defaults: dict[str, Any],
) -> list[str]:
    return stage_kernel_resolution.backend_search_order(
        requested_backend=requested_backend,
        preferred_backend=preferred_backend,
        defaults=defaults,
        backend_policy=_load_backend_policy(),
    )

def _model_profile_aliases(model_cfg: dict[str, Any]) -> tuple[str, ...]:
    aliases: list[str] = []
    for candidate in (
        model_cfg.get("family"),
        model_cfg.get("identifier"),
        model_cfg.get("checkpoint"),
        model_cfg.get("label"),
    ):
        if not candidate:
            continue
        text = str(candidate).strip().lower()
        if not text:
            continue
        aliases.append(text)
        aliases.append(Path(text).name)
    return tuple(dict.fromkeys(aliases))

def _profile_applies_to_model(profile: dict[str, Any], model_cfg: dict[str, Any]) -> bool:
    applies_to = [str(item).strip().lower() for item in profile.get("applies_to", []) if str(item).strip()]
    if not applies_to:
        return True
    aliases = _model_profile_aliases(model_cfg)
    return any(target in alias for target in applies_to for alias in aliases)

def _select_context_bucket(context_buckets: dict[str, Any], prompts: list[str]) -> str | None:
    candidates: list[tuple[int, str]] = []
    for bucket_id, bucket_cfg in context_buckets.items():
        try:
            prompt_tokens = int(bucket_cfg.get("prompt_tokens", 0))
        except (TypeError, ValueError):
            continue
        candidates.append((prompt_tokens, str(bucket_id)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    observed_max_prompt = max((_estimate_token_count(prompt) for prompt in prompts), default=0)
    for prompt_budget, bucket_id in candidates:
        if observed_max_prompt <= prompt_budget:
            return bucket_id
    return candidates[-1][1]

def _context_bucket_candidates(context_buckets: dict[str, Any], prompts: list[str]) -> list[str]:
    candidates: list[tuple[int, str]] = []
    observed_max_prompt = max((_estimate_token_count(prompt) for prompt in prompts), default=0)
    for bucket_id, bucket_cfg in context_buckets.items():
        try:
            prompt_tokens = int(bucket_cfg.get("prompt_tokens", 0))
        except (TypeError, ValueError):
            continue
        if prompt_tokens and observed_max_prompt <= prompt_tokens:
            candidates.append((prompt_tokens, str(bucket_id)))
    candidates.sort(key=lambda item: item[0])
    return [bucket_id for _, bucket_id in candidates]

def _max_new_token_candidates(base_max_new_tokens: int, *, fallback_ladder: tuple[str, ...]) -> list[int]:
    resolved = [max(1, int(base_max_new_tokens))]
    if "lower max new tokens" not in fallback_ladder:
        return resolved
    current = resolved[0]
    while current > 64:
        current = max(64, current // 2)
        if current not in resolved:
            resolved.append(current)
        if current == 64:
            break
    return resolved

def _execution_profile_contract(
    execution_profile: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any], tuple[str, ...], tuple[str, ...]]:
    contract = _load_yaml(INFERENCE_FAMILY_CONTRACT_PATH)
    defaults = contract.get("defaults", {}) if isinstance(contract, dict) else {}
    fallback_ladder = tuple(str(item) for item in defaults.get("fallback_ladder", []) if str(item).strip())
    contract_metrics = tuple(str(item) for item in defaults.get("metrics", []) if str(item).strip())
    profiles = contract.get("profiles", []) if isinstance(contract, dict) else []
    profile = next((item for item in profiles if str(item.get("id")) == str(execution_profile)), None)
    return contract, profile if isinstance(profile, dict) else None, defaults, fallback_ladder, contract_metrics

def _build_execution_profile_plan(
    execution_profile: str,
    *,
    model_cfg: dict[str, Any],
    defaults: dict[str, Any],
    fallback_ladder: tuple[str, ...],
    contract_metrics: tuple[str, ...],
    profile: dict[str, Any] | None,
    resolved_backend: str | None = None,
    selected_bucket: str | None = None,
    resolved_max_new_tokens: int | None = None,
) -> ExecutionProfilePlan:
    requested_backend = str(model_cfg.get("backend", "")).strip()
    requested_max_new_tokens = int(model_cfg.get("max_new_tokens", 32) or 32)
    if not isinstance(profile, dict):
        return ExecutionProfilePlan(
            requested_profile=str(execution_profile),
            resolved_profile=str(execution_profile),
            source="explicit-config",
            requested_backend=requested_backend,
            resolved_backend=resolved_backend or requested_backend,
            contract_backend=None,
            context_bucket=None,
            prompt_token_budget=None,
            max_new_tokens=resolved_max_new_tokens if resolved_max_new_tokens is not None else requested_max_new_tokens,
            batch_probe_order=(),
            fallback_ladder=fallback_ladder,
            contract_metrics=contract_metrics,
            gpu_memory_headroom_gb=None,
            applies_to_model=True,
            notes=("No machine-readable inference-family profile matched this execution_profile.",),
            contract_path=str(INFERENCE_FAMILY_CONTRACT_PATH),
        )
    preferred_backend = _resolve_profile_backend(str(profile.get("preferred_backend", "")).strip())
    applies_to_model = _profile_applies_to_model(profile, model_cfg)
    notes: list[str] = []
    if not applies_to_model:
        notes.append("Execution profile was requested explicitly but does not match the configured model identifier.")
    context_buckets = profile.get("context_buckets", {})
    bucket_id = selected_bucket
    bucket_cfg = context_buckets.get(bucket_id, {}) if isinstance(context_buckets, dict) and bucket_id else {}
    prompt_token_budget = bucket_cfg.get("prompt_tokens")
    max_new_tokens = requested_max_new_tokens
    if bucket_cfg.get("max_new_tokens") is not None:
        max_new_tokens = min(max_new_tokens, int(bucket_cfg["max_new_tokens"]))
    if resolved_max_new_tokens is not None:
        max_new_tokens = min(max_new_tokens, int(resolved_max_new_tokens))
    batch_probe_order = _normalize_batch_probe_order(
        bucket_cfg.get("batch_probe_order"),
        default=_default_transformers_batch_size(str(model_cfg.get("identifier", ""))),
    )
    backend = _resolve_profile_backend(resolved_backend or requested_backend or preferred_backend)
    if preferred_backend and preferred_backend != backend:
        notes.append(f"Profile-preferred backend `{preferred_backend}` resolved to `{backend}`.")
    return ExecutionProfilePlan(
        requested_profile=str(execution_profile),
        resolved_profile=str(profile.get("id", execution_profile)),
        source="inference-family-contract",
        requested_backend=requested_backend,
        resolved_backend=backend,
        contract_backend=preferred_backend or None,
        context_bucket=bucket_id,
        prompt_token_budget=int(prompt_token_budget) if prompt_token_budget is not None else None,
        max_new_tokens=max_new_tokens,
        batch_probe_order=tuple(batch_probe_order),
        fallback_ladder=fallback_ladder,
        contract_metrics=contract_metrics,
        gpu_memory_headroom_gb=(
            float(defaults["gpu_memory_headroom_gb"]) if defaults.get("gpu_memory_headroom_gb") is not None else None
        ),
        applies_to_model=applies_to_model,
        notes=tuple(notes),
        contract_path=str(INFERENCE_FAMILY_CONTRACT_PATH),
    )

def _execution_plan_search_candidates(
    execution_profile: str,
    *,
    model_cfg: dict[str, Any],
    prompts: list[str],
    base_plan: ExecutionProfilePlan,
) -> list[ExecutionProfilePlan]:
    _contract, profile, defaults, fallback_ladder, contract_metrics = _execution_profile_contract(execution_profile)
    if not isinstance(profile, dict):
        return [base_plan]
    available_backends = _available_runtime_backends()
    backend_candidates = [
        backend
        for backend in _backend_search_order(
            requested_backend=_resolve_profile_backend(str(model_cfg.get("backend", "")).strip()),
            preferred_backend=_resolve_profile_backend(str(profile.get("preferred_backend", "")).strip()),
            defaults=defaults,
        )
        if bool(available_backends.get(backend, {}).get("available"))
    ]
    context_buckets = profile.get("context_buckets", {}) if isinstance(profile.get("context_buckets"), dict) else {}
    bucket_candidates = _context_bucket_candidates(context_buckets, prompts)
    if base_plan.context_bucket and base_plan.context_bucket not in bucket_candidates:
        bucket_candidates.insert(0, str(base_plan.context_bucket))
    if not bucket_candidates and base_plan.context_bucket:
        bucket_candidates = [str(base_plan.context_bucket)]
    candidates: list[ExecutionProfilePlan] = []
    seen: set[tuple[str, str | None, int]] = set()
    for bucket_id in bucket_candidates:
        bucket_cfg = context_buckets.get(bucket_id, {})
        requested_max_new_tokens = int(model_cfg.get("max_new_tokens", 32) or 32)
        bucket_max_new_tokens = int(bucket_cfg.get("max_new_tokens", requested_max_new_tokens) or requested_max_new_tokens)
        for max_new_tokens in _max_new_token_candidates(
            min(requested_max_new_tokens, bucket_max_new_tokens),
            fallback_ladder=fallback_ladder,
        ):
            for backend in backend_candidates:
                candidate = _build_execution_profile_plan(
                    execution_profile,
                    model_cfg=model_cfg,
                    defaults=defaults,
                    fallback_ladder=fallback_ladder,
                    contract_metrics=contract_metrics,
                    profile=profile,
                    resolved_backend=backend,
                    selected_bucket=bucket_id,
                    resolved_max_new_tokens=max_new_tokens,
                )
                key = (candidate.resolved_backend, candidate.context_bucket, candidate.max_new_tokens)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(candidate)
    if not candidates:
        return [base_plan]
    base_key = (base_plan.resolved_backend, base_plan.context_bucket, base_plan.max_new_tokens)
    return [base_plan, *[candidate for candidate in candidates if (candidate.resolved_backend, candidate.context_bucket, candidate.max_new_tokens) != base_key]]

def _selected_autotune_metric(autotune: dict[str, Any], field: str) -> float | None:
    selected_batch_size = autotune.get("selected_batch_size")
    if selected_batch_size is not None:
        for candidate in autotune.get("candidates", []):
            if int(candidate.get("batch_size", 0) or 0) == int(selected_batch_size):
                value = candidate.get(field)
                if value is not None:
                    return float(value)
    direct_value = autotune.get(f"selected_{field}")
    if direct_value is None:
        return None
    return float(direct_value)

def _autotune_candidate_rank(
    *,
    candidate_plan: ExecutionProfilePlan,
    base_plan: ExecutionProfilePlan,
    selected_batch_size: int,
    selected_samples_per_s: float,
    backend_rank: dict[str, int],
) -> tuple[int, int, int, float, int]:
    return (
        int(candidate_plan.max_new_tokens == base_plan.max_new_tokens),
        int(candidate_plan.context_bucket == base_plan.context_bucket),
        int(selected_batch_size),
        float(selected_samples_per_s),
        -int(backend_rank.get(candidate_plan.resolved_backend, 999)),
    )

def _autotune_execution_plan(
    stage_id: str,
    *,
    execution_profile: str,
    model_cfg: dict[str, Any],
    prompts: list[str],
    runtime_contract: dict[str, Any],
    decode_config: dict[str, Any] | None = None,
) -> tuple[ExecutionProfilePlan, Any]:
    base_plan = _resolve_execution_profile(execution_profile, model_cfg=model_cfg, prompts=prompts)
    candidates = _execution_plan_search_candidates(
        execution_profile,
        model_cfg=model_cfg,
        prompts=prompts,
        base_plan=base_plan,
    )
    base_predictor = None
    base_build_error: Exception | None = None
    try:
        base_predictor = _build_predictor(
            backend=base_plan.resolved_backend,
            identifier=str(model_cfg["identifier"]),
                dtype=str(model_cfg.get("dtype", "float16")),
                max_new_tokens=int(base_plan.max_new_tokens),
                runtime_contract=runtime_contract,
                execution_plan=base_plan,
                decode_config=decode_config,
            )
        base_predictor = _attach_runtime_context(base_predictor, stage_id=stage_id, model=model_cfg)
    except (RuntimeError, OSError, ValueError) as exc:
        logger.warning("Base predictor build failed during autotune: %s", exc)
        base_build_error = exc
    if len(candidates) <= 1 or base_plan.resolved_backend.startswith("mock-"):
        if base_predictor is None:
            raise RuntimeError(
                f"Unable to initialize backend `{base_plan.resolved_backend}` for execution_profile `{execution_profile}`."
            ) from base_build_error
        runtime_stats = dict(getattr(base_predictor, "runtime_stats", _empty_runtime_stats()))
        runtime_stats["execution_search"] = {
            "status": "skipped",
            "reason": "single_candidate_or_mock_backend",
            "candidate_count": len(candidates),
            "selected_backend": base_plan.resolved_backend,
            "selected_context_bucket": base_plan.context_bucket,
            "selected_max_new_tokens": base_plan.max_new_tokens,
        }
        base_predictor.runtime_stats = runtime_stats
        return base_plan, base_predictor
    preview_prompts = prompts[: min(len(prompts), 4)]
    defaults = _execution_profile_contract(execution_profile)[2]
    backend_rank = {
        backend: index
        for index, backend in enumerate(
            _backend_search_order(
                requested_backend=_resolve_profile_backend(str(model_cfg.get("backend", "")).strip()),
                preferred_backend=base_plan.contract_backend or "",
                defaults=defaults,
            )
        )
    }
    candidate_records: list[dict[str, Any]] = []
    best_rank: tuple[int, int, int, float, int] | None = None
    best_plan: ExecutionProfilePlan | None = base_plan if base_predictor is not None else None
    best_predictor = base_predictor
    for candidate_plan in candidates:
        try:
            candidate_predictor = _build_predictor(
                backend=candidate_plan.resolved_backend,
                identifier=str(model_cfg["identifier"]),
                dtype=str(model_cfg.get("dtype", "float16")),
                max_new_tokens=int(candidate_plan.max_new_tokens),
                runtime_contract=runtime_contract,
                execution_plan=candidate_plan,
                decode_config=decode_config,
            )
            candidate_predictor = _attach_runtime_context(candidate_predictor, stage_id=stage_id, model=model_cfg)
            candidate_predictor = _maybe_autotune_batch_size(candidate_predictor, preview_prompts)
            candidate_runtime_stats = dict(getattr(candidate_predictor, "runtime_stats", _empty_runtime_stats()))
            autotune = dict(candidate_runtime_stats.get("autotune", {}))
            selected_batch_size = int(autotune.get("selected_batch_size") or getattr(candidate_predictor, "batch_size", 1) or 1)
            selected_samples_per_s = float(_selected_autotune_metric(autotune, "samples_per_s") or 0.0)
            candidate_record = {
                "plan": candidate_plan.to_dict(),
                "status": autotune.get("status", "unknown"),
                "strategy": autotune.get("strategy"),
                "selected_batch_size": selected_batch_size,
                "selected_samples_per_s": selected_samples_per_s,
                "selected_peak_vram_mb": _selected_autotune_metric(autotune, "peak_vram_mb"),
                "warnings": autotune.get("warnings", []),
            }
            candidate_records.append(candidate_record)
            if candidate_record["status"] != "completed":
                continue
            rank = _autotune_candidate_rank(
                candidate_plan=candidate_plan,
                base_plan=base_plan,
                selected_batch_size=selected_batch_size,
                selected_samples_per_s=selected_samples_per_s,
                backend_rank=backend_rank,
            )
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_plan = candidate_plan
                best_predictor = candidate_predictor
        except (RuntimeError, OSError, ValueError) as exc:
            logger.warning("Candidate backend failed during autotune: %s", exc)
            candidate_records.append(
                {
                    "plan": candidate_plan.to_dict(),
                    "status": "failed",
                    "error": str(exc),
                }
            )
    if best_predictor is None or best_plan is None:
        raise RuntimeError(
            f"Execution-profile search could not initialize any backend for execution_profile `{execution_profile}`."
        ) from base_build_error
    best_runtime_stats = dict(getattr(best_predictor, "runtime_stats", _empty_runtime_stats()))
    best_runtime_stats["execution_search"] = {
        "status": "completed" if best_rank is not None else "failed",
        "selected_backend": best_plan.resolved_backend,
        "selected_context_bucket": best_plan.context_bucket,
        "selected_max_new_tokens": best_plan.max_new_tokens,
        "base_backend": base_plan.resolved_backend,
        "base_context_bucket": base_plan.context_bucket,
        "base_max_new_tokens": base_plan.max_new_tokens,
        "candidate_count": len(candidates),
        "candidates": candidate_records,
    }
    best_predictor.runtime_stats = best_runtime_stats
    return best_plan, best_predictor

def _resolve_execution_profile(
    execution_profile: str,
    *,
    model_cfg: dict[str, Any],
    prompts: list[str],
) -> ExecutionProfilePlan:
    _contract, profile, defaults, fallback_ladder, contract_metrics = _execution_profile_contract(execution_profile)
    requested_backend = _resolve_profile_backend(str(model_cfg.get("backend", "")).strip())
    preferred_backend = _resolve_profile_backend(str(profile.get("preferred_backend", "")).strip()) if isinstance(profile, dict) else ""
    resolved_backend = stage_kernel_resolution.resolve_execution_backend(
        requested_backend=requested_backend,
        preferred_backend=preferred_backend,
        backend_policy=_load_backend_policy(),
    )
    selected_bucket = None
    if isinstance(profile, dict) and isinstance(profile.get("context_buckets"), dict):
        selected_bucket = _select_context_bucket(profile.get("context_buckets", {}), prompts)
    return _build_execution_profile_plan(
        execution_profile,
        model_cfg=model_cfg,
        defaults=defaults,
        fallback_ladder=fallback_ladder,
        contract_metrics=contract_metrics,
        profile=profile,
        resolved_backend=resolved_backend,
        selected_bucket=selected_bucket,
    )

def _truncate_text_markers(text: str, markers: tuple[str, ...]) -> str:
    cutoff = len(text)
    lowered = text.lower()
    for marker in markers:
        index = lowered.find(marker.lower())
        if index != -1:
            cutoff = min(cutoff, index)
    return text[:cutoff].strip()

def _normalize_prediction_output(adapter: StageAdapter, raw_output: str, *, prompt: str) -> str:
    normalize_prediction_output = getattr(adapter, "normalize_prediction_output", None)
    if callable(normalize_prediction_output):
        normalized = normalize_prediction_output(raw_output, prompt=prompt)
        if isinstance(normalized, str):
            return normalized
    return raw_output

def _load_dataset_bundle(
    adapter: StageAdapter,
    *,
    promotion_manifest_path: Path,
    tiers: list[str] | None,
    split_kinds: list[str] | None,
    split_families: list[str] | None,
    lexicalizations: list[str] | None,
    rule_families: list[str] | None,
    limit: int | None,
) -> dict:
    promotion_manifest = adapter.load_promotion_manifest(promotion_manifest_path)
    selected_files = adapter.resolve_dataset_files(
        promotion_manifest,
        tiers=tiers,
        split_kinds=split_kinds,
        split_families=split_families,
    )
    per_source_examples: list[list[tuple[dict, dict]]] = []
    for source_metadata in selected_files:
        local_path = Path(source_metadata["local_path"]).expanduser()
        source_examples: list[tuple[dict, dict]] = []
        for example in adapter.iter_examples([local_path], limit=None):
            if not adapter.include_example(
                example,
                lexicalizations=lexicalizations,
                rule_families=rule_families,
            ):
                continue
            source_examples.append((example, source_metadata))
        if source_examples:
            per_source_examples.append(source_examples)
    examples = _round_robin_examples(per_source_examples, limit=limit)
    return {
        "promotion_manifest": promotion_manifest,
        "selected_files": selected_files,
        "examples": examples,
    }

def _build_predictor(
    *,
    backend: str,
    identifier: str,
    dtype: str,
    max_new_tokens: int,
    runtime_contract: dict[str, Any] | None = None,
    execution_plan: ExecutionProfilePlan | None = None,
    decode_config: dict[str, Any] | None = None,
) -> Any:
    if backend == "mock-entailment":
        predictor = MockPredictor("entailment")
        return _apply_execution_plan(predictor, execution_plan)
    if backend == "mock-contradiction":
        predictor = MockPredictor("contradiction")
        return _apply_execution_plan(predictor, execution_plan)
    if backend == "local-transformers":
        predictor = TransformersPredictor(
            identifier,
            max_new_tokens=max_new_tokens,
            dtype=dtype,
            runtime_contract=runtime_contract,
            prompt_token_budget=execution_plan.prompt_token_budget if execution_plan else None,
            batch_probe_order=execution_plan.batch_probe_order if execution_plan else None,
            decode_config=decode_config,
        )
        return _apply_execution_plan(predictor, execution_plan)
    if backend == "vllm":
        predictor = VllmPredictor(
            identifier,
            max_new_tokens=max_new_tokens,
            dtype=dtype,
            runtime_contract=runtime_contract,
            prompt_token_budget=execution_plan.prompt_token_budget if execution_plan else None,
            batch_probe_order=execution_plan.batch_probe_order if execution_plan else None,
            decode_config=decode_config,
        )
        return _apply_execution_plan(predictor, execution_plan)
    raise ValueError(f"Unsupported backend: {backend}")

def _apply_execution_plan(predictor: Any, execution_plan: ExecutionProfilePlan | None) -> Any:
    predictor.runtime_stats = dict(getattr(predictor, "runtime_stats", _empty_runtime_stats()))
    if execution_plan is None:
        return predictor
    if execution_plan.batch_probe_order:
        predictor.batch_probe_order = list(execution_plan.batch_probe_order)
        predictor.batch_size = int(execution_plan.batch_probe_order[0])
    if execution_plan.prompt_token_budget is not None:
        predictor.prompt_token_budget = int(execution_plan.prompt_token_budget)
    predictor.max_new_tokens = int(execution_plan.max_new_tokens)
    predictor.runtime_stats["execution_plan"] = execution_plan.to_dict()
    predictor.runtime_stats["selected_batch_size"] = int(getattr(predictor, "batch_size", 1) or 1)
    return predictor

def _attach_runtime_context(predictor: Any, *, stage_id: str, model: dict[str, Any]) -> Any:
    runtime_stats = dict(getattr(predictor, "runtime_stats", _empty_runtime_stats()))
    runtime_stats["stage_id"] = stage_id
    runtime_stats["model"] = {
        "family": model.get("family"),
        "identifier": model.get("identifier"),
        "dtype": model.get("dtype"),
    }
    runtime_stats["autotune_cache_path"] = str(AUTOTUNE_CACHE_PATH)
    predictor.runtime_stats = runtime_stats
    return predictor

def _configure_generation_tokenizer(tokenizer: Any) -> Any:
    if getattr(tokenizer, "pad_token_id", None) is None and getattr(tokenizer, "eos_token_id", None) is not None:
        tokenizer.pad_token = tokenizer.eos_token
    if getattr(tokenizer, "padding_side", None) != "left":
        try:
            tokenizer.padding_side = "left"
        except (AttributeError, TypeError):
            return tokenizer
    return tokenizer

def _default_transformers_batch_size(model_path: str) -> int:
    lowered = model_path.lower()
    if "2b" in lowered or "0.8b" in lowered:
        return 16
    if "4b" in lowered or "e4b" in lowered or "3b" in lowered:
        return 8
    return 4

def _round_robin_examples(
    per_source_examples: list[list[tuple[dict, dict]]],
    *,
    limit: int | None,
) -> list[tuple[dict, dict]]:
    if limit is None:
        return [record for source_examples in per_source_examples for record in source_examples]
    indices = [0] * len(per_source_examples)
    selected: list[tuple[dict, dict]] = []
    while len(selected) < int(limit):
        advanced = False
        for source_index, source_examples in enumerate(per_source_examples):
            example_index = indices[source_index]
            if example_index >= len(source_examples):
                continue
            selected.append(source_examples[example_index])
            indices[source_index] += 1
            advanced = True
            if len(selected) >= int(limit):
                return selected
        if not advanced:
            break
    return selected

def _run_predictions(
    adapter: StageAdapter,
    predictor: Any,
    examples: list[tuple[dict, dict]],
    *,
    predictions_path: Path | None,
) -> list[dict]:
    records: list[dict] = []
    handle = predictions_path.open("w", encoding="utf-8") if predictions_path else None
    runtime_stats = dict(getattr(predictor, "runtime_stats", _empty_runtime_stats()))
    runtime_stats["started_at"] = _now_utc()
    predictor.runtime_stats = runtime_stats
    started_monotonic = time.monotonic()
    try:
        predict_many = getattr(predictor, "predict_many", None)
        if callable(predict_many):
            preview_prompts = [adapter.format_prompt(example) for example, _ in examples[: min(len(examples), 4)]]
            predictor = _maybe_autotune_batch_size(predictor, preview_prompts)
            batch: list[tuple[dict, dict]] = []
            prompts: list[str] = []
            batch_size = max(1, int(getattr(predictor, "batch_size", 1)))
            for example, source_metadata in examples:
                batch.append((example, source_metadata))
                prompts.append(adapter.format_prompt(example))
                if len(batch) >= batch_size:
                    _append_prediction_batch(adapter, predictor, predict_many, batch, prompts, records, handle)
                    batch = []
                    prompts = []
                    batch_size = max(1, int(getattr(predictor, "batch_size", batch_size)))
            if batch:
                _append_prediction_batch(adapter, predictor, predict_many, batch, prompts, records, handle)
        else:
            for example, source_metadata in examples:
                prompt = adapter.format_prompt(example)
                raw_output = predictor.predict(prompt)
                predicted_label = adapter.parse_prediction(
                    _normalize_prediction_output(adapter, raw_output, prompt=prompt)
                )
                record = adapter.build_prediction_record(
                    example,
                    predicted_label=predicted_label,
                    raw_output=raw_output,
                    source_metadata=source_metadata,
                )
                records.append(record)
                if handle is not None:
                    handle.write(json.dumps(record) + "\n")
                _record_runtime_batch(predictor, [prompt], [raw_output], requested_batch_size=1)
    finally:
        if handle is not None:
            handle.close()
    _finalize_runtime_stats(predictor, started_monotonic)
    return records

def _append_prediction_batch(
    adapter: StageAdapter,
    predictor: Any,
    predict_many: Any,
    batch: list[tuple[dict, dict]],
    prompts: list[str],
    records: list[dict],
    handle: Any,
) -> None:
    raw_outputs = list(predict_many(prompts))
    if len(raw_outputs) != len(batch):
        raise RuntimeError(
            f"Batch predictor returned {len(raw_outputs)} outputs for {len(batch)} prompts."
        )
    for (example, source_metadata), prompt, raw_output in zip(batch, prompts, raw_outputs):
        predicted_label = adapter.parse_prediction(
            _normalize_prediction_output(adapter, raw_output, prompt=prompt)
        )
        record = adapter.build_prediction_record(
            example,
            predicted_label=predicted_label,
            raw_output=raw_output,
            source_metadata=source_metadata,
        )
        records.append(record)
        if handle is not None:
            handle.write(json.dumps(record) + "\n")
    _record_runtime_batch(predictor, prompts, raw_outputs, requested_batch_size=len(batch))

def _record_runtime_batch(
    predictor: Any,
    prompts: list[str],
    raw_outputs: list[str],
    *,
    requested_batch_size: int,
) -> None:
    runtime_stats = dict(getattr(predictor, "runtime_stats", _empty_runtime_stats()))
    prompt_budget = getattr(predictor, "prompt_token_budget", None)
    prompt_tokens = [_count_tokens(prompt, predictor, clamp=prompt_budget) for prompt in prompts]
    generated_tokens = [_count_tokens(output, predictor) for output in raw_outputs]
    runtime_stats["executed_examples"] = int(runtime_stats.get("executed_examples", 0)) + len(prompts)
    runtime_stats["prompt_tokens_total"] = int(runtime_stats.get("prompt_tokens_total", 0)) + sum(prompt_tokens)
    runtime_stats["generated_tokens_total"] = int(runtime_stats.get("generated_tokens_total", 0)) + sum(generated_tokens)
    runtime_stats["prompt_tokens_max"] = max(
        int(runtime_stats.get("prompt_tokens_max", 0)),
        max(prompt_tokens, default=0),
    )
    runtime_stats["generated_tokens_max"] = max(
        int(runtime_stats.get("generated_tokens_max", 0)),
        max(generated_tokens, default=0),
    )
    runtime_stats.setdefault("batch_requests", []).append(
        {
            "requested_batch_size": int(requested_batch_size),
            "resolved_batch_size": int(getattr(predictor, "batch_size", requested_batch_size) or requested_batch_size),
            "prompt_tokens": sum(prompt_tokens),
            "generated_tokens": sum(generated_tokens),
        }
    )
    predictor.runtime_stats = runtime_stats

def _finalize_runtime_stats(predictor: Any, started_monotonic: float) -> None:
    runtime_stats = dict(getattr(predictor, "runtime_stats", _empty_runtime_stats()))
    elapsed_seconds = max(time.monotonic() - started_monotonic, 1e-9)
    runtime_stats["elapsed_s"] = round(elapsed_seconds, 6)
    runtime_stats["completed_at"] = _now_utc()
    generated_tokens_total = int(runtime_stats.get("generated_tokens_total", 0))
    executed_examples = int(runtime_stats.get("executed_examples", 0))
    runtime_stats["toks_per_s"] = round(generated_tokens_total / elapsed_seconds, 6) if generated_tokens_total else 0.0
    runtime_stats["samples_per_s"] = round(executed_examples / elapsed_seconds, 6) if executed_examples else 0.0
    prompt_budget = getattr(predictor, "prompt_token_budget", None)
    runtime_stats["selected_batch_size"] = int(getattr(predictor, "batch_size", 1) or 1)
    runtime_stats["budget"] = {
        "prompt_token_budget": int(prompt_budget) if prompt_budget is not None else None,
        "prompt_token_utilization": (
            round(int(runtime_stats.get("prompt_tokens_max", 0)) / int(prompt_budget), 6)
            if prompt_budget
            else None
        ),
        "max_new_tokens": int(getattr(predictor, "max_new_tokens", 0) or 0),
        "selected_batch_size": int(getattr(predictor, "batch_size", 1) or 1),
        "batch_probe_order": [int(value) for value in getattr(predictor, "batch_probe_order", [])],
    }
    predictor.runtime_stats = runtime_stats

def _build_runtime_report(
    *,
    stage_id: str,
    execution_plan: ExecutionProfilePlan,
    predictor: Any,
    model: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    return stage_kernel_reporting.build_runtime_report(
        stage_id=stage_id,
        execution_plan=execution_plan,
        predictor=predictor,
        model=model,
        output_dir=output_dir,
        runtime_capability_probe=_runtime_capability_probe,
        empty_runtime_stats=_empty_runtime_stats,
    )

def _runtime_telemetry_metrics(runtime_report: dict[str, Any]) -> dict[str, Any]:
    return stage_kernel_reporting.runtime_telemetry_metrics(runtime_report)

def _runtime_manifest_payload(runtime_report: dict[str, Any]) -> dict[str, Any]:
    return stage_kernel_reporting.runtime_manifest_payload(runtime_report)

def _selection_slice(selected_files: list[dict]) -> str:
    seen: list[str] = []
    for item in selected_files:
        label = f"{item.get('split_kind', 'unknown')}:{item.get('split_family', 'unknown')}"
        if label not in seen:
            seen.append(label)
    return ",".join(seen)

def dry_run_validate(config_path: Path, *, max_steps: int = 2, timeout: float = 60) -> bool:
    """Run a quick validation of experiment code before full GPU launch.

    Validates config loading, imports, and stage kernel wiring without
    requiring a GPU.  Runs the experiment subprocess with a short timeout
    and returns False if anything fails so the caller can abort the full
    GPU run before burning expensive compute.

    Parameters
    ----------
    config_path:
        Path to the experiment YAML / JSON configuration file.
    max_steps:
        Maximum number of examples / iterations to run during validation.
    timeout:
        Maximum wall-clock seconds to allow the validation subprocess.

    Returns
    -------
    True if the dry run succeeded without errors, False otherwise.
    """
    import os as _os
    import subprocess
    import sys as _sys

    resolved = Path(config_path).expanduser().resolve()
    env = dict(_os.environ)
    env["CUDA_VISIBLE_DEVICES"] = ""       # force CPU-only path
    env["DEEPLOOP_DRY_RUN"] = "1"
    env["DEEPLOOP_DRY_RUN_MAX_STEPS"] = str(max(int(max_steps), 1))

    # Build a small self-contained validation script that is shipped to
    # the subprocess so import / syntax errors are caught there.
    script = (
        "import sys, traceback\n"
        "from pathlib import Path\n"
        "config_path = Path({})\n".format(repr(str(resolved)))
        + (
            "try:\n"
            "    import yaml\n"
            "    config = yaml.safe_load(config_path.read_text('utf-8'))\n"
            "    if not isinstance(config, dict):\n"
            "        print('ERROR: config is not a mapping', file=sys.stderr)\n"
            "        sys.exit(1)\n"
            "    stage_id = config.get('stage_id', '')\n"
            "    if not stage_id:\n"
            "        print('ERROR: no stage_id in config', file=sys.stderr)\n"
            "        sys.exit(1)\n"
            "    adapter_spec = config.get('adapter') or config.get('adapter_spec')\n"
            "    from deeploop.runtime.stage_kernels import run_stage_from_config\n"
            "    result = run_stage_from_config(stage_id, config_path, adapter_spec=adapter_spec)\n"
            "    print(f'OK: status={result.status}')\n"
            "except Exception:\n"
            "    traceback.print_exc()\n"
            "    sys.exit(1)\n"
        )
    )

    try:
        completed = subprocess.run(
            [_sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=float(timeout),
            env=env,
        )
        if completed.returncode != 0:
            stderr_snippet = completed.stderr.strip()[-500:] if completed.stderr.strip() else "(no stderr)"
            print(
                f"[deeploop] Dry-run validation FAILED for {resolved}\n"
                f"  returncode={completed.returncode}\n"
                f"  {stderr_snippet}",
                file=_sys.stderr,
            )
            return False
        return True
    except subprocess.TimeoutExpired:
        print(
            f"[deeploop] Dry-run validation TIMED OUT ({timeout}s) for {resolved}",
            file=_sys.stderr,
        )
        return False
    except OSError as exc:
        print(
            f"[deeploop] Dry-run validation OS ERROR: {exc}",
            file=_sys.stderr,
        )
        return False

def _build_manifest(
    *,
    adapter: StageAdapter,
    stage_id: str,
    loop_id: str,
    mode: str,
    claim_state: str,
    mission_id: str | None,
    resource_tier: str,
    execution_profile: str,
    model: dict,
    dataset: dict,
    prompt: dict,
    output_dir: Path,
    command: str,
    seed: int,
    notes: list[str],
    metrics: dict,
    stage_context: dict,
    report_paths: list[str],
    runtime_payload: dict[str, Any] | None = None,
    status: str = "completed",
) -> dict:
    return stage_kernel_reporting.build_manifest(
        adapter=adapter,
        stage_id=stage_id,
        loop_id=loop_id,
        mode=mode,
        claim_state=claim_state,
        mission_id=mission_id,
        resource_tier=resource_tier,
        execution_profile=execution_profile,
        model=model,
        dataset=dataset,
        prompt=prompt,
        output_dir=output_dir,
        command=command,
        seed=seed,
        notes=notes,
        metrics=metrics,
        stage_context=stage_context,
        report_paths=report_paths,
        stage_registry_contract_path=STAGE_REGISTRY_CONTRACT_PATH,
        load_json=_load_json,
        runtime_context=_runtime_context(),
        runtime_payload=runtime_payload,
        status=status,
    )

def _merge_model_config(stage_model: dict, source_model: dict) -> dict:
    identifier = stage_model.get("identifier") or stage_model.get("checkpoint") or source_model.get("identifier")
    return {
        "family": str(stage_model.get("family", source_model.get("family", "unknown"))),
        "identifier": str(identifier),
        "backend": str(stage_model.get("backend", source_model.get("backend", "mock-entailment"))),
        "dtype": str(stage_model.get("dtype", source_model.get("dtype", "float16"))),
        "max_new_tokens": int(stage_model.get("max_new_tokens", source_model.get("max_new_tokens", 32))),
    }

def _units_from_layer_spec(layer_spec: Any) -> list[str]:
    if isinstance(layer_spec, list):
        units = [str(item).strip().lower() for item in layer_spec if str(item).strip()]
    else:
        text = str(layer_spec or "").lower()
        units = [unit for unit in ZONE_ORDER if unit in text]
    return units or list(ZONE_ORDER)

def _assign_proxy_unit(record: dict, allowed_units: list[str]) -> str:
    chain_len = int(record.get("chain_len", 0) or 0)
    split_family = str(record.get("split_family", "iid"))
    lexicalization = str(record.get("lex", ""))

    if chain_len >= 4 or split_family != "iid":
        preferred = "late"
    elif lexicalization == "delex" or chain_len >= 2:
        preferred = "mid"
    else:
        preferred = "early"

    if preferred in allowed_units:
        return preferred

    preferred_index = ZONE_ORDER.index(preferred)
    available = sorted(allowed_units, key=lambda item: abs(ZONE_ORDER.index(item) - preferred_index))
    return available[0]

# ---------------------------------------------------------------------------
# Kernel function imports (loaded after shared helpers to avoid circular imports)
# ---------------------------------------------------------------------------
from deeploop.runtime.kernel_baseline_evaluation import run_baseline_evaluation  # noqa: E402 F401
from deeploop.runtime.kernel_prompt_decode_sweep import run_prompt_decode_sweep  # noqa: E402 F401
from deeploop.runtime.kernel_mechanistic_localization import run_mechanistic_localization  # noqa: E402 F401
from deeploop.runtime.kernel_causal_intervention import run_causal_intervention  # noqa: E402 F401

_KERNELS = {
    "baseline-evaluation": StageKernel(
        stage_id="baseline-evaluation",
        runner=lambda config_path, adapter: run_baseline_evaluation(config_path, adapter=adapter),
        summary="Generic baseline evaluation kernel.",
    ),
    "prompt-decode-sweep": StageKernel(
        stage_id="prompt-decode-sweep",
        runner=lambda config_path, adapter: run_prompt_decode_sweep(config_path, adapter=adapter),
        summary="Prompt/decode sweep kernel for benchmark-bound prompt experiments.",
    ),
    "mechanistic-localization": StageKernel(
        stage_id="mechanistic-localization",
        runner=lambda config_path, adapter: run_mechanistic_localization(config_path, adapter=adapter),
        summary="Deterministic runnable mechanistic localization proxy kernel.",
    ),
    "causal-intervention": StageKernel(
        stage_id="causal-intervention",
        runner=lambda config_path, adapter: run_causal_intervention(config_path, adapter=adapter),
        summary="Deterministic runnable causal intervention proxy kernel.",
    ),
}

def get_stage_registry() -> dict[str, StageKernel]:
    return stage_kernel_registry.get_stage_registry(_KERNELS)

def run_stage_from_config(
    stage_id: str,
    config_path: Path,
    *,
    adapter: StageAdapter | None = None,
    adapter_spec: str | None = None,
) -> KernelRunResult:
    return stage_kernel_registry.run_stage_from_config(
        stage_id,
        config_path,
        adapter=adapter,
        adapter_spec=adapter_spec,
        kernels=_KERNELS,
        adapter_loader=load_stage_adapter,
    )

def load_stage_adapter(adapter_spec: str | None) -> StageAdapter:
    return stage_kernel_registry.load_stage_adapter(adapter_spec)

def load_stage_registry_contract() -> dict:
    return stage_kernel_registry.load_stage_registry_contract(load_yaml=_load_yaml)

