from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.artifacts.mission_package import build_mission_package
from deeploop.core.paths import RUNS_DIR, SCRATCH_DIR


class MissionPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_root = SCRATCH_DIR / "mission-package-tests"
        self.mission_root = self.fixture_root / "package-test-mission"
        shutil.rmtree(self.fixture_root, ignore_errors=True)
        self.mission_root.mkdir(parents=True, exist_ok=True)
        self.note_path = self.mission_root / "findings" / "note.md"
        self.note_path.parent.mkdir(parents=True, exist_ok=True)
        self.note_path.write_text("# note\n", encoding="utf-8")
        self.ledger_path = self.mission_root / "ledger.jsonl"
        self.ledger_path.write_text(
            json.dumps({"kind": "finding", "mission_id": "package-test-mission", "related_paths": [str(self.note_path)]}) + "\n",
            encoding="utf-8",
        )
        self.substrate_run_root = RUNS_DIR.parent / "translation-pilot" / "package-test-run"
        shutil.rmtree(self.substrate_run_root, ignore_errors=True)
        self.substrate_run_root.mkdir(parents=True, exist_ok=True)
        self.substrate_manifest = self.substrate_run_root / "run_manifest.json"
        self.substrate_manifest.write_text(
            json.dumps({"mission_id": "package-test-mission", "metrics": {}, "artifacts": {"output_dir": str(self.substrate_run_root)}}) + "\n",
            encoding="utf-8",
        )
        self.mission_state_path = self.mission_root / "mission_state.json"
        self.mission_state_path.write_text(
            json.dumps(
                {
                    "mission_id": "package-test-mission",
                    "target_repo": str(REPO_ROOT.parent / "translation-pilot"),
                    "platform_expansion": {
                        "surfaces": {
                            "scheduler": {"status": "planned"},
                            "indexed_memory": {"status": "planned"},
                            "release_automation": {"status": "planned"},
                        }
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.platform_manifest = self.mission_root / "runtime" / "platform" / "platform-expansion.json"
        self.platform_manifest.parent.mkdir(parents=True, exist_ok=True)
        self.platform_manifest.write_text(json.dumps({"mission_id": "package-test-mission"}, indent=2) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.fixture_root, ignore_errors=True)
        shutil.rmtree(self.substrate_run_root, ignore_errors=True)

    def test_build_mission_package_indexes_artifacts(self) -> None:
        result = build_mission_package(self.mission_state_path, package_name="smoke-package")
        artifact_index = json.loads(Path(result["artifact_index_path"]).read_text(encoding="utf-8"))
        indexed_paths = {entry["path"] for entry in artifact_index["artifacts"]}
        self.assertIn(str(self.mission_state_path.resolve()), indexed_paths)
        self.assertIn(str(self.note_path.resolve()), indexed_paths)
        self.assertIn(str(self.substrate_manifest.resolve()), indexed_paths)
        self.assertIn(str(self.platform_manifest.resolve()), indexed_paths)
        self.assertTrue(Path(result["summary_path"]).exists())
        self.assertTrue(Path(result["package_manifest_path"]).exists())


if __name__ == "__main__":
    unittest.main()
