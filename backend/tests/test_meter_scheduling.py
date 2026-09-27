"""Length-based orders retain their quantity across manual and assisted production."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import Machine, MachineCategory, Order, OrderIntakeItem, ProductionTask
from app.services.agent_projections import item_snapshot
from app.services.production_service import create_task
from app.services.scheduling import service as schedule_service
from tests.test_agent_v2 import enable_v2  # noqa: F401
from tests.test_scheduling import _setup_schedulable
from tests.test_scheduling_v2 import run_selected


async def extra_machine(db, order):
    from app.models import Product

    product = await db.get(Product, order.product_id)
    machine = Machine(name="另一台机器", min_width=100, max_width=1200, is_active=True)
    db.add(machine)
    await db.flush()
    db.add(MachineCategory(machine_id=machine.id, category_id=product.category_id))
    await db.commit()
    return machine


async def queue(db, machine, source, unit, quantity):
    task = ProductionTask(machine_id=machine.id, position=1, status="WAITING")
    db.add(task)
    await db.flush()
    order = Order(
        order_no=f"QUEUED-{uuid4().hex}",
        customer_id=source.customer_id,
        product_id=source.product_id,
        formula_id=source.formula_id,
        formula_snapshot=source.formula_snapshot,
        spec_params=source.spec_params,
        quantity=quantity,
        unit=unit,
        status="PRODUCING",
        task_id=task.id,
    )
    db.add(order)
    await db.commit()
    return task


@pytest.mark.parametrize("widths", [(500, 500), (50, 50)])
async def test_meter_orders_merge_and_keep_original_quantity(client, db_session, widths):
    _, machine, orders = await _setup_schedulable(db_session, widths=widths)
    for order, quantity in zip(orders, (7500, 10000)):
        order.unit, order.quantity = "m", quantity
    await db_session.commit()
    plan = await run_selected(client, db_session, [order.id for order in orders])
    assert plan.unassigned == [] and len(plan.tasks) == 1
    assert plan.tasks[0]["order_ids"] == [order.id for order in orders]
    assert plan.tasks[0]["total_quantity_kg"] is None
    assert plan.tasks[0]["total_quantity_m"] == 17500
    assert plan.tasks[0]["total_width"] == sum(widths)
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0
    saved = await client.put(
        f"/api/agent/v2/plans/{plan.id}/draft",
        json={
            "expected_revision": 1,
            "tasks": [{"machine_id": machine.id, "order_ids": plan.input_order_ids}],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["tasks"][0]["total_quantity_m"] == 17500
    applied = await client.post(
        f"/api/agent/v2/plans/{plan.id}/apply",
        json={"expected_revision": 2},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert applied.status_code == 200, applied.text
    for order, quantity in zip(orders, (7500, 10000)):
        await db_session.refresh(order)
        assert order.unit == "m" and order.quantity == quantity and order.status == "PRODUCING"
    assert orders[0].task_id == orders[1].task_id


async def test_manual_meter_merge_and_move(client, db_session):
    _, machine, orders = await _setup_schedulable(db_session, widths=(300, 300, 300))
    for order in orders:
        order.unit = "m"
    await db_session.commit()
    response = await client.post(
        "/api/production-tasks", json={"machine_id": machine.id, "order_ids": [o.id for o in orders[:2]]}
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    moved = await client.post(
        "/api/production-tasks/actions/move-order", json={"order_id": orders[2].id, "target_task_id": task_id}
    )
    assert moved.status_code == 200, moved.text
    for order in orders:
        await db_session.refresh(order)
        assert order.task_id == task_id and order.unit == "m" and order.status == "PRODUCING"


async def test_assisted_mixed_units_stay_separate_and_reject_merge(client, db_session):
    _, machine, orders = await _setup_schedulable(db_session, widths=(500, 500))
    orders[0].unit = "m"
    await db_session.commit()
    plan = await run_selected(client, db_session, [o.id for o in orders])
    assert len(plan.tasks) == 2
    rejected = await client.put(
        f"/api/agent/v2/plans/{plan.id}/draft",
        json={
            "expected_revision": 1,
            "tasks": [{"machine_id": machine.id, "order_ids": plan.input_order_ids}],
        },
    )
    assert rejected.status_code == 409
    assert "米数与重量" in rejected.json()["error"]["message"]
    assert (await client.get(f"/api/agent/v2/plans/{plan.id}")).json()["revision"] == 1
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0


async def test_existing_meter_queue_uses_task_counts_for_all_candidates(db_session):
    session, meter_machine, orders = await _setup_schedulable(db_session, widths=(500,))
    other = await extra_machine(db_session, orders[0])
    first = await queue(db_session, meter_machine, orders[0], "m", 7500)
    second = await queue(db_session, meter_machine, orders[0], "m", 10000)
    await queue(db_session, other, orders[0], "kg", 100000)
    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")
    assert plan.input_fingerprint["__load_basis__"] == "TASK_COUNT"
    assert plan.tasks[0]["machine_id"] == other.id
    assert "粗略" in plan.tasks[0]["reason"]
    # Completed meter tasks do not affect current load or the choice of load metric.
    first.status = second.status = "DONE"
    await db_session.commit()
    updated = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")
    assert updated.input_fingerprint["__load_basis__"] == "WEIGHT_KG"
    assert updated.tasks[0]["machine_id"] == meter_machine.id


@pytest.mark.parametrize("units", [("m", "kg"), ("m", "g"), ("m", "t")])
async def test_manual_production_rejects_mixed_units(client, db_session, units):
    _, machine, orders = await _setup_schedulable(db_session, widths=(500, 500))
    for order, unit in zip(orders, units):
        order.unit = unit
    await db_session.commit()
    rejected = await client.post(
        "/api/production-tasks", json={"machine_id": machine.id, "order_ids": [o.id for o in orders]}
    )
    assert rejected.status_code == 409 and "米数与重量" in rejected.json()["detail"]
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0
    task = await create_task(db_session, machine.id, [orders[0].id])
    rejected_move = await client.post(
        "/api/production-tasks/actions/move-order", json={"order_id": orders[1].id, "target_task_id": task.id}
    )
    assert rejected_move.status_code == 409
    await db_session.refresh(orders[1])
    assert orders[1].task_id is None and orders[1].status == "PENDING"
    assert (await client.get(f"/api/orders/{orders[0].id}")).json()["unit"] == "m"


async def test_meter_width_constraints_and_old_rule_plans_still_guarded(db_session):
    session, machine, orders = await _setup_schedulable(db_session, widths=(50, 1300))
    for order in orders:
        order.unit = "m"
    await db_session.commit()
    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")
    assert not plan.tasks and len(plan.unassigned) == 2
    assert "最小生产宽度" in plan.unassigned[0]["reason"]
    with pytest.raises(HTTPException) as rejected:
        await create_task(db_session, machine.id, [orders[0].id])
    assert rejected.value.status_code == 409
    plan_id = plan.id
    await db_session.rollback()
    # Simulate a persisted plan generated before this production policy existed.
    plan = await db_session.get(type(plan), plan_id)
    plan.input_fingerprint = {k: v for k, v in plan.input_fingerprint.items() if k != "__scheduling_rules__"}
    await db_session.commit()
    assert await schedule_service.plan_is_stale(db_session, plan)
    with pytest.raises(HTTPException) as rejected:
        await schedule_service.apply_schedule_plan(db_session, plan.id, "test-user")
    assert "规则已更新" in rejected.value.detail


def test_retired_draft_warning_is_hidden_without_mutating_history():
    warning = {"field": "unit", "code": "WEIGHT_CONVERSION_UNAVAILABLE", "message": "旧提示"}
    unrelated = {"field": "customer_id", "code": "ENTITY_REQUIRED", "message": "请选择客户"}
    item = OrderIntakeItem(issues=[warning, unrelated])
    assert item_snapshot(item)["issues"] == [unrelated]
    assert item.issues == [warning, unrelated]
