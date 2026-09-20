"""Validated staged uploads, scoped to a single typed Session."""

import asyncio
import hashlib
import io
import warnings
from datetime import UTC, datetime, timedelta

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatAttachment
from app.models.base import generate_id
from app.services import chat_attachment_service as files
from app.services.agent_session_service import fail, require_idle, require_session

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 20_000_000


def inspect_image(content: bytes) -> tuple[str, int, int]:
    if not content or len(content) > MAX_BYTES:
        fail("ATTACHMENT_LIMIT", "图片不能为空且不得超过5MiB", 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in {"JPEG", "PNG"} or getattr(image, "n_frames", 1) != 1:
                    fail("INVALID_IMAGE", "仅支持单帧PNG或JPEG图片", 422)
                width, height = image.size
                if width * height > MAX_PIXELS:
                    fail("ATTACHMENT_LIMIT", "图片像素总数不得超过2000万", 413)
                mime = "image/png" if image.format == "PNG" else "image/jpeg"
                image.verify()
            # verify checks structure; load also rejects truncated pixel data.
            with Image.open(io.BytesIO(content)) as image:
                image.load()
                if len(image.getexif().tobytes()) > 65536:
                    fail("INVALID_IMAGE", "图片元数据过大", 422)
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,  # Pillow reports PNG checksum failures through SyntaxError.
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        fail("INVALID_IMAGE", "图片无法解码，请重新上传", 422)
    return mime, width, height


def attachment_dto(attachment: ChatAttachment) -> dict:
    return {
        name: getattr(attachment, name)
        for name in (
            "id",
            "status",
            "mime_type",
            "byte_size",
            "width_px",
            "height_px",
            "available",
            "expires_at",
        )
    }


async def upload(db: AsyncSession, sid: str, uid: str, client_upload_id: str, content: bytes) -> dict:
    session = await require_session(db, sid, uid, lock=True, writable=True)
    if session.agent_type != "ORDER_INTAKE":
        fail("IMAGE_NOT_ALLOWED", "排单助手不接受图片", 422)
    digest = hashlib.sha256(content).hexdigest()
    old = (
        await db.execute(
            select(ChatAttachment).where(
                ChatAttachment.session_id == sid, ChatAttachment.client_upload_id == client_upload_id
            )
        )
    ).scalar_one_or_none()
    if old:
        if old.sha256 != digest:
            fail("IDEMPOTENCY_MISMATCH", "该上传标识已用于不同图片")
        return attachment_dto(old)
    await require_idle(db, session)
    mime, width, height = await asyncio.to_thread(inspect_image, content)
    aid = generate_id()
    key = aid + (".png" if mime == "image/png" else ".jpg")
    await asyncio.to_thread(files._write_file, key, content)
    attachment = ChatAttachment(
        id=aid,
        session_id=sid,
        client_upload_id=client_upload_id,
        status="STAGED",
        position=None,
        mime_type=mime,
        byte_size=len(content),
        storage_key=key,
        width_px=width,
        height_px=height,
        sha256=digest,
        available=True,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(attachment)
    try:
        await db.commit()
    except BaseException:
        await db.rollback()
        # A later orphan sweep handles process death between the disk write and commit.
        await asyncio.to_thread(files._delete_file, key)
        raise
    return attachment_dto(attachment)


async def owned_file(db: AsyncSession, aid: str, uid: str):
    attachment = await db.get(ChatAttachment, aid)
    if attachment is None or attachment.session_id is None:
        fail("RESOURCE_NOT_FOUND", "附件不存在", 404)
    await require_session(db, attachment.session_id, uid)
    path = files._storage_path(attachment.storage_key)
    if not attachment.available or not path.is_file():
        fail("ATTACHMENT_UNAVAILABLE", "附件不可用", 404)
    return path, attachment.mime_type
