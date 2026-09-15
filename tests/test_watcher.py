"""Unit tests for the filesystem watcher."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "ha_config2git" / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from pathfilter import PathFilter  # noqa: E402
from watcher import DEFAULT_POLL_INTERVAL, Watcher, WatcherError  # noqa: E402


class Recorder:
    """Callable that counts invocations and supports condition-based waiting."""

    def __init__(self) -> None:
        self.calls = 0
        self._cond = threading.Condition()

    def __call__(self) -> None:
        with self._cond:
            self.calls += 1
            self._cond.notify_all()

    def wait_until(self, count: int, timeout: float) -> int:
        with self._cond:
            self._cond.wait_for(lambda: self.calls >= count, timeout=timeout)
            return self.calls


class _SpyFilter:
    """Wraps a PathFilter and records paths that it matched."""

    def __init__(self, inner: PathFilter) -> None:
        self.inner = inner
        self.matched_paths: list[str] = []

    def matches(self, relative_path: str) -> bool:
        matched = self.inner.matches(relative_path)
        if matched:
            self.matched_paths.append(relative_path)
        return matched

    def excludes(self, relative_path: str) -> bool:
        return self.inner.excludes(relative_path)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_watcher(
    source: Path,
    recorder: Recorder,
    include: tuple[str, ...] = ("*.yaml",),
    exclude: tuple[str, ...] = ("secrets.yaml", "*.tmp"),
    debounce: float = 0.1,
) -> Watcher:
    path_filter = PathFilter(include_patterns=list(include), exclude_patterns=list(exclude))
    return Watcher(source, path_filter, recorder, debounce, poll_interval=0.01)


class LifecycleTests(unittest.TestCase):
    def test_start_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)

            self.assertFalse(watcher.running)
            watcher.start()
            self.assertTrue(watcher.running)
            watcher.stop()
            self.assertFalse(watcher.running)
            watcher.stop()  # idempotent

    def test_non_directory_source_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            recorder = Recorder()
            watcher = _make_watcher(base / "missing", recorder)
            with self.assertRaises(WatcherError):
                watcher.start()

    def test_multiple_start_creates_single_watcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "a.yaml", "aaaa")
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)
            watcher.start()
            watcher.start()  # must be a no-op, no second thread

            _write(source / "a.yaml", "bbbbbb")
            self.assertEqual(recorder.wait_until(1, timeout=2.0), 1)
            self.assertEqual(recorder.wait_until(2, timeout=0.4), 1)
            watcher.stop()


class DetectionTests(unittest.TestCase):
    def test_relevant_file_change_triggers_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "a.yaml", "aaaa")
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)
            watcher.start()

            _write(source / "a.yaml", "bbbbbb")
            self.assertEqual(recorder.wait_until(1, timeout=2.0), 1)
            watcher.stop()

    def test_creation_of_relevant_file_triggers_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)
            watcher.start()

            _write(source / "b.yaml", "hello")
            self.assertEqual(recorder.wait_until(1, timeout=2.0), 1)
            watcher.stop()

    def test_deletion_of_relevant_file_triggers_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "a.yaml", "aaaa")
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)
            watcher.start()

            (source / "a.yaml").unlink()
            self.assertEqual(recorder.wait_until(1, timeout=2.0), 1)
            watcher.stop()

    def test_excluded_file_change_no_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "secrets.yaml", "old-secret")
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)
            watcher.start()

            _write(source / "secrets.yaml", "new-secret-value")
            self.assertEqual(recorder.wait_until(1, timeout=0.4), 0)
            watcher.stop()

    def test_not_included_file_change_no_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "notes.txt", "aaaa")
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)
            watcher.start()

            _write(source / "notes.txt", "bbbbbb")
            self.assertEqual(recorder.wait_until(1, timeout=0.4), 0)
            watcher.stop()

    def test_exclude_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "secrets.yaml", "old-secret")
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)
            watcher.start()

            # Matches include ("*.yaml") but is excluded ("secrets.yaml").
            _write(source / "secrets.yaml", "changed-secret")
            self.assertEqual(recorder.wait_until(1, timeout=0.4), 0)

            # Matches include and is not excluded.
            _write(source / "a.yaml", "data")
            self.assertEqual(recorder.wait_until(1, timeout=2.0), 1)
            watcher.stop()

    def test_nested_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            recorder = Recorder()
            watcher = _make_watcher(source, recorder, include=("**/*.yaml",))
            watcher.start()

            _write(source / "sub" / "dir" / "nested.yaml", "data")
            self.assertEqual(recorder.wait_until(1, timeout=2.0), 1)
            watcher.stop()


class DebounceTests(unittest.TestCase):
    def test_multiple_relevant_changes_single_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "a.yaml", "a")
            _write(source / "b.yaml", "b")
            _write(source / "c.yaml", "c")
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)
            watcher.start()

            _write(source / "a.yaml", "aaa")
            _write(source / "b.yaml", "bbb")
            _write(source / "c.yaml", "ccc")

            self.assertEqual(recorder.wait_until(1, timeout=2.0), 1)
            self.assertEqual(recorder.wait_until(2, timeout=0.4), 1)
            watcher.stop()

    def test_changes_after_debounce_separate_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "a.yaml", "first")
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)
            watcher.start()

            _write(source / "a.yaml", "second")
            self.assertEqual(recorder.wait_until(1, timeout=2.0), 1)

            _write(source / "a.yaml", "third")
            self.assertEqual(recorder.wait_until(2, timeout=2.0), 2)
            watcher.stop()

    def test_irrelevant_changes_do_not_reset_debounce(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "a.yaml", "old")
            _write(source / "excluded.tmp", "junk")
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)
            watcher.start()

            _write(source / "a.yaml", "new")
            end = time.monotonic() + 0.4
            i = 0
            while time.monotonic() < end:
                _write(source / "excluded.tmp", f"junk {i}")
                i += 1
                time.sleep(0.02)

            self.assertEqual(recorder.wait_until(1, timeout=1.0), 1)
            self.assertEqual(recorder.wait_until(2, timeout=0.3), 1)
            watcher.stop()

    def test_stop_prevents_pending_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "a.yaml", "old")
            recorder = Recorder()
            watcher = _make_watcher(source, recorder)
            watcher.start()

            _write(source / "a.yaml", "new")
            watcher.stop()

            self.assertEqual(recorder.wait_until(1, timeout=0.4), 0)
            self.assertFalse(watcher.running)


class PathFilterUsageTests(unittest.TestCase):
    def test_path_filter_is_actually_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "a.yaml", "old")
            recorder = Recorder()
            inner = PathFilter(include_patterns=["*.yaml"], exclude_patterns=["*.tmp"])
            spy = _SpyFilter(inner)
            watcher = Watcher(source, spy, recorder, 0.1, poll_interval=0.01)
            watcher.start()

            _write(source / "a.yaml", "new")
            self.assertEqual(recorder.wait_until(1, timeout=2.0), 1)
            self.assertIn("a.yaml", spy.matched_paths)
            watcher.stop()


class PollIntervalTests(unittest.TestCase):
    def test_default_poll_interval_avoids_busy_polling(self):
        self.assertGreaterEqual(DEFAULT_POLL_INTERVAL, 1.0)

    def test_explicit_poll_interval_is_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            recorder = Recorder()
            watcher = Watcher(
                source, PathFilter(["*.yaml"], []), recorder, 0.1, poll_interval=0.25
            )
            self.assertEqual(watcher.poll_interval, 0.25)

    def test_default_poll_interval_applied_when_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            recorder = Recorder()
            watcher = Watcher(source, PathFilter(["*.yaml"], []), recorder, 0.1)
            self.assertEqual(watcher.poll_interval, DEFAULT_POLL_INTERVAL)

    def test_zero_poll_interval_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            recorder = Recorder()
            with self.assertRaises(WatcherError):
                Watcher(source, PathFilter(["*.yaml"], []), recorder, 0.1, poll_interval=0)

    def test_negative_poll_interval_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            recorder = Recorder()
            with self.assertRaises(WatcherError):
                Watcher(source, PathFilter(["*.yaml"], []), recorder, 0.1, poll_interval=-1)


class SnapshotPruningTests(unittest.TestCase):
    def test_excluded_directory_not_in_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / "configuration.yaml", "x")
            _write(source / ".storage" / "core.config", "x")
            _write(source / ".storage" / "deep" / "nested.yaml", "x")
            recorder = Recorder()
            path_filter = PathFilter(
                include_patterns=["**"], exclude_patterns=[".storage/**"]
            )
            watcher = Watcher(source, path_filter, recorder, 0.1, poll_interval=0.01)

            snapshot = watcher._snapshot()

            self.assertIn("configuration.yaml", snapshot)
            self.assertNotIn(".storage/core.config", snapshot)
            self.assertNotIn(".storage/deep/nested.yaml", snapshot)

    def test_non_excluded_file_still_detected_with_excluded_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _write(source / ".storage" / "core.config", "x")
            recorder = Recorder()
            path_filter = PathFilter(
                include_patterns=["*.yaml"], exclude_patterns=[".storage/**"]
            )
            watcher = Watcher(source, path_filter, recorder, 0.1, poll_interval=0.01)
            watcher.start()

            _write(source / "a.yaml", "new")

            self.assertEqual(recorder.wait_until(1, timeout=2.0), 1)
            watcher.stop()


if __name__ == "__main__":
    unittest.main()


