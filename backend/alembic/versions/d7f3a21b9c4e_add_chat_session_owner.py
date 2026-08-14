"""add chat session owner

Revision ID: d7f3a21b9c4e
Revises: c354112c761f
Create Date: 2026-07-29

Existing sessions cannot be attributed safely, so they remain NULL and are
hidden by the application. Every newly-created session is owned by a user.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7f3a21b9c4e"
down_revision: str | Sequence[str] | None = "c354112c761f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("user_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_chat_sessions_user_id_users",
        "chat_sessions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_constraint("fk_chat_sessions_user_id_users", "chat_sessions", type_="foreignkey")
    op.drop_column("chat_sessions", "user_id")
