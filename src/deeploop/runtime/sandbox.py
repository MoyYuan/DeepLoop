from __future__ import annotations

import shutil
from pathlib import Path

from deeploop.core.paths import COPILOT_RULES_PATH, REPO_ROOT, SANDBOXES_DIR, WORKSPACE_RULES_PATH


ROLE_ENV_MAP = {
    "planner": "deeploop",
    "literature-scout": "deeploop",
    "dataset-strategist": "deeploop",
    "experiment-designer": "deeploop",
    "execution-operator": "llm",
    "critic-verifier": "deeploop",
    "report-synthesizer": "deeploop",
}


def rule_sources_for_repo(target_repo: Path) -> list[str]:
    sources = [
        str(COPILOT_RULES_PATH),
        str(WORKSPACE_RULES_PATH),
        str(REPO_ROOT / "AGENTS.md"),
    ]
    repo_agents = target_repo / "AGENTS.md"
    repo_copilot = target_repo / ".github" / "copilot-instructions.md"
    if repo_agents.exists():
        sources.append(str(repo_agents))
    if repo_copilot.exists():
        sources.append(str(repo_copilot))
    return sources


def build_sandbox_spec(mission_id: str, role: str, target_repo: Path, *, reset: bool = False) -> dict:
    sandbox_root = SANDBOXES_DIR / mission_id / role
    inputs_dir = sandbox_root / "inputs"
    outputs_dir = sandbox_root / "outputs"
    if reset:
        shutil.rmtree(inputs_dir, ignore_errors=True)
        shutil.rmtree(outputs_dir, ignore_errors=True)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return {
        "role": role,
        "env_name": ROLE_ENV_MAP.get(role, "deeploop"),
        "sandbox_root": str(sandbox_root),
        "inputs_dir": str(inputs_dir),
        "outputs_dir": str(outputs_dir),
        "rule_sources": rule_sources_for_repo(target_repo),
    }
