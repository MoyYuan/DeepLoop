from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import RUNS_DIR, SCRATCH_DIR
from deeploop.runtime.runtime_recovery import run_stage_with_recovery
from deeploop.runtime.stage_kernels import run_stage_from_config
from tests.test_stage_kernels import DemoAdapter


class RuntimeRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_root = SCRATCH_DIR / "runtime-recovery-tests"
        self.run_root = RUNS_DIR / "runtime-recovery-tests"
        shutil.rmtree(self.fixture_root, ignore_errors=True)
        shutil.rmtree(self.run_root, ignore_errors=True)
        self.fixture_root.mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)

        dataset_path = self.fixture_root / "records.jsonl"
        dataset_path.write_text(
            json.dumps(
                {
                    "premises": ["A implies B"],
                    "hypothesis": "B follows from A",
                    "tier": "C",
                    "lex": "lex",
                    "rule": "symmetry_not_transitive",
                    "chain_len": 1,
                    "label": "entailment",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.promotion_manifest_path = self.fixture_root / "promotion_manifest.json"
        self.promotion_manifest_path.write_text(
            json.dumps(
                {
                    "dataset_id": "recovery-demo",
                    "files": [
                        {
                            "source": "records.jsonl",
                            "local_path": str(dataset_path),
                            "tier": "C",
                            "split_kind": "dev",
                            "split_family": "iid",
                        }
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

    def test_backend_fallback_recovers_stage(self) -> None:
        config_path = self.fixture_root / "baseline.yaml"
        output_dir = self.run_root / "baseline"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "mission_id": "recovery-mission",
                    "mode": "sandboxed-yolo",
                    "claim_state": "exploratory",
                    "resource_tier": "cpu-smoke",
                    "execution_profile": "cpu-smoke",
                    "dataset": {
                        "promotion_manifest": str(self.promotion_manifest_path),
                        "selection": {
                            "tiers": ["C"],
                            "split_kinds": ["dev"],
                            "split_families": ["iid"],
                            "lexicalizations": ["lex"],
                            "rule_families": ["symmetry_not_transitive"],
                        },
                        "limit_examples": 1,
                    },
                    "model": {
                        "family": "demo",
                        "identifier": "broken://backend",
                        "backend": "unsupported-backend",
                        "dtype": "none",
                    },
                    "run": {"loop_id": "recovery-baseline", "output_dir": str(output_dir)},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        result = run_stage_with_recovery("baseline-evaluation", config_path, adapter=self.adapter)
        report = json.loads(result.recovery_report_path.read_text(encoding="utf-8"))
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(report["attempt_count"], 2)
        self.assertEqual(manifest["model"]["backend"], "mock-entailment")

    def test_blocked_stage_is_recorded(self) -> None:
        baseline_config = self.fixture_root / "baseline-ok.yaml"
        baseline_output = self.run_root / "baseline-ok"
        baseline_config.write_text(
            yaml.safe_dump(
                {
                    "mission_id": "recovery-mission",
                    "mode": "sandboxed-yolo",
                    "claim_state": "exploratory",
                    "resource_tier": "cpu-smoke",
                    "execution_profile": "cpu-smoke",
                    "dataset": {
                        "promotion_manifest": str(self.promotion_manifest_path),
                        "selection": {
                            "tiers": ["C"],
                            "split_kinds": ["dev"],
                            "split_families": ["iid"],
                            "lexicalizations": ["lex"],
                            "rule_families": ["symmetry_not_transitive"],
                        },
                        "limit_examples": 1,
                    },
                    "model": {
                        "family": "demo",
                        "identifier": "mock://entailment",
                        "backend": "mock-entailment",
                        "dtype": "none",
                    },
                    "run": {"loop_id": "baseline-ok", "output_dir": str(baseline_output)},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        baseline_result = run_stage_from_config("baseline-evaluation", baseline_config, adapter=self.adapter)
        intervention_config = self.fixture_root / "intervention.yaml"
        intervention_output = self.run_root / "intervention"
        intervention_config.write_text(
            yaml.safe_dump(
                {
                    "project": "demo",
                    "phase": "causal-intervention",
                    "study_id": "blocked-intervention",
                    "localization_source": str(self.fixture_root / "missing-study-manifest.json"),
                    "model": {"family": "demo", "checkpoint": "mock://entailment", "target_layers": "late"},
                    "intervention": {
                        "method": "activation_steering",
                        "strength": "small",
                        "side_effect_response": "preserve",
                    },
                    "evaluation": {"compare_against": str(baseline_result.manifest_path)},
                    "run": {"output_dir": str(intervention_output)},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        result = run_stage_with_recovery("causal-intervention", intervention_config, adapter=self.adapter)
        report = json.loads(result.recovery_report_path.read_text(encoding="utf-8"))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(report["attempts"][0]["classification"], "missing-artifact")

    def test_resume_existing_manifest(self) -> None:
        config_path = self.fixture_root / "resume.yaml"
        output_dir = self.run_root / "resume"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "mission_id": "resume-mission",
                    "mode": "sandboxed-yolo",
                    "claim_state": "exploratory",
                    "resource_tier": "cpu-smoke",
                    "execution_profile": "cpu-smoke",
                    "dataset": {
                        "promotion_manifest": str(self.promotion_manifest_path),
                        "selection": {
                            "tiers": ["C"],
                            "split_kinds": ["dev"],
                            "split_families": ["iid"],
                            "lexicalizations": ["lex"],
                            "rule_families": ["symmetry_not_transitive"],
                        },
                        "limit_examples": 1,
                    },
                    "model": {
                        "family": "demo",
                        "identifier": "mock://entailment",
                        "backend": "mock-entailment",
                        "dtype": "none",
                    },
                    "run": {"loop_id": "resume-baseline", "output_dir": str(output_dir)},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        run_stage_from_config("baseline-evaluation", config_path, adapter=self.adapter)
        result = run_stage_with_recovery("baseline-evaluation", config_path, adapter=self.adapter)
        self.assertEqual(result.status, "resumed")
        self.assertTrue(result.resumed)


if __name__ == "__main__":
    unittest.main()
