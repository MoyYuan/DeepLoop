"""Mission script to run fresh-context redteam analysis.

Executes red-team evaluation on mission findings, challenging the primary
interpretation with fresh-context readings, alternative explanations,
falsification checks, and destructive sanity tests.

Produces durable JSON/MD artifacts and integrates findings into the mission ledger.
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

from deeploop.fresh_context_redteam import evaluate_fresh_context_redteam


def run_fresh_context_redteam_for_mission(
    artifact_name: str,
    mission_state_path: Path | str | None = None,
    contract_path: Path | str | None = None,
    verbose: bool = False,
) -> dict:
    """
    Run fresh-context redteam analysis on a mission artifact.

    Args:
        artifact_name: Name of the artifact to analyze (e.g., "translation-full-baseline")
        mission_state_path: Path to mission_state.json
        contract_path: Path to fresh-context-redteam.yaml contract
        verbose: Enable verbose output

    Returns:
        Dictionary with analysis results
    """
    if contract_path is None:
        contract_path = (
            Path(__file__).parent.parent.parent
            / "configs"
            / "autonomy"
            / "fresh-context-redteam.yaml"
        )

    result = evaluate_fresh_context_redteam(
        artifact_name=artifact_name,
        mission_state_path=Path(mission_state_path) if mission_state_path else None,
        contract_path=Path(contract_path),
    )

    if verbose:
        print(f"✓ Fresh-context redteam analysis complete for {artifact_name}")
        print(f"  Report JSON: {result.get('report_json_path')}")
        print(f"  Report MD: {result.get('report_markdown_path')}")
        print(f"  Challenges raised: {result.get('challenges_raised', 0)}")

    return result


def run_fresh_context_redteam_for_translation(
    mission_state_path: Path | str | None = None,
    verbose: bool = True,
) -> dict:
    """Run fresh-context redteam on the translation plain-folder mission baseline."""
    return run_fresh_context_redteam_for_mission(
        artifact_name="translation-full-baseline",
        mission_state_path=mission_state_path,
        verbose=verbose,
    )


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run fresh-context redteam analysis on mission artifacts"
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
        help="Path to fresh-context-redteam.yaml contract",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    result = run_fresh_context_redteam_for_mission(
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
