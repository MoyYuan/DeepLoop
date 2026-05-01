from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.mission.mission_discovery import compile_discovery_config


class MissionDiscoveryTests(unittest.TestCase):
    def test_compile_discovery_config_without_project_root_creates_plain_artifact_context(self) -> None:
        mission_id = "interactive-discovery-unit-test"
        config = compile_discovery_config(
            mission_idea="Explore promising residual-vs-direct forecasting directions for the dataset.",
            discovery_answers={
                "available_assets": "One CSV dataset and a baseline notebook.",
                "success_criteria": "Beat the baseline MAE without leakage on a held-out split.",
                "risks_and_leakage": "Watch for temporal leakage from future-derived features.",
                "compute_budget": "Keep the plan within 6 GPU-hours.",
                "deliverables": "Produce an executable mission, evaluation plan, and final memo.",
                "novelty_and_tradeoffs": "Prefer paper-grade rigor over risky novelty.",
                "missing_information": "Need confirmation on the final prediction horizon.",
            },
            mission_id=mission_id,
        )

        discovery_root = Path(config["mission"]["target_repo"])
        self.addCleanup(lambda: shutil.rmtree(discovery_root, ignore_errors=True))

        self.assertEqual(config["mission"]["id"], mission_id)
        self.assertEqual(config["mission"]["human_inputs"]["mission_discovery"]["mode"], "interactive")
        self.assertEqual(
            config["mission"]["human_inputs"]["mission_discovery"]["answers"]["mission_idea"],
            "Explore promising residual-vs-direct forecasting directions for the dataset.",
        )
        self.assertIn("temporal leakage", " ".join(config["mission"]["constraints"]))
        self.assertTrue((discovery_root / "project-facts.yaml").exists())
        self.assertTrue((discovery_root / "docs" / "project-brief.md").exists())

    def test_init_mission_script_supports_interactive_discovery_before_kickoff(self) -> None:
        mission_id = "interactive-discovery-cli-test"
        mission_root = Path.home() / "workspaces" / "runs" / "deeploop" / "missions" / mission_id
        discovery_root = Path.home() / "workspaces" / "scratch" / "deeploop" / "mission_discovery_projects" / mission_id
        discovery_config_path = Path.home() / "workspaces" / "scratch" / "deeploop" / "mission_discovery_configs" / f"{mission_id}.yaml"
        shutil.rmtree(mission_root, ignore_errors=True)
        shutil.rmtree(discovery_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(mission_root, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(discovery_root, ignore_errors=True))
        self.addCleanup(lambda: discovery_config_path.unlink(missing_ok=True))

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/mission/init_mission.py",
                "--discover",
                "--mission-id",
                mission_id,
                "--mission-idea",
                "Figure out a leakage-safe research plan for a tabular forecasting dataset.",
                "--force",
            ],
            input="\n".join(
                [
                    "A CSV dataset, a README, and a simple baseline.",
                    "Improve validation MAE over baseline and document slice behavior.",
                    "Guard against temporal leakage and entity overlap.",
                    "Stay within 8 GPU-hours and at most 2 concurrent jobs.",
                    "Return a compiled mission, execution checklist, and final report.",
                    "Aim for a solid paper-grade plan before chasing ambitious novelty.",
                    "Need the exact publication target and benchmark convention.",
                    "y",
                ]
            )
            + "\n",
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("mission-discovery: starting interactive mission formulation", completed.stdout)
        self.assertIn("mission-discovery: current missing checklist", completed.stdout)
        self.assertIn("mission-discovery: compiled mission summary", completed.stdout)
        self.assertIn("Proceed with mission kickoff?", completed.stdout)
        self.assertIn("mission-init: used confirmed discovery config", completed.stdout)
        self.assertTrue(mission_root.joinpath("mission_state.json").exists())
        self.assertTrue(discovery_config_path.exists())

        mission_state = json.loads(mission_root.joinpath("mission_state.json").read_text(encoding="utf-8"))
        self.assertEqual(mission_state["mission_id"], mission_id)
        self.assertIn("temporal leakage", " ".join(mission_state["constraints"]))
        self.assertEqual(mission_state["human_inputs"]["mission_discovery"]["mode"], "interactive")
        self.assertEqual(
            mission_state["human_inputs"]["mission_discovery"]["answers"]["mission_idea"],
            "Figure out a leakage-safe research plan for a tabular forecasting dataset.",
        )
        self.assertTrue(Path(mission_state["target_repo"]).joinpath("project-facts.yaml").exists())


if __name__ == "__main__":
    unittest.main()
