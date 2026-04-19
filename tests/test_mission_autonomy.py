from __future__ import annotations

from pathlib import Path
import shutil
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.autonomy.mission_contract_snapshot import (
    load_mission_contract_snapshot,
    materialize_mission_contract_snapshot,
    mission_contract_snapshot_path,
    resolve_phase_contract_for_state,
)
from deeploop.autonomy.mission_autonomy import (
    build_outer_loop_contract,
    load_mission_outer_loop_policy,
    resolve_phase_contract,
)
from deeploop.autonomy.gate_taxonomy import load_gate_policy, resolve_gate_contract
from deeploop.core.paths import MISSIONS_DIR


class MissionAutonomyTests(unittest.TestCase):
    def test_policy_defaults_to_sandboxed_yolo(self) -> None:
        policy = load_mission_outer_loop_policy()
        self.assertEqual(policy["default_mode"], "sandboxed-yolo")
        self.assertEqual(policy["mode_defaults"]["sandboxed-yolo"]["execution_mode"], "sandboxed-yolo")
        self.assertEqual(policy["mode_defaults"]["managed"]["intervention_profile"], "hook-enabled")
        self.assertIn("local-training", policy["action_classes"])
        self.assertTrue(policy["action_classes"]["external-publish"]["requires_operator_approval"])

    def test_gate_taxonomy_defaults_to_minimal_profile(self) -> None:
        policy = load_gate_policy()
        contract = resolve_gate_contract(mode="sandboxed-yolo", gates_policy=policy)
        self.assertEqual(policy["default_hard_gate_profile"], "minimal")
        self.assertEqual(contract["hard_gate_profile"], "minimal")
        self.assertIn("system-global-safety", contract["hard_gate_risk_classes"])
        self.assertIn("budget-overrun", contract["soft_gate_risk_classes"])
        self.assertEqual(contract["soft_gate_preferred_actions"], ["retry", "reroute", "downscope"])

    def test_build_outer_loop_contract_materializes_expected_defaults(self) -> None:
        mission_root = MISSIONS_DIR / "mission-autonomy-contract-smoke"
        mission_root.mkdir(parents=True, exist_ok=True)
        contract = build_outer_loop_contract(mission_root, mode="sandboxed-yolo")
        self.assertEqual(contract["mode"], "sandboxed-yolo")
        self.assertEqual(contract["permissions_profile"], "sandboxed")
        self.assertEqual(contract["intervention_profile"], "outcome-review")
        self.assertEqual(contract["external_publish"], "human-review-required")
        self.assertEqual(contract["hard_gate_profile"], "minimal")
        self.assertIn("sandbox-boundary", contract["hard_gate_risk_classes"])
        self.assertIn("quality-shortfall", contract["soft_gate_risk_classes"])
        self.assertIn("branch-create", contract["autonomous_action_kinds"])
        self.assertIn("research_memory_events_path", contract)
        self.assertIn("research_memory_index_path", contract)

    def test_build_outer_loop_contract_rejects_removed_legacy_aliases(self) -> None:
        mission_root = MISSIONS_DIR / "mission-autonomy-contract-alias-smoke"
        mission_root.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(ValueError):
            build_outer_loop_contract(mission_root, mode="deeploop")
        with self.assertRaises(ValueError):
            build_outer_loop_contract(mission_root, mode="advanced")

    def test_state_machine_exposes_transition_metadata(self) -> None:
        critique = resolve_phase_contract("critique")
        metadata = {entry["target"]: entry for entry in critique["transition_metadata"]}
        self.assertEqual(metadata["experiment-design"]["branch_status"], "recovery-active")
        self.assertEqual(metadata["experiment-design"]["recovery_status"], "reroute-planned")
        self.assertEqual(metadata["final-report"]["branch_status"], "report-ready")

    def test_resolve_phase_contract_for_state_prefers_materialized_snapshot(self) -> None:
        mission_root = MISSIONS_DIR / "mission-autonomy-snapshot-smoke"
        shutil.rmtree(mission_root, ignore_errors=True)
        mission_root.mkdir(parents=True, exist_ok=True)
        snapshot = materialize_mission_contract_snapshot(
            mission_root,
            mode="sandboxed-yolo",
            state_machine={
                "states": [
                    {
                        "id": "execution",
                        "outputs": ["custom execution artifact"],
                        "transitions": ["critique"],
                    }
                ],
                "terminal_rules": [],
            },
        )

        phase_contract = resolve_phase_contract_for_state(
            "execution",
            mission_state={"contract_snapshot": {"path": snapshot["snapshot_path"]}},
        )
        self.assertEqual(phase_contract["outputs"], ["custom execution artifact"])
        self.assertEqual(phase_contract["transitions"], ["critique"])
        snapshot_path = mission_contract_snapshot_path(mission_root)
        self.assertTrue(snapshot_path.exists())
        loaded = load_mission_contract_snapshot(snapshot_path)
        self.assertEqual(loaded["outer_loop_contract"]["mode"], "sandboxed-yolo")


if __name__ == "__main__":
    unittest.main()
