from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.statistical_rigor import DEFAULT_CONTRACT_PATH, evaluate_statistical_rigor


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, help="Run-output directory or manifest path to evaluate.")
    parser.add_argument("--mission-state")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT_PATH))
    parser.add_argument("--output-root")
    parser.add_argument("--artifact-name")
    args = parser.parse_args()

    result = evaluate_statistical_rigor(
        Path(args.path).expanduser().resolve(),
        contract_path=Path(args.contract).expanduser().resolve(),
        mission_state_path=Path(args.mission_state).expanduser().resolve() if args.mission_state else None,
        output_root=Path(args.output_root).expanduser().resolve() if args.output_root else None,
        artifact_name=args.artifact_name,
    )
    print(f"statistical-rigor: guidance {result['recommended_state']}")
    print(f"statistical-rigor: effective_count {result['effective_count']}")
    print(f"statistical-rigor: warnings {result['warning_count']}")
    print(f"statistical-rigor: wrote {result['report_json_path']}")
    print(f"statistical-rigor: wrote {result['report_markdown_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
