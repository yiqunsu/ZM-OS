from pydantic import BaseModel, ConfigDict


class ProductCategoryCreate(BaseModel):
    name: str
    desc: str | None = None


class ProductCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    desc: str | None = None


class PatternOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    desc: str | None = None


class ProductCreate(BaseModel):
    name: str
    category_id: str


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category_id: str
    category: ProductCategoryOut
