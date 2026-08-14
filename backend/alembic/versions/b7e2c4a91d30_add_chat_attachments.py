"""add chat attachments

Revision ID: b7e2c4a91d30
Revises: aa31d65c704b
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e2c4a91d30"
down_revision: str | Sequence[str] | None = "aa31d65c704b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(length=32), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "byte_size > 0",
            name="ck_chat_attachments_byte_size_positive",
        ),
        sa.CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png')",
            name="ck_chat_attachments_mime_type_supported",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat_messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        op.f("ix_chat_attachments_message_id"),
        "chat_attachments",
        ["message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_attachments_message_id"), table_name="chat_attachments")
    op.drop_table("chat_attachments")
