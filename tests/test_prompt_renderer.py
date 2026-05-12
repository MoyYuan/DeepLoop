from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime._prompt_renderer import render_prompt


class PromptRendererTests(unittest.TestCase):
    def test_render_prompt_prefers_direct_file_writes_for_artifacts(self) -> None:
        prompt = render_prompt(
            mission_state={
                "mission_id": "demo-mission",
                "current_phase": "idea-intake",
                "next_phase": "literature-review",
                "objective": "Demo objective",
                "autonomy_status": {"state": "initialized", "reason": "demo"},
                "outer_loop": {
                    "execution_mode": "sandboxed-yolo",
                    "permissions_profile": "sandboxed",
                    "intervention_profile": "outcome-review",
                    "external_publish": "human-review-required",
                    "hard_gate_profile": "minimal",
                },
            },
            action={
                "role": "planner",
                "task": "Write a note and return a result payload.",
                "kind": "runtime-validation",
                "phase": "idea-intake",
                "branch_id": None,
                "decision_id": None,
                "action_id": "demo-action",
                "loop_action_id": "demo-loop-action",
                "notes": [],
                "artifacts": [],
            },
            sandbox={
                "sandbox_root": "/tmp/demo-sandbox",
                "inputs_dir": "/tmp/demo-sandbox/inputs",
                "outputs_dir": "/tmp/demo-sandbox/outputs",
                "rule_sources": ["/tmp/rules.md"],
            },
            recent_ledger=[],
            recent_memory=[],
            branch_record=None,
            decision_record=None,
            result_json_path=Path("/tmp/demo-sandbox/agent_result.json"),
            iteration_number=1,
            max_iterations=1,
        )

        self.assertIn("Prefer direct file create/edit tools", prompt)
        self.assertIn("do not leave simple artifact creation to long-running shell commands", prompt)


if __name__ == "__main__":
    unittest.main()
