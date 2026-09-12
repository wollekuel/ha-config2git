"""SSH setup for pushing to GitHub via a repository-scoped deploy key.

This module is the single place that derives the GitHub SSH remote URL and
prepares the SSH runtime files (private key and pinned ``known_hosts``). It has
no knowledge of Git, Home Assistant or the PathFilter and never runs git or a
subprocess itself.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

GITHUB_HOST = "github.com"
SSH_DIR = Path("/data/.ssh")
KEY_FILENAME = "id_github"
KNOWN_HOSTS_FILENAME = "known_hosts"

# Pinned GitHub SSH host keys, taken verbatim from the official documentation:
# https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
# DSA is intentionally omitted because GitHub is closing it down.
GITHUB_KNOWN_HOSTS = """github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=
"""


class SshError(RuntimeError):
    """Raised when the SSH setup (private key) is invalid."""


@dataclass(frozen=True)
class SshSetup:
    """Resolved SSH runtime configuration produced by :func:`prepare_ssh`."""

    key_path: Path
    known_hosts_path: Path
    ssh_command: str


def ssh_remote_url(repository: str) -> str:
    """Return the deterministic GitHub SSH remote URL for ``owner/repository``.

    ``repository`` must already be normalized (no ``.git`` suffix and no
    trailing slash); normalization happens exclusively in ``config.py``.
    """
    return f"git@{GITHUB_HOST}:{repository}.git"


def prepare_ssh(private_key: str, ssh_dir: Path = SSH_DIR) -> SshSetup:
    """Write the deploy key and pinned known_hosts, then build the ssh command.

    The key is written with mode 0600 inside a 0700 directory and is never
    logged, returned in an error message or otherwise leaked.

    Raises :class:`SshError` when the key is missing or obviously invalid.
    """
    if not private_key or not private_key.strip():
        raise SshError("no SSH private key configured")
    if "-----BEGIN" not in private_key or "PRIVATE KEY" not in private_key:
        raise SshError("configured SSH private key does not look like a valid key")

    ssh_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)

    key_path = ssh_dir / KEY_FILENAME
    key_path.write_text(private_key.rstrip() + chr(10), encoding="utf-8")
    os.chmod(key_path, 0o600)

    known_hosts_path = ssh_dir / KNOWN_HOSTS_FILENAME
    known_hosts_path.write_text(GITHUB_KNOWN_HOSTS, encoding="utf-8")
    os.chmod(known_hosts_path, 0o644)

    return SshSetup(
        key_path=key_path,
        known_hosts_path=known_hosts_path,
        ssh_command=_build_ssh_command(key_path, known_hosts_path),
    )


def _build_ssh_command(key_path: Path, known_hosts_path: Path) -> str:
    """Return a shell-quoted ``ssh`` invocation for ``GIT_SSH_COMMAND``."""
    return shlex.join(
        [
            "ssh",
            "-i",
            str(key_path),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={known_hosts_path}",
            "-o",
            "BatchMode=yes",
            "-o",
            "LogLevel=ERROR",
        ]
    )
