"""Unit tests for the main application entry point."""

from __future__ import annotations

import json
import signal
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1] / "ha_config2git" / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

import main as main_module  # noqa: E402
from git_backend import GitBackendError  # noqa: E402
from orchestrator import SyncRunResult  # noqa: E402
from sync import SyncError  # noqa: E402
from watcher import WatcherError  # noqa: E402


def _write_options(base: Path, **overrides) -> Path:
    options = {"github_repository": "test-org/test-repo"}
    options.update(overrides)
    path = base / "options.json"
    path.write_text(json.dumps(options), encoding="utf-8")
    return path


class MainTests(unittest.TestCase):
    def _make_app(self, base: Path, **kwargs):
        options_path = kwargs.pop("options_path", _write_options(base))
        orchestrator_factory = kwargs.pop("orchestrator_factory", None)
        watcher_factory = kwargs.pop("watcher_factory", None)

        orchestrator = mock.Mock()
        orchestrator.run_once.return_value = SyncRunResult(changed=False)

        if orchestrator_factory is None:
            orchestrator_factory = mock.Mock(return_value=orchestrator)
        if watcher_factory is None:
            watcher_factory = mock.Mock(return_value=mock.Mock())

        app = main_module.App(
            options_path=options_path,
            orchestrator_factory=orchestrator_factory,
            watcher_factory=watcher_factory,
            **kwargs,
        )
        return app, orchestrator_factory, watcher_factory

    def _run_and_shutdown(self, app):
        ready = threading.Event()
        with mock.patch.object(
            app, "_install_signal_handlers", side_effect=lambda: ready.set()
        ):
            thread = threading.Thread(target=app.run)
            thread.start()
            self.assertTrue(ready.wait(timeout=2.0))
            app._handle_signal(signal.SIGTERM, None)
            thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        return thread


    def test_successful_initialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app, orchestrator_factory, watcher_factory = self._make_app(base)

            code = app._initialize()

            self.assertIsNone(code)
            orchestrator_factory.assert_called_once()
            watcher_factory.assert_called_once()
            self.assertIsNotNone(app._orchestrator)
            self.assertIsNotNone(app._watcher)

    def test_config_error_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            missing = base / "missing" / "options.json"
            app, _, _ = self._make_app(base, options_path=missing)

            self.assertEqual(app.run(), 1)
            # No components were built.
            self.assertIsNone(app._orchestrator)
            self.assertIsNone(app._watcher)

    def test_uses_config_as_source_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app, orchestrator_factory, watcher_factory = self._make_app(base)
            app._initialize()

            self.assertEqual(orchestrator_factory.call_args.args[0], "/config")
            self.assertEqual(watcher_factory.call_args.args[0], "/config")

    def test_uses_data_repository_as_repository_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app, orchestrator_factory, _ = self._make_app(base)
            app._initialize()

            self.assertEqual(orchestrator_factory.call_args.args[1], "/data/repository")

    def test_component_start_error_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            def boom(*args, **kwargs):
                raise WatcherError("boom")

            app, _, _ = self._make_app(base, watcher_factory=boom)
            self.assertEqual(app._initialize(), 1)
            self.assertIsNone(app._watcher)

    def test_orchestrator_build_error_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            def boom(*args, **kwargs):
                raise SyncError("boom")

            app, _, _ = self._make_app(base, orchestrator_factory=boom)
            self.assertEqual(app._initialize(), 1)
            self.assertIsNone(app._orchestrator)


    def test_watcher_started_and_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app, _, _ = self._make_app(base)
            self._run_and_shutdown(app)

            self.assertIsNotNone(app._watcher)
            app._watcher.start.assert_called_once()
            app._watcher.stop.assert_called_once()

    def test_signal_handlers_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app, _, _ = self._make_app(base)
            with mock.patch.object(main_module.signal, "signal") as sig_signal:
                app._install_signal_handlers()

            registered = [call.args[0] for call in sig_signal.call_args_list]
            self.assertIn(signal.SIGTERM, registered)
            self.assertIn(signal.SIGINT, registered)
            for call in sig_signal.call_args_list:
                self.assertIs(call.args[1].__func__, app._handle_signal.__func__)
                self.assertIs(call.args[1].__self__, app)

    def test_handle_signal_sets_shutdown_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app, _, _ = self._make_app(base)
            app._shutdown_event = threading.Event()

            app._handle_signal(signal.SIGTERM, None)

            self.assertTrue(app._shutdown_event.is_set())


class CallbackTests(unittest.TestCase):
    def _make_app(self, base: Path):
        options = {"github_repository": "test-org/test-repo"}
        options_path = base / "options.json"
        options_path.write_text(json.dumps(options), encoding="utf-8")

        orchestrator = mock.Mock()
        orchestrator.run_once.return_value = SyncRunResult(changed=False)
        watcher = mock.Mock()

        app = main_module.App(
            options_path=options_path,
            orchestrator_factory=mock.Mock(return_value=orchestrator),
            watcher_factory=mock.Mock(return_value=watcher),
        )
        app._initialize()
        return app, orchestrator, watcher

    def test_callback_invokes_orchestrator(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app, orchestrator, _ = self._make_app(base)

            app._on_change()

            orchestrator.run_once.assert_called_once()

    def test_callback_is_wired_to_watcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app, _, _ = self._make_app(base)

            self.assertIs(app._watcher_factory.call_args.args[2].__func__, app._on_change.__func__)

    def test_callback_handles_sync_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app, orchestrator, _ = self._make_app(base)
            orchestrator.run_once.side_effect = SyncError("boom")

            app._on_change()  # must not raise

            orchestrator.run_once.assert_called_once()

    def test_callback_handles_git_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app, orchestrator, _ = self._make_app(base)
            orchestrator.run_once.side_effect = GitBackendError("boom")

            app._on_change()  # must not raise

            orchestrator.run_once.assert_called_once()


if __name__ == "__main__":
    unittest.main()


