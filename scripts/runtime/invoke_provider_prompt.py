from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]


def _bootstrap_import_path() -> None:
    candidates: list[Path] = []

    cache_src = os.environ.get("DEEPLOOP_RUNTIME_CACHE_SRC", "").strip()
    if cache_src:
        candidates.append(Path(cache_src).expanduser().resolve())

    repo_src = REPO_ROOT / "src"
    if repo_src.is_dir():
        candidates.append(repo_src)

    package_root = SCRIPT_PATH.parents[3]
    if package_root.name == "deeploop" and (package_root / "__init__.py").is_file():
        candidates.append(package_root.parent)

    for candidate in candidates:
        candidate_text = str(candidate)
        if candidate.is_dir() and candidate_text not in sys.path:
            sys.path.insert(0, candidate_text)


_bootstrap_import_path()

from deeploop.runtime.provider_launcher import run_provider_prompt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider-family", default="copilot-cli")
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--result-json-path")
    parser.add_argument("--sandbox-root")
    parser.add_argument("--mission-state-path")
    parser.add_argument("--target-repo")
    parser.add_argument("--model")
    parser.add_argument("--allow-all", action="store_true", default=False)
    parser.add_argument("--no-ask-user", action="store_true", default=False)
    parser.add_argument("--idle-timeout-seconds", type=float)
    args = parser.parse_args(argv)

    completed = run_provider_prompt(
        Path(args.prompt_file).expanduser().resolve(),
        provider_family=args.provider_family,
        result_json_path=Path(args.result_json_path).expanduser().resolve() if args.result_json_path else None,
        sandbox_root=Path(args.sandbox_root).expanduser().resolve() if args.sandbox_root else None,
        mission_state_path=Path(args.mission_state_path).expanduser().resolve() if args.mission_state_path else None,
        target_repo=Path(args.target_repo).expanduser().resolve() if args.target_repo else None,
        model=args.model,
        allow_all=args.allow_all,
        no_ask_user=args.no_ask_user,
        idle_timeout_seconds=args.idle_timeout_seconds,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
