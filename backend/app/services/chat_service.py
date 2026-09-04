"""Chat session + message persistence.

The ChatMessage table is the source of truth for the conversation as shown in the
UI (and for audit). LangGraph's checkpointer separately persists the graph's
execution state (keyed by session_id as thread_id) so interrupts can resume.
"""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ChatAttachment, ChatMessage, ChatSession
from app.services import chat_attachment_service


async def list_sessions(db: AsyncSession, user_id: str) -> list[dict]:
    result = await db.execute(
        select(
            ChatSession.id,
            ChatSession.title,
            ChatSession.created_at,
            func.count(ChatMessage.id).label("message_count"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == user_id)
        .group_by(ChatSession.id)
        .order_by(ChatSession.created_at.desc())
    )
    return [
        {"id": r.id, "title": r.title, "created_at": r.created_at, "message_count": r.message_count}
        for r in result.all()
    ]


async def create_session(db: AsyncSession, user_id: str) -> ChatSession:
    title = datetime.now().strftime("%Y-%m-%d %H:%M")
    session = ChatSession(title=title, user_id=user_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(db: AsyncSession, session_id: str, user_id: str) -> None:
    await require_session(db, session_id, user_id)
    storage_keys = list(
        (
            await db.execute(
                select(ChatAttachment.storage_key)
                .join(ChatMessage, ChatMessage.id == ChatAttachment.message_id)
                .where(ChatMessage.session_id == session_id)
            )
        ).scalars()
    )
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    await db.execute(delete(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id))
    await db.commit()
    await chat_attachment_service.delete_files(storage_keys)


async def get_history(db: AsyncSession, session_id: str, user_id: str) -> list[ChatMessage]:
    await require_session(db, session_id, user_id)
    result = await db.execute(
        select(ChatMessage)
        .options(selectinload(ChatMessage.attachments))
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return list(result.scalars().all())


async def require_session(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    *,
    for_update: bool = False,
) -> ChatSession:
    statement = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(404, "Session 不存在")
    return session


async def get_pending(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    *,
    for_update: bool = False,
) -> ChatMessage | None:
    await require_session(db, session_id, user_id)
    statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.is_pending.is_(True))
        .order_by(ChatMessage.created_at.desc())
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalars().first()


async def clear_workspace(db: AsyncSession, session_id: str, user_id: str) -> None:
    session = await require_session(db, session_id, user_id, for_update=True)
    session.active_workspace = None
    session.workspace_state = None
    await db.commit()


async def save_order_workspace_draft(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    draft: dict,
) -> ChatSession:
    session = await require_session(db, session_id, user_id, for_update=True)
    session.active_workspace = "order_form"
    session.workspace_state = {"order_draft": draft}
    await db.commit()
    await db.refresh(session)
    return session


async def add_message(
    db: AsyncSession,
    session_id: str,
    role: str,
    content: str | None = None,
    tool_calls: dict | list | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    is_pending: bool = False,
) -> ChatMessage:
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        is_pending=is_pending,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg
