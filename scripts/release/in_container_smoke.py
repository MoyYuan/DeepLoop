from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from deeploop.core.paths import EXPECTED_EXTERNAL_DIRS, MISSIONS_DIR, PROJECTS_DIR, SCRATCH_DIR, WORKSPACE_ROOT

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_SRC_ROOT = SCRIPT_REPO_ROOT / "src"
IMPORTED_DEEPLOOP_PATH = Path(sys.modules["deeploop.core.paths"].__file__).resolve()


def _deeploop_subprocess_env(env: dict[str, str] | None = None) -> dict[str, str]:
    resolved_env = dict(os.environ if env is None else env)
    if IMPORTED_DEEPLOOP_PATH.is_relative_to(SCRIPT_SRC_ROOT):
        pythonpath_entries = [str(SCRIPT_SRC_ROOT)]
        existing_pythonpath = str(resolved_env.get("PYTHONPATH") or "").strip()
        if existing_pythonpath:
            pythonpath_entries.extend(
                entry for entry in existing_pythonpath.split(os.pathsep) if entry and entry != str(SCRIPT_SRC_ROOT)
            )
        resolved_env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    return resolved_env


def _run_capture(
    command: list[str],
    *,
    input_text: str | None = None,
    expected_returncode: int | None = 0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    print(f"+ {shlex.join(command)}", flush=True)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        input=input_text,
        text=True,
        env=_deeploop_subprocess_env(env),
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    if expected_returncode is not None and completed.returncode != expected_returncode:
        raise SystemExit(completed.returncode)
    return completed


def _run(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return _run_capture(command, env=env)


def _deeploop_command(*args: str) -> list[str]:
    resolved = shutil.which("deeploop")
    if resolved is not None:
        return [resolved, *args]
    manage_script = SCRIPT_REPO_ROOT / "scripts" / "mission" / "manage_mission.py"
    return [sys.executable, str(manage_script), *args]


def _python_bin_only_env() -> dict[str, str]:
    env = _deeploop_subprocess_env()
    env["PATH"] = str(Path(sys.executable).expanduser().resolve().parent)
    return env


def _extract_trailing_json(stdout: str) -> dict:
    decoder = json.JSONDecoder()
    for start in reversed([index for index, char in enumerate(stdout) if char == "{"]):
        try:
            payload, end = decoder.raw_decode(stdout[start:])
        except ValueError:
            continue
        if stdout[start + end :].strip():
            continue
        if isinstance(payload, dict):
            return payload
    raise SystemExit("docker-smoke: command output did not end with a JSON object")


def _run_json_capture(
    command: list[str],
    *,
    input_text: str | None = None,
    expected_returncode: int | None = 0,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    completed = _run_capture(
        command,
        input_text=input_text,
        expected_returncode=expected_returncode,
        env=env,
    )
    return completed, _extract_trailing_json(completed.stdout)


def _copy_project(source: Path, destination_root: Path) -> Path:
    if not source.exists():
        raise SystemExit(f"docker-smoke: missing smoke project: {source}")
    project_root = destination_root / source.name
    shutil.rmtree(project_root, ignore_errors=True)
    shutil.copytree(source, project_root)
    return project_root


def _snapshot_project_files(project_root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(project_root))
        for path in project_root.rglob("*")
        if path.is_file()
    )


def _expected_version_from_install_spec(install_spec: str | None) -> str | None:
    if not install_spec or "==" not in install_spec:
        return None
    package_name, version = install_spec.split("==", 1)
    return version if package_name.strip() == "deeploop" else None


def _mission_root(mission_id: str) -> Path:
    return MISSIONS_DIR / mission_id


def _package_root(mission_id: str) -> Path:
    return MISSIONS_DIR.parent / "packages" / mission_id


def _discovery_config_path(mission_id: str) -> Path:
    return SCRATCH_DIR / "mission_discovery_configs" / f"{mission_id}.yaml"


def _starter_project_root(mission_id: str) -> Path:
    return PROJECTS_DIR / mission_id.removesuffix("-mission")


def _cleanup_mission_artifacts(mission_id: str, *, remove_discovery_config: bool = False) -> None:
    shutil.rmtree(_mission_root(mission_id), ignore_errors=True)
    shutil.rmtree(_package_root(mission_id), ignore_errors=True)
    if remove_discovery_config:
        _discovery_config_path(mission_id).unlink(missing_ok=True)
        shutil.rmtree(_starter_project_root(mission_id), ignore_errors=True)


def _release_validation_smoke_root() -> Path:
    return SCRATCH_DIR / "release-validation" / "docker-smoke"


def _package_mission(state_path: Path) -> tuple[dict, Path, Path, Path]:
    package_completed = _run(["deeploop-package-mission", "--mission-state", str(state_path)])
    package_result = json.loads(package_completed.stdout)
    package_root = Path(package_result["package_root"]).expanduser().resolve()
    manifest_path = Path(package_result["manifest_path"]).expanduser().resolve()
    summary_path = Path(package_result["summary_path"]).expanduser().resolve()
    if not package_root.exists() or not manifest_path.exists() or not summary_path.exists():
        raise SystemExit("docker-smoke: package outputs were missing")
    return package_result, package_root, manifest_path, summary_path


def _write_partial_project_folder(project_root: Path) -> None:
    shutil.rmtree(project_root, ignore_errors=True)
    (project_root / "docs").mkdir(parents=True, exist_ok=True)
    (project_root / "data").mkdir(parents=True, exist_ok=True)
    (project_root / "docs" / "project-brief.md").write_text(
        "# Project brief\n\nForecast weekly demand from the retailer export in data/store_snapshot.csv.\n",
        encoding="utf-8",
    )
    (project_root / "data" / "store_snapshot.csv").write_text(
        "week_start,store_id,next_week_units\n2024-01-01,s1,42\n",
        encoding="utf-8",
    )


def _assert_project_unmutated(project_root: Path, before_paths: list[str]) -> None:
    after_paths = _snapshot_project_files(project_root)
    if before_paths != after_paths:
        raise SystemExit("docker-smoke: project-root bootstrap mutated the example project")


def _assert_mission_state_targets_project(mission_state: dict, project_root: Path) -> None:
    if Path(mission_state.get("target_repo", "")).resolve() != project_root.resolve():
        raise SystemExit("docker-smoke: mission state target_repo did not match the copied example project")


def _bootstrap_plain_folder_project(project_root: Path, *, mission_id: str) -> tuple[Path, dict]:
    before_paths = _snapshot_project_files(project_root)
    _cleanup_mission_artifacts(mission_id)
    mission_root = _mission_root(mission_id)
    _run(
        [
            "deeploop-init-mission",
            "--project-root",
            str(project_root),
            "--mission-id",
            mission_id,
            "--force",
        ]
    )

    state_path = mission_root / "mission_state.json"
    if not state_path.exists():
        raise SystemExit(f"docker-smoke: missing mission state: {state_path}")
    mission_state = json.loads(state_path.read_text(encoding="utf-8"))
    _assert_project_unmutated(project_root, before_paths)
    if mission_state.get("project_contract", {}).get("status") != "plain-artifacts":
        raise SystemExit("docker-smoke: expected plain-artifacts project contract in mission state")
    _assert_mission_state_targets_project(mission_state, project_root)
    return state_path, mission_state


def _run_translation_bootstrap(repo_root: Path, smoke_root: Path, *, mission_id: str) -> dict:
    project_root = _copy_project(repo_root / "examples" / "translation-budget-ladder", smoke_root)
    state_path, mission_state = _bootstrap_plain_folder_project(project_root, mission_id=mission_id)
    if mission_state.get("status") not in {"initialized", "ready"}:
        raise SystemExit(
            f"docker-smoke: expected translation mission status `initialized` or `ready`, got {mission_state.get('status')!r}"
        )
    return {
        "workflow": "translation-budget-ladder",
        "project_root": str(project_root),
        "mission_state_path": str(state_path),
        "mission_status": mission_state.get("status"),
        "current_phase": mission_state.get("current_phase"),
    }


def _run_zero_start_bundled_starter_provider_gate_smoke(*, mission_id: str) -> dict:
    _cleanup_mission_artifacts(mission_id, remove_discovery_config=True)
    completed = _run_capture(
        _deeploop_command(
            "start",
            "--idea",
            "Find a good starter path for benchmarking translation robustness.",
        ),
        expected_returncode=1,
        env=_python_bin_only_env(),
    )
    stdout = completed.stdout
    if "Provider not ready" not in stdout:
        raise SystemExit("docker-smoke: start did not report provider readiness")
    if "OPENAI_API_KEY" not in stdout:
        raise SystemExit("docker-smoke: start did not surface the expected next setup step")
    if "deeploop provider-ready" not in stdout:
        raise SystemExit("docker-smoke: start did not provide the expected readiness recheck command")

    # Extract the provider readiness message from stdout
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    next_step = next((line for line in lines if "Provider not ready" in line), "Provider not ready")
    recheck = next((line for line in lines if "deeploop provider-ready" in line), "")

    return {
        "workflow": "zero-start-bundled-starter",
        "next_step": next_step,
        "recheck_command": recheck,
    }


def _run_literature_operator_package_smoke(repo_root: Path, smoke_root: Path, *, mission_id: str) -> dict:
    project_root = _copy_project(
        repo_root / "tests" / "_proof_fixtures" / "plain_folder" / "literature-gap-map",
        smoke_root,
    )
    state_path, mission_state = _bootstrap_plain_folder_project(project_root, mission_id=mission_id)
    readiness = mission_state.get("mission_contract", {}).get("readiness", {})
    if mission_state.get("status") != "initialized":
        raise SystemExit(
            f"docker-smoke: expected literature mission status `initialized`, got {mission_state.get('status')!r}"
        )
    if mission_state.get("current_phase") != "idea-intake":
        raise SystemExit(
            f"docker-smoke: expected literature mission current phase `idea-intake`, got {mission_state.get('current_phase')!r}"
        )
    if readiness.get("status") != "ready-with-clarifications":
        raise SystemExit(
            "docker-smoke: expected literature mission readiness `ready-with-clarifications`"
        )
    if readiness.get("launch_recommendation") != "launch-with-disclosed-guardrails":
        raise SystemExit(
            "docker-smoke: expected literature mission launch recommendation `launch-with-disclosed-guardrails`"
        )

    mission_summary_path = state_path.parent / "mission_summary.md"
    if not mission_summary_path.exists():
        raise SystemExit(f"docker-smoke: missing mission summary: {mission_summary_path}")
    mission_summary_text = mission_summary_path.read_text(encoding="utf-8")
    if (
        "### Clarifications" not in mission_summary_text
        or "What leakage boundary should DeepLoop enforce" not in mission_summary_text
    ):
        raise SystemExit("docker-smoke: literature mission summary did not surface the expected operator clarifications")

    package_result, package_root, _, summary_path = _package_mission(state_path)
    package_payload = package_result.get("package") if isinstance(package_result.get("package"), dict) else {}
    checks = package_payload.get("checks") if isinstance(package_payload.get("checks"), dict) else {}
    missing_required = set(checks.get("missing_required_artifacts") or [])
    if checks.get("all_required_artifacts_present") is not False:
        raise SystemExit("docker-smoke: literature package did not record the expected missing lightweight artifacts")
    if {"category:findings", "category:manifests"} - missing_required:
        raise SystemExit("docker-smoke: literature package did not record missing findings/manifests")
    package_summary_text = summary_path.read_text(encoding="utf-8")
    if "Current phase: idea-intake (initialized)" not in package_summary_text:
        raise SystemExit("docker-smoke: literature package summary did not preserve mission phase/status context")

    return {
        "workflow": "literature-gap-map",
        "project_root": str(project_root),
        "mission_state_path": str(state_path),
        "mission_status": mission_state.get("status"),
        "current_phase": mission_state.get("current_phase"),
        "readiness_status": readiness.get("status"),
        "launch_recommendation": readiness.get("launch_recommendation"),
        "package_root": str(package_root),
        "missing_required_artifacts": sorted(missing_required),
    }


def _run_messy_plain_folder_smoke(repo_root: Path, smoke_root: Path, *, mission_id: str) -> dict:
    project_root = _copy_project(
        repo_root / "tests" / "_proof_fixtures" / "plain_folder" / "forecast-rough-notes",
        smoke_root,
    )
    state_path, mission_state = _bootstrap_plain_folder_project(project_root, mission_id=mission_id)
    readiness = mission_state.get("mission_contract", {}).get("readiness", {})
    if mission_state.get("status") != "initialized":
        raise SystemExit(
            f"docker-smoke: expected messy-notes mission status `initialized`, got {mission_state.get('status')!r}"
        )
    if mission_state.get("current_phase") != "idea-intake":
        raise SystemExit(
            f"docker-smoke: expected messy-notes mission current phase `idea-intake`, got {mission_state.get('current_phase')!r}"
        )
    if readiness.get("status") != "ready-with-clarifications":
        raise SystemExit(
            "docker-smoke: expected messy-notes mission readiness `ready-with-clarifications`"
        )
    if readiness.get("launch_recommendation") != "launch-with-disclosed-guardrails":
        raise SystemExit(
            "docker-smoke: expected messy-notes mission launch recommendation `launch-with-disclosed-guardrails`"
        )
    if mission_state.get("mission_contract", {}).get("data", {}).get("target") != "next_week_units":
        raise SystemExit("docker-smoke: expected messy-notes mission target `next_week_units`")

    mission_summary_path = state_path.parent / "mission_summary.md"
    if not mission_summary_path.exists():
        raise SystemExit(f"docker-smoke: missing mission summary: {mission_summary_path}")
    mission_summary_text = mission_summary_path.read_text(encoding="utf-8")
    if "### Clarifications" not in mission_summary_text or "### Defaults applied" not in mission_summary_text:
        raise SystemExit("docker-smoke: messy-notes mission summary did not surface bounded clarifications/defaults")

    _, package_root, _, _ = _package_mission(state_path)

    return {
        "workflow": "forecast-rough-notes",
        "project_root": str(project_root),
        "mission_state_path": str(state_path),
        "mission_status": mission_state.get("status"),
        "current_phase": mission_state.get("current_phase"),
        "readiness_status": readiness.get("status"),
        "launch_recommendation": readiness.get("launch_recommendation"),
        "package_root": str(package_root),
    }


def _run_discovery_first_plain_folder_smoke(repo_root: Path, smoke_root: Path, *, mission_id: str) -> dict:
    project_root = _copy_project(
        repo_root / "tests" / "_proof_fixtures" / "plain_folder" / "forecast-rough-notes",
        smoke_root,
    )
    before_paths = _snapshot_project_files(project_root)
    _cleanup_mission_artifacts(mission_id, remove_discovery_config=True)
    discovery_config_path = _discovery_config_path(mission_id)
    completed = _run_capture(
        [
            "deeploop-init-mission",
            "--discover",
            "--project-root",
            str(project_root),
            "--mission-id",
            mission_id,
            "--force",
        ],
        input_text="\n".join(["", "", "", "", "", "", "", "", "y"]) + "\n",
    )
    if "mission-init: used confirmed discovery config" not in completed.stdout:
        raise SystemExit("docker-smoke: discovery-first bootstrap did not report the confirmed discovery config")
    if not discovery_config_path.exists():
        raise SystemExit(f"docker-smoke: missing discovery config: {discovery_config_path}")

    state_path = _mission_root(mission_id) / "mission_state.json"
    if not state_path.exists():
        raise SystemExit(f"docker-smoke: missing mission state: {state_path}")
    mission_state = json.loads(state_path.read_text(encoding="utf-8"))
    readiness = mission_state.get("mission_contract", {}).get("readiness", {})

    if mission_state.get("status") != "initialized":
        raise SystemExit(
            f"docker-smoke: expected discovery mission status `initialized`, got {mission_state.get('status')!r}"
        )
    if mission_state.get("project_contract", {}).get("status") != "plain-artifacts":
        raise SystemExit("docker-smoke: expected discovery mission plain-artifacts project contract")
    _assert_mission_state_targets_project(mission_state, project_root)
    if readiness.get("status") != "ready-with-defaults":
        raise SystemExit("docker-smoke: expected discovery mission readiness `ready-with-defaults`")
    if readiness.get("launch_recommendation") != "launch-with-disclosed-defaults":
        raise SystemExit(
            "docker-smoke: expected discovery mission launch recommendation `launch-with-disclosed-defaults`"
        )
    if mission_state.get("human_inputs", {}).get("mission_discovery", {}).get("mode") != "interactive":
        raise SystemExit("docker-smoke: expected discovery mission to record interactive discovery answers")
    available_assets = mission_state.get("human_inputs", {}).get("mission_discovery", {}).get("answers", {}).get(
        "available_assets",
        "",
    )
    if "data/store_demand_sample.csv" not in available_assets:
        raise SystemExit("docker-smoke: discovery mission did not preserve the expected asset hints")
    _assert_project_unmutated(project_root, before_paths)

    return {
        "workflow": "forecast-rough-notes-discovery",
        "project_root": str(project_root),
        "mission_state_path": str(state_path),
        "mission_status": mission_state.get("status"),
        "readiness_status": readiness.get("status"),
        "launch_recommendation": readiness.get("launch_recommendation"),
        "discovery_config_path": str(discovery_config_path),
        "discovery_mode": mission_state.get("human_inputs", {}).get("mission_discovery", {}).get("mode"),
    }


def _run_partial_project_folder_repair_smoke(repo_root: Path, smoke_root: Path, *, mission_id: str) -> dict:
    project_root = smoke_root / "partial-project-folder"
    _write_partial_project_folder(project_root)
    before_paths = _snapshot_project_files(project_root)
    completed, payload = _run_json_capture(
        _deeploop_command(
            "run",
            "--project-root",
            str(project_root),
            "--mission-id",
            mission_id,
            "--force",
            "--until-complete",
        ),
        expected_returncode=1,
    )
    stderr = completed.stderr
    if payload.get("status") != "bootstrap-repair-required":
        raise SystemExit("docker-smoke: partial project repair smoke did not return the repair status")
    repair = payload.get("bootstrap_repair") if isinstance(payload.get("bootstrap_repair"), dict) else {}
    if str(repair.get("reason") or "") != "missing-bootstrap-contract":
        raise SystemExit("docker-smoke: partial project repair smoke did not report the expected repair reason")
    required_markers = ["could not bootstrap this project root", "missing-bootstrap-contract", "project-facts.yaml"]
    if any(marker.lower() not in stderr.lower() for marker in required_markers):
        raise SystemExit("docker-smoke: partial project repair smoke missed the expected repair diagnostics")
    detected_inputs = repair.get("detected_inputs") if isinstance(repair.get("detected_inputs"), dict) else {}
    detected_data = detected_inputs.get("data") if isinstance(detected_inputs.get("data"), list) else []
    if not any(str(item.get("path") or "") == "data/store_snapshot.csv" for item in detected_data if isinstance(item, dict)):
        raise SystemExit("docker-smoke: partial project repair smoke did not preserve the detected dataset input")
    if (project_root / ".deeploop").exists():
        raise SystemExit("docker-smoke: partial project repair unexpectedly wrote local .deeploop state")
    _assert_project_unmutated(project_root, before_paths)

    return {
        "workflow": "partial-project-folder-repair",
        "project_root": str(project_root),
        "repair_exit_code": completed.returncode,
        "repair_signal": repair.get("reason"),
        "starter_scaffold_path": repair.get("starter_scaffold_path"),
        "expected_target_path": repair.get("starter_target_path"),
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, payloads: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(payload) + "\n" for payload in payloads), encoding="utf-8")


def _operator_handoff_request(mission_state_path: Path, *, mission_id: str) -> dict:
    return {
        "schema_version": 1,
        "request_id": "docker-smoke-operator-request",
        "mission_id": mission_id,
        "created_at": "2026-04-12T20:01:00Z",
        "status": "open",
        "summary": "Autopilot paused at `sandbox-boundary`: attempted write outside mutable roots.",
        "explanation": "DeepLoop stopped because the requested write crossed the sandbox boundary.",
        "blocker": {
            "kind": "hard-gate",
            "gate": "hard",
            "risk_class": "sandbox-boundary",
            "label": "sandbox escape / writes outside allowed mutable roots",
            "reason": "attempted write outside mutable roots",
            "default_response": "stop-and-escalate",
            "preferred_actions": [],
            "hard_gate_profile": "minimal",
        },
        "context": {
            "mission_state_path": str(mission_state_path),
            "runtime_root": str(mission_state_path.parent / "runtime" / "mission_outer_runtime"),
            "mode": "sandboxed-yolo",
            "phase": "execution",
            "next_phase": "critique",
            "decision_id": "docker-smoke-decision",
            "decision_type": "local-eval",
            "action_id": "run-baseline",
            "action_kind": "local-eval",
            "action_task": "Run the bounded baseline evaluation.",
            "branch_id": None,
            "executor_id": "stage-kernel",
        },
        "recommendation": {
            "summary": "Adjust the write target so the action stays inside the sandbox, then resume autopilot.",
            "pros": ["Keeps the default safety posture."],
            "cons": ["Requires a quick operator review."],
        },
        "alternatives": [
            {
                "option_id": "adjust-and-resume",
                "summary": "Keep the action inside the sandbox.",
                "pros": ["Preserves sandboxed-yolo."],
                "cons": ["May require a smaller change."],
                "next_steps": [f"deeploop resume --mission-state {mission_state_path}"],
            }
        ],
        "next_steps": [
            f"deeploop inbox --mission-state {mission_state_path}",
            f"deeploop resume --mission-state {mission_state_path}",
        ],
        "continue_command": f"deeploop resume --mission-state {mission_state_path}",
    }


def _run_operator_handoff_surface_smoke(*, mission_id: str) -> dict:
    _cleanup_mission_artifacts(mission_id)
    mission_root = _mission_root(mission_id)
    state_path = mission_root / "mission_state.json"
    mission_state = {
        "mission_id": mission_id,
        "mode": "sandboxed-yolo",
        "title": "Docker validation operator handoff",
        "current_phase": "execution",
        "next_phase": "critique",
        "status": "blocked",
        "autonomy_status": {"state": "paused", "reason": "sandbox boundary"},
        "next_actions": {"summary": "Adjust the sandbox target.", "actions": []},
    }
    request = _operator_handoff_request(state_path, mission_id=mission_id)
    _write_json(state_path, mission_state)
    _write_json(mission_root / "current_operator_request.json", request)
    _write_jsonl(mission_root / "mission_operator_requests.jsonl", [request])
    _write_jsonl(
        mission_root / "ledger.jsonl",
        [{"timestamp": "2026-04-12T20:00:00Z", "actor": "mission-runtime", "event": "blocked", "status": "blocked"}],
    )

    status_completed = _run_capture(_deeploop_command("status", "--mission-state", str(state_path), "--full"))
    inbox_completed = _run_capture(_deeploop_command("inbox", "--mission-state", str(state_path), "--full"))
    if "PAUSED — DeepLoop needs an operator decision before it can continue." not in status_completed.stdout:
        raise SystemExit("docker-smoke: status did not render the expected paused operator handoff")
    if f"deeploop status --mission-state {state_path}" not in status_completed.stdout:
        raise SystemExit("docker-smoke: status did not surface the primary operator loop")
    if f"deeploop inbox --mission-state {state_path}" not in status_completed.stdout:
        raise SystemExit("docker-smoke: status did not surface the inbox command")
    if f"deeploop resume --mission-state {state_path}" not in status_completed.stdout:
        raise SystemExit("docker-smoke: status did not surface the resume command")
    if "## Current request" not in inbox_completed.stdout:
        raise SystemExit("docker-smoke: inbox did not render the current operator request")
    if "attempted write outside mutable roots" not in inbox_completed.stdout:
        raise SystemExit("docker-smoke: inbox did not preserve the blocker summary")
    if f"deeploop resume --mission-state {state_path}" not in inbox_completed.stdout:
        raise SystemExit("docker-smoke: inbox did not surface the request-specific resume command")

    return {
        "workflow": "operator-handoff-surface",
        "mission_state_path": str(state_path),
        "continue_command": request["continue_command"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the provider-free DeepLoop install smoke inside the release-validation container.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--repo-root", required=True, help="Path to the repo checkout copied into the container.")
    parser.add_argument("--install-source", choices=("wheel", "pypi"), required=True, help="How DeepLoop was installed in this container.")
    parser.add_argument("--install-spec", help="Optional requirement spec used for PyPI validation.")
    parser.add_argument("--mission-id", default="docker-release-validation", help="Deterministic mission id for the smoke init step.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.exists():
        raise SystemExit(f"docker-smoke: missing repo root: {repo_root}")

    expected_version = _expected_version_from_install_spec(args.install_spec)
    installed_version = importlib.metadata.version("deeploop")
    if expected_version is not None and installed_version != expected_version:
        raise SystemExit(
            f"docker-smoke: installed deeploop version {installed_version} does not match requested {expected_version}"
        )

    for path in EXPECTED_EXTERNAL_DIRS:
        path.mkdir(parents=True, exist_ok=True)

    smoke_root = _release_validation_smoke_root()
    shutil.rmtree(smoke_root, ignore_errors=True)
    smoke_root.mkdir(parents=True, exist_ok=True)

    help_commands = [
        _deeploop_command("--help"),
        _deeploop_command("run", "--help"),
        _deeploop_command("provider-ready", "--help"),
        _deeploop_command("status", "--help"),
        _deeploop_command("inbox", "--help"),
        _deeploop_command("resume", "--help"),
        ["deeploop-init-mission", "--help"],
        ["deeploop-package-mission", "--help"],
        ["deeploop-analyze", "--help"],
    ]
    for command in help_commands:
        _run(command)

    smoke_cases = [
        _run_zero_start_bundled_starter_provider_gate_smoke(
            mission_id=f"{args.mission_id}-zero-start",
        ),
        _run_translation_bootstrap(repo_root, smoke_root, mission_id=args.mission_id),
        _run_literature_operator_package_smoke(
            repo_root,
            smoke_root,
            mission_id=f"{args.mission_id}-literature",
        ),
        _run_messy_plain_folder_smoke(
            repo_root,
            smoke_root,
            mission_id=f"{args.mission_id}-messy-notes",
        ),
        _run_discovery_first_plain_folder_smoke(
            repo_root,
            smoke_root,
            mission_id=f"{args.mission_id}-discovery",
        ),
        _run_partial_project_folder_repair_smoke(
            repo_root,
            smoke_root,
            mission_id=f"{args.mission_id}-repair",
        ),
        _run_operator_handoff_surface_smoke(
            mission_id=f"{args.mission_id}-operator-handoff",
        ),
    ]

    summary = {
        "install_source": args.install_source,
        "install_spec": args.install_spec,
        "installed_version": installed_version,
        "workspace_root": str(WORKSPACE_ROOT),
        "cases": smoke_cases,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
