from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from deeploop.core.structured_io import write_markdown
from deeploop.mission.project_bootstrap import render_mission_contract_summary_lines


def _string_value(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_strings(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        value = raw.strip()
        return [value] if value else []
    if isinstance(raw, list | tuple):
        values: list[str] = []
        for item in raw:
            values.extend(_normalize_strings(item))
        return values
    value = str(raw).strip()
    return [value] if value else []


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def render_mission_summary_lines(mission_state: Mapping[str, Any]) -> list[str]:
    mission_id = _string_value(mission_state.get("mission_id")) or "unknown"
    mission_mode = _string_value(mission_state.get("mode")) or _string_value(_mapping(mission_state.get("outer_loop")).get("mode"))
    mission_profile = _string_value(mission_state.get("mission_profile"))
    target_repo = _string_value(mission_state.get("target_repo"))
    objective = _string_value(mission_state.get("objective"))
    mission_constraints = _normalize_strings(mission_state.get("constraints"))
    current_phase = _string_value(mission_state.get("current_phase")) or "unknown"
    status = _string_value(mission_state.get("status")) or "unknown"
    contract_snapshot = _mapping(mission_state.get("contract_snapshot"))
    contract_snapshot_path = _string_value(contract_snapshot.get("path") or contract_snapshot.get("snapshot_path"))
    platform_expansion = _mapping(mission_state.get("platform_expansion"))
    platform_root = _string_value(platform_expansion.get("platform_root"))
    surfaces = platform_expansion.get("surfaces") if isinstance(platform_expansion.get("surfaces"), Mapping) else {}
    project_contract = _mapping(mission_state.get("project_contract"))
    project_contract_status = _string_value(project_contract.get("status"))
    project_contract_root = _string_value(project_contract.get("contract_root") or project_contract.get("repo_root"))
    mission_contract_path = _string_value(mission_state.get("mission_contract_path"))
    lines = [
        "# Mission summary",
        "",
        f"- mission_id: `{mission_id}`",
        f"- mode: `{mission_mode or 'unknown'}`",
        *([f"- mission_profile: `{mission_profile}`"] if mission_profile else []),
        *([f"- target_repo: `{target_repo}`"] if target_repo else []),
        *([f"- objective: {objective}"] if objective else []),
        *([f"- constraints: {'; '.join(mission_constraints)}"] if mission_constraints else []),
        f"- current_phase: `{current_phase}`",
        f"- status: `{status}`",
        *([f"- contract_snapshot_path: `{contract_snapshot_path}`"] if contract_snapshot_path else []),
        *([f"- platform_root: `{platform_root}`"] if platform_root else []),
        *(
            [
                "- platform_surfaces: "
                + ", ".join(
                    f"`{surface_id}` ({_string_value(_mapping(surface).get('status')) or 'planned'})"
                    for surface_id, surface in sorted(surfaces.items())
                )
            ]
            if surfaces
            else []
        ),
        *([f"- project_contract_status: `{project_contract_status}`"] if project_contract_status else []),
        *([f"- project_contract_root: `{project_contract_root}`"] if project_contract_root else []),
        *([f"- mission_contract_path: `{mission_contract_path}`"] if mission_contract_path else []),
    ]
    mission_contract = mission_state.get("mission_contract")
    if isinstance(mission_contract, dict):
        lines.extend(["", *render_mission_contract_summary_lines(mission_contract)])
    return lines


def sync_mission_summary(
    mission_root: Path,
    mission_state: Mapping[str, Any],
    *,
    write_if_missing: bool = False,
) -> Path | None:
    summary_path = mission_root / "mission_summary.md"
    if not write_if_missing and not summary_path.exists():
        return None
    write_markdown(summary_path, render_mission_summary_lines(mission_state))
    return summary_path


def sync_mission_summary_for_state_path(
    mission_state_path: Path,
    mission_state: Mapping[str, Any],
    *,
    write_if_missing: bool = False,
) -> Path | None:
    return sync_mission_summary(mission_state_path.parent, mission_state, write_if_missing=write_if_missing)


__all__ = [
    "render_mission_summary_lines",
    "sync_mission_summary",
    "sync_mission_summary_for_state_path",
]
