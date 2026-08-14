import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import runner
from app.core.database import get_db
from app.core.security import CurrentUser, get_current_user
from app.models import ChatMessage
from app.schemas.chat import (
    ChatMessageOut,
    ChatSessionOut,
    ConfirmRequest,
    OrderWorkspaceDraftRequest,
    SendMessageRequest,
    WorkspaceStateOut,
)
from app.services import chat_attachment_service, chat_service, schedule_service

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


def _pending_action(pending: ChatMessage) -> tuple[str, dict[str, Any]]:
    calls = pending.tool_calls
    if not isinstance(calls, list) or not calls or not isinstance(calls[0], dict):
        return "", {}
    call = calls[0]
    if isinstance(call.get("name"), str):
        args = call.get("args")
        return call["name"], args if isinstance(args, dict) else {}
    function = call.get("function")
    if not isinstance(function, dict) or not isinstance(function.get("name"), str):
        return "", {}
    raw_args = function.get("arguments")
    if not isinstance(raw_args, str):
        return function["name"], {}
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError:
        parsed = {}
    return function["name"], parsed if isinstance(parsed, dict) else {}


def _events(*events: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
    async def generate():
        for event in events:
            yield event

    return generate()


# ─── Sessions ───────────────────────────────────────────────────────────────


@router.get("/sessions", response_model=list[ChatSessionOut])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await chat_service.list_sessions(db, user.id)


@router.post("/sessions", response_model=ChatSessionOut)
async def create_session(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await chat_service.create_session(db, user.id)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    await chat_service.delete_session(db, session_id, user.id)


# ─── Chat ───────────────────────────────────────────────────────────────────


@router.get("/chat", response_model=list[ChatMessageOut])
async def get_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await chat_service.get_history(db, session_id, user.id)


@router.get("/attachments/{attachment_id}")
async def get_chat_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    path, mime_type = await chat_attachment_service.get_owned_attachment(
        db,
        attachment_id,
        user.id,
    )
    return FileResponse(
        path,
        media_type=mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/workspace/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_workspace(
    body: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    await chat_service.clear_workspace(db, body.session_id, user.id)


@router.get("/workspace", response_model=WorkspaceStateOut)
async def get_workspace(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    session = await chat_service.require_session(db, session_id, user.id)
    state = session.workspace_state if isinstance(session.workspace_state, dict) else {}
    response: dict[str, Any] = {"active_workspace": session.active_workspace}
    if session.active_workspace == "order_form" and isinstance(state.get("order_draft"), dict):
        response["order_draft"] = state["order_draft"]
    elif session.active_workspace == "schedule_plan":
        plan = await schedule_service.get_latest_draft(db, session_id, user.id)
        if plan is not None:
            response["schedule_plan"] = {
                "id": plan.id,
                "status": plan.status.value,
                "tasks": plan.tasks,
                "unassigned": plan.unassigned,
                "created_at": plan.created_at.isoformat(),
            }
    return response


@router.put("/workspace/order-draft", response_model=WorkspaceStateOut)
async def save_order_workspace_draft(
    body: OrderWorkspaceDraftRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    session = await chat_service.save_order_workspace_draft(
        db,
        body.session_id,
        user.id,
        body.draft.model_dump(),
    )
    return {
        "active_workspace": session.active_workspace,
        "order_draft": session.workspace_state["order_draft"],
    }


@router.post("/chat")
async def send_message(
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    content = (body.content or "").strip()
    await chat_service.require_session(db, body.session_id, user.id)
    if await chat_service.get_pending(db, body.session_id, user.id):
        raise HTTPException(409, "请先处理待确认的操作")

    return _sse(
        runner.stream_turn(
            body.session_id,
            content,
            user.id,
            user.email,
            body.image_data_url,
        )
    )


@router.post("/chat/confirm")
async def confirm(
    body: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    pending = await chat_service.get_pending(db, body.session_id, user.id, for_update=True)
    if pending is None:
        raise HTTPException(404, "没有待确认的操作")
    action, args = _pending_action(pending)
    if action == "submit_order_form":
        pending.is_pending = False
        await db.commit()
        return _sse(_events({"type": "form_submit"}))
    if action == "execute_schedule_plan":
        plan_id = str(args.get("plan_id") or "")
        if not plan_id:
            raise HTTPException(409, "待确认的排产方案无效")
        try:
            result = await schedule_service.apply_schedule_plan(db, plan_id, user.id)
            pending.is_pending = False
            session = await chat_service.require_session(db, body.session_id, user.id)
            session.active_workspace = None
            assistant_msg = ChatMessage(
                session_id=body.session_id,
                role="assistant",
                content=(
                    f"✅ 排产已执行：创建 {result['task_count']} 个生产任务，"
                    f"安排 {result['order_count']} 张订单。"
                ),
            )
            db.add(assistant_msg)
            await db.commit()
            await db.refresh(assistant_msg)
        except Exception:
            await db.rollback()
            raise
        return _sse(
            _events(
                {"type": "schedule_applied", "result": result},
                {"type": "panel", "panel": "schedule_plan", "action": "close"},
                {"type": "delta", "content": assistant_msg.content},
                {"type": "text_done", "message_id": assistant_msg.id, "user_message_id": ""},
            )
        )
    pending.is_pending = False
    await db.commit()

    return _sse(runner.stream_resume(body.session_id, "confirm", user.email))


@router.post("/chat/cancel")
async def cancel(
    body: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    pending = await chat_service.get_pending(db, body.session_id, user.id, for_update=True)
    if pending is None:
        raise HTTPException(404, "没有待取消的操作")
    action, _args = _pending_action(pending)
    await db.delete(pending)
    await db.commit()

    if action in {"submit_order_form", "execute_schedule_plan"}:
        return _sse(_events({"type": "confirmation_cancelled"}))

    return _sse(runner.stream_resume(body.session_id, "cancel", user.email))
