from __future__ import annotations

import argparse
from pathlib import Path

from deeploop.core.paths import SCRATCH_DIR
from deeploop.core.structured_io import write_text, write_yaml_mapping
from deeploop.mission.orchestrator import initialize_mission
from deeploop.mission.project_bootstrap import build_mission_config_from_project_root


def main() -> int:
    parser = argparse.ArgumentParser()
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--config")
    source_group.add_argument("--project-root")
    parser.add_argument("--mission-id")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.project_root:
        project_root = Path(args.project_root).expanduser().resolve()
        generated_config = build_mission_config_from_project_root(project_root, mission_id=args.mission_id)
        generated_config_dir = SCRATCH_DIR / "mission_bootstrap_configs"
        generated_config_dir.mkdir(parents=True, exist_ok=True)
        generated_config_path = generated_config_dir / f"{generated_config['mission']['id']}.yaml"
        write_yaml_mapping(generated_config_path, generated_config)
        result = initialize_mission(generated_config_path, force=args.force)
        persisted_config_path = Path(result["mission_root"]) / "generated_mission_config.yaml"
        write_text(persisted_config_path, generated_config_path.read_text(encoding="utf-8"))
        print(f"mission-init: bootstrapped mission config from project folder {project_root}")
        print(f"mission-init: wrote generated config to {persisted_config_path}")
    else:
        result = initialize_mission(Path(args.config).expanduser().resolve(), force=args.force)

    print(f"mission-init: wrote state to {result['state_path']}")
    print(f"mission-init: wrote summary to {result['summary_path']}")
    print(f"mission-init: wrote ledger to {result['ledger_path']}")
    return 0


__all__ = ["main"]
