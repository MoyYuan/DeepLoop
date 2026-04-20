from __future__ import annotations

import argparse
from pathlib import Path

from deeploop.core.paths import SCRATCH_DIR
from deeploop.core.structured_io import write_text, write_yaml_mapping
from deeploop.mission.orchestrator import initialize_mission
from deeploop.mission.project_bootstrap import build_mission_config_from_project_root


def _add_init_args(parser: argparse.ArgumentParser) -> None:
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--config", help="Path to an explicit mission config YAML.")
    source_group.add_argument("--project-root", help="Path to the plain researcher project folder.")
    parser.add_argument("--mission-id", help="Optional override for the generated mission id.")
    parser.add_argument("--force", action="store_true", help="Replace any existing mission root with the same mission id.")


def _init_mission(args: argparse.Namespace) -> int:
    if getattr(args, "project_root", None):
        project_root = Path(args.project_root).expanduser().resolve()
        generated_config = build_mission_config_from_project_root(project_root, mission_id=getattr(args, "mission_id", None))
        generated_config_dir = SCRATCH_DIR / "mission_bootstrap_configs"
        generated_config_dir.mkdir(parents=True, exist_ok=True)
        generated_config_path = generated_config_dir / f"{generated_config['mission']['id']}.yaml"
        write_yaml_mapping(generated_config_path, generated_config)
        result = initialize_mission(generated_config_path, force=getattr(args, "force", False))
        persisted_config_path = Path(result["mission_root"]) / "generated_mission_config.yaml"
        write_text(persisted_config_path, generated_config_path.read_text(encoding="utf-8"))
        print(f"mission-init: bootstrapped mission config from project folder {project_root}")
        print(f"mission-init: wrote generated config to {persisted_config_path}")
    else:
        result = initialize_mission(Path(args.config).expanduser().resolve(), force=getattr(args, "force", False))

    print(f"mission-init: wrote state to {result['state_path']}")
    print(f"mission-init: wrote summary to {result['summary_path']}")
    print(f"mission-init: wrote ledger to {result['ledger_path']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    _add_init_args(parser)
    args = parser.parse_args()
    return _init_mission(args)


__all__ = ["main", "_add_init_args", "_init_mission"]
