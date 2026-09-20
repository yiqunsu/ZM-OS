"""Normalize screenshot quantities without silently choosing from ranges or totals."""

import re
from decimal import Decimal, InvalidOperation

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
