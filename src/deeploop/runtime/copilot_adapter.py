from __future__ import annotations

from pathlib import Path
from typing import Sequence


def build_copilot_prompt_command(
    prompt_text: str,
    *,
    add_dirs: Sequence[Path] = (),
    model: str | None = None,
    allow_all: bool = True,
    no_ask_user: bool = True,
    output_format: str = "text",
) -> list[str]:
    command = ["copilot", "-p", prompt_text, "--output-format", output_format]
    if allow_all:
        command.append("--allow-all")
    if no_ask_user:
        command.append("--no-ask-user")
    if model:
        command.extend(["--model", model])
    seen: set[str] = set()
    for path in add_dirs:
        resolved = str(path.expanduser().resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        command.extend(["--add-dir", resolved])
    return command
