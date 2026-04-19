from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.mission.mission_runtime import run_mission


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backend entrypoint for the canonical DeepLoop autopilot runtime.",
        epilog=(
            "For normal operator workflows, prefer manage_mission.py start/resume. Smaller surfaces "
            "such as run_queue.py and run_recursive_agent_loop.py are bounded helper runtimes under "
            "the same mission controller."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mission-state",
        required=True,
        help="Path to the mission_state.json file to advance.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=12,
        help="Maximum outer-loop decisions to execute before returning max-iterations.",
    )
    parser.add_argument(
        "--runtime-root",
        help="Optional override for the mission_outer_runtime output directory.",
    )
    args = parser.parse_args()

    result = run_mission(
        Path(args.mission_state).expanduser().resolve(),
        max_iterations=args.max_iterations,
        runtime_root=Path(args.runtime_root).expanduser().resolve() if args.runtime_root else None,
    )
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
