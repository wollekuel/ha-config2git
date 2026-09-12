"""Synchronize selected files from a source directory into a repository.

This module has no knowledge of Home Assistant, GitHub or SSH. It only
mirrors files selected by a :class:`~pathfilter.PathFilter` from a source
directory into a repository directory, using only the standard library.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pathfilter import PathFilter


class SyncError(Exception):
    """Raised when the sync configuration is invalid."""


@dataclass
class SyncResult:
    """Outcome of a single sync run."""

    copied: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Return True if any file was copied or deleted."""
        return bool(self.copied or self.deleted)


class Sync:
    """Mirror files selected by ``path_filter`` from ``source_dir`` into
    ``repository_dir``.

    Relative paths are preserved. The source directory is never modified.
    Files in the repository directory that do not match the filter are left
    untouched. Symlinks are not followed and are never synchronized.
    """

    def __init__(
        self,
        source_dir: str | Path,
        repository_dir: str | Path,
        path_filter: PathFilter,
    ) -> None:
        self._source = Path(source_dir).resolve()
        self._repo = Path(repository_dir).resolve()
        self._filter = path_filter

        if self._source == self._repo:
            raise SyncError("source_dir and repository_dir must be different directories")
        if self._repo.is_relative_to(self._source):
            raise SyncError("repository_dir must not be inside source_dir")
        if self._source.is_relative_to(self._repo):
            raise SyncError("source_dir must not be inside repository_dir")
        if not self._source.is_dir():
            raise SyncError(
                f"source_dir does not exist or is not a directory: {self._source}"
            )

    def sync(self) -> SyncResult:
        """Synchronize the source into the repository and return the result."""
        self._repo.mkdir(parents=True, exist_ok=True)
        result = SyncResult()
        self._copy_source_files(result)
        self._delete_stale_files(result)
        self._remove_empty_dirs()
        result.copied.sort()
        result.deleted.sort()
        return result

    # -- internal -----------------------------------------------------

    def _target(self, rel: str) -> Path:
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise SyncError(f"unsafe relative path: {rel!r}")
        return self._repo / rel_path

    def _copy_source_files(self, result: SyncResult) -> None:
        for root, _dirs, files in os.walk(self._source):
            for name in files:
                src = Path(root) / name
                if src.is_symlink():
                    continue
                rel = src.relative_to(self._source).as_posix()
                if not self._filter.matches(rel):
                    continue
                dst = self._target(rel)
                if dst.is_file() and not dst.is_symlink():
                    try:
                        if src.read_bytes() == dst.read_bytes():
                            continue
                    except OSError:
                        pass
                if dst.is_symlink():
                    dst.unlink()
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                result.copied.append(rel)

    def _delete_stale_files(self, result: SyncResult) -> None:
        for root, _dirs, files in os.walk(self._repo):
            for name in files:
                dst = Path(root) / name
                if dst.is_symlink():
                    continue
                rel = dst.relative_to(self._repo).as_posix()
                if not self._filter.matches(rel):
                    continue
                src = self._source / rel
                if src.is_file() and not src.is_symlink():
                    continue
                dst.unlink(missing_ok=True)
                result.deleted.append(rel)

    def _remove_empty_dirs(self) -> None:
        for root, dirs, _files in os.walk(self._repo, topdown=False):
            for name in dirs:
                d = Path(root) / name
                if d.is_symlink():
                    continue
                rel = d.relative_to(self._repo).as_posix()
                if not self._filter.matches(rel):
                    continue
                try:
                    d.rmdir()
                except OSError:
                    pass
