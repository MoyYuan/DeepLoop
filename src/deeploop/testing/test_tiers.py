from __future__ import annotations

from functools import lru_cache
import sys
import unittest

from deeploop.core.paths import REPO_ROOT

TESTS_DIR = REPO_ROOT / "tests"

TIER_DESCRIPTIONS: dict[str, str] = {
    "unit": "Fast local-logic and invariant tests.",
    "integration": "Mocked integration tests for runtime wiring and operator surfaces.",
    "smoke": "Tiny real smoke tests with genuine artifacts and bounded sample sizes.",
    "real": "Bounded real proofs for long-run or production-like mission behavior.",
}

INTEGRATION_MODULES = frozenset(
    {
        "test_adaptation_training_runtime",
        "test_mission_executor_registry",
        "test_mission_management",
        "test_mission_monitor",
        "test_mission_runtime",
        "test_platform_integration",
        "test_recursive_agent_runtime",
        "test_runtime_recovery",
        "test_self_healing_runtime",
    }
)

SMOKE_TEST_IDS = frozenset(
    {
        "test_end_to_end_smoke.EndToEndSmokeTests.test_canonical_runtime_starts_without_missing_executor_block",
        "test_end_to_end_smoke.EndToEndSmokeTests.test_discovery_first_plain_folder_flow_handles_rough_notes_without_mutation",
        "test_end_to_end_smoke.EndToEndSmokeTests.test_end_to_end_smoke_runs_followups_and_packages",
        "test_end_to_end_smoke.EndToEndSmokeTests.test_messy_plain_folder_bootstrap_handles_rough_notes_and_packages_without_mutation",
        "test_end_to_end_smoke.EndToEndSmokeTests.test_mission_advance_generates_runtime_owned_followup_queue",
        "test_end_to_end_smoke.EndToEndSmokeTests.test_nontranslation_plain_folder_bootstrap_records_operator_blockers_and_packages",
        "test_end_to_end_smoke.EndToEndSmokeTests.test_partial_project_folder_bootstrap_surfaces_repair_without_mutation",
    }
)

REAL_TEST_IDS = frozenset(
    {
        "test_end_to_end_smoke.EndToEndSmokeTests.test_acceptance_campaign_materializes_green_review",
        "test_end_to_end_smoke.EndToEndSmokeTests.test_long_run_profile_stages_canonical_followups_with_real_backend",
        "test_repo_contract.RepoContractTests.test_mission_advance_and_meta_eval_scripts_run",
        "test_repo_contract.RepoContractTests.test_mission_init_script_materializes_mission_bundle",
        "test_repo_contract.RepoContractTests.test_mission_package_script_runs",
    }
)


def _module_name(test_id: str) -> str:
    return test_id.split(".", 1)[0]


def _iter_cases(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    cases: list[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            cases.extend(_iter_cases(item))
        else:
            cases.append(item)
    return cases


@lru_cache(maxsize=1)
def _discover_test_ids() -> tuple[str, ...]:
    repo_root_text = str(REPO_ROOT)
    tests_dir_text = str(TESTS_DIR)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)
    if tests_dir_text not in sys.path:
        sys.path.insert(0, tests_dir_text)
    loader = unittest.defaultTestLoader
    suite = loader.discover(start_dir="tests", pattern="test_*.py")
    return tuple(case.id() for case in _iter_cases(suite))


@lru_cache(maxsize=1)
def _tier_membership() -> dict[str, list[str]]:
    discovered = list(_discover_test_ids())
    smoke = [test_id for test_id in discovered if test_id in SMOKE_TEST_IDS]
    real = [test_id for test_id in discovered if test_id in REAL_TEST_IDS]
    smoke_or_real = set(smoke) | set(real)
    integration = [
        test_id
        for test_id in discovered
        if _module_name(test_id) in INTEGRATION_MODULES and test_id not in smoke_or_real
    ]
    unit = [test_id for test_id in discovered if test_id not in set(integration) | smoke_or_real]
    return {
        "unit": unit,
        "integration": integration,
        "smoke": smoke,
        "real": real,
    }


def available_tiers() -> tuple[str, ...]:
    return tuple(TIER_DESCRIPTIONS.keys())


def test_ids_for_tier(tier: str) -> list[str]:
    normalized = str(tier).strip().lower()
    if normalized not in TIER_DESCRIPTIONS:
        expected = ", ".join(available_tiers())
        raise ValueError(f"Unknown test tier `{tier}`. Expected one of: {expected}.")
    return _tier_membership()[normalized]


__all__ = [
    "TIER_DESCRIPTIONS",
    "available_tiers",
    "test_ids_for_tier",
]
