"""deeploop analyze — route a mission analysis prompt to the configured provider.

The command writes the prompt to a file under the mission root before passing
it to the provider, so the OS argument list never carries the full mission
state.  This avoids the ``[Errno 7] Argument list too long`` crash that occurs
when callers naively expand a large JSON file into a shell flag string.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _build_analyze_prompt(
    *,
    mission_state: dict[str, Any],
    mission_state_path: Path,
    result_json_path: Path,
    task: str | None = None,
) -> str:
    mission_id = str(mission_state.get("mission_id") or mission_state_path.parent.name)
    current_phase = str(mission_state.get("current_phase") or "unknown")
    next_phase = str(mission_state.get("next_phase") or "")
    title = str(mission_state.get("title") or "")
    mode = str(mission_state.get("mode") or (mission_state.get("outer_loop") or {}).get("mode") or "")

    lines = [
        "# DeepLoop mission analysis",
        "",
        "Produce a concise operator-facing analysis of the mission state listed below.",
        "Do not mutate any mission state, queue files, or operator requests.",
        "",
        "## Mission",
        "",
        f"- mission_id: `{mission_id}`",
    ]
    if title:
        lines.append(f"- title: {title}")
    lines.extend(
        [
            f"- current_phase: `{current_phase}`",
        ]
    )
    if next_phase:
        lines.append(f"- next_phase: `{next_phase}`")
    if mode:
        lines.append(f"- mode: `{mode}`")
    lines.extend(
        [
            f"- mission_state_path: `{mission_state_path}`",
            "",
        ]
    )

    resolved_task = task or (
        "Summarize the current mission status, identify any blockers or risks, "
        "and recommend the most impactful next step."
    )
    lines.extend(
        [
            "## Analysis task",
            "",
            resolved_task,
            "",
            "## Required output",
            "",
            f"Write JSON to `{result_json_path}` with this exact top-level shape:",
            "```json",
            "{",
            '  "status": "completed" | "in_progress" | "blocked" | "failed",',
            '  "summary": "short operator-facing summary of the mission state",',
            '  "recommended_next_step": "one sentence on the most impactful next action",',
            '  "findings": ["key finding 1", "key finding 2"],',
            '  "notes": ["optional caution or context note"]',
            "}",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _add_analyze_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mission-state",
        required=True,
        help="Path to mission_state.json.  Used both to build the default prompt and as provider context.",
    )
    parser.add_argument(
        "--prompt-file",
        help=(
            "Optional path to a fully custom prompt file.  "
            "When omitted a default analysis prompt is generated from --mission-state.  "
            "Always pass the prompt as a file — never inline the file contents into a CLI flag."
        ),
    )
    parser.add_argument(
        "--task",
        help=(
            "Optional one-sentence override for the analysis task description embedded in the "
            "generated prompt.  Ignored when --prompt-file is provided."
        ),
    )
    parser.add_argument(
        "--result-json-path",
        help=(
            "Optional path where the provider should write the result JSON.  "
            "Defaults to <mission_root>/runtime/analyze/<timestamp>/result.json."
        ),
    )
    parser.add_argument("--sandbox-root", help="Optional sandbox root passed to the provider launcher.")
    parser.add_argument("--target-repo", help="Optional target-repo path passed to the provider launcher.")
    parser.add_argument("--provider-family", default="copilot-cli", help="Provider family (default: copilot-cli).")
    parser.add_argument("--model", help="Optional model override for the provider.")
    parser.add_argument("--json", action="store_true", help="Emit the structured result payload as JSON.")


def _analyze(args: argparse.Namespace) -> int:
    # Import here to keep the module importable without installing the full package.
    import time

    from deeploop.core.structured_io import load_json_object
    from deeploop.runtime.provider_launcher import run_provider_prompt

    mission_state_path = Path(args.mission_state).expanduser().resolve()
    if not mission_state_path.exists():
        print(f"error: mission_state path does not exist: {mission_state_path}", file=sys.stderr)
        return 1

    mission_state = load_json_object(mission_state_path)

    # Determine where the result JSON will be written.
    mission_root = mission_state_path.parent
    timestamp_label = str(int(time.time()))
    analyze_root = mission_root / "runtime" / "analyze" / timestamp_label
    analyze_root.mkdir(parents=True, exist_ok=True)

    if args.result_json_path:
        result_json_path = Path(args.result_json_path).expanduser().resolve()
        result_json_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        result_json_path = analyze_root / "result.json"

    # Resolve the prompt file — either the caller's file or a freshly generated one.
    if args.prompt_file:
        prompt_file = Path(args.prompt_file).expanduser().resolve()
        if not prompt_file.exists():
            print(f"error: --prompt-file does not exist: {prompt_file}", file=sys.stderr)
            return 1
    else:
        prompt_text = _build_analyze_prompt(
            mission_state=mission_state,
            mission_state_path=mission_state_path,
            result_json_path=result_json_path,
            task=getattr(args, "task", None),
        )
        prompt_file = analyze_root / "prompt.md"
        # Write to a file — never pass the text as a CLI argument to avoid [Errno 7].
        prompt_file.write_text(prompt_text, encoding="utf-8")

    sandbox_root = Path(args.sandbox_root).expanduser().resolve() if args.sandbox_root else None
    target_repo = Path(args.target_repo).expanduser().resolve() if args.target_repo else None

    completed = run_provider_prompt(
        prompt_file,
        provider_family=args.provider_family,
        result_json_path=result_json_path,
        sandbox_root=sandbox_root,
        mission_state_path=mission_state_path,
        target_repo=target_repo,
        model=getattr(args, "model", None),
        allow_all=True,
        no_ask_user=True,
    )

    if completed.stdout:
        print(completed.stdout, end="", file=sys.stderr)
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)

    if result_json_path.exists():
        try:
            result_payload = json.loads(result_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result_payload = None
        if result_payload is not None:
            if args.json:
                print(json.dumps(result_payload, indent=2))
            else:
                print(_render_analyze_result(result_payload, result_json_path=result_json_path), end="")
            return completed.returncode

    # If the provider didn't write a result, just propagate the return code.
    if not args.json:
        print(f"warning: provider did not write a result to {result_json_path}", file=sys.stderr)
    return completed.returncode if completed.returncode != 0 else 1


def _render_analyze_result(result: dict[str, Any], *, result_json_path: Path) -> str:
    lines = [
        "# DeepLoop mission analysis",
        "",
        f"- status: `{result.get('status') or 'unknown'}`",
        f"- result_json_path: `{result_json_path}`",
        f"- summary: {result.get('summary') or 'n/a'}",
    ]
    recommended = result.get("recommended_next_step")
    if recommended:
        lines.append(f"- recommended_next_step: {recommended}")
    findings = result.get("findings")
    if isinstance(findings, list) and findings:
        lines.append(f"- findings: {'; '.join(str(item) for item in findings[:5])}")
    notes = result.get("notes")
    if isinstance(notes, list) and notes:
        lines.append(f"- notes: {'; '.join(str(item) for item in notes[:3])}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a DeepLoop mission by routing a prompt to the configured provider. "
            "The prompt is always written to a file before being sent — it is never expanded "
            "into a CLI argument, so this command is safe for large mission states."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_analyze_args(parser)
    args = parser.parse_args(argv)
    return _analyze(args)


__all__ = ["main", "_add_analyze_args", "_analyze", "_build_analyze_prompt"]
