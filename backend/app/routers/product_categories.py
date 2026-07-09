from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.product import ProductCategoryCreate, ProductCategoryOut
from app.services import category_service

router = APIRouter(
    prefix="/product-categories", tags=["product-categories"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=list[ProductCategoryOut])
async def list_categories(db: AsyncSession = Depends(get_db)):
    return await category_service.list_categories(db)


@router.post("", response_model=ProductCategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(body: ProductCategoryCreate, db: AsyncSession = Depends(get_db)):
    return await category_service.create_category(db, body.name, body.desc)


@router.put("/{category_id}", response_model=ProductCategoryOut)
async def update_category(
    category_id: str, body: ProductCategoryCreate, db: AsyncSession = Depends(get_db)
):
    return await category_service.update_category(db, category_id, body.name, body.desc)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: str, db: AsyncSession = Depends(get_db)):
    await category_service.delete_category(db, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
