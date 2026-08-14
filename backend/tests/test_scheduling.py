from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import (
    ChatMessage,
    ChatSession,
    Customer,
    Formula,
    Machine,
    MachineCategory,
    MachinePattern,
    Order,
    Pattern,
    Product,
    ProductCategory,
    ProductionTask,
    SchedulePlan,
    SchedulePlanStatus,
)
from app.models.order import OrderStatus
from app.services import schedule_service


async def _setup_schedulable(
    db_session,
    widths=(500, 600),
    *,
    min_width=100,
    max_width=1200,
):
    category = ProductCategory(name="PE膜")
    customer = Customer(company="排产客户", contact="王工")
    machine = Machine(
        name="1号机",
        is_active=True,
        min_width=min_width,
        max_width=max_width,
    )
    session = ChatSession(title="schedule", user_id="test-user")
    db_session.add_all([category, customer, machine, session])
    await db_session.flush()
    product = Product(name="透明膜", category_id=category.id)
    db_session.add(product)
    await db_session.flush()
    formula = Formula(
        name="共享配方",
        product_id=product.id,
        spec_params={},
        materials="相同材料",
    )
    db_session.add(formula)
    await db_session.flush()
    db_session.add(MachineCategory(machine_id=machine.id, category_id=category.id))
    orders = []
    for index, width in enumerate(widths, start=1):
        order = Order(
            order_no=f"ORD-SCHEDULE-{index}",
            customer_id=customer.id,
            product_id=product.id,
            formula_id=formula.id,
            formula_snapshot={"materials": "相同材料"},
            spec_params={"厚度": "50μm", "宽度": f"{width}mm"},
            quantity=100,
            unit="kg",
            status=OrderStatus.PENDING,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
        )
        db_session.add(order)
        orders.append(order)
    await db_session.commit()
    return session, machine, orders


async def test_schedule_combines_same_signature_and_explains_unassigned(db_session):
    session, machine, orders = await _setup_schedulable(db_session)
    missing_width = Order(
        order_no="ORD-SCHEDULE-NO-WIDTH",
        customer_id=orders[0].customer_id,
        product_id=orders[0].product_id,
        spec_params={"厚度": "50μm"},
        quantity=50,
        unit="kg",
        status=OrderStatus.PENDING,
    )
    db_session.add(missing_width)
    await db_session.commit()

    plan = await schedule_service.create_schedule_plan(
        db_session, session.id, "test-user"
    )

    assert len(plan.tasks) == 1
    assert plan.tasks[0]["machine_id"] == machine.id
    assert set(plan.tasks[0]["order_ids"]) == {order.id for order in orders}
    assert plan.tasks[0]["total_width"] == 1100
    assert "合并生产" in plan.tasks[0]["reason"]
    assert plan.unassigned == [
        {
            "order_id": missing_width.id,
            "order_no": missing_width.order_no,
            "reason": "订单缺少可识别的宽度",
        }
    ]


async def test_schedule_does_not_merge_distinct_formulas_with_same_materials(db_session):
    session, _machine, orders = await _setup_schedulable(db_session, widths=(500, 500))
    second_formula = Formula(
        name="同材料不同配方",
        product_id=orders[1].product_id,
        spec_params={},
        materials="相同材料",
    )
    db_session.add(second_formula)
    await db_session.flush()
    orders[1].formula_id = second_formula.id
    await db_session.commit()

    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")

    assert len(plan.tasks) == 2
    assert all(len(task["order_ids"]) == 1 for task in plan.tasks)


async def test_schedule_reports_pattern_mismatch(db_session):
    session, _machine, orders = await _setup_schedulable(db_session, widths=(500,))
    orders[0].spec_params = {"厚度": "50μm", "宽度": "500mm", "花纹": "压花"}
    await db_session.commit()

    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")

    assert plan.tasks == []
    assert plan.unassigned[0]["order_no"] == orders[0].order_no
    assert "花纹能力" in plan.unassigned[0]["reason"]


async def test_schedule_width_reason_uses_only_pattern_capable_machines(db_session):
    session, patterned_machine, orders = await _setup_schedulable(
        db_session,
        widths=(1000,),
        max_width=800,
    )
    pattern = Pattern(name="压花")
    wider_machine = Machine(
        name="2号宽机",
        is_active=True,
        min_width=100,
        max_width=1200,
    )
    db_session.add_all([pattern, wider_machine])
    await db_session.flush()
    product = await db_session.get(Product, orders[0].product_id)
    category_id = product.category_id
    db_session.add_all(
        [
            MachinePattern(machine_id=patterned_machine.id, pattern_id=pattern.id),
            MachineCategory(machine_id=wider_machine.id, category_id=category_id),
        ]
    )
    orders[0].spec_params = {"厚度": "50μm", "宽度": "1000mm", "花纹": "压花"}
    await db_session.commit()

    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")

    assert plan.tasks == []
    assert "最大宽度 800mm" in plan.unassigned[0]["reason"]


async def test_schedule_skips_overflowing_order_to_find_later_feasible_batch(db_session):
    session, _machine, orders = await _setup_schedulable(
        db_session,
        widths=(600, 500, 100),
        min_width=700,
        max_width=1000,
    )

    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")

    assert len(plan.tasks) == 1
    assert plan.tasks[0]["order_ids"] == [orders[0].id, orders[2].id]
    assert plan.tasks[0]["total_width"] == 700
    assert [item["order_id"] for item in plan.unassigned] == [orders[1].id]


async def test_schedule_tries_later_combination_when_earliest_cannot_reach_minimum(db_session):
    session, _machine, orders = await _setup_schedulable(
        db_session,
        widths=(600, 500, 500),
        min_width=1000,
        max_width=1000,
    )

    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")

    assert len(plan.tasks) == 1
    assert plan.tasks[0]["order_ids"] == [orders[1].id, orders[2].id]
    assert plan.tasks[0]["total_width"] == 1000
    assert [item["order_id"] for item in plan.unassigned] == [orders[0].id]


async def test_apply_schedule_plan_creates_all_tasks_and_updates_orders(db_session):
    session, _machine, orders = await _setup_schedulable(db_session)
    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")

    result = await schedule_service.apply_schedule_plan(db_session, plan.id, "test-user")
    await db_session.commit()

    assert result["task_count"] == 1
    assert result["order_count"] == 2
    refreshed_plan = await db_session.get(SchedulePlan, plan.id)
    refreshed_orders = list(
        (
            await db_session.execute(
                select(Order).where(Order.id.in_([order.id for order in orders]))
            )
        ).scalars()
    )
    assert refreshed_plan.status == SchedulePlanStatus.APPLIED
    assert all(order.status == OrderStatus.PRODUCING and order.task_id for order in refreshed_orders)


async def test_apply_schedule_plan_is_atomic_when_second_task_flush_fails(
    db_session, monkeypatch
):
    session, machine, orders = await _setup_schedulable(db_session, widths=(500, 500))
    plan = SchedulePlan(
        session_id=session.id,
        created_by_id="test-user",
        status=SchedulePlanStatus.DRAFT,
        input_order_ids=[order.id for order in orders],
        input_fingerprint={order.id: order.updated_at.isoformat() for order in orders},
        tasks=[
            {
                "machine_id": machine.id,
                "machine_name": machine.name,
                "order_ids": [order.id],
                "order_nos": [order.order_no],
                "total_width": 500,
                "reason": "测试",
            }
            for order in orders
        ],
        unassigned=[],
    )
    db_session.add(plan)
    await db_session.commit()
    plan_id = plan.id
    order_ids = [order.id for order in orders]

    original_flush = db_session.flush
    flush_count = 0

    async def flaky_flush(*args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        if flush_count == 2:
            raise RuntimeError("simulated second task failure")
        return await original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", flaky_flush)
    with pytest.raises(RuntimeError, match="second task failure"):
        await schedule_service.apply_schedule_plan(db_session, plan_id, "test-user")
    await db_session.rollback()

    task_count = await db_session.scalar(
        select(func.count()).select_from(ProductionTask).where(
            ProductionTask.notes == f"智能排产方案 {plan_id}"
        )
    )
    refreshed_orders = list(
        (
            await db_session.execute(select(Order).where(Order.id.in_(order_ids)))
        ).scalars()
    )
    assert task_count == 0
    assert all(order.status == OrderStatus.PENDING and order.task_id is None for order in refreshed_orders)


async def test_apply_rejects_stale_order_without_creating_tasks(db_session):
    session, _machine, orders = await _setup_schedulable(db_session)
    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")
    orders[0].updated_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(HTTPException, match="已被修改"):
        await schedule_service.apply_schedule_plan(db_session, plan.id, "test-user")
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(ProductionTask)) == 0


async def test_confirm_schedule_clears_workspace_in_same_commit(client, db_session):
    session, _machine, _orders = await _setup_schedulable(db_session)
    session_id = session.id
    session.active_workspace = "schedule_plan"
    plan = await schedule_service.create_schedule_plan(db_session, session.id, "test-user")
    db_session.add(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            tool_calls=[
                {
                    "name": "execute_schedule_plan",
                    "args": {"plan_id": plan.id},
                    "display": {},
                }
            ],
            is_pending=True,
        )
    )
    await db_session.commit()

    response = await client.post(
        "/api/agent/chat/confirm",
        json={"session_id": session_id},
    )

    assert response.status_code == 200
    assert '"type": "schedule_applied"' in response.text
    db_session.expire_all()
    refreshed_session = await db_session.get(ChatSession, session_id)
    assert refreshed_session.active_workspace is None
