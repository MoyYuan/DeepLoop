from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.artifacts.release_automation import (
    build_release_candidate_review,
    load_release_candidate_approvals,
    load_release_candidate_policy,
    materialize_release_candidate_promotion,
    materialize_release_candidate_review,
)
from deeploop.core.structured_io import load_json_object as _load_json


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate and optionally promote a DeepLoop mission package as a release candidate."
    )
    parser.add_argument("--package-manifest", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--approvals")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    args = parser.parse_args()

    package_manifest_path = Path(args.package_manifest).expanduser().resolve()
    package = _load_json(package_manifest_path)
    policy = load_release_candidate_policy(Path(args.policy).expanduser().resolve()) if args.policy else load_release_candidate_policy()
    approvals = load_release_candidate_approvals(Path(args.approvals).expanduser().resolve()) if args.approvals else None

    review = build_release_candidate_review(
        package,
        package_manifest_path=package_manifest_path,
        policy=policy,
        approvals=approvals,
    )
    materialized = materialize_release_candidate_review(
        review,
        package_root=Path(package["package_root"]),
        policy=policy,
    )
    rendered_review = materialized["review"]
    promotion_path = None
    if args.promote:
        if not rendered_review["eligible_for_promotion"]:
            print("release-candidate promotion blocked by failed gates", file=sys.stderr)
            exit_code = 2
        else:
            promotion_path = materialize_release_candidate_promotion(
                rendered_review,
                package_root=Path(package["package_root"]),
                policy=policy,
            )
            rendered_review["review_artifacts"]["promotion"] = str(promotion_path)
            materialized = materialize_release_candidate_review(
                rendered_review,
                package_root=Path(package["package_root"]),
                policy=policy,
            )
            rendered_review = materialized["review"]
            exit_code = 0
    else:
        exit_code = 0

    payload = {
        "decision": rendered_review["decision"],
        "eligible_for_promotion": rendered_review["eligible_for_promotion"],
        "review_json": str(materialized["review_json"]),
        "review_markdown": str(materialized["review_markdown"]),
        "promotion_json": str(promotion_path) if promotion_path else None,
    }
    print(json.dumps(rendered_review if args.emit_json else payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
