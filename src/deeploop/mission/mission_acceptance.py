from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from deeploop.core.shared import normalize_strings as _normalize_strings
from deeploop.core.structured_io import load_jsonl_objects

_EVALUATED_STATUSES = {"completed", "evaluated", "recorded", "succeeded", "success", "passed"}
_SKIPPED_STATUSES = {"skipped", "blocked", "failed"}



def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _int_criterion(criteria: Mapping[str, Any], key: str) -> int | None:
    value = criteria.get(key)
    if value is None:
        return None
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return None
    return resolved if resolved > 0 else None


def _mission_root(mission_state: Mapping[str, Any], mission_state_path: Path | None) -> Path | None:
    if mission_state_path is not None:
        return mission_state_path.expanduser().resolve().parent
    outer_loop = mission_state.get("outer_loop")
    if isinstance(outer_loop, Mapping):
        ledger_path = outer_loop.get("experiment_ledger_path")
        if isinstance(ledger_path, str) and ledger_path.strip():
            return Path(ledger_path).expanduser().resolve().parent
    return None


def _experiment_ledger_path(mission_state: Mapping[str, Any], mission_root: Path | None) -> Path | None:
    outer_loop = mission_state.get("outer_loop")
    if isinstance(outer_loop, Mapping):
        ledger_path = outer_loop.get("experiment_ledger_path")
        if isinstance(ledger_path, str) and ledger_path.strip():
            return Path(ledger_path).expanduser().resolve()
    if mission_root is not None:
        return mission_root / "mission_experiments.jsonl"
    return None


def _load_experiment_entries(mission_state: Mapping[str, Any], mission_root: Path | None) -> list[dict[str, Any]]:
    entries = mission_state.get("experiment_entries")
    if isinstance(entries, list):
        return [dict(item) for item in entries if isinstance(item, Mapping)]
    ledger_path = _experiment_ledger_path(mission_state, mission_root)
    if ledger_path is None or not ledger_path.exists():
        return []
    return load_jsonl_objects(ledger_path, missing_ok=True)


def _entry_status(entry: Mapping[str, Any]) -> str:
    return str(entry.get("status") or "").strip().lower()


def _metadata(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = entry.get("metadata")
    return metadata if isinstance(metadata, Mapping) else {}


def _entry_key(entry: Mapping[str, Any], *, fallback: str) -> str:
    metadata = _metadata(entry)
    for key in ("method_family", "method_id", "method", "hypothesis_id", "candidate_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    entry_id = str(entry.get("entry_id") or "").strip()
    return entry_id or fallback


def _evidence_items(evidence: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    raw = evidence.get(key)
    if not isinstance(raw, list):
        return []
    items: list[Mapping[str, Any]] = []
    for index, item in enumerate(raw):
        if isinstance(item, Mapping):
            items.append(item)
        elif str(item).strip():
            items.append({"id": str(item).strip(), "index": index})
    return items


def _state_item_key(item: Mapping[str, Any], *, fallback: str) -> str:
    for key in ("family", "method_family", "method_id", "method", "id", "hypothesis_id", "candidate_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _experiment_coverage(mission_state: Mapping[str, Any]) -> Mapping[str, Any]:
    coverage = mission_state.get("experiment_coverage")
    return coverage if isinstance(coverage, Mapping) else {}


def _coverage_methods(mission_state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    methods = _experiment_coverage(mission_state).get("methods")
    if not isinstance(methods, list):
        return []
    return [item for item in methods if isinstance(item, Mapping)]


def _coverage_method_status(method: Mapping[str, Any]) -> str:
    return str(method.get("status") or "").strip().lower()


def _coverage_method_key(method: Mapping[str, Any], *, fallback: str) -> str:
    for key in ("method_id", "method", "name", "id"):
        value = method.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    category = str(method.get("category") or "").strip()
    return f"{category}:{fallback}" if category else fallback


def _coverage_tags(method: Mapping[str, Any]) -> list[str]:
    tags = method.get("tags")
    return [str(item).strip() for item in tags if str(item).strip()] if isinstance(tags, list) else []


def _coverage_haystack(method: Mapping[str, Any]) -> str:
    return " ".join(
        [
            str(method.get("category") or ""),
            str(method.get("name") or ""),
            str(method.get("method") or ""),
            *[tag for tag in _coverage_tags(method)],
        ]
    ).lower()


def _coverage_method_is_novel(method: Mapping[str, Any]) -> bool:
    haystack = _coverage_haystack(method)
    return _bool(method.get("novel")) or _bool(method.get("is_novel")) or "novel" in haystack


def _coverage_method_is_llm_text(method: Mapping[str, Any]) -> bool:
    method_kind = str(method.get("method_kind") or method.get("method_type") or "").lower()
    category = str(method.get("category") or "").lower()
    haystack = _coverage_haystack(method)
    return (
        _bool(method.get("llm_text_method"))
        or method_kind in {"llm-text", "llm_text", "llm"}
        or "llm" in haystack
        or "text" in category
    )


def _coverage_artifact_candidates(mission_state: Mapping[str, Any], *tokens: str) -> list[str]:
    normalized_tokens = tuple(token.lower() for token in tokens if token)
    paths: list[str] = []
    coverage = _experiment_coverage(mission_state)
    for key in ("categories", "methods"):
        items = coverage.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            for raw_path in (
                *_normalize_strings(item.get("artifact_path")),
                *_normalize_strings(item.get("artifact")),
            ):
                if not normalized_tokens or any(token in raw_path.lower() for token in normalized_tokens):
                    paths.append(raw_path)
    return list(dict.fromkeys(paths))


def _count_methods_evaluated(
    mission_state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    experiment_entries: list[dict[str, Any]],
) -> int:
    observed: set[str] = set()
    for index, item in enumerate(_evidence_items(evidence, "methods_evaluated"), start=1):
        observed.add(_state_item_key(item, fallback=f"state-method-{index}"))
    for index, method in enumerate(_coverage_methods(mission_state), start=1):
        if _coverage_method_status(method) not in _EVALUATED_STATUSES:
            continue
        observed.add(_coverage_method_key(method, fallback=f"coverage-method-{index}"))
    for index, entry in enumerate(experiment_entries, start=1):
        if _entry_status(entry) not in _EVALUATED_STATUSES:
            continue
        metadata = _metadata(entry)
        if not any(metadata.get(key) for key in ("method_family", "method_id", "method", "hypothesis_id")):
            continue
        observed.add(_entry_key(entry, fallback=f"ledger-method-{index}"))
    return len(observed)


def _count_novel_methods_proposed(
    mission_state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    experiment_entries: list[dict[str, Any]],
) -> int:
    observed: set[str] = set()
    for index, item in enumerate(_evidence_items(evidence, "novel_methods_proposed"), start=1):
        observed.add(_state_item_key(item, fallback=f"state-novel-{index}"))
    for index, method in enumerate(_coverage_methods(mission_state), start=1):
        if _coverage_method_is_novel(method):
            observed.add(_coverage_method_key(method, fallback=f"coverage-novel-{index}"))
    for index, entry in enumerate(experiment_entries, start=1):
        metadata = _metadata(entry)
        haystack = " ".join(
            [
                str(entry.get("kind") or ""),
                str(entry.get("summary") or ""),
                *[str(item) for item in metadata.get("tags", []) if isinstance(metadata.get("tags"), list)],
            ]
        ).lower()
        if _bool(metadata.get("novel")) or _bool(metadata.get("is_novel")) or "novel" in haystack:
            observed.add(_entry_key(entry, fallback=f"ledger-novel-{index}"))
    return len(observed)


def _count_llm_text_methods_evaluated(
    mission_state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    experiment_entries: list[dict[str, Any]],
) -> int:
    observed: set[str] = set()
    for index, item in enumerate(_evidence_items(evidence, "llm_text_methods_evaluated"), start=1):
        observed.add(_state_item_key(item, fallback=f"state-llm-text-{index}"))
    for index, method in enumerate(_coverage_methods(mission_state), start=1):
        if _coverage_method_status(method) in _EVALUATED_STATUSES and _coverage_method_is_llm_text(method):
            observed.add(_coverage_method_key(method, fallback=f"coverage-llm-text-{index}"))
    for index, entry in enumerate(experiment_entries, start=1):
        if _entry_status(entry) not in _EVALUATED_STATUSES:
            continue
        metadata = _metadata(entry)
        method_kind = str(metadata.get("method_kind") or metadata.get("method_type") or "").lower()
        family = str(metadata.get("method_family") or metadata.get("method") or "").lower()
        if _bool(metadata.get("llm_text_method")) or method_kind in {"llm-text", "llm_text", "llm"} or "llm" in family:
            observed.add(_entry_key(entry, fallback=f"ledger-llm-text-{index}"))
    return len(observed)


def _skipped_methods(
    mission_state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    experiment_entries: list[dict[str, Any]],
) -> list[str]:
    skipped = [
        _state_item_key(item, fallback=f"state-skipped-{index}")
        for index, item in enumerate(_evidence_items(evidence, "skipped_methods"), start=1)
    ]
    for index, method in enumerate(_coverage_methods(mission_state), start=1):
        if _coverage_method_status(method) in _SKIPPED_STATUSES:
            skipped.append(_coverage_method_key(method, fallback=f"coverage-skipped-{index}"))
    for index, entry in enumerate(experiment_entries, start=1):
        if _entry_status(entry) in _SKIPPED_STATUSES:
            skipped.append(_entry_key(entry, fallback=f"ledger-skipped-{index}"))
    return sorted(set(skipped))


def _artifact_candidates(
    mission_state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
    coverage_tokens: tuple[str, ...] = (),
) -> list[str]:
    artifacts = evidence.get("artifacts")
    sources: list[Any] = []
    if isinstance(artifacts, Mapping):
        sources.append(artifacts)
    sources.append(evidence)
    paths: list[str] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in keys:
            paths.extend(_normalize_strings(source.get(key)))
    paths.extend(_coverage_artifact_candidates(mission_state, *coverage_tokens))
    return list(dict.fromkeys(paths))


def _resolve_artifact_path(raw_path: str, mission_root: Path | None) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute() or mission_root is None:
        return path
    return mission_root / path


def _artifact_status(paths: list[str], mission_root: Path | None) -> tuple[str, str]:
    if not paths:
        return ("missing", "")
    existing = [path for path in paths if _resolve_artifact_path(path, mission_root).exists()]
    if existing:
        return ("met", ", ".join(existing))
    return ("missing", ", ".join(paths))


def _row(
    criterion: str,
    *,
    requested: Any,
    achieved: Any,
    status: str,
    artifact_path: str = "",
) -> dict[str, Any]:
    return {
        "criterion": criterion,
        "requested": requested,
        "achieved": achieved,
        "artifact_path": artifact_path,
        "status": status,
    }


def evaluate_mission_acceptance(
    mission_state: Mapping[str, Any],
    *,
    mission_state_path: Path | None = None,
) -> dict[str, Any]:
    criteria = mission_state.get("acceptance_criteria")
    if not isinstance(criteria, Mapping) or not criteria:
        return {
            "schema_version": 1,
            "status": "not-requested",
            "allow_final_report_only_if_criteria_met": False,
            "rows": [],
            "blockers": [],
            "counts": {},
        }
    mission_root = _mission_root(mission_state, mission_state_path)
    evidence = mission_state.get("acceptance_evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    experiment_entries = _load_experiment_entries(mission_state, mission_root)
    counts = {
        "methods_evaluated": _count_methods_evaluated(mission_state, evidence, experiment_entries),
        "novel_methods_proposed": _count_novel_methods_proposed(mission_state, evidence, experiment_entries),
        "llm_text_methods_evaluated": _count_llm_text_methods_evaluated(mission_state, evidence, experiment_entries),
        "skipped_methods": len(_skipped_methods(mission_state, evidence, experiment_entries)),
    }
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    for criterion, count_key in (
        ("min_methods_evaluated", "methods_evaluated"),
        ("min_novel_methods_proposed", "novel_methods_proposed"),
        ("min_llm_text_methods_evaluated", "llm_text_methods_evaluated"),
    ):
        requested = _int_criterion(criteria, criterion)
        if requested is None:
            continue
        achieved = counts[count_key]
        status = "met" if achieved >= requested else "unmet"
        rows.append(_row(criterion, requested=requested, achieved=achieved, status=status))
        if status != "met":
            blockers.append(f"acceptance criterion `{criterion}` unmet: requested {requested}, achieved {achieved}")

    artifact_criteria = (
        ("require_leaderboard", ("leaderboard", "leaderboard_path"), ("leaderboard",)),
        ("require_prediction_files", ("prediction_files", "prediction_file", "predictions_path"), ("prediction",)),
        ("require_horizon_metrics", ("horizon_metrics", "horizon_metrics_path"), ("horizon", "metric")),
    )
    for criterion, keys, coverage_tokens in artifact_criteria:
        if not _bool(criteria.get(criterion)):
            continue
        artifact_status, artifact_path = _artifact_status(
            _artifact_candidates(mission_state, evidence, keys=keys, coverage_tokens=coverage_tokens),
            mission_root,
        )
        status = "met" if artifact_status == "met" else "unmet"
        rows.append(_row(criterion, requested=True, achieved=artifact_status, status=status, artifact_path=artifact_path))
        if status != "met":
            blockers.append(f"acceptance criterion `{criterion}` unmet: required artifact evidence is missing")

    if _bool(criteria.get("require_failure_log_for_skipped_methods")):
        skipped = _skipped_methods(mission_state, evidence, experiment_entries)
        if skipped:
            artifact_status, artifact_path = _artifact_status(
                _artifact_candidates(
                    mission_state,
                    evidence,
                    keys=("failure_log", "failure_log_path", "skipped_methods_failure_log"),
                    coverage_tokens=("failure", "skip"),
                ),
                mission_root,
            )
            status = "met" if artifact_status == "met" else "unmet"
            achieved: Any = artifact_status
        else:
            artifact_path = ""
            status = "met"
            achieved = "no skipped methods"
        rows.append(
            _row(
                "require_failure_log_for_skipped_methods",
                requested=True,
                achieved=achieved,
                status=status,
                artifact_path=artifact_path,
            )
        )
        if status != "met":
            blockers.append(
                "acceptance criterion `require_failure_log_for_skipped_methods` unmet: skipped methods lack a failure log"
            )

    overall_status = "met" if not blockers else "unmet"
    return {
        "schema_version": 1,
        "status": overall_status,
        "allow_final_report_only_if_criteria_met": _bool(criteria.get("allow_final_report_only_if_criteria_met")),
        "rows": rows,
        "blockers": blockers,
        "counts": counts,
    }


def acceptance_criteria_blockers(
    mission_state: Mapping[str, Any],
    *,
    mission_state_path: Path | None = None,
) -> tuple[str, ...]:
    evaluation = evaluate_mission_acceptance(mission_state, mission_state_path=mission_state_path)
    if not evaluation.get("allow_final_report_only_if_criteria_met"):
        return ()
    return tuple(str(item) for item in evaluation.get("blockers", []) if str(item).strip())


__all__ = ["acceptance_criteria_blockers", "evaluate_mission_acceptance"]
