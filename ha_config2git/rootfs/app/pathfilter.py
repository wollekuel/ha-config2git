"""Central include/exclude path filter shared by watcher.py and sync.py.

Git metadata is reserved: ``.git`` directories and ``.git`` files are excluded
unconditionally at every depth and can never be enabled through the include or
exclude configuration.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable

# Git metadata is reserved: it must never become part of the backup, no matter
# how the include/exclude configuration looks. The rule is applied internally
# by PathFilter, so it cannot be disabled by saved user options either.
RESERVED_EXCLUDE_PATTERNS = ("**/.git/**",)


def normalize_pattern(pattern: str) -> str:
    """Canonicalize a single glob pattern to a relative POSIX form."""
    pattern = pattern.strip()
    while pattern.startswith("./"):
        pattern = pattern[2:]
    pattern = pattern.lstrip("/")
    pattern = pattern.rstrip("/")
    return pattern


def _normalize_path(path: str) -> str:
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    path = path.lstrip("/")
    path = path.rstrip("/")
    segments = [segment for segment in path.split("/") if segment not in ("", ".")]
    return "/".join(segments)


def _match_segments(pattern: list[str], path: list[str]) -> bool:
    """Match pattern segments against path segments with ``**`` support."""
    if not pattern:
        return not path
    if pattern[0] == "**":
        for index in range(len(path) + 1):
            if _match_segments(pattern[1:], path[index:]):
                return True
        return False
    if not path:
        return False
    if fnmatch.fnmatchcase(path[0], pattern[0]):
        return _match_segments(pattern[1:], path[1:])
    return False


def _match_segments_may_extend(pattern: list[str], path: list[str]) -> bool:
    """Return True if some (possibly empty) extension of ``path`` matches ``pattern``.

    Unlike :func:`_match_segments`, this allows appending extra path segments, so
    it answers "could this pattern match a descendant of ``path``?".
    """
    if not pattern:
        return not path
    if pattern[0] == "**":
        for index in range(len(path) + 1):
            if _match_segments_may_extend(pattern[1:], path[index:]):
                return True
        return False
    if not path:
        # We may append a segment matching pattern[0], then match the rest.
        return _match_segments_may_extend(pattern[1:], [])
    if fnmatch.fnmatchcase(path[0], pattern[0]):
        return _match_segments_may_extend(pattern[1:], path[1:])
    return False


def _pattern_matches_path(pattern: str, path: str) -> bool:
    """Return True if a pattern matches a path or one of its ancestors."""
    pattern_segments = pattern.split("/") if pattern else []
    path_segments = path.split("/") if path else []

    if _match_segments(pattern_segments, path_segments):
        return True

    # A directory match covers everything beneath it: check ancestor paths.
    for index in range(1, len(path_segments)):
        if _match_segments(pattern_segments, path_segments[:index]):
            return True

    return False


class PathFilter:
    """Match relative POSIX paths against include/exclude glob patterns.

    ``exclude_patterns`` always win over ``include_patterns``. ``*`` matches
    within a single path segment, ``**`` matches zero or more whole segments.
    A pattern that matches a directory also matches everything beneath it.

    Git metadata is reserved: the patterns in :data:`RESERVED_EXCLUDE_PATTERNS`
    (``.git`` directories and files at any depth) are always excluded, no matter
    how the include and exclude patterns are configured. See
    :attr:`reserved_exclude_patterns`.
    """

    def __init__(
        self,
        include_patterns: Iterable[str] = (),
        exclude_patterns: Iterable[str] = (),
    ) -> None:
        self._include = tuple(normalize_pattern(p) for p in include_patterns)
        self._exclude = tuple(normalize_pattern(p) for p in exclude_patterns)
        # Reserved patterns stay separate from the user configuration so that
        # the public ``exclude_patterns`` API is unchanged. They are applied
        # together with the user patterns; because excludes always win over
        # includes, they can never be re-enabled by configuration.
        self._reserved_exclude = tuple(
            normalize_pattern(p) for p in RESERVED_EXCLUDE_PATTERNS
        )
        self._effective_exclude = self._exclude + self._reserved_exclude

    @property
    def include_patterns(self) -> tuple[str, ...]:
        return self._include

    @property
    def exclude_patterns(self) -> tuple[str, ...]:
        """Return the exclude patterns configured by the user."""
        return self._exclude

    @property
    def reserved_exclude_patterns(self) -> tuple[str, ...]:
        """Return the reserved exclusions that are always applied."""
        return self._reserved_exclude

    def matches(self, relative_path: str) -> bool:
        """Return True if the path should be included (and is not excluded)."""
        path = _normalize_path(relative_path)
        if not path:
            return False

        for pattern in self._effective_exclude:
            if _pattern_matches_path(pattern, path):
                return False

        for pattern in self._include:
            if _pattern_matches_path(pattern, path):
                return True

        return False

    def excludes(self, relative_path: str) -> bool:
        """Return True if the path or one of its ancestors matches an exclude pattern.

        Reserved exclusions (Git metadata) count as well, so this returns True
        for ``.git`` directories, which lets the watcher prune them before it
        considers include-based traversal.
        """
        path = _normalize_path(relative_path)
        if not path:
            return False
        for pattern in self._effective_exclude:
            if _pattern_matches_path(pattern, path):
                return True
        return False

    def may_contain_included(self, relative_dir: str) -> bool:
        """Return True if some path at or below ``relative_dir`` could be included.

        This is a traversal hint only and never changes the ``matches()`` result.
        It is conservative: ``True`` means an include pattern might match a
        descendant (so the directory should be traversed), while ``False`` is a
        hard guarantee that no include pattern can match anything beneath it (so
        the traversal may safely prune the directory).
        """
        path = _normalize_path(relative_dir)
        path_segments = path.split("/") if path else []
        for pattern in self._include:
            if _pattern_matches_path(pattern, path):
                return True
            if _match_segments_may_extend(pattern.split("/") if pattern else [], path_segments):
                return True
        return False
