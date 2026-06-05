"""Tests for deeploop.runtime.gpu_monitor.ExperimentMonitor."""

from __future__ import annotations

import os
import subprocess  # noqa: F401 -- used in mock for TimeoutExpired
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.gpu_monitor import ExperimentMonitor, GpuMonitorConfig


class ExperimentMonitorTests(unittest.TestCase):
    """Test ExperimentMonitor using mocks and temp files."""

    def setUp(self):
        self.pid = 12345
        self.temp_log = tempfile.NamedTemporaryFile(  # noqa: SIM115
            delete=False, suffix=".log", mode="w"
        )
        self.log_path = Path(self.temp_log.name)
        self.monitor = ExperimentMonitor(
            pid=self.pid,
            log_file=self.log_path,
            poll_interval=0.001,
        )

    def tearDown(self):
        self.temp_log.close()
        if self.log_path.exists():
            self.log_path.unlink()

    # ------------------------------------------------------------------
    # is_running
    # ------------------------------------------------------------------

    @patch("os.kill")
    def test_is_running_true(self, mock_kill):
        """is_running returns True when the process exists."""
        mock_kill.return_value = None
        self.assertTrue(self.monitor.is_running())
        mock_kill.assert_called_once_with(self.pid, 0)

    @patch("os.kill")
    def test_is_running_false(self, mock_kill):
        """is_running returns False when the process does not exist."""
        mock_kill.side_effect = OSError("No such process")
        self.assertFalse(self.monitor.is_running())

    # ------------------------------------------------------------------
    # gpu_utilization
    # ------------------------------------------------------------------

    @patch("deeploop.runtime.gpu_monitor.subprocess.run")
    def test_gpu_utilization_success(self, mock_run):
        """gpu_utilization parses nvidia-smi output correctly."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "75 %, 1234 MiB\n80 %, 5678 MiB\n"
        mock_run.return_value = mock_result

        result = self.monitor.gpu_utilization()
        self.assertIsNotNone(result)
        self.assertIn("devices", result)
        self.assertEqual(len(result["devices"]), 2)
        self.assertEqual(result["devices"][0]["utilization.gpu"], "75 %")
        self.assertEqual(result["devices"][1]["memory.used"], "5678 MiB")

    @patch("deeploop.runtime.gpu_monitor.subprocess.run")
    def test_gpu_utilization_no_nvidia_smi(self, mock_run):
        """gpu_utilization returns None when nvidia-smi is not found."""
        mock_run.side_effect = FileNotFoundError("nvidia-smi not found")
        self.assertIsNone(self.monitor.gpu_utilization())

    @patch("deeploop.runtime.gpu_monitor.subprocess.run")
    def test_gpu_utilization_bad_returncode(self, mock_run):
        """gpu_utilization returns None when nvidia-smi returns non-zero."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        self.assertIsNone(self.monitor.gpu_utilization())

    @patch("deeploop.runtime.gpu_monitor.subprocess.run")
    def test_gpu_utilization_timeout(self, mock_run):
        """gpu_utilization returns None on subprocess timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="nvidia-smi", timeout=10
        )
        self.assertIsNone(self.monitor.gpu_utilization())

    # ------------------------------------------------------------------
    # tail_metrics
    # ------------------------------------------------------------------

    def test_tail_metrics_returns_content(self):
        """tail_metrics returns the last lines of the log file."""
        self.temp_log.write("line1\nline2\nline3\n")
        self.temp_log.flush()
        result = self.monitor.tail_metrics(lines=2)
        self.assertIn("line2", result)
        self.assertIn("line3", result)
        self.assertNotIn("line1", result)

    def test_tail_metrics_missing_file(self):
        """tail_metrics returns empty string when log file is missing."""
        self.log_path.unlink()
        self.assertEqual(self.monitor.tail_metrics(), "")

    def test_tail_metrics_fewer_lines_than_requested(self):
        """tail_metrics returns all lines when file is shorter than requested."""
        self.temp_log.write("only line\n")
        self.temp_log.flush()
        result = self.monitor.tail_metrics(lines=50)
        self.assertEqual(result.strip(), "only line")

    def test_tail_metrics_empty_file(self):
        """tail_metrics returns empty string for an empty log file."""
        # File exists but is empty
        self.temp_log.flush()
        result = self.monitor.tail_metrics()
        self.assertEqual(result, "")

    # ------------------------------------------------------------------
    # detect_completion
    # ------------------------------------------------------------------

    def test_detect_completion_matching_signals(self):
        """detect_completion returns True for known completion signals."""
        self.assertTrue(
            self.monitor.detect_completion("Training complete")
        )
        self.assertTrue(
            self.monitor.detect_completion("Evaluation complete")
        )
        self.assertTrue(
            self.monitor.detect_completion("Saved checkpoint")
        )
        self.assertTrue(
            self.monitor.detect_completion("Best metric: 0.95")
        )

    def test_detect_completion_non_matching(self):
        """detect_completion returns False for unrelated text."""
        self.assertFalse(
            self.monitor.detect_completion("Still training...")
        )
        self.assertFalse(
            self.monitor.detect_completion("loss: 0.234")
        )

    def test_detect_completion_empty(self):
        """detect_completion returns False for empty string."""
        self.assertFalse(self.monitor.detect_completion(""))
        self.assertFalse(self.monitor.detect_completion(None))  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # wait
    # ------------------------------------------------------------------

    @patch("os.kill")
    def test_wait_process_already_dead_returns_crashed(self, mock_kill):
        """wait returns 'crashed' when process is already dead."""
        mock_kill.side_effect = OSError("No such process")
        result = self.monitor.wait(timeout=1, check_interval=0.001)
        self.assertEqual(result, "crashed")

    @patch("os.kill")
    def test_wait_process_exits_after_some_checks(self, mock_kill):
        """wait returns 'crashed' when process exits mid-loop.

        mocks os.kill to succeed for 2 calls, then raise OSError.
        """
        # os.kill succeeds twice (process alive), then raises OSError (process dies)
        os_kill_values: list = [None, None]
        for _ in range(500):
            os_kill_values.append(OSError())
        mock_kill.side_effect = os_kill_values

        result = self.monitor.wait(timeout=5, check_interval=0.001)
        self.assertEqual(result, "crashed")
        self.assertGreaterEqual(mock_kill.call_count, 2)

    @patch("os.kill")
    def test_wait_completion_signal_found(self, mock_kill):
        """wait returns 'completed' when log contains a completion signal."""
        mock_kill.side_effect = OSError("No such process")
        self.temp_log.write("Training complete\n")
        self.temp_log.flush()
        result = self.monitor.wait(timeout=1, check_interval=0.001)
        self.assertEqual(result, "completed")

    @patch("os.kill")
    def test_wait_completion_during_liveness(self, mock_kill):
        """wait returns 'completed' even when process is still alive."""
        mock_kill.return_value = None  # process stays alive
        self.temp_log.write("Best metric: 0.99\n")
        self.temp_log.flush()
        result = self.monitor.wait(timeout=1, check_interval=0.001)
        self.assertEqual(result, "completed")

    # ------------------------------------------------------------------
    # GPU monitor: missing nvidia-smi (via gpu_utilization)
    # ------------------------------------------------------------------

    @patch("deeploop.runtime.gpu_monitor.subprocess.run")
    def test_gpu_utilization_oserror(self, mock_run):
        """gpu_utilization returns None when subprocess raises OSError."""
        mock_run.side_effect = OSError("Permission denied")
        self.assertIsNone(self.monitor.gpu_utilization())
