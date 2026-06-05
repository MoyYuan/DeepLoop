"""Two-tier fixed-size memory for research missions.

Keeps LLM context under a fixed character budget using a frozen
Tier 1 (project brief) and a rolling, auto-compressing Tier 2
(memory log).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class _CompressedBlock:
    """Represents a group of results collapsed into a summary line."""

    count: int = 0


class BoundedMemory:
    """Two-tier fixed-size memory for research missions.

    Tier 1 (FROZEN):
        PROJECT_BRIEF -- human-written, never changes, max 3000 chars.
    Tier 2 (ROLLING):
        MEMORY_LOG -- auto-compressed, max 2000 chars, last 15 decisions.
    Total budget: ~5000 chars (~1500 tokens).
    """

    def __init__(
        self,
        project_brief: str,
        max_brief_chars: int = 3000,
        max_log_chars: int = 2000,
        max_decisions: int = 15,
    ) -> None:
        self.project_brief = project_brief[:max_brief_chars]
        self._max_brief_chars = max_brief_chars
        self._max_log_chars = max_log_chars
        self._max_decisions = max_decisions
        self._key_results: list[str] = []
        self._recent_decisions: list[str] = []
        self._compressed_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_result(self, summary: str) -> None:
        """Append a key result, auto-compressing the oldest when the
        rendered memory log would exceed ``max_log_chars``.

        If adding *summary* pushes the Tier 2 block over budget, the
        oldest uncompressed results are collapsed into a single summary
        line ``"(N earlier results summarized)"``.
        """
        self._key_results.append(summary)

        # Check whether we need to compress.
        estimated = self._render_log(
            compressed_count=self._compressed_count,
            key_results=self._key_results,
            recent_decisions=self._recent_decisions,
            max_decisions=self._max_decisions,
        )
        if len(estimated) > self._max_log_chars:
            self._compress()

    def record_decision(self, decision: str) -> None:
        """Record a recent decision, rolling off the oldest when the
        maximum number of decisions is exceeded."""
        self._recent_decisions.append(decision)
        while len(self._recent_decisions) > self._max_decisions:
            self._recent_decisions.pop(0)

    def memory_log(self) -> str:
        """Render Tier 2 memory as a compact markdown string, guaranteed
        to be no longer than ``max_log_chars`` characters.

        The rendered block has the form::

            ### Key Results
            - result 1
            - result 2
            ...

            ### Recent Decisions
            - decision 1
            - decision 2
            ...
        """
        rendered = self._render_log(
            compressed_count=self._compressed_count,
            key_results=self._key_results,
            recent_decisions=self._recent_decisions,
            max_decisions=self._max_decisions,
        )
        if len(rendered) <= self._max_log_chars:
            return rendered
        return rendered[: self._max_log_chars - 3] + "..."

    def context_block(self) -> str:
        """Return the full prompt context: Tier 1 (project brief) followed
        by Tier 2 (memory log).

        The result is guaranteed to stay under
        ``max_brief_chars + max_log_chars + 200`` characters.
        """
        brief = self.project_brief
        if len(brief) > self._max_brief_chars:
            brief = brief[: self._max_brief_chars - 3] + "..."

        log = self.memory_log()

        parts = [
            "## Project Brief",
            brief,
            "",
            "## Memory Log",
            log,
        ]
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compress(self) -> None:
        """Compress oldest key results into a single summary line."""
        if len(self._key_results) <= 1:
            return

        compress_count = max(1, len(self._key_results) // 2)
        self._key_results = self._key_results[compress_count:]
        self._compressed_count += compress_count

        # If still over budget, keep compressing recursively.
        estimated = self._render_log(
            compressed_count=self._compressed_count,
            key_results=self._key_results,
            recent_decisions=self._recent_decisions,
            max_decisions=self._max_decisions,
        )
        if len(estimated) > self._max_log_chars and len(self._key_results) > 1:
            self._compress()

    @staticmethod
    def _render_log(
        compressed_count: int,
        key_results: Sequence[str],
        recent_decisions: Sequence[str],
        max_decisions: int,
    ) -> str:
        """Build the raw Tier 2 markdown string without length capping."""
        lines: list[str] = []

        lines.append("### Key Results")
        if compressed_count > 0:
            lines.append(f"- ({compressed_count} earlier results summarized)")
        for result in key_results:
            lines.append(f"- {result}")

        decisions = list(recent_decisions)
        if len(decisions) > max_decisions:
            decisions = decisions[-max_decisions:]

        if decisions:
            lines.append("")
            lines.append("### Recent Decisions")
            for decision in decisions:
                lines.append(f"- {decision}")

        return "\n".join(lines)


__all__ = [
    "BoundedMemory",
]
