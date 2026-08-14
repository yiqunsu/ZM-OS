"""add Casdoor identity mapping

Revision ID: e8c1b90d54a2
Revises: d7f3a21b9c4e
Create Date: 2026-07-29

Existing users remain unlinked until their first verified Casdoor login. Their
local IDs stay unchanged so all business and chat ownership references remain
stable.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8c1b90d54a2"
down_revision: str | Sequence[str] | None = "d7f3a21b9c4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("external_subject", sa.String(length=255), nullable=True))
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=True)
    op.create_index(
        "ix_users_external_subject",
        "users",
        ["external_subject"],
        unique=True,
    )


def downgrade() -> None:
    connection = op.get_bind()
    missing_password_count = connection.execute(
        sa.text("SELECT count(*) FROM users WHERE password_hash IS NULL")
    ).scalar_one()
    if missing_password_count:
        raise RuntimeError(
            "Cannot downgrade Casdoor identity migration while passwordless users exist"
        )

    op.drop_index("ix_users_external_subject", table_name="users")
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=False)
    op.drop_column("users", "external_subject")
