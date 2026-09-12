"""Unit tests for ha-config2git configuration handling."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "ha_config2git" / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from config import (  # noqa: E402
    DEFAULTS,
    Config,
    ConfigError,
    load_config,
    load_config_from_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_YAML_PATH = REPO_ROOT / "ha_config2git" / "config.yaml"


def _parse_yaml_scalar(text: str):
    text = text.strip()
    if text == "":
        return ""
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        return text[1:-1]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def load_options_from_config_yaml() -> dict:
    """Extract the ``options`` block from config.yaml via a minimal parser."""
    text = CONFIG_YAML_PATH.read_text(encoding="utf-8")
    match = re.search(r"(?m)^options:\s*\n(.*?)(?=^schema:)", text, re.S)
    if match is None:
        raise AssertionError("options block not found in config.yaml")
    block = match.group(1)

    options: dict = {}
    lines = block.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if stripped.startswith("- ") or ":" not in stripped:
            index += 1
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            items = []
            j = index + 1
            while j < len(lines):
                sub = lines[j]
                if not sub.strip():
                    j += 1
                    continue
                if len(sub) - len(sub.lstrip(" ")) <= indent:
                    break
                if sub.strip().startswith("- "):
                    items.append(_parse_yaml_scalar(sub.strip()[2:]))
                j += 1
            options[key] = items
            index = j
            continue
        options[key] = _parse_yaml_scalar(value)
        index += 1
    return options


class RepositoryValidationTests(unittest.TestCase):
    def test_valid_repository(self):
        config = load_config({"github_repository": "owner/repo"})
        self.assertIsInstance(config, Config)
        self.assertEqual(config.github_repository, "owner/repo")

    def test_repository_with_git_suffix_is_normalized(self):
        config = load_config({"github_repository": "owner/repo.git"})
        self.assertEqual(config.github_repository, "owner/repo")

    def test_repository_with_trailing_slash_is_normalized(self):
        config = load_config({"github_repository": "owner/repo/"})
        self.assertEqual(config.github_repository, "owner/repo")

    def test_repository_whitespace_is_stripped(self):
        config = load_config({"github_repository": "  owner/repo  "})
        self.assertEqual(config.github_repository, "owner/repo")

    def test_repository_missing_owner(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "/repo"})

    def test_repository_missing_name(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "owner/"})

    def test_repository_empty(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": ""})

    def test_repository_too_many_parts(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "a/b/c"})

    def test_repository_with_spaces(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "owner/rep o"})

    def test_repository_not_a_string(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": 123})


class BranchAndAuthorTests(unittest.TestCase):
    def test_branch_empty(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "owner/repo", "github_branch": ""})

    def test_branch_whitespace(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "owner/repo", "github_branch": "   "})

    def test_branch_stripped(self):
        config = load_config({"github_repository": "owner/repo", "github_branch": " main "})
        self.assertEqual(config.github_branch, "main")

    def test_empty_git_author_name(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "owner/repo", "git_author_name": ""})

    def test_empty_git_author_email(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "owner/repo", "git_author_email": "  "})


class PatternTests(unittest.TestCase):
    def test_include_patterns_empty_raises(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "owner/repo", "include_patterns": []})

    def test_include_patterns_defaults_used_when_missing(self):
        config = load_config({"github_repository": "owner/repo"})
        self.assertIn("*.yaml", config.include_patterns)
        self.assertIn("custom_components/**", config.include_patterns)

    def test_exclude_patterns_optional_empty(self):
        config = load_config({"github_repository": "owner/repo", "exclude_patterns": []})
        self.assertEqual(config.exclude_patterns, ())

    def test_exclude_patterns_defaults_used_when_missing(self):
        config = load_config({"github_repository": "owner/repo"})
        self.assertIn("secrets.yaml", config.exclude_patterns)

    def test_pattern_normalization(self):
        config = load_config(
            {
                "github_repository": "owner/repo",
                "include_patterns": [
                    "./automations/*.yaml",
                    "/scripts/",
                    "  custom_components/**  ",
                ],
                "exclude_patterns": ["/secrets.yaml", "./.storage/**", ""],
            }
        )
        self.assertEqual(
            config.include_patterns,
            ("automations/*.yaml", "scripts", "custom_components/**"),
        )
        self.assertEqual(config.exclude_patterns, ("secrets.yaml", ".storage/**"))

    def test_pattern_deduplication(self):
        config = load_config(
            {"github_repository": "owner/repo", "include_patterns": ["*.yaml", "*.yaml", "./*.yaml"]}
        )
        self.assertEqual(config.include_patterns, ("*.yaml",))

    def test_patterns_must_be_list(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "owner/repo", "include_patterns": "*.yaml"})

    def test_patterns_must_be_strings(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "owner/repo", "include_patterns": [1, 2]})


class DefaultsAndSummaryTests(unittest.TestCase):
    def test_defaults_applied_for_partial_options(self):
        config = load_config({"github_repository": "owner/repo"})
        self.assertEqual(config.github_branch, "main")
        self.assertEqual(config.git_author_name, "ha-config2git")
        self.assertEqual(config.git_author_email, "ha-config2git@home-assistant")
        self.assertEqual(config.commit_debounce_seconds, 30)
        self.assertEqual(config.push_interval_seconds, 300)
        self.assertEqual(config.log_level, "info")

    def test_defaults_match_config_yaml_options(self):
        self.assertEqual(load_options_from_config_yaml(), DEFAULTS)

    def test_log_level_stored_verbatim(self):
        config = load_config({"github_repository": "owner/repo", "log_level": "warning"})
        self.assertEqual(config.log_level, "warning")

    def test_config_is_frozen(self):
        config = load_config({"github_repository": "owner/repo"})
        with self.assertRaises(AttributeError):
            config.github_branch = "other"


class SshPrivateKeyTests(unittest.TestCase):
    def test_default_is_empty(self):
        config = load_config({"github_repository": "owner/repo"})
        self.assertEqual(config.ssh_private_key, "")

    def test_ssh_private_key_loaded(self):
        key = "-----BEGIN OPENSSH PRIVATE KEY----- body -----END OPENSSH PRIVATE KEY-----"
        config = load_config(
            {"github_repository": "owner/repo", "ssh_private_key": key}
        )
        self.assertEqual(config.ssh_private_key, key)

    def test_ssh_private_key_whitespace_is_stripped(self):
        config = load_config(
            {"github_repository": "owner/repo", "ssh_private_key": "  key value  "}
        )
        self.assertEqual(config.ssh_private_key, "key value")

    def test_ssh_private_key_must_be_string(self):
        with self.assertRaises(ConfigError):
            load_config({"github_repository": "owner/repo", "ssh_private_key": 123})

    def test_summary_omits_ssh_private_key(self):
        config = load_config(
            {"github_repository": "owner/repo", "ssh_private_key": "some-key-value"}
        )
        self.assertNotIn("ssh_private_key", config.summary())

    def test_summary_never_leaks_key_content(self):
        secret = "SUPER-SECRET-PRIVATE-KEY-BODY-12345"
        config = load_config(
            {"github_repository": "owner/repo", "ssh_private_key": secret}
        )
        self.assertNotIn(secret, str(config.summary()))


class LoadConfigFromPathTests(unittest.TestCase):
    def test_valid_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "options.json"
            path.write_text(json.dumps({"github_repository": "owner/repo"}), encoding="utf-8")
            config = load_config_from_path(path)
            self.assertEqual(config.github_repository, "owner/repo")

    def test_missing_file(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config_from_path(Path("/nonexistent/options.json"))
        self.assertIn("not found", str(ctx.exception))

    def test_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "options.json"
            path.write_text("{ not valid json", encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_config_from_path(path)
            self.assertIn("not valid JSON", str(ctx.exception))

    def test_json_array_instead_of_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "options.json"
            path.write_text(json.dumps(["a", "b"]), encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_config_from_path(path)
            self.assertIn("JSON object", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

