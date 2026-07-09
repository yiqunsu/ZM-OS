from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.order import OrderStatus
from app.schemas.customer import CustomerRef
from app.schemas.formula import FormulaRef
from app.schemas.product import ProductOut
from app.schemas.production import TaskRef


class OrderCreate(BaseModel):
    customer_id: str
    product_id: str
    spec_params: dict[str, str] = {}
    quantity: float
    unit: str
    formula_id: str | None = None
    extra_notes: str | None = None


class OrderUpdate(BaseModel):
    customer_id: str | None = None
    product_id: str | None = None
    spec_params: dict[str, str] | None = None
    quantity: float | None = None
    unit: str | None = None
    formula_id: str | None = None
    extra_notes: str | None = None
    status: OrderStatus | None = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_no: str
    customer_id: str
    product_id: str
    spec_params: dict[str, str]
    quantity: float
    unit: str
    formula_id: str | None = None
    formula_snapshot: dict | None = None
    extra_notes: str | None = None
    status: OrderStatus
    task_id: str | None = None
    created_at: datetime

    customer: CustomerRef
    product: ProductOut
    formula: FormulaRef | None = None
    task: TaskRef | None = None
