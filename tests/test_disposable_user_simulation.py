from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
import sys

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.testing.disposable_user_simulation import (
    DEFAULT_MATRIX_PATH,
    apply_runtime_constraints_to_project_facts,
    build_scenario_contract,
    load_disposable_user_simulation_matrix,
    materialize_scenario_workspace,
    recommended_deeploop_commands,
)
from deeploop.testing.disposable_user_simulation_outer_user import (
    DEFAULT_OUTER_USER_MODEL,
    DisposableUserSimulationInputs,
    build_phase_prompt,
    run_disposable_user_simulation,
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "testing" / "run_disposable_user_simulation_matrix.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("run_disposable_user_simulation_matrix_script", SCRIPT_PATH)
assert _SCRIPT_SPEC is not None and _SCRIPT_SPEC.loader is not None
run_disposable_user_simulation_matrix = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(run_disposable_user_simulation_matrix)


class DisposableUserSimulationTests(unittest.TestCase):
    def test_resolve_host_copilot_mounts_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            (home / ".config" / "gh").mkdir(parents=True, exist_ok=True)
            (home / ".copilot").mkdir(parents=True, exist_ok=True)
            fake_binary = home / "bin" / "copilot"
            fake_binary.parent.mkdir(parents=True, exist_ok=True)
            fake_binary.write_text("#!/bin/sh\n", encoding="utf-8")

            with patch.object(run_disposable_user_simulation_matrix.shutil, "which", return_value=str(fake_binary)):
                mounts = run_disposable_user_simulation_matrix._resolve_host_copilot_mounts(enabled=True, home=home)

        self.assertEqual(mounts[0]["target"], "/usr/local/bin/copilot")
        self.assertTrue(mounts[0]["read_only"])
        self.assertEqual(mounts[1]["target"], "/home/deeploop/.config/gh")
        self.assertEqual(mounts[2]["target"], "/home/deeploop/.copilot")
        self.assertFalse(mounts[2]["read_only"])

    def test_resolve_host_copilot_mounts_requires_binary_and_gh_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            with patch.object(run_disposable_user_simulation_matrix.shutil, "which", return_value=None):
                with self.assertRaisesRegex(FileNotFoundError, "host `copilot` binary"):
                    run_disposable_user_simulation_matrix._resolve_host_copilot_mounts(enabled=True, home=home)

            fake_binary = home / "bin" / "copilot"
            fake_binary.parent.mkdir(parents=True, exist_ok=True)
            fake_binary.write_text("#!/bin/sh\n", encoding="utf-8")
            with patch.object(run_disposable_user_simulation_matrix.shutil, "which", return_value=str(fake_binary)):
                with self.assertRaisesRegex(FileNotFoundError, "~/.config/gh"):
                    run_disposable_user_simulation_matrix._resolve_host_copilot_mounts(enabled=True, home=home)

    def test_load_matrix_exposes_required_runtime_pins(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)

        self.assertTrue(matrix.sequential_execution)
        self.assertEqual(matrix.minimum_session_seconds, 3600)
        self.assertEqual(matrix.simulator.required_model_alias, "gpt-5.4-mini")
        self.assertEqual(matrix.control_plane.selection_profile, "gate2-coding-agent-copilot-gpt5-mini")
        self.assertEqual(matrix.control_plane.model_alias, "gpt-5-mini")
        self.assertEqual(matrix.experiment_execution.selection_profile, "gate2-local-qwen3_5-9b-openai")
        self.assertEqual(matrix.experiment_execution.model_identifier, "Qwen/Qwen3.5-9B")
        self.assertEqual(len(matrix.scenarios), 3)

    def test_apply_runtime_constraints_updates_project_facts(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        scenario = matrix.scenarios[0]

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            facts_path = project_root / "project-facts.yaml"
            facts_path.write_text(
                yaml.safe_dump({"project": {"name": "demo", "constraints": ["existing"], "human_inputs": {}}}, sort_keys=False),
                encoding="utf-8",
            )

            apply_runtime_constraints_to_project_facts(project_root, matrix, scenario)

            updated = yaml.safe_load(facts_path.read_text(encoding="utf-8"))

        project = updated["project"]
        self.assertIn("existing", project["constraints"])
        self.assertTrue(any("Qwen/Qwen3.5-9B" in item for item in project["constraints"]))
        self.assertEqual(project["human_inputs"]["outer_user_simulator_model"], "gpt-5.4-mini")
        self.assertEqual(
            project["human_inputs"]["deeploop_experiment_execution_selection_profile"],
            "gate2-local-qwen3_5-9b-openai",
        )

    def test_materialize_workspace_copies_fixture_and_injects_constraints(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        scenario = next(item for item in matrix.scenarios if item.project_shape == "plain-folder-fixture")

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir)
            project_root = materialize_scenario_workspace(matrix, scenario, workspace_root=workspace_root)
            assert project_root is not None
            facts = yaml.safe_load((project_root / "project-facts.yaml").read_text(encoding="utf-8"))
            docs_exists = (project_root / "docs").exists()

        self.assertTrue(docs_exists)
        self.assertEqual(facts["project"]["human_inputs"]["user_simulation_scenario"], scenario.scenario_id)
        self.assertIn("gpt-5-mini", " ".join(facts["project"]["constraints"]))

    def test_recommended_commands_use_project_root_when_present(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        starter_scenario = next(item for item in matrix.scenarios if item.project_shape == "bundled-starter")
        discovery_scenario = next(item for item in matrix.scenarios if item.project_shape == "discovery-first")

        starter_commands = recommended_deeploop_commands(matrix, starter_scenario)
        discovery_commands = recommended_deeploop_commands(matrix, discovery_scenario)

        self.assertIn("--project-root", starter_commands[0])
        self.assertEqual(discovery_commands[0], "deeploop run --until-complete")
        self.assertEqual(
            discovery_commands[1:],
            [
                "deeploop status --mission-state <mission-state.json>",
                "deeploop inbox --mission-state <mission-state.json>",
                "deeploop resume --mission-state <mission-state.json>",
            ],
        )

    def test_run_scenario_prepare_only_writes_contract_bundle(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        scenario = matrix.scenarios[0]

        with tempfile.TemporaryDirectory() as tmpdir:
            scenario_root = Path(tmpdir) / "scenario"
            summary = run_disposable_user_simulation_matrix._run_scenario(
                docker_bin="docker",
                image_tag="demo:latest",
                campaign_id="campaign-1",
                scenario_root=scenario_root,
                scenario=scenario,
                matrix=matrix,
                simulator_command=None,
                prepare_only=True,
                host_copilot_mount=False,
            )

            contract = json.loads((scenario_root / "scenario_contract.json").read_text(encoding="utf-8"))
            runtime_pins = yaml.safe_load((scenario_root / "deeploop_runtime_pins.yaml").read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "prepared")
        self.assertEqual(contract["runtime_constraints"]["deeploop_control_plane"]["model"]["alias"], "gpt-5-mini")
        self.assertEqual(
            runtime_pins["runtime_constraints"]["deeploop_experiment_execution"]["model"]["identifier"],
            "Qwen/Qwen3.5-9B",
        )
        self.assertEqual(summary["container_mounts"], [])

    def test_main_defaults_output_root_under_reports_local(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        scenario = matrix.scenarios[0]
        captured_roots: list[Path] = []

        def fake_run_scenario(**kwargs):
            captured_roots.append(kwargs["scenario_root"])
            return {"status": "prepared"}

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            with patch.object(run_disposable_user_simulation_matrix, "REPO_ROOT", repo_root):
                with patch.object(run_disposable_user_simulation_matrix, "DEFAULT_OUTPUT_ROOT", repo_root / "reports" / "local" / "disposable-user-simulation"):
                    with patch.object(run_disposable_user_simulation_matrix, "_run_scenario", side_effect=fake_run_scenario):
                        exit_code = run_disposable_user_simulation_matrix.main(
                            [
                                "--prepare-only",
                                "--campaign-id",
                                "campaign-local-output",
                                "--scenario",
                                scenario.scenario_id,
                            ]
                        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            captured_roots,
            [repo_root / "reports" / "local" / "disposable-user-simulation" / "campaign-local-output" / scenario.scenario_id],
        )

    def test_prepare_campaign_output_root_uses_managed_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            manager_path = temp_root / "sandbox_manager.py"
            manager_path.write_text("# stub\n", encoding="utf-8")
            requested_root = temp_root / "requested-output"
            registry_root = temp_root / "sandbox-registry"
            created_root = temp_root / "managed-output"
            captured: dict[str, object] = {}

            def fake_run(manager_path_arg, command, *, registry_root=None):
                captured["manager_path"] = manager_path_arg
                captured["command"] = command
                captured["registry_root"] = registry_root
                created_root.mkdir(parents=True, exist_ok=True)
                return {
                    "id": "sandbox-123",
                    "path": str(created_root),
                    "state": "active",
                    "purpose": "disposable user simulation",
                    "type": "validation",
                    "expires_at": "2026-05-16T00:00:00Z",
                    "cleanup_policy": {"mode": "manual"},
                    "integrity": {
                        "manifest_path": str(registry_root / "manifests" / "sandbox-123.json"),
                        "registry_root": str(registry_root),
                    },
                }

            args = argparse.Namespace(
                output_root=str(requested_root),
                managed_sandbox=True,
                sandbox_manager=str(manager_path),
                sandbox_registry_root=str(registry_root),
                sandbox_cleanup_policy="manual",
                sandbox_ttl_hours=12.0,
            )

            with patch.object(run_disposable_user_simulation_matrix, "_run_sandbox_manager_json", side_effect=fake_run):
                output_root, managed = run_disposable_user_simulation_matrix._prepare_campaign_output_root(
                    args=args,
                    campaign_id="campaign-managed",
                )

            self.assertEqual(output_root, created_root)
            self.assertTrue(output_root.is_dir())
            self.assertIsNotNone(managed)
            assert managed is not None
            self.assertEqual(managed.manager_path, manager_path)
            self.assertEqual(managed.registry_root, registry_root)

        self.assertEqual(
            captured["command"],
            [
                "create",
                "--repo",
                "deeploop",
                "--purpose",
                "disposable user simulation",
                "--type",
                "validation",
                "--cleanup-policy",
                "manual",
                "--ttl-hours",
                "12.0",
                "--path",
                str(requested_root),
            ],
        )

    def test_main_records_managed_sandbox_metadata(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        scenario = matrix.scenarios[0]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "managed-output"
            managed = run_disposable_user_simulation_matrix.ManagedSandboxContext(
                manager_path=Path(tmpdir) / "sandbox_manager.py",
                registry_root=Path(tmpdir) / "sandbox-registry",
                manifest={
                    "id": "sandbox-123",
                    "path": str(output_root),
                    "state": "active",
                    "purpose": "disposable user simulation",
                    "type": "validation",
                    "expires_at": "2026-05-16T00:00:00Z",
                    "cleanup_policy": {"mode": "delete"},
                    "integrity": {
                        "manifest_path": str(Path(tmpdir) / "sandbox-registry" / "manifests" / "sandbox-123.json"),
                        "registry_root": str(Path(tmpdir) / "sandbox-registry"),
                    },
                },
            )

            def fake_run_scenario(**kwargs):
                return {
                    "scenario_id": kwargs["scenario"].scenario_id,
                    "status": "prepared",
                    "container_name": "demo-container",
                    "elapsed_seconds": 0.0,
                    "contract_path": str(output_root / kwargs["scenario"].scenario_id / "scenario_contract.json"),
                    "container_mounts": [],
                }

            with patch.object(
                run_disposable_user_simulation_matrix,
                "_prepare_campaign_output_root",
                return_value=(output_root, managed),
            ):
                with patch.object(run_disposable_user_simulation_matrix, "_run_scenario", side_effect=fake_run_scenario):
                    exit_code = run_disposable_user_simulation_matrix.main(
                        [
                            "--prepare-only",
                            "--managed-sandbox",
                            "--campaign-id",
                            "campaign-managed",
                            "--scenario",
                            scenario.scenario_id,
                        ]
                    )

            summary_payload = json.loads((output_root / "campaign_summary.json").read_text(encoding="utf-8"))
            metadata_payload = json.loads((output_root / "metadata" / "managed-sandbox.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary_payload["managed_sandbox"]["id"], "sandbox-123")
        self.assertEqual(summary_payload["managed_sandbox"]["path"], str(output_root))
        self.assertEqual(metadata_payload["id"], "sandbox-123")

    def test_run_simulator_command_enforces_minimum_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenario_root = Path(tmpdir)
            with patch.object(run_disposable_user_simulation_matrix.time, "monotonic", side_effect=[10.0, 11.0]):
                with patch.object(
                    run_disposable_user_simulation_matrix.subprocess,
                    "run",
                    return_value=run_disposable_user_simulation_matrix.subprocess.CompletedProcess(
                        ["echo", "ok"],
                        0,
                        "stdout",
                        "stderr",
                    ),
                ):
                    with self.assertRaisesRegex(RuntimeError, "minimum required duration"):
                        run_disposable_user_simulation_matrix._run_simulator_command(
                            ["echo", "ok"],
                            scenario_root=scenario_root,
                            env={},
                            minimum_session_seconds=3600,
                        )

    def test_build_scenario_contract_keeps_runtime_pins(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        scenario = matrix.scenarios[1]

        contract = build_scenario_contract(matrix, scenario, campaign_id="campaign-2", container_name="demo-container")

        self.assertEqual(contract["runtime_constraints"]["outer_user_simulator"]["model_alias"], "gpt-5.4-mini")
        self.assertEqual(
            contract["runtime_constraints"]["deeploop_experiment_execution"]["host_execution_profile"],
            "qwen3_5-9b-openai-local",
        )
        self.assertEqual(contract["container"]["project_root"], None)

    def test_outer_user_wrapper_builds_phase_prompt_with_pinned_lanes(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        scenario = matrix.scenarios[0]

        inputs = DisposableUserSimulationInputs(
            campaign_id="campaign-outer",
            scenario_id=scenario.scenario_id,
            container_name="demo-container",
            scenario_root=REPO_ROOT / "build" / "outer-user-simulation",
            prompt_path=REPO_ROOT / "build" / "outer-user-simulation" / "prompt.md",
            contract_path=REPO_ROOT / "build" / "outer-user-simulation" / "scenario_contract.json",
            runtime_pins_path=REPO_ROOT / "build" / "outer-user-simulation" / "runtime_pins.yaml",
            workspace_root="/home/deeploop/Workspaces",
            artifacts_root="/artifacts",
            minimum_session_seconds=3600,
        )

        prompt = build_phase_prompt(
            inputs,
            phase_index=0,
            phase_count=3,
            phase_name="opening",
            previous_transcript="",
            prompt_text="Outer prompt body",
            contract_text='{"contract_id": "demo"}',
            runtime_pins_text="runtime_constraints: {}",
        )

        self.assertIn("gpt-5.4-mini", prompt)
        self.assertIn("Outer prompt body", prompt)
        self.assertIn("contract_id", prompt)
        self.assertIn("runtime_constraints", prompt)
        self.assertIn("use that exact command before trying `deeploop run --until-complete`", prompt)

    def test_render_outer_user_prompt_prefers_project_root_command(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        scenario = next(item for item in matrix.scenarios if item.project_shape == "plain-folder-fixture")

        contract = build_scenario_contract(matrix, scenario, campaign_id="campaign-outer", container_name="demo-container")
        from deeploop.testing.disposable_user_simulation import render_outer_user_prompt

        prompt_lines = render_outer_user_prompt(matrix, scenario, contract)
        prompt = "\n".join(prompt_lines)

        self.assertIn("project_root", prompt)
        self.assertIn("start with that exact command before trying discovery-style fallbacks", prompt)

    def test_outer_user_wrapper_writes_phase_transcripts(self) -> None:
        matrix = load_disposable_user_simulation_matrix(DEFAULT_MATRIX_PATH)
        scenario = matrix.scenarios[0]
        scenario_root = REPO_ROOT / "build" / "test-disposable-user-simulation" / "outer-user-wrapper"
        shutil.rmtree(scenario_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, scenario_root, True)
        scenario_root.mkdir(parents=True, exist_ok=True)
        (scenario_root / "artifacts").mkdir(parents=True, exist_ok=True)
        (scenario_root / "prompt.md").write_text("Outer prompt body", encoding="utf-8")

        contract = build_scenario_contract(matrix, scenario, campaign_id="campaign-outer", container_name="demo-container")
        (scenario_root / "scenario_contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
        (scenario_root / "runtime_pins.yaml").write_text(
            yaml.safe_dump(run_disposable_user_simulation_matrix._scenario_runtime_pins_yaml(contract), sort_keys=False),
            encoding="utf-8",
        )

        inputs = DisposableUserSimulationInputs(
            campaign_id="campaign-outer",
            scenario_id=scenario.scenario_id,
            container_name="demo-container",
            scenario_root=scenario_root,
            prompt_path=scenario_root / "prompt.md",
            contract_path=scenario_root / "scenario_contract.json",
            runtime_pins_path=scenario_root / "runtime_pins.yaml",
            workspace_root="/home/deeploop/Workspaces",
            artifacts_root="/artifacts",
            minimum_session_seconds=3600,
        )

        current = [0.0]
        call_count = [0]

        def fake_clock() -> float:
            return current[0]

        def fake_sleep(seconds: float) -> None:
            current[0] += seconds

        def fake_run(command, **kwargs):
            call_count[0] += 1
            self.assertIn("--model", command)
            self.assertIn(DEFAULT_OUTER_USER_MODEL, command)
            current[0] += 0.25
            return run_disposable_user_simulation_matrix.subprocess.CompletedProcess(
                command,
                0,
                f"phase-{call_count[0]} output\n",
                "",
            )

        summary = run_disposable_user_simulation(
            inputs,
            runner=fake_run,
            clock=fake_clock,
            sleeper=fake_sleep,
        )

        run_root = scenario_root / "artifacts" / "outer-user-simulation"
        self.assertEqual(summary["status"], "passed")
        self.assertTrue((run_root / "summary.json").exists())
        self.assertTrue((run_root / "transcript.md").exists())
        self.assertTrue((run_root / "phases" / "01-opening" / "phase.json").exists())
        self.assertGreaterEqual(summary["elapsed_seconds"], 3600)
        self.assertEqual(call_count[0], 3)


if __name__ == "__main__":
    unittest.main()
