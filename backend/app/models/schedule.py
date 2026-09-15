from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, generate_id


class SchedulePlanStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class SchedulePlan(Base):
    __tablename__ = "schedule_plans"
    __table_args__ = (
        UniqueConstraint("id", "session_id", name="uq_schedule_plans_id_session"),
        CheckConstraint("revision > 0", name="ck_schedule_plans_revision"),
        Index(
            "uq_schedule_plans_v2_draft",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'DRAFT' AND created_by_run_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["created_by_run_id", "session_id"],
            ["agent_runs.id", "agent_runs.session_id"],
            name="fk_schedule_plans_created_run",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["superseded_by_id", "session_id"],
            ["schedule_plans.id", "schedule_plans.session_id"],
            name="fk_schedule_plans_superseded",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    created_by_run_id: Mapped[str | None] = mapped_column(unique=True)
    revision: Mapped[int] = mapped_column(BigInteger, default=1, server_default="1")
    applied_result: Mapped[dict | None] = mapped_column(JSONB)
    superseded_by_id: Mapped[str | None]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[SchedulePlanStatus] = mapped_column(
        SqlEnum(
            SchedulePlanStatus,
            name="schedule_plan_status",
            native_enum=False,
            create_constraint=True,
            length=32,
        ),
        default=SchedulePlanStatus.DRAFT,
        index=True,
    )
    input_order_ids: Mapped[list[str]] = mapped_column(JSONB)
    input_fingerprint: Mapped[dict] = mapped_column(JSONB)
    tasks: Mapped[list[dict]] = mapped_column(JSONB)
    unassigned: Mapped[list[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped["ChatSession"] = relationship(back_populates="schedule_plans", foreign_keys=[session_id])
