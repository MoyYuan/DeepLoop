from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import EXPECTED_EXTERNAL_DIRS, WORKSPACE_ROOT


def _check_python_version() -> tuple[bool, str]:
    major, minor = sys.version_info[:2]
    supported = (major, minor) >= (3, 11)
    return supported, f"detected {major}.{minor}; required >= 3.11"


def _check_operating_system() -> tuple[bool, str]:
    system = platform.system()
    supported = system == "Linux"
    return supported, f"detected {system}; supported public bootstrap contract is Linux"


def _check_workspace_root() -> tuple[bool, str]:
    if not WORKSPACE_ROOT.exists():
        return False, f"workspace root is missing: {WORKSPACE_ROOT}"
    writable = os.access(WORKSPACE_ROOT, os.W_OK)
    return writable, f"workspace root `{WORKSPACE_ROOT}` is {'writable' if writable else 'not writable'}"


def _check_external_dirs() -> tuple[bool, str]:
    missing = [str(path) for path in EXPECTED_EXTERNAL_DIRS if not path.exists()]
    if missing:
        return False, f"missing expected workspace dirs: {', '.join(missing[:4])}"
    unwritable = [str(path) for path in EXPECTED_EXTERNAL_DIRS if not os.access(path, os.W_OK)]
    if unwritable:
        return False, f"workspace dirs are not writable: {', '.join(unwritable[:4])}"
    return True, f"validated {len(EXPECTED_EXTERNAL_DIRS)} writable workspace dirs under `{WORKSPACE_ROOT}`"


def validate_public_bootstrap_environment() -> dict[str, tuple[bool, str]]:
    return {
        "python_version": _check_python_version(),
        "operating_system": _check_operating_system(),
        "workspace_root": _check_workspace_root(),
        "external_dirs": _check_external_dirs(),
    }


def main() -> int:
    checks = validate_public_bootstrap_environment()
    all_passed = True
    print("# DeepLoop public bootstrap preflight")
    for name, (passed, message) in checks.items():
        all_passed = all_passed and passed
        symbol = "PASS" if passed else "FAIL"
        print(f"- {name}: {symbol} — {message}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
