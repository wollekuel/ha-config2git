"""Unit tests for the Sync component."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "ha_config2git" / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from pathfilter import PathFilter  # noqa: E402
from sync import Sync, SyncError  # noqa: E402


def _write(path: Path, content: str = "content") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rel_files(root: Path) -> set[str]:
    result: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            result.add(Path(dirpath, name).relative_to(root).as_posix())
    return result


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink()
    }


def _run_git(repo: Path, *args: str) -> None:
    """Run a git command inside ``repo`` (fixture helper)."""
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )


def _make_nested_repository(path: Path) -> None:
    """Create a real Git repository with one commit below ``path``.

    The repository is expected to contain files already; they are staged so
    that the resulting ``.git`` directory has an index and a resolvable HEAD.
    """
    path.mkdir(parents=True, exist_ok=True)
    _run_git(path, "init", "-q", ".")
    _run_git(path, "add", "-A")
    _run_git(
        path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "initial",
    )


class SyncTestCase(unittest.TestCase):
    def _sync(self, source: Path, repo: Path, include, exclude=()):
        return Sync(source, repo, PathFilter(include_patterns=include, exclude_patterns=exclude))


class CopyTests(SyncTestCase):
    def test_single_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "configuration.yaml", "hello")

            result = self._sync(source, repo, ["*.yaml"]).sync()

            self.assertEqual(result.copied, ["configuration.yaml"])
            self.assertEqual(_read(repo / "configuration.yaml"), "hello")

    def test_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml")
            _write(source / "b.yaml")
            _write(source / "c.txt")

            result = self._sync(source, repo, ["*.yaml"]).sync()

            self.assertEqual(result.copied, ["a.yaml", "b.yaml"])
            self.assertEqual(_rel_files(repo), {"a.yaml", "b.yaml"})

    def test_nested_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "custom_components/foo/__init__.py")
            _write(source / "custom_components/foo/bar.py")

            result = self._sync(source, repo, ["custom_components/**"]).sync()

            self.assertEqual(
                set(result.copied),
                {"custom_components/foo/__init__.py", "custom_components/foo/bar.py"},
            )
            self.assertEqual(
                _read(repo / "custom_components/foo/__init__.py"), "content"
            )


class PatternTests(SyncTestCase):
    def test_include_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "config.yaml")
            _write(source / "config.json")
            _write(source / "config.txt")

            result = self._sync(source, repo, ["*.yaml", "*.json"]).sync()

            self.assertEqual(result.copied, ["config.json", "config.yaml"])

    def test_exclude_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "configuration.yaml")
            _write(source / "secrets.yaml")

            result = self._sync(
                source, repo, ["*.yaml"], exclude=["secrets.yaml"]
            ).sync()

            self.assertEqual(result.copied, ["configuration.yaml"])
            self.assertNotIn("secrets.yaml", _rel_files(repo))

    def test_exclude_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "custom_components/foo/__init__.py")
            _write(source / "custom_components/foo/secret.py")

            result = self._sync(
                source, repo, ["custom_components/**"], exclude=["**/secret.py"]
            ).sync()

            self.assertEqual(result.copied, ["custom_components/foo/__init__.py"])


class IncrementalTests(SyncTestCase):
    def test_new_file_on_second_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml")
            sync = self._sync(source, repo, ["*.yaml"])

            sync.sync()
            _write(source / "b.yaml")
            result = sync.sync()

            self.assertEqual(result.copied, ["b.yaml"])

    def test_changed_file_on_second_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml", "v1")
            sync = self._sync(source, repo, ["*.yaml"])

            sync.sync()
            _write(source / "a.yaml", "v2")
            result = sync.sync()

            self.assertEqual(result.copied, ["a.yaml"])
            self.assertEqual(_read(repo / "a.yaml"), "v2")

    def test_deleted_source_file_removed_in_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml")
            _write(source / "b.yaml")
            sync = self._sync(source, repo, ["*.yaml"])

            sync.sync()
            (source / "a.yaml").unlink()
            result = sync.sync()

            self.assertEqual(result.deleted, ["a.yaml"])
            self.assertNotIn("a.yaml", _rel_files(repo))
            self.assertIn("b.yaml", _rel_files(repo))

    def test_result_has_changes_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml")
            sync = self._sync(source, repo, ["*.yaml"])

            self.assertTrue(sync.sync().has_changes)
            self.assertFalse(sync.sync().has_changes)
            _write(source / "a.yaml", "changed")
            self.assertTrue(sync.sync().has_changes)


class ChangeClassificationTests(SyncTestCase):
    def test_new_files_classified_as_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml")
            _write(source / "b.yaml")

            result = self._sync(source, repo, ["*.yaml"]).sync()

            self.assertEqual(result.added, ["a.yaml", "b.yaml"])
            self.assertEqual(result.modified, [])
            self.assertEqual(result.deleted, [])
            self.assertEqual(result.copied, ["a.yaml", "b.yaml"])

    def test_changed_files_classified_as_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml", "v1")
            sync = self._sync(source, repo, ["*.yaml"])

            sync.sync()
            _write(source / "a.yaml", "v2")
            result = sync.sync()

            self.assertEqual(result.added, [])
            self.assertEqual(result.modified, ["a.yaml"])
            self.assertEqual(result.deleted, [])
            self.assertEqual(result.copied, ["a.yaml"])

    def test_deleted_files_classified_as_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml")
            sync = self._sync(source, repo, ["*.yaml"])

            sync.sync()
            (source / "a.yaml").unlink()
            result = sync.sync()

            self.assertEqual(result.added, [])
            self.assertEqual(result.modified, [])
            self.assertEqual(result.deleted, ["a.yaml"])
            self.assertEqual(result.copied, [])

    def test_mixed_add_modify_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml", "v1")
            _write(source / "b.yaml", "v1")
            sync = self._sync(source, repo, ["*.yaml"])

            sync.sync()
            _write(source / "c.yaml", "v1")
            _write(source / "a.yaml", "v2")
            (source / "b.yaml").unlink()
            result = sync.sync()

            self.assertEqual(result.added, ["c.yaml"])
            self.assertEqual(result.modified, ["a.yaml"])
            self.assertEqual(result.deleted, ["b.yaml"])
            self.assertEqual(result.copied, ["a.yaml", "c.yaml"])

    def test_excluded_files_never_classified(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml")
            _write(source / "secrets.yaml")
            sync = self._sync(source, repo, ["*.yaml"], exclude=["secrets.yaml"])

            result = sync.sync()

            self.assertEqual(result.added, ["a.yaml"])
            self.assertEqual(result.modified, [])
            self.assertEqual(result.deleted, [])
            self.assertNotIn("secrets.yaml", result.copied)


class DeletionSafetyTests(SyncTestCase):
    def test_unmanaged_target_files_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml")
            sync = self._sync(source, repo, ["*.yaml"])

            sync.sync()
            _write(repo / "unmanaged.txt")

            result = sync.sync()

            self.assertEqual(result.deleted, [])
            self.assertIn("unmanaged.txt", _rel_files(repo))

    def test_excluded_target_files_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml")
            sync = self._sync(source, repo, ["*.yaml"], exclude=["secrets.yaml"])

            sync.sync()
            _write(repo / "secrets.yaml")

            result = sync.sync()

            self.assertEqual(result.deleted, [])
            self.assertIn("secrets.yaml", _rel_files(repo))


class EmptyDirectoryTests(SyncTestCase):
    def test_empty_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml")
            _write(source / "sub/b.yaml")
            (source / "empty").mkdir()
            sync = self._sync(source, repo, ["**"])

            sync.sync()
            # An empty source directory is never mirrored.
            self.assertFalse((repo / "empty").exists())

            # After the last file in a directory is removed, the directory goes.
            (source / "sub/b.yaml").unlink()
            sync.sync()
            self.assertFalse((repo / "sub").exists())


class SourceIntegrityTests(SyncTestCase):
    def test_source_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "a.yaml", "data")
            _write(source / "sub/b.yaml", "nested")
            sync = self._sync(source, repo, ["**"])

            before = _snapshot(source)
            sync.sync()
            after = _snapshot(source)

            self.assertEqual(before, after)


class SafetyTests(SyncTestCase):
    def test_source_equals_repository_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "same"
            d.mkdir()
            with self.assertRaises(SyncError):
                Sync(d, d, PathFilter(include_patterns=["**"]))

    def test_repository_inside_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            repo = source / "repo"
            with self.assertRaises(SyncError):
                Sync(source, repo, PathFilter(include_patterns=["**"]))

    def test_path_traversal_prevented(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            outside = base / "outside.yaml"
            _write(outside, "secret")
            source.mkdir(parents=True)
            (source / "escape.yaml").symlink_to(outside)

            result = self._sync(source, repo, ["*.yaml"]).sync()

            self.assertEqual(result.copied, [])
            self.assertFalse((repo / "escape.yaml").exists())
            self.assertEqual(_read(outside), "secret")


class SymlinkTests(SyncTestCase):
    def test_symlink_in_source_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "real.yaml", "data")
            (source / "link.yaml").symlink_to("real.yaml")

            result = self._sync(source, repo, ["*.yaml"]).sync()

            self.assertEqual(result.copied, ["real.yaml"])
            self.assertFalse((repo / "link.yaml").exists())
            self.assertEqual(_read(repo / "real.yaml"), "data")


class GitMetadataTests(SyncTestCase):
    def test_nested_git_repository_is_not_synchronized(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "configuration.yaml", "root")
            _write(source / "esphome" / "demo.yaml", "esphome")
            _make_nested_repository(source / "esphome")

            # The nested repository really contains Git metadata.
            nested_metadata = _rel_files(source / "esphome" / ".git")
            self.assertIn("index", nested_metadata)
            self.assertIn("HEAD", nested_metadata)

            result = self._sync(source, repo, ["*.yaml", "esphome/**"]).sync()

            self.assertEqual(result.added, ["configuration.yaml", "esphome/demo.yaml"])
            self.assertEqual(result.deleted, [])
            self.assertEqual(
                _rel_files(repo), {"configuration.yaml", "esphome/demo.yaml"}
            )
            self.assertFalse((repo / "esphome" / ".git").exists())

    def test_repository_git_metadata_protected_with_broad_include(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            _write(source / "configuration.yaml", "root")
            _write(source / ".git" / "config", "source metadata")
            _write(source / ".git" / "objects" / "ab" / "cdef", "source object")
            marker = _write(repo / ".git" / "config", "repository metadata")
            head = _write(repo / ".git" / "HEAD", "ref: refs/heads/main")
            (repo / ".git" / "refs" / "tags").mkdir(parents=True)

            sync = self._sync(source, repo, ["**"])
            first = sync.sync()
            second = sync.sync()

            # Only the real configuration file is synchronized.
            self.assertEqual(first.copied, ["configuration.yaml"])
            self.assertEqual(first.deleted, [])
            self.assertEqual(second.copied, [])
            self.assertEqual(second.deleted, [])
            self.assertEqual(_read(repo / "configuration.yaml"), "root")

            # The repository's own Git metadata is neither replaced nor deleted.
            self.assertEqual(_read(marker), "repository metadata")
            self.assertEqual(_read(head), "ref: refs/heads/main")
            self.assertFalse((repo / ".git" / "objects" / "ab" / "cdef").exists())
            self.assertTrue((repo / ".git" / "refs" / "tags").is_dir())


if __name__ == "__main__":
    unittest.main()


