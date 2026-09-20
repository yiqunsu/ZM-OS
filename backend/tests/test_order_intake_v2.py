"""Screenshot groups, independent drafts and explicit business confirmation."""

import json
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from sqlalchemy import func, select

from app.agent.specialized.order_capabilities import OrderCapabilities
from app.agent.specialized.order_graph import build_order_graph
from app.agent.worker import RunResult, claim, finalize
from app.models import (
    AgentAuditLog,
    AgentRun,
    ChatMessage,
    Customer,
    Order,
    OrderIntakeItem,
    Product,
    ProductCategory,
)
from tests.support.extraction_fixture import extracted_order, screenshot
from tests.test_agent_v2 import body, create, enable_v2, upload  # noqa: F401


async def setup_item(client, db_session):
    sid = (await create(client, "ORDER_INTAKE"))["id"]
    image = await upload(client, sid)
    response = await client.post(
        f"/api/agent/v2/sessions/{sid}/messages", json=body(content="请录入", attachment_ids=[image["id"]])
    )
    assert response.status_code == 202, response.text
    iid = response.json()["work_item_ids"][0]
    return sid, iid


async def seed_fields(db):
    customer = Customer(company="示例客户", contact="示例联系人")
    category = ProductCategory(name="测试薄膜")
    db.add_all([customer, category])
    await db.flush()
    product = Product(name="测试产品", category_id=category.id)
    db.add(product)
    await db.commit()
    return {
        "customer_id": customer.id,
        "product_id": product.id,
        "spec_params": {"宽幅": "42.5cm", "厚度": "11.8丝"},
        "quantity": "7500",
        "unit": "m",
        "formula_mode": "none",
    }


class FakeModel:
    def __init__(self, calls=None, decision="ALLOW"):
        self.calls = calls or []
        self.decision = decision
        self.tools = None
        self.bound = False
        self.inputs = []

    def bind_tools(self, tools, **kwargs):
        self.tools = tools
        parent = self

        class Bound:
            async def ainvoke(self, messages, **kwargs):
                parent.inputs.append(messages)
                return parent.calls.pop(0) if parent.calls else AIMessage(content="请核对草稿")

        return Bound()

    async def ainvoke(self, messages, **kwargs):
        assert kwargs["response_format"] == {"type": "json_object"}
        return AIMessage(
            content=json.dumps(
                {
                    "decision": self.decision,
                    "reason": "可选解释不得影响路由，也不进入审计",
                    "reason_code": "IN_SCOPE" if self.decision == "ALLOW" else "WRONG_AGENT",
                }
            )
        )

    async def astream(self, messages):
        self.inputs.append(messages)
        yield AIMessageChunk(content="订单草稿已准备，请在右侧核对后点击创建。")


def factory(db):
    @asynccontextmanager
    async def context():
        try:
            yield db
        except BaseException:
            await db.rollback()
            raise

    return context


@pytest.mark.asyncio
async def test_graph_recognizes_only_current_image_and_normalizes(client, db_session):
    fields = await seed_fields(db_session)
    sid, iid = await setup_item(client, db_session)
    context = await claim(db_session, "test-worker")
    calls = []

    async def vision(messages, model):
        calls.append(messages)
        return screenshot(
            extracted_order(
                customer_name="示例客户", product_description="测试产品", quantity=7.5, quantity_unit="t"
            )
        )

    capabilities = OrderCapabilities(
        context, sessions=factory(db_session), model=FakeModel(), vision_call=vision
    )
    result = await build_order_graph(capabilities).ainvoke({}, config={"recursion_limit": 40})
    await finalize(db_session, context, result["result"])
    item = await db_session.get(OrderIntakeItem, iid)
    assert len(calls) == 1
    assert len([part for part in calls[0][1]["content"] if part["type"] == "image_url"]) == 1
    assert item.recognition_status == "SUCCEEDED"
    assert item.draft["customer_id"] == fields["customer_id"]
    assert item.draft["quantity"] == "7500.0" and item.draft["unit"] == "kg"
    assert item.draft["spec_params"]["宽幅"] == "425mm" and item.draft["spec_params"]["厚度"] == "118μm"
    assert await db_session.scalar(select(func.count()).select_from(Order)) == 0
    # User continuation reuses recognized data, even if a second vision call would fail.
    session = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()["session"]
    sent = await client.post(
        f"/api/agent/v2/sessions/{sid}/messages",
        json=body(session["state_revision"], content="还缺什么", target_work_item_id=iid),
    )
    assert sent.status_code == 202
    context2 = await claim(db_session, "test-worker")
    second = OrderCapabilities(context2, sessions=factory(db_session), model=FakeModel(), vision_call=vision)
    result = await build_order_graph(second).ainvoke({})
    await finalize(db_session, context2, result["result"])
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_confirmation_uses_latest_draft_once_and_waits_for_next_button(client, db_session):
    fields = await seed_fields(db_session)
    sid, iid = await setup_item(client, db_session)
    context = await claim(db_session, "worker")
    item = await db_session.get(OrderIntakeItem, iid)
    saved = await client.patch(
        f"/api/agent/v2/items/{iid}/draft", json={"expected_revision": item.revision, "patch": fields}
    )
    assert saved.status_code == 200, saved.text
    busy_confirm = await client.post(
        f"/api/agent/v2/items/{iid}/confirm",
        json={"expected_revision": saved.json()["revision"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert busy_confirm.status_code == 409
    await finalize(db_session, context, RunResult("请核对"))
    image = await upload(client, sid)
    session = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()["session"]
    queued = await client.post(
        f"/api/agent/v2/sessions/{sid}/messages",
        json=body(session["state_revision"], content="", attachment_ids=[image["id"]]),
    )
    assert queued.status_code == 202
    next_iid = queued.json()["work_item_ids"][0]
    context = await claim(db_session, "worker")
    await finalize(db_session, context, RunResult("已排队"))
    modified = await client.patch(
        f"/api/agent/v2/items/{iid}/draft",
        json={"expected_revision": saved.json()["revision"], "patch": {"quantity": "888"}},
    )
    stale = await client.post(
        f"/api/agent/v2/items/{iid}/confirm",
        json={"expected_revision": saved.json()["revision"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert stale.status_code == 409
    request = {
        "json": {"expected_revision": modified.json()["revision"]},
        "headers": {"Idempotency-Key": str(uuid4())},
    }
    created = await client.post(f"/api/agent/v2/items/{iid}/confirm", **request)
    assert created.status_code == 200, created.text
    assert (await client.post(f"/api/agent/v2/items/{iid}/confirm", **request)).json() == created.json()
    another_key = await client.post(
        f"/api/agent/v2/items/{iid}/confirm", json=request["json"], headers={"Idempotency-Key": str(uuid4())}
    )
    assert another_key.json()["returned_existing"] is True
    assert await db_session.scalar(select(func.count()).select_from(Order)) == 1
    order = await db_session.get(Order, created.json()["order"]["id"])
    assert order.quantity == 888 and order.unit == "m"
    assert (await db_session.get(OrderIntakeItem, next_iid)).status == "PENDING"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.session_id == sid, AgentRun.status.in_(["QUEUED", "RUNNING"]))
        )
        == 0
    )
    message = await db_session.scalar(
        select(ChatMessage).where(ChatMessage.command_id == created.json()["command_id"])
    )
    action = message.presentation["actions"][0]
    assert action["kind"] == "NEXT_ITEM" and action["expected_next_item_id"] == next_iid
    response = await client.post(
        f"/api/agent/v2/sessions/{sid}/next-item",
        json={key: action[key] for key in ("expected_state_revision", "expected_next_item_id")},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    assert (await db_session.get(OrderIntakeItem, next_iid)).status == "ACTIVE"
    assert (
        await db_session.scalar(
            select(func.count()).select_from(AgentAuditLog).where(AgentAuditLog.kind == "ORDER_CREATED")
        )
        == 1
    )


@pytest.mark.asyncio
async def test_defer_resume_and_close_preserve_draft(client, db_session):
    sid, iid = await setup_item(client, db_session)
    context = await claim(db_session, "worker")
    item = await db_session.get(OrderIntakeItem, iid)
    saved = await client.patch(
        f"/api/agent/v2/items/{iid}/draft",
        json={"expected_revision": item.revision, "patch": {"extra_notes": "保留备注"}},
    )
    await finalize(db_session, context, RunResult("请核对"))
    deferred = await client.post(
        f"/api/agent/v2/items/{iid}/defer",
        json={"expected_revision": saved.json()["revision"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert deferred.status_code == 200
    assert item.status == "DEFERRED" and item.draft["extra_notes"] == "保留备注"
    selected = await client.post(
        f"/api/agent/v2/items/{iid}/select",
        json={
            "expected_revision": item.revision,
            "expected_state_revision": deferred.json()["state_revision"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert selected.status_code == 202, selected.text
    context = await claim(db_session, "worker")
    await finalize(db_session, context, RunResult("继续核对"))
    closed = await client.post(
        f"/api/agent/v2/items/{iid}/close",
        json={"expected_revision": item.revision, "confirmed": True},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert closed.status_code == 200
    assert item.status == "CLOSED" and item.draft["extra_notes"] == "保留备注"
    refused = await client.post(
        f"/api/agent/v2/items/{iid}/confirm",
        json={"expected_revision": item.revision},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert refused.status_code == 409


@pytest.mark.asyncio
async def test_model_old_revision_cannot_overwrite_manual_fields(client, db_session):
    _, iid = await setup_item(client, db_session)
    context = await claim(db_session, "worker")
    capabilities = OrderCapabilities(context, sessions=factory(db_session), model=FakeModel())
    loaded = await capabilities.load()
    old_revision = loaded["item"]["revision"]
    response = await client.patch(
        f"/api/agent/v2/items/{iid}/draft",
        json={"expected_revision": old_revision, "patch": {"quantity": "999", "unit": "kg"}},
    )
    assert response.status_code == 200
    rejected = await capabilities.tool(
        {
            "id": "stale-write",
            "name": "patch_current_draft",
            "args": {"expected_revision": old_revision, "patch": {"quantity": "1"}},
        }
    )
    assert rejected["error_code"] == "DRAFT_REVISION_CONFLICT"
    assert (await db_session.get(OrderIntakeItem, iid)).draft["quantity"] == "999"
    assert (await capabilities.tool({"id": "unsafe", "name": "create_order", "args": {}}))[
        "error_code"
    ] == "TOOL_NOT_ALLOWED"
    invalid = await client.patch(
        f"/api/agent/v2/items/{iid}/draft",
        json={"expected_revision": response.json()["revision"], "patch": {"formula_mode": "new"}},
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_scope_rejection_never_recognizes_or_uses_tools(client, db_session):
    _, iid = await setup_item(client, db_session)
    context = await claim(db_session, "worker")

    async def vision(*args):
        raise AssertionError("out-of-scope input must not reach vision")

    capabilities = OrderCapabilities(
        context, sessions=factory(db_session), model=FakeModel(decision="OUT_OF_SCOPE"), vision_call=vision
    )
    result = await build_order_graph(capabilities).ainvoke({})
    assert result["result"].outcome == "OUT_OF_SCOPE"
    assert (await db_session.get(OrderIntakeItem, iid)).recognition_status == "NOT_STARTED"


async def test_multi_order_screenshot_is_atomic_paged_and_independently_confirmed(client, db_session):
    await seed_fields(db_session)
    sid, iid = await setup_item(client, db_session)
    context = await claim(db_session, "multi-worker")

    async def vision(*args):
        return screenshot(
            extracted_order(customer_name="示例客户", product_description="测试产品"),
            extracted_order(
                customer_name="示例客户", product_description="测试产品", width=60.5, quantity=10000
            ),
        )

    cap = OrderCapabilities(context, sessions=factory(db_session), model=FakeModel(), vision_call=vision)
    loaded = await cap.load()
    await cap.recognize(loaded)
    # Same fenced extraction call is replayed, not duplicated.
    await cap.recognize(loaded)
    await finalize(db_session, context, RunResult("已识别两笔订单"))
    page1 = (await client.get(f"/api/agent/v2/sessions/{sid}/items?limit=1")).json()
    assert page1["next_cursor"] == "1:1"
    page2 = (await client.get(f"/api/agent/v2/sessions/{sid}/items?limit=1&cursor=1:1")).json()
    first, second = page1["items"][0], page2["items"][0]
    assert first["id"] == iid and second["source_order_index"] == 2
    assert first["source_attachment_id"] == second["source_attachment_id"]
    assert second["draft"]["quantity"] == "10000" and second["draft"]["spec_params"]["宽幅"] == "605mm"
    assert page2["next_cursor"] is None
    snap = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
    assert len(snap["work_items"]) == 2
    # Saved edits survive a single atomic switch; no additional model run.
    saved = await client.patch(
        f"/api/agent/v2/items/{iid}/draft",
        json={"expected_revision": first["revision"], "patch": {"quantity": "8000"}},
    )
    assert saved.status_code == 200
    selected = await client.post(
        f"/api/agent/v2/items/{second['id']}/select",
        json={
            "expected_revision": second["revision"],
            "expected_state_revision": snap["session"]["state_revision"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert selected.status_code == 200 and selected.json()["run_id"] is None
    snap = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
    current = snap["active_work_item"]
    assert current["id"] == second["id"]
    previous = (await client.get(f"/api/agent/v2/items/{iid}")).json()
    assert previous["status"] == "DEFERRED" and previous["draft"]["quantity"] == "8000"
    assert await db_session.scalar(select(func.count()).select_from(Order)) == 0
    confirmed = await client.post(
        f"/api/agent/v2/items/{second['id']}/confirm",
        json={"expected_revision": current["revision"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert confirmed.status_code == 200
    # Confirming one sibling cannot create the other.
    assert await db_session.scalar(select(func.count()).select_from(Order)) == 1
    assert (await client.get(f"/api/agent/v2/items/{iid}")).json()["order_id"] is None


async def test_stale_screenshot_extraction_cannot_partially_create_siblings(client, db_session):
    sid, iid = await setup_item(client, db_session)
    context = await claim(db_session, "multi-worker")

    async def vision(*args):
        return screenshot(
            extracted_order(quantity=1, quantity_unit="kg"), extracted_order(quantity=2, quantity_unit="kg")
        )

    cap = OrderCapabilities(context, sessions=factory(db_session), model=FakeModel(), vision_call=vision)
    loaded = await cap.load()
    await client.patch(
        f"/api/agent/v2/items/{iid}/draft",
        json={"expected_revision": loaded["item"]["revision"], "patch": {"extra_notes": "用户修改必须保留"}},
    )
    await cap.recognize(loaded)
    items = (await client.get(f"/api/agent/v2/sessions/{sid}/items")).json()["items"]
    assert len(items) == 1 and items[0]["draft"]["extra_notes"] == "用户修改必须保留"
    assert items[0]["recognition_status"] == "NOT_STARTED"
