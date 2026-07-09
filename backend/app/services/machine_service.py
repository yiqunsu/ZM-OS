from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Machine, MachineCategory, MachinePattern, ProductionTask
from app.schemas.machine import MachineOut

_LOAD_OPTS = (
    selectinload(Machine.category_links).selectinload(MachineCategory.category),
    selectinload(Machine.pattern_links).selectinload(MachinePattern.pattern),
)


async def list_machines(db: AsyncSession) -> list[Machine]:
    result = await db.execute(select(Machine).order_by(Machine.name).options(*_LOAD_OPTS))
    return list(result.scalars().all())


def _validate(name: str, min_width: float | None, max_width: float | None) -> None:
    if not name.strip():
        raise HTTPException(400, "机器名称为必填项")
    if min_width is None or max_width is None or float(min_width) >= float(max_width):
        raise HTTPException(400, "宽度范围不合法（最小值须小于最大值）")


async def create_machine(
    db: AsyncSession,
    name: str,
    is_active: bool,
    min_width: float,
    max_width: float,
    notes: str | None,
    category_ids: list[str],
    pattern_ids: list[str],
) -> Machine:
    _validate(name, min_width, max_width)
    machine = Machine(
        name=name.strip(),
        is_active=is_active,
        min_width=float(min_width),
        max_width=float(max_width),
        notes=notes.strip() if notes else None,
    )
    db.add(machine)
    await db.flush()

    for cid in category_ids:
        db.add(MachineCategory(machine_id=machine.id, category_id=cid))
    for pid in pattern_ids:
        db.add(MachinePattern(machine_id=machine.id, pattern_id=pid))

    await db.commit()
    return await _get_loaded(db, machine.id)


async def update_machine(
    db: AsyncSession,
    machine_id: str,
    name: str,
    is_active: bool,
    min_width: float,
    max_width: float,
    notes: str | None,
    category_ids: list[str],
    pattern_ids: list[str],
) -> Machine:
    _validate(name, min_width, max_width)
    machine = await db.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(404, "机器不存在")

    # 先删除旧的关联，再重建
    await db.execute(delete(MachineCategory).where(MachineCategory.machine_id == machine_id))
    await db.execute(delete(MachinePattern).where(MachinePattern.machine_id == machine_id))

    machine.name = name.strip()
    machine.is_active = is_active
    machine.min_width = float(min_width)
    machine.max_width = float(max_width)
    machine.notes = notes.strip() if notes else None

    for cid in category_ids:
        db.add(MachineCategory(machine_id=machine_id, category_id=cid))
    for pid in pattern_ids:
        db.add(MachinePattern(machine_id=machine_id, pattern_id=pid))

    await db.commit()
    return await _get_loaded(db, machine_id)


async def delete_machine(db: AsyncSession, machine_id: str) -> None:
    task_count = await db.scalar(
        select(func.count()).select_from(ProductionTask).where(ProductionTask.machine_id == machine_id)
    )
    if task_count:
        raise HTTPException(409, "该机器存在关联生产任务，无法删除")

    machine = await db.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(404, "机器不存在")

    await db.execute(delete(MachineCategory).where(MachineCategory.machine_id == machine_id))
    await db.execute(delete(MachinePattern).where(MachinePattern.machine_id == machine_id))
    await db.delete(machine)
    await db.commit()


async def _get_loaded(db: AsyncSession, machine_id: str) -> Machine:
    result = await db.execute(select(Machine).where(Machine.id == machine_id).options(*_LOAD_OPTS))
    return result.scalar_one()


def to_out(machine: Machine) -> MachineOut:
    return MachineOut(
        id=machine.id,
        name=machine.name,
        is_active=machine.is_active,
        min_width=machine.min_width,
        max_width=machine.max_width,
        notes=machine.notes,
        categories=[link.category for link in machine.category_links],
        patterns=[link.pattern for link in machine.pattern_links],
    )
