"""Unit tests for the local GitBackend."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "ha_config2git" / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from git_backend import GitBackend, GitBackendError  # noqa: E402


def _global_config(key: str):
    result = subprocess.run(
        ["git", "config", "--global", key],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip()


def _local_config(repo: Path, key: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "config", key],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write(repo: Path, name: str, content: str = "content") -> Path:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class InitTests(unittest.TestCase):
    def test_init_creates_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = GitBackend.init(Path(tmp), "A", "a@example.com", "main")
            self.assertEqual(backend.current_branch(), "main")
            self.assertTrue((Path(tmp) / ".git").is_dir())

    def test_init_uses_requested_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = GitBackend.init(Path(tmp), "A", "a@example.com", "develop")
            self.assertEqual(backend.current_branch(), "develop")

    def test_init_configures_identity_locally(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            GitBackend.init(repo, "Test Author", "test@example.com", "main")
            self.assertEqual(_local_config(repo, "user.name"), "Test Author")
            self.assertEqual(_local_config(repo, "user.email"), "test@example.com")


class OpenTests(unittest.TestCase):
    def test_open_existing_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            GitBackend.init(repo, "A", "a@example.com", "main")
            backend = GitBackend.open(repo, "B", "b@example.com")
            self.assertEqual(backend.current_branch(), "main")

    def test_open_non_repository_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GitBackendError):
                GitBackend.open(Path(tmp), "A", "a@example.com")


class BranchTests(unittest.TestCase):
    def test_set_branch_creates_new_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = GitBackend.init(Path(tmp), "A", "a@example.com", "main")
            backend.set_branch("feature")
            self.assertEqual(backend.current_branch(), "feature")

    def test_set_branch_switches_existing_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            backend = GitBackend.init(repo, "A", "a@example.com", "main")
            _write(repo, "file.txt")
            backend.add_all()
            backend.commit("initial")
            backend.set_branch("feature")
            backend.set_branch("main")
            self.assertEqual(backend.current_branch(), "main")


class AddAndCommitTests(unittest.TestCase):
    def test_add_and_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            backend = GitBackend.init(repo, "A", "a@example.com", "main")
            _write(repo, "configuration.yaml")
            backend.add(["configuration.yaml"])
            self.assertTrue(backend.has_staged_changes())
            self.assertTrue(backend.commit("add configuration.yaml"))
            self.assertIn("add configuration.yaml", "\n".join(backend.log()))

    def test_no_commit_without_staged_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            backend = GitBackend.init(repo, "A", "a@example.com", "main")
            self.assertFalse(backend.has_staged_changes())
            self.assertFalse(backend.commit("nothing"))
            self.assertEqual(backend.log(), [])


class ChangeDetectionTests(unittest.TestCase):
    def test_changes_detected_and_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            backend = GitBackend.init(repo, "A", "a@example.com", "main")

            self.assertFalse(backend.has_changes())

            _write(repo, "a.yaml")
            self.assertTrue(backend.has_changes())

            backend.add_all()
            backend.commit("add a.yaml")
            self.assertFalse(backend.has_changes())

            _write(repo, "a.yaml", "changed")
            self.assertTrue(backend.has_changes())

    def test_untracked_file_is_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            backend = GitBackend.init(repo, "A", "a@example.com", "main")
            _write(repo, "new.yaml")
            self.assertTrue(backend.has_changes())


class ErrorTests(unittest.TestCase):
    def test_add_nonexistent_path_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = GitBackend.init(Path(tmp), "A", "a@example.com", "main")
            with self.assertRaises(GitBackendError):
                backend.add(["does-not-exist.txt"])

    def test_error_carries_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = GitBackend.init(Path(tmp), "A", "a@example.com", "main")
            try:
                backend.add(["does-not-exist.txt"])
            except GitBackendError as exc:
                self.assertTrue(exc.returncode)
                self.assertTrue(exc.command)
                self.assertTrue(exc.stderr)
            else:
                self.fail("GitBackendError was not raised")


class GlobalConfigUntouchedTests(unittest.TestCase):
    def test_global_config_unchanged(self):
        before_name = _global_config("user.name")
        before_email = _global_config("user.email")
        with tempfile.TemporaryDirectory() as tmp:
            GitBackend.init(Path(tmp), "Local Author", "local@example.com", "main")
        self.assertEqual(_global_config("user.name"), before_name)
        self.assertEqual(_global_config("user.email"), before_email)


if __name__ == "__main__":
    unittest.main()

