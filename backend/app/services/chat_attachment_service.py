"""Private filesystem storage for persisted chat image attachments."""

from __future__ import annotations

import os
from pathlib import Path

from app.core.config import settings
from app.models.base import generate_id


def _storage_root() -> Path:
    return Path(settings.CHAT_ATTACHMENT_DIR).expanduser().resolve()


def _storage_path(storage_key: str) -> Path:
    root = _storage_root()
    path = (root / storage_key).resolve()
    if path.parent != root:
        raise ValueError("invalid attachment storage key")
    return path


def _write_file(storage_key: str, content: bytes) -> None:
    path = _storage_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{generate_id()}.tmp")
    try:
        file_descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(file_descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _delete_file(storage_key: str) -> None:
    _storage_path(storage_key).unlink(missing_ok=True)
