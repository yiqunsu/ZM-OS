"""add schedule plans

Revision ID: f4a7c2d91e60
Revises: e8c1b90d54a2
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f4a7c2d91e60"
down_revision: str | Sequence[str] | None = "e8c1b90d54a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.schema.CreateSequence(sa.Sequence("order_no_seq")))
    connection = op.get_bind()
    max_suffix = connection.execute(
        sa.text(
            "SELECT max(substring(order_no from '([0-9]+)$')::bigint) "
            "FROM orders WHERE order_no ~ '[0-9]+$'"
        )
    ).scalar_one_or_none()
    connection.execute(
        sa.text("SELECT setval('order_no_seq', :value, :is_called)"),
        {"value": max_suffix or 1, "is_called": max_suffix is not None},
    )
    op.add_column("chat_sessions", sa.Column("active_workspace", sa.String(length=32)))
    status_enum = sa.Enum("DRAFT", "APPLIED", name="schedule_plan_status")
    op.create_table(
        "schedule_plans",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("created_by_id", sa.String(), nullable=False),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("input_order_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_fingerprint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tasks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unassigned", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedule_plans_created_by_id", "schedule_plans", ["created_by_id"])
    op.create_index("ix_schedule_plans_session_id", "schedule_plans", ["session_id"])
    op.create_index("ix_schedule_plans_status", "schedule_plans", ["status"])


def downgrade() -> None:
    op.drop_index("ix_schedule_plans_status", table_name="schedule_plans")
    op.drop_index("ix_schedule_plans_session_id", table_name="schedule_plans")
    op.drop_index("ix_schedule_plans_created_by_id", table_name="schedule_plans")
    op.drop_table("schedule_plans")
    sa.Enum(name="schedule_plan_status").drop(op.get_bind(), checkfirst=True)
    op.drop_column("chat_sessions", "active_workspace")
    op.execute(sa.schema.DropSequence(sa.Sequence("order_no_seq")))
