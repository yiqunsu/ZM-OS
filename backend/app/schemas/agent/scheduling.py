from pydantic import Field, field_validator

from app.schemas.agent import AgentInput
from app.schemas.agent.order_intake import CloseItem, ItemAction


class DraftTask(AgentInput):
    draft_task_id: str | None = Field(default=None, max_length=128)
    machine_id: str = Field(min_length=1, max_length=128)
    order_ids: list[str] = Field(min_length=1, max_length=1000)


class ScheduleDraftPatch(ItemAction):
    tasks: list[DraftTask] = Field(max_length=1000)


class ClosePlan(CloseItem):
    pass


class StartScheduling(AgentInput):
    expected_state_revision: int = Field(gt=0)
    order_ids: list[str] = Field(min_length=1, max_length=1000)

    @field_validator("order_ids")
    @classmethod
    def unique_orders(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(not item or len(item) > 128 for item in value):
            raise ValueError("请选择有效且不重复的待排订单")
        return sorted(value)
