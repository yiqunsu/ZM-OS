"""Historical v1 evidence conversion, kept outside the live recognition pipeline."""

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, field_validator, model_validator

from app.schemas.agent import AgentInput
from app.schemas.agent.order_intake import OrderDraft, ShortText
from app.services.order_specification import validate_specification


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


UNITS = {
    "m": ("1", "m"),
    "米": ("1", "m"),
    "kg": ("1", "kg"),
    "公斤": ("1", "kg"),
    "千克": ("1", "kg"),
    "g": ("0.001", "kg"),
    "克": ("0.001", "kg"),
    "t": ("1000", "kg"),
    "吨": ("1000", "kg"),
}
NUMBER = r"(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?"
# These describe fulfilment, not another quantity, a range or an arithmetic operation.
NOTE = r"(?:不要多|不多做|包含损耗|包括损耗|含损耗|损耗包含在内|不含损耗)"
SEPARATOR = r"[\s，,。；;、：:（）()\-—–]*"


def extracted_quantity(raw: str | None, unit_raw: str | None) -> tuple[str | None, str | None, str]:
    unit = (unit_raw or "").strip().lower()
    text = (raw or "").strip()
    number, note = None, ""
    if re.fullmatch(NUMBER, text):
        number = text
    else:
        # Require a full match: never take the first number from a range or multiple quantities.
        match = re.fullmatch(rf"({NUMBER})\s*(千克|公斤|kg|米|m|克|g|吨|t)\s*(.*)", text, re.IGNORECASE)
        if match:
            inline_unit = match[2].lower()
            tail = match[3].strip()
            consistent = not unit or (unit in UNITS and UNITS[unit] == UNITS[inline_unit])
            if consistent and re.fullmatch(rf"{SEPARATOR}(?:{NOTE}{SEPARATOR})*", tail):
                number, unit, note = match[1], inline_unit, tail
    canonical_unit = UNITS[unit][1] if unit in UNITS else None
    if number is not None:
        try:
            value = Decimal(number.replace(",", "").replace("，", ""))
            value *= Decimal(UNITS[unit][0]) if unit in UNITS else Decimal(1)
            if value.is_finite() and 0 < value <= Decimal("1e12") and value.as_tuple().exponent >= -12:
                return format(value, "f"), canonical_unit, note
        except InvalidOperation:
            pass
    return None, canonical_unit, f"原始数量：{text}" if text else ""


def inferred_specs(raw: RawOrderExtraction) -> tuple[dict, list[dict]]:
    """Only supplement a missing unit; an explicit (even unknown) unit always wins."""
    specs = {label: value for label, value in (("宽幅", raw.width_raw), ("厚度", raw.thickness_raw)) if value}
    issues = []
    for inference in raw.inferred_spec_units:
        label = "宽幅" if inference.field == "width" else "厚度"
        original = specs.get(label, "").strip()
        if not re.fullmatch(r"\d+(?:\.\d+)?", original) or Decimal(original) <= 0:
            continue
        specs[label] = original + inference.unit
        issues.append(
            {
                "field": f"spec_params.{label}",
                "code": "UNIT_INFERRED",
                "severity": "warning",
                "message": f"{label}原文 {original} 未标单位；AI 推测为 {inference.unit}，"
                f"已按此填入草稿，请核对。依据：{inference.basis}",
                "candidates": [],
            }
        )
    return specs, issues


def normalize_legacy(raw: RawOrderExtraction) -> tuple[dict, list[dict]]:
    draft = OrderDraft().model_dump()
    draft["spec_params"], issues = inferred_specs(raw)
    try:
        draft["spec_params"] = validate_specification(draft["spec_params"])
    except HTTPException:
        pass
    draft["quantity"], draft["unit"], note = extracted_quantity(raw.quantity_raw, raw.unit_raw)
    notes = raw.notes or ""
    if note and note not in notes:
        notes = "；".join(filter(None, [note, notes]))
    draft["extra_notes"] = notes[:2000]
    return draft, issues
