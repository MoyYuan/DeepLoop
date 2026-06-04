from __future__ import annotations

from pathlib import Path
from typing import Any

from deeploop.autonomy.mission_contract_snapshot import resolve_phase_contract_for_state
from deeploop.core.bounded_memory import BoundedMemory
from deeploop.project_contract import CONTRACT_OPERATIONAL_FIELDS


def result_contract_markdown(result_json_path: Path) -> list[str]:
    return [
        "Write a machine-readable result JSON to:",
        f"- `{result_json_path}`",
        "",
        "Required JSON fields:",
        '- `status`: one of `"continue"`, `"complete"`, `"blocked"`, `"failed"`',
        "- `summary`: short handoff summary",
        "",
        "Canonical optional JSON fields:",
        "- `continuation`: object with `role`, `task`, and optional `artifacts`, `action_id`, `kind`, `phase`, `branch_id`, `decision_id`, `notes`",
        "- `action_result`: object with optional `mission_action_id`, `loop_action_id`, `status`, `phase`, `kind`, `branch_id`, `decision_id`, `output_paths`, `notes`",
        "- `phase_control`: object with optional `current_phase`, `next_phase`, `decision_type`, `branch_status`, `recovery_status`, `summary`",
        "- `produced_artifacts`: list of output paths",
        "- `findings`: list of short findings strings",
        "- `mission_state_updates`: object merged into mission_state.json",
        "",
        "Legacy compatibility fields still accepted:",
        "- `next_role`: role for the next fresh-context iteration",
        "- `next_task`: task for the next fresh-context iteration",
        "",
        "If the mission is done, set `status` to `complete`.",
    ]


def _resolve_contract_field_value(mission_state: dict[str, Any], field: str) -> Any:
    if field in mission_state:
        return mission_state[field]
    project_contract = mission_state.get("project_contract")
    if not isinstance(project_contract, dict):
        return None
    requirements = project_contract.get("contract_requirements")
    if isinstance(requirements, dict) and field in requirements:
        return requirements[field]
    metadata = project_contract.get("project_metadata")
    if isinstance(metadata, dict) and field in metadata:
        return metadata[field]
    return None


def _format_contract_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _contract_value_lines(value: Any, *, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}- {key}:")
                lines.extend(_contract_value_lines(child, indent=indent + 1))
            else:
                lines.append(f"{prefix}- {key}: {_format_contract_scalar(child)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_contract_value_lines(item, indent=indent + 1))
            else:
                lines.append(f"{prefix}- {_format_contract_scalar(item)}")
        return lines
    return [f"{prefix}- {_format_contract_scalar(value)}"]


def mission_contract_markdown(mission_state: dict[str, Any]) -> list[str]:
    acceptance_criteria = _resolve_contract_field_value(mission_state, "acceptance_criteria")
    lines: list[str] = []
    if acceptance_criteria is not None:
        lines.extend(
            [
                "## Mission acceptance criteria",
                "",
                "Project-contract pass/fail requirements; do not treat these as optional.",
                "",
                *_contract_value_lines(acceptance_criteria),
                "",
            ]
        )
    other_requirements: dict[str, Any] = {}
    for field in CONTRACT_OPERATIONAL_FIELDS:
        if field == "acceptance_criteria":
            continue
        value = _resolve_contract_field_value(mission_state, field)
        if value is not None:
            other_requirements[field] = value
    if other_requirements:
        lines.extend(["## Mission contract requirements", ""])
        for field, value in other_requirements.items():
            lines.append(f"### {field}")
            lines.append("")
            lines.extend(_contract_value_lines(value))
            lines.append("")
    return lines


def render_prompt(
    *,
    mission_state: dict[str, Any],
    action: dict[str, Any],
    sandbox: dict[str, str],
    recent_ledger: list[dict[str, Any]],
    recent_memory: list[dict[str, Any]],
    branch_record: dict[str, Any] | None,
    decision_record: dict[str, Any] | None,
    result_json_path: Path,
    iteration_number: int,
    max_iterations: int | None = None,
    bounded_memory: BoundedMemory | None = None,
) -> str:
    current_phase = str(mission_state.get("current_phase") or "")
    phase_policy = resolve_phase_contract_for_state(current_phase, mission_state=mission_state)
    autonomy_status = mission_state.get("autonomy_status", {})
    next_actions = mission_state.get("next_actions", {})
    outer_loop = mission_state.get("outer_loop", {})
    lines = [
        "# DeepLoop recursive agent iteration",
        "",
        f"- mission_id: `{mission_state.get('mission_id')}`",
        f"- iteration: `{iteration_number}`",
        *(
            [
                f"- recursive_iteration_budget: `{iteration_number}/{max_iterations}`",
                f"- recursive_iterations_remaining_after_this: `{max(max_iterations - iteration_number, 0)}`",
            ]
            if max_iterations is not None
            else []
        ),
        f"- role: `{action['role']}`",
        f"- loop_action_id: `{action.get('loop_action_id')}`",
        f"- mission_action_id: `{action.get('action_id')}`",
        f"- action_kind: `{action.get('kind')}`",
        f"- action_phase: `{action.get('phase')}`",
        f"- branch_id: `{action.get('branch_id')}`",
        f"- decision_id: `{action.get('decision_id')}`",
        f"- current_phase: `{current_phase}`",
        f"- next_phase: `{mission_state.get('next_phase')}`",
        f"- objective: {mission_state.get('objective')}",
        f"- autonomy_state: `{autonomy_status.get('state', 'unknown')}`",
        f"- autonomy_reason: {autonomy_status.get('reason', '')}",
        "",
        "## Current task",
        "",
        action["task"],
        "",
    ]
    phase_outputs = phase_policy.get("outputs", [])
    phase_transitions = phase_policy.get("transitions", [])
    transition_metadata = phase_policy.get("transition_metadata", [])
    phase_rules = phase_policy.get("terminal_rules", [])
    if isinstance(outer_loop, dict) and outer_loop:
        lines.extend(
            [
                "## Mission autonomy contract",
                "",
                f"- execution_mode: `{outer_loop.get('execution_mode', 'unknown')}`",
                f"- permissions_profile: `{outer_loop.get('permissions_profile', outer_loop.get('internal_execution', 'unknown'))}`",
                f"- intervention_profile: `{outer_loop.get('intervention_profile', 'unknown')}`",
                f"- external_publish: `{outer_loop.get('external_publish', 'unknown')}`",
                f"- hard_gate_profile: `{outer_loop.get('hard_gate_profile', 'unknown')}`",
            ]
        )
        autonomous_action_kinds = outer_loop.get("autonomous_action_kinds", [])
        if isinstance(autonomous_action_kinds, list) and autonomous_action_kinds:
            lines.append(f"- autonomous_action_kinds: `{', '.join(str(item) for item in autonomous_action_kinds)}`")
        hard_gate_risk_classes = outer_loop.get("hard_gate_risk_classes", [])
        if isinstance(hard_gate_risk_classes, list) and hard_gate_risk_classes:
            lines.append(f"- hard_gate_risk_classes: `{', '.join(str(item) for item in hard_gate_risk_classes)}`")
        soft_gate_preferred_actions = outer_loop.get("soft_gate_preferred_actions", [])
        if isinstance(soft_gate_preferred_actions, list) and soft_gate_preferred_actions:
            lines.append(f"- soft_gate_strategy: `{', '.join(str(item) for item in soft_gate_preferred_actions)}`")
        lines.append("")
    if phase_outputs or phase_transitions or phase_rules:
        lines.extend(["## Phase constraints", ""])
        if phase_outputs:
            lines.append("Required phase outputs:")
            lines.extend(f"- {item}" for item in phase_outputs)
            lines.append("")
        if phase_transitions:
            lines.append("Allowed next transitions:")
            lines.extend(f"- `{item}`" for item in phase_transitions)
            lines.append("")
        if transition_metadata:
            lines.append("Transition metadata:")
            for item in transition_metadata:
                if not isinstance(item, dict):
                    continue
                prefix = (
                    f"- `{item.get('target')}` via `{item.get('decision_type')}` "
                    f"(branch_status=`{item.get('branch_status')}`, recovery_status=`{item.get('recovery_status')}`)"
                )
                summary = str(item.get("summary") or "").strip()
                lines.append(f"{prefix}: {summary}" if summary else prefix)
            lines.append("")
        if phase_rules:
            lines.append("Relevant terminal/promotion rules:")
            lines.extend(f"- {item}" for item in phase_rules)
            lines.append("")
    lines.extend(mission_contract_markdown(mission_state))
    if isinstance(next_actions, dict):
        next_actions_summary = str(next_actions.get("summary") or "").strip()
        if next_actions_summary:
            lines.extend(["## Mission continuation context", "", next_actions_summary, ""])
    lines.extend(
        [
            "## Policy placement rule",
            "",
            "- Put universal runtime or operator-surface invariants in DeepLoop, not in ad hoc workarounds.",
            "- Put reusable project-agnostic methods in skills.",
            "- Put domain-specific scientific readiness rules in the substrate repo.",
            "- Put cross-repo safety or machine hygiene defaults in machine-wide instructions.",
            "- Do not compensate for a DeepLoop product gap by encoding it as a manual habit or pseudo-skill.",
            "",
            "## Foundational substrate rule",
            "",
            "- Treat the project repo as a minimal fact/contract substrate, not as the hidden home of DeepLoop orchestration or build code.",
            "- Substrate repos may provide the brief, benchmark/test data, baseline metrics, slice definitions, and scientific/safety rules DeepLoop starts from.",
            "- Those minimal substrate facts do not cap DeepLoop's scientific choices: DeepLoop may propose additional trusted datasets, better metrics, new evaluation slices, or new training plans when the science requires it.",
            "- DeepLoop owns build repo code, runtime scripts, generated configs, experiment implementation code, and other surfaces needed to design, build, train, evaluate, and run the work.",
            "- Do not add new DeepLoop-owned code, generated configs, or runtime/build logic to the substrate repo unless it is an explicitly documented temporary migration shim.",
            "",
        ]
    )
    if action["notes"]:
        lines.extend(["## Action notes", ""])
        lines.extend(f"- {item}" for item in action["notes"])
        lines.append("")
    if branch_record is not None:
        lines.extend(
            [
                "## Branch context",
                "",
                f"- branch_type: `{branch_record.get('branch_type')}`",
                f"- status: `{branch_record.get('status')}`",
                f"- recovery_status: `{branch_record.get('recovery_status')}`",
                f"- source_phase: `{branch_record.get('source_phase')}`",
                f"- target_phase: `{branch_record.get('target_phase')}`",
                f"- objective: {branch_record.get('objective')}",
                "",
            ]
        )
    if decision_record is not None:
        lines.extend(
            [
                "## Decision context",
                "",
                f"- decision_type: `{decision_record.get('decision_type')}`",
                f"- phase: `{decision_record.get('phase')}`",
                f"- scope: `{decision_record.get('scope')}`",
                f"- summary: {decision_record.get('summary')}",
                "",
            ]
        )
    artifacts = action.get("artifacts", [])
    if artifacts:
        lines.extend(["## Input artifacts", ""])
        lines.extend(f"- `{artifact}`" for artifact in artifacts)
        lines.append("")
    lines.extend(
        [
            "## Sandbox",
            "",
            f"- sandbox_root: `{sandbox['sandbox_root']}`",
            f"- inputs_dir: `{sandbox['inputs_dir']}`",
            f"- outputs_dir: `{sandbox['outputs_dir']}`",
            "",
            "## Rule sources",
            "",
        ]
    )
    lines.extend(f"- `{source}`" for source in sandbox["rule_sources"])
    lines.append("")
    if bounded_memory is not None:
        lines.append(bounded_memory.context_block())
        lines.append("")
    else:
        if recent_ledger:
            lines.extend(["## Recent mission ledger", ""])
            for entry in recent_ledger:
                lines.append(
                    f"- `{entry.get('created_at', 'unknown')}` `{entry.get('kind', 'unknown')}` `{entry.get('status', 'unknown')}`: {entry.get('summary', '')}"
                )
            lines.append("")
        if recent_memory:
            lines.extend(["## Recent recursive-loop memory", ""])
            for entry in recent_memory:
                lines.append(
                    f"- iteration `{entry.get('iteration')}` role `{entry.get('role')}` status `{entry.get('status')}`: {entry.get('summary', '')}"
                )
        lines.append("")
    lines.extend(["## Output contract", "", *result_contract_markdown(result_json_path)])
    lines.extend(
        [
            "",
            "## Working rules",
            "",
            "- This is a fresh-context iteration. Use the provided artifacts and external memory instead of assuming earlier context.",
            "- Write durable outputs only inside the sandbox outputs directory or mission artifact paths.",
            "- Prefer direct file create/edit tools for sandbox artifacts and agent_result.json; avoid shell-based file creation unless no direct file tool can satisfy the requirement.",
            "- Finish required file writes directly before concluding the iteration; do not leave simple artifact creation to long-running shell commands.",
            "- Record the next step explicitly when work should continue.",
            "- Do not stop early if the task can be advanced within the available artifacts and tools.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def iteration_summary_markdown(summary: dict[str, Any]) -> list[str]:
    lines = [
        f"# Recursive agent iteration {summary['iteration']}",
        "",
        f"- role: `{summary['role']}`",
        f"- loop_action_id: `{summary.get('loop_action_id')}`",
        f"- mission_action_id: `{summary.get('mission_action_id')}`",
        f"- action_kind: `{summary.get('action_kind')}`",
        f"- phase: `{summary.get('phase')}`",
        f"- branch_id: `{summary.get('branch_id')}`",
        f"- task: {summary['task']}",
        f"- status: `{summary['status']}`",
        f"- returncode: `{summary['returncode']}`",
        f"- started_at: `{summary['started_at']}`",
        f"- completed_at: `{summary['completed_at']}`",
        f"- prompt_path: `{summary['prompt_path']}`",
        f"- log_path: `{summary['log_path']}`",
    ]
    result = summary.get("result")
    if isinstance(result, dict):
        lines.extend(
            [
                "",
                "## Agent result",
                "",
                f"- summary: {result.get('summary')}",
                f"- next_role: `{result.get('next_role')}`",
                f"- next_task: {result.get('next_task')}",
            ]
        )
    normalized = summary.get("normalized_result")
    if isinstance(normalized, dict):
        continuation = normalized.get("continuation") or {}
        phase_control = normalized.get("phase_control") or {}
        action_result = normalized.get("action_result") or {}
        lines.extend(
            [
                "",
                "## Structured outcome",
                "",
                f"- continuation_role: `{continuation.get('role')}`",
                f"- continuation_task: {continuation.get('task')}",
                f"- action_result_status: `{action_result.get('status')}`",
                f"- phase_next: `{phase_control.get('next_phase')}`",
                f"- branch_status: `{phase_control.get('branch_status')}`",
                f"- recovery_status: `{phase_control.get('recovery_status')}`",
            ]
        )
    return lines


def loop_report_markdown(report: dict[str, Any]) -> list[str]:
    lines = [
        "# Recursive agent runtime",
        "",
        f"- mission_id: `{report['mission_id']}`",
        f"- loop_name: `{report['loop_name']}`",
        f"- status: `{report['status']}`",
        f"- iterations_completed: `{report['iterations_completed']}`",
        f"- consecutive_failures: `{report['consecutive_failures']}`",
        "",
        "## Iterations",
        "",
    ]
    for item in report["iterations"]:
        lines.append(
            f"- `{item['iteration']}` `{item['role']}` `{item.get('loop_action_id')}` "
            f"`{item.get('mission_action_id')}` -> `{item['status']}`"
        )
    return lines


__all__ = [
    "iteration_summary_markdown",
    "loop_report_markdown",
    "render_prompt",
    "result_contract_markdown",
]
