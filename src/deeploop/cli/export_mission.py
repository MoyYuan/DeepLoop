from __future__ import annotations

import argparse
import json
from pathlib import Path

from deeploop.artifacts.submission_export import SUPPORTED_EXPORT_FORMATS, export_submission_repository
from deeploop.core.paths import REPO_ROOT


def _add_export_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mission-state", required=True, help="Path to the mission state JSON.")
    parser.add_argument("--output", required=True, help="Destination folder for the self-contained submission repo.")
    parser.add_argument(
        "--format",
        default="github-repo",
        choices=SUPPORTED_EXPORT_FORMATS,
        help="Submission export layout to materialize.",
    )
    parser.add_argument("--contract", help="Path to an explicit artifact-package contract YAML.")
    parser.add_argument("--force", action="store_true", help="Replace an existing non-empty output folder.")


def _export_mission(args: argparse.Namespace) -> int:
    result = export_submission_repository(
        Path(args.mission_state).expanduser().resolve(),
        Path(args.output).expanduser().resolve(),
        export_format=args.format,
        contract_path=Path(args.contract).expanduser().resolve()
        if getattr(args, "contract", None)
        else REPO_ROOT / "configs" / "runtime" / "artifact-package-contract.yaml",
        force=bool(getattr(args, "force", False)),
    )
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    _add_export_args(parser)
    args = parser.parse_args()
    return _export_mission(args)


__all__ = ["main", "_add_export_args", "_export_mission"]
