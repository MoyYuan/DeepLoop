"""
Mission-phase statistical rigor runner.

Evaluates statistical rigor for mission-linked runs and writes results
to the mission ledger along with JSON and markdown reports.
"""

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
    """
    Run statistical rigor evaluation for a mission-linked target.
    
    Expects:
      --mission-state: path to mission_state.json
      --path: path to run output, manifest, or study directory
      --artifact-name (optional): name for output artifacts
      --contract (optional): path to contract YAML
    """
    parser = argparse.ArgumentParser(
        description="Evaluate statistical rigor for a mission-linked run or study."
    )
    parser.add_argument(
        "--mission-state",
        required=True,
        help="Path to mission_state.json for ledger linking.",
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Path to run-output directory, manifest, or study.",
    )
    parser.add_argument(
        "--artifact-name",
        help="Optional name for output artifacts (defaults to derived name).",
    )
    parser.add_argument(
        "--contract",
        default=str(DEFAULT_CONTRACT_PATH),
        help="Path to statistical-rigor contract YAML.",
    )
    args = parser.parse_args()

    try:
        result = evaluate_statistical_rigor(
            Path(args.path).expanduser().resolve(),
            contract_path=Path(args.contract).expanduser().resolve(),
            mission_state_path=Path(args.mission_state).expanduser().resolve(),
            artifact_name=args.artifact_name,
        )
        print(f"rigor-mission: recommended_state {result['recommended_state']}")
        print(f"rigor-mission: effective_count {result['effective_count']}")
        print(f"rigor-mission: warnings {result['warning_count']}")
        print(f"rigor-mission: json_report {result['report_json_path']}")
        print(f"rigor-mission: md_report {result['report_markdown_path']}")
        if result['co_located_json_path']:
            print(f"rigor-mission: co_located_json {result['co_located_json_path']}")
        if result['co_located_markdown_path']:
            print(f"rigor-mission: co_located_md {result['co_located_markdown_path']}")
        return 0
    except Exception as e:
        print(f"rigor-mission: ERROR {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
