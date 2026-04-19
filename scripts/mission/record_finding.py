from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.autonomy.mission_autonomy import build_outer_loop_contract
from deeploop.core.ledger import append_jsonl, make_ledger_entry, now_utc
from deeploop.mission.mission_memory import append_mission_experiment_entry, sync_mission_memory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission-state", required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()

    state_path = Path(args.mission_state).resolve()
    mission_root = state_path.parent
    state = json.loads(state_path.read_text(encoding="utf-8"))
    outer_loop = state.get("outer_loop") if isinstance(state.get("outer_loop"), dict) else {}
    if not outer_loop:
        outer_loop = build_outer_loop_contract(mission_root, mode=str(state.get("mode") or "default"))
        state["outer_loop"] = outer_loop
    findings_root = mission_root / "findings"
    findings_root.mkdir(parents=True, exist_ok=True)
    finding_path = findings_root / f"finding-{now_utc().replace(':', '-')}.md"
    finding_path.write_text(args.summary + "\n", encoding="utf-8")

    ledger_path = mission_root / "ledger.jsonl"
    append_jsonl(
        ledger_path,
        make_ledger_entry(
            kind="finding",
            mission_id=state["mission_id"],
            summary=args.summary,
            status="recorded",
            related_paths=[str(finding_path)],
        ),
    )
    append_mission_experiment_entry(
        state_path,
        state["mission_id"],
        contract=outer_loop,
        entry_id=f"promoted-finding-{finding_path.stem}",
        kind="promoted-finding",
        status="recorded",
        summary=args.summary,
        phase=str(state.get("current_phase") or ""),
        artifact_paths=[str(finding_path)],
        metadata={
            "finding_id": finding_path.stem,
            "finding_path": str(finding_path),
            "claim_state": "promoted",
        },
    )
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    sync_mission_memory(state_path, state, contract=outer_loop)
    print(f"record-finding: wrote {finding_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
