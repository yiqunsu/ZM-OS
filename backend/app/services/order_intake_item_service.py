"""Order work items, versioned drafts and explicitly confirmed business creation."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentAuditLog,
    AgentCommand,
    ChatAttachment,
    ChatMessage,
    ChatSession,
    Order,
    OrderIntakeItem,
)
from app.models.base import generate_id
from app.schemas.agent.order_intake import OrderDraft
from app.services import agent_session_service as sessions
from app.services.agent_event_service import append_event, canonical_hash
from app.services.agent_projections import item_snapshot
from app.services.order_draft_service import merge_patch, validate_draft


async def require_item(db: AsyncSession, iid: str, uid: str, *, writable: bool = True):
    item = await db.get(OrderIntakeItem, iid)
    if item is None:
        sessions.fail("RESOURCE_NOT_FOUND", "订单工作项不存在", 404)
    session = await sessions.require_session(db, item.session_id, uid, lock=writable, writable=writable)
    if session.agent_type != "ORDER_INTAKE":
        sessions.fail("WRONG_AGENT_TYPE", "此会话不支持录单", 422)
    if writable:
        attachment = await db.get(ChatAttachment, item.source_attachment_id)
        if attachment.intake_archived_at is not None:
            sessions.fail("SCREENSHOT_ARCHIVED", "截图已归档，请先恢复后再处理")
        item = await db.scalar(
            select(OrderIntakeItem)
            .where(OrderIntakeItem.id == iid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return session, item


def require_item_revision(item: OrderIntakeItem, expected: int) -> None:
    if item.revision != expected:
        sessions.fail("DRAFT_REVISION_CONFLICT", "草稿已更新，请读取最新内容后重试")


async def patch_draft(
    db: AsyncSession,
    session: ChatSession,
    item: OrderIntakeItem,
    expected: int,
    patch: dict,
    *,
    source: str = "USER",
    run_id: str | None = None,
) -> dict:
    require_item_revision(item, expected)
    if not (source == "EXTRACTION" and item.status in {"PENDING", "ACTIVE"}) and (
        item.status != "ACTIVE" or session.active_work_item_id != item.id
    ):
        sessions.fail("WORK_ITEM_CLOSED", "只有当前核对中的订单可以修改")
    draft = merge_patch(OrderDraft.model_validate(item.draft), patch)
    prior_draft = OrderDraft.model_validate(item.draft)
    retained_inferences = [
        issue
        for issue in item.issues
        if (
            issue["code"] == "UNIT_INFERRED"
            and prior_draft.spec_params.get(issue["field"].removeprefix("spec_params."))
            == draft.spec_params.get(issue["field"].removeprefix("spec_params."))
        )
        or (
            issue["code"] == "ENTITY_INFERRED"
            and getattr(prior_draft, issue["field"], None) == getattr(draft, issue["field"], None)
        )
    ]
    item.draft = draft.model_dump()
    item.issues = await validate_draft(db, draft) + retained_inferences
    provenance = dict(item.provenance)
    for field, value in patch.items():
        paths = [f"spec_params.{key}" for key in value] if field == "spec_params" else [field]
        for path in paths:
            provenance[path] = {
                "source": source,
                "source_message_id": item.source_message_id,
                "source_attachment_id": item.source_attachment_id,
                "source_run_id": run_id,
            }
    item.provenance = provenance
    item.revision += 1
    item.updated_at = datetime.now(UTC)
    append_event(
        db,
        session,
        "draft.updated",
        {"revision": item.revision},
        actor_kind="AGENT" if run_id else "USER",
        actor_user_id=None if run_id else session.user_id,
        work_item_id=item.id,
        run_id=run_id,
    )
    return item_snapshot(item)


async def item_command(db: AsyncSession, iid: str, uid: str, key: str, kind: str, payload: dict) -> dict:
    digest = canonical_hash({"operation": kind, "item_id": iid, **payload})
    existing = await sessions.command_replay(db, uid, key, digest)
    if existing:
        return existing.result
    session, item = await require_item(db, iid, uid)
    await sessions.require_idle(db, session)
    cid = generate_id()
    audit = None
    returned_existing = kind == "CONFIRM_ORDER" and item.status == "CREATED"
    result = {
        "schema_version": 1,
        "command_id": cid,
        "kind": kind,
        "item_id": iid,
        "run_id": None,
        "returned_existing": returned_existing,
    }
    if returned_existing:
        order = await db.get(Order, item.order_id)
        result["order"] = {"id": order.id, "order_no": order.order_no}
    else:
        require_item_revision(item, payload["expected_revision"])
        if item.status in {"CREATED", "CLOSED"}:
            sessions.fail("WORK_ITEM_CLOSED", "该订单工作项已结束")
        now = datetime.now(UTC)
        if kind == "CONFIRM_ORDER":
            if item.status != "ACTIVE" or session.active_work_item_id != iid:
                sessions.fail("ACTION_STALE", "请先选择此订单进行核对")
            draft = OrderDraft.model_validate(item.draft)
            issues = await validate_draft(db, draft)
            if any(issue["severity"] == "blocking" for issue in issues):
                sessions.fail("DRAFT_INCOMPLETE", "请先补齐并核对订单字段", 422)
            from app.services.order_submission_service import create_from_workspace_draft

            order = await create_from_workspace_draft(db, draft.model_dump())
            item.status, item.order_id, item.completed_at = "CREATED", order.id, now
            session.active_work_item_id = None
            result["order"] = {"id": order.id, "order_no": order.order_no}
            append_event(db, session, "work_item.created", result["order"], command_id=cid, work_item_id=iid)
            audit = AgentAuditLog(
                kind="ORDER_CREATED",
                user_id=uid,
                session_id=session.id,
                command_id=cid,
                object_type="order",
                object_id=order.id,
                result={"schema_version": 1, "order_id": order.id, "order_no": order.order_no},
            )
        elif kind == "DEFER_ITEM":
            if item.status != "ACTIVE" or session.active_work_item_id != iid:
                sessions.fail("ACTION_STALE", "只有当前订单可以暂放")
            item.status, item.deferred_at, session.active_work_item_id = "DEFERRED", now, None
            append_event(db, session, "work_item.deferred", {}, command_id=cid, work_item_id=iid)
        elif kind == "CLOSE_ITEM":
            if payload.get("confirmed") is not True:
                sessions.fail("INPUT_INVALID", "请明确确认放弃", 422)
            item.status, item.closed_at = "CLOSED", now
            if session.active_work_item_id == iid:
                session.active_work_item_id = None
            append_event(db, session, "work_item.closed", {}, command_id=cid, work_item_id=iid)
        elif kind == "RECOGNIZE_ITEM":
            if item.recognition_status == "SUCCEEDED":
                sessions.fail("ACTION_STALE", "此截图已识别，请核对已有草稿")
            session.state = {**session.state, "intake_workbench": True}
            run = sessions.new_run(
                session,
                trigger_kind="RESUME_ITEM",
                event_seq=session.last_event_seq,
                command_id=cid,
                work_item_id=iid,
                message_id=item.source_message_id,
            )
            db.add(run)
            result["run_id"] = run.id
            append_event(db, session, "run.queued", {}, run_id=run.id, work_item_id=iid)
        elif kind == "SELECT_ITEM":
            sessions.require_revision(session, payload["expected_state_revision"])
            if item.status not in {"PENDING", "DEFERRED"}:
                sessions.fail("ACTION_STALE", "该订单当前不可切换")
            if session.active_work_item_id:
                previous = await db.get(OrderIntakeItem, session.active_work_item_id)
                previous.status, previous.deferred_at = "DEFERRED", now
                previous.revision += 1
                previous.updated_at = now
                session.active_work_item_id = None
                append_event(db, session, "work_item.deferred", {}, command_id=cid, work_item_id=previous.id)
                await db.flush()
            item.status, item.activated_at, session.active_work_item_id = "ACTIVE", now, iid
            event = append_event(db, session, "work_item.activated", {}, command_id=cid, work_item_id=iid)
            if item.recognition_status != "SUCCEEDED":
                run = sessions.new_run(
                    session,
                    trigger_kind="RESUME_ITEM",
                    event_seq=event.seq,
                    command_id=cid,
                    work_item_id=iid,
                    message_id=item.source_message_id,
                )
                db.add(run)
                result["run_id"] = run.id
                append_event(db, session, "run.queued", {}, run_id=run.id, command_id=cid)
        else:
            raise ValueError("unsupported work item command")
        item.revision += 1
        item.updated_at = now
        if payload.get("advance") and kind in {"CONFIRM_ORDER", "DEFER_ITEM", "CLOSE_ITEM"}:
            from app.services.order_intake_workflow import advance_review

            await db.flush()
            await advance_review(db, session)
        session.state_revision += 1
        append_event(db, session, "session.state_changed", {"state_revision": session.state_revision})
        if kind == "CONFIRM_ORDER":
            next_item = await db.scalar(
                select(OrderIntakeItem)
                .join(ChatAttachment, ChatAttachment.id == OrderIntakeItem.source_attachment_id)
                .where(
                    ChatAttachment.intake_archived_at.is_(None),
                    OrderIntakeItem.session_id == session.id,
                    OrderIntakeItem.status == "PENDING",
                )
                .order_by(OrderIntakeItem.queue_position, OrderIntakeItem.source_order_index)
                .limit(1)
            )
            text = f"已创建订单 {order.order_no}。" + (
                "是否处理下一单？" if next_item else "暂无待处理订单；已暂存的草稿可从截图与订单列表继续。"
            )
            if payload.get("advance"):
                text = f"已创建订单 {order.order_no}。"
            actions = (
                [
                    {
                        "kind": "NEXT_ITEM",
                        "label": "处理下一单",
                        "session_id": session.id,
                        "expected_state_revision": session.state_revision,
                        "expected_next_item_id": next_item.id,
                    }
                ]
                if next_item and not payload.get("advance")
                else []
            )
            message = ChatMessage(
                id=generate_id(),
                session_id=session.id,
                role="assistant",
                origin="BUSINESS",
                content=text,
                command_id=cid,
                work_item_id=iid,
                event_seq=session.last_event_seq + 1,
                presentation={"schema_version": 1, "actions": actions},
            )
            db.add(message)
            append_event(
                db,
                session,
                "message.completed",
                {"role": "assistant", "text": text, "attachment_ids": []},
                message_id=message.id,
                command_id=cid,
                work_item_id=iid,
            )
    result.update(
        state_revision=session.state_revision,
        item_revision=item.revision,
        event_cursor=session.last_event_seq,
    )
    db.add(
        AgentCommand(
            id=cid,
            user_id=uid,
            session_id=session.id,
            idempotency_key=key,
            kind=kind,
            request_hash=digest,
            payload=payload,
            target_id=iid,
            expected_revision=payload["expected_revision"],
            result_run_id=result["run_id"],
            http_status=202 if result["run_id"] else 200,
            result=result,
        )
    )
    await db.flush()
    if audit is not None:
        db.add(audit)
    await db.commit()
    return result


async def next_item(db: AsyncSession, sid: str, uid: str, key: str, payload: dict) -> dict:
    digest = canonical_hash({"operation": "NEXT_ITEM", "session_id": sid, **payload})
    existing = await sessions.command_replay(db, uid, key, digest)
    if existing:
        return existing.result
    session = await sessions.require_session(db, sid, uid, lock=True, writable=True)
    if session.agent_type != "ORDER_INTAKE":
        sessions.fail("WRONG_AGENT_TYPE", "排单助手没有下一张截图", 422)
    await sessions.require_idle(db, session)
    sessions.require_revision(session, payload["expected_state_revision"])
    if session.active_work_item_id:
        sessions.fail("ACTION_STALE", "请先结束或暂放当前订单")
    item = await db.scalar(
        select(OrderIntakeItem)
        .join(ChatAttachment, ChatAttachment.id == OrderIntakeItem.source_attachment_id)
        .where(
            ChatAttachment.intake_archived_at.is_(None),
            OrderIntakeItem.session_id == sid,
            OrderIntakeItem.status == "PENDING",
        )
        .order_by(OrderIntakeItem.queue_position, OrderIntakeItem.source_order_index)
        .with_for_update()
        .limit(1)
    )
    if item is None or item.id != payload["expected_next_item_id"]:
        sessions.fail("ACTION_STALE", "待处理队列已改变，请刷新")
    cid = generate_id()
    item.status, item.activated_at = "ACTIVE", datetime.now(UTC)
    item.revision += 1
    session.active_work_item_id = item.id
    session.state_revision += 1
    event = append_event(
        db, session, "work_item.activated", {"revision": item.revision}, command_id=cid, work_item_id=item.id
    )
    run = None
    if item.recognition_status != "SUCCEEDED":
        run = sessions.new_run(
            session,
            trigger_kind="NEXT_ITEM",
            event_seq=event.seq,
            command_id=cid,
            work_item_id=item.id,
            message_id=item.source_message_id,
        )
        db.add(run)
        append_event(db, session, "run.queued", {}, run_id=run.id, command_id=cid)
    result = {
        "schema_version": 1,
        "command_id": cid,
        "kind": "NEXT_ITEM",
        "run_id": run.id if run else None,
        "item_id": item.id,
        "state_revision": session.state_revision,
        "event_cursor": session.last_event_seq,
        "returned_existing": False,
    }
    db.add(
        AgentCommand(
            id=cid,
            user_id=uid,
            session_id=sid,
            idempotency_key=key,
            kind="NEXT_ITEM",
            request_hash=digest,
            payload=payload,
            target_id=item.id,
            result_run_id=run.id if run else None,
            http_status=202 if run else 200,
            result=result,
        )
    )
    await db.commit()
    return result
