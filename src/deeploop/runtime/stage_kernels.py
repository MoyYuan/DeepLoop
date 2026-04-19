from __future__ import annotations

import json
import math
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

import yaml

from deeploop.autonomy.operating_modes import DEFAULT_OPERATING_MODE
from deeploop.core.paths import REPO_ROOT as DEEPLOOP_REPO_ROOT, RUNS_DIR
from deeploop.runtime import (
    _stage_kernel_registry as stage_kernel_registry,
    _stage_kernel_reporting as stage_kernel_reporting,
    _stage_kernel_resolution as stage_kernel_resolution,
)


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


def run_baseline_evaluation(config_path: Path, *, adapter: StageAdapter) -> KernelRunResult:
    config = _load_yaml(config_path)
    dataset_cfg = config["dataset"]
    selection = dataset_cfg["selection"]
    prompt_cfg = config.get("prompt", {})
    promotion_manifest_path = Path(
        dataset_cfg.get("promotion_manifest", str(adapter.default_promotion_manifest()))
    ).expanduser()
    dataset_bundle = _load_dataset_bundle(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        tiers=selection.get("tiers"),
        split_kinds=selection.get("split_kinds"),
        split_families=selection.get("split_families"),
        lexicalizations=selection.get("lexicalizations"),
        rule_families=selection.get("rule_families"),
        limit=dataset_cfg.get("limit_examples"),
    )

    model_cfg = config["model"]
    _configure_adapter_model_family(adapter, model_cfg)
    _configure_adapter_prompt(adapter, prompt_cfg)
    model_identifier = model_cfg.get("identifier", model_cfg.get("checkpoint", model_cfg.get("label", "")))
    prompt_samples = [adapter.format_prompt(example) for example, _ in dataset_bundle["examples"]]
    runtime_model_cfg = {
        "family": model_cfg.get("family"),
        "identifier": model_identifier,
        "backend": model_cfg.get("backend"),
        "dtype": str(model_cfg.get("dtype", "float16")),
        "max_new_tokens": int(model_cfg.get("max_new_tokens", 32) or 32),
    }
    execution_plan, predictor = _autotune_execution_plan(
        "baseline-evaluation",
        execution_profile=str(config["execution_profile"]),
        model_cfg=runtime_model_cfg,
        prompts=prompt_samples,
        runtime_contract=_adapter_runtime_contract(adapter),
    )
    manifest_model = {
        "family": model_cfg["family"],
        "identifier": model_identifier,
        "backend": execution_plan.resolved_backend,
        "dtype": str(model_cfg.get("dtype", "float16")),
        "max_new_tokens": int(execution_plan.max_new_tokens),
    }

    output_dir = Path(config["run"]["output_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "predictions.jsonl"
    metrics_path = output_dir / "metrics.json"
    manifest_path = output_dir / "run_manifest.json"
    runtime_report_path = output_dir / "runtime_report.json"

    records = _run_predictions(
        adapter,
        predictor,
        dataset_bundle["examples"],
        predictions_path=predictions_path,
    )
    runtime_report = _build_runtime_report(
        stage_id="baseline-evaluation",
        execution_plan=execution_plan,
        predictor=predictor,
        model=manifest_model,
        output_dir=output_dir,
    )
    _write_json(runtime_report_path, runtime_report)
    runtime_manifest_payload = _runtime_manifest_payload(runtime_report)
    metrics = {**adapter.compute_metrics(records), **_runtime_telemetry_metrics(runtime_report)}
    _write_json(metrics_path, metrics)

    manifest = _build_manifest(
        adapter=adapter,
        stage_id="baseline-evaluation",
        loop_id=config["run"]["loop_id"],
        mode=config["mode"],
        claim_state=config["claim_state"],
        mission_id=config.get("mission_id", UNKNOWN_MISSION_ID),
        resource_tier=config["resource_tier"],
        execution_profile=config["execution_profile"],
        model=manifest_model,
        dataset={
            "name": _dataset_name(adapter, dataset_bundle["promotion_manifest"]),
            "slice": _selection_slice(dataset_bundle["selected_files"]),
            "provenance": str(promotion_manifest_path),
        },
        prompt={
            "template_id": prompt_cfg.get("template_id", adapter.prompt_template_id),
            "parser_id": prompt_cfg.get("parser_id", getattr(adapter, "parser_id", "unknown-parser")),
        },
        output_dir=output_dir,
        command=f"baseline-evaluation --config {config_path}",
        seed=int(config["run"].get("seed", 0)),
        notes=_normalize_notes(config["run"].get("notes", [])),
        metrics=metrics,
        stage_context={
            "selection": selection,
            "dataset_record_count": len(dataset_bundle["examples"]),
            "config_path": str(config_path),
            "execution_contract": runtime_manifest_payload["execution_plan"],
            "runtime_telemetry": runtime_manifest_payload["telemetry"],
            "runtime_budget": runtime_manifest_payload["budget"],
            "capabilities": runtime_manifest_payload["capabilities"],
            "runtime_autotune": runtime_manifest_payload["autotune"],
            "execution_search": runtime_manifest_payload["execution_search"],
            "artifacts": {
                "predictions_path": str(predictions_path),
                "metrics_path": str(metrics_path),
                "runtime_report_path": str(runtime_report_path),
            },
        },
        report_paths=[str(runtime_report_path)],
        runtime_payload={
            "execution_profile": runtime_manifest_payload["execution_plan"],
            "telemetry": runtime_manifest_payload["telemetry"],
            "budget": runtime_manifest_payload["budget"],
            "capabilities": runtime_manifest_payload["capabilities"],
            "autotune": runtime_manifest_payload["autotune"],
            "execution_search": runtime_manifest_payload["execution_search"],
            "runtime_report_path": str(runtime_report_path),
        },
    )
    _validate_manifest(manifest)
    _write_json(manifest_path, manifest)

    return KernelRunResult(
        stage_id="baseline-evaluation",
        status="completed",
        output_dir=output_dir,
        manifest_path=manifest_path,
        artifacts={
            "predictions": predictions_path,
            "metrics": metrics_path,
            "runtime_report": runtime_report_path,
            "manifest": manifest_path,
        },
    )


def run_prompt_decode_sweep(config_path: Path, *, adapter: StageAdapter) -> KernelRunResult:
    config = _load_yaml(config_path)
    direction = str(config["selected_direction"])
    runtime_root = Path(config.get("runtime_root", adapter.runs_root)).expanduser()
    output_paths = _prompt_sweep_output_paths(config, direction=direction, runtime_root=runtime_root)
    output_dir = output_paths["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths["reports_dir"].mkdir(parents=True, exist_ok=True)
    dataset_materialization = dict(config.get("dataset_materialization", {}))
    promotion_manifest_path = Path(
        dataset_materialization.get("promotion_manifest_path", adapter.default_promotion_manifest())
    ).expanduser()
    primary_bundle = _prompt_sweep_selection(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        selection=_prompt_sweep_selection_config(dataset_materialization, "primary_dev_selection", direction),
    )
    holdout_bundle = _prompt_sweep_selection(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        selection=_prompt_sweep_selection_config(dataset_materialization, "secondary_holdout_selection", direction),
    )
    final_bundle = _prompt_sweep_selection(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        selection=_prompt_sweep_selection_config(dataset_materialization, "final_test_selection", direction),
    )
    model_cfg = _prompt_sweep_model_config(config)
    runtime_lock = dict(config.get("runtime_lock", {}))
    locked_context_bucket = str(runtime_lock.get("context_bucket", "short"))
    metric_path = _metric_path(config.get("metric_path"), default=("sacrebleu", "score"))
    diagnostic_metric_path = _metric_path(
        config.get("diagnostic_metric_path"),
        default=tuple(metric_path),
    )
    promotion_rules = _prompt_sweep_promotion_rules(config)
    loop_id = str(config.get("run", {}).get("loop_id", f"prompt-decode-{direction}"))
    seed = int(config.get("run", {}).get("seed", 0))
    variant_matrix = list(config.get("variant_matrix", []))[: int(config.get("max_variants", len(config.get("variant_matrix", []))))]
    rows: list[dict[str, Any]] = []
    executed_results: list[dict[str, Any]] = []
    total_stage_gpu_hours = 0.0

    for raw_variant in variant_matrix:
        variant = deepcopy(raw_variant)
        variant_id = str(variant["variant_id"])
        context_bucket = str(variant.get("context_bucket", locked_context_bucket))
        if context_bucket != locked_context_bucket:
            rows.append(
                {
                    "variant_id": variant_id,
                    "status": "skipped",
                    "prompt_family": variant.get("prompt_family", variant.get("template_id")),
                    "context_bucket": context_bucket,
                    "trusted_source_ids": list(variant.get("trusted_source_ids", [])),
                    "skip_reason": (
                        f"context_bucket={context_bucket} drifts from locked runtime "
                        f"context_bucket={locked_context_bucket}"
                    ),
                }
            )
            continue
        decode_config = _decode_policy_config(
            variant.get("decode"),
            decode_policy=variant.get("decode_policy"),
            max_new_tokens=int(model_cfg.get("max_new_tokens", 32) or 32),
        )
        variant_result = _run_prompt_sweep_variant(
            adapter=adapter,
            stage_id="prompt-decode-sweep",
            execution_profile=str(config["execution_profile"]),
            model_cfg=model_cfg,
            variant=variant,
            decode_config=decode_config,
            primary_examples=primary_bundle["examples"],
            holdout_examples=holdout_bundle["examples"],
            output_dir=output_dir / variant_id,
            seed=seed,
        )
        total_stage_gpu_hours += float(variant_result["runtime_gpu_hours"])
        row = {
            "variant_id": variant_id,
            "status": "completed",
            "prompt_family": variant_result["prompt_family"],
            "context_bucket": context_bucket,
            "trusted_source_ids": list(variant.get("trusted_source_ids", [])),
            "wmt18_primary": {
                "score": _metric_at_path(variant_result["primary_metrics"], metric_path),
                "runtime_gpu_hours": round(float(variant_result["primary_runtime_gpu_hours"]), 6),
            },
            "wmt17_holdout": {
                "score": _metric_at_path(variant_result["holdout_metrics"], metric_path),
                "runtime_gpu_hours": round(float(variant_result["holdout_runtime_gpu_hours"]), 6),
            },
            "artifacts": variant_result["artifacts"],
        }
        executed_results.append(
            {
                "variant": variant,
                "decode_config": decode_config,
                "result": variant_result,
                "row": row,
            }
        )
        rows.append(row)

    if not executed_results:
        raise ValueError("Prompt/decode sweep had no executable variants under the current runtime contract.")

    best_executed = _select_best_prompt_variant(executed_results, metric_path=metric_path)
    baseline_anchor_cfg = dict(config.get("baseline_anchor_replay", {}))
    baseline_anchor_template_id = str(baseline_anchor_cfg.get("template_id", "baseline-plain-v1"))
    baseline_anchor = _run_prompt_sweep_baseline_anchor(
        adapter=adapter,
        stage_id="prompt-decode-sweep",
        execution_profile=str(config["execution_profile"]),
        model_cfg=model_cfg,
        template_id=baseline_anchor_template_id,
        final_examples=final_bundle["examples"],
        output_dir=output_dir / "baseline-anchor",
        seed=seed,
    )
    total_stage_gpu_hours += float(baseline_anchor["runtime_gpu_hours"])
    final_result = _run_prompt_sweep_final_candidate(
        adapter=adapter,
        stage_id="prompt-decode-sweep",
        execution_profile=str(config["execution_profile"]),
        model_cfg=model_cfg,
        variant=best_executed["variant"],
        decode_config=best_executed["decode_config"],
        final_examples=final_bundle["examples"],
        output_dir=output_dir / best_executed["variant"]["variant_id"],
        seed=seed,
    )
    total_stage_gpu_hours += float(final_result["runtime_gpu_hours"])
    best_row = best_executed["row"]
    final_score = _metric_at_path(final_result["metrics"], metric_path)
    if final_score is None:
        raise ValueError("Prompt/decode sweep final candidate metrics are missing the requested metric.")
    promotion_reference = _prompt_sweep_reference_payload(
        config,
        metric_path=metric_path,
        baseline_anchor=baseline_anchor,
    )
    baseline_anchor_preflight = _prompt_sweep_baseline_anchor_preflight(
        reference=promotion_reference,
        baseline_anchor=baseline_anchor,
    )
    best_row["wmt19_final"] = {
        "score": final_score,
        "runtime_gpu_hours": round(float(final_result["runtime_gpu_hours"]), 6),
    }
    if promotion_reference["score"] is None:
        raise ValueError("Prompt/decode sweep promotion reference is missing the requested metric.")
    full_set_gain = round(
        float(final_score) - float(promotion_reference["score"]),
        4,
    )
    reference_metrics = promotion_reference.get("metrics")
    slice_override = _prompt_sweep_slice_override(
        baseline_metrics=reference_metrics if isinstance(reference_metrics, dict) else {},
        candidate_metrics=final_result["metrics"],
        metric_path=diagnostic_metric_path,
        full_set_gain=full_set_gain,
        override_rules=promotion_rules["slice_signal_override"],
    )
    best_row["wmt19_final"]["gain_vs_reference"] = full_set_gain
    best_row["wmt19_final"]["reference_label"] = promotion_reference["label"]
    if promotion_reference["kind"] == "baseline-anchor":
        best_row["wmt19_final"]["gain_vs_baseline_anchor"] = full_set_gain
    else:
        best_row["wmt19_final"]["gain_vs_locked_baseline"] = full_set_gain
    required_slice_ids = _string_list(
        dict(config.get("slice_audit", {})).get("required_slice_ids")
    ) or _string_list(promotion_rules["slice_signal_override"].get("eligible_slice_ids"))
    slice_audit = _prompt_sweep_diagnostic_slice_audit(
        direction=direction,
        best_variant=best_executed["variant"],
        reference=promotion_reference,
        reference_metrics=reference_metrics if isinstance(reference_metrics, dict) else None,
        candidate_metrics=final_result["metrics"],
        eligible_slice_ids=required_slice_ids,
    )
    _write_json(output_paths["diagnostic_slice_audit_path"], slice_audit)
    if config.get("slice_audit") and not slice_audit["clean"]:
        raise ValueError(
            "Prompt/decode diagnostic slice audit is incomplete: "
            + ", ".join(slice_audit["issues"])
        )
    decision = _prompt_sweep_promotion_decision(
        best_variant=best_executed["variant"],
        best_row=best_row,
        best_result=best_executed["result"],
        final_result=final_result,
        reference=promotion_reference,
        baseline_anchor=baseline_anchor,
        baseline_anchor_preflight=baseline_anchor_preflight,
        slice_override=slice_override,
        promotion_rules=promotion_rules,
        metric_path=metric_path,
    )
    scoreboard = {
        "version": 2,
        "mission_id": config.get("mission_id"),
        "loop_action_id": config.get("loop_action_id"),
        "stage_id": "prompt-decode",
        "selected_direction": direction,
        "selected_starter": config.get("selected_starter"),
        "promotion_reference": promotion_reference,
        "baseline_anchor": baseline_anchor["summary"],
        "baseline_anchor_preflight": baseline_anchor_preflight,
        "smoke_limit_from_baseline": None,
        "rows": rows,
    }
    _write_json(output_paths["scoreboard_path"], scoreboard)
    summary = {
        "version": 2,
        "mission_id": config.get("mission_id"),
        "loop_action_id": config.get("loop_action_id"),
        "stage_id": "prompt-decode",
        "status": "completed",
        "selected_direction": direction,
        "selected_starter": config.get("selected_starter"),
        "executed_variant_ids": [item["variant"]["variant_id"] for item in executed_results],
        "skipped_variant_ids": [
            item["variant_id"] for item in rows if item.get("status") == "skipped"
        ],
        "stage_spent_gpu_hours": round(total_stage_gpu_hours, 6),
        "decision": decision["decision"],
        "best_candidate": decision["best_candidate"],
        "promotion_reference": promotion_reference,
        "baseline_anchor": baseline_anchor["summary"],
        "baseline_anchor_preflight": baseline_anchor_preflight,
        "notes": _normalize_notes(
            [
                config.get("notes", []),
                baseline_anchor_cfg.get("notes", []),
                "DeepLoop executed the prompt/decode sweep through the shared stage-kernel surface.",
            ]
        ),
    }
    _update_prompt_sweep_crash_notes(
        output_paths["crash_notes_path"],
        summary=summary,
        scoreboard_path=output_paths["scoreboard_path"],
        promotion_decision_path=output_paths["promotion_decision_path"],
        summary_path=output_paths["summary_path"],
        diagnostic_slice_audit_path=output_paths["diagnostic_slice_audit_path"],
    )
    manifest = _build_manifest(
        adapter=adapter,
        stage_id="prompt-decode-sweep",
        loop_id=loop_id,
        mode=str(config.get("mode", DEFAULT_OPERATING_MODE)),
        claim_state=str(config.get("claim_state", "exploratory")),
        mission_id=config.get("mission_id"),
        resource_tier=str(config["resource_tier"]),
        execution_profile=str(config["execution_profile"]),
        model=model_cfg,
        dataset={
            "name": _dataset_name(adapter, primary_bundle["promotion_manifest"]),
            "slice": f"primary-dev:{direction},secondary-holdout:{direction},final-test:{direction}",
            "provenance": str(promotion_manifest_path),
        },
        prompt={
            "template_id": str(best_executed["variant"].get("template_id")),
            "parser_id": getattr(adapter, "parser_id", "unknown-parser"),
        },
        output_dir=output_dir,
        command=f"prompt-decode-sweep --config {config_path}",
        seed=seed,
        notes=_normalize_notes(config.get("notes", [])),
        metrics={
            "best_primary_score": _metric_at_path(best_executed["result"]["primary_metrics"], metric_path),
            "best_holdout_score": _metric_at_path(best_executed["result"]["holdout_metrics"], metric_path),
            "best_final_score": final_score,
            "reference_kind": promotion_reference["kind"],
            "reference_score": promotion_reference["score"],
            "baseline_anchor_score": _metric_at_path(baseline_anchor["metrics"], metric_path),
            "gain_vs_reference": full_set_gain,
            "decision": decision["decision"],
            "executed_variants": len(executed_results),
            "skipped_variants": len(rows) - len(executed_results),
        },
        stage_context={
            "direction": direction,
            "runtime_root": str(runtime_root),
            "locked_context_bucket": locked_context_bucket,
            "dataset_materialization": {
                "promotion_manifest_path": str(promotion_manifest_path),
                "primary_dev_selection": _prompt_sweep_selection_config(
                    dataset_materialization,
                    "primary_dev_selection",
                    direction,
                ),
                "secondary_holdout_selection": _prompt_sweep_selection_config(
                    dataset_materialization,
                    "secondary_holdout_selection",
                    direction,
                ),
                "final_test_selection": _prompt_sweep_selection_config(
                    dataset_materialization,
                    "final_test_selection",
                    direction,
                ),
            },
            "variant_matrix": variant_matrix,
            "promotion_rules": promotion_rules,
            "promotion_reference": promotion_reference,
            "baseline_anchor": baseline_anchor["summary"],
            "baseline_anchor_preflight": baseline_anchor_preflight,
            "artifacts": {
                "scoreboard_path": str(output_paths["scoreboard_path"]),
                "promotion_decision_path": str(output_paths["promotion_decision_path"]),
                "diagnostic_slice_audit_path": str(output_paths["diagnostic_slice_audit_path"]),
                "summary_path": str(output_paths["summary_path"]),
                "crash_notes_path": str(output_paths["crash_notes_path"]),
            },
        },
        report_paths=[
            str(output_paths["scoreboard_path"]),
            str(output_paths["promotion_decision_path"]),
            str(output_paths["diagnostic_slice_audit_path"]),
            str(output_paths["summary_path"]),
            str(output_paths["crash_notes_path"]),
        ],
    )
    manifest_path = output_dir / "run_manifest.json"
    _validate_manifest(manifest)
    _write_json(manifest_path, manifest)
    _write_json(output_paths["promotion_decision_path"], decision)
    _write_json(output_paths["summary_path"], summary)
    decision["replication_gate"] = _prompt_sweep_replication_gate(
        config,
        output_paths=output_paths,
        manifest_path=manifest_path,
        slice_audit=slice_audit,
        reference=promotion_reference,
    )
    summary["replication_gate"] = decision["replication_gate"]
    _write_json(output_paths["promotion_decision_path"], decision)
    _write_json(output_paths["summary_path"], summary)
    return KernelRunResult(
        stage_id="prompt-decode-sweep",
        status="completed",
        output_dir=output_dir,
        manifest_path=manifest_path,
        summary_path=output_paths["summary_path"],
        artifacts={
            "scoreboard": output_paths["scoreboard_path"],
            "promotion_decision": output_paths["promotion_decision_path"],
            "diagnostic_slice_audit": output_paths["diagnostic_slice_audit_path"],
            "summary": output_paths["summary_path"],
            "crash_notes": output_paths["crash_notes_path"],
            "manifest": manifest_path,
        },
    )


def run_mechanistic_localization(config_path: Path, *, adapter: StageAdapter) -> KernelRunResult:
    config = _load_yaml(config_path)
    source_manifest_path = Path(config["behavioral_source_manifest"]).expanduser()
    source_manifest = _load_json(source_manifest_path)
    study_id = config["study_id"]
    output_dir = Path(config.get("run", {}).get("output_dir", adapter.runs_root / study_id)).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "study_summary.json"
    observations_path = output_dir / "localization_observations.jsonl"
    candidates_path = output_dir / "localization_candidates.json"
    manifest_path = output_dir / "study_manifest.json"

    dataset_cfg = config["dataset"]
    promotion_manifest_path = Path(
        source_manifest.get("dataset", {}).get("provenance", adapter.default_promotion_manifest())
    ).expanduser()
    dataset_bundle = _load_dataset_bundle(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        tiers=dataset_cfg.get("tiers"),
        split_kinds=dataset_cfg.get("split_kinds"),
        split_families=dataset_cfg.get("split_families"),
        lexicalizations=dataset_cfg.get("lexicalizations"),
        rule_families=dataset_cfg.get("rule_families"),
        limit=dataset_cfg.get("limit_examples"),
    )

    model_cfg = _merge_model_config(config.get("model", {}), source_manifest.get("model", {}))
    prompt_cfg = source_manifest.get("prompt", config.get("prompt", {}))
    _configure_adapter_model_family(adapter, model_cfg)
    _configure_adapter_prompt(adapter, prompt_cfg)
    prompt_samples = [adapter.format_prompt(example) for example, _ in dataset_bundle["examples"]]
    execution_plan, predictor = _autotune_execution_plan(
        "mechanistic-localization",
        execution_profile=str(source_manifest.get("execution_profile", "mechanistic-proxy")),
        model_cfg=model_cfg,
        prompts=prompt_samples,
        runtime_contract=_adapter_runtime_contract(adapter),
    )
    model_cfg["backend"] = execution_plan.resolved_backend
    model_cfg["max_new_tokens"] = int(execution_plan.max_new_tokens)
    baseline_records = _run_predictions(
        adapter,
        predictor,
        dataset_bundle["examples"],
        predictions_path=None,
    )
    runtime_report_path = output_dir / "runtime_report.json"
    runtime_report = _build_runtime_report(
        stage_id="mechanistic-localization",
        execution_plan=execution_plan,
        predictor=predictor,
        model=model_cfg,
        output_dir=output_dir,
    )
    _write_json(runtime_report_path, runtime_report)
    runtime_manifest_payload = _runtime_manifest_payload(runtime_report)
    metrics = {**adapter.compute_metrics(baseline_records), **_runtime_telemetry_metrics(runtime_report)}
    allowed_units = _units_from_layer_spec(config["model"].get("layer_selection"))
    observations, candidates = _mechanistic_proxy_outputs(
        baseline_records,
        allowed_units=allowed_units,
        methods=config.get("methods", {}),
    )
    _write_jsonl(observations_path, observations)
    _write_json(candidates_path, {"study_id": study_id, "candidate_units": candidates})

    top_candidate = candidates[0] if candidates else None
    summary = {
        "study_id": study_id,
        "phase": config["phase"],
        "status": "completed",
        "behavioral_source_manifest": str(source_manifest_path),
        "source_accuracy": source_manifest.get("metrics", {}).get("accuracy"),
        "executed_examples": len(observations),
        "candidate_units": [candidate["unit_id"] for candidate in candidates],
        "top_candidate": top_candidate["unit_id"] if top_candidate else None,
        "methods": config.get("methods", {}),
        "notes": _normalize_notes(
            [
                "DeepLoop runnable kernel executed a deterministic localization proxy rather than a prep-only bundle.",
                config.get("reporting", {}).get("notes", []),
            ]
        ),
    }
    _write_json(summary_path, summary)

    manifest = _build_manifest(
        adapter=adapter,
        stage_id="mechanistic-localization",
        loop_id=study_id,
        mode=DEFAULT_OPERATING_MODE,
        claim_state="exploratory",
        mission_id=source_manifest.get("mission_id", UNKNOWN_MISSION_ID),
        resource_tier=source_manifest.get("resource_tier", "cpu-smoke"),
        execution_profile=source_manifest.get("execution_profile", "mechanistic-proxy"),
        model=model_cfg,
        dataset={
            "name": _dataset_name(adapter, dataset_bundle["promotion_manifest"]),
            "slice": _selection_slice(dataset_bundle["selected_files"]),
            "provenance": str(promotion_manifest_path),
        },
        prompt=prompt_cfg
        if isinstance(prompt_cfg, dict)
        else {"template_id": adapter.prompt_template_id, "parser_id": getattr(adapter, "parser_id", "unknown-parser")},
        output_dir=output_dir,
        command=f"mechanistic-localization --config {config_path}",
        seed=int(config.get("run", {}).get("seed", 0)),
        notes=_normalize_notes(
            [
                "Deterministic proxy localization; model-internals execution remains future work.",
                config.get("reporting", {}).get("notes", []),
            ]
        ),
        metrics={
            "executed_examples": len(observations),
            "baseline_accuracy": metrics.get("accuracy"),
            "top_candidate_score": top_candidate["normalized_score"] if top_candidate else None,
            "candidate_count": len(candidates),
            **_runtime_telemetry_metrics(runtime_report),
        },
        stage_context={
            "behavioral_source_manifest": str(source_manifest_path),
            "dataset_filters": dataset_cfg,
            "methods": config.get("methods", {}),
            "candidate_units": candidates,
            "execution_contract": runtime_manifest_payload["execution_plan"],
            "runtime_telemetry": runtime_manifest_payload["telemetry"],
            "runtime_budget": runtime_manifest_payload["budget"],
            "capabilities": runtime_manifest_payload["capabilities"],
            "runtime_autotune": runtime_manifest_payload["autotune"],
            "execution_search": runtime_manifest_payload["execution_search"],
            "artifacts": {
                "summary_path": str(summary_path),
                "observations_path": str(observations_path),
                "candidates_path": str(candidates_path),
                "runtime_report_path": str(runtime_report_path),
            },
            "proxy_kernel": True,
        },
        report_paths=[str(summary_path), str(candidates_path), str(runtime_report_path)],
        runtime_payload={
            "execution_profile": runtime_manifest_payload["execution_plan"],
            "telemetry": runtime_manifest_payload["telemetry"],
            "budget": runtime_manifest_payload["budget"],
            "capabilities": runtime_manifest_payload["capabilities"],
            "autotune": runtime_manifest_payload["autotune"],
            "execution_search": runtime_manifest_payload["execution_search"],
            "runtime_report_path": str(runtime_report_path),
        },
    )
    _validate_manifest(manifest)
    _write_json(manifest_path, manifest)

    return KernelRunResult(
        stage_id="mechanistic-localization",
        status="completed",
        output_dir=output_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
        artifacts={
            "summary": summary_path,
            "observations": observations_path,
            "candidates": candidates_path,
            "runtime_report": runtime_report_path,
            "manifest": manifest_path,
        },
    )


def run_causal_intervention(config_path: Path, *, adapter: StageAdapter) -> KernelRunResult:
    config = _load_yaml(config_path)
    localization_source = Path(config["localization_source"]).expanduser()
    study_id = config["study_id"]
    output_dir = Path(config.get("run", {}).get("output_dir", adapter.runs_root / study_id)).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "study_summary.json"
    predictions_path = output_dir / "intervention_predictions.jsonl"
    metrics_path = output_dir / "intervention_metrics.json"
    manifest_path = output_dir / "study_manifest.json"

    compare_manifest_path = Path(config["evaluation"]["compare_against"]).expanduser()
    compare_manifest = _load_json(compare_manifest_path)

    if not localization_source.exists():
        summary = {
            "study_id": study_id,
            "phase": config["phase"],
            "status": "blocked",
            "localization_source": str(localization_source),
            "compare_against": str(compare_manifest_path),
            "notes": _normalize_notes(config.get("reporting", {}).get("notes", [])),
        }
        _write_json(summary_path, summary)
        manifest = _build_manifest(
            adapter=adapter,
            stage_id="causal-intervention",
            loop_id=study_id,
            mode=DEFAULT_OPERATING_MODE,
            claim_state="exploratory",
            mission_id=compare_manifest.get("mission_id", UNKNOWN_MISSION_ID),
            resource_tier=compare_manifest.get("resource_tier", "cpu-smoke"),
            execution_profile=compare_manifest.get("execution_profile", "intervention-proxy"),
            model=_merge_model_config(config.get("model", {}), compare_manifest.get("model", {})),
            dataset=compare_manifest.get("dataset", {}),
            prompt=compare_manifest.get("prompt", {}),
            output_dir=output_dir,
            command=f"causal-intervention --config {config_path}",
            seed=int(config.get("run", {}).get("seed", 0)),
            notes=_normalize_notes(
                [
                    "Blocked because localization evidence is missing.",
                    config.get("reporting", {}).get("notes", []),
                ]
            ),
            metrics={"localization_source_exists": False},
            stage_context={
                "localization_source": str(localization_source),
                "compare_against": str(compare_manifest_path),
                "proxy_kernel": True,
            },
            report_paths=[str(summary_path)],
            status="blocked",
        )
        _validate_manifest(manifest)
        _write_json(manifest_path, manifest)
        return KernelRunResult(
            stage_id="causal-intervention",
            status="blocked",
            output_dir=output_dir,
            manifest_path=manifest_path,
            summary_path=summary_path,
            artifacts={"summary": summary_path, "manifest": manifest_path},
        )

    localization_manifest = _load_json(localization_source)
    candidates_path = Path(
        localization_manifest.get("stage_context", {})
        .get("artifacts", {})
        .get("candidates_path", localization_source.parent / "localization_candidates.json")
    ).expanduser()
    candidates_payload = _load_json(candidates_path)
    candidates = candidates_payload.get("candidate_units", [])
    dataset_filters = dict(localization_manifest.get("stage_context", {}).get("dataset_filters", {}))
    promotion_manifest_path = Path(
        localization_manifest.get("dataset", {}).get("provenance")
        or compare_manifest.get("dataset", {}).get("provenance")
        or adapter.default_promotion_manifest()
    ).expanduser()
    dataset_bundle = _load_dataset_bundle(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        tiers=dataset_filters.get("tiers"),
        split_kinds=dataset_filters.get("split_kinds"),
        split_families=dataset_filters.get("split_families"),
        lexicalizations=dataset_filters.get("lexicalizations"),
        rule_families=dataset_filters.get("rule_families"),
        limit=dataset_filters.get("limit_examples"),
    )

    model_cfg = _merge_model_config(config.get("model", {}), compare_manifest.get("model", {}))
    prompt_cfg = compare_manifest.get("prompt", config.get("prompt", {}))
    _configure_adapter_model_family(adapter, model_cfg)
    _configure_adapter_prompt(adapter, prompt_cfg)
    prompt_samples = [adapter.format_prompt(example) for example, _ in dataset_bundle["examples"]]
    execution_plan, predictor = _autotune_execution_plan(
        "causal-intervention",
        execution_profile=str(compare_manifest.get("execution_profile", "intervention-proxy")),
        model_cfg=model_cfg,
        prompts=prompt_samples,
        runtime_contract=_adapter_runtime_contract(adapter),
    )
    model_cfg["backend"] = execution_plan.resolved_backend
    model_cfg["max_new_tokens"] = int(execution_plan.max_new_tokens)
    baseline_records = _run_predictions(
        adapter,
        predictor,
        dataset_bundle["examples"],
        predictions_path=None,
    )
    runtime_report_path = output_dir / "runtime_report.json"
    runtime_report = _build_runtime_report(
        stage_id="causal-intervention",
        execution_plan=execution_plan,
        predictor=predictor,
        model=model_cfg,
        output_dir=output_dir,
    )
    _write_json(runtime_report_path, runtime_report)
    runtime_manifest_payload = _runtime_manifest_payload(runtime_report)
    targeted_units = _select_target_units(config["model"].get("target_layers"), candidates)
    post_records, intervention_metrics = _apply_intervention_proxy(
        baseline_records,
        candidates=candidates,
        targeted_units=targeted_units,
        strength=str(config["intervention"].get("strength", "small")),
        side_effect_response=str(config["intervention"].get("side_effect_response", "preserve")).lower(),
        metric_fn=adapter.compute_metrics,
    )
    _write_jsonl(predictions_path, post_records)
    _write_json(metrics_path, intervention_metrics)

    summary = {
        "study_id": study_id,
        "phase": config["phase"],
        "status": "completed",
        "localization_source": str(localization_source),
        "compare_against": str(compare_manifest_path),
        "targeted_units": targeted_units,
        "accuracy_delta": intervention_metrics["accuracy_delta"],
        "notes": _normalize_notes(
            [
                "DeepLoop runnable kernel executed a deterministic intervention proxy rather than a prep-only gate.",
                config.get("reporting", {}).get("notes", []),
            ]
        ),
    }
    _write_json(summary_path, summary)

    manifest = _build_manifest(
        adapter=adapter,
        stage_id="causal-intervention",
        loop_id=study_id,
        mode=DEFAULT_OPERATING_MODE,
        claim_state="exploratory",
        mission_id=compare_manifest.get("mission_id", UNKNOWN_MISSION_ID),
        resource_tier=compare_manifest.get("resource_tier", "cpu-smoke"),
        execution_profile=compare_manifest.get("execution_profile", "intervention-proxy"),
        model=model_cfg,
        dataset={
            "name": _dataset_name(adapter, dataset_bundle["promotion_manifest"]),
            "slice": _selection_slice(dataset_bundle["selected_files"]),
            "provenance": str(promotion_manifest_path),
        },
        prompt=prompt_cfg
        if isinstance(prompt_cfg, dict)
        else {"template_id": adapter.prompt_template_id, "parser_id": getattr(adapter, "parser_id", "unknown-parser")},
        output_dir=output_dir,
        command=f"causal-intervention --config {config_path}",
        seed=int(config.get("run", {}).get("seed", 0)),
        notes=_normalize_notes(
            [
                "Deterministic proxy intervention; model-internals execution remains future work.",
                config.get("reporting", {}).get("notes", []),
            ]
        ),
        metrics={
            "accuracy_pre": intervention_metrics["pre_metrics"].get("accuracy"),
            "accuracy_post": intervention_metrics["post_metrics"].get("accuracy"),
            "accuracy_delta": intervention_metrics["accuracy_delta"],
            "recoveries": intervention_metrics["recoveries"],
            "side_effect_count": intervention_metrics["side_effect_count"],
            "side_effect_rate": intervention_metrics["side_effect_rate"],
            **_runtime_telemetry_metrics(runtime_report),
        },
        stage_context={
            "localization_source": str(localization_source),
            "compare_against": str(compare_manifest_path),
            "targeted_units": targeted_units,
            "dataset_filters": dataset_filters,
            "execution_contract": runtime_manifest_payload["execution_plan"],
            "runtime_telemetry": runtime_manifest_payload["telemetry"],
            "runtime_budget": runtime_manifest_payload["budget"],
            "capabilities": runtime_manifest_payload["capabilities"],
            "runtime_autotune": runtime_manifest_payload["autotune"],
            "execution_search": runtime_manifest_payload["execution_search"],
            "artifacts": {
                "summary_path": str(summary_path),
                "predictions_path": str(predictions_path),
                "metrics_path": str(metrics_path),
                "candidates_path": str(candidates_path),
                "runtime_report_path": str(runtime_report_path),
            },
            "proxy_kernel": True,
            "intervention": config.get("intervention", {}),
        },
        report_paths=[str(summary_path), str(metrics_path), str(runtime_report_path)],
        runtime_payload={
            "execution_profile": runtime_manifest_payload["execution_plan"],
            "telemetry": runtime_manifest_payload["telemetry"],
            "budget": runtime_manifest_payload["budget"],
            "capabilities": runtime_manifest_payload["capabilities"],
            "autotune": runtime_manifest_payload["autotune"],
            "execution_search": runtime_manifest_payload["execution_search"],
            "runtime_report_path": str(runtime_report_path),
        },
    )
    _validate_manifest(manifest)
    _write_json(manifest_path, manifest)

    return KernelRunResult(
        stage_id="causal-intervention",
        status="completed",
        output_dir=output_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
        artifacts={
            "summary": summary_path,
            "predictions": predictions_path,
            "metrics": metrics_path,
            "runtime_report": runtime_report_path,
            "manifest": manifest_path,
        },
    )


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict | list) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _git_commit(repo_root: Path) -> str:
    return stage_kernel_reporting.git_commit(repo_root)


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
    except Exception as exc:
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
        except Exception as exc:
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


def _string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    return [str(raw)]


def _metric_path(raw: Any, *, default: tuple[str, ...]) -> tuple[str, ...]:
    path = tuple(_string_list(raw))
    return path or tuple(default)


def _metric_at_path(payload: Any, metric_path: tuple[str, ...]) -> float | None:
    current = payload
    for key in metric_path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    if current is None:
        return None
    return float(current)


def _prompt_sweep_reference_value(payload: Any, metric_path: tuple[str, ...]) -> float | None:
    if not isinstance(payload, dict):
        return None
    direct = _metric_at_path(payload, metric_path)
    if direct is not None:
        return direct
    if len(metric_path) >= 2 and metric_path[-1] == "score":
        current = payload.get(metric_path[0])
        if isinstance(current, (int, float)):
            return float(current)
    return None


def _prompt_sweep_selected_starter_reference(
    selected_starter: dict[str, Any],
    metric_path: tuple[str, ...],
) -> float | None:
    if not metric_path:
        return None
    metric_name = metric_path[0]
    candidate_keys = (
        f"locked_baseline_{metric_name}",
        f"baseline_{metric_name}",
        metric_name,
    )
    for key in candidate_keys:
        value = selected_starter.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _prompt_sweep_reference_payload(
    config: dict[str, Any],
    *,
    metric_path: tuple[str, ...],
    baseline_anchor: dict[str, Any],
) -> dict[str, Any]:
    promotion_reference = dict(config.get("promotion_reference", {}))
    selected_starter = dict(config.get("selected_starter", {}))
    reference_metrics_path = promotion_reference.get("baseline_metrics_path") or promotion_reference.get("metrics_path")
    reference_metrics = None
    if reference_metrics_path:
        reference_metrics = _load_json(Path(reference_metrics_path).expanduser())
    reference_score = None
    for candidate in (
        _prompt_sweep_reference_value(reference_metrics, metric_path),
        _prompt_sweep_reference_value(promotion_reference.get("reference_numbers"), metric_path),
        _prompt_sweep_selected_starter_reference(selected_starter, metric_path),
    ):
        if candidate is not None:
            reference_score = round(float(candidate), 4)
            break
    if reference_score is not None:
        return {
            "kind": str(promotion_reference.get("kind", "locked-baseline")),
            "label": str(
                promotion_reference.get("label")
                or promotion_reference.get("kind")
                or "locked-baseline"
            ),
            "run_id": promotion_reference.get("baseline_run_id") or selected_starter.get("locked_baseline_run_id"),
            "metrics_path": str(reference_metrics_path) if reference_metrics_path else None,
            "metrics": reference_metrics,
            "score": reference_score,
            "scoring_signatures": dict(promotion_reference.get("scoring_signatures", {})),
        }
    anchor_score = _metric_at_path(baseline_anchor["metrics"], metric_path)
    return {
        "kind": "baseline-anchor",
        "label": "baseline-anchor-replay",
        "run_id": None,
        "metrics_path": baseline_anchor["summary"]["artifacts"]["metrics_path"],
        "metrics": baseline_anchor["metrics"],
        "score": round(float(anchor_score), 4) if anchor_score is not None else None,
        "scoring_signatures": {},
    }


def _prompt_sweep_baseline_anchor_preflight(
    *,
    reference: dict[str, Any],
    baseline_anchor: dict[str, Any],
) -> dict[str, Any]:
    expected_signatures = dict(reference.get("scoring_signatures", {}))
    reference_metrics = reference.get("metrics")
    if not expected_signatures and isinstance(reference_metrics, dict):
        for metric_name in ("sacrebleu", "chrf"):
            metric_payload = reference_metrics.get(metric_name)
            if isinstance(metric_payload, dict) and metric_payload.get("signature"):
                expected_signatures[metric_name] = str(metric_payload["signature"])
    checks: list[dict[str, Any]] = []
    if not expected_signatures:
        return {
            "status": "not-applicable",
            "reference_kind": reference["kind"],
            "checks": checks,
        }
    for metric_name, expected in sorted(expected_signatures.items()):
        actual = None
        metric_payload = baseline_anchor["metrics"].get(metric_name)
        if isinstance(metric_payload, dict):
            actual = metric_payload.get("signature")
        checks.append(
            {
                "metric": metric_name,
                "expected": expected,
                "actual": actual,
                "status": "passed" if expected == actual else "failed",
            }
        )
    failures = [item for item in checks if item["status"] != "passed"]
    if failures:
        raise ValueError(
            "Prompt/decode baseline-anchor preflight failed: "
            + "; ".join(
                f"{item['metric']} expected {item['expected']} got {item['actual']}"
                for item in failures
            )
        )
    return {
        "status": "passed",
        "reference_kind": reference["kind"],
        "checks": checks,
    }


def _prompt_sweep_slice_metric(metric_payload: Any, metric_name: str) -> dict[str, Any]:
    nested = metric_payload.get(metric_name) if isinstance(metric_payload, dict) else None
    if isinstance(nested, dict):
        return {
            "score": nested.get("score"),
            "signature": nested.get("signature"),
        }
    return {
        "score": None,
        "signature": None,
    }


def _prompt_sweep_delta(candidate_value: Any, reference_value: Any) -> float | None:
    if candidate_value is None or reference_value is None:
        return None
    return round(float(candidate_value) - float(reference_value), 4)


def _prompt_sweep_diagnostic_slice_audit(
    *,
    direction: str,
    best_variant: dict[str, Any],
    reference: dict[str, Any],
    reference_metrics: dict[str, Any] | None,
    candidate_metrics: dict[str, Any],
    eligible_slice_ids: list[str],
) -> dict[str, Any]:
    reference_slices = dict(reference_metrics.get("diagnostic_slices", {})) if isinstance(reference_metrics, dict) else {}
    candidate_slices = dict(candidate_metrics.get("diagnostic_slices", {}))
    slices: dict[str, Any] = {}
    issues: list[str] = []
    for slice_id in eligible_slice_ids:
        reference_slice = reference_slices.get(slice_id, {})
        candidate_slice = candidate_slices.get(slice_id, {})
        candidate_count = candidate_slice.get("count") if isinstance(candidate_slice, dict) else None
        reference_count = reference_slice.get("count") if isinstance(reference_slice, dict) else None
        count = candidate_count if candidate_count is not None else reference_count
        if not isinstance(candidate_slice, dict):
            issues.append(f"missing-candidate-slice:{slice_id}")
        if count is None:
            issues.append(f"missing-count:{slice_id}")
        slices[slice_id] = {
            "count": count,
            "sacrebleu": _prompt_sweep_slice_metric(candidate_slice, "sacrebleu"),
            "chrf": _prompt_sweep_slice_metric(candidate_slice, "chrf"),
            "output_length_ratio": (
                candidate_slice.get("output_length_ratio") if isinstance(candidate_slice, dict) else None
            ),
            "reference_count": reference_count,
            "reference_sacrebleu": _prompt_sweep_slice_metric(reference_slice, "sacrebleu"),
            "reference_chrf": _prompt_sweep_slice_metric(reference_slice, "chrf"),
            "reference_output_length_ratio": (
                reference_slice.get("output_length_ratio") if isinstance(reference_slice, dict) else None
            ),
            "delta": {
                "sacrebleu": _prompt_sweep_delta(
                    _metric_at_path(candidate_slice, ("sacrebleu", "score")),
                    _metric_at_path(reference_slice, ("sacrebleu", "score")),
                ),
                "chrf": _prompt_sweep_delta(
                    _metric_at_path(candidate_slice, ("chrf", "score")),
                    _metric_at_path(reference_slice, ("chrf", "score")),
                ),
                "output_length_ratio": _prompt_sweep_delta(
                    candidate_slice.get("output_length_ratio") if isinstance(candidate_slice, dict) else None,
                    reference_slice.get("output_length_ratio") if isinstance(reference_slice, dict) else None,
                ),
            },
            "status": "ok" if count is not None and isinstance(candidate_slice, dict) else "incomplete",
        }
    return {
        "version": 1,
        "stage_id": "prompt-decode",
        "direction": direction,
        "reference": {
            "kind": reference["kind"],
            "label": reference["label"],
            "run_id": reference.get("run_id"),
            "metrics_path": reference.get("metrics_path"),
        },
        "candidate": {
            "variant_id": str(best_variant["variant_id"]),
        },
        "required_slice_ids": eligible_slice_ids,
        "clean": not issues,
        "issues": issues,
        "slices": slices,
    }


def _prompt_sweep_replication_gate(
    config: dict[str, Any],
    *,
    output_paths: dict[str, Path],
    manifest_path: Path,
    slice_audit: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    gate_cfg = dict(config.get("replication_gate", {}))
    required_artifacts = _string_list(gate_cfg.get("required_artifacts"))
    if not required_artifacts:
        required_artifacts = [
            str(manifest_path),
            str(output_paths["scoreboard_path"]),
            str(output_paths["promotion_decision_path"]),
            str(output_paths["summary_path"]),
            str(output_paths["diagnostic_slice_audit_path"]),
        ]
    artifact_statuses = [
        {
            "path": path,
            "exists": Path(path).expanduser().exists(),
        }
        for path in required_artifacts
    ]
    follow_up_manifest_complete = all(item["exists"] for item in artifact_statuses)
    follow_up_manifest_clean = (
        follow_up_manifest_complete
        and bool(slice_audit.get("clean"))
        and reference["kind"] != "baseline-anchor"
    )
    return {
        "status": "closed",
        "policy_status": str(gate_cfg.get("status", "closed-until-clean-follow-up")),
        "follow_up_manifest_complete": follow_up_manifest_complete,
        "follow_up_manifest_clean": follow_up_manifest_clean,
        "required_artifacts": required_artifacts,
        "artifact_statuses": artifact_statuses,
        "reason": (
            "Execution produced a follow-up package, but replication remains closed until critique reviews the clean manifest bundle."
        ),
    }


def _prompt_sweep_output_paths(config: dict[str, Any], *, direction: str, runtime_root: Path) -> dict[str, Path]:
    run_cfg = config.get("run", {})
    output_dir = Path(
        run_cfg.get("output_dir", runtime_root / "runs" / f"prompt-{direction}")
    ).expanduser()
    reports_dir = Path(config.get("reports_dir", runtime_root / "reports")).expanduser()
    return {
        "output_dir": output_dir,
        "reports_dir": reports_dir,
        "scoreboard_path": reports_dir / "prompt_decode_scoreboard.json",
        "promotion_decision_path": reports_dir / "prompt_decode_promotion_decision.json",
        "diagnostic_slice_audit_path": reports_dir / "diagnostic_slice_audit.json",
        "summary_path": output_dir / "summary.json",
        "crash_notes_path": Path(config.get("crash_notes_path", runtime_root / "crash_stability_notes.json")).expanduser(),
    }


def _prompt_sweep_selection_config(
    dataset_materialization: dict[str, Any],
    key: str,
    direction: str,
) -> dict[str, Any]:
    defaults = {
        "primary_dev_selection": {"tiers": ["primary-dev"], "split_kinds": ["primary-dev"]},
        "secondary_holdout_selection": {"tiers": ["secondary-holdout"], "split_kinds": ["secondary-holdout"]},
        "final_test_selection": {"tiers": ["final-test"], "split_kinds": ["final-test"]},
    }
    selection = deepcopy(defaults.get(key, {}))
    selection.update(deepcopy(dataset_materialization.get(key, {})))
    selection["split_families"] = _string_list(selection.get("split_families")) or [direction]
    if "limit_examples" not in selection and dataset_materialization.get("limit_examples") is not None:
        selection["limit_examples"] = int(dataset_materialization["limit_examples"])
    return selection


def _prompt_sweep_selection(
    adapter: StageAdapter,
    *,
    promotion_manifest_path: Path,
    selection: dict[str, Any],
) -> dict[str, Any]:
    return _load_dataset_bundle(
        adapter,
        promotion_manifest_path=promotion_manifest_path,
        tiers=_string_list(selection.get("tiers")),
        split_kinds=_string_list(selection.get("split_kinds")),
        split_families=_string_list(selection.get("split_families")),
        lexicalizations=_string_list(selection.get("lexicalizations")) or None,
        rule_families=_string_list(selection.get("rule_families")) or None,
        limit=int(selection["limit_examples"]) if selection.get("limit_examples") is not None else None,
    )


def _prompt_sweep_model_config(config: dict[str, Any]) -> dict[str, Any]:
    runtime_lock = dict(config.get("runtime_lock", {}))
    selected_starter = dict(config.get("selected_starter", {}))
    identifier = (
        runtime_lock.get("resolved_model_path")
        or runtime_lock.get("resolved_model_id")
        or selected_starter.get("resolved_model_id")
        or config.get("model", {}).get("identifier")
    )
    if not identifier:
        raise ValueError("prompt-decode-sweep requires a resolved model path or identifier in runtime_lock.")
    family = str(
        runtime_lock.get("family")
        or config.get("model", {}).get("family")
        or ("qwen3.5" if "qwen" in str(identifier).lower() else "unknown")
    )
    return {
        "family": family,
        "identifier": str(identifier),
        "backend": str(runtime_lock.get("backend", config.get("model", {}).get("backend", "local-transformers"))),
        "dtype": str(runtime_lock.get("dtype", config.get("model", {}).get("dtype", "float16"))),
        "max_new_tokens": int(
            runtime_lock.get("max_new_tokens", config.get("model", {}).get("max_new_tokens", 256)) or 256
        ),
    }


def _decode_policy_config(raw_decode: Any, *, decode_policy: Any, max_new_tokens: int) -> dict[str, Any]:
    if isinstance(raw_decode, dict):
        return _normalize_generation_config(raw_decode, max_new_tokens=max_new_tokens)
    policy = str(decode_policy or "greedy")
    if policy == "greedy":
        return _normalize_generation_config(
            {
                "do_sample": False,
                "temperature": 0.0,
                "top_p": 1.0,
                "repetition_penalty": 1.0,
                "max_new_tokens": max_new_tokens,
            },
            max_new_tokens=max_new_tokens,
        )
    if policy == "temperature-0.2":
        return _normalize_generation_config(
            {
                "do_sample": True,
                "temperature": 0.2,
                "top_p": 0.95,
                "repetition_penalty": 1.02,
                "max_new_tokens": max_new_tokens,
            },
            max_new_tokens=max_new_tokens,
        )
    raise ValueError(f"Unsupported prompt/decode policy: {policy}")


def _prompt_sweep_split_execution(
    adapter: StageAdapter,
    predictor: Any,
    *,
    examples: list[tuple[dict, dict]],
    split_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / f"{split_id}_predictions.jsonl"
    metrics_path = output_dir / f"{split_id}_metrics.json"
    started = time.monotonic()
    records = _run_predictions(adapter, predictor, examples, predictions_path=predictions_path)
    elapsed_s = max(time.monotonic() - started, 1e-9)
    metrics = adapter.compute_metrics(records)
    _write_json(metrics_path, metrics)
    return {
        "records": records,
        "metrics": metrics,
        "runtime_gpu_hours": round(elapsed_s / 3600.0, 6),
        "artifacts": {
            "predictions_path": str(predictions_path),
            "metrics_path": str(metrics_path),
        },
    }


def _prompt_sweep_prompt_samples(
    adapter: StageAdapter,
    examples: list[tuple[dict, dict]],
) -> list[str]:
    sample_examples = examples[: min(len(examples), 4)]
    return [adapter.format_prompt(example) for example, _ in sample_examples]


def _run_prompt_sweep_variant(
    *,
    adapter: StageAdapter,
    stage_id: str,
    execution_profile: str,
    model_cfg: dict[str, Any],
    variant: dict[str, Any],
    decode_config: dict[str, Any],
    primary_examples: list[tuple[dict, dict]],
    holdout_examples: list[tuple[dict, dict]],
    output_dir: Path,
    seed: int,
) -> dict[str, Any]:
    _configure_adapter_prompt(adapter, {"template_id": variant["template_id"]})
    prompt_samples = _prompt_sweep_prompt_samples(adapter, primary_examples or holdout_examples)
    execution_plan, predictor = _autotune_execution_plan(
        stage_id,
        execution_profile=execution_profile,
        model_cfg=model_cfg,
        prompts=prompt_samples,
        runtime_contract=_adapter_runtime_contract(adapter),
        decode_config=decode_config,
    )
    primary_run = _prompt_sweep_split_execution(
        adapter,
        predictor,
        examples=primary_examples,
        split_id="primary_dev",
        output_dir=output_dir,
    )
    holdout_run = _prompt_sweep_split_execution(
        adapter,
        predictor,
        examples=holdout_examples,
        split_id="secondary_holdout",
        output_dir=output_dir,
    )
    runtime_report = _build_runtime_report(
        stage_id=stage_id,
        execution_plan=execution_plan,
        predictor=predictor,
        model=model_cfg,
        output_dir=output_dir,
    )
    runtime_report_path = output_dir / "runtime_report.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(runtime_report_path, runtime_report)
    return {
        "prompt_family": str(variant.get("prompt_family", variant.get("template_id", "unknown"))),
        "primary_metrics": primary_run["metrics"],
        "holdout_metrics": holdout_run["metrics"],
        "primary_runtime_gpu_hours": primary_run["runtime_gpu_hours"],
        "holdout_runtime_gpu_hours": holdout_run["runtime_gpu_hours"],
        "runtime_gpu_hours": round(primary_run["runtime_gpu_hours"] + holdout_run["runtime_gpu_hours"], 6),
        "execution_plan": execution_plan.to_dict(),
        "seed": seed,
        "artifacts": {
            "primary_dev": primary_run["artifacts"],
            "secondary_holdout": holdout_run["artifacts"],
            "runtime_report_path": str(runtime_report_path),
        },
    }


def _run_prompt_sweep_baseline_anchor(
    *,
    adapter: StageAdapter,
    stage_id: str,
    execution_profile: str,
    model_cfg: dict[str, Any],
    template_id: str,
    final_examples: list[tuple[dict, dict]],
    output_dir: Path,
    seed: int,
) -> dict[str, Any]:
    _configure_adapter_prompt(adapter, {"template_id": template_id})
    prompt_samples = _prompt_sweep_prompt_samples(adapter, final_examples)
    execution_plan, predictor = _autotune_execution_plan(
        stage_id,
        execution_profile=execution_profile,
        model_cfg=model_cfg,
        prompts=prompt_samples,
        runtime_contract=_adapter_runtime_contract(adapter),
    )
    final_run = _prompt_sweep_split_execution(
        adapter,
        predictor,
        examples=final_examples,
        split_id="final_test",
        output_dir=output_dir,
    )
    runtime_report = _build_runtime_report(
        stage_id=stage_id,
        execution_plan=execution_plan,
        predictor=predictor,
        model=model_cfg,
        output_dir=output_dir,
    )
    runtime_report_path = output_dir / "runtime_report.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(runtime_report_path, runtime_report)
    return {
        "metrics": final_run["metrics"],
        "runtime_gpu_hours": final_run["runtime_gpu_hours"],
        "summary": {
            "template_id": template_id,
            "score": _metric_at_path(final_run["metrics"], ("sacrebleu", "score"))
            if _metric_at_path(final_run["metrics"], ("sacrebleu", "score")) is not None
            else final_run["metrics"],
            "artifacts": {
                **final_run["artifacts"],
                "runtime_report_path": str(runtime_report_path),
            },
            "seed": seed,
        },
    }


def _run_prompt_sweep_final_candidate(
    *,
    adapter: StageAdapter,
    stage_id: str,
    execution_profile: str,
    model_cfg: dict[str, Any],
    variant: dict[str, Any],
    decode_config: dict[str, Any],
    final_examples: list[tuple[dict, dict]],
    output_dir: Path,
    seed: int,
) -> dict[str, Any]:
    final_output_dir = output_dir / "final-test"
    _configure_adapter_prompt(adapter, {"template_id": variant["template_id"]})
    prompt_samples = _prompt_sweep_prompt_samples(adapter, final_examples)
    execution_plan, predictor = _autotune_execution_plan(
        stage_id,
        execution_profile=execution_profile,
        model_cfg=model_cfg,
        prompts=prompt_samples,
        runtime_contract=_adapter_runtime_contract(adapter),
        decode_config=decode_config,
    )
    final_run = _prompt_sweep_split_execution(
        adapter,
        predictor,
        examples=final_examples,
        split_id="final_test",
        output_dir=final_output_dir,
    )
    runtime_report = _build_runtime_report(
        stage_id=stage_id,
        execution_plan=execution_plan,
        predictor=predictor,
        model=model_cfg,
        output_dir=final_output_dir,
    )
    runtime_report_path = final_output_dir / "runtime_report.json"
    final_output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(runtime_report_path, runtime_report)
    return {
        "metrics": final_run["metrics"],
        "runtime_gpu_hours": final_run["runtime_gpu_hours"],
        "artifacts": {
            **final_run["artifacts"],
            "runtime_report_path": str(runtime_report_path),
        },
        "seed": seed,
    }


def _select_best_prompt_variant(
    executed_results: list[dict[str, Any]],
    *,
    metric_path: tuple[str, ...],
) -> dict[str, Any]:
    def _sort_key(item: dict[str, Any]) -> tuple[float, float]:
        primary_score = _metric_at_path(item["result"]["primary_metrics"], metric_path)
        holdout_score = _metric_at_path(item["result"]["holdout_metrics"], metric_path)
        return (
            float(primary_score if primary_score is not None else float("-inf")),
            float(holdout_score if holdout_score is not None else float("-inf")),
        )

    return max(executed_results, key=_sort_key)


def _prompt_sweep_promotion_rules(config: dict[str, Any]) -> dict[str, Any]:
    default_rules = {
        "full_set_gain_threshold": 0.3,
        "slice_signal_override": {
            "required_slice_gain": 0.8,
            "required_slice_count": 2,
            "max_full_set_regression": -0.2,
            "eligible_slice_ids": [],
        },
    }
    rules = deepcopy(default_rules)
    rules.update(deepcopy(config.get("promotion_rules", {})))
    override = dict(default_rules["slice_signal_override"])
    override.update(deepcopy(rules.get("slice_signal_override", {})))
    override["eligible_slice_ids"] = _string_list(override.get("eligible_slice_ids"))
    rules["slice_signal_override"] = override
    return rules


def _prompt_sweep_slice_override(
    *,
    baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
    metric_path: tuple[str, ...],
    full_set_gain: float,
    override_rules: dict[str, Any],
) -> dict[str, Any]:
    slice_gains: dict[str, Any] = {}
    winning_slice_ids: list[str] = []
    required_gain = float(override_rules.get("required_slice_gain", 0.8))
    eligible_slice_ids = _string_list(override_rules.get("eligible_slice_ids"))
    baseline_slices = dict(baseline_metrics.get("diagnostic_slices", {}))
    candidate_slices = dict(candidate_metrics.get("diagnostic_slices", {}))
    for slice_id in eligible_slice_ids:
        baseline_score = _metric_at_path(baseline_slices.get(slice_id), metric_path)
        candidate_score = _metric_at_path(candidate_slices.get(slice_id), metric_path)
        if baseline_score is None or candidate_score is None:
            continue
        gain = round(candidate_score - baseline_score, 4)
        slice_gains[slice_id] = {
            "baseline": baseline_score,
            "candidate": candidate_score,
            "gain_vs_baseline": gain,
            "count": candidate_slices.get(slice_id, {}).get("count"),
        }
        if gain >= required_gain:
            winning_slice_ids.append(slice_id)
    max_full_set_regression = float(override_rules.get("max_full_set_regression", -0.2))
    required_count = int(override_rules.get("required_slice_count", 2))
    return {
        "passes": full_set_gain >= max_full_set_regression and len(winning_slice_ids) >= required_count,
        "winning_slice_ids": winning_slice_ids,
        "slice_gains": slice_gains,
    }


def _prompt_sweep_promotion_decision(
    *,
    best_variant: dict[str, Any],
    best_row: dict[str, Any],
    best_result: dict[str, Any],
    final_result: dict[str, Any],
    reference: dict[str, Any],
    baseline_anchor: dict[str, Any],
    baseline_anchor_preflight: dict[str, Any],
    slice_override: dict[str, Any],
    promotion_rules: dict[str, Any],
    metric_path: tuple[str, ...],
) -> dict[str, Any]:
    full_set_gain = float(best_row["wmt19_final"]["gain_vs_reference"])
    threshold = float(promotion_rules.get("full_set_gain_threshold", 0.3))
    decision = "promote" if full_set_gain >= threshold or slice_override["passes"] else "no-promotion"
    best_candidate = {
        "variant_id": best_variant["variant_id"],
        "primary_score": _metric_at_path(best_result["primary_metrics"], metric_path),
        "holdout_score": _metric_at_path(best_result["holdout_metrics"], metric_path),
        "final_score": _metric_at_path(final_result["metrics"], metric_path),
        "gain_vs_reference": full_set_gain,
        "reference_label": reference["label"],
        "slice_override": slice_override,
        "artifacts": {
            **best_result["artifacts"],
            "final_test": final_result["artifacts"],
        },
    }
    if reference["kind"] == "baseline-anchor":
        best_candidate["gain_vs_baseline_anchor"] = full_set_gain
    else:
        best_candidate["gain_vs_locked_baseline"] = full_set_gain
    return {
        "version": 2,
        "stage_id": "prompt-decode",
        "decision": decision,
        "reference": {
            "kind": reference["kind"],
            "label": reference["label"],
            "run_id": reference.get("run_id"),
            "metrics_path": reference.get("metrics_path"),
            "score": reference.get("score"),
        },
        "baseline_anchor": baseline_anchor["summary"],
        "baseline_anchor_preflight": baseline_anchor_preflight,
        "best_candidate": best_candidate,
        "rules": promotion_rules,
    }


def _update_prompt_sweep_crash_notes(
    path: Path,
    *,
    summary: dict[str, Any],
    scoreboard_path: Path,
    promotion_decision_path: Path,
    summary_path: Path,
    diagnostic_slice_audit_path: Path,
) -> None:
    payload = {}
    if path.exists():
        loaded = _load_json(path)
        if isinstance(loaded, dict):
            payload = loaded
    payload["prompt_decode_stage"] = {
        "status": summary["status"],
        "executed_variant_ids": summary["executed_variant_ids"],
        "skipped_variant_ids": summary["skipped_variant_ids"],
        "issues": [],
        "artifacts": {
            "scoreboard_path": str(scoreboard_path),
            "promotion_decision_path": str(promotion_decision_path),
            "diagnostic_slice_audit_path": str(diagnostic_slice_audit_path),
            "summary_path": str(summary_path),
        },
    }
    _write_json(path, payload)


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


def _mechanistic_proxy_outputs(records: list[dict], *, allowed_units: list[str], methods: dict) -> tuple[list[dict], list[dict]]:
    grouped: dict[str, dict] = {
        unit: {
            "examples": 0,
            "failing_examples": 0,
            "proxy_recovery_score": 0.0,
            "proxy_collateral_risk": 0.0,
            "rule_counts": {},
            "split_counts": {},
        }
        for unit in allowed_units
    }
    observations: list[dict] = []

    for record in records:
        candidate_unit = _assign_proxy_unit(record, allowed_units)
        is_correct = record.get("predicted_label") == record.get("gold_label")
        chain_len = int(record.get("chain_len", 0) or 0)
        recovery_weight = 1.0 + (0.2 * min(chain_len, 5)) + (0.3 if record.get("split_family") != "iid" else 0.0)
        collateral_risk = 0.15 + (0.1 if record.get("lex") == "delex" else 0.0)
        observation = {
            **record,
            "candidate_unit": candidate_unit,
            "was_correct": is_correct,
            "recovery_score_proxy": round(recovery_weight if not is_correct else 0.0, 6),
            "collateral_risk_proxy": round(collateral_risk if is_correct else collateral_risk / 2, 6),
        }
        observations.append(observation)

        bucket = grouped[candidate_unit]
        bucket["examples"] += 1
        bucket["proxy_collateral_risk"] += observation["collateral_risk_proxy"]
        rule = str(record.get("rule", "unknown"))
        split_family = str(record.get("split_family", "unknown"))
        bucket["rule_counts"][rule] = bucket["rule_counts"].get(rule, 0) + 1
        bucket["split_counts"][split_family] = bucket["split_counts"].get(split_family, 0) + 1
        if not is_correct:
            bucket["failing_examples"] += 1
            bucket["proxy_recovery_score"] += observation["recovery_score_proxy"]

    enabled_methods = [name for name, enabled in methods.items() if enabled]
    candidates: list[dict] = []
    for unit, payload in grouped.items():
        examples = payload["examples"]
        normalized_score = payload["proxy_recovery_score"] - (0.5 * payload["proxy_collateral_risk"])
        dominant_rules = sorted(payload["rule_counts"], key=payload["rule_counts"].get, reverse=True)[:3]
        dominant_splits = sorted(payload["split_counts"], key=payload["split_counts"].get, reverse=True)[:3]
        candidates.append(
            {
                "unit_id": unit,
                "examples": examples,
                "failing_examples": payload["failing_examples"],
                "error_rate": round(payload["failing_examples"] / examples, 6) if examples else None,
                "proxy_recovery_score": round(payload["proxy_recovery_score"], 6),
                "proxy_collateral_risk": round(payload["proxy_collateral_risk"], 6),
                "normalized_score": round(normalized_score, 6),
                "dominant_rule_families": dominant_rules,
                "dominant_split_families": dominant_splits,
                "methods": enabled_methods,
            }
        )
    candidates.sort(key=lambda item: item["normalized_score"], reverse=True)
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    return observations, candidates


def _select_target_units(target_layers: Any, candidates: list[dict]) -> list[str]:
    requested_units = _units_from_layer_spec(target_layers)
    available_units = [candidate["unit_id"] for candidate in candidates if candidate["normalized_score"] >= 0]
    if not available_units:
        available_units = [candidate["unit_id"] for candidate in candidates]
    intersection = [unit for unit in requested_units if unit in available_units]
    if intersection:
        return intersection
    return available_units[:2] if len(available_units) > 1 else available_units


def _apply_intervention_proxy(
    baseline_records: list[dict],
    *,
    candidates: list[dict],
    targeted_units: list[str],
    strength: str,
    side_effect_response: str,
    metric_fn: Any,
) -> tuple[list[dict], dict]:
    candidate_map = {candidate["unit_id"]: candidate for candidate in candidates}
    allowed_units = targeted_units or [candidate["unit_id"] for candidate in candidates] or list(ZONE_ORDER)
    strength_factor = _strength_factor(strength)

    max_score = max((max(candidate["normalized_score"], 0.0) for candidate in candidates), default=1.0) or 1.0
    post_records: list[dict] = []
    recoveries = 0
    side_effect_count = 0
    originally_correct = 0

    for record in baseline_records:
        post_record = dict(record)
        candidate_unit = _assign_proxy_unit(record, allowed_units)
        candidate = candidate_map.get(candidate_unit, {"normalized_score": 0.0, "dominant_split_families": []})
        score_factor = max(candidate.get("normalized_score", 0.0), 0.0) / max_score
        targeted = candidate_unit in targeted_units
        was_correct = record.get("predicted_label") == record.get("gold_label")
        if was_correct:
            originally_correct += 1

        effect = "unchanged"
        if targeted and not was_correct and (strength_factor + score_factor) >= 0.75:
            post_record["predicted_label"] = post_record["gold_label"]
            effect = "recovered"
            recoveries += 1
        else:
            dominant_splits = set(candidate.get("dominant_split_families", []))
            collateral_slice = targeted and was_correct and record.get("split_family") not in dominant_splits
            if collateral_slice and strength_factor >= 0.8 and "reduce" not in side_effect_response:
                post_record["predicted_label"] = _flip_label(str(post_record.get("predicted_label", "unparsed")))
                effect = "collateral"
                side_effect_count += 1
            elif collateral_slice:
                effect = "attenuated"

        post_record["candidate_unit"] = candidate_unit
        post_record["intervention_applied"] = targeted
        post_record["intervention_effect"] = effect
        post_records.append(post_record)

    pre_metrics = metric_fn(baseline_records)
    post_metrics = metric_fn(post_records)
    post_correct = sum(1 for record in post_records if record.get("predicted_label") == record.get("gold_label"))
    pre_correct = sum(1 for record in baseline_records if record.get("predicted_label") == record.get("gold_label"))
    accuracy_delta = (
        round(post_metrics["accuracy"] - pre_metrics["accuracy"], 6)
        if pre_metrics.get("accuracy") is not None and post_metrics.get("accuracy") is not None
        else None
    )
    side_effect_rate = round(side_effect_count / originally_correct, 6) if originally_correct else None

    metrics = {
        "pre_metrics": pre_metrics,
        "post_metrics": post_metrics,
        "recoveries": recoveries,
        "side_effect_count": side_effect_count,
        "side_effect_rate": side_effect_rate,
        "accuracy_delta": accuracy_delta,
        "pre_correct": pre_correct,
        "post_correct": post_correct,
        "targeted_units": targeted_units,
    }
    return post_records, metrics


def _strength_factor(strength: str) -> float:
    lowered = strength.lower()
    if "large" in lowered or "strong" in lowered:
        return 0.85
    if "medium" in lowered or "sweep" in lowered:
        return 0.65
    return 0.45


def _flip_label(label: str) -> str:
    lowered = label.lower()
    if lowered == "entailment":
        return "contradiction"
    if lowered == "contradiction":
        return "entailment"
    return "unparsed"
