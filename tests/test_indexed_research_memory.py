from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from deeploop.research.indexed_memory import (
    build_research_memory_contract,
    load_research_memory_index,
    record_research_memory_entry,
    retrieve_research_memory,
)
from runtime_artifact_helpers import fresh_test_root

TEST_WORK_ROOT = REPO_ROOT / "tests" / "_runtime_artifacts" / "indexed_research_memory"


def _fresh_test_root(name: str) -> Path:
    return fresh_test_root(TEST_WORK_ROOT, name)


class IndexedResearchMemoryTests(unittest.TestCase):
    def test_records_retrievable_grounded_evidence_with_provenance(self) -> None:
        test_root = _fresh_test_root("retrieves_grounded_evidence")
        contract = build_research_memory_contract(memory_root=test_root / "research-memory")

        recorded = record_research_memory_entry(
            {
                "entity_type": "critique",
                "entity_id": "finding-adapter-patch",
                "mission_id": "mission-prior",
                "status": "recorded",
                "summary": "Adapter patch reduced crash rate while preserving accuracy.",
                "payload": {
                    "critique_id": "finding-adapter-patch",
                    "manifest_id": "manifest-7",
                    "finding": "Adapter patch reduced crash rate while preserving accuracy.",
                    "recommendation": "Reuse the patch whenever the failure mode is crash instability.",
                },
                "provenance": {
                    "source_kind": "promoted-finding",
                    "mission_id": "mission-prior",
                    "recorded_at": "2026-01-01T00:00:00+00:00",
                    "source_paths": [str(test_root / "mission-prior" / "findings" / "finding-adapter-patch.md")],
                    "source_entry_id": "promoted-finding-finding-adapter-patch",
                },
                "promotion": {
                    "status": "promoted",
                    "promoted_at": "2026-01-01T00:00:00+00:00",
                    "source_entry_ids": ["promoted-finding-finding-adapter-patch"],
                },
            },
            contract=contract,
        )

        matches = retrieve_research_memory(query="crash rate accuracy patch", contract=contract, limit=3)

        self.assertEqual(recorded["entity_type"], "critique")
        self.assertEqual(matches[0]["entity_id"], "finding-adapter-patch")
        self.assertEqual(matches[0]["promotion"]["status"], "promoted")
        self.assertIn("finding-adapter-patch.md", matches[0]["provenance"]["source_paths"][0])

    def test_retention_archives_old_ephemeral_entries_but_keeps_failed_results(self) -> None:
        test_root = _fresh_test_root("retains_failed_results")
        contract = build_research_memory_contract(memory_root=test_root / "research-memory")

        for index in range(10):
            record_research_memory_entry(
                {
                    "entity_type": "experiment",
                    "entity_id": f"experiment-{index}",
                    "mission_id": "mission-retention",
                    "status": "completed",
                    "summary": f"Completed bounded run {index}.",
                    "payload": {
                        "manifest_id": f"manifest-{index}",
                        "hypothesis_id": "hypothesis-main",
                        "resource_tier": "bounded",
                        "execution_profile": "stage-kernel",
                        "result_state": "completed",
                    },
                    "provenance": {
                        "source_kind": "experiment-run",
                        "mission_id": "mission-retention",
                        "recorded_at": f"2026-01-01T00:00:{index:02d}+00:00",
                        "source_paths": [str(test_root / f"run-{index}.json")],
                        "source_entry_id": f"experiment-{index}",
                    },
                    "promotion": {"status": "candidate", "source_entry_ids": [f"experiment-{index}"]},
                },
                contract=contract,
            )
        record_research_memory_entry(
            {
                "entity_type": "experiment",
                "entity_id": "experiment-failed-anchor",
                "mission_id": "mission-retention",
                "status": "failed",
                "summary": "Failed run exposed a reproducible crash loop.",
                "payload": {
                    "manifest_id": "manifest-failed",
                    "hypothesis_id": "hypothesis-main",
                    "resource_tier": "bounded",
                    "execution_profile": "stage-kernel",
                    "result_state": "failed",
                },
                "provenance": {
                    "source_kind": "experiment-run",
                    "mission_id": "mission-retention",
                    "recorded_at": "2026-01-01T00:00:59+00:00",
                    "source_paths": [str(test_root / "failed-run.json")],
                    "source_entry_id": "experiment-failed-anchor",
                },
                "promotion": {"status": "candidate", "source_entry_ids": ["experiment-failed-anchor"]},
            },
            contract=contract,
        )

        index = load_research_memory_index(contract=contract)
        active_ids = {entry["entity_id"] for entry in index["active_entries"]}
        archived_ids = {entry["entity_id"] for entry in index["archived_entries"]}

        self.assertIn("experiment-failed-anchor", active_ids)
        self.assertNotIn("experiment-0", active_ids)
        self.assertIn("experiment-0", archived_ids)

    def test_load_research_memory_index_repairs_concatenated_json_documents(self) -> None:
        test_root = _fresh_test_root("repairs_concatenated_index")
        contract = build_research_memory_contract(memory_root=test_root / "research-memory")
        index_path = Path(contract["research_memory_index_path"])
        index_path.parent.mkdir(parents=True, exist_ok=True)
        first = {"schema_version": 1, "active_entries": [{"entity_id": "old"}], "archived_entries": []}
        second = {"schema_version": 1, "active_entries": [{"entity_id": "new"}], "archived_entries": []}
        index_path.write_text(
            json.dumps(first, indent=2) + "\n" + json.dumps(second, indent=2) + "\n",
            encoding="utf-8",
        )

        repaired = load_research_memory_index(contract=contract)

        self.assertEqual([entry["entity_id"] for entry in repaired["active_entries"]], ["new"])
        persisted = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual([entry["entity_id"] for entry in persisted["active_entries"]], ["new"])

    def test_load_research_memory_index_rebuilds_truncated_single_document_from_events(self) -> None:
        test_root = _fresh_test_root("rebuilds_truncated_index")
        contract = build_research_memory_contract(memory_root=test_root / "research-memory")
        recorded = record_research_memory_entry(
            {
                "entity_type": "critique",
                "entity_id": "recoverable-entry",
                "mission_id": "mission-rebuild",
                "status": "recorded",
                "summary": "Recovered from a truncated index by replaying the event ledger.",
                "payload": {
                    "critique_id": "recoverable-entry",
                    "manifest_id": "manifest-rebuild",
                    "finding": "Recovered from a truncated index by replaying the event ledger.",
                    "recommendation": "Rebuild the index from entries when the JSON document is truncated.",
                },
                "provenance": {
                    "source_kind": "promoted-finding",
                    "mission_id": "mission-rebuild",
                    "recorded_at": "2026-01-01T00:00:00+00:00",
                    "source_entry_id": "recoverable-entry",
                },
                "promotion": {
                    "status": "promoted",
                    "promoted_at": "2026-01-01T00:00:00+00:00",
                    "source_entry_ids": ["recoverable-entry"],
                },
            },
            contract=contract,
        )
        index_path = Path(contract["research_memory_index_path"])
        index_path.write_text('{"schema_version": 1, "active_entries": [', encoding="utf-8")

        rebuilt = load_research_memory_index(contract=contract)

        self.assertEqual([entry["entity_id"] for entry in rebuilt["active_entries"]], [recorded["entity_id"]])
        persisted = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual([entry["entity_id"] for entry in persisted["active_entries"]], [recorded["entity_id"]])

    def test_load_research_memory_index_deduplicates_archived_entries_when_rebuilding_from_events(self) -> None:
        test_root = _fresh_test_root("deduplicates_archived_entries")
        contract = build_research_memory_contract(memory_root=test_root / "research-memory")

        for index in range(10):
            record_research_memory_entry(
                {
                    "entity_type": "experiment",
                    "entity_id": f"experiment-{index}",
                    "mission_id": "mission-dedup",
                    "status": "completed",
                    "summary": f"Completed bounded run {index}.",
                    "payload": {
                        "manifest_id": f"manifest-{index}",
                        "hypothesis_id": "hypothesis-main",
                        "resource_tier": "bounded",
                        "execution_profile": "stage-kernel",
                        "result_state": "completed",
                    },
                    "provenance": {
                        "source_kind": "experiment-run",
                        "mission_id": "mission-dedup",
                        "recorded_at": f"2026-01-01T00:00:{index:02d}+00:00",
                        "source_entry_id": f"experiment-{index}",
                    },
                    "promotion": {"status": "candidate", "source_entry_ids": [f"experiment-{index}"]},
                },
                contract=contract,
            )

        index_path = Path(contract["research_memory_index_path"])
        index_path.write_text('{"schema_version": 1, "active_entries": [', encoding="utf-8")

        rebuilt = load_research_memory_index(contract=contract)

        self.assertEqual(len(rebuilt["active_entries"]), 8)
        self.assertEqual({entry["entity_id"] for entry in rebuilt["archived_entries"]}, {"experiment-0", "experiment-1"})
        self.assertEqual(len(rebuilt["archived_entries"]), 2)

    def test_load_research_memory_index_rebuilds_oversized_index_from_events_before_parsing(self) -> None:
        test_root = _fresh_test_root("rebuilds_oversized_index")
        contract = build_research_memory_contract(memory_root=test_root / "research-memory")
        recorded = record_research_memory_entry(
            {
                "entity_type": "critique",
                "entity_id": "oversized-index-entry",
                "mission_id": "mission-oversized",
                "status": "recorded",
                "summary": "Replay events instead of parsing a pathologically bloated index.",
                "payload": {
                    "critique_id": "oversized-index-entry",
                    "manifest_id": "manifest-oversized",
                    "finding": "Replay events instead of parsing a pathologically bloated index.",
                    "recommendation": "Rebuild from the authoritative event ledger when the index is implausibly large.",
                },
                "provenance": {
                    "source_kind": "promoted-finding",
                    "mission_id": "mission-oversized",
                    "recorded_at": "2026-01-01T00:00:00+00:00",
                    "source_entry_id": "oversized-index-entry",
                },
                "promotion": {
                    "status": "promoted",
                    "promoted_at": "2026-01-01T00:00:00+00:00",
                    "source_entry_ids": ["oversized-index-entry"],
                },
            },
            contract=contract,
        )
        index_path = Path(contract["research_memory_index_path"])
        index_path.write_text(
            json.dumps({"schema_version": 1, "active_entries": [{"entity_id": "stale"}], "archived_entries": []}, indent=2)
            + ("\n" * 512),
            encoding="utf-8",
        )

        with (
            patch("deeploop.research.indexed_memory._MAX_REASONABLE_INDEX_BYTES", 1),
            patch("deeploop.research.indexed_memory._MAX_INDEX_TO_EVENTS_RATIO", 0),
            patch("deeploop.research.indexed_memory._load_json", side_effect=AssertionError("oversized index should rebuild")),
        ):
            rebuilt = load_research_memory_index(contract=contract)

        self.assertEqual([entry["entity_id"] for entry in rebuilt["active_entries"]], [recorded["entity_id"]])

    def test_rejects_recursive_payload_before_json_serialization(self) -> None:
        test_root = _fresh_test_root("rejects_recursive_payload")
        contract = build_research_memory_contract(memory_root=test_root / "research-memory")
        payload: dict[str, object] = {"summary": "Recursive payload should fail normally."}
        payload["self"] = payload

        with self.assertRaisesRegex(ValueError, "circular reference"):
            record_research_memory_entry(
                {
                    "entity_type": "mission",
                    "entity_id": "recursive-mission",
                    "mission_id": "recursive-mission",
                    "status": "running",
                    "summary": "Recursive payload should fail normally.",
                    "payload": payload,
                    "provenance": {
                        "source_kind": "mission-memory",
                        "mission_id": "recursive-mission",
                        "recorded_at": "2026-01-01T00:00:00+00:00",
                    },
                },
                contract=contract,
            )


if __name__ == "__main__":
    unittest.main()
