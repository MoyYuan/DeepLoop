from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from deeploop.mission.project_bootstrap import render_bootstrap_repair_lines
from deeploop.mission.project_runner import _jsonify, run_project_until_complete


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project-root",
        required=True,
        help="Path to the plain researcher project folder. `deeploop run` bootstraps or reuses the mission state for you.",
    )
    parser.add_argument("--mission-id", help="Optional override for the generated mission id.")
    parser.add_argument("--force", action="store_true", help="Replace any existing mission root with the same mission id.")
    parser.add_argument(
        "--until-complete",
        action="store_true",
        required=True,
        help=(
            "Keep extending bounded runtime passes until the mission completes or hits a true operator handoff. "
            "Use `deeploop init` plus `deeploop start`/`deeploop resume` instead when you want manual control."
        ),
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
        help="Absolute mission-runtime iteration budget across the full `--until-complete` run.",
    )


def _first_next_command(snapshot: dict[str, Any] | None) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    operator_console = snapshot.get("operator_console")
    if not isinstance(operator_console, dict):
        return None
    next_commands = operator_console.get("next_commands")
    if not isinstance(next_commands, list):
        return None
    for entry in next_commands:
        if isinstance(entry, dict):
            command = str(entry.get("command") or "").strip()
            if command:
                return command
    return None


def _resume_summary_line(result: dict[str, Any]) -> str | None:
    resume_summary = result.get("resume_summary")
    if not isinstance(resume_summary, dict):
        return None
    parts: list[str] = []
    if resume_summary.get("resumed_existing_mission"):
        initial_iterations = int(resume_summary.get("initial_iterations_completed", 0) or 0)
        initial_status = str(resume_summary.get("initial_runtime_status") or "unknown")
        parts.append(f"reused prior mission state ({initial_iterations} recorded iteration(s), status `{initial_status}`)")
    bounded_resume_passes = int(resume_summary.get("bounded_resume_passes", 0) or 0)
    if bounded_resume_passes > 0:
        parts.append(f"auto-resumed {bounded_resume_passes} bounded pass(es)")
    soft_recovery_resume_passes = int(resume_summary.get("soft_recovery_resume_passes", 0) or 0)
    if soft_recovery_resume_passes > 0:
        parts.append(f"{soft_recovery_resume_passes} via soft-gate recovery")
    if not parts:
        return None
    return "; ".join(parts)


def _noncompleted_summary_lines(result: dict[str, Any]) -> list[str]:
    status = str(result.get("status") or "stopped")
    bootstrap_repair = result.get("bootstrap_repair") if isinstance(result.get("bootstrap_repair"), dict) else None
    if status == "bootstrap-repair-required" and isinstance(bootstrap_repair, dict):
        return [
            "DeepLoop could not bootstrap this project root yet.",
            f"- outcome: `{status}`",
            *render_bootstrap_repair_lines(bootstrap_repair, format="plain"),
        ]
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else None
    operator_console = snapshot.get("operator_console") if isinstance(snapshot, dict) else None
    headline = (
        str(operator_console.get("headline") or "").strip()
        if isinstance(operator_console, dict)
        else ""
    )
    summary = (
        str(operator_console.get("summary") or "").strip()
        if isinstance(operator_console, dict)
        else ""
    )
    recommendation = (
        str(operator_console.get("recommendation") or "").strip()
        if isinstance(operator_console, dict)
        else ""
    )
    mission_state_path = result.get("mission_state_path")
    next_command = _first_next_command(snapshot)
    lines = [
        "DeepLoop did not complete this run.",
        f"- outcome: `{status}`",
    ]
    if headline:
        lines.append(f"- handoff: {headline}")
    if summary:
        lines.append(f"- summary: {summary}")
    elif status == "max-total-iterations":
        lines.append("- summary: Reached the total `--max-total-iterations` budget before completion.")
    if recommendation:
        lines.append(f"- recommendation: {recommendation}")
    resume_line = _resume_summary_line(result)
    if resume_line:
        lines.append(f"- resume: {resume_line}")
    if next_command:
        lines.append(f"- next_command: `{next_command}`")
    elif mission_state_path:
        lines.append(f"- next_command: `deeploop status --mission-state {mission_state_path}`")
    return lines


def _run_project(args: argparse.Namespace) -> int:
    if not args.until_complete:
        print(
            "error: `deeploop run` requires `--until-complete`; use `deeploop init` plus "
            "`deeploop start`/`deeploop resume` for manual step-by-step control.",
            flush=True,
        )
        return 2
    result = run_project_until_complete(
        Path(args.project_root),
        mission_id=getattr(args, "mission_id", None),
        force=getattr(args, "force", False),
        chunk_iterations=getattr(args, "chunk_iterations", 8),
        max_total_iterations=getattr(args, "max_total_iterations", 256),
    )
    if result["status"] != "completed":
        print("\n".join(_noncompleted_summary_lines(result)), file=sys.stderr, flush=True)
    print(json.dumps(_jsonify(result), indent=2))
    return 0 if result["status"] == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a plain researcher project folder through DeepLoop until completion or a true operator boundary. "
            "This command handles init + bounded start/resume loops for you."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_run_args(parser)
    args = parser.parse_args()
    return _run_project(args)


__all__ = ["main", "_add_run_args", "_run_project"]
