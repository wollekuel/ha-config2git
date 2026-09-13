"""Orchestrate a single full synchronization run.

This module ties together the :class:`~sync.Sync` and
:class:`~git_backend.GitBackend` components to perform exactly one run:
synchronize the Home Assistant configuration into the local repository and, if
anything changed, commit and push it.

There is intentionally no file-system watcher and no automatic retry here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from commit_message import render_commit_message
from config import Config
from git_backend import GitBackend
from pathfilter import PathFilter
from sync import Sync


@dataclass
class SyncRunResult:
    """Structured outcome of a single orchestrated sync run."""

    changed: bool
    copied: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    committed: bool = False
    pushed: bool = False


class Orchestrator:
    """Run a single sync-and-commit-and-push cycle.

    The remote is injected (a URL or path understood by ``git push``). An
    optional ``ssh_command`` is passed through to :meth:`GitBackend.push` so
    that pushes to GitHub use the prepared SSH configuration.
    """

    def __init__(
        self,
        source_dir: str | Path,
        repository_dir: str | Path,
        remote: str,
        config: Config,
        ssh_command: str | None = None,
    ) -> None:
        self._source_dir = Path(source_dir)
        self._repository_dir = Path(repository_dir)
        self._remote = remote
        self._config = config
        self._ssh_command = ssh_command
        self._filter = PathFilter(config.include_patterns, config.exclude_patterns)

    def run_once(self) -> SyncRunResult:
        """Synchronize, then commit and push if anything changed."""
        result = Sync(self._source_dir, self._repository_dir, self._filter).sync()

        committed = False
        pushed = False
        if result.has_changes:
            backend = self._get_backend()
            backend.add_all()
            message = render_commit_message(
                self._config.commit_message_template,
                added=result.added,
                modified=result.modified,
                deleted=result.deleted,
            )
            committed = backend.commit(message)
            if committed:
                backend.push(
                    self._remote,
                    self._config.github_branch,
                    ssh_command=self._ssh_command,
                )
                pushed = True

        return SyncRunResult(
            changed=result.has_changes,
            copied=list(result.copied),
            deleted=list(result.deleted),
            committed=committed,
            pushed=pushed,
        )

    def _get_backend(self) -> GitBackend:
        repo = self._repository_dir
        if (repo / ".git").is_dir():
            backend = GitBackend.open(
                repo, self._config.git_author_name, self._config.git_author_email
            )
            backend.set_branch(self._config.github_branch)
            return backend
        return GitBackend.init(
            repo,
            self._config.git_author_name,
            self._config.git_author_email,
            self._config.github_branch,
        )
