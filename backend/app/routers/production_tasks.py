from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.production import ProductionTaskCreate, ProductionTaskOut, ProductionTaskUpdate
from app.services import production_service

router = APIRouter(
    prefix="/production-tasks", tags=["production-tasks"], dependencies=[Depends(get_current_user)]
)


@router.post("", response_model=ProductionTaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(body: ProductionTaskCreate, db: AsyncSession = Depends(get_db)):
    return await production_service.create_task(db, body.machine_id, body.order_ids)


@router.put("/{task_id}", response_model=ProductionTaskOut)
async def update_task(task_id: str, body: ProductionTaskUpdate, db: AsyncSession = Depends(get_db)):
    return await production_service.update_task(
        db, task_id, body.status, body.position, body.machine_id, body.order_ids
    )


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    await production_service.delete_task(db, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
