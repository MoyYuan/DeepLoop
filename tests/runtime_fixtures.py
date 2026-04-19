from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


class DemoRuntimeAdapter:
    name = "runtime_fixtures.demo_runtime_adapter"
    substrate_name = "demo-substrate"
    substrate_repo_root = Path(__file__).resolve().parents[1]
    runs_root = Path.home() / "workspaces" / "runs" / "deeploop" / "runtime-fixtures"
    prompt_template_id = "demo_prompt_v1"
    parser_id = "demo_parser_v1"

    def __init__(self, promotion_manifest_path: Path | None = None) -> None:
        self._promotion_manifest_path = promotion_manifest_path or (self.runs_root / "missing-promotion-manifest.json")

    def default_promotion_manifest(self) -> Path:
        return self._promotion_manifest_path

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
        return json.dumps({"hypothesis": example["hypothesis"], "rule": example["rule"]})

    def parse_prediction(self, text: str) -> str:
        try:
            return str(json.loads(text).get("label", "unparsed"))
        except json.JSONDecodeError:
            return "unparsed"

    def compute_metrics(self, records: list[dict]) -> dict:
        total = len(records)
        correct = sum(1 for record in records if record["predicted_label"] == record["gold_label"])
        lexicalization: dict[str, dict] = {}
        rule_family: dict[str, dict] = {}
        for field, bucket in (("lex", lexicalization), ("rule", rule_family)):
            values = sorted({record[field] for record in records})
            for value in values:
                selected = [record for record in records if record[field] == value]
                bucket[value] = {
                    "count": len(selected),
                    "accuracy": round(
                        sum(1 for record in selected if record["predicted_label"] == record["gold_label"]) / max(len(selected), 1),
                        6,
                    ),
                }
        lexicalization_gap = None
        if "lex" in lexicalization and "delex" in lexicalization:
            lexicalization_gap = round(lexicalization["lex"]["accuracy"] - lexicalization["delex"]["accuracy"], 6)
        return {
            "count": total,
            "accuracy": round(correct / total, 6) if total else None,
            "lexicalization": lexicalization,
            "rule_family": rule_family,
            "lexicalization_gap": lexicalization_gap,
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


def build_demo_adapter() -> DemoRuntimeAdapter:
    return DemoRuntimeAdapter()
