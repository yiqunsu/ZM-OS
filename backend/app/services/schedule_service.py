"""Deterministic, explainable scheduling draft generation and atomic application."""

import hashlib
import json
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
from app.services.production_rules import (
    OrderProductionProfile as OrderInfo,
)
from app.services.production_rules import (
    ProductionSignature,
    validate_machine_batch,
)
from app.services.production_rules import (
    order_profile as _order_info,
)
from app.services.scheduling_lock import lock_scheduling_inputs

SCHEDULING_RULE_VERSION = 3

_PENDING_SET_KEY = "__pending_order_set__"
_ACTIVE_MACHINE_SET_KEY = "__active_machine_set__"
_MACHINE_KEY_PREFIX = "machine:"


def plan_revision(plan: SchedulePlan) -> str:
    return _stable_hash({"tasks": plan.tasks, "unassigned": plan.unassigned})


def plan_payload(plan: SchedulePlan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "status": plan.status.value,
        "tasks": plan.tasks,
        "unassigned": plan.unassigned,
        "created_at": plan.created_at.isoformat(),
        "revision": plan_revision(plan),
    }


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
    orders = await _load_orders(db)
    scoped = plan.input_fingerprint.get("__selection_scope__", False)
    if scoped:
        orders = [order for order in orders if order.id in plan.input_order_ids]
    fingerprint = _input_fingerprint(orders, await _load_machines(db))
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
    orders = {order.id: order for order in await _load_orders(db)}
    machines = {machine.id: machine for machine in await _load_machines(db)}
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
                "total_quantity_kg": _batch_quantity_kg(batch),
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


@dataclass(slots=True)
class MachineState:
    machine: Machine
    category_ids: set[str]
    pattern_names: set[str]
    load_kg: float | None
    task_count: int
    last_signature: ProductionSignature | None
    last_width: float | None


def _machine_compatible(state: MachineState, info: OrderInfo) -> bool:
    if not state.machine.is_active or info.signature.category_id not in state.category_ids:
        return False
    pattern = info.signature.pattern.casefold()
    return not pattern or pattern in state.pattern_names


def _changeover_key(
    state: MachineState,
    signature: ProductionSignature,
    total_width: float,
    batch_load_kg: float | None,
    task_count_basis: bool,
) -> tuple[int, int, int, int, int, float, float, str, str]:
    previous = state.last_signature
    unused_ratio = (state.machine.max_width - total_width) / state.machine.max_width
    if task_count_basis:
        load = state.task_count + 1
    else:
        assert state.load_kg is not None and batch_load_kg is not None
        load = state.load_kg + batch_load_kg
    return (
        int(previous is not None and previous.material != signature.material),
        int(previous is not None and previous.category_id != signature.category_id),
        int(previous is not None and previous.thickness != signature.thickness),
        int(previous is not None and previous.pattern.casefold() != signature.pattern.casefold()),
        int(state.last_width is not None and state.last_width != total_width),
        round(unused_ratio, 6),
        load,
        state.machine.name,
        state.machine.id,
    )


def _reason(
    state: MachineState,
    signature: ProductionSignature,
    order_count: int,
    total_width: float,
) -> str:
    previous = state.last_signature
    if previous is None:
        prefix = "机器当前无待生产任务"
    else:
        unchanged: list[str] = []
        if signature.material and previous.material == signature.material:
            unchanged.append("配方/材料")
        if previous.category_id == signature.category_id:
            unchanged.append("产品大类")
        if signature.thickness and previous.thickness == signature.thickness:
            unchanged.append("厚度")
        if signature.pattern and previous.pattern.casefold() == signature.pattern.casefold():
            unchanged.append("花纹")
        prefix = f"优先保持{'、'.join(unchanged)}不变" if unchanged else "在可用机器中换产代价最低"
    utilization = total_width / state.machine.max_width * 100
    if order_count > 1:
        detail = f"{order_count} 张订单生产签名一致，合并生产以减少换产"
    else:
        detail = "机器类别、宽度和花纹能力均匹配"
    return f"{prefix}；{detail}；幅宽利用率 {utilization:.1f}%"


def _quantity_kg(order: Order) -> float | None:
    factor = {"t": 1000, "kg": 1, "g": 0.001}.get(order.unit)
    return float(order.quantity) * factor if factor is not None else None


def _batch_quantity_kg(orders: list[Order]) -> float | None:
    weights = [_quantity_kg(order) for order in orders]
    return None if any(weight is None for weight in weights) else sum(weights)


def _load_basis(orders: list[Order], machines: list[Machine]) -> str:
    # All candidate machines must use the same comparable tie-breaker.
    queued = [
        order
        for machine in machines
        for task in machine.tasks
        if task.status != TaskStatus.DONE
        for order in task.orders
    ]
    return "TASK_COUNT" if any(_quantity_kg(order) is None for order in [*orders, *queued]) else "WEIGHT_KG"


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
        .execution_options(populate_existing=True)
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
                load_kg=_batch_quantity_kg(
                    [
                        order
                        for task in machine.tasks
                        if task.status != TaskStatus.DONE
                        for order in task.orders
                    ]
                ),
                task_count=sum(task.status != TaskStatus.DONE for task in machine.tasks),
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
        compatible_states = [state for state in category_states if pattern.casefold() in state.pattern_names]
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
    best_batch: list[OrderInfo] = []
    best_width = 0.0
    best_indexes: tuple[int, ...] = ()
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
            indexes = tuple(index for index, info in enumerate(remaining) if info.order.id in selected_ids)
            if total_width > best_width or (
                total_width == best_width and (not best_indexes or indexes < best_indexes)
            ):
                best_batch = ordered_batch
                best_width = total_width
                best_indexes = indexes
    return best_batch, best_width


def _build_tasks(orders: list[Order], machines: list[Machine]) -> tuple[list[dict], list[dict]]:
    states = _machine_states(machines)
    infos = [_order_info(order) for order in orders]
    task_count_basis = _load_basis(orders, machines) == "TASK_COUNT"
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

    groups: dict[tuple[ProductionSignature, bool, str | None], list[OrderInfo]] = defaultdict(list)
    for info in schedulable:
        discriminator = None if info.signature.complete_for_merge else info.order.id
        groups[(info.signature, info.order.unit == "m", discriminator)].append(info)

    tasks: list[dict] = []
    for (signature, _meter, _discriminator), group in groups.items():
        remaining = list(group)
        while remaining:
            candidates: list[tuple[tuple[Any, ...], MachineState, list[OrderInfo], float]] = []
            for state in states:
                if not _machine_compatible(state, remaining[0]):
                    continue
                batch, total_width = _select_batch(remaining, state)
                if batch:
                    batch_load_kg = _batch_quantity_kg([info.order for info in batch])
                    candidates.append(
                        (
                            _changeover_key(
                                state,
                                signature,
                                total_width,
                                batch_load_kg,
                                task_count_basis,
                            ),
                            state,
                            batch,
                            total_width,
                        )
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
            batch_load_kg = _batch_quantity_kg([info.order for info in batch])
            reason = _reason(state, signature, len(batch), total_width)
            if task_count_basis:
                reason += "；同等条件下按未完成任务数粗略比较负载，不代表预计工时"
            tasks.append(
                {
                    "machine_id": state.machine.id,
                    "machine_name": state.machine.name,
                    "order_ids": [info.order.id for info in batch],
                    "order_nos": [info.order.order_no for info in batch],
                    "total_width": total_width,
                    "width_utilization": round(total_width / state.machine.max_width, 4),
                    "total_quantity_kg": batch_load_kg,
                    "total_quantity_m": sum(
                        float(info.order.quantity) for info in batch if info.order.unit == "m"
                    ),
                    "reason": reason,
                }
            )
            state.load_kg = (
                state.load_kg + batch_load_kg
                if state.load_kg is not None and batch_load_kg is not None
                else None
            )
            state.task_count += 1
            state.last_signature = signature
            state.last_width = total_width
            selected_order_ids = {info.order.id for info in batch}
            remaining = [info for info in remaining if info.order.id not in selected_order_ids]

    return tasks, unassigned


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _machine_fingerprint(machine: Machine) -> str:
    active_tasks = sorted(
        (task for task in machine.tasks if task.status != TaskStatus.DONE),
        key=lambda task: (task.position, task.id),
    )
    return _stable_hash(
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


def _input_fingerprint(orders: list[Order], machines: list[Machine]) -> dict[str, Any]:
    fingerprint = {order.id: order.updated_at.isoformat() for order in orders}
    fingerprint["schema_version"] = 1
    fingerprint["__scheduling_rules__"] = SCHEDULING_RULE_VERSION
    fingerprint["__load_basis__"] = _load_basis(orders, machines)
    fingerprint["__order_contents__"] = _stable_hash(
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
    fingerprint[_PENDING_SET_KEY] = _stable_hash(sorted(order.id for order in orders))
    fingerprint[_ACTIVE_MACHINE_SET_KEY] = _stable_hash(sorted(machine.id for machine in machines))
    fingerprint.update(
        {f"{_MACHINE_KEY_PREFIX}{machine.id}": _machine_fingerprint(machine) for machine in machines}
    )
    return fingerprint


async def create_schedule_plan(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    *,
    commit: bool = True,
    order_ids: list[str] | None = None,
) -> SchedulePlan:
    orders = await _load_orders(db)
    if order_ids is not None:
        selected = set(order_ids)
        if not selected or len(selected) != len(order_ids) or not selected <= {order.id for order in orders}:
            raise HTTPException(409, "选中的订单已变化，请刷新后重新选择")
        orders = [order for order in orders if order.id in selected]
    machines = await _load_machines(db)
    tasks, unassigned = _build_tasks(orders, machines)
    fingerprint = _input_fingerprint(orders, machines)
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
    expected_machine_set = plan.input_fingerprint.get(_ACTIVE_MACHINE_SET_KEY)
    if expected_machine_set and expected_machine_set != _stable_hash(
        sorted(machine.id for machine in active_machines)
    ):
        raise HTTPException(409, "排产方案已过期：可用机器集合已发生变化，请重新生成方案")
    for machine in active_machines:
        expected = plan.input_fingerprint.get(f"{_MACHINE_KEY_PREFIX}{machine.id}")
        if expected and expected != _machine_fingerprint(machine):
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
    expected_pending_set = plan.input_fingerprint.get(_PENDING_SET_KEY)
    if expected_pending_set and expected_pending_set != _stable_hash(current_pending_ids):
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
    current_contents = _input_fingerprint(orders, active_machines)["__order_contents__"]
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
