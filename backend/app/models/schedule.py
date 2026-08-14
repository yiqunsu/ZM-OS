from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, generate_id


class SchedulePlanStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"


class SchedulePlan(Base):
    __tablename__ = "schedule_plans"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[SchedulePlanStatus] = mapped_column(
        SqlEnum(SchedulePlanStatus, name="schedule_plan_status"),
        default=SchedulePlanStatus.DRAFT,
        index=True,
    )
    input_order_ids: Mapped[list[str]] = mapped_column(JSONB)
    input_fingerprint: Mapped[dict[str, str]] = mapped_column(JSONB)
    tasks: Mapped[list[dict]] = mapped_column(JSONB)
    unassigned: Mapped[list[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped["ChatSession"] = relationship(back_populates="schedule_plans")
