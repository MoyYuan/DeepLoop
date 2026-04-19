from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

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
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
