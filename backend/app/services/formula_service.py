from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Formula, Order, Product

_LOAD_OPTS = (selectinload(Formula.product).selectinload(Product.category), selectinload(Formula.source))


async def list_formulas(db: AsyncSession) -> list[Formula]:
    result = await db.execute(select(Formula).order_by(Formula.name).options(*_LOAD_OPTS))
    return list(result.scalars().all())


async def create_formula(
    db: AsyncSession,
    name: str,
    product_id: str,
    spec_params: dict,
    materials: str,
    source_id: str | None,
    notes: str | None,
) -> Formula:
    if not name.strip() or not product_id:
        raise HTTPException(400, "配方名称和关联产品为必填项")
    formula = Formula(
        name=name.strip(),
        product_id=product_id,
        spec_params=spec_params,
        materials=materials,
        source_id=source_id or None,
        notes=notes.strip() if notes else None,
    )
    db.add(formula)
    await db.commit()
    return await _get_loaded(db, formula.id)


async def update_formula(
    db: AsyncSession,
    formula_id: str,
    name: str,
    product_id: str,
    spec_params: dict,
    materials: str,
    source_id: str | None,
    notes: str | None,
) -> Formula:
    if not name.strip() or not product_id:
        raise HTTPException(400, "配方名称和关联产品为必填项")
    formula = await db.get(Formula, formula_id)
    if formula is None:
        raise HTTPException(404, "配方不存在")
    formula.name = name.strip()
    formula.product_id = product_id
    formula.spec_params = spec_params
    formula.materials = materials
    formula.source_id = source_id or None
    formula.notes = notes.strip() if notes else None
    await db.commit()
    return await _get_loaded(db, formula_id)


async def delete_formula(db: AsyncSession, formula_id: str) -> None:
    order_count = await db.scalar(
        select(func.count()).select_from(Order).where(Order.formula_id == formula_id)
    )
    if order_count:
        raise HTTPException(409, "该配方已被订单引用，无法删除")

    formula = await db.get(Formula, formula_id)
    if formula is None:
        raise HTTPException(404, "配方不存在")

    # 解除衍生配方的来源引用
    await db.execute(update(Formula).where(Formula.source_id == formula_id).values(source_id=None))
    await db.delete(formula)
    await db.commit()


async def _get_loaded(db: AsyncSession, formula_id: str) -> Formula:
    result = await db.execute(select(Formula).where(Formula.id == formula_id).options(*_LOAD_OPTS))
    return result.scalar_one()
