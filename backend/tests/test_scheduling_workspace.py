from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import func, select

from app.agent.scheduling import build_scheduling_graph
from app.models import Order, ProductionTask
from app.models.order import OrderStatus
from app.services import schedule_service
from tests.test_scheduling import _setup_schedulable


async def test_loop_has_bounded_tool_execution():
    class RepeatingModel:
        def bind_tools(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            return AIMessage(content="", tool_calls=[{
                "name": "read_board", "args": {}, "id": f"call-{len(messages)}", "type": "tool_call",
            }])

    adapter = AsyncMock()
    adapter.invoke.return_value = {"machines": []}
    result = await build_scheduling_graph(RepeatingModel(), adapter).ainvoke({
        "messages": [HumanMessage(content="排单")], "steps": 0,
    })
    assert adapter.invoke.await_count == 5
    assert "上限" in result["messages"][-1].content


async def test_loop_reads_tool_result_and_rejects_unknown_tools():
    class Model:
        def bind_tools(self, tools, **kwargs):
            self.calls = 0
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "generate_draft", "args": {}, "id": "a", "type": "tool_call"},
                    {"name": "delete_order", "args": {}, "id": "b", "type": "tool_call"},
                ])
            assert isinstance(messages[-1], ToolMessage)
            assert "不支持" in messages[-1].content
            assert "saved-plan" in messages[-2].content
            return AIMessage(content="草案已生成，请在右侧核对。")

    adapter = AsyncMock()
    adapter.invoke.return_value = {"id": "saved-plan"}
    graph = build_scheduling_graph(Model(), adapter)
    result = await graph.ainvoke({"messages": [HumanMessage(content="排单")], "steps": 0})
    adapter.invoke.assert_awaited_once_with("generate_draft")
    assert result["messages"][-1].content == "草案已生成，请在右侧核对。"


async def test_draft_edit_apply_and_revision_protection(client, db_session):
    session, machine, orders = await _setup_schedulable(db_session)
    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")
    revision = schedule_service.plan_revision(plan)
    response = await client.put(f"/api/schedule-plans/{plan.id}", json={
        "revision": revision,
        "tasks": [{"machine_id": machine.id, "order_ids": [orders[0].id]}],
    })
    assert response.status_code == 200, response.text
    updated = response.json()
    assert len(updated["unassigned"]) == 1
    assert updated["revision"] != revision
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0
    assert (await db_session.get(Order, orders[0].id)).status == OrderStatus.PENDING
    stale_confirm = await client.post(f"/api/schedule-plans/{plan.id}/apply", json={"revision": revision})
    assert stale_confirm.status_code == 409
    response = await client.post(
        f"/api/schedule-plans/{plan.id}/apply", json={"revision": updated["revision"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["order_count"] == 1
    response = await client.post(
        f"/api/schedule-plans/{plan.id}/apply", json={"revision": updated["revision"]},
    )
    assert response.status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 1


@pytest.mark.parametrize("invalid", ["duplicate", "machine", "foreign"])
async def test_draft_rejects_invalid_edits_atomically(client, db_session, invalid):
    session, machine, orders = await _setup_schedulable(db_session)
    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")
    revision = schedule_service.plan_revision(plan)
    ids = [orders[0].id, orders[0].id] if invalid == "duplicate" else [orders[0].id]
    if invalid == "foreign":
        ids = ["not-in-plan"]
    response = await client.put(f"/api/schedule-plans/{plan.id}", json={
        "revision": revision,
        "tasks": [{"machine_id": "missing" if invalid == "machine" else machine.id, "order_ids": ids}],
    })
    assert response.status_code == 409
    await db_session.refresh(plan)
    assert schedule_service.plan_revision(plan) == revision
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0


async def test_plan_private_and_stale(client, db_session):
    session, _, orders = await _setup_schedulable(db_session)
    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")
    with pytest.raises(HTTPException) as denied:
        await schedule_service.require_plan(db_session, plan.id, "other-user")
    assert denied.value.status_code == 404
    orders[0].quantity = 999
    await db_session.commit()
    response = await client.get(f"/api/schedule-plans/{plan.id}")
    assert response.json()["stale"] is True
    response = await client.put(f"/api/schedule-plans/{plan.id}", json={
        "revision": schedule_service.plan_revision(plan), "tasks": [],
    })
    assert response.status_code == 409
