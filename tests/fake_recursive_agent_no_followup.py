from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--result-json", required=True)
    args = parser.parse_args()

    result_path = Path(args.result_json)
    payload = {
        "status": "continue",
        "summary": "Completed one bounded step but intentionally emitted no next handoff.",
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
