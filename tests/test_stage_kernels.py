from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import RUNS_DIR, SCRATCH_DIR
from deeploop.runtime.stage_kernels import (
    ExecutionProfilePlan,
    _configure_adapter_prompt,
    _configure_generation_tokenizer,
    _autotune_execution_plan,
    _load_dataset_bundle,
    _maybe_autotune_batch_size,
    _resolve_execution_profile,
    _runtime_capability_probe,
    _run_predictions,
    get_stage_registry,
    run_stage_from_config,
)


DEMO_MANIFEST_ENV = "DEEPLOOP_STAGE_KERNEL_TEST_PROMOTION_MANIFEST"


class DemoAdapter:
    name = "demo.stage_adapter"
    substrate_name = "demo-substrate"
    substrate_repo_root = REPO_ROOT
    runs_root = RUNS_DIR / "demo-stage-kernel-tests"
    prompt_template_id = "demo_prompt_v1"
    parser_id = "demo_parser_v1"

    def __init__(self, promotion_manifest_path: Path) -> None:
        self._promotion_manifest_path = promotion_manifest_path
        self.configured_family: str | None = None
        self.configured_prompt_template: str | None = None

    def default_promotion_manifest(self) -> Path:
        return self._promotion_manifest_path

    def load_promotion_manifest(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def resolve_dataset_files(
        self,
        manifest: dict,
        *,
        tiers: list[str] | None = None,
        split_kinds: list[str] | None = None,
        split_families: list[str] | None = None,
    ) -> list[dict]:
        selected: list[dict] = []
        for item in manifest["files"]:
            if tiers and item["tier"] not in tiers:
                continue
            if split_kinds and item["split_kind"] not in split_kinds:
                continue
            if split_families and item["split_family"] not in split_families:
                continue
            selected.append(item)
        return selected

    def iter_examples(self, paths, *, limit: int | None = None):
        emitted = 0
        for path in paths:
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                yield json.loads(line)
                emitted += 1
                if limit is not None and emitted >= limit:
                    return

    def include_example(
        self,
        example: dict,
        *,
        lexicalizations: list[str] | None = None,
        rule_families: list[str] | None = None,
    ) -> bool:
        if lexicalizations and example["lex"] not in lexicalizations:
            return False
        if rule_families and example["rule"] not in rule_families:
            return False
        return True

    def format_prompt(self, example: dict) -> str:
        return json.dumps(
            {
                "hypothesis": example["hypothesis"],
                "rule": example["rule"],
                "prompt_template_id": self.configured_prompt_template or self.prompt_template_id,
            }
        )

    def configure_model_family(self, model_family: str | None) -> None:
        self.configured_family = None if model_family is None else str(model_family)

    def configure_prompt_template(self, prompt_template_id: str | None) -> None:
        self.configured_prompt_template = None if prompt_template_id is None else str(prompt_template_id)

    def runtime_contract(self) -> dict:
        return {
            "family": self.configured_family or "demo",
            "use_chat_template": False,
            "stop_markers": ["\nuser", "\nassistant"],
        }

    def normalize_prediction_output(self, text: str, *, prompt: str | None = None) -> str:
        normalized = text
        if prompt and text.startswith(prompt):
            normalized = text[len(prompt) :]
        return normalized.split("\nuser", 1)[0].strip()

    def parse_prediction(self, text: str) -> str:
        try:
            return str(json.loads(text).get("label", "unparsed"))
        except json.JSONDecodeError:
            return "unparsed"

    def compute_metrics(self, records: list[dict]) -> dict:
        total = len(records)
        correct = sum(1 for record in records if record["predicted_label"] == record["gold_label"])
        diagnostic_slices = {}
        slice_ids = sorted({slice_id for record in records for slice_id in record.get("slice_ids", [])})
        for slice_id in slice_ids:
            subset = [record for record in records if slice_id in record.get("slice_ids", [])]
            subset_total = len(subset)
            subset_correct = sum(1 for record in subset if record["predicted_label"] == record["gold_label"])
            diagnostic_slices[slice_id] = {
                "count": subset_total,
                "accuracy": round(subset_correct / subset_total, 6) if subset_total else None,
            }
        return {
            "count": total,
            "accuracy": round(correct / total, 6) if total else None,
            "diagnostic_slices": diagnostic_slices,
        }

    def build_prediction_record(
        self,
        example: dict,
        *,
        predicted_label: str,
        raw_output: str,
        source_metadata: dict,
    ) -> dict:
        return {
            "source_file": source_metadata["source"],
            "tier": example["tier"],
            "lex": example["lex"],
            "rule": example["rule"],
            "chain_len": example["chain_len"],
            "split_kind": source_metadata["split_kind"],
            "split_family": source_metadata["split_family"],
            "gold_label": example["label"],
            "predicted_label": predicted_label,
            "slice_ids": list(example.get("slice_ids", [])),
            "prompt_template_id": self.configured_prompt_template or self.prompt_template_id,
            "raw_output": raw_output,
        }

    def dataset_name(self, manifest: dict) -> str:
        return manifest["dataset_id"]


def build_demo_adapter() -> DemoAdapter:
    return DemoAdapter(Path(os.environ[DEMO_MANIFEST_ENV]))


class StageKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_root = SCRATCH_DIR / "stage-kernel-tests"
        self.run_root = RUNS_DIR / "stage-kernel-tests"
        shutil.rmtree(self.fixture_root, ignore_errors=True)
        shutil.rmtree(self.run_root, ignore_errors=True)
        self.fixture_root.mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)

        dataset_path = self.fixture_root / "demo_records.jsonl"
        records = [
            {
                "premises": ["A implies B"],
                "hypothesis": "B follows from A",
                "tier": "C",
                "lex": "lex",
                "rule": "symmetry_not_transitive",
                "chain_len": 1,
                "label": "entailment",
            },
            {
                "premises": ["C excludes D"],
                "hypothesis": "D is supported",
                "tier": "C",
                "lex": "delex",
                "rule": "transitivity_chain",
                "chain_len": 3,
                "label": "contradiction",
            },
            {
                "premises": ["E implies F", "F implies G"],
                "hypothesis": "G follows from E",
                "tier": "S",
                "lex": "lex",
                "rule": "transitivity_chain",
                "chain_len": 4,
                "label": "contradiction",
            },
        ]
        dataset_path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        self.promotion_manifest_path = self.fixture_root / "promotion_manifest.json"
        self.promotion_manifest_path.write_text(
            json.dumps(
                {
                    "dataset_id": "demo-dataset",
                    "files": [
                        {
                            "source": "demo_records.jsonl",
                            "local_path": str(dataset_path),
                            "tier": "C",
                            "split_kind": "dev",
                            "split_family": "iid",
                        },
                        {
                            "source": "demo_records.jsonl",
                            "local_path": str(dataset_path),
                            "tier": "S",
                            "split_kind": "dev",
                            "split_family": "length_ood",
                        },
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.adapter = DemoAdapter(self.promotion_manifest_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.fixture_root, ignore_errors=True)
        shutil.rmtree(self.run_root, ignore_errors=True)

    def test_stage_registry_contains_required_kernels(self) -> None:
        self.assertEqual(
            set(get_stage_registry()),
            {"baseline-evaluation", "prompt-decode-sweep", "mechanistic-localization", "causal-intervention"},
        )

    def test_prompt_decode_sweep_runs_from_shared_kernel(self) -> None:
        prompt_dataset_path = self.fixture_root / "prompt_records.jsonl"
        prompt_records = [
            {
                "premises": ["A implies B"],
                "hypothesis": "B follows from A",
                "tier": "C",
                "lex": "lex",
                "rule": "symmetry_not_transitive",
                "chain_len": 1,
                "label": "entailment",
                "slice_ids": ["difficulty-hard"],
            },
            {
                "premises": ["C excludes D"],
                "hypothesis": "D is supported",
                "tier": "C",
                "lex": "delex",
                "rule": "transitivity_chain",
                "chain_len": 3,
                "label": "contradiction",
                "slice_ids": [],
            },
        ]
        prompt_dataset_path.write_text(
            "".join(json.dumps(record) + "\n" for record in prompt_records),
            encoding="utf-8",
        )
        prompt_manifest_path = self.fixture_root / "prompt_promotion_manifest.json"
        prompt_manifest_path.write_text(
            json.dumps(
                {
                    "dataset_id": "prompt-demo",
                    "files": [
                        {
                            "source": "prompt_records.jsonl",
                            "local_path": str(prompt_dataset_path),
                            "tier": "primary-dev",
                            "split_kind": "primary-dev",
                            "split_family": "iid",
                        },
                        {
                            "source": "prompt_records.jsonl",
                            "local_path": str(prompt_dataset_path),
                            "tier": "secondary-holdout",
                            "split_kind": "secondary-holdout",
                            "split_family": "iid",
                        },
                        {
                            "source": "prompt_records.jsonl",
                            "local_path": str(prompt_dataset_path),
                            "tier": "final-test",
                            "split_kind": "final-test",
                            "split_family": "iid",
                        },
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        adapter = DemoAdapter(prompt_manifest_path)
        prompt_runtime_root = self.run_root / "prompt-runtime"
        prompt_output_dir = prompt_runtime_root / "runs" / "prompt-iid"
        baseline_metrics_path = self.fixture_root / "prompt_locked_baseline_metrics.json"
        baseline_metrics_path.write_text(
            json.dumps(
                {
                    "count": 2,
                    "accuracy": 0.25,
                    "diagnostic_slices": {
                        "difficulty-hard": {
                            "count": 1,
                            "accuracy": 0.0,
                        }
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        prompt_config = self.fixture_root / "prompt_decode.yaml"
        prompt_config.write_text(
            yaml.safe_dump(
                {
                    "mission_id": "demo-mission",
                    "loop_action_id": "demo-prompt-loop",
                    "mode": "human-directed",
                    "claim_state": "exploratory",
                    "resource_tier": "cpu-smoke",
                    "execution_profile": "qwen3_5-small-fp16",
                    "runtime_root": str(prompt_runtime_root),
                    "selected_direction": "iid",
                    "selected_starter": {
                        "run_id": "baseline-demo",
                        "starter_alias": "demo-starter",
                        "resolved_model_id": "mock://entailment",
                        "baseline_sacrebleu": 0.0,
                    },
                    "runtime_lock": {
                        "resolved_model_id": "mock://entailment",
                        "backend": "mock-entailment",
                        "dtype": "float16",
                        "context_bucket": "short",
                        "max_new_tokens": 64,
                    },
                    "dataset_materialization": {
                        "promotion_manifest_path": str(prompt_manifest_path),
                        "primary_dev_selection": {"split_kinds": ["primary-dev"], "split_families": ["iid"]},
                        "secondary_holdout_selection": {
                            "split_kinds": ["secondary-holdout"],
                            "split_families": ["iid"],
                        },
                        "final_test_selection": {"split_kinds": ["final-test"], "split_families": ["iid"]},
                    },
                    "metric_path": ["accuracy"],
                    "diagnostic_metric_path": ["accuracy"],
                    "promotion_rules": {
                        "full_set_gain_threshold": 0.05,
                        "slice_signal_override": {
                            "required_slice_gain": 0.0,
                            "required_slice_count": 0,
                            "max_full_set_regression": -1.0,
                            "eligible_slice_ids": [],
                        },
                    },
                    "promotion_reference": {
                        "kind": "locked-baseline",
                        "label": "locked-demo-baseline",
                        "baseline_run_id": "baseline-demo",
                        "baseline_metrics_path": str(baseline_metrics_path),
                        "reference_numbers": {"accuracy": 0.25},
                    },
                    "baseline_anchor_replay": {"template_id": "demo_baseline_prompt"},
                    "slice_audit": {
                        "required_slice_ids": ["difficulty-hard"],
                    },
                    "replication_gate": {
                        "status": "closed-until-clean-follow-up",
                    },
                    "variant_matrix": [
                        {
                            "variant_id": "v1-demo-greedy",
                            "template_id": "demo_prompt_variant_a",
                            "prompt_family": "demo-a",
                            "context_bucket": "short",
                            "decode_policy": "greedy",
                        },
                        {
                            "variant_id": "v2-demo-lowtemp",
                            "template_id": "demo_prompt_variant_b",
                            "prompt_family": "demo-b",
                            "context_bucket": "short",
                            "decode_policy": "temperature-0.2",
                        },
                    ],
                    "run": {"loop_id": "demo-prompt-sweep", "output_dir": str(prompt_output_dir)},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = run_stage_from_config("prompt-decode-sweep", prompt_config, adapter=adapter)

        summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        scoreboard = json.loads(result.artifacts["scoreboard"].read_text(encoding="utf-8"))
        decision = json.loads(result.artifacts["promotion_decision"].read_text(encoding="utf-8"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(manifest["stage"]["id"], "prompt-decode-sweep")
        self.assertEqual(summary["executed_variant_ids"], ["v1-demo-greedy", "v2-demo-lowtemp"])
        self.assertEqual(summary["skipped_variant_ids"], [])
        self.assertEqual(scoreboard["selected_direction"], "iid")
        self.assertEqual(decision["best_candidate"]["variant_id"], "v1-demo-greedy")
        self.assertEqual(decision["reference"]["kind"], "locked-baseline")
        self.assertEqual(decision["best_candidate"]["gain_vs_reference"], 0.25)
        self.assertEqual(decision["replication_gate"]["status"], "closed")
        self.assertTrue(decision["replication_gate"]["follow_up_manifest_complete"])
        self.assertTrue(decision["replication_gate"]["follow_up_manifest_clean"])
        self.assertTrue(result.artifacts["diagnostic_slice_audit"].exists())
        self.assertTrue((prompt_output_dir / "v1-demo-greedy" / "primary_dev_predictions.jsonl").exists())
        self.assertTrue((prompt_output_dir / "baseline-anchor" / "final_test_predictions.jsonl").exists())

    def test_run_predictions_batches_when_predictor_supports_it(self) -> None:
        class BatchPredictor:
            batch_size = 2

            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            def predict_many(self, prompts: list[str]) -> list[str]:
                self.calls.append(list(prompts))
                return [json.dumps({"label": "entailment"}) for _ in prompts]

        examples = [
            (
                {
                    "hypothesis": "B follows from A",
                    "tier": "C",
                    "lex": "lex",
                    "rule": "symmetry_not_transitive",
                    "chain_len": 1,
                    "label": "entailment",
                },
                {"source": "demo_records.jsonl", "split_kind": "dev", "split_family": "iid"},
            ),
            (
                {
                    "hypothesis": "D is supported",
                    "tier": "C",
                    "lex": "delex",
                    "rule": "transitivity_chain",
                    "chain_len": 3,
                    "label": "contradiction",
                },
                {"source": "demo_records.jsonl", "split_kind": "dev", "split_family": "iid"},
            ),
            (
                {
                    "hypothesis": "G follows from E",
                    "tier": "S",
                    "lex": "lex",
                    "rule": "transitivity_chain",
                    "chain_len": 4,
                    "label": "contradiction",
                },
                {"source": "demo_records.jsonl", "split_kind": "dev", "split_family": "length_ood"},
            ),
        ]
        predictions_path = self.fixture_root / "batched_predictions.jsonl"
        predictor = BatchPredictor()

        records = _run_predictions(
            self.adapter,
            predictor,
            examples,
            predictions_path=predictions_path,
        )

        self.assertEqual(len(records), 3)
        self.assertEqual([len(batch) for batch in predictor.calls], [2, 1])
        self.assertEqual(len(predictions_path.read_text(encoding="utf-8").splitlines()), 3)

    def test_run_predictions_normalizes_runtime_artifacts_before_parsing(self) -> None:
        class EchoingPredictor:
            def predict(self, prompt: str) -> str:
                return f"{prompt}\n{{\"label\": \"contradiction\"}}\nuser"

        examples = [
            (
                {
                    "hypothesis": "B follows from A",
                    "tier": "C",
                    "lex": "lex",
                    "rule": "symmetry_not_transitive",
                    "chain_len": 1,
                    "label": "contradiction",
                },
                {"source": "demo_records.jsonl", "split_kind": "dev", "split_family": "iid"},
            )
        ]

        records = _run_predictions(self.adapter, EchoingPredictor(), examples, predictions_path=None)
        self.assertEqual(records[0]["predicted_label"], "contradiction")
        self.assertIn("\"label\": \"contradiction\"", records[0]["raw_output"])

    def test_dataset_limit_round_robins_across_selected_files(self) -> None:
        bundle = _load_dataset_bundle(
            self.adapter,
            promotion_manifest_path=self.promotion_manifest_path,
            tiers=["C", "S"],
            split_kinds=["dev"],
            split_families=["iid", "length_ood"],
            lexicalizations=["lex", "delex"],
            rule_families=["symmetry_not_transitive", "transitivity_chain"],
            limit=2,
        )

        self.assertEqual(len(bundle["examples"]), 2)
        self.assertEqual(
            [source["split_family"] for _, source in bundle["examples"]],
            ["iid", "length_ood"],
        )

    def test_execution_profile_contract_resolves_bucket_and_backend(self) -> None:
        plan = _resolve_execution_profile(
            "qwen3_5-small-fp16",
            model_cfg={
                "family": "qwen3.5",
                "identifier": "Qwen3.5-2B-Base",
                "backend": "local-transformers",
                "max_new_tokens": 512,
            },
            prompts=[" ".join(["alpha"] * 96)],
        )

        self.assertEqual(plan.source, "inference-family-contract")
        self.assertEqual(plan.context_bucket, "short")
        self.assertEqual(plan.prompt_token_budget, 512)
        self.assertEqual(plan.max_new_tokens, 256)
        self.assertEqual(plan.batch_probe_order[0], 32)
        self.assertEqual(plan.resolved_backend, "local-transformers")
        self.assertIn("switch backend", plan.fallback_ladder)

    def test_generation_tokenizer_uses_left_padding_and_pad_token(self) -> None:
        tokenizer = type(
            "Tokenizer",
            (),
            {
                "pad_token_id": None,
                "eos_token_id": 7,
                "eos_token": "</s>",
                "padding_side": "right",
            },
        )()

        configured = _configure_generation_tokenizer(tokenizer)

        self.assertEqual(configured.pad_token, "</s>")
        self.assertEqual(configured.padding_side, "left")

    def test_generation_tokenizer_tolerates_read_only_padding_side(self) -> None:
        class ReadOnlyTokenizer:
            pad_token_id = 3
            eos_token_id = 7
            eos_token = "</s>"

            @property
            def padding_side(self) -> str:
                return "right"

        tokenizer = ReadOnlyTokenizer()

        configured = _configure_generation_tokenizer(tokenizer)

        self.assertIs(configured, tokenizer)
        self.assertEqual(configured.padding_side, "right")

    def test_configure_adapter_prompt_tolerates_read_only_prompt_template_id(
        self,
    ) -> None:
        class ReadOnlyAdapter:
            @property
            def prompt_template_id(self) -> str:
                return "unchanged"

        adapter = ReadOnlyAdapter()

        _configure_adapter_prompt(adapter, {"template_id": "demo_prompt_override"})

        self.assertEqual(adapter.prompt_template_id, "unchanged")

    def test_runtime_capability_probe_reports_gpu_and_backend_inventory(self) -> None:
        class FakeCuda:
            def is_available(self) -> bool:
                return True

            def current_device(self) -> int:
                return 0

            def get_device_properties(self, device_index: int):
                self._assert_device_index(device_index)
                return type("Props", (), {"total_memory": 48 * 1024 * 1024 * 1024})()

            def mem_get_info(self, device_index: int):
                self._assert_device_index(device_index)
                return (24 * 1024 * 1024 * 1024, 48 * 1024 * 1024 * 1024)

            def get_device_capability(self, device_index: int) -> tuple[int, int]:
                self._assert_device_index(device_index)
                return (8, 9)

            def device_count(self) -> int:
                return 1

            def get_device_name(self, device_index: int) -> str:
                self._assert_device_index(device_index)
                return "RTX Test"

            def is_bf16_supported(self, device_index: int) -> bool:
                self._assert_device_index(device_index)
                return True

            @staticmethod
            def _assert_device_index(device_index: int) -> None:
                if device_index != 0:
                    raise AssertionError("unexpected device index")

        predictor = type("Predictor", (), {"torch": type("Torch", (), {"cuda": FakeCuda()})()})()
        execution_plan = ExecutionProfilePlan(
            requested_profile="unit-profile",
            resolved_profile="unit-profile",
            source="unit-test",
            requested_backend="vllm",
            resolved_backend="local-transformers",
            contract_backend="vllm",
            context_bucket="short",
            prompt_token_budget=512,
            max_new_tokens=128,
            batch_probe_order=(16, 8, 4),
            fallback_ladder=("lower batch size", "switch backend"),
            contract_metrics=("peak_vram_mb",),
            gpu_memory_headroom_gb=6.0,
            applies_to_model=True,
        )

        probe = _runtime_capability_probe(
            predictor,
            execution_plan=execution_plan,
            model={"dtype": "float16"},
        )

        self.assertEqual(probe["selected_backend"], "local-transformers")
        self.assertTrue(probe["degraded_backend"])
        self.assertEqual(probe["machine"]["device_name"], "RTX Test")
        self.assertEqual(probe["machine"]["cuda_capability"], "8.9")
        self.assertEqual(probe["machine"]["gpu_count"], 1)
        self.assertEqual(probe["machine"]["total_vram_mb"], 49152.0)
        self.assertEqual(probe["machine"]["free_vram_mb"], 24576.0)
        self.assertTrue(probe["machine"]["dtype_support"]["bfloat16"])
        self.assertIn("vllm", probe["backends"])

    def test_batch_autotuner_prefers_headroom_safe_candidate(self) -> None:
        class FakeCuda:
            def __init__(self) -> None:
                self.last_batch_size = 0

            def is_available(self) -> bool:
                return True

            def current_device(self) -> int:
                return 0

            def get_device_properties(self, device_index: int):
                self._assert_device_index(device_index)
                return type("Props", (), {"total_memory": 10 * 1024 * 1024 * 1024})()

            def reset_peak_memory_stats(self) -> None:
                return None

            def max_memory_allocated(self) -> int:
                allocations = {
                    8: int(9.5 * 1024 * 1024 * 1024),
                    4: int(7.0 * 1024 * 1024 * 1024),
                    2: int(4.0 * 1024 * 1024 * 1024),
                }
                return allocations.get(self.last_batch_size, 0)

            def empty_cache(self) -> None:
                return None

            @staticmethod
            def _assert_device_index(device_index: int) -> None:
                if device_index != 0:
                    raise AssertionError("unexpected device index")

        class PredictiveBatcher:
            def __init__(self) -> None:
                self.batch_size = 8
                self.batch_probe_order = [8, 4, 2]
                self.runtime_stats = {
                    "execution_plan": {
                        "gpu_memory_headroom_gb": 2.0,
                        "context_bucket": "short",
                        "prompt_token_budget": 512,
                        "max_new_tokens": 64,
                        "resolved_backend": "local-transformers",
                    },
                    "stage_id": "baseline-evaluation",
                    "model": {
                        "family": "demo",
                        "identifier": "demo-model",
                        "dtype": "float16",
                    },
                    "autotune_cache_path": str(self_fixture_root / "autotune-cache.json"),
                }
                self.torch = type("Torch", (), {"cuda": FakeCuda()})()

            def _predict_batch(self, prompts: list[str]) -> list[str]:
                self.torch.cuda.last_batch_size = len(prompts)
                return ["token" for _ in prompts]

            def count_tokens(self, text: str) -> int:
                return len(text.split())

        self_fixture_root = self.fixture_root
        predictor = PredictiveBatcher()

        tuned = _maybe_autotune_batch_size(predictor, ["alpha prompt", "beta prompt"])

        self.assertEqual(tuned.batch_size, 4)
        self.assertEqual(tuned.batch_probe_order, [4, 2])
        self.assertEqual(tuned.runtime_stats["autotune"]["status"], "completed")
        self.assertEqual(tuned.runtime_stats["autotune"]["selected_batch_size"], 4)
        self.assertEqual(tuned.runtime_stats["autotune"]["cache"]["status"], "miss")
        self.assertTrue((self.fixture_root / "autotune-cache.json").exists())

    def test_batch_autotuner_reuses_cached_result(self) -> None:
        class CachedPredictor:
            def __init__(self, cache_path: Path) -> None:
                self.batch_size = 8
                self.batch_probe_order = [8, 4, 2]
                self.runtime_stats = {
                    "execution_plan": {
                        "gpu_memory_headroom_gb": 2.0,
                        "context_bucket": "short",
                        "prompt_token_budget": 512,
                        "max_new_tokens": 64,
                        "resolved_backend": "local-transformers",
                    },
                    "stage_id": "baseline-evaluation",
                    "model": {
                        "family": "demo",
                        "identifier": "demo-model",
                        "dtype": "float16",
                    },
                    "autotune_cache_path": str(cache_path),
                }

            def count_tokens(self, text: str) -> int:
                return len(text.split())

        cache_path = self.fixture_root / "autotune-cache.json"
        cache_key_payload = {
            "schema_version": 1,
            "stage_id": "baseline-evaluation",
            "backend": "local-transformers",
            "model_family": "demo",
            "model_identifier": "demo-model",
            "dtype": "float16",
            "context_bucket": "short",
            "prompt_token_budget": 512,
            "max_new_tokens": 64,
            "gpu_memory_headroom_gb": 2.0,
            "batch_probe_order": [2, 4, 8],
            "machine": {
                "gpu_available": False,
                "device_name": None,
                "cuda_capability": None,
                "total_vram_mb": None,
            },
            "prompt_signature": {
                "prompt_count": 2,
                "prompt_tokens_max": 2,
                "prompt_tokens_avg": 2.0,
            },
        }
        cache_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "entries": {
                        json.dumps(cache_key_payload, sort_keys=True): {
                            "updated_at": "2025-01-01T00:00:00+00:00",
                            "selected_batch_size": 4,
                            "peak_vram_mb": 4096.0,
                            "samples_per_s": 12.0,
                            "cache_key": cache_key_payload,
                        }
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        predictor = CachedPredictor(cache_path)
        tuned = _maybe_autotune_batch_size(predictor, ["alpha prompt", "beta prompt"])

        self.assertEqual(tuned.batch_size, 4)
        self.assertEqual(tuned.batch_probe_order, [4, 2])
        self.assertEqual(tuned.runtime_stats["autotune"]["strategy"], "cache-reuse")
        self.assertEqual(tuned.runtime_stats["autotune"]["cache"]["status"], "hit")

    def test_execution_plan_autotuner_can_switch_to_faster_backend(self) -> None:
        class FakePredictor:
            def __init__(self, backend: str, execution_plan: ExecutionProfilePlan) -> None:
                self.backend = backend
                self.batch_size = execution_plan.batch_probe_order[0] if execution_plan.batch_probe_order else 1
                self.batch_probe_order = list(execution_plan.batch_probe_order)
                self.max_new_tokens = execution_plan.max_new_tokens
                self.runtime_stats = {"execution_plan": execution_plan.to_dict()}

        def fake_build_predictor(
            *,
            backend: str,
            identifier: str,
            dtype: str,
            max_new_tokens: int,
            runtime_contract: dict,
            execution_plan: ExecutionProfilePlan,
            decode_config: dict | None = None,
        ):
            _ = (identifier, dtype, max_new_tokens, runtime_contract, decode_config)
            return FakePredictor(backend, execution_plan)

        def fake_autotune(predictor: FakePredictor, prompts: list[str]) -> FakePredictor:
            _ = prompts
            selected_batch_size = 8 if predictor.backend == "vllm" else 4
            predictor.batch_size = selected_batch_size
            predictor.runtime_stats["autotune"] = {
                "status": "completed",
                "strategy": "warmup-batch-search",
                "selected_batch_size": selected_batch_size,
                "selected_samples_per_s": float(selected_batch_size),
                "selected_peak_vram_mb": 2048.0,
                "candidates": [
                    {
                        "batch_size": selected_batch_size,
                        "status": "ok",
                        "samples_per_s": float(selected_batch_size),
                        "peak_vram_mb": 2048.0,
                    }
                ],
            }
            return predictor

        with (
            patch("deeploop.runtime.stage_kernels._build_predictor", side_effect=fake_build_predictor),
            patch("deeploop.runtime.stage_kernels._maybe_autotune_batch_size", side_effect=fake_autotune),
            patch(
                "deeploop.runtime.stage_kernels._available_runtime_backends",
                return_value={
                    "local-transformers": {"available": True, "reason": "test"},
                    "vllm": {"available": True, "reason": "test"},
                    "mock-entailment": {"available": True, "reason": "test"},
                    "mock-contradiction": {"available": True, "reason": "test"},
                },
            ),
        ):
            plan, predictor = _autotune_execution_plan(
                "baseline-evaluation",
                execution_profile="qwen3_5-small-fp16",
                model_cfg={
                    "family": "qwen3.5",
                    "identifier": "Qwen3.5-2B-Base",
                    "backend": "",
                    "dtype": "float16",
                    "max_new_tokens": 512,
                },
                prompts=[" ".join(["alpha"] * 96)],
                runtime_contract={},
            )

        self.assertEqual(plan.resolved_backend, "vllm")
        self.assertEqual(plan.context_bucket, "short")
        self.assertEqual(plan.max_new_tokens, 256)
        self.assertEqual(predictor.runtime_stats["execution_search"]["selected_backend"], "vllm")
        self.assertEqual(predictor.runtime_stats["execution_search"]["status"], "completed")

    def test_execution_plan_autotuner_recovers_when_preferred_base_backend_is_unavailable(self) -> None:
        class FakePredictor:
            def __init__(self, backend: str, execution_plan: ExecutionProfilePlan) -> None:
                self.backend = backend
                self.batch_size = execution_plan.batch_probe_order[0] if execution_plan.batch_probe_order else 1
                self.batch_probe_order = list(execution_plan.batch_probe_order)
                self.max_new_tokens = execution_plan.max_new_tokens
                self.runtime_stats = {"execution_plan": execution_plan.to_dict()}

        def fake_build_predictor(
            *,
            backend: str,
            identifier: str,
            dtype: str,
            max_new_tokens: int,
            runtime_contract: dict,
            execution_plan: ExecutionProfilePlan,
            decode_config: dict | None = None,
        ):
            _ = (identifier, dtype, max_new_tokens, runtime_contract, decode_config)
            if backend == "vllm":
                raise RuntimeError("vllm backend requires torch and vllm to be installed.")
            return FakePredictor(backend, execution_plan)

        def fake_autotune(predictor: FakePredictor, prompts: list[str]) -> FakePredictor:
            _ = prompts
            predictor.runtime_stats["autotune"] = {
                "status": "completed",
                "strategy": "warmup-batch-search",
                "selected_batch_size": predictor.batch_size,
                "selected_samples_per_s": 4.0,
                "selected_peak_vram_mb": 1024.0,
                "candidates": [
                    {
                        "batch_size": predictor.batch_size,
                        "status": "ok",
                        "samples_per_s": 4.0,
                        "peak_vram_mb": 1024.0,
                    }
                ],
            }
            return predictor

        with (
            patch("deeploop.runtime.stage_kernels._build_predictor", side_effect=fake_build_predictor),
            patch("deeploop.runtime.stage_kernels._maybe_autotune_batch_size", side_effect=fake_autotune),
            patch(
                "deeploop.runtime.stage_kernels._available_runtime_backends",
                return_value={
                    "local-transformers": {"available": True, "reason": "test"},
                    "vllm": {"available": False, "reason": "missing"},
                    "mock-entailment": {"available": True, "reason": "test"},
                    "mock-contradiction": {"available": True, "reason": "test"},
                },
            ),
        ):
            plan, predictor = _autotune_execution_plan(
                "baseline-evaluation",
                execution_profile="qwen3_5-small-fp16",
                model_cfg={
                    "family": "qwen3.5",
                    "identifier": "Qwen3.5-2B-Base",
                    "backend": "vllm",
                    "dtype": "float16",
                    "max_new_tokens": 256,
                },
                prompts=["alpha beta gamma"],
                runtime_contract={},
            )

        self.assertEqual(plan.resolved_backend, "local-transformers")
        self.assertEqual(predictor.runtime_stats["execution_search"]["selected_backend"], "local-transformers")
        self.assertEqual(predictor.runtime_stats["execution_search"]["base_backend"], "vllm")
        self.assertEqual(predictor.runtime_stats["execution_search"]["status"], "completed")
        self.assertTrue(
            any(
                candidate["plan"]["resolved_backend"] == "vllm" and candidate["status"] == "failed"
                for candidate in predictor.runtime_stats["execution_search"]["candidates"]
            )
        )

    def test_kernels_execute_and_emit_manifests(self) -> None:
        baseline_config = self.fixture_root / "baseline.yaml"
        baseline_output_dir = self.run_root / "baseline"
        baseline_config.write_text(
            yaml.safe_dump(
                {
                    "mission_id": "demo-mission",
                    "mode": "human-directed",
                    "claim_state": "exploratory",
                    "resource_tier": "cpu-smoke",
                    "execution_profile": "qwen3_5-small-fp16",
                    "dataset": {
                        "promotion_manifest": str(self.promotion_manifest_path),
                        "selection": {
                            "tiers": ["C", "S"],
                            "split_kinds": ["dev"],
                            "split_families": ["iid", "length_ood"],
                            "lexicalizations": ["lex", "delex"],
                            "rule_families": ["symmetry_not_transitive", "transitivity_chain"],
                        },
                        "limit_examples": 3,
                    },
                    "model": {
                        "family": "qwen3.5",
                        "identifier": "Qwen3.5-2B-Base",
                        "backend": "mock-entailment",
                        "dtype": "float16",
                    },
                    "prompt": {"template_id": "demo_prompt_override_v2"},
                    "run": {
                        "loop_id": "demo-baseline",
                        "output_dir": str(baseline_output_dir),
                        "notes": ["baseline smoke"],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        baseline_result = run_stage_from_config(
            "baseline-evaluation",
            baseline_config,
            adapter=self.adapter,
        )
        self.assertEqual(self.adapter.configured_family, "qwen3.5")
        self.assertEqual(self.adapter.configured_prompt_template, "demo_prompt_override_v2")
        baseline_manifest = json.loads(baseline_result.manifest_path.read_text(encoding="utf-8"))
        baseline_runtime_report = json.loads(baseline_result.artifacts["runtime_report"].read_text(encoding="utf-8"))
        first_prediction = json.loads(
            baseline_result.artifacts["predictions"].read_text(encoding="utf-8").splitlines()[0]
        )
        self.assertEqual(baseline_manifest["stage"]["id"], "baseline-evaluation")
        self.assertEqual(baseline_manifest["prompt"]["template_id"], "demo_prompt_override_v2")
        self.assertEqual(baseline_manifest["code"]["repo"], str(REPO_ROOT))
        self.assertTrue(baseline_result.artifacts["predictions"].exists())
        self.assertEqual(first_prediction["prompt_template_id"], "demo_prompt_override_v2")
        self.assertEqual(baseline_manifest["stage_context"]["execution_contract"]["context_bucket"], "short")
        self.assertIn(str(baseline_result.artifacts["runtime_report"]), baseline_manifest["artifacts"]["report_paths"])
        self.assertEqual(baseline_runtime_report["telemetry"]["executed_examples"], 3)
        self.assertEqual(baseline_runtime_report["budget"]["batch_probe_order"][0], 32)
        self.assertIn("capabilities", baseline_runtime_report)
        self.assertEqual(
            baseline_runtime_report["capabilities"]["selected_backend"],
            baseline_runtime_report["model"]["resolved_backend"],
        )
        self.assertIn("autotune", baseline_runtime_report)
        self.assertEqual(baseline_runtime_report["autotune"]["status"], "skipped")
        self.assertEqual(baseline_runtime_report["execution_search"]["status"], "skipped")
        self.assertIn("oom_retries", baseline_manifest["metrics"])
        self.assertIn("capabilities", baseline_manifest["stage_context"])
        self.assertIn("runtime_autotune", baseline_manifest["stage_context"])

        mechanistic_config = self.fixture_root / "mechanistic.yaml"
        mechanistic_output_dir = self.run_root / "mechanistic"
        mechanistic_config.write_text(
            yaml.safe_dump(
                {
                    "project": "demo-substrate",
                    "phase": "mechanistic-localization",
                    "study_id": "demo-mechanistic",
                    "behavioral_source_manifest": str(baseline_result.manifest_path),
                    "model": {
                        "family": "qwen3.5",
                        "checkpoint": "Qwen3.5-2B-Base",
                        "layer_selection": "early mid late sweep",
                    },
                    "dataset": {
                        "tiers": ["C", "S"],
                        "split_families": ["iid", "length_ood"],
                        "lexicalizations": ["lex", "delex"],
                        "rule_families": ["symmetry_not_transitive", "transitivity_chain"],
                    },
                    "methods": {"probe": True, "activation_patching": True},
                    "reporting": {"notes": "mechanistic smoke"},
                    "run": {"output_dir": str(mechanistic_output_dir)},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        mechanistic_result = run_stage_from_config(
            "mechanistic-localization",
            mechanistic_config,
            adapter=self.adapter,
        )
        mechanistic_manifest = json.loads(mechanistic_result.manifest_path.read_text(encoding="utf-8"))
        candidates = json.loads(mechanistic_result.artifacts["candidates"].read_text(encoding="utf-8"))
        self.assertEqual(mechanistic_manifest["stage"]["id"], "mechanistic-localization")
        self.assertTrue(candidates["candidate_units"])

        intervention_config = self.fixture_root / "intervention.yaml"
        intervention_output_dir = self.run_root / "intervention"
        intervention_config.write_text(
            yaml.safe_dump(
                {
                    "project": "demo-substrate",
                    "phase": "causal-intervention",
                    "study_id": "demo-intervention",
                    "localization_source": str(mechanistic_result.manifest_path),
                    "model": {
                        "family": "qwen3.5",
                        "checkpoint": "Qwen3.5-2B-Base",
                        "target_layers": "late",
                    },
                    "intervention": {
                        "method": "activation_steering",
                        "strength": "small_to_medium_sweep",
                        "side_effect_response": "reduce steering strength on collateral-damage slices",
                    },
                    "evaluation": {"compare_against": str(baseline_result.manifest_path)},
                    "reporting": {"notes": "intervention smoke"},
                    "run": {"output_dir": str(intervention_output_dir)},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        intervention_result = run_stage_from_config(
            "causal-intervention",
            intervention_config,
            adapter=self.adapter,
        )
        intervention_manifest = json.loads(intervention_result.manifest_path.read_text(encoding="utf-8"))
        intervention_metrics = json.loads(intervention_result.artifacts["metrics"].read_text(encoding="utf-8"))
        self.assertEqual(intervention_manifest["stage"]["id"], "causal-intervention")
        self.assertEqual(intervention_result.status, "completed")
        self.assertIn("accuracy_delta", intervention_metrics)

    def test_stage_kernel_cli_can_emit_json(self) -> None:
        baseline_config = self.fixture_root / "baseline_cli.yaml"
        baseline_output_dir = self.run_root / "baseline-cli"
        baseline_config.write_text(
            yaml.safe_dump(
                {
                    "mission_id": "demo-mission",
                    "mode": "human-directed",
                    "claim_state": "exploratory",
                    "resource_tier": "cpu-smoke",
                    "execution_profile": "qwen3_5-small-fp16",
                    "dataset": {
                        "promotion_manifest": str(self.promotion_manifest_path),
                        "selection": {
                            "tiers": ["C"],
                            "split_kinds": ["dev"],
                            "split_families": ["iid"],
                            "lexicalizations": ["lex", "delex"],
                            "rule_families": ["symmetry_not_transitive", "transitivity_chain"],
                        },
                        "limit_examples": 2,
                    },
                    "model": {
                        "family": "qwen3.5",
                        "identifier": "Qwen3.5-2B-Base",
                        "backend": "mock-entailment",
                        "dtype": "float16",
                    },
                    "prompt": {"template_id": "demo_prompt_override_cli"},
                    "run": {
                        "loop_id": "demo-baseline-cli",
                        "output_dir": str(baseline_output_dir),
                        "notes": ["baseline cli smoke"],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/runtime/run_stage_kernel.py",
                "--stage",
                "baseline-evaluation",
                "--config",
                str(baseline_config),
                "--adapter",
                "test_stage_kernels:build_demo_adapter",
                "--pythonpath",
                str(REPO_ROOT / "tests"),
                "--json",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, DEMO_MANIFEST_ENV: str(self.promotion_manifest_path)},
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

        payload = json.loads(completed.stdout)
        first_prediction = json.loads((baseline_output_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(payload["stage_id"], "baseline-evaluation")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["manifest_path"], str(baseline_output_dir / "run_manifest.json"))
        self.assertEqual(payload["artifacts"]["predictions"], str(baseline_output_dir / "predictions.jsonl"))
        self.assertEqual(first_prediction["prompt_template_id"], "demo_prompt_override_cli")

    def test_prompt_decode_stage_kernel_cli_can_emit_json(self) -> None:
        prompt_dataset_path = self.fixture_root / "prompt_cli_records.jsonl"
        prompt_dataset_path.write_text(
            "".join(
                json.dumps(record) + "\n"
                for record in [
                    {
                        "premises": ["A implies B"],
                        "hypothesis": "B follows from A",
                        "tier": "C",
                        "lex": "lex",
                        "rule": "symmetry_not_transitive",
                        "chain_len": 1,
                        "label": "entailment",
                    },
                    {
                        "premises": ["C excludes D"],
                        "hypothesis": "D is supported",
                        "tier": "C",
                        "lex": "delex",
                        "rule": "transitivity_chain",
                        "chain_len": 3,
                        "label": "contradiction",
                    },
                ]
            ),
            encoding="utf-8",
        )
        prompt_manifest_path = self.fixture_root / "prompt_cli_manifest.json"
        prompt_manifest_path.write_text(
            json.dumps(
                {
                    "dataset_id": "prompt-cli-demo",
                    "files": [
                        {
                            "source": "prompt_cli_records.jsonl",
                            "local_path": str(prompt_dataset_path),
                            "tier": "primary-dev",
                            "split_kind": "primary-dev",
                            "split_family": "iid",
                        },
                        {
                            "source": "prompt_cli_records.jsonl",
                            "local_path": str(prompt_dataset_path),
                            "tier": "secondary-holdout",
                            "split_kind": "secondary-holdout",
                            "split_family": "iid",
                        },
                        {
                            "source": "prompt_cli_records.jsonl",
                            "local_path": str(prompt_dataset_path),
                            "tier": "final-test",
                            "split_kind": "final-test",
                            "split_family": "iid",
                        },
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        prompt_runtime_root = self.run_root / "prompt-cli-runtime"
        prompt_output_dir = prompt_runtime_root / "runs" / "prompt-iid"
        prompt_config = self.fixture_root / "prompt_cli.yaml"
        prompt_config.write_text(
            yaml.safe_dump(
                {
                    "mission_id": "demo-mission",
                    "loop_action_id": "demo-prompt-cli-loop",
                    "mode": "human-directed",
                    "claim_state": "exploratory",
                    "resource_tier": "cpu-smoke",
                    "execution_profile": "qwen3_5-small-fp16",
                    "runtime_root": str(prompt_runtime_root),
                    "selected_direction": "iid",
                    "selected_starter": {
                        "run_id": "baseline-demo",
                        "starter_alias": "demo-starter",
                        "resolved_model_id": "mock://entailment",
                        "baseline_sacrebleu": 0.0,
                    },
                    "runtime_lock": {
                        "resolved_model_id": "mock://entailment",
                        "backend": "mock-entailment",
                        "dtype": "float16",
                        "context_bucket": "short",
                        "max_new_tokens": 64,
                    },
                    "dataset_materialization": {
                        "promotion_manifest_path": str(prompt_manifest_path),
                        "primary_dev_selection": {"split_kinds": ["primary-dev"], "split_families": ["iid"]},
                        "secondary_holdout_selection": {
                            "split_kinds": ["secondary-holdout"],
                            "split_families": ["iid"],
                        },
                        "final_test_selection": {"split_kinds": ["final-test"], "split_families": ["iid"]},
                    },
                    "metric_path": ["accuracy"],
                    "diagnostic_metric_path": ["accuracy"],
                    "promotion_rules": {
                        "full_set_gain_threshold": 0.05,
                        "slice_signal_override": {
                            "required_slice_gain": 0.0,
                            "required_slice_count": 0,
                            "max_full_set_regression": -1.0,
                            "eligible_slice_ids": [],
                        },
                    },
                    "baseline_anchor_replay": {"template_id": "demo_baseline_prompt"},
                    "variant_matrix": [
                        {
                            "variant_id": "v1-demo-greedy",
                            "template_id": "demo_prompt_variant_a",
                            "prompt_family": "demo-a",
                            "context_bucket": "short",
                            "decode_policy": "greedy",
                        }
                    ],
                    "run": {"loop_id": "demo-prompt-cli", "output_dir": str(prompt_output_dir)},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/runtime/run_stage_kernel.py",
                "--stage",
                "prompt-decode-sweep",
                "--config",
                str(prompt_config),
                "--adapter",
                "test_stage_kernels:build_demo_adapter",
                "--pythonpath",
                str(REPO_ROOT / "tests"),
                "--json",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, DEMO_MANIFEST_ENV: str(prompt_manifest_path)},
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

        payload = json.loads(completed.stdout)
        summary = json.loads((prompt_output_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["stage_id"], "prompt-decode-sweep")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["manifest_path"], str(prompt_output_dir / "run_manifest.json"))
        self.assertEqual(summary["executed_variant_ids"], ["v1-demo-greedy"])


if __name__ == "__main__":
    unittest.main()
