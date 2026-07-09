from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Formula, Order, Product
from app.models.order import OrderStatus

_LOAD_OPTS = (
    selectinload(Order.customer),
    selectinload(Order.product).selectinload(Product.category),
    selectinload(Order.formula),
    selectinload(Order.task),
)


async def list_orders(db: AsyncSession) -> list[Order]:
    result = await db.execute(select(Order).order_by(Order.created_at.desc()).options(*_LOAD_OPTS))
    return list(result.scalars().all())


async def get_order(db: AsyncSession, order_id: str) -> Order:
    order = await _get_loaded(db, order_id)
    if order is None:
        raise HTTPException(404, "订单不存在")
    return order


async def _generate_order_no(db: AsyncSession) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"ORD-{today}"
    count = await db.scalar(
        select(func.count()).select_from(Order).where(Order.order_no.startswith(prefix))
    )
    return f"{prefix}-{(count or 0) + 1:03d}"


async def _build_formula_snapshot(db: AsyncSession, formula_id: str | None) -> dict | None:
    if not formula_id:
        return None
    formula = await db.get(Formula, formula_id)
    if formula is None:
        return None
    return {"name": formula.name, "specParams": formula.spec_params, "materials": formula.materials}


async def create_order(
    db: AsyncSession,
    customer_id: str,
    product_id: str,
    spec_params: dict,
    quantity: float,
    unit: str,
    formula_id: str | None,
    extra_notes: str | None,
) -> Order:
    if not customer_id or not product_id or quantity is None or not unit:
        raise HTTPException(400, "客户、产品、数量和单位为必填项")

    order_no = await _generate_order_no(db)
    formula_snapshot = await _build_formula_snapshot(db, formula_id)

    order = Order(
        order_no=order_no,
        customer_id=customer_id,
        product_id=product_id,
        spec_params=spec_params,
        quantity=quantity,
        unit=unit,
        formula_id=formula_id or None,
        formula_snapshot=formula_snapshot,
        extra_notes=extra_notes.strip() if extra_notes else None,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    await db.commit()
    return await _get_loaded(db, order.id)


async def update_order(db: AsyncSession, order_id: str, fields: dict[str, Any]) -> Order:
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "订单不存在")

    if "formula_id" in fields:
        order.formula_snapshot = await _build_formula_snapshot(db, fields["formula_id"])
        order.formula_id = fields["formula_id"] or None
    if "customer_id" in fields:
        order.customer_id = fields["customer_id"]
    if "product_id" in fields:
        order.product_id = fields["product_id"]
    if "spec_params" in fields:
        order.spec_params = fields["spec_params"] or {}
    if "quantity" in fields:
        order.quantity = fields["quantity"]
    if "unit" in fields:
        order.unit = fields["unit"]
    if "extra_notes" in fields:
        notes = fields["extra_notes"]
        order.extra_notes = notes.strip() if notes else None
    if "status" in fields:
        order.status = fields["status"]
        if fields["status"] == OrderStatus.PENDING:
            order.task_id = None

    await db.commit()
    return await _get_loaded(db, order_id)


async def delete_order(db: AsyncSession, order_id: str) -> None:
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "订单不存在")
    await db.delete(order)
    await db.commit()


async def _get_loaded(db: AsyncSession, order_id: str) -> Order | None:
    result = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(*_LOAD_OPTS)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()
