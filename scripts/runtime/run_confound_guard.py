from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.confound_guard import DEFAULT_CONTRACT_PATH, evaluate_confound_guard


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--mission-state")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT_PATH))
    parser.add_argument("--repo-root")
    parser.add_argument("--artifact-name")
    args = parser.parse_args()

    result = evaluate_confound_guard(
        Path(args.config).expanduser().resolve(),
        contract_path=Path(args.contract).expanduser().resolve(),
        mission_state_path=Path(args.mission_state).expanduser().resolve() if args.mission_state else None,
        repo_root=Path(args.repo_root).expanduser().resolve() if args.repo_root else None,
        artifact_name=args.artifact_name,
    )
    print(f"confound-guard: verdict {result['verdict']}")
    print(f"confound-guard: wrote {result['report_json_path']}")
    print(f"confound-guard: wrote {result['report_markdown_path']}")
    return 2 if result["verdict"] == "block" else 0


if __name__ == "__main__":
    raise SystemExit(main())
