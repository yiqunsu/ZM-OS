"""Durable Agent execution records. Business drafts outlive individual runs."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_id


class AgentType(StrEnum):
    ORDER_INTAKE = "ORDER_INTAKE"
    SCHEDULING = "SCHEDULING"
    LEGACY = "LEGACY"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunOutcome(StrEnum):
    ANSWERED = "ANSWERED"
    NEEDS_INPUT = "NEEDS_INPUT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    QUEUED_ONLY = "QUEUED_ONLY"
    DRAFT_READY = "DRAFT_READY"
    NO_PENDING = "NO_PENDING"
    NO_FEASIBLE = "NO_FEASIBLE"
    LIMIT_REACHED = "LIMIT_REACHED"


EVENT_KINDS = (
    "session.created",
    "session.archived",
    "session.restored",
    "session.deleting",
    "session.state_changed",
    "message.accepted",
    "message.completed",
    "command.accepted",
    "run.queued",
    "run.started",
    "run.progress",
    "run.succeeded",
    "run.failed",
    "run.cancelled",
    "admittance.decided",
    "work_item.queued",
    "work_item.activated",
    "work_item.deferred",
    "work_item.closed",
    "work_item.created",
    "recognition.completed",
    "recognition.failed",
    "draft.updated",
    "plan.generated",
    "plan.updated",
    "plan.superseded",
    "plan.closed",
    "plan.applied",
    "tool.started",
    "tool.succeeded",
    "tool.failed",
    "tool.abandoned",
    "assistant.delta",
)
COMMAND_KINDS = (
    "RECOGNIZE_ITEM",
    "ARCHIVE_SCREENSHOT",
    "RESTORE_SCREENSHOT",
    "DELETE_SCREENSHOT",
    "CREATE_SESSION",
    "NEXT_ITEM",
    "SELECT_ITEM",
    "DEFER_ITEM",
    "CLOSE_ITEM",
    "CONFIRM_ORDER",
    "APPLY_PLAN",
    "REPLACE_PLAN",
    "CLOSE_PLAN",
    "RETRY_RUN",
    "ARCHIVE_SESSION",
    "RESTORE_SESSION",
    "DELETE_SESSION",
)
OPEN_RUN_STATUSES = ("QUEUED", "RUNNING")


def enum_check(column: str, values, name: str):
    return CheckConstraint(f"{column} IN ({','.join(repr(str(v)) for v in values)})", name=name)


def session_reference(table: str, column: str, target: str):
    # Deferred references allow message/event/run cycles to commit atomically.
    return ForeignKeyConstraint(
        [column, "session_id"],
        [f"{target}.id", f"{target}.session_id"],
        name=f"fk_{table}_{column}_session",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("id", "session_id", name="uq_agent_runs_id_session"),
        enum_check("status", RunStatus, "ck_agent_runs_status"),
        enum_check("outcome", RunOutcome, "ck_agent_runs_outcome"),
        enum_check(
            "trigger_kind",
            ("MESSAGE", "NEXT_ITEM", "RESUME_ITEM", "RETRY", "REPLACE_PLAN"),
            "ck_agent_runs_trigger",
        ),
        CheckConstraint(
            "(status = 'SUCCEEDED') = (outcome IS NOT NULL)", name="ck_agent_runs_outcome_terminal"
        ),
        CheckConstraint(
            "(status IN ('SUCCEEDED','FAILED','CANCELLED')) = (finished_at IS NOT NULL)",
            name="ck_agent_runs_finished",
        ),
        CheckConstraint("status != 'FAILED' OR error_code IS NOT NULL", name="ck_agent_runs_failure"),
        CheckConstraint(
            "status != 'RUNNING' OR (lease_token IS NOT NULL AND lease_expires_at IS NOT "
            "NULL AND deadline_at IS NOT NULL)",
            name="ck_agent_runs_lease",
        ),
        CheckConstraint(
            "(trigger_kind = 'MESSAGE' AND trigger_message_id IS NOT NULL) OR "
            "(trigger_kind != 'MESSAGE' AND trigger_command_id IS NOT NULL)",
            name="ck_agent_runs_input",
        ),
        CheckConstraint(
            "input_event_seq > 0 AND model_call_count >= 0 AND tool_call_count >= 0",
            name="ck_agent_runs_counts",
        ),
        Index(
            "uq_agent_runs_open_session",
            "session_id",
            unique=True,
            postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        Index("ix_agent_runs_queue", "status", "queued_at", "id"),
        Index("ix_agent_runs_lease", "status", "lease_expires_at"),
        Index(
            "uq_agent_runs_trigger_command",
            "trigger_command_id",
            unique=True,
            postgresql_where=text("trigger_command_id IS NOT NULL"),
        ),
        session_reference("agent_runs", "trigger_message_id", "chat_messages"),
        session_reference("agent_runs", "trigger_command_id", "agent_commands"),
        session_reference("agent_runs", "work_item_id", "order_intake_items"),
        session_reference("agent_runs", "retry_of_run_id", "agent_runs"),
        session_reference("agent_runs", "output_message_id", "chat_messages"),
        session_reference("agent_runs", "generated_plan_id", "schedule_plans"),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    trigger_kind: Mapped[str]
    trigger_message_id: Mapped[str | None] = mapped_column(index=True)
    trigger_command_id: Mapped[str | None]
    work_item_id: Mapped[str | None]
    retry_of_run_id: Mapped[str | None] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(default="QUEUED", server_default="QUEUED")
    outcome: Mapped[str | None]
    input_event_seq: Mapped[int] = mapped_column(BigInteger)
    graph_key: Mapped[str] = mapped_column(String(64))
    graph_version: Mapped[str] = mapped_column(String(128))
    config_snapshot: Mapped[dict] = mapped_column(JSONB)
    context_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    output_message_id: Mapped[str | None]
    generated_plan_id: Mapped[str | None]
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    lease_token: Mapped[str | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_call_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    prompt_tokens: Mapped[int | None] = mapped_column(BigInteger)
    completion_tokens: Mapped[int | None] = mapped_column(BigInteger)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentCommand(Base):
    __tablename__ = "agent_commands"
    __table_args__ = (
        UniqueConstraint("id", "session_id", name="uq_agent_commands_id_session"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_agent_commands_user_key"),
        enum_check("kind", COMMAND_KINDS, "ck_agent_commands_kind"),
        CheckConstraint("http_status IN (200,201,202,204)", name="ck_agent_commands_response"),
        CheckConstraint(
            "octet_length(payload::text) <= 16384 AND octet_length(result::text) <= 131072",
            name="ck_agent_commands_size",
        ),
        session_reference("agent_commands", "result_run_id", "agent_runs"),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str]
    request_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    target_id: Mapped[str | None]
    expected_revision: Mapped[int | None] = mapped_column(BigInteger)
    result_run_id: Mapped[str | None]
    http_status: Mapped[int]
    result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionEvent(Base):
    __tablename__ = "session_events"
    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_session_events_seq"),
        enum_check("kind", EVENT_KINDS, "ck_session_events_kind"),
        enum_check("actor_kind", ("USER", "AGENT", "SYSTEM"), "ck_session_events_actor"),
        CheckConstraint("seq > 0 AND schema_version = 1", name="ck_session_events_version"),
        CheckConstraint("actor_kind != 'USER' OR actor_user_id IS NOT NULL", name="ck_session_events_user"),
        CheckConstraint("octet_length(payload::text) <= 131072", name="ck_session_events_size"),
        Index("ix_session_events_run_seq", "run_id", "seq"),
        Index("ix_session_events_kind_seq", "session_id", "kind", "seq"),
        *(
            session_reference("session_events", col, target)
            for col, target in (
                ("run_id", "agent_runs"),
                ("message_id", "chat_messages"),
                ("command_id", "agent_commands"),
                ("work_item_id", "order_intake_items"),
                ("tool_call_id", "agent_tool_calls"),
            )
        ),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(default=1, server_default="1")
    actor_kind: Mapped[str]
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    run_id: Mapped[str | None]
    message_id: Mapped[str | None] = mapped_column(index=True)
    command_id: Mapped[str | None]
    work_item_id: Mapped[str | None]
    tool_call_id: Mapped[str | None]
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderIntakeItem(Base):
    __tablename__ = "order_intake_items"
    __table_args__ = (
        UniqueConstraint("id", "session_id", name="uq_order_intake_items_id_session"),
        UniqueConstraint(
            "session_id", "queue_position", "source_order_index", name="uq_order_intake_items_position"
        ),
        UniqueConstraint(
            "source_attachment_id", "source_order_index", name="uq_order_intake_items_source_order"
        ),
        CheckConstraint("source_order_index BETWEEN 1 AND 20", name="ck_order_intake_items_source_order"),
        enum_check(
            "status", ("PENDING", "ACTIVE", "DEFERRED", "CREATED", "CLOSED"), "ck_order_intake_items_status"
        ),
        enum_check(
            "recognition_status", ("NOT_STARTED", "SUCCEEDED", "FAILED"), "ck_order_intake_items_recognition"
        ),
        CheckConstraint("order_id IS NULL OR status = 'CREATED'", name="ck_order_intake_items_order"),
        CheckConstraint("revision > 0 AND queue_position > 0", name="ck_order_intake_items_revision"),
        CheckConstraint(
            "octet_length(draft::text) <= 65536 AND octet_length(extraction::text) <= 65536",
            name="ck_order_intake_items_size",
        ),
        Index(
            "uq_order_intake_items_active",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_order_intake_items_queue", "session_id", "status", "queue_position"),
        session_reference("order_intake_items", "source_message_id", "chat_messages"),
        session_reference("order_intake_items", "source_attachment_id", "chat_attachments"),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    source_message_id: Mapped[str]
    source_attachment_id: Mapped[str]
    source_order_index: Mapped[int] = mapped_column(default=1, server_default="1")
    queue_position: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(default="PENDING", server_default="PENDING")
    revision: Mapped[int] = mapped_column(BigInteger, default=1, server_default="1")
    recognition_status: Mapped[str] = mapped_column(default="NOT_STARTED", server_default="NOT_STARTED")
    extraction: Mapped[dict | None] = mapped_column(JSONB)
    draft: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    issues: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), unique=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deferred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        UniqueConstraint("id", "session_id", name="uq_agent_tool_calls_id_session"),
        UniqueConstraint("run_id", "call_key", name="uq_agent_tool_calls_key"),
        enum_check("status", ("STARTED", "SUCCEEDED", "FAILED", "ABANDONED"), "ck_agent_tool_calls_status"),
        CheckConstraint(
            "octet_length(args::text) <= 65536 AND octet_length(result::text) <= 262144",
            name="ck_agent_tool_calls_size",
        ),
        session_reference("agent_tool_calls", "run_id", "agent_runs"),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(index=True)
    call_key: Mapped[str] = mapped_column(String(128))
    tool_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(default="STARTED", server_default="STARTED")
    args_hash: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentFileGcJob(Base):
    __tablename__ = "agent_file_gc_jobs"
    __table_args__ = (
        enum_check("status", ("PENDING", "RUNNING", "SUCCEEDED", "FAILED"), "ck_agent_file_gc_jobs_status"),
        CheckConstraint("attempts >= 0", name="ck_agent_file_gc_jobs_attempts"),
        Index("ix_agent_file_gc_jobs_queue", "status", "next_attempt_at"),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=generate_id)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), index=True
    )
    attachment_id: Mapped[str | None]
    storage_key: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(default="PENDING", server_default="PENDING")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
