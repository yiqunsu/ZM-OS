"""Missing specification units can be inferred without rewriting source evidence."""

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.agent.specialized.order_capabilities import OrderCapabilities
from app.agent.specialized.order_graph import build_order_graph
from app.agent.worker import claim, finalize
from app.models import OrderIntakeItem
from app.schemas.agent.order_intake import RawOrderExtraction
from app.services.legacy_order_extraction import inferred_specs
from app.services.order_matching_service import extracted_draft
from tests.support.extraction_fixture import extracted_order, screenshot
from tests.test_agent_v2 import enable_v2  # noqa: F401
from tests.test_order_intake_v2 import FakeModel, factory, setup_item


def evidence(**changes):
    return RawOrderExtraction.model_validate(
        {
            "width_raw": "42.5",
            "thickness_raw": "11.8",
            "quantity_raw": "7500",
            "unit_raw": "米",
            "inferred_spec_units": [
                {"field": "width", "unit": "cm", "basis": "根据薄膜规格上下文推测"},
                {"field": "thickness", "unit": "丝", "basis": "根据聊天中同类厚度表示推测"},
            ],
            **changes,
        }
    )


async def test_inference_fills_standard_values_and_keeps_evidence(db_session):
    raw = evidence()
    draft = await extracted_draft(db_session, raw)
    assert draft["spec_params"]["宽幅"] == "425mm"
    assert draft["spec_params"]["厚度"] == "118μm"
    assert raw.width_raw == "42.5" and raw.thickness_raw == "11.8"
    assert draft["quantity"] == "7500" and draft["unit"] == "m"
    _, issues = inferred_specs(raw)
    assert len(issues) == 2 and all(i["code"] == "UNIT_INFERRED" for i in issues)


@pytest.mark.parametrize("width,thickness", [("42.5mm", "11.8μm"), ("42.5", "11.8g")])
async def test_explicit_units_are_never_overridden(db_session, width, thickness):
    raw = evidence(width_raw=width, thickness_raw=thickness)
    specs, issues = inferred_specs(raw)
    assert specs["厚度"] == thickness
    if width.endswith("mm"):
        assert specs["宽幅"] == width and not issues
    else:
        assert len(issues) == 1
    draft = await extracted_draft(db_session, raw)
    assert draft["spec_params"]["厚度"] == thickness


async def test_missing_inference_does_not_apply_a_default(db_session):
    draft = await extracted_draft(db_session, evidence(inferred_spec_units=[]))
    assert draft["spec_params"]["宽幅"] == "42.5"
    assert draft["spec_params"]["厚度"] == "11.8"


@pytest.mark.parametrize(
    "entries",
    [
        [{"field": "width", "unit": "丝", "basis": "依据"}],
        [{"field": "thickness", "unit": "g", "basis": "依据"}],
        [{"field": "width", "unit": "cm", "basis": " "}],
        [{"field": "width", "unit": "cm", "basis": "依据"}] * 2,
    ],
)
def test_invalid_or_ambiguous_unit_inferences_are_rejected(entries):
    with pytest.raises(ValidationError):
        evidence(inferred_spec_units=entries)


async def test_graph_persists_each_order_inference_and_preserves_notices_after_edits(client, db_session):
    sid, iid = await setup_item(client, db_session)
    context = await claim(db_session, "inference-worker")

    async def vision(messages, model):
        assert "inference_basis" in messages[0]["content"]
        return screenshot(
            extracted_order(width_inferred=True, thickness_inferred=True),
            extracted_order(width=60.5, width_inferred=True, thickness_inferred=True),
        )

    capabilities = OrderCapabilities(
        context, sessions=factory(db_session), model=FakeModel(), vision_call=vision
    )
    result = await build_order_graph(capabilities).ainvoke({})
    await finalize(db_session, context, result["result"])
    items = (
        await db_session.scalars(
            select(OrderIntakeItem)
            .where(OrderIntakeItem.session_id == sid)
            .order_by(OrderIntakeItem.source_order_index)
        )
    ).all()
    assert [item.draft["spec_params"]["宽幅"] for item in items] == ["425mm", "605mm"]
    assert all(len([i for i in item.issues if i["code"] == "UNIT_INFERRED"]) == 2 for item in items)
    assert all(item.order_id is None for item in items)
    assert items[0].extraction["width"]["source_text"] == "42.5"
    saved = await client.patch(
        f"/api/agent/v2/items/{iid}/draft",
        json={"expected_revision": items[0].revision, "patch": {"quantity": "8000"}},
    )
    assert saved.status_code == 200
    assert len([i for i in saved.json()["issues"] if i["code"] == "UNIT_INFERRED"]) == 2
    corrected = await client.patch(
        f"/api/agent/v2/items/{iid}/draft",
        json={"expected_revision": saved.json()["revision"], "patch": {"spec_params": {"宽幅": "42.5mm"}}},
    )
    assert corrected.status_code == 200
    assert [i["field"] for i in corrected.json()["issues"] if i["code"] == "UNIT_INFERRED"] == [
        "spec_params.厚度"
    ]
    assert items[0].extraction["width"]["source_text"] == "42.5"
