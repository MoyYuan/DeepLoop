from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.mission.mission_monitor import build_mission_snapshot, render_mission_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backend renderer for the DeepLoop autopilot monitor surface.",
        epilog="For normal operator monitoring, prefer manage_mission.py status or manage_mission.py logs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--mission-state", required=True, help="Path to mission_state.json.")
    parser.add_argument("--launch-metadata", help="Optional detached-launch metadata JSON.")
    parser.add_argument("--log-tail", type=int, default=20, help="Number of detached-process log lines to show.")
    parser.add_argument("--ledger-tail", type=int, default=8, help="Number of recent ledger entries to show.")
    parser.add_argument("--json", action="store_true", help="Emit the structured monitor snapshot as JSON.")
    args = parser.parse_args()

    snapshot = build_mission_snapshot(
        Path(args.mission_state).expanduser().resolve(),
        launch_metadata_path=Path(args.launch_metadata).expanduser().resolve() if args.launch_metadata else None,
        log_tail_lines=args.log_tail,
        ledger_tail=args.ledger_tail,
    )
    if args.json:
        print(json.dumps(snapshot, indent=2))
    else:
        print(render_mission_snapshot(snapshot), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
