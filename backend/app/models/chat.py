from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, generate_id


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str]
    active_workspace: Mapped[str | None] = mapped_column(String(32))
    workspace_state: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session")
    schedule_plans: Mapped[list["SchedulePlan"]] = relationship(back_populates="session")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("chat_sessions.id"))
    role: Mapped[str]
    content: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB)
    tool_call_id: Mapped[str | None]
    tool_name: Mapped[str | None]
    is_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ChatSession | None"] = relationship(back_populates="messages")
    attachments: Mapped[list["ChatAttachment"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )


class ChatAttachment(Base):
    __tablename__ = "chat_attachments"
    __table_args__ = (
        CheckConstraint("byte_size > 0", name="ck_chat_attachments_byte_size_positive"),
        CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png')",
            name="ck_chat_attachments_mime_type_supported",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    mime_type: Mapped[str] = mapped_column(String(32))
    byte_size: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped["ChatMessage"] = relationship(back_populates="attachments")
