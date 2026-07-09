from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Machine, MachineCategory, Order, Product, ProductionTask
from app.models.order import OrderStatus
from app.models.production import TaskStatus
from app.schemas.kanban import KanbanMachine, KanbanOut
from app.schemas.production import OrderSummary, ProductionTaskOut

_TASK_ORDER_OPTS = (
    selectinload(ProductionTask.orders).selectinload(Order.customer),
    selectinload(ProductionTask.orders).selectinload(Order.product).selectinload(Product.category),
)


async def get_kanban(db: AsyncSession) -> KanbanOut:
    machines_result = await db.execute(
        select(Machine)
        .where(Machine.is_active.is_(True))
        .order_by(Machine.name)
        .options(selectinload(Machine.category_links).selectinload(MachineCategory.category))
    )
    machines = list(machines_result.scalars().all())

    tasks_result = await db.execute(
        select(ProductionTask)
        .where(
            ProductionTask.machine_id.in_([m.id for m in machines]),
            ProductionTask.status != TaskStatus.DONE,
        )
        .order_by(ProductionTask.position)
        .options(*_TASK_ORDER_OPTS)
    )
    tasks = list(tasks_result.scalars().all())
    tasks_by_machine: dict[str, list[ProductionTask]] = {}
    for t in tasks:
        tasks_by_machine.setdefault(t.machine_id, []).append(t)

    pending_result = await db.execute(
        select(Order)
        .where(Order.status == OrderStatus.PENDING, Order.task_id.is_(None))
        .order_by(Order.created_at.asc())
        .options(selectinload(Order.customer), selectinload(Order.product).selectinload(Product.category))
    )
    pending_orders = list(pending_result.scalars().all())

    kanban_machines = [
        KanbanMachine(
            id=m.id,
            name=m.name,
            is_active=m.is_active,
            min_width=m.min_width,
            max_width=m.max_width,
            notes=m.notes,
            categories=[link.category for link in m.category_links],
            tasks=[
                ProductionTaskOut(
                    id=t.id,
                    machine_id=t.machine_id,
                    position=t.position,
                    status=t.status,
                    notes=t.notes,
                    orders=[OrderSummary.model_validate(o) for o in t.orders],
                )
                for t in tasks_by_machine.get(m.id, [])
            ],
        )
        for m in machines
    ]

    return KanbanOut(
        machines=kanban_machines,
        pending_orders=[OrderSummary.model_validate(o) for o in pending_orders],
    )
