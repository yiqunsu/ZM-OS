"""Scheduling proposals remain editable and require explicit, versioned confirmation."""

import asyncio
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from sqlalchemy import delete, func, select

from app.agent.specialized.scheduling_capabilities import SchedulingCapabilities
from app.agent.specialized.scheduling_graph import build_scheduling_graph
from app.agent.worker import RunResult, claim, finalize, lock_run
from app.models import AgentAuditLog, AgentRun, Order, ProductionTask, SchedulePlan
from tests.test_agent_v2 import body, create, enable_v2, independent_sessions  # noqa: F401
from tests.test_order_intake_v2 import FakeModel, factory
from tests.test_scheduling import _setup_schedulable


class ScheduleModel(FakeModel):
    def __init__(self, operation="GENERATE", **kwargs):
        super().__init__(**kwargs)
        self.operation = operation

    async def ainvoke(self, messages, **kwargs):
        assert kwargs["response_format"] == {"type": "json_object"}
        return AIMessage(
            content=json.dumps(
                {
                    "decision": "ALLOW",
                    "reason_code": "IN_SCOPE",
                    "requested_operation": self.operation,
                    "reason": "额外解释不授权执行",
                }
            )
        )


async def run_graph(client, db, sid=None, operation="GENERATE"):
    if sid is None:
        sid = (await create(client))["id"]
    session = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()["session"]
    sent = await client.post(
        f"/api/agent/v2/sessions/{sid}/messages", json=body(session["state_revision"], content="帮我排单")
    )
    assert sent.status_code == 202, sent.text
    context = await claim(db, "worker")
    capabilities = SchedulingCapabilities(context, sessions=factory(db), model=ScheduleModel(operation))
    result = await build_scheduling_graph(capabilities).ainvoke({}, config={"recursion_limit": 40})
    await finalize(db, context, result["result"])
    run = await db.get(AgentRun, context.run_id)
    return sid, run, result["result"]


@pytest.mark.asyncio
async def test_empty_pending_completes_without_plan(client, db_session):
    _, run, result = await run_graph(client, db_session)
    assert result.outcome == "NO_PENDING" and run.status == "SUCCEEDED"
    assert await db_session.scalar(select(func.count()).select_from(SchedulePlan)) == 0


@pytest.mark.asyncio
async def test_generate_edit_and_apply_once(client, db_session):
    _, machine, orders = await _setup_schedulable(db_session)
    sid, run, result = await run_graph(client, db_session)
    assert result.outcome == "DRAFT_READY"
    plan = await db_session.get(SchedulePlan, run.generated_plan_id)
    assert plan.status == "DRAFT" and len(plan.tasks) == 1
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0
    assert (await client.get(f"/api/schedule-plans/{plan.id}")).status_code == 404
    edited = await client.put(
        f"/api/agent/v2/plans/{plan.id}/draft",
        json={
            "expected_revision": plan.revision,
            "tasks": [{"machine_id": machine.id, "order_ids": [order.id]} for order in orders],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["revision"] == 2 and len(edited.json()["tasks"]) == 2
    stale = await client.post(
        f"/api/agent/v2/plans/{plan.id}/apply",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert stale.status_code == 409
    request = {"json": {"expected_revision": 2}, "headers": {"Idempotency-Key": str(uuid4())}}
    applied = await client.post(f"/api/agent/v2/plans/{plan.id}/apply", **request)
    assert applied.status_code == 200, applied.text
    assert (await client.post(f"/api/agent/v2/plans/{plan.id}/apply", **request)).json() == applied.json()
    duplicate = await client.post(
        f"/api/agent/v2/plans/{plan.id}/apply",
        json={"expected_revision": 2},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert duplicate.json()["returned_existing"]
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 2
    await db_session.refresh(orders[0])
    assert orders[0].status == "PRODUCING" and orders[0].task_id
    assert (
        await db_session.scalar(
            select(func.count()).select_from(AgentAuditLog).where(AgentAuditLog.kind == "SCHEDULE_APPLIED")
        )
        == 1
    )


@pytest.mark.asyncio
async def test_replacement_requires_command_and_preserves_plan_on_failure(client, db_session):
    await _setup_schedulable(db_session)
    sid, run, _ = await run_graph(client, db_session)
    old_plan = await db_session.get(SchedulePlan, run.generated_plan_id)
    _, another, result = await run_graph(client, db_session, sid)
    assert result.outcome == "NEEDS_INPUT" and another.generated_plan_id is None
    assert await db_session.scalar(select(func.count()).select_from(SchedulePlan)) == 1
    replaced = await client.post(
        f"/api/agent/v2/plans/{old_plan.id}/replace",
        json={"expected_revision": old_plan.revision},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert replaced.status_code == 202
    context = await claim(db_session, "worker")
    caps = SchedulingCapabilities(context, sessions=factory(db_session), model=ScheduleModel())
    result = await build_scheduling_graph(caps).ainvoke({})
    await finalize(db_session, context, result["result"])
    await db_session.refresh(old_plan)
    assert old_plan.status == "SUPERSEDED" and old_plan.superseded_by_id
    new = await db_session.get(SchedulePlan, old_plan.superseded_by_id)
    assert new.status == "DRAFT"
    # Querying a draft never authorizes opportunistic generation by a tool call.
    session = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()["session"]
    await client.post(
        f"/api/agent/v2/sessions/{sid}/messages", json=body(session["state_revision"], content="帮我排单")
    )
    context = await claim(db_session, "worker")
    caps = SchedulingCapabilities(context, sessions=factory(db_session), model=ScheduleModel("EXPLAIN_DRAFT"))
    loaded = await caps.load()
    await caps.admit(loaded)
    denied = await caps.tool({"id": "not-authorized", "name": "generate_draft", "args": {}})
    assert denied["error_code"] == "GENERATION_NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_unfeasible_and_stale_inputs_never_apply(client, db_session):
    _, _, orders = await _setup_schedulable(db_session)
    for order in orders:
        order.spec_params = {**order.spec_params, "宽度": "9999mm"}
    await db_session.commit()
    _, run, result = await run_graph(client, db_session)
    assert result.outcome == "NO_FEASIBLE"
    plan = await db_session.get(SchedulePlan, run.generated_plan_id)
    denied = await client.post(
        f"/api/agent/v2/plans/{plan.id}/apply",
        json={"expected_revision": plan.revision},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert denied.status_code == 422
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0

    for order in orders:
        order.spec_params = {**order.spec_params, "宽度": "500mm"}
    await db_session.commit()
    _, run, _ = await run_graph(client, db_session)
    plan = await db_session.get(SchedulePlan, run.generated_plan_id)
    # Add a pending order after drafting: the pending-set fingerprint must reject it.
    original = orders[0]
    extra = Order(
        order_no="NEW-ORDER-AFTER-DRAFT",
        customer_id=original.customer_id,
        product_id=original.product_id,
        spec_params=original.spec_params,
        quantity=10,
        unit="kg",
        status="PENDING",
    )
    db_session.add(extra)
    await db_session.commit()
    denied = await client.post(
        f"/api/agent/v2/plans/{plan.id}/apply",
        json={"expected_revision": plan.revision},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "PLAN_STALE"
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0


@pytest.mark.asyncio
async def test_failed_replacement_keeps_existing_draft(client, db_session, monkeypatch):
    from app.services.scheduling import service as schedule_service

    await _setup_schedulable(db_session)
    sid, run, _ = await run_graph(client, db_session)
    previous_id = run.generated_plan_id
    previous = await db_session.get(SchedulePlan, previous_id)
    await client.post(
        f"/api/agent/v2/plans/{previous_id}/replace",
        json={"expected_revision": previous.revision},
        headers={"Idempotency-Key": str(uuid4())},
    )

    async def unavailable(*args, **kwargs):
        raise HTTPException(409, "输入发生变化")

    monkeypatch.setattr(schedule_service, "create_schedule_plan", unavailable)
    context = await claim(db_session, "worker")
    caps = SchedulingCapabilities(context, sessions=factory(db_session), model=ScheduleModel())
    result = await build_scheduling_graph(caps).ainvoke({})
    await finalize(db_session, context, result["result"])
    assert result["result"].outcome == "NEEDS_INPUT"
    restored = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
    assert restored["session"]["active_plan_id"] == previous_id
    await db_session.refresh(previous)
    assert previous.status == "DRAFT" and previous.superseded_by_id is None
    assert await db_session.scalar(select(func.count()).select_from(SchedulePlan)) == 1


@pytest.mark.asyncio
async def test_normal_order_insert_serializes_with_agent_confirmation(independent_sessions):  # noqa: F811
    """AC26: a pending row invisible at confirmation start is rechecked after its writer commits."""
    from app.models import Customer, Formula, Machine, MachineCategory, Product, ProductCategory
    from app.schemas.agent import CreateSession, SendMessage
    from app.services import agent_schedule_service as plans
    from app.services import agent_session_service as sessions
    from app.services import order_service

    session_factory = independent_sessions
    async with session_factory() as db:
        legacy, machine, orders = await _setup_schedulable(db)
        legacy.title = "concurrency-test"
        product = await db.get(Product, orders[0].product_id)
        category_id, product_id, customer_id = product.category_id, product.id, orders[0].customer_id
        formula_id, machine_id = orders[0].formula_id, machine.id
        sid = (
            await sessions.create_session(
                db,
                "test-user",
                str(uuid4()),
                CreateSession(agent_type="SCHEDULING", title="concurrency-test"),
            )
        )["session"]["id"]
        await sessions.accept_message(db, sid, "test-user", SendMessage(**body()))
        context = await claim(db, "worker")
        session, run = await lock_run(db, context)
        generated = await plans.generate(db, session, run)
        pid, revision = generated["id"], generated["revision"]
        await db.commit()
        await finalize(db, context, RunResult("草案已生成"))

    inserted, release = asyncio.Event(), asyncio.Event()

    async def normal_insert():
        async with session_factory() as db:
            await order_service.create_order_record(
                db, customer_id, product_id, {"宽幅": "300mm", "厚度": "50μm"}, 50, "kg", formula_id, None
            )
            inserted.set()
            await release.wait()
            await db.commit()

    async def confirm():
        async with session_factory() as db:
            return await plans.plan_command(
                db, pid, "test-user", str(uuid4()), "APPLY_PLAN", {"expected_revision": revision}
            )

    writer = asyncio.create_task(normal_insert())
    confirmation = None
    try:
        await asyncio.wait_for(inserted.wait(), 3)
        confirmation = asyncio.create_task(confirm())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(confirmation), 0.2)
        release.set()
        await writer
        with pytest.raises(HTTPException) as rejected:
            await confirmation
        assert rejected.value.detail["code"] == "PLAN_STALE"
        async with session_factory() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(ProductionTask)
                    .where(ProductionTask.machine_id == machine_id)
                )
                == 0
            )
    finally:
        release.set()
        await asyncio.gather(writer, *([confirmation] if confirmation else []), return_exceptions=True)
        async with session_factory() as db:
            await db.execute(delete(Order).where(Order.product_id == product_id))
            await db.execute(delete(ProductionTask).where(ProductionTask.machine_id == machine_id))
            await db.execute(delete(MachineCategory).where(MachineCategory.machine_id == machine_id))
            await db.execute(delete(Machine).where(Machine.id == machine_id))
            await db.execute(delete(Formula).where(Formula.product_id == product_id))
            await db.execute(delete(Product).where(Product.id == product_id))
            await db.execute(delete(ProductCategory).where(ProductCategory.id == category_id))
            await db.execute(delete(Customer).where(Customer.id == customer_id))
            await db.commit()


class WorkbenchModel:
    async def ainvoke(self, messages, **kwargs):
        assert "排单说明助手" in messages[0].content
        assert not kwargs.get("tools")
        return AIMessage(content="按规格与配方匹配机器，新增任务排在已有任务之后。")


async def run_selected(client, db, ids, *, model=None):
    session = await create(client)
    request = {
        "json": {"expected_state_revision": session["state_revision"], "order_ids": ids},
        "headers": {"Idempotency-Key": str(uuid4())},
    }
    path = f"/api/agent/v2/sessions/{session['id']}/schedule"
    accepted = await client.post(path, **request)
    assert accepted.status_code == 202, accepted.text
    assert (await client.post(path, **request)).json() == accepted.json()
    context = await claim(db, "worker")
    caps = SchedulingCapabilities(context, sessions=factory(db), model=model or WorkbenchModel())
    result = await build_scheduling_graph(caps).ainvoke({})
    await finalize(db, context, result["result"])
    run = await db.get(AgentRun, context.run_id)
    return await db.get(SchedulePlan, run.generated_plan_id)


@pytest.mark.asyncio
async def test_selected_scope_edit_apply_and_unrelated_orders(client, db_session):
    from app.services.scheduling import service as schedule_service

    _, machine, orders = await _setup_schedulable(db_session)
    plan = await run_selected(client, db_session, [orders[0].id])
    assert plan.input_order_ids == [orders[0].id]
    assert plan.tasks[0]["order_ids"] == [orders[0].id]
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0
    # Other pending orders may change without invalidating this explicitly selected scope.
    orders[1].quantity = 222
    await db_session.commit()
    assert not await schedule_service.plan_is_stale(db_session, plan)
    rejected = await client.put(
        f"/api/agent/v2/plans/{plan.id}/draft",
        json={"expected_revision": 1, "tasks": [{"machine_id": machine.id, "order_ids": [orders[1].id]}]},
    )
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "INPUT_INVALID"
    removed = await client.put(
        f"/api/agent/v2/plans/{plan.id}/draft", json={"expected_revision": 1, "tasks": []}
    )
    assert removed.status_code == 200
    assert removed.json()["unassigned"][0]["order_id"] == orders[0].id
    restored = await client.put(
        f"/api/agent/v2/plans/{plan.id}/draft",
        json={"expected_revision": 2, "tasks": [{"machine_id": machine.id, "order_ids": [orders[0].id]}]},
    )
    assert restored.status_code == 200
    request = {"json": {"expected_revision": 3}, "headers": {"Idempotency-Key": str(uuid4())}}
    applied = await client.post(f"/api/agent/v2/plans/{plan.id}/apply", **request)
    assert applied.status_code == 200, applied.text
    assert (await client.post(f"/api/agent/v2/plans/{plan.id}/apply", **request)).json() == applied.json()
    for order in orders:
        await db_session.refresh(order)
    assert orders[0].status == "PRODUCING" and orders[0].task_id
    assert orders[1].status == "PENDING" and orders[1].task_id is None


@pytest.mark.asyncio
async def test_workbench_selection_validation_and_idempotence(client, db_session):
    _, _, orders = await _setup_schedulable(db_session)
    session = await create(client)
    path = f"/api/agent/v2/sessions/{session['id']}/schedule"
    for ids, code in [([], 422), ([orders[0].id] * 2, 422), (["missing"], 409)]:
        response = await client.post(
            path,
            json={"expected_state_revision": 1, "order_ids": ids},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == code, response.text
    key = str(uuid4())
    request = {
        "json": {"expected_state_revision": 1, "order_ids": [orders[0].id]},
        "headers": {"Idempotency-Key": key},
    }
    accepted = await client.post(path, **request)
    assert accepted.status_code == 202
    request["json"]["order_ids"] = [orders[1].id]
    rejected = await client.post(path, **request)
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "IDEMPOTENCY_MISMATCH"


@pytest.mark.asyncio
async def test_scoped_replacement_and_optional_explanation_failure(client, db_session):
    class BrokenExplanation:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("model unavailable")

    _, _, orders = await _setup_schedulable(db_session)
    plan = await run_selected(client, db_session, [orders[0].id], model=BrokenExplanation())
    assert plan.status == "DRAFT" and len(plan.tasks) == 1
    replaced = await client.post(
        f"/api/agent/v2/plans/{plan.id}/replace",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert replaced.status_code == 202
    context = await claim(db_session, "worker")
    caps = SchedulingCapabilities(context, sessions=factory(db_session), model=WorkbenchModel())
    result = await build_scheduling_graph(caps).ainvoke({})
    await finalize(db_session, context, result["result"])
    await db_session.refresh(plan)
    successor = await db_session.get(SchedulePlan, plan.superseded_by_id)
    assert successor.input_order_ids == [orders[0].id]
    orders[0].quantity = 333
    await db_session.commit()
    rejected = await client.post(
        f"/api/agent/v2/plans/{successor.id}/apply",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert rejected.status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0


@pytest.mark.asyncio
async def test_close_plan_requires_confirmation_and_preserves_orders(client, db_session):
    await _setup_schedulable(db_session)
    sid, run, _ = await run_graph(client, db_session)
    plan = await db_session.get(SchedulePlan, run.generated_plan_id)
    path = f"/api/agent/v2/plans/{plan.id}/close"
    for payload in ({"expected_revision": 1}, {"expected_revision": 1, "confirmed": False}):
        rejected = await client.post(path, json=payload, headers={"Idempotency-Key": str(uuid4())})
        assert rejected.status_code == 422
    request = {
        "json": {"expected_revision": 1, "confirmed": True},
        "headers": {"Idempotency-Key": str(uuid4())},
    }
    closed = await client.post(path, **request)
    assert closed.status_code == 200, closed.text
    assert (await client.post(path, **request)).json() == closed.json()
    state = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()
    assert state["session"]["active_plan_id"] is None
    saved = (await client.get(f"/api/agent/v2/plans/{plan.id}")).json()
    assert saved["status"] == "CLOSED" and saved["revision"] == 2
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0
    orders = (await db_session.scalars(select(Order))).all()
    assert len(orders) == 2 and all(order.status == "PENDING" and order.task_id is None for order in orders)
