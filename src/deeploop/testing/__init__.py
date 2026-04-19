"""Testing helpers and canonical test-tier definitions for DeepLoop."""

from deeploop.testing.acceptance_campaigns import (
    DEFAULT_ACCEPTANCE_CAMPAIGN,
    build_acceptance_review,
    materialize_acceptance_review,
    render_acceptance_review_markdown,
)
from deeploop.testing.test_tiers import TIER_DESCRIPTIONS, available_tiers, test_ids_for_tier

__all__ = [
    "DEFAULT_ACCEPTANCE_CAMPAIGN",
    "TIER_DESCRIPTIONS",
    "available_tiers",
    "build_acceptance_review",
    "materialize_acceptance_review",
    "render_acceptance_review_markdown",
    "test_ids_for_tier",
]
