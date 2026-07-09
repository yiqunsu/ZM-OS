from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, generate_id


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    company: Mapped[str]
    contact: Mapped[str]
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
