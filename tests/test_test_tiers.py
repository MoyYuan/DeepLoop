from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.testing.test_tiers import TIER_DESCRIPTIONS, available_tiers, test_ids_for_tier


class TestTierDefinitionsTests(unittest.TestCase):
    def test_all_canonical_tiers_are_present(self) -> None:
        self.assertEqual(available_tiers(), ("unit", "integration", "smoke", "real"))
        self.assertIn("unit", TIER_DESCRIPTIONS)
        self.assertIn("integration", TIER_DESCRIPTIONS)
        self.assertIn("smoke", TIER_DESCRIPTIONS)
        self.assertIn("real", TIER_DESCRIPTIONS)

    def test_tier_assignments_are_non_empty_and_disjoint(self) -> None:
        tier_map = {tier: set(test_ids_for_tier(tier)) for tier in available_tiers()}
        for tier, test_ids in tier_map.items():
            self.assertTrue(test_ids, f"expected non-empty tier: {tier}")
        tiers = list(tier_map)
        for index, left in enumerate(tiers):
            for right in tiers[index + 1 :]:
                self.assertFalse(tier_map[left] & tier_map[right], f"tiers overlap: {left}, {right}")

    def test_known_examples_land_in_expected_tiers(self) -> None:
        self.assertIn(
            "test_mission_runtime.MissionRuntimeTests.test_runtime_surfaces_blocked_queue_entry_details_in_operator_request",
            test_ids_for_tier("integration"),
        )
        self.assertIn(
            "test_end_to_end_smoke.EndToEndSmokeTests.test_end_to_end_smoke_runs_followups_and_packages",
            test_ids_for_tier("smoke"),
        )
        self.assertIn(
            "test_end_to_end_smoke.EndToEndSmokeTests.test_long_run_profile_stages_canonical_followups_with_real_backend",
            test_ids_for_tier("real"),
        )
        self.assertIn(
            "test_end_to_end_smoke.EndToEndSmokeTests.test_acceptance_campaign_materializes_green_review",
            test_ids_for_tier("real"),
        )


if __name__ == "__main__":
    unittest.main()
