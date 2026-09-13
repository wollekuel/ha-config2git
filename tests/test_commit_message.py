"""Unit tests for the commit message template renderer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "ha_config2git" / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from commit_message import (  # noqa: E402
    MAX_LISTED_FILES,
    MAX_SUBJECT_LENGTH,
    SUPPORTED_PLACEHOLDERS,
    TemplateError,
    render_commit_message,
    validate_template,
)

DEFAULT_TEMPLATE = "Sync Home Assistant configuration: {changed_files}"


class ValidateTemplateTests(unittest.TestCase):
    def test_valid_template_without_placeholders(self):
        validate_template("Update config")  # must not raise

    def test_valid_template_with_all_placeholders(self):
        validate_template(
            "{changed_count} {changed_files} {added_count} "
            "{modified_count} {deleted_count}"
        )

    def test_unknown_placeholder_raises(self):
        with self.assertRaises(TemplateError):
            validate_template("{branch}")

    def test_missing_closing_brace_raises(self):
        with self.assertRaises(TemplateError):
            validate_template("{changed_count")

    def test_stray_closing_brace_raises(self):
        with self.assertRaises(TemplateError):
            validate_template("changed_count}")

    def test_doubled_braces_rejected(self):
        with self.assertRaises(TemplateError):
            validate_template("{{changed_count}}")

    def test_format_spec_rejected(self):
        with self.assertRaises(TemplateError):
            validate_template("{changed_files:>10}")

    def test_conversion_rejected(self):
        with self.assertRaises(TemplateError):
            validate_template("{changed_files!r}")

    def test_positional_placeholder_rejected(self):
        with self.assertRaises(TemplateError):
            validate_template("{0}")

    def test_empty_placeholder_rejected(self):
        with self.assertRaises(TemplateError):
            validate_template("{}")

    def test_error_message_lists_supported_placeholders(self):
        with self.assertRaises(TemplateError) as ctx:
            validate_template("{branch}")
        for name in SUPPORTED_PLACEHOLDERS:
            self.assertIn(name, str(ctx.exception))


class RenderCountTests(unittest.TestCase):
    def test_changed_count(self):
        msg = render_commit_message(
            "{changed_count}", added=["a"], modified=["b"], deleted=["c"]
        )
        self.assertEqual(msg, "3")

    def test_added_count(self):
        msg = render_commit_message(
            "{added_count}", added=["a", "b"], modified=["c"], deleted=["d"]
        )
        self.assertEqual(msg, "2")

    def test_modified_count(self):
        msg = render_commit_message(
            "{modified_count}", added=["a"], modified=["b", "c"], deleted=["d"]
        )
        self.assertEqual(msg, "2")

    def test_deleted_count(self):
        msg = render_commit_message(
            "{deleted_count}", added=["a"], modified=["b"], deleted=["c", "d"]
        )
        self.assertEqual(msg, "2")

    def test_zero_counts_for_empty_changes(self):
        msg = render_commit_message(
            "{changed_count}/{added_count}/{modified_count}/{deleted_count}",
            added=[],
            modified=[],
            deleted=[],
        )
        self.assertEqual(msg, "0/0/0/0")


class RenderChangedFilesTests(unittest.TestCase):
    def test_single_file(self):
        msg = render_commit_message(
            "{changed_files}", added=["configuration.yaml"], modified=[], deleted=[]
        )
        self.assertEqual(msg, "configuration.yaml")

    def test_two_files_sorted(self):
        msg = render_commit_message(
            "{changed_files}", added=["b.yaml"], modified=["a.yaml"], deleted=[]
        )
        self.assertEqual(msg, "a.yaml, b.yaml")

    def test_five_files_listed_verbatim(self):
        files = [f"f{i}.yaml" for i in range(MAX_LISTED_FILES)]
        msg = render_commit_message(
            "{changed_files}", added=files, modified=[], deleted=[]
        )
        self.assertEqual(msg, "f0.yaml, f1.yaml, f2.yaml, f3.yaml, f4.yaml")

    def test_more_than_five_files_truncated(self):
        files = [f"f{i}.yaml" for i in range(8)]
        msg = render_commit_message(
            "{changed_files}", added=files, modified=[], deleted=[]
        )
        self.assertEqual(
            msg, "f0.yaml, f1.yaml, f2.yaml, f3.yaml, f4.yaml, … (+3 more)"
        )

    def test_exactly_six_files_truncated(self):
        files = [f"f{i}.yaml" for i in range(6)]
        msg = render_commit_message(
            "{changed_files}", added=files, modified=[], deleted=[]
        )
        self.assertEqual(
            msg, "f0.yaml, f1.yaml, f2.yaml, f3.yaml, f4.yaml, … (+1 more)"
        )

    def test_deleted_files_included_in_changed_files(self):
        msg = render_commit_message(
            "{changed_files}", added=["a.yaml"], modified=[], deleted=["b.yaml"]
        )
        self.assertEqual(msg, "a.yaml, b.yaml")

    def test_empty_changed_files(self):
        msg = render_commit_message(
            "{changed_files}", added=[], modified=[], deleted=[]
        )
        self.assertEqual(msg, "")

    def test_deterministic_order(self):
        files = ["z.yaml", "a.yaml", "m.yaml"]
        first = render_commit_message(
            "{changed_files}", added=files, modified=[], deleted=[]
        )
        second = render_commit_message(
            "{changed_files}", added=files, modified=[], deleted=[]
        )
        self.assertEqual(first, second)
        self.assertEqual(first, "a.yaml, m.yaml, z.yaml")

    def test_special_characters_and_spaces_in_filenames(self):
        msg = render_commit_message(
            "{changed_files}",
            added=["my file.yaml", "ümlaut.yaml", "sp ace/na me.yaml"],
            modified=[],
            deleted=[],
        )
        self.assertEqual(msg, "my file.yaml, sp ace/na me.yaml, ümlaut.yaml")


class RenderLengthTests(unittest.TestCase):
    def test_exactly_200_characters(self):
        template = "x" * MAX_SUBJECT_LENGTH
        msg = render_commit_message(template, added=[], modified=[], deleted=[])
        self.assertEqual(len(msg), MAX_SUBJECT_LENGTH)

    def test_over_200_characters_is_truncated(self):
        template = "x" * 300
        msg = render_commit_message(template, added=[], modified=[], deleted=[])
        self.assertEqual(len(msg), MAX_SUBJECT_LENGTH)
        self.assertEqual(msg, "x" * MAX_SUBJECT_LENGTH)

    def test_many_long_filenames_keep_message_within_limit(self):
        files = [
            f"this_is_a_rather_long_filename_number_{i}.yaml" for i in range(30)
        ]
        msg = render_commit_message(
            DEFAULT_TEMPLATE, added=files, modified=[], deleted=[]
        )
        self.assertLessEqual(len(msg), MAX_SUBJECT_LENGTH)

    def test_truncation_keeps_ellipsis_representation_intact(self):
        files = [
            f"this_is_a_rather_long_filename_number_{i}.yaml" for i in range(30)
        ]
        msg = render_commit_message(
            DEFAULT_TEMPLATE, added=files, modified=[], deleted=[]
        )
        self.assertLessEqual(len(msg), MAX_SUBJECT_LENGTH)
        if "… (+" in msg:
            self.assertTrue(msg.endswith(" more)"))


class RenderSecurityTests(unittest.TestCase):
    def test_only_paths_never_file_content(self):
        # The renderer only ever receives relative paths; it never reads file
        # contents. Secret-like tokens are never part of the output.
        msg = render_commit_message(
            "{changed_files}",
            added=["configuration.yaml"],
            modified=[],
            deleted=[],
        )
        self.assertEqual(msg, "configuration.yaml")
        self.assertNotIn("api_key", msg)
        self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", msg)

    def test_render_rejects_unknown_placeholder(self):
        with self.assertRaises(TemplateError):
            render_commit_message("{branch}", added=[], modified=[], deleted=[])


if __name__ == "__main__":
    unittest.main()


