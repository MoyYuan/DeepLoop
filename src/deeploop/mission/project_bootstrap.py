from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from deeploop.mission.orchestrator import DEFAULT_OPERATING_MODE
from deeploop.project_contract import CONTRACT_OPERATIONAL_FIELDS, discover_project_contract

DEFAULT_BOOTSTRAP_ROLES = [
    "planner",
    "literature-scout",
    "dataset-strategist",
    "experiment-designer",
    "execution-operator",
    "critic-verifier",
    "report-synthesizer",
]

DEFAULT_BOOTSTRAP_PHASES = [
    "idea-intake",
    "literature-review",
    "question-design",
    "benchmark-selection",
    "experiment-design",
    "execution",
    "critique",
    "replication",
    "final-report",
]

DEFAULT_BOOTSTRAP_AUTOPILOT = {"max_iterations": 64}
DEFAULT_RECURSIVE_AGENT_AUTOPILOT = {
    "max_iterations": 4,
}
DEFAULT_PHASE_EXECUTION_HINTS = {
    "idea-intake": {"executor": "recursive-agent"},
    "literature-review": {"executor": "recursive-agent"},
    "question-design": {"executor": "recursive-agent", "next_phase_on_success": "benchmark-selection"},
    "benchmark-selection": {"executor": "recursive-agent"},
    "experiment-design": {"executor": "recursive-agent"},
    "execution": {"executor": "recursive-agent", "next_phase_on_success": "critique"},
    "critique": {"executor": "recursive-agent", "next_phase_on_success": "replication"},
    "replication": {"executor": "recursive-agent", "next_phase_on_success": "final-report"},
    "final-report": {"executor": "report-synthesis"},
}

DEFAULT_BOOTSTRAP_CONSTRAINT = (
    "Treat the project folder as a minimal fact/contract substrate; DeepLoop owns "
    "build repo code, runtime scripts, generated configs, and experiment logic."
)
DEFAULT_DELIVERABLES = [
    "mission summary",
    "run manifests",
    "metrics summary",
    "findings summary",
    "artifact readiness notes",
]
DEFAULT_SPLIT_POLICY = (
    "Use an explicit holdout evaluation split and forbid test-set-directed iteration "
    "until the operator approves a stronger split contract."
)
DEFAULT_BENCHMARK_POLICY = (
    "Compare against the strongest reproducible starting baseline available from the "
    "project substrate or the simplest credible baseline DeepLoop can materialize."
)
DEFAULT_NOVELTY_TARGET = "Optimize for measurable improvement over baseline, not novelty claims."
DEFAULT_COMPUTE_BUDGET = "Use the bootstrap autopilot budget conservatively until an explicit compute budget is provided."
DEFAULT_STOP_RULES = "Stop on blocking prerequisites, exhausted budget, or lack of measurable progress."
DEFAULT_PUBLICATION_BOUNDARY = "Treat outputs as internal-only unless the operator explicitly approves external publication."
DEFAULT_LEAKAGE_GUARDRAIL = (
    "Assume strict no-leakage handling: holdout/test data must not inform prompt, feature, or hyperparameter choices."
)
_KICKOFF_DOC_HINTS = ("project-brief", "kickoff", "brief", "readme")
_PATH_HINT_FILE_EXTENSIONS = "csv|tsv|jsonl|json|parquet|txt"
_IDENTIFIER_PATTERN = r"[A-Za-z0-9_.\-]+"
_TARGET_VARIABLE_PATTERN = rf"\btarget(?: variable| column| label)?(?: is|:)?\s+[`'\"]?({_IDENTIFIER_PATTERN})"
_LABEL_COLUMN_PATTERN = rf"\blabel(?: column)?(?: is|:)?\s+[`'\"]?({_IDENTIFIER_PATTERN})"
_PREDICTION_TARGET_PATTERN = rf"\bpredict(?:ing)?\s+[`'\"]?({_IDENTIFIER_PATTERN})"
_TRANSLATION_TARGET_PATTERN = rf"\btranslate\b.*?\bfrom\s+({_IDENTIFIER_PATTERN})\s+\bto\s+({_IDENTIFIER_PATTERN})"
_COMPUTE_BUDGET_PATTERN = r"\b(\d+)\s*(gpu|cpu)\s*hours?\b"
_EXCLUDED_TARGET_KEYWORDS = {"quality", "performance", "metrics", "baseline"}
_TASK_TYPE_PATTERNS = (
    ("translation", ("translation", "translate", "bilingual")),
    ("summarization", ("summarization", "summarize", "summary generation")),
    ("generation", ("generation", "generate", "next token", "completion")),
    ("retrieval", ("retrieval", "search", "rank", "ranking")),
    ("classification", ("classifier", "classification", "classify")),
    ("regression", ("regression", "regressor", "predict", "forecast", "estimate")),
    ("benchmarking", ("benchmark", "baseline comparison", "ablation")),
)


def _clean_text(value: Any, *, fallback: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return fallback


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def _flatten_text_fragments(value: Any) -> list[str]:
    flattened: list[str] = []
    if isinstance(value, str):
        text = _collapse_whitespace(value.strip())
        return [text] if text else []
    if isinstance(value, list):
        for item in value:
            flattened.extend(_flatten_text_fragments(item))
        return flattened
    if isinstance(value, dict):
        for key, item in value.items():
            flattened.extend(_flatten_text_fragments(f"{key}:"))
            flattened.extend(_flatten_text_fragments(item))
        return flattened
    if value is None:
        return []
    text = _collapse_whitespace(str(value).strip())
    return [text] if text else []


def _merge_mapping(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_mapping(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _promoted_contract_requirements_for_config(contract: dict[str, Any], project_metadata: dict[str, Any]) -> dict[str, Any]:
    requirements = contract.get("contract_requirements") if isinstance(contract.get("contract_requirements"), dict) else {}
    promoted = {field: requirements[field] for field in CONTRACT_OPERATIONAL_FIELDS if field in requirements}
    human_inputs = project_metadata.get("human_inputs") if isinstance(project_metadata.get("human_inputs"), dict) else {}
    for field in CONTRACT_OPERATIONAL_FIELDS:
        if field in promoted:
            continue
        if field in project_metadata:
            promoted[field] = project_metadata[field]
        # Plain-folder starters historically declare budgets under
        # `project.human_inputs`; keep that location operational while also
        # promoting `budgets` as a first-class mission contract field.
        elif field == "budgets" and field in human_inputs:
            promoted[field] = human_inputs[field]
    return promoted


def _slugify(value: str) -> str:
    slug_chars: list[str] = []
    pending_dash = False
    for char in value.lower():
        if char.isalnum():
            if pending_dash and slug_chars:
                slug_chars.append("-")
            slug_chars.append(char)
            pending_dash = False
        elif slug_chars:
            pending_dash = True
    slug = "".join(slug_chars).strip("-")
    return slug or "deeploop-project"


def _preferred_kickoff_docs(docs: list[str]) -> list[Path]:
    def _rank(path: Path) -> tuple[int, str]:
        lower_name = path.name.lower()
        for index, hint in enumerate(_KICKOFF_DOC_HINTS):
            if hint in lower_name:
                return (index, lower_name)
        return (len(_KICKOFF_DOC_HINTS), lower_name)

    existing = [Path(doc) for doc in docs if Path(doc).exists()]
    return sorted(existing, key=_rank)


def _normalize_kickoff_text(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\s{0,3}(?:[#>*-]+|\d+\.)\s*", "", line).strip()
        if cleaned.lower() in {"kickoff", "project brief", "brief"}:
            continue
        cleaned_lines.append(cleaned)
    return _collapse_whitespace(" ".join(line for line in cleaned_lines if line))


def _read_kickoff_text(docs: list[str]) -> str:
    for doc_path in _preferred_kickoff_docs(docs):
        text = _normalize_kickoff_text(doc_path.read_text(encoding="utf-8").strip())
        if text:
            return text
    return ""


def _truncate_text(text: str, *, limit: int = 800) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _summarize_text(text: str, *, fallback: str) -> str:
    cleaned = _collapse_whitespace(text.strip())
    if not cleaned:
        return fallback
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    if not sentences:
        return fallback
    summary = " ".join(sentences[:2])
    return summary if len(summary) <= 220 else _truncate_text(summary, limit=220)


def _first_sentence(text: str, *, fallback: str) -> str:
    cleaned = _collapse_whitespace(text.strip())
    if not cleaned:
        return fallback
    match = re.search(r"^.*?[.!?](?:\s|$)", cleaned)
    if match:
        return match.group(0).strip()
    return _truncate_text(cleaned, limit=220)


def _extract_path_hints(text: str) -> list[str]:
    matches = re.findall(
        rf"(?:~?/|\.{{1,2}}/)[A-Za-z0-9._/-]+|[A-Za-z0-9._/-]+\.(?:{_PATH_HINT_FILE_EXTENSIONS})",
        text,
    )
    seen: set[str] = set()
    ordered: list[str] = []
    for match in matches:
        normalized = match.strip(".,;:()[]{}")
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def _first_mapping_value(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", [], {}):
            return mapping[key]
    return None


def _coerce_summary_value(value: Any) -> str | list[str] | dict[str, Any] | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        return _collapse_whitespace(value.strip())
    if isinstance(value, list):
        cleaned: list[str | list[str] | dict[str, Any]] = []
        for entry in value:
            item = _coerce_summary_value(entry)
            if item in (None, "", [], {}):
                continue
            cleaned.append(item)
        return cleaned or None
    if isinstance(value, dict):
        cleaned = {
            str(key): item
            for key, raw_item in value.items()
            if (item := _coerce_summary_value(raw_item)) not in (None, "", [], {})
        }
        return cleaned or None
    return _collapse_whitespace(str(value))


def _infer_task_type(text: str) -> str:
    lower_text = text.lower()
    if any(hint in lower_text for hint in ("next token", "language model", "text completion")):
        return "generation"
    for task_type, hints in _TASK_TYPE_PATTERNS:
        if any(hint in lower_text for hint in hints):
            return task_type
    return "research"


def _extract_target(text: str, task_type: str) -> str | None:
    patterns = [_TARGET_VARIABLE_PATTERN, _LABEL_COLUMN_PATTERN, _PREDICTION_TARGET_PATTERN]
    if task_type == "translation":
        match = re.search(_TRANSLATION_TARGET_PATTERN, text, flags=re.IGNORECASE)
        if match:
            return {
                "source_language": match.group(1),
                "target_language": match.group(2),
            }
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip(".,;:()[]{}'\"")
        if candidate and candidate.lower() not in _EXCLUDED_TARGET_KEYWORDS:
            return candidate
    return None


def _infer_deliverables(text: str) -> list[str]:
    deliverables: list[str] = []
    keyword_map = (
        ("run manifest", "run manifests"),
        ("manifest", "run manifests"),
        ("metric", "metrics summary"),
        ("final report", "final report"),
        ("findings", "findings summary"),
        ("artifact package", "artifact package"),
    )
    lower_text = text.lower()
    for needle, label in keyword_map:
        if needle in lower_text and label not in deliverables:
            deliverables.append(label)
    return deliverables


def compile_mission_contract(
    *,
    objective: str,
    summary: str,
    project_metadata: dict[str, Any],
    human_inputs: dict[str, Any],
    artifacts: dict[str, list[str]],
    autopilot: dict[str, Any],
) -> dict[str, Any]:
    kickoff_text = _clean_text(
        project_metadata.get("kickoff"),
        fallback=_read_kickoff_text([str(path) for path in artifacts.get("docs", [])]),
    )
    text_fragments = [
        kickoff_text,
        objective,
        summary,
        *_clean_string_list(project_metadata.get("constraints")),
        *_flatten_text_fragments(human_inputs),
    ]
    combined_text = _collapse_whitespace(" ".join(fragment for fragment in text_fragments if fragment))
    task_type = _infer_task_type(combined_text)
    task_requires_target = task_type in {"classification", "regression", "retrieval"}
    dataset_value = _first_mapping_value(
        human_inputs,
        ("dataset_path", "dataset_paths", "data_path", "data_paths", "dataset_access", "datasets", "data"),
    )
    if dataset_value is None:
        dataset_value = _first_mapping_value(
            project_metadata,
            ("dataset_path", "dataset_paths", "data_path", "data_paths", "dataset_access", "datasets", "data"),
        )
    dataset_value = _coerce_summary_value(dataset_value) or _extract_path_hints(combined_text) or None
    target_value = _coerce_summary_value(
        _first_mapping_value(
            human_inputs,
            ("target", "target_variable", "label", "label_column", "prediction_target"),
        )
        or _first_mapping_value(
            project_metadata,
            ("target", "target_variable", "label", "label_column", "prediction_target"),
        )
    )
    if target_value is None:
        target_value = _extract_target(combined_text, task_type)
    split_policy = _coerce_summary_value(
        _first_mapping_value(
            human_inputs,
            ("split_policy", "evaluation_split", "holdout_policy", "train_validation_test_split"),
        )
        or _first_mapping_value(
            project_metadata,
            ("split_policy", "evaluation_split", "holdout_policy", "train_validation_test_split"),
        )
    )
    if split_policy is None and re.search(r"\b(train|validation|test|holdout)\b", combined_text, flags=re.IGNORECASE):
        split_policy = (
            "Detected a train/validation/test or holdout boundary in the kickoff, "
            "but the exact split policy still needs operator confirmation."
        )
    benchmark_expectations = _coerce_summary_value(
        _first_mapping_value(
            human_inputs,
            ("benchmark_expectations", "benchmark", "comparison", "comparisons", "baselines"),
        )
        or _first_mapping_value(
            project_metadata,
            ("benchmark_expectations", "benchmark", "comparison", "comparisons", "baselines"),
        )
    )
    if benchmark_expectations is None and re.search(r"\b(compare|baseline|benchmark|vs\.)\b", combined_text, flags=re.IGNORECASE):
        benchmark_expectations = "Kickoff asks for a baseline or benchmark comparison."
    success_criteria = _coerce_summary_value(
        _first_mapping_value(
            human_inputs,
            ("success_criteria", "success", "acceptance_criteria", "metrics", "metric"),
        )
        or _first_mapping_value(
            project_metadata,
            ("success_criteria", "success", "acceptance_criteria", "metrics", "metric"),
        )
    )
    if success_criteria is None and re.search(r"\b(improve|gain|beat|higher|lower|reduce)\b", combined_text, flags=re.IGNORECASE):
        success_criteria = "Kickoff asks for measurable improvement over the current starting point."
    deliverables = _coerce_summary_value(
        _first_mapping_value(
            human_inputs,
            ("deliverables", "artifacts", "artifact_requirements", "artifact_expectations"),
        )
        or _first_mapping_value(
            project_metadata,
            ("deliverables", "artifacts", "artifact_requirements", "artifact_expectations"),
        )
    )
    inferred_deliverables = _infer_deliverables(combined_text)
    if deliverables is None:
        deliverables = inferred_deliverables or list(DEFAULT_DELIVERABLES)
    elif isinstance(deliverables, list):
        deliverables = deliverables + [item for item in inferred_deliverables if item not in deliverables]
    novelty_target = _coerce_summary_value(
        _first_mapping_value(human_inputs, ("novelty_target", "research_ambition", "ambition"))
        or _first_mapping_value(project_metadata, ("novelty_target", "research_ambition", "ambition"))
    )
    compute_budget = _coerce_summary_value(
        _first_mapping_value(
            human_inputs,
            ("compute_budget", "budget", "budgets", "max_gpu_hours", "max_cpu_hours"),
        )
        or _first_mapping_value(
            project_metadata,
            ("compute_budget", "budget", "budgets", "max_gpu_hours", "max_cpu_hours"),
        )
    )
    if compute_budget is None:
        budget_match = re.search(_COMPUTE_BUDGET_PATTERN, combined_text, flags=re.IGNORECASE)
        if budget_match:
            compute_budget = f"{budget_match.group(1)} {budget_match.group(2).upper()} hours"
    if compute_budget is None and autopilot.get("max_iterations") is not None:
        compute_budget = {
            "default_policy": DEFAULT_COMPUTE_BUDGET,
            "max_iterations": int(autopilot["max_iterations"]),
        }
    stop_rules = _coerce_summary_value(
        _first_mapping_value(human_inputs, ("stop_rules", "stop_rule", "termination"))
        or _first_mapping_value(project_metadata, ("stop_rules", "stop_rule", "termination"))
    )
    if stop_rules is None and re.search(r"\b(stop|abort|max iterations|halt)\b", combined_text, flags=re.IGNORECASE):
        stop_rules = "Kickoff includes an explicit stopping instruction."
    leakage_policy = _coerce_summary_value(
        _first_mapping_value(human_inputs, ("leakage_constraints", "leakage_policy", "data_leakage"))
        or _first_mapping_value(project_metadata, ("leakage_constraints", "leakage_policy", "data_leakage"))
    )
    if leakage_policy is None and "leak" in combined_text.lower():
        leakage_policy = "Kickoff explicitly mentions leakage constraints."
    publication_boundary = _coerce_summary_value(
        _first_mapping_value(human_inputs, ("publication_boundary", "external_publication", "sharing_boundary"))
        or _first_mapping_value(project_metadata, ("publication_boundary", "external_publication", "sharing_boundary"))
    )
    if publication_boundary is None and re.search(r"\b(internal only|publish|publication|external)\b", combined_text, flags=re.IGNORECASE):
        publication_boundary = "Kickoff mentions publication or external sharing expectations."

    prerequisites: list[dict[str, Any]] = []

    def _add_prerequisite(
        *,
        prerequisite_id: str,
        section: str,
        status: str,
        question: str,
        reason: str,
        assumed_default: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "id": prerequisite_id,
            "section": section,
            "status": status,
            "question": question,
            "reason": reason,
        }
        if assumed_default:
            entry["assumed_default"] = assumed_default
        prerequisites.append(entry)

    if dataset_value is None:
        _add_prerequisite(
            prerequisite_id="dataset-access",
            section="data",
            status="blocking",
            question="Where is the dataset located, or how should DeepLoop obtain access to it?",
            reason="Execution cannot begin safely without knowing the dataset path or access contract.",
        )
    if target_value is None and task_requires_target:
        _add_prerequisite(
            prerequisite_id="target-definition",
            section="data",
            status="blocking",
            question="What target variable should DeepLoop optimize or predict?",
            reason="Supervised tasks need an explicit target definition to avoid silently optimizing the wrong outcome.",
        )
    if split_policy is None:
        split_policy = DEFAULT_SPLIT_POLICY
        _add_prerequisite(
            prerequisite_id="split-policy",
            section="evaluation",
            status="defaulted",
            question="Should DeepLoop keep the default holdout split policy, or do you want a project-specific split contract?",
            reason="Split policy controls how evaluation evidence stays trustworthy.",
            assumed_default=DEFAULT_SPLIT_POLICY,
        )
    if benchmark_expectations is None:
        benchmark_expectations = DEFAULT_BENCHMARK_POLICY
        _add_prerequisite(
            prerequisite_id="benchmark-expectations",
            section="evaluation",
            status="defaulted",
            question="What benchmark or baseline should count as the comparison target?",
            reason="Benchmark expectations determine whether the mission can claim improvement.",
            assumed_default=DEFAULT_BENCHMARK_POLICY,
        )
    if success_criteria is None:
        success_criteria = "Show a measurable improvement over the agreed baseline or produce a falsifying analysis."
    if deliverables == list(DEFAULT_DELIVERABLES):
        _add_prerequisite(
            prerequisite_id="artifact-expectations",
            section="artifacts",
            status="defaulted",
            question="Are the default deliverables enough, or do you need extra artifacts packaged at the end of the mission?",
            reason="Artifact expectations define what the operator should receive at mission completion.",
            assumed_default=", ".join(DEFAULT_DELIVERABLES),
        )
    if novelty_target is None:
        novelty_target = DEFAULT_NOVELTY_TARGET
        _add_prerequisite(
            prerequisite_id="novelty-target",
            section="evaluation",
            status="needs-clarification",
            question="Is this mission aiming for baseline improvement only, or should DeepLoop pursue a stronger novelty target?",
            reason="Research ambition changes how aggressively DeepLoop should search for new methods versus robust baselines.",
            assumed_default=DEFAULT_NOVELTY_TARGET,
        )
    if compute_budget is None:
        compute_budget = DEFAULT_COMPUTE_BUDGET
        _add_prerequisite(
            prerequisite_id="compute-budget",
            section="budget",
            status="defaulted",
            question="What compute budget, if any, should override the conservative bootstrap budget?",
            reason="Budget clarity prevents DeepLoop from spending more compute than the operator intended.",
            assumed_default=DEFAULT_COMPUTE_BUDGET,
        )
    if stop_rules is None:
        stop_rules = DEFAULT_STOP_RULES
        _add_prerequisite(
            prerequisite_id="stop-rules",
            section="budget",
            status="defaulted",
            question="Do you want a mission-specific stop rule, or should DeepLoop keep the conservative default?",
            reason="Stop rules determine when the mission should stop iterating instead of over-searching.",
            assumed_default=DEFAULT_STOP_RULES,
        )
    if leakage_policy is None:
        leakage_policy = DEFAULT_LEAKAGE_GUARDRAIL
        _add_prerequisite(
            prerequisite_id="leakage-policy",
            section="boundaries",
            status="needs-clarification",
            question="What leakage boundary should DeepLoop enforce for train, validation, and test data?",
            reason="Leakage ambiguity can invalidate the mission's evaluation evidence.",
            assumed_default=DEFAULT_LEAKAGE_GUARDRAIL,
        )
    if publication_boundary is None:
        publication_boundary = DEFAULT_PUBLICATION_BOUNDARY
        _add_prerequisite(
            prerequisite_id="publication-boundary",
            section="boundaries",
            status="defaulted",
            question="Should DeepLoop treat results as internal-only, or is any external publication allowed?",
            reason="Publication boundaries determine whether public-facing artifacts are even allowed.",
            assumed_default=DEFAULT_PUBLICATION_BOUNDARY,
        )

    blocking_count = sum(1 for item in prerequisites if item["status"] == "blocking")
    clarification_count = sum(1 for item in prerequisites if item["status"] == "needs-clarification")
    defaulted = [item for item in prerequisites if item["status"] == "defaulted"]
    if blocking_count:
        readiness_status = "blocked"
        launch_recommendation = "stop-for-operator-input"
    elif clarification_count:
        readiness_status = "ready-with-clarifications"
        launch_recommendation = "launch-with-disclosed-guardrails"
    elif defaulted:
        readiness_status = "ready-with-defaults"
        launch_recommendation = "launch-with-disclosed-defaults"
    else:
        readiness_status = "ready"
        launch_recommendation = "launch"

    follow_up_questions = [
        item["question"]
        for item in prerequisites
        if item["status"] in {"blocking", "needs-clarification"}
    ][:4]
    defaults_applied = [
        {
            "section": item["section"],
            "reason": item["reason"],
            "assumed_default": item.get("assumed_default"),
        }
        for item in prerequisites
        if item["status"] == "defaulted"
    ]
    return {
        "objective": {
            "text": objective,
            "summary": summary,
            "task_type": task_type,
            **({"source_kickoff": _truncate_text(kickoff_text)} if kickoff_text else {}),
        },
        "data": {
            "dataset": dataset_value,
            "target": target_value,
            "split_policy": split_policy,
        },
        "evaluation": {
            "benchmark_expectations": benchmark_expectations,
            "success_criteria": success_criteria,
            "novelty_target": novelty_target,
        },
        "artifacts": {
            "deliverables": deliverables,
            "docs": [str(path) for path in artifacts.get("docs", [])],
            "configs": [str(path) for path in artifacts.get("configs", [])],
        },
        "budget": {
            "compute_budget": compute_budget,
            "stop_rules": stop_rules,
        },
        "boundaries": {
            "leakage_policy": leakage_policy,
            "publication_boundary": publication_boundary,
        },
        "prerequisites": prerequisites,
        "defaults_applied": defaults_applied,
        "follow_up_questions": follow_up_questions,
        "readiness": {
            "status": readiness_status,
            "launch_recommendation": launch_recommendation,
            "blocking_count": blocking_count,
            "clarification_count": clarification_count,
            "defaulted_count": len(defaulted),
        },
    }


def build_mission_config_from_project_root(project_root: Path, *, mission_id: str | None = None) -> dict[str, Any]:
    repo_root = project_root.expanduser().resolve()
    contract = discover_project_contract(repo_root)
    project_metadata = contract.get("project_metadata") if isinstance(contract.get("project_metadata"), dict) else {}
    project_name = _clean_text(project_metadata.get("name"), fallback=repo_root.name)
    mission_slug = _slugify(project_name)
    resolved_mission_id = _clean_text(
        mission_id or project_metadata.get("mission_id"),
        fallback=f"{mission_slug}-mission",
    )
    artifacts = contract.get("artifacts") if isinstance(contract.get("artifacts"), dict) else {}
    kickoff_text = _clean_text(
        project_metadata.get("kickoff"),
        fallback=_read_kickoff_text([str(path) for path in artifacts.get("docs", [])]),
    )
    title = _clean_text(project_metadata.get("title"), fallback=f"{project_name} mission")
    summary = _clean_text(
        project_metadata.get("summary"),
        fallback=_summarize_text(
            kickoff_text,
            fallback=(
                f"Bootstrap DeepLoop from the minimal facts in `{repo_root.name}` and keep "
                "all implementation/build surfaces DeepLoop-owned."
            ),
        ),
    )
    objective = _clean_text(
        project_metadata.get("objective"),
        fallback=_first_sentence(
            kickoff_text,
            fallback=(
                f"Use DeepLoop to make measurable progress on `{project_name}` starting only "
                "from the project folder's minimal facts and contracts."
            ),
        ),
    )
    constraints = _clean_string_list(project_metadata.get("constraints"))
    if DEFAULT_BOOTSTRAP_CONSTRAINT not in constraints:
        constraints.append(DEFAULT_BOOTSTRAP_CONSTRAINT)
    roles = _clean_string_list(project_metadata.get("roles")) or DEFAULT_BOOTSTRAP_ROLES
    phases = _clean_string_list(project_metadata.get("phases")) or DEFAULT_BOOTSTRAP_PHASES
    human_inputs = project_metadata.get("human_inputs") if isinstance(project_metadata.get("human_inputs"), dict) else {}
    autopilot = project_metadata.get("autopilot") if isinstance(project_metadata.get("autopilot"), dict) else {}
    merged_autopilot = dict(DEFAULT_BOOTSTRAP_AUTOPILOT)
    merged_autopilot.update({key: value for key, value in autopilot.items() if key not in {"recursive_agent", "phase_execution_hints"}})
    recursive_agent_cfg = (
        autopilot.get("recursive_agent")
        if isinstance(autopilot.get("recursive_agent"), dict)
        else {}
    )
    merged_autopilot["recursive_agent"] = _merge_mapping(
        {
            "loop_name": f"{mission_slug}-phase-loop",
            **DEFAULT_RECURSIVE_AGENT_AUTOPILOT,
        },
        recursive_agent_cfg,
    )
    raw_phase_hints = autopilot.get("phase_execution_hints") if isinstance(autopilot.get("phase_execution_hints"), dict) else {}
    phase_hints = {
        phase: dict(hint)
        for phase, hint in DEFAULT_PHASE_EXECUTION_HINTS.items()
    }
    for phase, raw_hint in raw_phase_hints.items():
        if not isinstance(raw_hint, dict):
            continue
        phase_hints[str(phase)] = _merge_mapping(dict(phase_hints.get(str(phase), {})), raw_hint)
    merged_autopilot["phase_execution_hints"] = phase_hints
    mission_contract = compile_mission_contract(
        objective=objective,
        summary=summary,
        project_metadata=project_metadata,
        human_inputs=human_inputs,
        artifacts={
            "docs": [str(path) for path in artifacts.get("docs", [])],
            "configs": [str(path) for path in artifacts.get("configs", [])],
        },
        autopilot=merged_autopilot,
    )
    contract_requirements = _promoted_contract_requirements_for_config(contract, project_metadata)
    mission_payload: dict[str, Any] = {
        "id": resolved_mission_id,
        "mode": _clean_text(project_metadata.get("mode"), fallback=DEFAULT_OPERATING_MODE),
        "title": title,
        "summary": summary,
        "objective": objective,
        "target_repo": str(repo_root),
        "target_project": project_name,
        "constraints": constraints,
        "human_inputs": human_inputs,
    }
    mission_payload.update(contract_requirements)
    contract_coverage = contract.get("contract_coverage")
    if isinstance(contract_coverage, list):
        mission_payload["contract_coverage"] = contract_coverage
    return {
        "mission": mission_payload,
        "roles": roles,
        "phases": phases,
        "artifacts": {
            "docs": [str(path) for path in artifacts.get("docs", [])],
            "configs": [str(path) for path in artifacts.get("configs", [])],
            "data": [dict(item) for item in artifacts.get("data", []) if isinstance(item, dict)],
        },
        "autopilot": merged_autopilot,
        "mission_contract": mission_contract,
    }
