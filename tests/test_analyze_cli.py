from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.cli.analyze import _build_analyze_prompt


class AnalyzePromptTests(unittest.TestCase):
    def test_build_analyze_prompt_says_deeploop_writes_result_file(self) -> None:
        prompt = _build_analyze_prompt(
            mission_state={"mission_id": "demo-mission", "current_phase": "idea-intake", "next_phase": "literature-review"},
            mission_state_path=Path("/tmp/demo/mission_state.json"),
            result_json_path=Path("/tmp/demo/result.json"),
        )

        self.assertIn("DeepLoop will write the returned JSON", prompt)
        self.assertIn("Return the JSON object only.", prompt)
        self.assertNotIn("Write JSON to", prompt)


if __name__ == "__main__":
    unittest.main()
