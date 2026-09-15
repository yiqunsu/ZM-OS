"""Order quantities may carry units and delivery notes, but must be unambiguous."""

import pytest

from app.schemas.agent.order_intake import RawOrderExtraction
from app.services.order_matching_service import extracted_draft
from app.services.order_quantity_extraction import extracted_quantity
from tests.support.extraction_fixture import extracted_order, screenshot
from tests.test_agent_v2 import enable_v2  # noqa: F401


@pytest.mark.parametrize(
    "raw,unit,quantity,normalized,note",
    [
        ("7500米不要多-包含损耗", "米", "7500", "m", "不要多-包含损耗"),
        ("10000米不要多-包含损耗", "米", "10000", "m", "不要多-包含损耗"),
        ("7,500米（含损耗）", "m", "7500", "m", "（含损耗）"),
        ("7.5吨", "吨", "7500.0", "kg", ""),
        ("250克", "", "0.250", "kg", ""),
        ("7500", None, "7500", None, ""),
        (None, "米", None, "m", ""),
        ("7,500", "米", "7500", "m", ""),
    ],
)
def test_parse_one_quantity_with_explicit_units_and_delivery_notes(raw, unit, quantity, normalized, note):
    assert extracted_quantity(raw, unit) == (quantity, normalized, note)


@pytest.mark.parametrize(
    "raw,unit",
    [
        ("7500-10000米", "米"),
        ("7500米+损耗100米", "米"),
        ("7500米或10000米", "米"),
        ("7500米以上", "米"),
        ("约7500米", "米"),
        ("7500米", "kg"),
        ("7500克", "kg"),
        ("7,50米", "米"),
        ("0米", "米"),
        ("NaN", "kg"),
        ("1000000000001", "kg"),
        ("0.0000000000001", "kg"),
    ],
)
def test_never_choose_from_ranges_conflicts_or_invalid_numbers(raw, unit):
    quantity, _, note = extracted_quantity(raw, unit)
    assert quantity is None and raw in note


async def test_draft_preserves_delivery_constraints_and_existing_notes(db_session):
    raw = RawOrderExtraction(quantity_raw="7500米不要多-包含损耗", unit_raw="米", notes="加急")
    draft = await extracted_draft(db_session, raw)
    assert draft["quantity"] == "7500" and draft["unit"] == "m"
    assert draft["extra_notes"] == "不要多-包含损耗；加急"
    assert raw.quantity_raw == "7500米不要多-包含损耗"


async def test_graph_and_scoped_repair_keep_each_quantity_and_user_edits(client, db_session):
    from sqlalchemy import select

    from app.agent.specialized.order_capabilities import OrderCapabilities
    from app.agent.specialized.order_graph import build_order_graph
    from app.agent.worker import claim, finalize
    from app.models import ChatSession, OrderIntakeItem, SessionEvent
    from scripts.repair_intake_quantities import repair
    from tests.test_order_intake_v2 import FakeModel, factory, setup_item

    sid, iid = await setup_item(client, db_session)
    context = await claim(db_session, "quantity-worker")

    async def vision(*args):
        return screenshot(
            *(
                extracted_order(quantity=n, quantity_source=f"{n}米不要多-包含损耗", notes="不要多-包含损耗")
                for n in (7500, 10000)
            )
        )

    cap = OrderCapabilities(context, sessions=factory(db_session), model=FakeModel(), vision_call=vision)
    result = await build_order_graph(cap).ainvoke({})
    await finalize(db_session, context, result["result"])
    items = (
        await db_session.scalars(
            select(OrderIntakeItem)
            .where(OrderIntakeItem.session_id == sid)
            .order_by(OrderIntakeItem.source_order_index)
        )
    ).all()
    assert [i.draft["quantity"] for i in items] == ["7500", "10000"]
    assert all(i.draft["unit"] == "m" and "包含损耗" in i.draft["extra_notes"] for i in items)
    # Reproduce the old persisted blanks, including a non-active sibling.
    items[1].status = "DEFERRED"
    for item in items:
        item.extraction = {
            "schema_version": 1,
            "quantity_raw": f"{item.draft['quantity']}米不要多-包含损耗",
            "unit_raw": "米",
        }
        item.draft = {**item.draft, "quantity": None, "unit": None, "extra_notes": "加急"}
    await db_session.commit()
    changes = await repair(db_session, [i.id for i in items])
    await db_session.commit()
    assert len(changes) == 2
    assert [i.draft["quantity"] for i in items] == ["7500", "10000"]
    assert all(i.draft["extra_notes"] == "不要多-包含损耗；加急" and i.order_id is None for i in items)
    assert items[1].status == "DEFERRED"
    assert (await db_session.get(ChatSession, sid)).active_work_item_id == iid
    events = (await db_session.scalars(select(SessionEvent).where(SessionEvent.session_id == sid))).all()
    assert len([e for e in events if e.payload.get("repair") == "quantity_text"]) == 2
    assert await repair(db_session, [i.id for i in items]) == []
    items[0].draft = {**items[0].draft, "quantity": None}
    items[0].provenance = {**items[0].provenance, "quantity": {"source": "USER"}}
    await db_session.commit()
    assert await repair(db_session, [iid]) == []
    assert items[0].draft["quantity"] is None
