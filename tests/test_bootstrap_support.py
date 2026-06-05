from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.cli.bootstrap_support import _provider_ready, check_provider_readiness


class BootstrapSupportTests(unittest.TestCase):
    def test_check_provider_readiness_reports_missing_openai_compatible_api_key(self) -> None:
        report = check_provider_readiness(
            provider_family="openai-compatible-api",
            resume_command="deeploop run --until-complete",
        )

        self.assertEqual(report["status"], "action-required")
        self.assertEqual(report["provider_family"], "openai-compatible-api")
        self.assertIn("OPENAI_API_KEY", report["next_step"])
        self.assertEqual(report["resume_command"], "deeploop run --until-complete")

    def test_check_provider_readiness_reports_missing_openai_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            report = check_provider_readiness(provider_family="openai-compatible-api")

        self.assertEqual(report["status"], "action-required")
        self.assertEqual(report["provider_family"], "openai-compatible-api")
        self.assertTrue(any(check["name"] == "OPENAI_API_KEY" for check in report["failed_checks"]))
        self.assertIn("OPENAI_API_KEY", report["next_step"])

    @patch("deeploop.cli.bootstrap_support.check_provider_readiness")
    def test_provider_ready_cli_returns_nonzero_for_action_required(self, mock_check_provider_readiness) -> None:
        mock_check_provider_readiness.return_value = {
            "status": "action-required",
            "provider_family": "copilot-cli",
            "display_name": "Copilot CLI",
            "runtime_integration": "implemented",
            "scope_boundary": "setup only",
            "setup_doc": "docs/reference/provider-setup.md",
            "selection_doc": "docs/reference/provider-selection.md",
            "summary": "missing setup",
            "next_step": "install Copilot CLI",
            "resume_command": "deeploop run --until-complete",
            "recheck_command": "deeploop provider-ready --provider-family copilot-cli",
            "failed_checks": [],
            "manual_notes": [],
        }

        with redirect_stdout(io.StringIO()):
            result = _provider_ready(
                argparse.Namespace(
                    provider_family="copilot-cli",
                    selection_profile=None,
                    resume_command="deeploop run --until-complete",
                    json=True,
                )
            )

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
