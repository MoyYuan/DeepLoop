from __future__ import annotations

import argparse
import importlib.metadata
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from deeploop.core.paths import EXPECTED_EXTERNAL_DIRS, MISSIONS_DIR, WORKSPACE_ROOT


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    print(f"+ {shlex.join(command)}", flush=True)
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.returncode != 0:
        if completed.stderr:
            print(completed.stderr.rstrip(), file=sys.stderr)
        raise SystemExit(completed.returncode)
    return completed


def _copy_example(repo_root: Path, destination_root: Path) -> Path:
    source = repo_root / "examples" / "translation-budget-ladder"
    if not source.exists():
        raise SystemExit(f"docker-smoke: missing example project: {source}")
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

    smoke_root = WORKSPACE_ROOT / "docker-validation"
    smoke_root.mkdir(parents=True, exist_ok=True)
    project_root = _copy_example(repo_root, smoke_root)
    before_paths = _snapshot_project_files(project_root)

    help_commands = [
        ["deeploop", "--help"],
        ["deeploop-init-mission", "--help"],
        ["deeploop-run-project", "--help"],
        ["deeploop-package-mission", "--help"],
        ["deeploop-analyze", "--help"],
    ]
    for command in help_commands:
        _run(command)

    mission_root = MISSIONS_DIR / args.mission_id
    shutil.rmtree(mission_root, ignore_errors=True)
    _run(
        [
            "deeploop-init-mission",
            "--project-root",
            str(project_root),
            "--mission-id",
            args.mission_id,
            "--force",
        ]
    )

    state_path = mission_root / "mission_state.json"
    if not state_path.exists():
        raise SystemExit(f"docker-smoke: missing mission state: {state_path}")
    mission_state = json.loads(state_path.read_text(encoding="utf-8"))
    after_paths = _snapshot_project_files(project_root)
    if before_paths != after_paths:
        raise SystemExit("docker-smoke: project-root bootstrap mutated the example project")
    if mission_state.get("status") not in {"initialized", "ready"}:
        raise SystemExit(
            f"docker-smoke: expected mission status `initialized` or `ready`, got {mission_state.get('status')!r}"
        )
    if mission_state.get("project_contract", {}).get("status") != "plain-artifacts":
        raise SystemExit("docker-smoke: expected plain-artifacts project contract in mission state")
    if Path(mission_state.get("target_repo", "")).resolve() != project_root.resolve():
        raise SystemExit("docker-smoke: mission state target_repo did not match the copied example project")

    summary = {
        "install_source": args.install_source,
        "install_spec": args.install_spec,
        "installed_version": installed_version,
        "workspace_root": str(WORKSPACE_ROOT),
        "mission_state_path": str(state_path),
        "project_root": str(project_root),
        "mission_status": mission_state.get("status"),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
