from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.runtime_recovery import run_stage_with_recovery
from deeploop.runtime.stage_kernels import get_stage_registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=sorted(get_stage_registry()), required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--mission-state")
    parser.add_argument("--pythonpath", action="append", default=[])
    parser.add_argument("--json", action="store_true", dest="emit_json")
    args = parser.parse_args()

    for raw_path in args.pythonpath:
        resolved = str(Path(raw_path).expanduser())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)

    result = run_stage_with_recovery(
        args.stage,
        Path(args.config).resolve(),
        adapter_spec=args.adapter,
        policy_path=Path(args.policy).resolve() if args.policy else REPO_ROOT / "configs" / "runtime" / "recovery-policy.yaml",
        mission_state_path=Path(args.mission_state).resolve() if args.mission_state else None,
    )
    payload = {
        "stage_id": result.stage_id,
        "status": result.status,
        "attempt_count": result.attempt_count,
        "output_dir": str(result.output_dir),
        "manifest_path": str(result.manifest_path),
        "summary_path": str(result.summary_path) if result.summary_path else None,
        "recovery_report_path": str(result.recovery_report_path),
        "recovery_history_path": str(result.recovery_history_path),
        "artifacts": {name: str(path) for name, path in sorted(result.artifacts.items())},
        "resumed": result.resumed,
    }
    if args.emit_json:
        print(json.dumps(payload))
        return 0
    print(f"{result.stage_id}: status {result.status}")
    print(f"{result.stage_id}: attempts {result.attempt_count}")
    print(f"{result.stage_id}: manifest -> {result.manifest_path}")
    print(f"{result.stage_id}: recovery_report -> {result.recovery_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
