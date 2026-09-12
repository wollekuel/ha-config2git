"""Application entry point for ha-config2git.

Loads the configuration, prepares the SSH key for GitHub pushes, builds the
PathFilter, Orchestrator and Watcher, starts watching the Home Assistant
configuration directory and runs a single synchronization pass for every
relevant change. It blocks until SIGTERM/SIGINT and stops the watcher cleanly
on shutdown.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from pathlib import Path

from config import OPTIONS_PATH, ConfigError, load_config_from_path
from git_backend import GitBackendError
from orchestrator import Orchestrator
from pathfilter import PathFilter
from ssh import SshError, prepare_ssh, ssh_remote_url
from sync import SyncError
from watcher import Watcher, WatcherError

SOURCE_DIR = "/config"
REPOSITORY_DIR = "/data/repository"

_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class App:
    """Wires together the configuration and the sync components."""

    def __init__(
        self,
        *,
        source_dir: str | Path = SOURCE_DIR,
        repository_dir: str | Path = REPOSITORY_DIR,
        options_path: Path = OPTIONS_PATH,
        orchestrator_factory=Orchestrator,
        watcher_factory=Watcher,
        ssh_factory=prepare_ssh,
    ) -> None:
        self._source_dir = source_dir
        self._repository_dir = repository_dir
        self._options_path = options_path
        self._orchestrator_factory = orchestrator_factory
        self._watcher_factory = watcher_factory
        self._ssh_factory = ssh_factory

        self._log = logging.getLogger("ha_config2git")
        self._config = None
        self._ssh_command = None
        self._orchestrator = None
        self._watcher = None
        self._shutdown_event = None

    def run(self) -> int:
        """Run the application until shutdown, then stop the watcher."""
        code = self._initialize()
        if code is not None:
            return code

        try:
            self._watcher.start()
        except WatcherError as exc:
            self._log.error("Failed to start watcher: %s", exc)
            return 1

        self._shutdown_event = threading.Event()
        self._install_signal_handlers()
        self._log.info("Watching %s for changes.", self._source_dir)
        self._shutdown_event.wait()

        self._watcher.stop()
        self._log.info("Watcher stopped; shutdown complete.")
        return 0

    def _initialize(self) -> int | None:
        try:
            config = load_config_from_path(self._options_path)
        except ConfigError as exc:
            self._log.error("Invalid configuration: %s", exc)
            return 1

        self._config = config
        logging.getLogger().setLevel(_LOG_LEVELS.get(config.log_level, logging.INFO))
        self._log.info("Configuration loaded:")
        for key, value in config.summary().items():
            self._log.info("  %s = %s", key, value)

        try:
            ssh_setup = self._ssh_factory(config.ssh_private_key)
        except SshError as exc:
            self._log.error("SSH setup failed: %s", exc)
            return 1
        self._ssh_command = ssh_setup.ssh_command

        try:
            self._build_components()
        except (WatcherError, SyncError, GitBackendError) as exc:
            self._log.error("Failed to initialize components: %s", exc)
            return 1

        return None

    def _build_components(self) -> None:
        path_filter = PathFilter(
            self._config.include_patterns, self._config.exclude_patterns
        )
        remote = ssh_remote_url(self._config.github_repository)
        self._orchestrator = self._orchestrator_factory(
            self._source_dir,
            self._repository_dir,
            remote,
            self._config,
            self._ssh_command,
        )
        self._watcher = self._watcher_factory(
            self._source_dir,
            path_filter,
            self._on_change,
            self._config.commit_debounce_seconds,
        )

    def _on_change(self) -> None:
        """Watcher callback: run one synchronization pass without crashing."""
        try:
            result = self._orchestrator.run_once()
        except (SyncError, GitBackendError) as exc:
            self._log.error("Synchronization run failed: %s", exc)
            return

        if result.changed:
            self._log.info(
                "Synchronized: %d copied, %d deleted (committed=%s, pushed=%s)",
                len(result.copied),
                len(result.deleted),
                result.committed,
                result.pushed,
            )
        else:
            self._log.debug("No changes to synchronize.")

    def _install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._handle_signal)

    def _handle_signal(self, signum: int, _frame) -> None:
        self._log.info("Received signal %s; shutting down.", signum)
        if self._shutdown_event is not None:
            self._shutdown_event.set()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    return App().run()


if __name__ == "__main__":
    sys.exit(main())


