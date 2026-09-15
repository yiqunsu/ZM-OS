"""Add durable agent terminal audit summaries

Revision ID: d10f0a120002
Revises: d10f0a120001
Create Date: 2026-09-11 03:10:46.009453

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd10f0a120002'
down_revision: Union[str, Sequence[str], None] = 'd10f0a120001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agent_audit_logs', sa.Column('kind', sa.String(), nullable=True))
    op.add_column('agent_audit_logs', sa.Column('user_id', sa.String(), nullable=True))
    op.add_column('agent_audit_logs', sa.Column('run_id', sa.String(), nullable=True))
    op.add_column('agent_audit_logs', sa.Column('command_id', sa.String(), nullable=True))
    op.add_column('agent_audit_logs', sa.Column('object_type', sa.String(), nullable=True))
    op.add_column('agent_audit_logs', sa.Column('object_id', sa.String(), nullable=True))
    op.add_column('agent_audit_logs', sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.alter_column('agent_audit_logs', 'prompt_tokens',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('agent_audit_logs', 'completion_tokens',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('agent_audit_logs', 'total_tokens',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.create_index('uq_agent_audit_logs_command_kind', 'agent_audit_logs', ['command_id', 'kind'], unique=True, postgresql_where=sa.text('command_id IS NOT NULL'))
    op.create_index('uq_agent_audit_logs_run_kind', 'agent_audit_logs', ['run_id', 'kind'], unique=True, postgresql_where=sa.text('run_id IS NOT NULL'))
    op.create_foreign_key(None, 'agent_audit_logs', 'agent_runs', ['run_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(None, 'agent_audit_logs', 'agent_commands', ['command_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(None, 'agent_audit_logs', 'users', ['user_id'], ['id'], ondelete='RESTRICT')
    op.create_check_constraint("ck_agent_audit_logs_kind", "agent_audit_logs",
        "kind IS NULL OR kind IN ('RUN_FINISHED','ORDER_CREATED','SCHEDULE_APPLIED')")


def downgrade() -> None:
    raise RuntimeError("Keep terminal audit records; roll back the application, not durable audit data.")
