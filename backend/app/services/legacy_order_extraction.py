"""Historical v1 evidence support; never used for new model output."""

import re
from decimal import Decimal

from fastapi import HTTPException

from app.schemas.agent.order_intake import OrderDraft, RawOrderExtraction
from app.services.order_quantity_extraction import extracted_quantity
from app.services.order_specification import validate_specification


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
