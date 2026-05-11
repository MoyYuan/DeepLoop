from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deeploop.core.paths import SCRATCH_DIR, WORKSPACE_ROOT, WORKSPACE_ROOT_ENV_VAR, workspace_root_diagnostics
from deeploop.core.structured_io import write_text, write_yaml_mapping
from deeploop.mission.mission_discovery import run_interactive_discovery
from deeploop.mission.orchestrator import initialize_mission
from deeploop.mission.project_bootstrap import (
    build_mission_config_from_project_root,
    render_bootstrap_repair_lines,
    render_mission_contract_summary_lines,
    resolve_project_root_for_bootstrap,
)


def _add_init_args(parser: argparse.ArgumentParser) -> None:
    parser.epilog = (
        f"Workspace root: set {WORKSPACE_ROOT_ENV_VAR} before init/start to choose where "
        "DeepLoop writes mission, run, scratch, ledger, and package artifacts."
    )
    parser.add_argument("--config", help="Path to an explicit mission config YAML.")
    parser.add_argument("--project-root", help="Path to the plain researcher project folder.")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Start an interactive pre-mission discovery flow before autonomous kickoff.",
    )
    parser.add_argument(
        "--mission-idea",
        help="Optional rough natural-language starting point for --discover mode.",
    )
    parser.add_argument("--mission-id", help="Optional override for the generated mission id.")
    parser.add_argument("--force", action="store_true", help="Replace any existing mission root with the same mission id.")


def _print_readiness_summary(config: dict[str, object]) -> None:
    mission_contract = config.get("mission_contract") if isinstance(config.get("mission_contract"), dict) else {}
    if not mission_contract:
        return
    for line in render_mission_contract_summary_lines(mission_contract, format="plain"):
        print(f"mission-init: {line}" if line else "mission-init:")


def _init_mission(args: argparse.Namespace) -> int:
    has_config = bool(getattr(args, "config", None))
    has_project_root = bool(getattr(args, "project_root", None))
    discover = bool(getattr(args, "discover", False))
    if discover and has_config:
        print(
            "mission-init: --discover generates a config interactively; use --config to initialize from an existing config file instead",
            file=sys.stderr,
        )
        return 2
    if not discover and not has_config and not has_project_root:
        print("mission-init: supply --config or --project-root, or use --discover", file=sys.stderr)
        return 2
    if not discover and has_config and has_project_root:
        print(
            "mission-init: --config and --project-root cannot be used together; use --discover if you want an interactive project-root bootstrap",
            file=sys.stderr,
        )
        return 2
    if getattr(args, "mission_idea", None) and not discover:
        print("mission-init: --mission-idea is only supported with --discover", file=sys.stderr)
        return 2

    project_root = None
    try:
        if discover:
            if has_project_root:
                project_root = resolve_project_root_for_bootstrap(Path(args.project_root))
            discovery = run_interactive_discovery(
                mission_id=getattr(args, "mission_id", None),
                mission_idea=getattr(args, "mission_idea", None),
                project_root=project_root,
            )
            if discovery.get("cancelled") and not discovery.get("config_path"):
                print("mission-init: discovery cancelled before kickoff")
                return 0
            if not discovery["confirmed"]:
                print(f"mission-init: discovery saved compiled config to {discovery['config_path']}")
                print("mission-init: kickoff cancelled; edit the compiled config and re-run when ready")
                return 0
            result = initialize_mission(Path(discovery["config_path"]).expanduser().resolve(), force=getattr(args, "force", False))
            persisted_config_path = Path(result["mission_root"]) / "generated_mission_config.yaml"
            write_text(persisted_config_path, Path(discovery["config_path"]).read_text(encoding="utf-8"))
            print(f"mission-init: used confirmed discovery config {discovery['config_path']}")
            print(f"mission-init: wrote generated config to {persisted_config_path}")
            _print_readiness_summary(discovery["config"])
        elif has_project_root:
            project_root = resolve_project_root_for_bootstrap(Path(args.project_root))
            generated_config = build_mission_config_from_project_root(project_root, mission_id=getattr(args, "mission_id", None))
            bootstrap_repair = (
                generated_config.get("bootstrap_repair") if isinstance(generated_config.get("bootstrap_repair"), dict) else None
            )
            if isinstance(bootstrap_repair, dict) and str(bootstrap_repair.get("status") or "").strip().lower() == "required":
                print(f"mission-init: project-root bootstrap needs repair for {project_root}", file=sys.stderr)
                for line in render_bootstrap_repair_lines(bootstrap_repair, format="plain"):
                    print(f"mission-init: {line}" if line else "mission-init:", file=sys.stderr)
                return 2
            generated_config_dir = SCRATCH_DIR / "mission_bootstrap_configs"
            generated_config_dir.mkdir(parents=True, exist_ok=True)
            generated_config_path = generated_config_dir / f"{generated_config['mission']['id']}.yaml"
            write_yaml_mapping(generated_config_path, generated_config)
            result = initialize_mission(generated_config_path, force=getattr(args, "force", False))
            persisted_config_path = Path(result["mission_root"]) / "generated_mission_config.yaml"
            write_text(persisted_config_path, generated_config_path.read_text(encoding="utf-8"))
            print(f"mission-init: bootstrapped mission config from project folder {project_root}")
            print(f"mission-init: wrote generated config to {persisted_config_path}")
            _print_readiness_summary(generated_config)
        else:
            result = initialize_mission(Path(args.config).expanduser().resolve(), force=getattr(args, "force", False))
    except (FileNotFoundError, ValueError) as exc:
        print(f"mission-init: {exc}", file=sys.stderr)
        return 2

    print(f"mission-init: workspace root is {WORKSPACE_ROOT} (override with {WORKSPACE_ROOT_ENV_VAR})")
    for diagnostic in workspace_root_diagnostics(project_root):
        print(f"mission-init: WARNING: {diagnostic}")
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
