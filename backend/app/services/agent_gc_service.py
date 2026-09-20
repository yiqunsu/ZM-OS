"""Retryable private-file cleanup; only remove a Session after every file is gone."""

import asyncio
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentAuditLog, AgentFileGcJob, ChatAttachment, ChatSession
from app.services.chat_attachment_service import _delete_file


async def collect_once(db: AsyncSession) -> bool:
    now = await db.scalar(select(func.clock_timestamp()))
    job = (
        await db.execute(
            select(AgentFileGcJob)
            .where(AgentFileGcJob.status.in_(["PENDING", "FAILED"]), AgentFileGcJob.next_attempt_at <= now)
            .order_by(AgentFileGcJob.next_attempt_at, AgentFileGcJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        await db.rollback()
        return False
    # Local unlink is idempotent and bounded; keeping the row locked avoids overlapping GC attempts.
    job.attempts += 1
    job.updated_at = now
    try:
        await asyncio.to_thread(_delete_file, job.storage_key)
    except (OSError, ValueError):
        job.status, job.last_error_code = "FAILED", "FILE_DELETE_FAILED"
        job.next_attempt_at = now + timedelta(seconds=min(3600, 2 ** min(job.attempts, 12)))
    else:
        job.status, job.completed_at, job.last_error_code = "SUCCEEDED", now, None
    await db.commit()
    return True


async def sweep_staged(db: AsyncSession) -> int:
    now = await db.scalar(select(func.clock_timestamp()))
    # Session-first locks match upload/accept/delete. No binding can race expiry.
    candidates = select(ChatAttachment.session_id).where(
        ChatAttachment.status == "STAGED", ChatAttachment.expires_at <= now
    )
    sessions = (
        (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.status != "DELETING", ChatSession.id.in_(candidates))
                .order_by(ChatSession.id)
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    count = 0
    for session in sessions:
        expired = (
            (
                await db.execute(
                    select(ChatAttachment)
                    .where(
                        ChatAttachment.session_id == session.id,
                        ChatAttachment.status == "STAGED",
                        ChatAttachment.expires_at <= now,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for attachment in expired:
            db.add(
                AgentFileGcJob(
                    session_id=session.id, attachment_id=attachment.id, storage_key=attachment.storage_key
                )
            )
            await db.delete(attachment)
            count += 1
    await db.commit()
    return count


async def finish_deletions(db: AsyncSession) -> int:
    sessions = (
        (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.status == "DELETING")
                .order_by(ChatSession.id)
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    count = 0
    for session in sessions:
        pending = await db.scalar(
            select(func.count())
            .select_from(AgentFileGcJob)
            .where(AgentFileGcJob.session_id == session.id, AgentFileGcJob.status != "SUCCEEDED")
        )
        if pending:
            continue
        session.active_work_item_id = session.active_plan_id = None
        await db.flush()
        await db.execute(
            update(AgentAuditLog).where(AgentAuditLog.session_id == session.id).values(session_id=None)
        )
        await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
        count += 1
    await db.commit()
    return count


async def sweep_orphans(db: AsyncSession) -> int:
    """Recover a crash after an atomic disk write but before metadata commit."""
    import re
    import time

    from sqlalchemy.dialects.postgresql import insert

    from app.models.base import generate_id
    from app.services.chat_attachment_service import _storage_root

    def old_keys():
        root = _storage_root()
        if not root.is_dir():
            return []
        keys = []
        for path in root.iterdir():
            if re.fullmatch(
                r"[a-f0-9]{32}\.(png|jpg)|\.[a-f0-9]{32}\.(png|jpg)\.[a-f0-9]{32}\.tmp", path.name
            ):
                try:
                    if path.lstat().st_mtime < time.time() - 86400:
                        keys.append(path.name)
                except FileNotFoundError:
                    continue
        return keys

    keys = await asyncio.to_thread(old_keys)
    if not keys:
        await db.rollback()
        return 0
    known = set(
        (
            await db.scalars(select(ChatAttachment.storage_key).where(ChatAttachment.storage_key.in_(keys)))
        ).all()
    )
    count = 0
    for key in keys:
        if key in known:
            continue
        result = await db.execute(
            insert(AgentFileGcJob)
            .values(id=generate_id(), storage_key=key)
            .on_conflict_do_nothing(index_elements=["storage_key"])
        )
        count += result.rowcount
    await db.commit()
    return count
