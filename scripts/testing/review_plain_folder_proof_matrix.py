from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.structured_io import write_json_object
from deeploop.testing.proof_matrix_reviews import (
    build_multi_substrate_proof_review,
    materialize_proof_matrix_review,
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_campaign_summary(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a milestone-style proof review from one or more existing campaign summaries.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--campaign-summary",
        action="append",
        required=True,
        type=Path,
        help="Path to a campaign_summary.json file. Repeatable.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Directory where the combined review should be written.",
    )
    parser.add_argument(
        "--review-id",
        help="Optional explicit review id for the combined campaign summary.",
    )
    args = parser.parse_args()

    campaign_summaries = [_load_campaign_summary(path.expanduser().resolve()) for path in args.campaign_summary]
    combined_summary = {
        "campaign_id": args.review_id or f"plain-folder-proof-review-{_utc_stamp()}",
        "source_campaigns": [summary.get("campaign_id") for summary in campaign_summaries],
        "status": "failed"
        if any(summary.get("status") != "passed" for summary in campaign_summaries)
        else "passed",
        "cases_run": [
            case_id
            for summary in campaign_summaries
            for case_id in summary.get("cases_run", [])
        ],
        "failed_case_ids": [
            case_id
            for summary in campaign_summaries
            for case_id in summary.get("failed_case_ids", [])
        ],
        "case_summaries": [
            case_summary
            for summary in campaign_summaries
            for case_summary in summary.get("case_summaries", [])
        ],
    }
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    write_json_object(output_root / "combined_campaign_summary.json", combined_summary)
    review = build_multi_substrate_proof_review(combined_summary)
    review_paths = materialize_proof_matrix_review(review, output_root)
    payload = {
        **combined_summary,
        **review_paths,
        "proof_review": review,
    }
    print(json.dumps(payload, indent=2))
    return 0 if review.get("decision") == "eligible-for-promotion" else 1


if __name__ == "__main__":
    raise SystemExit(main())
