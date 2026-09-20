"""User-wide screenshot list and atomic archive commands; runtime ownership stays in Sessions."""

import base64
import json
from datetime import UTC, date, datetime

from sqlalchemy import Date, cast, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentCommand, ChatAttachment, ChatSession, OrderIntakeItem
from app.models.base import generate_id
from app.services import agent_session_service as sessions
from app.services.agent_event_service import append_event, canonical_hash


def screenshot_rankings(user_ids):
    """Rank the complete visible collection, independent of status tabs and pagination."""
    day = cast(func.timezone("Asia/Shanghai", ChatAttachment.created_at), Date)
    archived = or_(ChatAttachment.intake_archived_at.is_not(None), ChatSession.status == "ARCHIVED")
    live = (
        select(OrderIntakeItem.id)
        .where(
            OrderIntakeItem.source_attachment_id == ChatAttachment.id,
            OrderIntakeItem.status != "CLOSED",
        )
        .exists()
    )
    return (
        select(
            ChatAttachment.id,
            ChatAttachment.created_at.label("source_uploaded_at"),
            day.label("source_day"),
            archived.label("source_archived"),
            ChatAttachment.intake_revision.label("screenshot_revision"),
            func.row_number()
            .over(
                partition_by=(ChatSession.user_id, day, archived),
                order_by=(ChatAttachment.created_at, ChatAttachment.id),
            )
            .label("source_day_position"),
        )
        .join(ChatSession, ChatSession.id == ChatAttachment.session_id)
        .where(
            ChatSession.user_id.in_(user_ids),
            ChatSession.agent_type == "ORDER_INTAKE",
            ChatSession.status.in_(["ACTIVE", "ARCHIVED"]),
            live,
        )
        .subquery()
    )


async def list_screenshots(db: AsyncSession, uid: str, tab: str, cursor: str | None, limit: int) -> dict:
    from app.models import AgentRun
    from app.models.agent import OPEN_RUN_STATUSES
    from app.services.agent_query_service import item_dtos

    ranked = screenshot_rankings([uid])
    pending = OrderIntakeItem.status.in_(["PENDING", "ACTIVE", "DEFERRED"])
    counts = dict(
        (
            await db.execute(
                select(OrderIntakeItem.status, func.count())
                .join(ranked, ranked.c.id == OrderIntakeItem.source_attachment_id)
                .where(~ranked.c.source_archived, OrderIntakeItem.status != "CLOSED")
                .group_by(OrderIntakeItem.status)
            )
        ).all()
    )
    counts["ARCHIVED"] = await db.scalar(
        select(func.count())
        .select_from(OrderIntakeItem)
        .join(ranked, ranked.c.id == OrderIntakeItem.source_attachment_id)
        .where(ranked.c.source_archived, OrderIntakeItem.status != "CLOSED")
    )
    eligible = (
        select(OrderIntakeItem.id)
        .where(
            OrderIntakeItem.source_attachment_id == ranked.c.id,
            OrderIntakeItem.status != "CLOSED"
            if tab == "archived"
            else OrderIntakeItem.status == "CREATED"
            if tab == "created"
            else pending,
        )
        .exists()
    )
    query = select(ranked).where(ranked.c.source_archived == (tab == "archived"), eligible)
    if cursor:
        try:
            day, uploaded, aid = json.loads(base64.urlsafe_b64decode(cursor))
            day, uploaded = date.fromisoformat(day), datetime.fromisoformat(uploaded)
            if uploaded.tzinfo is None or not isinstance(aid, str):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            sessions.fail("INVALID_CURSOR", "截图列表已变化，请刷新", 422)
        query = query.where(
            or_(
                ranked.c.source_day < day,
                (ranked.c.source_day == day)
                & (tuple_(ranked.c.source_uploaded_at, ranked.c.id) > (uploaded, aid)),
            )
        )
    rows = (
        (
            await db.execute(
                query.order_by(ranked.c.source_day.desc(), ranked.c.source_uploaded_at, ranked.c.id).limit(
                    limit + 1
                )
            )
        )
        .mappings()
        .all()
    )
    selected = rows[:limit]
    items = list(
        (
            await db.scalars(
                select(OrderIntakeItem)
                .where(
                    OrderIntakeItem.source_attachment_id.in_([r["id"] for r in selected]),
                    OrderIntakeItem.status != "CLOSED",
                )
                .order_by(OrderIntakeItem.source_order_index)
            )
        ).all()
    )
    dtos = await item_dtos(db, items)
    runs = dict(
        (
            await db.execute(
                select(AgentRun.session_id, AgentRun.work_item_id).where(
                    AgentRun.session_id.in_({i.session_id for i in items}),
                    AgentRun.status.in_(OPEN_RUN_STATUSES),
                )
            )
        ).all()
    )
    groups = [
        {
            **r,
            "items": [i for i in dtos if i["source_attachment_id"] == r["id"]],
        }
        for r in selected
    ]
    for group in groups:
        sid = group["items"][0]["session_id"]
        group["busy"] = sid in runs
        group["running_item_id"] = runs.get(sid)
    last = selected[-1] if len(rows) > limit else None
    return {
        "screenshots": groups,
        "counts": counts,
        "next_cursor": base64.urlsafe_b64encode(
            json.dumps(
                [
                    last["source_day"].isoformat(),
                    last["source_uploaded_at"].isoformat(),
                    last["id"],
                ]
            ).encode()
        ).decode()
        if last
        else None,
    }


async def archive_screenshot(
    db: AsyncSession,
    aid: str,
    uid: str,
    key: str,
    *,
    archived: bool,
    expected_revision: int,
) -> dict:
    kind = "ARCHIVE_SCREENSHOT" if archived else "RESTORE_SCREENSHOT"
    payload = {"archived": archived, "expected_revision": expected_revision}
    digest = canonical_hash({"operation": kind, "attachment_id": aid, **payload})
    replay = await sessions.command_replay(db, uid, key, digest)
    if replay:
        return replay.result
    attachment = await db.get(ChatAttachment, aid)
    if not attachment or not attachment.session_id:
        sessions.fail("RESOURCE_NOT_FOUND", "截图不存在", 404)
    session = await sessions.require_session(db, attachment.session_id, uid, lock=True)
    if session.agent_type != "ORDER_INTAKE" or attachment.status != "BOUND":
        sessions.fail("RESOURCE_NOT_FOUND", "订单截图不存在", 404)
    await sessions.require_idle(db, session)
    await db.refresh(attachment)
    if attachment.intake_revision != expected_revision:
        sessions.fail("SCREENSHOT_REVISION_CONFLICT", "截图已更新，请刷新后重试")
    now, cid = datetime.now(UTC), generate_id()
    if not archived and session.status == "ARCHIVED":
        # Restore one screenshot from an old archived Session, keeping all siblings archived.
        siblings = (
            await db.scalars(
                select(ChatAttachment).where(
                    ChatAttachment.session_id == session.id,
                    ChatAttachment.status == "BOUND",
                )
            )
        ).all()
        for sibling in siblings:
            if sibling.id != aid and sibling.intake_archived_at is None:
                sibling.intake_archived_at = session.archived_at or now
                sibling.intake_revision += 1
        session.status, session.archived_at = "ACTIVE", None
        append_event(
            db,
            session,
            "session.restored",
            {"source_attachment_id": aid},
            actor_kind="USER",
            actor_user_id=uid,
            command_id=cid,
        )
    attachment.intake_archived_at = now if archived else None
    attachment.intake_revision += 1
    current = (
        await db.get(OrderIntakeItem, session.active_work_item_id) if session.active_work_item_id else None
    )
    if current:
        source = await db.get(ChatAttachment, current.source_attachment_id)
        if source.intake_archived_at is not None:
            current.status, current.deferred_at = "DEFERRED", now
            current.revision += 1
            current.updated_at = now
            session.active_work_item_id = None
            append_event(db, session, "work_item.deferred", {}, work_item_id=current.id, command_id=cid)
    session.state_revision += 1
    append_event(
        db,
        session,
        "session.state_changed",
        {
            "state_revision": session.state_revision,
            "action": kind,
            "source_attachment_id": aid,
        },
        actor_kind="USER",
        actor_user_id=uid,
        command_id=cid,
    )
    result = {"attachment_id": aid, "archived": archived, "revision": attachment.intake_revision}
    db.add(
        AgentCommand(
            id=cid,
            user_id=uid,
            session_id=session.id,
            idempotency_key=key,
            kind=kind,
            request_hash=digest,
            payload=payload,
            target_id=aid,
            expected_revision=expected_revision,
            http_status=200,
            result=result,
        )
    )
    await db.commit()
    return result
