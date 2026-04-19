from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.testing.plain_folder_proof_matrix import (
    PlainFolderProofCase,
    discover_plain_folder_proof_cases,
    parse_run_project_output,
    snapshot_project_tree,
    summarize_boundary_check,
)


class PlainFolderProofMatrixTests(unittest.TestCase):
    def test_discover_plain_folder_proof_cases_reads_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixtures_root = Path(tmpdir)
            case_root = fixtures_root / "demo-case"
            (case_root / "docs").mkdir(parents=True, exist_ok=True)
            (case_root / "project-facts.yaml").write_text("project:\n  name: demo\n", encoding="utf-8")
            (case_root / "proof-case.yaml").write_text(
                "\n".join(
                    [
                        "case_id: demo-case",
                        "title: Demo case",
                        "summary: Demo summary",
                        "workflow_shape: literature-heavy",
                        "expected_focus: prior-art synthesis",
                        "autonomy_claims:",
                        "  - Keep the operator inbox clear.",
                        "acceptance_thresholds:",
                        "  require_final_report_outputs: true",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            cases = discover_plain_folder_proof_cases(fixtures_root)

        self.assertEqual(
            cases,
            [
                PlainFolderProofCase(
                    case_id="demo-case",
                    fixture_root=case_root.resolve(),
                    title="Demo case",
                    summary="Demo summary",
                    workflow_shape="literature-heavy",
                    expected_focus="prior-art synthesis",
                    autonomy_claims=("Keep the operator inbox clear.",),
                    acceptance_thresholds={"require_final_report_outputs": True},
                )
            ],
        )

    def test_parse_run_project_output_accepts_trailing_noise(self) -> None:
        payload = parse_run_project_output('{"status":"completed","mission_state_path":"/tmp/demo"}\nextra logs')
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["mission_state_path"], "/tmp/demo")

    def test_snapshot_and_boundary_summary_detect_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "docs").mkdir(parents=True, exist_ok=True)
            (project_root / "docs" / "brief.md").write_text("# Brief\n", encoding="utf-8")
            before = snapshot_project_tree(project_root)
            (project_root / "runtime").mkdir(parents=True, exist_ok=True)
            (project_root / "runtime" / "state.json").write_text("{}\n", encoding="utf-8")
            after = snapshot_project_tree(project_root)

        boundary = summarize_boundary_check(before, after)
        self.assertFalse(boundary["project_tree_unchanged"])
        self.assertIn("runtime/", boundary["added_paths"])
        self.assertIn("runtime/state.json", boundary["added_paths"])


if __name__ == "__main__":
    unittest.main()
