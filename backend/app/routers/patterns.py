from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.product import PatternOut
from app.services import pattern_service

router = APIRouter(prefix="/patterns", tags=["patterns"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[PatternOut])
async def list_patterns(db: AsyncSession = Depends(get_db)):
    return await pattern_service.list_patterns(db)
