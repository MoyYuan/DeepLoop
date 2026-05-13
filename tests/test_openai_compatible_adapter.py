from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.openai_compatible_adapter import (
    _extract_choice_response_text,
    _extract_first_json_object,
    _normalize_api_base_url,
    _request_payload,
    build_openai_compatible_prompt_command,
    main,
)


class OpenAICompatibleAdapterTests(unittest.TestCase):
    def test_build_command_uses_module_entrypoint(self) -> None:
        command = build_openai_compatible_prompt_command(
            Path("/tmp/prompt.md"),
            result_json_path=Path("/tmp/result.json"),
            model="demo-model",
        )
        self.assertEqual(command[:3], [sys.executable, "-m", "deeploop.runtime.openai_compatible_adapter"])
        self.assertIn("--prompt-file", command)
        self.assertIn("--result-json-path", command)
        self.assertIn("demo-model", command)

    def test_normalize_api_base_url_accepts_existing_v1(self) -> None:
        self.assertEqual(_normalize_api_base_url("http://localhost:8080/v1"), "http://localhost:8080/v1")
        self.assertEqual(_normalize_api_base_url("http://localhost:8080"), "http://localhost:8080/v1")

    def test_extract_first_json_object_strips_qwen_wrappers(self) -> None:
        payload = _extract_first_json_object(
            "<think>hidden reasoning</think>\n```json\n{\"status\": \"completed\", \"summary\": \"done\"}\n```"
        )
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["summary"], "done")

    def test_extract_choice_response_text_accepts_output_text_blocks(self) -> None:
        text = _extract_choice_response_text(
            {
                "message": {
                    "content": [
                        {
                            "type": "output_text",
                            "text": "{\"status\": \"completed\", \"summary\": \"done\"}",
                        }
                    ]
                }
            }
        )
        self.assertEqual(text, "{\"status\": \"completed\", \"summary\": \"done\"}")

    def test_extract_choice_response_text_falls_back_to_reasoning_content(self) -> None:
        text = _extract_choice_response_text(
            {
                "message": {
                    "content": None,
                    "reasoning_content": "{\"status\": \"completed\", \"summary\": \"done\"}",
                }
            }
        )
        self.assertEqual(text, "{\"status\": \"completed\", \"summary\": \"done\"}")

    def test_request_payload_enables_json_object_mode_for_result_flows(self) -> None:
        payload = json.loads(_request_payload("prompt", model="demo-model", json_only=True).decode("utf-8"))
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["messages"], [{"role": "user", "content": "prompt"}])

    @patch("deeploop.runtime.openai_compatible_adapter._invoke_openai_compatible")
    def test_main_writes_result_json_from_response(self, mock_invoke) -> None:
        mock_invoke.return_value = "{\"status\": \"completed\", \"summary\": \"done\"}"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_file = root / "prompt.md"
            result_json_path = root / "result.json"
            prompt_file.write_text("prompt", encoding="utf-8")

            exit_code = main(
                [
                    "--prompt-file",
                    str(prompt_file),
                    "--result-json-path",
                    str(result_json_path),
                    "--model",
                    "demo-model",
                ]
            )

            payload = json.loads(result_json_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["summary"], "done")
        self.assertEqual(mock_invoke.call_args.kwargs["json_only"], True)
