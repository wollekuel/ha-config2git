"""Local Git backend for ha-config2git.

Wraps the ``git`` command line program via ``subprocess`` and intentionally
has no knowledge of Home Assistant, ``/config``, the PathFilter, SSH or GitHub.
Push and remote operations are implemented in a later phase.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable
from pathlib import Path


class GitBackendError(RuntimeError):
    """Raised when a git command fails."""

    def __init__(
        self,
        message: str,
        command: list[str] | None = None,
        returncode: int | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


class GitBackend:
    """Encapsulate local git operations for a single repository."""

    def __init__(
        self, repo_path: str | Path, author_name: str, author_email: str
    ) -> None:
        self._path = Path(repo_path)
        self._author_name = author_name
        self._author_email = author_email

    # -- construction ---------------------------------------------------

    @classmethod
    def init(
        cls,
        repo_path: str | Path,
        author_name: str,
        author_email: str,
        branch: str,
    ) -> "GitBackend":
        """Create a new repository using the requested initial branch."""
        path = Path(repo_path)
        path.mkdir(parents=True, exist_ok=True)
        backend = cls(path, author_name, author_email)
        backend._run(["init"])
        backend._run(["symbolic-ref", "HEAD", f"refs/heads/{branch}"])
        backend._configure_identity()
        return backend

    @classmethod
    def open(
        cls,
        repo_path: str | Path,
        author_name: str,
        author_email: str,
    ) -> "GitBackend":
        """Open an existing repository, verifying that it is a git repo."""
        backend = cls(repo_path, author_name, author_email)
        backend._ensure_is_repository()
        backend._configure_identity()
        return backend

    # -- low level ------------------------------------------------------

    def _run(
        self,
        args: list[str],
        *,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        command = ["git", *args]
        result = subprocess.run(
            command,
            cwd=str(self._path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        if check and result.returncode != 0:
            raise GitBackendError(
                f"git command failed: {' '.join(command)} "
                f"(exit code {result.returncode}): "
                f"{(result.stderr or result.stdout).strip()}",
                command=command,
                returncode=result.returncode,
                stderr=result.stderr,
            )
        return result

    def _configure_identity(self) -> None:
        """Set the commit identity for this repository only (not globally)."""
        self._run(["config", "user.name", self._author_name])
        self._run(["config", "user.email", self._author_email])

    def _ensure_is_repository(self) -> None:
        if not self._path.is_dir():
            raise GitBackendError(f"{self._path} does not exist or is not a directory")
        result = self._run(["rev-parse", "--is-inside-work-tree"], check=False)
        if result.returncode != 0:
            raise GitBackendError(f"{self._path} is not a git repository")

    def _branch_exists(self, branch: str) -> bool:
        result = self._run(
            ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            check=False,
        )
        return result.returncode == 0

    # -- repository API -------------------------------------------------

    def current_branch(self) -> str:
        """Return the name of the currently checked-out branch."""
        result = self._run(["branch", "--show-current"])
        return result.stdout.strip()

    def set_branch(self, branch: str) -> None:
        """Check out an existing branch or create and check out a new one."""
        if self.current_branch() == branch:
            return
        if self._branch_exists(branch):
            self._run(["checkout", branch])
        else:
            self._run(["checkout", "-b", branch])

    def status(self) -> list[str]:
        """Return porcelain status lines (staged, unstaged, untracked)."""
        result = self._run(["status", "--porcelain"])
        return [line for line in result.stdout.splitlines() if line.strip()]

    def has_changes(self) -> bool:
        """Return True if there are any working tree changes."""
        return bool(self.status())

    def has_staged_changes(self) -> bool:
        """Return True if there are staged changes ready to commit."""
        result = self._run(["diff", "--cached", "--name-only"])
        return bool(result.stdout.strip())

    def add(self, paths: Iterable[str]) -> None:
        """Stage the given paths for the next commit."""
        path_list = list(paths)
        if not path_list:
            return
        self._run(["add", "--", *path_list])

    def add_all(self) -> None:
        """Stage all working tree changes."""
        self._run(["add", "-A"])

    def commit(self, message: str) -> bool:
        """Commit staged changes. Returns False if nothing was staged."""
        if not self.has_staged_changes():
            return False
        self._run(["commit", "-m", message])
        return True

    def push(
        self, remote: str, branch: str, ssh_command: str | None = None
    ) -> None:
        """Push the given branch to the configured remote.

        ``ssh_command`` is passed to git as the ``GIT_SSH_COMMAND`` environment
        variable for this invocation only; the parent environment is never
        modified.
        """
        env = None
        if ssh_command is not None:
            env = {**os.environ, "GIT_SSH_COMMAND": ssh_command}
        self._run(["push", remote, branch], env=env)

    def log(self) -> list[str]:
        """Return the commit log as ``<short-hash> <subject>`` lines."""
        head = self._run(["rev-parse", "--verify", "--quiet", "HEAD"], check=False)
        if head.returncode != 0:
            return []
        result = self._run(["log", "--oneline"])
        return [line for line in result.stdout.splitlines() if line.strip()]
