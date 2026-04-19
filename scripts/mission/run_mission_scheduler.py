from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.mission.mission_scheduler import (
    load_mission_scheduler_config,
    render_mission_scheduler_summary,
    run_mission_scheduler,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the cooperative DeepLoop multi-mission scheduler.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", required=True, help="Path to the multi-mission scheduler YAML config.")
    parser.add_argument("--json", action="store_true", help="Emit the final scheduler result as JSON.")
    args = parser.parse_args()

    config = load_mission_scheduler_config(Path(args.config))
    result = run_mission_scheduler(config)
    if args.json:
        print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, indent=2))
    else:
        summary = json.loads(Path(result["summary_json_path"]).read_text(encoding="utf-8"))
        print(render_mission_scheduler_summary(summary), end="")
    return 0 if result["status"] in {"completed", "budget-exhausted"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
