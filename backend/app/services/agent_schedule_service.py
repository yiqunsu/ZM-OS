"""Versioned scheduling workspace. Only explicit API commands affect production."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentAuditLog,
    AgentCommand,
    AgentRun,
    ChatMessage,
    ChatSession,
    SchedulePlan,
    SchedulePlanStatus,
)
from app.models.base import generate_id
from app.services import agent_session_service as sessions
from app.services import schedule_service as scheduling
from app.services.agent_event_service import append_event, canonical_hash
from app.services.scheduling_lock import lock_scheduling_inputs


def plan_snapshot(plan: SchedulePlan) -> dict:
    snapshot = {
        name: getattr(plan, name)
        for name in (
            "id",
            "session_id",
            "status",
            "revision",
            "tasks",
            "unassigned",
            "input_order_ids",
            "created_at",
            "updated_at",
            "applied_result",
            "superseded_by_id",
            "created_by_run_id",
        )
    }

    snapshot["load_basis"] = plan.input_fingerprint.get("__load_basis__", "WEIGHT_KG")
    return snapshot


async def require_plan(db: AsyncSession, pid: str, uid: str, *, write: bool = False):
    plan = await db.get(SchedulePlan, pid)
    if plan is None or plan.created_by_run_id is None:
        sessions.fail("RESOURCE_NOT_FOUND", "排产草案不存在", 404)
    session = await sessions.require_session(db, plan.session_id, uid, lock=write, writable=write)
    if session.agent_type != "SCHEDULING":
        sessions.fail("WRONG_AGENT_TYPE", "此会话不支持排产", 422)
    if write:
        plan = await db.scalar(
            select(SchedulePlan)
            .where(SchedulePlan.id == pid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return session, plan


def require_revision(plan: SchedulePlan, expected: int) -> None:
    if plan.status != SchedulePlanStatus.DRAFT or plan.revision != expected:
        sessions.fail("DRAFT_REVISION_CONFLICT", "草案已改变，请读取最新版本")


async def generate(db: AsyncSession, session: ChatSession, run: AgentRun) -> dict:
    if run.generated_plan_id:
        return plan_snapshot(await db.get(SchedulePlan, run.generated_plan_id))
    previous = await db.get(SchedulePlan, session.active_plan_id) if session.active_plan_id else None
    replacement = run.config_snapshot.get("retry_intent")
    if previous:
        if not replacement or replacement.get("kind") != "REPLACE_PLAN":
            return {**plan_snapshot(previous), "replacement_required": True}
        if replacement["plan_id"] != previous.id or replacement["expected_revision"] != previous.revision:
            sessions.fail("DRAFT_REVISION_CONFLICT", "原草案已更新，请重新确认替换")
    await lock_scheduling_inputs(db)
    orders = await scheduling._load_orders(db)
    if not orders:
        return {"outcome": "NO_PENDING", "pending_count": 0}
    plan = await scheduling.create_schedule_plan(
        db, session.id, session.user_id, commit=False, order_ids=run.config_snapshot.get("selected_order_ids")
    )
    if previous:
        previous.status, previous.superseded_by_id, previous.updated_at = (
            SchedulePlanStatus.SUPERSEDED,
            plan.id,
            datetime.now(UTC),
        )
        await db.flush()
        append_event(
            db, session, "plan.superseded", {"plan_id": previous.id, "replacement_id": plan.id}, run_id=run.id
        )
    plan.created_by_run_id = run.id
    plan.tasks = [{**task, "draft_task_id": generate_id()} for task in plan.tasks]
    run.generated_plan_id = plan.id
    session.active_plan_id = plan.id
    session.state_revision += 1
    append_event(
        db, session, "plan.generated", {"plan_id": plan.id, "revision": plan.revision}, run_id=run.id
    )
    append_event(db, session, "session.state_changed", {"state_revision": session.state_revision})
    await db.flush()
    return {**plan_snapshot(plan), "outcome": "DRAFT_READY" if plan.tasks else "NO_FEASIBLE"}


async def patch_plan(db: AsyncSession, pid: str, uid: str, expected: int, tasks: list[dict]) -> dict:
    session, plan = await require_plan(db, pid, uid, write=True)
    await sessions.require_idle(db, session)
    require_revision(plan, expected)
    original_ids = {
        (task["machine_id"], tuple(task["order_ids"])): task.get("draft_task_id") for task in plan.tasks
    }
    try:
        await scheduling.update_schedule_draft(
            db, pid, uid, scheduling.plan_revision(plan), tasks, commit=False, allow_v2=True
        )
    except HTTPException as error:
        sessions.fail(
            "PLAN_STALE" if "变化" in str(error.detail) else "INPUT_INVALID",
            str(error.detail),
            error.status_code,
        )
    plan.tasks = [
        {
            **task,
            "draft_task_id": original_ids.get((task["machine_id"], tuple(task["order_ids"])))
            or generate_id(),
        }
        for task in plan.tasks
    ]
    plan.revision += 1
    plan.updated_at = datetime.now(UTC)
    append_event(
        db,
        session,
        "plan.updated",
        {"plan_id": pid, "revision": plan.revision},
        actor_kind="USER",
        actor_user_id=uid,
    )
    await db.commit()
    return plan_snapshot(plan)


async def plan_command(db: AsyncSession, pid: str, uid: str, key: str, kind: str, payload: dict) -> dict:
    digest = canonical_hash({"operation": kind, "plan_id": pid, **payload})
    old = await sessions.command_replay(db, uid, key, digest)
    if old:
        return old.result
    session, plan = await require_plan(db, pid, uid, write=True)
    await sessions.require_idle(db, session)
    cid = generate_id()
    audit = None
    repeated = kind == "APPLY_PLAN" and plan.status == SchedulePlanStatus.APPLIED
    result = {
        "schema_version": 1,
        "command_id": cid,
        "kind": kind,
        "plan_id": pid,
        "run_id": None,
        "returned_existing": repeated,
    }
    if repeated:
        result["applied_result"] = plan.applied_result
    else:
        require_revision(plan, payload["expected_revision"])
        if session.active_plan_id != pid:
            sessions.fail("ACTION_STALE", "该草案不是当前工作区")
        if kind == "APPLY_PLAN":
            if not plan.tasks:
                sessions.fail("NO_FEASIBLE", "没有可下发的排产任务", 422)
            try:
                applied = await scheduling.apply_schedule_plan(db, pid, uid, allow_v2=True)
            except HTTPException as error:
                sessions.fail("PLAN_STALE", str(error.detail), error.status_code)
            plan.applied_result = {"schema_version": 1, **applied}
            result["applied_result"] = plan.applied_result
            plan.revision += 1
            session.active_plan_id = None
            session.state = {
                **session.state,
                "scheduling_order_ids": [row["order_id"] for row in plan.unassigned],
            }
            append_event(db, session, "plan.applied", {"plan_id": pid, **applied}, command_id=cid)
            audit = AgentAuditLog(
                kind="SCHEDULE_APPLIED",
                user_id=uid,
                session_id=session.id,
                command_id=cid,
                object_type="schedule_plan",
                object_id=pid,
                result={"schema_version": 1, **applied},
            )
            message = ChatMessage(
                id=generate_id(),
                session_id=session.id,
                role="assistant",
                origin="BUSINESS",
                content=f"排产成功：创建{applied['task_count']}个生产任务，安排{applied['order_count']}张订单。",
                command_id=cid,
                event_seq=session.last_event_seq + 1,
            )
            db.add(message)
            append_event(
                db,
                session,
                "message.completed",
                {"role": "assistant", "text": message.content, "attachment_ids": []},
                message_id=message.id,
                command_id=cid,
            )
        elif kind == "CLOSE_PLAN":
            if payload.get("confirmed") is not True:
                sessions.fail("INPUT_INVALID", "请明确确认关闭草案", 422)
            plan.status, plan.closed_at = SchedulePlanStatus.CLOSED, datetime.now(UTC)
            plan.revision += 1
            session.active_plan_id = None
            append_event(db, session, "plan.closed", {"plan_id": pid}, command_id=cid)
        elif kind == "REPLACE_PLAN":
            event = append_event(
                db,
                session,
                "command.accepted",
                {"kind": kind},
                command_id=cid,
                actor_kind="USER",
                actor_user_id=uid,
            )
            run = sessions.new_run(session, trigger_kind="REPLACE_PLAN", event_seq=event.seq, command_id=cid)
            run.config_snapshot = {
                **run.config_snapshot,
                "retry_intent": {"kind": "REPLACE_PLAN", "plan_id": pid, "expected_revision": plan.revision},
                "scheduling_workbench": bool(plan.input_fingerprint.get("__selection_scope__")),
                "selected_order_ids": plan.input_order_ids
                if plan.input_fingerprint.get("__selection_scope__")
                else None,
            }
            db.add(run)
            result["run_id"] = run.id
            append_event(db, session, "run.queued", {}, run_id=run.id, command_id=cid)
        else:
            raise ValueError("unsupported plan command")
        session.state_revision += 1
        plan.updated_at = datetime.now(UTC)
        append_event(db, session, "session.state_changed", {"state_revision": session.state_revision})
    result.update(
        state_revision=session.state_revision,
        plan_revision=plan.revision,
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
            target_id=pid,
            expected_revision=payload["expected_revision"],
            result_run_id=result["run_id"],
            http_status=202 if result["run_id"] else 200,
            result=result,
        )
    )
    await db.flush()
    if audit:
        db.add(audit)
    await db.commit()
    return result
