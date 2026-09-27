"""Screenshot recognition queue; one fenced Run per image, independent of review selection."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentCommand, AgentRun, ChatAttachment, ChatSession, OrderIntakeItem, SessionEvent
from app.models.base import generate_id
from app.services.agent_event_service import append_event, canonical_hash


async def advance_review(db: AsyncSession, session: ChatSession) -> None:
    """Select the next ready draft within the caller's confirmation transaction."""
    if session.active_work_item_id:
        current = await db.get(OrderIntakeItem, session.active_work_item_id)
        if current.recognition_status != "FAILED":
            return
        current.status = "PENDING"
        current.revision += 1
        session.active_work_item_id = None
        await db.flush()
    item = await db.scalar(
        select(OrderIntakeItem)
        .join(ChatAttachment, ChatAttachment.id == OrderIntakeItem.source_attachment_id)
        .where(
            ChatAttachment.intake_archived_at.is_(None),
            OrderIntakeItem.session_id == session.id,
            OrderIntakeItem.status == "PENDING",
            OrderIntakeItem.recognition_status == "SUCCEEDED",
        )
        .order_by(OrderIntakeItem.queue_position, OrderIntakeItem.source_order_index)
        .limit(1)
    )
    if item:
        item.status, item.activated_at = "ACTIVE", datetime.now(UTC)
        item.revision += 1
        session.active_work_item_id = item.id
        append_event(db, session, "work_item.activated", {"revision": item.revision}, work_item_id=item.id)


async def continue_recognition(db: AsyncSession, session: ChatSession, run: AgentRun) -> None:
    """Called after a terminal Run under the Session lock, including lease expiry."""
    if not run.config_snapshot.get("intake_workbench") or session.status != "ACTIVE":
        return
    if run.status == "FAILED" and run.work_item_id:
        item = await db.get(OrderIntakeItem, run.work_item_id)
        # Only this Run's failure is authoritative; a retry may have an older failure.
        recorded_failure = await db.scalar(
            select(SessionEvent.id).where(
                SessionEvent.run_id == run.id,
                SessionEvent.work_item_id == item.id,
                SessionEvent.kind == "recognition.failed",
            ).limit(1)
        )
        if item.recognition_status != "SUCCEEDED" and recorded_failure is None:
            item.recognition_status, item.last_error_code = "FAILED", run.error_code
            item.revision += 1
            append_event(
                db,
                session,
                "recognition.failed",
                {"error_code": run.error_code},
                run_id=run.id,
                work_item_id=item.id,
            )
    await db.flush()  # Release the unique open-Run slot before enqueueing its successor.
    pending = await db.scalar(
        select(OrderIntakeItem)
        .join(ChatAttachment, ChatAttachment.id == OrderIntakeItem.source_attachment_id)
        .where(
            ChatAttachment.intake_archived_at.is_(None),
            OrderIntakeItem.session_id == session.id,
            OrderIntakeItem.status.in_(["PENDING", "ACTIVE"]),
            OrderIntakeItem.source_order_index == 1,
            OrderIntakeItem.recognition_status == "NOT_STARTED",
        )
        .order_by(OrderIntakeItem.queue_position)
        .limit(1)
    )
    if pending:
        from app.services.agent_session_service import new_run

        cid = generate_id()
        following = new_run(
            session,
            command_id=cid,
            trigger_kind="RESUME_ITEM",
            event_seq=session.last_event_seq,
            message_id=pending.source_message_id,
            work_item_id=pending.id,
        )
        db.add(following)
        payload = {"after_run_id": run.id, "item_id": pending.id}
        db.add(
            AgentCommand(
                id=cid,
                session_id=session.id,
                user_id=session.user_id,
                kind="RECOGNIZE_ITEM",
                idempotency_key=f"recognize-after:{run.id}",
                request_hash=canonical_hash(payload),
                payload=payload,
                target_id=pending.id,
                result_run_id=following.id,
                http_status=202,
                result={"run_id": following.id, "item_id": pending.id},
            )
        )
        append_event(db, session, "run.queued", {}, run_id=following.id, work_item_id=pending.id)
    else:
        await advance_review(db, session)
