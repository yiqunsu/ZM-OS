from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_id


class UserRole(str, enum.Enum):
    OWNER = "OWNER"
    OPERATOR = "OPERATOR"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str]
    role: Mapped[UserRole] = mapped_column(SqlEnum(UserRole, name="user_role"), default=UserRole.OPERATOR)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
