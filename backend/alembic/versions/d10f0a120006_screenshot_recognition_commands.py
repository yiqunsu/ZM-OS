"""Allow durable image recognition commands for the order workbench."""

from alembic import op

revision = "d10f0a120006"
down_revision = "d10f0a120005"
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
    replace(KINDS)


def downgrade():
    # Existing recognition commands must be retained; fail rather than delete audit history.
    replace(tuple(v for v in KINDS if v != "RECOGNIZE_ITEM"))
