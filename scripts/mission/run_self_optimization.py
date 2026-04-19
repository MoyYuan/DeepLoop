"""
Mission script to run self-optimization analysis.

Executes self-optimization evaluation on mission artifacts,
generates bounded optimization recommendations, and writes durable artifacts.

Integrates with the deterministic self-optimization engine to process
utility scores, self-correction decisions, statistical rigor reports, and
confound assessments to emit ledger entries and structured recommendations.
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

from deeploop.research.self_optimization import optimize_from_artifacts


def run_self_optimization_for_mission(
    artifact_dir: str | Path,
    mission_id: str,
    mission_state_path: Path | str | None = None,
    contract_path: Path | str | None = None,
    verbose: bool = False,
) -> dict:
    """
    Run self-optimization analysis on a mission artifact set.

    Args:
        artifact_dir: Directory containing mission artifacts
        mission_id: Identifier for the mission
        mission_state_path: Path to mission_state.json
        contract_path: Path to self-optimization.yaml contract
        verbose: Enable verbose output

    Returns:
        Dictionary with analysis results and recommendations
    """
    if contract_path is None:
        contract_path = (
            Path(__file__).parent.parent.parent
            / "configs"
            / "autonomy"
            / "self-optimization.yaml"
        )

    result = optimize_from_artifacts(
        artifact_dir=Path(artifact_dir),
        mission_id=mission_id,
        contract_path=Path(contract_path),
        mission_state_path=Path(mission_state_path) if mission_state_path else None,
    )

    if verbose:
        print(f"✓ Self-optimization analysis complete for {mission_id}")
        print(f"  Report JSON: {result.get('report_json_path')}")
        print(f"  Recommendations YAML: {result.get('recommendations_yaml_path')}")
        
        report = result.get("report", {})
        recs = report.get("recommendations", [])
        print(f"  Generated {len(recs)} recommendations:")
        for rec in recs:
            print(f"    - {rec['action']} ({rec['category']}) @ {rec['confidence_level']:.0%}")

    return result


def run_self_optimization_for_translation(
    artifact_dir: str | Path | None = None,
    mission_state_path: Path | str | None = None,
    verbose: bool = True,
) -> dict:
    """
    Run self-optimization on the translation plain-folder mission.
    
    Args:
        artifact_dir: Directory containing mission artifacts (default: derived from mission state)
        mission_state_path: Path to the translation mission_state.json
        verbose: Enable verbose output
    
    Returns:
        Analysis results and recommendations
    """
    from deeploop.core.paths import MISSIONS_DIR
    
    if mission_state_path is None:
        mission_state_path = MISSIONS_DIR / "translation-full-mission" / "mission_state.json"
    
    # If no artifact_dir specified, use mission parent
    if artifact_dir is None:
        artifact_dir = Path(mission_state_path).parent
    
    return run_self_optimization_for_mission(
        artifact_dir=artifact_dir,
        mission_id="translation-full",
        mission_state_path=mission_state_path,
        verbose=verbose,
    )


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run self-optimization analysis on mission artifacts"
    )
    parser.add_argument(
        "--artifact-dir",
        type=str,
        required=True,
        help="Directory containing mission artifacts",
    )
    parser.add_argument(
        "--mission-id",
        type=str,
        required=True,
        help="Identifier for the mission",
    )
    parser.add_argument(
        "--mission-state",
        type=str,
        help="Path to mission_state.json",
    )
    parser.add_argument(
        "--contract",
        type=str,
        help="Path to self-optimization.yaml contract",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    result = run_self_optimization_for_mission(
        artifact_dir=args.artifact_dir,
        mission_id=args.mission_id,
        mission_state_path=args.mission_state,
        contract_path=args.contract,
        verbose=args.verbose,
    )

    # Output result as JSON
    print(json.dumps(result, indent=2, default=str))

    return 0


if __name__ == "__main__":
    exit(main())
