import os
from pathlib import Path

def _resolve_repo_root() -> Path:
    source_root = Path(__file__).resolve().parents[3]
    if (source_root / "configs").is_dir() and (source_root / "schemas").is_dir():
        return source_root

    packaged_assets_root = Path(__file__).resolve().parents[1] / "_assets"
    if (packaged_assets_root / "configs").is_dir() and (packaged_assets_root / "schemas").is_dir():
        return packaged_assets_root

    raise RuntimeError(
        "Unable to resolve DeepLoop runtime assets. Expected either a source checkout "
        f"at {source_root} or packaged assets at {packaged_assets_root}."
    )


REPO_ROOT = _resolve_repo_root()
WORKSPACE_ROOT_ENV_VAR = "DEEPLOOP_WORKSPACE_ROOT"
RUNS_ROOT_ENV_VAR = "DEEPLOOP_RUNS_ROOT"
FALLBACK_WORKSPACE_ROOT_NAME = "workspaces"
COMMON_WORKSPACE_ROOT_NAMES = ("Workspaces", "workspace", FALLBACK_WORKSPACE_ROOT_NAME)
WORKSPACE_URI_PREFIX = "workspace://"


def _default_workspace_root() -> Path:
    home = Path.home()
    for name in COMMON_WORKSPACE_ROOT_NAMES:
        candidate = home / name
        if candidate.exists():
            return candidate
    return home / FALLBACK_WORKSPACE_ROOT_NAME


DEFAULT_WORKSPACE_ROOT = _default_workspace_root()


def _resolve_workspace_root() -> Path:
    override = os.environ.get(WORKSPACE_ROOT_ENV_VAR, "").strip()
    if not override:
        return DEFAULT_WORKSPACE_ROOT
    return Path(override).expanduser().resolve()


def _resolve_runs_dir() -> Path:
    override = os.environ.get(RUNS_ROOT_ENV_VAR, "").strip()
    if not override:
        return WORKSPACE_ROOT / "runs" / "deeploop"
    return Path(override).expanduser().resolve()


def resolve_workspace_path(path: str | Path) -> Path:
    raw_text = str(path)
    if raw_text.startswith(WORKSPACE_URI_PREFIX):
        relative = raw_text.removeprefix(WORKSPACE_URI_PREFIX).lstrip("/")
        return (WORKSPACE_ROOT / relative).resolve()
    if raw_text.startswith(f"${{{WORKSPACE_ROOT_ENV_VAR}}}"):
        relative = raw_text.removeprefix(f"${{{WORKSPACE_ROOT_ENV_VAR}}}").lstrip("/")
        return (WORKSPACE_ROOT / relative).resolve()
    if raw_text.startswith(f"${WORKSPACE_ROOT_ENV_VAR}"):
        relative = raw_text.removeprefix(f"${WORKSPACE_ROOT_ENV_VAR}").lstrip("/")
        return (WORKSPACE_ROOT / relative).resolve()
    return Path(raw_text).expanduser().resolve()


def workspace_root_diagnostics(project_root: str | Path | None = None) -> list[str]:
    diagnostics: list[str] = []
    home = Path.home()
    lowercase_root = home / FALLBACK_WORKSPACE_ROOT_NAME
    titlecase_root = home / "Workspaces"
    if lowercase_root.exists() and titlecase_root.exists() and lowercase_root.resolve() != titlecase_root.resolve():
        diagnostics.append(
            f"Both `{titlecase_root}` and `{lowercase_root}` exist on this case-sensitive filesystem. "
            f"DeepLoop is using `{WORKSPACE_ROOT}`; set {WORKSPACE_ROOT_ENV_VAR} before init/start to choose a different root."
        )

    if project_root is not None:
        resolved_project_root = Path(project_root).expanduser().resolve()
        try:
            resolved_project_root.relative_to(WORKSPACE_ROOT.resolve())
        except ValueError:
            diagnostics.append(
                f"Project root `{resolved_project_root}` is outside DeepLoop workspace root `{WORKSPACE_ROOT}`. "
                f"Set {WORKSPACE_ROOT_ENV_VAR}={resolved_project_root.parent} before init/start if runtime artifacts should share that workspace."
            )
    return diagnostics


WORKSPACE_ROOT = _resolve_workspace_root()
DATA_DIR = WORKSPACE_ROOT / "data" / "deeploop"
CHECKPOINT_DIR = WORKSPACE_ROOT / "checkpoints" / "deeploop"
RUNS_DIR = _resolve_runs_dir()
LAUNCHES_DIR = RUNS_DIR / "launches"
PACKAGES_DIR = RUNS_DIR / "packages"
SCRATCH_DIR = WORKSPACE_ROOT / "scratch" / "deeploop"
MISSIONS_DIR = RUNS_DIR / "missions"
LEDGER_DIR = RUNS_DIR / "ledger"
RESEARCH_MEMORY_DIR = LEDGER_DIR / "research_memory"
FINDINGS_DIR = RUNS_DIR / "findings"
SANDBOXES_DIR = SCRATCH_DIR / "sandboxes"
PROJECTS_DIR = WORKSPACE_ROOT / "projects"
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
    PROJECTS_DIR,
)
EXPECTED_SUBSTRATE_REPOS: tuple[Path, ...] = ()


def ensure_expected_external_dirs() -> tuple[list[Path], list[Path]]:
    created: list[Path] = []
    existing: list[Path] = []
    for path in EXPECTED_EXTERNAL_DIRS:
        if path.exists():
            existing.append(path)
        else:
            created.append(path)
        path.mkdir(parents=True, exist_ok=True)
    return created, existing

__all__ = [
    "CHECKPOINT_DIR",
    "COPILOT_RULES_PATH",
    "DATA_DIR",
    "DEFAULT_WORKSPACE_ROOT",
    "EXPECTED_EXTERNAL_DIRS",
    "EXPECTED_SUBSTRATE_REPOS",
    "ensure_expected_external_dirs",
    "FINDINGS_DIR",
    "LAUNCHES_DIR",
    "LEDGER_DIR",
    "RESEARCH_MEMORY_DIR",
    "MISSIONS_DIR",
    "PACKAGES_DIR",
    "PROJECTS_DIR",
    "COMMON_WORKSPACE_ROOT_NAMES",
    "REPO_ROOT",
    "RUNS_DIR",
    "RUNS_ROOT_ENV_VAR",
    "SANDBOXES_DIR",
    "SCRATCH_DIR",
    "FALLBACK_WORKSPACE_ROOT_NAME",
    "WORKSPACE_ROOT",
    "WORKSPACE_ROOT_ENV_VAR",
    "WORKSPACE_RULES_PATH",
    "WORKSPACE_URI_PREFIX",
    "resolve_workspace_path",
    "workspace_root_diagnostics",
]
