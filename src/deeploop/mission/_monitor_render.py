from __future__ import annotations

import json
from typing import Any, Mapping

from deeploop.mission._monitor_classification import _runtime_recovery_entries
from deeploop.mission._operator_surface import operator_response as _operator_response


def render_mission_snapshot(snapshot: dict[str, Any]) -> str:
    mission = snapshot["mission"]
    autonomy = mission.get("autonomy_status", {})
    outer_loop = snapshot.get("outer_loop", {})
    runtime = outer_loop.get("runtime") if isinstance(outer_loop, Mapping) else None
    current_action = outer_loop.get("current_action") if isinstance(outer_loop, Mapping) else None
    historical_action = outer_loop.get("historical_action") if isinstance(outer_loop, Mapping) else None
    recursive_agent = outer_loop.get("recursive_agent") if isinstance(outer_loop, Mapping) else None
    current_branch = outer_loop.get("current_branch") if isinstance(outer_loop, Mapping) else None
    operator_inbox = snapshot.get("operator_inbox", {})
    current_operator_request = (
        operator_inbox.get("current_request") if isinstance(operator_inbox, Mapping) else None
    )
    operator_console = snapshot.get("operator_console", {})
    next_commands = operator_console.get("next_commands", []) if isinstance(operator_console, Mapping) else []
    alternatives = operator_console.get("alternatives", []) if isinstance(operator_console, Mapping) else []
    operator_response = _operator_response(current_operator_request)
    budgets = snapshot.get("budgets", {})
    scheduler = snapshot.get("mission_scheduler")
    evidence = snapshot.get("evidence", {})
    promotion = evidence.get("promotion", {}) if isinstance(evidence, Mapping) else {}
    failures = snapshot.get("failures", {})

    lines = [
        "# DeepLoop operator console",
        "",
        "## Top summary",
        "",
        f"- operator_summary: {operator_console.get('headline')}",
        f"- is_running: `{'yes' if operator_console.get('is_running') else 'no'}`",
        f"- mission_state: `{operator_console.get('state')}`",
        f"- lifecycle_state: `{operator_console.get('lifecycle_state')}`",
        f"- operator_state: `{operator_console.get('operator_state')}`",
        f"- attention_level: `{operator_console.get('attention_level')}`",
        f"- next_step_owner: `{operator_console.get('next_step_owner')}`",
        f"- resume_policy: `{operator_console.get('resume_policy')}`",
        f"- process_status: `{operator_console.get('process_status')}`",
        f"- gate_class: `{operator_console.get('gate_class')}`",
    ]
    if operator_console.get("gate_detail"):
        lines.append(f"- gate_detail: `{operator_console.get('gate_detail')}`")
    if operator_console.get("request_id"):
        lines.append(f"- active_request: `{operator_console.get('request_id')}`")
    lines.extend(
        [
            f"- active_summary: {operator_console.get('summary')}",
            f"- state_reason: {operator_console.get('state_reason')}",
            f"- stop_reason: {operator_console.get('stop_reason') or 'n/a'}",
            f"- recommendation: {operator_console.get('recommendation')}",
            f"- continue: {operator_console.get('continue_summary')}",
        ]
    )
    if operator_console.get("budget_summary"):
        lines.append(f"- budget_summary: {operator_console.get('budget_summary')}")
    if operator_console.get("inner_loop_summary"):
        lines.append(f"- inner_loop_summary: {operator_console.get('inner_loop_summary')}")
    if operator_console.get("current_recursive_iteration"):
        lines.append(f"- current_recursive_iteration: {operator_console.get('current_recursive_iteration')}")
    if operator_console.get("eta_summary"):
        lines.append(f"- eta_summary: {operator_console.get('eta_summary')}")
    if operator_console.get("blocked_on"):
        lines.append(f"- blocked_on: {operator_console.get('blocked_on')}")
    if operator_console.get("focus_action_id"):
        lines.append(f"- focus_action: `{operator_console.get('focus_action_id')}`")
    if operator_console.get("focus_executor_id"):
        lines.append(f"- focus_executor: `{operator_console.get('focus_executor_id')}`")
    if isinstance(operator_response, Mapping):
        lines.append(
            f"- operator_feedback: `{operator_response.get('action')}` recorded at `{operator_response.get('recorded_at')}`"
        )
        if operator_response.get("note"):
            lines.append(f"- operator_feedback_note: {operator_response.get('note')}")

    lines.extend(["", "## Alternatives", ""])
    if alternatives:
        for alternative in alternatives[:4]:
            if not isinstance(alternative, Mapping):
                continue
            pros_text = "; ".join(str(item) for item in alternative.get("pros") or []) or "none"
            cons_text = "; ".join(str(item) for item in alternative.get("cons") or []) or "none"
            lines.extend(
                [
                    f"- `{alternative.get('option_id')}`: {alternative.get('summary')}",
                    f"  - pros: {pros_text}",
                    f"  - cons: {cons_text}",
                ]
            )
            next_steps = alternative.get("next_steps")
            if isinstance(next_steps, list) and next_steps:
                lines.append(f"  - next: {'; '.join(str(item) for item in next_steps[:3])}")
    else:
        lines.append("- No alternative operator paths are surfaced right now.")

    lines.extend(["", "## Exact next commands", ""])
    if next_commands:
        for index, entry in enumerate(next_commands, start=1):
            if not isinstance(entry, Mapping):
                continue
            lines.append(f"{index}. `{entry.get('command')}`")
            if entry.get("description"):
                lines.append(f"   - {entry.get('description')}")
    else:
        lines.append("- No management commands are available yet.")

    lines.extend(
        [
            "",
            "## Mission snapshot",
            "",
            f"- mission_id: `{mission.get('mission_id')}`",
            f"- title: {mission.get('title')}",
            f"- status: `{mission.get('status')}`",
            f"- current_phase: `{mission.get('current_phase')}`",
            f"- next_phase: `{mission.get('next_phase')}`",
            f"- autonomy_state: `{autonomy.get('state', 'unknown')}`",
            f"- autonomy_reason: {autonomy.get('reason', 'n/a')}",
        ]
    )
    if mission.get("next_actions_summary"):
        lines.append(f"- next_actions_summary: {mission['next_actions_summary']}")

    if isinstance(scheduler, Mapping):
        composition = scheduler.get("composition", {}) if isinstance(scheduler.get("composition"), Mapping) else {}
        lines.extend(
            [
                "",
                "## Mission scheduler",
                "",
                f"- scheduler_id: `{scheduler.get('scheduler_id')}`",
                f"- scheduler_status: `{scheduler.get('scheduler_status')}`",
                f"- scheduler_priority: `{scheduler.get('priority')}`",
                f"- fair_share_weight: `{scheduler.get('fair_share_weight')}`",
                f"- scheduler_budget_iterations: `{scheduler.get('mission_budget_iterations')}`",
                f"- scheduler_iterations_consumed: `{scheduler.get('iterations_consumed')}`",
                f"- scheduler_remaining_budget: `{scheduler.get('remaining_budget')}`",
                f"- scheduler_last_effective_priority: `{scheduler.get('last_effective_priority')}`",
                f"- scheduler_suppression_reason: {scheduler.get('suppression_reason') or 'none'}",
                f"- scheduler_active_operator_request: {scheduler.get('active_operator_request_id') or 'none'}",
            ]
        )
        if scheduler.get("last_scheduled_at"):
            lines.append(f"- scheduler_last_scheduled_at: `{scheduler.get('last_scheduled_at')}`")
        if composition:
            lines.append(
                "- scheduler_composition: "
                + ", ".join(f"{key}={value}" for key, value in sorted(composition.items()) if value)
            )

    lines.extend(["", "## Mission outer loop", ""])
    if isinstance(runtime, Mapping):
        lines.extend(
            [
                f"- runtime_status: `{runtime.get('status')}`",
                f"- iterations_completed: `{runtime.get('iterations_completed')}`",
                f"- max_iterations: `{runtime.get('max_iterations')}`",
                f"- remaining_iterations: `{runtime.get('remaining_iterations')}`",
                f"- last_decision_id: `{runtime.get('last_decision_id')}`",
                f"- last_action_id: `{runtime.get('last_action_id')}`",
                f"- last_branch_id: `{runtime.get('last_branch_id')}`",
                f"- last_executor_id: `{runtime.get('last_executor_id')}`",
            ]
        )
        executor_usage = runtime.get("executor_usage_counts")
        if isinstance(executor_usage, Mapping) and executor_usage:
            lines.append(
                "- executor_usage_counts: "
                + ", ".join(f"{executor}={count}" for executor, count in executor_usage.items())
            )
            lines.append(f"- recursive_agent_invocations: `{runtime.get('recursive_agent_invocations')}`")
        latest_history = runtime.get("latest_history") or []
        if isinstance(latest_history, list) and latest_history:
            latest = latest_history[-1]
            if isinstance(latest, Mapping):
                lines.append(
                    f"- latest_transition: `{latest.get('directive')}` `{latest.get('decision_id')}` -> `{latest.get('outcome_status')}`"
                )
        if runtime.get("status") != "running" and runtime.get("terminal_reason"):
            lines.append(f"- terminal_reason: {runtime['terminal_reason']}")
        recursive_runtime = runtime.get("recursive_agent")
        if isinstance(recursive_runtime, Mapping):
            lines.append(f"- recursive_agent_summary: {recursive_runtime.get('summary')}")
            lines.append(f"- recursive_agent_status: `{recursive_runtime.get('status')}`")
    else:
        lines.append("- runtime_status: `unavailable`")
        lines.append("- runtime_note: outer-loop runtime artifacts have not been written yet.")

    latest_decision = outer_loop.get("latest_decision")
    if outer_loop.get("mode"):
        lines.append(f"- operating_mode: `{outer_loop.get('mode')}`")
    if outer_loop.get("mode_summary"):
        lines.append(f"- operating_posture: {outer_loop.get('mode_summary')}")
    if outer_loop.get("permissions_profile"):
        lines.append(f"- permissions_profile: `{outer_loop.get('permissions_profile')}`")
    if outer_loop.get("intervention_profile"):
        lines.append(f"- intervention_profile: `{outer_loop.get('intervention_profile')}`")
    if outer_loop.get("hard_gate_profile"):
        lines.append(f"- hard_gate_profile: `{outer_loop.get('hard_gate_profile')}`")
    hard_gate_risk_classes = outer_loop.get("hard_gate_risk_classes")
    if isinstance(hard_gate_risk_classes, list) and hard_gate_risk_classes:
        lines.append(f"- hard_gate_risk_classes: `{', '.join(str(item) for item in hard_gate_risk_classes)}`")
    soft_gate_preferred_actions = outer_loop.get("soft_gate_preferred_actions")
    if isinstance(soft_gate_preferred_actions, list) and soft_gate_preferred_actions:
        lines.append(f"- soft_gate_strategy: `{', '.join(str(item) for item in soft_gate_preferred_actions)}`")
    if isinstance(latest_decision, Mapping):
        lines.append(
            f"- latest_decision: `{latest_decision.get('decision_type')}` {latest_decision.get('summary')}"
        )
    latest_soft_gate = outer_loop.get("latest_soft_gate")
    if isinstance(latest_soft_gate, Mapping):
        lines.append(
            f"- latest_soft_gate: `{latest_soft_gate.get('risk_class')}` {latest_soft_gate.get('reason')}"
        )
        if not isinstance(current_operator_request, Mapping):
            lines.append(
                "- soft_gate_status: autopilot kept control and will prefer retry, reroute, or downscope before asking the operator."
            )

    lines.extend(["", "## Current work", ""])
    if isinstance(historical_action, Mapping):
        lines.extend(
            [
                f"- outer_action: `{historical_action.get('action_id')}`",
                f"- outer_action_status: `{historical_action.get('status')}` (historical)",
                f"- outer_action_task: {historical_action.get('task')}",
            ]
        )
    if isinstance(current_action, Mapping):
        lines.extend(
            [
                f"- current_action: `{current_action.get('action_id')}`",
                f"- action_status: `{current_action.get('status')}`",
                f"- action_kind: `{current_action.get('kind')}`",
                f"- action_role: `{current_action.get('role')}`",
                f"- action_executor: `{current_action.get('executor_id') or 'n/a'}`",
                f"- action_task: {current_action.get('task')}",
            ]
        )
        if current_action.get("notes"):
            lines.append(f"- action_notes: {'; '.join(current_action['notes'])}")
    else:
        lines.append("- current_action: none surfaced")

    if isinstance(recursive_agent, Mapping):
        active_recursive_action = recursive_agent.get("active_action")
        lines.append(f"- current_recursive_iteration: {recursive_agent.get('summary')}")
        if isinstance(active_recursive_action, Mapping):
            lines.extend(
                [
                    f"- current_recursive_action: `{active_recursive_action.get('loop_action_id') or active_recursive_action.get('action_id') or 'n/a'}`",
                    f"- recursive_action_role: `{active_recursive_action.get('role')}`",
                    f"- recursive_action_phase: `{active_recursive_action.get('phase')}`",
                    f"- recursive_action_task: {active_recursive_action.get('task')}",
                ]
            )

    if isinstance(current_branch, Mapping):
        lines.extend(
            [
                f"- current_branch: `{current_branch.get('branch_id')}`",
                f"- branch_status: `{current_branch.get('status')}`",
                f"- branch_type: `{current_branch.get('branch_type')}`",
                f"- branch_target_phase: `{current_branch.get('target_phase') or 'n/a'}`",
                f"- branch_objective: {current_branch.get('objective')}",
            ]
        )
    else:
        lines.append("- current_branch: none surfaced")

    branch_counts = outer_loop.get("branch_counts")
    if isinstance(branch_counts, Mapping) and branch_counts:
        lines.append("- branch_counts: " + ", ".join(f"{status}={count}" for status, count in branch_counts.items()))

    lines.extend(["", "## Operator inbox", ""])
    if isinstance(current_operator_request, Mapping):
        blocker = current_operator_request.get("blocker", {})
        recommendation = current_operator_request.get("recommendation", {})
        lines.extend(
            [
                f"- current_request: `{current_operator_request.get('request_id')}`",
                f"- blocker: `{blocker.get('kind')}` `{blocker.get('risk_class')}`",
                f"- request_summary: {current_operator_request.get('summary')}",
                f"- recommendation: {recommendation.get('summary')}",
                f"- continue_command: `{current_operator_request.get('continue_command')}`",
            ]
        )
        if isinstance(operator_response, Mapping):
            lines.append(
                f"- recorded_operator_action: `{operator_response.get('action')}` at `{operator_response.get('recorded_at')}`"
            )
            if operator_response.get("note"):
                lines.append(f"- recorded_operator_note: {operator_response.get('note')}")
    else:
        lines.append("- operator_inbox: clear")
        if outer_loop.get("mode") == "sandboxed-yolo":
            lines.append("- operator_note: default sandboxed autopilot is still in control.")

    jobs = snapshot.get("jobs", {})
    lines.extend(["", "## Jobs and budgets", ""])
    for label in ("evaluation", "training", "other"):
        category = jobs.get(label, {})
        in_progress = category.get("in_progress", []) if isinstance(category, Mapping) else []
        pending = category.get("pending", []) if isinstance(category, Mapping) else []
        deferred = category.get("deferred", []) if isinstance(category, Mapping) else []
        in_progress_ids = ", ".join(f"`{item.get('action_id')}`" for item in in_progress) or "none"
        pending_ids = ", ".join(f"`{item.get('action_id')}`" for item in pending) or "none"
        deferred_ids = ", ".join(f"`{item.get('action_id')}`" for item in deferred) or "none"
        lines.append(f"- {label}_in_progress: {in_progress_ids}")
        lines.append(f"- {label}_pending: {pending_ids}")
        lines.append(f"- {label}_deferred: {deferred_ids}")
    lines.append(f"- budget_summary: {budgets.get('summary')}")
    compute_budget = budgets.get("compute", {}) if isinstance(budgets, Mapping) else {}
    token_budget = budgets.get("token", {}) if isinstance(budgets, Mapping) else {}
    cost_budget = budgets.get("cost", {}) if isinstance(budgets, Mapping) else {}
    eta_budget = budgets.get("eta", {}) if isinstance(budgets, Mapping) else {}
    if isinstance(compute_budget, Mapping):
        lines.append(f"- compute_budget_status: `{compute_budget.get('status')}`")
        lines.append(f"- compute_budget_summary: {compute_budget.get('summary')}")
        signals = compute_budget.get("signals")
        if isinstance(signals, list) and signals:
            lines.append(f"- compute_underuse_signals: {'; '.join(str(item) for item in signals[:3])}")
    if isinstance(token_budget, Mapping):
        lines.append(f"- token_budget_status: `{token_budget.get('status')}`")
        lines.append(f"- token_budget_summary: {token_budget.get('summary')}")
    if isinstance(cost_budget, Mapping):
        lines.append(f"- cost_budget_status: `{cost_budget.get('status')}`")
        lines.append(f"- cost_budget_summary: {cost_budget.get('summary')}")
    if isinstance(eta_budget, Mapping):
        lines.append(f"- eta_quality: `{eta_budget.get('quality')}`")
        lines.append(f"- eta_summary: {eta_budget.get('summary')}")
    unavailable_budgets = budgets.get("unavailable_budgets")
    if isinstance(unavailable_budgets, list) and unavailable_budgets:
        lines.append(f"- unavailable_budgets: {', '.join(unavailable_budgets)}")

    stage_runs = jobs.get("stage_runs", [])
    if isinstance(stage_runs, list) and stage_runs:
        lines.extend(["", "### Stage runs", ""])
        for stage_run in stage_runs[:5]:
            if not isinstance(stage_run, Mapping):
                continue
            lines.append(f"- `{stage_run.get('stage_id')}` -> `{stage_run.get('status')}`")
            if stage_run.get("progress_summary"):
                lines.append(f"  - progress: {stage_run.get('progress_summary')}")
            if stage_run.get("eta_summary"):
                lines.append(f"  - eta: {stage_run.get('eta_summary')}")
            if stage_run.get("compute_summary"):
                lines.append(f"  - compute: {stage_run.get('compute_summary')}")

    inner_loop = budgets.get("inner_loop", {}) if isinstance(budgets, Mapping) else {}
    lines.extend(["", "## Inner-loop progress", ""])
    if isinstance(inner_loop, Mapping) and inner_loop.get("status") == "tracked":
        lines.extend(
            [
                f"- active_stage: `{inner_loop.get('stage_id')}`",
                f"- progress_summary: {inner_loop.get('progress_summary')}",
                f"- eta_quality: `{inner_loop.get('eta_quality')}`",
                f"- eta_summary: {inner_loop.get('eta_summary')}",
                f"- compute_summary: {inner_loop.get('compute_summary')}",
                f"- token_summary: {inner_loop.get('token_summary')}",
                f"- cost_summary: {inner_loop.get('cost_summary')}",
            ]
        )
        if inner_loop.get("dataset_record_count") is not None:
            lines.append(f"- dataset_record_count: `{inner_loop.get('dataset_record_count')}`")
        if inner_loop.get("executed_examples") is not None:
            lines.append(f"- executed_examples: `{inner_loop.get('executed_examples')}`")
        if inner_loop.get("remaining_examples") is not None:
            lines.append(f"- remaining_examples: `{inner_loop.get('remaining_examples')}`")
    else:
        lines.append("- inner_loop: unavailable")

    lines.extend(["", "## Evidence and promotion", ""])
    current_outputs = evidence.get("current_phase_outputs", []) if isinstance(evidence, Mapping) else []
    phase_outputs = evidence.get("phase_outputs_by_phase", {}) if isinstance(evidence, Mapping) else {}
    lines.append(
        "- current_phase_outputs: "
        + (", ".join(f"`{item}`" for item in current_outputs) if current_outputs else "none surfaced")
    )
    if isinstance(phase_outputs, Mapping) and phase_outputs:
        for phase, outputs in phase_outputs.items():
            rendered_outputs = ", ".join(f"`{item}`" for item in outputs) if outputs else "none"
            lines.append(f"- phase_outputs[{phase}]: {rendered_outputs}")
    lines.extend(
        [
            f"- promotion_state: `{promotion.get('state')}`",
            f"- promotion_summary: {promotion.get('summary')}",
        ]
    )
    promotion_reasons = promotion.get("reasons")
    if isinstance(promotion_reasons, list) and promotion_reasons:
        lines.append(f"- promotion_reasons: {'; '.join(promotion_reasons[:3])}")
    adaptation_metric_ratchet = evidence.get("adaptation_metric_ratchet") if isinstance(evidence, Mapping) else None
    if isinstance(adaptation_metric_ratchet, Mapping):
        lines.append(
            "- adaptation_metric_ratchet: "
            f"`{adaptation_metric_ratchet.get('decision') or 'unknown'}`"
            f" -> `{adaptation_metric_ratchet.get('route_to') or 'n/a'}`"
            f" on `{adaptation_metric_ratchet.get('primary_metric') or 'n/a'}`"
        )
        if adaptation_metric_ratchet.get("summary"):
            lines.append(f"- adaptation_metric_summary: {adaptation_metric_ratchet.get('summary')}")

    lines.extend(["", "## Failures and routing", ""])
    lines.extend(
        [
            f"- failure_count: `{failures.get('failure_count')}`",
            f"- last_failure: {failures.get('last_failure') or 'n/a'}",
            f"- last_blocker: {failures.get('last_blocker') or 'n/a'}",
            f"- completion_reason: {failures.get('completion_reason') or 'n/a'}",
        ]
    )
    last_reroute = failures.get("last_reroute")
    if isinstance(last_reroute, Mapping):
        lines.append(
            f"- last_reroute: `{last_reroute.get('entry_id')}` -> `{last_reroute.get('route_to') or last_reroute.get('status')}`"
        )

    autonomy_gap_telemetry = snapshot.get("autonomy_gap_telemetry")
    if isinstance(autonomy_gap_telemetry, Mapping):
        telemetry_counts = autonomy_gap_telemetry.get("counts", {})
        recovery_preferences = autonomy_gap_telemetry.get("recovery_preferences", {})
        temporary_gap_categories = autonomy_gap_telemetry.get("temporary_gap_categories", {})
        lines.extend(
            [
                "",
                "## Autonomy gap telemetry",
                "",
                f"- summary: {autonomy_gap_telemetry.get('summary')}",
                f"- operator_requests_total: `{telemetry_counts.get('operator_requests_total', 0)}`",
                f"- temporary_gap_requests: `{telemetry_counts.get('temporary_gap_requests', 0)}`",
                f"- permanent_boundary_requests: `{telemetry_counts.get('permanent_boundary_requests', 0)}`",
                f"- soft_gates_total: `{telemetry_counts.get('soft_gates_total', 0)}`",
                f"- bounded_recovery_outcomes: `{telemetry_counts.get('bounded_recovery_outcomes', 0)}`",
                f"- unresolved_temporary_gaps: `{telemetry_counts.get('unresolved_temporary_gaps', 0)}`",
                f"- temporary_gap_auto_recovered: `{telemetry_counts.get('temporary_gap_auto_recovered', 0)}`",
                f"- temporary_gap_escalated: `{telemetry_counts.get('temporary_gap_escalated', 0)}`",
                (
                    "- temporary_gap_categories: "
                    + (
                        ", ".join(f"{key}={value}" for key, value in temporary_gap_categories.items())
                        if isinstance(temporary_gap_categories, Mapping) and temporary_gap_categories
                        else "n/a"
                    )
                ),
                (
                    "- recovery_preferences: "
                    f"retry=`{recovery_preferences.get('retry', 0)}` "
                    f"reroute=`{recovery_preferences.get('reroute', 0)}` "
                    f"downscope=`{recovery_preferences.get('downscope', 0)}`"
                ),
            ]
        )
        latest_temporary_gap = autonomy_gap_telemetry.get("latest_temporary_gap")
        if isinstance(latest_temporary_gap, Mapping):
            lines.append(
                "- latest_temporary_gap: "
                f"`{latest_temporary_gap.get('kind')}` {latest_temporary_gap.get('summary')}"
            )
        latest_temporary_gap_hint = autonomy_gap_telemetry.get("latest_temporary_gap_hint")
        if isinstance(latest_temporary_gap_hint, Mapping):
            lines.append(
                "- latest_temporary_gap_hint: "
                f"`{latest_temporary_gap_hint.get('category')}` "
                f"-> `{latest_temporary_gap_hint.get('recommended_action') or 'n/a'}` "
                f"[{latest_temporary_gap_hint.get('telemetry_class')}]"
            )
        latest_soft_gate = autonomy_gap_telemetry.get("latest_soft_gate")
        if isinstance(latest_soft_gate, Mapping):
            lines.append(
                "- latest_soft_gate_observed: "
                f"`{latest_soft_gate.get('risk_class')}` {latest_soft_gate.get('reason') or 'n/a'}"
            )

    progress = snapshot.get("progress")
    if isinstance(progress, dict):
        lines.extend(
            [
                "",
                "## Current progress",
                "",
                f"- step: `{progress.get('step')}`",
                f"- status: `{progress.get('status')}`",
                f"- updated_at: `{progress.get('updated_at')}`",
            ]
        )
        details = progress.get("details")
        if isinstance(details, dict) and details:
            lines.extend(["", "### Progress details", ""])
            for key in sorted(details):
                value = details[key]
                if isinstance(value, (dict, list)):
                    rendered = json.dumps(value, sort_keys=True)
                else:
                    rendered = str(value)
                lines.append(f"- {key}: `{rendered}`")

    launch = snapshot.get("launch")
    if isinstance(launch, dict):
        lines.extend(
            [
                "",
                "## Detached process",
                "",
                f"- pid: `{launch.get('pid')}`",
                f"- process_status: `{launch.get('process_status')}`",
                f"- started_at: `{launch.get('started_at', launch.get('launched_at'))}`",
                f"- log_path: `{launch.get('log_path')}`",
            ]
        )

    runtime_recovery = snapshot.get("runtime_recovery")
    if isinstance(runtime_recovery, dict):
        counts = runtime_recovery.get("counts", {})
        lines.extend(
            [
                "",
                "## Runtime queue",
                "",
                f"- queue_name: `{runtime_recovery.get('queue_name')}`",
                f"- completed_jobs: `{counts.get('completed_jobs', 0)}`",
                f"- blocked_jobs: `{counts.get('blocked_jobs', 0)}`",
                f"- warned_jobs: `{counts.get('warned_jobs', 0)}`",
                f"- failed_jobs: `{counts.get('failed_jobs', 0)}`",
                f"- recovered_jobs: `{counts.get('recovered_jobs', 0)}`",
                f"- rerouted_jobs: `{counts.get('rerouted_jobs', 0)}`",
                f"- resumed_jobs: `{counts.get('resumed_jobs', 0)}`",
            ]
        )
        entries = _runtime_recovery_entries(runtime_recovery)
        if entries:
            lines.extend(["", "### Queue entries", ""])
            for entry in entries[:8]:
                if not isinstance(entry, dict):
                    continue
                summary = f"- `{entry.get('entry_id')}` -> `{entry.get('final_status')}`"
                if entry.get("next_route_to"):
                    summary += f" (next_route_to=`{entry.get('next_route_to')}`)"
                lines.append(summary)

    end_to_end_summary = snapshot.get("end_to_end_summary")
    if isinstance(end_to_end_summary, dict):
        artifacts = end_to_end_summary.get("artifacts", {})
        lines.extend(
            [
                "",
                "## End-to-end artifacts",
                "",
                f"- summary_json_path: `{snapshot['artifacts']['summary_json_path']}`",
                f"- package_manifest: `{artifacts.get('package_manifest', snapshot['artifacts'].get('package_manifest', 'n/a'))}`",
                f"- package_summary: `{artifacts.get('package_summary', 'n/a')}`",
            ]
        )

    lines.extend(["", "## Recent ledger", ""])
    recent_ledger = snapshot.get("recent_ledger", [])
    if recent_ledger:
        for entry in recent_ledger:
            if not isinstance(entry, dict):
                continue
            lines.append(
                f"- `{entry.get('created_at', 'unknown')}` `{entry.get('kind', 'unknown')}` `{entry.get('status', 'unknown')}`: {entry.get('summary', '')}"
            )
    else:
        lines.append("- No ledger entries found.")

    lines.extend(["", "## Key paths", ""])
    for key in (
        "mission_state_path",
        "launch_metadata_path",
        "decision_log_path",
        "branch_log_path",
        "operator_request_log_path",
        "current_operator_request_path",
        "scheduler_state_path",
        "scheduler_summary_json_path",
        "scheduler_summary_markdown_path",
        "mission_runtime_state_path",
        "mission_runtime_history_path",
        "mission_runtime_summary_json_path",
        "mission_runtime_summary_markdown_path",
        "progress_json_path",
        "progress_markdown_path",
        "summary_json_path",
        "summary_markdown_path",
        "ledger_path",
    ):
        value = snapshot["artifacts"].get(key)
        if value:
            lines.append(f"- {key}: `{value}`")

    log_tail = snapshot.get("log_tail", [])
    if log_tail:
        lines.extend(["", "## Log tail", "", "```text", *log_tail, "```"])

    return "\n".join(lines) + "\n"
