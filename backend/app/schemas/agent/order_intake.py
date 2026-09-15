"""Incomplete drafts are valid; only explicit confirmation requires a complete order."""

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.agent import AgentInput

ShortText = Annotated[str, Field(max_length=2000)]
OpaqueId = Annotated[str, Field(min_length=1, max_length=128)]


class SpecUnitInference(AgentInput):
    field: Literal["width", "thickness"]
    unit: Literal["mm", "cm", "μm", "um", "丝", "c"]
    basis: Annotated[str, Field(min_length=1, max_length=300)]

    @model_validator(mode="after")
    def compatible_unit(self):
        allowed = {"mm", "cm"} if self.field == "width" else {"μm", "um", "丝", "c"}
        if self.unit not in allowed or not self.basis.strip():
            raise ValueError("推测单位必须适用于对应规格，并说明依据")
        return self


class RawOrderExtraction(AgentInput):
    """Historical v1 evidence; not accepted from the live model."""
    schema_version: Literal[1] = 1
    customer_name: ShortText | None = None
    product_description: ShortText | None = None
    width_raw: ShortText | None = None
    thickness_raw: ShortText | None = None
    quantity_raw: ShortText | None = None
    unit_raw: ShortText | None = None
    formula_raw: ShortText | None = None
    source_reference_no: ShortText | None = None
    notes: ShortText | None = None
    warnings: list[ShortText] = Field(default_factory=list, max_length=20)
    inferred_spec_units: list[SpecUnitInference] = Field(default_factory=list, max_length=2)

    @field_validator("inferred_spec_units")
    @classmethod
    def unique_inference_fields(cls, value):
        if len({entry.field for entry in value}) != len(value):
            raise ValueError("每个规格只能有一个单位推测")
        return value


class OrderDraft(AgentInput):
    schema_version: Literal[1] = 1
    customer_id: OpaqueId | None = None
    product_id: OpaqueId | None = None
    spec_params: dict[str, ShortText] = Field(default_factory=dict, max_length=30)
    quantity: Annotated[str, Field(max_length=64)] | None = None
    unit: Literal["m", "kg"] | None = None
    formula_mode: Literal["none", "existing"] = "none"
    formula_id: OpaqueId | None = None
    extra_notes: ShortText = ""

    @field_validator("quantity")
    @classmethod
    def positive_decimal(cls, value):
        if value is not None:
            try:
                parsed = Decimal(value)
            except InvalidOperation as error:
                raise ValueError("数量无效") from error
            if not parsed.is_finite() or parsed <= 0 or parsed > Decimal("1e12"):
                raise ValueError("数量必须为有效正数且不超过一万亿")
            if parsed.as_tuple().exponent < -12:
                raise ValueError("数量最多保留12位小数")
            return format(parsed, "f")
        return value

    @field_validator("spec_params")
    @classmethod
    def valid_spec_keys(cls, value):
        if any(not key.strip() or len(key) > 128 for key in value):
            raise ValueError("规格名称无效")
        return value

    @model_validator(mode="after")
    def formula_consistency(self):
        if self.formula_mode == "none" and self.formula_id:
            raise ValueError("不选配方时不能指定配方ID")
        return self


class DraftPatch(AgentInput):
    expected_revision: int = Field(gt=0)
    # Validated against OrderDraft after the documented partial merge.
    patch: dict = Field(max_length=8)


class ItemAction(AgentInput):
    expected_revision: int = Field(gt=0)
    advance: bool = False


class CloseItem(ItemAction):
    confirmed: Literal[True]


class SelectItem(ItemAction):
    expected_state_revision: int = Field(gt=0)


class NextItem(AgentInput):
    expected_state_revision: int = Field(gt=0)
    expected_next_item_id: OpaqueId


class ScreenshotAction(AgentInput):
    expected_revision: int = Field(ge=0)
