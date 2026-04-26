from __future__ import annotations

import json
import shutil
import subprocess
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

from deeploop.core.paths import RUNS_DIR, SCRATCH_DIR
from deeploop.runtime.self_healing_runtime import run_self_healing_queue


class SelfHealingRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_root = SCRATCH_DIR / "self-healing-runtime-tests"
        self.run_root = RUNS_DIR / "self-healing-runtime-tests"
        shutil.rmtree(self.fixture_root, ignore_errors=True)
        shutil.rmtree(self.run_root, ignore_errors=True)
        self.fixture_root.mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.dataset_manifest_path = self._write_dataset_bundle()
        self._write_behavioral_matrix_contract()
        self.mission_state_path = self._write_mission_state()

    def tearDown(self) -> None:
        shutil.rmtree(self.fixture_root, ignore_errors=True)
        shutil.rmtree(self.run_root, ignore_errors=True)

    def _write_dataset_bundle(self) -> Path:
        dataset_path = self.fixture_root / "demo_records.jsonl"
        records = []
        for index in range(8):
            records.append(
                {
                    "premises": [f"P{index} implies Q{index}"],
                    "hypothesis": f"Q{index} follows from P{index}",
                    "tier": "C",
                    "lex": "lex" if index % 2 == 0 else "delex",
                    "rule": "symmetry_not_transitive" if index < 4 else "transitivity_chain",
                    "chain_len": 1 + (index % 3),
                    "label": "entailment",
                }
            )
        dataset_path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        manifest_path = self.fixture_root / "promotion_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "dataset_id": "demo-runtime-dataset",
                    "files": [
                        {
                            "source": "demo_records.jsonl",
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
        return manifest_path

    def _write_mission_state(self) -> Path:
        mission_root = self.run_root / "mission"
        mission_root.mkdir(parents=True, exist_ok=True)
        state_path = mission_root / "mission_state.json"
        state_path.write_text(
            json.dumps(
                {
                    "mission_id": "runtime-test-mission",
                    "mode": "sandboxed-yolo",
                    "title": "Runtime test mission",
                    "summary": "Exercise DeepLoop self-healing runtime.",
                    "current_phase": "execution",
                    "status": "running",
                    "roles": ["execution-operator"],
                    "autonomy_status": {"state": "initialized", "reason": "unit test"},
                    "next_actions": {},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return state_path

    def _write_behavioral_matrix_contract(self) -> Path:
        contract_path = self.fixture_root / "configs" / "eval" / "behavioral-matrix.yaml"
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_text(
            yaml.safe_dump(
                {
                    "metrics": [
                        {
                            "id": "accuracy",
                            "summary": "Track baseline accuracy for runtime smoke coverage.",
                        }
                    ],
                    "reporting": {
                        "primary_metric": "accuracy",
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return contract_path

    def _write_baseline_config(self, *, name: str, output_dir: Path, backend: str) -> Path:
        config_path = self.fixture_root / f"{name}.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "mission_id": "runtime-test-mission",
                    "mode": "sandboxed-yolo",
                    "claim_state": "exploratory",
                    "resource_tier": "cpu-smoke",
                    "execution_profile": "cpu-smoke-mock",
                    "dataset": {
                        "promotion_manifest": str(self.dataset_manifest_path),
                        "selection": {
                            "tiers": ["C"],
                            "split_kinds": ["dev"],
                            "split_families": ["iid"],
                            "lexicalizations": ["lex", "delex"],
                            "rule_families": ["symmetry_not_transitive", "transitivity_chain"],
                        },
                        "limit_examples": 8,
                    },
                    "model": {
                        "family": "mock",
                        "identifier": f"mock://{backend.replace('mock-', '')}",
                        "backend": backend,
                        "dtype": "none",
                    },
                    "prompt": {"template_id": "demo_prompt_v1"},
                    "run": {"loop_id": name, "output_dir": str(output_dir), "notes": [f"{name} runtime test"]},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return config_path

    def _write_queue_config(self, *, name: str, entry: dict) -> Path:
        config_path = self.fixture_root / f"{name}.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "queue_name": name,
                    "mission_state": str(self.mission_state_path),
                    "runtime_policy": str(REPO_ROOT / "configs" / "runtime" / "self-healing-runtime.yaml"),
                    "rerun_existing": True,
                    "max_jobs": 1,
                    "entries": [entry],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return config_path

    def _write_queue_config_with_max_jobs(self, *, name: str, entries: list, max_jobs: int) -> Path:
        config_path = self.fixture_root / f"{name}.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "queue_name": name,
                    "mission_state": str(self.mission_state_path),
                    "runtime_policy": str(REPO_ROOT / "configs" / "runtime" / "self-healing-runtime.yaml"),
                    "rerun_existing": True,
                    "max_jobs": max_jobs,
                    "entries": entries,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return config_path

    def test_cli_smoke_reroutes_import_failure_into_stage_kernel(self) -> None:
        output_dir = self.run_root / "import-reroute"
        baseline_config = self._write_baseline_config(
            name="import-reroute-baseline",
            output_dir=output_dir,
            backend="mock-entailment",
        )
        queue_config = self._write_queue_config(
            name="import-reroute-queue",
            entry={
                "id": "import-reroute-job",
                "repo": str(self.fixture_root),
                "stage_id": "baseline-evaluation",
                "adapter": "runtime_fixtures:build_demo_adapter",
                "pythonpath": [str(TESTS_ROOT)],
                "command": [
                    sys.executable,
                    str(TESTS_ROOT / "runtime_import_failure.py"),
                    "--config",
                    str(baseline_config),
                ],
                "expected_manifest": str(output_dir / "run_manifest.json"),
            },
        )

        completed = subprocess.run(
            [sys.executable, "scripts/runtime/run_queue.py", "--config", str(queue_config)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("queue-runtime: recovered 1 job(s)", completed.stdout)

        report = json.loads(
            (self.mission_state_path.parent / "runtime" / "self_healing_runtime" / "import-reroute-queue" / "queue_summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["counts"]["completed_jobs"], 1)
        self.assertEqual(report["counts"]["recovered_jobs"], 1)
        self.assertEqual(report["counts"]["rerouted_jobs"], 1)

        entry_summary = json.loads(
            (
                self.mission_state_path.parent
                / "runtime"
                / "self_healing_runtime"
                / "import-reroute-queue"
                / "import-reroute-job"
                / "summary.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(entry_summary["final_status"], "completed")
        self.assertEqual([attempt["mode"] for attempt in entry_summary["attempts"]], ["primary", "reroute"])
        self.assertEqual(entry_summary["attempts"][0]["failure"]["kind"], "import-env-failure")
        manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["runtime"]["entry_id"], "import-reroute-job")
        self.assertEqual(manifest["runtime"]["attempt"], 2)
        self.assertEqual(manifest["runtime"]["recovery_mode"], "reroute")

    def test_runtime_resumes_missing_artifact_and_records_history(self) -> None:
        output_dir = self.run_root / "resume-job"
        baseline_config = self._write_baseline_config(
            name="resume-baseline",
            output_dir=output_dir,
            backend="mock-entailment",
        )
        queue_config = self._write_queue_config(
            name="resume-queue",
            entry={
                "id": "resume-job",
                "repo": str(self.fixture_root),
                "command": [
                    sys.executable,
                    str(TESTS_ROOT / "runtime_resume_helper.py"),
                    "--config",
                    str(baseline_config),
                    "--manifest",
                    str(output_dir / "run_manifest.json"),
                    "--output-dir",
                    str(output_dir),
                ],
                "repair": {"max_resumes": 1},
                "expected_manifest": str(output_dir / "run_manifest.json"),
            },
        )

        result = run_self_healing_queue(queue_config)
        self.assertEqual(result["completed_jobs"], 1)
        self.assertEqual(result["recovered_jobs"], 1)
        self.assertEqual(result["resumed_jobs"], 1)

        entry_summary = json.loads(
            (
                self.mission_state_path.parent
                / "runtime"
                / "self_healing_runtime"
                / "resume-queue"
                / "resume-job"
                / "summary.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(entry_summary["final_status"], "completed")
        self.assertEqual([attempt["mode"] for attempt in entry_summary["attempts"]], ["primary", "resume"])

    def test_runtime_recreates_entry_root_before_writing_attempt_log(self) -> None:
        output_dir = self.run_root / "delete-entry-root"
        baseline_config = self._write_baseline_config(
            name="delete-entry-root-baseline",
            output_dir=output_dir,
            backend="mock-entailment",
        )
        queue_config = self._write_queue_config(
            name="delete-entry-root-queue",
            entry={
                "id": "delete-entry-root-job",
                "repo": str(self.fixture_root),
                "command": [
                    sys.executable,
                    str(TESTS_ROOT / "runtime_delete_entry_root.py"),
                    "--config",
                    str(baseline_config),
                ],
                "repair": {"max_retries": 0},
                "expected_manifest": str(output_dir / "run_manifest.json"),
            },
        )

        result = run_self_healing_queue(queue_config)
        self.assertEqual(result["failed_jobs"], 1)

        entry_root = (
            self.mission_state_path.parent
            / "runtime"
            / "self_healing_runtime"
            / "delete-entry-root-queue"
            / "delete-entry-root-job"
        )
        self.assertTrue((entry_root / "attempt-01-primary.log").exists())
        entry_summary = json.loads((entry_root / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(entry_summary["final_status"], "failed")
        self.assertEqual(entry_summary["attempts"][0]["returncode"], 1)
        self.assertEqual(entry_summary["attempts"][0]["failure"]["kind"], "command-failure")
        history_lines = (entry_root / "history.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertTrue(history_lines)

    def test_runtime_captures_scientific_failure_structurally(self) -> None:
        output_dir = self.run_root / "scientific-failure"
        baseline_config = self._write_baseline_config(
            name="scientific-failure-baseline",
            output_dir=output_dir,
            backend="mock-contradiction",
        )
        queue_config = self._write_queue_config(
            name="scientific-failure-queue",
            entry={
                "id": "scientific-failure-job",
                "repo": str(self.fixture_root),
                "command": [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "runtime" / "run_stage_kernel.py"),
                    "--stage",
                    "baseline-evaluation",
                    "--config",
                    str(baseline_config),
                    "--adapter",
                    "runtime_fixtures:build_demo_adapter",
                    "--pythonpath",
                    str(TESTS_ROOT),
                ],
                "expected_manifest": str(output_dir / "run_manifest.json"),
            },
        )

        result = run_self_healing_queue(queue_config)
        self.assertEqual(result["failed_jobs"], 1)
        self.assertEqual(result["completed_jobs"], 0)

        entry_summary = json.loads(
            (
                self.mission_state_path.parent
                / "runtime"
                / "self_healing_runtime"
                / "scientific-failure-queue"
                / "scientific-failure-job"
                / "summary.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(entry_summary["final_status"], "failed")
        self.assertEqual(entry_summary["attempts"][0]["failure"]["kind"], "scientific-failure")
        self.assertEqual(entry_summary["final_decision"]["action"], "stop")
        mission_state = json.loads(self.mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["autonomy_status"]["state"], "runtime-failed")

    def test_truncation_warning_emitted_when_max_jobs_caps_queue(self) -> None:
        output_dir_a = self.run_root / "trunc-job-a"
        output_dir_b = self.run_root / "trunc-job-b"
        baseline_config_a = self._write_baseline_config(
            name="trunc-baseline-a", output_dir=output_dir_a, backend="mock-entailment"
        )
        baseline_config_b = self._write_baseline_config(
            name="trunc-baseline-b", output_dir=output_dir_b, backend="mock-entailment"
        )
        entries = [
            {
                "id": "trunc-job-a",
                "repo": str(self.fixture_root),
                "command": [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "runtime" / "run_stage_kernel.py"),
                    "--stage",
                    "baseline-evaluation",
                    "--config",
                    str(baseline_config_a),
                    "--adapter",
                    "runtime_fixtures:build_demo_adapter",
                    "--pythonpath",
                    str(TESTS_ROOT),
                ],
                "expected_manifest": str(output_dir_a / "run_manifest.json"),
            },
            {
                "id": "trunc-job-b",
                "repo": str(self.fixture_root),
                "command": [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "runtime" / "run_stage_kernel.py"),
                    "--stage",
                    "baseline-evaluation",
                    "--config",
                    str(baseline_config_b),
                    "--adapter",
                    "runtime_fixtures:build_demo_adapter",
                    "--pythonpath",
                    str(TESTS_ROOT),
                ],
                "expected_manifest": str(output_dir_b / "run_manifest.json"),
            },
        ]
        queue_config = self._write_queue_config_with_max_jobs(
            name="trunc-queue",
            entries=entries,
            max_jobs=1,
        )

        result = run_self_healing_queue(queue_config)

        # Only 1 job should have been executed and 1 truncated
        self.assertEqual(result["completed_jobs"], 1)
        self.assertEqual(result["truncated_jobs"], 1)
        self.assertIsNotNone(result["truncation_warning"])
        self.assertIn("max_jobs=1", result["truncation_warning"])
        self.assertIn("1 job(s)", result["truncation_warning"])

        # Queue report JSON must record truncation
        report = json.loads(
            (
                self.mission_state_path.parent
                / "runtime"
                / "self_healing_runtime"
                / "trunc-queue"
                / "queue_summary.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(report["counts"]["truncated_jobs"], 1)
        self.assertIsNotNone(report["truncation_warning"])

        # Mission state autonomy_status must reflect completed-truncated
        mission_state = json.loads(self.mission_state_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["autonomy_status"]["state"], "completed-truncated")

        # Ledger must contain an autonomy-gate-warning entry
        ledger_path = self.mission_state_path.parent / "ledger.jsonl"
        ledger_entries = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
        gate_warnings = [e for e in ledger_entries if e.get("kind") == "autonomy-gate-warning"]
        self.assertTrue(gate_warnings, "Expected at least one autonomy-gate-warning ledger entry")
        self.assertEqual(gate_warnings[0]["metadata"]["truncated_jobs"], 1)
        self.assertEqual(gate_warnings[0]["status"], "truncated")


if __name__ == "__main__":
    unittest.main()
