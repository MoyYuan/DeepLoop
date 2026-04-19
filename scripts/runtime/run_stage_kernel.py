from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.stage_kernels import get_stage_registry, run_stage_from_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=sorted(get_stage_registry()), required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--adapter", required=True, help="module.path:factory")
    parser.add_argument("--pythonpath", action="append", default=[])
    parser.add_argument("--json", action="store_true", dest="emit_json")
    args = parser.parse_args()

    for raw_path in args.pythonpath:
        resolved = str(Path(raw_path).expanduser())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)

    result = run_stage_from_config(
        args.stage,
        Path(args.config).resolve(),
        adapter_spec=args.adapter,
    )
    payload = {
        "stage_id": result.stage_id,
        "status": result.status,
        "output_dir": str(result.output_dir),
        "manifest_path": str(result.manifest_path),
        "summary_path": str(result.summary_path) if result.summary_path is not None else None,
        "artifacts": {name: str(path) for name, path in sorted(result.artifacts.items())},
    }
    if args.emit_json:
        print(json.dumps(payload))
        return 0
    print(f"{args.stage}: status {result.status}")
    if result.summary_path is not None:
        print(f"{args.stage}: summary -> {result.summary_path}")
    print(f"{args.stage}: manifest -> {result.manifest_path}")
    for name, path in sorted(result.artifacts.items()):
        if path == result.manifest_path or path == result.summary_path:
            continue
        print(f"{args.stage}: {name} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
