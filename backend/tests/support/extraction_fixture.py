"""Explicit v2 structured model responses for integration tests."""


def extracted_order(
    *,
    width=42.5,
    width_unit="cm",
    thickness=11.8,
    thickness_unit="丝",
    quantity=7500,
    quantity_unit="m",
    width_inferred=False,
    thickness_inferred=False,
    quantity_source=None,
    notes=None,
    customer_name=None,
    product_description=None,
):
    def spec(value, unit, inferred):
        return {
            "value": value,
            "unit": unit,
            "source_text": (str(value) + ("" if inferred else (unit or ""))) if value is not None else None,
            "unit_source": "UNKNOWN" if unit is None else "INFERRED" if inferred else "EXPLICIT",
            "inference_basis": "基于当前产品及聊天上下文推测" if inferred else None,
        }

    return {
        "schema_version": 2,
        "customer_match": None,
        "product_match": None,
        "customer_name": customer_name,
        "product_description": product_description,
        "width": spec(width, width_unit, width_inferred),
        "thickness": spec(thickness, thickness_unit, thickness_inferred),
        "quantity": {
            "value": quantity,
            "unit": quantity_unit,
            "source_text": quantity_source
            or (f"{quantity}{quantity_unit or ''}" if quantity is not None else None),
        },
        "formula_raw": None,
        "source_reference_no": None,
        "notes": notes,
        "warnings": [],
    }


def screenshot(*orders):
    return {"schema_version": 2, "orders": list(orders)}
