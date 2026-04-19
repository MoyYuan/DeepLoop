"""Mission script to run self-correction analysis.

Executes self-correction evaluation on mission artifacts,
classifies failures, recommends recovery actions, and writes durable artifacts.

Integrates with the deterministic self-correction engine to process
mission manifests and emit ledger entries and structured reports.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deeploop.research.self_correction import evaluate_self_correction


def run_self_correction_for_mission(
    artifact_name: str,
    mission_state_path: Path | str | None = None,
    contract_path: Path | str | None = None,
    verbose: bool = False,
) -> dict:
    """
    Run self-correction analysis on a mission artifact set.

    Args:
        artifact_name: Name of the artifact set to analyze
        mission_state_path: Path to mission_state.json
        contract_path: Path to self-correction.yaml contract
        verbose: Enable verbose output

    Returns:
        Dictionary with analysis results
    """
    if contract_path is None:
        contract_path = (
            Path(__file__).parent.parent.parent
            / "configs"
            / "autonomy"
            / "self-correction.yaml"
        )

    result = evaluate_self_correction(
        artifact_name=artifact_name,
        mission_state_path=Path(mission_state_path) if mission_state_path else None,
        contract_path=Path(contract_path),
    )

    if verbose:
        print(f"✓ Self-correction analysis complete for {artifact_name}")
        print(f"  Report JSON: {result.get('report_json_path')}")
        print(f"  Report MD: {result.get('report_markdown_path')}")
        print(f"  Final decision: {result.get('final_decision', {}).get('action', 'unknown')}")

    return result


def run_self_correction_for_translation(
    mission_state_path: Path | str | None = None,
    verbose: bool = True,
) -> dict:
    """Run self-correction on the translation plain-folder mission."""
    return run_self_correction_for_mission(
        artifact_name="translation-full-baseline",
        mission_state_path=mission_state_path,
        verbose=verbose,
    )


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run self-correction analysis on mission artifacts"
    )
    parser.add_argument(
        "--artifact-name",
        type=str,
        required=True,
        help="Name of the artifact set to analyze",
    )
    parser.add_argument(
        "--mission-state",
        type=str,
        help="Path to mission_state.json",
    )
    parser.add_argument(
        "--contract",
        type=str,
        help="Path to self-correction.yaml contract",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    result = run_self_correction_for_mission(
        artifact_name=args.artifact_name,
        mission_state_path=args.mission_state,
        contract_path=args.contract,
        verbose=args.verbose,
    )

    # Output result as JSON
    print(json.dumps(result, indent=2, default=str))

    return 0


if __name__ == "__main__":
    exit(main())
