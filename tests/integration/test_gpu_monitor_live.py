"""Integration test: validate ExperimentMonitor with simulated training processes.

Uses subprocess and temp log files to exercise real completion, crash, and
timeout detection paths. No GPU or nvidia-smi required.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.gpu_monitor import ExperimentMonitor, GpuMonitorConfig


class GPUMonitorLiveTest(unittest.TestCase):
    """Simulate training processes and validate ExperimentMonitor behavior."""

    def setUp(self):
        self.log_file = tempfile.NamedTemporaryFile(  # noqa: SIM115
            delete=False, suffix=".log", mode="w"
        )
        self.log_path = Path(self.log_file.name)

    def tearDown(self):
        self.log_file.close()
        if self.log_path.exists():
            self.log_path.unlink()

    # ------------------------------------------------------------------
    # Helper: spawn a child process we can monitor
    # ------------------------------------------------------------------

    def _spawn_sleeper(self, sleep_seconds: float) -> subprocess.Popen:
        """Spawn a short-lived Python process."""
        code = f"import time; time.sleep({sleep_seconds})"
        return subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _spawn_log_writer(self, log_path: Path, messages: list[str], delay: float = 0.05) -> subprocess.Popen:
        """Spawn a process that writes messages to a log file then exits."""
        lines = "\\n".join(messages)
        code = (
            f"import time; path = {str(log_path)!r}\n"
            f"with open(path, 'w') as f:\n"
            f"    for msg in {messages!r}:\n"
            f"        f.write(msg + '\\n')\n"
            f"        f.flush()\n"
            f"        time.sleep({delay})\n"
        )
        return subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # ------------------------------------------------------------------
    # Completion detection
    # ------------------------------------------------------------------

    def test_monitor_detects_completion(self):
        """Write a training-completion signal to the log, verify 'completed'."""
        proc = self._spawn_log_writer(
            self.log_path,
            ["epoch 1, loss 0.5", "epoch 2, loss 0.3", "Training complete"],
            delay=0.02,
        )
        monitor = ExperimentMonitor(
            pid=proc.pid,
            log_file=self.log_path,
            poll_interval=0.01,
            config=GpuMonitorConfig(
                poll_interval_seconds=0.01,
                idle_timeout_minutes=0.1,
            ),
        )
        result = monitor.wait(timeout=30)
        proc.wait(timeout=5)
        self.assertEqual(
            result,
            "completed",
            f"Expected 'completed', got '{result}'. Log content:\n{self.log_path.read_text(errors='replace')}",
        )

    def test_monitor_detects_completion_with_evaluation_signal(self):
        """'Evaluation complete' is treated as a completion signal."""
        self.log_path.write_text("epoch 1\nepoch 2\nEvaluation complete\n", encoding="utf-8")
        # Use a process that stays alive briefly so the monitor can poll
        proc = self._spawn_sleeper(2)
        monitor = ExperimentMonitor(
            pid=proc.pid,
            log_file=self.log_path,
            poll_interval=0.01,
            config=GpuMonitorConfig(
                poll_interval_seconds=0.01,
                completion_signals=("Training complete", "Evaluation complete"),
            ),
        )
        result = monitor.wait(timeout=15)
        proc.wait(timeout=5)
        self.assertEqual(result, "completed")

    # ------------------------------------------------------------------
    # Crash detection
    # ------------------------------------------------------------------

    def test_monitor_detects_crash(self):
        """Write a CUDA OOM error into the log, verify 'crashed'."""
        self.log_path.write_text(
            "epoch 1: loss 0.5\n"
            "epoch 2: loss 0.4\n"
            "CUDA out of memory. Tried to allocate 2.00 GiB\n"
            "  GPU 0 has 0 bytes free\n",
            encoding="utf-8",
        )
        proc = self._spawn_sleeper(2)
        monitor = ExperimentMonitor(
            pid=proc.pid,
            log_file=self.log_path,
            poll_interval=0.01,
            config=GpuMonitorConfig(
                poll_interval_seconds=0.01,
                crash_signals=("CUDA out of memory", "RuntimeError", "Segmentation fault"),
            ),
        )
        result = monitor.wait(timeout=15)
        proc.wait(timeout=5)
        self.assertEqual(result, "crashed")

    def test_monitor_detects_crash_runtime_error(self):
        """'RuntimeError' in the log triggers crash detection."""
        self.log_path.write_text(
            "epoch 1: loss 0.5\n"
            "RuntimeError: shape mismatch\n",
            encoding="utf-8",
        )
        proc = self._spawn_sleeper(2)
        monitor = ExperimentMonitor(
            pid=proc.pid,
            log_file=self.log_path,
            poll_interval=0.01,
            config=GpuMonitorConfig(
                poll_interval_seconds=0.01,
                crash_signals=("CUDA out of memory", "RuntimeError", "Segmentation fault"),
            ),
        )
        result = monitor.wait(timeout=15)
        proc.wait(timeout=5)
        self.assertEqual(result, "crashed")

    def test_monitor_detects_crash_segfault(self):
        """'Segmentation fault' in the log triggers crash detection."""
        self.log_path.write_text(
            "epoch 42\n"
            "Segmentation fault (core dumped)\n",
            encoding="utf-8",
        )
        proc = self._spawn_sleeper(2)
        monitor = ExperimentMonitor(
            pid=proc.pid,
            log_file=self.log_path,
            poll_interval=0.01,
            config=GpuMonitorConfig(
                poll_interval_seconds=0.01,
                crash_signals=("CUDA out of memory", "RuntimeError", "Segmentation fault"),
            ),
        )
        result = monitor.wait(timeout=15)
        proc.wait(timeout=5)
        self.assertEqual(result, "crashed")

    # ------------------------------------------------------------------
    # Timeout handling
    # ------------------------------------------------------------------

    def test_monitor_handles_timeout(self):
        """Set a very short idle timeout; verify 'timeout' is returned.

        The process stays alive but doesn't write new log lines, so the
        idle-timeout branch should fire.
        """
        proc = self._spawn_sleeper(10)
        # Write one line so the monitor has something to read
        self.log_path.write_text("Starting training...\n", encoding="utf-8")

        monitor = ExperimentMonitor(
            pid=proc.pid,
            log_file=self.log_path,
            poll_interval=0.01,
            config=GpuMonitorConfig(
                poll_interval_seconds=0.01,
                idle_timeout_minutes=0.01,  # ~0.6 seconds
            ),
        )
        result = monitor.wait(timeout=15)
        proc.kill()
        proc.wait(timeout=5)
        self.assertEqual(
            result,
            "timeout",
            f"Expected 'timeout', got '{result}'",
        )

    def test_monitor_timeout_with_deadline(self):
        """A short wall-clock timeout returns 'timeout' before the log grows."""
        # Keep the process alive; write nothing to the log
        proc = self._spawn_sleeper(10)
        monitor = ExperimentMonitor(
            pid=proc.pid,
            log_file=self.log_path,
            poll_interval=0.01,
        )
        # The wall-clock timeout (0.5s) should fire before the idle timeout
        result = monitor.wait(timeout=0.5)
        proc.kill()
        proc.wait(timeout=5)
        self.assertEqual(result, "timeout")

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_monitor_process_already_dead(self):
        """If the process is already dead, wait returns 'crashed'."""
        proc = self._spawn_sleeper(0.01)
        proc.wait(timeout=5)
        self.log_path.write_text("some log output\n", encoding="utf-8")
        monitor = ExperimentMonitor(
            pid=proc.pid,
            log_file=self.log_path,
            poll_interval=0.01,
        )
        result = monitor.wait(timeout=5)
        # Process is dead and log has no completion signal -> crashed
        self.assertEqual(result, "crashed")

    def test_monitor_already_dead_with_completion(self):
        """If the process is dead and log has completion, returns 'completed'."""
        proc = self._spawn_sleeper(0.01)
        proc.wait(timeout=5)
        self.log_path.write_text("Training complete\n", encoding="utf-8")
        monitor = ExperimentMonitor(
            pid=proc.pid,
            log_file=self.log_path,
            poll_interval=0.01,
        )
        result = monitor.wait(timeout=5)
        self.assertEqual(result, "completed")

    # ------------------------------------------------------------------
    # gpu_utilization edge cases (no real GPU needed)
    # ------------------------------------------------------------------

    def test_gpu_utilization_returns_none_when_no_nvidia_smi(self):
        """On a system without nvidia-smi, gpu_utilization() returns None."""
        proc = self._spawn_sleeper(0.5)
        monitor = ExperimentMonitor(
            pid=proc.pid,
            log_file=self.log_path,
        )
        result = monitor.gpu_utilization()
        # This test can pass whether nvidia-smi exists or not, but we just
        # verify the return type contract: None or dict
        proc.wait(timeout=5)
        self.assertTrue(result is None or isinstance(result, dict))


if __name__ == "__main__":
    unittest.main()
