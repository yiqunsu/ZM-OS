"""Deterministic, explainable scheduling draft generation and atomic application."""

import re
from collections import defaultdict
from dataclasses import dataclass
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

_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_WIDTH_KEYS = {"宽度", "width", "幅宽"}
_THICKNESS_KEYS = {"厚度", "thickness", "厚"}
_PATTERN_KEYS = {"花纹", "pattern", "纹路"}


@dataclass(frozen=True, slots=True)
class ProductionSignature:
    material: str
    category_id: str
    category_name: str
    thickness: str
    pattern: str


@dataclass(slots=True)
class OrderInfo:
    order: Order
    width: float | None
    signature: ProductionSignature


@dataclass(slots=True)
class MachineState:
    machine: Machine
    category_ids: set[str]
    pattern_names: set[str]
    load: int
    last_signature: ProductionSignature | None
    last_width: float | None


def _normalized_key(value: str) -> str:
    return value.strip().casefold().replace(" ", "")


def _spec_value(spec_params: dict[str, Any], aliases: set[str]) -> str:
    normalized_aliases = {_normalized_key(alias) for alias in aliases}
    for key, value in (spec_params or {}).items():
        if _normalized_key(str(key)) in normalized_aliases and value is not None:
            return str(value).strip()
    return ""


def _number(value: str) -> float | None:
    match = _NUMBER_RE.search(value.replace(",", ""))
    if match is None:
        return None
    try:
        parsed = float(match.group())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _signature(order: Order) -> ProductionSignature:
    snapshot = order.formula_snapshot or {}
    material = str(order.formula_id or snapshot.get("materials") or "未指定配方").strip()
    return ProductionSignature(
        material=material,
        category_id=order.product.category_id,
        category_name=order.product.category.name,
        thickness=_spec_value(order.spec_params, _THICKNESS_KEYS) or "未指定厚度",
        pattern=_spec_value(order.spec_params, _PATTERN_KEYS),
    )


def _order_info(order: Order) -> OrderInfo:
    return OrderInfo(
        order=order,
        width=_number(_spec_value(order.spec_params, _WIDTH_KEYS)),
        signature=_signature(order),
    )


def _same_signature(left: ProductionSignature, right: ProductionSignature) -> bool:
    return (
        left.material,
        left.category_id,
        left.thickness,
        left.pattern.casefold(),
    ) == (
        right.material,
        right.category_id,
        right.thickness,
        right.pattern.casefold(),
    )


def _machine_compatible(state: MachineState, info: OrderInfo) -> bool:
    if not state.machine.is_active or info.signature.category_id not in state.category_ids:
        return False
    pattern = info.signature.pattern.casefold()
    return not pattern or pattern in state.pattern_names


def _changeover_key(
    state: MachineState,
    signature: ProductionSignature,
    total_width: float,
) -> tuple[int, int, int, int, int, int, str, str]:
    previous = state.last_signature
    return (
        int(previous is not None and previous.material != signature.material),
        int(previous is not None and previous.category_id != signature.category_id),
        int(previous is not None and previous.thickness != signature.thickness),
        int(previous is not None and previous.pattern.casefold() != signature.pattern.casefold()),
        int(state.last_width is not None and state.last_width != total_width),
        state.load,
        state.machine.name,
        state.machine.id,
    )


def _reason(state: MachineState, signature: ProductionSignature, order_count: int) -> str:
    previous = state.last_signature
    if previous is None:
        prefix = "机器当前无待生产任务"
    else:
        unchanged: list[str] = []
        if previous.material == signature.material:
            unchanged.append("配方/材料")
        if previous.category_id == signature.category_id:
            unchanged.append("产品大类")
        if previous.thickness == signature.thickness:
            unchanged.append("厚度")
        if previous.pattern.casefold() == signature.pattern.casefold():
            unchanged.append("花纹")
        prefix = f"优先保持{'、'.join(unchanged)}不变" if unchanged else "在可用机器中换产代价最低"
    if order_count > 1:
        return f"{prefix}；{order_count} 张订单生产签名一致，合并生产以减少换产"
    return f"{prefix}；机器类别、宽度和花纹能力均匹配"


def _last_task_signature(machine: Machine) -> tuple[ProductionSignature | None, float | None]:
    active_tasks = [task for task in machine.tasks if task.status != TaskStatus.DONE]
    if not active_tasks:
        return None, None
    task = max(active_tasks, key=lambda item: (item.position, item.id))
    if not task.orders:
        return None, None
    infos = [_order_info(order) for order in task.orders]
    widths = [info.width for info in infos]
    total_width = sum(width for width in widths if width is not None)
    return infos[0].signature, total_width if all(width is not None for width in widths) else None


async def _load_orders(db: AsyncSession, *, for_update: bool = False) -> list[Order]:
    stmt = (
        select(Order)
        .where(Order.status == OrderStatus.PENDING, Order.task_id.is_(None))
        .order_by(Order.created_at, Order.id)
        .options(selectinload(Order.product).selectinload(Product.category))
    )
    if for_update:
        stmt = stmt.with_for_update()
    return list((await db.execute(stmt)).scalars().all())


async def _load_machines(db: AsyncSession) -> list[Machine]:
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
    )
    return list(result.scalars().unique().all())


def _machine_states(machines: list[Machine]) -> list[MachineState]:
    states: list[MachineState] = []
    for machine in machines:
        signature, width = _last_task_signature(machine)
        states.append(
            MachineState(
                machine=machine,
                category_ids={link.category_id for link in machine.category_links},
                pattern_names={link.pattern.name.strip().casefold() for link in machine.pattern_links},
                load=sum(task.status != TaskStatus.DONE for task in machine.tasks),
                last_signature=signature,
                last_width=width,
            )
        )
    return states


def _unassigned_reason(info: OrderInfo, states: list[MachineState]) -> str:
    if info.width is None:
        return "订单缺少可识别的宽度"
    category_states = [state for state in states if info.signature.category_id in state.category_ids]
    if not category_states:
        return f"没有启用且支持“{info.signature.category_name}”的机器"
    pattern = info.signature.pattern
    compatible_states = category_states
    if pattern:
        compatible_states = [
            state for state in category_states if pattern.casefold() in state.pattern_names
        ]
        if not compatible_states:
            return f"没有机器具备“{pattern}”花纹能力"
    max_width = max(state.machine.max_width for state in compatible_states)
    if info.width > max_width:
        return f"订单宽度 {info.width:g}mm 超过可用机器最大宽度 {max_width:g}mm"
    return "订单宽度未达到任何匹配机器的最小生产宽度，且无法与同签名订单合并"


def _select_batch(
    remaining: list[OrderInfo],
    state: MachineState,
) -> tuple[list[OrderInfo], float]:
    """Pick the earliest deterministic feasible batch for one machine.

    Orders that would overflow the machine are skipped instead of terminating the
    scan.  If the earliest anchor prevents the batch from reaching ``min_width``,
    every later order is tried as the anchor so a feasible combination is not lost.
    """
    for anchor in remaining:
        assert anchor.width is not None
        if anchor.width > state.machine.max_width:
            continue
        batch: list[OrderInfo] = []
        total_width = 0.0
        scan_order = [anchor, *(info for info in remaining if info is not anchor)]
        for info in scan_order:
            assert info.width is not None
            if total_width + info.width > state.machine.max_width:
                continue
            total_width += info.width
            batch.append(info)
        if batch and total_width >= state.machine.min_width:
            selected_ids = {info.order.id for info in batch}
            ordered_batch = [info for info in remaining if info.order.id in selected_ids]
            return ordered_batch, total_width
    return [], 0.0


def _build_tasks(orders: list[Order], machines: list[Machine]) -> tuple[list[dict], list[dict]]:
    states = _machine_states(machines)
    infos = [_order_info(order) for order in orders]
    unassigned: list[dict] = []
    schedulable: list[OrderInfo] = []
    for info in infos:
        if info.width is None:
            unassigned.append(
                {
                    "order_id": info.order.id,
                    "order_no": info.order.order_no,
                    "reason": _unassigned_reason(info, states),
                }
            )
        else:
            schedulable.append(info)

    groups: dict[ProductionSignature, list[OrderInfo]] = defaultdict(list)
    for info in schedulable:
        groups[info.signature].append(info)

    tasks: list[dict] = []
    for signature, group in groups.items():
        remaining = list(group)
        while remaining:
            candidates: list[tuple[tuple[Any, ...], MachineState, list[OrderInfo], float]] = []
            for state in states:
                if not _machine_compatible(state, remaining[0]):
                    continue
                batch, total_width = _select_batch(remaining, state)
                if batch:
                    candidates.append(
                        (_changeover_key(state, signature, total_width), state, batch, total_width)
                    )

            if not candidates:
                for info in remaining:
                    unassigned.append(
                        {
                            "order_id": info.order.id,
                            "order_no": info.order.order_no,
                            "reason": _unassigned_reason(info, states),
                        }
                    )
                break

            _, state, batch, total_width = min(candidates, key=lambda item: item[0])
            reason = _reason(state, signature, len(batch))
            tasks.append(
                {
                    "machine_id": state.machine.id,
                    "machine_name": state.machine.name,
                    "order_ids": [info.order.id for info in batch],
                    "order_nos": [info.order.order_no for info in batch],
                    "total_width": total_width,
                    "reason": reason,
                }
            )
            state.load += 1
            state.last_signature = signature
            state.last_width = total_width
            selected_order_ids = {info.order.id for info in batch}
            remaining = [info for info in remaining if info.order.id not in selected_order_ids]

    return tasks, unassigned


async def create_schedule_plan(
    db: AsyncSession,
    session_id: str,
    user_id: str,
) -> SchedulePlan:
    orders = await _load_orders(db)
    machines = await _load_machines(db)
    tasks, unassigned = _build_tasks(orders, machines)
    fingerprint = {order.id: order.updated_at.isoformat() for order in orders}
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
    await db.commit()
    await db.refresh(plan)
    return plan


async def get_latest_draft(
    db: AsyncSession,
    session_id: str,
    user_id: str,
) -> SchedulePlan | None:
    result = await db.execute(
        select(SchedulePlan)
        .where(
            SchedulePlan.session_id == session_id,
            SchedulePlan.created_by_id == user_id,
            SchedulePlan.status == SchedulePlanStatus.DRAFT,
        )
        .order_by(SchedulePlan.created_at.desc(), SchedulePlan.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


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
    infos = [_order_info(order) for order in typed_orders]
    if any(info.width is None for info in infos):
        raise HTTPException(409, "排产方案中的订单缺少宽度")
    if any(not _same_signature(infos[0].signature, info.signature) for info in infos[1:]):
        raise HTTPException(409, "排产方案中的合并订单生产签名已不一致")
    category_ids = {link.category_id for link in machine.category_links}
    if infos[0].signature.category_id not in category_ids:
        raise HTTPException(409, f"排产方案已过期：机器“{machine.name}”不支持该产品大类")
    pattern = infos[0].signature.pattern.casefold()
    pattern_names = {link.pattern.name.strip().casefold() for link in machine.pattern_links}
    if pattern and pattern not in pattern_names:
        raise HTTPException(409, f"排产方案已过期：机器“{machine.name}”不支持该花纹")
    total_width = sum(info.width or 0 for info in infos)
    if total_width < machine.min_width or total_width > machine.max_width:
        raise HTTPException(
            409,
            f"排产方案已过期：合并宽度 {total_width:g}mm 不在机器“{machine.name}”范围内",
        )
    return typed_orders


async def apply_schedule_plan(
    db: AsyncSession,
    plan_id: str,
    user_id: str,
) -> dict[str, Any]:
    plan = (
        await db.execute(
            select(SchedulePlan)
            .where(SchedulePlan.id == plan_id, SchedulePlan.created_by_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(404, "排产方案不存在")
    if plan.status != SchedulePlanStatus.DRAFT:
        raise HTTPException(409, "排产方案已执行，不能重复确认")
    if not plan.tasks:
        raise HTTPException(409, "排产方案没有可执行任务")

    machine_ids = {str(task.get("machine_id") or "") for task in plan.tasks}
    machine_result = await db.execute(
        select(Machine)
        .where(Machine.id.in_(machine_ids))
        .with_for_update()
        .options(
            selectinload(Machine.category_links),
            selectinload(Machine.pattern_links).selectinload(MachinePattern.pattern),
        )
    )
    machines = {machine.id: machine for machine in machine_result.scalars().unique().all()}
    if len(machines) != len(machine_ids):
        raise HTTPException(409, "排产方案中的机器已不存在")

    order_result = await db.execute(
        select(Order)
        .where(Order.id.in_(plan.input_order_ids))
        .with_for_update()
        .options(selectinload(Order.product).selectinload(Product.category))
    )
    orders = list(order_result.scalars().all())
    orders_by_id = {order.id: order for order in orders}
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
            select(func.max(ProductionTask.position)).where(
                ProductionTask.machine_id == machine_id
            )
        )
        next_positions[machine_id] = (max_position or 0) + 1

    task_ids: list[str] = []
    for _task_payload, machine, task_orders in validated:
        task = ProductionTask(
            machine_id=machine.id,
            position=next_positions[machine.id],
            status=TaskStatus.PRODUCING,
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
