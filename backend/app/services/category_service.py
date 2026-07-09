from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MachineCategory, Product, ProductCategory


async def list_categories(db: AsyncSession) -> list[ProductCategory]:
    result = await db.execute(select(ProductCategory).order_by(ProductCategory.name))
    return list(result.scalars().all())


async def create_category(db: AsyncSession, name: str, desc: str | None) -> ProductCategory:
    if not name.strip():
        raise HTTPException(400, "大类名称为必填项")
    category = ProductCategory(name=name.strip(), desc=desc.strip() if desc else None)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


async def update_category(
    db: AsyncSession, category_id: str, name: str, desc: str | None
) -> ProductCategory:
    if not name.strip():
        raise HTTPException(400, "大类名称为必填项")
    category = await db.get(ProductCategory, category_id)
    if category is None:
        raise HTTPException(404, "大类不存在")
    category.name = name.strip()
    category.desc = desc.strip() if desc else None
    await db.commit()
    await db.refresh(category)
    return category


async def delete_category(db: AsyncSession, category_id: str) -> None:
    product_count = await db.scalar(
        select(func.count()).select_from(Product).where(Product.category_id == category_id)
    )
    if product_count:
        raise HTTPException(409, "该大类下存在产品，请先删除产品")

    category = await db.get(ProductCategory, category_id)
    if category is None:
        raise HTTPException(404, "大类不存在")

    await db.execute(delete(MachineCategory).where(MachineCategory.category_id == category_id))
    await db.delete(category)
    await db.commit()
