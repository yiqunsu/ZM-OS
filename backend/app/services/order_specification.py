"""Explicit units for the fixed order specification form."""

import math
import re
from decimal import Decimal

from fastapi import HTTPException


def validate_specification(specs: dict) -> dict:
    result = dict(specs)
    originals = []
    for label, aliases, factors, target in (
        ("宽幅", ("宽幅", "宽度", "幅宽", "width"), {"cm": 10, "mm": 1}, "mm"),
        ("厚度", ("厚度", "厚", "thickness"), {"丝": 10, "c": 10, "μm": 1, "um": 1}, "μm"),
    ):
        values = [str(specs[key]).strip() for key in aliases if key in specs]
        if len(values) != 1:
            raise HTTPException(400, f"请填写唯一的{label}及单位")
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(\S+)", values[0])
        if (
            not match
            or not math.isfinite(float(match[1]))
            or float(match[1]) <= 0
            or match[2].lower() not in factors
        ):
            raise HTTPException(400, f"{label}必须为正数并包含有效单位")
        canonical = format(Decimal(match[1]) * factors[match[2].lower()], "f")
        if "." in canonical:
            canonical = canonical.rstrip("0").rstrip(".")
        for key in aliases:
            result.pop(key, None)
        result[label] = canonical + target
        if values[0] != result[label]:
            originals.append(f"{label}：{values[0]}")
    if originals:
        result["原始规格"] = "；".join(filter(None, [specs.get("原始规格", ""), *originals]))
    return result


def standard_quantity(quantity: float, unit: str) -> tuple[float, str]:
    factors = {
        "m": (1, "m"),
        "cm": (0.01, "m"),
        "mm": (0.001, "m"),
        "kg": (1, "kg"),
        "g": (0.001, "kg"),
        "t": (1000, "kg"),
    }
    if unit not in factors or not math.isfinite(quantity) or quantity <= 0:
        raise HTTPException(400, "数量或单位无效")
    factor, target = factors[unit]
    return float(Decimal(str(quantity)) * Decimal(str(factor))), target
