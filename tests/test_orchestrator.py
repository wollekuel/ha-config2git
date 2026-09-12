"""Unit tests for the sync orchestration."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1] / "ha_config2git" / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from config import load_config  # noqa: E402
from git_backend import GitBackend, GitBackendError  # noqa: E402
from orchestrator import COMMIT_MESSAGE, Orchestrator, SyncRunResult  # noqa: E402
from sync import SyncError  # noqa: E402


def _write(path: Path, content: str = "content") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _config(**overrides):
    options = {"github_repository": "test-org/test-repo", "github_branch": "main"}
    options.update(overrides)
    return load_config(options)


def _init_bare(path: Path) -> None:
    subprocess.run(
        ["git", "init", "--bare", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )


def _remote_commit_count(bare: Path, branch: str = "main") -> int:
    result = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-list", "--count", branch],
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip())


def _remote_branches(bare: Path) -> list[str]:
    result = subprocess.run(
        ["git", "--git-dir", str(bare), "for-each-ref",
         "--format=%(refname:short)", "refs/heads"],
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _remote_file_content(bare: Path, branch: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "--git-dir", str(bare), "show", f"{branch}:{path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _remote_log(bare: Path, branch: str = "main") -> str:
    result = subprocess.run(
        ["git", "--git-dir", str(bare), "log", "--oneline", branch],
        capture_output=True,
        text=True,
    )
    return result.stdout


def _setup(base: Path, include_patterns=("*.yaml",)):
    source = base / "source"
    repo = base / "repo"
    bare = base / "remote.git"
    _init_bare(bare)
    orchestrator = Orchestrator(
        source, repo, str(bare), _config(include_patterns=list(include_patterns))
    )
    return source, repo, bare, orchestrator


class ChangeTests(unittest.TestCase):
    def test_change_syncs_stages_commits_and_pushes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, repo, bare, orchestrator = _setup(base)
            _write(source / "configuration.yaml", "hello")

            result = orchestrator.run_once()

            self.assertIsInstance(result, SyncRunResult)
            self.assertTrue(result.changed)
            self.assertEqual(result.copied, ["configuration.yaml"])
            self.assertEqual(result.deleted, [])
            self.assertTrue(result.committed)
            self.assertTrue(result.pushed)

            self.assertEqual(_remote_commit_count(bare), 1)
            self.assertIn("main", _remote_branches(bare))
            self.assertEqual(
                _remote_file_content(bare, "main", "configuration.yaml"), "hello"
            )
            self.assertIn(COMMIT_MESSAGE, _remote_log(bare))

    def test_multiple_changes_produce_single_commit_and_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, repo, bare, orchestrator = _setup(base)
            _write(source / "a.yaml", "A")
            _write(source / "b.yaml", "B")

            result = orchestrator.run_once()

            self.assertEqual(set(result.copied), {"a.yaml", "b.yaml"})
            self.assertTrue(result.committed)
            self.assertTrue(result.pushed)
            self.assertEqual(_remote_commit_count(bare), 1)
            self.assertEqual(_remote_file_content(bare, "main", "a.yaml"), "A")
            self.assertEqual(_remote_file_content(bare, "main", "b.yaml"), "B")

    def test_no_changes_produces_no_commit_or_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, repo, bare, orchestrator = _setup(base)
            _write(source / "configuration.yaml", "hello")
            orchestrator.run_once()

            result = orchestrator.run_once()

            self.assertFalse(result.changed)
            self.assertFalse(result.committed)
            self.assertFalse(result.pushed)
            self.assertEqual(result.copied, [])
            self.assertEqual(result.deleted, [])
            self.assertEqual(_remote_commit_count(bare), 1)

    def test_new_file_commits_and_pushes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, repo, bare, orchestrator = _setup(base)
            _write(source / "a.yaml", "A")
            orchestrator.run_once()

            _write(source / "b.yaml", "B")
            result = orchestrator.run_once()

            self.assertEqual(result.copied, ["b.yaml"])
            self.assertTrue(result.committed)
            self.assertTrue(result.pushed)
            self.assertEqual(_remote_commit_count(bare), 2)
            self.assertEqual(_remote_file_content(bare, "main", "b.yaml"), "B")

    def test_deleted_file_commits_and_pushes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, repo, bare, orchestrator = _setup(base)
            _write(source / "a.yaml", "A")
            _write(source / "b.yaml", "B")
            orchestrator.run_once()

            (source / "a.yaml").unlink()
            result = orchestrator.run_once()

            self.assertEqual(result.deleted, ["a.yaml"])
            self.assertTrue(result.committed)
            self.assertTrue(result.pushed)
            self.assertEqual(_remote_commit_count(bare), 2)
            self.assertIsNone(_remote_file_content(bare, "main", "a.yaml"))
            self.assertEqual(_remote_file_content(bare, "main", "b.yaml"), "B")


class CommitContentTests(unittest.TestCase):
    def test_commit_contains_expected_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, repo, bare, orchestrator = _setup(
                base, include_patterns=["*.yaml", "custom/**"]
            )
            _write(source / "configuration.yaml", "hello world")
            _write(source / "custom/flag.yaml", "nested")

            orchestrator.run_once()

            self.assertEqual(
                _remote_file_content(bare, "main", "configuration.yaml"),
                "hello world",
            )
            self.assertEqual(
                _remote_file_content(bare, "main", "custom/flag.yaml"), "nested"
            )
            self.assertIn(COMMIT_MESSAGE, _remote_log(bare))

    def test_push_lands_in_local_bare_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, repo, bare, orchestrator = _setup(base)
            _write(source / "configuration.yaml", "pushed-content")

            result = orchestrator.run_once()

            self.assertTrue(result.pushed)
            self.assertIn("main", _remote_branches(bare))
            self.assertEqual(
                _remote_file_content(bare, "main", "configuration.yaml"),
                "pushed-content",
            )


class ErrorPropagationTests(unittest.TestCase):
    def test_sync_error_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            source.mkdir()
            orchestrator = Orchestrator(source, source, "origin", _config())

            with self.assertRaises(SyncError):
                orchestrator.run_once()

    def test_git_backend_error_on_commit_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, repo, bare, orchestrator = _setup(base)
            _write(source / "configuration.yaml", "hello")

            backend = mock.Mock()
            backend.add_all.return_value = None
            backend.commit.side_effect = GitBackendError("commit failed")
            with mock.patch.object(orchestrator, "_get_backend", return_value=backend):
                with self.assertRaises(GitBackendError):
                    orchestrator.run_once()

            backend.add_all.assert_called_once()
            backend.commit.assert_called_once_with(COMMIT_MESSAGE)
            backend.push.assert_not_called()

    def test_git_backend_error_on_push_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, repo, bare, orchestrator = _setup(base)
            _write(source / "configuration.yaml", "hello")

            backend = mock.Mock()
            backend.add_all.return_value = None
            backend.commit.return_value = True
            backend.push.side_effect = GitBackendError("push failed")
            with mock.patch.object(orchestrator, "_get_backend", return_value=backend):
                with self.assertRaises(GitBackendError):
                    orchestrator.run_once()

            backend.add_all.assert_called_once()
            backend.commit.assert_called_once_with(COMMIT_MESSAGE)
            backend.push.assert_called_once_with(str(bare), "main", ssh_command=None)


class MockBackendTests(unittest.TestCase):
    def test_no_changes_skips_backend_entirely(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, repo, bare, orchestrator = _setup(base)
            _write(source / "configuration.yaml", "hello")
            orchestrator.run_once()

            backend = mock.Mock()
            with mock.patch.object(orchestrator, "_get_backend", return_value=backend):
                result = orchestrator.run_once()

            self.assertFalse(result.changed)
            backend.add_all.assert_not_called()
            backend.commit.assert_not_called()
            backend.push.assert_not_called()


class SshCommandTests(unittest.TestCase):
    def test_push_uses_ssh_command_when_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            bare = base / "remote.git"
            _init_bare(bare)
            orchestrator = Orchestrator(
                source, repo, str(bare), _config(), ssh_command="ssh -i /key"
            )
            _write(source / "configuration.yaml", "hello")

            backend = mock.Mock()
            backend.add_all.return_value = None
            backend.commit.return_value = True
            with mock.patch.object(orchestrator, "_get_backend", return_value=backend):
                orchestrator.run_once()

            backend.push.assert_called_once_with(
                str(bare), "main", ssh_command="ssh -i /key"
            )


class BranchConfigurationTests(unittest.TestCase):
    def test_custom_branch_is_used_for_commit_and_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            bare = base / "remote.git"
            _init_bare(bare)
            orchestrator = Orchestrator(
                source, repo, str(bare), _config(github_branch="develop")
            )
            _write(source / "configuration.yaml", "hello")

            result = orchestrator.run_once()

            self.assertTrue(result.pushed)
            self.assertIn("develop", _remote_branches(bare))
            self.assertNotIn("main", _remote_branches(bare))
            self.assertEqual(_remote_commit_count(bare, "develop"), 1)
            self.assertEqual(
                _remote_file_content(bare, "develop", "configuration.yaml"), "hello"
            )

    def test_existing_repository_on_different_branch_is_switched(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            bare = base / "remote.git"
            _init_bare(bare)
            # A pre-existing repository that was initialized on "master".
            GitBackend.init(repo, "Prev", "prev@example.com", "master")

            orchestrator = Orchestrator(source, repo, str(bare), _config())
            _write(source / "configuration.yaml", "hello")

            result = orchestrator.run_once()

            self.assertTrue(result.pushed)
            self.assertIn("main", _remote_branches(bare))
            self.assertNotIn("master", _remote_branches(bare))
            self.assertEqual(
                _remote_file_content(bare, "main", "configuration.yaml"), "hello"
            )

    def test_push_rejected_when_remote_has_existing_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            repo = base / "repo"
            bare = base / "remote.git"
            _init_bare(bare)
            # Seed the remote with unrelated history on "main".
            seed = base / "seed"
            backend = GitBackend.init(seed, "Seed", "seed@example.com", "main")
            _write(seed / "README.md", "seed")
            backend.add_all()
            backend.commit("seed commit")
            backend.push(str(bare), "main")

            orchestrator = Orchestrator(source, repo, str(bare), _config())
            _write(source / "configuration.yaml", "hello")

            with self.assertRaises(GitBackendError):
                orchestrator.run_once()


if __name__ == "__main__":
    unittest.main()


