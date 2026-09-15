"""Archive intake screenshots independently of their runtime sessions."""

import sqlalchemy as sa

from alembic import op

revision = "d10f0a120007"
down_revision = "d10f0a120006"
branch_labels = None
depends_on = None

KINDS = (
    "RECOGNIZE_ITEM",
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


def replace(values):
    op.drop_constraint("ck_agent_commands_kind", "agent_commands", type_="check")
    op.create_check_constraint(
        "ck_agent_commands_kind", "agent_commands", "kind IN (" + ",".join(repr(v) for v in values) + ")"
    )


def upgrade():
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.add_column(
        "chat_attachments", sa.Column("intake_archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "chat_attachments", sa.Column("intake_revision", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_check_constraint(
        "ck_chat_attachments_intake_revision", "chat_attachments", "intake_revision >= 0"
    )
    replace((*KINDS, "ARCHIVE_SCREENSHOT", "RESTORE_SCREENSHOT"))


def downgrade():
    # Refuse to discard archive state or recorded commands. Restore a backup for an older release.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM chat_attachments WHERE intake_revision > 0 "
        "OR intake_archived_at IS NOT NULL) THEN RAISE EXCEPTION "
        "'Screenshot archive history requires a backup restore'; END IF; END $$"
    )
    replace(KINDS)
    op.drop_constraint("ck_chat_attachments_intake_revision", "chat_attachments", type_="check")
    op.drop_column("chat_attachments", "intake_revision")
    op.drop_column("chat_attachments", "intake_archived_at")
