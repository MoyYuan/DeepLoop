from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from deeploop.runtime.openai_compatible_adapter import _extract_first_json_object


def build_anthropic_prompt_command(
    prompt_file: Path,
    *,
    result_json_path: Path | None = None,
    model: str | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "deeploop.runtime.anthropic_adapter",
        "--prompt-file",
        str(prompt_file.expanduser().resolve()),
    ]
    if result_json_path is not None:
        command.extend(["--result-json-path", str(result_json_path.expanduser().resolve())])
    if model:
        command.extend(["--model", model])
    return command


def _messages_endpoint() -> str:
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").strip().rstrip("/")
    if not base.startswith("https://"):
        base = f"https://{base}"
    return f"{base}/v1/messages"


def _required_api_key() -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY must be set for anthropic-api provider use")
    return api_key


def _resolved_model(explicit_model: str | None) -> str:
    model = (explicit_model or os.environ.get("ANTHROPIC_MODEL") or "").strip()
    if not model:
        raise ValueError("Provide --model or set ANTHROPIC_MODEL for anthropic-api provider use")
    return model


def _request_payload(prompt_text: str, *, model: str, json_only: bool = False) -> bytes:
    system = (
        "You are a helpful assistant. Reply with valid JSON only, no other text."
        if json_only
        else None
    )
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt_text}],
    }
    if system is not None:
        payload["system"] = system
    return json.dumps(payload).encode("utf-8")


def _extract_response_text(response_payload: dict[str, Any]) -> str:
    content = response_payload.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            text = first.get("text")
            if isinstance(text, str) and text.strip():
                return text
    raise RuntimeError("Anthropic response did not include textual content")


def _invoke_anthropic(prompt_text: str, *, model: str, json_only: bool = False) -> str:
    request = Request(
        _messages_endpoint(),
        data=_request_payload(prompt_text, model=model, json_only=json_only),
        headers={
            "x-api-key": _required_api_key(),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic request failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Anthropic request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Anthropic endpoint returned malformed JSON") from exc
    return _extract_response_text(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--result-json-path")
    parser.add_argument("--model")
    args = parser.parse_args(argv)

    prompt_path = Path(args.prompt_file).expanduser().resolve()
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    prompt_text = prompt_path.read_text(encoding="utf-8")
    model = _resolved_model(args.model)
    json_only = args.result_json_path is not None

    response_text = _invoke_anthropic(prompt_text, model=model, json_only=json_only)

    if json_only:
        parsed = _extract_first_json_object(response_text)
        result_path = Path(args.result_json_path).expanduser().resolve()
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")

    print(response_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
