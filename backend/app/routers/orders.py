from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.order import OrderCreate, OrderOut, OrderUpdate
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["orders"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[OrderOut])
async def list_orders(db: AsyncSession = Depends(get_db)):
    return await order_service.list_orders(db)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: str, db: AsyncSession = Depends(get_db)):
    return await order_service.get_order(db, order_id)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(body: OrderCreate, db: AsyncSession = Depends(get_db)):
    return await order_service.create_order(
        db,
        body.customer_id,
        body.product_id,
        body.spec_params,
        body.quantity,
        body.unit,
        body.formula_id,
        body.extra_notes,
    )


@router.put("/{order_id}", response_model=OrderOut)
async def update_order(order_id: str, body: OrderUpdate, db: AsyncSession = Depends(get_db)):
    fields = body.model_dump(exclude_unset=True)
    return await order_service.update_order(db, order_id, fields)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(order_id: str, db: AsyncSession = Depends(get_db)):
    await order_service.delete_order(db, order_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
