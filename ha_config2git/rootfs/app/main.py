"""Application entry point for ha-config2git."""

from __future__ import annotations

import logging
import sys

from config import ConfigError, load_config_from_path

_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    logger = logging.getLogger("ha_config2git")

    try:
        config = load_config_from_path()
    except ConfigError as exc:
        logger.error("Invalid configuration: %s", exc)
        return 1

    logging.getLogger().setLevel(_LOG_LEVELS.get(config.log_level, logging.INFO))

    logger.info("Configuration loaded successfully:")
    for key, value in config.summary().items():
        logger.info("  %s = %s", key, value)

    logger.info(
        "Configuration phase complete; watcher, git and ssh are not implemented yet."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
