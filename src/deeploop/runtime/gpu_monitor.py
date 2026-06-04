"""Monitor GPU training jobs using only OS primitives -- no LLM calls.

Provides ``ExperimentMonitor``, which polls a process for liveness (``kill -0``),
reads GPU statistics via ``nvidia-smi``, and tails training logs to detect
completion or crash signals without ever invoking an LLM API.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass
class GpuMonitorConfig:
    """Configuration for an ``ExperimentMonitor`` instance.

    Parameters
    ----------
    poll_interval_seconds:
        Seconds between liveness and log-tail checks during ``wait()``.
    completion_signals:
        Substrings in log output that indicate successful completion.
    crash_signals:
        Substrings in log output that indicate a crash.
    idle_timeout_minutes:
        Maximum minutes the process may appear alive without producing
        new log output before ``wait()`` returns ``"timeout"``.
    """

    poll_interval_seconds: float = 30.0
    completion_signals: tuple[str, ...] = (
        "Training complete",
        "Evaluation complete",
        "Saved checkpoint",
        "Best metric:",
    )
    crash_signals: tuple[str, ...] = (
        "CUDA out of memory",
        "RuntimeError",
        "Segmentation fault",
    )
    idle_timeout_minutes: float = 1440.0


class ExperimentMonitor:
    """Monitor a GPU training process using only OS primitives -- no LLM calls.

    Thread-safe: the ``wait()`` polling loop holds a lock around state
    mutations so that concurrent access to ``tail_metrics()`` or
    ``gpu_utilization()`` is safe.
    """

    def __init__(
        self,
        pid: int,
        log_file: Path,
        poll_interval: float = 30.0,
        config: GpuMonitorConfig | None = None,
    ) -> None:
        self._pid = pid
        self._log_file = log_file
        self._poll_interval = poll_interval
        self._config = config or GpuMonitorConfig(poll_interval_seconds=poll_interval)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        """Check if the monitored process is alive via ``kill -0 $PID``.

        Returns ``True`` if the process exists and is owned by the current
        user; ``False`` if the process has exited or does not exist.
        """
        try:
            os.kill(self._pid, 0)
        except OSError:
            return False
        return True

    def gpu_utilization(self) -> dict | None:
        """Query GPU utilization and memory usage via ``nvidia-smi``.

        Returns a dict with keys ``"utilization.gpu"``, ``"memory.used"``
        for each GPU found, or ``None`` if ``nvidia-smi`` is unavailable or
        returns no output.
        """
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

        if result.returncode != 0 or not result.stdout.strip():
            return None

        devices: list[dict[str, str]] = []
        for line in result.stdout.strip().splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 2:
                devices.append(
                    {
                        "utilization.gpu": parts[0],
                        "memory.used": parts[1],
                    }
                )
        return {"devices": devices} if devices else None

    def tail_metrics(self, lines: int = 50) -> str:
        """Return the last *lines* of the training log file.

        If the log file does not exist or cannot be read, an empty string
        is returned.
        """
        try:
            if not self._log_file.exists():
                return ""
            content = self._log_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

        all_lines = content.splitlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return "\n".join(tail)

    def wait(
        self,
        timeout: float | None = None,
        check_interval: float | None = None,
    ) -> str:
        """Block until the monitored process exits, a timeout fires, or a
        crash signal is detected.

        Parameters
        ----------
        timeout:
            Maximum seconds to wait.  ``None`` means wait indefinitely.
        check_interval:
            Seconds between polling iterations.  Falls back to
            ``self._poll_interval``.

        Returns
        -------
        str
            ``"completed"`` if a completion signal was found in the log,
            ``"crashed"`` if a crash signal was found,
            ``"timeout"`` if the deadline elapsed without completion.
        """
        interval = check_interval if check_interval is not None else self._poll_interval
        deadline: float | None = (time.monotonic() + timeout) if timeout is not None else None
        max_idle_seconds = self._config.idle_timeout_minutes * 60.0

        last_log_size = _log_file_size(self._log_file)

        while True:
            if deadline is not None and time.monotonic() >= deadline:
                return "timeout"

            # Check liveness
            if not self.is_running():
                # Process died -- check the log for signals
                with self._lock:
                    tail = self.tail_metrics(100)
                if self.detect_completion(tail):
                    return "completed"
                return "crashed"

            # Process is still alive -- tail the log
            with self._lock:
                tail = self.tail_metrics(100)

            if self.detect_completion(tail):
                return "completed"

            if _has_crash_signal(tail, self._config.crash_signals):
                return "crashed"

            # Detect idle timeouts when the log stops growing
            current_size = _log_file_size(self._log_file)
            if current_size <= last_log_size:
                elapsed_idle = 0.0
                idle_start = time.monotonic()
                while self.is_running():
                    if time.monotonic() - idle_start >= max_idle_seconds:
                        return "timeout"
                    if deadline is not None and time.monotonic() >= deadline:
                        return "timeout"
                    time.sleep(interval)
                    new_size = _log_file_size(self._log_file)
                    if new_size > current_size:
                        current_size = new_size
                        last_log_size = current_size
                        break
            else:
                last_log_size = current_size

            time.sleep(interval)

    def detect_completion(self, log_tail: str) -> bool:
        """Check *log_tail* for known training-completion signals.

        Returns ``True`` if any signal from ``self._config.completion_signals``
        appears in the text as a substring.
        """
        if not log_tail:
            return False
        for signal in self._config.completion_signals:
            if signal in log_tail:
                return True
        return False


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _log_file_size(path: Path) -> int:
    """Return the size (bytes) of *path*, or 0 on error."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _has_crash_signal(log_tail: str, crash_signals: Sequence[str]) -> bool:
    """Return ``True`` if any *crash_signals* appear in *log_tail*."""
    if not log_tail:
        return False
    for signal in crash_signals:
        if signal in log_tail:
            return True
    return False


__all__ = [
    "ExperimentMonitor",
    "GpuMonitorConfig",
]
