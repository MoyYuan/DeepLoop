from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.structured_io import write_json_object, write_markdown
from deeploop.testing.plain_folder_proof_matrix import (
    DEFAULT_CAMPAIGNS_ROOT,
    DEFAULT_FIXTURES_ROOT,
    PlainFolderProofCase,
    discover_plain_folder_proof_cases,
    parse_run_project_output,
    snapshot_project_tree,
    summarize_boundary_check,
)
from deeploop.testing.proof_matrix_reviews import (
    build_multi_substrate_proof_review,
    materialize_proof_matrix_review,
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _campaign_id(explicit: str | None) -> str:
    return explicit or f"plain-folder-proof-matrix-{_utc_stamp()}"


def _select_cases(all_cases: list[PlainFolderProofCase], requested_ids: list[str]) -> list[PlainFolderProofCase]:
    if not requested_ids:
        return all_cases
    requested = set(requested_ids)
    selected = [case for case in all_cases if case.case_id in requested]
    missing = sorted(requested - {case.case_id for case in selected})
    if missing:
        raise ValueError(f"Unknown proof cases: {', '.join(missing)}")
    return selected


def _materialize_case_project(case: PlainFolderProofCase, case_root: Path) -> Path:
    project_root = case_root / "project"
    if project_root.exists():
        shutil.rmtree(project_root)
    shutil.copytree(case.fixture_root, project_root)
    return project_root


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_strings(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        value = raw.strip()
        return [value] if value else []
    if isinstance(raw, list | tuple):
        values: list[str] = []
        for item in raw:
            values.extend(_normalize_strings(item))
        return values
    return [str(raw)]


def _threshold_enabled(case: PlainFolderProofCase, name: str, *, default: bool = True) -> bool:
    thresholds = case.acceptance_thresholds or {}
    value = thresholds.get(name, default)
    return bool(value)


def _run_case_command(command: list[str], *, case_timeout_seconds: float) -> tuple[subprocess.CompletedProcess[str], str | None]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timeout_message: str | None = None
    try:
        stdout, stderr = process.communicate(timeout=case_timeout_seconds)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), None
    except subprocess.TimeoutExpired as exc:
        timeout_message = f"run_project.py timed out after {case_timeout_seconds:g} seconds"
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            killed_stdout, killed_stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            killed_stdout, killed_stderr = process.communicate()
        if isinstance(killed_stdout, str):
            stdout = killed_stdout
        if isinstance(killed_stderr, str):
            stderr = killed_stderr
        return subprocess.CompletedProcess(command, 124, stdout, stderr), timeout_message


def _run_case(case: PlainFolderProofCase, case_root: Path, python_bin: str, *, case_timeout_seconds: float) -> dict:
    project_root = _materialize_case_project(case, case_root)
    before_paths = snapshot_project_tree(project_root)

    command = [
        python_bin,
        str(REPO_ROOT / "scripts" / "mission" / "run_project.py"),
        "--project-root",
        str(project_root),
        "--until-complete",
        "--force",
    ]
    completed, timeout_message = _run_case_command(command, case_timeout_seconds=case_timeout_seconds)
    if timeout_message is not None:
        timeout_message = f"{timeout_message} for proof case `{case.case_id}`"

    stdout_path = case_root / "run_project.stdout.txt"
    stderr_path = case_root / "run_project.stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")

    parsed_output: dict | None = None
    mission_state: dict = {}
    current_operator_request: dict = {}
    parse_error: str | None = None
    if completed.stdout.strip():
        try:
            parsed_output = parse_run_project_output(completed.stdout)
        except Exception as exc:  # pragma: no cover - exercised by live harness only
            parse_error = str(exc)
    else:
        parse_error = "run_project.py produced no stdout"

    if parsed_output and isinstance(parsed_output.get("mission_state_path"), str):
        mission_state_path = Path(parsed_output["mission_state_path"]).expanduser().resolve()
        if mission_state_path.exists():
            mission_state = _load_json(mission_state_path)
            operator_request_path = mission_state_path.parent / "current_operator_request.json"
            if operator_request_path.exists():
                current_operator_request = _load_json(operator_request_path)
    after_paths = snapshot_project_tree(project_root)
    boundary = summarize_boundary_check(before_paths, after_paths)
    phase_outputs = (
        mission_state.get("phase_outputs_by_phase")
        if isinstance(mission_state.get("phase_outputs_by_phase"), dict)
        else {}
    )
    final_report_outputs = _normalize_strings(phase_outputs.get("final-report"))

    operator_inbox = mission_state.get("operator_inbox") if isinstance(mission_state.get("operator_inbox"), dict) else {}
    status = "passed"
    failures: list[str] = []
    if timeout_message is not None:
        status = "failed"
        failures.append(timeout_message)
    if completed.returncode != 0:
        status = "failed"
        failures.append(f"run_project.py exited {completed.returncode}")
    if parse_error:
        status = "failed"
        failures.append(parse_error)
    if parsed_output and parsed_output.get("status") != "completed":
        status = "failed"
        failures.append(f"run_project status was {parsed_output.get('status')!r}")
    if mission_state and mission_state.get("status") != "completed":
        status = "failed"
        failures.append(f"mission_state.status was {mission_state.get('status')!r}")
    if mission_state and mission_state.get("current_phase") != "final-report":
        status = "failed"
        failures.append(f"mission_state.current_phase was {mission_state.get('current_phase')!r}")
    if operator_inbox.get("status") not in {None, "clear"}:
        status = "failed"
        failures.append(f"operator_inbox.status was {operator_inbox.get('status')!r}")
    if current_operator_request not in ({}, None):
        status = "failed"
        failures.append("current_operator_request.json was not empty")
    if not boundary["project_tree_unchanged"]:
        status = "failed"
        failures.append("project folder changed during proof run")
    if _threshold_enabled(case, "require_final_report_outputs") and not final_report_outputs:
        status = "failed"
        failures.append("final-report outputs were missing")

    summary = {
        "case_id": case.case_id,
        "title": case.title,
        "workflow_shape": case.workflow_shape,
        "expected_focus": case.expected_focus,
        "autonomy_claims": list(case.autonomy_claims),
        "acceptance_thresholds": case.acceptance_thresholds or {},
        "status": status,
        "failures": failures,
        "fixture_root": str(case.fixture_root),
        "project_root": str(project_root),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "run_project_result": parsed_output,
        "mission_state": {
            "status": mission_state.get("status"),
            "current_phase": mission_state.get("current_phase"),
            "operator_inbox_status": operator_inbox.get("status"),
            "final_report_outputs": final_report_outputs,
        },
        "operator_request": current_operator_request,
        "boundary_check": boundary,
        "case_timeout_seconds": case_timeout_seconds,
    }
    write_json_object(case_root / "proof_summary.json", summary)
    write_markdown(
        case_root / "proof_summary.md",
        [
            f"# Proof case: {case.case_id}",
            "",
            f"- title: `{case.title}`",
            f"- workflow_shape: `{case.workflow_shape}`",
            f"- expected_focus: `{case.expected_focus}`",
            f"- status: `{status}`",
            f"- project_root: `{project_root}`",
            f"- stdout: `{stdout_path}`",
            f"- stderr: `{stderr_path}`",
            f"- final_report_outputs: `{', '.join(final_report_outputs) if final_report_outputs else 'none'}`",
            "",
            "## Autonomy claims",
            "",
            *([f"- {claim}" for claim in case.autonomy_claims] if case.autonomy_claims else ["- none"]),
            "",
            "## Failures",
            "",
            *([f"- {failure}" for failure in failures] if failures else ["- none"]),
            "",
            "## Boundary check",
            "",
            f"- project_tree_unchanged: `{boundary['project_tree_unchanged']}`",
            *[f"- added: `{path}`" for path in boundary["added_paths"]],
            *[f"- removed: `{path}`" for path in boundary["removed_paths"]],
        ],
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the plain-folder bounded-real proof matrix.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--list", action="store_true", help="List available proof cases.")
    parser.add_argument("--case", action="append", default=[], help="Specific proof case id to run. Repeatable.")
    parser.add_argument("--fixtures-root", type=Path, default=DEFAULT_FIXTURES_ROOT, help="Where proof fixtures live.")
    parser.add_argument("--campaign-root", type=Path, default=DEFAULT_CAMPAIGNS_ROOT, help="Where campaign outputs are written.")
    parser.add_argument("--campaign-id", help="Optional explicit campaign id.")
    parser.add_argument("--python-bin", default=sys.executable, help="Python executable to use for run_project.py.")
    parser.add_argument(
        "--case-timeout-seconds",
        type=float,
        default=600.0,
        help="Fail an individual proof case if run_project.py exceeds this timeout.",
    )
    parser.add_argument("--stop-on-failure", action="store_true", help="Stop after the first failing case.")
    args = parser.parse_args()

    all_cases = discover_plain_folder_proof_cases(args.fixtures_root)
    if args.list:
        for case in all_cases:
            print(
                json.dumps(
                    {
                        "case_id": case.case_id,
                        "title": case.title,
                        "workflow_shape": case.workflow_shape,
                        "expected_focus": case.expected_focus,
                        "fixture_root": str(case.fixture_root),
                    }
                )
            )
        return 0

    selected_cases = _select_cases(all_cases, args.case)
    if not selected_cases:
        raise SystemExit("No plain-folder proof cases are available.")

    campaign_id = _campaign_id(args.campaign_id)
    campaign_root = args.campaign_root.expanduser().resolve() / campaign_id
    campaign_root.mkdir(parents=True, exist_ok=True)
    print(
        f"[plain-folder-proof-matrix] campaign={campaign_id} "
        f"cases={len(selected_cases)} timeout={args.case_timeout_seconds:g}s",
        flush=True,
    )

    case_summaries: list[dict] = []
    for case in selected_cases:
        case_root = campaign_root / case.case_id
        case_root.mkdir(parents=True, exist_ok=True)
        started_at = time.perf_counter()
        print(f"[plain-folder-proof-matrix] starting case={case.case_id}", flush=True)
        summary = _run_case(case, case_root, args.python_bin, case_timeout_seconds=args.case_timeout_seconds)
        elapsed_seconds = time.perf_counter() - started_at
        print(
            f"[plain-folder-proof-matrix] finished case={case.case_id} "
            f"status={summary['status']} elapsed={elapsed_seconds:.1f}s",
            flush=True,
        )
        case_summaries.append(summary)
        if args.stop_on_failure and summary["status"] != "passed":
            break

    failed_case_ids = [summary["case_id"] for summary in case_summaries if summary["status"] != "passed"]
    campaign_summary = {
        "campaign_id": campaign_id,
        "fixtures_root": str(args.fixtures_root.expanduser().resolve()),
        "campaign_root": str(campaign_root),
        "python_bin": args.python_bin,
        "case_timeout_seconds": args.case_timeout_seconds,
        "status": "failed" if failed_case_ids else "passed",
        "cases_run": [summary["case_id"] for summary in case_summaries],
        "failed_case_ids": failed_case_ids,
        "case_summaries": case_summaries,
    }
    proof_review = build_multi_substrate_proof_review(campaign_summary)
    review_paths = materialize_proof_matrix_review(proof_review, campaign_root)
    campaign_summary.update(review_paths)
    write_json_object(campaign_root / "campaign_summary.json", campaign_summary)
    write_markdown(
        campaign_root / "campaign_summary.md",
        [
            f"# Plain-folder proof matrix: {campaign_id}",
            "",
            f"- status: `{campaign_summary['status']}`",
            f"- campaign_root: `{campaign_root}`",
            f"- python_bin: `{args.python_bin}`",
            f"- proof_review: `{review_paths['review_json_path']}`",
            "",
            "## Cases",
            "",
            *[
                f"- `{summary['case_id']}`: `{summary['status']}` ({summary['workflow_shape']})"
                for summary in case_summaries
            ],
        ],
    )
    print(
        json.dumps(
            {
                **campaign_summary,
                "proof_review": proof_review,
            },
            indent=2,
        )
    )
    return 1 if failed_case_ids else 0


if __name__ == "__main__":
    raise SystemExit(main())
