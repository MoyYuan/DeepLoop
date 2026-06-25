from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_THINK_BLOCK_RE = re.compile(r"<think>\s*(.*?)\s*</think>", re.IGNORECASE | re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def build_openai_compatible_prompt_command(
    prompt_file: Path,
    *,
    result_json_path: Path | None = None,
    model: str | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "deeploop.runtime.openai_compatible_adapter",
        "--prompt-file",
        str(prompt_file.expanduser().resolve()),
    ]
    if result_json_path is not None:
        command.extend(["--result-json-path", str(result_json_path.expanduser().resolve())])
    if model:
        command.extend(["--model", model])
    return command


def _normalize_api_base_url(base_url: str) -> str:
    trimmed = base_url.strip().rstrip("/")
    if not trimmed:
        raise ValueError("OPENAI_BASE_URL must not be empty when set")
    if trimmed.endswith("/chat/completions"):
        return trimmed[: -len("/chat/completions")]
    if trimmed.endswith("/v1"):
        return trimmed
    return f"{trimmed}/v1"


def _strip_wrappers(text: str) -> str:
    stripped = _THINK_BLOCK_RE.sub("", text)
    fenced = _FENCE_RE.search(stripped)
    return fenced.group(1).strip() if fenced else stripped.strip()


def _extract_first_json_object(text: str) -> dict[str, Any]:
    candidate = _strip_wrappers(text)
    decoder = json.JSONDecoder()
    for index, char in enumerate(candidate):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("provider response did not contain a JSON object")


def _collect_text_segments(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        segments: list[str] = []
        for item in value:
            segments.extend(_collect_text_segments(item))
        return segments
    if isinstance(value, dict):
        item_type = str(value.get("type") or "").strip().lower()
        if item_type and item_type not in {
            "text",
            "output_text",
            "input_text",
            "reasoning",
            "reasoning_text",
            "message",
            "content",
        }:
            return []
        segments: list[str] = []
        for key in ("text", "content", "value", "output_text", "reasoning_content", "reasoning"):
            if key in value:
                segments.extend(_collect_text_segments(value.get(key)))
        return segments
    return []


def _extract_choice_response_text(first_choice: dict[str, Any]) -> str:
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("OpenAI-compatible response choice did not include a message object")
    for candidate in (
        message.get("content"),
        message.get("output_text"),
        first_choice.get("text"),
        message.get("reasoning_content"),
        message.get("reasoning"),
    ):
        segments = _collect_text_segments(candidate)
        combined = "\n".join(segment for segment in segments if segment)
        if combined:
            return combined
    raise RuntimeError("OpenAI-compatible response did not include textual assistant content")


def _chat_completion_endpoint() -> str:
    base_url = _normalize_api_base_url(os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    return f"{base_url}/chat/completions"


def _required_api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY must be set for openai-compatible-api provider use")
    return api_key


def _resolved_model(explicit_model: str | None) -> str:
    model = (explicit_model or os.environ.get("OPENAI_MODEL") or "").strip()
    if not model:
        raise ValueError("Provide --model or set OPENAI_MODEL for openai-compatible-api provider use")
    return model


def _is_local_openai_base_url(base_url: str | None) -> bool:
    raw_base_url = str(base_url or "").strip()
    if not raw_base_url:
        return False
    try:
        hostname = urlparse(_normalize_api_base_url(raw_base_url)).hostname
    except ValueError:
        return False
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _should_disable_qwen_thinking(*, model: str, json_only: bool) -> bool:
    return bool(
        json_only
        and "qwen" in model.lower()
        and _is_local_openai_base_url(os.environ.get("OPENAI_BASE_URL"))
    )


def _request_payload(prompt_text: str, *, model: str, json_only: bool = False) -> bytes:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0,
    }
    if json_only:
        payload["response_format"] = {"type": "json_object"}
    if _should_disable_qwen_thinking(model=model, json_only=json_only):
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    return json.dumps(payload).encode("utf-8")


def _invoke_openai_compatible(prompt_text: str, *, model: str, json_only: bool = False) -> tuple[str, dict[str, int]]:
    request = Request(
        _chat_completion_endpoint(),
        data=_request_payload(prompt_text, model=model, json_only=json_only),
        headers={
            "Authorization": f"Bearer {_required_api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(
                {"OpenAI-Organization": org_id}
                if (org_id := os.environ.get("OPENAI_ORG_ID", "").strip())
                else {}
            ),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI-compatible request failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"OpenAI-compatible request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI-compatible endpoint returned malformed JSON") from exc
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenAI-compatible response did not include choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RuntimeError("OpenAI-compatible response choice was not an object")
    response_text = _extract_choice_response_text(first_choice)
    usage = payload.get("usage")
    if isinstance(usage, dict):
        tokens = {
            "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "output_tokens": int(usage.get("completion_tokens", 0) or 0),
        }
    else:
        tokens = {"input_tokens": 0, "output_tokens": 0}
    return response_text, tokens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--result-json-path")
    parser.add_argument("--model")
    args = parser.parse_args(argv)

    prompt_file = Path(args.prompt_file).expanduser().resolve()
    prompt_text = prompt_file.read_text(encoding="utf-8")
    response_text, tokens = _invoke_openai_compatible(
        prompt_text,
        model=_resolved_model(args.model),
        json_only=bool(args.result_json_path),
    )
    print(response_text, end="" if response_text.endswith("\n") else "\n")
    if args.result_json_path:
        payload = _extract_first_json_object(response_text)
        payload["tokens"] = tokens
        result_json_path = Path(args.result_json_path).expanduser().resolve()
        result_json_path.parent.mkdir(parents=True, exist_ok=True)
        result_json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
