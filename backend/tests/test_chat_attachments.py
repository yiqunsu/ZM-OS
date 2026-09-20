"""Shared private storage and post-migration orphan GC; API coverage is in test_agent_v2."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import AgentFileGcJob
from app.services import agent_gc_service
from app.services import chat_attachment_service as storage


def test_private_atomic_storage_and_path_boundary(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "CHAT_ATTACHMENT_DIR", str(tmp_path))
    storage._write_file("image.png", b"image")
    path = tmp_path / "image.png"
    assert path.read_bytes() == b"image"
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        storage._write_file("../escape.png", b"image")
    storage._delete_file("image.png")
    storage._delete_file("image.png")
    assert not list(tmp_path.iterdir())


async def test_retired_attachment_gc_retries_without_session(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "CHAT_ATTACHMENT_DIR", str(tmp_path))
    storage._write_file("retired.png", b"old screenshot")
    db_session.add(
        AgentFileGcJob(storage_key="retired.png", next_attempt_at=datetime(2000, 1, 1, tzinfo=UTC))
    )
    await db_session.commit()
    original = agent_gc_service._delete_file

    def disk_failure(key):
        raise OSError("temporarily unavailable")

    monkeypatch.setattr(agent_gc_service, "_delete_file", disk_failure)
    assert await agent_gc_service.collect_once(db_session)
    job = await db_session.scalar(select(AgentFileGcJob).where(AgentFileGcJob.storage_key == "retired.png"))
    assert job.status == "FAILED" and (tmp_path / "retired.png").exists()
    job.next_attempt_at = datetime(2000, 1, 1, tzinfo=UTC)
    await db_session.commit()
    monkeypatch.setattr(agent_gc_service, "_delete_file", original)
    assert await agent_gc_service.collect_once(db_session)
    await db_session.refresh(job)
    assert job.status == "SUCCEEDED" and not (tmp_path / "retired.png").exists()


@pytest.mark.parametrize("image_format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_active_upload_inspector_accepts_decodable_images(image_format, mime):
    import io

    from PIL import Image

    from app.services.agent_attachment_service import inspect_image

    output = io.BytesIO()
    Image.new("RGB", (4, 3)).save(output, format=image_format)
    assert inspect_image(output.getvalue()) == (mime, 4, 3)


@pytest.mark.parametrize("content", [b"not an image", b"\x89PNG\r\n\x1a\ntruncated"])
def test_active_upload_inspector_rejects_invalid_pixels(content):
    from fastapi import HTTPException

    from app.services.agent_attachment_service import inspect_image

    with pytest.raises(HTTPException) as error:
        inspect_image(content)
    assert error.value.detail["code"] == "INVALID_IMAGE"


def test_active_upload_inspector_enforces_byte_limit(monkeypatch):
    from fastapi import HTTPException

    from app.services import agent_attachment_service as upload

    monkeypatch.setattr(upload, "MAX_BYTES", 3)
    with pytest.raises(HTTPException) as error:
        upload.inspect_image(b"1234")
    assert error.value.detail["code"] == "ATTACHMENT_LIMIT"


def test_png_invalid_checksum_returns_input_error():
    import base64

    from fastapi import HTTPException

    from app.services.agent_attachment_service import inspect_image

    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII="
    )
    with pytest.raises(HTTPException) as error:
        inspect_image(image)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "INVALID_IMAGE"
