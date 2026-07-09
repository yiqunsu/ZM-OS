from pydantic import BaseModel, ConfigDict

from app.models.order import OrderStatus
from app.models.production import TaskStatus
from app.schemas.customer import CustomerRef
from app.schemas.product import ProductOut


class TaskRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: TaskStatus


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
    status: TaskStatus | None = None
    position: int | None = None
    machine_id: str | None = None
    order_ids: list[str] | None = None


class ProductionTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    machine_id: str
    position: int
    status: TaskStatus
    notes: str | None = None
    orders: list[OrderSummary]
