"""Persist versioned assistant presentation snapshots."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c9d8e7f60123"
down_revision = "b7e2c4a91d30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("presentation", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "presentation")
