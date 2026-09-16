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


class ExcludesTests(unittest.TestCase):
    def test_directory_pattern_excludes_dir_and_contents(self):
        f = PathFilter(include_patterns=["**"], exclude_patterns=[".storage/**"])
        self.assertTrue(f.excludes(".storage"))
        self.assertTrue(f.excludes(".storage/core.config"))
        self.assertTrue(f.excludes(".storage/deep/nested.yaml"))

    def test_file_pattern_does_not_exclude_directory(self):
        f = PathFilter(include_patterns=["**"], exclude_patterns=["secrets.yaml"])
        self.assertFalse(f.excludes("scripts"))
        self.assertTrue(f.excludes("secrets.yaml"))

    def test_no_exclude_patterns(self):
        f = PathFilter(include_patterns=["**"], exclude_patterns=[])
        self.assertFalse(f.excludes("anything"))


class MayContainIncludedTests(unittest.TestCase):
    def test_root_may_contain_included(self):
        f = PathFilter(include_patterns=["*.yaml"])
        self.assertTrue(f.may_contain_included(""))

    def test_single_segment_pattern_does_not_cover_subdir(self):
        f = PathFilter(include_patterns=["*.yaml"])
        self.assertFalse(f.may_contain_included("deps"))

    def test_double_star_pattern_covers_its_dir(self):
        f = PathFilter(include_patterns=["custom_components/**"])
        self.assertTrue(f.may_contain_included("custom_components"))
        self.assertTrue(f.may_contain_included("custom_components/foo"))
        self.assertFalse(f.may_contain_included("deps"))

    def test_bare_directory_pattern(self):
        f = PathFilter(include_patterns=["scripts"])
        self.assertTrue(f.may_contain_included("scripts"))
        self.assertFalse(f.may_contain_included("script2"))

    def test_deeply_anchored_pattern(self):
        f = PathFilter(include_patterns=["automations/*.yaml"])
        self.assertTrue(f.may_contain_included("automations"))
        self.assertFalse(f.may_contain_included("automations/sub"))

    def test_glob_star_keeps_matching_dir(self):
        f = PathFilter(include_patterns=["*"])
        self.assertTrue(f.may_contain_included("deps"))

    def test_double_star_keeps_everything(self):
        f = PathFilter(include_patterns=["**"])
        self.assertTrue(f.may_contain_included("anything/deep/nested"))

    def test_directory_named_like_file_pattern(self):
        f = PathFilter(include_patterns=["*.yaml"])
        self.assertTrue(f.may_contain_included("foo.yaml"))

    def test_no_include_patterns_prunes_everything(self):
        f = PathFilter(include_patterns=[])
        self.assertFalse(f.may_contain_included("deps"))
        self.assertFalse(f.may_contain_included(""))

    def test_consistency_with_matches(self):
        include = [
            "*.yaml",
            "*.yml",
            "*.json",
            "custom_components/**",
            "blueprints/**",
            "esphome/**",
        ]
        exclude = ["secrets.yaml", "*.db", "*.db-*", ".storage/**"]
        f = PathFilter(include_patterns=include, exclude_patterns=exclude)

        directories = [
            "",
            "custom_components",
            "custom_components/foo",
            "blueprints",
            "esphome",
            "deps",
            "tts",
            "www",
            "scripts",
        ]
        candidates = [
            "configuration.yaml",
            "automations.json",
            "secrets.yaml",
            "home-assistant_v2.db",
            "custom_components/foo/__init__.py",
            "custom_components/foo/sub/bar.py",
            "blueprints/a/b.yaml",
            "esphome/c/d.yaml",
            "deps/module.py",
            "tts/voice.wav",
            "www/index.html",
            "scripts/run.sh",
        ]
        for directory in directories:
            for candidate in candidates:
                rel = f"{directory}/{candidate}" if directory else candidate
                if f.matches(rel):
                    self.assertTrue(
                        f.may_contain_included(directory),
                        f"matches({rel!r}) but may_contain_included({directory!r}) is False",
                    )


if __name__ == "__main__":
    unittest.main()
