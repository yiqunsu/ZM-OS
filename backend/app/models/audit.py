from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_id


class AgentAuditLog(Base):
    """Per-turn audit trail for the AI agent: who asked what, which skill/tools ran,
    and how many tokens it cost. Supports cost control and data-leak forensics."""

    __tablename__ = "agent_audit_logs"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    session_id: Mapped[str | None]
    user_email: Mapped[str | None]
    prompt: Mapped[str | None] = mapped_column(Text)
    skill: Mapped[str | None]
    tool_calls: Mapped[list | None] = mapped_column(JSONB)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
