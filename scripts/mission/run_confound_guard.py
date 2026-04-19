"""Standalone confound contamination guard runner."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.confound_guard import evaluate_confound_guard, DEFAULT_CONTRACT_PATH


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run confound contamination guard on a config"
    )
    parser.add_argument("--config", required=True, help="Path to config to analyze")
    parser.add_argument(
        "--mission-state",
        help="Path to mission state JSON for ledger integration",
    )
    parser.add_argument(
        "--artifact-name",
        default="confound-analysis",
        help="Name for output artifacts",
    )
    parser.add_argument(
        "--contract",
        help="Path to confound-guard contract YAML (default: configs/autonomy/confound-guard.yaml)",
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        print(f"error: config not found: {config_path}", file=sys.stderr)
        return 1

    mission_state_path = None
    if args.mission_state:
        mission_state_path = Path(args.mission_state).expanduser().resolve()
        if not mission_state_path.exists():
            print(f"error: mission state not found: {mission_state_path}", file=sys.stderr)
            return 1

    contract_path = None
    if args.contract:
        contract_path = Path(args.contract).expanduser().resolve()
        if not contract_path.exists():
            print(f"error: contract not found: {contract_path}", file=sys.stderr)
            return 1

    try:
        result = evaluate_confound_guard(
            config_path,
            mission_state_path=mission_state_path,
            artifact_name=args.artifact_name,
            contract_path=contract_path or DEFAULT_CONTRACT_PATH,
        )

        print(f"confound-guard: verdict={result['verdict']}")
        print(f"confound-guard: wrote {result['report_json_path']}")
        print(f"confound-guard: wrote {result['report_markdown_path']}")

        # Return success if pass/warn, fail if block
        return 0 if result["verdict"] in ("pass", "warn") else 1

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
