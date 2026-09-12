"""Unit tests for the shared PathFilter include/exclude logic."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "ha_config2git" / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from pathfilter import PathFilter, normalize_pattern  # noqa: E402


class SimpleStarTests(unittest.TestCase):
    def test_root_yaml(self):
        f = PathFilter(include_patterns=["*.yaml"])
        self.assertTrue(f.matches("automations.yaml"))
        self.assertFalse(f.matches("dir/automations.yaml"))
        self.assertFalse(f.matches("automations.txt"))


class DoubleStarTests(unittest.TestCase):
    def test_recursive(self):
        f = PathFilter(include_patterns=["custom_components/**"])
        self.assertTrue(f.matches("custom_components"))
        self.assertTrue(f.matches("custom_components/foo/__init__.py"))
        self.assertTrue(f.matches("custom_components/a/b/c/__init__.py"))
        self.assertFalse(f.matches("other/foo.py"))


class ExcludeWinsTests(unittest.TestCase):
    def test_exclude_wins(self):
        f = PathFilter(
            include_patterns=["*.yaml", "custom_components/**"],
            exclude_patterns=["secrets.yaml", "*.db", ".storage/**"],
        )
        self.assertFalse(f.matches("secrets.yaml"))
        self.assertFalse(f.matches("home-assistant_v2.db"))
        self.assertFalse(f.matches(".storage/core.config_entries"))
        self.assertTrue(f.matches("configuration.yaml"))
        self.assertTrue(f.matches("custom_components/foo/__init__.py"))


class DirectoryPatternTests(unittest.TestCase):
    def test_bare_directory_name(self):
        f = PathFilter(include_patterns=["scripts"])
        self.assertTrue(f.matches("scripts"))
        self.assertTrue(f.matches("scripts/foo.yaml"))
        self.assertTrue(f.matches("scripts/a/b/c.yaml"))
        self.assertFalse(f.matches("script2/foo.yaml"))

    def test_directory_with_double_star(self):
        f = PathFilter(include_patterns=["scripts/**"])
        self.assertTrue(f.matches("scripts/foo.yaml"))
        self.assertTrue(f.matches("scripts/a/b/c.yaml"))


class FileVsDirectoryTests(unittest.TestCase):
    def test_single_star(self):
        f = PathFilter(include_patterns=["*"])
        self.assertTrue(f.matches("configuration.yaml"))
        self.assertTrue(f.matches("some_dir/file.yaml"))


class NonMatchingTests(unittest.TestCase):
    def test_no_match(self):
        f = PathFilter(include_patterns=["*.yaml", "custom_components/**"])
        self.assertFalse(f.matches("configuration.txt"))

    def test_empty_include_matches_nothing(self):
        f = PathFilter(include_patterns=[])
        self.assertFalse(f.matches("anything.yaml"))


class LeadingSlashAndDotTests(unittest.TestCase):
    def test_path_normalization(self):
        f = PathFilter(include_patterns=["*.yaml"])
        self.assertTrue(f.matches("./automations.yaml"))
        self.assertTrue(f.matches("/automations.yaml"))
        self.assertTrue(f.matches("automations.yaml/"))


class DeduplicationTests(unittest.TestCase):
    def test_duplicate_patterns(self):
        f = PathFilter(
            include_patterns=["*.yaml", "*.yaml", "./*.yaml"],
            exclude_patterns=["secrets.yaml", "secrets.yaml"],
        )
        self.assertTrue(f.matches("configuration.yaml"))
        self.assertFalse(f.matches("secrets.yaml"))


class NormalizePatternTests(unittest.TestCase):
    def test_normalize_pattern(self):
        self.assertEqual(normalize_pattern("./custom_components/**"), "custom_components/**")
        self.assertEqual(normalize_pattern("/scripts/"), "scripts")
        self.assertEqual(normalize_pattern("  *.yaml  "), "*.yaml")


if __name__ == "__main__":
    unittest.main()
