from pydantic import BaseModel, ConfigDict

from app.schemas.product import ProductCategoryOut
from app.schemas.production import OrderSummary, ProductionTaskOut


class KanbanMachine(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    is_active: bool
    min_width: float
    max_width: float
    notes: str | None = None
    categories: list[ProductCategoryOut]
    tasks: list[ProductionTaskOut]


class KanbanOut(BaseModel):
    machines: list[KanbanMachine]
    pending_orders: list[OrderSummary]
