from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.schemas.order import OrderCreate
from app.services.order_specification import validate_specification
from app.services.production_rules import order_profile
from app.services.scheduling.planner import quantity_kg


@pytest.mark.parametrize("thickness", ["11.8丝", "11.8c", "118μm", "11.8C"])
def test_explicit_specification_units(thickness):
    result = validate_specification({"宽幅": "60.5cm", "厚度": thickness})
    assert result["宽幅"] == "605mm"
    assert result["厚度"] == "118μm"


@pytest.mark.parametrize(
    "specs",
    [
        {},
        {"宽幅": "40mm"},
        {"宽幅": "0mm", "厚度": "50g"},
        {"宽幅": "40mm", "厚度": "50g"},
        {"宽幅": "40", "厚度": "50μm"},
        {"宽幅": "40mm", "厚度": "50kg"},
    ],
)
def test_required_specs_reject_invalid_values(specs):
    with pytest.raises(HTTPException):
        validate_specification(specs)


@pytest.mark.parametrize("unit", ["m", "g", "kg", "t"])
def test_quantity_unit_contract(unit):
    assert OrderCreate(customer_id="c", product_id="p", quantity=10, unit=unit).unit == unit


def test_width_conversion_and_gram_load():
    order = SimpleNamespace(
        spec_params={"宽幅": "60.5cm", "厚度": "11.8c"},
        formula_snapshot={},
        formula_id=None,
        product=SimpleNamespace(category_id="p", category=SimpleNamespace(name="膜")),
        quantity=1000,
        unit="g",
    )
    assert order_profile(order).width == 605
    assert order_profile(order).signature.thickness == "118μm"
    assert quantity_kg(order) == 1


@pytest.mark.parametrize("unit", ["m", "g", "kg"])
async def test_create_and_reload_fixed_specs(client, unit):
    from tests.test_orders import _make_customer, _make_product

    customer = await _make_customer(client)
    product = await _make_product(client)
    payload = {
        "customer_id": customer["id"],
        "product_id": product["id"],
        "quantity": 10000,
        "unit": unit,
        "spec_params": {"宽幅": "60.5cm", "厚度": "11.8丝"},
    }
    response = await client.post("/api/orders", json=payload)
    assert response.status_code == 201, response.text
    saved = (await client.get(f"/api/orders/{response.json()['id']}")).json()
    assert saved["unit"] == ("kg" if unit == "g" else unit)
    assert saved["quantity"] == (10 if unit == "g" else 10000)
    assert saved["spec_params"]["宽幅"] == "605mm"
    assert saved["spec_params"]["厚度"] == "118μm"
    assert "60.5cm" in saved["spec_params"]["原始规格"]
    invalid = await client.post("/api/orders", json={**payload, "spec_params": {}})
    assert invalid.status_code == 400


async def test_meter_orders_schedule_with_original_quantity(db_session):
    from app.services.scheduling.service import create_schedule_plan
    from tests.test_scheduling import _setup_schedulable

    session, _, orders = await _setup_schedulable(db_session)
    orders[0].unit = "m"
    await db_session.flush()
    plan = await create_schedule_plan(db_session, session.id, "test-user")
    task = next(task for task in plan.tasks if orders[0].id in task["order_ids"])
    assert task["order_ids"] == [orders[0].id]
    assert task["total_quantity_kg"] is None
    assert task["total_quantity_m"] == orders[0].quantity
    assert not plan.unassigned
