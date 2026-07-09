from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, generate_id


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    PRODUCING = "PRODUCING"
    DONE = "DONE"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    order_no: Mapped[str] = mapped_column(String, unique=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    spec_params: Mapped[dict] = mapped_column(JSONB)
    quantity: Mapped[float]
    unit: Mapped[str]
    formula_id: Mapped[str | None] = mapped_column(ForeignKey("formulas.id"))
    formula_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    extra_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[OrderStatus] = mapped_column(
        SqlEnum(OrderStatus, name="order_status"), default=OrderStatus.PENDING
    )
    task_id: Mapped[str | None] = mapped_column(ForeignKey("production_tasks.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    customer: Mapped["Customer"] = relationship(back_populates="orders")
    product: Mapped["Product"] = relationship(back_populates="orders")
    formula: Mapped["Formula | None"] = relationship(back_populates="orders")
    task: Mapped["ProductionTask | None"] = relationship(back_populates="orders")
