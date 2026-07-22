"""Shared legacy-upload reference discovery and path normalization."""

from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID


MANAGED_FILE_PREFIX = "/api/files/"
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class LegacyUploadPathError(ValueError):
    """A stable path validation error which never includes the supplied path."""


def is_managed_file_reference(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(MANAGED_FILE_PREFIX)


def is_legacy_file_reference(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not is_managed_file_reference(value)
    )


def decode_audio_records(value: Any) -> Any:
    """Decode JSON returned as text by lightweight audit/test databases."""

    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def iter_legacy_file_references(
    value: Any,
    path: tuple[str | int, ...] = (),
) -> Iterator[tuple[tuple[str | int, ...], str]]:
    """Yield every nested non-managed string in a deterministic order."""

    if isinstance(value, dict):
        for key in sorted(value, key=str):
            yield from iter_legacy_file_references(value[key], path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_legacy_file_references(item, path + (index,))
    elif is_legacy_file_reference(value):
        yield path, value


def _is_within(path: Path, root: Path) -> bool:
    return path != root and root in path.parents


def _virtual_upload_relative(value: str) -> str | None:
    normalized = value
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("/uploads/"):
        return normalized[len("/uploads/") :]
    if normalized.startswith("uploads/"):
        return normalized[len("uploads/") :]
    return None


def resolve_legacy_upload_source(
    legacy_root: Path,
    database_value: str,
    *,
    tenant_id: UUID | None = None,
) -> Path:
    """Resolve one historical DB value exactly once beneath ``legacy_root``.

    Historical ``uploads/...``, ``/uploads/...`` and ``./uploads/...`` values
    are virtual upload-root paths, not paths to an additional nested directory.
    A native absolute path is accepted only when its resolved target remains
    beneath the configured root.  Cross-platform drive, UNC, URL, backslash,
    parent-segment and symlink tricks are rejected before the file is opened.
    """

    try:
        root = Path(legacy_root).resolve(strict=True)
    except (OSError, RuntimeError):
        raise LegacyUploadPathError("legacy uploads root is missing") from None
    if not isinstance(database_value, str) or not database_value.strip():
        raise LegacyUploadPathError("legacy file path is invalid")
    if database_value != database_value.strip() or "\x00" in database_value:
        raise LegacyUploadPathError("legacy file path is invalid")

    value = database_value
    virtual_relative = _virtual_upload_relative(value)
    native_path = Path(value)
    windows_path = PureWindowsPath(value)
    parsed = urlsplit(value)
    if parsed.scheme and not _WINDOWS_DRIVE.match(value):
        raise LegacyUploadPathError("legacy file URL is not allowed")
    if value.startswith("\\\\") or windows_path.drive.startswith("\\\\"):
        raise LegacyUploadPathError("legacy UNC path is not allowed")

    if virtual_relative is not None:
        if "\\" in virtual_relative:
            raise LegacyUploadPathError("legacy backslash path is not allowed")
        relative = PurePosixPath(virtual_relative)
        if not relative.parts or ".." in relative.parts:
            raise LegacyUploadPathError("legacy file path escapes uploads root")
        lexical = root.joinpath(*relative.parts)
    elif native_path.is_absolute():
        lexical = native_path
    else:
        if _WINDOWS_DRIVE.match(value):
            raise LegacyUploadPathError("legacy drive path is not allowed")
        if "\\" in value:
            raise LegacyUploadPathError("legacy backslash path is not allowed")
        relative = PurePosixPath(value)
        if not relative.parts or ".." in relative.parts or relative.is_absolute():
            raise LegacyUploadPathError("legacy file path escapes uploads root")
        lexical = root.joinpath(*relative.parts)

    try:
        unresolved = lexical.resolve(strict=False)
    except (OSError, RuntimeError):
        raise LegacyUploadPathError("legacy file path is invalid") from None
    if not _is_within(unresolved, root):
        raise LegacyUploadPathError("legacy file path escapes uploads root")

    try:
        relative_lexical = lexical.absolute().relative_to(root)
    except ValueError:
        raise LegacyUploadPathError("legacy file path escapes uploads root") from None
    current = root
    for part in relative_lexical.parts:
        current = current / part
        if current.is_symlink():
            raise LegacyUploadPathError("legacy file path contains a symbolic link")

    try:
        source = lexical.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError):
        raise LegacyUploadPathError("legacy file is missing") from None
    if not _is_within(source, root):
        raise LegacyUploadPathError("legacy file path escapes uploads root")
    if not source.is_file():
        raise LegacyUploadPathError("legacy file is not a regular file")

    relative_source = source.relative_to(root)
    if relative_source.parts and tenant_id is not None:
        try:
            path_tenant = UUID(relative_source.parts[0])
        except ValueError:
            path_tenant = None
        if path_tenant is not None and path_tenant != tenant_id:
            raise LegacyUploadPathError(
                "legacy file path belongs to another tenant"
            )
    return source
