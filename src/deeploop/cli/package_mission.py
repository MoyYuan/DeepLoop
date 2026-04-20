from __future__ import annotations

import argparse
import json
from pathlib import Path

from deeploop.artifacts.artifact_packager import package_mission_artifacts
from deeploop.core.paths import REPO_ROOT


def _add_package_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mission-state", required=True, help="Path to the mission state JSON.")
    parser.add_argument("--contract", help="Path to an explicit artifact-package contract YAML.")


def _package_mission(args: argparse.Namespace) -> int:
    result = package_mission_artifacts(
        Path(args.mission_state).expanduser().resolve(),
        contract_path=Path(args.contract).expanduser().resolve()
        if getattr(args, "contract", None)
        else REPO_ROOT / "configs" / "runtime" / "artifact-package-contract.yaml",
    )
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    _add_package_args(parser)
    args = parser.parse_args()
    return _package_mission(args)


__all__ = ["main", "_add_package_args", "_package_mission"]
