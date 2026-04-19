from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.self_healing_runtime import run_self_healing_queue


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DeepLoop's bounded self-healing queue runtime.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    result = run_self_healing_queue(Path(args.config).resolve())
    print(f"queue-runtime: completed {result['completed_jobs']} job(s)")
    print(f"queue-runtime: blocked {result['blocked_jobs']} job(s)")
    print(f"queue-runtime: warned {result['warned_jobs']} job(s)")
    print(f"queue-runtime: failed {result.get('failed_jobs', 0)} job(s)")
    print(f"queue-runtime: recovered {result.get('recovered_jobs', 0)} job(s)")
    print(f"queue-runtime: rerouted {result.get('rerouted_jobs', 0)} job(s)")
    print(f"queue-runtime: resumed {result.get('resumed_jobs', 0)} attempt(s)")
    print(f"queue-runtime: ledger updated at {result['ledger_path']}")
    if "runtime_report_path" in result:
        print(f"queue-runtime: runtime report at {result['runtime_report_path']}")
    return 1 if result.get("failed_jobs", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
