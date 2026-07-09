from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Order, Product, ProductionTask
from app.models.order import OrderStatus
from app.models.production import TaskStatus

_TASK_LOAD_OPTS = (
    selectinload(ProductionTask.orders).selectinload(Order.customer),
    selectinload(ProductionTask.orders).selectinload(Order.product).selectinload(Product.category),
)


async def create_task(db: AsyncSession, machine_id: str, order_ids: list[str]) -> ProductionTask:
    if not machine_id or not order_ids:
        raise HTTPException(400, "machineId 和 orderIds 为必填项")

    max_position = await db.scalar(
        select(func.max(ProductionTask.position)).where(ProductionTask.machine_id == machine_id)
    )
    position = (max_position or 0) + 1

    task = ProductionTask(machine_id=machine_id, position=position, status=TaskStatus.PRODUCING)
    db.add(task)
    await db.flush()

    await db.execute(
        update(Order)
        .where(Order.id.in_(order_ids))
        .values(status=OrderStatus.PRODUCING, task_id=task.id)
    )

    await db.commit()
    return await _get_loaded(db, task.id)


async def update_task(
    db: AsyncSession,
    task_id: str,
    status: TaskStatus | None,
    position: int | None,
    machine_id: str | None,
    order_ids: list[str] | None,
) -> ProductionTask:
    task = await _get_loaded(db, task_id)
    if task is None:
        raise HTTPException(404, "生产任务不存在")

    if order_ids is not None:
        old_ids = {o.id for o in task.orders}
        new_ids = set(order_ids)
        removed = old_ids - new_ids
        added = new_ids - old_ids
        if removed:
            await db.execute(
                update(Order)
                .where(Order.id.in_(removed))
                .values(status=OrderStatus.PENDING, task_id=None)
            )
        if added:
            await db.execute(
                update(Order)
                .where(Order.id.in_(added))
                .values(status=OrderStatus.PRODUCING, task_id=task_id)
            )

    if status is not None:
        order_status = OrderStatus.DONE if status == TaskStatus.DONE else OrderStatus.PRODUCING
        await db.execute(update(Order).where(Order.task_id == task_id).values(status=order_status))
        task.status = status
    if position is not None:
        task.position = position
    if machine_id is not None:
        task.machine_id = machine_id

    await db.commit()
    return await _get_loaded(db, task_id)


async def delete_task(db: AsyncSession, task_id: str) -> None:
    task = await db.get(ProductionTask, task_id)
    if task is None:
        raise HTTPException(404, "生产任务不存在")

    await db.execute(
        update(Order).where(Order.task_id == task_id).values(status=OrderStatus.PENDING, task_id=None)
    )
    await db.delete(task)
    await db.commit()


async def _get_loaded(db: AsyncSession, task_id: str) -> ProductionTask | None:
    result = await db.execute(
        select(ProductionTask)
        .where(ProductionTask.id == task_id)
        .options(*_TASK_LOAD_OPTS)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()
