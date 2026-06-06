"""Mission script to run utility-scorer branch ranking.

Produces durable JSON/MD scoring artifacts and integrates findings into the mission ledger.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.utility_scorer import evaluate_utility_score


def run_utility_scorer_for_mission(
    artifact_name: str,
    mission_state_path: Path | str | None = None,
    contract_path: Path | str | None = None,
    verbose: bool = False,
) -> dict:
    contract = Path(contract_path) if contract_path else None
    state_path = Path(mission_state_path) if mission_state_path else None
    return evaluate_utility_score(
        artifact_name=artifact_name,
        mission_state_path=state_path,
        contract_path=contract,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run DeepLoop utility-scorer branch ranking")
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--mission-state-path")
    parser.add_argument("--contract-path")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    result = run_utility_scorer_for_mission(
        artifact_name=args.artifact_name,
        mission_state_path=args.mission_state_path,
        contract_path=args.contract_path,
        verbose=args.verbose,
    )
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for line in result.get("lines", [str(result)]):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
