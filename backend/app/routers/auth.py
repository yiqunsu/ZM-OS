from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import CurrentUser, get_current_user
from app.schemas.auth import LoginRequest, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    if settings.AUTH_PROVIDER != "local":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "本地密码登录未启用")
    user = await auth_service.authenticate(db, body.email, body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱或密码错误")
    return user


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser = Depends(get_current_user)):
    return user
