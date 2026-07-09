from pydantic import BaseModel, ConfigDict

from app.schemas.product import PatternOut, ProductCategoryOut


class MachineCreate(BaseModel):
    name: str
    is_active: bool = True
    min_width: float
    max_width: float
    notes: str | None = None
    category_ids: list[str] = []
    pattern_ids: list[str] = []


class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    is_active: bool
    min_width: float
    max_width: float
    notes: str | None = None
    categories: list[ProductCategoryOut]
    patterns: list[PatternOut]
