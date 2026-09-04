from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.kanban import KanbanOut
from app.schemas.production import (
    ProductionOrderMove,
    ProductionTaskCreate,
    ProductionTaskMove,
    ProductionTaskOut,
    ProductionTaskReorder,
    ProductionTaskUpdate,
)
from app.services import kanban_service, production_service

router = APIRouter(
    prefix="/production-tasks", tags=["production-tasks"], dependencies=[Depends(get_current_user)]
)


@router.post("", response_model=ProductionTaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(body: ProductionTaskCreate, db: AsyncSession = Depends(get_db)):
    return await production_service.create_task(db, body.machine_id, body.order_ids)


@router.post("/actions/move-order", response_model=KanbanOut)
async def move_order(body: ProductionOrderMove, db: AsyncSession = Depends(get_db)):
    await production_service.move_order(
        db,
        order_id=body.order_id,
        source_task_id=body.source_task_id,
        target_task_id=body.target_task_id,
        target_machine_id=body.target_machine_id,
    )
    return await kanban_service.get_kanban(db)


@router.post("/actions/move-task", response_model=KanbanOut)
async def move_task(body: ProductionTaskMove, db: AsyncSession = Depends(get_db)):
    await production_service.move_task(
        db,
        task_id=body.task_id,
        target_machine_id=body.target_machine_id,
        target_index=body.target_index,
    )
    return await kanban_service.get_kanban(db)


@router.post("/actions/reorder", response_model=KanbanOut)
async def reorder_tasks(body: ProductionTaskReorder, db: AsyncSession = Depends(get_db)):
    await production_service.reorder_tasks(
        db,
        machine_id=body.machine_id,
        ordered_task_ids=body.ordered_task_ids,
    )
    return await kanban_service.get_kanban(db)


@router.put("/{task_id}", response_model=ProductionTaskOut)
async def update_task(task_id: str, body: ProductionTaskUpdate, db: AsyncSession = Depends(get_db)):
    return await production_service.update_task(db, task_id, body.model_dump(exclude_unset=True))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    await production_service.delete_task(db, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
