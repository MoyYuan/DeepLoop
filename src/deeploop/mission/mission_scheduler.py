from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from deeploop.autonomy.operator_inbox import load_current_operator_request
from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.core.paths import REPO_ROOT
from deeploop.core.structured_io import load_json_object, write_json_object, write_markdown
from deeploop.mission.mission_monitor import build_mission_snapshot
from deeploop.mission.mission_runtime import run_mission
from deeploop.mission.mission_state import load_mission_state, write_mission_state
from deeploop.platform.contracts import sync_platform_expansion_bundle

DEFAULT_SCHEDULER_POLICY_PATH = REPO_ROOT / "configs" / "runtime" / "mission-scheduler.yaml"
_TERMINAL_MISSION_STATUSES = {"completed", "failed"}
_SCHEDULER_STATE_FILE = "scheduler_state.json"
_SCHEDULER_HISTORY_FILE = "scheduler_history.jsonl"
_SCHEDULER_SUMMARY_JSON_FILE = "summary.json"
_SCHEDULER_SUMMARY_MD_FILE = "summary.md"

@dataclass(frozen=True)
class MissionSchedulerBudgetPolicy:
    max_total_iterations: int = 12
    default_mission_budget_iterations: int = 6
    slice_iterations: int = 1
    max_consecutive_slices: int = 1

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "MissionSchedulerBudgetPolicy":
        payload = dict(raw or {})
        return cls(
            max_total_iterations=max(int(payload.get("max_total_iterations", 12) or 12), 1),
            default_mission_budget_iterations=max(
                int(payload.get("default_mission_budget_iterations", 6) or 6),
                1,
            ),
            slice_iterations=max(int(payload.get("slice_iterations", 1) or 1), 1),
            max_consecutive_slices=max(int(payload.get("max_consecutive_slices", 1) or 1), 1),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "max_total_iterations": self.max_total_iterations,
            "default_mission_budget_iterations": self.default_mission_budget_iterations,
            "slice_iterations": self.slice_iterations,
            "max_consecutive_slices": self.max_consecutive_slices,
        }

@dataclass(frozen=True)
class MissionSchedulerFairnessPolicy:
    starvation_window: int = 2
    aging_weight: float = 25.0

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "MissionSchedulerFairnessPolicy":
        payload = dict(raw or {})
        return cls(
            starvation_window=max(int(payload.get("starvation_window", 2) or 2), 1),
            aging_weight=max(float(payload.get("aging_weight", 25.0) or 25.0), 0.0),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "starvation_window": self.starvation_window,
            "aging_weight": self.aging_weight,
        }

@dataclass(frozen=True)
class MissionSchedulerPreemptionPolicy:
    higher_priority_delta: int = 1
    preempt_for_higher_priority: bool = True
    preempt_for_operator_attention: bool = True
    preempt_for_safety: bool = True

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "MissionSchedulerPreemptionPolicy":
        payload = dict(raw or {})
        return cls(
            higher_priority_delta=max(int(payload.get("higher_priority_delta", 1) or 1), 0),
            preempt_for_higher_priority=bool(payload.get("preempt_for_higher_priority", True)),
            preempt_for_operator_attention=bool(payload.get("preempt_for_operator_attention", True)),
            preempt_for_safety=bool(payload.get("preempt_for_safety", True)),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "higher_priority_delta": self.higher_priority_delta,
            "preempt_for_higher_priority": self.preempt_for_higher_priority,
            "preempt_for_operator_attention": self.preempt_for_operator_attention,
            "preempt_for_safety": self.preempt_for_safety,
        }

@dataclass(frozen=True)
class MissionSchedulerCompositionPolicy:
    open_request_policy: str = "pause-lower-priority"
    safety_block_policy: str = "pause-lower-priority"

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "MissionSchedulerCompositionPolicy":
        payload = dict(raw or {})
        open_request_policy = str(payload.get("open_request_policy", "pause-lower-priority") or "pause-lower-priority")
        safety_block_policy = str(payload.get("safety_block_policy", "pause-lower-priority") or "pause-lower-priority")
        allowed = {"continue", "pause-lower-priority", "halt-all"}
        if open_request_policy not in allowed:
            raise ValueError(f"Unsupported open_request_policy: {open_request_policy}")
        if safety_block_policy not in allowed:
            raise ValueError(f"Unsupported safety_block_policy: {safety_block_policy}")
        return cls(open_request_policy=open_request_policy, safety_block_policy=safety_block_policy)

    def to_payload(self) -> dict[str, Any]:
        return {
            "open_request_policy": self.open_request_policy,
            "safety_block_policy": self.safety_block_policy,
        }

@dataclass(frozen=True)
class MissionSchedulerPolicy:
    policy_name: str
    base_priority_weight: float
    budget: MissionSchedulerBudgetPolicy
    fairness: MissionSchedulerFairnessPolicy
    preemption: MissionSchedulerPreemptionPolicy
    composition: MissionSchedulerCompositionPolicy

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "MissionSchedulerPolicy":
        payload = dict(raw or {})
        return cls(
            policy_name=str(payload.get("policy_name", "deeploop-multi-mission-scheduler")),
            base_priority_weight=max(float(payload.get("base_priority_weight", 100.0) or 100.0), 1.0),
            budget=MissionSchedulerBudgetPolicy.from_mapping(
                payload.get("budget") if isinstance(payload.get("budget"), Mapping) else None
            ),
            fairness=MissionSchedulerFairnessPolicy.from_mapping(
                payload.get("fairness") if isinstance(payload.get("fairness"), Mapping) else None
            ),
            preemption=MissionSchedulerPreemptionPolicy.from_mapping(
                payload.get("preemption") if isinstance(payload.get("preemption"), Mapping) else None
            ),
            composition=MissionSchedulerCompositionPolicy.from_mapping(
                payload.get("composition") if isinstance(payload.get("composition"), Mapping) else None
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "base_priority_weight": self.base_priority_weight,
            "budget": self.budget.to_payload(),
            "fairness": self.fairness.to_payload(),
            "preemption": self.preemption.to_payload(),
            "composition": self.composition.to_payload(),
        }

@dataclass(frozen=True)
class MissionSchedulerMission:
    mission_state_path: Path
    mission_id: str
    priority: int = 100
    fair_share_weight: float = 1.0
    mission_budget_iterations: int | None = None

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        *,
        base_dir: Path,
        default_budget_iterations: int,
    ) -> "MissionSchedulerMission":
        raw_path = raw.get("mission_state") or raw.get("mission_state_path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("Each mission scheduler entry must define `mission_state`.")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        else:
            path = path.resolve()
        mission_state = load_mission_state(path)
        mission_id = str(raw.get("mission_id") or mission_state.get("mission_id") or path.parent.name)
        raw_budget = raw.get("mission_budget_iterations")
        mission_budget_iterations = max(int(raw_budget), 1) if raw_budget is not None else default_budget_iterations
        return cls(
            mission_state_path=path,
            mission_id=mission_id,
            priority=int(raw.get("priority", 100) or 100),
            fair_share_weight=max(float(raw.get("fair_share_weight", 1.0) or 1.0), 0.1),
            mission_budget_iterations=mission_budget_iterations,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "mission_state_path": str(self.mission_state_path),
            "priority": self.priority,
            "fair_share_weight": self.fair_share_weight,
            "mission_budget_iterations": self.mission_budget_iterations,
        }

@dataclass(frozen=True)
class MissionSchedulerConfig:
    scheduler_id: str
    scheduler_root: Path
    policy: MissionSchedulerPolicy
    missions: tuple[MissionSchedulerMission, ...]
    config_path: Path | None = None

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        *,
        base_dir: Path,
        config_path: Path | None = None,
    ) -> "MissionSchedulerConfig":
        default_policy = _load_yaml(DEFAULT_SCHEDULER_POLICY_PATH) if DEFAULT_SCHEDULER_POLICY_PATH.exists() else {}
        policy_path = raw.get("policy_path")
        policy_payload: dict[str, Any] = dict(default_policy)
        if isinstance(policy_path, str) and policy_path.strip():
            resolved_policy_path = Path(policy_path).expanduser()
            if not resolved_policy_path.is_absolute():
                resolved_policy_path = (base_dir / resolved_policy_path).resolve()
            else:
                resolved_policy_path = resolved_policy_path.resolve()
            policy_payload = _merge_mappings(policy_payload, _load_yaml(resolved_policy_path))
        if isinstance(raw.get("policy"), Mapping):
            policy_payload = _merge_mappings(policy_payload, dict(raw["policy"]))
        policy = MissionSchedulerPolicy.from_mapping(policy_payload)

        missions_raw = raw.get("missions")
        if not isinstance(missions_raw, list) or not missions_raw:
            raise ValueError("Mission scheduler configs must declare at least one mission entry.")
        missions = tuple(
            MissionSchedulerMission.from_mapping(
                item,
                base_dir=base_dir,
                default_budget_iterations=policy.budget.default_mission_budget_iterations,
            )
            for item in missions_raw
            if isinstance(item, Mapping)
        )
        if not missions:
            raise ValueError("Mission scheduler configs did not contain any valid mission entries.")

        scheduler_id = str(raw.get("scheduler_id") or "deeploop-multi-mission-scheduler").strip() or "deeploop-multi-mission-scheduler"
        scheduler_root_raw = raw.get("scheduler_root")
        if isinstance(scheduler_root_raw, str) and scheduler_root_raw.strip():
            scheduler_root = Path(scheduler_root_raw).expanduser()
            if not scheduler_root.is_absolute():
                scheduler_root = (base_dir / scheduler_root).resolve()
            else:
                scheduler_root = scheduler_root.resolve()
        else:
            scheduler_root = (base_dir / "runtime" / scheduler_id).resolve()
        return cls(
            scheduler_id=scheduler_id,
            scheduler_root=scheduler_root,
            policy=policy,
            missions=missions,
            config_path=config_path,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "scheduler_id": self.scheduler_id,
            "scheduler_root": str(self.scheduler_root),
            "config_path": str(self.config_path) if self.config_path is not None else None,
            "policy": self.policy.to_payload(),
            "missions": [mission.to_payload() for mission in self.missions],
        }

@dataclass
class _MissionView:
    spec: MissionSchedulerMission
    mission_state: dict[str, Any]
    record: dict[str, Any]
    mission_status: str
    open_operator_request: dict[str, Any] | None
    open_operator_request_id: str | None
    safety_blocked: bool
    wait_cycles: int
    effective_priority: float
    remaining_budget: int | None
    suppression_reason: str | None = None
    preemption_reason: str | None = None

def _merge_mappings(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merge_mappings(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged

def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded

def _write_markdown(path: Path, lines: list[str]) -> None:
    write_markdown(path, lines)

def _history_path(scheduler_root: Path) -> Path:
    return scheduler_root / _SCHEDULER_HISTORY_FILE

def _state_path(scheduler_root: Path) -> Path:
    return scheduler_root / _SCHEDULER_STATE_FILE

def _summary_json_path(scheduler_root: Path) -> Path:
    return scheduler_root / _SCHEDULER_SUMMARY_JSON_FILE

def _summary_markdown_path(scheduler_root: Path) -> Path:
    return scheduler_root / _SCHEDULER_SUMMARY_MD_FILE

def load_mission_scheduler_config(config_path: Path) -> MissionSchedulerConfig:
    resolved = config_path.expanduser().resolve()
    return MissionSchedulerConfig.from_mapping(_load_yaml(resolved), base_dir=resolved.parent, config_path=resolved)

def _load_existing_scheduler_state(config: MissionSchedulerConfig) -> dict[str, Any] | None:
    path = _state_path(config.scheduler_root)
    if not path.exists():
        return None
    return load_json_object(path)

def _default_scheduler_state(config: MissionSchedulerConfig) -> dict[str, Any]:
    started_at = now_utc()
    return {
        "schema_version": 1,
        "scheduler_id": config.scheduler_id,
        "scheduler_root": str(config.scheduler_root),
        "config_path": str(config.config_path) if config.config_path is not None else None,
        "status": "initialized",
        "started_at": started_at,
        "updated_at": started_at,
        "cycles_completed": 0,
        "iterations_dispatched": 0,
        "last_selected_mission_id": None,
        "last_effective_priority": None,
        "consecutive_slices": 0,
        "terminal_reason": None,
        "policy": config.policy.to_payload(),
        "history_path": str(_history_path(config.scheduler_root)),
        "summary_json_path": str(_summary_json_path(config.scheduler_root)),
        "summary_markdown_path": str(_summary_markdown_path(config.scheduler_root)),
        "missions": {
            spec.mission_id: {
                **spec.to_payload(),
                "iterations_consumed": 0,
                "last_scheduled_at": None,
                "last_scheduled_cycle": None,
                "latest_result_status": None,
                "latest_terminal_reason": None,
                "suppression_reason": None,
                "last_effective_priority": None,
                "open_operator_request_id": None,
                "safety_blocked": False,
            }
            for spec in config.missions
        },
        "preemptions": [],
        "composition": {},
    }

def _reconcile_scheduler_state(config: MissionSchedulerConfig, existing: dict[str, Any] | None) -> dict[str, Any]:
    state = existing or _default_scheduler_state(config)
    state["scheduler_id"] = config.scheduler_id
    state["scheduler_root"] = str(config.scheduler_root)
    state["config_path"] = str(config.config_path) if config.config_path is not None else None
    state["policy"] = config.policy.to_payload()
    missions = state.setdefault("missions", {})
    for spec in config.missions:
        record = missions.get(spec.mission_id, {}) if isinstance(missions.get(spec.mission_id), dict) else {}
        missions[spec.mission_id] = {
            **record,
            **spec.to_payload(),
            "iterations_consumed": int(record.get("iterations_consumed", 0) or 0),
            "last_scheduled_at": record.get("last_scheduled_at"),
            "last_scheduled_cycle": record.get("last_scheduled_cycle"),
            "latest_result_status": record.get("latest_result_status"),
            "latest_terminal_reason": record.get("latest_terminal_reason"),
            "suppression_reason": record.get("suppression_reason"),
            "last_effective_priority": record.get("last_effective_priority"),
            "open_operator_request_id": record.get("open_operator_request_id"),
            "safety_blocked": bool(record.get("safety_blocked", False)),
        }
    return state

def _load_operator_request(mission_state_path: Path, mission_state: Mapping[str, Any]) -> dict[str, Any] | None:
    operator_inbox = mission_state.get("operator_inbox") if isinstance(mission_state.get("operator_inbox"), Mapping) else {}
    outer_loop = mission_state.get("outer_loop") if isinstance(mission_state.get("outer_loop"), Mapping) else {}
    raw_path = operator_inbox.get("current_operator_request_path") or outer_loop.get("current_operator_request_path")
    if isinstance(raw_path, str) and raw_path.strip():
        path = Path(raw_path).expanduser().resolve()
    else:
        path = mission_state_path.parent / "current_operator_request.json"
    if not path.exists():
        return None
    request = load_current_operator_request(path)
    return request if isinstance(request, dict) and request else None

def _runtime_iterations(mission_state_path: Path, mission_state: Mapping[str, Any]) -> int:
    runtime = mission_state.get("mission_runtime") if isinstance(mission_state.get("mission_runtime"), Mapping) else {}
    iterations = runtime.get("iterations_completed")
    if isinstance(iterations, int):
        return iterations
    raw_state_path = runtime.get("state_path")
    if isinstance(raw_state_path, str) and raw_state_path.strip():
        path = Path(raw_state_path).expanduser().resolve()
        if path.exists():
            try:
                loaded = load_json_object(path)
            except (json.JSONDecodeError, ValueError):
                return 0
            return int(loaded.get("iterations_completed", 0) or 0)
    default_state_path = mission_state_path.parent / "runtime" / "mission_outer_runtime" / "runtime_state.json"
    if default_state_path.exists():
        return int(load_json_object(default_state_path).get("iterations_completed", 0) or 0)
    return 0

def _safety_blocked(mission_state: Mapping[str, Any], open_request: Mapping[str, Any] | None) -> bool:
    if open_request is not None:
        blocker = open_request.get("blocker") if isinstance(open_request.get("blocker"), Mapping) else {}
        if str(blocker.get("kind") or "") == "hard-gate":
            return True
    status = str(mission_state.get("status") or "")
    return status == "failed"

def _remaining_budget(record: Mapping[str, Any], spec: MissionSchedulerMission) -> int | None:
    budget = spec.mission_budget_iterations
    if budget is None:
        return None
    consumed = int(record.get("iterations_consumed", 0) or 0)
    return max(int(budget) - consumed, 0)

def _effective_priority(*, spec: MissionSchedulerMission, wait_cycles: int, policy: MissionSchedulerPolicy) -> float:
    aging_bonus = float(wait_cycles) * policy.fairness.aging_weight * spec.fair_share_weight
    return float(spec.priority) * policy.base_priority_weight + aging_bonus

def _compose_views(config: MissionSchedulerConfig, state: dict[str, Any]) -> tuple[list[_MissionView], dict[str, Any]]:
    views: list[_MissionView] = []
    requesting: list[tuple[str, int]] = []
    safety_blocking: list[tuple[str, int]] = []
    cycles_completed = int(state.get("cycles_completed", 0) or 0)

    for spec in config.missions:
        mission_state = load_mission_state(spec.mission_state_path)
        record = state["missions"][spec.mission_id]
        wait_cycles = cycles_completed - int(record.get("last_scheduled_cycle", -1) or -1) - 1
        wait_cycles = max(wait_cycles, 0)
        open_request = _load_operator_request(spec.mission_state_path, mission_state)
        open_request_id = str(open_request.get("request_id")) if isinstance(open_request, Mapping) and open_request.get("request_id") else None
        safety_blocked = _safety_blocked(mission_state, open_request)
        if open_request_id is not None:
            requesting.append((spec.mission_id, spec.priority))
        if safety_blocked:
            safety_blocking.append((spec.mission_id, spec.priority))
        views.append(
            _MissionView(
                spec=spec,
                mission_state=mission_state,
                record=record,
                mission_status=str(mission_state.get("status") or "running"),
                open_operator_request=dict(open_request) if isinstance(open_request, Mapping) else None,
                open_operator_request_id=open_request_id,
                safety_blocked=safety_blocked,
                wait_cycles=wait_cycles,
                effective_priority=_effective_priority(spec=spec, wait_cycles=wait_cycles, policy=config.policy),
                remaining_budget=_remaining_budget(record, spec),
            )
        )

    composition = {
        "open_request_policy": config.policy.composition.open_request_policy,
        "safety_block_policy": config.policy.composition.safety_block_policy,
        "open_request_mission_ids": [mission_id for mission_id, _ in requesting],
        "safety_blocking_mission_ids": [mission_id for mission_id, _ in safety_blocking],
    }

    operator_priority_floor = None
    if requesting and config.policy.composition.open_request_policy == "pause-lower-priority":
        operator_priority_floor = max(priority for _, priority in requesting)
    if requesting and config.policy.composition.open_request_policy == "halt-all":
        composition["halt_reason"] = "operator-request-open"

    safety_priority_floor = None
    if safety_blocking and config.policy.composition.safety_block_policy == "pause-lower-priority":
        safety_priority_floor = max(priority for _, priority in safety_blocking)
    if safety_blocking and config.policy.composition.safety_block_policy == "halt-all":
        composition["halt_reason"] = "safety-blocked-mission"

    for view in views:
        if view.mission_status in _TERMINAL_MISSION_STATUSES:
            view.suppression_reason = "terminal"
        elif view.remaining_budget == 0:
            view.suppression_reason = "mission-budget-exhausted"
        elif view.open_operator_request_id is not None:
            view.suppression_reason = "operator-request-open"
        elif composition.get("halt_reason"):
            view.suppression_reason = str(composition["halt_reason"])
        elif operator_priority_floor is not None and view.spec.priority < operator_priority_floor:
            view.suppression_reason = "operator-focus"
        elif safety_priority_floor is not None and view.spec.priority < safety_priority_floor:
            view.suppression_reason = "safety-composition"
        elif view.mission_status == "blocked":
            view.suppression_reason = "blocked"
    return views, composition

def _select_view(
    config: MissionSchedulerConfig,
    state: dict[str, Any],
    views: list[_MissionView],
    composition: Mapping[str, Any],
) -> _MissionView | None:
    eligible = [view for view in views if view.suppression_reason is None]
    if not eligible:
        return None

    last_selected = state.get("last_selected_mission_id")
    consecutive = int(state.get("consecutive_slices", 0) or 0)
    if last_selected is not None and consecutive >= config.policy.budget.max_consecutive_slices and len(eligible) > 1:
        alternate = [view for view in eligible if view.spec.mission_id != last_selected]
        if alternate:
            for view in alternate:
                view.preemption_reason = "fairness-window"
            eligible = alternate

    starved = [view for view in eligible if view.wait_cycles >= config.policy.fairness.starvation_window]
    candidates = starved or eligible
    chosen = sorted(
        candidates,
        key=lambda item: (
            item.effective_priority,
            item.wait_cycles,
            item.spec.priority,
            item.spec.mission_id,
        ),
        reverse=True,
    )[0]

    if state.get("last_selected_mission_id") and state.get("last_selected_mission_id") != chosen.spec.mission_id:
        previous_priority = 0
        for view in views:
            if view.spec.mission_id == state.get("last_selected_mission_id"):
                previous_priority = view.spec.priority
                break
        if chosen.preemption_reason is None:
            if composition.get("halt_reason") == "operator-request-open" and config.policy.preemption.preempt_for_operator_attention:
                chosen.preemption_reason = "operator-focus"
            elif composition.get("halt_reason") == "safety-blocked-mission" and config.policy.preemption.preempt_for_safety:
                chosen.preemption_reason = "safety-composition"
            elif (
                config.policy.preemption.preempt_for_higher_priority
                and chosen.spec.priority - previous_priority >= config.policy.preemption.higher_priority_delta
            ):
                chosen.preemption_reason = "higher-priority-ready"
    return chosen

def _append_history(scheduler_root: Path, payload: dict[str, Any]) -> None:
    append_jsonl(_history_path(scheduler_root), payload)

def _write_scheduler_surface(config: MissionSchedulerConfig, state: dict[str, Any], views: list[_MissionView]) -> None:
    summary_json_path = _summary_json_path(config.scheduler_root)
    summary_markdown_path = _summary_markdown_path(config.scheduler_root)
    state_path = _state_path(config.scheduler_root)
    view_map = {view.spec.mission_id: view for view in views}
    for spec in config.missions:
        mission_state = load_mission_state(spec.mission_state_path)
        view = view_map.get(spec.mission_id)
        record = state["missions"][spec.mission_id]
        mission_state["mission_scheduler"] = {
            "scheduler_id": config.scheduler_id,
            "scheduler_state_path": str(state_path),
            "scheduler_summary_json_path": str(summary_json_path),
            "scheduler_summary_markdown_path": str(summary_markdown_path),
            "scheduler_status": state.get("status"),
            "priority": spec.priority,
            "fair_share_weight": spec.fair_share_weight,
            "mission_budget_iterations": spec.mission_budget_iterations,
            "iterations_consumed": int(record.get("iterations_consumed", 0) or 0),
            "remaining_budget": _remaining_budget(record, spec),
            "last_scheduled_at": record.get("last_scheduled_at"),
            "last_scheduled_cycle": record.get("last_scheduled_cycle"),
            "last_effective_priority": record.get("last_effective_priority"),
            "suppression_reason": view.suppression_reason if view is not None else record.get("suppression_reason"),
            "active_operator_request_id": view.open_operator_request_id if view is not None else None,
            "composition": dict(state.get("composition", {})),
        }
        write_mission_state(spec.mission_state_path, mission_state)
        sync_platform_expansion_bundle(spec.mission_state_path, mission_state=mission_state)

def _scheduler_summary(config: MissionSchedulerConfig, state: dict[str, Any]) -> dict[str, Any]:
    mission_snapshots = [build_mission_snapshot(spec.mission_state_path, log_tail_lines=0, ledger_tail=0) for spec in config.missions]
    recent_history = []
    history_path = _history_path(config.scheduler_root)
    if history_path.exists():
        recent_history = [
            json.loads(line)
            for line in history_path.read_text(encoding="utf-8").splitlines()[-12:]
            if line.strip()
        ]
    return {
        **state,
        "config": config.to_payload(),
        "mission_snapshots": mission_snapshots,
        "recent_history": recent_history,
    }

def render_mission_scheduler_summary(summary: dict[str, Any]) -> str:
    policy = summary.get("policy", {}) if isinstance(summary.get("policy"), Mapping) else {}
    budget = policy.get("budget", {}) if isinstance(policy.get("budget"), Mapping) else {}
    fairness = policy.get("fairness", {}) if isinstance(policy.get("fairness"), Mapping) else {}
    composition = summary.get("composition", {}) if isinstance(summary.get("composition"), Mapping) else {}
    lines = [
        "# DeepLoop multi-mission scheduler",
        "",
        f"- scheduler_id: `{summary.get('scheduler_id')}`",
        f"- status: `{summary.get('status')}`",
        f"- cycles_completed: `{summary.get('cycles_completed')}`",
        f"- iterations_dispatched: `{summary.get('iterations_dispatched')}`",
        f"- last_selected_mission_id: `{summary.get('last_selected_mission_id')}`",
        f"- terminal_reason: {summary.get('terminal_reason') or 'n/a'}",
        "",
        "## Policy",
        "",
        f"- policy_name: `{policy.get('policy_name')}`",
        f"- base_priority_weight: `{policy.get('base_priority_weight')}`",
        f"- max_total_iterations: `{budget.get('max_total_iterations')}`",
        f"- default_mission_budget_iterations: `{budget.get('default_mission_budget_iterations')}`",
        f"- slice_iterations: `{budget.get('slice_iterations')}`",
        f"- max_consecutive_slices: `{budget.get('max_consecutive_slices')}`",
        f"- starvation_window: `{fairness.get('starvation_window')}`",
        f"- aging_weight: `{fairness.get('aging_weight')}`",
        f"- open_request_policy: `{composition.get('open_request_policy')}`",
        f"- safety_block_policy: `{composition.get('safety_block_policy')}`",
        "",
        "## Missions",
        "",
    ]
    missions = summary.get("missions", {}) if isinstance(summary.get("missions"), Mapping) else {}
    for mission_id in sorted(missions):
        record = missions[mission_id]
        lines.extend(
            [
                f"- `{mission_id}` priority=`{record.get('priority')}` status=`{record.get('latest_result_status') or 'pending'}` consumed=`{record.get('iterations_consumed')}` remaining_budget=`{record.get('mission_budget_iterations') if record.get('mission_budget_iterations') is not None else 'unbounded'}`",
                f"  - suppression_reason: {record.get('suppression_reason') or 'none'}",
                f"  - open_operator_request_id: {record.get('open_operator_request_id') or 'none'}",
                f"  - last_scheduled_at: {record.get('last_scheduled_at') or 'never'}",
            ]
        )
    preemptions = summary.get("preemptions") if isinstance(summary.get("preemptions"), list) else []
    lines.extend(["", "## Recent preemptions", ""])
    if preemptions:
        for event in preemptions[-5:]:
            if not isinstance(event, Mapping):
                continue
            lines.append(
                f"- cycle `{event.get('cycle')}` `{event.get('from_mission_id')}` -> `{event.get('to_mission_id')}` because `{event.get('reason')}`"
            )
    else:
        lines.append("- No preemption events recorded.")
    return "\n".join(lines) + "\n"

def _write_summary(config: MissionSchedulerConfig, state: dict[str, Any]) -> dict[str, Any]:
    summary = _scheduler_summary(config, state)
    write_json_object(_summary_json_path(config.scheduler_root), summary)
    _write_markdown(_summary_markdown_path(config.scheduler_root), render_mission_scheduler_summary(summary).splitlines())
    return summary

def _record_scheduler_ledger(config: MissionSchedulerConfig, state: dict[str, Any], *, summary: str, status: str) -> None:
    ledger_path = config.scheduler_root / "ledger.jsonl"
    append_jsonl(
        ledger_path,
        make_ledger_entry(
            kind="mission-scheduler",
            mission_id=config.scheduler_id,
            summary=summary,
            status=status,
            related_paths=[
                str(_state_path(config.scheduler_root)),
                str(_history_path(config.scheduler_root)),
                str(_summary_json_path(config.scheduler_root)),
                str(_summary_markdown_path(config.scheduler_root)),
            ],
            metadata={
                "scheduler_id": config.scheduler_id,
                "cycles_completed": state.get("cycles_completed"),
                "iterations_dispatched": state.get("iterations_dispatched"),
            },
        ),
    )

def run_mission_scheduler(
    config_or_path: MissionSchedulerConfig | Path,
    *,
    runner: Callable[..., dict[str, Any]] = run_mission,
) -> dict[str, Any]:
    config = config_or_path if isinstance(config_or_path, MissionSchedulerConfig) else load_mission_scheduler_config(config_or_path)
    config.scheduler_root.mkdir(parents=True, exist_ok=True)
    state = _reconcile_scheduler_state(config, _load_existing_scheduler_state(config))

    while int(state.get("iterations_dispatched", 0) or 0) < config.policy.budget.max_total_iterations:
        views, composition = _compose_views(config, state)
        state["composition"] = dict(composition)
        chosen = _select_view(config, state, views, composition)
        if chosen is None:
            halt_reason = composition.get("halt_reason")
            if halt_reason:
                state["status"] = "blocked"
                state["terminal_reason"] = str(halt_reason)
            elif composition.get("open_request_mission_ids"):
                state["status"] = "blocked"
                state["terminal_reason"] = "operator-review-required"
            elif composition.get("safety_blocking_mission_ids"):
                state["status"] = "blocked"
                state["terminal_reason"] = "safety-blocked-mission"
            else:
                state["status"] = "completed"
                state["terminal_reason"] = "No runnable missions remain within policy and budget bounds."
            break

        previous = state.get("last_selected_mission_id")
        if previous and previous != chosen.spec.mission_id and chosen.preemption_reason:
            event = {
                "event": "preemption",
                "recorded_at": now_utc(),
                "cycle": int(state.get("cycles_completed", 0) or 0) + 1,
                "from_mission_id": previous,
                "to_mission_id": chosen.spec.mission_id,
                "reason": chosen.preemption_reason,
            }
            state.setdefault("preemptions", []).append(event)
            _append_history(config.scheduler_root, event)

        before_iterations = _runtime_iterations(chosen.spec.mission_state_path, chosen.mission_state)
        max_iterations = before_iterations + config.policy.budget.slice_iterations
        result = runner(chosen.spec.mission_state_path, max_iterations=max_iterations)
        refreshed_state = load_json_object(chosen.spec.mission_state_path)
        after_iterations = _runtime_iterations(chosen.spec.mission_state_path, refreshed_state)
        consumed = max(after_iterations - before_iterations, 0)
        if consumed <= 0 and str(result.get("status") or "") not in _TERMINAL_MISSION_STATUSES:
            state["status"] = "failed"
            state["terminal_reason"] = f"Mission `{chosen.spec.mission_id}` made no scheduling progress."
            break

        mission_record = state["missions"][chosen.spec.mission_id]
        mission_record["iterations_consumed"] = int(mission_record.get("iterations_consumed", 0) or 0) + consumed
        mission_record["last_scheduled_at"] = now_utc()
        mission_record["last_scheduled_cycle"] = int(state.get("cycles_completed", 0) or 0)
        mission_record["latest_result_status"] = result.get("status")
        mission_record["latest_terminal_reason"] = result.get("terminal_reason")
        mission_record["last_effective_priority"] = chosen.effective_priority
        mission_record["suppression_reason"] = None
        mission_record["open_operator_request_id"] = chosen.open_operator_request_id
        mission_record["safety_blocked"] = chosen.safety_blocked

        state["cycles_completed"] = int(state.get("cycles_completed", 0) or 0) + 1
        state["iterations_dispatched"] = int(state.get("iterations_dispatched", 0) or 0) + consumed
        state["last_effective_priority"] = chosen.effective_priority
        if state.get("last_selected_mission_id") == chosen.spec.mission_id:
            state["consecutive_slices"] = int(state.get("consecutive_slices", 0) or 0) + 1
        else:
            state["consecutive_slices"] = 1
        state["last_selected_mission_id"] = chosen.spec.mission_id
        state["status"] = "running"
        state["updated_at"] = now_utc()
        _append_history(
            config.scheduler_root,
            {
                "event": "dispatch",
                "recorded_at": state["updated_at"],
                "cycle": state["cycles_completed"],
                "mission_id": chosen.spec.mission_id,
                "result_status": result.get("status"),
                "iterations_consumed": consumed,
                "effective_priority": chosen.effective_priority,
                "preemption_reason": chosen.preemption_reason,
            },
        )
        write_json_object(_state_path(config.scheduler_root), state)
        post_views, post_composition = _compose_views(config, state)
        state["composition"] = dict(post_composition)
        _write_scheduler_surface(config, state, post_views)
        _write_summary(config, state)

        if str(result.get("status") or "") in _TERMINAL_MISSION_STATUSES:
            continue

    else:
        state["status"] = "budget-exhausted"
        state["terminal_reason"] = "Reached scheduler max_total_iterations budget."

    views, composition = _compose_views(config, state)
    state["composition"] = dict(composition)
    state["updated_at"] = now_utc()
    write_json_object(_state_path(config.scheduler_root), state)
    _write_scheduler_surface(config, state, views)
    summary = _write_summary(config, state)
    _record_scheduler_ledger(
        config,
        state,
        summary=f"Scheduler finished with status `{state.get('status')}` after {state.get('cycles_completed')} cycle(s).",
        status=str(state.get("status") or "unknown"),
    )
    return {
        "status": state.get("status"),
        "terminal_reason": state.get("terminal_reason"),
        "scheduler_root": config.scheduler_root,
        "state_path": _state_path(config.scheduler_root),
        "history_path": _history_path(config.scheduler_root),
        "summary_json_path": _summary_json_path(config.scheduler_root),
        "summary_markdown_path": _summary_markdown_path(config.scheduler_root),
        "cycles_completed": state.get("cycles_completed"),
        "iterations_dispatched": state.get("iterations_dispatched"),
        "missions": summary.get("missions"),
        "preemptions": summary.get("preemptions"),
        "composition": summary.get("composition"),
    }

__all__ = [
    "DEFAULT_SCHEDULER_POLICY_PATH",
    "MissionSchedulerBudgetPolicy",
    "MissionSchedulerCompositionPolicy",
    "MissionSchedulerConfig",
    "MissionSchedulerFairnessPolicy",
    "MissionSchedulerMission",
    "MissionSchedulerPolicy",
    "MissionSchedulerPreemptionPolicy",
    "load_mission_scheduler_config",
    "render_mission_scheduler_summary",
    "run_mission_scheduler",
]
