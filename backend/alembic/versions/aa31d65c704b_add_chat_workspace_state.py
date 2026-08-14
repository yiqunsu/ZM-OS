"""add chat workspace state

Revision ID: aa31d65c704b
Revises: f4a7c2d91e60
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "aa31d65c704b"
down_revision: str | Sequence[str] | None = "f4a7c2d91e60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("workspace_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "workspace_state")
