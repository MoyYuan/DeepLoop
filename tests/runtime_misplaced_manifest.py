from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml


def _manifest(config: dict, output_dir: Path) -> dict:
    timestamp = "2026-05-01T00:00:00+00:00"
    run_cfg = config.get("run", {}) if isinstance(config.get("run"), dict) else {}
    model_cfg = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
    return {
        "schema_version": 1,
        "project": "demo-substrate",
        "mode": str(config.get("mode", "sandboxed-yolo")),
        "loop_id": str(run_cfg.get("loop_id", "misplaced-helper-loop")),
        "claim_state": str(config.get("claim_state", "exploratory")),
        "mission_id": str(config.get("mission_id", "runtime-test-mission")),
        "resource_tier": str(config.get("resource_tier", "cpu-smoke")),
        "execution_profile": str(config.get("execution_profile", "cpu-smoke")),
        "code": {"repo": str(output_dir), "git_commit": "nogit"},
        "model": {
            "family": str(model_cfg.get("family", "mock")),
            "identifier": str(model_cfg.get("identifier", "mock://entailment")),
            "backend": str(model_cfg.get("backend", "mock-entailment")),
            "dtype": str(model_cfg.get("dtype", "none")),
        },
        "dataset": {"name": "demo-runtime-dataset", "slice": "dev:iid", "provenance": str(output_dir / "promotion_manifest.json")},
        "prompt": {"template_id": "demo_prompt_v1", "parser_id": "demo_parser_v1"},
        "run": {
            "seed": 0,
            "command": "runtime_misplaced_manifest.py",
            "started_at": timestamp,
            "completed_at": timestamp,
            "status": "completed",
        },
        "metrics": {"count": 8, "accuracy": 0.75},
        "artifacts": {"log_path": None, "output_dir": str(output_dir), "report_paths": []},
        "notes": [f"Manifest written during {os.environ.get('DEEPLOOP_RUNTIME_RECOVERY_MODE', 'primary')}."],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--actual-manifest", required=True)
    parser.add_argument("--outside-manifest")
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"Expected mapping config in {args.config}")
    actual_manifest_path = Path(args.actual_manifest).expanduser()
    output_dir = actual_manifest_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = _manifest(config, output_dir)
    actual_manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.outside_manifest:
        outside_manifest_path = Path(args.outside_manifest).expanduser()
        outside_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        outside_manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
