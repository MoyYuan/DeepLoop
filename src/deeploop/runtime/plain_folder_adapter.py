from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from deeploop.core.paths import RUNS_DIR


class PlainFolderStageAdapter:
    name = "deeploop.runtime.plain_folder_adapter"
    substrate_name = "plain-folder"
    substrate_repo_root = Path(__file__).resolve().parents[3]
    runs_root = RUNS_DIR / "plain-folder-adapter"
    prompt_template_id = "plain_folder_prompt_v1"
    parser_id = "plain_folder_parser_v1"

    def default_promotion_manifest(self) -> Path:
        return self.runs_root / "missing-promotion-manifest.json"

    def load_promotion_manifest(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def resolve_dataset_files(
        self,
        manifest: dict,
        *,
        tiers: list[str] | None = None,
        split_kinds: list[str] | None = None,
        split_families: list[str] | None = None,
    ) -> list[dict]:
        selected: list[dict] = []
        for item in manifest["files"]:
            if tiers and item["tier"] not in tiers:
                continue
            if split_kinds and item["split_kind"] not in split_kinds:
                continue
            if split_families and item["split_family"] not in split_families:
                continue
            selected.append(item)
        return selected

    def iter_examples(self, paths: Iterable[Path], *, limit: int | None = None):
        emitted = 0
        for path in paths:
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                yield json.loads(line)
                emitted += 1
                if limit is not None and emitted >= limit:
                    return

    def include_example(
        self,
        example: dict,
        *,
        lexicalizations: list[str] | None = None,
        rule_families: list[str] | None = None,
    ) -> bool:
        if lexicalizations and example["lex"] not in lexicalizations:
            return False
        if rule_families and example["rule"] not in rule_families:
            return False
        return True

    def format_prompt(self, example: dict) -> str:
        return json.dumps(
            {
                "project_statement": example["hypothesis"],
                "source_doc": example.get("source_doc", "plain-folder"),
            }
        )

    def parse_prediction(self, text: str) -> str:
        try:
            return str(json.loads(text).get("label", "unparsed"))
        except json.JSONDecodeError:
            return "unparsed"

    def compute_metrics(self, records: list[dict]) -> dict:
        total = len(records)
        correct = sum(1 for record in records if record["predicted_label"] == record["gold_label"])
        by_source: dict[str, dict[str, float | int | None]] = {}
        source_ids = sorted({str(record.get("source_doc", "plain-folder")) for record in records})
        for source_id in source_ids:
            selected = [record for record in records if str(record.get("source_doc", "plain-folder")) == source_id]
            source_total = len(selected)
            source_correct = sum(1 for record in selected if record["predicted_label"] == record["gold_label"])
            by_source[source_id] = {
                "count": source_total,
                "accuracy": round(source_correct / source_total, 6) if source_total else None,
            }
        return {
            "count": total,
            "accuracy": round(correct / total, 6) if total else None,
            "source_documents": by_source,
        }

    def build_prediction_record(
        self,
        example: dict,
        *,
        predicted_label: str,
        raw_output: str,
        source_metadata: dict,
    ) -> dict:
        return {
            "source_file": source_metadata["source"],
            "source_doc": example.get("source_doc", "plain-folder"),
            "tier": example["tier"],
            "lex": example["lex"],
            "rule": example["rule"],
            "chain_len": example["chain_len"],
            "split_kind": source_metadata["split_kind"],
            "split_family": source_metadata["split_family"],
            "gold_label": example["label"],
            "predicted_label": predicted_label,
            "raw_output": raw_output,
        }

    def dataset_name(self, manifest: dict) -> str:
        return manifest["dataset_id"]


def build_plain_folder_adapter() -> PlainFolderStageAdapter:
    return PlainFolderStageAdapter()
