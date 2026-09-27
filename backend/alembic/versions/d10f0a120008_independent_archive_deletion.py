"""Keep screenshot and formal order deletion independent."""

from alembic import op

revision = "d10f0a120008"
down_revision = "d10f0a120007"
branch_labels = None
depends_on = None

KINDS = (
    "RECOGNIZE_ITEM",
    "ARCHIVE_SCREENSHOT",
    "RESTORE_SCREENSHOT",
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


def constraints(*, independent):
    op.drop_constraint("ck_agent_commands_kind", "agent_commands", type_="check")
    kinds = (*KINDS, "DELETE_SCREENSHOT") if independent else KINDS
    op.create_check_constraint(
        "ck_agent_commands_kind", "agent_commands", "kind IN (" + ",".join(repr(v) for v in kinds) + ")"
    )
    op.drop_constraint("ck_order_intake_items_order", "order_intake_items", type_="check")
    op.create_check_constraint(
        "ck_order_intake_items_order",
        "order_intake_items",
        "order_id IS NULL OR status = 'CREATED'"
        if independent
        else "(status = 'CREATED') = (order_id IS NOT NULL)",
    )
    op.drop_constraint("order_intake_items_order_id_fkey", "order_intake_items", type_="foreignkey")
    op.create_foreign_key(
        "order_intake_items_order_id_fkey",
        "order_intake_items",
        "orders",
        ["order_id"],
        ["id"],
        ondelete="SET NULL" if independent else "RESTRICT",
    )


def upgrade():
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    constraints(independent=True)


def downgrade():
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM order_intake_items WHERE status = 'CREATED' "
        "AND order_id IS NULL) OR EXISTS (SELECT 1 FROM agent_commands WHERE kind = 'DELETE_SCREENSHOT') "
        "THEN RAISE EXCEPTION 'Independent deletion history requires a backup restore'; END IF; END $$"
    )
    constraints(independent=False)
