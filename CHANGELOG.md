# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> **Entwicklungsstand `0.3.0-alpha.1`:** Dieser Stand existiert ausschließlich
> auf dem Branch `develop` und dient Tests in einer
> Home-Assistant-Testinstallation. Es handelt sich **nicht** um ein
> offizielles `0.3.0`-Release.

### Added

- Configurable commit messages via `commit_message_template` with placeholders
  `{changed_count}`, `{changed_files}`, `{added_count}`, `{modified_count}` and
  `{deleted_count}`. The default is now an informative message that lists the
  changed files (`Sync Home Assistant configuration: {changed_files}`).
- Commit message templates are validated at startup (unknown placeholders and
  invalid syntax are rejected). Rendered messages are capped at 200 characters
  and the file list is truncated deterministically (`… (+M more)`).

## [0.2.0]

### Added

- Home Assistant App (Add-on) packaging: `config.yaml`, `Dockerfile`, `run.sh`,
  and repository manifest (`repository.yaml`).
- Configuration handling with validation and normalization for:
  - `github_repository` (format `OWNER/REPOSITORY`, with `.git`/trailing-slash
    normalization),
  - `github_branch` (configurable branch used for commit and push),
  - `git_author_name`, `git_author_email`,
  - `commit_debounce_seconds`, `push_interval_seconds`, `log_level`,
  - `ssh_private_key` (OpenSSH private key canonicalization),
  - `include_patterns` and `exclude_patterns`.
- Include/exclude path filter (`*` matches within a segment, `**` across
  segments, exclude patterns win).
- Filesystem watcher with configurable debounce.
- Local Git backend: `init`, `open`, branch handling, staging, commit, and push.
- Sync of `/config` into the local repository at `/data/repository`.
- Orchestrator that ties sync → commit → push together.
- GitHub SSH remote derived from `github_repository`
  (`git@github.com:OWNER/REPOSITORY.git`).
- SSH setup for GitHub: repository-scoped deploy key, pinned `known_hosts`
  (GitHub host keys), and a per-push `GIT_SSH_COMMAND` (the global environment
  is never modified).
- Secure private key handling: written with restrictive permissions, never
  logged, and omitted from the configuration summary.
- Application entry point with signal handling and logging.

### Fixed

- Normalization of OpenSSH private keys whose line breaks were folded into
  spaces by the Home Assistant UI (avoids
  `Load key ... error in libcrypto: unsupported`).

### Known limitations

- `push_interval_seconds` is reserved but not yet used (no periodic push; a
  push happens only after a commit).
- The watcher uses polling (`os.scandir`), not inotify.
- The commit message is fixed (`Sync Home Assistant configuration`).
- Only OpenSSH-format private keys are normalized; other PEM formats are
  passed through unchanged.
- No force push is performed; a repository with incompatible existing history
  can fail the first push with a non-fast-forward error.

### Validation

- A real end-to-end test in Home Assistant succeeded: a change under `/config`
  was detected, committed, and pushed to a GitHub repository via the deploy
  key.
