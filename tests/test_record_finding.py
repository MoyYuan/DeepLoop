from __future__ import annotations

import json
import shutil
import subprocess
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

from deeploop.autonomy.mission_autonomy import build_outer_loop_contract
from deeploop.research.indexed_memory import load_research_memory_index
from runtime_artifact_helpers import fresh_test_root

TEST_WORK_ROOT = REPO_ROOT / "tests" / "_runtime_artifacts" / "record_finding"


def _fresh_test_root(name: str) -> Path:
    return fresh_test_root(TEST_WORK_ROOT, name)


class RecordFindingTests(unittest.TestCase):
    def test_record_finding_updates_mission_memory_and_experiment_ledger(self) -> None:
        test_root = _fresh_test_root("updates_memory_and_ledger")
        mission_root = test_root / "mission"
        mission_root.mkdir(parents=True, exist_ok=True)
        mission_state_path = mission_root / "mission_state.json"
        outer_loop = build_outer_loop_contract(mission_root, mode="sandboxed-yolo")
        research_memory_root = test_root / "research-memory"
        outer_loop["research_memory_root"] = str(research_memory_root.resolve())
        outer_loop["research_memory_events_path"] = str((research_memory_root / "research_memory_entries.jsonl").resolve())
        outer_loop["research_memory_index_path"] = str((research_memory_root / "research_memory_index.json").resolve())
        mission_state_path.write_text(
            json.dumps(
                {
                    "mission_id": "mission-record-finding",
                    "mode": "sandboxed-yolo",
                    "title": "Record finding test",
                    "summary": "Exercise finding persistence.",
                    "objective": "Keep promoted findings durable.",
                    "current_phase": "final-report",
                    "next_phase": "final-report",
                    "status": "running",
                    "target_repo": str(REPO_ROOT),
                    "roles": ["report-synthesizer"],
                    "outer_loop": outer_loop,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/mission/record_finding.py",
                "--mission-state",
                str(mission_state_path),
                "--summary",
                "Adapter patch reduced crash rate while preserving accuracy.",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

        experiment_entries = [
            json.loads(line)
            for line in (mission_root / "mission_experiments.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(experiment_entries), 1)
        self.assertEqual(experiment_entries[0]["kind"], "promoted-finding")
        mission_memory = json.loads((mission_root / "mission_memory.json").read_text(encoding="utf-8"))
        self.assertEqual(mission_memory["counts"]["promoted_findings"], 1)
        self.assertEqual(
            mission_memory["promoted_findings"][0]["summary"],
            "Adapter patch reduced crash rate while preserving accuracy.",
        )
        research_memory = load_research_memory_index(contract=outer_loop)
        promoted = [entry for entry in research_memory["active_entries"] if entry["entity_type"] == "critique"]
        self.assertEqual(len(promoted), 1)
        self.assertEqual(promoted[0]["summary"], "Adapter patch reduced crash rate while preserving accuracy.")


if __name__ == "__main__":
    unittest.main()
