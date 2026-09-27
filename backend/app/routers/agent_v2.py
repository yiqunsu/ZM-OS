"""Opt-in durable Agent transport; no model work runs in HTTP handlers."""

import asyncio
import json
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import CurrentUser, get_current_user
from app.models.base import generate_id
from app.schemas.agent import CreateSession, SendMessage, SessionAction
from app.schemas.agent.order_intake import (
    CloseItem,
    DraftPatch,
    ItemAction,
    NextItem,
    ScreenshotAction,
    SelectItem,
)
from app.schemas.agent.scheduling import ClosePlan, ScheduleDraftPatch, StartScheduling
from app.services import agent_attachment_service as attachments
from app.services import agent_query_service as queries
from app.services import agent_schedule_service as plans
from app.services import agent_session_service as service
from app.services import order_intake_item_service as intake
from app.services import order_screenshot_service as screenshots
from app.services.scheduling import service as schedules


class AgentRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def wrapped(request: Request):
            request_id = generate_id()
            try:
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    # Bound multipart before FastAPI spools files, including chunked uploads.
                    chunks, size = [], 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 6 * 1024 * 1024:
                            service.fail("ATTACHMENT_LIMIT", "请求内容过大", 413)
                        chunks.append(chunk)
                    request._body = b"".join(chunks)
                response = await handler(request)
            except HTTPException as exc:
                error = (
                    exc.detail
                    if isinstance(exc.detail, dict) and "code" in exc.detail
                    else {
                        "code": "AUTH_REQUIRED" if exc.status_code == 401 else "REQUEST_REJECTED",
                        "message": str(exc.detail),
                        "retryable": False,
                        "details": {},
                    }
                )
                response = JSONResponse(
                    {"error": error, "request_id": request_id},
                    status_code=exc.status_code,
                    headers=exc.headers,
                )
            except RequestValidationError:
                response = JSONResponse(
                    {
                        "error": {
                            "code": "INPUT_INVALID",
                            "message": "请求参数不符合要求",
                            "retryable": False,
                            "details": {},
                        },
                        "request_id": request_id,
                    },
                    status_code=422,
                )
            response.headers["X-Request-ID"] = request_id
            return response

        return wrapped


def enabled() -> None:
    if not settings.AGENT_V2_ENABLED:
        service.fail("AGENT_V2_DISABLED", "新版助手尚未开放", 503)


router = APIRouter(
    prefix="/agent/v2",
    tags=["agent-v2"],
    route_class=AgentRoute,
    dependencies=[Depends(get_current_user), Depends(enabled)],
)
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[CurrentUser, Depends(get_current_user)]
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


@router.post("/sessions", status_code=201)
async def create_session(body: CreateSession, db: Db, user: User, key: Key):
    return await service.create_session(db, user.id, key, body)


@router.get("/sessions")
async def list_sessions(
    db: Db,
    user: User,
    cursor: str | None = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=100),
    agent_type: Literal["ORDER_INTAKE", "SCHEDULING"] | None = None,
    status: Literal["ACTIVE", "ARCHIVED", "DELETING"] | None = None,
):
    return await queries.list_sessions(db, user.id, cursor, limit, agent_type, status)


@router.post("/scheduling/workspace")
async def scheduling_workspace(db: Db, user: User, key: Key):
    return await service.workspace(db, user.id, key, agent_type="SCHEDULING")


@router.post("/sessions/{sid}/schedule", status_code=202)
async def start_scheduling(sid: str, body: StartScheduling, db: Db, user: User, key: Key):
    return await service.accept_message(
        db,
        sid,
        user.id,
        SendMessage(
            client_message_id=key,
            expected_state_revision=body.expected_state_revision,
            content=f"为选中的 {len(body.order_ids)} 笔订单生成排单草稿",
        ),
        schedule_order_ids=body.order_ids,
    )


@router.post("/intake/workspace")
async def intake_workspace(db: Db, user: User, key: Key):
    return await service.workspace(db, user.id, key)


@router.get("/intake/screenshots")
async def intake_screenshots(
    db: Db,
    user: User,
    tab: Literal["pending", "created", "archived"] = "pending",
    cursor: str | None = Query(None, max_length=512),
    limit: int = Query(20, ge=1, le=50),
):
    return await screenshots.list_screenshots(db, user.id, tab, cursor, limit)


@router.delete("/intake/screenshots/{aid}")
async def delete_screenshot(aid: str, body: ScreenshotAction, db: Db, user: User, key: Key):
    return await screenshots.delete_screenshot(
        db,
        aid,
        user.id,
        key,
        expected_revision=body.expected_revision,
    )


@router.post("/intake/screenshots/{aid}/{action}")
async def archive_screenshot(
    aid: str,
    action: Literal["archive", "restore"],
    body: ScreenshotAction,
    db: Db,
    user: User,
    key: Key,
):
    return await screenshots.archive_screenshot(
        db,
        aid,
        user.id,
        key,
        archived=action == "archive",
        expected_revision=body.expected_revision,
    )


@router.get("/sessions/{sid}/snapshot")
async def snapshot(sid: str, db: Db, user: User):
    return await queries.snapshot(db, sid, user.id)


@router.post("/sessions/{sid}/messages", status_code=202)
async def send_message(sid: str, body: SendMessage, db: Db, user: User):
    return await service.accept_message(db, sid, user.id, body)


@router.post("/sessions/{sid}/recognize", status_code=202)
async def recognize_images(sid: str, body: SendMessage, db: Db, user: User):
    return await service.accept_message(db, sid, user.id, body, recognize_only=True)


@router.get("/sessions/{sid}/messages")
async def messages(
    sid: str,
    db: Db,
    user: User,
    cursor: int = Query(0, ge=0),
    before: int | None = Query(None, gt=0),
    limit: int = Query(50, ge=1, le=100),
):
    return await queries.messages(db, sid, user.id, cursor, before, limit)


@router.post("/sessions/{sid}/attachments", status_code=201)
async def upload(
    sid: str,
    db: Db,
    user: User,
    file: Annotated[UploadFile, File()],
    client_upload_id: Annotated[str, Form(min_length=1, max_length=128)],
):
    try:
        content = await file.read(attachments.MAX_BYTES + 1)
        return await attachments.upload(db, sid, user.id, client_upload_id, content)
    finally:
        await file.close()


@router.get("/attachments/{aid}/content")
async def attachment_content(aid: str, db: Db, user: User):
    path, mime = await attachments.owned_file(db, aid, user.id)
    return FileResponse(
        path,
        media_type=mime,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/runs/{rid}")
async def run_status(rid: str, db: Db, user: User):
    return await queries.run_status(db, rid, user.id)


@router.post("/runs/{rid}/retry", status_code=202)
async def retry(rid: str, body: SessionAction, db: Db, user: User, key: Key):
    return await service.retry_run(db, rid, user.id, key, body.expected_state_revision)


@router.get("/commands/{cid}")
async def command_result(cid: str, db: Db, user: User):
    return await queries.command_result(db, cid, user.id)


async def stream_events(db: AsyncSession, sid: str, uid: str, after: int):
    cursor = after
    heartbeat_at = asyncio.get_running_loop().time()
    while True:
        try:
            page = await queries.events_after(db, sid, uid, cursor, 200)
            # End the read transaction before yielding or waiting on the browser.
            await db.rollback()
        except HTTPException:
            await db.rollback()
            return
        for event in page["events"]:
            payload = json.dumps(jsonable_encoder(event), ensure_ascii=False)
            yield f'id: {event["seq"]}\nevent: {event["kind"]}\ndata: {payload}\n\n'
        cursor = page["cursor"]
        if len(page["events"]) == 200:
            continue
        if asyncio.get_running_loop().time() - heartbeat_at >= 15:
            yield ": heartbeat\n\n"
            heartbeat_at = asyncio.get_running_loop().time()
        await asyncio.sleep(0.5)


@router.get("/sessions/{sid}/events")
async def events(
    sid: str,
    db: Db,
    user: User,
    after: int = Query(0, ge=0),
    stream: bool = False,
    last_event_id: Annotated[str | None, Header()] = None,
):
    if last_event_id is not None:
        if not last_event_id.isdecimal() or len(last_event_id) > 18:
            service.fail("INVALID_CURSOR", "事件游标无效", 422)
        after = max(after, int(last_event_id))
    await service.require_session(db, sid, user.id)
    if not stream:
        return await queries.events_after(db, sid, user.id, after, 200)
    await db.rollback()
    return StreamingResponse(
        stream_events(db, sid, user.id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{sid}/archive")
async def archive(sid: str, db: Db, user: User, key: Key):
    return await service.change_status(db, sid, user.id, key, "ARCHIVE_SESSION")


@router.post("/sessions/{sid}/restore")
async def restore(sid: str, db: Db, user: User, key: Key):
    return await service.change_status(db, sid, user.id, key, "RESTORE_SESSION")


@router.delete("/sessions/{sid}", status_code=202)
async def delete_session(sid: str, db: Db, user: User, key: Key):
    return await service.change_status(db, sid, user.id, key, "DELETE_SESSION")


@router.get("/sessions/{sid}/items")
async def work_items(
    sid: str,
    db: Db,
    user: User,
    cursor: str = Query("0:0", pattern=r"^\d+:\d+$", max_length=48),
    limit: int = Query(50, ge=1, le=100),
):
    return await queries.work_items(db, sid, user.id, cursor, limit)


@router.get("/items/{iid}")
async def work_item(iid: str, db: Db, user: User):
    return await queries.work_item(db, iid, user.id)


@router.patch("/items/{iid}/draft")
async def patch_item(iid: str, body: DraftPatch, db: Db, user: User):
    session, item = await intake.require_item(db, iid, user.id)
    result = await intake.patch_draft(db, session, item, body.expected_revision, body.patch)
    await db.commit()
    return result


@router.post("/items/{iid}/recognize", status_code=202)
async def recognize_item(iid: str, body: ItemAction, db: Db, user: User, key: Key):
    return await intake.item_command(
        db, iid, user.id, key, "RECOGNIZE_ITEM", body.model_dump(exclude_defaults=True)
    )


@router.post("/items/{iid}/confirm")
async def confirm_item(iid: str, body: ItemAction, db: Db, user: User, key: Key):
    return await intake.item_command(
        db, iid, user.id, key, "CONFIRM_ORDER", body.model_dump(exclude_defaults=True)
    )


@router.post("/items/{iid}/defer")
async def defer_item(iid: str, body: ItemAction, db: Db, user: User, key: Key):
    return await intake.item_command(
        db, iid, user.id, key, "DEFER_ITEM", body.model_dump(exclude_defaults=True)
    )


@router.post("/items/{iid}/close")
async def close_item(iid: str, body: CloseItem, db: Db, user: User, key: Key):
    return await intake.item_command(
        db, iid, user.id, key, "CLOSE_ITEM", body.model_dump(exclude_defaults=True)
    )


@router.post("/items/{iid}/select", status_code=202)
async def select_item(iid: str, body: SelectItem, db: Db, user: User, key: Key):
    result = await intake.item_command(
        db, iid, user.id, key, "SELECT_ITEM", body.model_dump(exclude_defaults=True)
    )
    return JSONResponse(result, status_code=202 if result["run_id"] else 200)


@router.post("/sessions/{sid}/next-item", status_code=202)
async def next_item(sid: str, body: NextItem, db: Db, user: User, key: Key):
    result = await intake.next_item(db, sid, user.id, key, body.model_dump())
    return JSONResponse(result, status_code=202 if result["run_id"] else 200)


@router.get("/plans/{pid}")
async def get_plan(pid: str, db: Db, user: User):
    _, plan = await plans.require_plan(db, pid, user.id)
    stale = await schedules.plan_is_stale(db, plan)
    return {
        **plans.plan_snapshot(plan),
        "stale": stale,
        "stale_reasons": ["生产数据已变化，请重新生成"] if stale else [],
    }


@router.put("/plans/{pid}/draft")
async def patch_plan(pid: str, body: ScheduleDraftPatch, db: Db, user: User):
    return await plans.patch_plan(
        db, pid, user.id, body.expected_revision, [task.model_dump() for task in body.tasks]
    )


@router.post("/plans/{pid}/replace", status_code=202)
async def replace_plan(pid: str, body: ItemAction, db: Db, user: User, key: Key):
    return await plans.plan_command(db, pid, user.id, key, "REPLACE_PLAN", body.model_dump())


@router.post("/plans/{pid}/close")
async def close_plan(pid: str, body: ClosePlan, db: Db, user: User, key: Key):
    return await plans.plan_command(db, pid, user.id, key, "CLOSE_PLAN", body.model_dump())


@router.post("/plans/{pid}/apply")
async def apply_plan(pid: str, body: ItemAction, db: Db, user: User, key: Key):
    return await plans.plan_command(db, pid, user.id, key, "APPLY_PLAN", body.model_dump())
