from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

SCRIPT_PATH = REPO_ROOT / "scripts" / "testing" / "run_plain_folder_proof_matrix.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("run_plain_folder_proof_matrix_script", SCRIPT_PATH)
assert _SCRIPT_SPEC is not None and _SCRIPT_SPEC.loader is not None
run_plain_folder_proof_matrix = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(run_plain_folder_proof_matrix)


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

    def test_run_case_marks_timeout_as_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fixture_root = tmp_path / "fixture"
            (fixture_root / "docs").mkdir(parents=True, exist_ok=True)
            (fixture_root / "project-facts.yaml").write_text("project:\n  name: demo\n", encoding="utf-8")
            case_root = tmp_path / "campaign" / "demo-case"
            case_root.mkdir(parents=True, exist_ok=True)
            case = PlainFolderProofCase(
                case_id="demo-case",
                fixture_root=fixture_root,
                title="Demo case",
                summary="Demo summary",
                workflow_shape="literature-heavy",
                expected_focus="prior-art synthesis",
                autonomy_claims=(),
            )
            with patch.object(
                run_plain_folder_proof_matrix,
                "_run_case_command",
                return_value=(
                    subprocess.CompletedProcess(
                        [sys.executable, "scripts/mission/run_project.py"],
                        124,
                        "partial stdout",
                        "partial stderr",
                    ),
                    "run_project.py timed out after 12 seconds",
                ),
            ):
                summary = run_plain_folder_proof_matrix._run_case(
                    case,
                    case_root,
                    sys.executable,
                    case_timeout_seconds=12,
                )

        self.assertEqual(summary["status"], "failed")
        self.assertIn("timed out after 12 seconds", "\n".join(summary["failures"]))
        self.assertEqual(summary["case_timeout_seconds"], 12)
        self.assertIn("run_project.py exited 124", summary["failures"])

    def test_run_case_command_kills_process_group_on_timeout(self) -> None:
        process = Mock()
        process.pid = 4242
        process.returncode = None
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(
                cmd=["python", "scripts/mission/run_project.py"],
                timeout=5,
                output="partial stdout",
                stderr="partial stderr",
            ),
            ("partial stdout", "partial stderr"),
        ]

        with patch.object(run_plain_folder_proof_matrix.subprocess, "Popen", return_value=process):
            with patch.object(run_plain_folder_proof_matrix.os, "killpg") as killpg:
                completed, timeout_message = run_plain_folder_proof_matrix._run_case_command(
                    [sys.executable, "scripts/mission/run_project.py"],
                    case_timeout_seconds=5,
                )

        self.assertEqual(completed.returncode, 124)
        self.assertEqual(completed.stdout, "partial stdout")
        self.assertEqual(completed.stderr, "partial stderr")
        self.assertEqual(timeout_message, "run_project.py timed out after 5 seconds")
        killpg.assert_called_once_with(4242, run_plain_folder_proof_matrix.signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
