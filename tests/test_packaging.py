"""Structural regression tests for the Home Assistant app packaging.

Home Assistant's Supervisor looks for ``CHANGELOG.md`` next to the app's
``config.yaml`` (in the app folder, not in the repository root). These tests
keep the changelog at that location so the app's update dialog can show it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "ha_config2git"
APP_CONFIG = APP_DIR / "config.yaml"
APP_CHANGELOG = APP_DIR / "CHANGELOG.md"
ROOT_CHANGELOG = REPO_ROOT / "CHANGELOG.md"

_VERSION_RE = re.compile(r"(?m)^version:\s*\"?([^\"\s]+)\"?\s*$")


def _app_version() -> str:
    """Return the authoritative app version from ``ha_config2git/config.yaml``."""
    match = _VERSION_RE.search(APP_CONFIG.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError("no version found in ha_config2git/config.yaml")
    return match.group(1)


class AppStructureTests(unittest.TestCase):
    def test_app_config_exists(self):
        self.assertTrue(APP_CONFIG.is_file())

    def test_app_changelog_lives_next_to_config(self):
        # The Supervisor reads the changelog from the app folder.
        self.assertTrue(APP_CHANGELOG.is_file())
        self.assertEqual(APP_CHANGELOG.parent, APP_CONFIG.parent)

    def test_no_changelog_in_repository_root(self):
        # A root-level changelog is never read by Home Assistant and would only
        # duplicate the content that has to be maintained in the app folder.
        self.assertFalse(ROOT_CHANGELOG.exists())

    def test_changelog_documents_current_version(self):
        changelog = APP_CHANGELOG.read_text(encoding="utf-8")
        pattern = re.compile(
            r"^#{2,3}\s*\[?" + re.escape(_app_version()) + r"\]?\s*$",
            re.MULTILINE,
        )
        self.assertRegex(changelog, pattern)

    def test_released_versions_still_documented(self):
        changelog = APP_CHANGELOG.read_text(encoding="utf-8")
        for version in ("0.2.0", "0.3.0", "0.3.2", "0.3.3"):
            self.assertIn(f"## [{version}]", changelog)


if __name__ == "__main__":
    unittest.main()
