from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.product import ProductCreate, ProductOut
from app.services import product_service

router = APIRouter(prefix="/products", tags=["products"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ProductOut])
async def list_products(db: AsyncSession = Depends(get_db)):
    return await product_service.list_products(db)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(body: ProductCreate, db: AsyncSession = Depends(get_db)):
    return await product_service.create_product(db, body.name, body.category_id)


@router.put("/{product_id}", response_model=ProductOut)
async def update_product(product_id: str, body: ProductCreate, db: AsyncSession = Depends(get_db)):
    return await product_service.update_product(db, product_id, body.name, body.category_id)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: str, db: AsyncSession = Depends(get_db)):
    await product_service.delete_product(db, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
