from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Formula, Order, Product, ProductCategory


async def list_products(db: AsyncSession) -> list[Product]:
    result = await db.execute(
        select(Product)
        .join(ProductCategory)
        .order_by(ProductCategory.name, Product.name)
        .options(selectinload(Product.category))
    )
    return list(result.scalars().all())


async def create_product(db: AsyncSession, name: str, category_id: str) -> Product:
    if not name.strip() or not category_id:
        raise HTTPException(400, "产品名称和所属大类为必填项")
    product = Product(name=name.strip(), category_id=category_id)
    db.add(product)
    await db.commit()
    return await _get_loaded(db, product.id)


async def update_product(db: AsyncSession, product_id: str, name: str, category_id: str) -> Product:
    if not name.strip() or not category_id:
        raise HTTPException(400, "产品名称和所属大类为必填项")
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "产品不存在")
    product.name = name.strip()
    product.category_id = category_id
    await db.commit()
    return await _get_loaded(db, product_id)


async def delete_product(db: AsyncSession, product_id: str) -> None:
    order_count = await db.scalar(
        select(func.count()).select_from(Order).where(Order.product_id == product_id)
    )
    formula_count = await db.scalar(
        select(func.count()).select_from(Formula).where(Formula.product_id == product_id)
    )
    if order_count or formula_count:
        raise HTTPException(409, "该产品存在关联订单或配方，无法删除")

    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "产品不存在")

    await db.delete(product)
    await db.commit()


async def _get_loaded(db: AsyncSession, product_id: str) -> Product:
    result = await db.execute(
        select(Product).where(Product.id == product_id).options(selectinload(Product.category))
    )
    return result.scalar_one()
