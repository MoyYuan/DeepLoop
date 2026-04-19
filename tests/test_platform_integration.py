from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from deeploop.artifacts.artifact_packager import package_mission_artifacts
from deeploop.core.paths import WORKSPACE_ROOT
from deeploop.mission.mission_scheduler import load_mission_scheduler_config, run_mission_scheduler
from deeploop.platform.contracts import materialize_platform_expansion_bundle, sync_platform_expansion_bundle
from runtime_artifact_helpers import fresh_test_root, write_json, write_jsonl, write_yaml

TEST_WORK_ROOT = REPO_ROOT / "tests" / "_runtime_artifacts" / "platform_integration"
TEST_PACKAGE_ROOT = WORKSPACE_ROOT / "runs" / "deeploop-tests" / "platform-integration-packages"
TEST_RUN_ROOT = WORKSPACE_ROOT / "runs" / "platform-integration-target"


def _fresh_test_root(name: str) -> Path:
    return fresh_test_root(TEST_WORK_ROOT, name)


class PlatformIntegrationTests(unittest.TestCase):
    def tearDown(self) -> None:
        shutil.rmtree(TEST_WORK_ROOT, ignore_errors=True)
        shutil.rmtree(TEST_PACKAGE_ROOT, ignore_errors=True)
        shutil.rmtree(TEST_RUN_ROOT, ignore_errors=True)

    def test_scheduler_memory_and_release_surfaces_sync_as_one_system(self) -> None:
        test_root = _fresh_test_root("scheduler_memory_release")
        mission_root = test_root / "mission"
        mission_state_path = mission_root / "mission_state.json"
        target_repo = WORKSPACE_ROOT / "repos" / "platform-integration-target"
        mission_id = "platform-integration-mission"

        mission_memory_path = mission_root / "mission_memory.json"
        experiment_ledger_path = mission_root / "mission_experiments.jsonl"
        research_memory_root = mission_root / "research-memory"
        research_memory_events_path = research_memory_root / "research_memory_entries.jsonl"
        research_memory_index_path = research_memory_root / "research_memory_index.json"
        findings_path = mission_root / "findings" / "stability-note.md"
        ledger_path = mission_root / "ledger.jsonl"
        findings_path.parent.mkdir(parents=True, exist_ok=True)
        findings_path.write_text("# Stability note\n\n- Crash loop fixed.\n", encoding="utf-8")
        write_json(
            mission_memory_path,
            {
                "updated_at": "2026-01-01T00:00:00+00:00",
                "retrieved_research_context": {
                    "query": "crash loop patch",
                    "matches": [
                        {
                            "entity_type": "critique",
                            "entity_id": "patch-finding",
                            "mission_id": "prior-mission",
                            "status": "recorded",
                            "summary": "Patch fixed the crash loop.",
                            "score": 0.91,
                            "promotion_status": "promoted",
                            "source_paths": [str(findings_path)],
                            "updated_at": "2026-01-01T00:00:00+00:00",
                        }
                    ],
                },
            },
        )
        write_jsonl(experiment_ledger_path, [])
        write_jsonl(
            ledger_path,
            [
                {
                    "kind": "finding",
                    "mission_id": mission_id,
                    "summary": "Recorded crash-loop fix.",
                    "status": "completed",
                    "related_paths": [str(findings_path)],
                }
            ],
        )
        write_json(
            research_memory_index_path,
            {
                "schema_version": 1,
                "updated_at": "2026-01-01T00:00:00+00:00",
                "active_entries": [],
                "archived_entries": [],
            },
        )
        write_jsonl(research_memory_events_path, [])

        mission_state = {
            "mission_id": mission_id,
            "title": "Platform integration mission",
            "objective": "Exercise integrated platform outputs.",
            "current_phase": "execution",
            "next_phase": "critique",
            "status": "running",
            "target_repo": str(target_repo),
            "autonomy_status": {"state": "initialized", "reason": "integration test"},
            "next_actions": {"summary": "Package the integrated mission.", "actions": []},
            "outer_loop": {
                "mission_memory_path": str(mission_memory_path.resolve()),
                "experiment_ledger_path": str(experiment_ledger_path.resolve()),
                "research_memory_events_path": str(research_memory_events_path.resolve()),
                "research_memory_index_path": str(research_memory_index_path.resolve()),
            },
        }
        write_json(mission_state_path, mission_state)
        mission_state["platform_expansion"] = materialize_platform_expansion_bundle(
            mission_id=mission_id,
            mission_root=mission_root,
            mission_state_path=mission_state_path,
            target_repo=target_repo,
        )
        write_json(mission_state_path, mission_state)

        run_root = TEST_RUN_ROOT / "baseline"
        critique_json = run_root / "self_correction_report.json"
        critique_md = run_root / "self_correction_report.md"
        metrics_path = run_root / "metrics.json"
        write_json(metrics_path, {"accuracy": 0.73})
        write_json(
            critique_json,
            {
                "mission_id": mission_id,
                "promotion_guidance": {
                    "max_allowed_state": "paper-candidate",
                    "reasons": ["Need human approval before release promotion."],
                },
                "warnings": [{"message": "Release requires human approval."}],
                "artifacts": {
                    "report_markdown": str(critique_md),
                },
            },
        )
        critique_md.write_text("# Self correction\n\n- Human approval still required.\n", encoding="utf-8")
        write_json(
            run_root / "run_manifest.json",
            {
                "mission_id": mission_id,
                "loop_id": "baseline-loop",
                "claim_state": "paper-candidate",
                "run": {"status": "completed"},
                "metrics": {"accuracy": 0.73},
                "artifacts": {"output_dir": str(run_root)},
            },
        )

        scheduler_config_path = test_root / "scheduler.yaml"
        write_yaml(
            scheduler_config_path,
            {
                "scheduler_id": "platform-scheduler",
                "scheduler_root": str(test_root / "scheduler"),
                "policy": {
                    "budget": {
                        "max_total_iterations": 1,
                        "slice_iterations": 1,
                        "default_mission_budget_iterations": 2,
                    }
                },
                "missions": [{"mission_state": str(mission_state_path), "priority": 80}],
            },
        )

        def runner(state_path: Path, *, max_iterations: int) -> dict[str, object]:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["mission_runtime"] = {"iterations_completed": max_iterations}
            write_json(state_path, state)
            return {"status": "max-iterations", "iterations_completed": max_iterations, "terminal_reason": None}

        scheduler_result = run_mission_scheduler(load_mission_scheduler_config(scheduler_config_path), runner=runner)
        self.assertEqual(scheduler_result["status"], "budget-exhausted")

        package_result = package_mission_artifacts(mission_state_path, output_root=TEST_PACKAGE_ROOT)
        self.assertTrue(package_result["manifest_path"].exists())
        sync_platform_expansion_bundle(
            mission_state_path,
            mission_state=json.loads(mission_state_path.read_text(encoding="utf-8")),
            package_payload={
                "package_root": str(package_result["package_root"]),
                "manifest_path": str(package_result["manifest_path"]),
                "summary_path": str(package_result["summary_path"]),
                "release_review_path": str(package_result["release_review_path"]),
                "release_review_markdown_path": str(package_result["release_review_markdown_path"]),
            },
            package_manifest_path=package_result["manifest_path"],
            release_review_path=package_result["release_review_path"],
        )

        updated_state = json.loads(mission_state_path.read_text(encoding="utf-8"))
        surfaces = updated_state["platform_expansion"]["surfaces"]
        self.assertEqual(surfaces["scheduler"]["status"], "budget-exhausted")
        self.assertEqual(surfaces["indexed_memory"]["status"], "active")
        self.assertEqual(surfaces["release_automation"]["status"], "blocked")

        scheduler_handoff = json.loads(Path(surfaces["scheduler"]["handoff_path"]).read_text(encoding="utf-8"))
        scheduler_queue = json.loads(
            Path(scheduler_handoff["integration_state"]["mission_queue_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(scheduler_queue["scheduler_id"], "platform-scheduler")
        self.assertEqual(scheduler_queue["scheduler_status"], "budget-exhausted")

        indexed_memory_handoff = json.loads(Path(surfaces["indexed_memory"]["handoff_path"]).read_text(encoding="utf-8"))
        source_catalog = json.loads(
            Path(indexed_memory_handoff["integration_state"]["source_catalog_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(source_catalog["retrieved_research_context"]["match_count"], 1)
        self.assertEqual(source_catalog["research_memory_index_path"], str(research_memory_index_path.resolve()))

        release_handoff = json.loads(Path(surfaces["release_automation"]["handoff_path"]).read_text(encoding="utf-8"))
        release_request = json.loads(
            Path(release_handoff["integration_state"]["release_candidate_request_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(release_request["decision"], "blocked")
        self.assertEqual(release_request["package_manifest_path"], str(package_result["manifest_path"]))
        self.assertEqual(release_request["review_json_path"], str(package_result["release_review_path"]))
        release_notes = Path(release_handoff["integration_state"]["release_notes_draft_path"]).read_text(encoding="utf-8")
        self.assertIn("scheduler_status", release_notes)
        self.assertIn("indexed_memory_status", release_notes)


if __name__ == "__main__":
    unittest.main()
