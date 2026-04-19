from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--result-json", required=True)
    args = parser.parse_args()

    result_path = Path(args.result_json)
    outputs_dir = Path(os.environ["DEEPLOOP_SANDBOX_OUTPUTS_DIR"])
    iteration = int(os.environ["DEEPLOOP_AGENT_ITERATION"])
    loop_action_id = os.environ.get("DEEPLOOP_LOOP_ACTION_ID") or None

    if iteration == 1:
        artifact = outputs_dir / "contract-gate.json"
        artifact.write_text('{"status":"failed-preflight"}\n', encoding="utf-8")
        payload = {
            "status": "continue",
            "summary": "Recorded the contract failure and handed the branch to critique.",
            "produced_artifacts": [str(artifact)],
            "continuation": {
                "role": "critic-verifier",
                "task": "Critique the recorded contract failure before any retry.",
                "phase": "critique",
                "kind": "phase-transition",
                "notes": ["Do not rerun execution before critique closes the branch."],
            },
            "action_result": {
                "loop_action_id": loop_action_id,
                "status": "contract-failure-recorded",
                "phase": "execution",
                "kind": "phase-transition",
                "output_paths": [str(artifact)],
                "notes": ["Execution completed its bounded contract check and produced critique-ready evidence."],
            },
            "phase_control": {
                "current_phase": "execution",
                "next_phase": "critique",
                "decision_type": "phase-transition",
                "branch_status": "critique-ready",
                "recovery_status": "not-needed",
                "summary": "Execution must hand off to critique after the contract-failure gate.",
            },
        }
    else:
        artifact = outputs_dir / "critique-note.txt"
        artifact.write_text("critique closed\n", encoding="utf-8")
        payload = {
            "status": "complete",
            "summary": "Critique closed the contract-failure branch without replaying execution.",
            "produced_artifacts": [str(artifact)],
            "action_result": {
                "loop_action_id": loop_action_id,
                "status": "completed",
                "phase": "critique",
                "kind": "phase-transition",
                "output_paths": [str(artifact)],
                "notes": ["Critique consumed the recorded contract-failure evidence."],
            },
            "phase_control": {
                "current_phase": "critique",
                "next_phase": "replication",
                "decision_type": "phase-transition",
                "branch_status": "closed-no-promotion",
                "recovery_status": "not-needed",
                "summary": "Critique closes the branch after the contract-failure evidence review.",
            },
        }

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
