from __future__ import annotations

import argparse
import json
from pathlib import Path


def _manifest(output_dir: Path) -> dict:
    timestamp = "2026-04-12T00:00:00+00:00"
    return {
        "schema_version": 1,
        "project": "demo-substrate",
        "mode": "sandboxed-yolo",
        "loop_id": "resume-helper-loop",
        "claim_state": "exploratory",
        "mission_id": "runtime-test-mission",
        "resource_tier": "cpu-smoke",
        "execution_profile": "resume-helper",
        "code": {"repo": str(output_dir), "git_commit": "nogit"},
        "model": {
            "family": "mock",
            "identifier": "mock://entailment",
            "backend": "mock-entailment",
            "dtype": "none",
        },
        "dataset": {"name": "demo-runtime-dataset", "slice": "dev:iid", "provenance": str(output_dir / "promotion_manifest.json")},
        "prompt": {"template_id": "demo_prompt_v1", "parser_id": "demo_parser_v1"},
        "run": {
            "seed": 0,
            "command": "runtime_resume_helper.py",
            "started_at": timestamp,
            "completed_at": timestamp,
            "status": "completed",
        },
        "metrics": {"count": 8, "accuracy": 0.75},
        "artifacts": {"log_path": None, "output_dir": str(output_dir), "report_paths": []},
        "notes": ["Manifest written by runtime resume helper."],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest).expanduser()
    counter_path = output_dir / ".resume-attempt"
    attempt = int(counter_path.read_text(encoding="utf-8")) + 1 if counter_path.exists() else 1
    counter_path.write_text(str(attempt), encoding="utf-8")

    if attempt == 1:
        (output_dir / "partial-output.json").write_text(json.dumps({"attempt": attempt}) + "\n", encoding="utf-8")
        return 0

    manifest_path.write_text(json.dumps(_manifest(output_dir), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
