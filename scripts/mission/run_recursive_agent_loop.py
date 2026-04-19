from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.recursive_agent_runtime import run_recursive_agent_loop


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded recursive-agent executor used by the mission outer runtime.",
        epilog=(
            "This is a secondary executor surface. Prefer run_mission.py for top-level mission "
            "execution and use this entrypoint for isolated debugging or compatibility flows."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the recursive loop config YAML.",
    )
    args = parser.parse_args()

    result = run_recursive_agent_loop(Path(args.config).resolve())
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, indent=2))
    return 0 if result["status"] in {"completed", "max-iterations"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
