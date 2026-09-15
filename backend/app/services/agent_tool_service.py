"""Tool receipts and effects share a transaction; identity never comes from model args."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.limits import MAX_TOOL_CALLS
from app.agent.worker import RunContext, lock_run
from app.models import AgentToolCall
from app.models.base import generate_id
from app.services.agent_event_service import append_event, canonical_hash
from app.services.agent_session_service import fail

ToolOperation = Callable[[AsyncSession], Awaitable[dict]]


async def perform_tool(
    sessions: async_sessionmaker[AsyncSession],
    context: RunContext,
    *,
    call_key: str,
    tool_name: str,
    args: dict,
    allowed_tools: frozenset[str],
    operation: ToolOperation,
) -> dict:
    if tool_name not in allowed_tools or not call_key or len(call_key) > 128:
        fail("TOOL_NOT_ALLOWED", "此助手不能使用该工具")
    digest = canonical_hash(args)
    async with sessions() as db:
        session, run = await lock_run(db, context)
        existing = await db.scalar(
            select(AgentToolCall).where(AgentToolCall.run_id == run.id, AgentToolCall.call_key == call_key)
        )
        if existing:
            if existing.args_hash != digest or existing.tool_name != tool_name:
                fail("TOOL_CALL_CONFLICT", "工具调用标识冲突")
            if existing.status == "SUCCEEDED":
                return existing.result
            fail("TOOL_CALL_INCOMPLETE", "该工具调用已执行或未完成，请重试本轮")
        if run.tool_call_count >= MAX_TOOL_CALLS:
            fail("TOOL_LIMIT_REACHED", "本轮工具调用已达上限")
        call = AgentToolCall(
            id=generate_id(),
            session_id=session.id,
            run_id=run.id,
            call_key=call_key,
            tool_name=tool_name,
            args_hash=digest,
            args=args,
        )
        db.add(call)
        run.tool_call_count += 1
        append_event(
            db,
            session,
            "tool.started",
            {"tool_name": tool_name},
            actor_kind="AGENT",
            run_id=run.id,
            tool_call_id=call.id,
        )
        call_id = call.id
        await db.commit()
    try:
        async with sessions() as db:
            session, run = await lock_run(db, context)
            call = await db.scalar(select(AgentToolCall).where(AgentToolCall.id == call_id).with_for_update())
            # operation is a registered, trusted short database use case: no model/network I/O or commit.
            result = jsonable_encoder(await operation(db))
            now = await db.scalar(select(func.clock_timestamp()))
            if now >= run.deadline_at or now >= run.lease_expires_at:
                from app.agent.worker import LeaseLost

                raise LeaseLost()
            call.status, call.result, call.finished_at = "SUCCEEDED", result, datetime.now(UTC)
            append_event(
                db,
                session,
                "tool.succeeded",
                {"tool_name": tool_name},
                actor_kind="AGENT",
                run_id=run.id,
                tool_call_id=call.id,
            )
            await db.commit()
            return result
    except Exception:
        # If the lease was lost, the watchdog alone can finalize this receipt.
        from app.agent.worker import LeaseLost

        try:
            async with sessions() as db:
                session, run = await lock_run(db, context)
                call = await db.get(AgentToolCall, call_id)
                call.status, call.error_code, call.finished_at = "FAILED", "TOOL_FAILED", datetime.now(UTC)
                append_event(
                    db,
                    session,
                    "tool.failed",
                    {"tool_name": tool_name, "error_code": "TOOL_FAILED"},
                    actor_kind="AGENT",
                    run_id=run.id,
                    tool_call_id=call.id,
                )
                await db.commit()
        except LeaseLost:
            pass
        raise
