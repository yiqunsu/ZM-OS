"""Private filesystem storage for persisted chat image attachments."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models import ChatAttachment, ChatMessage, ChatSession
from app.models.base import generate_id
from app.services.order_intake_service import decode_image_data_url

_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png"}


def attachment_metadata(attachment: ChatAttachment) -> dict[str, str | int]:
    return {
        "id": attachment.id,
        "mime_type": attachment.mime_type,
        "byte_size": attachment.byte_size,
    }


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


async def persist_user_message(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    content: str,
    image_data_url: str | None,
) -> ChatMessage:
    session = (
        await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(404, "Session 不存在")

    attachment: ChatAttachment | None = None
    storage_key: str | None = None
    if image_data_url:
        image = decode_image_data_url(image_data_url)
        attachment_id = generate_id()
        storage_key = f"{attachment_id}{_EXTENSIONS[image.mime_type]}"
        await asyncio.to_thread(_write_file, storage_key, image.content)
        attachment = ChatAttachment(
            id=attachment_id,
            mime_type=image.mime_type,
            byte_size=len(image.content),
            storage_key=storage_key,
        )

    message = ChatMessage(
        session_id=session_id,
        role="user",
        content=content,
        attachments=[],
    )
    if attachment is not None:
        message.attachments.append(attachment)
    db.add(message)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        if storage_key is not None:
            await delete_files([storage_key])
        raise
    return message


async def get_owned_attachment(
    db: AsyncSession,
    attachment_id: str,
    user_id: str,
) -> tuple[Path, str]:
    attachment = (
        await db.execute(
            select(ChatAttachment)
            .join(ChatMessage, ChatMessage.id == ChatAttachment.message_id)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(
                ChatAttachment.id == attachment_id,
                ChatSession.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise HTTPException(404, "附件不存在")
    path = _storage_path(attachment.storage_key)
    if not path.is_file():
        raise HTTPException(404, "附件不存在")
    return path, attachment.mime_type


async def delete_files(storage_keys: list[str]) -> None:
    for storage_key in storage_keys:
        try:
            await asyncio.to_thread(_delete_file, storage_key)
        except (OSError, ValueError) as err:
            logger.warning(
                "chat_attachment_cleanup_failed",
                storage_key=storage_key,
                error_type=type(err).__name__,
            )
