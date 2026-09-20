import math
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Customer, Formula, Order, Product
from app.models.order import OrderStatus, order_number_sequence
from app.services.order_specification import standard_quantity, validate_specification
from app.services.scheduling_lock import lock_scheduling_inputs

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
    serial = await db.scalar(select(order_number_sequence.next_value()))
    return f"ORD-{today}-{serial:03d}"


async def _build_formula_snapshot(
    db: AsyncSession,
    formula_id: str | None,
    product_id: str | None = None,
) -> dict | None:
    if not formula_id:
        return None
    formula = await db.get(Formula, formula_id)
    if formula is None:
        raise HTTPException(400, "配方不存在")
    if product_id is not None and formula.product_id != product_id:
        raise HTTPException(400, "配方与订单产品不匹配")
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
    order = await create_order_record(
        db,
        customer_id,
        product_id,
        spec_params,
        quantity,
        unit,
        formula_id,
        extra_notes,
    )
    await db.commit()
    return await _get_loaded(db, order.id)


async def create_order_record(
    db: AsyncSession,
    customer_id: str,
    product_id: str,
    spec_params: dict,
    quantity: float,
    unit: str,
    formula_id: str | None,
    extra_notes: str | None,
) -> Order:
    """Build and flush an order without committing the surrounding use case."""
    await lock_scheduling_inputs(db)
    if not customer_id or not product_id or quantity is None or not unit:
        raise HTTPException(400, "客户、产品、数量和单位为必填项")
    if not math.isfinite(quantity) or quantity <= 0:
        raise HTTPException(400, "订单数量必须大于零")
    if unit not in {"m", "g", "kg", "t", "cm", "mm"}:
        raise HTTPException(400, "订单单位仅支持 m、g、kg 或历史单位 t")
    spec_params = validate_specification(spec_params)
    if unit not in {"m", "kg"}:
        extra_notes = "；".join(filter(None, [extra_notes, f"原始数量：{quantity:g}{unit}"]))
    quantity, unit = standard_quantity(quantity, unit)
    if await db.get(Customer, customer_id) is None:
        raise HTTPException(400, "客户不存在")
    if await db.get(Product, product_id) is None:
        raise HTTPException(400, "产品不存在")

    order_no = await _generate_order_no(db)
    formula_snapshot = await _build_formula_snapshot(db, formula_id, product_id)

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
    await db.flush()
    return order


async def update_order(db: AsyncSession, order_id: str, fields: dict[str, Any]) -> Order:
    await lock_scheduling_inputs(db)
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "订单不存在")
    if order.task_id is not None and fields:
        raise HTTPException(409, "订单已进入排产，请先通过生产看板将订单退回待排单")
    if "status" in fields and fields["status"] != OrderStatus.PENDING:
        raise HTTPException(400, "订单生产状态只能由生产任务流转更新")

    if "formula_id" in fields:
        target_product_id = fields.get("product_id", order.product_id)
        order.formula_snapshot = await _build_formula_snapshot(db, fields["formula_id"], target_product_id)
        order.formula_id = fields["formula_id"] or None
    elif "product_id" in fields and order.formula_id:
        await _build_formula_snapshot(db, order.formula_id, fields["product_id"])
    if "customer_id" in fields:
        order.customer_id = fields["customer_id"]
    if "product_id" in fields:
        order.product_id = fields["product_id"]
    if "spec_params" in fields:
        order.spec_params = validate_specification(fields["spec_params"] or {})
    if "quantity" in fields:
        order.quantity = fields["quantity"]
    if "unit" in fields:
        order.unit = fields["unit"]
    if "unit" in fields or "quantity" in fields:
        order.quantity, order.unit = standard_quantity(order.quantity, order.unit)
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
    await lock_scheduling_inputs(db)
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "订单不存在")
    if order.task_id is not None:
        raise HTTPException(409, "订单已进入排产，请先通过生产看板将订单退回待排单")
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
