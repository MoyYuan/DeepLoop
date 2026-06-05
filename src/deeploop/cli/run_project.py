from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

import yaml

from deeploop.cli.bootstrap_support import check_provider_readiness
from deeploop.mission.project_bootstrap import render_bootstrap_repair_lines
from deeploop.mission.project_runner import (
    _find_explicit_mission_configs,
    _jsonify,
    run_project_until_complete,
)

_DEFAULT_RUN_CHUNK_ITERATIONS = 8
_DEFAULT_RUN_MAX_TOTAL_ITERATIONS = 256
_DEFAULT_FIRST_RUN_SELECTION_PROFILE = "deepseek-chat-control-plane"


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project-root",
        help=(
            "Optional path to the plain researcher project folder. If omitted, use --idea or supply "
            "a research idea as the first positional argument."
        ),
    )
    parser.add_argument("--idea", help="Rough research idea to bootstrap a project from when --project-root is not given.")
    parser.add_argument("--mission-idea", help="Optional rough research goal to seed the interactive no-project flow.")
    parser.add_argument("--mission-id", help="Optional override for the generated mission id.")
    parser.add_argument("--force", action="store_true", help="Replace any existing mission root with the same mission id.")
    parser.add_argument(
        "--until-complete",
        action="store_true",
        required=True,
        help=(
            "Keep extending bounded runtime passes until the mission completes or pauses at a true operator handoff. "
            "If it pauses, continue with `deeploop status --mission-state <mission-state.json>`, "
            "`deeploop inbox --mission-state <mission-state.json>`, and "
            "`deeploop resume --mission-state <mission-state.json>`. "
            "Use `deeploop init` plus `deeploop start` when you want manual kickoff control."
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


def _load_run_config(config_path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def _config_provider_readiness_target(config: dict[str, Any]) -> tuple[str | None, str | None]:
    def _search_provider_selection(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            selection = value.get("provider_selection")
            if isinstance(selection, dict):
                return selection
            for nested in value.values():
                found = _search_provider_selection(nested)
                if found is not None:
                    return found
        if isinstance(value, list):
            for item in value:
                found = _search_provider_selection(item)
                if found is not None:
                    return found
        return None

    selection = _search_provider_selection(config)
    if selection is None:
        return (None, _DEFAULT_FIRST_RUN_SELECTION_PROFILE)
    selection_profile = str(selection.get("profile") or "").strip() or None
    mission_default = selection.get("mission_default") if isinstance(selection.get("mission_default"), dict) else {}
    provider_family = (
        str(selection.get("provider_family") or "").strip()
        or str(mission_default.get("provider_family") or "").strip()
        or None
    )
    return provider_family, selection_profile or _DEFAULT_FIRST_RUN_SELECTION_PROFILE


def _run_resume_command(
    args: argparse.Namespace,
    *,
    project_root: Path | None,
    mission_id: str | None = None,
) -> str:
    command = ["deeploop", "run"]
    if project_root is not None:
        command.extend(["--project-root", str(project_root)])
    resolved_mission_id = mission_id or getattr(args, "mission_id", None)
    if resolved_mission_id:
        command.extend(["--mission-id", resolved_mission_id])
    if getattr(args, "force", False):
        command.append("--force")
    chunk_iterations = int(getattr(args, "chunk_iterations", _DEFAULT_RUN_CHUNK_ITERATIONS))
    max_total_iterations = int(getattr(args, "max_total_iterations", _DEFAULT_RUN_MAX_TOTAL_ITERATIONS))
    if chunk_iterations != _DEFAULT_RUN_CHUNK_ITERATIONS:
        command.extend(["--chunk-iterations", str(chunk_iterations)])
    if max_total_iterations != _DEFAULT_RUN_MAX_TOTAL_ITERATIONS:
        command.extend(["--max-total-iterations", str(max_total_iterations)])
    command.append("--until-complete")
    return shlex.join(command)


def _provider_readiness_result(
    *,
    config_path: Path | None,
    project_root: Path | None,
    resume_command: str,
) -> dict[str, Any] | None:
    provider_family: str | None = None
    selection_profile: str | None = _DEFAULT_FIRST_RUN_SELECTION_PROFILE
    mission_id: str | None = None
    if config_path is not None and config_path.exists():
        config = _load_run_config(config_path)
        mission = config.get("mission") if isinstance(config.get("mission"), dict) else {}
        mission_id = str(mission.get("id") or "").strip() or None
        provider_family, selection_profile = _config_provider_readiness_target(config)
    report = check_provider_readiness(
        provider_family=provider_family,
        selection_profile=selection_profile,
        resume_command=resume_command,
    )
    if report["status"] == "ready":
        return None
    return {
        "status": "provider-readiness-required",
        "project_root": project_root,
        "config_path": config_path,
        "mission_id": mission_id,
        "provider_readiness": report,
    }


def _noncompleted_summary_lines(result: dict[str, Any]) -> list[str]:
    status = str(result.get("status") or "stopped")
    bootstrap_repair = result.get("bootstrap_repair") if isinstance(result.get("bootstrap_repair"), dict) else None
    if status == "bootstrap-repair-required" and isinstance(bootstrap_repair, dict):
        return [
            "DeepLoop could not bootstrap this project root yet.",
            f"- outcome: `{status}`",
            *render_bootstrap_repair_lines(bootstrap_repair, format="plain"),
        ]
    provider_readiness = (
        result.get("provider_readiness") if isinstance(result.get("provider_readiness"), dict) else None
    )
    if status == "provider-readiness-required" and isinstance(provider_readiness, dict):
        lines = [
            "DeepLoop stopped before kickoff because the required provider setup is not ready yet.",
            f"- outcome: `{status}`",
            f"- provider_family: `{provider_readiness.get('provider_family')}`",
            f"- setup_status: `{provider_readiness.get('status')}`",
        ]
        selection_profile = str(provider_readiness.get("selection_profile") or "").strip()
        if selection_profile:
            lines.append(f"- selection_profile: `{selection_profile}`")
        summary = str(provider_readiness.get("summary") or "").strip()
        if summary:
            lines.append(f"- summary: {summary}")
        failed_checks = (
            provider_readiness.get("failed_checks") if isinstance(provider_readiness.get("failed_checks"), list) else []
        )
        for check in failed_checks[:4]:
            label = check.get("name")
            if check.get("kind") == "python-import":
                label = ", ".join(check.get("modules", []))
            lines.append(f"- missing: `{check.get('kind')}` `{label}` — {check.get('message')}")
        next_step = str(provider_readiness.get("next_step") or "").strip()
        if next_step:
            lines.append(f"- next_step: {next_step}")
        resume_command = str(provider_readiness.get("resume_command") or "").strip()
        if resume_command:
            lines.append(f"- resume_command: `{resume_command}`")
        recheck_command = str(provider_readiness.get("recheck_command") or "").strip()
        if recheck_command:
            lines.append(f"- recheck_command: `{recheck_command}`")
        return lines
    readiness = result.get("readiness") if isinstance(result.get("readiness"), dict) else None
    if status == "mission-readiness-required" and isinstance(readiness, dict):
        lines = [
            "DeepLoop stopped before kickoff because the mission contract still needs operator input.",
            f"- outcome: `{status}`",
            f"- readiness_status: `{readiness.get('status')}`",
            f"- launch_recommendation: `{readiness.get('launch_recommendation')}`",
        ]
        mission_state_path = result.get("mission_state_path")
        if mission_state_path:
            lines.append(f"- mission_state: `{mission_state_path}`")
        mission_summary_path = result.get("mission_summary_path")
        if mission_summary_path:
            lines.append(f"- mission_summary: `{mission_summary_path}`")
        for question in result.get("follow_up_questions", [])[:4]:
            lines.append(f"- needs_answer: {question}")
        lines.append(
            "- next_step: answer the blocking project-contract question(s) in the substrate or mission config, then rerun `deeploop run`."
        )
        return lines
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
    status_command = f"deeploop status --mission-state {mission_state_path}" if mission_state_path else None
    inbox_command = f"deeploop inbox --mission-state {mission_state_path}" if mission_state_path else None
    resume_command = f"deeploop resume --mission-state {mission_state_path}" if mission_state_path else None
    lines = [
        "DeepLoop paused before completion.",
        f"- outcome: `{status}`",
    ]
    if mission_state_path:
        lines.append(f"- mission_state: `{mission_state_path}`")
    if headline:
        lines.append(f"- handoff: {headline}")
    if summary:
        lines.append(f"- summary: {summary}")
    elif status == "max-total-iterations":
        lines.append("- summary: Reached the total `--max-total-iterations` budget before completion.")
    if recommendation:
        lines.append(f"- recommendation: {recommendation}")
    if status_command:
        lines.append(f"- operator_loop: start with `{status_command}`")
    if inbox_command:
        lines.append(f"- operator_loop_if_needed: if DeepLoop needs you, open `{inbox_command}`")
    if resume_command:
        lines.append(f"- operator_loop_resume: when the fix or choice is ready, run `{resume_command}`")
    resume_line = _resume_summary_line(result)
    if resume_line:
        lines.append(f"- resume: {resume_line}")
    if mission_state_path:
        lines.append(
            f"- advanced_detail: `deeploop logs --mission-state {mission_state_path}` and "
            f"`deeploop decisions --mission-state {mission_state_path}` only if `status` is not enough"
        )
    return lines


def _run_project(args: argparse.Namespace) -> int:
    if not args.until_complete:
        print(
            "error: `deeploop run` requires `--until-complete`; use `deeploop init` plus "
            "`deeploop start`/`deeploop resume` for manual step-by-step control.",
            flush=True,
        )
        return 2
    try:
        if getattr(args, "project_root", None):
            raw_project_root = Path(args.project_root).expanduser()
            resolved_project_root = raw_project_root.resolve()
            explicit_configs = _find_explicit_mission_configs(resolved_project_root) if raw_project_root.exists() else []
            provider_gate = (
                _provider_readiness_result(
                    config_path=explicit_configs[0] if explicit_configs else None,
                    project_root=resolved_project_root,
                    resume_command=_run_resume_command(args, project_root=resolved_project_root),
                )
                if raw_project_root.exists() and explicit_configs
                else None
            )
            if provider_gate is not None:
                result = provider_gate
            else:
                result = run_project_until_complete(
                    raw_project_root,
                    mission_id=getattr(args, "mission_id", None),
                    force=getattr(args, "force", False),
                    chunk_iterations=getattr(args, "chunk_iterations", 8),
                    max_total_iterations=getattr(args, "max_total_iterations", 256),
                )
        else:
            # Non-interactive bootstrap from --idea
            from deeploop.core.paths import PROJECTS_DIR
            from deeploop.core.shared import slugify as _slugify

            idea = getattr(args, "idea", None)
            if not idea:
                print("Usage: deeploop run --idea \"your research idea\" --until-complete", flush=True)
                print("  or: deeploop run --project-root <path> --until-complete", flush=True)
                print("  or: deeploop init --discover   (interactive discovery)", flush=True)
                return 2

            import yaml

            project_root = PROJECTS_DIR / _slugify(idea)[:40]
            project_root.mkdir(parents=True, exist_ok=True)
            project_facts_path = project_root / "project-facts.yaml"
            if not project_facts_path.exists():
                project_facts = {
                    "project": {
                        "name": _slugify(idea)[:40],
                        "title": idea[:120],
                        "summary": idea[:500],
                        "objective": idea[:500],
                    }
                }
                project_facts_path.write_text(yaml.safe_dump(project_facts, sort_keys=False), encoding="utf-8")

            result = run_project_until_complete(
                project_root,
                mission_id=getattr(args, "mission_id", None),
                force=getattr(args, "force", False),
                chunk_iterations=getattr(args, "chunk_iterations", 8),
                max_total_iterations=getattr(args, "max_total_iterations", 256),
            )
    except (FileNotFoundError, ValueError) as exc:
        print(f"run: {exc}", file=sys.stderr, flush=True)
        return 2
    if result["status"] != "completed":
        print("\n".join(_noncompleted_summary_lines(result)), file=sys.stderr, flush=True)
    print(json.dumps(_jsonify(result), indent=2))
    return 0 if result["status"] == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a plain researcher project folder through DeepLoop until completion or a true operator boundary. "
            "When the run pauses, stay on `deeploop status --mission-state <mission-state.json>`, "
            "`deeploop inbox --mission-state <mission-state.json>`, and "
            "`deeploop resume --mission-state <mission-state.json>`."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_run_args(parser)
    args = parser.parse_args()
    return _run_project(args)


__all__ = ["main", "_add_run_args", "_run_project"]
