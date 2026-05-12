from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from deeploop.artifacts.real_runtime_validation import (
    load_gate_2_real_runtime_validation_contract,
    validate_real_runtime,
)
from runtime_artifact_helpers import fresh_test_root, write_json

TEST_ROOT = REPO_ROOT / "tests" / "_runtime_artifacts" / "real_runtime_validation"


def _fresh_test_root(name: str) -> Path:
    return fresh_test_root(TEST_ROOT, name)


def _write_bootstrapped_mission(config_path: Path, root: Path) -> dict[str, str]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    mission_cfg = config.get("mission") if isinstance(config.get("mission"), dict) else {}
    mission_id = str(mission_cfg.get("id") or "gate-2-runtime-test")
    target_repo = Path(str(mission_cfg.get("target_repo") or root / "project")).expanduser().resolve()
    mission_root = root / "missions" / mission_id
    mission_root.mkdir(parents=True, exist_ok=True)
    mission_state_path = mission_root / "mission_state.json"
    mission_summary_path = mission_root / "mission_summary.md"
    ledger_path = mission_root / "ledger.jsonl"
    write_json(
        mission_state_path,
        {
            "mission_id": mission_id,
            "mode": "sandboxed-yolo",
            "title": "Gate 2 runtime validation mission",
            "summary": "Validate one real provider-backed runtime path.",
            "objective": "Exercise the release runtime lane honestly.",
            "current_phase": "idea-intake",
            "next_phase": "literature-review",
            "status": "initialized",
            "target_repo": str(target_repo),
            "roles": ["planner"],
            "autonomy_status": {"state": "initialized", "reason": "test"},
        },
    )
    mission_summary_path.write_text("# Mission summary\n", encoding="utf-8")
    ledger_path.write_text("", encoding="utf-8")
    return {
        "mission_root": str(mission_root),
        "state_path": str(mission_state_path),
        "summary_path": str(mission_summary_path),
        "ledger_path": str(ledger_path),
    }


class RealRuntimeValidationTests(unittest.TestCase):
    def tearDown(self) -> None:
        shutil.rmtree(TEST_ROOT, ignore_errors=True)

    def test_contract_wires_only_the_two_approved_gate_2_lanes(self) -> None:
        contract = load_gate_2_real_runtime_validation_contract()

        self.assertEqual(contract["contract_id"], "gate-2-real-runtime-validation")
        self.assertEqual(contract["source_lane_contract"], "configs/runtime/gate-2-runtime-lanes.yaml")
        self.assertTrue(contract["proof_boundary"]["manual_notes_required"])
        self.assertEqual(
            set(contract["lanes"]),
            {
                "local-qwen-openai-compatible",
                "copilot-cli-gpt-5-mini-coding-agent",
            },
        )
        self.assertEqual(contract["lanes"]["local-qwen-openai-compatible"]["validation_surface"], "deeploop-analyze")
        self.assertEqual(
            contract["lanes"]["copilot-cli-gpt-5-mini-coding-agent"]["validation_surface"],
            "recursive-agent-runtime",
        )

    @patch("deeploop.artifacts.real_runtime_validation.run_provider_prompt")
    @patch("deeploop.artifacts.real_runtime_validation.check_provider_readiness")
    @patch("deeploop.artifacts.real_runtime_validation.initialize_mission")
    def test_local_qwen_lane_records_durable_runtime_evidence(
        self,
        mock_initialize_mission,
        mock_check_provider_readiness,
        mock_run_provider_prompt,
    ) -> None:
        test_root = _fresh_test_root("local-qwen-lane")
        evidence_root = test_root / "evidence"

        def _fake_initialize(config_path: Path, force: bool = False) -> dict[str, str]:
            self.assertTrue(force)
            return _write_bootstrapped_mission(Path(config_path), test_root)

        def _fake_prompt(
            prompt_path: Path,
            *,
            result_json_path: Path | None = None,
            **_: object,
        ):
            assert result_json_path is not None
            write_json(
                result_json_path,
                {
                    "status": "completed",
                    "summary": "Mission state analyzed against the local Qwen lane.",
                    "recommended_next_step": "Run the next bounded experiment.",
                    "findings": ["Lane returned structured JSON."],
                    "notes": ["Local server stayed external to DeepLoop."],
                },
            )
            return __import__("subprocess").CompletedProcess(
                args=[str(prompt_path)],
                returncode=0,
                stdout='{"status":"completed"}\n',
                stderr="",
            )

        mock_initialize_mission.side_effect = _fake_initialize
        mock_check_provider_readiness.return_value = {
            "status": "ready",
            "summary": "ready",
            "provider_family": "openai-compatible-api",
            "selection_profile": "gate2-local-qwen3_5-9b-openai",
        }
        mock_run_provider_prompt.side_effect = _fake_prompt

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "placeholder-token", "OPENAI_BASE_URL": "http://127.0.0.1:8000/v1"},
            clear=False,
        ):
            result = validate_real_runtime(
                lane_ids=["local-qwen-openai-compatible"],
                output_root=evidence_root,
                validation_id="demo-qwen-run",
                operator="tester",
                machine_label="ci-host",
                general_notes=["Local Qwen server was started manually before the harness ran."],
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["lane_results"][0]["status"], "passed")
        record = json.loads(Path(result["lane_results"][0]["record_json_path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["provider_readiness"]["status"], "ready")
        self.assertTrue(record["project_boundary"]["unchanged"])
        env_checks = {item["name"]: item for item in record["manual_boundary_checks"] if item["kind"] == "env"}
        self.assertTrue(env_checks["OPENAI_API_KEY"]["passed"])
        self.assertTrue(env_checks["OPENAI_BASE_URL"]["passed"])
        self.assertEqual(record["runtime_execution"]["result"]["status"], "completed")
        self.assertTrue(Path(record["runtime_execution"]["result_json_path"]).exists())

    @patch("deeploop.artifacts.real_runtime_validation.run_recursive_agent_loop")
    @patch("deeploop.artifacts.real_runtime_validation.check_provider_readiness")
    @patch("deeploop.artifacts.real_runtime_validation.initialize_mission")
    def test_copilot_lane_records_recursive_runtime_artifacts(
        self,
        mock_initialize_mission,
        mock_check_provider_readiness,
        mock_run_recursive_agent_loop,
    ) -> None:
        test_root = _fresh_test_root("copilot-lane")
        evidence_root = test_root / "evidence"

        def _fake_initialize(config_path: Path, force: bool = False) -> dict[str, str]:
            self.assertTrue(force)
            return _write_bootstrapped_mission(Path(config_path), test_root)

        def _fake_recursive_loop(config_path: Path) -> dict[str, object]:
            config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
            mission_state_path = Path(str(config["mission_state"]))
            runtime_root = mission_state_path.parent / "runtime" / "recursive_agent_runtime" / str(config["loop_name"])
            runtime_root.mkdir(parents=True, exist_ok=True)
            report_json_path = runtime_root / "loop_report.json"
            report_markdown_path = runtime_root / "loop_report.md"
            memory_path = runtime_root / "loop_memory.jsonl"
            state_path = runtime_root / "agent_loop_state.json"
            latest_result_path = runtime_root / "iteration-01-planner" / "summary.json"
            latest_result_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(latest_result_path, {"status": "continue", "summary": "Completed one bounded validation iteration."})
            write_json(report_json_path, {"status": "max-iterations"})
            report_markdown_path.write_text("# Loop report\n", encoding="utf-8")
            memory_path.write_text("{}\n", encoding="utf-8")
            write_json(state_path, {"status": "max-iterations"})
            return {
                "status": "max-iterations",
                "iterations_completed": 1,
                "iterations_remaining": 0,
                "consecutive_failures": 0,
                "runtime_root": runtime_root,
                "memory_path": memory_path,
                "state_path": state_path,
                "report_json_path": report_json_path,
                "report_markdown_path": report_markdown_path,
                "latest_iteration_path": latest_result_path.parent,
                "latest_result_path": latest_result_path,
                "latest_outcome": {
                    "status": "continue",
                    "summary": "Completed one bounded validation iteration.",
                    "action_result": {"status": "completed", "mission_action_id": "demo-validation-action"},
                },
            }

        mock_initialize_mission.side_effect = _fake_initialize
        mock_check_provider_readiness.return_value = {
            "status": "ready",
            "summary": "ready",
            "provider_family": "copilot-cli",
            "selection_profile": "gate2-coding-agent-copilot-gpt5-mini",
        }
        mock_run_recursive_agent_loop.side_effect = _fake_recursive_loop

        result = validate_real_runtime(
            lane_ids=["copilot-cli-gpt-5-mini-coding-agent"],
            output_root=evidence_root,
            validation_id="demo-copilot-run",
            operator="tester",
            machine_label="ci-host",
            general_notes=["Copilot CLI auth was already present on this machine."],
        )

        self.assertEqual(result["status"], "passed")
        record = json.loads(Path(result["lane_results"][0]["record_json_path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["runtime_execution"]["loop_result"]["status"], "max-iterations")
        self.assertEqual(record["runtime_execution"]["loop_result"]["latest_outcome"]["status"], "continue")
        self.assertTrue(Path(record["runtime_execution"]["config_path"]).exists())
        mission_state = json.loads(Path(record["mission_state_path"]).read_text(encoding="utf-8"))
        self.assertEqual(
            mission_state["next_actions"]["summary"],
            "Gate 2 runtime validation action for copilot-cli-gpt-5-mini-coding-agent",
        )
        self.assertEqual(mission_state["next_actions"]["actions"][0]["status"], "pending")

    @patch("deeploop.artifacts.real_runtime_validation.run_recursive_agent_loop")
    @patch("deeploop.artifacts.real_runtime_validation.check_provider_readiness")
    @patch("deeploop.artifacts.real_runtime_validation.initialize_mission")
    def test_validation_fails_when_manual_boundary_notes_are_missing(
        self,
        mock_initialize_mission,
        mock_check_provider_readiness,
        mock_run_recursive_agent_loop,
    ) -> None:
        test_root = _fresh_test_root("missing-manual-note")
        evidence_root = test_root / "evidence"

        mock_initialize_mission.side_effect = lambda config_path, force=False: _write_bootstrapped_mission(Path(config_path), test_root)
        mock_check_provider_readiness.return_value = {
            "status": "ready",
            "summary": "ready",
            "provider_family": "copilot-cli",
            "selection_profile": "gate2-coding-agent-copilot-gpt5-mini",
        }

        result = validate_real_runtime(
            lane_ids=["copilot-cli-gpt-5-mini-coding-agent"],
            output_root=evidence_root,
            validation_id="missing-note-run",
            operator="tester",
            machine_label="ci-host",
        )

        self.assertEqual(result["status"], "failed")
        mock_run_recursive_agent_loop.assert_not_called()
        record = json.loads(Path(result["lane_results"][0]["record_json_path"]).read_text(encoding="utf-8"))
        self.assertIn("record at least one manual boundary note", " ".join(record["failure_reasons"]).lower())


if __name__ == "__main__":
    unittest.main()
