from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Order


async def list_customers(db: AsyncSession) -> list[Customer]:
    result = await db.execute(select(Customer).order_by(Customer.company))
    return list(result.scalars().all())


async def create_customer(db: AsyncSession, company: str, contact: str, notes: str | None) -> Customer:
    if not company or not contact:
        raise HTTPException(400, "公司名称和联系人为必填项")
    customer = Customer(company=company, contact=contact, notes=notes)
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return customer


async def update_customer(
    db: AsyncSession, customer_id: str, company: str, contact: str, notes: str | None
) -> Customer:
    if not company or not contact:
        raise HTTPException(400, "公司名称和联系人为必填项")
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "客户不存在")
    customer.company = company
    customer.contact = contact
    customer.notes = notes
    await db.commit()
    await db.refresh(customer)
    return customer


async def delete_customer(db: AsyncSession, customer_id: str) -> None:
    order_count = await db.scalar(
        select(func.count()).select_from(Order).where(Order.customer_id == customer_id)
    )
    if order_count:
        raise HTTPException(409, "该客户存在关联订单，无法删除")

    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "客户不存在")

    await db.delete(customer)
    await db.commit()
