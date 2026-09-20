"""PostgreSQL worker: a browser connection never owns execution lifetime.

Executors are registered explicitly by (graph_key, graph_version).
Unsupported versions fail closed rather than using v1.
"""

import asyncio
import contextlib
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.errors import AdmissionResponseError
from app.core.database import async_session
from app.core.logging import logger
from app.models import AgentAuditLog, AgentRun, AgentToolCall, ChatMessage, ChatSession
from app.models.agent import RunOutcome
from app.models.base import generate_id
from app.services.agent_event_service import append_event

LEASE_SECONDS = 30
HEARTBEAT_SECONDS = 10
HEALTH_FILE = Path("/tmp/filmos-agent-worker-heartbeat")


class LeaseLost(Exception):
    """The worker no longer has permission to publish any effect."""


@dataclass(frozen=True)
class RunContext:
    run_id: str
    session_id: str
    user_id: str
    work_item_id: str | None
    lease_token: str
    graph_key: str
    graph_version: str
    input_event_seq: int


@dataclass(frozen=True)
class RunResult:
    text: str
    outcome: RunOutcome = RunOutcome.ANSWERED


Executor = Callable[[RunContext], Awaitable[RunResult]]


async def lock_run(db: AsyncSession, context: RunContext) -> tuple[ChatSession, AgentRun]:
    session = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.id == context.session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    run = (
        await db.execute(
            select(AgentRun)
            .where(AgentRun.id == context.run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    now = await db.scalar(select(func.clock_timestamp()))
    if (
        session is None
        or session.status != "ACTIVE"
        or run is None
        or run.status != "RUNNING"
        or run.session_id != session.id
        or session.user_id != context.user_id
        or run.lease_token != context.lease_token
        or run.lease_expires_at <= now
        or run.deadline_at <= now
        or run.work_item_id != context.work_item_id
        or (
            run.work_item_id is not None
            and session.active_work_item_id != run.work_item_id
            and not run.config_snapshot.get("intake_workbench")
        )
    ):
        raise LeaseLost()
    return session, run


async def claim(db: AsyncSession, worker_id: str) -> RunContext | None:
    candidate = select(AgentRun.session_id).where(AgentRun.status == "QUEUED")
    session = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.status == "ACTIVE", ChatSession.id.in_(candidate))
            .order_by(ChatSession.updated_at, ChatSession.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if session is None:
        await db.rollback()
        return None
    run = (
        await db.execute(
            select(AgentRun)
            .where(AgentRun.session_id == session.id, AgentRun.status == "QUEUED")
            .with_for_update()
        )
    ).scalar_one()
    now = await db.scalar(select(func.clock_timestamp()))
    if now >= run.queued_at + timedelta(seconds=run.config_snapshot["queue_timeout_seconds"]):
        await _fail_locked(db, session, run, "QUEUE_TIMEOUT", "等待执行超时，请重试")
        await db.commit()
        return None
    run.status, run.worker_id, run.lease_token = "RUNNING", worker_id, generate_id()
    run.started_at = run.heartbeat_at = now
    run.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    run.deadline_at = now + timedelta(seconds=run.config_snapshot["run_timeout_seconds"])
    append_event(db, session, "run.started", {}, run_id=run.id)
    context = RunContext(
        run.id,
        session.id,
        session.user_id,
        run.work_item_id,
        run.lease_token,
        run.graph_key,
        run.graph_version,
        run.input_event_seq,
    )
    await db.commit()
    return context


async def heartbeat(db: AsyncSession, context: RunContext) -> None:
    _, run = await lock_run(db, context)
    now = await db.scalar(select(func.clock_timestamp()))
    run.heartbeat_at = now
    run.lease_expires_at = min(now + timedelta(seconds=LEASE_SECONDS), run.deadline_at)
    await db.commit()


def audit_terminal(db: AsyncSession, session: ChatSession, run: AgentRun) -> None:
    usage_complete = (run.context_snapshot or {}).get("usage_complete", True)
    db.add(
        AgentAuditLog(
            kind="RUN_FINISHED",
            user_id=session.user_id,
            session_id=session.id,
            run_id=run.id,
            object_type="agent_run",
            object_id=run.id,
            result={
                "schema_version": 1,
                "status": run.status,
                "outcome": run.outcome,
                "error_code": run.error_code,
                "usage_complete": usage_complete,
            },
            prompt_tokens=run.prompt_tokens if usage_complete else None,
            completion_tokens=run.completion_tokens if usage_complete else None,
            total_tokens=run.total_tokens if usage_complete else None,
        )
    )


async def _fail_locked(
    db: AsyncSession, session: ChatSession, run: AgentRun, code: str, message: str
) -> None:
    run.status, run.error_code, run.error_message = "FAILED", code, message
    run.finished_at = await db.scalar(select(func.clock_timestamp()))
    run.lease_token, run.lease_expires_at = None, None
    calls = (
        (
            await db.execute(
                select(AgentToolCall)
                .where(AgentToolCall.run_id == run.id, AgentToolCall.status == "STARTED")
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for call in calls:
        call.status, call.error_code, call.finished_at = "ABANDONED", code, run.finished_at
        append_event(db, session, "tool.abandoned", {"error_code": code}, run_id=run.id, tool_call_id=call.id)
    audit_terminal(db, session, run)
    from app.services.order_intake_workflow import continue_recognition

    await continue_recognition(db, session, run)
    session.state_revision += 1
    append_event(db, session, "run.failed", {"error_code": code, "message": message}, run_id=run.id)
    append_event(db, session, "session.state_changed", {"state_revision": session.state_revision})


async def fail_run(db: AsyncSession, context: RunContext, code: str, message: str) -> None:
    session, run = await lock_run(db, context)
    await _fail_locked(db, session, run, code, message)
    await db.commit()


async def finalize(db: AsyncSession, context: RunContext, result: RunResult) -> str:
    if not result.text.strip() or len(result.text) > 20000:
        raise ValueError("invalid final response")
    outcome = RunOutcome(result.outcome)
    session, run = await lock_run(db, context)
    message = ChatMessage(
        id=generate_id(),
        session_id=session.id,
        role="assistant",
        origin="AGENT",
        content=result.text,
        run_id=run.id,
        work_item_id=run.work_item_id,
        event_seq=session.last_event_seq + 1,
    )
    db.add(message)
    append_event(
        db,
        session,
        "message.completed",
        {"role": "assistant", "text": result.text, "attachment_ids": []},
        actor_kind="AGENT",
        run_id=run.id,
        message_id=message.id,
        work_item_id=run.work_item_id,
    )
    run.status, run.outcome, run.output_message_id = "SUCCEEDED", outcome.value, message.id
    run.finished_at = await db.scalar(select(func.clock_timestamp()))
    run.lease_token, run.lease_expires_at = None, None
    audit_terminal(db, session, run)
    from app.services.order_intake_workflow import continue_recognition

    await continue_recognition(db, session, run)
    session.state_revision += 1
    append_event(
        db, session, "run.succeeded", {"outcome": outcome.value, "message_id": message.id}, run_id=run.id
    )
    append_event(db, session, "session.state_changed", {"state_revision": session.state_revision})
    await db.commit()
    return message.id


async def append_delta(db: AsyncSession, context: RunContext, text: str, chunk_index: int) -> None:
    if not text or len(text) > 4096 or chunk_index < 0:
        raise ValueError("invalid delta")
    session, _ = await lock_run(db, context)
    append_event(
        db,
        session,
        "assistant.delta",
        {"text": text, "chunk_index": chunk_index},
        actor_kind="AGENT",
        run_id=context.run_id,
    )
    await db.commit()


async def expire_runs(db: AsyncSession, limit: int = 100) -> int:
    # Session first, just like claim/finalize. Never lock Run then Session.
    now = await db.scalar(select(func.clock_timestamp()))
    candidates = select(AgentRun.session_id).where(
        (
            (AgentRun.status == "RUNNING")
            & ((AgentRun.lease_expires_at <= now) | (AgentRun.deadline_at <= now))
        )
        | ((AgentRun.status == "QUEUED") & (AgentRun.queued_at <= now - timedelta(seconds=120)))
    )
    sessions = (
        (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.id.in_(candidates))
                .order_by(ChatSession.id)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    count = 0
    for session in sessions:
        run = (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.session_id == session.id, AgentRun.status.in_(["QUEUED", "RUNNING"]))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            continue
        if run.status == "QUEUED":
            code, message = "QUEUE_TIMEOUT", "等待执行超时，请重试"
        elif run.deadline_at <= now:
            code, message = "RUN_TIMEOUT", "本轮处理超时，输入和草稿已保留"
        elif run.lease_expires_at <= now:
            code, message = "WORKER_LOST", "执行中断，输入和草稿已保留"
        else:
            continue
        await _fail_locked(db, session, run, code, message)
        count += 1
    await db.commit()
    return count


class Worker:
    def __init__(
        self,
        executors: dict[tuple[str, str], Executor],
        *,
        sessions: async_sessionmaker[AsyncSession] = async_session,
        concurrency: int = 2,
    ):
        if not 1 <= concurrency <= 16:
            raise ValueError("worker concurrency must be between 1 and 16")
        self.executors, self.sessions, self.concurrency = executors, sessions, concurrency
        self.worker_id, self.stopping = generate_id(), asyncio.Event()

    async def _heartbeat(self, context: RunContext) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            async with self.sessions() as db:
                await heartbeat(db, context)

    async def execute(self, context: RunContext) -> None:
        executor = self.executors.get((context.graph_key, context.graph_version))
        if executor is None:
            async with self.sessions() as db:
                await fail_run(db, context, "GRAPH_VERSION_UNAVAILABLE", "该版本的助手暂未可用，请稍后重试")
            return
        work = asyncio.create_task(executor(context))
        pulse = asyncio.create_task(self._heartbeat(context))
        try:
            async with self.sessions() as db:
                _, run = await lock_run(db, context)
                now = await db.scalar(select(func.clock_timestamp()))
                remaining = max(0, (run.deadline_at - now).total_seconds())
            done, _ = await asyncio.wait(
                {work, pulse}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if pulse in done:
                pulse.result()
            if work not in done:
                raise TimeoutError()
            async with self.sessions() as db:
                await finalize(db, context, work.result())
        except LeaseLost:
            pass
        except asyncio.CancelledError:
            with contextlib.suppress(LeaseLost):
                async with self.sessions() as db:
                    await fail_run(db, context, "WORKER_STOPPED", "执行已停止，输入和草稿已保留")
            raise
        except AdmissionResponseError:
            logger.warning("agent_run_failed", run_id=context.run_id, error_code=AdmissionResponseError.code)
            with contextlib.suppress(LeaseLost):
                async with self.sessions() as db:
                    await fail_run(
                        db, context, AdmissionResponseError.code, AdmissionResponseError.public_message
                    )
        except Exception as err:
            logger.warning("agent_run_failed", run_id=context.run_id, error_type=type(err).__name__)
            # Model/provider exception text must never reach the API, event log or audit.
            with contextlib.suppress(LeaseLost):
                async with self.sessions() as db:
                    await fail_run(db, context, "EXECUTION_FAILED", "本轮处理失败，输入和草稿已保留")
        finally:
            work.cancel()
            pulse.cancel()
            await asyncio.gather(work, pulse, return_exceptions=True)

    async def _slot(self) -> None:
        while not self.stopping.is_set():
            async with self.sessions() as db:
                context = await claim(db, self.worker_id)
            if context:
                await self.execute(context)
            else:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.stopping.wait(), timeout=0.5)

    async def _watchdog(self) -> None:
        while not self.stopping.is_set():
            async with self.sessions() as db:
                await expire_runs(db)
            from app.services import agent_gc_service as gc

            async with self.sessions() as db:
                await gc.sweep_staged(db)
            async with self.sessions() as db:
                await gc.sweep_orphans(db)
            async with self.sessions() as db:
                await gc.collect_once(db)
            async with self.sessions() as db:
                await gc.finish_deletions(db)
            HEALTH_FILE.touch()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stopping.wait(), timeout=5)

    async def serve(self) -> None:
        async with asyncio.TaskGroup() as group:
            for _ in range(self.concurrency):
                group.create_task(self._slot())
            group.create_task(self._watchdog())


async def main() -> None:
    from app.core.config import settings
    from app.core.logging import configure_logging, logger
    from app.core.phoenix import setup_phoenix

    configure_logging()
    if not settings.AGENT_V2_ENABLED:
        raise SystemExit("AGENT_V2_ENABLED is disabled; specialized Agent cutover is not enabled")
    from app.agent.registry import executors

    setup_phoenix(private=True)
    HEALTH_FILE.unlink(missing_ok=True)
    worker = Worker(executors())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stopping.set)
    logger.info("agent_worker_started", worker_id=worker.worker_id, concurrency=worker.concurrency)
    try:
        await worker.serve()
    except Exception as error:
        # SQL/provider exceptions may contain body text; never print the raw traceback.
        logger.error("agent_worker_stopped", error_type=type(error).__name__)
        raise SystemExit(1) from None
    logger.info("agent_worker_stopped", reason="shutdown")


if __name__ == "__main__":
    if sys.argv[1:] == ["--healthcheck"]:
        try:
            healthy = 0 <= time.time() - HEALTH_FILE.stat().st_mtime < 30
        except OSError:
            healthy = False
        raise SystemExit(0 if healthy else 1)
    asyncio.run(main())
