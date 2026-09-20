"""Version specialized scheduling drafts

Revision ID: d10f0a120003
Revises: d10f0a120002
Create Date: 2026-09-11 10:51:49.782216

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd10f0a120003'
down_revision: Union[str, Sequence[str], None] = 'd10f0a120002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('schedule_plans', sa.Column('created_by_run_id', sa.String(), nullable=True))
    op.add_column('schedule_plans', sa.Column('revision', sa.BigInteger(), server_default='1', nullable=False))
    op.add_column('schedule_plans', sa.Column('applied_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('schedule_plans', sa.Column('superseded_by_id', sa.String(), nullable=True))
    op.add_column('schedule_plans', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('schedule_plans', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('schedule_plans', 'status',
               existing_type=postgresql.ENUM('DRAFT', 'APPLIED', name='schedule_plan_status'),
               type_=sa.Enum('DRAFT', 'APPLIED', 'SUPERSEDED', 'CLOSED', name='schedule_plan_status', native_enum=False, create_constraint=True, length=32),
               postgresql_using='status::text',
               existing_nullable=False)
    op.create_unique_constraint('uq_schedule_plans_id_session', 'schedule_plans', ['id', 'session_id'])
    op.create_index('uq_schedule_plans_v2_draft', 'schedule_plans', ['session_id'], unique=True, postgresql_where=sa.text("status = 'DRAFT' AND created_by_run_id IS NOT NULL"))
    op.create_unique_constraint(None, 'schedule_plans', ['created_by_run_id'])


    op.create_check_constraint("ck_schedule_plans_revision", "schedule_plans", "revision > 0")
    op.create_foreign_key('fk_agent_runs_generated_plan_id_session', 'agent_runs', 'schedule_plans', ['generated_plan_id', 'session_id'], ['id', 'session_id'], initially='DEFERRED', deferrable=True)
    op.create_foreign_key('fk_chat_sessions_active_plan', 'chat_sessions', 'schedule_plans', ['active_plan_id', 'id'], ['id', 'session_id'], initially='DEFERRED', deferrable=True)
    op.create_foreign_key('fk_schedule_plans_created_run', 'schedule_plans', 'agent_runs', ['created_by_run_id', 'session_id'], ['id', 'session_id'], initially='DEFERRED', deferrable=True)
    op.create_foreign_key('fk_schedule_plans_superseded', 'schedule_plans', 'schedule_plans', ['superseded_by_id', 'session_id'], ['id', 'session_id'], initially='DEFERRED', deferrable=True)
    op.execute("DROP TYPE schedule_plan_status")


def downgrade() -> None:
    raise RuntimeError("Keep versioned scheduling proposals; roll back the application without deleting durable state.")
