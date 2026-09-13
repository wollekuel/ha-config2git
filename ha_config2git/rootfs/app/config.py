"""Configuration handling for the ha-config2git app.

The configuration originates from the Home Assistant App configuration
(``config.yaml``) and is made available to the running container as
``/data/options.json`` by the Supervisor. The defaults defined here mirror the
``options`` block in ``config.yaml``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pathfilter import normalize_pattern

OPTIONS_PATH = Path("/data/options.json")

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

_OPENSSH_KEY_HEADER = "-----BEGIN OPENSSH PRIVATE KEY-----"
_OPENSSH_KEY_FOOTER = "-----END OPENSSH PRIVATE KEY-----"
_OPENSSH_KEY_RE = re.compile(
    re.escape(_OPENSSH_KEY_HEADER) + r"(?P<body>.*?)" + re.escape(_OPENSSH_KEY_FOOTER),
    re.DOTALL,
)
_WHITESPACE_RE = re.compile(r"\s+")
_BASE64_LINE_LENGTH = 64

DEFAULTS: dict[str, Any] = {
    "github_repository": "",
    "github_branch": "main",
    "git_author_name": "ha-config2git",
    "git_author_email": "ha-config2git@home-assistant",
    "commit_debounce_seconds": 30,
    "push_interval_seconds": 300,
    "log_level": "info",
    "ssh_private_key": "",
    "include_patterns": [
        "*.yaml",
        "*.yml",
        "*.json",
        "custom_components/**",
        "blueprints/**",
        "esphome/**",
    ],
    "exclude_patterns": [
        "secrets.yaml",
        "*.db",
        "*.db-*",
        ".storage/**",
    ],
}


class ConfigError(ValueError):
    """Raised when the application configuration is invalid."""


@dataclass(frozen=True)
class Config:
    """Validated, normalized application configuration."""

    github_repository: str
    github_branch: str
    git_author_name: str
    git_author_email: str
    commit_debounce_seconds: int
    push_interval_seconds: int
    log_level: str
    ssh_private_key: str
    include_patterns: tuple[str, ...]
    exclude_patterns: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        """Return a logging-safe representation without secrets."""
        # ssh_private_key is intentionally omitted: its content must never
        # appear in logs or summaries.
        return {
            "github_repository": self.github_repository,
            "github_branch": self.github_branch,
            "git_author_name": self.git_author_name,
            "git_author_email": self.git_author_email,
            "commit_debounce_seconds": self.commit_debounce_seconds,
            "push_interval_seconds": self.push_interval_seconds,
            "log_level": self.log_level,
            "include_patterns": list(self.include_patterns),
            "exclude_patterns": list(self.exclude_patterns),
        }


def _normalize_repository(value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError("github_repository must be a string")
    repository = value.strip()
    repository = repository.rstrip("/")
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not _REPOSITORY_RE.match(repository):
        raise ConfigError(
            f"github_repository must be in the format 'owner/repository' "
            f"(got: {repository!r})"
        )
    return repository


def _as_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_ssh_private_key(value: Any) -> str:
    """Return the SSH private key string (may be empty), canonicalized.

    The key is a secret: its content must never appear in summaries or error
    messages. Only the type is validated here; whether a key is required for
    operation is decided in a later integration step.

    OpenSSH private keys are normalized into canonical PEM lines so that keys
    whose line breaks were folded into spaces (as some Home Assistant UIs do)
    still load correctly. Anything that is not an OpenSSH key is returned
    unchanged.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError("ssh_private_key must be a string")
    key = value.strip()
    if not key:
        return ""
    return _canonicalize_openssh_key(key)


def _canonicalize_openssh_key(key: str) -> str:
    """Return ``key`` in canonical OpenSSH PEM form when it is one."""
    match = _OPENSSH_KEY_RE.search(key)
    if match is None:
        return key
    body = _WHITESPACE_RE.sub("", match.group("body"))
    if not body:
        return key
    wrapped = "\n".join(
        body[i : i + _BASE64_LINE_LENGTH]
        for i in range(0, len(body), _BASE64_LINE_LENGTH)
    )
    return f"{_OPENSSH_KEY_HEADER}\n{wrapped}\n{_OPENSSH_KEY_FOOTER}\n"


def _normalize_patterns(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"{field} must be a list of strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for pattern in value:
        if not isinstance(pattern, str):
            raise ConfigError(f"{field} must contain only strings")
        pattern = normalize_pattern(pattern)
        if not pattern:
            continue
        if pattern not in seen:
            seen.add(pattern)
            normalized.append(pattern)
    return tuple(normalized)


def load_config(options: Mapping[str, Any]) -> Config:
    """Validate and normalize the given options into a :class:`Config`.

    ``options`` is expected to be a mapping of option name to value as
    provided by the Supervisor in ``/data/options.json``. Missing options fall
    back to :data:`DEFAULTS`.
    """
    merged: dict[str, Any] = dict(DEFAULTS)
    merged.update(options)

    include_patterns = _normalize_patterns(
        merged.get("include_patterns"), "include_patterns"
    )
    if not include_patterns:
        raise ConfigError("include_patterns must contain at least one entry")

    return Config(
        github_repository=_normalize_repository(merged.get("github_repository")),
        github_branch=_as_non_empty_str(merged.get("github_branch"), "github_branch"),
        git_author_name=_as_non_empty_str(
            merged.get("git_author_name"), "git_author_name"
        ),
        git_author_email=_as_non_empty_str(
            merged.get("git_author_email"), "git_author_email"
        ),
        commit_debounce_seconds=merged["commit_debounce_seconds"],
        push_interval_seconds=merged["push_interval_seconds"],
        log_level=merged["log_level"],
        ssh_private_key=_normalize_ssh_private_key(merged.get("ssh_private_key")),
        include_patterns=include_patterns,
        exclude_patterns=_normalize_patterns(
            merged.get("exclude_patterns"), "exclude_patterns"
        ),
    )


def load_config_from_path(path: Path = OPTIONS_PATH) -> Config:
    """Load configuration from a JSON options file (default: ``/data/options.json``)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"options file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"options file is not valid JSON: {path}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("options must be a JSON object")

    return load_config(raw)

