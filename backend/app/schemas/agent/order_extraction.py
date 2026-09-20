"""Version 2 model output: numeric measurements, closed units and separate evidence."""

import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.schemas.agent import AgentInput
from app.schemas.agent.entity_matching import EntityGuess

Text = Annotated[str, Field(strict=True, max_length=2000)]
Basis = Annotated[str, Field(strict=True, min_length=1, max_length=300)]
Number = Annotated[float, Field(strict=True, gt=0, le=1e12, allow_inf_nan=False)]


class Measurement(AgentInput):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: Number | None
    source_text: Text | None

    @field_validator("value")
    @classmethod
    def bounded_precision(cls, value):
        if value is not None and Decimal(str(value)).as_tuple().exponent < -12:
            raise ValueError("数值最多12位小数")
        return value


class Specification(Measurement):
    unit_source: Literal["EXPLICIT", "INFERRED", "UNKNOWN"]
    inference_basis: Basis | None

    @model_validator(mode="after")
    def consistent_source(self):
        if self.unit is None:
            if self.unit_source != "UNKNOWN" or self.inference_basis is not None:
                raise ValueError("未知单位必须标记UNKNOWN且推测依据为null")
        elif self.unit_source == "UNKNOWN":
            raise ValueError("已填写单位必须说明来源")
        elif self.unit_source == "INFERRED":
            if self.value is None or not self.inference_basis or not self.inference_basis.strip():
                raise ValueError("单位推测必须有数值和非空依据")
            original = (self.source_text or "").strip()
            if not re.fullmatch(r"\d+(?:\.\d+)?", original) or Decimal(original) != Decimal(str(self.value)):
                raise ValueError("推测只补充无单位的原始数值，不覆盖原文已写单位")
        elif self.inference_basis is not None:
            raise ValueError("明确单位不得附加推测依据")
        return self


class Width(Specification):
    unit: Literal["mm", "cm"] | None


class Thickness(Specification):
    unit: Literal["μm", "丝"] | None


class Quantity(Measurement):
    unit: Literal["m", "kg", "g", "t"] | None


class OrderExtraction(AgentInput):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[2]
    customer_match: EntityGuess | None = None
    product_match: EntityGuess | None = None
    customer_name: Text | None
    product_description: Text | None
    width: Width
    thickness: Thickness
    quantity: Quantity
    formula_raw: Text | None
    source_reference_no: Text | None
    notes: Text | None
    warnings: list[Text] = Field(max_length=20)


class ScreenshotExtraction(AgentInput):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[2]
    orders: list[OrderExtraction] = Field(min_length=1, max_length=20)
    context_text: Text | None = None  # Visible group/sender context; not an instruction.
