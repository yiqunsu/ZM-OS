"""Retire legacy conversations and schedule durable attachment deletion.

Revision ID: d10f0a120004
Revises: d10f0a120003
"""
from alembic import op

revision = "d10f0a120004"
down_revision = "d10f0a120003"
branch_labels = None
depends_on = None


def upgrade():
    # Keep file keys until the worker has successfully unlinked every image.
    # No formal order or production task is deleted by this migration.
    op.execute("""
        INSERT INTO agent_file_gc_jobs
            (id, session_id, attachment_id, storage_key, status, attempts)
        SELECT md5('retire-legacy:' || a.id), s.id, a.id, a.storage_key, 'PENDING', 0
        FROM chat_attachments a
        JOIN chat_messages m ON m.id = a.message_id
        JOIN chat_sessions s ON s.id = COALESCE(a.session_id, m.session_id)
        WHERE s.agent_type = 'LEGACY'
        ON CONFLICT (storage_key) DO NOTHING
    """)
    op.execute("""
        UPDATE chat_sessions SET status = 'DELETING',
            deletion_requested_at = CURRENT_TIMESTAMP,
            active_work_item_id = NULL, active_plan_id = NULL
        WHERE agent_type = 'LEGACY'
    """)
    # Remove conversational content now; retries need only the private file keys.
    op.execute("""
        UPDATE agent_audit_logs SET session_id = NULL
        WHERE session_id IN (SELECT id FROM chat_sessions WHERE agent_type = 'LEGACY')
    """)
    op.execute("DELETE FROM chat_sessions WHERE agent_type = 'LEGACY'")
    op.execute(
        "UPDATE agent_audit_logs SET prompt = NULL, user_email = NULL, tool_calls = NULL WHERE kind IS NULL"
    )
    # These tables belong solely to the retired request-bound LangGraph runtime.
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints", "checkpoint_migrations"):
        op.execute(f'DROP TABLE IF EXISTS "{table}"')


def downgrade():
    raise RuntimeError("Legacy conversation deletion is irreversible; restore the pre-migration backup.")
