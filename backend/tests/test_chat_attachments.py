import base64
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import ChatAttachment, ChatMessage, ChatSession, User, UserRole
from app.services import chat_attachment_service, chat_service


def _png_data_url(content: bytes = b"test") -> tuple[str, bytes]:
    raw = b"\x89PNG\r\n\x1a\n" + content
    return f"data:image/png;base64,{base64.b64encode(raw).decode()}", raw


async def test_attachment_round_trips_through_history_and_authenticated_download(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "CHAT_ATTACHMENT_DIR", str(tmp_path))
    session = ChatSession(title="attachment history", user_id="test-user")
    db_session.add(session)
    await db_session.commit()
    data_url, raw = _png_data_url()

    message = await chat_attachment_service.persist_user_message(
        db_session,
        session.id,
        "test-user",
        "图片订单",
        data_url,
    )
    attachment = message.attachments[0]
    assert Path(tmp_path, attachment.storage_key).stat().st_mode & 0o777 == 0o600

    history = await client.get("/api/agent/chat", params={"session_id": session.id})
    assert history.status_code == 200
    assert history.json()[0]["attachments"] == [
        {
            "id": attachment.id,
            "mime_type": "image/png",
            "byte_size": len(raw),
        }
    ]
    assert "storage_key" not in history.text

    download = await client.get(f"/api/agent/attachments/{attachment.id}")
    assert download.status_code == 200
    assert download.content == raw
    assert download.headers["content-type"] == "image/png"
    assert download.headers["cache-control"] == "private, no-store"
    assert download.headers["x-content-type-options"] == "nosniff"

    Path(tmp_path, attachment.storage_key).unlink()
    missing_file = await client.get(f"/api/agent/attachments/{attachment.id}")
    assert missing_file.status_code == 404
    assert str(tmp_path) not in missing_file.text


async def test_attachment_download_is_scoped_to_session_owner(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "CHAT_ATTACHMENT_DIR", str(tmp_path))
    other_user = User(
        email="attachment-other@filmos.local",
        password_hash="test-only-not-a-real-password-hash",
        role=UserRole.OPERATOR,
    )
    db_session.add(other_user)
    await db_session.flush()
    other_session = ChatSession(title="private attachment", user_id=other_user.id)
    db_session.add(other_session)
    await db_session.commit()
    data_url, _raw = _png_data_url()
    message = await chat_attachment_service.persist_user_message(
        db_session,
        other_session.id,
        other_user.id,
        "private",
        data_url,
    )

    response = await client.get(f"/api/agent/attachments/{message.attachments[0].id}")

    assert response.status_code == 404
    assert str(tmp_path) not in response.text


async def test_session_delete_removes_attachment_metadata_and_file(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "CHAT_ATTACHMENT_DIR", str(tmp_path))
    session = ChatSession(title="delete attachment", user_id="test-user")
    db_session.add(session)
    await db_session.commit()
    data_url, _raw = _png_data_url()
    message = await chat_attachment_service.persist_user_message(
        db_session,
        session.id,
        "test-user",
        "delete me",
        data_url,
    )
    attachment = message.attachments[0]
    stored_path = Path(tmp_path, attachment.storage_key)
    assert stored_path.is_file()

    response = await client.delete(f"/api/agent/sessions/{session.id}")

    assert response.status_code == 204
    assert not stored_path.exists()
    attachment_id = attachment.id
    db_session.expire_all()
    assert await db_session.get(ChatAttachment, attachment_id) is None


async def test_database_failure_compensates_written_attachment_file(
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "CHAT_ATTACHMENT_DIR", str(tmp_path))
    session = ChatSession(title="commit failure", user_id="test-user")
    db_session.add(session)
    await db_session.commit()
    session_id = session.id
    data_url, _raw = _png_data_url()

    async def fail_commit():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await chat_attachment_service.persist_user_message(
            db_session,
            session.id,
            "test-user",
            "must roll back",
            data_url,
        )

    assert list(tmp_path.iterdir()) == []
    messages = list(
        (
                await db_session.execute(
                    select(ChatMessage).where(ChatMessage.session_id == session_id)
                )
        ).scalars()
    )
    assert messages == []


async def test_file_write_failure_does_not_create_message(
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "CHAT_ATTACHMENT_DIR", str(tmp_path))
    session = ChatSession(title="file failure", user_id="test-user")
    db_session.add(session)
    await db_session.commit()
    data_url, _raw = _png_data_url()

    def fail_write(_storage_key: str, _content: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(chat_attachment_service, "_write_file", fail_write)

    with pytest.raises(OSError, match="disk full"):
        await chat_attachment_service.persist_user_message(
            db_session,
            session.id,
            "test-user",
            "must not persist",
            data_url,
        )

    assert list(tmp_path.iterdir()) == []
    history = await chat_service.get_history(db_session, session.id, "test-user")
    assert history == []
