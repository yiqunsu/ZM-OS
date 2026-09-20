from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.order import OrderStatus
from app.models.production import TaskStatus
from app.schemas.customer import CustomerRef
from app.schemas.product import ProductOut


class TaskRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: TaskStatus
    updated_at: datetime


class OrderSummary(BaseModel):
    """订单的精简视图，用于看板/生产任务里嵌套展示，不含 formula/task 字段避免循环嵌套。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    order_no: str
    spec_params: dict[str, str]
    quantity: float
    unit: str
    status: OrderStatus
    customer: CustomerRef
    product: ProductOut


class ProductionTaskCreate(BaseModel):
    machine_id: str
    order_ids: list[str]


class ProductionTaskUpdate(BaseModel):
    expected_status: TaskStatus | None = None
    expected_updated_at: datetime | None = None
    expected_order_ids: list[str] | None = None
    status: TaskStatus | None = None
    position: int | None = None
    machine_id: str | None = None
    order_ids: list[str] | None = None


class ProductionOrderMove(BaseModel):
    order_id: str
    source_task_id: str | None = None
    target_task_id: str | None = None
    target_machine_id: str | None = None


class ProductionTaskMove(BaseModel):
    task_id: str
    target_machine_id: str
    target_index: int = Field(ge=0)


class ProductionTaskReorder(BaseModel):
    machine_id: str
    ordered_task_ids: list[str]


class ProductionTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    machine_id: str
    position: int
    status: TaskStatus
    updated_at: datetime
    notes: str | None = None
    orders: list[OrderSummary]
