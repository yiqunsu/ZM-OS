from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.kanban import KanbanOut
from app.services import kanban_service

router = APIRouter(prefix="/kanban", tags=["kanban"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=KanbanOut)
async def get_kanban(db: AsyncSession = Depends(get_db)):
    return await kanban_service.get_kanban(db)
