"""Expand durable agent session and run foundation

Revision ID: d10f0a120001
Revises: c9d8e7f60123
Create Date: 2026-09-11 01:31:57.065512

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd10f0a120001'
down_revision: Union[str, Sequence[str], None] = 'c9d8e7f60123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('agent_commands',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('target_id', sa.String(), nullable=True),
    sa.Column('expected_revision', sa.BigInteger(), nullable=True),
    sa.Column('result_run_id', sa.String(), nullable=True),
    sa.Column('http_status', sa.Integer(), nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('CREATE_SESSION','NEXT_ITEM','SELECT_ITEM','DEFER_ITEM','CLOSE_ITEM','CONFIRM_ORDER','APPLY_PLAN','REPLACE_PLAN','CLOSE_PLAN','RETRY_RUN','ARCHIVE_SESSION','RESTORE_SESSION','DELETE_SESSION')", name='ck_agent_commands_kind'),
    sa.CheckConstraint('http_status IN (200,201,202,204)', name='ck_agent_commands_response'),
    sa.CheckConstraint('octet_length(payload::text) <= 16384 AND octet_length(result::text) <= 131072', name='ck_agent_commands_size'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'session_id', name='uq_agent_commands_id_session'),
    sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_agent_commands_user_key')
    )
    op.create_index(op.f('ix_agent_commands_session_id'), 'agent_commands', ['session_id'], unique=False)
    op.create_table('agent_file_gc_jobs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=True),
    sa.Column('attachment_id', sa.String(), nullable=True),
    sa.Column('storage_key', sa.String(), nullable=False),
    sa.Column('status', sa.String(), server_default='PENDING', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error_code', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('PENDING','RUNNING','SUCCEEDED','FAILED')", name='ck_agent_file_gc_jobs_status'),
    sa.CheckConstraint('attempts >= 0', name='ck_agent_file_gc_jobs_attempts'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('storage_key')
    )
    op.create_index('ix_agent_file_gc_jobs_queue', 'agent_file_gc_jobs', ['status', 'next_attempt_at'], unique=False)
    op.create_index(op.f('ix_agent_file_gc_jobs_session_id'), 'agent_file_gc_jobs', ['session_id'], unique=False)
    op.create_table('agent_runs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('trigger_kind', sa.String(), nullable=False),
    sa.Column('trigger_message_id', sa.String(), nullable=True),
    sa.Column('trigger_command_id', sa.String(), nullable=True),
    sa.Column('work_item_id', sa.String(), nullable=True),
    sa.Column('retry_of_run_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(), server_default='QUEUED', nullable=False),
    sa.Column('outcome', sa.String(), nullable=True),
    sa.Column('input_event_seq', sa.BigInteger(), nullable=False),
    sa.Column('graph_key', sa.String(length=64), nullable=False),
    sa.Column('graph_version', sa.String(length=128), nullable=False),
    sa.Column('config_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('context_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('output_message_id', sa.String(), nullable=True),
    sa.Column('generated_plan_id', sa.String(), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('worker_id', sa.String(length=128), nullable=True),
    sa.Column('lease_token', sa.String(), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('model_call_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('tool_call_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('prompt_tokens', sa.BigInteger(), nullable=True),
    sa.Column('completion_tokens', sa.BigInteger(), nullable=True),
    sa.Column('total_tokens', sa.BigInteger(), nullable=True),
    sa.Column('queued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'SUCCEEDED') = (outcome IS NOT NULL)", name='ck_agent_runs_outcome_terminal'),
    sa.CheckConstraint("(status IN ('SUCCEEDED','FAILED','CANCELLED')) = (finished_at IS NOT NULL)", name='ck_agent_runs_finished'),
    sa.CheckConstraint("(trigger_kind = 'MESSAGE' AND trigger_message_id IS NOT NULL) OR (trigger_kind != 'MESSAGE' AND trigger_command_id IS NOT NULL)", name='ck_agent_runs_input'),
    sa.CheckConstraint("outcome IN ('ANSWERED','NEEDS_INPUT','OUT_OF_SCOPE','QUEUED_ONLY','DRAFT_READY','NO_PENDING','NO_FEASIBLE','LIMIT_REACHED')", name='ck_agent_runs_outcome'),
    sa.CheckConstraint("status != 'FAILED' OR error_code IS NOT NULL", name='ck_agent_runs_failure'),
    sa.CheckConstraint("status != 'RUNNING' OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND deadline_at IS NOT NULL)", name='ck_agent_runs_lease'),
    sa.CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')", name='ck_agent_runs_status'),
    sa.CheckConstraint("trigger_kind IN ('MESSAGE','NEXT_ITEM','RESUME_ITEM','RETRY','REPLACE_PLAN')", name='ck_agent_runs_trigger'),
    sa.CheckConstraint('input_event_seq > 0 AND model_call_count >= 0 AND tool_call_count >= 0', name='ck_agent_runs_counts'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'session_id', name='uq_agent_runs_id_session')
    )
    op.create_index('ix_agent_runs_lease', 'agent_runs', ['status', 'lease_expires_at'], unique=False)
    op.create_index('ix_agent_runs_queue', 'agent_runs', ['status', 'queued_at', 'id'], unique=False)
    op.create_index(op.f('ix_agent_runs_retry_of_run_id'), 'agent_runs', ['retry_of_run_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_trigger_message_id'), 'agent_runs', ['trigger_message_id'], unique=False)
    op.create_index('uq_agent_runs_open_session', 'agent_runs', ['session_id'], unique=True, postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"))
    op.create_index('uq_agent_runs_trigger_command', 'agent_runs', ['trigger_command_id'], unique=True, postgresql_where=sa.text('trigger_command_id IS NOT NULL'))
    op.create_table('agent_tool_calls',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('run_id', sa.String(), nullable=False),
    sa.Column('call_key', sa.String(length=128), nullable=False),
    sa.Column('tool_name', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(), server_default='STARTED', nullable=False),
    sa.Column('args_hash', sa.String(length=64), nullable=False),
    sa.Column('args', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('STARTED','SUCCEEDED','FAILED','ABANDONED')", name='ck_agent_tool_calls_status'),
    sa.CheckConstraint('octet_length(args::text) <= 65536 AND octet_length(result::text) <= 262144', name='ck_agent_tool_calls_size'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'session_id', name='uq_agent_tool_calls_id_session'),
    sa.UniqueConstraint('run_id', 'call_key', name='uq_agent_tool_calls_key')
    )
    op.create_index(op.f('ix_agent_tool_calls_run_id'), 'agent_tool_calls', ['run_id'], unique=False)
    op.create_index(op.f('ix_agent_tool_calls_session_id'), 'agent_tool_calls', ['session_id'], unique=False)
    op.create_table('session_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('seq', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.String(length=64), nullable=False),
    sa.Column('schema_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('actor_kind', sa.String(), nullable=False),
    sa.Column('actor_user_id', sa.String(), nullable=True),
    sa.Column('run_id', sa.String(), nullable=True),
    sa.Column('message_id', sa.String(), nullable=True),
    sa.Column('command_id', sa.String(), nullable=True),
    sa.Column('work_item_id', sa.String(), nullable=True),
    sa.Column('tool_call_id', sa.String(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("actor_kind != 'USER' OR actor_user_id IS NOT NULL", name='ck_session_events_user'),
    sa.CheckConstraint("actor_kind IN ('USER','AGENT','SYSTEM')", name='ck_session_events_actor'),
    sa.CheckConstraint("kind IN ('session.created','session.archived','session.restored','session.deleting','session.state_changed','message.accepted','message.completed','command.accepted','run.queued','run.started','run.progress','run.succeeded','run.failed','run.cancelled','admittance.decided','work_item.queued','work_item.activated','work_item.deferred','work_item.closed','work_item.created','recognition.completed','recognition.failed','draft.updated','plan.generated','plan.updated','plan.superseded','plan.closed','plan.applied','tool.started','tool.succeeded','tool.failed','tool.abandoned','assistant.delta')", name='ck_session_events_kind'),
    sa.CheckConstraint('octet_length(payload::text) <= 131072', name='ck_session_events_size'),
    sa.CheckConstraint('seq > 0 AND schema_version = 1', name='ck_session_events_version'),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'seq', name='uq_session_events_seq')
    )
    op.create_index('ix_session_events_kind_seq', 'session_events', ['session_id', 'kind', 'seq'], unique=False)
    op.create_index(op.f('ix_session_events_message_id'), 'session_events', ['message_id'], unique=False)
    op.create_index('ix_session_events_run_seq', 'session_events', ['run_id', 'seq'], unique=False)
    op.create_table('order_intake_items',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('source_message_id', sa.String(), nullable=False),
    sa.Column('source_attachment_id', sa.String(), nullable=False),
    sa.Column('queue_position', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(), server_default='PENDING', nullable=False),
    sa.Column('revision', sa.BigInteger(), server_default='1', nullable=False),
    sa.Column('recognition_status', sa.String(), server_default='NOT_STARTED', nullable=False),
    sa.Column('extraction', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('draft', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('issues', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('order_id', sa.String(), nullable=True),
    sa.Column('last_error_code', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deferred_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'CREATED') = (order_id IS NOT NULL)", name='ck_order_intake_items_order'),
    sa.CheckConstraint("recognition_status IN ('NOT_STARTED','SUCCEEDED','FAILED')", name='ck_order_intake_items_recognition'),
    sa.CheckConstraint("status IN ('PENDING','ACTIVE','DEFERRED','CREATED','CLOSED')", name='ck_order_intake_items_status'),
    sa.CheckConstraint('octet_length(draft::text) <= 65536 AND octet_length(extraction::text) <= 65536', name='ck_order_intake_items_size'),
    sa.CheckConstraint('revision > 0 AND queue_position > 0', name='ck_order_intake_items_revision'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'session_id', name='uq_order_intake_items_id_session'),
    sa.UniqueConstraint('order_id'),
    sa.UniqueConstraint('session_id', 'queue_position', name='uq_order_intake_items_position'),
    sa.UniqueConstraint('source_attachment_id')
    )
    op.create_index('ix_order_intake_items_queue', 'order_intake_items', ['session_id', 'status', 'queue_position'], unique=False)
    op.create_index('uq_order_intake_items_active', 'order_intake_items', ['session_id'], unique=True, postgresql_where=sa.text("status = 'ACTIVE'"))
    op.add_column('chat_attachments', sa.Column('session_id', sa.String(), nullable=True))
    op.add_column('chat_attachments', sa.Column('client_upload_id', sa.String(), nullable=True))
    op.add_column('chat_attachments', sa.Column('position', sa.Integer(), server_default='0', nullable=True))
    op.add_column('chat_attachments', sa.Column('status', sa.String(), server_default='BOUND', nullable=False))
    op.add_column('chat_attachments', sa.Column('width_px', sa.Integer(), nullable=True))
    op.add_column('chat_attachments', sa.Column('height_px', sa.Integer(), nullable=True))
    op.add_column('chat_attachments', sa.Column('sha256', sa.String(length=64), nullable=True))
    op.add_column('chat_attachments', sa.Column('available', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('chat_attachments', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('chat_attachments', 'message_id',
               existing_type=sa.VARCHAR(),
               nullable=True)
    op.drop_index(op.f('ix_chat_attachments_message_id'), table_name='chat_attachments')
    op.create_index(op.f('ix_chat_attachments_message_id'), 'chat_attachments', ['message_id'], unique=False)
    op.create_index('ix_chat_attachments_expiry', 'chat_attachments', ['status', 'expires_at'], unique=False)
    op.create_index(op.f('ix_chat_attachments_session_id'), 'chat_attachments', ['session_id'], unique=False)
    op.create_unique_constraint('uq_chat_attachments_id_session', 'chat_attachments', ['id', 'session_id'])
    op.create_unique_constraint('uq_chat_attachments_position', 'chat_attachments', ['message_id', 'position'])
    op.create_unique_constraint('uq_chat_attachments_upload', 'chat_attachments', ['session_id', 'client_upload_id'])
    op.add_column('chat_messages', sa.Column('client_message_id', sa.String(), nullable=True))
    op.add_column('chat_messages', sa.Column('request_hash', sa.String(length=64), nullable=True))
    op.add_column('chat_messages', sa.Column('origin', sa.String(), server_default='MIGRATION', nullable=False))
    op.add_column('chat_messages', sa.Column('content_schema_version', sa.Integer(), server_default='1', nullable=False))
    op.add_column('chat_messages', sa.Column('run_id', sa.String(), nullable=True))
    op.add_column('chat_messages', sa.Column('command_id', sa.String(), nullable=True))
    op.add_column('chat_messages', sa.Column('work_item_id', sa.String(), nullable=True))
    op.add_column('chat_messages', sa.Column('event_seq', sa.BigInteger(), nullable=True))
    op.create_index('ix_chat_messages_session_seq', 'chat_messages', ['session_id', 'event_seq', 'id'], unique=False)
    op.create_index(op.f('ix_chat_messages_work_item_id'), 'chat_messages', ['work_item_id'], unique=False)
    op.create_unique_constraint('uq_chat_messages_client_id', 'chat_messages', ['session_id', 'client_message_id'])
    op.create_index('uq_chat_messages_command_final', 'chat_messages', ['command_id'], unique=True, postgresql_where=sa.text("origin = 'BUSINESS'"))
    op.create_unique_constraint('uq_chat_messages_id_session', 'chat_messages', ['id', 'session_id'])
    op.create_index('uq_chat_messages_run_final', 'chat_messages', ['run_id'], unique=True, postgresql_where=sa.text("origin = 'AGENT'"))
    op.drop_constraint(op.f('chat_messages_session_id_fkey'), 'chat_messages', type_='foreignkey')
    op.add_column('chat_sessions', sa.Column('agent_type', sa.String(), server_default='LEGACY', nullable=False))
    op.add_column('chat_sessions', sa.Column('status', sa.String(), server_default='ACTIVE', nullable=False))
    op.add_column('chat_sessions', sa.Column('state_schema_version', sa.Integer(), server_default='1', nullable=False))
    op.add_column('chat_sessions', sa.Column('state_revision', sa.BigInteger(), server_default='1', nullable=False))
    op.add_column('chat_sessions', sa.Column('state', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.add_column('chat_sessions', sa.Column('active_work_item_id', sa.String(), nullable=True))
    op.add_column('chat_sessions', sa.Column('active_plan_id', sa.String(), nullable=True))
    op.add_column('chat_sessions', sa.Column('last_event_seq', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('chat_sessions', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('chat_sessions', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('chat_sessions', sa.Column('deletion_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_chat_sessions_owner_status', 'chat_sessions', ['user_id', 'status', 'updated_at', 'id'], unique=False)


    op.create_check_constraint('ck_chat_sessions_agent_type', 'chat_sessions', "agent_type IN ('ORDER_INTAKE','SCHEDULING','LEGACY')")
    op.create_check_constraint('ck_chat_sessions_item_type', 'chat_sessions', "active_work_item_id IS NULL OR agent_type = 'ORDER_INTAKE'")
    op.create_check_constraint('ck_chat_sessions_owner', 'chat_sessions', "agent_type = 'LEGACY' OR user_id IS NOT NULL")
    op.create_check_constraint('ck_chat_sessions_plan_type', 'chat_sessions', "active_plan_id IS NULL OR agent_type = 'SCHEDULING'")
    op.create_check_constraint('ck_chat_sessions_revision', 'chat_sessions', 'state_revision > 0 AND last_event_seq >= 0')
    op.create_check_constraint('ck_chat_sessions_state_size', 'chat_sessions', 'octet_length(state::text) <= 16384')
    op.create_check_constraint('ck_chat_sessions_status', 'chat_sessions', "status IN ('ACTIVE','ARCHIVED','DELETING')")
    op.create_check_constraint('ck_chat_messages_agent', 'chat_messages', "origin != 'AGENT' OR (run_id IS NOT NULL AND role = 'assistant')")
    op.create_check_constraint('ck_chat_messages_origin', 'chat_messages', "origin IN ('USER','AGENT','BUSINESS','MIGRATION')")
    op.create_check_constraint('ck_chat_messages_user', 'chat_messages', "origin != 'USER' OR (client_message_id IS NOT NULL AND request_hash IS NOT NULL AND role = 'user')")
    op.create_check_constraint('ck_chat_messages_v2', 'chat_messages', "origin = 'MIGRATION' OR (session_id IS NOT NULL AND event_seq > 0 AND content IS NOT NULL AND role IN ('user','assistant','system'))")
    op.create_check_constraint('ck_chat_attachments_bound', 'chat_attachments', "status != 'BOUND' OR message_id IS NOT NULL")
    op.create_check_constraint('ck_chat_attachments_pixels', 'chat_attachments', '(width_px IS NULL AND height_px IS NULL) OR (width_px > 0 AND height_px > 0 AND width_px::bigint * height_px <= 20000000)')
    op.create_check_constraint('ck_chat_attachments_position', 'chat_attachments', 'position IS NULL OR position BETWEEN 0 AND 4')
    op.create_check_constraint('ck_chat_attachments_staged', 'chat_attachments', "status != 'STAGED' OR (message_id IS NULL AND expires_at IS NOT NULL AND session_id IS NOT NULL)")
    op.create_check_constraint('ck_chat_attachments_status', 'chat_attachments', "status IN ('STAGED','BOUND')")
    op.create_foreign_key('fk_agent_commands_result_run_id_session', 'agent_commands', 'agent_runs', ['result_run_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_agent_runs_output_message_id_session', 'agent_runs', 'chat_messages', ['output_message_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_agent_runs_retry_of_run_id_session', 'agent_runs', 'agent_runs', ['retry_of_run_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_agent_runs_trigger_command_id_session', 'agent_runs', 'agent_commands', ['trigger_command_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_agent_runs_trigger_message_id_session', 'agent_runs', 'chat_messages', ['trigger_message_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_agent_runs_work_item_id_session', 'agent_runs', 'order_intake_items', ['work_item_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_agent_tool_calls_run_id_session', 'agent_tool_calls', 'agent_runs', ['run_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_session_events_command_id_session', 'session_events', 'agent_commands', ['command_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_session_events_message_id_session', 'session_events', 'chat_messages', ['message_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_session_events_run_id_session', 'session_events', 'agent_runs', ['run_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_session_events_tool_call_id_session', 'session_events', 'agent_tool_calls', ['tool_call_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_session_events_work_item_id_session', 'session_events', 'order_intake_items', ['work_item_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_order_intake_items_source_attachment_id_session', 'order_intake_items', 'chat_attachments', ['source_attachment_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_order_intake_items_source_message_id_session', 'order_intake_items', 'chat_messages', ['source_message_id', 'session_id'], ['id', 'session_id'], deferrable=True, initially="DEFERRED")
    op.create_foreign_key('fk_chat_attachments_message_id_session', 'chat_attachments', 'chat_messages', ['message_id', 'session_id'], ['id', 'session_id'], initially='DEFERRED', deferrable=True)
    op.create_foreign_key(None, 'chat_attachments', 'chat_sessions', ['session_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key(None, 'chat_messages', 'chat_sessions', ['session_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_chat_messages_command_id_session', 'chat_messages', 'agent_commands', ['command_id', 'session_id'], ['id', 'session_id'], initially='DEFERRED', deferrable=True)
    op.create_foreign_key('fk_chat_messages_run_id_session', 'chat_messages', 'agent_runs', ['run_id', 'session_id'], ['id', 'session_id'], initially='DEFERRED', deferrable=True)
    op.create_foreign_key('fk_chat_messages_work_item_id_session', 'chat_messages', 'order_intake_items', ['work_item_id', 'session_id'], ['id', 'session_id'], initially='DEFERRED', deferrable=True)
    op.create_foreign_key('fk_chat_sessions_active_item', 'chat_sessions', 'order_intake_items', ['active_work_item_id', 'id'], ['id', 'session_id'], initially='DEFERRED', deferrable=True)
    # Expand only: old execution remains on LEGACY until the explicit D6 cutover.
    # No image I/O in a schema transaction; legacy file inspection is a separate step.
    op.execute("""UPDATE chat_attachments AS a
        SET session_id = m.session_id, client_upload_id = 'legacy:' || a.id
        FROM chat_messages AS m WHERE m.id = a.message_id""")


def downgrade() -> None:
    raise RuntimeError(
        "This expansion preserves durable inputs. Roll back the application with v2 disabled; "
        "restore a verified database/files backup for schema rollback."
    )
