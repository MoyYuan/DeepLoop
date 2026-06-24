#!/usr/bin/env python3
"""Generate a conference paper from a completed DeepLoop mission.

Usage:
    python -m deeploop.scripts.paper.generate_paper \\
        --mission-state <path> [--conference iclr2025] [--output-dir <path>]

This script is also available as the ``deeploop generate-paper`` CLI command.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from deeploop.mission.mission_state import load_mission_state
from deeploop.paper.generator import generate_paper


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a conference paper from a DeepLoop mission."
    )
    parser.add_argument(
        "--mission-state",
        required=True,
        type=Path,
        help="Path to mission_state.json.",
    )
    parser.add_argument(
        "--conference",
        default="iclr2025",
        help="Conference style (iclr2025, neurips2025, icml2025).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: <mission_root>/paper_output).",
    )
    parser.add_argument(
        "--experiment-results",
        type=Path,
        default=None,
        help="Path to JSON file with experiment results for context.",
    )
    parser.add_argument(
        "--statistical-report",
        type=Path,
        default=None,
        help="Path to JSON file with statistical analysis.",
    )
    args = parser.parse_args(argv)

    # Load mission state
    mission_state_path = args.mission_state.expanduser().resolve()
    if not mission_state_path.exists():
        print(f"Error: mission state file not found: {mission_state_path}", file=sys.stderr)
        return 1

    mission_state = load_mission_state(mission_state_path)

    # Load optional experiment results
    experiment_results = None
    if args.experiment_results:
        er_path = args.experiment_results.expanduser().resolve()
        if er_path.exists():
            experiment_results = json.loads(er_path.read_text(encoding="utf-8"))

    # Load optional statistical report
    statistical_report = None
    if args.statistical_report:
        sr_path = args.statistical_report.expanduser().resolve()
        if sr_path.exists():
            statistical_report = json.loads(sr_path.read_text(encoding="utf-8"))

    # Default output dir
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = mission_state_path.parent / "paper_output"

    # Generate
    result = generate_paper(
        mission_state,
        conference=args.conference,
        experiment_results=experiment_results,
        statistical_report=statistical_report,
        output_dir=output_dir,
    )

    print(f"Paper generated: {result['tex_path']}")
    if result.get("pdf_path"):
        print(f"PDF compiled: {result['pdf_path']}")
    print(f"Output directory: {result['output_dir']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
