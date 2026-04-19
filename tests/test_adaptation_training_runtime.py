from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from deeploop.runtime.adaptation_training_runtime import run_adaptation_training
from runtime_artifact_helpers import fresh_test_root, write_json, write_yaml

TEST_WORK_ROOT = REPO_ROOT / "tests" / "_runtime_artifacts" / "adaptation_training_runtime"


def _fresh_test_root(name: str) -> Path:
    return fresh_test_root(TEST_WORK_ROOT, name)


def _write_json(path: Path, payload: dict) -> None:
    write_json(path, payload)


def _write_yaml(path: Path, payload: dict) -> None:
    write_yaml(path, payload)


class AdaptationTrainingRuntimeTests(unittest.TestCase):
    def test_runtime_materializes_jobs_and_compares_against_best_prior_anchor(self) -> None:
        test_root = _fresh_test_root("success")
        baseline_metrics_path = test_root / "baseline_metrics.json"
        intervention_metrics_path = test_root / "intervention_metrics.json"
        _write_json(baseline_metrics_path, {"accuracy": 0.61, "loss": 0.42})
        _write_json(intervention_metrics_path, {"accuracy": 0.66, "loss": 0.37})

        config_path = test_root / "adaptation.yaml"
        _write_yaml(
            config_path,
            {
                "branch_id": "adapt-branch",
                "objective": "Improve the bounded adaptation branch.",
                "training_kind": "lora",
                "runtime": {
                    "repo_root": str(REPO_ROOT),
                    "output_root": str(test_root / "runtime"),
                    "max_runtime_hours": 0.05,
                    "gpu_count": 1,
                },
                "artifacts": {
                    "baseline_metrics_path": str(baseline_metrics_path),
                    "intervention_metrics_path": str(intervention_metrics_path),
                    "adapter_artifact_path": "outputs/adapter.bin",
                    "evaluation_metrics_path": "outputs/eval_metrics.json",
                },
                "train": {
                    "command": [
                        sys.executable,
                        "-c",
                        (
                            "from pathlib import Path; import os; "
                            "path = Path(os.environ['DEEPLOOP_ADAPTATION_ADAPTER_PATH']); "
                            "path.parent.mkdir(parents=True, exist_ok=True); "
                            "path.write_text('adapter', encoding='utf-8')"
                        ),
                    ]
                },
                "evaluate": {
                    "command": [
                        sys.executable,
                        "-c",
                        (
                            "import json, os; from pathlib import Path; "
                            "path = Path(os.environ['DEEPLOOP_ADAPTATION_EVAL_METRICS_PATH']); "
                            "path.parent.mkdir(parents=True, exist_ok=True); "
                            "path.write_text(json.dumps({'accuracy': 0.72, 'loss': 0.31}), encoding='utf-8')"
                        ),
                    ]
                },
                "comparison": {
                    "primary_metric": "accuracy",
                    "higher_is_better": True,
                    "min_improvement": 0.02,
                    "max_allowed_regression": 0.02,
                    "guardrail_metrics": ["loss"],
                    "route_on_keep": "replication",
                    "route_on_discard": "experiment-design",
                },
            },
        )

        result = run_adaptation_training(config_path)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["comparison"]["decision"], "keep")
        self.assertEqual(result["comparison"]["anchor_label"], "intervention")
        self.assertEqual(result["comparison"]["route_to"], "replication")
        self.assertTrue(Path(result["train_job_path"]).exists())
        self.assertTrue(Path(result["eval_job_path"]).exists())
        self.assertTrue(Path(result["adapter_artifact_path"]).exists())
        self.assertTrue(Path(result["evaluation_metrics_path"]).exists())
        report = json.loads(Path(result["report_json_path"]).read_text(encoding="utf-8"))
        self.assertEqual(report["comparison"]["decision"], "keep")
        self.assertIn("keep/discard adaptation comparison", result["produced_outputs"])

    def test_runtime_blocks_out_of_scope_training_surface(self) -> None:
        test_root = _fresh_test_root("blocked")
        baseline_metrics_path = test_root / "baseline_metrics.json"
        _write_json(baseline_metrics_path, {"accuracy": 0.61})
        config_path = test_root / "adaptation.yaml"
        _write_yaml(
            config_path,
            {
                "training_kind": "dpo",
                "runtime": {
                    "repo_root": str(REPO_ROOT),
                    "output_root": str(test_root / "runtime"),
                    "max_runtime_hours": 0.05,
                    "gpu_count": 1,
                },
                "artifacts": {
                    "baseline_metrics_path": str(baseline_metrics_path),
                    "adapter_artifact_path": "outputs/adapter.bin",
                    "evaluation_metrics_path": "outputs/eval_metrics.json",
                },
                "train": {"command": [sys.executable, "-c", "raise SystemExit(0)"]},
                "evaluate": {"command": [sys.executable, "-c", "raise SystemExit(0)"]},
                "comparison": {"primary_metric": "accuracy"},
            },
        )

        result = run_adaptation_training(config_path)

        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["gate_event"]["gate"], "soft")
        self.assertEqual(result["gate_event"]["risk_class"], "executor-mismatch")
        self.assertIn("soft-gated", Path(result["report_json_path"]).read_text(encoding="utf-8"))
        self.assertFalse(Path(result["training_log_path"]).exists())

    def test_runtime_fails_when_re_evaluation_artifact_is_missing(self) -> None:
        test_root = _fresh_test_root("failed")
        baseline_metrics_path = test_root / "baseline_metrics.json"
        _write_json(baseline_metrics_path, {"accuracy": 0.61})
        config_path = test_root / "adaptation.yaml"
        _write_yaml(
            config_path,
            {
                "training_kind": "lora",
                "runtime": {
                    "repo_root": str(REPO_ROOT),
                    "output_root": str(test_root / "runtime"),
                    "max_runtime_hours": 0.05,
                    "gpu_count": 1,
                },
                "artifacts": {
                    "baseline_metrics_path": str(baseline_metrics_path),
                    "adapter_artifact_path": "outputs/adapter.bin",
                    "evaluation_metrics_path": "outputs/eval_metrics.json",
                },
                "train": {
                    "command": [
                        sys.executable,
                        "-c",
                        (
                            "from pathlib import Path; import os; "
                            "path = Path(os.environ['DEEPLOOP_ADAPTATION_ADAPTER_PATH']); "
                            "path.parent.mkdir(parents=True, exist_ok=True); "
                            "path.write_text('adapter', encoding='utf-8')"
                        ),
                    ]
                },
                "evaluate": {"command": [sys.executable, "-c", "raise SystemExit(0)"]},
                "comparison": {"primary_metric": "accuracy"},
            },
        )

        result = run_adaptation_training(config_path)

        self.assertEqual(result["status"], "failed")
        self.assertIn("without producing metrics", Path(result["report_json_path"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
