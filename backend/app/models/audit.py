from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_id


class AgentAuditLog(Base):
    """Per-turn audit trail for the AI agent: who asked what, which skill/tools ran,
    and how many tokens it cost. Supports cost control and data-leak forensics."""

    __tablename__ = "agent_audit_logs"
    __table_args__ = (
        CheckConstraint(
            "kind IS NULL OR kind IN ('RUN_FINISHED','ORDER_CREATED','SCHEDULE_APPLIED')",
            name="ck_agent_audit_logs_kind",
        ),
        Index(
            "uq_agent_audit_logs_run_kind",
            "run_id",
            "kind",
            unique=True,
            postgresql_where=text("run_id IS NOT NULL"),
        ),
        Index(
            "uq_agent_audit_logs_command_kind",
            "command_id",
            "kind",
            unique=True,
            postgresql_where=text("command_id IS NOT NULL"),
        ),
    )
    # Legacy prompt/email columns remain only until the reviewed D6 retention migration.
    kind: Mapped[str | None]
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    command_id: Mapped[str | None] = mapped_column(ForeignKey("agent_commands.id", ondelete="SET NULL"))
    object_type: Mapped[str | None]
    object_id: Mapped[str | None]
    result: Mapped[dict | None] = mapped_column(JSONB)

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    session_id: Mapped[str | None]
    user_email: Mapped[str | None]
    prompt: Mapped[str | None] = mapped_column(Text)
    skill: Mapped[str | None]
    tool_calls: Mapped[list | None] = mapped_column(JSONB)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
