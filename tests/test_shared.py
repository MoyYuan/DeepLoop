"""Tests for deeploop.core.shared utilities."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.shared import (
    build_command,
    dedupe_strings,
    is_relative_to,
    normalize_list_like,
    normalize_strings,
    slugify,
)


class SharedTests(unittest.TestCase):
    """Test all functions in deeploop.core.shared."""

    # ------------------------------------------------------------------
    # slugify
    # ------------------------------------------------------------------

    def test_slugify_basic(self):
        """slugify converts to lowercase and joins with hyphens."""
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_slugify_empty(self):
        """slugify returns empty string for empty input."""
        self.assertEqual(slugify(""), "")

    def test_slugify_special_chars_stripped(self):
        """slugify strips non-alphanumeric characters."""
        self.assertEqual(slugify("Hello World!@#$"), "hello-world")
        self.assertEqual(slugify("hello---world"), "hello-world")
        self.assertEqual(slugify("@hello world@"), "hello-world")
        self.assertEqual(slugify("__hello__world__"), "hello-world")

    def test_slugify_with_numbers(self):
        """slugify preserves digits joined into tokens."""
        self.assertEqual(slugify("Test 123 abc"), "test-123-abc")
        self.assertEqual(slugify("test123abc"), "test123abc")

    # ------------------------------------------------------------------
    # is_relative_to
    # ------------------------------------------------------------------

    def test_is_relative_to_true(self):
        """is_relative_to returns True when path is a descendant."""
        self.assertTrue(is_relative_to(Path("/tmp/foo/bar"), Path("/tmp")))
        self.assertTrue(is_relative_to(Path("/tmp/foo"), Path("/tmp")))

    def test_is_relative_to_false(self):
        """is_relative_to returns False when path is not a descendant."""
        self.assertFalse(is_relative_to(Path("/tmp/foo/bar"), Path("/var")))
        self.assertFalse(is_relative_to(Path("/tmp"), Path("/tmp/foo")))

    def test_is_relative_to_equal_paths(self):
        """is_relative_to returns True for equal paths."""
        self.assertTrue(is_relative_to(Path("/tmp"), Path("/tmp")))

    # ------------------------------------------------------------------
    # build_command
    # ------------------------------------------------------------------

    def test_build_command_no_env(self):
        """build_command returns command as-is when env_name is None."""
        cmd = ["python", "script.py"]
        result = build_command(cmd, env_name=None)
        self.assertEqual(result, ["python", "script.py"])
        self.assertIsNot(result, cmd)

    def test_build_command_with_env(self):
        """build_command wraps command with conda run."""
        self.assertEqual(
            build_command(["python", "script.py"], env_name="test"),
            ["conda", "run", "-n", "test", "python", "script.py"],
        )

    # ------------------------------------------------------------------
    # dedupe_strings
    # ------------------------------------------------------------------

    def test_dedupe_strings_basic(self):
        """dedupe_strings removes duplicates preserving order."""
        self.assertEqual(dedupe_strings(["a", "b", "a"]), ["a", "b"])

    def test_dedupe_strings_empty(self):
        """dedupe_strings handles empty list."""
        self.assertEqual(dedupe_strings([]), [])

    def test_dedupe_strings_preserves_order(self):
        """dedupe_strings keeps first occurrence order."""
        self.assertEqual(
            dedupe_strings(["b", "a", "b", "c", "a"]),
            ["b", "a", "c"],
        )

    # ------------------------------------------------------------------
    # normalize_strings
    # ------------------------------------------------------------------

    def test_normalize_strings_none(self):
        """normalize_strings(None) returns []."""
        self.assertEqual(normalize_strings(None), [])

    def test_normalize_strings_str(self):
        """normalize_strings wraps a single string."""
        self.assertEqual(normalize_strings("hello"), ["hello"])

    def test_normalize_strings_list(self):
        """normalize_strings deduplicates a list of strings."""
        self.assertEqual(normalize_strings(["a", "b", "a"]), ["a", "b"])

    def test_normalize_strings_path(self):
        """normalize_strings converts a Path to its string form."""
        self.assertEqual(normalize_strings(Path("/tmp/test")), ["/tmp/test"])

    def test_normalize_strings_tuple(self):
        """normalize_strings handles tuples."""
        self.assertEqual(normalize_strings(("a", "b")), ["a", "b"])

    def test_normalize_strings_empty_string(self):
        """normalize_strings skips empty strings."""
        self.assertEqual(normalize_strings(""), [])

    # ------------------------------------------------------------------
    # normalize_list_like
    # ------------------------------------------------------------------

    def test_normalize_list_like_none(self):
        """normalize_list_like(None) returns []."""
        self.assertEqual(normalize_list_like(None), [])

    def test_normalize_list_like_str(self):
        """normalize_list_like wraps a string."""
        self.assertEqual(normalize_list_like("str"), ["str"])

    def test_normalize_list_like_list(self):
        """normalize_list_like converts list items to strings."""
        self.assertEqual(normalize_list_like(["a", "b"]), ["a", "b"])
