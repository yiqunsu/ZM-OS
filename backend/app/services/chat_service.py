"""Chat session + message persistence.

The ChatMessage table is the source of truth for the conversation as shown in the
UI (and for audit). LangGraph's checkpointer separately persists the graph's
execution state (keyed by session_id as thread_id) so interrupts can resume.
"""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage, ChatSession


async def list_sessions(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(
            ChatSession.id,
            ChatSession.title,
            ChatSession.created_at,
            func.count(ChatMessage.id).label("message_count"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .group_by(ChatSession.id)
        .order_by(ChatSession.created_at.desc())
    )
    return [
        {"id": r.id, "title": r.title, "created_at": r.created_at, "message_count": r.message_count}
        for r in result.all()
    ]


async def create_session(db: AsyncSession) -> ChatSession:
    title = datetime.now().strftime("%Y-%m-%d %H:%M")
    session = ChatSession(title=title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(db: AsyncSession, session_id: str) -> None:
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    await db.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db.commit()


async def get_history(db: AsyncSession, session_id: str) -> list[ChatMessage]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return list(result.scalars().all())


async def require_session(db: AsyncSession, session_id: str) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(404, "Session 不存在")
    return session


async def get_pending(db: AsyncSession, session_id: str) -> ChatMessage | None:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.is_pending.is_(True))
        .order_by(ChatMessage.created_at.desc())
    )
    return result.scalars().first()


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
