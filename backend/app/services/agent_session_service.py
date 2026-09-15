"""v2 acceptance is a short transaction, never a model execution."""

from datetime import UTC, datetime

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentCommand,
    AgentRun,
    ChatAttachment,
    ChatMessage,
    ChatSession,
    OrderIntakeItem,
)
from app.models.agent import OPEN_RUN_STATUSES
from app.models.base import generate_id
from app.schemas.agent import CreateSession, SendMessage
from app.services.agent_event_service import append_event, canonical_hash
from app.services.agent_projections import accepted_dto, run_dto, session_dto


def fail(code: str, message: str, status: int = 409) -> None:
    raise HTTPException(status, {"code": code, "message": message, "retryable": False, "details": {}})


async def require_session(
    db: AsyncSession, sid: str, uid: str, *, lock: bool = False, writable: bool = False
) -> ChatSession:
    query = select(ChatSession).where(
        ChatSession.id == sid, ChatSession.user_id == uid, ChatSession.agent_type != "LEGACY"
    )
    if lock:
        query = query.with_for_update()
    session = (await db.execute(query.execution_options(populate_existing=True))).scalar_one_or_none()
    if session is None:
        fail("RESOURCE_NOT_FOUND", "会话不存在", 404)
    if session.status == "DELETING":
        fail("SESSION_DELETING", "会话正在删除", 410)
    if writable and session.status != "ACTIVE":
        fail("SESSION_ARCHIVED", "请先恢复会话")
    return session


async def open_run(db: AsyncSession, sid: str) -> AgentRun | None:
    return (
        await db.execute(
            select(AgentRun).where(AgentRun.session_id == sid, AgentRun.status.in_(OPEN_RUN_STATUSES))
        )
    ).scalar_one_or_none()


async def require_idle(db: AsyncSession, session: ChatSession) -> None:
    if await open_run(db, session.id):
        fail("SESSION_BUSY", "本轮仍在处理，请稍后再试")


def require_revision(session: ChatSession, expected: int) -> None:
    if session.state_revision != expected:
        fail("SESSION_STATE_CHANGED", "会话状态已更新，请刷新后重试")


async def command_replay(db: AsyncSession, uid: str, key: str, request_hash: str) -> AgentCommand | None:
    # Key lock precedes Session locks; CREATE_SESSION has no Session row to lock yet.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 7301))"), {"key": f"{uid}:{key}"}
    )
    command = (
        await db.execute(
            select(AgentCommand).where(AgentCommand.user_id == uid, AgentCommand.idempotency_key == key)
        )
    ).scalar_one_or_none()
    if command and command.request_hash != request_hash:
        fail("IDEMPOTENCY_MISMATCH", "该操作标识已用于不同请求")
    if command:
        await require_session(db, command.session_id, uid)
    return command


async def create_session(db: AsyncSession, uid: str, key: str, body: CreateSession) -> dict:
    digest = canonical_hash({"operation": "CREATE_SESSION", **body.model_dump()})
    existing = await command_replay(db, uid, key, digest)
    if existing:
        return existing.result
    session = ChatSession(
        id=generate_id(),
        user_id=uid,
        agent_type=body.agent_type,
        title=body.title or {"ORDER_INTAKE": "录入订单", "SCHEDULING": "智能排单"}[body.agent_type],
    )
    db.add(session)
    await db.flush()
    cid = generate_id()
    append_event(
        db,
        session,
        "session.created",
        {"agent_type": body.agent_type},
        actor_kind="USER",
        actor_user_id=uid,
        command_id=cid,
    )
    result = jsonable_encoder({"session": session_dto(session), "event_cursor": session.last_event_seq})
    db.add(
        AgentCommand(
            id=cid,
            user_id=uid,
            session_id=session.id,
            idempotency_key=key,
            kind="CREATE_SESSION",
            request_hash=digest,
            payload=body.model_dump(),
            http_status=201,
            result=result,
        )
    )
    await db.commit()
    return result


def new_run(
    session: ChatSession,
    *,
    trigger_kind: str,
    event_seq: int,
    message_id: str | None = None,
    command_id: str | None = None,
    work_item_id: str | None = None,
    queued_only: bool = False,
) -> AgentRun:
    from app.agent.registry import GRAPH_VERSION, configuration

    return AgentRun(
        id=generate_id(),
        session_id=session.id,
        trigger_kind=trigger_kind,
        trigger_message_id=message_id,
        trigger_command_id=command_id,
        work_item_id=work_item_id,
        input_event_seq=event_seq,
        graph_key={"ORDER_INTAKE": "order_intake", "SCHEDULING": "scheduling"}[session.agent_type],
        graph_version=GRAPH_VERSION,
        config_snapshot={
            **configuration(),
            "queued_only": queued_only,
            "intake_workbench": session.state.get("intake_workbench", False),
        },
    )


async def accept_message(
    db: AsyncSession,
    sid: str,
    uid: str,
    body: SendMessage,
    *,
    recognize_only: bool = False,
    schedule_order_ids: list[str] | None = None,
) -> dict:
    session = await require_session(db, sid, uid, lock=True, writable=True)
    digest = canonical_hash(
        {
            **body.model_dump(exclude={"client_message_id"}),
            **({"recognize_only": True} if recognize_only else {}),
            **({"selected_order_ids": schedule_order_ids} if schedule_order_ids is not None else {}),
        }
    )
    existing = (
        await db.execute(
            select(ChatMessage).where(
                ChatMessage.session_id == sid, ChatMessage.client_message_id == body.client_message_id
            )
        )
    ).scalar_one_or_none()
    if existing:
        if existing.request_hash != digest:
            fail("IDEMPOTENCY_MISMATCH", "该消息标识已用于不同内容")
        run = (
            await db.execute(
                select(AgentRun).where(
                    AgentRun.trigger_message_id == existing.id, AgentRun.trigger_kind == "MESSAGE"
                )
            )
        ).scalar_one()
        items = (
            await db.scalars(
                select(OrderIntakeItem)
                .where(OrderIntakeItem.source_message_id == existing.id)
                .order_by(OrderIntakeItem.queue_position, OrderIntakeItem.source_order_index)
            )
        ).all()
        accepted_revision = run.config_snapshot["accepted_state_revision"]
        return accepted_dto(existing, run, items, accepted_revision)
    if recognize_only:
        if session.agent_type != "ORDER_INTAKE" or not body.attachment_ids or body.content:
            fail("INPUT_INVALID", "请选择要识别的订单截图", 422)
        session.state = {**session.state, "intake_workbench": True}
    await require_idle(db, session)
    require_revision(session, body.expected_state_revision)
    if schedule_order_ids is not None:
        from app.services import schedule_service
        from app.services.scheduling_lock import lock_scheduling_inputs

        if session.agent_type != "SCHEDULING":
            fail("WRONG_AGENT_TYPE", "此工作区不支持排单", 422)
        if session.active_plan_id:
            fail("PLAN_EXISTS", "请先处理当前排单草稿")
        await lock_scheduling_inputs(db)
        pending = {order.id for order in await schedule_service._load_orders(db)}
        if (
            not schedule_order_ids
            or len(set(schedule_order_ids)) != len(schedule_order_ids)
            or not set(schedule_order_ids) <= pending
        ):
            fail("ORDER_SELECTION_STALE", "部分订单已不在待排列表，请刷新后重新选择", 409)
        session.state = {**session.state, "scheduling_order_ids": schedule_order_ids}
    if body.target_work_item_id is not None and body.target_work_item_id != session.active_work_item_id:
        fail("ACTION_STALE", "当前订单已切换，请刷新后重试")
    if not body.attachment_ids and body.target_work_item_id != session.active_work_item_id:
        fail("ACTION_STALE", "请刷新当前订单后再补充信息")
    if body.attachment_ids and session.agent_type != "ORDER_INTAKE":
        fail("IMAGE_NOT_ALLOWED", "排单助手不接受图片", 422)
    attachments = []
    now = datetime.now(UTC)
    for aid in body.attachment_ids:
        attachment = (
            await db.execute(
                select(ChatAttachment)
                .where(ChatAttachment.id == aid, ChatAttachment.session_id == sid)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if attachment is None:
            fail("RESOURCE_NOT_FOUND", "附件不存在", 404)
        if (
            attachment.status != "STAGED"
            or not attachment.available
            or not attachment.expires_at
            or attachment.expires_at <= now
        ):
            fail("ATTACHMENT_UNAVAILABLE", "附件已使用或过期，请重新上传")
        attachments.append(attachment)
    message = ChatMessage(
        id=generate_id(),
        session_id=sid,
        client_message_id=body.client_message_id,
        request_hash=digest,
        role="user",
        origin="USER",
        content=body.content,
        event_seq=session.last_event_seq + 1,
        work_item_id=None if attachments else session.active_work_item_id,
    )
    db.add(message)
    accepted = append_event(
        db,
        session,
        "message.accepted",
        {"role": "user", "text": body.content, "attachment_ids": body.attachment_ids},
        actor_kind="USER",
        actor_user_id=uid,
        message_id=message.id,
    )
    queued_only = bool(attachments and session.active_work_item_id)
    position = (
        await db.execute(
            select(func.coalesce(func.max(OrderIntakeItem.queue_position), 0)).where(
                OrderIntakeItem.session_id == sid
            )
        )
    ).scalar_one()
    items = []
    for index, attachment in enumerate(attachments):
        attachment.message_id, attachment.position = message.id, index
        attachment.status, attachment.expires_at = "BOUND", None
        item = OrderIntakeItem(
            id=generate_id(),
            session_id=sid,
            source_message_id=message.id,
            source_attachment_id=attachment.id,
            queue_position=position + index + 1,
            draft={"schema_version": 1, "spec_params": {}, "formula_mode": "none", "extra_notes": ""},
        )
        db.add(item)
        items.append(item)
        append_event(db, session, "work_item.queued", {"position": item.queue_position}, work_item_id=item.id)
    if items and session.active_work_item_id is None:
        await db.flush()
        first = (
            await db.execute(
                select(OrderIntakeItem)
                .join(ChatAttachment, ChatAttachment.id == OrderIntakeItem.source_attachment_id)
                .where(
                    ChatAttachment.intake_archived_at.is_(None),
                    OrderIntakeItem.session_id == sid,
                    OrderIntakeItem.status == "PENDING",
                )
                .order_by(OrderIntakeItem.queue_position, OrderIntakeItem.source_order_index)
                .limit(1)
            )
        ).scalar_one()
        first.status, first.activated_at = "ACTIVE", now
        first.revision += 1
        session.active_work_item_id = first.id
        append_event(db, session, "work_item.activated", {"revision": first.revision}, work_item_id=first.id)
    run = new_run(
        session,
        trigger_kind="MESSAGE",
        event_seq=accepted.seq,
        message_id=message.id,
        work_item_id=items[0].id
        if recognize_only
        else (None if queued_only else session.active_work_item_id),
        queued_only=queued_only,
    )
    db.add(run)
    session.state_revision += 1
    append_event(db, session, "run.queued", {}, run_id=run.id)
    append_event(db, session, "session.state_changed", {"state_revision": session.state_revision})
    await db.flush()
    run.config_snapshot = {
        **run.config_snapshot,
        "accepted_state_revision": session.state_revision,
        "intake_workbench": recognize_only,
        "scheduling_workbench": schedule_order_ids is not None,
        "selected_order_ids": schedule_order_ids,
    }
    result = accepted_dto(message, run, items, session.state_revision)
    await db.commit()
    return result


async def retry_run(db: AsyncSession, rid: str, uid: str, key: str, expected: int) -> dict:
    digest = canonical_hash({"operation": "RETRY_RUN", "run_id": rid, "expected_state_revision": expected})
    existing = await command_replay(db, uid, key, digest)
    if existing:
        return existing.result
    original = await db.get(AgentRun, rid)
    if original is None:
        fail("RESOURCE_NOT_FOUND", "执行记录不存在", 404)
    session = await require_session(db, original.session_id, uid, lock=True, writable=True)
    await require_idle(db, session)
    require_revision(session, expected)
    await db.refresh(original)
    latest = await db.scalar(
        select(AgentRun.id)
        .where(AgentRun.session_id == session.id)
        .order_by(AgentRun.queued_at.desc(), AgentRun.id.desc())
        .limit(1)
    )
    if original.status != "FAILED" or latest != rid:
        fail("ACTION_STALE", "只能重试最近一次失败的执行")
    if original.work_item_id and original.work_item_id != session.active_work_item_id:
        fail("ACTION_STALE", "该订单已切换，无法重试旧执行")
    cid = generate_id()
    event = append_event(
        db,
        session,
        "command.accepted",
        {"kind": "RETRY_RUN"},
        actor_kind="USER",
        actor_user_id=uid,
        command_id=cid,
    )
    run = new_run(
        session,
        trigger_kind="RETRY",
        event_seq=original.input_event_seq,
        message_id=original.trigger_message_id,
        command_id=cid,
        work_item_id=original.work_item_id,
        queued_only=original.config_snapshot.get("queued_only", False),
    )
    run.config_snapshot = {
        **run.config_snapshot,
        "intake_workbench": original.config_snapshot.get("intake_workbench", False),
        "scheduling_workbench": original.config_snapshot.get("scheduling_workbench", False),
        "selected_order_ids": original.config_snapshot.get("selected_order_ids"),
    }
    replacement = original.config_snapshot.get("retry_intent")
    if replacement and replacement.get("kind") == "REPLACE_PLAN":
        from app.models import SchedulePlan

        plan = await db.get(SchedulePlan, replacement["plan_id"])
        if (
            plan is None
            or session.active_plan_id != plan.id
            or plan.revision != replacement["expected_revision"]
        ):
            fail("DRAFT_REVISION_CONFLICT", "替换目标已更新，请重新确认替换")
        run.config_snapshot = {**run.config_snapshot, "retry_intent": replacement}
    run.retry_of_run_id = rid
    db.add(run)
    session.state_revision += 1
    append_event(db, session, "run.queued", {}, run_id=run.id, command_id=cid)
    append_event(db, session, "session.state_changed", {"state_revision": session.state_revision})
    await db.flush()
    result = jsonable_encoder(
        {
            "command_id": cid,
            "run": run_dto(run),
            "state_revision": session.state_revision,
            "event_cursor": event.seq,
        }
    )
    db.add(
        AgentCommand(
            id=cid,
            user_id=uid,
            session_id=session.id,
            idempotency_key=key,
            kind="RETRY_RUN",
            request_hash=digest,
            payload={"run_id": rid, "expected_state_revision": expected},
            target_id=rid,
            result_run_id=run.id,
            http_status=202,
            result=result,
        )
    )
    await db.commit()
    return result


async def change_status(db: AsyncSession, sid: str, uid: str, key: str, kind: str) -> dict:
    from app.models import AgentFileGcJob, AgentToolCall

    digest = canonical_hash({"operation": kind, "session_id": sid})
    # Deletion retries must remain readable after DELETING, without revealing content.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 7301))"), {"key": f"{uid}:{key}"}
    )
    old = (
        await db.execute(
            select(AgentCommand).where(AgentCommand.user_id == uid, AgentCommand.idempotency_key == key)
        )
    ).scalar_one_or_none()
    if old:
        if old.request_hash != digest:
            fail("IDEMPOTENCY_MISMATCH", "该操作标识已用于不同请求")
        return old.result
    session = await require_session(db, sid, uid, lock=True)
    cid = generate_id()
    if kind == "DELETE_SESSION":
        now = datetime.now(UTC)
        session.status, session.deletion_requested_at = "DELETING", now
        run = await open_run(db, sid)
        if run:
            run.status, run.finished_at, run.lease_token, run.lease_expires_at = "CANCELLED", now, None, None
            calls = (
                (
                    await db.execute(
                        select(AgentToolCall).where(
                            AgentToolCall.run_id == run.id, AgentToolCall.status == "STARTED"
                        )
                    )
                )
                .scalars()
                .all()
            )
            for call in calls:
                call.status, call.finished_at, call.error_code = "ABANDONED", now, "SESSION_DELETING"
                append_event(
                    db,
                    session,
                    "tool.abandoned",
                    {"error_code": "SESSION_DELETING"},
                    run_id=run.id,
                    tool_call_id=call.id,
                )
            append_event(db, session, "run.cancelled", {}, run_id=run.id)
        from app.agent.worker import audit_terminal

        if run:
            audit_terminal(db, session, run)
        attachments = (
            (await db.execute(select(ChatAttachment).where(ChatAttachment.session_id == sid))).scalars().all()
        )
        for attachment in attachments:
            db.add(
                AgentFileGcJob(
                    session_id=sid, attachment_id=attachment.id, storage_key=attachment.storage_key
                )
            )
        event_kind = "session.deleting"
    else:
        await require_idle(db, session)
        if kind == "ARCHIVE_SESSION":
            session.status, session.archived_at = "ARCHIVED", datetime.now(UTC)
            event_kind = "session.archived"
        elif kind == "RESTORE_SESSION":
            session.status, session.archived_at = "ACTIVE", None
            event_kind = "session.restored"
        else:
            raise ValueError("unsupported session command")
    session.state_revision += 1
    append_event(db, session, event_kind, {}, actor_kind="USER", actor_user_id=uid, command_id=cid)
    result = {
        "command_id": cid,
        "status": session.status,
        "state_revision": session.state_revision,
        "event_cursor": session.last_event_seq,
    }
    db.add(
        AgentCommand(
            id=cid,
            user_id=uid,
            session_id=sid,
            idempotency_key=key,
            kind=kind,
            request_hash=digest,
            payload={},
            http_status=202 if kind == "DELETE_SESSION" else 200,
            result=result,
        )
    )
    await db.commit()
    return result


async def workspace(db: AsyncSession, uid: str, key: str, *, agent_type: str = "ORDER_INTAKE") -> dict:
    from app.models import User
    from app.services.agent_projections import session_dto

    # Serialize concurrent first-entry clicks without creating a new public grouping entity.
    await db.scalar(select(User).where(User.id == uid).with_for_update())
    session = await db.scalar(
        select(ChatSession)
        .where(
            ChatSession.user_id == uid,
            ChatSession.agent_type == agent_type,
            ChatSession.status == "ACTIVE",
        )
        .order_by(ChatSession.active_plan_id.is_(None), ChatSession.created_at, ChatSession.id)
        .limit(1)
    )
    if session:
        result = {"session": session_dto(session)}
        await db.commit()
        return result
    return await create_session(db, uid, key, CreateSession(agent_type=agent_type))
