from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class DialogueTurn:
    """A single turn in a structured multi-agent dialogue."""

    role: str
    """Role identifier, e.g., "designer", "executor", "critic"."""

    content: str
    """Natural language content of the turn."""

    artifacts: list[str] = field(default_factory=list)
    """File paths produced during this turn."""

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    """ISO-8601 timestamp of when the turn was recorded."""


class AgentDialogue:
    """Structured multi-agent dialogue for research collaboration.

    Maintains an ordered list of :class:`DialogueTurn` entries and provides
    helpers for summarising the conversation and generating structured
    protocol messages compatible with the DeepLoop role system.
    """

    def __init__(self, roles: list[str]) -> None:
        self.turns: list[DialogueTurn] = []
        self.roles = roles

    def add_turn(
        self,
        role: str,
        content: str,
        artifacts: list[str] | None = None,
    ) -> DialogueTurn:
        """Append a new dialogue turn and return it.

        Parameters
        ----------
        role:
            The agent role producing this turn.  Should be one of the roles
            declared in *self.roles*.
        content:
            Natural language utterance for the turn.
        artifacts:
            Optional list of file paths produced during this turn.
        """
        turn = DialogueTurn(
            role=role,
            content=content,
            artifacts=artifacts or [],
        )
        self.turns.append(turn)
        return turn

    def last_turn(self) -> DialogueTurn | None:
        """Return the most recent turn, or *None* if the dialogue is empty."""
        return self.turns[-1] if self.turns else None

    def summary(self) -> str:
        """Compact dialogue summary for inclusion in LLM context.

        Returns a multi-line string with one line per turn, omitting
        artifact details.  Useful when the full turn history is too large
        to include verbatim in a prompt.
        """
        if not self.turns:
            return "[no dialogue turns]"
        lines: list[str] = []
        for idx, turn in enumerate(self.turns, start=1):
            artifacts_hint = (
                f" ({len(turn.artifacts)} artifact(s))" if turn.artifacts else ""
            )
            lines.append(f"{idx}. [{turn.role}]{artifacts_hint} {turn.content}")
        return "\n".join(lines)

    def protocol_message(self, role: str, message_type: str) -> str:
        """Generate a structured protocol message.

        Parameters
        ----------
        role:
            The agent role that will send (or has sent) this message.
        message_type:
            One of ``"PLAN"``, ``"CODE"``, ``"DIALOGUE"``, ``"REVIEW"``.

        Returns
        -------
        A formatted protocol string that can be included in an LLM prompt
        or written to a handoff file.
        """
        valid_types = {"PLAN", "CODE", "DIALOGUE", "REVIEW"}
        if message_type.upper() not in valid_types:
            msg = (
                f"Unknown message_type {message_type!r}; "
                f"expected one of {', '.join(sorted(valid_types))}"
            )
            raise ValueError(msg)

        last = self.last_turn()
        return (
            f"<protocol role={role!r} type={message_type.upper()}>\n"
            f"{last.content if last is not None else '[dialogue start]'}\n"
            f"</protocol>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the dialogue to a JSON-compatible dictionary."""
        return {
            "roles": list(self.roles),
            "turns": [
                {
                    "role": t.role,
                    "content": t.content,
                    "artifacts": list(t.artifacts),
                    "timestamp": t.timestamp,
                }
                for t in self.turns
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentDialogue:
        """Deserialize a dialogue from a dictionary produced by *to_dict*."""
        roles = list(data.get("roles", []))
        dialogue = cls(roles=roles)
        for turn_data in data.get("turns", []):
            dialogue.turns.append(
                DialogueTurn(
                    role=str(turn_data["role"]),
                    content=str(turn_data["content"]),
                    artifacts=[str(a) for a in turn_data.get("artifacts", [])],
                    timestamp=str(turn_data.get("timestamp", "")),
                )
            )
        return dialogue
