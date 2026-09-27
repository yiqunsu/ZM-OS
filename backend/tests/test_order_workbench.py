"""The workbench recognizes every image, isolates failures and confirms one order at a time."""

import pytest
from sqlalchemy import select

from app.agent.specialized.order_capabilities import OrderCapabilities
from app.agent.specialized.order_graph import build_order_graph
from app.agent.worker import claim, fail_run, finalize
from app.models import AgentRun, OrderIntakeItem, SessionEvent
from tests.support.extraction_fixture import extracted_order, screenshot
from tests.test_agent_v2 import body, create, enable_v2, upload  # noqa: F401
from tests.test_order_intake_v2 import factory, seed_fields


class NoChatModel:
    async def ainvoke(self, *args, **kwargs):
        raise AssertionError("Button recognition must not invoke chat admission")

    def bind_tools(self, *args, **kwargs):
        raise AssertionError("Button recognition must not start a planning loop")


@pytest.mark.parametrize("first_fails", [False, True])
async def test_batch_recognition_failure_isolation_and_retry(client, db_session, first_fails):
    await seed_fields(db_session)
    sid = (await create(client, "ORDER_INTAKE"))["id"]
    images = [await upload(client, sid), await upload(client, sid)]
    request = body(attachment_ids=[i["id"] for i in images], content="")
    accepted = await client.post(f"/api/agent/v2/sessions/{sid}/recognize", json=request)
    assert accepted.status_code == 202, accepted.text
    calls = 0

    async def vision(messages, model):
        nonlocal calls
        calls += 1
        if first_fails and calls == 1:
            raise RuntimeError("synthetic vision outage")
        return screenshot(extracted_order(customer_name="示例客户", product_description="测试产品"))

    for index in range(2):
        context = await claim(db_session, "image-worker")
        assert context is not None
        graph = build_order_graph(
            OrderCapabilities(context, sessions=factory(db_session), model=NoChatModel(), vision_call=vision)
        )
        if first_fails and index == 0:
            with pytest.raises(RuntimeError):
                await graph.ainvoke({})
            await fail_run(db_session, context, "MODEL_UNAVAILABLE", "图片识别失败")
        else:
            result = await graph.ainvoke({})
            await finalize(db_session, context, result["result"])
    assert await claim(db_session, "image-worker") is None
    state = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
    assert [i["recognition_status"] for i in state["work_items"]] == [
        "FAILED" if first_fails else "SUCCEEDED",
        "SUCCEEDED",
    ]
    assert state["active_work_item"]["id"] == state["work_items"][int(first_fails)]["id"]
    assert state["work_items"][1]["customer_name"] == "示例客户"
    assert all(i["order_id"] is None for i in state["work_items"])
    replay = await client.post(f"/api/agent/v2/sessions/{sid}/recognize", json=request)
    assert replay.status_code == 202 and replay.json()["run_id"] == accepted.json()["run_id"]
    if first_fails:
        failed = state["work_items"][0]
        retry = await client.post(
            f"/api/agent/v2/items/{failed['id']}/recognize",
            json={"expected_revision": failed["revision"]},
            headers={"Idempotency-Key": "retry-image"},
        )
        assert retry.status_code == 202, retry.text
        context = await claim(db_session, "image-worker")
        result = await build_order_graph(
            OrderCapabilities(context, sessions=factory(db_session), model=NoChatModel(), vision_call=vision)
        ).ainvoke({})
        await finalize(db_session, context, result["result"])
        assert (await db_session.get(OrderIntakeItem, failed["id"])).recognition_status == "SUCCEEDED"
    assert len((await db_session.scalars(select(AgentRun).where(AgentRun.session_id == sid))).all()) == (
        3 if first_fails else 2
    )


async def test_confirmation_advances_atomically_without_creating_next_order(client, db_session):
    await seed_fields(db_session)
    sid = (await create(client, "ORDER_INTAKE"))["id"]
    image = await upload(client, sid)
    response = await client.post(
        f"/api/agent/v2/sessions/{sid}/recognize", json=body(content="", attachment_ids=[image["id"]])
    )
    assert response.status_code == 202
    context = await claim(db_session, "worker")

    async def vision(messages, model):
        return screenshot(
            *[extracted_order(customer_name="示例客户", product_description="测试产品") for _ in range(2)]
        )

    result = await build_order_graph(
        OrderCapabilities(context, sessions=factory(db_session), model=NoChatModel(), vision_call=vision)
    ).ainvoke({})
    await finalize(db_session, context, result["result"])
    state = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
    first = state["work_items"][0]
    path = f"/api/agent/v2/items/{first['id']}/confirm"
    payload = {"expected_revision": first["revision"], "advance": True}
    response = await client.post(path, json=payload, headers={"Idempotency-Key": "confirm-advance"})
    assert response.status_code == 200, response.text
    replay = await client.post(path, json=payload, headers={"Idempotency-Key": "confirm-advance"})
    assert replay.json() == response.json()
    state = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
    assert [i["status"] for i in state["work_items"]] == ["CREATED", "ACTIVE"]
    assert state["work_items"][1]["order_id"] is None
    assert state["work_item_counts"] == {"CREATED": 1, "ACTIVE": 1}
    assert state["active_run"] is None


async def test_recognition_command_rejects_text_and_wrong_service(client, db_session):
    sid = (await create(client, "ORDER_INTAKE"))["id"]
    image = await upload(client, sid)
    for request in [body(content="请删除订单", attachment_ids=[image["id"]]), body(content="")]:
        response = await client.post(f"/api/agent/v2/sessions/{sid}/recognize", json=request)
        assert response.status_code == 422
    scheduling = (await create(client, "SCHEDULING"))["id"]
    response = await client.post(
        f"/api/agent/v2/sessions/{scheduling}/recognize", json=body(content="", attachment_ids=[image["id"]])
    )
    assert response.status_code == 422
    assert (await db_session.scalars(select(AgentRun))).all() == []


async def test_lost_worker_skips_failed_image_and_fences_late_result(client, db_session):
    from datetime import UTC, datetime, timedelta

    from app.agent.worker import LeaseLost, expire_runs

    sid = (await create(client, "ORDER_INTAKE"))["id"]
    images = [await upload(client, sid), await upload(client, sid)]
    await client.post(
        f"/api/agent/v2/sessions/{sid}/recognize",
        json=body(content="", attachment_ids=[i["id"] for i in images]),
    )
    old = await claim(db_session, "lost-worker")
    run = await db_session.get(AgentRun, old.run_id)
    run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert await expire_runs(db_session) == 1
    following = await claim(db_session, "new-worker")
    assert following and following.work_item_id != old.work_item_id
    with pytest.raises(LeaseLost):
        await OrderCapabilities(old, sessions=factory(db_session)).load()
    assert (await db_session.get(OrderIntakeItem, old.work_item_id)).recognition_status == "FAILED"


async def test_workbench_conflict_fails_without_recognition_loop(client, db_session):
    from fastapi import HTTPException

    sid = (await create(client, "ORDER_INTAKE"))["id"]
    image = await upload(client, sid)
    await client.post(
        f"/api/agent/v2/sessions/{sid}/recognize", json=body(content="", attachment_ids=[image["id"]])
    )
    context = await claim(db_session, "worker")
    capability = OrderCapabilities(context, sessions=factory(db_session), model=NoChatModel())
    loaded = await capability.load()
    item = await db_session.get(OrderIntakeItem, context.work_item_id)
    item.revision += 1
    await db_session.commit()

    async def vision(messages, model):
        return screenshot(extracted_order())

    capability.vision_call = vision
    with pytest.raises(HTTPException):
        await capability.recognize(loaded)
    await fail_run(db_session, context, "DRAFT_REVISION_CONFLICT", "草稿已更新")
    assert await claim(db_session, "worker") is None
    state = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
    assert state["work_items"][0]["recognition_status"] == "FAILED"


async def test_new_images_recognize_without_replacing_current_review(client, db_session):
    await seed_fields(db_session)
    sid = (await create(client, "ORDER_INTAKE"))["id"]
    first_id = None
    for number in (1, 2):
        state = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
        image = await upload(client, sid)
        accepted = await client.post(
            f"/api/agent/v2/sessions/{sid}/recognize",
            json=body(
                content="",
                attachment_ids=[image["id"]],
                expected_state_revision=state["session"]["state_revision"],
            ),
        )
        assert accepted.status_code == 202, accepted.text
        context = await claim(db_session, "worker")
        if first_id:
            assert context.work_item_id != first_id

        async def vision(messages, model):
            return screenshot(extracted_order(quantity=number * 100))

        result = await build_order_graph(
            OrderCapabilities(context, sessions=factory(db_session), model=NoChatModel(), vision_call=vision)
        ).ainvoke({})
        await finalize(db_session, context, result["result"])
        state = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
        first_id = first_id or state["active_work_item"]["id"]
        assert state["session"]["active_work_item_id"] == first_id
    assert [i["recognition_status"] for i in state["work_items"]] == ["SUCCEEDED", "SUCCEEDED"]
    assert [i["draft"]["quantity"] for i in state["work_items"]] == ["100", "200"]


async def test_specific_recognition_failure_survives_worker_failure_and_retry(client, db_session):
    await seed_fields(db_session)
    sid = (await create(client, "ORDER_INTAKE"))["id"]
    image = await upload(client, sid)
    response = await client.post(
        f"/api/agent/v2/sessions/{sid}/recognize",
        json=body(content="", attachment_ids=[image["id"]]),
    )
    assert response.status_code == 202
    context = await claim(db_session, "diagnostic-worker")
    capabilities = OrderCapabilities(context, sessions=factory(db_session), model=NoChatModel())
    await capabilities._recognition_failed("EXTRACTION_INVALID")
    await fail_run(db_session, context, "EXECUTION_FAILED", "图片识别失败")
    item = await db_session.get(OrderIntakeItem, context.work_item_id)
    assert item.last_error_code == "EXTRACTION_INVALID"
    failures = (await db_session.scalars(select(SessionEvent).where(
        SessionEvent.run_id == context.run_id, SessionEvent.kind == "recognition.failed"
    ))).all()
    assert len(failures) == 1
    retry = await client.post(
        f"/api/agent/v2/items/{item.id}/recognize",
        json={"expected_revision": item.revision},
        headers={"Idempotency-Key": "diagnostic-retry"},
    )
    assert retry.status_code == 202, retry.text
    following = await claim(db_session, "diagnostic-worker")
    await fail_run(db_session, following, "WORKER_STOPPED", "处理已停止")
    await db_session.refresh(item)
    assert item.last_error_code == "WORKER_STOPPED"
