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
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import MISSIONS_DIR, WORKSPACE_ROOT
from deeploop.mission.orchestrator import initialize_mission
from deeploop.mission.project_bootstrap import build_mission_config_from_project_root
from deeploop.project_contract import discover_project_contract, resolve_runtime_provider


class ProjectContractTests(unittest.TestCase):
    def test_mission_template_uses_workspace_uri_for_target_repo(self) -> None:
        template = yaml.safe_load(
            (REPO_ROOT / "examples" / "templates" / "mission-config.template.yaml").read_text(encoding="utf-8")
        )

        self.assertEqual(template["mission"]["target_repo"], "workspace://repos/TODO_REPO")

    def test_discover_project_contract_reports_missing_contract(self) -> None:
        repo_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "missing_repo"
        shutil.rmtree(repo_root, ignore_errors=True)
        repo_root.mkdir(parents=True, exist_ok=True)

        contract = discover_project_contract(repo_root)

        self.assertEqual(contract["status"], "missing")
        self.assertEqual(len(contract["missing_recommended_files"]), 3)
        self.assertIn(".deeploop", contract["contract_root"])
        self.assertTrue(contract["warnings"])

    def test_initialize_mission_ingests_project_contract_artifacts(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "mission_init"
        repo_root = test_root / "demo-project"
        shutil.rmtree(test_root, ignore_errors=True)
        (repo_root / ".deeploop" / "missions").mkdir(parents=True, exist_ok=True)
        (repo_root / ".github").mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "research").mkdir(parents=True, exist_ok=True)
        (repo_root / "configs" / "runtime").mkdir(parents=True, exist_ok=True)
        (repo_root / "data").mkdir(parents=True, exist_ok=True)

        (repo_root / "AGENTS.md").write_text("# Repo guidance\n", encoding="utf-8")
        (repo_root / ".github" / "copilot-instructions.md").write_text("# Copilot guidance\n", encoding="utf-8")
        project_doc = repo_root / "docs" / "research" / "project-brief.md"
        project_doc.write_text("# Project brief\n", encoding="utf-8")
        provider_config = repo_root / "configs" / "runtime" / "provider.yaml"
        provider_config.write_text("provider: demo\n", encoding="utf-8")
        project_data = repo_root / "data" / "train.csv"
        project_data.write_text("dt,value\n2024-01-01,1\n", encoding="utf-8")
        contract_project = repo_root / ".deeploop" / "project.yaml"
        contract_project.write_text(
            yaml.safe_dump(
                {
                    "project": {"name": "demo-project", "domain": "demo"},
                    "artifacts": {
                        "docs": ["docs/research/project-brief.md"],
                        "configs": ["configs/runtime/provider.yaml"],
                        "data": [
                            {
                                "path": "data/train.csv",
                                "kind": "tabular-timeseries",
                                "format": "csv",
                                "role": "primary-dataset",
                                "read_only": True,
                                "prompt_safe": "header-and-summary-only",
                                "split_keys": ["dt"],
                            }
                        ],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        runtime_providers = repo_root / ".deeploop" / "runtime-providers.yaml"
        runtime_providers.write_text("providers: []\n", encoding="utf-8")
        evaluation_contract = repo_root / ".deeploop" / "evaluation-contract.yaml"
        evaluation_contract.write_text("metrics: []\n", encoding="utf-8")
        mission_file = repo_root / ".deeploop" / "missions" / "demo.yaml"
        mission_file.write_text("mission: demo\n", encoding="utf-8")
        extra_doc = repo_root / "docs" / "research" / "extra.md"
        extra_doc.write_text("# Extra doc\n", encoding="utf-8")
        extra_config = repo_root / "configs" / "runtime" / "extra.yaml"
        extra_config.write_text("kind: extra\n", encoding="utf-8")
        extra_data = repo_root / "data" / "holdout.csv"
        extra_data.write_text("dt,value\n2024-01-02,2\n", encoding="utf-8")

        config_path = test_root / "mission.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "mission": {
                        "id": "project-contract-init-test",
                        "mode": "sandboxed-yolo",
                        "title": "Project contract test",
                        "summary": "Verify project contract discovery.",
                        "objective": "Ingest project-owned DeepLoop metadata.",
                        "target_repo": str(repo_root),
                        "experiment_coverage": {
                            "methods": [
                                {
                                    "category": "Numeric baselines",
                                    "name": "demo baseline",
                                    "status": "proposed",
                                }
                            ],
                            "budget": {"gpu_requested": False},
                        },
                    },
                    "acceptance_criteria": {
                        "min_methods_evaluated": 1,
                        "allow_final_report_only_if_criteria_met": True,
                    },
                    "roles": ["planner", "dataset-strategist", "execution-operator"],
                    "phases": ["idea-intake", "final-report"],
                    "artifacts": {
                        "docs": [str(extra_doc)],
                        "configs": [str(extra_config)],
                        "data": [{"path": str(extra_data), "kind": "labels", "format": "csv"}],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = initialize_mission(config_path, force=True)
        self.addCleanup(lambda: shutil.rmtree(Path(result["mission_root"]), ignore_errors=True))
        mission_state = json.loads(Path(result["state_path"]).read_text(encoding="utf-8"))
        planner_handoff = json.loads((Path(result["mission_root"]) / "agent_handoffs" / "planner.json").read_text(encoding="utf-8"))
        dataset_handoff = json.loads((Path(result["mission_root"]) / "agent_handoffs" / "dataset-strategist.json").read_text(encoding="utf-8"))
        execution_handoff = json.loads((Path(result["mission_root"]) / "agent_handoffs" / "execution-operator.json").read_text(encoding="utf-8"))

        self.assertEqual(mission_state["project_contract"]["status"], "available")
        self.assertEqual(mission_state["project_contract"]["project_metadata"]["name"], "demo-project")
        self.assertIn(str(project_doc.resolve()), mission_state["artifacts"]["docs"])
        self.assertIn(str(extra_doc.resolve()), mission_state["artifacts"]["docs"])
        self.assertIn(str(provider_config.resolve()), mission_state["artifacts"]["configs"])
        self.assertIn(str(extra_config.resolve()), mission_state["artifacts"]["configs"])
        data_paths = [artifact["path"] for artifact in mission_state["artifacts"]["data"]]
        self.assertIn(str(project_data.resolve()), data_paths)
        self.assertIn(str(extra_data.resolve()), data_paths)
        project_data_record = next(artifact for artifact in mission_state["artifacts"]["data"] if artifact["path"] == str(project_data.resolve()))
        self.assertEqual(project_data_record["kind"], "tabular-timeseries")
        self.assertEqual(project_data_record["role"], "primary-dataset")
        self.assertEqual(project_data_record["split_keys"], ["dt"])
        self.assertNotIn(str(project_data.resolve()), mission_state["artifacts"]["configs"])
        self.assertIn(str(contract_project.resolve()), planner_handoff["input_artifacts"])
        self.assertIn(str(runtime_providers.resolve()), planner_handoff["input_artifacts"])
        self.assertIn(str(evaluation_contract.resolve()), planner_handoff["input_artifacts"])
        self.assertIn(str(mission_file.resolve()), planner_handoff["input_artifacts"])
        self.assertIn(str(project_doc.resolve()), planner_handoff["input_artifacts"])
        self.assertIn(str(extra_doc.resolve()), planner_handoff["input_artifacts"])
        self.assertIn(str(project_data.resolve()), planner_handoff["input_artifacts"])
        self.assertIn(str(extra_data.resolve()), planner_handoff["input_artifacts"])
        self.assertNotIn("dataset_artifacts", planner_handoff)
        self.assertEqual(
            [artifact["path"] for artifact in dataset_handoff["dataset_artifacts"]],
            data_paths,
        )
        self.assertEqual(
            [artifact["path"] for artifact in execution_handoff["dataset_artifacts"]],
            data_paths,
        )
        self.assertIn(str(repo_root.joinpath("AGENTS.md").resolve()), mission_state["rule_sources"])
        self.assertIn(str(repo_root.joinpath(".github", "copilot-instructions.md").resolve()), mission_state["rule_sources"])
        self.assertEqual(
            mission_state["experiment_coverage"]["methods"][0]["status"],
            "proposed",
        )
        self.assertEqual(
            mission_state["acceptance_criteria"]["min_methods_evaluated"],
            1,
        )

    def test_initialize_mission_resolves_workspace_root_tokens_in_config_paths(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "workspace_uri_config"
        shutil.rmtree(test_root, ignore_errors=True)
        test_root.mkdir(parents=True, exist_ok=True)

        repo_name = "workspace-uri-config-project"
        repo_root = WORKSPACE_ROOT / "repos" / repo_name
        queue_path = WORKSPACE_ROOT / "runs" / "deeploop" / "queues" / "workspace-uri-config.yaml"
        shutil.rmtree(repo_root, ignore_errors=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text("entries: []\n", encoding="utf-8")
        self.addCleanup(lambda: shutil.rmtree(repo_root, ignore_errors=True))
        self.addCleanup(lambda: queue_path.unlink(missing_ok=True))

        config_path = test_root / "mission.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "mission": {
                        "id": "workspace-uri-config-test",
                        "mode": "sandboxed-yolo",
                        "title": "Workspace URI config test",
                        "summary": "Verify workspace-root-aware mission config paths.",
                        "objective": "Resolve workspace:// paths during mission initialization.",
                        "target_repo": f"workspace://repos/{repo_name}",
                        "bootstrap": {
                            "baseline_queue_config": "workspace://runs/deeploop/queues/workspace-uri-config.yaml",
                        },
                    },
                    "roles": ["planner"],
                    "phases": ["idea-intake", "final-report"],
                    "autopilot": {
                        "recursive_agent": {
                            "agent": {
                                "cwd": f"workspace://repos/{repo_name}",
                            }
                        }
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = initialize_mission(config_path, force=True)
        self.addCleanup(lambda: shutil.rmtree(Path(result["mission_root"]), ignore_errors=True))
        mission_state = json.loads(Path(result["state_path"]).read_text(encoding="utf-8"))
        recursive_profile_path = Path(mission_state["runtime_profiles"]["recursive_agent"]["config_path"])
        recursive_profile = yaml.safe_load(recursive_profile_path.read_text(encoding="utf-8"))

        self.assertEqual(mission_state["target_repo"], str(repo_root.resolve()))
        self.assertEqual(mission_state["bootstrap"]["baseline_queue_config"], str(queue_path.resolve()))
        self.assertEqual(recursive_profile["agent"]["cwd"], str(repo_root.resolve()))

    def test_discover_project_contract_supports_plain_project_facts(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "plain_artifacts"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "translation-pilot"
        (repo_root / "docs").mkdir(parents=True, exist_ok=True)
        brief_path = repo_root / "docs" / "project-brief.md"
        brief_path.write_text("# Project brief\n", encoding="utf-8")
        metrics_path = repo_root / "docs" / "benchmark-and-metrics.md"
        metrics_path.write_text("# Benchmark and metrics\n", encoding="utf-8")
        facts_path = repo_root / "project-facts.yaml"
        facts_path.write_text(
            yaml.safe_dump(
                {
                    "project": {
                        "name": "translation-zh-en-pilot",
                        "objective": "Improve translation quality from researcher artifacts only.",
                    },
                    "artifacts": {
                        "docs": ["docs/project-brief.md", "docs/benchmark-and-metrics.md"],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        contract = discover_project_contract(repo_root)

        self.assertEqual(contract["status"], "plain-artifacts")
        self.assertEqual(contract["project_metadata"]["name"], "translation-zh-en-pilot")
        self.assertEqual(contract["contract_files"], [str(facts_path.resolve())])
        self.assertEqual(
            contract["artifacts"]["docs"],
            [str(brief_path.resolve()), str(metrics_path.resolve())],
        )
        self.assertFalse(contract["warnings"])

    def test_plain_project_contract_preserves_data_and_warns_on_csv_configs(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "plain_data_artifacts"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "epf-pilot"
        (repo_root / "data").mkdir(parents=True, exist_ok=True)
        dataset_path = repo_root / "data" / "daily.csv"
        dataset_path.write_text("dt,pred_dt,value\n2024-01-01,2024-01-02,1\n", encoding="utf-8")
        facts_path = repo_root / "project-facts.yaml"
        facts_path.write_text(
            yaml.safe_dump(
                {
                    "project": {"name": "epf-pilot"},
                    "artifacts": {
                        "configs": ["data/daily.csv"],
                        "data": [
                            {
                                "path": "data/daily.csv",
                                "kind": "tabular-timeseries",
                                "role": "primary-dataset",
                                "read_only": True,
                                "prompt_safe": "header-and-summary-only",
                                "split_keys": ["dt", "pred_dt"],
                            }
                        ],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        contract = discover_project_contract(repo_root)

        self.assertEqual(contract["artifacts"]["data"][0]["path"], str(dataset_path.resolve()))
        self.assertEqual(contract["artifacts"]["data"][0]["format"], "csv")
        self.assertEqual(contract["artifacts"]["data"][0]["split_keys"], ["dt", "pred_dt"])
        self.assertTrue(any("artifacts.configs" in warning and "artifacts.data" in warning for warning in contract["warnings"]))

    def test_build_mission_config_from_project_root_uses_plain_project_metadata(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "project_bootstrap"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "translation-pilot"
        (repo_root / "docs").mkdir(parents=True, exist_ok=True)

        brief_path = repo_root / "docs" / "project-brief.md"
        brief_path.write_text("# Project brief\n", encoding="utf-8")
        metrics_path = repo_root / "docs" / "benchmark-and-metrics.md"
        metrics_path.write_text("# Metrics\n", encoding="utf-8")
        facts_path = repo_root / "project-facts.yaml"
        facts_path.write_text(
            yaml.safe_dump(
                {
                    "project": {
                        "name": "translation-zh-en-pilot",
                        "title": "English <-> Chinese translation pilot",
                        "summary": "Bootstrap from a no-code translation folder.",
                        "objective": "Improve the translation metric over the two starting Qwen baselines.",
                        "constraints": ["Use only the folder's facts as the substrate."],
                        "human_inputs": {
                            "ideas": ["English <-> Chinese machine translation"],
                            "budgets": {"max_gpu_hours": 12, "max_parallel_jobs": 2},
                        },
                        "acceptance_criteria": {
                            "min_methods_brainstormed": 12,
                            "require_gpu_method_attempt": True,
                        },
                    },
                    "artifacts": {"docs": ["docs/project-brief.md", "docs/benchmark-and-metrics.md"]},
                    "artifact_contract": {
                        "required_outputs": ["leaderboard", "test predictions for each evaluated method"],
                    },
                    "data": {"test_split": "held-out"},
                    "evaluation_contract": {"primary_metric": "bleu"},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        config = build_mission_config_from_project_root(repo_root)

        self.assertEqual(config["mission"]["id"], "translation-zh-en-pilot-mission")
        self.assertEqual(config["mission"]["title"], "English <-> Chinese translation pilot")
        self.assertEqual(config["mission"]["objective"], "Improve the translation metric over the two starting Qwen baselines.")
        self.assertIn("Use only the folder's facts as the substrate.", config["mission"]["constraints"])
        self.assertIn("minimal fact/contract substrate", " ".join(config["mission"]["constraints"]))
        self.assertEqual(config["mission"]["human_inputs"]["budgets"]["max_gpu_hours"], 12)
        self.assertEqual(config["mission"]["acceptance_criteria"]["min_methods_brainstormed"], 12)
        self.assertTrue(config["mission"]["acceptance_criteria"]["require_gpu_method_attempt"])
        self.assertEqual(config["mission"]["budgets"]["max_parallel_jobs"], 2)
        self.assertIn("leaderboard", config["mission"]["artifact_contract"]["required_outputs"])
        self.assertEqual(config["mission"]["data"]["test_split"], "held-out")
        self.assertEqual(config["mission"]["evaluation_contract"]["primary_metric"], "bleu")
        coverage = {entry["field"]: entry for entry in config["mission"]["contract_coverage"]}
        self.assertTrue(coverage["acceptance_criteria"]["present"])
        self.assertTrue(coverage["acceptance_criteria"]["promoted_to_config"])
        self.assertTrue(coverage["acceptance_criteria"]["included_in_prompts"])
        self.assertFalse(coverage["acceptance_criteria"]["enforced_by_runtime"])
        self.assertEqual(config["artifacts"]["docs"], [str(brief_path.resolve()), str(metrics_path.resolve())])
        self.assertEqual(config["autopilot"]["max_iterations"], 64)
        self.assertNotIn("launch_env_name", config["autopilot"])
        self.assertEqual(config["autopilot"]["recursive_agent"]["loop_name"], "translation-zh-en-pilot-phase-loop")
        self.assertEqual(config["autopilot"]["phase_execution_hints"]["idea-intake"]["executor"], "recursive-agent")
        self.assertEqual(config["autopilot"]["phase_execution_hints"]["execution"]["executor"], "recursive-agent")
        self.assertEqual(config["autopilot"]["phase_execution_hints"]["execution"]["next_phase_on_success"], "critique")
        self.assertEqual(config["autopilot"]["phase_execution_hints"]["replication"]["executor"], "recursive-agent")
        self.assertEqual(config["autopilot"]["phase_execution_hints"]["replication"]["next_phase_on_success"], "final-report")
        self.assertEqual(config["autopilot"]["phase_execution_hints"]["final-report"]["executor"], "report-synthesis")
        self.assertEqual(config["autopilot"]["phase_execution_hints"]["question-design"]["next_phase_on_success"], "benchmark-selection")
        self.assertTrue(facts_path.exists())

    def test_discover_plain_project_facts_warns_for_unoperationalized_top_level_fields(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "plain_unoperationalized"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "translation-pilot"
        repo_root.mkdir(parents=True, exist_ok=True)
        facts_path = repo_root / "project-facts.yaml"
        facts_path.write_text(
            yaml.safe_dump(
                {
                    "project": {
                        "name": "translation-zh-en-pilot",
                        "objective": "Improve translation quality from researcher artifacts only.",
                    },
                    "scratch_notes": {"owner": "researcher"},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        contract = discover_project_contract(repo_root)

        self.assertEqual(contract["unoperationalized_fields"], ["scratch_notes"])
        self.assertTrue(contract["warnings"])
        self.assertIn("scratch_notes", contract["warnings"][0])
        coverage = {entry["field"]: entry for entry in contract["contract_coverage"]}
        self.assertTrue(coverage["scratch_notes"]["present"])
        self.assertFalse(coverage["scratch_notes"]["promoted_to_config"])

    def test_init_mission_script_accepts_project_root(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "project_root_cli"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "translation-pilot"
        (repo_root / "docs").mkdir(parents=True, exist_ok=True)

        brief_path = repo_root / "docs" / "project-brief.md"
        brief_path.write_text("# Project brief\n", encoding="utf-8")
        metrics_path = repo_root / "docs" / "benchmark-and-metrics.md"
        metrics_path.write_text("# Benchmark and metrics\n", encoding="utf-8")
        (repo_root / "project-facts.yaml").write_text(
            yaml.safe_dump(
                {
                    "project": {
                        "name": "translation-zh-en-cli",
                        "title": "English <-> Chinese folder bootstrap",
                        "summary": "Use the project folder itself as the onboarding input.",
                        "objective": "Improve translation quality from the project folder only.",
                        "acceptance_criteria": {
                            "min_methods_evaluated": 8,
                            "require_leaderboard": True,
                        },
                    },
                    "artifacts": {"docs": ["docs/project-brief.md", "docs/benchmark-and-metrics.md"]},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        expected_config = build_mission_config_from_project_root(repo_root)
        mission_id = expected_config["mission"]["id"]
        mission_root = MISSIONS_DIR / mission_id
        self.addCleanup(lambda: shutil.rmtree(mission_root, ignore_errors=True))

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/mission/init_mission.py",
                "--project-root",
                str(repo_root),
                "--force",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("bootstrapped mission config from project folder", completed.stdout)
        state_path = mission_root / "mission_state.json"
        generated_config_path = mission_root / "generated_mission_config.yaml"
        self.assertTrue(state_path.exists(), f"missing mission state: {state_path}")
        self.assertTrue(generated_config_path.exists(), f"missing generated config: {generated_config_path}")
        mission_state = json.loads(state_path.read_text(encoding="utf-8"))
        generated_config = yaml.safe_load(generated_config_path.read_text(encoding="utf-8"))
        self.assertEqual(mission_state["mission_id"], mission_id)
        self.assertEqual(mission_state["target_repo"], str(repo_root.resolve()))
        self.assertEqual(mission_state["objective"], "Improve translation quality from the project folder only.")
        self.assertEqual(generated_config["mission"]["acceptance_criteria"]["min_methods_evaluated"], 8)
        self.assertEqual(mission_state["acceptance_criteria"]["min_methods_evaluated"], 8)
        self.assertTrue(mission_state["acceptance_criteria"]["require_leaderboard"])
        self.assertEqual(mission_state["project_contract"]["status"], "plain-artifacts")
        self.assertEqual(mission_state["phase_execution_hints"]["idea-intake"]["executor"]["id"], "recursive-agent")
        self.assertEqual(mission_state["phase_execution_hints"]["execution"]["executor"]["id"], "stage-kernel")
        self.assertEqual(mission_state["phase_execution_hints"]["execution"]["executor"]["params"]["stage_id"], "baseline-evaluation")
        self.assertEqual(mission_state["phase_execution_hints"]["critique"]["executor"]["id"], "evaluation-comparison")
        self.assertEqual(mission_state["phase_execution_hints"]["replication"]["executor"]["id"], "stage-kernel")
        self.assertEqual(mission_state["phase_execution_hints"]["final-report"]["executor"]["id"], "report-synthesis")
        self.assertEqual(
            mission_state["artifacts"]["docs"],
            [str(brief_path.resolve()), str(metrics_path.resolve())],
        )
        self.assertIn("plain_folder_followups", mission_state)
        self.assertTrue(Path(mission_state["plain_folder_followups"]["execution_config_path"]).exists())
        self.assertTrue(Path(mission_state["plain_folder_followups"]["replication_config_path"]).exists())
        self.assertTrue(Path(mission_state["plain_folder_followups"]["promotion_manifest_path"]).exists())

    def test_build_mission_config_from_project_root_compiles_readiness_from_natural_language_brief(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "natural_language_brief"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "housing-pilot"
        (repo_root / "docs").mkdir(parents=True, exist_ok=True)
        brief_path = repo_root / "docs" / "project-brief.md"
        brief_path.write_text(
            "\n".join(
                [
                    "# Kickoff",
                    "Build a regression baseline using /datasets/housing/train.csv to predict sale_price.",
                    "Keep a strict holdout split and avoid neighborhood leakage.",
                    "Compare against the current linear baseline.",
                    "Deliver run manifests, metrics, and a final report.",
                    "Cap compute at 4 GPU hours and stop after two failed attempts.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (repo_root / "project-facts.yaml").write_text(
            yaml.safe_dump(
                {
                    "project": {
                        "name": "housing-regression-pilot",
                    },
                    "artifacts": {"docs": ["docs/project-brief.md"]},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        config = build_mission_config_from_project_root(repo_root)
        mission_contract = config["mission_contract"]

        self.assertEqual(config["mission"]["objective"], "Build a regression baseline using /datasets/housing/train.csv to predict sale_price.")
        self.assertEqual(mission_contract["objective"]["task_type"], "regression")
        self.assertEqual(mission_contract["data"]["dataset"], ["/datasets/housing/train.csv"])
        self.assertEqual(mission_contract["data"]["target"], "sale_price")
        self.assertIn("holdout", mission_contract["data"]["split_policy"].lower())
        self.assertEqual(mission_contract["budget"]["compute_budget"], "4 GPU hours")
        self.assertEqual(mission_contract["readiness"]["status"], "ready-with-clarifications")
        self.assertTrue(
            any(item["id"] == "publication-boundary" for item in mission_contract["prerequisites"]),
            "Expected publication-boundary prerequisite to be present",
        )
        self.assertTrue(
            any(item["id"] == "novelty-target" for item in mission_contract["prerequisites"]),
            "Expected novelty-target prerequisite to be present",
        )

    def test_build_mission_config_from_project_root_surfaces_repair_scaffold_for_missing_plain_folder_contract(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "missing_plain_contract"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "starter-pilot"
        (repo_root / "docs").mkdir(parents=True, exist_ok=True)
        (repo_root / "data").mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "project-brief.md").write_text("# Project brief\n", encoding="utf-8")
        (repo_root / "data" / "train.csv").write_text("label,value\n1,2\n", encoding="utf-8")

        config = build_mission_config_from_project_root(repo_root)
        repair = config["bootstrap_repair"]
        mission_contract = config["mission_contract"]
        starter_payload = yaml.safe_load(Path(repair["starter_scaffold_path"]).read_text(encoding="utf-8"))

        self.assertEqual(repair["reason"], "missing-bootstrap-contract")
        self.assertEqual(mission_contract["readiness"]["status"], "blocked")
        self.assertEqual(mission_contract["readiness"]["launch_recommendation"], "repair-bootstrap-input")
        self.assertEqual(repair["starter_target_path"], str((repo_root / "project-facts.yaml").resolve()))
        self.assertIn("docs/project-brief.md", starter_payload["artifacts"]["docs"])
        self.assertEqual(starter_payload["artifacts"]["data"][0]["path"], "data/train.csv")
        self.assertTrue(any(item["id"] == "bootstrap-repair" for item in mission_contract["prerequisites"]))

    def test_build_mission_config_from_project_root_surfaces_ambiguous_partial_contract(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "ambiguous_plain_contract"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "ambiguous-pilot"
        (repo_root / ".deeploop").mkdir(parents=True, exist_ok=True)
        (repo_root / "project-facts.yaml").write_text(
            yaml.safe_dump({"project": {"name": "ambiguous-pilot"}}, sort_keys=False),
            encoding="utf-8",
        )

        config = build_mission_config_from_project_root(repo_root)
        repair = config["bootstrap_repair"]

        self.assertEqual(repair["reason"], "ambiguous-bootstrap-root")
        self.assertIsNone(repair["starter_scaffold_path"])
        self.assertEqual(
            repair["starter_target_path"],
            str((repo_root / ".deeploop" / "project.yaml").resolve()),
        )
        self.assertEqual(config["mission_contract"]["readiness"]["launch_recommendation"], "repair-bootstrap-input")

    def test_initialize_mission_writes_compiled_mission_contract_summary(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "compiled_contract_summary"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "crm-pilot"
        (repo_root / "docs").mkdir(parents=True, exist_ok=True)
        brief_path = repo_root / "docs" / "project-brief.md"
        brief_path.write_text(
            "# Kickoff\n"
            "Train a classifier on our CRM export to improve retention decisions.\n"
            "Avoid leakage.\n",
            encoding="utf-8",
        )
        (repo_root / "project-facts.yaml").write_text(
            yaml.safe_dump(
                {
                    "project": {"name": "crm-retention"},
                    "artifacts": {"docs": ["docs/project-brief.md"]},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        generated_config = build_mission_config_from_project_root(repo_root)
        config_path = test_root / "mission.yaml"
        config_path.write_text(yaml.safe_dump(generated_config, sort_keys=False), encoding="utf-8")

        result = initialize_mission(config_path, force=True)
        self.addCleanup(lambda: shutil.rmtree(Path(result["mission_root"]), ignore_errors=True))
        mission_state = json.loads(Path(result["state_path"]).read_text(encoding="utf-8"))
        mission_summary = Path(result["summary_path"]).read_text(encoding="utf-8")
        planner_handoff_path = Path(result["mission_root"]) / "agent_handoffs" / "planner.json"
        planner_handoff = json.loads(planner_handoff_path.read_text(encoding="utf-8"))

        self.assertEqual(mission_state["mission_contract"]["readiness"]["status"], "blocked")
        self.assertTrue(Path(mission_state["mission_contract_path"]).exists())
        self.assertIn("compiled_mission_contract.yaml", "\n".join(planner_handoff["input_artifacts"]))
        self.assertIn("## Readiness summary", mission_summary)
        self.assertIn("### Blocking prerequisites", mission_summary)
        self.assertIn("Where is the dataset located", mission_summary)
        self.assertIn("What target variable should DeepLoop optimize or predict?", mission_summary)

    def test_init_mission_script_reports_bootstrap_repair_for_missing_plain_folder_contract(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "project_root_repair_cli"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "repair-cli-pilot"
        (repo_root / "docs").mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "project-brief.md").write_text("# Project brief\n", encoding="utf-8")

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/mission/init_mission.py",
                "--project-root",
                str(repo_root),
                "--force",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("project-root bootstrap needs repair", completed.stderr)
        self.assertIn("missing-bootstrap-contract", completed.stderr)
        self.assertIn("starter_scaffold", completed.stderr)

    def test_resolve_runtime_provider_rejects_malformed_provider_contract(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "malformed_provider"
        shutil.rmtree(test_root, ignore_errors=True)
        contract_root = test_root / "demo-project" / ".deeploop"
        contract_root.mkdir(parents=True, exist_ok=True)
        providers_path = contract_root / "runtime-providers.yaml"
        providers_path.write_text(
            yaml.safe_dump(
                {
                    "providers": {
                        "followup_planner": {
                            "params": ["not-a-mapping"],
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            resolve_runtime_provider(
                {
                    "contract_root": str(contract_root.resolve()),
                    "runtime_providers_path": str(providers_path.resolve()),
                },
                "followup_planner",
            )

    def test_resolve_runtime_provider_resolves_pythonpath_and_contract_relative_params(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "project_contract" / "provider_pythonpath"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "demo-project"
        contract_root = repo_root / ".deeploop"
        (contract_root / "queues").mkdir(parents=True, exist_ok=True)
        (repo_root / "src").mkdir(parents=True, exist_ok=True)
        providers_path = contract_root / "runtime-providers.yaml"
        providers_path.write_text(
            yaml.safe_dump(
                {
                    "providers": {
                        "followup_planner": {
                            "entrypoint": "demo_followup:stage_followups",
                            "pythonpath": ["../src"],
                            "params": {
                                "baseline_queue_config": "queues/translation-long-run-baseline-queue.yaml",
                            },
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        provider = resolve_runtime_provider(
            {
                "repo_root": str(repo_root.resolve()),
                "contract_root": str(contract_root.resolve()),
                "runtime_providers_path": str(providers_path.resolve()),
            },
            "followup_planner",
        )

        self.assertEqual(provider["entrypoint"], "demo_followup:stage_followups")
        self.assertEqual(provider["pythonpath"], [str((repo_root / "src").resolve())])
        self.assertEqual(
            provider["params"]["baseline_queue_config"],
            str((contract_root / "queues" / "translation-long-run-baseline-queue.yaml").resolve()),
        )


if __name__ == "__main__":
    unittest.main()
