from pydantic import BaseModel, ConfigDict


class CustomerCreate(BaseModel):
    company: str
    contact: str
    notes: str | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company: str
    contact: str
    notes: str | None = None


class CustomerRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company: str
