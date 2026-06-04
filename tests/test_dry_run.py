"""Tests for dry_run_validate."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import yaml

from deeploop.runtime.stage_kernels import dry_run_validate


class TestDryRunValidate(unittest.TestCase):
    """Test dry_run_validate for experiment config validation."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_config(self, config: dict, filename: str = "config.yaml") -> Path:
        path = self.temp_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)
        return path

    def test_valid_config_returns_true(self):
        """A valid config with a known stage_id and minimal fields returns True."""
        config = {
            "stage_id": "baseline-evaluation",
            "model": {
                "family": "test-family",
                "identifier": "test-model",
            },
        }
        config_path = self._write_config(config)

        # We mock subprocess.run to simulate success
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["python", "-c", "..."],
                returncode=0,
                stdout="OK: status=completed",
                stderr="",
            )
            result = dry_run_validate(config_path)
            self.assertTrue(result)

    def test_invalid_yaml_returns_false(self):
        """A config file with invalid YAML syntax returns False."""
        config_path = self.temp_dir / "bad.yaml"
        config_path.write_text("{ invalid: yaml: : unbalanced", encoding="utf-8")

        with patch("subprocess.run") as mock_run:
            # The subprocess itself will try yaml.safe_load and fail
            # We simulate a non-zero returncode
            mock_run.return_value = subprocess.CompletedProcess(
                args=["python", "-c", "..."],
                returncode=1,
                stdout="",
                stderr="ERROR: config is not a mapping",
            )
            result = dry_run_validate(config_path)
            self.assertFalse(result)

    def test_missing_stage_id_returns_false(self):
        """A config without a stage_id returns False."""
        config = {
            "model": {
                "family": "test-family",
                "identifier": "test-model",
            }
        }
        config_path = self._write_config(config)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["python", "-c", "..."],
                returncode=1,
                stdout="",
                stderr="ERROR: no stage_id in config",
            )
            result = dry_run_validate(config_path)
            self.assertFalse(result)

    def test_subprocess_nonzero_returncode_returns_false(self):
        """When subprocess.run returns non-zero exit code, dry_run_validate returns False."""
        config = {
            "stage_id": "baseline-evaluation",
            "model": {
                "family": "test-family",
                "identifier": "test-model",
            },
        }
        config_path = self._write_config(config)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["python", "-c", "..."],
                returncode=1,
                stdout="",
                stderr="Some error occurred",
            )
            result = dry_run_validate(config_path)
            mock_run.assert_called_once()
            self.assertFalse(result)

    def test_subprocess_timeout_expired_returns_false(self):
        """When subprocess.run raises TimeoutExpired, dry_run_validate returns False."""
        config = {
            "stage_id": "baseline-evaluation",
            "model": {
                "family": "test-family",
                "identifier": "test-model",
            },
        }
        config_path = self._write_config(config)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["python", "-c", "..."],
                timeout=60,
            )
            result = dry_run_validate(config_path)
            self.assertFalse(result)

    def test_subprocess_timeout_expired_with_output_returns_false(self):
        """TimeoutExpired with partial output still returns False."""
        config = {
            "stage_id": "baseline-evaluation",
            "model": {
                "family": "test-family",
                "identifier": "test-model",
            },
        }
        config_path = self._write_config(config)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["python", "-c", "..."],
                timeout=60,
                output="partial stdout",
                stderr="partial stderr",
            )
            result = dry_run_validate(config_path)
            self.assertFalse(result)

    def test_config_with_adapter_field(self):
        """A config with an adapter_spec field is still valid with mock."""
        config = {
            "stage_id": "baseline-evaluation",
            "adapter_spec": "demo",
            "model": {
                "family": "test-family",
                "identifier": "test-model",
            },
        }
        config_path = self._write_config(config)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["python", "-c", "..."],
                returncode=0,
                stdout="OK: status=completed",
                stderr="",
            )
            result = dry_run_validate(config_path)
            self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
