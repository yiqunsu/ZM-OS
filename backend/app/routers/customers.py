from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.customer import CustomerCreate, CustomerOut
from app.services import customer_service

router = APIRouter(prefix="/customers", tags=["customers"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[CustomerOut])
async def list_customers(db: AsyncSession = Depends(get_db)):
    return await customer_service.list_customers(db)


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(body: CustomerCreate, db: AsyncSession = Depends(get_db)):
    return await customer_service.create_customer(db, body.company, body.contact, body.notes)


@router.put("/{customer_id}", response_model=CustomerOut)
async def update_customer(customer_id: str, body: CustomerCreate, db: AsyncSession = Depends(get_db)):
    return await customer_service.update_customer(
        db, customer_id, body.company, body.contact, body.notes
    )


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(customer_id: str, db: AsyncSession = Depends(get_db)):
    await customer_service.delete_customer(db, customer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
