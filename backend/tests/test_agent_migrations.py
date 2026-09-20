"""Exercise the real Alembic chain on disposable PostgreSQL databases."""

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from tests.conftest import ADMIN_DSN

BACKEND = Path(__file__).resolve().parents[1]


async def alembic(db_name: str, *args: str) -> None:
    assert db_name.startswith("filmos_migration_test_")
    env = {
        **os.environ,
        "DATABASE_URL": f"postgresql+asyncpg://filmos:filmos@localhost:5432/{db_name}",
        "ENVIRONMENT": "development",
        "AUTH_PROVIDER": "local",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        *args,
        cwd=BACKEND,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 60)
    assert process.returncode == 0, (stdout + stderr).decode()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_empty_and_legacy_upgrade_no_drift(legacy):
    db_name = f"filmos_migration_test_{uuid4().hex[:12]}"
    admin = await asyncpg.connect(**ADMIN_DSN)
    connection = None
    try:
        await admin.execute(f'CREATE DATABASE "{db_name}"')
        if legacy:
            await alembic(db_name, "upgrade", "c9d8e7f60123")
            connection = await asyncpg.connect(**{**ADMIN_DSN, "database": db_name})
            await connection.execute("INSERT INTO chat_sessions(id,title) VALUES('old-session','历史会话')")
            await connection.execute(
                "INSERT INTO chat_messages(id,session_id,role,content,is_pending) "
                "VALUES('old-message','old-session','user','原始文字',false)"
            )
            await connection.execute(
                "INSERT INTO chat_attachments(id,message_id,mime_type,byte_size,storage_key) "
                "VALUES('old-image','old-message','image/png',100,'old-image.png')"
            )
            await connection.close()
            connection = None
        await alembic(db_name, "upgrade", "d10f0a120003")
        connection = await asyncpg.connect(**{**ADMIN_DSN, "database": db_name})
        await connection.execute(
            "INSERT INTO users(id,email,password_hash,role) "
            "VALUES('new-owner','migration@test.local','test','OWNER')"
        )
        await connection.execute(
            "INSERT INTO chat_sessions(id,title,user_id,agent_type) "
            "VALUES('new-session','新版保留','new-owner','ORDER_INTAKE')"
        )
        await connection.execute(
            "INSERT INTO chat_messages(id,session_id,role,content,is_pending) "
            "VALUES('new-message','new-session','user','新版订单',false)"
        )
        await connection.execute(
            "INSERT INTO chat_attachments(id,message_id,session_id,mime_type,byte_size,storage_key) "
            "VALUES('new-image','new-message','new-session','image/png',1,'new.png')"
        )
        await connection.execute(
            "INSERT INTO order_intake_items(id,session_id,source_message_id,"
            "source_attachment_id,queue_position,draft) "
            "VALUES('new-item','new-session','new-message','new-image',1,'{\"extra_notes\":\"保留草稿\"}')"
        )
        for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs", "checkpoint_migrations"):
            await connection.execute(f'CREATE TABLE "{table}" (id text)')
        await connection.close()
        connection = None
        await alembic(db_name, "upgrade", "head")
        await alembic(db_name, "check")
        connection = await asyncpg.connect(**{**ADMIN_DSN, "database": db_name})
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == "d10f0a120007"
        constraints = set(
            await connection.fetch(
                "SELECT conname FROM pg_constraint WHERE connamespace='public'::regnamespace"
            )
        )
        names = {row["conname"] for row in constraints}
        # Autogenerate does not compare CHECK constraints; verify them explicitly.
        assert {
            "ck_chat_sessions_owner",
            "ck_chat_messages_v2",
            "ck_agent_runs_lease",
            "ck_agent_audit_logs_kind",
            "fk_chat_messages_run_id_session",
            "fk_chat_attachments_message_id_session",
        } <= names
        indexes = await connection.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE indexname='uq_agent_runs_open_session'"
        )
        assert "UNIQUE" in indexes and "QUEUED" in indexes and "RUNNING" in indexes
        assert await connection.fetchval("SELECT id FROM chat_sessions") == "new-session"
        assert await connection.fetchval("SELECT to_regclass('public.checkpoints')") is None
        assert await connection.fetchval("SELECT source_order_index FROM order_intake_items") == 1
        assert await connection.fetchval("SELECT draft->>'extra_notes' FROM order_intake_items") == "保留草稿"
        if legacy:
            assert await connection.fetchval("SELECT count(*) FROM chat_sessions") == 1
            assert await connection.fetchval("SELECT count(*) FROM chat_messages") == 1
            assert await connection.fetchval("SELECT count(*) FROM chat_attachments") == 1
            job = await connection.fetchrow("SELECT session_id,storage_key,status FROM agent_file_gc_jobs")
            assert dict(job) == {"session_id": None, "storage_key": "old-image.png", "status": "PENDING"}

    finally:
        if connection and not connection.is_closed():
            await connection.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        await admin.close()
