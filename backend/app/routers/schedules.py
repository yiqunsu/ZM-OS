from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentUser, get_current_user
from app.models import AgentAuditLog, ChatMessage, SchedulePlanStatus
from app.services import chat_service, schedule_service

router = APIRouter(prefix="/schedule-plans", tags=["schedule-plans"])


class TaskInput(BaseModel):
    machine_id: str = Field(min_length=1)
    order_ids: list[str] = Field(min_length=1, max_length=1000)


class RevisionInput(BaseModel):
    revision: str = Field(min_length=64, max_length=64)


class DraftInput(RevisionInput):
    tasks: list[TaskInput] = Field(max_length=1000)


@router.get("/{plan_id}")
async def get_plan(
    plan_id: str, user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = await schedule_service.require_plan(db, plan_id, user.id)
    return {**schedule_service.plan_payload(plan), "stale": await schedule_service.plan_is_stale(db, plan)}


@router.put("/{plan_id}")
async def edit_plan(
    plan_id: str, body: DraftInput, user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = await schedule_service.update_schedule_draft(
        db, plan_id, user.id, body.revision, [task.model_dump() for task in body.tasks],
    )
    return schedule_service.plan_payload(plan)


@router.post("/{plan_id}/apply")
async def apply_plan(
    plan_id: str, body: RevisionInput, user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = await schedule_service.require_plan(db, plan_id, user.id, lock=True)
    if plan.status != SchedulePlanStatus.DRAFT or body.revision != schedule_service.plan_revision(plan):
        raise HTTPException(409, "草案已修改或执行，请重新加载并核对")
    result = await schedule_service.apply_schedule_plan(db, plan_id, user.id)
    session = await chat_service.require_session(db, plan.session_id, user.id)
    session.active_workspace = None
    session.workspace_state = None
    db.add(ChatMessage(
        session_id=session.id, role="assistant",
        content=f"排产已执行：创建 {result['task_count']} 个任务，安排 {result['order_count']} 张订单。",
    ))
    db.add(AgentAuditLog(
        session_id=session.id, user_email=user.email, skill="schedule-workspace-apply",
        tool_calls=[{"name": "apply_schedule_plan", "revision": body.revision, "result": result}],
    ))
    await db.commit()
    return result
