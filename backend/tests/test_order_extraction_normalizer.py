"""Typed conversion boundaries and user edits survive recognition application."""

from decimal import Decimal

import pytest

from app.agent.specialized.order_capabilities import OrderCapabilities
from app.agent.specialized.order_graph import build_order_graph
from app.agent.worker import claim, finalize
from app.models import OrderIntakeItem
from app.schemas.agent.order_extraction import OrderExtraction
from app.schemas.agent.order_intake import OrderDraft
from app.services.order_extraction_normalizer import normalize_extraction
from tests.support.extraction_fixture import extracted_order, screenshot
from tests.test_agent_v2 import enable_v2  # noqa: F401
from tests.test_order_intake_v2 import FakeModel, factory, setup_item


@pytest.mark.parametrize(
    "quantity,unit,expected,target",
    [
        (7.5, "t", "7500", "kg"),
        (0.001, "g", "0.000001", "kg"),
        (1e-9, "g", "0.000000000001", "kg"),
        (0.125, "m", "0.125", "m"),
        (1e-12, "g", None, "kg"),
        (1e12, "t", None, "kg"),
    ],
)
def test_quantity_conversion_preserves_decimal_precision_and_draft_bounds(quantity, unit, expected, target):
    raw = OrderExtraction.model_validate(extracted_order(quantity=quantity, quantity_unit=unit))
    draft, _ = normalize_extraction(raw)
    OrderDraft.model_validate(draft)
    assert draft["unit"] == target
    if expected is None:
        assert draft["quantity"] is None
        assert "原始数量" in draft["extra_notes"]
    else:
        assert Decimal(draft["quantity"]) == Decimal(expected)


def test_known_measurement_converts_independently_of_incomplete_other_field():
    raw = OrderExtraction.model_validate(extracted_order(width_inferred=True, thickness_unit=None))
    original = raw.model_dump()
    draft, issues = normalize_extraction(raw)
    assert draft["spec_params"]["宽幅"] == "425mm"
    assert draft["spec_params"]["厚度"] == "11.8"
    assert issues[0]["field"] == "spec_params.宽幅" and issues[0]["code"] == "UNIT_INFERRED"
    assert raw.model_dump() == original


async def test_recognition_preserves_manual_values_and_intentional_clears(client, db_session):
    _, iid = await setup_item(client, db_session)
    current = (await client.get(f"/api/agent/v2/items/{iid}")).json()
    saved = await client.patch(
        f"/api/agent/v2/items/{iid}/draft",
        json={
            "expected_revision": current["revision"],
            "patch": {
                "quantity": None,
                "extra_notes": "人工确认的备注",
                "spec_params": {"宽幅": "500mm"},
                "formula_mode": "none",
                "formula_id": None,
            },
        },
    )
    assert saved.status_code == 200
    context = await claim(db_session, "normalization-worker")

    async def vision(messages, model):
        return screenshot(extracted_order(width_inferred=True, notes="模型备注"))

    result = await build_order_graph(
        OrderCapabilities(context, sessions=factory(db_session), model=FakeModel(), vision_call=vision)
    ).ainvoke({})
    await finalize(db_session, context, result["result"])
    item = await db_session.get(OrderIntakeItem, iid)
    assert item.draft["quantity"] is None
    assert item.draft["extra_notes"] == "人工确认的备注"
    assert item.draft["spec_params"]["宽幅"] == "500mm"
    assert item.draft["spec_params"]["厚度"] == "118μm"
    assert item.draft["formula_mode"] == "none" and item.draft["formula_id"] is None
    assert not any(issue["field"] == "spec_params.宽幅" for issue in item.issues)
    assert item.extraction["width"]["value"] == 42.5
    assert item.order_id is None
