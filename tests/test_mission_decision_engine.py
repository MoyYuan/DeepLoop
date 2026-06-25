from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.autonomy.mission_autonomy import (
    validate_mission_action,
    validate_mission_branch_record,
    validate_mission_decision,
)
from deeploop.mission.mission_decision_engine import (
    MissionBranchState,
    MissionDecisionDirective,
    MissionDecisionEngine,
    MissionEvidence,
)
from deeploop.runtime.mission_executor_registry import (
    AdaptationTrainingExecutorAction,
    MissionExecutorId,
    StageKernelExecutorAction,
)


def _base_state(*, current_phase: str, next_phase: str, actions: list[dict] | None = None) -> dict:
    return {
        "mission_id": "unit-mission",
        "mode": "sandboxed-yolo",
        "title": "Unit mission",
        "summary": "Exercise mission decisions.",
        "objective": "Choose the next bounded mission step honestly.",
        "current_phase": current_phase,
        "next_phase": next_phase,
        "status": "running",
        "autonomy_status": {"state": "initialized", "reason": "unit test"},
        "next_actions": {"actions": actions or []},
    }


class MissionDecisionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = MissionDecisionEngine()

    def test_engine_continues_existing_pending_phase_work(self) -> None:
        mission_state = _base_state(
            current_phase="experiment-design",
            next_phase="execution",
            actions=[
                {
                    "action_id": "draft-manifest",
                    "role": "experiment-designer",
                    "task": "Draft the next bounded manifest.",
                    "kind": "artifact-edit",
                    "artifacts": ["configs/runtime/demo.yaml"],
                }
            ],
        )

        outcome = self.engine.decide(mission_state)

        self.assertEqual(outcome.directive, MissionDecisionDirective.CONTINUE)
        self.assertIsNotNone(outcome.action)
        assert outcome.action is not None
        self.assertEqual(outcome.action.role, "experiment-designer")
        self.assertEqual(outcome.action.kind, "artifact-edit")
        payloads = outcome.payload_bundle()
        self.assertEqual(validate_mission_decision(payloads["decision"]), [])
        self.assertEqual(validate_mission_action(payloads["action"]), [])

    def test_engine_dispatches_explicit_executor_backed_action(self) -> None:
        mission_state = _base_state(
            current_phase="execution",
            next_phase="critique",
            actions=[
                {
                    "action_id": "run-baseline",
                    "role": "execution-operator",
                    "task": "Run the bounded baseline evaluation.",
                    "kind": "local-eval",
                    "executor": {
                        "id": "stage-kernel",
                        "params": {
                            "stage_id": "baseline-evaluation",
                            "config_path": "configs/runtime/demo-stage.yaml",
                        },
                    },
                }
            ],
        )

        outcome = self.engine.decide(mission_state)

        self.assertEqual(outcome.directive, MissionDecisionDirective.DISPATCH)
        self.assertIsNotNone(outcome.action)
        assert outcome.action is not None
        self.assertIsNotNone(outcome.action.executor_dispatch)
        assert outcome.action.executor_dispatch is not None
        self.assertEqual(outcome.action.executor_dispatch.executor_id, MissionExecutorId.STAGE_KERNEL)
        self.assertIsInstance(outcome.action.executor_dispatch.action, StageKernelExecutorAction)
        self.assertEqual(outcome.action.executor_dispatch.action.stage_id, "baseline-evaluation")

    def test_engine_synthesizes_current_phase_work_for_missing_outputs(self) -> None:
        mission_state = _base_state(current_phase="critique", next_phase="experiment-design")
        evidence = MissionEvidence(produced_outputs=("critique_evidence.json",))

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.CONTINUE)
        self.assertEqual(set(outcome.missing_outputs), {"confound_notes", "next-step recommendation"})
        self.assertIsNotNone(outcome.action)
        assert outcome.action is not None
        self.assertEqual(outcome.action.role, "critic-verifier")
        self.assertIn("confound_notes", outcome.action.task)

    def test_engine_downscopes_repeated_artifact_failures_to_planner(self) -> None:
        mission_state = _base_state(current_phase="literature-review", next_phase="question-design")
        evidence = MissionEvidence(recent_failures=("idle subprocess",), failure_count=1)

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.CONTINUE)
        self.assertIsNotNone(outcome.action)
        assert outcome.action is not None
        self.assertEqual(outcome.action.role, "planner")
        self.assertIn("recovery-downscope=planner", outcome.action.notes)
        self.assertIn("Downscope `literature-review`", outcome.action.task)

    def test_engine_reroutes_through_recovery_transition(self) -> None:
        mission_state = _base_state(current_phase="critique", next_phase="experiment-design")
        evidence = MissionEvidence(
            produced_outputs=("critique_evidence.json", "confound_notes", "next-step recommendation"),
            recent_failures=("failed-1", "failed-2", "failed-3"),
            failure_count=4,
        )

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.REROUTE)
        self.assertIsNotNone(outcome.branch_record)
        self.assertIsNotNone(outcome.action)
        assert outcome.branch_record is not None
        assert outcome.action is not None
        self.assertEqual(outcome.branch_record.status, "recovery-active")
        self.assertEqual(outcome.branch_record.recovery_status, "reroute-planned")
        self.assertEqual(outcome.action.phase, "experiment-design")
        payloads = outcome.payload_bundle()
        self.assertEqual(validate_mission_decision(payloads["decision"]), [])
        self.assertEqual(validate_mission_action(payloads["action"]), [])
        self.assertEqual(validate_mission_branch_record(payloads["branch_record"]), [])

    def test_engine_retries_active_recovery_branch_before_hard_blocking(self) -> None:
        mission_state = _base_state(
            current_phase="execution",
            next_phase="critique",
            actions=[
                {
                    "action_id": "retry-bounded-eval",
                    "role": "execution-operator",
                    "task": "Retry the bounded evaluation with the recovery settings.",
                    "kind": "local-eval",
                }
            ],
        )
        evidence = MissionEvidence(
            recent_failures=("oom-1", "oom-2"),
            failure_count=2,
            branch_records=(
                MissionBranchState(
                    branch_id="recovery-branch",
                    branch_type="recovery",
                    objective="Recover the bounded execution",
                    status="recovery-active",
                    recovery_status="retry-planned",
                    runtime_owner="deeploop",
                    source_phase="execution",
                    target_phase="execution",
                ),
            ),
        )

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.RETRY)
        self.assertIsNotNone(outcome.action)
        assert outcome.action is not None
        self.assertEqual(outcome.action.branch_id, "recovery-branch")
        self.assertIn("retry", " ".join(outcome.action.notes))

    def test_engine_dispatches_adaptation_training_executor(self) -> None:
        mission_state = _base_state(
            current_phase="execution",
            next_phase="critique",
            actions=[
                {
                    "action_id": "adapt-model",
                    "role": "execution-operator",
                    "task": "Run the bounded adaptation step.",
                    "kind": "local-training",
                    "executor": {
                        "id": "adaptation-training",
                        "params": {"training_config_path": "configs/runtime/train.yaml"},
                    },
                }
            ],
        )

        outcome = self.engine.decide(mission_state)

        self.assertEqual(outcome.directive, MissionDecisionDirective.DISPATCH)
        self.assertIsNotNone(outcome.action)
        assert outcome.action is not None
        self.assertEqual(outcome.action.kind, "local-training")
        self.assertIsNotNone(outcome.action.executor_dispatch)
        assert outcome.action.executor_dispatch is not None
        self.assertEqual(outcome.action.executor_dispatch.executor_id, MissionExecutorId.ADAPTATION_TRAINING)
        self.assertIsInstance(outcome.action.executor_dispatch.action, AdaptationTrainingExecutorAction)
        payloads = outcome.payload_bundle()
        self.assertEqual(validate_mission_decision(payloads["decision"]), [])
        self.assertEqual(validate_mission_action(payloads["action"]), [])

    def test_engine_completes_when_completion_contract_is_satisfied(self) -> None:
        mission_state = _base_state(current_phase="final-report", next_phase="final-report")
        mission_state["completed_phases"] = ["idea-intake", "literature-review", "question-design", "experiment-design", "execution", "critique", "replication"]
        mission_state["phase_outputs_by_phase"] = {
            "execution": ["run_manifest.json", "predictions.jsonl", "metrics.json", "runtime_report.json"],
            "critique": ["critique_evidence.json", "confound_notes", "next-step recommendation"],
            "replication": ["repeated-run manifests", "replication summary"],
            "final-report": ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        }
        mission_state["operator_inbox"] = {"status": "clear"}
        evidence = MissionEvidence(
            produced_outputs=("findings summary", "paper-candidate recommendation", "artifact readiness notes")
        )

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.COMPLETE)
        self.assertIsNone(outcome.action)
        payloads = outcome.payload_bundle()
        self.assertEqual(validate_mission_decision(payloads["decision"]), [])

    def test_engine_blocks_completion_when_execution_evidence_is_missing(self) -> None:
        mission_state = _base_state(current_phase="final-report", next_phase="final-report")
        mission_state["completed_phases"] = ["idea-intake", "literature-review", "question-design", "experiment-design", "critique", "replication"]
        mission_state["phase_outputs_by_phase"] = {
            "critique": ["critique_evidence.json", "confound_notes", "next-step recommendation"],
            "replication": ["repeated-run manifests", "replication summary"],
            "final-report": ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        }
        mission_state["operator_inbox"] = {"status": "clear"}
        evidence = MissionEvidence(
            produced_outputs=("findings summary", "paper-candidate recommendation", "artifact readiness notes")
        )

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.BLOCK)
        self.assertIn("completion contract requires completed phase `execution`", outcome.notes)
        self.assertIn("completion contract missing `execution` output `run_manifest.json`", outcome.notes)

    def test_engine_blocks_final_report_transition_when_acceptance_criteria_are_unmet(self) -> None:
        mission_state = _base_state(current_phase="replication", next_phase="final-report")
        mission_state["completed_phases"] = ["execution", "critique"]
        mission_state["phase_outputs_by_phase"] = {
            "execution": ["run_manifest.json", "predictions.jsonl", "metrics.json", "runtime_report.json"],
            "critique": ["critique_evidence.json", "confound_notes", "next-step recommendation"],
            "replication": ["repeated-run manifests", "replication summary"],
        }
        mission_state["acceptance_criteria"] = {
            "min_methods_evaluated": 2,
            "allow_final_report_only_if_criteria_met": True,
        }
        mission_state["acceptance_evidence"] = {
            "methods_evaluated": [{"method_id": "ridge", "family": "linear"}],
        }
        evidence = MissionEvidence(produced_outputs=("repeated-run manifests", "replication summary"))

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.BLOCK)
        self.assertIn("acceptance criterion `min_methods_evaluated` unmet: requested 2, achieved 1", outcome.notes)

    def test_engine_allows_final_report_transition_when_acceptance_criteria_are_met(self) -> None:
        mission_state = _base_state(current_phase="replication", next_phase="final-report")
        mission_state["completed_phases"] = ["execution", "critique"]
        mission_state["phase_outputs_by_phase"] = {
            "execution": ["run_manifest.json", "predictions.jsonl", "metrics.json", "runtime_report.json"],
            "critique": ["critique_evidence.json", "confound_notes", "next-step recommendation"],
            "replication": ["repeated-run manifests", "replication summary"],
        }
        mission_state["acceptance_criteria"] = {
            "min_methods_evaluated": 2,
            "allow_final_report_only_if_criteria_met": True,
        }
        mission_state["acceptance_evidence"] = {
            "methods_evaluated": [
                {"method_id": "ridge", "family": "linear"},
                {"method_id": "xgboost", "family": "tree"},
            ],
        }
        evidence = MissionEvidence(produced_outputs=("repeated-run manifests", "replication summary"))

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.BRANCH)
        self.assertIsNotNone(outcome.action)
        assert outcome.action is not None
        self.assertEqual(outcome.action.phase, "final-report")

    def test_engine_blocks_completion_when_acceptance_criteria_are_unmet(self) -> None:
        mission_state = _base_state(current_phase="final-report", next_phase="final-report")
        mission_state["completed_phases"] = [
            "idea-intake",
            "literature-review",
            "question-design",
            "experiment-design",
            "execution",
            "critique",
            "replication",
        ]
        mission_state["phase_outputs_by_phase"] = {
            "execution": ["run_manifest.json", "predictions.jsonl", "metrics.json", "runtime_report.json"],
            "critique": ["critique_evidence.json", "confound_notes", "next-step recommendation"],
            "replication": ["repeated-run manifests", "replication summary"],
            "final-report": ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        }
        mission_state["operator_inbox"] = {"status": "clear"}
        mission_state["acceptance_criteria"] = {
            "min_methods_evaluated": 2,
            "allow_final_report_only_if_criteria_met": True,
        }
        mission_state["acceptance_evidence"] = {
            "methods_evaluated": [{"method_id": "ridge", "family": "linear"}],
        }
        evidence = MissionEvidence(
            produced_outputs=("findings summary", "paper-candidate recommendation", "artifact readiness notes")
        )

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.BLOCK)
        self.assertIn("acceptance criterion `min_methods_evaluated` unmet: requested 2, achieved 1", outcome.notes)

    def test_engine_allows_explicit_replication_waiver_for_completion(self) -> None:
        mission_state = _base_state(current_phase="final-report", next_phase="final-report")
        mission_state["completed_phases"] = ["idea-intake", "literature-review", "question-design", "experiment-design", "execution", "critique"]
        mission_state["phase_outputs_by_phase"] = {
            "execution": ["run_manifest.json", "predictions.jsonl", "metrics.json", "runtime_report.json"],
            "critique": ["critique_evidence.json", "confound_notes", "next-step recommendation"],
            "final-report": ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        }
        mission_state["completion_contract"] = {
            "replication_requirement": "waived",
            "replication_waiver_reason": "Budget was exhausted after critique and the final report records the remaining replication gap.",
        }
        mission_state["operator_inbox"] = {"status": "clear"}
        evidence = MissionEvidence(
            produced_outputs=("findings summary", "paper-candidate recommendation", "artifact readiness notes")
        )

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.COMPLETE)
        self.assertIsNone(outcome.action)

    def test_engine_infers_no_win_budget_replication_waiver_for_completion(self) -> None:
        mission_state = _base_state(current_phase="final-report", next_phase="final-report")
        mission_state["completed_phases"] = ["idea-intake", "literature-review", "question-design", "experiment-design", "execution", "critique"]
        mission_state["phase_outputs_by_phase"] = {
            "execution": ["run_manifest.json", "predictions.jsonl", "metrics.json", "runtime_report.json"],
            "critique": ["critique_evidence.json", "confound_notes", "next-step recommendation"],
            "final-report": ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        }
        mission_state["branch_closure_mode"] = "no-win-under-budget"
        mission_state["downstream_execution_authorized"] = False
        mission_state["operator_inbox"] = {"status": "clear"}
        evidence = MissionEvidence(
            produced_outputs=("findings summary", "paper-candidate recommendation", "artifact readiness notes")
        )

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.COMPLETE)
        self.assertIsNone(outcome.action)

    def test_engine_infers_final_report_no_promotion_replication_waiver_for_completion(self) -> None:
        mission_state = _base_state(current_phase="final-report", next_phase="final-report")
        mission_state["completed_phases"] = ["idea-intake", "literature-review", "question-design", "experiment-design", "execution", "critique"]
        mission_state["phase_outputs_by_phase"] = {
            "execution": ["run_manifest.json", "predictions.jsonl", "metrics.json", "runtime_report.json"],
            "critique": ["critique_evidence.json", "confound_notes", "next-step recommendation"],
            "final-report": ["findings summary", "paper-candidate recommendation", "artifact readiness notes"],
        }
        mission_state["final_report"] = {
            "decision": "no-promotion",
            "close_mission": True,
            "no_further_execution_reroute": True,
        }
        mission_state["operator_inbox"] = {"status": "clear"}
        evidence = MissionEvidence(
            produced_outputs=("findings summary", "paper-candidate recommendation", "artifact readiness notes")
        )

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.COMPLETE)
        self.assertIsNone(outcome.action)

    def test_engine_ignores_future_phase_actions_until_transition(self) -> None:
        mission_state = _base_state(
            current_phase="execution",
            next_phase="critique",
            actions=[
                {
                    "action_id": "assemble-final-report",
                    "role": "report-synthesizer",
                    "task": "Package the final report.",
                    "kind": "final-report",
                    "phase": "final-report",
                    "executor": {
                        "id": "report-synthesis",
                        "params": {"mission_state_path": "runs/unit-mission/mission_state.json"},
                    },
                }
            ],
        )
        evidence = MissionEvidence(
            produced_outputs=("run_manifest.json", "predictions.jsonl", "metrics.json", "runtime_report.json"),
        )

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.BRANCH)
        self.assertIsNotNone(outcome.action)
        assert outcome.action is not None
        self.assertEqual(outcome.action.phase, "critique")
        self.assertEqual(outcome.action.kind, "phase-transition")

    def test_engine_uses_deterministic_route_when_enabled(self) -> None:
        mission_state = _base_state(current_phase="critique", next_phase="experiment-design")
        mission_state["deterministic_routing"] = {"enabled": True}
        mission_state["phase_execution_hints"] = {
            "critique": {
                "deterministic_routes": [
                    {
                        "rule_id": "ratchet-keep",
                        "target": "replication",
                        "summary": "Route directly into replication when the ratchet keeps the adapted artifact.",
                        "when": [
                            {"path": "adaptation_training.metric_ratchet.decision", "eq": "keep"},
                            {"path": "adaptation_training.metric_ratchet.route_to", "eq": "replication"},
                        ],
                    }
                ]
            }
        }
        mission_state["adaptation_training"] = {"metric_ratchet": {"decision": "keep", "route_to": "replication"}}
        evidence = MissionEvidence(
            produced_outputs=("critique_evidence.json", "confound_notes", "next-step recommendation"),
        )

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.BRANCH)
        self.assertIsNotNone(outcome.action)
        assert outcome.action is not None
        self.assertEqual(outcome.action.phase, "replication")
        self.assertIn("deterministic_route_rule=ratchet-keep", outcome.decision.notes)

    def test_engine_falls_back_when_deterministic_route_does_not_match(self) -> None:
        mission_state = _base_state(current_phase="critique", next_phase="experiment-design")
        mission_state["deterministic_routing"] = {"enabled": True}
        mission_state["phase_execution_hints"] = {
            "critique": {
                "deterministic_routes": [
                    {
                        "rule_id": "ratchet-keep",
                        "target": "replication",
                        "when": [{"path": "adaptation_training.metric_ratchet.decision", "eq": "keep"}],
                    }
                ]
            }
        }
        mission_state["adaptation_training"] = {"metric_ratchet": {"decision": "discard", "route_to": "experiment-design"}}
        evidence = MissionEvidence(
            produced_outputs=("critique_evidence.json", "confound_notes", "next-step recommendation"),
            recent_failures=("failed-1", "failed-2", "failed-3"),
            failure_count=4,
        )

        outcome = self.engine.decide(mission_state, evidence=evidence)

        self.assertEqual(outcome.directive, MissionDecisionDirective.REROUTE)
        self.assertIsNotNone(outcome.action)
        assert outcome.action is not None
        self.assertEqual(outcome.action.phase, "experiment-design")
        self.assertNotIn("deterministic_route_rule=ratchet-keep", outcome.decision.notes)

    def test_engine_rejects_malformed_deterministic_route(self) -> None:
        mission_state = _base_state(current_phase="critique", next_phase="replication")
        mission_state["deterministic_routing"] = {"enabled": True}
        mission_state["phase_execution_hints"] = {
            "critique": {
                "deterministic_routes": [
                    {
                        "rule_id": "broken-rule",
                        "target": "replication",
                    }
                ]
            }
        }
        evidence = MissionEvidence(
            produced_outputs=("critique_evidence.json", "confound_notes", "next-step recommendation"),
        )

        with self.assertRaisesRegex(ValueError, "Deterministic routes must declare `when`"):
            self.engine.decide(mission_state, evidence=evidence)


if __name__ == "__main__":
    unittest.main()
