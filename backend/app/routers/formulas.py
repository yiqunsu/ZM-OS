from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.formula import FormulaCreate, FormulaOut
from app.services import formula_service

router = APIRouter(prefix="/formulas", tags=["formulas"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[FormulaOut])
async def list_formulas(db: AsyncSession = Depends(get_db)):
    return await formula_service.list_formulas(db)


@router.post("", response_model=FormulaOut, status_code=status.HTTP_201_CREATED)
async def create_formula(body: FormulaCreate, db: AsyncSession = Depends(get_db)):
    return await formula_service.create_formula(
        db, body.name, body.product_id, body.spec_params, body.materials, body.source_id, body.notes
    )


@router.put("/{formula_id}", response_model=FormulaOut)
async def update_formula(formula_id: str, body: FormulaCreate, db: AsyncSession = Depends(get_db)):
    return await formula_service.update_formula(
        db,
        formula_id,
        body.name,
        body.product_id,
        body.spec_params,
        body.materials,
        body.source_id,
        body.notes,
    )


@router.delete("/{formula_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_formula(formula_id: str, db: AsyncSession = Depends(get_db)):
    await formula_service.delete_formula(db, formula_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
