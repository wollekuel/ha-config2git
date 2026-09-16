"""Recursive filesystem watcher for ha-config2git.

Watches a source directory tree for changes to regular files selected by the
:class:`~pathfilter.PathFilter` and invokes a callback once after a
configurable debounce period with no further relevant changes.

Only the standard library is used: the tree is polled with :func:`os.scandir`
in a daemon thread, so the watcher is cross-platform and never prevents a
clean process shutdown.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from pathfilter import PathFilter


class WatcherError(RuntimeError):
    """Raised when the watcher is misconfigured or cannot start."""


DEFAULT_POLL_INTERVAL = 1.0


class Watcher:
    """Recursively watch ``source_dir`` and debounce relevant file changes.

    The watcher only reacts to regular files selected by ``path_filter``.
    Excluded or non-included changes neither trigger a callback nor reset the
    debounce timer. Directory changes are not reported directly; they only
    matter insofar as they produce a relevant file event.
    """

    def __init__(
        self,
        source_dir: str | Path,
        path_filter: PathFilter,
        callback: Callable[[], None],
        debounce_seconds: float,
        *,
        poll_interval: float | None = None,
    ) -> None:
        self._source = Path(source_dir).resolve()
        self._filter = path_filter

        if not callable(callback):
            raise WatcherError("callback must be callable")
        self._callback = callback

        try:
            debounce = float(debounce_seconds)
        except (TypeError, ValueError) as exc:
            raise WatcherError("debounce_seconds must be a number") from exc
        if debounce < 0:
            raise WatcherError("debounce_seconds must be >= 0")
        self._debounce = debounce

        if poll_interval is None:
            poll_interval = DEFAULT_POLL_INTERVAL
        try:
            poll_interval = float(poll_interval)
        except (TypeError, ValueError) as exc:
            raise WatcherError("poll_interval must be a number") from exc
        if poll_interval <= 0:
            raise WatcherError("poll_interval must be > 0")
        self._poll_interval = poll_interval

        self._stop_event = threading.Event()
        self._stop_event.set()  # not running until start()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_relevant = 0.0
        self._pending = False

    @property
    def poll_interval(self) -> float:
        """Return the configured polling interval in seconds."""
        return self._poll_interval

    # -- lifecycle ------------------------------------------------------

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        """Start watching. Safe to call more than once (no extra thread)."""
        with self._lock:
            if self.running:
                return
            if not self._source.is_dir():
                raise WatcherError(f"source_dir is not a directory: {self._source}")
            self._stop_event.clear()
            baseline = self._snapshot()
            if self._stop_event.is_set():
                return  # stop() was called while establishing the baseline
            self._last_relevant = 0.0
            self._pending = False
            self._thread = threading.Thread(
                target=self._run,
                args=(baseline,),
                name="ha-config2git-watcher",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop watching and cancel any pending debounce. Idempotent."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
            self._thread = None

    # -- internals ------------------------------------------------------

    def _run(self, previous: dict[str, tuple[int, int]]) -> None:
        while not self._stop_event.is_set():
            if self._stop_event.wait(self._poll_interval):
                return
            current = self._snapshot()
            relevant = self._relevant_changes(previous, current)
            previous = current

            now = time.monotonic()
            if relevant:
                self._last_relevant = now
                self._pending = True

            if self._pending and (now - self._last_relevant) >= self._debounce:
                self._pending = False
                if not self._stop_event.is_set():
                    self._callback()

    def _snapshot(self) -> dict[str, tuple[int, int]]:
        """Map relative POSIX paths to ``(mtime_ns, size)`` signatures.

        Excluded directories are pruned during traversal so their contents are
        never scanned. Directories that cannot contain any included file are
        pruned as well. Symlinks are never followed.
        """
        result: dict[str, tuple[int, int]] = {}
        stack: list[tuple[str, str]] = [(str(self._source), "")]
        while stack:
            directory, rel_dir = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if entry.is_symlink():
                            continue
                        rel = entry.name if rel_dir == "" else f"{rel_dir}/{entry.name}"
                        if entry.is_dir(follow_symlinks=False):
                            if self._filter.excludes(rel):
                                continue
                            if not self._filter.may_contain_included(rel):
                                continue
                            stack.append((entry.path, rel))
                        elif entry.is_file(follow_symlinks=False):
                            stat = entry.stat(follow_symlinks=False)
                            result[rel] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                # A directory may disappear between scandir calls; skip it.
                continue
        return result

    def _relevant_changes(
        self,
        previous: dict[str, tuple[int, int]],
        current: dict[str, tuple[int, int]],
    ) -> bool:
        for path, signature in current.items():
            if previous.get(path) != signature and self._filter.matches(path):
                return True
        for path in previous:
            if path not in current and self._filter.matches(path):
                return True
        return False

