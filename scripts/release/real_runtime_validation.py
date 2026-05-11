from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.artifacts.real_runtime_validation import validate_real_runtime


def _parse_lane_notes(values: list[str]) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for raw in values:
        lane_id, separator, note = raw.partition("=")
        if not separator or not lane_id.strip() or not note.strip():
            raise ValueError("--lane-note entries must use the form <lane-id>=<note>")
        parsed.setdefault(lane_id.strip(), []).append(note.strip())
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Gate 2 real-runtime validation harness for the approved local Qwen OpenAI-compatible lane "
            "and/or the Copilot CLI gpt-5-mini coding-agent lane."
        )
    )
    parser.add_argument("--lane", action="append", dest="lanes", help="Specific lane id to validate. Repeat to run multiple lanes.")
    parser.add_argument("--output-root", help="Optional override for the durable evidence root.")
    parser.add_argument("--validation-id", help="Optional stable id for this validation batch.")
    parser.add_argument("--operator", help="Optional operator label recorded in the durable evidence.")
    parser.add_argument("--machine-label", help="Optional machine label recorded in the durable evidence.")
    parser.add_argument(
        "--manual-note",
        action="append",
        default=[],
        help="Manual setup or proof-boundary note that applies to every requested lane. Repeat as needed.",
    )
    parser.add_argument(
        "--lane-note",
        action="append",
        default=[],
        help="Lane-specific manual note using <lane-id>=<note>. Repeat as needed.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the batch summary as JSON.")
    args = parser.parse_args(argv)

    try:
        lane_notes = _parse_lane_notes(args.lane_note)
        result = validate_real_runtime(
            lane_ids=args.lanes,
            output_root=args.output_root,
            validation_id=args.validation_id,
            operator=args.operator,
            machine_label=args.machine_label,
            general_notes=args.manual_note,
            lane_notes=lane_notes,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"gate-2-runtime-validation: {result['status']}")
        print(f"gate-2-runtime-validation: summary_json={result['summary_json_path']}")
        for item in result["lane_results"]:
            print(
                "gate-2-runtime-validation: "
                f"{item['lane_id']}={item['status']} ({item['record_json_path']})"
            )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
