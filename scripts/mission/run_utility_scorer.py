"""
Mission-phase utility scorer runner.

Evaluates utility scores for all experiment branches in a mission
and writes ranked results to JSON/Markdown reports with ledger integration.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.utility_scorer import DEFAULT_CONTRACT_PATH, evaluate_utility_score


def main() -> int:
    """
    Run utility scoring for all branches in a mission.

    Expects:
      --mission-state: path to mission_state.json
      --branches: path to branches directory
      --artifact-name (optional): name for output artifacts
      --contract (optional): path to contract YAML
    """
    parser = argparse.ArgumentParser(
        description="Evaluate utility scores for mission branches."
    )
    parser.add_argument(
        "--mission-state",
        required=True,
        help="Path to mission_state.json for ledger linking.",
    )
    parser.add_argument(
        "--branches",
        required=True,
        help="Path to branches directory.",
    )
    parser.add_argument(
        "--artifact-name",
        help="Optional name for output artifacts.",
    )
    parser.add_argument(
        "--contract",
        default=str(DEFAULT_CONTRACT_PATH),
        help="Path to utility-scorer contract YAML.",
    )
    args = parser.parse_args()

    try:
        result = evaluate_utility_score(
            Path(args.branches).expanduser().resolve(),
            mission_state_path=Path(args.mission_state).expanduser().resolve(),
            contract_path=Path(args.contract).expanduser().resolve(),
            artifact_name=args.artifact_name,
        )
        print(f"utility-scorer: total_branches {result['total_branches']}")
        print(f"utility-scorer: mean_score {result['summary']['mean_score']}")
        print(f"utility-scorer: json_report {result['report_json_path']}")
        print(f"utility-scorer: md_report {result['report_markdown_path']}")
        if result["ranked_branches"]:
            top = result["ranked_branches"][0]
            print(f"utility-scorer: top_recommendation {top.recommendation}")
            print(f"utility-scorer: top_score {top.overall_score}")
        return 0
    except Exception as e:
        print(f"utility-scorer: ERROR {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
