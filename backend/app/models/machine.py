from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, generate_id


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    name: Mapped[str]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    min_width: Mapped[float]
    max_width: Mapped[float]
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    category_links: Mapped[list["MachineCategory"]] = relationship(back_populates="machine")
    pattern_links: Mapped[list["MachinePattern"]] = relationship(back_populates="machine")
    tasks: Mapped[list["ProductionTask"]] = relationship(back_populates="machine")


class MachineCategory(Base):
    __tablename__ = "machine_categories"

    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.id"), primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("product_categories.id"), primary_key=True)

    machine: Mapped["Machine"] = relationship(back_populates="category_links")
    category: Mapped["ProductCategory"] = relationship(back_populates="machine_links")


class MachinePattern(Base):
    __tablename__ = "machine_patterns"

    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.id"), primary_key=True)
    pattern_id: Mapped[str] = mapped_column(ForeignKey("patterns.id"), primary_key=True)

    machine: Mapped["Machine"] = relationship(back_populates="pattern_links")
    pattern: Mapped["Pattern"] = relationship(back_populates="machine_links")
