from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.schedule import SchedulePlanStatus


class ScheduleTaskOut(BaseModel):
    machine_id: str
    machine_name: str
    order_ids: list[str]
    order_nos: list[str]
    total_width: float
    reason: str


class UnassignedOrderOut(BaseModel):
    order_id: str
    order_no: str
    reason: str


class SchedulePlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: SchedulePlanStatus
    tasks: list[ScheduleTaskOut]
    unassigned: list[UnassignedOrderOut]
    created_at: datetime


class ScheduleApplyResult(BaseModel):
    plan_id: str
    task_ids: list[str]
    task_count: int
    order_count: int
