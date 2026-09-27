"""Scheduling use cases; preserve caller-owned commits and atomic plan application."""

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Machine,
    MachineCategory,
    MachinePattern,
    Order,
    Product,
    ProductionTask,
    SchedulePlan,
    SchedulePlanStatus,
)
from app.models.order import OrderStatus
from app.models.production import TaskStatus
from app.services.production_rules import validate_machine_batch
from app.services.scheduling_lock import lock_scheduling_inputs

from .inputs import (
    ACTIVE_MACHINE_SET_KEY,
    MACHINE_KEY_PREFIX,
    PENDING_SET_KEY,
    SCHEDULING_RULE_VERSION,
    input_fingerprint,
    load_machines,
    load_orders,
    machine_fingerprint,
    stable_hash,
)
from .planner import batch_quantity_kg, build_tasks


def plan_revision(plan: SchedulePlan) -> str:
    return stable_hash({"tasks": plan.tasks, "unassigned": plan.unassigned})


async def require_plan(
    db: AsyncSession,
    plan_id: str,
    user_id: str,
    *,
    lock: bool = False,
    allow_v2: bool = False,
) -> SchedulePlan:
    stmt = select(SchedulePlan).where(
        SchedulePlan.id == plan_id,
        SchedulePlan.created_by_id == user_id,
    )
    if not allow_v2:
        stmt = stmt.where(SchedulePlan.created_by_run_id.is_(None))
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    plan = (await db.execute(stmt)).scalar_one_or_none()
    if plan is None:
        raise HTTPException(404, "排产方案不存在")
    return plan


async def plan_is_stale(db: AsyncSession, plan: SchedulePlan) -> bool:
    orders = await load_orders(db)
    scoped = plan.input_fingerprint.get("__selection_scope__", False)
    if scoped:
        orders = [order for order in orders if order.id in plan.input_order_ids]
    fingerprint = input_fingerprint(orders, await load_machines(db))
    if scoped:
        fingerprint["__selection_scope__"] = True
    return plan.input_fingerprint != fingerprint


async def update_schedule_draft(
    db: AsyncSession,
    plan_id: str,
    user_id: str,
    revision: str,
    tasks: list[dict],
    *,
    commit: bool = True,
    allow_v2: bool = False,
) -> SchedulePlan:
    plan = await require_plan(db, plan_id, user_id, lock=True, allow_v2=allow_v2)
    await lock_scheduling_inputs(db)
    if plan.status != SchedulePlanStatus.DRAFT or revision != plan_revision(plan):
        raise HTTPException(409, "草案已被修改或执行，请重新加载")
    if await plan_is_stale(db, plan):
        raise HTTPException(409, "生产数据已变化，请重新生成方案")
    orders = {order.id: order for order in await load_orders(db)}
    machines = {machine.id: machine for machine in await load_machines(db)}
    assigned: set[str] = set()
    normalized = []
    for task in tasks:
        machine = machines.get(task["machine_id"])
        if machine is None:
            raise HTTPException(409, "机器不存在或已停用")
        ids = task["order_ids"]
        if any(key in assigned for key in ids) or len(ids) != len(set(ids)):
            raise HTTPException(409, "草案中存在重复订单")
        if any(key not in plan.input_order_ids or key not in orders for key in ids):
            raise HTTPException(409, "订单不属于本草案")
        batch = [orders[key] for key in ids]
        width = validate_machine_batch(machine, batch)
        assigned.update(ids)
        normalized.append(
            {
                "machine_id": machine.id,
                "machine_name": machine.name,
                "order_ids": ids,
                "order_nos": [order.order_no for order in batch],
                "total_width": width,
                "width_utilization": round(width / machine.max_width, 4),
                "total_quantity_kg": batch_quantity_kg(batch),
                "total_quantity_m": sum(float(order.quantity) for order in batch if order.unit == "m"),
                "reason": "人工调整；已通过机器能力与合并规则校验",
            }
        )
    plan.tasks = normalized
    plan.unassigned = [
        {"order_id": key, "order_no": orders[key].order_no, "reason": "尚未安排到草案任务"}
        for key in plan.input_order_ids
        if key not in assigned
    ]
    if commit:
        await db.commit()
    else:
        await db.flush()
    return plan


async def create_schedule_plan(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    *,
    commit: bool = True,
    order_ids: list[str] | None = None,
) -> SchedulePlan:
    orders = await load_orders(db)
    if order_ids is not None:
        selected = set(order_ids)
        if not selected or len(selected) != len(order_ids) or not selected <= {order.id for order in orders}:
            raise HTTPException(409, "选中的订单已变化，请刷新后重新选择")
        orders = [order for order in orders if order.id in selected]
    machines = await load_machines(db)
    tasks, unassigned = build_tasks(orders, machines)
    fingerprint = input_fingerprint(orders, machines)
    if order_ids is not None:
        fingerprint["__selection_scope__"] = True
    plan = SchedulePlan(
        session_id=session_id,
        created_by_id=user_id,
        status=SchedulePlanStatus.DRAFT,
        input_order_ids=[order.id for order in orders],
        input_fingerprint=fingerprint,
        tasks=tasks,
        unassigned=unassigned,
    )
    db.add(plan)
    if commit:
        await db.commit()
        await db.refresh(plan)
    else:
        await db.flush()
    return plan


def _validate_task(
    task: dict[str, Any],
    machine: Machine,
    orders_by_id: dict[str, Order],
) -> list[Order]:
    if not machine.is_active:
        raise HTTPException(409, f"排产方案已过期：机器“{machine.name}”已停用")
    order_ids = task.get("order_ids")
    if not isinstance(order_ids, list) or not order_ids:
        raise HTTPException(409, "排产方案中的任务没有订单")
    orders = [orders_by_id.get(str(order_id)) for order_id in order_ids]
    if any(order is None for order in orders):
        raise HTTPException(409, "排产方案引用了不存在的订单")
    typed_orders = [order for order in orders if order is not None]
    validate_machine_batch(machine, typed_orders)
    return typed_orders


async def apply_schedule_plan(
    db: AsyncSession,
    plan_id: str,
    user_id: str,
    *,
    allow_v2: bool = False,
) -> dict[str, Any]:
    plan = (
        await db.execute(
            select(SchedulePlan)
            .where(SchedulePlan.id == plan_id, SchedulePlan.created_by_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if plan is None or (plan.created_by_run_id is not None and not allow_v2):
        raise HTTPException(404, "排产方案不存在")
    if plan.status != SchedulePlanStatus.DRAFT:
        raise HTTPException(409, "排产方案已执行，不能重复确认")
    await lock_scheduling_inputs(db)
    if plan.input_fingerprint.get("__scheduling_rules__") != SCHEDULING_RULE_VERSION:
        raise HTTPException(409, "排单规则已更新，请重新生成草稿")
    if not plan.tasks:
        raise HTTPException(409, "排产方案没有可执行任务")

    machine_ids = {str(task.get("machine_id") or "") for task in plan.tasks}
    machine_result = await db.execute(
        select(Machine)
        .order_by(Machine.id)
        .with_for_update()
        .options(
            selectinload(Machine.category_links).selectinload(MachineCategory.category),
            selectinload(Machine.pattern_links).selectinload(MachinePattern.pattern),
            selectinload(Machine.tasks)
            .selectinload(ProductionTask.orders)
            .selectinload(Order.product)
            .selectinload(Product.category),
        )
        .execution_options(populate_existing=True)
    )
    machines = {machine.id: machine for machine in machine_result.scalars().unique().all()}
    if not machine_ids.issubset(machines):
        raise HTTPException(409, "排产方案中的机器已不存在")

    active_machines = [machine for machine in machines.values() if machine.is_active]
    expected_machine_set = plan.input_fingerprint.get(ACTIVE_MACHINE_SET_KEY)
    if expected_machine_set and expected_machine_set != stable_hash(
        sorted(machine.id for machine in active_machines)
    ):
        raise HTTPException(409, "排产方案已过期：可用机器集合已发生变化，请重新生成方案")
    for machine in active_machines:
        expected = plan.input_fingerprint.get(f"{MACHINE_KEY_PREFIX}{machine.id}")
        if expected and expected != machine_fingerprint(machine):
            raise HTTPException(
                409,
                f"排产方案已过期：机器“{machine.name}”的能力或任务队列已变化",
            )

    current_pending_ids = list(
        (
            await db.execute(
                select(Order.id)
                .where(Order.status == OrderStatus.PENDING, Order.task_id.is_(None))
                .order_by(Order.id)
                .with_for_update()
            )
        ).scalars()
    )
    if plan.input_fingerprint.get("__selection_scope__"):
        current_pending_ids = [oid for oid in current_pending_ids if oid in plan.input_order_ids]
    expected_pending_set = plan.input_fingerprint.get(PENDING_SET_KEY)
    if expected_pending_set and expected_pending_set != stable_hash(current_pending_ids):
        raise HTTPException(409, "排产方案已过期：待排订单集合已发生变化，请重新生成方案")

    order_result = await db.execute(
        select(Order)
        .where(Order.id.in_(plan.input_order_ids))
        .with_for_update()
        .options(selectinload(Order.product).selectinload(Product.category))
    )
    orders = list(order_result.scalars().all())
    orders_by_id = {order.id: order for order in orders}
    expected_contents = plan.input_fingerprint.get("__order_contents__")
    current_contents = input_fingerprint(orders, active_machines)["__order_contents__"]
    if expected_contents and expected_contents != current_contents:
        raise HTTPException(409, "排产方案已过期：订单内容已变化")
    if set(orders_by_id) != set(plan.input_order_ids):
        raise HTTPException(409, "排产方案已过期：部分订单已不存在")
    for order in orders:
        if order.updated_at.isoformat() != plan.input_fingerprint.get(order.id):
            raise HTTPException(409, f"排产方案已过期：订单 {order.order_no} 已被修改")

    assigned_ids: list[str] = []
    validated: list[tuple[dict[str, Any], Machine, list[Order]]] = []
    for task in plan.tasks:
        machine = machines[str(task.get("machine_id") or "")]
        task_orders = _validate_task(task, machine, orders_by_id)
        validated.append((task, machine, task_orders))
        assigned_ids.extend(order.id for order in task_orders)
    if len(assigned_ids) != len(set(assigned_ids)):
        raise HTTPException(409, "排产方案中存在重复订单")
    for order_id in assigned_ids:
        order = orders_by_id[order_id]
        if order.status != OrderStatus.PENDING or order.task_id is not None:
            raise HTTPException(409, f"排产方案已过期：订单 {order.order_no} 已被占用")

    next_positions: dict[str, int] = {}
    for machine_id in machine_ids:
        max_position = await db.scalar(
            select(func.max(ProductionTask.position)).where(ProductionTask.machine_id == machine_id)
        )
        next_positions[machine_id] = (max_position or 0) + 1

    task_ids: list[str] = []
    for _task_payload, machine, task_orders in validated:
        task = ProductionTask(
            machine_id=machine.id,
            position=next_positions[machine.id],
            status=TaskStatus.WAITING,
            notes=f"智能排产方案 {plan.id}",
        )
        next_positions[machine.id] += 1
        db.add(task)
        await db.flush()
        task_ids.append(task.id)
        for order in task_orders:
            order.status = OrderStatus.PRODUCING
            order.task_id = task.id

    plan.status = SchedulePlanStatus.APPLIED
    plan.applied_at = datetime.now(timezone.utc)
    await db.flush()
    return {
        "plan_id": plan.id,
        "task_ids": task_ids,
        "task_count": len(task_ids),
        "order_count": len(assigned_ids),
    }
