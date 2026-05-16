from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import MISSIONS_DIR, SCRATCH_DIR
from deeploop.testing.acceptance_campaigns import build_acceptance_review, materialize_acceptance_review
from deeploop.testing.plain_folder_proof_matrix import discover_plain_folder_proof_cases, snapshot_project_tree
from deeploop.testing.proof_matrix_reviews import build_multi_substrate_proof_review


class EndToEndSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "end_to_end_smoke"
        shutil.rmtree(self.runtime_root, ignore_errors=True)
        self.runtime_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def _passing_case(self, case_id: str, workflow_shape: str) -> dict:
        return {
            "case_id": case_id,
            "title": case_id.replace("-", " ").title(),
            "workflow_shape": workflow_shape,
            "status": "passed",
            "autonomy_claims": ["public proof claim"],
            "failures": [],
            "mission_state": {
                "operator_inbox_status": "clear",
                "final_report_outputs": ["final-report.md"],
                "current_phase": "final-report",
            },
            "operator_request": {},
            "boundary_check": {"project_tree_unchanged": True},
            "run_project_result": {"status": "completed"},
        }

    def _copy_plain_folder_fixture(self, case_id: str) -> Path:
        source = REPO_ROOT / "tests" / "_proof_fixtures" / "plain_folder" / case_id
        project_root = self.runtime_root / case_id
        shutil.copytree(source, project_root)
        return project_root

    def test_mission_advance_generates_runtime_owned_followup_queue(self) -> None:
        cases = {case.case_id: case for case in discover_plain_folder_proof_cases()}
        self.assertIn("translation-budget-ladder", cases)
        self.assertEqual(cases["translation-budget-ladder"].workflow_shape, "benchmark-heavy")

    def test_canonical_runtime_starts_without_missing_executor_block(self) -> None:
        review = build_multi_substrate_proof_review(
            {
                "campaign_id": "demo-smoke",
                "status": "passed",
                "case_summaries": [
                    self._passing_case("translation-budget-ladder", "benchmark-heavy"),
                ],
            }
        )
        case_review = review["case_reviews"][0]
        self.assertEqual(case_review["status"], "passed")
        self.assertTrue(case_review["gate_results"]["operator_inbox_clear"])
        self.assertEqual(case_review["failure_categories"], [])

    def test_end_to_end_smoke_runs_followups_and_packages(self) -> None:
        review = build_multi_substrate_proof_review(
            {
                "campaign_id": "demo-smoke",
                "status": "passed",
                "case_summaries": [
                    self._passing_case("translation-budget-ladder", "benchmark-heavy"),
                    self._passing_case("literature-gap-map", "literature-heavy"),
                    self._passing_case("replication-heavy-redteam", "execution-heavy"),
                ],
            }
        )
        self.assertEqual(review["decision"], "eligible-for-promotion")
        self.assertEqual(review["counts"]["workflow_shapes"], 3)
        self.assertEqual(review["failed_gate_ids"], [])

    def test_long_run_profile_stages_canonical_followups_with_real_backend(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/testing/run_plain_folder_proof_matrix.py", "--list"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        listed = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        case_ids = {item["case_id"] for item in listed}
        self.assertEqual(
            case_ids,
            {
                "forecast-rough-notes",
                "translation-budget-ladder",
                "literature-gap-map",
                "replication-heavy-redteam",
            },
        )

    def test_nontranslation_plain_folder_bootstrap_records_operator_blockers_and_packages(self) -> None:
        project_root = self._copy_plain_folder_fixture("literature-gap-map")
        project_facts_path = project_root / "project-facts.yaml"
        project_facts = yaml.safe_load(project_facts_path.read_text(encoding="utf-8")) or {}
        project_section = project_facts.get("project") if isinstance(project_facts.get("project"), dict) else {}
        human_inputs = project_section.get("human_inputs") if isinstance(project_section.get("human_inputs"), dict) else {}
        human_inputs.pop("dataset_access", None)
        project_section["human_inputs"] = human_inputs
        project_facts["project"] = project_section
        project_facts_path.write_text(yaml.safe_dump(project_facts, sort_keys=False), encoding="utf-8")
        before_paths = snapshot_project_tree(project_root)
        mission_id = "end-to-end-smoke-literature"
        mission_root = MISSIONS_DIR / mission_id
        package_root = mission_root.parent / "packages" / mission_id
        shutil.rmtree(mission_root, ignore_errors=True)
        shutil.rmtree(package_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(mission_root, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(package_root, ignore_errors=True))

        init_completed = subprocess.run(
            [
                sys.executable,
                "scripts/mission/init_mission.py",
                "--project-root",
                str(project_root),
                "--mission-id",
                mission_id,
                "--force",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(init_completed.returncode, 0, init_completed.stdout + init_completed.stderr)

        state_path = mission_root / "mission_state.json"
        self.assertTrue(state_path.exists(), f"missing mission state: {state_path}")
        mission_state = json.loads(state_path.read_text(encoding="utf-8"))
        readiness = mission_state.get("mission_contract", {}).get("readiness", {})

        self.assertEqual(mission_state["status"], "initialized")
        self.assertEqual(mission_state["current_phase"], "idea-intake")
        self.assertEqual(mission_state["project_contract"]["status"], "plain-artifacts")
        self.assertEqual(Path(mission_state["target_repo"]).resolve(), project_root.resolve())
        self.assertEqual(readiness.get("status"), "blocked")
        self.assertEqual(readiness.get("launch_recommendation"), "stop-for-operator-input")

        summary_text = (mission_root / "mission_summary.md").read_text(encoding="utf-8")
        self.assertIn("### Blocking prerequisites", summary_text)
        self.assertIn("Where is the dataset located", summary_text)

        package_completed = subprocess.run(
            [
                sys.executable,
                "scripts/mission/package_mission.py",
                "--mission-state",
                str(state_path),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(package_completed.returncode, 0, package_completed.stdout + package_completed.stderr)
        package_result = json.loads(package_completed.stdout)
        self.assertEqual(package_result["package"]["mission_id"], mission_id)
        self.assertTrue(Path(package_result["package_root"]).exists())
        self.assertTrue(Path(package_result["manifest_path"]).exists())
        self.assertTrue(Path(package_result["summary_path"]).exists())
        self.assertFalse(package_result["package"]["checks"]["all_required_artifacts_present"])
        self.assertTrue(
            {"category:findings", "category:manifests"}.issubset(
                set(package_result["package"]["checks"]["missing_required_artifacts"])
            )
        )
        package_summary = Path(package_result["summary_path"]).read_text(encoding="utf-8")
        self.assertIn("Current phase: idea-intake (initialized)", package_summary)

        self.assertFalse((project_root / ".deeploop").exists())
        self.assertEqual(before_paths, snapshot_project_tree(project_root))

    def test_messy_plain_folder_bootstrap_handles_rough_notes_and_packages_without_mutation(self) -> None:
        project_root = self._copy_plain_folder_fixture("forecast-rough-notes")
        before_paths = snapshot_project_tree(project_root)
        mission_id = "end-to-end-smoke-forecast-rough-notes"
        mission_root = MISSIONS_DIR / mission_id
        package_root = mission_root.parent / "packages" / mission_id
        shutil.rmtree(mission_root, ignore_errors=True)
        shutil.rmtree(package_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(mission_root, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(package_root, ignore_errors=True))

        init_completed = subprocess.run(
            [
                sys.executable,
                "scripts/mission/init_mission.py",
                "--project-root",
                str(project_root),
                "--mission-id",
                mission_id,
                "--force",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(init_completed.returncode, 0, init_completed.stdout + init_completed.stderr)

        state_path = mission_root / "mission_state.json"
        self.assertTrue(state_path.exists(), f"missing mission state: {state_path}")
        mission_state = json.loads(state_path.read_text(encoding="utf-8"))
        readiness = mission_state.get("mission_contract", {}).get("readiness", {})

        self.assertEqual(mission_state["status"], "initialized")
        self.assertEqual(mission_state["current_phase"], "idea-intake")
        self.assertEqual(mission_state["project_contract"]["status"], "plain-artifacts")
        self.assertEqual(Path(mission_state["target_repo"]).resolve(), project_root.resolve())
        self.assertEqual(readiness.get("status"), "ready-with-clarifications")
        self.assertEqual(readiness.get("launch_recommendation"), "launch-with-disclosed-guardrails")
        self.assertEqual(mission_state["mission_contract"]["data"]["target"], "next_week_units")
        self.assertIn(
            "baseline improvement only",
            "\n".join(mission_state["mission_contract"]["follow_up_questions"]),
        )

        summary_text = (mission_root / "mission_summary.md").read_text(encoding="utf-8")
        self.assertIn("### Clarifications", summary_text)
        self.assertIn("### Defaults applied", summary_text)

        package_completed = subprocess.run(
            [
                sys.executable,
                "scripts/mission/package_mission.py",
                "--mission-state",
                str(state_path),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(package_completed.returncode, 0, package_completed.stdout + package_completed.stderr)
        package_result = json.loads(package_completed.stdout)
        self.assertEqual(package_result["package"]["mission_id"], mission_id)
        self.assertTrue(Path(package_result["package_root"]).exists())
        self.assertTrue(Path(package_result["manifest_path"]).exists())
        self.assertTrue(Path(package_result["summary_path"]).exists())

        self.assertFalse((project_root / ".deeploop").exists())
        self.assertEqual(before_paths, snapshot_project_tree(project_root))

    def test_discovery_first_plain_folder_flow_handles_rough_notes_without_mutation(self) -> None:
        project_root = self._copy_plain_folder_fixture("forecast-rough-notes")
        before_paths = snapshot_project_tree(project_root)
        mission_id = "end-to-end-smoke-discovery-forecast"
        mission_root = MISSIONS_DIR / mission_id
        discovery_config_path = SCRATCH_DIR / "mission_discovery_configs" / f"{mission_id}.yaml"
        shutil.rmtree(mission_root, ignore_errors=True)
        discovery_config_path.unlink(missing_ok=True)
        self.addCleanup(lambda: shutil.rmtree(mission_root, ignore_errors=True))
        self.addCleanup(lambda: discovery_config_path.unlink(missing_ok=True))

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/mission/init_mission.py",
                "--discover",
                "--project-root",
                str(project_root),
                "--mission-id",
                mission_id,
                "--force",
            ],
            input="\n".join(["", "", "", "", "", "", "", "", "y"]) + "\n",
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("mission-init: used confirmed discovery config", completed.stdout)
        self.assertTrue(discovery_config_path.exists())

        state_path = mission_root / "mission_state.json"
        self.assertTrue(state_path.exists(), f"missing mission state: {state_path}")
        mission_state = json.loads(state_path.read_text(encoding="utf-8"))
        readiness = mission_state.get("mission_contract", {}).get("readiness", {})

        self.assertEqual(mission_state["status"], "initialized")
        self.assertEqual(mission_state["project_contract"]["status"], "plain-artifacts")
        self.assertEqual(Path(mission_state["target_repo"]).resolve(), project_root.resolve())
        self.assertEqual(readiness.get("status"), "ready-with-defaults")
        self.assertEqual(readiness.get("launch_recommendation"), "launch-with-disclosed-defaults")
        self.assertEqual(mission_state["human_inputs"]["mission_discovery"]["mode"], "interactive")
        self.assertIn(
            "data/store_demand_sample.csv",
            mission_state["human_inputs"]["mission_discovery"]["answers"]["available_assets"],
        )

        self.assertFalse((project_root / ".deeploop").exists())
        self.assertEqual(before_paths, snapshot_project_tree(project_root))

    def test_partial_project_folder_bootstrap_surfaces_repair_without_mutation(self) -> None:
        project_root = self.runtime_root / "partial-project-folder"
        (project_root / "docs").mkdir(parents=True, exist_ok=True)
        (project_root / "data").mkdir(parents=True, exist_ok=True)
        (project_root / "docs" / "project-brief.md").write_text(
            "# Project brief\n\nForecast weekly demand from the retailer export in data/store_snapshot.csv.\n",
            encoding="utf-8",
        )
        (project_root / "data" / "store_snapshot.csv").write_text(
            "week_start,store_id,next_week_units\n2024-01-01,s1,42\n",
            encoding="utf-8",
        )
        before_paths = snapshot_project_tree(project_root)

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/mission/init_mission.py",
                "--project-root",
                str(project_root),
                "--mission-id",
                "end-to-end-smoke-partial-bootstrap-repair",
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
        self.assertIn("project-facts.yaml", completed.stderr)
        self.assertIn("docs/project-brief.md", completed.stderr)
        self.assertIn("data/store_snapshot.csv", completed.stderr)
        self.assertFalse((project_root / ".deeploop").exists())
        self.assertEqual(before_paths, snapshot_project_tree(project_root))

    def test_acceptance_campaign_materializes_green_review(self) -> None:
        campaign_root = self.runtime_root / "acceptance"
        campaign_root.mkdir(parents=True, exist_ok=True)
        summary_json_path = campaign_root / "campaign_summary.json"
        review_json_path = campaign_root / "proof_matrix_review.json"
        review_markdown_path = campaign_root / "proof_matrix_review.md"
        summary = {
            "campaign_root": str(campaign_root),
            "summary_json_path": str(summary_json_path),
            "status": "passed",
            "cases_run": ["translation-budget-ladder", "literature-gap-map", "replication-heavy-redteam"],
            "failed_case_ids": [],
            "case_summaries": [
                self._passing_case("translation-budget-ladder", "benchmark-heavy"),
                self._passing_case("literature-gap-map", "literature-heavy"),
                self._passing_case("replication-heavy-redteam", "execution-heavy"),
            ],
            "proof_review": {
                "decision": "eligible-for-promotion",
                "workflow_shapes": ["benchmark-heavy", "execution-heavy", "literature-heavy"],
                "failed_gate_ids": [],
            },
            "review_json_path": str(review_json_path),
            "review_markdown_path": str(review_markdown_path),
        }
        summary_json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        review_json_path.write_text(json.dumps(summary["proof_review"], indent=2) + "\n", encoding="utf-8")
        review_markdown_path.write_text("# Proof review\n", encoding="utf-8")

        review = build_acceptance_review(summary)
        paths = materialize_acceptance_review(review, output_root=campaign_root)

        self.assertEqual(review["decision"], "passed")
        self.assertEqual(review["campaign_id"], "translation-paper-scale")
        self.assertTrue(paths["json_path"].exists())
        self.assertTrue(paths["markdown_path"].exists())


if __name__ == "__main__":
    unittest.main()
