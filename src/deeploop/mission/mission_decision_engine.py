from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from deeploop.autonomy.gate_taxonomy import resolve_gate_contract
from deeploop.autonomy.mission_contract_snapshot import load_mission_contract_snapshot_for_state, resolve_phase_contract_for_state
from deeploop.autonomy.mission_autonomy import (
    ensure_valid_contract_payload,
    enrich_outer_loop_contract,
    load_mission_outer_loop_policy,
    resolve_phase_contract,
)
from deeploop.autonomy.operating_modes import DEFAULT_OPERATING_MODE, is_autonomous_operating_mode, resolve_operating_mode
from deeploop.core.ledger import now_utc
from deeploop.core.paths import REPO_ROOT
from deeploop.runtime.mission_executor_registry import (
    AdaptationTrainingExecutorAction,
    EvaluationComparisonExecutorAction,
    MissionExecutorAction,
    MissionExecutorId,
    RecursiveAgentExecutorAction,
    ReportSynthesisExecutorAction,
    SelfHealingQueueExecutorAction,
    StageKernelExecutorAction,
    get_mission_executor_registry,
)

AUTONOMY_GATES_PATH = REPO_ROOT / "configs" / "autonomy" / "gates.yaml"

_PHASE_ROLE_DEFAULTS = {
    "idea-intake": "planner",
    "literature-review": "literature-scout",
    "question-design": "planner",
    "benchmark-selection": "dataset-strategist",
    "experiment-design": "experiment-designer",
    "execution": "execution-operator",
    "critique": "critic-verifier",
    "replication": "execution-operator",
    "final-report": "report-synthesizer",
}

_PHASE_ACTION_KIND_DEFAULTS = {
    "execution": "local-eval",
    "critique": "critique",
    "replication": "replication",
    "final-report": "final-report",
}

_ACTIONABLE_STATUSES = {"pending", "in_progress"}
_BLOCKING_STATUSES = {"blocked"}
_DONE_STATUSES = {"completed", "cancelled"}
_MISSING = object()


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded


def _normalize_strings(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, (str, Path)):
        text = str(raw).strip()
        return (text,) if text else ()
    if isinstance(raw, list | tuple):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def _slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def _path_value(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in (segment.strip() for segment in path.split(".")):
        if not part:
            raise ValueError(f"Deterministic route path `{path}` is invalid.")
        if not isinstance(current, Mapping):
            return _MISSING
        if part not in current:
            return _MISSING
        current = current[part]
    return current


def _default_role_for_phase(phase: str) -> str:
    return _PHASE_ROLE_DEFAULTS.get(phase, "planner")


def _default_kind_for_phase(phase: str) -> str:
    return _PHASE_ACTION_KIND_DEFAULTS.get(phase, "artifact-edit")


def _recovery_role_for_missing_outputs(phase: str, *, kind: str, failure_count: int) -> str:
    default_role = _default_role_for_phase(phase)
    if failure_count > 0 and kind == "artifact-edit" and default_role != "planner":
        return "planner"
    return default_role


def _phase_outputs_for_state(mission_state: Mapping[str, Any], phase: str) -> tuple[str, ...]:
    phase_outputs = mission_state.get("phase_outputs_by_phase")
    if isinstance(phase_outputs, Mapping):
        resolved = _normalize_strings(phase_outputs.get(phase))
        if resolved:
            return resolved
    if phase == str(mission_state.get("current_phase") or ""):
        return _normalize_strings(mission_state.get("produced_outputs") or mission_state.get("phase_outputs"))
    return ()


def _branch_type_for_transition(*, target_phase: str, branch_status: str, recovery_status: str) -> str:
    if recovery_status != "not-needed" or branch_status == "recovery-active":
        return "recovery"
    if target_phase == "replication" or branch_status == "replication-active":
        return "replication"
    if target_phase == "final-report" or branch_status == "report-ready":
        return "report"
    if target_phase in {"execution", "experiment-design"}:
        return "execution"
    return "analysis"


def _deep_merge(base: dict[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class MissionBranchState:
    branch_id: str
    branch_type: str
    objective: str
    status: str
    recovery_status: str
    runtime_owner: str
    source_phase: str
    target_phase: str | None = None
    parent_branch_id: str | None = None
    created_by_decision_id: str | None = None
    git_branch: str | None = None
    artifacts: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    updated_at: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MissionBranchState":
        return cls(
            branch_id=str(payload.get("branch_id") or ""),
            branch_type=str(payload.get("branch_type") or "analysis"),
            objective=str(payload.get("objective") or ""),
            status=str(payload.get("status") or "planned"),
            recovery_status=str(payload.get("recovery_status") or "not-needed"),
            runtime_owner=str(payload.get("runtime_owner") or "deeploop"),
            source_phase=str(payload.get("source_phase") or ""),
            target_phase=str(payload["target_phase"]) if payload.get("target_phase") is not None else None,
            parent_branch_id=str(payload["parent_branch_id"]) if payload.get("parent_branch_id") is not None else None,
            created_by_decision_id=(
                str(payload["created_by_decision_id"]) if payload.get("created_by_decision_id") is not None else None
            ),
            git_branch=str(payload["git_branch"]) if payload.get("git_branch") is not None else None,
            artifacts=_normalize_strings(payload.get("artifacts")),
            notes=_normalize_strings(payload.get("notes")),
            updated_at=str(payload["updated_at"]) if payload.get("updated_at") is not None else None,
        )

    def to_payload(self, *, mission_id: str) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "branch_id": self.branch_id,
            "mission_id": mission_id,
            "branch_type": self.branch_type,
            "objective": self.objective,
            "status": self.status,
            "recovery_status": self.recovery_status,
            "runtime_owner": self.runtime_owner,
            "source_phase": self.source_phase,
            "target_phase": self.target_phase,
            "parent_branch_id": self.parent_branch_id,
            "created_by_decision_id": self.created_by_decision_id,
            "git_branch": self.git_branch,
            "artifacts": list(self.artifacts),
            "updated_at": self.updated_at or now_utc(),
            "notes": list(self.notes),
        }
        ensure_valid_contract_payload(payload, kind="mission_branch_record")
        return payload


@dataclass(frozen=True)
class PendingMissionAction:
    role: str
    task: str
    kind: str | None = None
    phase: str | None = None
    status: str = "pending"
    action_id: str | None = None
    branch_id: str | None = None
    artifacts: tuple[str, ...] = ()
    output_paths: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    produces_outputs: tuple[str, ...] = ()
    executor: dict[str, Any] | None = None
    requires_operator_approval: bool | None = None
    next_phase_on_success: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PendingMissionAction":
        executor = payload.get("executor")
        if not isinstance(executor, dict):
            executor_id = payload.get("executor_id")
            if executor_id is not None:
                maybe_params = payload.get("executor_params")
                executor = {
                    "id": str(executor_id),
                    "params": dict(maybe_params) if isinstance(maybe_params, Mapping) else {},
                }
            else:
                executor = None
        return cls(
            role=str(payload.get("role") or "planner"),
            task=str(payload.get("task") or "").strip(),
            kind=str(payload["kind"]) if payload.get("kind") is not None else None,
            phase=str(payload["phase"]) if payload.get("phase") is not None else None,
            status=str(payload.get("status") or "pending"),
            action_id=str(payload["action_id"]) if payload.get("action_id") is not None else None,
            branch_id=str(payload["branch_id"]) if payload.get("branch_id") is not None else None,
            artifacts=_normalize_strings(payload.get("artifacts")),
            output_paths=_normalize_strings(payload.get("output_paths")),
            notes=_normalize_strings(payload.get("notes")),
            produces_outputs=_normalize_strings(payload.get("produces_outputs")),
            executor=dict(executor) if isinstance(executor, dict) else None,
            requires_operator_approval=(
                bool(payload["requires_operator_approval"])
                if payload.get("requires_operator_approval") is not None
                else None
            ),
            next_phase_on_success=(
                str(payload["next_phase_on_success"]) if payload.get("next_phase_on_success") is not None else None
            ),
        )


@dataclass(frozen=True)
class MissionEvidence:
    produced_outputs: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    recent_failures: tuple[str, ...] = ()
    branch_records: tuple[MissionBranchState, ...] = ()
    failure_count: int = 0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "MissionEvidence":
        if payload is None:
            return cls()
        branch_records = payload.get("branch_records") or payload.get("branches") or ()
        normalized_branches: list[MissionBranchState] = []
        if isinstance(branch_records, list | tuple):
            for record in branch_records:
                if isinstance(record, MissionBranchState):
                    normalized_branches.append(record)
                elif isinstance(record, Mapping):
                    normalized_branches.append(MissionBranchState.from_mapping(record))
        return cls(
            produced_outputs=_normalize_strings(payload.get("produced_outputs") or payload.get("phase_outputs")),
            blockers=_normalize_strings(payload.get("blockers") or payload.get("blocked_reasons")),
            recent_failures=_normalize_strings(payload.get("recent_failures")),
            branch_records=tuple(normalized_branches),
            failure_count=int(payload.get("failure_count", 0) or 0),
        )


class MissionDecisionDirective(str, Enum):
    CONTINUE = "continue-current-phase"
    DISPATCH = "dispatch-executor"
    BRANCH = "branch"
    REROUTE = "reroute"
    RETRY = "retry"
    BLOCK = "block"
    FAIL = "fail"
    COMPLETE = "complete"


@dataclass(frozen=True)
class MissionExecutorDispatch:
    executor_id: MissionExecutorId
    action: MissionExecutorAction
    summary: str


@dataclass(frozen=True)
class MissionTransition:
    from_phase: str
    to_phase: str
    branch_status: str
    recovery_status: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "from_phase": self.from_phase,
            "to_phase": self.to_phase,
            "branch_status": self.branch_status,
            "recovery_status": self.recovery_status,
        }


@dataclass(frozen=True)
class MissionPlannedAction:
    action_id: str
    mission_id: str
    kind: str
    role: str
    task: str
    phase: str
    decision_id: str | None = None
    branch_id: str | None = None
    runtime_owner: str = "deeploop"
    requires_operator_approval: bool = False
    status: str = "pending"
    artifacts: tuple[str, ...] = ()
    output_paths: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    produces_outputs: tuple[str, ...] = ()
    created_at: str | None = None
    executor_dispatch: MissionExecutorDispatch | None = None
    next_phase_on_success: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "action_id": self.action_id,
            "mission_id": self.mission_id,
            "decision_id": self.decision_id,
            "branch_id": self.branch_id,
            "kind": self.kind,
            "role": self.role,
            "task": self.task,
            "status": self.status,
            "phase": self.phase,
            "runtime_owner": self.runtime_owner,
            "requires_operator_approval": self.requires_operator_approval,
            "artifacts": list(self.artifacts),
            "output_paths": list(self.output_paths),
            "created_at": self.created_at or now_utc(),
            "notes": list(self.notes),
            "produces_outputs": list(self.produces_outputs),
            "next_phase_on_success": self.next_phase_on_success,
        }
        ensure_valid_contract_payload(payload, kind="mission_action")
        return payload


@dataclass(frozen=True)
class MissionDecisionRecord:
    decision_id: str
    mission_id: str
    decision_type: str
    summary: str
    phase: str
    scope: str
    authority_mode: str
    requires_operator_approval: bool
    approval_state: str
    result_status: str
    recorded_at: str
    transition: MissionTransition | None = None
    selected_action_ids: tuple[str, ...] = ()
    selected_branch_ids: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "decision_id": self.decision_id,
            "mission_id": self.mission_id,
            "decision_type": self.decision_type,
            "summary": self.summary,
            "phase": self.phase,
            "scope": self.scope,
            "authority": {
                "mode": self.authority_mode,
                "requires_operator_approval": self.requires_operator_approval,
                "approval_state": self.approval_state,
            },
            "result": {"status": self.result_status, "recorded_at": self.recorded_at},
            "transition": self.transition.to_payload() if self.transition is not None else None,
            "selected_action_ids": list(self.selected_action_ids),
            "selected_branch_ids": list(self.selected_branch_ids),
            "artifacts": list(self.artifacts),
            "notes": list(self.notes),
        }
        if payload["transition"] is None:
            payload.pop("transition")
        ensure_valid_contract_payload(payload, kind="mission_decision")
        return payload


@dataclass(frozen=True)
class MissionDecisionOutcome:
    directive: MissionDecisionDirective
    decision: MissionDecisionRecord
    action: MissionPlannedAction | None = None
    branch_record: MissionBranchState | None = None
    missing_outputs: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def payload_bundle(self) -> dict[str, dict[str, Any] | None]:
        return {
            "decision": self.decision.to_payload(),
            "action": self.action.to_payload() if self.action is not None else None,
            "branch_record": (
                self.branch_record.to_payload(mission_id=self.decision.mission_id) if self.branch_record is not None else None
            ),
        }


class MissionDecisionEngine:
    def __init__(
        self,
        *,
        outer_loop_policy: Mapping[str, Any] | None = None,
        gates_policy: Mapping[str, Any] | None = None,
    ) -> None:
        self.outer_loop_policy = dict(outer_loop_policy or load_mission_outer_loop_policy())
        self.gates_policy = dict(gates_policy or _load_yaml(AUTONOMY_GATES_PATH))

    def decide(
        self,
        mission_state: Mapping[str, Any],
        *,
        evidence: MissionEvidence | Mapping[str, Any] | None = None,
    ) -> MissionDecisionOutcome:
        mission_id = str(mission_state.get("mission_id") or "").strip()
        current_phase = str(mission_state.get("current_phase") or "").strip()
        if not mission_id or not current_phase:
            raise ValueError("mission_state must include non-empty mission_id and current_phase")

        evidence_snapshot = self._evidence_from_state(mission_state, evidence)
        pending_actions = self._pending_actions(mission_state)
        current_phase_actions = tuple(
            action
            for action in pending_actions
            if action.phase is None or not str(action.phase).strip() or str(action.phase).strip() == current_phase
        )
        pending_action = next(
            (action for action in current_phase_actions if action.status in _ACTIONABLE_STATUSES or not action.status),
            None,
        )
        blocked_action = next((action for action in current_phase_actions if action.status in _BLOCKING_STATUSES), None)

        phase_contract = resolve_phase_contract_for_state(current_phase, mission_state=mission_state)
        required_outputs = _normalize_strings(phase_contract.get("outputs"))
        observed_outputs = set(evidence_snapshot.produced_outputs)
        missing_outputs = tuple(output for output in required_outputs if output not in observed_outputs)

        failure_count = self._failure_count(mission_state, evidence_snapshot)
        max_retries = int(self._gates_policy_for_state(mission_state).get("failure_policy", {}).get("max_oom_retries_per_run", 0) or 0)
        active_branch = self._active_branch(
            evidence_snapshot.branch_records,
            allowed_targets=set(_normalize_strings(phase_contract.get("transitions"))),
            current_phase=current_phase,
        )

        if active_branch is not None and active_branch.recovery_status == "retry-planned" and pending_action is not None:
            if failure_count < max_retries:
                return self._retry_outcome(mission_state, pending_action, active_branch, missing_outputs)

        prefer_recovery = failure_count >= max_retries or bool(evidence_snapshot.blockers)
        transition_meta = self._select_transition_metadata(
            mission_state,
            phase_contract,
            active_branch=active_branch,
            prefer_recovery=prefer_recovery,
        )
        if transition_meta is not None and active_branch is not None and active_branch.recovery_status == "reroute-planned":
            return self._transition_outcome(
                mission_state,
                transition_meta=transition_meta,
                directive=MissionDecisionDirective.REROUTE,
                branch_record=active_branch,
                missing_outputs=missing_outputs,
            )

        if pending_action is not None:
            kind = self._resolved_action_kind(mission_state, pending_action, current_phase)
            planned_action = self._planned_action_from_pending(
                mission_state,
                pending_action,
                kind=kind,
                phase=current_phase,
            )
            if planned_action.requires_operator_approval:
                return self._blocked_outcome(
                    mission_state,
                    decision_type=kind,
                    summary=f"Action `{planned_action.action_id}` requires operator approval before execution.",
                    action=planned_action,
                    missing_outputs=missing_outputs,
                )
            executor_dispatch, executor_note = self._resolve_executor_dispatch(pending_action)
            if executor_dispatch is not None:
                dispatch_action = MissionPlannedAction(
                    action_id=planned_action.action_id,
                    mission_id=planned_action.mission_id,
                    kind=planned_action.kind,
                    role=planned_action.role,
                    task=planned_action.task,
                    phase=planned_action.phase,
                    decision_id=planned_action.decision_id,
                    branch_id=planned_action.branch_id,
                    runtime_owner=planned_action.runtime_owner,
                    requires_operator_approval=planned_action.requires_operator_approval,
                    status=planned_action.status,
                    artifacts=planned_action.artifacts,
                    output_paths=planned_action.output_paths,
                    notes=planned_action.notes + ((_normalize_strings(executor_note)[0],) if executor_note else ()),
                    produces_outputs=planned_action.produces_outputs,
                    executor_dispatch=executor_dispatch,
                    next_phase_on_success=planned_action.next_phase_on_success,
                )
                return self._selected_outcome(
                    mission_state,
                    directive=MissionDecisionDirective.DISPATCH,
                    decision_type=kind,
                    summary=f"Dispatch `{dispatch_action.action_id}` through executor `{executor_dispatch.executor_id.value}`.",
                    action=dispatch_action,
                    missing_outputs=missing_outputs,
                )
            return self._selected_outcome(
                mission_state,
                directive=MissionDecisionDirective.CONTINUE,
                decision_type=kind,
                summary=f"Continue `{current_phase}` via role `{planned_action.role}`.",
                action=planned_action,
                missing_outputs=missing_outputs,
            )

        if current_phase == "final-report" and not missing_outputs:
            return self._complete_outcome(mission_state)

        if missing_outputs:
            return self._missing_outputs_outcome(mission_state, missing_outputs, failure_count=failure_count)

        if transition_meta is not None:
            directive = self._directive_for_transition(transition_meta)
            return self._transition_outcome(
                mission_state,
                transition_meta=transition_meta,
                directive=directive,
                branch_record=active_branch,
                missing_outputs=missing_outputs,
            )

        autonomy_state = str((mission_state.get("autonomy_status") or {}).get("state") or "").lower()
        if "failed" in autonomy_state or str(mission_state.get("status") or "").lower() == "failed":
            return self._failed_outcome(mission_state, failure_count=failure_count, missing_outputs=missing_outputs)

        if blocked_action is not None:
            return self._blocked_outcome(
                mission_state,
                decision_type=self._resolved_action_kind(mission_state, blocked_action, current_phase),
                summary=f"Mission is blocked on action `{blocked_action.action_id or blocked_action.role}`.",
                action=self._planned_action_from_pending(
                    mission_state,
                    blocked_action,
                    kind=self._resolved_action_kind(mission_state, blocked_action, current_phase),
                    phase=current_phase,
                    force_status="blocked",
                ),
                missing_outputs=missing_outputs,
            )

        return self._blocked_outcome(
            mission_state,
            decision_type="operator-review",
            summary="No pending mission action, recovery path, or valid phase transition could be selected.",
            missing_outputs=missing_outputs,
        )

    def _evidence_from_state(
        self,
        mission_state: Mapping[str, Any],
        evidence: MissionEvidence | Mapping[str, Any] | None,
    ) -> MissionEvidence:
        base = MissionEvidence()
        state_evidence = MissionEvidence.from_mapping(
            {
                "phase_outputs": mission_state.get("produced_outputs") or mission_state.get("phase_outputs"),
                "recent_failures": mission_state.get("recent_failures"),
                "failure_count": mission_state.get("failure_count", 0),
                "branches": mission_state.get("branches") or mission_state.get("branch_records"),
                "blocked_reasons": mission_state.get("blocked_reasons"),
            }
        )
        raw = evidence if isinstance(evidence, MissionEvidence) else MissionEvidence.from_mapping(evidence)
        merged = _deep_merge(
            {
                "produced_outputs": list(base.produced_outputs),
                "blockers": list(base.blockers),
                "recent_failures": list(base.recent_failures),
                "branch_records": list(base.branch_records),
                "failure_count": base.failure_count,
            },
            {
                "produced_outputs": list(state_evidence.produced_outputs),
                "blockers": list(state_evidence.blockers),
                "recent_failures": list(state_evidence.recent_failures),
                "branch_records": list(state_evidence.branch_records),
                "failure_count": state_evidence.failure_count,
            },
        )
        merged = _deep_merge(
            merged,
            {
                "produced_outputs": list(raw.produced_outputs),
                "blockers": list(raw.blockers),
                "recent_failures": list(raw.recent_failures),
                "branch_records": list(raw.branch_records),
                "failure_count": raw.failure_count,
            },
        )
        autonomy = mission_state.get("autonomy_status")
        if isinstance(autonomy, Mapping):
            state = str(autonomy.get("state") or "")
            reason = str(autonomy.get("reason") or "").strip()
            if reason and ("blocked" in state or "failed" in state):
                blockers = list(merged["blockers"])
                if reason not in blockers:
                    blockers.append(reason)
                merged["blockers"] = blockers
        return MissionEvidence(
            produced_outputs=tuple(merged["produced_outputs"]),
            blockers=tuple(merged["blockers"]),
            recent_failures=tuple(merged["recent_failures"]),
            branch_records=tuple(merged["branch_records"]),
            failure_count=int(merged["failure_count"] or 0),
        )

    def _pending_actions(self, mission_state: Mapping[str, Any]) -> tuple[PendingMissionAction, ...]:
        next_actions = mission_state.get("next_actions")
        if not isinstance(next_actions, Mapping):
            return ()
        raw_actions = next_actions.get("actions")
        if not isinstance(raw_actions, list):
            return ()
        actions: list[PendingMissionAction] = []
        for item in raw_actions:
            if not isinstance(item, Mapping):
                continue
            action = PendingMissionAction.from_mapping(item)
            if action.task and action.status not in _DONE_STATUSES:
                actions.append(action)
        return tuple(actions)

    def _outer_loop_policy_for_state(self, mission_state: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = load_mission_contract_snapshot_for_state(mission_state)
        policy = snapshot.get("outer_loop_policy") if isinstance(snapshot, Mapping) else None
        return dict(policy) if isinstance(policy, Mapping) else dict(self.outer_loop_policy)

    def _gates_policy_for_state(self, mission_state: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = load_mission_contract_snapshot_for_state(mission_state)
        policy = snapshot.get("gates_policy") if isinstance(snapshot, Mapping) else None
        return dict(policy) if isinstance(policy, Mapping) else dict(self.gates_policy)

    def _resolved_action_kind(
        self,
        mission_state: Mapping[str, Any],
        action: PendingMissionAction,
        current_phase: str,
    ) -> str:
        action_classes = self._outer_loop_policy_for_state(mission_state).get("action_classes", {})
        if isinstance(action.kind, str) and action.kind in action_classes:
            return action.kind
        return _default_kind_for_phase(current_phase)

    def _outer_loop_contract(self, mission_state: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = load_mission_contract_snapshot_for_state(mission_state)
        existing = mission_state.get("outer_loop")
        if isinstance(existing, Mapping):
            gate_contract = snapshot.get("gate_contract") if isinstance(snapshot, Mapping) else None
            contract = dict(snapshot.get("outer_loop_contract", {})) if isinstance(snapshot, Mapping) else {}
            contract.update(existing)
            return enrich_outer_loop_contract(
                contract,
                mode=str(existing.get("mode") or mission_state.get("mode") or DEFAULT_OPERATING_MODE),
                gate_contract=dict(gate_contract) if isinstance(gate_contract, Mapping) else None,
            )
        outer_loop_policy = self._outer_loop_policy_for_state(mission_state)
        gates_policy = self._gates_policy_for_state(mission_state)
        default_mode = str(outer_loop_policy.get("default_mode") or DEFAULT_OPERATING_MODE)
        mode = str(mission_state.get("mode") or DEFAULT_OPERATING_MODE)
        resolved_mode = resolve_operating_mode(mode, default=default_mode)
        mode_defaults = outer_loop_policy.get("mode_defaults", {})
        selected = mode_defaults.get(resolved_mode, mode_defaults.get("default", {}))
        if not isinstance(selected, Mapping):
            selected = {}
        action_classes = outer_loop_policy.get("action_classes", {})
        gate_contract = resolve_gate_contract(mode=resolved_mode, gates_policy=gates_policy)
        autonomous_action_kinds = [
            action_id
            for action_id, config in action_classes.items()
            if isinstance(config, Mapping) and not bool(config.get("requires_operator_approval", False))
        ]
        return enrich_outer_loop_contract(
            {
            "mode": resolved_mode,
            "execution_mode": str(selected.get("execution_mode", resolved_mode)),
            "internal_execution": str(selected.get("internal_execution", selected.get("permissions_profile", "human-approved"))),
            "permissions_profile": str(selected.get("permissions_profile", "human-approved")),
            "intervention_profile": str(selected.get("intervention_profile", "step-by-step")),
            "default_operator_approval": str(selected.get("default_operator_approval", "required")),
            "gate_policy_name": gate_contract["policy_name"],
            "hard_gate_profile": gate_contract["hard_gate_profile"],
            "hard_gate_profile_summary": gate_contract["hard_gate_profile_summary"],
            "hard_gate_risk_classes": list(gate_contract["hard_gate_risk_classes"]),
            "soft_gate_risk_classes": list(gate_contract["soft_gate_risk_classes"]),
            "soft_gate_preferred_actions": list(gate_contract["soft_gate_preferred_actions"]),
            "gate_risk_classes": list(gate_contract["gate_risk_classes"]),
            "autonomous_action_kinds": autonomous_action_kinds,
            "branch_statuses": list(outer_loop_policy.get("branch_statuses", [])),
            "recovery_statuses": list(outer_loop_policy.get("recovery_statuses", [])),
            },
            mode=resolved_mode,
            gate_contract=gate_contract,
        )

    def _action_authority(self, mission_state: Mapping[str, Any], action_kind: str) -> tuple[str, bool, str, str]:
        outer_loop = self._outer_loop_contract(mission_state)
        outer_loop_policy = self._outer_loop_policy_for_state(mission_state)
        action_classes = outer_loop_policy.get("action_classes", {})
        raw_action_policy = action_classes.get(action_kind, {})
        scope = str(raw_action_policy.get("scope", "internal")) if isinstance(raw_action_policy, Mapping) else "internal"
        requires_operator_approval = bool(
            raw_action_policy.get("requires_operator_approval", False)
            if isinstance(raw_action_policy, Mapping)
            else False
        )
        autonomous_action_kinds = set(_normalize_strings(outer_loop.get("autonomous_action_kinds")))
        if requires_operator_approval:
            return scope, True, "operator-reviewed", "pending"
        operating_mode = str(outer_loop.get("mode") or mission_state.get("mode") or "")
        if action_kind in autonomous_action_kinds and is_autonomous_operating_mode(
            operating_mode,
            default=str(outer_loop_policy.get("default_mode") or DEFAULT_OPERATING_MODE),
        ):
            return scope, False, "autonomous", "not-required"
        return scope, False, "mixed", "not-required"

    def _planned_action_from_pending(
        self,
        mission_state: Mapping[str, Any],
        pending_action: PendingMissionAction,
        *,
        kind: str,
        phase: str,
        force_status: str | None = None,
    ) -> MissionPlannedAction:
        scope, requires_operator_approval, _, _ = self._action_authority(mission_state, kind)
        _ = scope
        action_id = pending_action.action_id or _slug(
            f"{mission_state['mission_id']}-{phase}-{pending_action.role}-{kind}",
            fallback="mission-action",
        )
        decision_id = _slug(f"{mission_state['mission_id']}-{phase}-{kind}", fallback="mission-decision")
        requires = pending_action.requires_operator_approval
        if requires is None:
            requires = requires_operator_approval
        return MissionPlannedAction(
            action_id=action_id,
            mission_id=str(mission_state["mission_id"]),
            kind=kind,
            role=pending_action.role or _default_role_for_phase(phase),
            task=pending_action.task,
            phase=phase,
            decision_id=decision_id,
            branch_id=pending_action.branch_id,
            requires_operator_approval=bool(requires),
            status=force_status or pending_action.status or "pending",
            artifacts=pending_action.artifacts,
            output_paths=pending_action.output_paths,
            notes=pending_action.notes,
            produces_outputs=pending_action.produces_outputs,
            next_phase_on_success=pending_action.next_phase_on_success,
        )

    def _resolve_executor_dispatch(
        self,
        action: PendingMissionAction,
    ) -> tuple[MissionExecutorDispatch | None, str | None]:
        if not isinstance(action.executor, dict):
            return None, None
        executor_id = action.executor.get("id") or action.executor.get("executor_id")
        if not isinstance(executor_id, str) or not executor_id.strip():
            return None, "Executor hint is missing a valid id."
        params = action.executor.get("params")
        if not isinstance(params, Mapping):
            params = {key: value for key, value in action.executor.items() if key not in {"id", "executor_id"}}
        try:
            resolved_executor = MissionExecutorId(str(executor_id))
        except ValueError:
            return None, f"Unknown executor hint `{executor_id}`."
        try:
            executor_action = self._build_executor_action(resolved_executor, params)
        except (KeyError, TypeError, ValueError) as exc:
            return None, str(exc)
        registry = get_mission_executor_registry()
        executor = registry[resolved_executor]
        return (
            MissionExecutorDispatch(
                executor_id=resolved_executor,
                action=executor_action,
                summary=executor.summary,
            ),
            None,
        )

    def _phase_execution_hint(
        self,
        mission_state: Mapping[str, Any],
        *,
        phase: str,
        missing_outputs: tuple[str, ...],
    ) -> PendingMissionAction | None:
        raw_hints = mission_state.get("phase_execution_hints")
        if not isinstance(raw_hints, Mapping):
            return None
        raw_hint = raw_hints.get(phase)
        if not isinstance(raw_hint, Mapping):
            return None
        executor = raw_hint.get("executor")
        if not isinstance(executor, Mapping):
            return None
        return PendingMissionAction(
            role=_default_role_for_phase(phase),
            task="",
            kind=_default_kind_for_phase(phase),
            phase=phase,
            artifacts=_normalize_strings(raw_hint.get("artifacts")),
            notes=_normalize_strings(raw_hint.get("notes")),
            produces_outputs=_normalize_strings(raw_hint.get("produces_outputs")) or missing_outputs,
            executor=dict(executor),
            next_phase_on_success=(
                str(raw_hint["next_phase_on_success"]) if raw_hint.get("next_phase_on_success") is not None else None
            ),
        )

    def _build_executor_action(
        self,
        executor_id: MissionExecutorId,
        params: Mapping[str, Any],
    ) -> MissionExecutorAction:
        if executor_id == MissionExecutorId.RECURSIVE_AGENT:
            return RecursiveAgentExecutorAction(config_path=params["config_path"])
        if executor_id == MissionExecutorId.SELF_HEALING_QUEUE:
            return SelfHealingQueueExecutorAction(
                config_path=params["config_path"],
                policy_path=params.get("policy_path"),
            )
        if executor_id == MissionExecutorId.STAGE_KERNEL:
            return StageKernelExecutorAction(
                stage_id=params["stage_id"],
                config_path=params["config_path"],
                adapter_spec=params.get("adapter_spec"),
                pythonpath=tuple(params.get("pythonpath", ())),
            )
        if executor_id == MissionExecutorId.ADAPTATION_TRAINING:
            return AdaptationTrainingExecutorAction(
                training_config_path=params["training_config_path"],
                mission_state_path=params.get("mission_state_path"),
            )
        if executor_id == MissionExecutorId.EVALUATION_COMPARISON:
            return EvaluationComparisonExecutorAction(
                mission_state_path=params.get("mission_state_path"),
                manifest_paths=tuple(params.get("manifest_paths", ())),
                run_roots=tuple(params.get("run_roots", ())),
                contract_path=params.get("contract_path") or EvaluationComparisonExecutorAction.contract_path,
                artifact_name=params.get("artifact_name"),
            )
        if executor_id == MissionExecutorId.REPORT_SYNTHESIS:
            return ReportSynthesisExecutorAction(
                mission_state_path=params["mission_state_path"],
                contract_path=params.get("contract_path") or ReportSynthesisExecutorAction.contract_path,
                output_root=params.get("output_root"),
            )
        raise ValueError(f"Unsupported executor id `{executor_id.value}`.")

    def _failure_count(self, mission_state: Mapping[str, Any], evidence: MissionEvidence) -> int:
        count = max(evidence.failure_count, len(evidence.recent_failures))
        agent_driver = mission_state.get("agent_driver")
        if isinstance(agent_driver, Mapping):
            count = max(count, int(agent_driver.get("consecutive_failures", 0) or 0))
        runtime_recovery = mission_state.get("runtime_recovery")
        if isinstance(runtime_recovery, Mapping):
            counts = runtime_recovery.get("counts")
            if isinstance(counts, Mapping):
                failed_jobs = int(counts.get("failed_jobs", 0) or 0)
                blocked_jobs = int(counts.get("blocked_jobs", 0) or 0)
                count = max(count, failed_jobs + blocked_jobs)
        return count

    def _active_branch(
        self,
        branch_records: tuple[MissionBranchState, ...],
        *,
        allowed_targets: set[str],
        current_phase: str,
    ) -> MissionBranchState | None:
        if not branch_records:
            return None
        priorities = {
            "recovery-active": 0,
            "report-ready": 1,
            "replication-active": 2,
            "critique-ready": 3,
            "active": 4,
            "planned": 5,
        }
        candidates = [
            record
            for record in branch_records
            if record.status not in {"completed", "abandoned"}
            and (
                record.target_phase is None
                or record.target_phase == current_phase
                or record.target_phase in allowed_targets
                or not allowed_targets
            )
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: priorities.get(item.status, 99))[0]

    def _select_transition_metadata(
        self,
        mission_state: Mapping[str, Any],
        phase_contract: Mapping[str, Any],
        *,
        active_branch: MissionBranchState | None,
        prefer_recovery: bool,
    ) -> dict[str, str] | None:
        metadata = phase_contract.get("transition_metadata")
        if not isinstance(metadata, list):
            return None
        transition_entries = [item for item in metadata if isinstance(item, Mapping)]
        if not transition_entries:
            return None
        deterministic_route = self._matched_deterministic_route(
            mission_state,
            transition_entries=transition_entries,
            allowed_targets=set(_normalize_strings(phase_contract.get("transitions"))),
        )
        if deterministic_route is not None:
            return deterministic_route
        next_phase = str(mission_state.get("next_phase") or "").strip()
        if next_phase:
            for item in transition_entries:
                if str(item.get("target")) == next_phase:
                    return dict(item)
            return {
                "target": next_phase,
                "decision_type": "phase-transition",
                "summary": f"Continue the configured mission plan into `{next_phase}`.",
                "branch_status": "active",
                "recovery_status": "not-needed",
            }
        if active_branch is not None and active_branch.target_phase:
            for item in transition_entries:
                if str(item.get("target")) == active_branch.target_phase:
                    return dict(item)
        if prefer_recovery:
            for item in transition_entries:
                if str(item.get("recovery_status", "not-needed")) != "not-needed":
                    return dict(item)
        return dict(transition_entries[0])

    def _matched_deterministic_route(
        self,
        mission_state: Mapping[str, Any],
        *,
        transition_entries: list[Mapping[str, Any]],
        allowed_targets: set[str],
    ) -> dict[str, str] | None:
        routing_cfg = mission_state.get("deterministic_routing")
        if not isinstance(routing_cfg, Mapping) or not bool(routing_cfg.get("enabled")):
            return None
        current_phase = str(mission_state.get("current_phase") or "").strip()
        if not current_phase:
            return None
        raw_hints = mission_state.get("phase_execution_hints")
        if not isinstance(raw_hints, Mapping):
            return None
        raw_hint = raw_hints.get(current_phase)
        if not isinstance(raw_hint, Mapping):
            return None
        raw_routes = raw_hint.get("deterministic_routes")
        if raw_routes is None:
            return None
        if not isinstance(raw_routes, list):
            raise ValueError(f"Phase `{current_phase}` deterministic_routes must be a list.")
        for index, raw_rule in enumerate(raw_routes):
            if not isinstance(raw_rule, Mapping):
                raise ValueError(f"Phase `{current_phase}` deterministic route #{index + 1} must be a mapping.")
            if not self._deterministic_route_matches(raw_rule, mission_state):
                continue
            target = str(raw_rule.get("target") or "").strip()
            if not target:
                raise ValueError(f"Phase `{current_phase}` deterministic route #{index + 1} is missing a target.")
            if allowed_targets and target not in allowed_targets:
                raise ValueError(
                    f"Phase `{current_phase}` deterministic route target `{target}` is not allowed by the phase contract."
                )
            transition = next((dict(item) for item in transition_entries if str(item.get("target")) == target), None)
            if transition is None:
                transition = {
                    "target": target,
                    "decision_type": "phase-transition",
                    "summary": f"Continue the configured mission plan into `{target}`.",
                    "branch_status": "active",
                    "recovery_status": "not-needed",
                }
            rule_id = str(raw_rule.get("rule_id") or raw_rule.get("id") or f"{current_phase}-route-{index + 1}").strip()
            transition["routing_rule_id"] = rule_id
            if isinstance(raw_rule.get("decision_type"), str) and str(raw_rule.get("decision_type")).strip():
                transition["decision_type"] = str(raw_rule.get("decision_type")).strip()
            if isinstance(raw_rule.get("summary"), str) and str(raw_rule.get("summary")).strip():
                transition["summary"] = str(raw_rule.get("summary")).strip()
            if isinstance(raw_rule.get("branch_status"), str) and str(raw_rule.get("branch_status")).strip():
                transition["branch_status"] = str(raw_rule.get("branch_status")).strip()
            if isinstance(raw_rule.get("recovery_status"), str) and str(raw_rule.get("recovery_status")).strip():
                transition["recovery_status"] = str(raw_rule.get("recovery_status")).strip()
            return transition
        return None

    def _deterministic_route_matches(self, rule: Mapping[str, Any], mission_state: Mapping[str, Any]) -> bool:
        raw_when = rule.get("when")
        if isinstance(raw_when, Mapping):
            clauses = [raw_when]
        elif isinstance(raw_when, list):
            clauses = list(raw_when)
        else:
            raise ValueError("Deterministic routes must declare `when` as a mapping or list of mappings.")
        if not clauses:
            raise ValueError("Deterministic routes must include at least one `when` clause.")
        for index, clause in enumerate(clauses):
            if not isinstance(clause, Mapping):
                raise ValueError(f"Deterministic route clause #{index + 1} must be a mapping.")
            path = str(clause.get("path") or "").strip()
            if not path:
                raise ValueError(f"Deterministic route clause #{index + 1} is missing `path`.")
            value = _path_value(mission_state, path)
            exists_expected = clause.get("exists")
            if exists_expected is not None:
                if bool(exists_expected) != (value is not _MISSING):
                    return False
            if value is _MISSING:
                if any(key in clause for key in ("eq", "in", "gte", "lte")):
                    return False
                continue
            if "eq" in clause and value != clause.get("eq"):
                return False
            if "in" in clause:
                expected = clause.get("in")
                if not isinstance(expected, (list, tuple, set)):
                    raise ValueError(f"Deterministic route clause `{path}` must use a list/tuple/set for `in`.")
                if value not in expected:
                    return False
            if "gte" in clause:
                if float(value) < float(clause.get("gte")):
                    return False
            if "lte" in clause:
                if float(value) > float(clause.get("lte")):
                    return False
        return True

    def _directive_for_transition(self, transition_meta: Mapping[str, Any]) -> MissionDecisionDirective:
        branch_status = str(transition_meta.get("branch_status", "active"))
        recovery_status = str(transition_meta.get("recovery_status", "not-needed"))
        if recovery_status == "reroute-planned" or branch_status == "recovery-active":
            return MissionDecisionDirective.REROUTE
        if branch_status in {"replication-active", "report-ready", "critique-ready"}:
            return MissionDecisionDirective.BRANCH
        return MissionDecisionDirective.CONTINUE

    def _transition_outcome(
        self,
        mission_state: Mapping[str, Any],
        *,
        transition_meta: Mapping[str, Any],
        directive: MissionDecisionDirective,
        branch_record: MissionBranchState | None,
        missing_outputs: tuple[str, ...],
    ) -> MissionDecisionOutcome:
        mission_id = str(mission_state["mission_id"])
        from_phase = str(mission_state["current_phase"])
        to_phase = str(transition_meta.get("target") or mission_state.get("next_phase") or from_phase)
        branch_status = str(transition_meta.get("branch_status", "active"))
        recovery_status = str(transition_meta.get("recovery_status", "not-needed"))
        decision_type = str(transition_meta.get("decision_type", "phase-transition"))
        role = _default_role_for_phase(to_phase)
        decision_id = _slug(f"{mission_id}-{from_phase}-{to_phase}-{directive.value}", fallback="mission-decision")
        summary = str(transition_meta.get("summary") or f"Advance the mission from {from_phase} to {to_phase}.")
        resolved_branch = branch_record
        if resolved_branch is None and directive in {MissionDecisionDirective.BRANCH, MissionDecisionDirective.REROUTE}:
            branch_type = _branch_type_for_transition(
                target_phase=to_phase,
                branch_status=branch_status,
                recovery_status=recovery_status,
            )
            resolved_branch = MissionBranchState(
                branch_id=_slug(f"{mission_id}-{branch_type}-{to_phase}", fallback="mission-branch"),
                branch_type=branch_type,
                objective=summary,
                status=branch_status,
                recovery_status=recovery_status,
                runtime_owner="deeploop",
                source_phase=from_phase,
                target_phase=to_phase,
                created_by_decision_id=decision_id,
                notes=(summary,),
            )
        action = MissionPlannedAction(
            action_id=_slug(f"{mission_id}-{to_phase}-phase-transition", fallback="phase-transition"),
            mission_id=mission_id,
            kind=decision_type,
            role=role,
            task=self._transition_task(from_phase=from_phase, to_phase=to_phase, summary=summary, directive=directive),
            phase=to_phase,
            decision_id=decision_id,
            branch_id=resolved_branch.branch_id if resolved_branch is not None else None,
            requires_operator_approval=False,
            notes=(summary,),
        )
        transition = MissionTransition(
            from_phase=from_phase,
            to_phase=to_phase,
            branch_status=branch_status,
            recovery_status=recovery_status,
        )
        decision_notes = list((f"missing_outputs={', '.join(missing_outputs)}",) if missing_outputs else ())
        routing_rule_id = str(transition_meta.get("routing_rule_id") or "").strip()
        if routing_rule_id:
            decision_notes.append(f"deterministic_route_rule={routing_rule_id}")
        return MissionDecisionOutcome(
            directive=directive,
            decision=self._decision_record(
                mission_state,
                decision_id=decision_id,
                decision_type=decision_type,
                summary=summary,
                phase=from_phase,
                result_status="selected",
                transition=transition,
                selected_action_ids=(action.action_id,),
                selected_branch_ids=((resolved_branch.branch_id,) if resolved_branch is not None else ()),
                notes=tuple(decision_notes),
            ),
            action=action,
            branch_record=resolved_branch,
            missing_outputs=missing_outputs,
            notes=(summary,),
        )

    def _transition_task(
        self,
        *,
        from_phase: str,
        to_phase: str,
        summary: str,
        directive: MissionDecisionDirective,
    ) -> str:
        if directive == MissionDecisionDirective.REROUTE:
            return f"Reroute the mission from `{from_phase}` to `{to_phase}`. {summary}"
        if directive == MissionDecisionDirective.BRANCH:
            return f"Continue the mission through the `{to_phase}` branch. {summary}"
        return f"Advance the mission from `{from_phase}` to `{to_phase}`. {summary}"

    def _missing_outputs_outcome(
        self,
        mission_state: Mapping[str, Any],
        missing_outputs: tuple[str, ...],
        *,
        failure_count: int = 0,
    ) -> MissionDecisionOutcome:
        phase = str(mission_state["current_phase"])
        kind = _default_kind_for_phase(phase)
        role = _recovery_role_for_missing_outputs(phase, kind=kind, failure_count=failure_count)
        mission_id = str(mission_state["mission_id"])
        decision_id = _slug(f"{mission_id}-{phase}-missing-outputs", fallback="mission-decision")
        phase_hint = self._phase_execution_hint(mission_state, phase=phase, missing_outputs=missing_outputs)
        task = (
            f"Close the remaining `{phase}` outputs: {', '.join(missing_outputs)}."
            if missing_outputs
            else f"Continue the `{phase}` work."
        )
        notes = tuple(f"missing output: {output}" for output in missing_outputs)
        if role != _default_role_for_phase(phase):
            task = (
                f"Downscope `{phase}` after repeated failures and close the remaining outputs: "
                f"{', '.join(missing_outputs)}."
            )
            notes += ("recovery-downscope=planner",)
        executor_dispatch = None
        hint_artifacts: tuple[str, ...] = ()
        hint_notes: tuple[str, ...] = ()
        produces_outputs = missing_outputs
        next_phase_on_success = None
        executor_note = None
        if phase_hint is not None:
            executor_dispatch, executor_note = self._resolve_executor_dispatch(phase_hint)
            hint_artifacts = phase_hint.artifacts
            hint_notes = phase_hint.notes
            produces_outputs = phase_hint.produces_outputs or missing_outputs
            next_phase_on_success = phase_hint.next_phase_on_success
        action = MissionPlannedAction(
            action_id=_slug(f"{mission_id}-{phase}-missing-outputs", fallback="mission-action"),
            mission_id=mission_id,
            kind=kind,
            role=role,
            task=task,
            phase=phase,
            decision_id=decision_id,
            artifacts=hint_artifacts,
            notes=notes + hint_notes + ((_normalize_strings(executor_note)[0],) if executor_note else ()),
            produces_outputs=produces_outputs,
            executor_dispatch=executor_dispatch,
            next_phase_on_success=next_phase_on_success,
        )
        if executor_dispatch is not None:
            return self._selected_outcome(
                mission_state,
                directive=MissionDecisionDirective.DISPATCH,
                decision_type=kind,
                summary=f"Dispatch `{action.action_id}` through executor `{executor_dispatch.executor_id.value}` to close missing `{phase}` outputs.",
                action=action,
                missing_outputs=missing_outputs,
            )
        return MissionDecisionOutcome(
            directive=MissionDecisionDirective.CONTINUE,
            decision=self._decision_record(
                mission_state,
                decision_id=decision_id,
                decision_type=kind,
                summary=f"Continue `{phase}` because required outputs are still missing.",
                phase=phase,
                result_status="selected",
                selected_action_ids=(action.action_id,),
                notes=notes,
            ),
            action=action,
            missing_outputs=missing_outputs,
            notes=notes,
        )

    def _retry_outcome(
        self,
        mission_state: Mapping[str, Any],
        pending_action: PendingMissionAction,
        branch_record: MissionBranchState,
        missing_outputs: tuple[str, ...],
    ) -> MissionDecisionOutcome:
        phase = str(mission_state["current_phase"])
        kind = self._resolved_action_kind(mission_state, pending_action, phase)
        mission_id = str(mission_state["mission_id"])
        decision_id = _slug(f"{mission_id}-{phase}-{branch_record.branch_id}-retry", fallback="mission-decision")
        action = MissionPlannedAction(
            action_id=pending_action.action_id or _slug(f"{mission_id}-{phase}-retry", fallback="mission-action"),
            mission_id=mission_id,
            kind=kind,
            role=pending_action.role,
            task=pending_action.task,
            phase=phase,
            decision_id=decision_id,
            branch_id=branch_record.branch_id,
            requires_operator_approval=False,
            notes=pending_action.notes + ("retry planned by recovery policy",),
        )
        return MissionDecisionOutcome(
            directive=MissionDecisionDirective.RETRY,
            decision=self._decision_record(
                mission_state,
                decision_id=decision_id,
                decision_type=kind,
                summary=f"Retry `{action.action_id}` under recovery branch `{branch_record.branch_id}`.",
                phase=phase,
                result_status="selected",
                selected_action_ids=(action.action_id,),
                selected_branch_ids=(branch_record.branch_id,),
                notes=("retry-planned",),
            ),
            action=action,
            branch_record=branch_record,
            missing_outputs=missing_outputs,
            notes=("retry-planned",),
        )

    def _blocked_outcome(
        self,
        mission_state: Mapping[str, Any],
        *,
        decision_type: str,
        summary: str,
        action: MissionPlannedAction | None = None,
        missing_outputs: tuple[str, ...] = (),
        extra_notes: tuple[str, ...] = (),
    ) -> MissionDecisionOutcome:
        mission_id = str(mission_state["mission_id"])
        phase = str(mission_state["current_phase"])
        decision_id = _slug(f"{mission_id}-{phase}-{decision_type}-blocked", fallback="mission-decision")
        if action is not None and action.decision_id != decision_id:
            action = MissionPlannedAction(
                action_id=action.action_id,
                mission_id=action.mission_id,
                kind=action.kind,
                role=action.role,
                task=action.task,
                phase=action.phase,
                decision_id=decision_id,
                branch_id=action.branch_id,
                runtime_owner=action.runtime_owner,
                requires_operator_approval=action.requires_operator_approval,
                status="blocked",
                artifacts=action.artifacts,
                output_paths=action.output_paths,
                notes=action.notes,
                produces_outputs=action.produces_outputs,
                created_at=action.created_at,
                executor_dispatch=action.executor_dispatch,
                next_phase_on_success=action.next_phase_on_success,
            )
        notes = tuple(f"missing output: {output}" for output in missing_outputs) + tuple(extra_notes)
        return MissionDecisionOutcome(
            directive=MissionDecisionDirective.BLOCK,
            decision=self._decision_record(
                mission_state,
                decision_id=decision_id,
                decision_type=decision_type,
                summary=summary,
                phase=phase,
                result_status="blocked",
                selected_action_ids=((action.action_id,) if action is not None else ()),
                notes=notes,
            ),
            action=action,
            missing_outputs=missing_outputs,
            notes=notes,
        )

    def _failed_outcome(
        self,
        mission_state: Mapping[str, Any],
        *,
        failure_count: int,
        missing_outputs: tuple[str, ...],
    ) -> MissionDecisionOutcome:
        phase = str(mission_state["current_phase"])
        mission_id = str(mission_state["mission_id"])
        decision_id = _slug(f"{mission_id}-{phase}-failed", fallback="mission-decision")
        notes = tuple(f"missing output: {output}" for output in missing_outputs)
        if failure_count:
            notes += (f"failure_count={failure_count}",)
        return MissionDecisionOutcome(
            directive=MissionDecisionDirective.FAIL,
            decision=self._decision_record(
                mission_state,
                decision_id=decision_id,
                decision_type="operator-review",
                summary="Mission entered a failed autonomy state without a valid bounded recovery path.",
                phase=phase,
                result_status="rejected",
                notes=notes,
            ),
            missing_outputs=missing_outputs,
            notes=notes,
        )

    def _completion_contract_blockers(self, mission_state: Mapping[str, Any]) -> tuple[str, ...]:
        blockers: list[str] = []
        completed_phases = set(_normalize_strings(mission_state.get("completed_phases")))
        operator_inbox = mission_state.get("operator_inbox")
        operator_status = (
            str(operator_inbox.get("status") or "").strip().lower() if isinstance(operator_inbox, Mapping) else "clear"
        )
        if operator_status and operator_status != "clear":
            blockers.append("completion contract requires a clear operator inbox")

        for phase in ("execution", "critique"):
            if phase not in completed_phases:
                blockers.append(f"completion contract requires completed phase `{phase}`")
            required_outputs = tuple(
                str(item)
                for item in resolve_phase_contract_for_state(phase, mission_state=mission_state).get("outputs", ())
            )
            observed_outputs = set(_phase_outputs_for_state(mission_state, phase))
            for output in required_outputs:
                if output not in observed_outputs:
                    blockers.append(f"completion contract missing `{phase}` output `{output}`")

        replication_outputs = set(_phase_outputs_for_state(mission_state, "replication"))
        completion_contract = (
            mission_state.get("completion_contract") if isinstance(mission_state.get("completion_contract"), Mapping) else {}
        )
        replication_requirement = str(completion_contract.get("replication_requirement") or "").strip().lower()
        replication_waiver_reason = str(completion_contract.get("replication_waiver_reason") or "").strip()
        branch_closure_mode = str(mission_state.get("branch_closure_mode") or "").strip().lower()
        downstream_execution_authorized = mission_state.get("downstream_execution_authorized")
        final_report = mission_state.get("final_report") if isinstance(mission_state.get("final_report"), Mapping) else {}
        final_report_decision = str(final_report.get("decision") or "").strip().lower()
        final_report_closes_mission = final_report.get("close_mission") is True
        final_report_closes_execution = final_report.get("no_further_execution_reroute") is True
        inferred_waiver_reason = ""
        if branch_closure_mode == "no-win-under-budget" and downstream_execution_authorized is False:
            inferred_waiver_reason = (
                "Replication was waived because critique closed the branch as a no-win-under-budget outcome "
                "with no downstream execution authorized."
            )
        elif (
            final_report_decision == "no-promotion"
            and final_report_closes_mission
            and final_report_closes_execution
        ):
            inferred_waiver_reason = (
                "Replication was waived because the final report closed the mission as a no-promotion outcome "
                "with no further execution reroute authorized."
            )
        if "replication" in completed_phases:
            required_outputs = tuple(
                str(item)
                for item in resolve_phase_contract_for_state("replication", mission_state=mission_state).get("outputs", ())
            )
            for output in required_outputs:
                if output not in replication_outputs:
                    blockers.append(f"completion contract missing `replication` output `{output}`")
        elif replication_requirement == "waived":
            if not replication_waiver_reason and inferred_waiver_reason:
                replication_waiver_reason = inferred_waiver_reason
            if not replication_waiver_reason:
                blockers.append("completion contract requires a replication waiver reason when replication is waived")
        elif inferred_waiver_reason and not replication_requirement:
            replication_requirement = "waived"
            replication_waiver_reason = inferred_waiver_reason
        else:
            blockers.append("completion contract requires replication evidence or an explicit waiver")

        return tuple(blockers)

    def _complete_outcome(self, mission_state: Mapping[str, Any]) -> MissionDecisionOutcome:
        completion_blockers = self._completion_contract_blockers(mission_state)
        if completion_blockers:
            return self._blocked_outcome(
                mission_state,
                decision_type="final-report",
                summary="Final-report outputs exist, but the completion contract is still unsatisfied.",
                extra_notes=completion_blockers,
            )
        mission_id = str(mission_state["mission_id"])
        phase = str(mission_state["current_phase"])
        decision_id = _slug(f"{mission_id}-{phase}-complete", fallback="mission-decision")
        return MissionDecisionOutcome(
            directive=MissionDecisionDirective.COMPLETE,
            decision=self._decision_record(
                mission_state,
                decision_id=decision_id,
                decision_type="final-report",
                summary="Final-report outputs are present and the completion contract is satisfied.",
                phase=phase,
                result_status="selected",
            ),
        )

    def _selected_outcome(
        self,
        mission_state: Mapping[str, Any],
        *,
        directive: MissionDecisionDirective,
        decision_type: str,
        summary: str,
        action: MissionPlannedAction,
        missing_outputs: tuple[str, ...],
    ) -> MissionDecisionOutcome:
        decision_id = action.decision_id or _slug(
            f"{mission_state['mission_id']}-{action.phase}-{decision_type}",
            fallback="mission-decision",
        )
        notes = tuple(f"missing output: {output}" for output in missing_outputs)
        resolved_action = MissionPlannedAction(
            action_id=action.action_id,
            mission_id=action.mission_id,
            kind=action.kind,
            role=action.role,
            task=action.task,
            phase=action.phase,
            decision_id=decision_id,
            branch_id=action.branch_id,
            runtime_owner=action.runtime_owner,
            requires_operator_approval=action.requires_operator_approval,
            status=action.status,
            artifacts=action.artifacts,
            output_paths=action.output_paths,
            notes=action.notes,
            produces_outputs=action.produces_outputs,
            created_at=action.created_at,
            executor_dispatch=action.executor_dispatch,
            next_phase_on_success=action.next_phase_on_success,
        )
        return MissionDecisionOutcome(
            directive=directive,
            decision=self._decision_record(
                mission_state,
                decision_id=decision_id,
                decision_type=decision_type,
                summary=summary,
                phase=str(mission_state["current_phase"]),
                result_status="selected",
                selected_action_ids=(resolved_action.action_id,),
                notes=notes,
            ),
            action=resolved_action,
            missing_outputs=missing_outputs,
            notes=notes,
        )

    def _decision_record(
        self,
        mission_state: Mapping[str, Any],
        *,
        decision_id: str,
        decision_type: str,
        summary: str,
        phase: str,
        result_status: str,
        transition: MissionTransition | None = None,
        selected_action_ids: tuple[str, ...] = (),
        selected_branch_ids: tuple[str, ...] = (),
        notes: tuple[str, ...] = (),
    ) -> MissionDecisionRecord:
        scope, requires_operator_approval, authority_mode, approval_state = self._action_authority(
            mission_state,
            decision_type,
        )
        return MissionDecisionRecord(
            decision_id=decision_id,
            mission_id=str(mission_state["mission_id"]),
            decision_type=decision_type,
            summary=summary,
            phase=phase,
            scope=scope,
            authority_mode=authority_mode,
            requires_operator_approval=requires_operator_approval,
            approval_state=approval_state,
            result_status=result_status,
            recorded_at=now_utc(),
            transition=transition,
            selected_action_ids=selected_action_ids,
            selected_branch_ids=selected_branch_ids,
            notes=notes,
        )


def decide_next_mission_action(
    mission_state: Mapping[str, Any],
    *,
    evidence: MissionEvidence | Mapping[str, Any] | None = None,
    engine: MissionDecisionEngine | None = None,
) -> MissionDecisionOutcome:
    return (engine or MissionDecisionEngine()).decide(mission_state, evidence=evidence)
