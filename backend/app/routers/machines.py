from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.machine import MachineCreate, MachineOut
from app.services import machine_service

router = APIRouter(prefix="/machines", tags=["machines"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[MachineOut])
async def list_machines(db: AsyncSession = Depends(get_db)):
    machines = await machine_service.list_machines(db)
    return [machine_service.to_out(m) for m in machines]


@router.post("", response_model=MachineOut, status_code=status.HTTP_201_CREATED)
async def create_machine(body: MachineCreate, db: AsyncSession = Depends(get_db)):
    machine = await machine_service.create_machine(
        db,
        body.name,
        body.is_active,
        body.min_width,
        body.max_width,
        body.notes,
        body.category_ids,
        body.pattern_ids,
    )
    return machine_service.to_out(machine)


@router.put("/{machine_id}", response_model=MachineOut)
async def update_machine(machine_id: str, body: MachineCreate, db: AsyncSession = Depends(get_db)):
    machine = await machine_service.update_machine(
        db,
        machine_id,
        body.name,
        body.is_active,
        body.min_width,
        body.max_width,
        body.notes,
        body.category_ids,
        body.pattern_ids,
    )
    return machine_service.to_out(machine)


@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_machine(machine_id: str, db: AsyncSession = Depends(get_db)):
    await machine_service.delete_machine(db, machine_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
