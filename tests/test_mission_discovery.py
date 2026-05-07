from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import MISSIONS_DIR, SCRATCH_DIR
from deeploop.cli.init_mission import _init_mission
from deeploop.mission.mission_discovery import compile_discovery_config, run_interactive_discovery


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
        mission_root = MISSIONS_DIR / mission_id
        discovery_root = SCRATCH_DIR / "mission_discovery_projects" / mission_id
        discovery_config_path = SCRATCH_DIR / "mission_discovery_configs" / f"{mission_id}.yaml"
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
        self.assertIn("readiness summary", completed.stdout)
        self.assertIn("defaults applied", completed.stdout)
        self.assertIn("Proceed with mission kickoff?", completed.stdout)
        self.assertIn("mission-init: used confirmed discovery config", completed.stdout)
        self.assertIn("mission-init: readiness summary", completed.stdout)
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

    def test_init_mission_script_discovery_cancel_keeps_compiled_config_without_launching(self) -> None:
        mission_id = "interactive-discovery-cli-cancel-test"
        mission_root = MISSIONS_DIR / mission_id
        discovery_root = SCRATCH_DIR / "mission_discovery_projects" / mission_id
        discovery_config_path = SCRATCH_DIR / "mission_discovery_configs" / f"{mission_id}.yaml"
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
                "Plan a cautious benchmark mission from rough notes.",
            ],
            input="\n".join(
                [
                    "Dataset notes and a baseline.",
                    "Improve benchmark score without leakage.",
                    "Avoid train/test contamination.",
                    "2 GPU-hours.",
                    "Compiled mission and memo.",
                    "Prefer rigor.",
                    "Need benchmark approval.",
                    "n",
                ]
            )
            + "\n",
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("kickoff cancelled", completed.stdout)
        self.assertTrue(discovery_config_path.exists())
        self.assertFalse(mission_root.joinpath("mission_state.json").exists())

    def test_init_mission_rejects_invalid_argument_combinations(self) -> None:
        cases = [
            (
                argparse.Namespace(
                    config="mission.yaml",
                    project_root=None,
                    discover=True,
                    mission_idea=None,
                    mission_id=None,
                    force=False,
                ),
                "--discover generates a config interactively",
            ),
            (
                argparse.Namespace(
                    config=None,
                    project_root=None,
                    discover=False,
                    mission_idea=None,
                    mission_id=None,
                    force=False,
                ),
                "supply --config or --project-root, or use --discover",
            ),
            (
                argparse.Namespace(
                    config="mission.yaml",
                    project_root="project",
                    discover=False,
                    mission_idea=None,
                    mission_id=None,
                    force=False,
                ),
                "--config and --project-root cannot be used together",
            ),
            (
                argparse.Namespace(
                    config="mission.yaml",
                    project_root=None,
                    discover=False,
                    mission_idea="rough idea",
                    mission_id=None,
                    force=False,
                ),
                "--mission-idea is only supported with --discover",
            ),
        ]

        for args, expected in cases:
            with self.subTest(args=args):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    result = _init_mission(args)
                self.assertEqual(result, 2)
                self.assertIn(expected, stderr.getvalue())

    def test_run_interactive_discovery_cancels_after_repeated_empty_mission_idea(self) -> None:
        responses = iter(["", "", ""])
        printed: list[str] = []

        result = run_interactive_discovery(
            mission_id="interactive-discovery-empty-idea-test",
            reader=lambda prompt: next(responses),
            printer=printed.append,
        )

        self.assertTrue(result["cancelled"])
        self.assertFalse(result["confirmed"])
        self.assertIsNone(result["config_path"])
        self.assertIn("mission-discovery: no mission idea provided; canceling discovery", printed)

    def test_run_interactive_discovery_respects_explicit_cancel_token(self) -> None:
        printed: list[str] = []

        result = run_interactive_discovery(
            mission_id="interactive-discovery-quit-test",
            reader=lambda prompt: "quit",
            printer=printed.append,
        )

        self.assertTrue(result["cancelled"])
        self.assertFalse(result["confirmed"])
        self.assertIsNone(result["config_path"])
        self.assertEqual(printed, ["mission-discovery: starting interactive mission formulation"])

    def test_run_interactive_discovery_preserves_blank_followup_answers_as_missing(self) -> None:
        responses = iter(
            [
                "A baseline notebook and dataset.",
                "",
                "Watch for leakage.",
                "4 GPU-hours.",
                "Mission memo.",
                "Prefer rigor.",
                "Need benchmark sign-off.",
                "n",
            ]
        )
        printed: list[str] = []

        result = run_interactive_discovery(
            mission_id="interactive-discovery-blank-followup-test",
            mission_idea="Refine a forecasting mission from partial notes.",
            reader=lambda prompt: next(responses),
            printer=printed.append,
        )
        self.addCleanup(lambda: Path(result["config_path"]).unlink(missing_ok=True))
        self.addCleanup(lambda: shutil.rmtree(Path(result["config"]["mission"]["target_repo"]), ignore_errors=True))

        self.assertFalse(result["confirmed"])
        checklist = result["config"]["mission"]["human_inputs"]["mission_discovery"]["checklist"]
        success_criteria = next(item for item in checklist if item["id"] == "success_criteria")
        self.assertEqual(success_criteria["status"], "missing")

    def test_run_interactive_discovery_prefills_answers_from_project_context(self) -> None:
        test_root = REPO_ROOT / "tests" / "_runtime_artifacts" / "mission_discovery" / "project_context"
        shutil.rmtree(test_root, ignore_errors=True)
        repo_root = test_root / "housing-pilot"
        (repo_root / "docs").mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "project-brief.md").write_text(
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
                    "project": {"name": "housing-regression-pilot"},
                    "artifacts": {"docs": ["docs/project-brief.md"]},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        prompts: list[str] = []
        responses = iter(["", "", "", "", "", "", "", "", "n"])
        printed: list[str] = []

        result = run_interactive_discovery(
            mission_id="interactive-discovery-context-test",
            project_root=repo_root,
            reader=lambda prompt: prompts.append(prompt) or next(responses),
            printer=printed.append,
        )

        self.addCleanup(lambda: shutil.rmtree(test_root, ignore_errors=True))
        self.addCleanup(lambda: Path(result["config_path"]).unlink(missing_ok=True))

        self.assertFalse(result["confirmed"])
        self.assertIn("keep detected objective", prompts[0])
        self.assertTrue(any("keep detected" in prompt for prompt in prompts[1:]))
        self.assertEqual(
            result["config"]["mission"]["objective"],
            "Build a regression baseline using /datasets/housing/train.csv to predict sale_price.",
        )
        self.assertEqual(result["config"]["mission_contract"]["data"]["target"], "sale_price")
        self.assertEqual(result["config"]["mission_contract"]["budget"]["compute_budget"], "4 GPU hours")
        self.assertEqual(result["config"]["mission_contract"]["readiness"]["status"], "ready-with-defaults")
        self.assertTrue(any("readiness summary" in line for line in printed))
        self.assertTrue(any("defaults applied" in line for line in printed))


if __name__ == "__main__":
    unittest.main()
