from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.agent import AgentType, enum_check, session_reference
from app.models.base import Base, generate_id


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        enum_check("agent_type", AgentType, "ck_chat_sessions_agent_type"),
        enum_check("status", ("ACTIVE", "ARCHIVED", "DELETING"), "ck_chat_sessions_status"),
        CheckConstraint("agent_type = 'LEGACY' OR user_id IS NOT NULL", name="ck_chat_sessions_owner"),
        CheckConstraint("state_revision > 0 AND last_event_seq >= 0", name="ck_chat_sessions_revision"),
        CheckConstraint("octet_length(state::text) <= 16384", name="ck_chat_sessions_state_size"),
        CheckConstraint(
            "active_work_item_id IS NULL OR agent_type = 'ORDER_INTAKE'", name="ck_chat_sessions_item_type"
        ),
        CheckConstraint(
            "active_plan_id IS NULL OR agent_type = 'SCHEDULING'", name="ck_chat_sessions_plan_type"
        ),
        ForeignKeyConstraint(
            ["active_work_item_id", "id"],
            ["order_intake_items.id", "order_intake_items.session_id"],
            name="fk_chat_sessions_active_item",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["active_plan_id", "id"],
            ["schedule_plans.id", "schedule_plans.session_id"],
            name="fk_chat_sessions_active_plan",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_chat_sessions_owner_status", "user_id", "status", "updated_at", "id"),
    )
    # LEGACY remains the v1 default during the expand phase; v2 sets its type explicitly.
    agent_type: Mapped[str] = mapped_column(default="LEGACY", server_default="LEGACY")
    status: Mapped[str] = mapped_column(default="ACTIVE", server_default="ACTIVE")
    state_schema_version: Mapped[int] = mapped_column(default=1, server_default="1")
    state_revision: Mapped[int] = mapped_column(BigInteger, default=1, server_default="1")
    state: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    active_work_item_id: Mapped[str | None]
    active_plan_id: Mapped[str | None]
    last_event_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str]
    active_workspace: Mapped[str | None] = mapped_column(String(32))
    workspace_state: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", foreign_keys="ChatMessage.session_id"
    )
    schedule_plans: Mapped[list["SchedulePlan"]] = relationship(
        back_populates="session", foreign_keys="SchedulePlan.session_id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("id", "session_id", name="uq_chat_messages_id_session"),
        UniqueConstraint("session_id", "client_message_id", name="uq_chat_messages_client_id"),
        enum_check("origin", ("USER", "AGENT", "BUSINESS", "MIGRATION"), "ck_chat_messages_origin"),
        CheckConstraint(
            "origin = 'MIGRATION' OR (session_id IS NOT NULL AND event_seq > 0 AND content "
            "IS NOT NULL AND role IN ('user','assistant','system'))",
            name="ck_chat_messages_v2",
        ),
        CheckConstraint(
            "origin != 'USER' OR (client_message_id IS NOT NULL AND request_hash IS NOT "
            "NULL AND role = 'user')",
            name="ck_chat_messages_user",
        ),
        CheckConstraint(
            "origin != 'AGENT' OR (run_id IS NOT NULL AND role = 'assistant')", name="ck_chat_messages_agent"
        ),
        Index("uq_chat_messages_run_final", "run_id", unique=True, postgresql_where=text("origin = 'AGENT'")),
        Index(
            "uq_chat_messages_command_final",
            "command_id",
            unique=True,
            postgresql_where=text("origin = 'BUSINESS'"),
        ),
        Index("ix_chat_messages_session_seq", "session_id", "event_seq", "id"),
        session_reference("chat_messages", "run_id", "agent_runs"),
        session_reference("chat_messages", "command_id", "agent_commands"),
        session_reference("chat_messages", "work_item_id", "order_intake_items"),
    )
    client_message_id: Mapped[str | None]
    request_hash: Mapped[str | None] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(default="MIGRATION", server_default="MIGRATION")
    content_schema_version: Mapped[int] = mapped_column(default=1, server_default="1")
    run_id: Mapped[str | None]
    command_id: Mapped[str | None]
    work_item_id: Mapped[str | None] = mapped_column(index=True)
    event_seq: Mapped[int | None] = mapped_column(BigInteger)

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    role: Mapped[str]
    content: Mapped[str | None] = mapped_column(Text)
    presentation: Mapped[dict | None] = mapped_column(JSONB)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB)
    tool_call_id: Mapped[str | None]
    tool_name: Mapped[str | None]
    is_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ChatSession | None"] = relationship(back_populates="messages", foreign_keys=[session_id])
    attachments: Mapped[list["ChatAttachment"]] = relationship(
        back_populates="message",
        foreign_keys="ChatAttachment.message_id",
        cascade="all, delete-orphan",
    )


class ChatAttachment(Base):
    __tablename__ = "chat_attachments"
    __table_args__ = (
        UniqueConstraint("id", "session_id", name="uq_chat_attachments_id_session"),
        UniqueConstraint("session_id", "client_upload_id", name="uq_chat_attachments_upload"),
        UniqueConstraint("message_id", "position", name="uq_chat_attachments_position"),
        enum_check("status", ("STAGED", "BOUND"), "ck_chat_attachments_status"),
        CheckConstraint(
            "status != 'STAGED' OR (message_id IS NULL AND expires_at IS NOT NULL AND "
            "session_id IS NOT NULL)",
            name="ck_chat_attachments_staged",
        ),
        CheckConstraint("status != 'BOUND' OR message_id IS NOT NULL", name="ck_chat_attachments_bound"),
        CheckConstraint("position IS NULL OR position BETWEEN 0 AND 4", name="ck_chat_attachments_position"),
        CheckConstraint(
            "(width_px IS NULL AND height_px IS NULL) OR (width_px > 0 AND height_px > 0 "
            "AND width_px::bigint * height_px <= 20000000)",
            name="ck_chat_attachments_pixels",
        ),
        session_reference("chat_attachments", "message_id", "chat_messages"),
        Index("ix_chat_attachments_expiry", "status", "expires_at"),
        CheckConstraint("intake_revision >= 0", name="ck_chat_attachments_intake_revision"),
        CheckConstraint("byte_size > 0", name="ck_chat_attachments_byte_size_positive"),
        CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png')",
            name="ck_chat_attachments_mime_type_supported",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    client_upload_id: Mapped[str | None]
    position: Mapped[int | None] = mapped_column(default=0, server_default="0")
    status: Mapped[str] = mapped_column(default="BOUND", server_default="BOUND")
    width_px: Mapped[int | None]
    height_px: Mapped[int | None]
    sha256: Mapped[str | None] = mapped_column(String(64))
    intake_archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intake_revision: Mapped[int] = mapped_column(default=0, server_default="0")
    available: Mapped[bool] = mapped_column(default=True, server_default="true")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mime_type: Mapped[str] = mapped_column(String(32))
    byte_size: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped["ChatMessage"] = relationship(back_populates="attachments", foreign_keys=[message_id])
