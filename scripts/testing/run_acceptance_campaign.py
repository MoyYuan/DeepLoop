from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
root_text = str(SRC_ROOT)
if root_text not in sys.path:
    sys.path.insert(0, root_text)

from deeploop.testing.acceptance_campaigns import (
    DEFAULT_ACCEPTANCE_CAMPAIGN,
    build_acceptance_review,
    materialize_acceptance_review,
)


def _parse_json_payload(raw_output: str) -> dict[str, object]:
    lines = raw_output.splitlines()
    json_start = next((index for index, line in enumerate(lines) if line.strip().startswith("{")), None)
    if json_start is None:
        raise RuntimeError(f"Acceptance campaign did not emit a final JSON payload.\n{raw_output}")
    return json.loads("\n".join(lines[json_start:]))


def _run_plain_folder_campaign(args: argparse.Namespace) -> dict[str, object]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "testing" / "run_plain_folder_proof_matrix.py"),
        "--campaign-id",
        args.campaign,
        "--python-bin",
        args.python_bin,
    ]
    if args.fixtures_root:
        command.extend(["--fixtures-root", str(args.fixtures_root)])
    if args.campaign_root:
        command.extend(["--campaign-root", str(args.campaign_root)])
    if args.stop_on_failure:
        command.append("--stop-on-failure")
    for case_id in args.case:
        command.extend(["--case", case_id])

    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(completed.stdout + completed.stderr)
    return _parse_json_payload(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run DeepLoop's public translation plain-folder acceptance campaign.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--campaign",
        choices=(DEFAULT_ACCEPTANCE_CAMPAIGN,),
        default=DEFAULT_ACCEPTANCE_CAMPAIGN,
        help="Which acceptance campaign to run.",
    )
    parser.add_argument("--case", action="append", default=[], help="Specific proof case id to run. Repeatable.")
    parser.add_argument("--fixtures-root", type=Path, help="Override the proof fixture root.")
    parser.add_argument("--campaign-root", type=Path, help="Override where campaign outputs are written.")
    parser.add_argument("--python-bin", default=sys.executable, help="Python executable to use for project runs.")
    parser.add_argument("--stop-on-failure", action="store_true", help="Stop after the first failing proof case.")
    args = parser.parse_args()

    summary = _run_plain_folder_campaign(args)
    campaign_root = Path(summary["campaign_root"]).expanduser().resolve()
    summary_json_path = campaign_root / "campaign_summary.json"
    summary["summary_json_path"] = str(summary_json_path)
    review = build_acceptance_review(summary, campaign_id=args.campaign)
    review_paths = materialize_acceptance_review(review, output_root=campaign_root)

    print(f"campaign: {args.campaign}")
    print(f"decision: {review['decision']}")
    print(f"summary_json: {summary_json_path}")
    print(f"acceptance_review_json: {review_paths['json_path']}")
    print(f"acceptance_review_md: {review_paths['markdown_path']}")
    return 0 if review["decision"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
