from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, generate_id


class TaskStatus(str, enum.Enum):
    WAITING = "WAITING"
    PRODUCING = "PRODUCING"
    DONE = "DONE"


class ProductionTask(Base):
    __tablename__ = "production_tasks"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.id"))
    position: Mapped[int]
    status: Mapped[TaskStatus] = mapped_column(
        SqlEnum(TaskStatus, name="task_status"), default=TaskStatus.WAITING
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    machine: Mapped["Machine"] = relationship(back_populates="tasks")
    orders: Mapped[list["Order"]] = relationship(back_populates="task")
