"""Deterministic planning over loaded records; no database I/O or transaction ownership."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.models import Machine, Order
from app.models.production import TaskStatus
from app.services.production_rules import OrderProductionProfile as OrderInfo
from app.services.production_rules import ProductionSignature
from app.services.production_rules import order_profile as _order_info


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


def quantity_kg(order: Order) -> float | None:
    factor = {"t": 1000, "kg": 1, "g": 0.001}.get(order.unit)
    return float(order.quantity) * factor if factor is not None else None


def batch_quantity_kg(orders: list[Order]) -> float | None:
    weights = [quantity_kg(order) for order in orders]
    return None if any(weight is None for weight in weights) else sum(weights)


def load_basis(orders: list[Order], machines: list[Machine]) -> str:
    # All candidate machines must use the same comparable tie-breaker.
    queued = [
        order
        for machine in machines
        for task in machine.tasks
        if task.status != TaskStatus.DONE
        for order in task.orders
    ]
    return "TASK_COUNT" if any(quantity_kg(order) is None for order in [*orders, *queued]) else "WEIGHT_KG"


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


def _machine_states(machines: list[Machine]) -> list[MachineState]:
    states: list[MachineState] = []
    for machine in machines:
        signature, width = _last_task_signature(machine)
        states.append(
            MachineState(
                machine=machine,
                category_ids={link.category_id for link in machine.category_links},
                pattern_names={link.pattern.name.strip().casefold() for link in machine.pattern_links},
                load_kg=batch_quantity_kg(
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


def build_tasks(orders: list[Order], machines: list[Machine]) -> tuple[list[dict], list[dict]]:
    states = _machine_states(machines)
    infos = [_order_info(order) for order in orders]
    task_count_basis = load_basis(orders, machines) == "TASK_COUNT"
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
                    batch_load_kg = batch_quantity_kg([info.order for info in batch])
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
            batch_load_kg = batch_quantity_kg([info.order for info in batch])
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
