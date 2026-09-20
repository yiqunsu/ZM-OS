"""Convert validated measurements to draft fields without parsing their source text."""

from decimal import Decimal

from app.schemas.agent.order_extraction import OrderExtraction
from app.schemas.agent.order_intake import OrderDraft, RawOrderExtraction


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def normalize_extraction(raw: OrderExtraction | RawOrderExtraction) -> tuple[dict, list[dict]]:
    if isinstance(raw, RawOrderExtraction):
        from app.services.legacy_order_extraction import normalize_legacy

        return normalize_legacy(raw)
    draft = OrderDraft().model_dump()
    specs, originals, issues = {}, [], []
    for measurement, label, factors, target in (
        (raw.width, "宽幅", {"cm": 10, "mm": 1}, "mm"),
        (raw.thickness, "厚度", {"丝": 10, "μm": 1}, "μm"),
    ):
        if measurement.value is None:
            continue
        value = Decimal(str(measurement.value))
        number = decimal_text(value)
        if measurement.unit is None:
            specs[label] = number
            continue
        specs[label] = decimal_text(value * factors[measurement.unit]) + target
        original = number + measurement.unit
        if original != specs[label]:
            originals.append(f"{label}：{original}")
        if measurement.unit_source == "INFERRED":
            issues.append(
                {
                    "field": f"spec_params.{label}",
                    "code": "UNIT_INFERRED",
                    "severity": "warning",
                    "message": f"{label}原文 {measurement.source_text} 未标单位；"
                    f"AI 推测为 {measurement.unit}，"
                    f"已按此填入草稿，请核对。依据：{measurement.inference_basis}",
                    "candidates": [],
                }
            )
    if originals:
        specs["原始规格"] = "；".join(originals)
    draft["spec_params"] = specs
    quantity = raw.quantity
    factors = {"m": ("1", "m"), "kg": ("1", "kg"), "g": ("0.001", "kg"), "t": ("1000", "kg")}
    factor, unit = factors.get(quantity.unit, ("1", None))
    draft["unit"] = unit
    notes = raw.notes or ""
    if quantity.value is not None:
        value = Decimal(decimal_text(Decimal(str(quantity.value)))) * Decimal(factor)
        normalized = format(value, "f")
        # A valid source measurement can exceed the draft's bounds after conversion.
        if value <= Decimal("1e12") and Decimal(normalized).as_tuple().exponent >= -12:
            draft["quantity"] = normalized
        else:
            note = f"原始数量：{decimal_text(Decimal(str(quantity.value)))}{quantity.unit or ''}"
            notes = "；".join(filter(None, [note, notes]))
    draft["extra_notes"] = notes[:2000]
    return draft, issues
