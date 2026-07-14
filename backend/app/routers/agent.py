import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import runner
from app.core.database import get_db
from app.core.security import CurrentUser, get_current_user
from app.schemas.chat import ChatMessageOut, ChatSessionOut, ConfirmRequest, SendMessageRequest
from app.services import chat_service

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(get_current_user)])

_SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _sse(events: AsyncGenerator[dict[str, Any], None]) -> StreamingResponse:
    async def gen():
        async for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(gen(), headers=_SSE_HEADERS)


# ─── Sessions ───────────────────────────────────────────────────────────────


@router.get("/sessions", response_model=list[ChatSessionOut])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    return await chat_service.list_sessions(db)


@router.post("/sessions", response_model=ChatSessionOut)
async def create_session(db: AsyncSession = Depends(get_db)):
    return await chat_service.create_session(db)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    await chat_service.delete_session(db, session_id)


# ─── Chat ───────────────────────────────────────────────────────────────────


@router.get("/chat", response_model=list[ChatMessageOut])
async def get_history(session_id: str, db: AsyncSession = Depends(get_db)):
    return await chat_service.get_history(db, session_id)


@router.post("/chat")
async def send_message(
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(400, "消息不能为空")
    await chat_service.require_session(db, body.session_id)
    if await chat_service.get_pending(db, body.session_id):
        raise HTTPException(409, "请先处理待确认的操作")

    return _sse(runner.stream_turn(body.session_id, content, user.email))


@router.post("/chat/confirm")
async def confirm(
    body: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    pending = await chat_service.get_pending(db, body.session_id)
    if pending is None:
        raise HTTPException(404, "没有待确认的操作")
    pending.is_pending = False
    await db.commit()

    return _sse(runner.stream_resume(body.session_id, "confirm", user.email))


@router.post("/chat/cancel")
async def cancel(
    body: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    pending = await chat_service.get_pending(db, body.session_id)
    if pending is None:
        raise HTTPException(404, "没有待取消的操作")
    await db.delete(pending)
    await db.commit()

    return _sse(runner.stream_resume(body.session_id, "cancel", user.email))
