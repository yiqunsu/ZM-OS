import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.agent.specialized.order_capabilities import OrderCapabilities
from app.agent.specialized.order_graph import build_order_graph
from app.agent.worker import claim, finalize
from app.models import Customer, OrderIntakeItem
from app.schemas.agent.entity_matching import extraction_schema
from app.services.order_matching_service import suggested_draft, vision_catalog, visual_suggestions
from tests.support.extraction_fixture import extracted_order, screenshot
from tests.test_agent_v2 import body, create, enable_v2, upload  # noqa: F401
from tests.test_order_intake_v2 import factory, seed_fields


def guess(identifier, **changes):
    return dict(
        candidate_id=identifier,
        confidence=0.96,
        runner_up_confidence=0.2,
        evidence="瑞豪跟单",
        reason="发送者昵称包含瑞豪",
        **changes,
    )


def sample(choice):
    order = extracted_order(product_description="测试用薄膜")
    order["customer_match"] = choice
    return {**screenshot(order), "context_text": "群：协茂～瑞豪一部；瑞豪跟单"}


@pytest.mark.parametrize(
    "change,code",
    [
        ({"confidence": 0.89}, "LOW_CONFIDENCE"),
        ({"runner_up_confidence": 0.85}, "LOW_CONFIDENCE"),
        ({"evidence": "没有此证据"}, "EVIDENCE_MISMATCH"),
    ],
)
def test_uncertain_ungrounded_choices_are_not_applied(change, code):
    catalog = {"customer_id": [{"id": "rh", "label": "瑞豪"}], "product_id": []}
    choice = {**guess("rh"), **change}
    raw = extraction_schema(catalog).model_validate(sample(choice))
    accepted, diagnostics = visual_suggestions(raw, catalog)
    assert accepted == {}
    assert diagnostics[0]["code"] == code


def test_dynamic_enums_empty_catalog_and_required_decisions():
    catalog = {"customer_id": [{"id": "rh", "label": "瑞豪"}], "product_id": []}
    schema = extraction_schema(catalog)
    with pytest.raises(ValidationError):
        schema.model_validate(sample(guess("invented")))
    invalid = sample(None)
    del invalid["orders"][0]["product_match"]
    with pytest.raises(ValidationError):
        schema.model_validate(invalid)
    with pytest.raises(ValidationError):
        extraction_schema({"customer_id": [], "product_id": []}).model_validate(sample(guess("rh")))
    assert schema.model_validate(sample(None)).orders[0].customer_match is None
    assert '"const": "rh"' in json.dumps(schema.model_json_schema())


async def test_catalog_refresh_duplicates_and_master_data_changes(db_session):
    await seed_fields(db_session)
    rh = Customer(company="瑞豪", contact="")
    db_session.add(rh)
    await db_session.commit()
    catalog = await vision_catalog(db_session)
    assert rh.id in {r["id"] for r in catalog["customer_id"]}
    raw = extraction_schema(catalog).model_validate(sample(guess(rh.id)))
    suggestions, _ = visual_suggestions(raw, catalog)
    draft, issues = await suggested_draft(db_session, raw.orders[0], suggestions[1])
    assert draft["customer_id"] == rh.id and issues[0]["code"] == "ENTITY_INFERRED"
    db_session.add(Customer(company="瑞豪", contact=""))
    await db_session.flush()
    accepted, diagnostics = visual_suggestions(raw, await vision_catalog(db_session))
    assert not accepted and diagnostics[0]["code"] == "AMBIGUOUS_NAME"
    rh.company = "已改名"
    await db_session.flush()
    draft, _ = await suggested_draft(db_session, raw.orders[0], suggestions[1])
    assert draft["customer_id"] is None


async def test_oversize_catalog_is_not_silently_truncated(db_session):
    db_session.add_all([Customer(company=f"客户{n}", contact="") for n in range(51)])
    await db_session.flush()
    catalog = await vision_catalog(db_session)
    assert catalog["customer_id"] == [] and "customer_id" in catalog["manual_fields"]


@pytest.mark.parametrize("invalid", [False, True])
async def test_single_vision_call_matches_two_orders_and_keeps_manual_fields(client, db_session, invalid):
    fields = await seed_fields(db_session)
    rh = Customer(company="瑞豪", contact="")
    db_session.add(rh)
    await db_session.commit()
    sid = (await create(client, "ORDER_INTAKE"))["id"]
    image = await upload(client, sid)
    accepted = await client.post(
        f"/api/agent/v2/sessions/{sid}/recognize", json=body(content="", attachment_ids=[image["id"]])
    )
    iid = accepted.json()["work_item_ids"][0]
    item = await db_session.get(OrderIntakeItem, iid)
    item.provenance = {"product_id": {"source": "USER"}}
    await db_session.commit()
    calls = 0

    async def vision(messages, model):
        nonlocal calls
        calls += 1
        injected = json.loads(messages[1]["content"][0]["text"])["catalog"]
        assert any(c["id"] == rh.id for c in injected["customer_id"])
        assert all("category" in p for p in injected["product_id"])
        orders = [extracted_order(product_description="测试用薄膜") for _ in range(2)]
        for order in orders:
            order["customer_match"] = guess("invented" if invalid else rh.id)
            order["product_match"] = {**guess(fields["product_id"]), "evidence": "测试用薄膜"}
        return {**screenshot(*orders), "context_text": "瑞豪跟单"}

    class NoTextModel:
        async def ainvoke(self, *args, **kwargs):
            raise AssertionError("Image recognition must not call a second matching model")

    context = await claim(db_session, "worker")
    result = await build_order_graph(
        OrderCapabilities(
            context,
            sessions=factory(db_session),
            model=NoTextModel(),
            vision_call=vision,
        )
    ).ainvoke({})
    await finalize(db_session, context, result["result"])
    state = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
    first, second = state["work_items"]
    assert calls == (2 if invalid else 1)
    assert first["draft"]["product_id"] is None
    assert first["draft"]["quantity"] == "7500"
    assert first["draft"]["customer_id"] == (None if invalid else rh.id)
    assert second["draft"]["product_id"] == fields["product_id"]
    if not invalid:
        assert "截图产品原文：测试用薄膜" in second["draft"]["extra_notes"]
        path = f"/api/agent/v2/items/{iid}/draft"
        saved = await client.patch(
            path,
            json={
                "expected_revision": first["revision"],
                "patch": {"customer_id": rh.id, "quantity": "8000"},
            },
        )
        assert any(i["code"] == "ENTITY_INFERRED" for i in saved.json()["issues"])
        changed = await client.patch(
            path, json={"expected_revision": saved.json()["revision"], "patch": {"customer_id": None}}
        )
        assert not any(i["code"] == "ENTITY_INFERRED" for i in changed.json()["issues"])
    else:
        assert any("格式无效" in i["message"] for i in first["issues"])
    assert all(i.order_id is None for i in (await db_session.scalars(select(OrderIntakeItem))).all())


async def test_vision_connection_failure_is_recorded_without_source_or_credentials(client, db_session):
    from app.agent.model_transport import VisionError
    from app.models import SessionEvent
    from tests.test_order_intake_v2 import FakeModel, setup_item

    sid, iid = await setup_item(client, db_session)
    context = await claim(db_session, "failure-worker")

    async def unavailable(messages, model):
        raise VisionError("CONNECTION_ERROR", "private upstream detail")

    with pytest.raises(RuntimeError, match="extraction unavailable"):
        await build_order_graph(
            OrderCapabilities(
                context, sessions=factory(db_session), model=FakeModel(), vision_call=unavailable
            )
        ).ainvoke({})
    row = await db_session.get(OrderIntakeItem, iid)
    assert row.recognition_status == "FAILED" and row.last_error_code == "CONNECTION_ERROR"
    events = (await db_session.scalars(select(SessionEvent).where(SessionEvent.session_id == sid))).all()
    payloads = [e.payload for e in events]
    assert any(p.get("code") == "CONNECTION_ERROR" for p in payloads)
    assert "private upstream" not in json.dumps(payloads)
