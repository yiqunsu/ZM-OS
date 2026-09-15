"""Atomic production-board mutations backed by shared compatibility rules."""

from datetime import datetime, timezone

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
)
from app.models.order import OrderStatus
from app.models.production import TaskStatus
from app.services.production_rules import validate_machine_batch
from app.services.scheduling_lock import lock_scheduling_inputs

_TASK_LOAD_OPTS = (
    selectinload(ProductionTask.orders).selectinload(Order.customer),
    selectinload(ProductionTask.orders).selectinload(Order.product).selectinload(Product.category),
)
_MACHINE_LOAD_OPTS = (
    selectinload(Machine.category_links).selectinload(MachineCategory.category),
    selectinload(Machine.pattern_links).selectinload(MachinePattern.pattern),
)
_ORDER_LOAD_OPTS = (selectinload(Order.product).selectinload(Product.category),)


async def _lock_machine(db: AsyncSession, machine_id: str) -> Machine:
    result = await db.execute(
        select(Machine).where(Machine.id == machine_id).with_for_update().options(*_MACHINE_LOAD_OPTS)
    )
    machine = result.scalar_one_or_none()
    if machine is None:
        raise HTTPException(404, "机器不存在")
    return machine


async def _lock_machines(db: AsyncSession, machine_ids: set[str]) -> dict[str, Machine]:
    if not machine_ids:
        return {}
    result = await db.execute(
        select(Machine)
        .where(Machine.id.in_(machine_ids))
        .order_by(Machine.id)
        .with_for_update()
        .options(*_MACHINE_LOAD_OPTS)
        .execution_options(populate_existing=True)
    )
    machines = {machine.id: machine for machine in result.scalars().unique().all()}
    if set(machines) != machine_ids:
        raise HTTPException(404, "机器不存在")
    return machines


async def _lock_orders(db: AsyncSession, order_ids: set[str]) -> dict[str, Order]:
    if not order_ids:
        return {}
    result = await db.execute(
        select(Order)
        .where(Order.id.in_(order_ids))
        .order_by(Order.id)
        .with_for_update()
        .options(*_ORDER_LOAD_OPTS)
        .execution_options(populate_existing=True)
    )
    orders = {order.id: order for order in result.scalars().all()}
    if set(orders) != order_ids:
        raise HTTPException(404, "订单不存在")
    return orders


async def _lock_tasks(db: AsyncSession, task_ids: set[str]) -> dict[str, ProductionTask]:
    if not task_ids:
        return {}
    result = await db.execute(
        select(ProductionTask)
        .where(ProductionTask.id.in_(task_ids))
        .order_by(ProductionTask.id)
        .with_for_update()
        .options(*_TASK_LOAD_OPTS)
        .execution_options(populate_existing=True)
    )
    tasks = {task.id: task for task in result.scalars().unique().all()}
    if set(tasks) != task_ids:
        raise HTTPException(404, "生产任务不存在")
    return tasks


async def _active_queue(
    db: AsyncSession,
    machine_id: str,
    *,
    for_update: bool = False,
) -> list[ProductionTask]:
    stmt = (
        select(ProductionTask)
        .where(
            ProductionTask.machine_id == machine_id,
            ProductionTask.status != TaskStatus.DONE,
        )
        .order_by(ProductionTask.position, ProductionTask.id)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return list((await db.execute(stmt)).scalars().all())


async def _normalize_queue(db: AsyncSession, machine_id: str) -> None:
    queue = await _active_queue(db, machine_id, for_update=True)
    for position, task in enumerate(queue, start=1):
        task.position = position


def _require_waiting(task: ProductionTask) -> None:
    if task.status != TaskStatus.WAITING:
        raise HTTPException(409, "运行中或已完成的生产任务不能再拆分、合并、移动或删除")


async def create_task(db: AsyncSession, machine_id: str, order_ids: list[str]) -> ProductionTask:
    await lock_scheduling_inputs(db)
    if not machine_id or not order_ids:
        raise HTTPException(400, "machineId 和 orderIds 为必填项")
    if len(order_ids) != len(set(order_ids)):
        raise HTTPException(400, "生产任务中不能包含重复订单")

    machine = await _lock_machine(db, machine_id)
    orders_by_id = await _lock_orders(db, set(order_ids))
    orders = [orders_by_id[order_id] for order_id in order_ids]
    for order in orders:
        if order.status != OrderStatus.PENDING or order.task_id is not None:
            raise HTTPException(409, f"订单 {order.order_no} 已被其他生产任务占用")
    validate_machine_batch(machine, orders)

    max_position = await db.scalar(
        select(func.max(ProductionTask.position)).where(
            ProductionTask.machine_id == machine_id,
            ProductionTask.status != TaskStatus.DONE,
        )
    )
    task = ProductionTask(
        machine_id=machine_id,
        position=(max_position or 0) + 1,
        status=TaskStatus.WAITING,
    )
    db.add(task)
    await db.flush()
    for order in orders:
        order.status = OrderStatus.PRODUCING
        order.task_id = task.id

    await db.commit()
    loaded = await _get_loaded(db, task.id)
    assert loaded is not None
    return loaded


async def update_task(
    db: AsyncSession,
    task_id: str,
    fields: dict,
) -> ProductionTask:
    await lock_scheduling_inputs(db)
    unsupported = set(fields) - {"status", "expected_status", "expected_updated_at", "expected_order_ids"}
    if unsupported:
        raise HTTPException(400, "任务队列或订单变更请使用原子看板操作接口")
    status = fields.get("status")
    if status is None:
        raise HTTPException(400, "没有可更新的任务字段")

    initial = await db.get(ProductionTask, task_id)
    if initial is None:
        raise HTTPException(404, "生产任务不存在")
    machine = await _lock_machine(db, initial.machine_id)
    task = (await _lock_tasks(db, {task_id}))[task_id]
    if (
        fields.get("expected_status") is not None
        and fields["expected_status"] != task.status
        or fields.get("expected_updated_at") is not None
        and fields["expected_updated_at"] != task.updated_at
        or fields.get("expected_order_ids") is not None
        and set(fields["expected_order_ids"]) != {order.id for order in task.orders}
    ):
        raise HTTPException(409, "生产任务或关联订单已变化，请刷新后重新确认")

    if status == task.status:
        await db.commit()
        loaded = await _get_loaded(db, task_id)
        assert loaded is not None
        return loaded
    allowed = {
        TaskStatus.WAITING: {TaskStatus.PRODUCING},
        TaskStatus.PRODUCING: {TaskStatus.DONE, TaskStatus.WAITING},
        TaskStatus.DONE: {TaskStatus.PRODUCING},
    }
    if status not in allowed.get(task.status, set()):
        raise HTTPException(
            409, "请按“待生产 → 生产中 → 已完成”流转；生产中可撤回待生产，已完成只能恢复生产"
        )

    if status == TaskStatus.PRODUCING:
        validate_machine_batch(machine, task.orders)
        producing_id = await db.scalar(
            select(ProductionTask.id).where(
                ProductionTask.machine_id == task.machine_id,
                ProductionTask.status == TaskStatus.PRODUCING,
                ProductionTask.id != task.id,
            )
        )
        if producing_id is not None:
            raise HTTPException(409, "该机器已有生产中的任务，请先完成当前任务")
        if task.status == TaskStatus.DONE:
            queue = await _active_queue(db, task.machine_id, for_update=True)
            task.position = max((item.position for item in queue), default=0) + 1
    for order in task.orders:
        order.status = OrderStatus.DONE if status == TaskStatus.DONE else OrderStatus.PRODUCING
    task.status = status
    task.updated_at = datetime.now(timezone.utc)

    await db.commit()
    loaded = await _get_loaded(db, task_id)
    assert loaded is not None
    return loaded


async def delete_task(db: AsyncSession, task_id: str) -> None:
    await lock_scheduling_inputs(db)
    initial = await db.get(ProductionTask, task_id)
    if initial is None:
        raise HTTPException(404, "生产任务不存在")
    await _lock_machine(db, initial.machine_id)
    task = (await _lock_tasks(db, {task_id}))[task_id]
    _require_waiting(task)
    await _lock_orders(db, {order.id for order in task.orders})

    for order in task.orders:
        order.status = OrderStatus.PENDING
        order.task_id = None
    machine_id = task.machine_id
    await db.delete(task)
    await db.flush()
    await _normalize_queue(db, machine_id)
    await db.commit()


async def move_order(
    db: AsyncSession,
    *,
    order_id: str,
    source_task_id: str | None,
    target_task_id: str | None,
    target_machine_id: str | None,
) -> None:
    await lock_scheduling_inputs(db)
    if target_task_id and target_machine_id:
        raise HTTPException(400, "订单只能移动到已有任务或新机器任务中的一种")
    if source_task_id and source_task_id == target_task_id:
        return

    task_ids = {item for item in (source_task_id, target_task_id) if item}
    preview_result = await db.execute(select(ProductionTask).where(ProductionTask.id.in_(task_ids)))
    previews = {task.id: task for task in preview_result.scalars().all()}
    if set(previews) != task_ids:
        raise HTTPException(404, "生产任务不存在")
    preview_machine_ids = {task.id: task.machine_id for task in previews.values()}
    machine_ids = set(preview_machine_ids.values())
    if target_machine_id:
        machine_ids.add(target_machine_id)
    machines = await _lock_machines(db, machine_ids)
    tasks = await _lock_tasks(db, task_ids)
    if any(tasks[task_id].machine_id != preview_machine_ids[task_id] for task_id in task_ids):
        raise HTTPException(409, "生产任务位置已发生变化，请刷新后重试")
    source = tasks.get(source_task_id) if source_task_id else None
    target = tasks.get(target_task_id) if target_task_id else None
    order = (await _lock_orders(db, {order_id}))[order_id]

    if source is None:
        if order.status != OrderStatus.PENDING or order.task_id is not None:
            raise HTTPException(409, f"订单 {order.order_no} 已不在待排产区，请刷新后重试")
    else:
        _require_waiting(source)
        if order.task_id != source.id:
            raise HTTPException(409, f"订单 {order.order_no} 已不在原生产任务中，请刷新后重试")

    if target is not None:
        _require_waiting(target)
        validate_machine_batch(machines[target.machine_id], [*target.orders, order])
    elif target_machine_id is not None:
        validate_machine_batch(machines[target_machine_id], [order])

    source_machine_id: str | None = None
    if source is not None:
        source_machine_id = source.machine_id
        remaining = [item for item in source.orders if item.id != order.id]
        if remaining:
            validate_machine_batch(machines[source.machine_id], remaining)

    if target is not None:
        order.status = OrderStatus.PRODUCING
        order.task_id = target.id
    elif target_machine_id is not None:
        max_position = await db.scalar(
            select(func.max(ProductionTask.position)).where(
                ProductionTask.machine_id == target_machine_id,
                ProductionTask.status != TaskStatus.DONE,
            )
        )
        new_task = ProductionTask(
            machine_id=target_machine_id,
            position=(max_position or 0) + 1,
            status=TaskStatus.WAITING,
        )
        db.add(new_task)
        await db.flush()
        order.status = OrderStatus.PRODUCING
        order.task_id = new_task.id
    else:
        order.status = OrderStatus.PENDING
        order.task_id = None

    if source is not None and len(source.orders) == 1:
        await db.delete(source)
        await db.flush()
    if source_machine_id is not None:
        await _normalize_queue(db, source_machine_id)
    if target_machine_id is not None and target_machine_id != source_machine_id:
        await _normalize_queue(db, target_machine_id)
    await db.commit()


async def move_task(
    db: AsyncSession,
    *,
    task_id: str,
    target_machine_id: str,
    target_index: int,
) -> None:
    await lock_scheduling_inputs(db)
    initial = await db.get(ProductionTask, task_id)
    if initial is None:
        raise HTTPException(404, "生产任务不存在")
    machines = await _lock_machines(db, {initial.machine_id, target_machine_id})
    task = (await _lock_tasks(db, {task_id}))[task_id]
    _require_waiting(task)
    await _lock_orders(db, {order.id for order in task.orders})
    validate_machine_batch(machines[target_machine_id], list(task.orders))

    source_machine_id = task.machine_id
    source_queue = await _active_queue(db, source_machine_id, for_update=True)
    if target_machine_id == source_machine_id:
        queue = [item for item in source_queue if item.id != task.id]
        queue.insert(min(target_index, len(queue)), task)
        for position, item in enumerate(queue, start=1):
            item.position = position
    else:
        target_queue = await _active_queue(db, target_machine_id, for_update=True)
        task.machine_id = target_machine_id
        source_queue = [item for item in source_queue if item.id != task.id]
        target_queue.insert(min(target_index, len(target_queue)), task)
        for position, item in enumerate(source_queue, start=1):
            item.position = position
        for position, item in enumerate(target_queue, start=1):
            item.position = position
    await db.commit()


async def reorder_tasks(
    db: AsyncSession,
    *,
    machine_id: str,
    ordered_task_ids: list[str],
) -> None:
    await lock_scheduling_inputs(db)
    if len(ordered_task_ids) != len(set(ordered_task_ids)):
        raise HTTPException(400, "任务排序中不能包含重复任务")
    await _lock_machine(db, machine_id)
    queue = await _active_queue(db, machine_id, for_update=True)
    current_ids = {task.id for task in queue}
    if set(ordered_task_ids) != current_ids or len(ordered_task_ids) != len(queue):
        raise HTTPException(409, "机器任务队列已发生变化，请刷新后重新排序")
    by_id = {task.id: task for task in queue}
    for position, task_id in enumerate(ordered_task_ids, start=1):
        by_id[task_id].position = position
    await db.commit()


async def _get_loaded(db: AsyncSession, task_id: str) -> ProductionTask | None:
    result = await db.execute(
        select(ProductionTask)
        .where(ProductionTask.id == task_id)
        .options(*_TASK_LOAD_OPTS)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()
