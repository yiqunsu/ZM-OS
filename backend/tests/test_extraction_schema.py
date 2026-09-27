"""Model output is typed; strings and raw source never become measurement values."""


import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.agent.specialized.order_capabilities import OrderCapabilities, schema_diagnostics
from app.agent.specialized.order_graph import build_order_graph
from app.agent.worker import claim, finalize
from app.models import OrderIntakeItem, SessionEvent
from app.schemas.agent.order_extraction import OrderExtraction, ScreenshotExtraction
from app.services.order_matching_service import extracted_draft
from tests.support.extraction_fixture import extracted_order, screenshot
from tests.test_agent_v2 import enable_v2  # noqa: F401
from tests.test_order_intake_v2 import FakeModel, factory, setup_item


@pytest.mark.parametrize("field", ["width", "thickness", "quantity"])
@pytest.mark.parametrize(
    "value", ["7500", "7500米", True, False, 0, -1, float("inf"), float("nan"), 1e13, 1e-13]
)
def test_measurements_reject_wrong_types_and_out_of_bounds(field, value):
    order = extracted_order()
    order[field]["value"] = value
    with pytest.raises(ValidationError):
        ScreenshotExtraction.model_validate(screenshot(order))


@pytest.mark.parametrize(
    "field,unit", [("width", "kg"), ("thickness", "g"), ("quantity", "卷"), ("quantity", "米")]
)
def test_units_are_closed_enumerations(field, unit):
    order = extracted_order()
    order[field]["unit"] = unit
    with pytest.raises(ValidationError):
        OrderExtraction.model_validate(order)


def test_required_fields_text_ids_and_no_legacy_model_response():
    order = extracted_order()
    order["source_reference_no"] = "000123"
    assert OrderExtraction.model_validate(order).source_reference_no == "000123"
    order["source_reference_no"] = 123
    with pytest.raises(ValidationError):
        OrderExtraction.model_validate(order)
    del order["source_reference_no"]
    with pytest.raises(ValidationError):
        OrderExtraction.model_validate(order)
    with pytest.raises(ValidationError):
        ScreenshotExtraction.model_validate({"orders": [{"quantity_raw": "7500米"}]})
    schema = ScreenshotExtraction.model_json_schema()
    assert schema["$defs"]["Quantity"]["properties"]["value"]["anyOf"][0]["type"] == "number"
    assert schema["$defs"]["Quantity"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"inference_basis": None},
        {"inference_basis": " "},
        {"source_text": "42.5cm"},
        {"source_text": "42.5g"},
        {"value": 425},
        {"unit": None},
    ],
)
def test_inferred_unit_cannot_change_source_value_or_explicit_unit(change):
    order = extracted_order(width_inferred=True)
    order["width"].update(change)
    with pytest.raises(ValidationError):
        OrderExtraction.model_validate(order)


async def test_null_does_not_fall_back_to_parsing_source_text(db_session):
    order = extracted_order(
        quantity=None, quantity_unit="m", quantity_source="7500-10000米", width=None, width_unit=None
    )
    order["width"]["source_text"] = "42.5cm"
    draft = await extracted_draft(db_session, OrderExtraction.model_validate(order))
    assert draft["quantity"] is None and draft["unit"] == "m"
    assert "宽幅" not in draft["spec_params"]


@pytest.mark.parametrize("fixed", [True, False])
async def test_graph_retries_specific_field_errors_before_saving(client, db_session, fixed):
    sid, iid = await setup_item(client, db_session)
    context = await claim(db_session, "schema-worker")
    calls = []

    async def vision(messages, model):
        calls.append(messages[0]["content"])
        order = extracted_order(quantity=7500, quantity_unit="m")
        if len(calls) == 1 or not fixed:
            order["quantity"]["value"] = "SECRET_INVALID_VALUE"
        return screenshot(order)

    graph = build_order_graph(
        OrderCapabilities(context, sessions=factory(db_session), model=FakeModel(), vision_call=vision)
    )
    if fixed:
        result = await graph.ainvoke({})
        await finalize(db_session, context, result["result"])
    else:
        with pytest.raises(RuntimeError, match="extraction invalid"):
            await graph.ainvoke({})
    assert len(calls) == 2
    assert "orders.0.quantity.value" in calls[1] and "float_type" in calls[1]
    assert "SECRET_INVALID_VALUE" not in calls[1]
    item = await db_session.get(OrderIntakeItem, iid)
    if fixed:
        assert item.draft["quantity"] == "7500" and item.extraction["schema_version"] == 2
        assert isinstance(item.extraction["quantity"]["value"], (int, float))
    else:
        assert item.recognition_status == "FAILED" and item.extraction is None
        assert item.draft.get("quantity") is None
    assert item.order_id is None
    events = (await db_session.scalars(select(SessionEvent).where(
        SessionEvent.run_id == context.run_id, SessionEvent.kind == "run.progress"
    ))).all()
    diagnostics = [e.payload for e in events if e.payload.get("stage") == "RECOGNITION_ERROR"]
    assert len(diagnostics) == (1 if fixed else 2)
    for event in diagnostics:
        assert {"field": "orders.0.quantity.value", "type": "float_type"} in event["errors"]
    assert "SECRET_INVALID_VALUE" not in str(diagnostics)


def test_schema_diagnostics_excludes_unknown_keys_and_values():
    response = screenshot(extracted_order())
    response["PRIVATE_CUSTOMER_TEXT"] = "SECRET_VALUE"
    response["orders"][0]["quantity"]["value"] = "SECRET_NUMBER"
    with pytest.raises(ValidationError) as failure:
        ScreenshotExtraction.model_validate(response)
    diagnostics = schema_diagnostics(failure.value)
    assert {"field": "<unknown>", "type": "extra_forbidden"} in diagnostics
    assert {"field": "orders.0.quantity.value", "type": "float_type"} in diagnostics
    assert "SECRET" not in str(diagnostics) and "PRIVATE" not in str(diagnostics)
