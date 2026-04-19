from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.testing.test_tiers import TIER_DESCRIPTIONS, available_tiers, test_ids_for_tier


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one of DeepLoop's canonical test tiers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--tier", choices=available_tiers(), help="Which canonical DeepLoop test tier to run.")
    parser.add_argument("--list", action="store_true", help="List available tiers and discovered test counts.")
    parser.add_argument("--failfast", action="store_true", help="Stop on the first failing test.")
    parser.add_argument("--verbosity", type=int, default=1, help="unittest runner verbosity.")
    args = parser.parse_args()

    if args.list:
        for tier in available_tiers():
            print(f"{tier}: {TIER_DESCRIPTIONS[tier]}")
            print(f"  tests: {len(test_ids_for_tier(tier))}")
        return 0

    if not args.tier:
        parser.error("--tier is required unless --list is used")

    test_ids = test_ids_for_tier(args.tier)
    if not test_ids:
        print(f"No tests are currently assigned to tier `{args.tier}`.", file=sys.stderr)
        return 1

    suite = unittest.defaultTestLoader.loadTestsFromNames(test_ids)
    result = unittest.TextTestRunner(verbosity=args.verbosity, failfast=args.failfast).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
