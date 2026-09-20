"""Support independently confirmed order drafts grouped by source screenshot.

Revision ID: d10f0a120005
Revises: d10f0a120004
"""

from alembic import op
import sqlalchemy as sa

revision = "d10f0a120005"
down_revision = "d10f0a120004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "order_intake_items",
        sa.Column("source_order_index", sa.Integer(), server_default="1", nullable=False),
    )
    op.drop_constraint("order_intake_items_source_attachment_id_key", "order_intake_items", type_="unique")
    op.drop_constraint("uq_order_intake_items_position", "order_intake_items", type_="unique")
    op.create_unique_constraint(
        "uq_order_intake_items_position",
        "order_intake_items",
        ["session_id", "queue_position", "source_order_index"],
    )
    op.create_unique_constraint(
        "uq_order_intake_items_source_order",
        "order_intake_items",
        ["source_attachment_id", "source_order_index"],
    )
    op.create_check_constraint(
        "ck_order_intake_items_source_order", "order_intake_items", "source_order_index BETWEEN 1 AND 20"
    )


def downgrade():
    # Fail instead of silently dropping siblings if multi-order data exists.
    op.create_unique_constraint(
        "order_intake_items_source_attachment_id_key", "order_intake_items", ["source_attachment_id"]
    )
    op.drop_constraint("uq_order_intake_items_source_order", "order_intake_items", type_="unique")
    op.drop_constraint("uq_order_intake_items_position", "order_intake_items", type_="unique")
    op.create_unique_constraint(
        "uq_order_intake_items_position", "order_intake_items", ["session_id", "queue_position"]
    )
    op.drop_constraint("ck_order_intake_items_source_order", "order_intake_items", type_="check")
    op.drop_column("order_intake_items", "source_order_index")
