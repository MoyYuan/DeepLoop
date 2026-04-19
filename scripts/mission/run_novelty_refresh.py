"""Mission script to run novelty-refresh analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.novelty_refresh import evaluate_novelty_refresh


def run_novelty_refresh_for_mission(
    mission_id: str,
    artifact_name: str,
    mission_state_path: Path | str | None = None,
    contract_path: Path | str | None = None,
    verbose: bool = False,
) -> dict:
    """Run novelty-refresh analysis on a mission."""
    if contract_path is None:
        contract_path = (
            Path(__file__).parent.parent.parent
            / "configs"
            / "autonomy"
            / "novelty-refresh.yaml"
        )

    result = evaluate_novelty_refresh(
        mission_id=mission_id,
        mission_state_path=Path(mission_state_path) if mission_state_path else None,
        artifact_name=artifact_name,
        contract_path=Path(contract_path),
    )

    if verbose:
        print(f"✓ Novelty-refresh analysis complete for {mission_id}")
        print(f"  Report JSON: {result.get('report_json_path')}")
        print(f"  Report MD: {result.get('report_markdown_path')}")
        print(f"  Novelty score: {result.get('novelty_score')}")

    return result


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run novelty-refresh analysis on mission artifacts"
    )
    parser.add_argument(
        "--mission-id",
        type=str,
        required=True,
        help="Mission id to evaluate",
    )
    parser.add_argument(
        "--artifact-name",
        type=str,
        required=True,
        help="Artifact basename for output files",
    )
    parser.add_argument(
        "--mission-state",
        type=str,
        help="Path to mission_state.json",
    )
    parser.add_argument(
        "--contract",
        type=str,
        help="Path to novelty-refresh.yaml contract",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()
    result = run_novelty_refresh_for_mission(
        mission_id=args.mission_id,
        artifact_name=args.artifact_name,
        mission_state_path=args.mission_state,
        contract_path=args.contract,
        verbose=args.verbose,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
