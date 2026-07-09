from pydantic import BaseModel, ConfigDict

from app.schemas.product import ProductOut


class FormulaRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    materials: str | None = None


class FormulaCreate(BaseModel):
    name: str
    product_id: str
    spec_params: dict[str, str] = {}
    materials: str = ""
    source_id: str | None = None
    notes: str | None = None


class FormulaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    product_id: str
    spec_params: dict[str, str]
    materials: str
    source_id: str | None = None
    source: FormulaRef | None = None
    notes: str | None = None
    product: ProductOut
