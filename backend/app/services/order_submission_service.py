"""Atomic submission of the collaborative order workspace."""

import math
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Formula, Order, Product
from app.services import order_service
from app.services.scheduling_lock import lock_scheduling_inputs


def _quantity(value: Any) -> float:
    try:
        quantity = float(value)
    except (TypeError, ValueError) as err:
        raise HTTPException(409, "订单草稿缺少有效数量，请在右侧表单补充") from err
    if not math.isfinite(quantity) or quantity <= 0:
        raise HTTPException(409, "订单草稿缺少有效数量，请在右侧表单补充")
    return quantity


async def create_from_workspace_draft(db: AsyncSession, draft: dict[str, Any]) -> Order:
    await lock_scheduling_inputs(db)
    customer_id = str(draft.get("customer_id") or "")
    product_id = str(draft.get("product_id") or "")
    if not customer_id or await db.get(Customer, customer_id) is None:
        raise HTTPException(409, "订单草稿缺少有效客户，请在右侧表单补充")
    if not product_id or await db.get(Product, product_id) is None:
        raise HTTPException(409, "订单草稿缺少有效产品，请在右侧表单补充")

    raw_specs = draft.get("spec_params")
    spec_params = raw_specs if isinstance(raw_specs, dict) else {}
    unit = str(draft.get("unit") or "kg")
    if unit not in {"m", "g", "kg", "t", "cm", "mm"}:
        raise HTTPException(409, "订单单位仅支持 m、g、kg 或历史单位 t")

    formula_id = str(draft.get("formula_id") or "") or None
    mode = str(draft.get("formula_mode") or "none")
    if mode == "none" and formula_id:
        mode = "existing"
    if mode == "new":
        name = str(draft.get("new_formula_name") or "").strip()
        if not name:
            raise HTTPException(409, "新配方缺少名称，请在右侧表单补充")
        formula = Formula(
            name=name,
            product_id=product_id,
            spec_params=spec_params,
            materials=str(draft.get("new_formula_materials") or ""),
        )
        db.add(formula)
        await db.flush()
        formula_id = formula.id
    elif mode == "existing":
        if not formula_id:
            raise HTTPException(409, "请选择已有配方，或切换为不选配方")
        formula = await db.get(Formula, formula_id)
        if formula is None:
            raise HTTPException(409, "所选配方已不存在，请重新选择")
        if formula.product_id != product_id:
            raise HTTPException(409, "所选配方与订单产品不匹配，请重新选择")
    else:
        formula_id = None

    return await order_service.create_order_record(
        db,
        customer_id=customer_id,
        product_id=product_id,
        spec_params={str(key): str(value) for key, value in spec_params.items()},
        quantity=_quantity(draft.get("quantity")),
        unit=unit,
        formula_id=formula_id,
        extra_notes=str(draft.get("extra_notes") or "").strip() or None,
    )
