from __future__ import annotations

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


def default_role_for_phase(phase: str) -> str:
    return _PHASE_ROLE_DEFAULTS.get(phase, "planner")


def default_kind_for_phase(phase: str) -> str:
    return _PHASE_ACTION_KIND_DEFAULTS.get(phase, "artifact-edit")

