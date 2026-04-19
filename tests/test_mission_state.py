from __future__ import annotations

import sys
import unittest
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from deeploop.mission.mission_state import (
    MISSION_STATE_SCHEMA_VERSION,
    load_mission_state,
    write_mission_state,
)
from deeploop.core.structured_io import load_json_object
from runtime_artifact_helpers import fresh_test_root

TEST_WORK_ROOT = REPO_ROOT / "tests" / "_runtime_artifacts" / "mission_state"


def _fresh_test_root(name: str) -> Path:
    return fresh_test_root(TEST_WORK_ROOT, name)


class MissionStateTests(unittest.TestCase):
    def test_load_mission_state_migrates_legacy_payload(self) -> None:
        test_root = _fresh_test_root("load_migrates_legacy_payload")
        path = test_root / "mission_state.json"
        path.write_text(
            '{\n'
            '  "mission_id": "demo",\n'
            '  "mode": "sandboxed-yolo",\n'
            '  "current_phase": "execution",\n'
            '  "outer_loop": {}\n'
            '}\n',
            encoding="utf-8",
        )

        state = load_mission_state(path)

        self.assertEqual(state["schema_version"], MISSION_STATE_SCHEMA_VERSION)
        self.assertEqual(state["completed_phases"], [])
        self.assertEqual(state["phase_history"], ["execution"])
        self.assertEqual(state["outer_loop"]["mode"], "sandboxed-yolo")

    def test_write_mission_state_persists_current_schema_version(self) -> None:
        test_root = _fresh_test_root("write_persists_schema_version")
        path = test_root / "mission_state.json"

        write_mission_state(
            path,
            {
                "mission_id": "demo",
                "mode": "sandboxed-yolo",
                "current_phase": "execution",
                "completed_phases": [],
                "phase_history": ["execution"],
            },
        )

        state = load_mission_state(path)
        self.assertEqual(state["schema_version"], MISSION_STATE_SCHEMA_VERSION)

    def test_written_state_validates_against_schema(self) -> None:
        test_root = _fresh_test_root("written_state_validates_against_schema")
        path = test_root / "mission_state.json"
        schema_path = REPO_ROOT / "schemas" / "mission-state.schema.json"

        write_mission_state(
            path,
            {
                "mission_id": "demo",
                "mode": "sandboxed-yolo",
                "title": "Demo mission",
                "summary": "Schema validation test",
                "current_phase": "execution",
                "status": "running",
                "roles": ["execution-operator"],
                "completed_phases": [],
                "phase_history": ["execution"],
                "contract_snapshot": {"schema_version": 1, "path": "/tmp/demo-contract-snapshot.json"},
                "outer_loop": {
                    "mode": "sandboxed-yolo",
                    "contract_snapshot_path": "/tmp/demo-contract-snapshot.json",
                    "decision_log_path": "/tmp/demo-decisions.jsonl",
                    "branch_log_path": "/tmp/demo-branches.jsonl"
                },
            },
        )

        schema = load_json_object(schema_path)
        jsonschema.Draft202012Validator(schema).validate(load_mission_state(path))


if __name__ == "__main__":
    unittest.main()
