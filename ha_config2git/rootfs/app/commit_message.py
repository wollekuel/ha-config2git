"""Commit message template rendering for ha-config2git.

Turns a configurable template plus the outcome of a sync run into the subject
line that is handed to :class:`~git_backend.GitBackend`. This module is a pure,
side-effect-free helper: it performs no I/O, no shell calls, no git calls and
never reads file contents. It only combines relative paths and counts with a
user-provided template.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

# The only placeholders a template may use. Validation and rendering share this
# single whitelist so that they can never diverge.
SUPPORTED_PLACEHOLDERS = frozenset(
    {
        "changed_count",
        "changed_files",
        "added_count",
        "modified_count",
        "deleted_count",
    }
)

# A rendered commit subject must never exceed this length.
MAX_SUBJECT_LENGTH = 200

# At most this many paths are listed verbatim in ``{changed_files}``; the rest
# is summarized as ``… (+M more)``.
MAX_LISTED_FILES = 5

_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")

_INVALID_SYNTAX_MESSAGE = (
    "commit_message_template has invalid syntax: only simple {name} "
    "placeholders are supported"
)

_UNSUPPORTED_MESSAGE = (
    "commit_message_template contains an unsupported placeholder (supported: "
    + ", ".join(sorted(SUPPORTED_PLACEHOLDERS))
    + ")"
)


class TemplateError(ValueError):
    """Raised when a commit message template is invalid."""


def validate_template(template: str) -> None:
    """Raise :class:`TemplateError` if ``template`` is not valid.

    A valid template is arbitrary literal text that may contain zero or more
    ``{name}`` placeholders where ``name`` is one of
    :data:`SUPPORTED_PLACEHOLDERS`. Format specs, conversions, positional or
    attribute access and any other ``{}`` usage are rejected.

    Error messages never echo the template contents, so that accidentally
    pasted secrets are not leaked through logs or exceptions.
    """
    position = 0
    for match in _PLACEHOLDER_RE.finditer(template):
        if _contains_brace(template[position : match.start()]):
            raise TemplateError(_INVALID_SYNTAX_MESSAGE)
        if match.group(1) not in SUPPORTED_PLACEHOLDERS:
            raise TemplateError(_UNSUPPORTED_MESSAGE)
        position = match.end()
    if _contains_brace(template[position:]):
        raise TemplateError(_INVALID_SYNTAX_MESSAGE)


def render_commit_message(
    template: str,
    *,
    added: Sequence[str],
    modified: Sequence[str],
    deleted: Sequence[str],
) -> str:
    """Render ``template`` for the given change lists.

    The template must be valid (see :func:`validate_template`); it is validated
    again defensively so that rendering can never evaluate anything beyond the
    whitelisted placeholders. The result is deterministic: paths are sorted and
    the file list is shortened before the message is ever hard-truncated, so the
    ``… (+M more)`` representation is never cut in half.
    """
    validate_template(template)

    changed = sorted([*added, *modified, *deleted])
    counts: Mapping[str, str] = {
        "changed_count": str(len(changed)),
        "added_count": str(len(added)),
        "modified_count": str(len(modified)),
        "deleted_count": str(len(deleted)),
    }

    def render(values: Mapping[str, str]) -> str:
        return _PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], template)

    # Prefer listing as many paths as possible while staying within the length
    # limit; reduce the listed count instead of chopping the summary suffix.
    for listed in range(min(MAX_LISTED_FILES, len(changed)), -1, -1):
        values = {**counts, "changed_files": _format_file_list(changed, listed)}
        message = render(values)
        if len(message) <= MAX_SUBJECT_LENGTH:
            return message

    # Last resort: the fixed text alone exceeds the limit. Cap it at a code
    # point boundary (Python string slicing never splits a code point).
    values = {**counts, "changed_files": _format_file_list(changed, 0)}
    return render(values)[:MAX_SUBJECT_LENGTH]


def _format_file_list(files: Sequence[str], max_listed: int) -> str:
    if not files:
        return ""
    if len(files) <= max_listed:
        return ", ".join(files)
    listed = files[:max_listed]
    remaining = len(files) - max_listed
    if not listed:
        return f"… (+{remaining} more)"
    return ", ".join(listed) + f", … (+{remaining} more)"


def _contains_brace(text: str) -> bool:
    return "{" in text or "}" in text
