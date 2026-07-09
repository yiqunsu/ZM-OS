from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, generate_id


class Formula(Base):
    __tablename__ = "formulas"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    name: Mapped[str]
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    spec_params: Mapped[dict] = mapped_column(JSONB)
    materials: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("formulas.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    product: Mapped["Product"] = relationship(back_populates="formulas")
    source: Mapped["Formula | None"] = relationship(remote_side="Formula.id", back_populates="derived")
    derived: Mapped[list["Formula"]] = relationship(back_populates="source")
    orders: Mapped[list["Order"]] = relationship(back_populates="formula")
