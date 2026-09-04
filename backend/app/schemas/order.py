from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.order import OrderStatus
from app.schemas.customer import CustomerRef
from app.schemas.formula import FormulaRef
from app.schemas.product import ProductOut
from app.schemas.production import TaskRef


class OrderCreate(BaseModel):
    customer_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    spec_params: dict[str, str] = Field(default_factory=dict)
    quantity: float = Field(gt=0)
    unit: Literal["kg", "t"]
    formula_id: str | None = None
    extra_notes: str | None = None


class OrderDraftCreate(BaseModel):
    customer_id: str = Field(default="", max_length=128)
    product_id: str = Field(default="", max_length=128)
    spec_params: dict[str, str] = Field(default_factory=dict)
    quantity: str | float = ""
    unit: Literal["kg", "t"] = "kg"
    formula_mode: Literal["none", "existing", "new"] = "none"
    formula_id: str = Field(default="", max_length=128)
    formula_materials: str = Field(default="", max_length=10000)
    new_formula_name: str = Field(default="", max_length=255)
    new_formula_materials: str = Field(default="", max_length=10000)
    extra_notes: str = Field(default="", max_length=10000)


class OrderUpdate(BaseModel):
    customer_id: str | None = None
    product_id: str | None = None
    spec_params: dict[str, str] | None = None
    quantity: float | None = Field(default=None, gt=0)
    unit: Literal["kg", "t"] | None = None
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
