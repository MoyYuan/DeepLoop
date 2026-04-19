from __future__ import annotations

import argparse
import json
from pathlib import Path

from deeploop.artifacts.artifact_packager import package_mission_artifacts
from deeploop.core.paths import REPO_ROOT


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission-state", required=True)
    parser.add_argument("--contract")
    args = parser.parse_args()

    result = package_mission_artifacts(
        Path(args.mission_state).expanduser().resolve(),
        contract_path=Path(args.contract).expanduser().resolve()
        if args.contract
        else REPO_ROOT / "configs" / "runtime" / "artifact-package-contract.yaml",
    )
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, indent=2))
    return 0


__all__ = ["main"]
