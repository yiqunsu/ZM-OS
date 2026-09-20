"""Authorized read use cases and consistent session snapshots."""

import base64
import json
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentCommand,
    AgentRun,
    ChatAttachment,
    ChatMessage,
    ChatSession,
    Customer,
    OrderIntakeItem,
    Product,
    SessionEvent,
)
from app.models.agent import OPEN_RUN_STATUSES
from app.services.agent_event_service import event_dto
from app.services.agent_projections import item_snapshot, message_dto, run_dto, session_dto
from app.services.agent_session_service import fail, open_run, require_session


async def events_after(db: AsyncSession, sid: str, uid: str, after: int, limit: int = 100) -> dict:
    await require_session(db, sid, uid)
    events = (
        (
            await db.execute(
                select(SessionEvent)
                .where(SessionEvent.session_id == sid, SessionEvent.seq > after)
                .order_by(SessionEvent.seq)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {"events": [event_dto(event) for event in events], "cursor": events[-1].seq if events else after}


async def snapshot(db: AsyncSession, sid: str, uid: str) -> dict:
    # The short Session lock shares writers' serialization point, so cursor and rows agree.
    session = await require_session(db, sid, uid, lock=True)
    messages = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == sid)
                .order_by(ChatMessage.event_seq.desc().nulls_last(), ChatMessage.id.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    recent = (
        (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.session_id == sid, AgentRun.status.not_in(OPEN_RUN_STATUSES))
                .order_by(AgentRun.queued_at.desc(), AgentRun.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    active = await open_run(db, sid)
    items = (
        (
            await db.execute(
                select(OrderIntakeItem)
                .where(OrderIntakeItem.session_id == sid)
                .order_by(OrderIntakeItem.queue_position, OrderIntakeItem.source_order_index)
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    result = {
        "session": session_dto(session),
        "event_cursor": session.last_event_seq,
        "messages": await message_dtos(db, list(reversed(messages))),
        "active_run": run_dto(active) if active else None,
        "recent_run_results": [run_dto(run) for run in recent],
        "work_items": await item_dtos(db, items),
    }
    # The current item and next queue head must remain available beyond the first history page.

    current_item = (
        await db.get(OrderIntakeItem, session.active_work_item_id) if session.active_work_item_id else None
    )
    next_item = await db.scalar(
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
    result["active_work_item"] = (await item_dtos(db, [current_item]))[0] if current_item else None
    result["next_work_item"] = (await item_dtos(db, [next_item]))[0] if next_item else None
    counts = (
        await db.execute(
            select(OrderIntakeItem.status, func.count())
            .where(OrderIntakeItem.session_id == sid)
            .group_by(OrderIntakeItem.status)
        )
    ).all()
    result["work_item_counts"] = dict(counts)
    await db.commit()
    return result


async def message_dtos(db: AsyncSession, messages: list[ChatMessage]) -> list[dict]:
    attachments = (
        await db.scalars(
            select(ChatAttachment)
            .where(ChatAttachment.message_id.in_([message.id for message in messages]))
            .order_by(ChatAttachment.position)
        )
    ).all()
    by_message: dict[str, list[dict]] = {}
    for attachment in attachments:
        by_message.setdefault(attachment.message_id, []).append(
            {
                name: getattr(attachment, name)
                for name in ("id", "position", "mime_type", "byte_size", "width_px", "height_px", "available")
            }
        )
    return [{**message_dto(message), "attachments": by_message.get(message.id, [])} for message in messages]


async def list_sessions(
    db: AsyncSession, uid: str, cursor: str | None, limit: int, agent_type: str | None, status: str | None
) -> dict:
    query = select(ChatSession).where(ChatSession.user_id == uid, ChatSession.agent_type != "LEGACY")
    if agent_type:
        query = query.where(ChatSession.agent_type == agent_type)
    if status:
        query = query.where(ChatSession.status == status)
    if cursor:
        try:
            timestamp, last_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            updated_at = datetime.fromisoformat(timestamp)
            if updated_at.tzinfo is None or not isinstance(last_id, str):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            fail("INVALID_CURSOR", "会话游标无效", 422)
        query = query.where(tuple_(ChatSession.updated_at, ChatSession.id) < tuple_(updated_at, last_id))
    rows = (
        (
            await db.execute(
                query.order_by(ChatSession.updated_at.desc(), ChatSession.id.desc()).limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps([last.updated_at.isoformat(), last.id]).encode()
        ).decode()
    return {
        "items": await session_dtos(db, rows[:limit]),
        "next_cursor": next_cursor,
    }


async def messages(db: AsyncSession, sid: str, uid: str, cursor: int, before: int | None, limit: int) -> dict:
    await require_session(db, sid, uid)
    if before is not None and cursor:
        fail("INPUT_INVALID", "不能同时使用前向和后向游标", 422)
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == sid,
                    ChatMessage.event_seq < before if before is not None else ChatMessage.event_seq > cursor,
                )
                .order_by(ChatMessage.event_seq.desc() if before is not None else ChatMessage.event_seq)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": await message_dtos(db, list(reversed(rows[:limit])) if before is not None else rows[:limit]),
        "next_cursor": rows[limit - 1].event_seq if len(rows) > limit else None,
    }


async def run_status(db: AsyncSession, rid: str, uid: str) -> dict:
    run = await db.get(AgentRun, rid)
    if run is None:
        fail("RESOURCE_NOT_FOUND", "执行记录不存在", 404)
    await require_session(db, run.session_id, uid)
    return run_dto(run)


async def command_result(db: AsyncSession, cid: str, uid: str) -> dict:
    command = await db.get(AgentCommand, cid)
    if command is None or command.user_id != uid:
        fail("RESOURCE_NOT_FOUND", "操作不存在", 404)
    await require_session(db, command.session_id, uid)
    return {"id": command.id, "http_status": command.http_status, "result": command.result}


async def work_items(db: AsyncSession, sid: str, uid: str, cursor: str, limit: int) -> dict:
    session = await require_session(db, sid, uid)
    if session.agent_type != "ORDER_INTAKE":
        fail("WRONG_AGENT_TYPE", "此会话没有录单工作项", 422)
    position, index = map(int, cursor.split(":"))
    rows = (
        await db.scalars(
            select(OrderIntakeItem)
            .where(
                OrderIntakeItem.session_id == sid,
                tuple_(OrderIntakeItem.queue_position, OrderIntakeItem.source_order_index)
                > (position, index),
            )
            .order_by(OrderIntakeItem.queue_position, OrderIntakeItem.source_order_index)
            .limit(limit + 1)
        )
    ).all()
    return {
        "items": await item_dtos(db, rows[:limit]),
        "next_cursor": f"{rows[limit - 1].queue_position}:{rows[limit - 1].source_order_index}"
        if len(rows) > limit
        else None,
    }


async def work_item(db: AsyncSession, iid: str, uid: str) -> dict:
    item = await db.get(OrderIntakeItem, iid)
    if item is None:
        fail("RESOURCE_NOT_FOUND", "工作项不存在", 404)
    await require_session(db, item.session_id, uid)
    return (await item_dtos(db, [item]))[0]


async def screenshot_positions(db: AsyncSession, items: list[OrderIntakeItem]) -> dict:
    """Display-only ranks over ALL live screenshots, before item pagination (Beijing time)."""
    if not items:
        return {}
    from app.services.order_screenshot_service import screenshot_rankings

    owners = select(ChatSession.user_id).where(ChatSession.id.in_({i.session_id for i in items}))
    ranked = screenshot_rankings(owners)
    rows = (
        (await db.execute(select(ranked).where(ranked.c.id.in_({i.source_attachment_id for i in items}))))
        .mappings()
        .all()
    )
    return {row["id"]: {key: value for key, value in row.items() if key != "id"} for row in rows}


async def item_dtos(db: AsyncSession, items: list[OrderIntakeItem]) -> list[dict]:
    positions = await screenshot_positions(db, items)
    customers = dict(
        (
            await db.execute(
                select(Customer.id, Customer.company).where(
                    Customer.id.in_([i.draft.get("customer_id") for i in items])
                )
            )
        ).all()
    )
    products = dict(
        (
            await db.execute(
                select(Product.id, Product.name).where(
                    Product.id.in_([i.draft.get("product_id") for i in items])
                )
            )
        ).all()
    )
    return [
        {
            **item_snapshot(i),
            **positions.get(i.source_attachment_id, {}),
            "customer_name": customers.get(i.draft.get("customer_id")),
            "product_name": products.get(i.draft.get("product_id")),
        }
        for i in items
    ]


async def session_dtos(db: AsyncSession, rows: list[ChatSession]) -> list[dict]:
    ids = [s.id for s in rows]
    images = dict(
        (
            await db.execute(
                select(ChatAttachment.session_id, func.count())
                .where(ChatAttachment.session_id.in_(ids), ChatAttachment.status == "BOUND")
                .group_by(ChatAttachment.session_id)
            )
        ).all()
    )
    orders = dict(
        (
            await db.execute(
                select(OrderIntakeItem.session_id, func.count())
                .where(OrderIntakeItem.session_id.in_(ids), OrderIntakeItem.recognition_status == "SUCCEEDED")
                .group_by(OrderIntakeItem.session_id)
            )
        ).all()
    )
    return [
        {**session_dto(s), "image_count": images.get(s.id, 0), "order_count": orders.get(s.id, 0)}
        for s in rows
    ]
