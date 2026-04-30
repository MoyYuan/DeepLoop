import os
from pathlib import Path


def _resolve_repo_root() -> Path:
    source_root = Path(__file__).resolve().parents[3]
    if (source_root / "configs").is_dir() and (source_root / "schemas").is_dir():
        return source_root

    packaged_assets_root = Path(__file__).resolve().parents[1] / "_assets"
    if (packaged_assets_root / "configs").is_dir() and (packaged_assets_root / "schemas").is_dir():
        return packaged_assets_root

    return source_root


REPO_ROOT = _resolve_repo_root()
DEFAULT_WORKSPACE_ROOT = Path.home() / "workspaces"
WORKSPACE_ROOT_ENV_VAR = "DEEPLOOP_WORKSPACE_ROOT"


def _resolve_workspace_root() -> Path:
    override = os.environ.get(WORKSPACE_ROOT_ENV_VAR, "").strip()
    if not override:
        return DEFAULT_WORKSPACE_ROOT
    return Path(override).expanduser().resolve()


WORKSPACE_ROOT = _resolve_workspace_root()
DATA_DIR = WORKSPACE_ROOT / "data" / "deeploop"
CHECKPOINT_DIR = WORKSPACE_ROOT / "checkpoints" / "deeploop"
RUNS_DIR = WORKSPACE_ROOT / "runs" / "deeploop"
LAUNCHES_DIR = RUNS_DIR / "launches"
PACKAGES_DIR = RUNS_DIR / "packages"
SCRATCH_DIR = WORKSPACE_ROOT / "scratch" / "deeploop"
MISSIONS_DIR = RUNS_DIR / "missions"
LEDGER_DIR = RUNS_DIR / "ledger"
RESEARCH_MEMORY_DIR = LEDGER_DIR / "research_memory"
FINDINGS_DIR = RUNS_DIR / "findings"
SANDBOXES_DIR = SCRATCH_DIR / "sandboxes"
COPILOT_RULES_PATH = Path.home() / ".copilot" / "copilot-instructions.md"
WORKSPACE_RULES_PATH = WORKSPACE_ROOT / "AGENTS.md"

EXPECTED_EXTERNAL_DIRS = (
    DATA_DIR,
    CHECKPOINT_DIR,
    RUNS_DIR,
    LAUNCHES_DIR,
    PACKAGES_DIR,
    SCRATCH_DIR,
    MISSIONS_DIR,
    LEDGER_DIR,
    RESEARCH_MEMORY_DIR,
    FINDINGS_DIR,
    SANDBOXES_DIR,
)
EXPECTED_SUBSTRATE_REPOS: tuple[Path, ...] = ()

__all__ = [
    "CHECKPOINT_DIR",
    "COPILOT_RULES_PATH",
    "DATA_DIR",
    "DEFAULT_WORKSPACE_ROOT",
    "EXPECTED_EXTERNAL_DIRS",
    "EXPECTED_SUBSTRATE_REPOS",
    "FINDINGS_DIR",
    "LAUNCHES_DIR",
    "LEDGER_DIR",
    "RESEARCH_MEMORY_DIR",
    "MISSIONS_DIR",
    "PACKAGES_DIR",
    "REPO_ROOT",
    "RUNS_DIR",
    "SANDBOXES_DIR",
    "SCRATCH_DIR",
    "WORKSPACE_ROOT",
    "WORKSPACE_ROOT_ENV_VAR",
    "WORKSPACE_RULES_PATH",
]
