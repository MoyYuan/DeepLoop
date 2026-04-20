from __future__ import annotations

import argparse
import json
from pathlib import Path

from deeploop.mission.project_runner import _jsonify, run_project_until_complete


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", required=True, help="Path to the plain researcher project folder.")
    parser.add_argument("--mission-id", help="Optional override for the generated mission id.")
    parser.add_argument("--force", action="store_true", help="Replace any existing mission root with the same mission id.")
    parser.add_argument(
        "--until-complete",
        action="store_true",
        help="Keep extending the bounded mission runtime until completion, operator review, or total-iteration exhaustion.",
    )
    parser.add_argument(
        "--chunk-iterations",
        type=int,
        default=8,
        help="How many additional bounded mission-runtime iterations to grant per pass.",
    )
    parser.add_argument(
        "--max-total-iterations",
        type=int,
        default=256,
        help="Absolute mission-runtime iteration budget for the whole until-complete run.",
    )


def _run_project(args: argparse.Namespace) -> int:
    if not args.until_complete:
        print("error: --until-complete is required for the canonical plain-folder project runner.", flush=True)
        return 2
    result = run_project_until_complete(
        Path(args.project_root),
        mission_id=getattr(args, "mission_id", None),
        force=getattr(args, "force", False),
        chunk_iterations=getattr(args, "chunk_iterations", 8),
        max_total_iterations=getattr(args, "max_total_iterations", 256),
    )
    print(json.dumps(_jsonify(result), indent=2))
    return 0 if result["status"] == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a plain researcher project folder through DeepLoop until completion or a true operator boundary.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_run_args(parser)
    args = parser.parse_args()
    return _run_project(args)


__all__ = ["main", "_add_run_args", "_run_project"]
