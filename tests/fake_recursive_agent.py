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

    prompt_path = Path(args.prompt)
    result_path = Path(args.result_json)
    outputs_dir = Path(os.environ["DEEPLOOP_SANDBOX_OUTPUTS_DIR"])
    iteration = int(os.environ["DEEPLOOP_AGENT_ITERATION"])
    role = os.environ["DEEPLOOP_AGENT_ROLE"]
    mission_action_id = os.environ.get("DEEPLOOP_MISSION_ACTION_ID") or None
    loop_action_id = os.environ.get("DEEPLOOP_LOOP_ACTION_ID") or None
    branch_id = os.environ.get("DEEPLOOP_MISSION_BRANCH_ID") or None
    decision_id = os.environ.get("DEEPLOOP_MISSION_DECISION_ID") or None

    if iteration == 1:
        artifact = outputs_dir / "planner-note.txt"
        artifact.write_text("planner note\n", encoding="utf-8")
        payload = {
            "status": "continue",
            "summary": "Planned the next execution step.",
            "produced_artifacts": [str(artifact), str(prompt_path)],
            "findings": [f"{role} identified the first bounded experiment."],
            "continuation": {
                "role": "execution-operator",
                "task": "Run the first experiment from the drafted plan.",
                "artifacts": [str(artifact)],
                "action_id": "execute-first-step",
                "kind": "local-eval",
                "phase": "execution",
                "branch_id": branch_id,
                "decision_id": decision_id,
                "notes": ["Continue on the same execution branch."],
            },
            "action_result": {
                "mission_action_id": mission_action_id,
                "loop_action_id": loop_action_id,
                "status": "completed",
                "phase": "idea-intake",
                "kind": "critique",
                "branch_id": branch_id,
                "decision_id": decision_id,
                "output_paths": [str(artifact)],
                "notes": ["Planner handoff completed."],
            },
            "phase_control": {
                "current_phase": "execution",
                "next_phase": "execution",
                "decision_type": "phase-transition",
                "branch_status": "active",
                "recovery_status": "not-needed",
                "summary": "Remain in execution while handing off the next step.",
            },
            "mission_state_updates": {
                "status": "agent-loop-planning",
                "current_phase": "execution",
            },
        }
    else:
        artifact = outputs_dir / "execution-note.txt"
        artifact.write_text("execution note\n", encoding="utf-8")
        payload = {
            "status": "complete",
            "summary": "Completed the bounded recursive research loop.",
            "produced_artifacts": [str(artifact)],
            "findings": [f"{role} completed the bounded loop."],
            "action_result": {
                "mission_action_id": mission_action_id,
                "loop_action_id": loop_action_id,
                "status": "completed",
                "phase": "execution",
                "kind": "local-eval",
                "branch_id": branch_id,
                "decision_id": decision_id,
                "output_paths": [str(artifact)],
                "notes": ["Execution step completed cleanly."],
            },
            "phase_control": {
                "current_phase": "execution",
                "next_phase": "critique",
                "decision_type": "phase-transition",
                "branch_status": "critique-ready",
                "recovery_status": "recovered",
                "summary": "Promote the branch into critique after execution.",
            },
            "mission_state_updates": {
                "status": "agent-loop-complete",
                "next_phase": "critique",
            },
        }
        print("<DEE PLOOP COMPLETE>")

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
