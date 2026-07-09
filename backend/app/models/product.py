from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, generate_id


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    name: Mapped[str]
    desc: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    products: Mapped[list["Product"]] = relationship(back_populates="category")
    machine_links: Mapped[list["MachineCategory"]] = relationship(back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    name: Mapped[str]
    category_id: Mapped[str] = mapped_column(ForeignKey("product_categories.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    category: Mapped["ProductCategory"] = relationship(back_populates="products")
    formulas: Mapped[list["Formula"]] = relationship(back_populates="product")
    orders: Mapped[list["Order"]] = relationship(back_populates="product")


class Pattern(Base):
    __tablename__ = "patterns"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    name: Mapped[str]
    desc: Mapped[str | None] = mapped_column(Text)

    machine_links: Mapped[list["MachinePattern"]] = relationship(back_populates="pattern")
