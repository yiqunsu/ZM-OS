"""Load scheduling inputs and fingerprint the state used to validate drafts."""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Machine, MachineCategory, MachinePattern, Order, Product, ProductionTask
from app.models.order import OrderStatus
from app.models.production import TaskStatus

from .planner import load_basis

SCHEDULING_RULE_VERSION = 3
PENDING_SET_KEY = "__pending_order_set__"
ACTIVE_MACHINE_SET_KEY = "__active_machine_set__"
MACHINE_KEY_PREFIX = "machine:"


async def load_orders(db: AsyncSession, *, for_update: bool = False) -> list[Order]:
    stmt = (
        select(Order)
        .where(Order.status == OrderStatus.PENDING, Order.task_id.is_(None))
        .order_by(Order.created_at, Order.id)
        .options(selectinload(Order.product).selectinload(Product.category))
    )
    if for_update:
        stmt = stmt.with_for_update()
    return list((await db.execute(stmt)).scalars().all())


async def load_machines(db: AsyncSession) -> list[Machine]:
    result = await db.execute(
        select(Machine)
        .where(Machine.is_active.is_(True))
        .order_by(Machine.name, Machine.id)
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
    return list(result.scalars().unique().all())


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def machine_fingerprint(machine: Machine) -> str:
    active_tasks = sorted(
        (task for task in machine.tasks if task.status != TaskStatus.DONE),
        key=lambda task: (task.position, task.id),
    )
    return stable_hash(
        {
            "active": machine.is_active,
            "min_width": machine.min_width,
            "max_width": machine.max_width,
            "categories": sorted(link.category_id for link in machine.category_links),
            "patterns": sorted(link.pattern_id for link in machine.pattern_links),
            "queue": [
                {
                    "id": task.id,
                    "position": task.position,
                    "status": task.status.value,
                    "updated_at": task.updated_at.isoformat(),
                    "orders": sorted((order.id, order.updated_at.isoformat()) for order in task.orders),
                }
                for task in active_tasks
            ],
        }
    )


def input_fingerprint(orders: list[Order], machines: list[Machine]) -> dict[str, Any]:
    fingerprint = {order.id: order.updated_at.isoformat() for order in orders}
    fingerprint["schema_version"] = 1
    fingerprint["__scheduling_rules__"] = SCHEDULING_RULE_VERSION
    fingerprint["__load_basis__"] = load_basis(orders, machines)
    fingerprint["__order_contents__"] = stable_hash(
        [
            {
                "id": order.id,
                "quantity": order.quantity,
                "unit": order.unit,
                "spec": order.spec_params,
                "formula": order.formula_snapshot,
                "product": order.product_id,
                "category": order.product.category_id,
                "customer": order.customer_id,
                "formula_id": order.formula_id,
            }
            for order in sorted(orders, key=lambda item: item.id)
        ]
    )
    fingerprint[PENDING_SET_KEY] = stable_hash(sorted(order.id for order in orders))
    fingerprint[ACTIVE_MACHINE_SET_KEY] = stable_hash(sorted(machine.id for machine in machines))
    fingerprint.update(
        {f"{MACHINE_KEY_PREFIX}{machine.id}": machine_fingerprint(machine) for machine in machines}
    )
    return fingerprint
