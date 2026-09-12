"""Unit tests for the SSH setup (deploy key + pinned known_hosts)."""

from __future__ import annotations

import shlex
import stat
import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "ha_config2git" / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

import ssh  # noqa: E402
from ssh import SshError  # noqa: E402

_VALID_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "fake-key-material-not-a-real-key\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)


class RemoteUrlTests(unittest.TestCase):
    def test_remote_url_from_repository(self):
        self.assertEqual(
            ssh.ssh_remote_url("owner/repository"),
            "git@github.com:owner/repository.git",
        )

    def test_remote_url_assumes_normalized_repository(self):
        self.assertEqual(
            ssh.ssh_remote_url("test-org/test-repo"),
            "git@github.com:test-org/test-repo.git",
        )

    def test_remote_url_is_deterministic(self):
        self.assertEqual(ssh.ssh_remote_url("a/b"), ssh.ssh_remote_url("a/b"))

    def test_remote_url_uses_github_host(self):
        self.assertTrue(ssh.ssh_remote_url("a/b").startswith("git@github.com:"))


class PrepareSshTests(unittest.TestCase):
    def test_key_written_with_restrictive_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp) / ".ssh"
            setup = ssh.prepare_ssh(_VALID_KEY, ssh_dir=ssh_dir)

            self.assertEqual(stat.S_IMODE(ssh_dir.stat().st_mode), 0o700)
            self.assertEqual(
                stat.S_IMODE((ssh_dir / "id_github").stat().st_mode), 0o600
            )
            self.assertEqual(setup.key_path, ssh_dir / "id_github")

    def test_known_hosts_written_with_pinned_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp) / ".ssh"
            setup = ssh.prepare_ssh(_VALID_KEY, ssh_dir=ssh_dir)

            known_hosts = ssh_dir / "known_hosts"
            self.assertEqual(
                known_hosts.read_text(encoding="utf-8"), ssh.GITHUB_KNOWN_HOSTS
            )
            self.assertEqual(stat.S_IMODE(known_hosts.stat().st_mode), 0o644)
            self.assertEqual(setup.known_hosts_path, known_hosts)

    def test_key_written_with_clean_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp) / ".ssh"
            ssh.prepare_ssh(_VALID_KEY, ssh_dir=ssh_dir)
            content = (ssh_dir / "id_github").read_text(encoding="utf-8")
            self.assertTrue(content.startswith("-----BEGIN"))
            self.assertTrue(content.endswith("-----END OPENSSH PRIVATE KEY-----\n"))

    def test_prepare_ssh_overwrites_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp) / ".ssh"
            ssh.prepare_ssh(_VALID_KEY, ssh_dir=ssh_dir)
            key_path = ssh_dir / "id_github"
            key_path.write_text("stale", encoding="utf-8")
            ssh.prepare_ssh(_VALID_KEY, ssh_dir=ssh_dir)
            self.assertNotEqual(key_path.read_text(encoding="utf-8"), "stale")


class SshCommandTests(unittest.TestCase):
    def test_contains_expected_security_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp) / ".ssh"
            setup = ssh.prepare_ssh(_VALID_KEY, ssh_dir=ssh_dir)

            command = setup.ssh_command
            self.assertIn("IdentitiesOnly=yes", command)
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn(f"UserKnownHostsFile={ssh_dir / 'known_hosts'}", command)
            self.assertIn("BatchMode=yes", command)
            self.assertIn(f"-i {ssh_dir / 'id_github'}", command)

    def test_forbids_insecure_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp) / ".ssh"
            setup = ssh.prepare_ssh(_VALID_KEY, ssh_dir=ssh_dir)

            self.assertNotIn("StrictHostKeyChecking=no", setup.ssh_command)
            self.assertNotIn("/dev/null", setup.ssh_command)

    def test_ssh_command_quotes_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp) / "my ssh dir"
            setup = ssh.prepare_ssh(_VALID_KEY, ssh_dir=ssh_dir)

            parts = shlex.split(setup.ssh_command)
            self.assertIn(str(ssh_dir / "id_github"), parts)
            self.assertIn("IdentitiesOnly=yes", parts)
            self.assertIn("StrictHostKeyChecking=yes", parts)


class ValidationTests(unittest.TestCase):
    def test_empty_key_rejected(self):
        for bad in ("", "   \n\t"):
            with self.assertRaises(SshError):
                ssh.prepare_ssh(bad)

    def test_invalid_key_rejected(self):
        with self.assertRaises(SshError):
            ssh.prepare_ssh("this is not a private key")

    def test_error_does_not_echo_key_material(self):
        garbage = "totally-not-a-key" * 10
        with self.assertRaises(SshError) as ctx:
            ssh.prepare_ssh(garbage)
        self.assertNotIn(garbage, str(ctx.exception))


class KnownHostsContentTests(unittest.TestCase):
    def test_known_hosts_is_not_empty(self):
        self.assertTrue(ssh.GITHUB_KNOWN_HOSTS.strip())

    def test_known_hosts_pins_ed25519(self):
        self.assertIn(
            "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl",
            ssh.GITHUB_KNOWN_HOSTS,
        )

    def test_known_hosts_pins_ecdsa(self):
        self.assertIn(
            "github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=",
            ssh.GITHUB_KNOWN_HOSTS,
        )

    def test_known_hosts_pins_rsa(self):
        self.assertIn(
            "github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=",
            ssh.GITHUB_KNOWN_HOSTS,
        )

    def test_known_hosts_omits_dsa(self):
        self.assertNotIn("ssh-dss", ssh.GITHUB_KNOWN_HOSTS)
        self.assertNotIn("ssh-dsa", ssh.GITHUB_KNOWN_HOSTS)

    def test_known_hosts_lines_are_github_entries(self):
        for line in ssh.GITHUB_KNOWN_HOSTS.splitlines():
            if line.strip():
                self.assertTrue(line.startswith("github.com "))


if __name__ == "__main__":
    unittest.main()
